"""Integrated tracker connection lifecycle; fake feeds never contact a provider."""
import queue
import json
import tkinter as tk
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_ais import DesktopAIS, age_text


def snapshot():
    return {"schema_version": 1, "stream_id": "test", "sequence": 1,
            "generated_utc": "2026-10-12T00:00:01Z",
            "feed": {"status": "live", "label": "simulated"},
            "vessels": [{"mmsi": "123456789", "name": "TEST CONTACT", "ship_type": "Cargo",
                         "lat": 53, "lon": -6, "sog_kn": 5, "cog_deg": 10,
                         "received_utc": "2026-10-12T00:00:00Z", "label": "simulated"}]}


class DesktopAISTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tcl()
        self.app = SimpleNamespace(root=self.root, _draw_map=Mock(), _fit_points=Mock(),
                                   _change_map_center=Mock(), approved=None, position_s=5400)
        self.factory = Mock(side_effect=self.make_poller)
        self.tracker = DesktopAIS(self.app, self.factory)

    def make_poller(self, address):
        return SimpleNamespace(events=queue.Queue(), start=Mock(), stop=Mock(), address=address)

    def tearDown(self):
        self.tracker.close()

    def connect(self):
        self.tracker.address.set("https://ais.example.org")
        self.tracker.connect()
        return self.tracker.poller

    def test_start_is_offline_and_invalid_address_does_not_start_worker(self):
        self.factory.assert_not_called()
        self.tracker.address.set("http://public.example.org")
        self.tracker.connect()
        self.factory.assert_not_called()
        self.assertIn("HTTPS", self.tracker.status)

    def test_received_data_does_not_change_fictional_replay(self):
        poller = self.connect()
        poller.events.put(("data", snapshot()))
        self.tracker.poll()
        self.assertEqual(len(self.tracker.positions()), 1)
        self.assertEqual(self.app.position_s, 5400)
        self.assertIsNone(self.app.approved)
        self.assertIn("simulated", self.tracker.status)

    def test_each_queued_fix_is_recorded_and_history_survives_cache_reload(self):
        poller = self.connect()
        start = datetime.now(timezone.utc) - timedelta(minutes=3)
        for index in range(2):
            data = snapshot()
            data['sequence'] += index
            data['vessels'][0].update(lat=53 + index / 100,
                received_utc=(start + timedelta(minutes=index)).isoformat())
            poller.events.put(('data', data))
        self.tracker.poll()
        self.assertEqual(len(self.tracker.history.tracks['123456789']), 2)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'latest.json'
            self.tracker.cache_path = path
            self.tracker.fleet.add('123456789')
            self.tracker.save_cache()
            with patch.dict('os.environ', {'ARGUS_LIVE_SERVER': 'https://ais.example.org'}):
                restored = DesktopAIS(self.app, self.factory, cache_path=path)
            try:
                self.assertEqual(restored.history.tracks, self.tracker.history.tracks)
            finally:
                restored.close()
            self.tracker.cache_path = None
        self.tracker.disconnect()
        self.assertEqual(self.tracker.history.total, 0)

    def test_invalid_response_retains_valid_data_and_disconnect_clears_it(self):
        poller = self.connect()
        poller.events.put(("data", snapshot()))
        self.tracker.poll()
        poller.events.put(("data", {"schema_version": 99}))
        self.tracker.poll()
        self.assertEqual(len(self.tracker.positions()), 1)
        self.assertIn("Invalid", self.tracker.status)
        self.tracker.disconnect()
        poller.stop.assert_called_once()
        self.assertEqual(self.tracker.positions(), [])

    def test_reconnect_ignores_old_worker_queue_and_retains_last_valid_contacts(self):
        old = self.connect()
        old.events.put(("data", snapshot()))
        self.tracker.poll()
        new = self.connect()
        old.stop.assert_called_once()
        old.events.put(("data", snapshot()))
        self.tracker.poll()
        self.assertIs(self.tracker.poller, new)
        self.assertEqual(len(self.tracker.positions()), 1)

    def test_server_switch_clears_other_servers_contacts(self):
        self.connect()
        self.tracker.state.apply(snapshot())
        self.tracker.address.set("https://different.example.org")
        self.tracker.connect()
        self.assertEqual(self.tracker.positions(), [])

    def test_center_and_fit_use_received_coordinates(self):
        self.tracker.state.apply(snapshot())
        self.tracker.selected = "123456789"
        self.tracker.center()
        self.app._change_map_center.assert_called_once_with((53, -6))
        self.tracker.fit()
        self.app._fit_points.assert_called_once_with([(53, -6)])

    def test_age_missing_and_future_timestamps(self):
        self.assertEqual(age_text(None, 100), "No position")
        self.assertEqual(age_text(200, 100), "<1 min")
        self.assertEqual(age_text(0, 3600), "1 h")

    def test_cache_preserves_received_time_and_is_not_a_live_connection(self):
        with TemporaryDirectory() as directory:
            self.connect()
            self.tracker.state.apply(snapshot())
            path = Path(directory) / "latest.json"
            self.tracker.cache_path = path
            self.tracker.fleet.add('123456789')
            self.tracker.save_cache()
            with patch.dict("os.environ", {"ARGUS_LIVE_SERVER": "https://ais.example.org"}):
                restored = DesktopAIS(self.app, self.factory, cache_path=path)
            try:
                self.assertEqual(restored.positions()[0]['received_utc'], '2026-10-12T00:00:00Z')
                self.assertIsNone(restored.poller)
                self.assertEqual(restored.fleet, {'123456789'})
                self.assertTrue(restored.status.startswith('Cached'))
                self.assertNotIn('raw', json.loads(path.read_text())['vessels'][0])
            finally:
                restored.close()

    def test_cache_from_another_server_is_not_displayed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'latest.json'
            path.write_text(json.dumps({**snapshot(), 'server': 'https://other.example.org'}))
            restored = DesktopAIS(self.app, self.factory, cache_path=path)
            try:
                self.assertEqual(restored.positions(), [])
            finally:
                restored.close()


class DesktopAISWindowTests(unittest.TestCase):
    def test_docked_tracker_rebuild_search_and_map_overlay(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Native display unavailable: {error}")
        root.attributes("-alpha", 0)
        callback_errors = []
        root.report_callback_exception = lambda *error: callback_errors.append(error)
        with patch.dict('os.environ', {'ARGUS_UI_PREFERENCES': ''}):
            app = ArgusApp(root, *load_demo())
        app.ais_tracker.cache_path = None
        try:
            root.update()
            self.assertFalse(app.panel_visible)
            self.assertFalse(app.exercise_visible.get())
            self.assertGreater(app.map.winfo_width(), root.winfo_width() * .9)
            self.assertGreater(app.map.winfo_height(), root.winfo_height() * .8)
            self.assertTrue(app.alerts_panel.winfo_ismapped())
            self.assertLess(app.alerts_panel.winfo_x(), app.map.winfo_width() / 2)
            self.assertEqual(len(app.alert_cards), len(app.alerts))
            self.assertEqual(app.alert_cards[0][1].cget('text'), '--:--:--')
            self.assertTrue(app.map_layers['World ports'].get())
            app.fit_ireland()
            represented_ports = set()
            for item in app.map.find_all():
                for tag in app.map.gettags(item):
                    if tag.startswith('world-port:'):
                        represented_ports.add(int(tag.split(':')[1]))
                    elif tag.startswith('world-port-cluster:'):
                        represented_ports.update(row[0] for row in app._port_clusters[tag])
            self.assertEqual(represented_ports, app.irish_port_indices)
            app.open_window('ports')
            self.assertEqual(app.port_country.get(), 'Irish coast')
            self.assertEqual(len(app.port_table.get_children()), len(app.irish_port_indices))
            marine_index = next(i for i, p in enumerate(app.world_ports) if str(p[0]) in app.port_metadata)
            app._select_port(marine_index)
            self.assertIn('Marine Atlas', app.port_detail.cget('text'))
            app.open_window("ais")
            self.assertTrue(app.panel_visible)
            app.ais_tracker.state.apply(snapshot())
            app.ais_tracker.refresh()
            self.assertEqual(app.ais_tracker.table.get_children(), ("123456789",))
            app.ais_tracker.query.set("does not exist")
            self.assertEqual(app.ais_tracker.table.get_children(), ())
            app.ais_tracker.query.set("123456789")
            self.assertEqual(app.ais_tracker.table.get_children(), ("123456789",))
            app.ais_tracker.table.selection_set("123456789")
            app.ais_tracker.select()
            app.ais_tracker.center()
            root.update()
            app._draw_map()
            self.assertGreater(len(app.map.find_withtag("received_ais")), 1)
            self.assertIn("simulated", app.ais_tracker.detail.cget("text"))
            app.ais_tracker.select_on_map("123456789")
            self.assertEqual(app.ais_tracker.query.get(), "123456789")
            self.assertIn("2026-10-12T00:00:00Z", app.ais_tracker.detail.cget("text"))
            app.move_current_panel("bottom")
            self.assertEqual(app._panel_locations["ais"], "bottom")
            app._close_panel("ais")
            app.open_window("ais")
            self.assertEqual(app.ais_tracker.table.get_children(), ("123456789",))
            app.open_window("sar_plan")
            self.assertIn("sar_plan", app._panel_widgets)
            app.ais_tracker.disconnect()
            self.assertEqual(app.ais_tracker.table.get_children(), ())
            app.show_exercise()
            self.assertTrue(app.exercise_visible.get())
            self.assertRegex(app.alert_cards[0][1].cget('text'), r'^\d\d:\d\d:\d\d$')
            app.hide_exercise()
            self.assertFalse(app.exercise_visible.get())
            root.update()
            self.assertEqual(callback_errors, [])
        finally:
            app.close()
