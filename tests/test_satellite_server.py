"""Actual authenticated satellite API with mocked public/AI providers."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from argus.collab_server import Config, SERVICE, create_app
from test_satellite import fixture


class SatelliteServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace, self.scene, self.image = fixture(self.root/'satellite')
        self.environment = patch.dict('os.environ', {'ARGUS_SATELLITE_ROOT': str(self.workspace.root),
                                                    'ARGUS_SATELLITE_AIS_DIR': str(self.root/'ais')})
        self.environment.start()
        self.app = create_app(Config(self.root/'accounts.sqlite3', origin='http://127.0.0.1', allow_loopback_http=True))
        store = self.app[SERVICE].store
        hashed = store.hasher.hash('Synthetic-test-password-42')
        self.tokens = {}
        for name, groups in [('analyst', ['intelligence']), ('other', ['intelligence']), ('viewer', ['user'])]:
            user = store.create_user(name, hashed, groups)
            self.tokens[name] = store.issue_token(user['id'], 3600)[0]
        admin = store.create_user('testadmin', hashed, ['intelligence'], admin=True)
        self.tokens['admin'] = store.issue_token(admin['id'], 3600)[0]
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.http = ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.server.close()
        self.environment.stop()
        self.temp.cleanup()

    async def api(self, method, path, who=None, data=None):
        headers = {'Authorization': 'Bearer '+self.tokens[who]} if who else {}
        async with self.http.request(method, self.server.make_url('/v1/satellite/'+path), headers=headers, json=data) as response:
            raw = await response.text()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw

    async def finish(self, identifier, who='analyst'):
        for _ in range(200):
            status, result = await self.api('GET', 'jobs/'+identifier, who)
            self.assertEqual(status, 200)
            if result['status'] != 'running':
                return result
            await asyncio.sleep(.01)
        self.fail('Synthetic satellite job did not finish')

    async def test_login_and_evidence_permission_protect_crops_and_jobs(self):
        self.assertEqual((await self.api('GET', 'scenes'))[0], 401)
        self.assertEqual((await self.api('GET', 'scenes', 'viewer'))[0], 403)
        self.assertEqual((await self.api('POST', 'jobs', 'viewer', {'action': 'analyse'}))[0], 403)
        status, value = await self.api('GET', 'scenes', 'analyst')
        self.assertEqual(status, 200)
        self.assertEqual(len(value['scenes']), 1)
        status, value = await self.api('GET', 'scenes/'+self.scene['id']+'/image', 'analyst')
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(value['image_base64']), self.image)
        self.assertNotIn('key', json.dumps(value))

    async def test_history_jobs_are_unpaid_and_owned_by_requesting_account(self):
        status, value = await self.api('POST', 'jobs', 'analyst', {'action': 'history', 'identifier': self.scene['id']})
        self.assertEqual(status, 202)
        self.assertEqual((await self.api('GET', 'jobs/'+value['job_id'], 'other'))[0], 404)
        result = await self.finish(value['job_id'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['result']['ais']['coverage']['status'], 'unavailable')
        self.assertFalse((self.workspace.root/'ai/budget.json').exists())

    async def test_remote_clients_cannot_change_keys_budget_or_fetch_arbitrary_urls(self):
        self.assertEqual((await self.api('POST', 'jobs', 'analyst', {'action': 'configure', 'key': 'synthetic'}))[0], 400)
        status, value = await self.api('POST', 'jobs', 'analyst',
                                      {'action': 'prepare', 'product_id': 'https://127.0.0.1/secret', 'bbox': [-6.17,53.30,-6.07,53.36]})
        self.assertEqual(status, 202)
        result = await self.finish(value['job_id'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('identifier', result['error'])

    async def test_only_admin_can_enable_paid_cycles_and_evidence_users_can_read_contacts(self):
        self.assertEqual((await self.api('GET', 'contacts'))[0], 401)
        self.assertEqual((await self.api('GET', 'contacts', 'viewer'))[0], 403)
        self.assertEqual((await self.api('GET', 'contacts', 'analyst'))[0], 200)
        for who in ('viewer', 'analyst'):
            self.assertEqual((await self.api('POST', 'scan', who, {'action': 'start'}))[0], 403)
        with patch('argus.satellite_scan.CoastalScan.start', return_value={'enabled': True}) as start:
            code, value = await self.api('POST', 'scan', 'admin', {'action': 'start'})
            self.assertEqual(code, 200)
            self.assertTrue(value['enabled'])
            self.assertEqual(start.call_count, 1)
            self.assertEqual((await self.api('POST', 'scan', 'admin', {'action': 'start', 'budget': 999}))[0], 400)
            self.assertEqual(start.call_count, 1)
