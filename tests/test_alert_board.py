"""The simulated board is labelled, sorted by severity and counts ETAs down."""
import json
import unittest
from collections import Counter
from pathlib import Path

from argus.alert_board import LINES, build_board, line_path, update
from argus.levels import RANK

ROOT = Path(__file__).resolve().parents[1]


class AlertBoardTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        self.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        self.items = build_board(self.scenario, self.alerts)

    def test_board_is_labelled_and_sorted_from_critical_to_low(self):
        ids = [item["id"] for item in self.items]
        self.assertEqual(len(ids), len(set(ids)))
        ranks = [RANK[item["assessment"]["level"]] for item in self.items]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        counts = Counter(item["assessment"]["level"] for item in self.items)
        self.assertGreaterEqual(counts["critical"], 2)
        self.assertGreaterEqual(counts["high"], 4)
        self.assertGreaterEqual(counts["medium"], 6)
        self.assertEqual(counts["none"], 0)
        self.assertEqual(max(counts, key=counts.get), "low")
        for item in self.items:
            self.assertIn(item["label"], {"simulated", "fictional"})
            self.assertTrue(item["track"])
            self.assertTrue(line_path(item["line_id"], self.scenario))

    def test_exercise_alert_uses_the_same_rules(self):
        exercise = next(item for item in self.items if item.get("exercise"))
        self.assertEqual(exercise["label"], "fictional")
        self.assertEqual(exercise["assessment"]["level"], "high")
        self.assertEqual(exercise["assessment"]["basis"], "B4 I3 P3 A1 C0 = 11")

    def test_authorised_work_is_low_and_countdowns_raise_levels(self):
        repair = next(item for item in self.items if item["name"] == "CABLE WARDEN")
        self.assertEqual(repair["assessment"]["level"], "low")
        self.assertTrue(any("authorised operation" in note for note in repair["assessment"]["notes"]))
        heron = next(item for item in self.items if item["name"] == "GREY HERON")
        self.assertEqual(heron["assessment"]["level"], "high")
        self.assertEqual(update(self.items, 60), [])
        self.assertEqual(update(self.items, 4 * 60), ["SIM-06"])
        self.assertEqual(heron["assessment"]["level"], "critical")
        self.assertLess(heron["observations"]["eta_min"], 30)

    def test_illustrative_lines_are_valid_routes(self):
        for name, asset_class, path in LINES.values():
            self.assertTrue(name)
            self.assertIn(asset_class, {"telecom", "power", "gas", "cluster", "sole_link", "transatlantic"})
            self.assertGreaterEqual(len(path), 2)


if __name__ == "__main__":
    unittest.main()
