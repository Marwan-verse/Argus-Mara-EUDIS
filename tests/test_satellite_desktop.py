"""Native dock, actual raster overlay and saved acquisition-time review."""
from io import BytesIO
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image

from test_satellite import fixture


class SatelliteDesktopTests(unittest.TestCase):
    def test_satellite_panel_and_georeferenced_overlay(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.attributes('-alpha', 0)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': ''}), \
                patch('argus.satellite_workspace.get_key', return_value=''):
            app = ArgusApp(root, *load_demo())
            satellite = app.satellite
            satellite.workspace, scene, image = fixture(Path(temp)/'satellite')
            try:
                with patch.object(satellite, 'task', side_effect=lambda function, callback: callback(function())):
                    app.open_window('satellite')
                    root.update()
                    self.assertIn(scene['id'], satellite.scene_table.get_children())
                    satellite.scene_table.selection_set(scene['id'])
                    root.update()
                    self.assertEqual(satellite.current['scene']['acquired_utc'], scene['acquired_utc'])
                    self.assertIsNotNone(satellite.map_photo)
                    self.assertIn('UNAVAILABLE', satellite.details.get('1.0', 'end').upper())
                    self.assertEqual(satellite.workspace.status()['automatic'], False)
                    self.assertNotIn('Satellite analysis', app.map_layers)  # Independent review layer, not live AIS.
                    watch_status = satellite.workspace.status()
                    watch_status['scan'].update(enabled=True, running=True, covered_tiles=12,
                                                tiles_without_image=None, ais=None)
                    satellite.apply_watch((watch_status, [], None))
                    self.assertIn('SCANNING', satellite.coast_status.get())
                    self.assertIn('12/', satellite.coast_status.get())
                    for side in ('North', 'East', 'South', 'West'):
                        self.assertIn(side+':', satellite.coast_status.get())
                    self.assertIn('Rotation: North', satellite.coast_status.get())
                    point = {'id': 'AI-1', 'x': .5, 'y': .5, 'lat': 53.33, 'lon': -6.12,
                             'confidence': 'low', 'description': 'Synthetic test contact', 'association': 'provisional_spatiotemporal_match',
                             'matched_mmsi': '123456789', 'ambiguous': False,
                             'candidates': [{'mmsi': '123456789', 'name': 'SYNTHETIC TEST SHIP', 'distance_m': 15,
                                'nearest_fix_offset_s': 20, 'within_gate': True,
                                'position_evidence': {'position_method': 'observed_fix', 'observation_time_assumed': True},
                                'broadcast_fields': {'destination': {'value': 'TEST PORT', 'received_utc': scene['acquired_utc']}},
                                'latest': {'lat': 53.34, 'lon': -6.10, 'received_utc': '2026-10-13T13:00:00Z',
                                    'age_s': 30, 'stale': False, 'after_image': True, 'displacement_km': 2,
                                    'minimum_average_speed_kn': 1, 'travel_consistency': 'within_assumed_limit'}}]}
                    satellite.current['contacts'] = [point]
                    satellite.redraw()
                    self.assertTrue(app.map.find_withtag('satellite-contact-AI-1'))
                    satellite.show_contact(point)
                    root.update()
                    self.assertEqual(len(satellite.candidate_table.get_children()), 1)
                    self.assertEqual(satellite.selected_candidate['mmsi'], '123456789')
                    self.assertIn('TEST PORT', satellite.details.get('1.0', 'end'))
                    self.assertIn('RECEPTION-TIME ASSUMPTION', satellite.details.get('1.0', 'end'))
                    satellite.show_latest()
                    root.update()
                    self.assertTrue(app.map.find_withtag('satellite-latest'))
                    satellite.show_image.set(False)
                    satellite.redraw()
                    root.update()
                    self.assertEqual(errors, [])
            finally:
                app.close()
