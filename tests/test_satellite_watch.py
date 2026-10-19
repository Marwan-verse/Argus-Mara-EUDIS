"""SATELLITE-WATCH launchers: fresh-image window, setup script and app start."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus.satellite import atomic_json
from argus.satellite_scan import FRESH_DEFAULT_H, CoastalScan, max_image_age
from argus.satellite_workspace import SatelliteWorkspace

spec = importlib.util.spec_from_file_location('satellite_watch', ROOT/'scripts/satellite_watch.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

NOW = datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)
ENV = 'ARGUS_SATELLITE_MAX_IMAGE_AGE_H'
TENSORX_KEY = 'tx-' + 'k' * 30
DATABASE_KEY = 'sb_secret_' + 'd' * 30


def granule(when, cloud=20.0):
    return {'id': 'S2_' + when[:16].replace(':', ''), 'acquired_utc': when, 'bbox': [-6.5, 53.0, -5.0, 54.0],
            'cloud_percent': cloud}


def answers(*values):
    values = list(values)
    return lambda _prompt: values.pop(0)


class FreshWindowTests(unittest.TestCase):
    def discover_start(self, hours=None, last=None):
        seen = {}

        def search(sensor, area, start, end, all_pages=False):
            seen['start'] = datetime.fromisoformat(start)
            return []
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ):
            os.environ.pop(ENV, None)
            if hours is not None:
                os.environ[ENV] = hours
            engine = CoastalScan(SatelliteWorkspace(Path(folder)/'satellite'))
            if last:
                engine.state['last_discovery_utc'] = last.isoformat()
            engine.discover(now=NOW, search=search)
            return seen['start'], engine.state['message']

    def test_unset_keeps_the_seven_day_window(self):
        start, message = self.discover_start()
        self.assertEqual(start, NOW - timedelta(days=7))
        self.assertNotIn('images from the last', message)

    def test_window_limits_a_first_start(self):
        start, message = self.discover_start('36')
        self.assertEqual(start, NOW - timedelta(hours=36))
        self.assertTrue(message.endswith('· images from the last 36 h'))

    def test_window_also_limits_later_discoveries_but_never_widens_them(self):
        last = NOW - timedelta(hours=1)
        self.assertEqual(self.discover_start('36', last)[0], NOW - timedelta(hours=36))
        self.assertEqual(self.discover_start('168', last)[0], last - timedelta(days=2))

    def test_invalid_windows_are_refused(self):
        for raw in ('soon', '2', '500'):
            with patch.dict(os.environ, {ENV: raw}), self.assertRaises(ValueError, msg=raw):
                max_image_age()

    def test_launcher_default_is_valid(self):
        with patch.dict(os.environ, {ENV: str(FRESH_DEFAULT_H)}):
            self.assertEqual(max_image_age(), timedelta(hours=36))


class SetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        # main() switches keyless reading on (D108); keep that from leaking into later tests.
        self.environment = patch.dict(os.environ, {'ARGUS_SUPABASE_URL': 'https://example.supabase.co'})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.folder.cleanup()

    def test_database_setup_without_a_project_never_requests_a_secret(self):
        with patch.dict(os.environ, {'ARGUS_SUPABASE_URL': ''}), redirect_stdout(io.StringIO()):
            ask, rpc, save = Mock(), Mock(), Mock()
            self.assertIsNone(watch.connect_database(self.root, ask=ask, rpc=rpc, save=save))
        ask.assert_not_called()
        rpc.assert_not_called()
        save.assert_not_called()

    def test_tensorx_key_is_checked_for_free_before_it_is_saved(self):
        saved = []
        output = io.StringIO()
        with redirect_stdout(output):
            model = watch.connect_tensorx(self.root, ask=answers(TENSORX_KEY),
                                          choose=lambda key: {'id': 'qwen/qwen3.8-flash-next', 'reservation_usd': .2},
                                          save=saved.append)
        self.assertEqual(model['id'], 'qwen/qwen3.8-flash-next')
        self.assertEqual(saved, [TENSORX_KEY])
        self.assertEqual(json.loads((self.root/'ai/model.json').read_text())['reservation_usd'], .2)
        self.assertNotIn(TENSORX_KEY, output.getvalue())

    def test_a_refused_tensorx_key_is_not_saved_and_enter_skips(self):
        def refuse(key):
            raise ValueError('Provider refused request (HTTP 401); check access and credits')
        save = Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(watch.connect_tensorx(self.root, ask=answers(TENSORX_KEY, ''), choose=refuse, save=save))
        save.assert_not_called()
        self.assertIn('Not saved', output.getvalue())
        self.assertNotIn(TENSORX_KEY, output.getvalue())
        self.assertFalse((self.root/'ai/model.json').exists())

    def test_database_key_is_checked_then_saved_and_linked(self):
        rpc, save, link = Mock(return_value={'positions': 43000}), Mock(), Mock()
        state = watch.connect_database(self.root, ask=answers(DATABASE_KEY), rpc=rpc, save=save, link=link)
        self.assertEqual(state, {'positions': 43000})
        self.assertTrue(rpc.call_args[0][0].endswith('/rest/v1/rpc/argus_ais_status'))
        save.assert_called_once_with(DATABASE_KEY)
        link.assert_called_once_with(self.root)

    def test_a_wrong_database_key_format_is_never_sent(self):
        rpc = Mock()
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(watch.connect_database(self.root, ask=answers('my-password', ''), rpc=rpc,
                                                     save=Mock(), link=Mock()))
        rpc.assert_not_called()

    def test_budget_counts_image_checks_left_at_the_measured_real_cost(self):
        atomic_json(self.root/'ai/model.json', {'reservation_usd': .2})
        atomic_json(self.root/'ai/budget.json', {'reserved_usd': 0, 'reported_usd': 0, 'calls': 0})
        money = watch.budget(self.root)
        self.assertEqual((money['calls_left'], money['basis'], money['per_check_usd']), (100, 'worst case', .2))
        # After calls settle, one reservation of headroom stays free and the rest goes at $0.02 each.
        atomic_json(self.root/'ai/budget.json', {'reserved_usd': 1.0, 'reported_usd': .1, 'calls': 5, 'settled_calls': 5})
        money = watch.budget(self.root)
        self.assertEqual((money['left_usd'], money['calls_left'], money['basis'], money['halted']), (19.0, 940, 'measured', False))
        self.assertIsNone(watch.budget(self.root/'empty')['calls_left'])

    def test_granules_group_into_passes_and_missing_passes_are_expected(self):
        rows = [granule('2026-10-16T11:45:10Z'), granule('2026-10-16T11:57:30Z', 60.0),
                granule('2026-10-16T11:50:00Z', 40.0), granule('2026-10-15T11:26:00Z', 97.0)]
        found = watch.passes(rows)
        self.assertEqual([(p['first_utc'][:16], p['granules']) for p in found],
                         [('2026-10-16T11:45', 3), ('2026-10-15T11:26', 1)])
        self.assertEqual(found[0]['median_cloud'], 40.0)
        ten_days_ago = lambda *args, **kwargs: [granule('2026-10-06T11:45:00Z'), granule('2026-10-06T11:57:00Z')]
        expected = watch.expected_passes(NOW, 36, [], search=ten_days_ago)
        self.assertEqual([(p['first_utc'], p['last_utc'], p['taken']) for p in expected],
                         [('2026-10-16T11:45:00Z', '2026-10-16T11:57:00Z', False)])
        self.assertEqual(watch.expected_passes(NOW, 36, found[:1], search=ten_days_ago), [])

    def test_ships_at_counts_distinct_ships_with_positions(self):
        rows = [{'mmsi': '1', 'msg_type': 'PositionReport'}, {'mmsi': '1', 'msg_type': 'PositionReport'},
                {'mmsi': '2', 'msg_type': 'PositionReport'}, {'mmsi': '3', 'msg_type': 'ShipStaticData'}]
        self.assertEqual(watch.ships_at('2026-10-16T11:50:00Z', [-11, 51, -5, 56], rows_for=lambda *a: {'rows': rows}), 2)
        self.assertEqual(watch.ais_note(0, 290), ' · no AIS in the database at that time')
        self.assertEqual(watch.ais_note(6, 290), ' · 6 ships in the database at that time (thin: usually about 290)')
        self.assertEqual(watch.ais_note(240, 290), ' · 240 ships in the database at that time')

    def test_check_mode_reports_what_is_missing_and_never_asks(self):
        output = io.StringIO()
        with patch.object(watch, 'readers_installed', return_value=True), \
                patch.object(watch, 'tensorx_connected', return_value=False), \
                patch.object(watch.supabase_ais, 'linked', return_value=False), \
                patch.object(watch, 'show_images'), \
                patch.object(watch, 'connect_tensorx') as tensorx, \
                patch.object(watch, 'connect_database') as database, \
                redirect_stdout(output):
            code = watch.main(['--check', '--root', str(self.root)])
        self.assertEqual(code, watch.NOT_READY)
        tensorx.assert_not_called()
        database.assert_not_called()
        self.assertIn('Team database   not reachable', output.getvalue())
        self.assertIn('TensorX AI      not connected', output.getvalue())


    def test_without_a_key_the_team_database_is_read_only_and_nothing_is_asked(self):
        output = io.StringIO()
        with patch.object(watch, 'readers_installed', return_value=True), \
                patch.object(watch, 'tensorx_connected', return_value=True), \
                patch.object(watch.supabase_ais, 'configured', return_value=False), \
                patch.object(watch.supabase_ais, 'linked', return_value=False), \
                patch.object(watch.supabase_ais, 'readable', return_value=True), \
                patch.object(watch, 'show_database', return_value={'vessels_last_hour': 290}), \
                patch.object(watch, 'show_images'), \
                patch.object(watch, 'connect_database') as database, \
                redirect_stdout(output):
            code = watch.main(['--root', str(self.root)])
        self.assertEqual(code, 0)
        database.assert_not_called()
        self.assertIn('read only with locally configured credentials', output.getvalue())
        self.assertIn('Ready.', output.getvalue())

    def test_a_stored_database_key_links_a_new_workspace_without_asking(self):
        output = io.StringIO()
        with patch.object(watch, 'readers_installed', return_value=True), \
                patch.object(watch, 'tensorx_connected', return_value=True), \
                patch.object(watch.supabase_ais, 'configured', return_value=True), \
                patch.object(watch.supabase_ais, 'linked', side_effect=lambda root: (Path(root)/'database.link').is_file()), \
                patch.object(watch, 'show_database', return_value={'vessels_last_hour': 290}), \
                patch.object(watch, 'show_images'), \
                patch.object(watch, 'connect_database') as database, \
                redirect_stdout(output):
            code = watch.main(['--root', str(self.root)])
        self.assertEqual(code, 0)
        database.assert_not_called()
        self.assertTrue((self.root/'database.link').is_file())
        self.assertIn('workspace linked', output.getvalue())
        self.assertIn('Ready.', output.getvalue())


class StartWatchTests(unittest.TestCase):
    def setUp(self):
        from desktop_satellite import DesktopSatellite
        self.start_watch = DesktopSatellite.start_watch
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.panel = SimpleNamespace(closed=False, remote=False, busy=False, workspace=SimpleNamespace(root=self.root),
                                     messages=[], actions=[], retries=[])
        self.panel.message = self.panel.messages.append
        self.panel.scan_control = self.panel.actions.append
        self.panel.start_watch = lambda: None
        self.panel.app = SimpleNamespace(root=SimpleNamespace(after=lambda ms, _callback: self.panel.retries.append(ms)))

    def tearDown(self):
        self.folder.cleanup()

    def run_with_key(self, key):
        with patch('desktop_satellite.get_key', return_value=key):
            self.start_watch(self.panel)

    def test_without_tensorx_it_explains_the_free_option(self):
        self.run_with_key('')
        self.assertEqual(self.panel.actions, [])
        self.assertIn('AIS at image time', self.panel.messages[0])

    def test_with_tensorx_it_starts_the_scan_once(self):
        self.run_with_key(TENSORX_KEY)
        self.assertEqual(self.panel.actions, ['start'])
        atomic_json(self.root/'scan/state.json', {'enabled': True, 'jobs': {}, 'coverage': {}})
        self.run_with_key(TENSORX_KEY)  # an enabled scan is resumed by the panel itself
        self.assertEqual(self.panel.actions, ['start'])

    def test_a_busy_panel_retries_instead_of_dropping_the_start(self):
        self.panel.busy = True
        self.run_with_key(TENSORX_KEY)
        self.assertEqual((self.panel.actions, self.panel.retries), ([], [1000]))

    def test_the_app_offers_the_flag(self):
        result = subprocess.run([sys.executable, str(ROOT/'run_gui.py'), '--help'], capture_output=True,
                                encoding='utf-8', timeout=60, cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--coast-watch', result.stdout)


if __name__ == '__main__':
    unittest.main()
