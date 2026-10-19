"""Fleet pagination, dated evidence and history leads with fictional alerts hidden."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.satellite import atomic_json
from argus.fleet_history import analyse_history
from test_fleet_history import MMSI, rows, START
from test_satellite import fixture


class FleetHistoryDesktopTests(unittest.TestCase):
    def test_history_inventory_pages_detail_and_incident_link(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0',
                'ARGUS_UI_PREFERENCES': '', 'ARGUS_SATELLITE_AUTOSTART': '0',
                'ARGUS_SUPABASE_URL': 'https://example.supabase.co'}):
            app = ArgusApp(root, *load_demo())
            satellite = app.satellite
            satellite.workspace, _, _ = fixture(Path(temp)/'satellite')
            points = rows(5)
            for i in (1, 3):
                points[i]['lon'] = -6.4
            finding = analyse_history(MMSI, points)
            cached = {str(100000000+i): {'mmsi': str(100000000+i), 'checked_utc': None,
                                        'new_evidence_pending': True, 'checking': False, 'result': None}
                      for i in range(51)}
            cached[MMSI] = {'mmsi': MMSI, 'checked_utc': finding['checked_utc'], 'checking': False,
                            'new_evidence_pending': False, 'result': finding}
            atomic_json(satellite.workspace.fleet.index_path,
                        {'vessels': cached, 'summary': {'total_vessels': 52, 'checked_vessels': 1,
                                                      'never_checked': 51, 'review_required': 1},
                         'inventory_complete': True})
            try:
                with patch.object(satellite, 'task', side_effect=lambda function, callback: callback(function())):
                    app.open_window('satellite')
                    satellite.tabs.select(satellite.fleet_tab)
                    satellite.load_fleet('')
                    self.assertEqual(len(satellite.fleet_table.get_children()), 50)
                    self.assertIn('1/52', satellite.fleet_status.get())
                    satellite.fleet_forward()
                    self.assertEqual(len(satellite.fleet_table.get_children()), 2)
                    satellite.fleet_table.selection_set(MMSI)
                    satellite.show_history()
                    detail = satellite.fleet_details.get('1.0', 'end')
                    self.assertIn('not proof of transponder shutdown', detail)
                    self.assertIn('two places', detail)
                    satellite.fleet_previous()
                    self.assertEqual(len(satellite.fleet_table.get_children()), 50)
                    app.alert_board.show_demo_alerts.set(False)
                    app.alert_board.toggle_demo_alerts()
                    app.alert_board.refresh_history(satellite.workspace.fleet.page(only_leads=True))
                    self.assertTrue(app.alert_board.history_frame.winfo_manager())
                    self.assertIn('1 vessel histories require review', app.alert_counts_label.cget('text'))
                    entries = [link for link in app.alert_board.history_frame.links if link.kind == 'entry']
                    entries[0].invoke()
                    self.assertEqual(satellite.pending_fleet, MMSI)
                    self.assertEqual(satellite.tabs.select(), str(satellite.fleet_tab))
                    self.assertEqual(app.alert_board.visible_items(), [])
                    packet = satellite.workspace.fleet.page(only_leads=True)
                    packet['summary']['last_sync_utc'] = START.isoformat()
                    with patch('argus.fleet_history.time.time', return_value=START.timestamp()):
                        app.alert_board.refresh_history(packet)
                    with patch('argus.fleet_history.time.time', return_value=START.timestamp()+600):
                        app.alert_board.refresh_history(packet)
                        labels = app.alert_board.history_frame.texts()
                        self.assertTrue(any('Database sync: stale' in text for text in labels))
                    # Secret entry is native and masked; the key is neither sent
                    # to an AI model nor included in UI messages or fixture files.
                    with patch.dict('os.environ', {'ARGUS_SUPABASE_URL': ''}), \
                            patch('tkinter.simpledialog.askstring') as unconfigured_prompt, \
                            patch('argus.supabase_ais.http_rpc') as unconfigured_request:
                        satellite.connect_database()
                        unconfigured_prompt.assert_not_called()
                        unconfigured_request.assert_not_called()
                    secret = 'sb_secret_'+'x'*24
                    with patch('tkinter.simpledialog.askstring', return_value=secret) as prompt, \
                            patch('argus.supabase_ais.http_rpc', return_value={'positions': 2}) as remote, \
                            patch('argus.supabase_ais.save_key') as save:
                        satellite.connect_database()
                        self.assertEqual(prompt.call_args.kwargs['show'], '•')
                        save.assert_called_once_with(secret)
                        self.assertTrue((satellite.workspace.root/'database.link').exists())
                        self.assertEqual(remote.call_args.args[2], secret)
            finally:
                app.close()
            self.assertEqual(errors, [])
