"""Received history and selected-only rendering, using simulated fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.live_client import LiveState
from desktop_tracks import ReceivedTracks, RETENTION_SECONDS


START = datetime(2026, 10, 12, tzinfo=timezone.utc)
MMSI = '123456789'


def packet(second=0, identifier=MMSI, stream='test', **fields):
    stamp = (START + timedelta(seconds=second)).isoformat()
    return {'schema_version': 1, 'stream_id': stream, 'sequence': second + 1,
            'generated_utc': stamp, 'feed': {'status': 'live', 'label': 'simulated'},
            'vessels': [{'mmsi': identifier, 'name': 'TEST SHIP', 'lat': 53 + second / 100_000,
                         'lon': -6, 'received_utc': stamp, 'label': 'simulated', **fields}]}


class ReceivedTrackTests(unittest.TestCase):
    def setUp(self):
        self.state = LiveState()
        self.history = ReceivedTracks()

    def capture(self, second=0, **fields):
        self.state.apply(packet(second, **fields))
        self.history.capture(self.state.vessels, self.state.stream_id, START.timestamp() + second)

    def test_repeated_and_older_fixes_do_not_extend_a_path(self):
        self.capture()
        self.capture()
        self.capture(60)
        self.capture(10)
        self.assertEqual([p['received_s'] for p in self.history.tracks[MMSI]],
                         [START.timestamp(), START.timestamp() + 60])

    def test_gaps_and_source_changes_leave_separate_sections(self):
        self.capture()
        self.capture(60)
        self.capture(1000)
        self.capture(1001, stream='restarted')
        self.capture(1002, stream='restarted', label='real')
        self.assertEqual([len(s) for s in self.history.sections(MMSI)], [2, 1, 1, 1])

    def test_age_per_ship_and_total_limits_and_removals(self):
        with patch('desktop_tracks.MAX_POINTS', 2):
            for second in (0, 1, 2):
                self.capture(second)
        self.assertEqual(len(self.history.tracks[MMSI]), 2)
        with patch('desktop_tracks.MAX_TOTAL_POINTS', 2):
            both = packet(3, identifier='987654321')
            both['vessels'].extend(self.state.vessels.values())
            self.state.apply(both)
            self.history.capture(self.state.vessels, self.state.stream_id, START.timestamp() + 3)
        self.assertEqual(set(self.history.tracks), {'987654321'})
        self.history.prune(START.timestamp() + RETENTION_SECONDS + 4)
        self.assertEqual(self.history.total, 0)
        self.capture(5)
        self.history.prune(START.timestamp() + 5, set())
        self.assertEqual(self.history.tracks, {})

    def test_cache_validates_history_and_preserves_source_times(self):
        self.capture()
        self.capture(60)
        restored = ReceivedTracks()
        restored.restore(deepcopy(dict(self.history.tracks)), self.state.vessels, START.timestamp() + 61)
        self.assertEqual(restored.tracks, self.history.tracks)
        damaged = deepcopy(dict(self.history.tracks))
        damaged[MMSI][0]['lat'] = float('nan')
        restored.restore(damaged, self.state.vessels, START.timestamp() + 61)
        self.assertEqual(restored.tracks, self.history.tracks)
        damaged = deepcopy(dict(self.history.tracks))
        damaged[MMSI][1]['received_utc'] = (START + timedelta(hours=1)).isoformat()
        restored.restore(damaged, self.state.vessels, START.timestamp() + 61)
        self.assertEqual(restored.tracks, self.history.tracks)


class SelectedPathWindowTests(unittest.TestCase):
    def test_selection_destination_gaps_toggle_filter_and_clear(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.attributes('-alpha', 0)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': ''}):
            app = ArgusApp(root, *load_demo())
        tracker = app.ais_tracker
        tracker.cache_path = None
        tracker.state = LiveState()
        tracker.history = ReceivedTracks()
        try:
            root.update()
            for second in (0, 60, 1000):
                tracker.state.apply(packet(second, destination='DUBLIN',
                    destination_received_utc='2026-10-12T00:00:00Z'))
                tracker.history.capture(tracker.state.vessels, 'test', START.timestamp() + second)
            both = packet(1001, identifier='987654321')
            both['vessels'].extend(tracker.state.vessels.values())
            tracker.state.apply(both)
            app._draw_map()
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            tracker.select_on_map(MMSI)
            root.update()
            detail = tracker.detail.cget('text')
            self.assertIn('Declared destination: DUBLIN', detail)
            self.assertIn('First recorded fix: 53.00000, -6.00000', detail)
            self.assertIn('2026-10-12T00:00:00Z', detail)
            path = app.map.find_withtag('selected_ais_path')
            self.assertEqual(sum(app.map.type(item) == 'line' for item in path), 1)
            self.assertTrue(tracker.detail.winfo_ismapped())
            tracker.show_path.set(False)
            app._draw_map()
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            tracker.show_path.set(True)
            tracker.kind.set('Fishing')
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            tracker.reset_filters()
            tracker.select_on_map('987654321')
            self.assertIn('Declared destination: Not reported', tracker.detail.cget('text'))
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            tracker.select_on_map(MMSI)
            tracker.fit_path()
            tracker.clear_selection()
            root.update()
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            self.assertIsNone(app.approved)
            self.assertEqual(errors, [])
        finally:
            app.close()
