"""Editable branches must not leak truth into observed calculations."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from argus.scenario_lab import ScenarioLab

ROOT = Path(__file__).resolve().parents[1]


class ScenarioLabTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text())
        self.original = deepcopy(self.scenario)
        self.lab = ScenarioLab(self.scenario, self.scenario["vessels"][0]["mmsi"], 5400)

    def test_branch_changes_course_and_preserves_original_and_future_boundaries(self):
        self.assertTrue(all(f["t"] <= 5400 for f in self.lab.vessel["track"]))
        self.assertEqual(self.lab.scenario["detections"], [])
        before = self.lab.truth[-1]
        self.lab.configure(20, 90)
        result = self.lab.advance(300)
        self.assertEqual(self.lab.truth[-1]["lat"], before["lat"])
        self.assertGreater(self.lab.truth[-1]["lon"], before["lon"])
        self.assertEqual(result["observation_age_s"], 0)
        self.assertEqual(self.scenario, self.original)

    def test_hidden_course_changes_cannot_influence_detected_position_or_fleet(self):
        twin = ScenarioLab(self.scenario, self.scenario["vessels"][0]["mmsi"], 5400)
        self.lab.configure(25, 90, ais=False)
        twin.configure(2, 270, ais=False)
        a, b = self.lab.advance(1200), twin.advance(1200)
        self.assertNotEqual(self.lab.truth[-1], twin.truth[-1])
        self.assertEqual(a, b)
        self.assertTrue(a["dark"])
        self.assertEqual(a["last_observed"]["t"], 5400)
        self.assertEqual(a["observation_age_s"], 1200)
        self.lab.configure(25, 90, ais=True)
        returned = self.lab.advance(60)
        self.assertEqual(returned["observation_age_s"], 0)

    def test_storm_grounds_drones_and_bad_input_does_not_change_state(self):
        self.lab.configure(9, 0, wind=30)
        result = self.lab.advance()
        drones = [r for r in result["fleet"]["rows"] if r["kind"] == "drone"]
        self.assertTrue(drones)
        self.assertTrue(all(r["status"] == "unavailable" for r in drones))
        before = deepcopy(self.lab.vessel)
        for speed in (float("nan"), -1, 41):
            with self.assertRaises(ValueError):
                self.lab.configure(speed, 90)
        self.assertEqual(self.lab.vessel, before)
        self.assertEqual(self.scenario, self.original)


if __name__ == "__main__":
    unittest.main()
