"""Team Supabase link: key handling, database AIS in the Coast Watch join, scene upload."""
from importlib.util import find_spec
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from argus import supabase_ais
from test_satellite import AREA, WHEN, fixture

SECRET = 'sb_secret_' + 'x'*24
LEGACY = 'eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJl'
NO_KEY = {'ARGUS_SUPABASE_URL': 'https://example.supabase.co', 'ARGUS_SUPABASE_KEY': '', 'ARGUS_SUPABASE_KEY_FILE': '', 'ARGUS_SUPABASE_LINK': ''}


def database_rows():
    """What public.argus_ais_rows returns: two fixes around WHEN and as-of particulars."""
    common = {'mmsi': '123456789', 'msg_type': 'PositionReport', 'sog': 8, 'cog': 90, 'nav_status': 0,
              'time_utc': '', 'timestamp_source': 'received_time_assumption', 'stream_id': 'abc', 'label': 'real'}
    return {'rows': [
        {**common, 'lat': 53.33, 'lon': -6.1219, 'recv_utc': '2026-10-13T11:59:30.000Z'},
        {**common, 'lat': 53.33, 'lon': -6.1181, 'recv_utc': '2026-10-13T12:00:30.000Z'},
        {'mmsi': '123456789', 'msg_type': 'ShipStaticData', 'recv_utc': '2026-10-13T11:00:00.000Z',
         'stream_id': 'abc', 'label': 'real', 'present_fields': 'name', 'ship_name': 'DATABASE SHIP'},
        {'mmsi': '123456789', 'msg_type': 'ShipStaticData', 'recv_utc': '2026-10-13T11:00:00.000Z',
         'stream_id': 'abc', 'label': 'real', 'present_fields': 'length_m', 'length_m': 120}]}


class FakeDatabase:
    def __init__(self, answer=None, error=None):
        self.calls, self.answer, self.error = [], answer, error

    def __call__(self, url, payload, key):
        self.calls.append((url, payload, key))
        if self.error:
            raise ValueError(self.error)
        return self.answer


class KeyAndTransportTests(unittest.TestCase):
    def test_new_secret_keys_only_travel_in_the_apikey_header(self):
        self.assertNotIn('Authorization', supabase_ais.headers_for(SECRET))
        self.assertEqual(supabase_ais.headers_for(SECRET)['apikey'], SECRET)
        self.assertEqual(supabase_ais.headers_for(LEGACY)['Authorization'], 'Bearer ' + LEGACY)

    def test_off_until_a_key_exists_and_refuses_plain_http(self):
        with patch.dict(os.environ, NO_KEY), patch('argus.supabase_ais._keyring_password', return_value=''):
            self.assertFalse(supabase_ais.configured())
            with tempfile.TemporaryDirectory() as temp:
                self.assertFalse(supabase_ais.linked(temp))
            # D108: reads may use the publishable key, but writing still needs the secret one.
            with self.assertRaisesRegex(ValueError, 'not configured'):
                supabase_ais.rpc('argus_save_scene', {}, transport=FakeDatabase({}))
        self.assertFalse(supabase_ais.valid_key('anon-or-random-text'))
        self.assertTrue(supabase_ais.valid_key(SECRET) and supabase_ais.valid_key(LEGACY))
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            supabase_ais.http_rpc('http://example.supabase.co/rest/v1/rpc/argus_ais_status', {}, SECRET)

    def test_a_stored_key_alone_never_links_a_workspace(self):
        with patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}), tempfile.TemporaryDirectory() as temp:
            self.assertTrue(supabase_ais.configured())
            self.assertFalse(supabase_ais.linked(temp))
            supabase_ais.link(temp)
            self.assertTrue(supabase_ais.linked(temp))


class DatabaseJoinTests(unittest.TestCase):
    def test_database_source_conflicts_exclude_identity_and_remain_visible(self):
        packet = database_rows()
        packet['excluded_vessels'] = [{'mmsi': '123456789', 'reason': 'conflicting_positions_at_same_time'}]
        with patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}):
            result = supabase_ais.historical_ais_from_database(WHEN, AREA, transport=FakeDatabase(packet))
        self.assertEqual(result['vessels'], [])
        self.assertEqual(result['coverage']['excluded_vessels'], packet['excluded_vessels'])
        self.assertEqual(result['coverage']['status'], 'unavailable')
        self.assertEqual(result['coverage']['database_position_rows'], 2)
        for invalid in ([{'mmsi': 123456789, 'reason': 'ambiguous_stream_epochs'}],
                        [{'mmsi': '123456789', 'reason': 'unknown'}], 'unavailable'):
            packet['excluded_vessels'] = invalid
            with patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}):
                with self.assertRaisesRegex(ValueError, 'source-quality'):
                    supabase_ais.historical_ais_from_database(WHEN, AREA, transport=FakeDatabase(packet))

    def test_database_rows_feed_the_same_acquisition_time_join(self):
        fake = FakeDatabase(database_rows())
        with patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}):
            result = supabase_ais.historical_ais_from_database(WHEN, AREA, transport=fake)
        url, payload, key = fake.calls[0]
        self.assertTrue(url.endswith('/rest/v1/rpc/argus_ais_rows'))
        self.assertEqual((payload['p_t'], payload['p_w'], payload['p_n']), (WHEN, AREA[0], AREA[3]))
        self.assertEqual(key, SECRET)
        self.assertEqual(result['source'], 'supabase')
        self.assertEqual(result['coverage']['database_position_rows'], 2)
        vessel = result['vessels'][0]
        self.assertEqual(vessel['name'], 'DATABASE SHIP')
        self.assertEqual(vessel['broadcast_fields']['length_m']['value'], 120)
        self.assertAlmostEqual(vessel['position']['lon'], -6.12, places=3)

    def test_workspace_prefers_a_linked_database_and_falls_back_to_local_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}):
            workspace, scene, _ = fixture(Path(temp)/'satellite')
            scene['label'] = 'real'
            local = {'vessels': [], 'coverage': {'status': 'unavailable'}}
            database = {'vessels': [], 'source': 'supabase', 'coverage': {'database_position_rows': 3}}
            with patch('argus.satellite_workspace.historical_ais', return_value=dict(local)) as files, \
                    patch('argus.supabase_ais.historical_ais_from_database', return_value=database) as remote:
                self.assertEqual(workspace.ais_for_scene(scene)['coverage']['status'], 'unavailable')
                remote.assert_not_called()
                supabase_ais.link(workspace.root)
                self.assertEqual(workspace.ais_for_scene(scene)['source'], 'supabase')
                files.assert_called_once()
            with patch('argus.satellite_workspace.historical_ais', return_value={'vessels': [], 'coverage': {}}), \
                    patch('argus.supabase_ais.historical_ais_from_database', side_effect=ValueError('Cannot reach')):
                note = workspace.ais_for_scene(scene)['coverage']['database_note']
            self.assertIn('local archive used', note)


class SceneUploadTests(unittest.TestCase):
    def test_ai_contacts_are_saved_as_unreviewed_assumptions(self):
        scene = {'id': 'b'*24, 'sensor': 'Sentinel-2', 'acquired_utc': WHEN, 'bbox': AREA, 'label': 'real'}
        contacts = [{'id': 'c1', 'lat': 53.33, 'lon': -6.12, 'confidence': 'low', 'description': 'Bright hull'},
                    {'id': 'c2', 'lat': 53.34, 'lon': -6.10, 'confidence': .7},
                    {'id': 'bad', 'lat': float('nan'), 'lon': -6.1}]
        payload = supabase_ais.scene_payload(scene, contacts, [[-6.17, 53.30, -6.12, 53.33]])
        self.assertEqual(payload['label'], 'real')
        self.assertEqual([c['external_id'] for c in payload['contacts']], ['c1', 'c2'])
        self.assertTrue(all(c['label'] == 'assumption' and c['source'] == 'tensorx_ai' for c in payload['contacts']))
        self.assertEqual([c['confidence'] for c in payload['contacts']], [None, .7])
        self.assertFalse(payload['review_evidence']['image_input_verified'])
        reviewed = supabase_ais.scene_payload(scene, [{**contacts[0], 'overlap_ambiguous': True}],
                                             analysis={'image_input_verified': True})
        self.assertTrue(reviewed['review_evidence']['image_input_verified'])
        self.assertEqual(reviewed['review_evidence']['clear_footprint_radius_m'], 100)
        self.assertTrue(reviewed['contacts'][0]['overlap_ambiguous'])
        self.assertEqual(supabase_ais.scene_payload({**scene, 'label': 'simulated'}, [])['label'], 'simulated')
        json.dumps(payload, allow_nan=False)

    def test_publishing_failure_is_reported_not_raised(self):
        scene = {'id': 'b'*24, 'sensor': 'Sentinel-2', 'acquired_utc': WHEN, 'bbox': AREA, 'label': 'real'}
        with patch.dict(os.environ, {**NO_KEY, 'ARGUS_SUPABASE_KEY': SECRET}), tempfile.TemporaryDirectory() as temp:
            outcome = supabase_ais.publish_review(scene, [], temp, transport=FakeDatabase(error='Cannot reach'))
        self.assertFalse(outcome['saved'])
        self.assertIn('Cannot reach', outcome['error'])

    @unittest.skipUnless(find_spec('numpy'), 'numpy is in requirements-satellite.txt')
    def test_observed_areas_follow_the_clear_water_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, scene, _ = fixture(Path(temp)/'satellite')
            quality = Image.new('L', (64, 64), 9)  # cloud
            quality.paste(6, (0, 0, 32, 64))  # clear water in the western half
            buffer = BytesIO()
            quality.save(buffer, format='PNG')
            (workspace.scenes/(scene['id']+'.quality.png')).write_bytes(buffer.getvalue())
            scene['quality_sha256'] = hashlib.sha256(buffer.getvalue()).hexdigest()
            areas = supabase_ais.observed_rectangles(scene, workspace.scenes, tiles=8)
        middle = (AREA[0] + AREA[2]) / 2
        self.assertTrue(areas)
        self.assertTrue(all(east <= middle + 1e-6 and west >= AREA[0] - 1e-6 for west, _, east, _ in areas))
        self.assertTrue(all(AREA[1] - 1e-6 <= south < north <= AREA[3] + 1e-6 for _, south, _, north in areas))


class ProjectAddressTests(unittest.TestCase):
    """D106: a key is always used with the project it was linked to."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.env = patch.dict(os.environ, {'ARGUS_SATELLITE_ROOT': str(self.root)})
        self.env.start()
        os.environ.pop('ARGUS_SUPABASE_URL', None)

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def link_to(self, url):
        (self.root/supabase_ais.LINK_FILE).write_text(json.dumps({'url': url}), encoding='utf-8')

    def test_without_a_link_or_explicit_url_configuration_is_required(self):
        with self.assertRaisesRegex(ValueError, 'ARGUS_SUPABASE_URL'):
            supabase_ais.base_url()

    def test_a_linked_workspace_keeps_the_project_its_key_was_checked_against(self):
        self.link_to('https://otherprojectref.supabase.co/')
        self.assertEqual(supabase_ais.base_url(), 'https://otherprojectref.supabase.co')
        with self.assertRaises(ValueError):
            supabase_ais.base_url(follow_link=False)
        with patch.dict(os.environ, {'ARGUS_SUPABASE_URL': 'https://explicitref.supabase.co'}):
            self.assertEqual(supabase_ais.base_url(), 'https://explicitref.supabase.co')

    def test_a_link_file_cannot_send_the_key_outside_supabase(self):
        for url in ('https://example.com', 'http://otherprojectref.supabase.co', 'https://x.supabase.co/rest', 42):
            self.link_to(url)
            with self.assertRaises(ValueError):
                supabase_ais.base_url()

    def test_linking_records_the_explicit_project_not_an_old_link(self):
        self.link_to('https://otherprojectref.supabase.co')
        with patch.dict(os.environ, {'ARGUS_SUPABASE_URL': 'https://example.supabase.co'}):
            supabase_ais.link(self.root)
        self.assertEqual(json.loads((self.root/supabase_ais.LINK_FILE).read_text())['url'], 'https://example.supabase.co')



class ReadKeyTests(unittest.TestCase):
    """D108: reading the team database needs no secret key; writing still does."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.env = patch.dict(os.environ, {'ARGUS_SATELLITE_ROOT': str(self.root)})
        self.env.start()
        for name in ('ARGUS_SUPABASE_URL', 'ARGUS_SUPABASE_LINK'):
            os.environ.pop(name, None)
        self.no_secret = patch.object(supabase_ais, 'get_key', return_value='')
        self.no_secret.start()
        os.environ.pop('ARGUS_SUPABASE_READ', None)
        os.environ['ARGUS_SUPABASE_URL'] = 'https://example.supabase.co'
        os.environ['ARGUS_SUPABASE_PUBLISHABLE_KEY'] = 'sb_publishable_' + 'test_only_not_a_real_key'
        supabase_ais.enable_keyless_read()  # as run_gui.main does

    def tearDown(self):
        self.no_secret.stop()
        self.env.stop()
        self.folder.cleanup()

    def test_reading_requires_an_explicit_url_and_local_publishable_key(self):
        self.assertEqual(supabase_ais.read_key(), os.environ['ARGUS_SUPABASE_PUBLISHABLE_KEY'])
        with patch.dict(os.environ, {'ARGUS_SUPABASE_PUBLISHABLE_KEY': ''}):
            self.assertEqual(supabase_ais.read_key(), '')
            self.assertFalse(supabase_ais.readable(self.root))
        with patch.dict(os.environ, {'ARGUS_SUPABASE_URL': ''}):
            self.assertEqual(supabase_ais.read_key(), '')
            self.assertFalse(supabase_ais.readable(self.root))

    def test_only_the_apps_own_workspace_reads_without_a_link(self):
        self.assertTrue(supabase_ais.readable(self.root))
        self.assertFalse(supabase_ais.linked(self.root))
        with tempfile.TemporaryDirectory() as other:
            self.assertFalse(supabase_ais.readable(other))  # test folders stay offline
        with patch.dict(os.environ, {'ARGUS_SUPABASE_READ': '0'}):
            self.assertFalse(supabase_ais.readable(self.root))

    def test_keyless_reading_is_off_until_an_entry_point_turns_it_on(self):
        os.environ.pop('ARGUS_SUPABASE_READ')
        self.assertFalse(supabase_ais.readable(self.root))  # tests and servers that set ARGUS_SATELLITE_ROOT stay offline
        os.environ['ARGUS_SUPABASE_READ'] = '0'
        supabase_ais.enable_keyless_read()
        self.assertFalse(supabase_ais.readable(self.root))  # an explicit 0 wins

    def test_read_functions_use_the_publishable_key_and_writes_need_the_secret(self):
        calls = []
        transport = lambda url, payload, key: calls.append((url.rsplit('/', 1)[-1], key)) or {}
        for name in sorted(supabase_ais.READ_FUNCTIONS):
            supabase_ais.rpc(name, {}, transport=transport)
        self.assertEqual({key for _, key in calls}, {os.environ['ARGUS_SUPABASE_PUBLISHABLE_KEY']})
        for name in ('argus_save_scene', 'argus_compare_scene', 'argus_history_claim', 'argus_history_finish'):
            with self.assertRaisesRegex(ValueError, 'not configured'):
                supabase_ais.rpc(name, {}, transport=transport)
        self.assertEqual(len(calls), len(supabase_ais.READ_FUNCTIONS))

    def test_fleet_history_without_a_key_only_reads_the_team_results(self):
        from argus.fleet_history import FleetHistoryWorker
        names = []
        def call(name, payload):
            names.append(name)
            return {'vessels': [], 'next_after': None, 'summary': {'total_vessels': 0}}
        worker = FleetHistoryWorker(self.root, call=call)
        result = worker.step()
        self.assertEqual(names, ['argus_history_index'])  # never a claim or a result write
        self.assertIn(result['state'], {'checking', 'read_only'})
        self.assertIn('read only', result['message'])

if __name__ == '__main__':
    unittest.main()
