"""Corrupted AIS tracks never stop the assembler: bad fixes are dropped and counted, a failing detector is recorded."""

import copy
import json
import math
import random
import unittest
from collections import Counter
from pathlib import Path

from argus import assemble
from argus.assemble import (DETECTORS, assess_vessel, build_assessments, clean_vessel, context_from_scenario,
                            describe_data_quality)
from argus.brain import build_alerts

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
CONTEXT = context_from_scenario(SCENARIO)
EXERCISE = next(vessel for vessel in SCENARIO["vessels"] if vessel["mmsi"] == 999000001)
JUNK = [None, "12", "abc", "", 91, 181, 0, -5, 102.3, 360, 1e9, float("nan"), float("inf"), True, [], {}]


def vessel(track, **fields):
    return {"mmsi": 999000099, "name": "TEST VESSEL", "ship_type": 70, "ais_class": "A", "ais_length_m": 180,
            "destination": None, "nav_status": None, "track": track, "label": "simulated", **fields}


def fix(t, lat=53.30, lon=-5.50, sog=10.0, cog=90.0):
    return {"t": t, "lat": lat, "lon": lon, "sog_kn": sog, "cog_deg": cog}


def straight(count=30, start=0, lat=53.30, lon=-5.50, step_deg=0.003):
    return [fix(start + 60 * index, lat, lon + step_deg * index) for index in range(count)]


def as_number(value):
    """Reference for the rule: a finite int/float or numeric text, else None (written apart from the module)."""
    if type(value) in (int, float):
        return value if math.isfinite(value) else None
    if type(value) is str:
        try:
            value = float(value)
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return None


def expected_quality(track):
    """What clean_vessel must report, computed fix by fix the slow, obvious way."""
    dropped, cleared, kept = Counter(), Counter(), []
    for item in track:
        if not isinstance(item, dict):
            dropped["not_a_fix"] += 1
            continue
        t, lat, lon = (as_number(item.get(key)) for key in ("t", "lat", "lon"))
        if t is None:
            dropped["no_time"] += 1
        elif lat is None or lon is None or lat == 91 or lon == 181:
            dropped["no_position"] += 1
        elif abs(lat) > 90 or abs(lon) > 180:
            dropped["position_out_of_range"] += 1
        elif lat == 0 and lon == 0:
            dropped["zero_position"] += 1
        else:
            for key, limit in (("sog_kn", 102.3), ("cog_deg", 360)):
                value = as_number(item.get(key))
                if item.get(key) is not None and (value is None or not 0 <= value < limit):
                    cleared[key] += 1
            kept.append(t)
    dropped["repeated_time"] = len(kept) - len(set(kept))
    reordered = sum(1 for before, after in zip(kept, kept[1:]) if after < before)
    return {"fixes_in": len(track), "fixes_used": len(set(kept)), "dropped": +dropped, "cleared": +cleared,
            "reordered": reordered}


class CorruptedTrackTests(unittest.TestCase):
    def assess_safely(self, test_vessel, context=None):
        """assess_vessel must not raise, must not change its input and must leave no detector error."""
        before = copy.deepcopy(test_vessel)
        result = assess_vessel(test_vessel, CONTEXT if context is None else context)
        self.assertEqual(repr(test_vessel), repr(before), "input vessel was modified")
        self.assertEqual(result["detector_errors"], [], "cleaning should leave the detectors nothing to fail on")
        self.assertIn(result["assessment"]["level"], ("none", "low", "medium", "high", "critical"))
        for kept in result["data_quality"]["dropped"].values():
            self.assertGreater(kept, 0)
        return result

    def check(self, track, dropped=None, cleared=None, reordered=0, used=None):
        result = self.assess_safely(vessel(track))
        quality = result["data_quality"]
        self.assertEqual(quality["dropped"], dropped or {})
        self.assertEqual(quality["cleared"], cleared or {})
        self.assertEqual(quality["reordered"], reordered)
        if used is not None:
            self.assertEqual(quality["fixes_used"], used)
        self.assertEqual(quality, expected_quality(track))
        return result

    def test_empty_and_single_fix(self):
        self.check([], used=0)
        self.check([fix(0)], used=1)
        self.assess_safely({"mmsi": 1, "name": "NO TRACK"})  # no track key at all

    def test_repeated_time_keeps_the_last_fix(self):
        track = straight(5)
        track.insert(3, {**track[2], "lon": -5.40, "sog_kn": 12.0})
        cleaned, quality = clean_vessel(vessel(track))
        self.assertEqual(quality["dropped"], {"repeated_time": 1})
        self.assertEqual([item["t"] for item in cleaned["track"]], [0, 60, 120, 180, 240])
        self.assertEqual(cleaned["track"][2]["lon"], -5.40)  # the later of the two fixes at t=120
        self.check(track, {"repeated_time": 1})

    def test_time_going_backwards_is_sorted(self):
        track = straight(6)
        track[2], track[4] = track[4], track[2]
        cleaned, quality = clean_vessel(vessel(track))
        self.assertEqual([item["t"] for item in cleaned["track"]], [0, 60, 120, 180, 240, 300])
        self.check(track, reordered=2)  # 240 -> 180 -> 120: time went backwards twice
        self.check(list(reversed(straight(6))), reordered=5)

    def test_missing_values(self):
        for key in ("sog_kn", "cog_deg"):
            track = straight(10)
            track[4][key] = None
            self.check(track)  # None is "not available" already: nothing to clear
        for key in ("lat", "lon", "t"):
            track = straight(10)
            track[4][key] = None
            self.check(track, {"no_time" if key == "t" else "no_position": 1})
        track = straight(10)
        del track[3]["lat"], track[5]["sog_kn"]
        self.check(track, {"no_position": 1})

    def test_ais_not_available_and_zero_positions(self):
        track = straight(10)
        track[2].update(lat=91)
        track[3].update(lon=181)
        track[4].update(lat=0, lon=0)
        track[5].update(lat=-95)
        self.check(track, {"no_position": 2, "zero_position": 1, "position_out_of_range": 1}, used=6)

    def test_speed_and_course_limits(self):
        track = straight(10)
        track[1]["sog_kn"] = 102.3
        track[2]["sog_kn"] = -1.0
        track[3]["sog_kn"] = "12"
        track[4]["cog_deg"] = 360
        track[5]["cog_deg"] = "abc"
        cleaned, _ = clean_vessel(vessel(track))
        self.assertEqual([item["sog_kn"] for item in cleaned["track"][1:4]], [None, None, 12.0])
        self.assertEqual([item["cog_deg"] for item in cleaned["track"][4:6]], [None, None])
        self.check(track, cleared={"sog_kn": 2, "cog_deg": 2})

    def test_vessel_fields(self):
        cleaned, quality = clean_vessel(vessel([], ship_type="70", ais_length_m="90"))
        self.assertEqual((cleaned["ship_type"], cleaned["ais_length_m"]), (70, 90.0))
        cleaned, quality = clean_vessel(vessel([], ship_type="cargo", ais_length_m=-3))
        self.assertEqual((cleaned["ship_type"], cleaned["ais_length_m"]), (None, None))
        self.assertEqual(quality["cleared"], {"ship_type": 1, "ais_length_m": 1})
        for length in (0, None):
            result = self.assess_safely(vessel(straight(10), ship_type="30", ais_length_m=length))
            self.assertFalse(result["relevance"]["small"])  # unknown or zero length is never small

    def test_long_gap_antimeridian_and_pole(self):
        self.check(straight(10) + straight(10, start=2 * 86400))
        across = [fix(60 * index, 52.0, 179.95 + 0.02 * index - (360 if 179.95 + 0.02 * index > 180 else 0))
                  for index in range(10)]
        self.check(across)
        self.check([fix(60 * index, 89.95 + 0.004 * index, 10.0) for index in range(10)])
        self.check([fix(60 * index, 90.0, 0.5 * index) for index in range(5)])

    def test_random_corruption_never_raises(self):
        rng = random.Random(20261015)
        base = EXERCISE["track"]
        for case in range(150):
            track = copy.deepcopy(base[rng.randrange(len(base)) // 2:][:rng.randrange(0, 80)])
            for _ in range(rng.randrange(0, 25)):
                if not track:
                    break
                index = rng.randrange(len(track))
                if not isinstance(track[index], dict):
                    continue
                action = rng.random()
                if action < 0.6:
                    track[index][rng.choice(("t", "lat", "lon", "sog_kn", "cog_deg"))] = rng.choice(JUNK)
                elif action < 0.75:
                    track.insert(rng.randrange(len(track) + 1), copy.deepcopy(track[index]))  # repeat
                elif action < 0.85:
                    other = rng.randrange(len(track))
                    track[index], track[other] = track[other], track[index]  # out of order
                elif action < 0.92:
                    track[index] = rng.choice([None, "fix", 42, []])  # not a fix at all
                else:
                    track[index].pop(rng.choice(("lat", "sog_kn", "t")), None)
            test_vessel = {**EXERCISE, "track": track, "ship_type": rng.choice([70, "70", "x", None, 30.0]),
                           "ais_length_m": rng.choice([180, "90", 0, None, -1, "?"])}
            with self.subTest(case=case):
                quality = self.assess_safely(test_vessel)["data_quality"]
                track_cleared = {key: count for key, count in quality["cleared"].items() if key in ("sog_kn", "cog_deg")}
                self.assertEqual({**quality, "cleared": track_cleared}, expected_quality(track))

    def test_describe_data_quality(self):
        self.assertIsNone(describe_data_quality(clean_vessel(vessel(straight(5)))[1]))
        track = straight(10)
        track[2]["lat"] = None
        track[3].update(lat=91, lon=181)
        track[4]["sog_kn"] = 102.3
        track.append(dict(track[-1]))
        self.assertEqual(describe_data_quality(clean_vessel(vessel(track))[1]),
                         "Data quality: 3 fixes ignored (no position 2, repeated time 1); unavailable: speed 1")


class FailingDetectorTests(unittest.TestCase):
    def setUp(self):
        assemble._logged_failures.clear()

    def test_failing_detector_is_recorded_and_the_rest_still_score(self):
        def bomb(test_vessel, context):
            raise RuntimeError("boom")

        expected = assess_vessel(EXERCISE, CONTEXT)
        with self.assertLogs("argus.assemble", "WARNING") as logs:
            result = assess_vessel(EXERCISE, CONTEXT, [bomb, *DETECTORS])
            again = assess_vessel(EXERCISE, CONTEXT, [*DETECTORS, bomb])
        self.assertEqual(len(logs.output), 1)  # one line per (detector, error type), not per vessel
        self.assertIn("bomb", logs.output[0])
        for outcome in (result, again):
            self.assertEqual(outcome["detector_errors"], [{"detector": "bomb", "error": "RuntimeError: boom"}])
            self.assertEqual(outcome["findings"], expected["findings"])
            self.assertEqual(outcome["assessment"], expected["assessment"])

    def test_detector_returning_garbage_is_recorded(self):
        with self.assertLogs("argus.assemble", "WARNING"):
            result = assess_vessel(EXERCISE, CONTEXT, [lambda test_vessel, context: None, *DETECTORS])
        self.assertEqual(result["detector_errors"][0]["error"].split(":")[0], "TypeError")
        self.assertEqual(result["assessment"]["level"], "high")


class CleanDataUnchangedTests(unittest.TestCase):
    def test_exercise_level_and_alert_unchanged(self):
        exercise = next(item for item in build_assessments(SCENARIO)["vessels"] if item["mmsi"] == 999000001)
        self.assertEqual(exercise["assessment"]["level"], "high")
        self.assertEqual(exercise["assessment"]["basis"], "B4 I3 P3 A1 C0 = 11")
        self.assertEqual(exercise["data_quality"], {"fixes_in": 160, "fixes_used": 160, "dropped": {},
                                                    "cleared": {}, "reordered": 0})
        self.assertEqual(exercise["detector_errors"], [])
        alerts = json.dumps(build_alerts(SCENARIO), indent=1, ensure_ascii=False) + "\n"
        self.assertEqual(alerts, (ROOT / "demo/alerts.json").read_text(encoding="utf-8"))

    def test_clean_fixes_are_passed_through(self):
        cleaned, quality = clean_vessel(EXERCISE)
        self.assertTrue(all(a is b for a, b in zip(cleaned["track"], EXERCISE["track"])))
        self.assertIsNone(describe_data_quality(quality))


if __name__ == "__main__":
    unittest.main()
