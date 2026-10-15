"""Floating selected-vessel interactions use labelled simulated AIS only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from argus.live_client import LiveState
from desktop_tracks import ReceivedTracks
from desktop_vessel_card import age_description, local_photo, navigation_status


class VesselCardDataTests(unittest.TestCase):
    def test_reported_status_age_and_local_photo_validation(self):
        self.assertEqual(navigation_status(0), 'Underway using engine')
        self.assertEqual(navigation_status(15), 'Not reported')
        self.assertEqual(age_description(0, 19*3600 + 27*60), '19 h 27 min ago')
        self.assertEqual(age_description(None, 1), 'No position received')
        with TemporaryDirectory() as directory:
            path = Path(directory)
            Image.new('RGB', (800, 500), '#304050').save(path / '250123456.jpg')
            self.assertEqual(local_photo(path, '250123456').size, (720, 340))
            self.assertIsNone(local_photo(path, '../250123456'))
            self.assertIsNone(local_photo(path, '123456789'))
            (path / '123456789.png').write_text('damaged')
            self.assertIsNone(local_photo(path, '123456789'))


class VesselCardWindowTests(unittest.TestCase):
    def test_click_popup_track_fleet_drag_resize_details_and_close(self):
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
        start = datetime.now(timezone.utc) - timedelta(minutes=3)
        try:
            root.update()
            for index in range(2):
                payload = {'schema_version': 1, 'stream_id': 'card-test', 'sequence': index+1,
                    'feed': {'status': 'live', 'label': 'simulated'}, 'vessels': [
                        {'mmsi': '250123456', 'name': 'TEST FISHING BOAT', 'ship_type': '30',
                         'lat': 53 + index/100, 'lon': -6, 'sog_kn': 5.5, 'cog_deg': 173,
                         'nav_status': 0, 'destination': 'DUBLIN',
                         'received_utc': (start + timedelta(minutes=index)).isoformat(), 'label': 'simulated'}]}
                tracker.state.apply(payload)
                tracker.history.capture(tracker.state.vessels, 'card-test', start.timestamp() + 120)
            tracker.select_on_map('250123456')
            root.update()
            card = tracker.card
            self.assertTrue(card.frame.winfo_ismapped())
            self.assertEqual(card.frame.cget('fg_color'), '#ffffff')
            self.assertFalse(app.panel_visible)
            self.assertEqual(card.name.cget('text'), 'TEST FISHING BOAT')
            self.assertEqual(card.kind.cget('text'), 'Fishing')
            self.assertEqual(card.destination.cget('text'), 'DUBLIN')
            self.assertEqual(card.labels['navigation'].cget('text'), 'Underway using engine')
            self.assertIn('5.5 kn', card.labels['speed'].cget('text'))
            self.assertIn('173°', card.labels['speed'].cget('text'))
            self.assertEqual(card.labels['draught'].cget('text'), 'Not reported')
            self.assertIn('unavailable', card.hero.cget('text'))
            self.assertIn('simulated', card.source.cget('text'))
            self.assertIn('unknown', card.source.cget('text'))
            card.report_button.invoke()
            root.update()
            self.assertEqual(app.report_dialog.vessel['id'], '250123456')
            self.assertEqual(app.report_dialog.vessel['label'], 'simulated')
            app.report_dialog.close()
            self.assertEqual(len(card.flag.find_all()), 3)
            self.assertTrue(app.map.find_withtag('selected_ais_name'))
            self.assertTrue(any(app.map.type(item) == 'line' and app.map.itemcget(item, 'fill') == '#ffd15a'
                                for item in app.map.find_withtag('selected_ais_path')))
            card.fleet_button.invoke()
            self.assertIn('250123456', tracker.fleet)
            self.assertEqual(card.fleet_button.cget('text'), 'Remove from fleet')
            card.fleet_button.invoke()
            self.assertNotIn('250123456', tracker.fleet)
            card.past_button.invoke()
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            card.past_button.invoke()
            self.assertTrue(app.map.find_withtag('selected_ais_path'))
            card.start_drag(SimpleNamespace(x_root=100, y_root=100))
            card.move_drag(SimpleNamespace(x_root=-1000, y_root=1000))
            root.update_idletasks()
            self.assertGreaterEqual(card.frame.winfo_x(), 0)
            self.assertLessEqual(card.frame.winfo_y() + card.frame.winfo_height(), app.chart_host.winfo_height())
            root.geometry('960x700')
            root.update()
            self.assertLessEqual(card.frame.winfo_x() + card.frame.winfo_width(), app.chart_host.winfo_width())
            self.assertTrue(card.body.winfo_ismapped())
            card.details_button.invoke()
            root.update()
            self.assertFalse(card.frame.winfo_ismapped())
            self.assertTrue(app.panel_visible)
            tracker.select_on_map('250123456')
            card.route_button.invoke()
            self.assertEqual(app.map_tool, 'measure')
            self.assertFalse(card.frame.winfo_ismapped())
            app._set_map_tool('measure')
            tracker.select_on_map('250123456')
            tracker.clear_selection()
            root.update()
            self.assertFalse(card.frame.winfo_ismapped())
            self.assertEqual(app.map.find_withtag('selected_ais_path'), ())
            self.assertIsNone(app.approved)
            self.assertEqual(errors, [])
        finally:
            app.close()
