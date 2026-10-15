"""Forwarding boundaries, existing account reuse and TLS-proxied E2EE delivery."""
import asyncio
from datetime import datetime, timedelta, timezone
import io
import ipaddress
import json
from pathlib import Path
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from argus.collab_client import ClientError, NoRedirect, SOCClient, forwarded_origin, server_url
from argus.collab_server import Config, SERVICE, create_app
from argus.soc_launcher import StartupError
from scripts import start_soc_forwarded as hosting

URL = 'https://team-8765.eu.devtunnels.ms'
SECRET = 'synthetic-forwarded-test-password'


class ForwardedClientTests(unittest.TestCase):
    def test_tunnel_headers_and_no_credentials_sent_to_redirect_target(self):
        client = SOCClient(URL)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ready":true}'
        client.opener = Mock()
        client.opener.open.return_value = response
        self.assertTrue(client.request('GET', '/healthz')['ready'])
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('X-tunnel-skip-antiphishing-page'), 'true')
        self.assertEqual(request.get_header('Accept'), 'application/json')
        with self.assertRaisesRegex(ClientError, 'Port Visibility'):
            NoRedirect().redirect_request(Request(URL + '/v1/login', data=b'synthetic'), None, 302,
                'Found', {}, 'https://github.com/login')
        self.assertEqual(client.opener.open.call_count, 1)
        for value in ('https://host.app.github.dev', URL):
            self.assertTrue(forwarded_origin(value))
        for value in ('https://devtunnels.ms.evil.invalid', 'https://notdevtunnels.ms', 'http://x.devtunnels.ms'):
            self.assertFalse(forwarded_origin(value))

    def test_tunnel_html_and_private_errors_have_actionable_diagnostics(self):
        client = SOCClient(URL)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'<html>provider sign in</html>'
        client.opener = Mock()
        client.opener.open.return_value = response
        with self.assertRaisesRegex(ClientError, 'Port Visibility'):
            client.request('GET', '/healthz')
        client.opener.open.side_effect = HTTPError(URL, 403, 'Forbidden', {}, io.BytesIO(b'<html>denied</html>'))
        with self.assertRaisesRegex(ClientError, 'Port Visibility'):
            client.request('GET', '/healthz')
        # An Argus password rejection remains an Argus rejection.
        client.opener.open.side_effect = HTTPError(URL, 401, 'Unauthorized', {}, io.BytesIO(b'{"error":"Invalid username or password"}'))
        with self.assertRaisesRegex(ClientError, 'Invalid username or password'):
            client.login('alice', SECRET)

    def test_unsafe_forwarding_addresses_are_rejected(self):
        for value in ('http://x.devtunnels.ms', 'https://@x.devtunnels.ms',
                      'https://x.devtunnels.ms:70000', 'https://x.devtunnels.ms\n',
                      'https://x${SECRET}.devtunnels.ms', 'https://x.devtunnels.ms/path',
                      'https://x.devtunnels.ms?token=secret', 'https://x\\evil.devtunnels.ms'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server_url(value)


class ForwardedHostingTests(unittest.TestCase):
    def test_preparation_listener_serves_only_fixed_text_and_stops(self):
        with hosting.forwarding_listener(0) as server:
            url = f'http://127.0.0.1:{server.server_address[1]}'
            with urlopen(url, timeout=2) as response:
                self.assertIn(b'Argus SOC setup', response.read())
            with self.assertRaises(HTTPError) as denied:
                urlopen(url + '/.git/config', timeout=2)
            self.assertEqual(denied.exception.code, 404)
        with self.assertRaises(OSError):
            urlopen(url, timeout=2)

    def test_missing_accounts_or_another_replica_does_not_start_or_seed(self):
        for missing in (True, False):
            commands = []
            def execute(command, environment):
                commands.append(command)
                if command[1:3] == ['volume', 'inspect']:
                    return SimpleNamespace(returncode=int(missing), stdout='')
                owners = {'Labels': 'com.docker.compose.project=another-stack,com.docker.compose.service=relay'}
                return SimpleNamespace(returncode=0, stdout=json.dumps(owners) if command[1] == 'ps' else '')
            with self.assertRaises(StartupError):
                hosting.start(URL, execute=execute, docker='docker')
            self.assertFalse(any('up' in command or 'seed' in command for command in commands))

    def test_existing_stack_keeps_database_and_does_not_read_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []
            def execute(command, environment):
                commands.append(command)
                labels = {'Labels': 'com.docker.compose.project=argus-soc-local,com.docker.compose.service=relay'}
                self.assertEqual(environment['SOC_FORWARDED_URL'], URL)
                return SimpleNamespace(returncode=0, stdout=json.dumps(labels) if command[1] == 'ps' else '')
            with patch.object(hosting, 'ROOT', root):
                self.assertEqual(hosting.start(URL, execute=execute, docker='docker', progress=lambda _: None), URL)
            saved = (root / 'data/soc-forwarded/host.env').read_text()
            self.assertIn(hosting.DEFAULT_VOLUME, saved)
            self.assertNotIn('PASSWORD', saved)
            self.assertTrue(any(command[-4:] == ['up', '-d', 'relay', 'https'] for command in commands))
            self.assertTrue(any('mode=ro' in command[-1] for command in commands))
            self.assertFalse(any('seed' in command or '--seed-demo' in command or 'down' in command for command in commands))

    def test_empty_account_database_does_not_replace_the_running_stack(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            def execute(command, environment):
                commands.append(command)
                return SimpleNamespace(returncode=int('-c' in command), stdout='')
            with patch.object(hosting, 'ROOT', Path(directory)), self.assertRaises(StartupError):
                hosting.start(URL, execute=execute, docker='docker', progress=lambda _: None)
            self.assertFalse(any('up' in command for command in commands))


class ForwardedIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_native_clients_through_tls_proxy_keep_accounts_and_exchange_chat_and_ping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            app = create_app(Config(path / 'accounts.sqlite3', origin=URL, proxy_network='127.0.0.1/32'))
            relay = app[SERVICE]
            hashed = relay.store.hasher.hash(SECRET)
            # These are existing accounts, created before forwarding starts.
            relay.store.create_user('alice', hashed, ['intelligence'])
            relay.store.create_user('bob', hashed, ['user'])
            backend = TestServer(app)
            await backend.start_server()
            transport = ClientSession(timeout=ClientTimeout(total=5))
            async def forward(request):
                headers = {k: v for k, v in request.headers.items() if k.lower() in ('authorization', 'content-type', 'accept', 'origin')}
                headers.update({'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '127.0.0.1'})
                async with transport.request(request.method, backend.make_url(request.path_qs),
                        data=await request.read(), headers=headers, allow_redirects=False) as response:
                    return web.Response(body=await response.read(), status=response.status,
                                        headers={'Content-Type': response.headers['Content-Type']})
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'forwarded-proxy-test')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256()))
            ca, private = path / 'ca.pem', path / 'key.pem'
            ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(ca, private)
            proxy = web.Application()
            proxy.router.add_route('*', '/{path:.*}', forward)
            frontend = TestServer(proxy, scheme='https')
            await frontend.start_server(ssl=tls)
            clients = [SOCClient(str(frontend.make_url('')).rstrip('/'), ca_file=str(ca)) for _ in range(2)]
            try:
                # Direct unencrypted access and spoofed browser origins stay denied.
                async with transport.get(backend.make_url('/healthz')) as response:
                    self.assertEqual(response.status, 426)
                async with transport.get(frontend.make_url('/healthz'), ssl=ssl.create_default_context(cafile=ca), headers={'Origin': 'https://evil.invalid'}) as response:
                    self.assertEqual(response.status, 403)
                a, b = clients
                await asyncio.to_thread(a.login, 'alice', SECRET)
                await asyncio.to_thread(b.login, 'bob', SECRET)
                self.assertEqual(relay.store.credential('alice')['password_hash'], hashed)
                room = await asyncio.to_thread(a.create)
                await asyncio.to_thread(b.join, room['code'])
                await asyncio.to_thread(a.lock)
                await asyncio.to_thread(b.poll)
                with self.assertRaises(ClientError):
                    await asyncio.to_thread(a.send, 'chat', {'text': 'not yet verified'})
                for client, peer in ((a, b), (b, a)):
                    self.assertTrue(client.cipher.verify_peer(peer.user['id'], peer.cipher.safety_codes[client.user['id']]))
                    await asyncio.to_thread(client.confirm)
                await asyncio.to_thread(a.poll)
                await asyncio.to_thread(b.poll)
                await asyncio.to_thread(a.send, 'chat', {'text': 'Forwarded private handoff'})
                self.assertEqual((await asyncio.to_thread(b.poll))[0]['payload']['text'], 'Forwarded private handoff')
                await asyncio.to_thread(b.send, 'ping', {'lat': 53.35, 'lon': -6.25})
                self.assertEqual((await asyncio.to_thread(a.poll))[0]['payload'], {'lat': 53.35, 'lon': -6.25})
                await asyncio.to_thread(b.send, 'chat', {'text': 'Return handoff received'})
                self.assertEqual((await asyncio.to_thread(a.poll))[0]['payload']['text'], 'Return handoff received')
                await asyncio.to_thread(a.send, 'ping', {'lat': 51.9, 'lon': -8.3})
                self.assertEqual((await asyncio.to_thread(b.poll))[0]['payload'], {'lat': 51.9, 'lon': -8.3})
                self.assertNotIn('Forwarded private handoff', json.dumps(relay.snapshot(relay.rooms[room['room_id']])))
                untrusted = SOCClient(str(frontend.make_url('')).rstrip('/'))
                with self.assertRaises(ClientError):
                    await asyncio.to_thread(untrusted.login, 'alice', SECRET)
            finally:
                for client in clients:
                    await asyncio.to_thread(client.logout)
                await frontend.close()
                await transport.close()
                await backend.close()
