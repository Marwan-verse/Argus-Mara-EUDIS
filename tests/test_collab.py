"""Security regressions and actual two-client HTTPS/E2EE communication."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from argus.collab_client import SOCClient, ClientError, server_url
from argus.collab_crypto import RoomCipher, validate_payload
from argus.collab_server import Config, SERVICE, create_app

SECRET = "synthetic-test-password-42"


def ciphers():
    a, b = RoomCipher(), RoomCipher()
    members = [{"user_id": "a", "username": "alice", "public_key": a.public_key},
               {"user_id": "b", "username": "bob", "public_key": b.public_key}]
    a.establish("room", "a", members)
    b.establish("room", "b", list(reversed(members)))
    return a, b, members


class CryptoTests(unittest.TestCase):
    def test_verification_direction_nonce_replay_and_tamper(self):
        a, b, members = ciphers()
        self.assertEqual(a.safety_code, b.safety_code)
        with self.assertRaises(ValueError):
            a.encrypt("chat", {"text": "private synthetic information"})
        a.confirm()
        b.confirm()
        first = a.encrypt("chat", {"text": "private synthetic information"})
        self.assertNotIn("private", first["ciphertext"])
        corrupt = dict(first, kind="evidence")
        with self.assertRaises(InvalidTag):
            b.decrypt(corrupt)
        self.assertEqual(b.decrypt(first), {"text": "private synthetic information"})
        with self.assertRaises(ValueError):
            b.decrypt(first)
        second = a.encrypt("ping", {"lat": 53.2, "lon": -6.3})
        self.assertNotEqual(first["ciphertext"], second["ciphertext"])
        self.assertEqual(b.decrypt(second)["lat"], 53.2)
        back = b.encrypt("chat", {"text": "reply"})
        self.assertEqual(a.decrypt(back)["text"], "reply")
        replacement = deepcopy(members)
        replacement[1]["public_key"] = RoomCipher().public_key
        with self.assertRaises(ValueError):
            a.establish("room", "a", replacement)
        self.assertFalse(a.verified)

    def test_payload_and_url_validation(self):
        for payload in ({"lat": float("nan"), "lon": 0}, {"lat": True, "lon": 0}, {"lat": 91, "lon": 0}, {"lat": 0, "lon": 181}):
            with self.assertRaises(ValueError):
                validate_payload("ping", payload)
        for url in ("http://example.com", "https://a:b@example.com", "https://example.com/path", "https://example.com?token=secret", "http://127.0.0.1"):
            with self.assertRaises(ValueError):
                server_url(url)
        self.assertEqual(server_url("http://127.0.0.1", True), "http://127.0.0.1")
        with patch.dict("os.environ", {"ARGUS_SOC_ORIGIN": "http://example.com", "ARGUS_SOC_DEV_HTTP": "1"}):
            with self.assertRaises(ValueError):
                Config.from_env()


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.app = create_app(Config(self.path / "accounts.sqlite3", origin="http://127.0.0.1", allow_loopback_http=True))
        self.relay = self.app[SERVICE]
        hashed = self.relay.store.hasher.hash(SECRET)
        self.alice = self.relay.store.create_user("alice", hashed, ["user", "intelligence"], admin=True)
        self.bob = self.relay.store.create_user("bob", hashed, ["user"])
        self.eve = self.relay.store.create_user("eve", hashed, ["user"])
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.http = ClientSession()
        self.tokens = {}
        for user in (self.alice, self.bob, self.eve):
            self.tokens[user["id"]] = self.relay.store.issue_token(user["id"], 3600)[0]

    async def asyncTearDown(self):
        await self.http.close()
        await self.server.close()
        self.temp.cleanup()

    async def api(self, method, path, user=None, data=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if user:
            headers["Authorization"] = "Bearer " + self.tokens[user["id"]]
        async with self.http.request(method, self.server.make_url(path), json=data, headers=headers, **kwargs) as response:
            raw = await response.text()
            try:
                result = json.loads(raw)
            except ValueError:
                result = raw
            return response.status, result

    async def room(self, group="user"):
        a, b = RoomCipher(), RoomCipher()
        status, created = await self.api("POST", "/v1/rooms", self.alice, {"group": group, "public_key": a.public_key})
        self.assertEqual(status, 200)
        status, joined = await self.api("POST", "/v1/join", self.bob, {"code": created["code"], "public_key": b.public_key})
        self.assertEqual(status, 200)
        a.establish(created["room_id"], self.alice["id"], joined["members"])
        b.establish(created["room_id"], self.bob["id"], joined["members"])
        return a, b, created, joined

    async def confirmed_room(self):
        a, b, created, joined = await self.room()
        for user, cipher in ((self.alice, a), (self.bob, b)):
            status, _ = await self.api("POST", f"/v1/rooms/{created['room_id']}/confirm", user, {})
            self.assertEqual(status, 200)
            cipher.confirm()
        return a, b, created, joined

    async def test_authentication_origin_admin_and_persistence(self):
        self.assertEqual((await self.api("GET", "/v1/me"))[0], 401)
        self.assertEqual((await self.api("GET", "/v1/admin", self.bob))[0], 403)
        self.assertEqual((await self.api("GET", "/v1/me", self.bob, headers={"Origin": "https://evil.example"}))[0], 403)
        self.assertEqual((await self.api("POST", "/v1/login", data={"username": "bob", "password": "wrong"}))[0], 401)
        status, login = await self.api("POST", "/v1/login", data={"username": "bob", "password": SECRET})
        self.assertEqual(status, 200)
        self.assertNotIn(SECRET.encode(), (self.path / "accounts.sqlite3").read_bytes())
        self.assertNotIn(login["token"].encode(), (self.path / "accounts.sqlite3").read_bytes())
        self.assertEqual((await self.api("GET", "/.git/config", self.bob))[0], 404)
        self.assertEqual((await self.api("GET", "/recorder/.apikey", self.bob))[0], 404)
        for _ in range(6):
            await self.api("POST", "/v1/login", data={"username": "bob", "password": "wrong"})
        self.assertEqual((await self.api("POST", "/v1/login", data={"username": "bob", "password": SECRET}))[0], 429)

    async def test_http_cannot_spoof_https_outside_proxy_network(self):
        self.relay.config.allow_loopback_http = False
        self.assertEqual((await self.api('GET', '/v1/me', self.bob, headers={'X-Forwarded-Proto': 'https'}))[0], 426)
        self.relay.config.proxy_network = '172.30.65.0/24'
        self.assertEqual((await self.api('GET', '/v1/me', self.bob, headers={'X-Forwarded-Proto': 'https'}))[0], 426)
        self.relay.config.proxy_network = '127.0.0.1/32'
        self.assertEqual((await self.api('GET', '/v1/me', self.bob))[0], 426)
        self.assertEqual((await self.api('GET', '/v1/me', self.bob, headers={'X-Forwarded-Proto': 'https'}))[0], 200)

    async def test_room_code_not_authorization_single_use_and_group(self):
        a, b, created, joined = await self.room()
        room_id = created["room_id"]
        self.assertEqual((await self.api("GET", f"/v1/rooms/{room_id}", self.eve))[0], 404)
        self.assertEqual((await self.api("POST", "/v1/join", self.eve, {"code": created["code"], "public_key": RoomCipher().public_key}))[0], 404)
        status, intel = await self.api("POST", "/v1/rooms", self.alice, {"group": "intelligence", "public_key": RoomCipher().public_key})
        self.assertEqual(status, 200)
        self.assertEqual((await self.api("POST", "/v1/join", self.bob, {"code": intel["code"], "public_key": RoomCipher().public_key}))[0], 404)
        self.assertEqual((await self.api("GET", f"/v1/rooms/{room_id}", self.bob))[0], 404)
        self.relay.rooms[intel["room_id"]].invitation_expires = 0
        self.assertEqual((await self.api("POST", "/v1/join", self.bob, {"code": intel["code"], "public_key": RoomCipher().public_key}))[0], 404)

    async def test_confirm_permissions_replay_and_no_plaintext_relay(self):
        a, b, created, joined = await self.room()
        a.confirm()
        packet = a.encrypt("chat", {"text": "SYNTHETIC_PRIVATE_MESSAGE"})
        path = f"/v1/rooms/{created['room_id']}/messages"
        self.assertEqual((await self.api("POST", path, self.alice, packet))[0], 409)
        for user in (self.alice, self.bob):
            await self.api("POST", f"/v1/rooms/{created['room_id']}/confirm", user, {})
        self.assertEqual((await self.api("POST", path, self.alice, packet))[0], 200)
        self.assertEqual((await self.api("POST", path, self.alice, packet))[0], 400)
        b.confirm()
        restricted = b.encrypt("evidence", {"text": "synthetic evidence"})
        self.assertEqual((await self.api("POST", path, self.bob, restricted))[0], 403)
        # Even intelligence users cannot use that tool in a user-scoped room.
        self.assertEqual((await self.api("POST", path, self.alice, a.encrypt("evidence", {"text": "evidence"})))[0], 403)
        self.assertEqual((await self.api("POST", path, self.bob, dict(packet, counter=2)))[0], 400)
        state = (await self.api("GET", f"/v1/rooms/{created['room_id']}", self.bob))[1]
        self.assertEqual(b.decrypt(state["messages"][0]["packet"])["text"], "SYNTHETIC_PRIVATE_MESSAGE")
        self.assertNotIn("SYNTHETIC_PRIVATE_MESSAGE", json.dumps(self.relay.snapshot(self.relay.rooms[created["room_id"]])))

    async def test_admin_membership_revocation_and_group_changes(self):
        a, b, created, joined = await self.confirmed_room()
        status, _ = await self.api("PUT", f"/v1/admin/users/{self.bob['id']}", self.alice,
                                  {"groups": ["intelligence"], "disabled": False})
        self.assertEqual(status, 200)
        self.assertEqual((await self.api("GET", "/v1/me", self.bob))[0], 401)
        self.assertNotIn(created["room_id"], self.relay.rooms)
        status, _ = await self.api("PUT", "/v1/admin/groups/custom", self.alice, {"permissions": ["map.view", "chat"]})
        self.assertEqual(status, 200)
        status, _ = await self.api("PUT", "/v1/admin/groups/custom", self.alice, {"permissions": ["root.shell"]})
        self.assertEqual(status, 400)
        self.assertEqual((await self.api("DELETE", "/v1/admin/groups/custom", self.alice))[0], 200)
        self.assertEqual((await self.api("PUT", f"/v1/admin/users/{self.alice['id']}", self.alice, {"groups": []}))[0], 400)

    async def test_admin_account_creation_disable_and_password_policy(self):
        data = {'username': 'charlie', 'password': 'weak', 'groups': ['user']}
        self.assertEqual((await self.api('POST', '/v1/admin/users', self.alice, data))[0], 400)
        data['password'] = SECRET
        self.assertEqual((await self.api('POST', '/v1/admin/users', self.bob, data))[0], 403)
        status, created = await self.api('POST', '/v1/admin/users', self.alice, data)
        self.assertEqual(status, 200)
        self.assertEqual(created['groups'], ['user'])
        status, logged_in = await self.api('POST', '/v1/login', data={'username': 'charlie', 'password': SECRET})
        self.assertEqual(status, 200)
        self.assertEqual((await self.api('PUT', '/v1/admin/users/' + created['id'], self.alice,
                                       {'groups': [], 'disabled': True}))[0], 200)
        self.assertEqual((await self.api('POST', '/v1/login', data={'username': 'charlie', 'password': SECRET}))[0], 401)
        self.assertIsNone(self.relay.store.authenticate(logged_in['token']))

    async def test_room_bound_to_login_and_expired_receiver(self):
        a, b, created, joined = await self.confirmed_room()
        original = self.tokens[self.bob["id"]]
        self.tokens[self.bob["id"]] = self.relay.store.issue_token(self.bob["id"], 3600)[0]
        self.assertEqual((await self.api("GET", f"/v1/rooms/{created['room_id']}", self.bob))[0], 404)
        self.relay.store.logout(original)
        path = f"/v1/rooms/{created['room_id']}/messages"
        self.assertEqual((await self.api("POST", path, self.alice, a.encrypt("chat", {"text": "hello"})))[0], 404)

    async def test_message_retention_cursor_and_size(self):
        self.relay.config.history_size = 2
        a, b, created, joined = await self.confirmed_room()
        path = f"/v1/rooms/{created['room_id']}/messages"
        for index in range(3):
            self.assertEqual((await self.api("POST", path, self.alice, a.encrypt("chat", {"text": str(index)})))[0], 200)
        self.assertEqual((await self.api("GET", f"/v1/rooms/{created['room_id']}?after=0", self.bob))[0], 409)
        status, state = await self.api("GET", f"/v1/rooms/{created['room_id']}?after=1", self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(len(state["messages"]), 2)
        self.assertEqual((await self.api("POST", path, self.alice, {"extra": "x" * 20000}))[0], 413)

    async def test_actual_https_two_clients(self):
        await self.server.close()
        # Replace the closed store/server with a TLS instance on localhost.
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                .sign(key, hashes.SHA256()))
        cert_path, key_path = self.path / "cert.pem", self.path / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        self.app = create_app(Config(self.path / "accounts.sqlite3"))
        self.relay = self.app[SERVICE]
        self.server = TestServer(self.app, scheme="https")
        await self.server.start_server(ssl=context)
        url = str(self.server.make_url("")).rstrip("/")
        a, b = SOCClient(url, ca_file=cert_path), SOCClient(url, ca_file=cert_path)
        await asyncio.to_thread(a.login, "alice", SECRET)
        await asyncio.to_thread(b.login, "bob", SECRET)
        room = await asyncio.to_thread(a.create, "user")
        await asyncio.to_thread(b.join, room["code"])
        await asyncio.to_thread(a.poll)
        self.assertEqual(a.cipher.safety_code, b.cipher.safety_code)
        await asyncio.to_thread(a.confirm)
        await asyncio.to_thread(b.confirm)
        await asyncio.to_thread(a.poll)
        await asyncio.to_thread(b.poll)
        await asyncio.to_thread(a.send, "chat", {"text": "Encrypted synthetic SOC handoff"})
        self.assertEqual((await asyncio.to_thread(b.poll))[0]["payload"]["text"], "Encrypted synthetic SOC handoff")
        await asyncio.to_thread(b.send, "ping", {"lat": 53.35, "lon": -6.25})
        self.assertEqual((await asyncio.to_thread(a.poll))[0]["payload"], {"lat": 53.35, "lon": -6.25})
        bad = SOCClient(url)
        with self.assertRaises(ClientError):
            await asyncio.to_thread(bad.login, "bob", SECRET)
        await asyncio.to_thread(b.logout)
        with self.assertRaises(ClientError):
            await asyncio.to_thread(a.poll)


if __name__ == "__main__":
    unittest.main()
