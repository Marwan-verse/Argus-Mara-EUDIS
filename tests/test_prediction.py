"""Dark-vessel prediction must stay usable during AIS gaps and never invent observations."""

import json
import unittest
from pathlib import Path

from argus.countdown import nm_between
from argus.prediction import (
    DEFAULT_V_MAX_KN,
    anchor_reachable_path,
    dark_countdown,
    distance_to_path_nm,
    earliest_possible_contact_s,
    last_fix_at,
    position_at,
    predict,
    reappearance_check,
    v_max_kn,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = {"t": 0, "lat": 53.0, "lon": -5.5, "sog_kn": 12.0, "cog_deg": 0.0}


class ScenarioPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        cls.scenario = scenario
        cls.track = scenario["vessels"][0]["track"]
        cls.cable = scenario["cables"][0]

    def test_countdown_runs_through_the_ais_gap(self):
        previous = None
        for now_s in range(1800, 3000, 60):
            countdown = dark_countdown(self.track, self.cable, now_s)
            self.assertEqual(countdown["last_fix_t"], 1740)
            self.assertEqual(countdown["label"], "predicted")
            self.assertGreater(countdown["remaining_s"], 0)
            if previous is not None:
                self.assertEqual(previous - countdown["remaining_s"], 60)
            previous = countdown["remaining_s"]

    def test_gap_positions_are_predicted_and_never_interpolated(self):
        position = position_at(self.track, 2400)
        self.assertEqual(position["status"], "predicted")
        self.assertEqual(position["prediction"]["from_fix_t"], 1740)
        self.assertAlmostEqual(position["uncertainty_nm"], DEFAULT_V_MAX_KN * 660 / 3600, places=3)
        self.assertEqual(position_at(self.track, 3030)["status"], "interpolated")
        self.assertEqual(position_at(self.track, 3000)["status"], "observed")
        self.assertIsNone(position_at(self.track, -1))

    def test_simulated_radar_contact_lies_inside_the_likely_cone(self):
        radar = self.scenario["detections"][0]
        last = last_fix_at(self.track, radar["t"])
        check = reappearance_check(last, radar, v_max_kn(self.track, last["t"]))
        self.assertEqual(check["verdict"], "consistent")
        self.assertTrue(check["in_cone"])

    def test_reappearance_at_3000_is_inside_the_reachable_circle(self):
        before, after = last_fix_at(self.track, 1740), last_fix_at(self.track, 3000)
        check = reappearance_check(before, after, v_max_kn(self.track, before["t"]))
        self.assertLessEqual(check["distance_nm"], check["reachable_nm"])
        self.assertEqual(check["verdict"], "consistent")

    def test_section_matches_route_when_whole_cable_is_reachable(self):
        path = anchor_reachable_path(self.cable)
        self.assertEqual(path[0], self.cable["path"][0])
        self.assertEqual(path[-1], self.cable["path"][-1])
        self.assertEqual(len(path), len(self.cable["path"]))


class PredictionGeometryTests(unittest.TestCase):
    def test_cone_and_circle_grow_with_time(self):
        prediction = predict(FIX, 1800, 15.0)
        self.assertAlmostEqual(prediction["lat"], 53.1, places=6)
        self.assertAlmostEqual(prediction["cone"]["near_nm"], 4.2)
        self.assertAlmostEqual(prediction["cone"]["far_nm"], 6.6)
        self.assertAlmostEqual(prediction["reachable"]["radius_nm"], 7.5)
        self.assertEqual(prediction["cone"]["polygon"][0], prediction["cone"]["polygon"][-1])

    def test_zero_elapsed_is_the_fix_itself(self):
        prediction = predict(FIX, 0, 15.0)
        self.assertEqual((prediction["lat"], prediction["lon"]), (FIX["lat"], FIX["lon"]))
        self.assertEqual(prediction["reachable"]["radius_nm"], 0)

    def test_missing_speed_or_course_gives_circle_only(self):
        for change in ({"sog_kn": None}, {"sog_kn": 0.0}, {"cog_deg": None}):
            prediction = predict({**FIX, **change}, 600, 15.0)
            self.assertIsNone(prediction["cone"])
            self.assertEqual((prediction["lat"], prediction["lon"]), (FIX["lat"], FIX["lon"]))
            self.assertAlmostEqual(prediction["reachable"]["radius_nm"], 2.5)

    def test_time_must_not_run_backwards(self):
        with self.assertRaises(ValueError):
            predict(FIX, -60, 15.0)
        with self.assertRaises(ValueError):
            reappearance_check(FIX, dict(FIX), 15.0)
        with self.assertRaises(ValueError):
            earliest_possible_contact_s(FIX, 0, [[54.0, -6.0], [54.0, -5.0]])

    def test_v_max_uses_recent_fastest_speed_or_default(self):
        track = [{"t": 0, "sog_kn": 20.0}, {"t": 4000, "sog_kn": None}, {"t": 4200, "sog_kn": 14.0}]
        self.assertAlmostEqual(v_max_kn(track, 4200), 1.2 * 14.0)
        self.assertEqual(v_max_kn(track[:2], 4000), DEFAULT_V_MAX_KN)
        self.assertAlmostEqual(v_max_kn(track, 3000), 24.0)

    def test_earliest_contact_is_straight_line_at_v_max(self):
        path = [[53.5, -6.0], [53.5, -5.0]]
        distance, closest = distance_to_path_nm(FIX["lat"], FIX["lon"], path)
        self.assertAlmostEqual(distance, 30.0, places=6)
        self.assertAlmostEqual(closest[1], -5.5, places=6)
        self.assertEqual(earliest_possible_contact_s(FIX, 15.0, path), 7200)

    def test_reappearance_verdicts(self):
        one_hour_ahead = {**FIX, "t": 3600, "lat": 53.2}
        self.assertEqual(reappearance_check(FIX, one_hour_ahead, 15.0)["verdict"], "consistent")
        turned = {**FIX, "t": 3600, "lat": 53.0, "lon": -5.5 + 10 / (60 * 0.6018)}
        self.assertAlmostEqual(nm_between(FIX["lat"], FIX["lon"], turned["lat"], turned["lon"]), 10, delta=0.05)
        self.assertEqual(reappearance_check(FIX, turned, 15.0)["verdict"], "manoeuvred_while_dark")
        jumped = {**FIX, "t": 3600, "lat": 53.5}
        check = reappearance_check(FIX, jumped, 15.0)
        self.assertEqual(check["verdict"], "physically_inconsistent")
        self.assertIn("spoofing", check["note"])
        no_course = reappearance_check({**FIX, "sog_kn": 0.0}, turned, 15.0)
        self.assertIsNone(no_course["in_cone"])
        self.assertEqual(no_course["verdict"], "consistent")

    def test_partial_anchor_section_is_clipped_from_the_route(self):
        cable = {"id": "c", "path": [[53.0, -6.0], [53.0, -5.0], [53.0, -4.0]],
                 "anchor_reachable": [[53.0, -5.5], [53.0, -4.5]]}
        path = anchor_reachable_path(cable)
        self.assertEqual(len(path), 3)
        self.assertAlmostEqual(path[0][1], -5.5, places=6)
        self.assertEqual(path[1], [53.0, -5.0])
        self.assertAlmostEqual(path[2][1], -4.5, places=6)
        self.assertIsNone(dark_countdown([FIX], {**cable, "anchor_reachable": []}, 60))


if __name__ == "__main__":
    unittest.main()
