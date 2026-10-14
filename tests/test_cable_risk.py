"""Cable risk detector: behaviour and proximity per line from the recent track, without needing an AIS gap."""

import json
import math
import time
import unittest
from pathlib import Path

from argus import assemble
from argus.assemble import assess_vessel, context_from_scenario, legacy_cable_v1
from argus.countdown import step
from argus.detectors import cable_risk
from argus.levels import assess

ROOT = Path(__file__).resolve().parents[1]
LAT = 53.40  # the test lines run east-west along this latitude


def line(identifier="test-line", lat=LAT, west=-6.0, east=-5.0, kind="power", depth=60, reachable=None):
    path = [[lat, west], [lat, (west + east) / 2], [lat, east]]
    return {"id": identifier, "name": f"Test {identifier}", "kind": kind, "label": "simulated", "path": path,
            "anchor_reachable": reachable if reachable is not None else [path[0], path[-1]], "min_depth_m": depth}


def south_of(nm, lon=-5.5, lat=LAT):
    return lat - nm / 60, lon


def track(start, legs, status=None, interval=60):
    """Fixes once a minute from ``start``; legs are (minutes, sog kn, cog deg or cog(minute))."""
    lat, lon = start
    fixes, t = [], 0
    for minutes, sog, cog in legs:
        for minute in range(minutes):
            course = cog(minute) if callable(cog) else cog
            fixes.append({"t": t, "lat": lat, "lon": lon, "sog_kn": sog, "cog_deg": course % 360,
                          **({"nav_status": status} if status else {})})
            lat, lon = step(lat, lon, course, sog * interval / 3600)
            t += interval
    return fixes


def vessel(fixes, ship_type=70, length=180, nav_status=None):
    return {"mmsi": 999000088, "name": "TEST GANNET", "ship_type": ship_type, "ais_class": "A",
            "ais_length_m": length, "destination": None, "nav_status": nav_status, "track": fixes,
            "label": "simulated"}


def yaw(minute):
    """Course swinging +/-15 degrees about north: an unsteady track."""
    return 15 * math.sin(minute / 2)


def detect(fixes, cables, now=None, **kwargs):
    return cable_risk.detect(vessel(fixes, **kwargs), {"now": now, "cables": cables})


BEHAVIOUR = {"speed_drop_pct", "course_change_deg", "dragging_at_anchor", "loiter_hours", "passes_6h",
             "slow_over_corridor_min", "anchored_near_cable", "fishing_near_corridor", "slowdown_near_corridor"}


class AnchorDragWithoutGap(unittest.TestCase):
    def setUp(self):
        # 60 min at 12 kn heading north, then 30 min at 9 kn yawing: no AIS gap anywhere.
        self.fixes = track(south_of(17), [(60, 12.0, 0), (30, 9.0, yaw)])
        self.cable = line()

    def test_slowdown_and_yaw_over_the_section_give_b1_and_an_eta(self):
        [finding] = detect(self.fixes, [self.cable])
        obs = finding["obs"]
        self.assertGreaterEqual(obs["speed_drop_pct"], 20)
        self.assertGreaterEqual(obs["course_change_deg"], 20)
        self.assertIsNotNone(obs["eta_min"])
        self.assertTrue(obs["method_possible"])
        self.assertEqual(finding["related"]["cable_id"], "test-line")
        self.assertEqual(finding["label"], "simulated")
        self.assertIn("cause unknown", finding["reasons"][0])
        self.assertIn("rule: ≥20% and ≥20° while under way", " ".join(finding["reasons"]))
        codes = {factor["code"] for factor in assess(obs)["factors"]}
        self.assertIn("B1", codes)

    def test_the_legacy_rule_misses_it_and_the_level_rises(self):
        scenario_vessel = vessel(self.fixes)
        context = {"now": None, "cables": [self.cable], "detections": [], "assets": []}
        self.assertEqual(legacy_cable_v1(scenario_vessel, context), [])  # no AIS gap
        result = assess_vessel(scenario_vessel, context)
        self.assertEqual(result["cable_id"], "test-line")
        self.assertIn(result["assessment"]["level"], ("high", "critical"))

    def test_eta_counts_from_now_while_approaching(self):
        early = detect(self.fixes[:75], [self.cable])[0]["obs"]
        late = detect(self.fixes, [self.cable])[0]["obs"]
        self.assertGreater(early["eta_min"], late["eta_min"])


class AnchorDragOnASteadyCourse(unittest.TestCase):
    """Public reporting on Eagle S gives only "12 to 9 kn": a steady course must not hide the drag."""

    def obs_and_level(self, slow_minutes, cable=None):
        fixes = track(south_of(17), [(60, 12.0, 0), (slow_minutes, 9.0, 0)])
        [finding] = detect(fixes, [cable or line()])
        return finding, assess(finding["obs"])

    def test_steady_drag_approaching_the_section_is_b1_and_high(self):
        finding, level = self.obs_and_level(20)  # about 2 nm south of the line, still approaching
        obs = finding["obs"]
        self.assertTrue(obs["drag_signature"])
        self.assertNotIn("course_change_deg", obs)
        self.assertIn("B1", {factor["code"] for factor in level["factors"]})
        self.assertLessEqual(obs["eta_min"], 30)
        self.assertEqual(level["level"], "high")
        self.assertIn("no turn needed", " ".join(finding["reasons"]))

    def test_still_dragging_after_crossing_is_at_least_medium(self):
        finding, level = self.obs_and_level(50)  # crossed, now about 2.5 nm north
        self.assertTrue(finding["obs"]["drag_signature"])
        self.assertGreater(finding["obs"]["distance_nm"], 2)
        self.assertIn(level["level"], ("medium", "high", "critical"))

    def test_a_short_slowdown_is_not_a_drag(self):
        finding, _ = self.obs_and_level(10)
        self.assertNotIn("drag_signature", finding["obs"])
        self.assertTrue(finding["obs"]["slowdown_near_corridor"])

    def test_slowing_to_enter_dublin_port_near_a_cable_landing_is_not_a_drag(self):
        cable = {"id": "dublin-holyhead", "name": "Dublin–Holyhead (illustrative)", "kind": "telecom",
                 "path": [[53.35, -6.05], [53.36, -5.70], [53.37, -5.35]]}
        fixes = track((53.34, -5.80), [(45, 12.0, 270), (20, 8.0, 270)])  # inbound towards Dublin Bay
        [finding] = cable_risk.detect(vessel(fixes), {"cables": [cable]})
        self.assertNotIn("drag_signature", finding["obs"])
        self.assertIn("Not scored as an anchor drag", " ".join(finding["reasons"]))


class AnchorReachableSection(unittest.TestCase):
    def test_line_deeper_than_the_cutoff_is_not_a_feasible_method(self):
        fixes = track(south_of(17), [(60, 12.0, 0), (30, 9.0, yaw)])
        [finding] = detect(fixes, [line(depth=400)])
        self.assertIs(finding["obs"]["method_possible"], False)
        self.assertIn("deeper than the assumed 250 m", finding["reasons"][-1])
        self.assertEqual(assess(finding["obs"])["level"], "medium")

    def test_a_crossing_outside_the_reachable_section_does_not_count_as_one(self):
        """Audit fix: the projected crossing must lie on the section, not just on a cable that has one."""
        cable = line(reachable=[[LAT, -5.3], [LAT, -5.0]])
        fixes = track(south_of(10, lon=-5.9), [(30, 12.0, 0)])
        [finding] = detect(fixes, [cable])
        self.assertIs(finding["obs"]["method_possible"], False)
        self.assertEqual(finding["related"]["section"], "too deep for an anchor")
        self.assertIn("outside its anchor-reachable section", finding["reasons"][-1])

    def test_unknown_depth_is_an_assumed_reachable_line(self):
        cable = {**line(), "min_depth_m": None, "anchor_reachable": None}
        fixes = track(south_of(3), [(20, 12.0, 0)])
        [finding] = cable_risk.detect(vessel(fixes), {"cables": [cable]})
        self.assertTrue(finding["obs"]["method_possible"])
        self.assertIn("assumed anchor-reachable", finding["reasons"][-1])


class LineBehaviour(unittest.TestCase):
    def test_loitering_an_hour_beside_the_line_is_b4(self):
        fixes = track(south_of(1.5), [(80, 1.0, lambda m: m * 9)])
        fixes = track(south_of(6.5), [(30, 10.0, 0)]) + [{**fix, "t": fix["t"] + 1800} for fix in fixes]  # arrives, then circles
        obs = detect(fixes, [line()])[0]["obs"]
        self.assertGreaterEqual(obs["loiter_hours"], 1.0)
        self.assertNotIn("speed_drop_pct", obs)  # circling slowly is loitering, not an anchor drag under way
        self.assertIn("B4", {factor["code"] for factor in assess(obs)["factors"]})

    def test_three_passes_in_six_hours_is_b5(self):
        fixes = track(south_of(1), [(15, 8.0, 0), (15, 8.0, 180), (15, 8.0, 0), (15, 8.0, 180)])
        obs = detect(fixes[:46], [line()])[0]["obs"]
        self.assertEqual(obs["passes_6h"], 3)
        self.assertIn("B5", {factor["code"] for factor in assess(obs)["factors"]})

    def test_moving_while_reporting_at_anchor_is_b2(self):
        fixes = track(south_of(0.8), [(20, 1.5, 90)], status="at anchor")
        obs = detect(fixes, [line()])[0]["obs"]
        self.assertTrue(obs["dragging_at_anchor"])
        self.assertEqual(obs["sog_kn"], 1.5)
        self.assertIn("B2", {factor["code"] for factor in assess(obs)["factors"]})

    def test_anchored_within_a_mile_is_b7(self):
        fixes = track(south_of(0.7), [(40, 0.1, 0)], status="at anchor")
        obs = detect(fixes, [line()])[0]["obs"]
        self.assertTrue(obs["anchored_near_cable"])
        self.assertNotIn("loiter_hours", obs)  # at anchor is B7, not loitering

    def test_slow_over_the_corridor_is_b6(self):
        fixes = track(south_of(0.9, lon=-5.8), [(20, 5.0, 90)])
        obs = detect(fixes, [line()])[0]["obs"]
        self.assertGreaterEqual(obs["slow_over_corridor_min"], 10)

    def test_trawling_speed_near_the_line_is_b10_for_fishing_vessels_only(self):
        fixes = track(south_of(1.5, lon=-5.9), [(40, 3.5, 90)])
        self.assertTrue(detect(fixes, [line()], ship_type=30)[0]["obs"]["fishing_near_corridor"])
        self.assertNotIn("fishing_near_corridor", detect(fixes, [line()])[0]["obs"])

    def test_fast_straight_transit_across_the_line_has_no_behaviour(self):
        fixes = track(south_of(8), [(40, 18.0, 0)])
        for now in (fixes[20]["t"], fixes[-1]["t"]):
            [finding] = detect(fixes, [line()], now=now)
            self.assertFalse(BEHAVIOUR & set(finding["obs"]), finding["obs"])
            self.assertIn("no behaviour cue", finding["reasons"][0])
            self.assertEqual(assess(finding["obs"])["level"], "none")

    def test_far_from_every_line_gives_no_finding(self):
        fixes = track(south_of(30), [(60, 12.0, 90), (30, 4.0, yaw)])
        self.assertEqual(detect(fixes, [line(), line("other", lat=LAT + 0.5)]), [])


class SeveralLines(unittest.TestCase):
    def test_one_finding_per_line_and_the_assembler_takes_the_most_urgent(self):
        near, far = line("near", kind="telecom"), line("far", lat=LAT + 0.12, kind="gas")
        fixes = track(south_of(17), [(60, 12.0, 0), (25, 9.0, yaw)])
        findings = detect(fixes, [far, near])
        self.assertEqual({f["related"]["cable_id"] for f in findings}, {"near", "far"})
        result = assess_vessel(vessel(fixes), {"cables": [far, near]}, [cable_risk.detect])
        self.assertEqual(result["cable_id"], "near")
        etas = {f["related"]["cable_id"]: f["obs"]["eta_min"] for f in findings}
        self.assertEqual(result["observations"]["eta_min"], etas["near"])
        self.assertEqual(result["observations"]["asset_class"], "telecom")

    def test_a_deep_line_in_the_corridor_ranks_below_a_reachable_one_ahead(self):
        deep = line("deep", depth=400)
        ahead = line("ahead", lat=LAT + 0.05)
        fixes = track(south_of(0.5), [(30, 4.0, 0)])
        result = assess_vessel(vessel(fixes), {"now": fixes[2]["t"], "cables": [deep, ahead]}, [cable_risk.detect])
        self.assertEqual(result["cable_id"], "ahead")
        self.assertTrue(result["observations"]["method_possible"])

    def test_three_hours_on_five_lines_is_fast(self):
        fixes = track(south_of(40), [(120, 12.0, 0), (60, 9.0, yaw)])
        cables = [line(f"line-{index}", lat=LAT + index * 0.05) for index in range(5)]
        started = time.perf_counter()
        findings = detect(fixes, cables)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(len(findings), 5)


class FastSkip(unittest.TestCase):
    """The bounding-box skip and the lazy speed/course are speed-ups only: findings never change."""

    def test_out_of_reach_skips_only_far_vessels_and_never_dark_ones(self):
        far = track(south_of(40), [(30, 6.0, 90)])
        self.assertTrue(cable_risk.out_of_reach(far[-1], line(), far[-1]["t"]))
        near = track(south_of(3), [(30, 6.0, 90)])
        self.assertFalse(cable_risk.out_of_reach(near[-1], line(), near[-1]["t"]))
        fast = track(south_of(40), [(5, 18.0, 0)])  # far, but could cross within the 3 h horizon
        self.assertFalse(cable_risk.out_of_reach(fast[-1], line(), fast[-1]["t"]))
        self.assertFalse(cable_risk.out_of_reach(far[-1], line(), far[-1]["t"] + 3600))  # dark for an hour

    def test_skipping_changes_no_finding(self):
        import random
        from unittest.mock import patch
        rng = random.Random(5)
        cables = [line(), line("north", lat=LAT + 0.4, kind="gas"), line("short", west=-5.6, east=-5.4)]
        for _ in range(60):
            start = (LAT + rng.uniform(-1.2, 1.2), rng.uniform(-6.8, -4.2))
            legs = [(rng.randint(20, 90), rng.uniform(4, 18), rng.uniform(0, 360)),
                    (rng.randint(5, 60), rng.uniform(2, 12), rng.uniform(0, 360))]
            fixes = track(start, legs)
            for now in (fixes[-1]["t"], fixes[-1]["t"] + rng.choice([0, 900, 2400])):
                fast = detect(fixes, cables, now=now)
                with patch.object(cable_risk, "out_of_reach", return_value=False):
                    self.assertEqual(fast, detect(fixes, cables, now=now))


class Exercise(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        self.vessel = self.scenario["vessels"][0]

    def test_detector_is_registered(self):
        self.assertIn(cable_risk.detect, assemble.DETECTORS)

    def test_exercise_is_still_high_at_the_alert_and_critical_near_the_section(self):
        at_alert = assess_vessel(self.vessel, context_from_scenario(self.scenario, 5400))
        self.assertEqual(at_alert["assessment"]["level"], "high")
        near = assess_vessel(self.vessel, context_from_scenario(self.scenario, 135 * 60))
        self.assertEqual(near["assessment"]["level"], "critical")
        self.assertLessEqual(near["observations"]["eta_min"], 30)


if __name__ == "__main__":
    unittest.main()
