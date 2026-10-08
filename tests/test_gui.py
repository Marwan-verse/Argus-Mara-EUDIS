"""Native replay behavior shared with the JSON exercise, without a display."""

import unittest
from html import unescape
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from run_gui import ArgusApp, fix_at, load_demo, response_status, trail_sections


class DesktopReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario, cls.alerts, _ = load_demo()
        cls.track = cls.scenario["vessels"][0]["track"]

    def test_ais_gap_has_no_invented_fix_or_joined_trail(self):
        self.assertIsNone(fix_at(self.track, 2400))
        sections = trail_sections(self.track, 3000)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][-1], (self.track[29]["lat"], self.track[29]["lon"]))

    def test_alert_uses_observed_fix_and_timely_options(self):
        alert = self.alerts["alerts"][0]
        self.assertEqual(alert["t"], 5400)
        self.assertEqual(fix_at(self.track, alert["t"])["sog_kn"], 9.1)
        statuses = {option["asset"]: response_status(option, alert["eta_earliest_s"])
                    for option in alert["options"]}
        self.assertEqual(sum(status == "In time" for status in statuses.values()), 2)

    def test_saved_decision_record_is_standalone_and_explicit(self):
        app = ArgusApp.__new__(ArgusApp)
        app.scenario = self.scenario
        app.alert = self.alerts["alerts"][0]
        app.vessel = self.scenario["vessels"][0]
        app.cable = self.scenario["cables"][0]
        app.position_s = app.alert["t"]
        app.approved = {"time": app.position_s, "asset": "VHF hail, Dublin coast radio",
                        "assumed_arrival_s": 120, "label": "simulated"}
        app.root = None
        with TemporaryDirectory() as directory:
            output = Path(directory) / "record.html"
            with patch("run_gui.filedialog.asksaveasfilename", return_value=str(output)), \
                    patch("run_gui.messagebox.showinfo"):
                app.save_record()
            record = output.read_text(encoding="utf-8")
        self.assertIn("VHF hail, Dublin coast radio", record)
        self.assertIn("No operational action was sent", record)
        self.assertIn('"eta_expected_s": 4411', unescape(record))
        self.assertIn("<!doctype html>", record)


if __name__ == "__main__":
    unittest.main()
