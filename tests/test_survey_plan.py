"""Seabed search planner: the worked example, the drag corridor and its GeoJSON, without network access."""

import json
import math
import unittest
from datetime import datetime
from pathlib import Path

from argus import survey_plan

ROOT = Path(__file__).resolve().parents[1]
CABLE = [(53.30, -5.30), (53.50, -5.30)]  # a north-south line


def drag_track(phases=((12, 60), (8, 90), (12, 30)), lat=53.40, lon=-5.80, t=1_792_150_000):
    """A ship heading east that slows to drag across the line and speeds up again."""
    fixes = []
    for knots, minutes in phases:
        for _ in range(minutes):
            lon += knots * 1852 / 60 / (math.cos(math.radians(lat)) * survey_plan.M_PER_DEG)
            t += 60
            fixes.append({"t": t, "lat": lat, "lon": lon, "sog_kn": knots})
    return fixes


class EstimateTests(unittest.TestCase):
    def rows(self, depth):
        return {row["id"]: row for row in survey_plan.estimate(10, 600, depth)}

    def test_worked_example_from_the_research(self):
        self.assertAlmostEqual(survey_plan.detection_radius_m(10, 5), 56.8, delta=0.1)
        self.assertEqual(survey_plan.half_width_m(50), 300)
        rows = self.rows(20)
        expected = {"usv": (112, 7, 77, 10.7), "auv": (113, 7, 77, 14.1), "drone": (89, 8, 88, 3.2)}
        for key, (spacing, lines, line_km, hours) in expected.items():
            with self.subTest(platform=key):
                row = rows[key]
                self.assertEqual((round(row["spacing_m"]), row["lines"], round(row["line_km"]), round(row["hours"], 1)),
                                 (spacing, lines, line_km, hours))
                self.assertEqual(row["status"], "ok")
        self.assertEqual(rows["drone"]["sorties"], 10)

    def test_deep_water_limits_the_drone(self):
        drone = self.rows(40)["drone"]
        self.assertEqual((round(drone["spacing_m"]), drone["lines"], round(drone["line_km"]), round(drone["hours"], 1)),
                         (28, 23, 253, 9.2))
        self.assertEqual(drone["status"], "impractical")
        drone = self.rows(60)["drone"]
        self.assertEqual(drone["status"], "cannot detect")
        self.assertIsNone(drone["lines"])


class PlanTests(unittest.TestCase):
    def test_drag_corridor_runs_from_slowdown_to_recovery(self):
        result = survey_plan.plan(drag_track(), CABLE, depth_m=50, subject="TEST")
        self.assertTrue(result["start_reason"].startswith("Slowdown from 12 to 8 kn at "))
        self.assertEqual(result["width_m"], 600)
        self.assertEqual(result["depth_source"], "operator entry")
        first, second = result["priorities"]
        self.assertTrue(first["text"].startswith("Cable crossing"))
        self.assertAlmostEqual(first["lon"], -5.30, places=4)
        self.assertTrue(second["text"].startswith("Speed recovered to 12 kn"))
        self.assertGreater(second["lon"], first["lon"])
        self.assertAlmostEqual(result["length_km"], 22.35, delta=0.2)  # 90 min at 8 kn + one minute at 12 kn
        self.assertEqual(len(result["lines"]), 7)
        self.assertTrue(all(len(line) == len(result["axis"]) for line in result["lines"]))
        self.assertEqual(first["box"]["lines"], 7)
        self.assertEqual(result["label"], "assumption")

    def test_gradual_slowdown_of_the_exercise_vessel_is_found(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        alert = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"][0]
        vessel = next(v for v in scenario["vessels"] if v["mmsi"] == alert["mmsi"])
        cable = next(c for c in scenario["cables"] if c["id"] == alert["segment_id"])
        offset = datetime.fromisoformat(scenario["t0_utc"].replace("Z", "+00:00")).timestamp()
        track = [{**fix, "t": fix["t"] + offset} for fix in vessel["track"]]
        result = survey_plan.plan(track, cable["path"], depth_m=cable["min_depth_m"])
        self.assertTrue(result["start_reason"].startswith("Slowdown from 12 to 9 kn"))
        self.assertTrue(result["priorities"][0]["text"].startswith("Cable crossing"))
        early = [fix for fix in track if fix["t"] <= alert["t"] + offset]
        with self.assertRaisesRegex(ValueError, "No cable crossing yet"):
            survey_plan.plan(early, cable["path"])

    def test_a_track_without_speeds_uses_what_is_shown(self):
        result = survey_plan.plan([(53.40, -5.33), (53.40, -5.31)], CABLE)
        self.assertEqual(result["start_reason"], "Speed history unavailable: the corridor covers the shown track.")
        self.assertEqual(result["depth_source"], "assumed (route depth unknown)")
        self.assertEqual(result["depth_m"], survey_plan.DEFAULT_DEPTH_M)
        self.assertTrue(result["priorities"][0]["text"].startswith("Nearest point of the line"))

    def test_a_single_fix_near_the_line_gets_a_one_km_box(self):
        result = survey_plan.plan([(53.40, -5.305)], CABLE, depth_m=30)
        self.assertEqual(result["length_km"], 1.0)
        self.assertEqual(len(result["axis"]), 2)

    def test_bad_inputs_are_refused(self):
        with self.assertRaises(ValueError):
            survey_plan.plan(drag_track(), CABLE, depth_m=0)
        with self.assertRaises(ValueError):
            survey_plan.plan([], CABLE)
        with self.assertRaisesRegex(ValueError, "No cable route"):
            survey_plan.plan(drag_track(), [])

    def test_geojson_is_lon_lat_and_labelled(self):
        result = survey_plan.plan(drag_track(), CABLE, depth_m=50, subject="TEST")
        collection = survey_plan.to_geojson(result)
        json.dumps(collection, allow_nan=False)
        kinds = [feature["properties"]["kind"] for feature in collection["features"]]
        self.assertEqual(kinds.count("survey_line"), 7)
        self.assertEqual(kinds[:2], ["corridor", "track_axis"])
        self.assertEqual(kinds.count("priority"), 2)
        ring = collection["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertTrue(all(-6 < lon < -4 and 53 < lat < 54 for lon, lat in ring))
        self.assertEqual({feature["properties"]["label"] for feature in collection["features"]}, {"assumption"})


if __name__ == "__main__":
    unittest.main()
