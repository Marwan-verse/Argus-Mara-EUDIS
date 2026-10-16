"""Global Fishing Watch radar in the native app: markers, details and the Incidents lead.

Opens a Tk window, so it runs in CI with the other GUI modules, not locally (D84).
"""
import gc
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from argus import gfw_sar
from argus.satellite_workspace import SatelliteWorkspace
from test_gfw_sar import fetched


class RadarDesktopTests(unittest.TestCase):
    def setUp(self):
        # Collect earlier tests' Tk objects here, on the main thread (see test_soc_launcher).
        gc.collect()

    def test_radar_markers_details_and_incident_review(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        from desktop_evidence_review import EvidenceReview
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.attributes('-alpha', 0)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': '',
                                          'ARGUS_SATELLITE_AUTOSTART': '0', 'GFW_API_TOKEN': ''}), \
                patch('argus.satellite_workspace.get_key', return_value=''), \
                patch('argus.gfw_sar._keyring_token', return_value=''):
            workspace_root = Path(temp)/'satellite'
            result, *_ = fetched(workspace_root)
            app = ArgusApp(root, *load_demo())
            satellite, board = app.satellite, app.alert_board
            try:
                satellite.watch_at = float('inf')  # this test drives the watch packet itself
                deadline = time.monotonic()+5
                while satellite.watch_future is not None and time.monotonic() < deadline:
                    root.update()
                satellite.workspace = SatelliteWorkspace(workspace_root)
                app.open_window('satellite')
                satellite.apply_radar({**gfw_sar.map_index(workspace_root), 'configured': True})
                self.assertIn('1 without AIS (leads)', satellite.radar_status.get())
                lead = next(d for d in result['detections'] if gfw_sar.is_lead(d))
                satellite.show_radar_point({'id': lead['id']})
                root.update()
                self.assertTrue(app.map.find_withtag('radar-contact-'+lead['id']))
                details = satellite.details.get('1.0', 'end')
                self.assertIn('RADAR CONTACT WITHOUT AIS', details)
                self.assertIn('Team AIS at radar time', details)
                self.assertIn('Powered by Global Fishing Watch', details)
                self.assertIn('Powered by Global Fishing Watch', app.map_attribution_label.cget('text'))
                satellite.show_radar.set(False)
                satellite.redraw()
                self.assertFalse(app.map.find_withtag('radar-contact-'+lead['id']))
                satellite.show_radar.set(True)
                board.refresh_evidence(satellite.workspace.comparison_index())
                entries = [link for link in board.evidence_frame.links if link.kind == 'entry']
                card = next(link for link in entries if 'Radar contact without AIS' in link.text)
                self.assertEqual(card.action, 'Show radar contact on map')
                self.assertIn('radar detections (Global Fishing Watch)', board.evidence_status)
                satellite.selected_radar = None
                card.invoke()
                root.update()
                self.assertEqual(satellite.selected_radar, lead['id'])
                form = EvidenceReview(board, next(r for r in board.evidence_leads if r.get('radar')))
                form.outcome.set('Insufficient evidence')
                form.reason.insert('1.0', 'Synthetic test analyst outcome for a radar contact.')
                form.save()
                deadline = time.monotonic()+5
                while form.window.winfo_exists() and time.monotonic() < deadline:
                    root.update()
                self.assertFalse(form.window.winfo_exists())
                radar_lead = next(r for r in board.evidence_leads if r.get('radar'))
                self.assertEqual(radar_lead['review_status'], 'insufficient_evidence')
                root.update()
                self.assertEqual(errors, [])
            finally:
                app.close()
                # Also collect this test's own Tk objects now, on the main thread. If a later
                # test's background job collects them, a Tk __del__ waits forever on the
                # destroyed interpreter and Python cannot exit (Windows 3.11 CI timed out).
                gc.collect()


if __name__ == '__main__':
    unittest.main()
