"""The alert board scored through argus.assemble keeps its levels and shows the small-vessel rule."""

import json
import unittest
from pathlib import Path

from argus.alert_board import build_board as original_board
from argus.brain_board import build_board, update

ROOT = Path(__file__).resolve().parents[1]


class BrainBoardTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        self.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        self.items = build_board(self.scenario, self.alerts)
        self.by_id = {item["id"]: item for item in self.items}

    def test_large_vessels_keep_their_levels(self):
        original = {item["id"]: item["assessment"] for item in original_board(self.scenario, self.alerts)}
        self.assertEqual(len(self.items), len(original) + 5)
        for identifier, assessment in original.items():
            item = self.by_id[identifier]
            if not item["relevance"]["small"]:
                self.assertEqual(item["assessment"], assessment, identifier)
        self.assertEqual(self.by_id["A1"]["detectors"], ["legacy_cable_v1"])
        self.assertEqual(self.by_id["A1"]["assessment"]["level"], "high")

    def test_small_craft_are_capped_or_explained(self):
        yacht, sea_lark, pilot = self.by_id["SIM-40"], self.by_id["SIM-41"], self.by_id["SIM-42"]
        self.assertEqual(yacht["assessment"]["level"], "low")
        self.assertIn("Capped at Low: small vessel", yacht["assessment"]["notes"][-1])
        self.assertEqual(pilot["assessment"]["level"], "low")
        self.assertEqual(sea_lark["assessment"]["level"], "high")
        self.assertIn("radar measured 62 m", sea_lark["assessment"]["notes"][-1])
        trawler = self.by_id["SIM-04"]
        self.assertEqual(trawler["assessment"]["level"], "high")
        self.assertIn("fishing vessel working at the line", trawler["assessment"]["notes"][-1])

    def test_line_fault_under_a_small_craft_stays_critical(self):
        yacht = self.by_id["SIM-43"]
        self.assertEqual(yacht["assessment"]["level"], "critical")
        self.assertIn("a line fault is reported", yacht["assessment"]["notes"][-1])
        self.assertNotIn("Capped at Low", " ".join(yacht["assessment"]["notes"]))

    def test_two_lines_are_scored_for_the_more_urgent_one(self):
        ship = self.by_id["SIM-44"]
        self.assertEqual(ship["detectors"], ["alert_board_simulated", "alert_board_simulated"])
        self.assertEqual(ship["cable_id"], "dublin-holyhead")
        self.assertEqual(ship["observations"]["asset_class"], "telecom")
        self.assertEqual(ship["observations"]["eta_min"], 20)
        self.assertEqual(ship["assessment"]["basis"], "B4 I0 P4 A1 C0 = 9")
        self.assertEqual(ship["assessment"]["level"], "high")

    def test_countdown_update_keeps_the_small_vessel_rule(self):
        changed = update(self.items, 20 * 60)
        self.assertIn("SIM-41", changed)  # 45 min ETA falls under 30 min
        self.assertEqual(self.by_id["SIM-41"]["assessment"]["level"], "critical")
        self.assertEqual(self.by_id["SIM-40"]["assessment"]["level"], "low")


if __name__ == "__main__":
    unittest.main()
