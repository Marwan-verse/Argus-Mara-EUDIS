"""Dark vessels: a satellite radar contact where AIS is silent, for a vessel's gap or with no AIS at all."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from argus import assemble
from argus.assemble import assess_vessel, build_assessments, context_from_scenario
from argus.countdown import step
from argus.detectors import dark_vessel
from argus.levels import assess

ROOT = Path(__file__).resolve().parents[1]
START = (53.00, -5.55)
GAP = (20 * 60, 60 * 60)  # AIS silent from minute 20 until minute 60
PASS_T = 40 * 60


def truth(minutes=90, sog=12.0, cog=0.0):
    """Where the vessel really is: one fix a minute on a straight course."""
    fixes = []
    for minute in range(minutes):
        lat, lon = step(*START, cog, sog * minute / 60)
        fixes.append({"t": minute * 60, "lat": round(lat, 5), "lon": round(lon, 5), "sog_kn": sog, "cog_deg": cog})
    return fixes


def with_gap(fixes, gap=GAP):
    return [fix for fix in fixes if not gap[0] <= fix["t"] < gap[1]]


def contact(t=PASS_T, offset_nm=0.0, bearing=90.0, length=200, **fields):
    """A simulated radar contact at the true position at ``t``, moved ``offset_nm`` on ``bearing``."""
    fix = next(fix for fix in truth() if fix["t"] == t)
    lat, lon = step(fix["lat"], fix["lon"], bearing, offset_nm)
    return {"t": t, "lat": lat, "lon": lon, "length_m": length, "source": "sentinel1",
            "scene_id": "S1A_TEST_SIMULATED", "matched_mmsi": None, "label": "simulated", **fields}


def vessel(fixes, length=190, label="fictional"):
    return {"mmsi": 999000066, "name": "TEST SKUA", "ship_type": 70, "ais_class": "A", "ais_length_m": length,
            "track": fixes, "label": label}


def detect(fixes, detections, now=None, **kwargs):
    return dark_vessel.detect(vessel(fixes, **kwargs), {"now": now, "detections": detections})


class GapTests(unittest.TestCase):
    def test_a_contact_inside_the_gap_on_the_vessel_track_is_a_dark_finding(self):
        [finding] = detect(with_gap(truth()), [contact()])
        self.assertEqual(finding["detector"], "dark_vessel")
        self.assertEqual(finding["t"], PASS_T)
        self.assertEqual(finding["obs"], {"ais_gap_min": 41, "dark_radar_contact": True, "radar_length_m": 200,
                                          "length_mismatch_pct": 5.3})
        self.assertEqual(finding["related"]["gap_start_t"], 19 * 60)
        self.assertEqual(finding["related"]["gap_end_t"], 60 * 60)
        self.assertEqual(finding["related"]["radar_contact"]["scene_id"], "S1A_TEST_SIMULATED")
        self.assertIn("when Sentinel-1 radar scene S1A_TEST_SIMULATED saw a contact", finding["reasons"][0])
        self.assertIn("identity unconfirmed", finding["reasons"][0])
        self.assertIn("AIS came back after 41 min", finding["reasons"][1])
        codes = {f["code"] for f in assess(finding["obs"])["factors"] if f["points"]}
        self.assertEqual(codes, {"I1", "I3"})

    def test_a_length_mismatch_adds_rule_i4(self):
        [finding] = detect(with_gap(truth()), [contact(length=260)])
        self.assertEqual(finding["obs"]["length_mismatch_pct"], 36.8)
        factors = {f["code"] for f in assess(finding["obs"])["factors"]}
        self.assertIn("I4", factors)

    def test_while_still_dark_the_gap_runs_to_now(self):
        [finding] = detect(with_gap(truth()), [contact()], now=50 * 60)
        self.assertEqual(finding["obs"]["ais_gap_min"], 31)
        self.assertIsNone(finding["related"]["gap_end_t"])
        self.assertIn("AIS still silent", finding["reasons"][1])

    def test_nothing_before_the_pass_is_seen(self):
        self.assertEqual(detect(with_gap(truth()), [contact()], now=PASS_T - 60), [])

    def test_a_contact_the_vessel_could_not_reach_gives_nothing(self):
        self.assertEqual(detect(with_gap(truth()), [contact(offset_nm=15)]), [])

    def test_the_returning_fix_must_be_reachable_from_the_contact(self):
        fixes = with_gap(truth())
        for fix in fixes:
            if fix["t"] >= GAP[1]:
                fix["lon"] -= 0.6  # AIS comes back about 21 nm west
        self.assertEqual(detect(fixes, [contact()]), [])
        self.assertEqual(len(detect(fixes, [contact()], now=GAP[1] - 60)), 1)  # before it came back

    def test_a_vessel_transmitting_at_the_pass_is_not_dark(self):
        self.assertEqual(detect(truth(), [contact()]), [])
        short_gap = with_gap(truth(), (35 * 60, 42 * 60))  # seven minutes: below the 10 min gap rule
        self.assertEqual(detect(short_gap, [contact()]), [])

    def test_a_contact_space_matched_to_ais_gives_nothing(self):
        self.assertEqual(detect(with_gap(truth()), [contact(matched_mmsi=999000099)]), [])

    def test_a_real_contact_never_pairs_with_fictional_ais(self):
        self.assertEqual(detect(with_gap(truth()), [contact(label="real")]), [])
        self.assertEqual(len(detect(with_gap(truth()), [contact(label="real")], label="real")), 1)

    def test_old_contacts_are_no_longer_looked_at(self):
        fixes = with_gap(truth(minutes=8 * 60))
        self.assertEqual(len(detect(fixes, [contact()], now=6 * 3600)), 1)
        self.assertEqual(detect(fixes, [contact()], now=PASS_T + 6 * 3600 + 60), [])


class RadarOnlyTests(unittest.TestCase):
    def test_a_contact_no_ais_vessel_could_reach_becomes_a_pseudo_vessel(self):
        far = contact(offset_nm=40)
        [pseudo] = dark_vessel.radar_only_vessels([vessel(with_gap(truth()))], [far, contact()])
        self.assertTrue(pseudo["radar_only"])
        self.assertEqual(pseudo["mmsi"], f"RADAR-S1A_TEST_SIMULATED-{PASS_T}")
        self.assertEqual(pseudo["track"], [{"t": PASS_T, "lat": far["lat"], "lon": far["lon"]}])
        self.assertEqual(pseudo["label"], "simulated")
        [finding] = dark_vessel.detect(pseudo, {})
        self.assertEqual(finding["obs"], {"no_ais": True, "dark_radar_contact": True, "radar_length_m": 200})
        self.assertIn("identity unknown", finding["reasons"][0])

    def test_transmitting_matched_or_future_contacts_are_explained(self):
        vessels = [vessel(truth())]
        self.assertEqual(dark_vessel.radar_only_vessels(vessels, [contact()]), [])
        self.assertEqual(dark_vessel.radar_only_vessels([], [contact(matched_mmsi=1)]), [])
        self.assertEqual(dark_vessel.radar_only_vessels([], [contact()], now=PASS_T - 60), [])

    def test_a_dark_contact_near_a_line_is_scored_with_the_line(self):
        line = {"id": "test-line", "name": "Test line", "kind": "power", "label": "simulated",
                "path": [[53.40, -6.0], [53.40, -5.0]], "anchor_reachable": None, "min_depth_m": None}
        near = {**contact(), "lat": 53.39, "lon": -5.5}
        [pseudo] = dark_vessel.radar_only_vessels([], [near])
        result = assess_vessel(pseudo, {"now": PASS_T, "cables": [line], "detections": [near]})
        self.assertEqual(sorted(f["detector"] for f in result["findings"]), ["cable_risk", "dark_vessel"])
        self.assertEqual(result["cable_id"], "test-line")
        self.assertEqual(result["assessment"]["level"], "medium")  # identity and proximity, no behaviour
        self.assertEqual(result["assessment"]["groups"]["I"], 3)


class ExerciseTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        self.vessel = self.scenario["vessels"][0]

    def test_registered_but_held_from_the_exercise_until_the_team_agrees(self):
        self.assertIn(dark_vessel.detect, assemble.DETECTORS)
        self.assertIn("dark_vessel", assemble.HELD_FROM_SCENARIO)
        at_radar = assess_vessel(self.vessel, context_from_scenario(self.scenario, 60 * 60))
        self.assertEqual(at_radar["assessment"]["level"], "none")
        self.assertNotIn("dark_vessel", [f["detector"] for f in at_radar["findings"]])

    def test_released_it_finds_the_exercise_radar_contact_in_the_ais_gap(self):
        with patch.object(assemble, "HELD_FROM_SCENARIO", ()):
            at_radar = assess_vessel(self.vessel, context_from_scenario(self.scenario, 60 * 60))
        [finding] = [f for f in at_radar["findings"] if f["detector"] == "dark_vessel"]
        self.assertEqual(finding["t"], 2400)
        self.assertEqual(finding["obs"]["ais_gap_min"], 21)
        self.assertEqual(at_radar["assessment"]["level"], "medium")  # D63: before the T+90 alert

    def test_assessments_list_radar_only_contacts_when_released(self):
        scenario = copy.deepcopy(self.scenario)
        far = {**scenario["detections"][0], "t": 3000, "lat": 52.5, "lon": -5.9, "scene_id": "S1A_FAR_SIMULATED"}
        scenario["detections"].append(far)
        held = build_assessments(scenario)
        self.assertEqual([item["mmsi"] for item in held["vessels"]], [999000001])
        with patch.object(assemble, "HELD_FROM_SCENARIO", ()):
            released = build_assessments(scenario)
        self.assertEqual([item["mmsi"] for item in released["vessels"]], [999000001, "RADAR-S1A_FAR_SIMULATED-3000"])
        self.assertIn("dark_vessel", released["detectors"])


if __name__ == "__main__":
    unittest.main()
