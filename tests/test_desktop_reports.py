"""Native report submission, incident display and SOC delivery failure behavior."""
import time
import tkinter as tk
from unittest.mock import Mock, patch
import unittest

import customtkinter as ctk

from argus.collab_client import ClientError
from argus.vessel_reports import make_report
from desktop_reports import open_report, board_snapshot
from run_gui import ArgusApp, load_demo
from tests.test_collab_desktop import FakeClient
from tests.test_vessel_reports import VESSEL


class DesktopReportTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        with patch.dict("os.environ", {"ARGUS_AIS_AUTOCONNECT": "0", "ARGUS_UI_PREFERENCES": ""}):
            self.app = ArgusApp(self.root, *load_demo())
        self.app.ais_tracker.cache_path = None

    def tearDown(self):
        self.app.close()
        self.assertEqual(self.errors, [])

    def pump(self):
        for _ in range(25):
            self.root.update()
            self.app.soc.tick()
            time.sleep(.01)

    def connect(self):
        client = FakeClient()
        client.room["room_id"] = "test-room"
        client.send = Mock()
        self.app.soc_client = self.app.soc.client = client
        self.app.soc_online = True
        return client

    def test_empty_reason_blocked_other_saved_and_survives_replay_reset(self):
        dialog = open_report(self.app, VESSEL)
        dialog.category.set("Other")
        dialog.submit()
        self.assertEqual(self.app.vessel_reports.entries, [])
        self.assertIn("Reason requires", dialog.problem.cget("text"))
        dialog.reason.insert("1.0", "Unusual activity for the duty officer to check.")
        dialog.submit()
        self.root.update()
        self.assertEqual(len(self.app.vessel_reports.grouped()), 1)
        self.assertTrue(self.app.alert_board.reports_frame.winfo_manager())
        self.assertIn("1 reported vessels", self.app.alert_counts_label.cget("text"))
        self.app.alert_board.restart()
        self.assertEqual(len(self.app.vessel_reports.entries), 1)
        self.assertIsNone(self.app.approved)

    def test_review_dialog_reports_selected_simulated_contact(self):
        board = self.app.alert_board
        board.open("SIM-40", reveal=False)
        board.dialog.report_button.invoke()
        self.assertEqual(self.app.report_dialog.vessel, board_snapshot(board.by_id["SIM-40"]))

    def test_soc_success_and_peer_receive_create_incidents_without_echo(self):
        client = self.connect()
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert("1.0", "Repeated unexplained turns.")
        dialog.submit()
        self.pump()
        client.send.assert_called_once()
        self.assertEqual(client.send.call_args.args[0], "report")
        self.assertEqual(self.app.vessel_reports.entries[0]["sender"], "analyst")
        remote = make_report(VESSEL, "Other", "A colleague's separate observation.")
        self.app.soc.receive([{"kind": "report", "payload": remote, "sender": "colleague"}])
        self.app.soc.receive([{"kind": "report", "payload": remote, "sender": "colleague"}])
        self.assertEqual(len(self.app.vessel_reports.entries), 2)
        self.assertEqual(len(self.app.vessel_reports.grouped()), 1)
        client.send.assert_called_once()
        self.assertIsNone(self.app.approved)

    def test_failed_send_preserves_draft_and_manual_retry_uses_same_id(self):
        client = self.connect()
        client.send.side_effect = ClientError("Network interrupted")
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert("1.0", "Please check this vessel.")
        dialog.submit()
        self.pump()
        self.assertEqual(self.app.vessel_reports.entries, [])
        self.assertIn("Network interrupted", dialog.problem.cget("text"))
        self.assertIn("Please check", dialog.reason.get("1.0", "end"))
        first_id = client.send.call_args.args[1]["id"]
        self.app.soc_online = True
        client.send.side_effect = None
        dialog.submit()
        self.pump()
        self.assertEqual(client.send.call_args.args[1]["id"], first_id)
        self.assertEqual(len(self.app.vessel_reports.entries), 1)

    def test_soc_unverified_or_permission_denied_does_not_send(self):
        client = self.connect()
        client.cipher.verified = False
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert("1.0", "Written reason.")
        dialog.submit()
        self.assertIn("verify every teammate", dialog.problem.cget("text"))
        client.cipher.verified = True
        client.room["permissions"] = ["chat"]
        dialog.submit()
        self.assertIn("every teammate", dialog.problem.cget("text"))
        client.send.assert_not_called()
        self.assertEqual(self.app.vessel_reports.entries, [])

    def test_changed_soc_session_requires_a_new_form(self):
        client = self.connect()
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert("1.0", "Reason intended for the previous team.")
        client.room["room_id"] = "another-room"
        dialog.submit()
        self.assertIn("session changed", dialog.problem.cget("text"))
        client.send.assert_not_called()
