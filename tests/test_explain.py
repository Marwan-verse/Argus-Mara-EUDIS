"""Why this level: groups, rules, line choice, detectors, small-vessel rule and data labels."""
import json
import unittest
from pathlib import Path

from argus.brain_board import build_board
from argus.explain import explain

ROOT = Path(__file__).resolve().parents[1]


class ExplainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.by_id = {item["id"]: item for item in build_board(scenario, alerts)}

    def tags(self, why):
        return [tag for tag, _text in why["labels"]]

    def test_five_groups_add_up_to_the_basis(self):
        why = explain(self.by_id["SIM-46"])
        self.assertEqual([group["key"] for group in why["groups"]], ["B", "I", "P", "A", "C"])
        self.assertEqual(sum(group["points"] for group in why["groups"]), self.by_id["SIM-46"]["assessment"]["score"])
        behaviour = why["groups"][0]
        self.assertEqual((behaviour["cap"], behaviour["points"]), (6, 2))
        self.assertEqual(behaviour["factors"][0]["code"], "B11")
        self.assertEqual(why["groups"][4]["factors"], [])  # context: nothing observed
        self.assertIsNone(why["groups"][2]["cap"])

    def test_rules_keep_level_caps_and_drop_detector_and_small_vessel_notes(self):
        why = explain(self.by_id["SIM-46"])
        self.assertEqual(len(why["rules"]), 1)
        self.assertTrue(why["rules"][0].startswith("Capped at Medium"))
        self.assertEqual(explain(self.by_id["SIM-40"])["rules"], [])

    def test_detector_findings_are_grouped_with_their_label(self):
        why = explain(self.by_id["SIM-46"])
        spoofing = next(finding for finding in why["findings"] if finding["detector"] == "ais_spoofing")
        self.assertEqual((spoofing["title"], spoofing["label"]), ("AIS spoofing check", "SIMULATED"))
        self.assertEqual(len(spoofing["reasons"]), 4)
        self.assertIn("inside land", spoofing["reasons"][3])
        exercise = explain(self.by_id["A1"])["findings"]
        self.assertEqual([(f["title"], f["label"]) for f in exercise], [("Cable approach rule v1", "EXERCISE")])

    def test_small_vessel_rule_capped_or_lifted(self):
        capped = explain(self.by_id["SIM-40"])["small_vessel"]
        self.assertTrue(capped["capped"])
        self.assertIn("class B, declared length 11 m", capped["reason"])
        lifted = explain(self.by_id["SIM-46"])["small_vessel"]
        self.assertFalse(lifted["capped"])
        self.assertIn("duplicate identity", lifted["outcome"])
        self.assertIsNone(explain(self.by_id["SIM-44"])["small_vessel"])

    def test_threatened_line_names_the_choice_and_the_others(self):
        line = explain(self.by_id["SIM-44"])["line"]
        self.assertEqual((line["id"], line["where"]), ("dublin-holyhead", "reached in 20 min"))
        self.assertEqual(line["others"], [{"id": "ic2", "name": "Gas interconnector IC2",
                                           "where": "reached in 5 h 00 min"}])
        self.assertEqual(explain(self.by_id["SIM-01"])["line"]["where"], "inside its 1 nm corridor")

    def test_data_labels_show_simulated_real_and_assumptions(self):
        tags = self.tags(explain(self.by_id["SIM-46"]))
        self.assertEqual(tags, ["SIMULATED", "ILLUSTRATIVE", "ASSUMPTION", "ASSUMPTION", "REAL", "RULE OUTCOME"])
        self.assertEqual(self.tags(explain(self.by_id["A1"])), ["EXERCISE", "ILLUSTRATIVE", "RULE OUTCOME"])
        self.assertNotIn("REAL", self.tags(explain(self.by_id["SIM-47"])))  # glitch: no on-land check reason


if __name__ == "__main__":
    unittest.main()
