"""Replay stories for the dark_vessel, declared_vs_actual and stop_off_port detectors (SIM-54 to SIM-56)."""

import json
import unittest
from pathlib import Path

from argus.brain_board import DARK_GAP_S, DARK_PASS_S, build_board, rescore_story

ROOT = Path(__file__).resolve().parents[1]
NEW_DETECTORS = {"dark_vessel", "declared_vs_actual", "stop_off_port"}


class StoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.items = {item["id"]: item for item in build_board(scenario, alerts)}

    def at(self, identifier: str, minute: int) -> dict:
        item = self.items[identifier]
        rescore_story(item, minute * 60)
        return item

    def codes(self, item: dict) -> set:
        return {factor["code"] for factor in item["assessment"]["factors"] if factor["points"]}

    def test_dark_approach_rises_when_the_radar_sees_it_and_again_when_ais_returns(self):
        story = self.items["SIM-54"]["story"]
        self.assertFalse([fix for fix in story["track"] if DARK_GAP_S[0] <= fix["t"] < DARK_GAP_S[1]])
        self.assertEqual(story["detections"][0]["t"], DARK_PASS_S)
        before = self.at("SIM-54", 109)
        self.assertEqual(before["assessment"]["level"], "none")  # dark, but an AIS gap alone is not a cue
        self.assertNotIn("dark_vessel", before["detectors"])
        seen = self.at("SIM-54", 110)
        self.assertEqual(seen["assessment"]["level"], "medium")
        self.assertIn("dark_vessel", seen["detectors"])
        self.assertTrue({"I1", "I3", "P1"} <= self.codes(seen))
        back = self.at("SIM-54", 135)
        self.assertEqual(back["assessment"]["level"], "critical")
        self.assertIn("B1", self.codes(back))
        self.assertEqual(back["title"], story["title"])

    def test_wrong_way_shows_the_destination_then_the_status_contradiction(self):
        self.assertEqual(self.items["SIM-55"]["story"]["destination"], "IEDUB>GBLIV")
        turned = self.at("SIM-55", 150)
        self.assertEqual(self.codes(turned), {"C3"})
        self.assertEqual(turned["assessment"]["level"], "none")  # a declared destination alone is context
        lying = self.at("SIM-55", 170)
        self.assertTrue({"B9", "C3"} <= self.codes(lying))
        self.assertEqual(lying["assessment"]["level"], "high")
        self.assertEqual(self.at("SIM-55", 180)["assessment"]["level"], "critical")

    def test_stopped_at_sea_reaches_medium_after_half_an_hour(self):
        self.assertEqual(self.at("SIM-56", 100)["assessment"]["level"], "none")
        self.assertEqual(self.at("SIM-56", 120)["assessment"]["level"], "low")
        stopped = self.at("SIM-56", 140)
        self.assertEqual(stopped["assessment"]["level"], "medium")
        self.assertIn("stop_off_port", stopped["detectors"])
        self.assertIn("B12", self.codes(stopped))

    def test_innocent_stories_stay_quiet_with_the_new_detectors(self):
        for identifier in ("SIM-52", "SIM-53"):
            item = self.items[identifier]
            for t in range(item["story"]["start_s"], item["story"]["track"][-1]["t"] + 1, 300):
                rescore_story(item, t)
                self.assertEqual(item["assessment"]["level"], "none", (identifier, t))
                self.assertFalse(NEW_DETECTORS & set(item["detectors"]), (identifier, t))

    def test_anchoring_off_the_cluster_outside_an_anchorage_adds_b12(self):
        holding = self.at("SIM-51", 175)
        self.assertEqual(holding["assessment"]["level"], "high")
        anchored = self.at("SIM-51", 180)  # 30 min stopped, away from any port or anchorage
        self.assertIn("B12", self.codes(anchored))
        self.assertEqual(anchored["assessment"]["level"], "critical")


if __name__ == "__main__":
    unittest.main()
