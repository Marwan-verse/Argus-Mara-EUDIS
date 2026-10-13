"""AIS spoofing detector: only physically impossible positions count, and one GPS glitch is not spoofing."""

import json
import time
import unittest
from pathlib import Path

from argus import assemble
from argus.assemble import assess_vessel, context_from_scenario
from argus.brain_board import build_board
from argus.countdown import step
from argus.detectors import ais_spoofing as spoof
from argus.prediction import reappearance_check, v_max_kn

ROOT = Path(__file__).resolve().parents[1]


def straight(count=60, lat=53.40, lon=-5.60, course=90, speed=10.0, interval=60, start=0):
    """A fictional straight track declaring its true speed."""
    track = []
    for index in range(count):
        here = step(lat, lon, course, speed * index * interval / 3600)
        track.append({"t": start + index * interval, "lat": here[0], "lon": here[1], "sog_kn": speed,
                      "cog_deg": course})
    return track


def moved(fix, course, distance_nm):
    lat, lon = step(fix["lat"], fix["lon"], course, distance_nm)
    return {**fix, "lat": lat, "lon": lon}


def vessel(track, ship_type=70, ais_class="A", length=180):
    return {"mmsi": 999000077, "name": "TEST SKUA", "ship_type": ship_type, "ais_class": ais_class,
            "ais_length_m": length, "destination": None, "nav_status": None, "track": track, "label": "simulated"}


def run(track, now=None):
    fixes = spoof.clean_track(track, now)
    return fixes, spoof.steps_between(fixes)


def kinds(finding):
    return [event["kind"] for event in finding["related"]["events"]]


def board_finding(obs):
    """Hand-written behaviour near a line, standing in for another detector."""
    def detect(vessel, context):
        return [{"detector": "test_behaviour", "mmsi": vessel["mmsi"], "t": 0, "position": [53.4, -5.5],
                 "strength": 0.8, "reasons": ["test behaviour"], "related": {"cable_id": "cable-test"},
                 "label": "simulated", "obs": obs}]
    return detect


def two_places_track():
    track = straight(40)
    return [moved(fix, 0, 12) if index >= 30 and index % 2 else fix for index, fix in enumerate(track)]


class CleanTrackTests(unittest.TestCase):
    def test_clean_track_has_no_finding(self):
        self.assertEqual(spoof.detect(vessel(straight(200)), {}), [])

    def test_missing_speed_and_not_available_values_are_ignored(self):
        track = straight(60)
        track[10]["sog_kn"] = None
        track[11]["sog_kn"] = 102.3
        track[20] = {**track[20], "lat": 91, "lon": 181}  # AIS "position not available"
        track[21] = {**track[21], "lat": 0, "lon": 0}
        self.assertEqual(spoof.detect(vessel(track), {}), [])
        fixes = spoof.clean_track(track)
        self.assertEqual(len(fixes), 58)
        self.assertIsNone(fixes[11]["sog_kn"])

    def test_gps_jitter_under_one_mile_is_not_a_jump(self):
        track = straight(30, interval=10)
        track[15] = moved(track[15], 0, 0.8)  # 0.8 nm in 10 s is 288 kn, but within the jitter allowance
        self.assertEqual(spoof.jump_events(*run(track)), [])


class JumpTests(unittest.TestCase):
    def test_impossible_jump_is_reported_with_numbers(self):
        track = straight(60)
        track[30:] = [moved(fix, 90, 38) for fix in track[30:]]
        events = spoof.jump_events(*run(track))
        self.assertEqual([event["kind"] for event in events], ["jump"])
        self.assertIn("Impossible position jump of 38.2 nm in 60 s implies 2290 kn; limit 50 kn.", events[0]["reason"])
        finding = spoof.detect(vessel(track), {})[0]
        self.assertEqual(finding["obs"], {"spoof_signs": True})  # one event over 5 nm
        self.assertIn("Possible AIS spoofing, for review", finding["reasons"][0])

    def test_limit_scales_with_declared_speed(self):
        track = straight(60, speed=30, interval=60)  # a fast craft declaring 30 kn: limit 90 kn
        track[30:] = [moved(fix, 90, 1.2) for fix in track[30:]]  # 0.5 + 1.2 nm in 60 s = 102 kn
        self.assertEqual(len(spoof.jump_events(*run(track))), 1)
        track = straight(60, speed=30, interval=60)
        track[30:] = [moved(fix, 90, 0.9) for fix in track[30:]]  # 0.5 + 0.9 nm in 60 s = 84 kn, under 90
        self.assertEqual(spoof.jump_events(*run(track)), [])

    def test_single_small_glitch_is_weak_without_spoof_signs(self):
        track = straight(60)
        track[30] = moved(track[30], 0, 3)
        finding = spoof.detect(vessel(track), {})[0]
        self.assertEqual(kinds(finding), ["outlier"])
        self.assertEqual(finding["obs"], {})
        self.assertEqual(finding["strength"], spoof.WEAK_STRENGTH)
        self.assertIn("possibly a GPS glitch", finding["reasons"][0])

    def test_single_far_outlier_alone_is_not_enough(self):
        track = straight(60)
        track[30] = moved(track[30], 0, 20)
        finding = spoof.detect(vessel(track), {})[0]
        self.assertEqual(kinds(finding), ["outlier"])
        self.assertEqual(finding["obs"], {})

    def test_two_glitches_within_an_hour_set_spoof_signs(self):
        track = straight(120)
        track[30], track[70] = moved(track[30], 0, 3), moved(track[70], 180, 3)
        finding = spoof.detect(vessel(track), {})[0]
        self.assertEqual(kinds(finding), ["outlier", "outlier"])
        self.assertEqual(finding["obs"], {"spoof_signs": True})
        track = straight(200)
        track[10], track[150] = moved(track[10], 0, 3), moved(track[150], 180, 3)  # 140 min apart
        self.assertEqual(spoof.detect(vessel(track), {})[0]["obs"], {})

    def test_fixes_after_now_are_ignored(self):
        track = straight(60)
        track[40:] = [moved(fix, 90, 38) for fix in track[40:]]
        self.assertEqual(spoof.detect(vessel(track), {"now": track[39]["t"]}), [])
        self.assertEqual(len(spoof.detect(vessel(track), {"now": track[45]["t"]})), 1)


class SpeedMismatchTests(unittest.TestCase):
    def test_three_pairs_in_a_row_are_one_event(self):
        track = straight(40, speed=10)
        for fix in track[10:14]:
            fix["sog_kn"] = 2.0  # pairs 10-11, 11-12, 12-13 declare 2 kn against 10 kn; the edges average 6
        events = spoof.speed_mismatch_events(*run(track))
        self.assertEqual(len(events), 1)
        self.assertIn("in 3 fix pairs in a row", events[0]["reason"])
        self.assertIn("declared 2.0 kn, positions imply 10.0 kn", events[0]["reason"])
        self.assertEqual(spoof.detect(vessel(track), {})[0]["obs"], {})  # one event alone stays weak

    def test_two_pairs_or_long_intervals_do_not_count(self):
        track = straight(40, speed=10)
        for fix in track[10:13]:
            fix["sog_kn"] = 2.0
        self.assertEqual(spoof.speed_mismatch_events(*run(track)), [])
        track = straight(10, speed=10, interval=900)  # 15 min apart: too far to compare
        for fix in track:
            fix["sog_kn"] = 2.0
        self.assertEqual(spoof.speed_mismatch_events(*run(track)), [])


class LandTests(unittest.TestCase):
    def test_land_lookup(self):
        self.assertFalse(spoof.on_land(53.40, -5.50))  # Irish Sea
        self.assertTrue(spoof.on_land(53.40, -7.90))  # central Ireland
        self.assertTrue(spoof.on_land(54.23, -4.53))  # Isle of Man
        self.assertGreater(spoof.inland_nm(54.23, -4.53), 1.0)
        self.assertIsNone(spoof.inland_nm(52.66, -8.63))  # Limerick: inland, but within 2 nm of the port

    def test_fix_inland_is_one_event_per_run(self):
        track = straight(10, lat=53.40, lon=-8.30, speed=5)  # a run of fixes across central Ireland
        events = spoof.land_events(spoof.clean_track(track))
        self.assertEqual([event["kind"] for event in events], ["on_land"])
        self.assertIn("nm inside land (Natural Earth 1:50m)", events[0]["reason"])
        self.assertEqual(spoof.land_events(spoof.clean_track(straight(60))), [])

    def test_lookup_is_fast(self):
        track = straight(5000, interval=10, speed=10.8, course=0, lat=53.0, lon=-5.5)
        spoof.detect(vessel(track[:2]), {})  # load the land and port files once
        start = time.perf_counter()
        spoof.detect(vessel(track), {})
        self.assertLess(time.perf_counter() - start, 0.5)


class TwoPlacesTests(unittest.TestCase):
    def test_alternating_positions_are_two_places(self):
        finding = spoof.detect(vessel(two_places_track()), {})[0]
        self.assertEqual(kinds(finding), ["two_places"])
        self.assertEqual(finding["obs"], {"spoof_signs": True})
        self.assertEqual(finding["strength"], 0.9)
        self.assertIn("possibly two transmitters using one MMSI", finding["reasons"][1])
        self.assertEqual(spoof.jump_events(*run(two_places_track())), [])  # not double-counted as jumps

    def test_two_consistent_fixes_away_and_back_are_two_places(self):
        track = straight(60)
        track[30:32] = [moved(fix, 0, 12) for fix in track[30:32]]
        events = spoof.two_places_events(*run(track))
        self.assertEqual([event["kind"] for event in events], ["two_places"])


class ReappearanceTests(unittest.TestCase):
    def test_return_outside_the_reachable_circle(self):
        track = straight(30) + straight(10, lat=53.40, lon=-4.60, start=29 * 60 + 20 * 60)
        events = spoof.reappearance_events(*run(track))
        self.assertEqual([event["kind"] for event in events], ["reappearance"])
        self.assertIn("After a 20 min AIS gap", events[0]["reason"])
        self.assertIn("possible position spoofing or identity reuse", events[0]["reason"])
        self.assertEqual(spoof.detect(vessel(track), {})[0]["obs"], {"spoof_signs": True})

    def test_physical_top_speed_by_ship_type(self):
        self.assertEqual([spoof.type_top_kn(code) for code in (70, "84", 65, 45, 30, None, "x")],
                         [25.0, 25.0, 35.0, 50.0, 30.0, 30.0, 30.0])

    def gap_return(self, ship_type, speed_in_gap):
        """Steams 6 kn for an hour, goes dark 2 h, returns as if it had run at speed_in_gap on the same course."""
        track = straight(61, speed=6.0)
        last = track[-1]
        back = straight(10, lat=last["lat"], lon=last["lon"], speed=6.0, start=last["t"] + 2 * 3600)
        track += [moved(fix, 90, speed_in_gap * 2) for fix in back]
        return spoof.detect(vessel(track, ship_type=ship_type, length=200), {})

    def test_fast_cargo_ship_after_a_gap_is_not_spoofing(self):
        finding = self.gap_return(70, 22.0)  # 44 nm in 2 h; cargo top speed 25 kn reaches 50 nm
        self.assertFalse(finding and finding[0]["obs"].get("spoof_signs"))

    def test_fast_ferry_after_a_gap_is_not_spoofing(self):
        finding = self.gap_return(60, 30.0)  # 60 nm in 2 h; passenger top speed 35 kn reaches 70 nm
        self.assertFalse(finding and finding[0]["obs"].get("spoof_signs"))

    def test_cargo_ship_at_40_knots_after_a_gap_is_spoofing(self):
        finding = self.gap_return(70, 40.0)  # 80 nm in 2 h, 30 nm beyond the 50 nm circle
        self.assertEqual(finding[0]["obs"], {"spoof_signs": True})
        self.assertEqual(kinds(finding[0]), ["reappearance"])
        self.assertIn("against an assumed maximum of 25.0 kn", finding[0]["reasons"][1])

    def test_return_inside_the_circle_is_fine(self):
        track = straight(30) + straight(10, lat=53.40, lon=-5.60, course=90, start=29 * 60 + 20 * 60)
        track[30:] = [moved(fix, 90, 5.0) for fix in track[30:]]
        self.assertEqual(spoof.reappearance_events(*run(track)), [])


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))

    def test_demo_scenario_has_no_spoofing(self):
        context = context_from_scenario(self.scenario)
        for demo_vessel in self.scenario["vessels"]:
            self.assertEqual(spoof.detect(demo_vessel, context), [], demo_vessel["mmsi"])
            fixes, steps = run(demo_vessel["track"])
            gaps = [index for index, item in enumerate(steps) if item["dt"] >= spoof.GAP_S]
            self.assertTrue(gaps)
            for index in gaps:
                check = reappearance_check(fixes[index], fixes[index + 1], v_max_kn(fixes, fixes[index]["t"]))
                self.assertNotEqual(check["verdict"], "physically_inconsistent")

    def test_demo_alert_level_is_unchanged(self):
        self.assertIn(spoof.detect, assemble.DETECTORS)
        alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        exercise = next(item for item in build_board(self.scenario, alerts) if item["id"] == "A1")
        self.assertEqual(exercise["assessment"]["level"], "high")
        self.assertEqual(exercise["assessment"]["basis"], "B4 I3 P3 A1 C0 = 11")
        self.assertEqual(exercise["detectors"], ["legacy_cable_v1"])


class AssembleTests(unittest.TestCase):
    def test_large_vessel_with_spoofing_gets_i2(self):
        result = assess_vessel(vessel(two_places_track()), {})  # the registered detectors
        codes = [factor["code"] for factor in result["assessment"]["factors"]]
        self.assertIn("I2", codes)
        self.assertEqual(result["observations"]["spoof_signs"], True)
        self.assertEqual([finding["detector"] for finding in result["findings"]], ["ais_spoofing"])

    def test_small_vessel_with_spoofing_is_not_capped(self):
        obs = {"slow_over_corridor_min": 15, "in_corridor": True, "asset_class": "telecom"}
        small = vessel(two_places_track(), ship_type=37, ais_class="B", length=12)
        result = assess_vessel(small, {}, [board_finding(obs), spoof.detect])
        self.assertTrue(result["relevance"]["small"])
        self.assertIsNone(result["relevance"]["cap"])
        self.assertNotEqual(result["assessment"]["level"], "low")
        self.assertIn("Small-vessel cap not applied: position jumps", " ".join(result["assessment"]["notes"]))
        glitch = straight(60)
        glitch[30] = moved(glitch[30], 0, 3)
        capped = assess_vessel(vessel(glitch, ship_type=37, ais_class="B", length=12), {},
                               [board_finding(obs), spoof.detect])
        self.assertEqual(capped["assessment"]["level"], "low")  # a single glitch does not lift the cap


if __name__ == "__main__":
    unittest.main()