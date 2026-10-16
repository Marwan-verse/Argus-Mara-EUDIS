"""Native report submission, incident display and SOC delivery failure behavior."""
from pathlib import Path
import tempfile
import time
import threading
import tkinter as tk
from unittest.mock import Mock, patch
import unittest

import customtkinter as ctk

from argus.collab_client import ClientError
from argus.report_ai import AI_LABEL, check_all, draft_report, strip_label, template_draft
from argus.vessel_reports import make_report
from desktop_reports import open_report, board_snapshot
from run_gui import ArgusApp, load_demo
from tests.test_collab_desktop import FakeClient
from tests.test_report_ai import KEY, FakeTensorX
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
        # Never a paid call from a test, even on a computer with a TensorX key in its keychain.
        no_key = patch("argus.report_ai.get_key", return_value="")
        no_key.start()
        self.addCleanup(no_key.stop)

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
        dialog.reason.delete("1.0", "end")
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

    def test_form_opens_prefilled_and_analyst_can_replace_every_word(self):
        with patch("argus.report_ai.json_http") as network:
            dialog = open_report(self.app, VESSEL)
            self.assertIn("Vessel and source:", dialog.reason.get("1.0", "end"))
            self.assertIn("SOC analyst review:", dialog.reason.get("1.0", "end"))
            self.assertEqual(dialog.generation["method"], "prefill")
            network.assert_not_called()
        dialog.reason.delete("1.0", "end")
        dialog.reason.insert("1.0", "Analyst replacement after reviewing the contact.")
        dialog.category.set("Other")
        dialog.submit()
        saved = self.app.vessel_reports.entries[0]["report"]
        self.assertEqual(saved["reason"], "Analyst replacement after reviewing the contact.")
        self.assertEqual(saved["category"], "Other")

    def settle(self, dialog):
        for _ in range(1500):  # up to about 15 s: a PDF render is slower under a loaded test run
            self.root.update()
            if not dialog.busy:
                return
            time.sleep(.01)
        self.fail("the report tool did not finish")

    def notes(self, dialog):
        return dialog.notes.get("1.0", "end")

    def test_review_window_report_drafts_from_brain_evidence_and_checks_it(self):
        board = self.app.alert_board
        board.open("SIM-41", reveal=False)
        board.dialog.report_button.invoke()
        dialog = self.app.report_dialog
        self.assertEqual(dialog.pack["kind"], "board")
        self.assertEqual(dialog.pack["item_id"], "SIM-41")
        self.assertEqual(dialog.pack["level"]["level"], board.by_id["SIM-41"]["assessment"]["level"])
        dialog.reason.insert("1.0", "My own first note.")
        dialog.draft_button.invoke()
        self.assertTrue(dialog.busy)
        self.settle(dialog)
        text = dialog.reason.get("1.0", "end")
        self.assertIn("SEA LARK", text)
        self.assertIn("Template draft from system data · reviewed by analyst", text)
        self.assertEqual(dialog.category.get(), dialog.pack["category"])
        self.assertIn("no AI used", self.notes(dialog))
        self.assertEqual(dialog.generation["method"], "template")
        dialog.check_button.invoke()
        self.settle(dialog)
        self.assertIn("Report is consistent with system data", self.notes(dialog))
        dialog.reason.insert("1.0", "Brain level Critical. ")
        dialog.check_button.invoke()
        self.settle(dialog)
        self.assertIn("Level differs from Brain", self.notes(dialog))
        dialog.reason.edit_undo()
        dialog.reason.edit_undo()
        self.assertIn("My own first note.", dialog.reason.get("1.0", "end"))
        dialog.reason.delete("1.0", "end")
        dialog.reason.insert("1.0", text.strip())
        dialog.submit()
        self.root.update()
        self.assertEqual(self.app.vessel_reports.entries[0]["report"]["reason"], text.strip())
        self.assertEqual(set(self.app.vessel_reports.entries[0]["report"]), {"id", "vessel", "category", "reason",
                                                                             "created_utc"})

    def test_with_a_key_the_window_shows_the_ai_draft_and_both_check_layers(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        board = self.app.alert_board
        board.open("SIM-41", reveal=False)
        board.dialog.report_button.invoke()
        dialog = self.app.report_dialog
        template = template_draft(dialog.pack)
        draft = FakeTensorX({"draft": strip_label(template["text"]), "category": dialog.pack["category"],
                             "evidence": template["evidence"]})
        check = FakeTensorX({"findings": []})
        root = Path(folder.name)
        with patch("argus.report_ai.get_key", return_value=KEY), \
                patch("desktop_reports.draft_report", lambda pack: draft_report(pack, root=root, transport=draft)), \
                patch("desktop_reports.check_all",
                      lambda pack, text, category: check_all(pack, text, category, root=root, transport=check)):
            dialog.draft_button.invoke()
            self.settle(dialog)
            self.assertTrue(dialog.reason.get("1.0", "end").strip().endswith(AI_LABEL))
            self.assertIn("AI-assisted draft by qwen/qwen3.8-flash-next", self.notes(dialog))
            self.assertEqual(dialog.generation["method"], "ai")
            dialog.check_button.invoke()
            self.settle(dialog)
        notes = self.notes(dialog)
        self.assertIn("CODE CHECK (exact, no AI)\nReport is consistent with system data.", notes)
        self.assertIn("AI CHECK (meaning, qwen/qwen3.8-flash-next)", notes)
        self.assertIn("No meaning problems found.", notes)
        self.assertEqual((len(draft.chats), len(check.chats)), (1, 1))
        dialog.close()

    def test_report_without_brain_item_drafts_with_placeholders_offline(self):
        dialog = open_report(self.app, VESSEL)
        self.assertEqual(dialog.pack["kind"], "minimal")
        dialog.draft_button.invoke()
        self.settle(dialog)
        self.assertIn("No Brain assessment", dialog.reason.get("1.0", "end"))
        dialog.check_button.invoke()
        self.settle(dialog)
        self.assertIn("Placeholder left in the text", self.notes(dialog))
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        target = Path(folder.name) / "report.pdf"
        with patch("desktop_reports.filedialog.asksaveasfilename", return_value="") as cancelled:
            dialog.pdf_button.invoke()
        cancelled.assert_called_once()
        self.assertFalse(dialog.busy)
        with patch("desktop_reports.filedialog.asksaveasfilename", return_value=str(target)):
            dialog.pdf_button.invoke()
            self.settle(dialog)
        self.assertIn("PDF saved", self.notes(dialog))
        self.assertTrue(target.read_bytes().startswith(b"%PDF"))
        self.assertEqual(self.app.vessel_reports.entries, [])  # saving a PDF sends nothing
        dialog.close()

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
        self.app.soc.open()
        self.root.update()
        chat = self.app.soc.chat.get('1.0', 'end')
        self.assertIn('Vessel report', chat)
        self.assertIn("A colleague's separate observation.", chat)
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

    def test_background_poll_queues_one_report_without_requiring_another_click(self):
        client = self.connect()
        release = threading.Event()
        def delayed_poll():
            release.wait(3)
            return []
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert('1.0', 'A report submitted during the background poll.')
        self.app.soc.task(delayed_poll, self.app.soc.receive, background=True)
        try:
            dialog.submit()
            dialog.submit()  # A second click cannot add another send.
            self.assertTrue(dialog.pending)
            self.assertIn('queued', dialog.problem.cget('text'))
            client.send.assert_not_called()
        finally:
            release.set()
        self.pump()
        client.send.assert_called_once()
        self.assertEqual(len(self.app.vessel_reports.entries), 1)

    def test_session_change_during_queued_poll_cannot_send_to_another_team(self):
        client = self.connect()
        release = threading.Event()
        def change_room():
            release.wait(3)
            client.room['room_id'] = 'another-team'
            return []
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert('1.0', 'Only for the original team.')
        self.app.soc.task(change_room, self.app.soc.receive, background=True)
        dialog.submit()
        release.set()
        self.pump()
        client.send.assert_not_called()
        self.assertEqual(self.app.vessel_reports.entries, [])
        self.assertIn('session changed', dialog.problem.cget('text'))
        self.assertIn('Only for the original team', dialog.reason.get('1.0', 'end'))

    def test_full_queue_preserves_draft_and_restores_submit_controls(self):
        client = self.connect()
        dialog = open_report(self.app, VESSEL)
        dialog.reason.insert('1.0', 'A draft that must stay editable.')
        self.app.soc.pending = 8
        try:
            dialog.submit()
            self.assertFalse(dialog.pending)
            self.assertEqual(str(dialog.submit_button.cget('state')), 'normal')
            self.assertIn('draft that must stay editable', dialog.reason.get('1.0', 'end'))
            client.send.assert_not_called()
        finally:
            self.app.soc.pending = 0
