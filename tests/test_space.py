import copy
import itertools
import json
import math
import unittest
from pathlib import Path

from argus.space import analyse, assignment, length_check, position_at, project, timestamp


ROOT = Path(__file__).resolve().parents[1]


def vessel(mmsi, lon, length=180):
    return {"mmsi": mmsi, "ais_length_m": length,
            "track": [{"t": 0, "lat": 53, "lon": lon, "sog_kn": 0, "cog_deg": 0}]}


class SpaceTests(unittest.TestCase):
    def test_demo_gap_keeps_identity_tentative(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text())
        original = copy.deepcopy(scenario)
        result = analyse(scenario)["detections"][0]
        self.assertEqual(scenario, original)
        self.assertTrue(result["dark_candidate"])
        self.assertIsNone(result["matched_mmsi"])
        candidate = result["custody_candidates"][0]
        self.assertEqual(candidate["mmsi"], 999000001)
        self.assertLess(candidate["projection_error_km"], 0.1)
        self.assertTrue(candidate["length_check"]["mismatch"])
        self.assertFalse(candidate["length_check"]["exceeds_threshold_after_uncertainty"])

    def test_length_threshold_and_unknown_values(self):
        self.assertFalse(length_check(225, 180)["mismatch"])
        self.assertTrue(length_check(228, 180)["mismatch"])
        self.assertFalse(length_check(250, 200)["mismatch"])
        self.assertTrue(length_check(251, 200)["mismatch"])
        for radar, ais in [(None, 180), (228, 0), (23, 180)]:
            self.assertIsNone(length_check(radar, ais)["mismatch"])
        with self.assertRaises(ValueError):
            length_check(math.nan, 180)

    def test_interpolation_staleness_and_no_future_only_fix(self):
        track = [{"t": 0, "lat": 53, "lon": -6, "sog_kn": 12, "cog_deg": 0},
                 {"t": 600, "lat": 53.02, "lon": -6}]
        self.assertAlmostEqual(position_at(track, 300)["lat"], 53.01)
        self.assertIsNone(position_at(track, -1))
        self.assertIsNone(position_at(track[:1], 301))
        track[1]["t"] = 1800
        self.assertIsNone(position_at(track, 600))
        self.assertIsNotNone(position_at(track[:1], 300))
        self.assertIsNone(project({**track[0], "sog_kn": 102.3}, 30))

    def test_interpolation_crosses_dateline_short_way(self):
        points = [{"t": 0, "lat": 0, "lon": 179}, {"t": 60, "lat": 0, "lon": -179}]
        self.assertAlmostEqual(abs(position_at(points, 30)["lon"]), 180)

    def test_one_to_one_global_match_beats_greedy(self):
        # First detection can match either vessel; second can match only vessel 1.
        scenario = {"vessels": [vessel(1, -6), vessel(2, -5.98)], "detections": [
            {"t": 0, "lat": 53, "lon": -5.991, "length_m": 228},
            {"t": 0, "lat": 53, "lon": -6.002, "length_m": 180}]}
        detections = analyse(scenario)["detections"]
        self.assertEqual([d["matched_mmsi"] for d in detections], [2, 1])
        self.assertTrue(detections[0]["length_check"]["mismatch"])

    def test_gate_and_separate_acquisition_times(self):
        scenario = {"vessels": [vessel(1, -6)], "detections": [
            {"t": 0, "lat": 53, "lon": -6, "scene_id": "a"},
            {"t": 0, "lat": 53, "lon": -6.001, "scene_id": "a"},
            {"t": 60, "lat": 53, "lon": -6, "scene_id": "b"},
            {"t": 60, "lat": 54, "lon": -6, "scene_id": "b"}]}
        result = analyse(scenario)["detections"]
        self.assertEqual([d["matched_mmsi"] for d in result], [1, None, 1, None])

    def test_source_reported_identity_is_reserved(self):
        scenario = {"vessels": [vessel(1, -6)], "detections": [
            {"t": 0, "lat": 53, "lon": -6, "matched_mmsi": 1, "length_m": 228},
            {"t": 0, "lat": 53, "lon": -6.001}]}
        result = analyse(scenario)["detections"]
        self.assertEqual(result[0]["association"], "source_reported")
        self.assertIsNone(result[1]["matched_mmsi"])

    def test_assignment_against_bruteforce(self):
        for costs in ([[2, 1, 4], [1, 3, 4]], [[0.6, 0.7, 3, 3], [0.2, 9, 3, 3]],
                      [[5, 5, 5], [5, 5, 5], [5, 5, 5]]):
            cols = assignment(costs)
            got = sum(row[col] for row, col in zip(costs, cols))
            expected = min(sum(row[col] for row, col in zip(costs, choice))
                           for choice in itertools.permutations(range(len(costs[0])), len(costs)))
            self.assertEqual(got, expected)

    def test_absolute_utc_tracks(self):
        when = timestamp("2026-10-07T12:00:00Z")
        track = [{"ts": "2026-10-07T13:00:00+01:00", "lat": 53, "lon": -6}]
        self.assertEqual(position_at(track, when), track[0])
        with self.assertRaises(ValueError):
            timestamp("2026-10-07T12:00:00")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            analyse({"detections": [{"t": 0, "lat": 91, "lon": 0}]})
        with self.assertRaises(ValueError):
            analyse({}, 0)
        self.assertEqual(analyse({})["detections"], [])
        unknown = analyse({"detections": [{"t": 0, "lat": 53, "lon": -6, "matched_mmsi": ""}]})
        self.assertTrue(unknown["detections"][0]["dark_candidate"])


if __name__ == "__main__":
    unittest.main()
