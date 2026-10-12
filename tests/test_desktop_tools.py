"""Desktop navigation and review workflows with explicitly simulated contacts."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop_ais import filter_contacts, speed_range, vessel_type
from argus.live_client import LiveState
from desktop_tools import ConsoleTools, parse_coordinates, search_results


def fixture(sequence=1):
    now = datetime.now(timezone.utc)
    rows = []
    for mmsi, name, kind, speed, age in (('111111111', 'Alpha Cargo', '70', 12, 0),
            ('222222222', 'Bravo Tanker', '80', 5, 3600),
            ('333333333', 'Charlie', 'Unavailable', None, 0)):
        rows.append({'mmsi': mmsi, 'name': name, 'ship_type': kind, 'sog_kn': speed,
            'cog_deg': 45, 'lat': 53.2, 'lon': -6.1,
            'received_utc': (now - timedelta(seconds=age)).isoformat(), 'label': 'simulated'})
    return {'schema_version': 1, 'stream_id': 'ui-test', 'sequence': sequence,
        'generated_utc': now.isoformat(), 'feed': {'status': 'live', 'label': 'simulated', 'stale_seconds': 900},
        'vessels': rows}


class DesktopFilterTests(unittest.TestCase):
    def test_speed_range_rejects_invalid_or_inverted_limits(self):
        self.assertEqual(speed_range('', '0'), (None, 0))
        self.assertEqual(speed_range('5', '12'), (5, 12))
        for low, high in (('nan', ''), ('inf', ''), ('-1', ''), ('', '103'), ('10', '5'), ('fish', '')):
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                speed_range(low, high)

    def test_freshness_boundary_and_missing_speed_are_explicit(self):
        rows = [{'received_s': 100, 'sog_kn': 5, 'type': '70'},
                {'received_s': 99, 'sog_kn': 6, 'type': '80'},
                {'received_s': None, 'sog_kn': None, 'type': 'Unavailable'}]
        self.assertEqual(filter_contacts(rows, 1000, 900, fresh_only=True), rows[:1])
        self.assertEqual(filter_contacts(rows, 1000, 900, low=5, high=6), rows[:2])
        self.assertEqual(filter_contacts(rows, 1000, 900, kind='Tanker'), rows[1:2])
        self.assertEqual(vessel_type('79'), 'Cargo')
        self.assertEqual(vessel_type(None), 'Unknown')

    def test_coordinates_support_hemispheres_and_reject_out_of_bounds(self):
        self.assertEqual(parse_coordinates('53.35, -6.25'), (53.35, -6.25))
        self.assertEqual(parse_coordinates('53.35N 6.25W'), (53.35, -6.25))
        self.assertIsNone(parse_coordinates('Dublin'))
        with self.assertRaises(ValueError):
            parse_coordinates('53, 200')
        self.assertFalse(ConsoleTools.valid_view('Bad', {'center': [float('nan'), 0], 'zoom': 8}))


class DesktopToolsWindowTests(unittest.TestCase):
    def test_all_seven_controls_work_together(self):
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
        app.ais_tracker.cache_path = None
        app.ais_tracker.state = LiveState()
        try:
            root.update()
            tracker, tools = app.ais_tracker, app.tools
            tracker.state.apply(fixture())
            app.open_window('ais')
            tracker.fresh_only.set(True)
            tracker.kind.set('Cargo')
            tracker.minimum_speed.set('10')
            self.assertEqual(tracker.table.get_children(), ('111111111',))
            ship_ids = {tag for item in app.map.find_all() for tag in app.map.gettags(item) if tag.startswith('ais-ship:')}
            self.assertEqual(ship_ids, {'ais-ship:111111111'})

            # Global search includes contacts excluded by map filters.
            self.assertTrue(root.bind('<Control-k>'))
            tools.open_search()
            tools.search_query.set('Bravo')
            self.assertEqual(tools.search_matches[0][1], '222222222')
            tools.choose_search()
            self.assertEqual(tracker.selected, '222222222')
            self.assertEqual(tracker.kind.get(), 'All types')
            self.assertIn('Tanker', tracker.detail.cget('text'))
            self.assertIn('Speed: 5.0 kn / Course: 45.0°', tracker.detail.cget('text'))
            self.assertIn('Stale', tracker.detail.cget('text'))

            # Follow uses a later received fix, preserving the source UTC.
            tracker.follow.set(True)
            tracker.update_follow()
            next_fix = fixture(2)
            next_fix['vessels'][1]['lat'] = 53.4
            next_fix['vessels'][1]['received_utc'] = datetime.now(timezone.utc).isoformat()
            tracker.poller = SimpleNamespace(events=queue.Queue(), stop=lambda: None)
            tracker.poller.events.put(('data', next_fix))
            tracker.poll()
            self.assertEqual(app.map_center, (53.4, -6.1))

            # Acknowledgement cannot approve or dispatch a response.
            identifier = app.alert['id']
            tools.set_alert_status(identifier, 'Acknowledged')
            self.assertEqual(tools.alert_statuses[identifier].get(), 'New')
            tools.review_alert(app.alert)
            tools.set_alert_status(identifier, 'Acknowledged')
            self.assertEqual(tools.alert_statuses[identifier].get(), 'Acknowledged')
            self.assertIn('1 acknowledged', app.alert_counts_label.cget('text'))
            self.assertIsNone(app.approved)
            self.assertEqual(tools.legend_sar.cget('state'), 'normal')

            # Legend switches control the map and stale-contact filtering.
            tools.legend_controls['Ports'].toggle()
            self.assertFalse(app.map_layers['World ports'].get())
            self.assertFalse(any(tag.startswith('world-port:') for item in app.map.find_all() for tag in app.map.gettags(item)))
            tools.legend_controls['Ports'].toggle()
            tools.legend_controls['Stale'].toggle()
            self.assertTrue(tracker.fresh_only.get())

            app.open_window('views')
            tools.apply_view('Dublin Bay')
            self.assertFalse(tracker.follow.get())
            self.assertGreater(app.map_zoom, 6)
            panel = app._panel_widgets['views']
            entry = next(w for w in panel.winfo_children() if isinstance(w, ttk.Entry))
            entry.insert(0, 'My harbour')
            save = next(w for w in panel.winfo_children() if isinstance(w, ttk.Button) and w.cget('text') == 'Save current view')
            save.invoke()
            self.assertIn('My harbour', tools.custom_views)
            self.assertTrue(search_results(app, 'My harbour', tools.custom_views))

            # Both overlay panels resize; alerts can be hidden and restored.
            tools.start_resize('alerts', 100)
            tools.resize('alerts', 140)
            self.assertEqual(tools.alert_width, 360)
            tools.start_resize('details', 100)
            tools.resize('details', 50)
            self.assertEqual(tools.detail_width, 455)
            tools.toggle_alerts()
            self.assertFalse(app.alerts_panel.winfo_ismapped())
            tools.toggle_alerts()

            tools.open_search()
            tools.search_query.set('53.35N 6.25W')
            tools.choose_search()
            self.assertEqual(app.map_center, (53.35, -6.25))
            tools.open_search()
            tools.search_query.set('Dublin')
            result = next(i for i, row in enumerate(tools.search_matches) if row[0] == 'port')
            tools.search_table.selection_set(str(result))
            tools.choose_search()
            self.assertIsNotNone(app.selected_port)

            with TemporaryDirectory() as directory:
                tools.settings_path = Path(directory) / 'preferences.json'
                tools.save()
                saved = json.loads(tools.settings_path.read_text())
                self.assertIn('My harbour', saved['views'])
                self.assertEqual(saved['detail_width'], 455)
                self.assertNotIn('alerts', saved)
                tools.settings_path = None
            root.update()
            self.assertEqual(errors, [])
        finally:
            app.close()
