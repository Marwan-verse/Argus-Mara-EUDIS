"""Real Tk lifecycle and controls for the four investigation lab tabs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk
from run_gui import ArgusApp, load_demo
from desktop_investigation import snapshot_sources


class DesktopInvestigationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.environment = patch.dict("os.environ", {"ARGUS_AIS_AUTOCONNECT": "0", "ARGUS_UI_PREFERENCES": ""})
        self.environment.start()
        self.app = ArgusApp(self.root, *load_demo())
        self.app.ais_tracker.cache_path = None
        self.original = deepcopy(self.app.scenario)
        self.app.open_window("investigation")
        self.lab = self.app.investigation_lab

    def tearDown(self):
        self.app.close()
        self.environment.stop()
        self.assertEqual(self.errors, [])

    def finish(self):
        deadline = time.monotonic() + 20
        while self.lab.future is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.assertIsNone(self.lab.future, "Local calculation did not finish")

    def test_four_tabs_real_calculations_and_protected_exports(self):
        self.assertEqual(len(self.lab.tabs.tabs()), 4)
        self.assertTrue(self.lab.events)
        self.lab.event_table.selection_set("0")
        self.lab.select_event()
        self.lab.center_event()
        self.assertIn("Received AIS position", self.lab.event_detail.get("1.0", "end"))
        self.lab.review_pairs()
        self.finish()
        self.assertEqual({r["kind"] for r in self.lab.pairs}, {"Parallel travel", "Possible rendezvous"})
        self.lab.speed.set("20")
        self.lab.course.set("90")
        self.assertTrue(self.lab.advance(300))
        self.assertEqual(self.lab.lab.now-self.lab.lab.start, 300)
        self.lab.ais.set(False)
        self.assertTrue(self.lab.advance(900))
        self.assertIn("AIS unavailable", self.lab.challenge_detail.get("1.0", "end"))
        self.lab.run_evaluation()
        self.finish()
        self.assertEqual(len(self.lab.result["rows"]), 5)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)/"evaluation.json"
            with patch("desktop_investigation.filedialog.asksaveasfilename", return_value=str(destination)):
                self.lab.export(self.lab.result, destination.name)
            self.assertEqual(json.loads(destination.read_text())["dataset_sha256"], self.lab.result["dataset_sha256"])
        protected = Path(__file__).resolve().parents[1]/"demo/scenario.json"
        before = protected.read_bytes()
        with patch("desktop_investigation.filedialog.asksaveasfilename", return_value=str(protected)):
            self.lab.export({}, "not-allowed.json")
        self.assertIn("protected", self.lab.status.get())
        self.assertEqual(protected.read_bytes(), before)
        self.assertEqual(self.app.scenario, self.original)

    def test_moving_panel_preserves_branch_and_stops_old_timers(self):
        self.lab.advance(300)
        now = self.lab.lab.now
        old = self.lab
        self.app._move_panel("investigation", "bottom")
        self.lab = self.app.investigation_lab
        self.assertTrue(old.closed)
        self.assertEqual(self.lab.lab.now, now)
        self.lab.play()
        self.assertIsNotNone(self.lab.play_job)
        self.app._close_panel("investigation")
        self.assertTrue(self.lab.closed)
        self.assertIsNone(self.lab.play_job)

    def test_snapshot_excludes_future_exercise_fixes(self):
        replay, _, observations = snapshot_sources(self.app)
        from argus.investigation import epoch
        end = epoch(self.app.scenario["t0_utc"]) + self.app.position_s
        self.assertTrue(all(f["t"] <= end for v in replay for f in v["track"]))
        self.assertTrue(all(epoch(o["acquired_utc"]) <= end for o in observations if o["source"].startswith("Exercise")))

    def test_scaled_panel_stays_within_the_chart(self):
        self.root.geometry("1100x720")
        self.root.deiconify()
        self.root.update()
        self.app._position_console_panel()
        self.root.update()
        host = self.app.chart_host
        panel = self.app.floating_panel
        self.assertLessEqual(panel.winfo_y() + panel.winfo_height(), host.winfo_height())


if __name__ == "__main__":
    unittest.main()
