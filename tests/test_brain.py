"""The rule alert must be reproducible and must never cite future observations."""

import copy
import json
import unittest
from pathlib import Path

from argus.brain import build_alerts

ROOT = Path(__file__).resolve().parents[1]


class BrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))

    def test_committed_alert_matches_observed_fix_and_rule_output(self):
        generated = build_alerts(self.scenario)
        committed = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, committed)
        alert = generated["alerts"][0]
        self.assertEqual(alert["t"], 5400)
        self.assertEqual(alert["observations"]["alert_fix_t"], alert["t"])
        self.assertEqual(alert["observations"]["gap_end_t"], 3000)
        self.assertIn("cause unknown", alert["reasons"][0])
        self.assertNotIn("identity mismatch", " ".join(alert["reasons"]).lower())

    def test_future_track_and_radar_are_not_required_for_alert(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["vessels"][0]["track"] = [fix for fix in scenario["vessels"][0]["track"] if fix["t"] <= 5400]
        scenario["detections"].append({"t": 9000, "lat": 53.3, "lon": -5.4,
                                        "source": "simulated", "scene_id": "future",
                                        "matched_mmsi": None, "label": "simulated"})
        self.assertEqual(build_alerts(scenario)["alerts"][0], build_alerts(self.scenario)["alerts"][0])

    def test_no_observed_large_slowdown_means_no_alert(self):
        scenario = copy.deepcopy(self.scenario)
        for fix in scenario["vessels"][0]["track"]:
            if fix["t"] >= 5400:
                fix["sog_kn"] = 11.0
        self.assertEqual(build_alerts(scenario)["alerts"], [])

    def test_no_projected_cable_crossing_means_no_alert(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["cables"][0]["path"] = [[55.0, -6.0], [55.0, -4.0]]
        self.assertEqual(build_alerts(scenario)["alerts"], [])


if __name__ == "__main__":
    unittest.main()
