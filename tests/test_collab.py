"""Security regressions and actual two-client HTTPS/E2EE communication."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import ssl
import tempfile
import time
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


def type_codes(*ciphers):
    """Each analyst types the code every peer reads aloud from the peer's own screen."""
    by_id = {cipher.own_id: cipher for cipher in ciphers}
    for cipher in ciphers:
        for peer_id in cipher.safety_codes:
            if not cipher.verify_peer(peer_id, by_id[peer_id].safety_codes[cipher.own_id]):
                raise AssertionError(f"{cipher.own_id} could not verify {peer_id}")


class CryptoTests(unittest.TestCase):
    def test_shorter_safety_encoding_retains_128_bits(self):
        from argus.collab_crypto import safety_display
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        material = bytes(range(16))
        encoded = safety_display(material).replace(' ', '')
        self.assertEqual(len(encoded), 26)
        decoded = 0
        for char in encoded:
            decoded = (decoded << 5) | alphabet.index(char)
        self.assertEqual(decoded.to_bytes(16, 'big'), material)

    def test_three_people_pairwise_keys_and_recipient_tampering(self):
        clients = {identifier: RoomCipher() for identifier in ('a', 'b', 'c')}
        members = [{'user_id': key, 'username': key, 'public_key': cipher.public_key} for key, cipher in clients.items()]
        for key, cipher in clients.items():
            cipher.establish('group', key, members)
        type_codes(*clients.values())
        for cipher in clients.values():
            cipher.confirm()
        for first, second in (('a', 'b'), ('a', 'c'), ('b', 'c')):
            self.assertEqual(clients[first].safety_codes[second], clients[second].safety_codes[first])
        packet = clients['a'].encrypt('chat', {'text': 'Everyone gets a separate encrypted copy'})
        self.assertNotEqual(packet['ciphertexts']['b'], packet['ciphertexts']['c'])
        damaged = deepcopy(packet)
        damaged['ciphertexts']['b'] = damaged['ciphertexts']['c']
        with self.assertRaises(InvalidTag):
            clients['b'].decrypt(damaged)
        for recipient in ('b', 'c'):
            self.assertEqual(clients[recipient].decrypt(packet)['text'], 'Everyone gets a separate encrypted copy')
        reply = clients['b'].encrypt('ping', {'lat': 53, 'lon': -6})
        for recipient in ('a', 'c'):
            self.assertEqual(clients[recipient].decrypt(reply)['lat'], 53)

    def test_verification_direction_nonce_replay_and_tamper(self):
        a, b, members = ciphers()
        self.assertEqual(a.safety_code, b.safety_code)
        with self.assertRaises(ValueError):
            a.encrypt("chat", {"text": "private synthetic information"})
        type_codes(a, b)
        a.confirm()
        b.confirm()
        first = a.encrypt("chat", {"text": "private synthetic information"})
        self.assertNotIn('private', json.dumps(first['ciphertexts']))
        corrupt = dict(first, kind="evidence")
        with self.assertRaises(InvalidTag):
            b.decrypt(corrupt)
        self.assertEqual(b.decrypt(first), {"text": "private synthetic information"})
        with self.assertRaises(ValueError):
            b.decrypt(first)
        second = a.encrypt("ping", {"lat": 53.2, "lon": -6.3})
        self.assertNotEqual(first['ciphertexts'], second['ciphertexts'])
        self.assertEqual(b.decrypt(second)["lat"], 53.2)
        back = b.encrypt("chat", {"text": "reply"})
        self.assertEqual(a.decrypt(back)["text"], "reply")
        replacement = deepcopy(members)
        replacement[1]["public_key"] = RoomCipher().public_key
        with self.assertRaises(ValueError):
            a.establish("room", "a", replacement)
        self.assertFalse(a.verified)

    def test_confirm_requires_the_typed_code_of_every_peer(self):
        clients = {identifier: RoomCipher() for identifier in ('a', 'b', 'c')}
        members = [{'user_id': key, 'username': key, 'public_key': cipher.public_key} for key, cipher in clients.items()]
        for key, cipher in clients.items():
            cipher.establish('group', key, members)
        a, b, c = clients['a'], clients['b'], clients['c']
        with self.assertRaises(ValueError):
            a.confirm()
        self.assertFalse(a.verify_peer('b', c.safety_codes['a']))
        self.assertFalse(a.verify_peer('b', b.safety_codes['a'].replace(' ', '')[:-1]))
        self.assertFalse(a.verify_peer('b', None))
        self.assertEqual(a.verified_peers, set())
        # Spacing, dashes and lower case are typing differences, not different codes.
        self.assertTrue(a.verify_peer('b', b.safety_codes['a'].lower().replace(' ', '-')))
        with self.assertRaises(ValueError):
            a.confirm()
        with self.assertRaises(ValueError):
            a.encrypt('chat', {'text': 'c has not been compared'})
        self.assertTrue(a.verify_peer('c', c.safety_codes['a']))
        a.confirm()
        self.assertTrue(a.verified)

    def test_typed_code_detects_relay_substituted_keys(self):
        a, b, fake_b, fake_a = RoomCipher(), RoomCipher(), RoomCipher(), RoomCipher()
        # A malicious relay shows each analyst its own key in place of the other analyst's.
        a.establish('room', 'a', [{'user_id': 'a', 'username': 'alice', 'public_key': a.public_key},
                                  {'user_id': 'b', 'username': 'bob', 'public_key': fake_b.public_key}])
        b.establish('room', 'b', [{'user_id': 'a', 'username': 'alice', 'public_key': fake_a.public_key},
                                  {'user_id': 'b', 'username': 'bob', 'public_key': b.public_key}])
        self.assertFalse(a.verify_peer('b', b.safety_codes['a']))
        self.assertFalse(b.verify_peer('a', a.safety_codes['b']))
        for cipher in (a, b):
            with self.assertRaises(ValueError):
                cipher.confirm()

    def test_text_rejects_invisible_and_direction_changing_characters(self):
        for text in ('report.‮gnp.exe', 'pay​ment', '⁦hidden⁩', 'a\u0085b', 'a\x7fb', 'a\rb', 'lone \ud800'):
            with self.assertRaises(ValueError):
                validate_payload('chat', {'text': text})
        for text in ('Привет, команда', 'line one\n\tline two', 'analyst \U0001F469‍\U0001F4BB', 'می‌خواهم'):
            self.assertEqual(validate_payload('chat', {'text': text})['text'], text)
        # A modified client that skips its own check is still refused by the receiver.
        a, b, members = ciphers()
        type_codes(a, b)
        a.confirm()
        b.confirm()
        with patch('argus.collab_crypto.validate_payload', lambda kind, payload: payload):
            packet = a.encrypt('chat', {'text': 'report.‮gnp.exe'})
        with self.assertRaises(ValueError):
            b.decrypt(packet)

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
        with patch.dict('os.environ', {'ARGUS_SOC_ORIGIN': 'https://example.com', 'ARGUS_SOC_LOCAL_DEMO': '1'}):
            with self.assertRaises(ValueError):
                Config.from_env()
        with patch.dict('os.environ', {'ARGUS_SOC_ORIGIN': 'https://localhost:8443', 'ARGUS_SOC_LOCAL_DEMO': '1'}):
            self.assertTrue(Config.from_env().local_demo)


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
        status, joined = await self.api('POST', f"/v1/rooms/{created['room_id']}/lock", self.alice, {})
        self.assertEqual(status, 200)
        a.establish(created["room_id"], self.alice["id"], joined["members"])
        b.establish(created["room_id"], self.bob["id"], joined["members"])
        return a, b, created, joined

    async def confirmed_room(self):
        a, b, created, joined = await self.room()
        type_codes(a, b)
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

    async def login_from(self, address, username, password):
        return (await self.api("POST", "/v1/login", data={"username": username, "password": password},
                               headers={"X-Forwarded-For": address}))[0]

    async def test_one_address_cannot_block_sign_in_for_other_people(self):
        # As in Docker: every request arrives from Caddy, which reports the client's address last.
        self.relay.config.proxy_network = "127.0.0.1/32"
        attacker, colleague = "203.0.113.9, 198.51.100.7", "192.0.2.44"
        for index in range(20):
            self.assertEqual(await self.login_from(attacker, f"guess{index:02d}", "wrong"), 401)
        self.assertEqual(await self.login_from(attacker, "bob", SECRET), 429)
        self.assertEqual(await self.login_from(colleague, "bob", SECRET), 200)
        # The client-written entry before Caddy's does not give the attacker a fresh address.
        self.assertEqual(await self.login_from("198.51.100.7", "bob", SECRET), 429)

    async def test_wrong_passwords_from_elsewhere_do_not_lock_out_the_account(self):
        self.relay.config.proxy_network = "127.0.0.1/32"
        for _ in range(8):
            self.assertEqual(await self.login_from("198.51.100.7", "bob", "wrong"), 401)
        self.assertEqual(await self.login_from("198.51.100.7", "bob", SECRET), 429)
        self.assertEqual(await self.login_from("192.0.2.44", "bob", SECRET), 200)

    async def test_forwarded_address_is_ignored_unless_it_comes_from_the_proxy(self):
        for index in range(20):
            self.assertEqual(await self.login_from(f"198.51.100.{index}", f"guess{index:02d}", "wrong"), 401)
        self.assertEqual(await self.login_from("192.0.2.44", "bob", SECRET), 429)

    async def test_requests_without_sign_in_cannot_use_up_signed_in_limits(self):
        statuses = [(await self.api("GET", "/v1/me"))[0] for _ in range(121)]
        self.assertEqual((statuses.count(401), statuses[-1]), (120, 429))
        self.assertEqual((await self.api("GET", "/v1/me", self.bob))[0], 200)
        # A flood from many addresses can exhaust the overall budget for requests without a sign-in...
        self.relay.rates[("anonymous",)] = (6000, time.monotonic() + 60)
        self.relay.config.proxy_network = "127.0.0.1/32"
        self.assertEqual((await self.api("GET", "/v1/me", headers={"X-Forwarded-For": "192.0.2.44"}))[0], 429)
        # ...but people already signed in keep working.
        self.assertEqual((await self.api("GET", "/v1/me", self.bob))[0], 200)

    async def test_requested_account_waits_for_an_administrator(self):
        url = str(self.server.make_url("")).rstrip("/")
        client = SOCClient(url, allow_loopback_http=True)
        self.assertTrue((await asyncio.to_thread(client.signup, "newcomer", SECRET))["pending"])
        stored = self.relay.store.credential("newcomer")
        self.assertNotEqual(stored["password_hash"], SECRET)
        with self.assertRaises(ClientError) as waiting:
            await asyncio.to_thread(client.login, "newcomer", SECRET)
        self.assertEqual(waiting.exception.status, 403)
        self.assertIn("administrator", str(waiting.exception))
        self.assertIsNone(client.token)
        for username, password in (("newcomer", SECRET), ("bob", SECRET), ("x", SECRET), ("shortpass", "too-short")):
            self.assertEqual((await self.api("POST", "/v1/signup", data={"username": username, "password": password}))[0], 400)
        # Approval is the existing administrator update: add the account to a group.
        self.assertEqual((await self.api("PUT", f"/v1/admin/users/{stored['id']}", self.alice,
                                         {"groups": ["user"], "disabled": False}))[0], 200)
        user = await asyncio.to_thread(client.login, "newcomer", SECRET)
        self.assertIn("chat", user["permissions"])
        self.assertFalse(user["admin"])

    async def test_account_requests_are_limited_per_address_and_while_waiting(self):
        statuses = [(await self.api("POST", "/v1/signup", data={"username": f"visitor{index}", "password": SECRET}))[0]
                    for index in range(4)]
        self.assertEqual(statuses, [200, 200, 200, 429])
        hashed = self.relay.store.hasher.hash(SECRET)
        for index in range(17):
            self.relay.store.create_user(f"waiting{index:02d}", hashed, [])
        self.relay.config.proxy_network = "127.0.0.1/32"
        status, refused = await self.api("POST", "/v1/signup", data={"username": "another", "password": SECRET},
                                         headers={"X-Forwarded-For": "192.0.2.44"})
        self.assertEqual(status, 503)
        self.assertIn("waiting for approval", refused["error"])
        self.assertIsNone(self.relay.store.credential("another"))

    async def test_remembered_token_resumes_until_revoked(self):
        url = str(self.server.make_url("")).rstrip("/")
        token = self.tokens[self.bob["id"]]
        client = SOCClient(url, allow_loopback_http=True)
        self.assertEqual((await asyncio.to_thread(client.resume, token))["username"], "bob")
        self.relay.store.logout(token)
        expired = SOCClient(url, allow_loopback_http=True)
        with self.assertRaises(ClientError) as refused:
            await asyncio.to_thread(expired.resume, token)
        self.assertEqual(refused.exception.status, 401)
        self.assertIsNone(expired.token)

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

    async def test_disjoint_groups_can_share_team_room_with_common_tools(self):
        with self.relay.store.db:
            self.relay.store.db.execute('DELETE FROM memberships WHERE user_id=? AND group_name=?', (self.alice['id'], 'user'))
        a, b = RoomCipher(), RoomCipher()
        status, created = await self.api('POST', '/v1/rooms', self.alice, {'group': None, 'public_key': a.public_key})
        self.assertEqual(status, 200)
        self.assertEqual(len(created['code']), 8)
        self.assertIsNone(created['group'])
        status, joined = await self.api('POST', '/v1/join', self.bob, {'code': created['code'], 'public_key': b.public_key})
        self.assertEqual(status, 200)
        self.assertNotIn('evidence.share', joined['permissions'])
        self.assertIn('chat', joined['permissions'])
        path = '/v1/rooms/' + created['room_id']
        locked = (await self.api('POST', path + '/lock', self.alice, {}))[1]
        for user, cipher in ((self.alice, a), (self.bob, b)):
            cipher.establish(created['room_id'], user['id'], locked['members'])
        type_codes(a, b)
        for user, cipher in ((self.alice, a), (self.bob, b)):
            cipher.confirm()
            await self.api('POST', path + '/confirm', user, {})
        self.assertEqual((await self.api('POST', path + '/messages', self.alice, a.encrypt('chat', {'text': 'mixed groups'})))[0], 200)
        self.assertEqual((await self.api('POST', path + '/messages', self.alice, a.encrypt('evidence', {'text': 'restricted'})))[0], 403)
        state = (await self.api('GET', path, self.bob))[1]
        self.assertEqual(b.decrypt(state['messages'][0]['packet'])['text'], 'mixed groups')
        # Changing either participant's group must terminate mixed-group rooms.
        self.assertEqual((await self.api('PUT', '/v1/admin/groups/intelligence', self.alice, {'permissions': ['map.view', 'chat']}))[0], 200)
        self.assertNotIn(created['room_id'], self.relay.rooms)

    async def test_multiuser_lobby_capacity_host_lock_and_all_confirmations(self):
        self.relay.config.max_members = 3
        ciphers_by_user = {u['id']: RoomCipher() for u in (self.alice, self.bob, self.eve)}
        status, created = await self.api('POST', '/v1/rooms', self.alice, {'group': 'user', 'public_key': ciphers_by_user[self.alice['id']].public_key})
        self.assertEqual(status, 200)
        for user in (self.bob, self.eve):
            status, lobby = await self.api('POST', '/v1/join', user, {'code': created['code'], 'public_key': ciphers_by_user[user['id']].public_key})
            self.assertEqual(status, 200)
        path = f"/v1/rooms/{created['room_id']}"
        self.assertEqual((await self.api('POST', path + '/lock', self.bob, {}))[0], 403)
        self.assertEqual((await self.api('POST', path + '/confirm', self.bob, {}))[0], 409)
        extra = self.relay.store.create_user('extra', self.relay.store.hasher.hash(SECRET), ['user'])
        self.tokens[extra['id']] = self.relay.store.issue_token(extra['id'], 3600)[0]
        self.assertEqual((await self.api('POST', '/v1/join', extra, {'code': created['code'], 'public_key': RoomCipher().public_key}))[0], 404)
        status, frozen = await self.api('POST', path + '/lock', self.alice, {})
        self.assertEqual(status, 200)
        self.assertTrue(frozen['locked'])
        for user in (self.alice, self.bob, self.eve):
            ciphers_by_user[user['id']].establish(created['room_id'], user['id'], frozen['members'])
        type_codes(*ciphers_by_user.values())
        for cipher in ciphers_by_user.values():
            cipher.confirm()
        for user in (self.alice, self.bob):
            await self.api('POST', path + '/confirm', user, {})
        cipher = ciphers_by_user[self.alice['id']]
        packet = cipher.encrypt('chat', {'text': 'three analysts'})
        self.assertEqual((await self.api('POST', path + '/messages', self.alice, packet))[0], 409)
        await self.api('POST', path + '/confirm', self.eve, {})
        damaged = deepcopy(packet)
        damaged['ciphertexts'].pop(self.eve['id'])
        self.assertEqual((await self.api('POST', path + '/messages', self.alice, damaged))[0], 400)
        self.assertEqual((await self.api('POST', path + '/messages', self.alice, packet))[0], 200)
        for user in (self.bob, self.eve):
            state = (await self.api('GET', path, user))[1]
            self.assertEqual(ciphers_by_user[user['id']].decrypt(state['messages'][0]['packet'])['text'], 'three analysts')

    async def test_confirm_permissions_replay_and_no_plaintext_relay(self):
        a, b, created, joined = await self.room()
        type_codes(a, b)
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
        self.assertEqual((await self.api("POST", path, self.alice, {"extra": "x" * 140000}))[0], 413)

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
        a, b, c = [SOCClient(url, ca_file=cert_path) for _ in range(3)]
        await asyncio.to_thread(a.login, "alice", SECRET)
        await asyncio.to_thread(b.login, "bob", SECRET)
        await asyncio.to_thread(c.login, 'eve', SECRET)
        room = await asyncio.to_thread(a.create, "user")
        await asyncio.to_thread(b.join, room["code"])
        await asyncio.to_thread(c.join, room['code'])
        await asyncio.to_thread(a.lock)
        await asyncio.to_thread(b.poll)
        await asyncio.to_thread(c.poll)
        await asyncio.to_thread(a.poll)
        for first, second in ((a, b), (a, c), (b, c)):
            self.assertEqual(first.cipher.safety_codes[second.user['id']], second.cipher.safety_codes[first.user['id']])
        with self.assertRaises(ClientError):
            await asyncio.to_thread(a.confirm)
        self.assertNotIn(a.user['id'], self.relay.rooms[room['room_id']].confirmed)
        type_codes(a.cipher, b.cipher, c.cipher)
        await asyncio.to_thread(a.confirm)
        await asyncio.to_thread(b.confirm)
        await asyncio.to_thread(c.confirm)
        await asyncio.to_thread(a.poll)
        await asyncio.to_thread(b.poll)
        await asyncio.to_thread(c.poll)
        await asyncio.to_thread(a.send, "chat", {"text": "Encrypted synthetic SOC handoff"})
        self.assertEqual((await asyncio.to_thread(b.poll))[0]["payload"]["text"], "Encrypted synthetic SOC handoff")
        self.assertEqual((await asyncio.to_thread(c.poll))[0]['payload']['text'], 'Encrypted synthetic SOC handoff')
        await asyncio.to_thread(b.send, "ping", {"lat": 53.35, "lon": -6.25})
        self.assertEqual((await asyncio.to_thread(a.poll))[0]["payload"], {"lat": 53.35, "lon": -6.25})
        self.assertEqual((await asyncio.to_thread(c.poll))[0]['payload'], {'lat': 53.35, 'lon': -6.25})
        bad = SOCClient(url)
        with self.assertRaises(ClientError):
            await asyncio.to_thread(bad.login, "bob", SECRET)
        await asyncio.to_thread(b.logout)
        with self.assertRaises(ClientError):
            await asyncio.to_thread(a.poll)


if __name__ == "__main__":
    unittest.main()
