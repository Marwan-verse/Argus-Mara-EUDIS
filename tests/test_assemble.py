"""Findings merge into one levels assessment; small vessels are capped unless evidence says otherwise."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from argus import assemble
from argus.alert_board import exercise_item
from argus.assemble import assess_vessel, context_from_scenario, merge_observations, relevance
from argus.brain import build_alerts

ROOT = Path(__file__).resolve().parents[1]
CABLE = {"cable_id": "cable-test"}


def finding(detector, obs, related=None):
    return {"detector": detector, "mmsi": 999000099, "t": 600, "position": [53.3, -5.5], "strength": 0.8,
            "reasons": [f"{detector} test reason"], "related": related or {}, "label": "simulated", "obs": obs}


def fixed(*findings):
    """A detector that returns the given findings, for tests."""
    return lambda vessel, context: list(findings)


def vessel(ship_type=None, ais_class="A", length=None):
    return {"mmsi": 999000099, "name": "TEST VESSEL", "ship_type": ship_type, "ais_class": ais_class,
            "ais_length_m": length, "destination": None, "nav_status": None, "track": [], "label": "simulated"}


# Drag pattern inside the corridor of a power line: Critical for a large ship.
DRAG = finding("cable_risk", {"speed_drop_pct": 41, "course_change_deg": 26, "ais_gap_min": 20, "in_corridor": True,
                              "asset_class": "power"}, CABLE)


class MergeTests(unittest.TestCase):
    def test_invented_findings_give_expected_level(self):
        findings = [
            finding("cable_risk", {"speed_drop_pct": 24, "course_change_deg": 30, "eta_min": 61,
                                   "asset_class": "telecom"}, CABLE),
            finding("dark_vessel", {"ais_gap_min": 20, "dark_radar_contact": True, "eta_min": 5}),
        ]
        result = assess_vessel(vessel(80, "A", 180), {}, [fixed(*findings)])
        self.assertEqual(result["observations"]["eta_min"], 61)  # ETA from a non-cable finding is ignored
        self.assertEqual(result["assessment"]["level"], "high")
        self.assertEqual(result["assessment"]["basis"], "B4 I3 P3 A1 C0 = 11")
        self.assertEqual(len(result["findings"]), 2)

    def test_merge_rules(self):
        obs = merge_observations([
            finding("a", {"speed_drop_pct": 10, "spoof_signs": False, "eta_min": 90, "distance_nm": 2,
                          "asset_class": "telecom"}, CABLE),
            finding("b", {"speed_drop_pct": 30, "spoof_signs": True, "eta_min": 40, "distance_nm": 6,
                          "asset_class": "gas"}, {"cable_id": "other"}),
            finding("c", {"speed_drop_pct": None, "asset_class": "power", "distance_nm": 0.5}),
        ])
        self.assertEqual(obs["speed_drop_pct"], 30)
        self.assertIs(obs["spoof_signs"], True)
        self.assertEqual(obs["eta_min"], 40)
        self.assertEqual(obs["distance_nm"], 6)  # same cable as the soonest ETA
        self.assertEqual(obs["asset_class"], "gas")
        self.assertIs(merge_observations([finding("a", {"no_ais": False})])["no_ais"], False)

    def test_cable_keys_come_from_one_cable(self):
        findings = [
            finding("cable_risk", {"speed_drop_pct": 24, "course_change_deg": 30}),
            finding("cable_risk", {"eta_min": 20, "asset_class": "telecom"}, {"cable_id": "telecom-1"}),
            finding("cable_risk", {"eta_min": 300, "asset_class": "gas"}, {"cable_id": "gas-1"}),
        ]
        result = assess_vessel(vessel(80, "A", 180), {}, [fixed(*findings)])
        self.assertEqual(result["observations"]["eta_min"], 20)
        self.assertEqual(result["observations"]["asset_class"], "telecom")
        self.assertEqual(result["assessment"]["basis"], "B4 I0 P4 A1 C0 = 9")
        self.assertEqual(result["cable_id"], "telecom-1")

    def test_corridor_is_more_urgent_than_a_sooner_eta(self):
        result = assess_vessel(vessel(80, "A", 180), {}, [fixed(
            finding("a", {"eta_min": 10, "distance_nm": 1, "asset_class": "telecom"}, {"cable_id": "telecom-1"}),
            finding("b", {"in_corridor": True, "distance_nm": 0.4, "asset_class": "power"}, {"cable_id": "power-1"}),
        )])
        self.assertEqual(result["cable_id"], "power-1")
        self.assertEqual(result["observations"]["asset_class"], "power")
        self.assertNotIn("eta_min", result["observations"])
        tie = assess_vessel(vessel(80, "A", 180), {}, [fixed(
            finding("a", {"eta_min": 30, "asset_class": "telecom"}, {"cable_id": "telecom-1"}),
            finding("b", {"eta_min": 30, "asset_class": "gas"}, {"cable_id": "gas-1"}),
        )])
        self.assertEqual(tie["cable_id"], "gas-1")

    def test_findings_about_one_cable_combine(self):
        obs = merge_observations([
            finding("a", {"eta_min": 61, "asset_class": "telecom"}, {"cable_id": "telecom-1"}),
            finding("b", {"in_corridor": True}, {"cable_id": "telecom-1"}),
            finding("c", {"in_corridor": True}),  # no cable named: ignored
        ])
        self.assertEqual(obs, {"in_corridor": True, "eta_min": 61, "asset_class": "telecom"})
        self.assertNotIn("in_corridor", merge_observations([finding("c", {"in_corridor": True})]))


class RelevanceTests(unittest.TestCase):
    def test_small_vessel_rules(self):
        self.assertTrue(relevance(vessel(None, "B", 18))["small"])
        self.assertTrue(relevance(vessel(37, "A", 45))["small"])
        self.assertTrue(relevance(vessel(52, "A", 32))["small"])
        self.assertFalse(relevance(vessel(None, "B", 30))["small"])
        self.assertFalse(relevance(vessel(70, "A", 20))["small"])
        self.assertFalse(relevance(vessel(37, "A", 50))["small"])
        self.assertFalse(relevance(vessel(37, "B", None))["small"])  # unknown length is not small
        self.assertFalse(relevance(vessel(37, "B", 0))["small"])

    def test_small_vessel_is_capped_at_low(self):
        boat = vessel(37, "B", 12)
        uncapped = assess_vessel(vessel(70, "A", 190), {}, [fixed(DRAG)])
        self.assertEqual(uncapped["assessment"]["level"], "critical")
        result = assess_vessel(boat, {}, [fixed(DRAG)])
        self.assertEqual(result["assessment"]["level"], "low")
        self.assertEqual(result["assessment"]["rank"], 1)
        self.assertEqual(result["assessment"]["score"], uncapped["assessment"]["score"])
        self.assertIn("Capped at Low: small vessel", result["assessment"]["notes"][-1])
        self.assertEqual(result["relevance"]["cap"], "low")
        self.assertEqual(len(result["findings"]), 1)  # kept, not dropped

    def test_small_vessel_with_length_evidence_is_not_capped(self):
        radar = finding("space_identity", {"radar_length_m": 40, "length_mismatch_pct": 233})
        result = assess_vessel(vessel(37, "B", 12), {}, [fixed(DRAG, radar)])
        self.assertEqual(result["assessment"]["level"], "critical")
        self.assertIsNone(result["relevance"]["cap"])
        self.assertIn("Small-vessel cap not applied: radar measured 40 m", result["assessment"]["notes"][-1])
        shorter = finding("space_identity", {"radar_length_m": 8, "length_mismatch_pct": 33})
        self.assertEqual(assess_vessel(vessel(37, "B", 12), {}, [fixed(DRAG, shorter)])["assessment"]["level"],
                         "low")

    def test_confirmed_facts_lift_the_cap(self):
        for flag, text in (("fault_confirmed", "line fault"), ("ignored_instruction", "did not comply")):
            fact = finding("operator", {flag: True, "in_corridor": True}, CABLE)
            result = assess_vessel(vessel(37, "B", 12), {}, [fixed(fact)])
            self.assertEqual(result["assessment"]["level"], "critical", flag)
            self.assertIsNone(result["relevance"]["cap"])
            self.assertIn(text, result["assessment"]["notes"][-1])
            self.assertNotIn("Capped at Low", " ".join(result["assessment"]["notes"]))

    def test_spoofing_lifts_the_cap(self):
        jump = finding("spoof_check", {"spoof_signs": True})
        result = assess_vessel(vessel(37, "B", 12), {}, [fixed(DRAG, jump)])
        self.assertIsNone(result["relevance"]["cap"])

    def test_fishing_vessel_working_the_line_is_not_capped(self):
        trawl = finding("cable_risk", {"passes_6h": 4, "in_corridor": True, "asset_vulnerable": True,
                                       "asset_class": "cluster"}, CABLE)
        result = assess_vessel(vessel(30, "A", 24), {}, [fixed(trawl)])
        self.assertEqual(result["assessment"]["level"], "high")
        self.assertIn("fishing vessel working at the line", result["relevance"]["exception"])

    def test_fishing_vessel_without_bottom_gear_signs_is_capped(self):
        dark = finding("dark_vessel", {"ais_gap_min": 25, "slowdown_near_corridor": True, "dark_radar_contact": True,
                                       "distance_nm": 3}, CABLE)
        self.assertEqual(assess_vessel(vessel(70, "A", 24), {}, [fixed(dark)])["assessment"]["level"], "medium")
        self.assertEqual(assess_vessel(vessel(30, "A", 24), {}, [fixed(dark)])["assessment"]["level"], "low")


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))

    def test_legacy_detector_matches_alert_board_exercise_item(self):
        alert = build_alerts(self.scenario)["alerts"][0]
        expected = exercise_item(self.scenario, alert)
        result = assess_vessel(self.scenario["vessels"][0], context_from_scenario(self.scenario))
        self.assertEqual(result["assessment"], expected["assessment"])
        self.assertEqual(result["assessment"]["level"], "high")
        legacy = result["findings"][0]
        self.assertEqual(legacy["detector"], "legacy_cable_v1")
        self.assertEqual(legacy["t"], alert["t"])
        self.assertEqual(legacy["related"], {"cable_id": alert["segment_id"]})
        self.assertEqual(legacy["obs"]["radar_length_m"], 228)

    def test_legacy_detector_uses_the_cable_kind(self):
        def legacy_obs(kind):
            scenario = copy.deepcopy(self.scenario)
            scenario["cables"][0]["kind"] = kind
            result = assess_vessel(scenario["vessels"][0], context_from_scenario(scenario))
            return result["findings"][0]["obs"], result

        obs, result = legacy_obs("gas")
        self.assertEqual(obs["asset_class"], "gas")
        self.assertEqual(result["assessment"]["groups"]["A"], 2)
        self.assertEqual(result["cable_id"], "cable-irish-sea-1")
        self.assertEqual(legacy_obs("power")[0]["asset_class"], "power")
        self.assertEqual(legacy_obs("mystery")[0]["asset_class"], "telecom")
        self.assertEqual(legacy_obs("telecom")[0]["asset_class"], "telecom")

    def test_now_before_the_alert_fix_gives_no_finding(self):
        result = assess_vessel(self.scenario["vessels"][0], context_from_scenario(self.scenario, now=5340))
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["assessment"]["level"], "none")

    def test_new_detector_connects_with_one_line(self):
        def watchlist(vessel, context):
            return [finding("watchlist", {"watchlist": True})]

        with mock.patch.object(assemble, "DETECTORS", [*assemble.DETECTORS, watchlist]):
            result = assess_vessel(self.scenario["vessels"][0], context_from_scenario(self.scenario))
        self.assertEqual([f["detector"] for f in result["findings"]], ["legacy_cable_v1", "watchlist"])
        self.assertIn("C1", [factor["code"] for factor in result["assessment"]["factors"]])

    def test_cli_writes_a_separate_file_and_leaves_alerts_untouched(self):
        alerts = (ROOT / "demo/alerts.json").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "assessments.json"
            subprocess.run([sys.executable, "-m", "argus.assemble", "--output", str(output)],
                           cwd=ROOT, check=True, capture_output=True)
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["vessels"][0]["assessment"]["level"], "high")
        self.assertEqual(result["detectors"], ["legacy_cable_v1", "ais_spoofing"])
        refused = subprocess.run([sys.executable, "-m", "argus.assemble", "--output", "demo/alerts.json"],
                                 cwd=ROOT, capture_output=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual((ROOT / "demo/alerts.json").read_bytes(), alerts)


if __name__ == "__main__":
    unittest.main()
