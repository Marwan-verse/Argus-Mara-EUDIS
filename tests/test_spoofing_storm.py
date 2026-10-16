"""Space weather in the AIS spoofing detector: a G3+ storm explains one vessel's small jumps, not two places."""

import json
import unittest
from pathlib import Path

from argus import space_weather as sw
from argus.assemble import assess_vessel, build_assessments, context_from_scenario
from argus.brain import build_alerts
from argus.detectors import ais_spoofing as spoof
from test_ais_spoofing import moved, straight, two_places_track, vessel

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))


def weather(kp, origin="live"):
    """A space weather status as argus.space_weather gives it, for one Kp value."""
    return sw.status({"kp": [{"t": "2026-10-15T12:00:00Z", "kp": kp}], "source": "NOAA SWPC",
                      "source_url": sw.SWPC_URL, "label": "real"}, origin)


STORM_G4 = weather(8.0)
STORM_2024 = sw.SpaceWeather(fetch=None, cache_path=ROOT / "data/space_weather/none.json").storm_2024()
QUIET = [None, weather(2.0), weather(5.0), weather(6.33)]  # no data, quiet, G1, G2: below the G3 threshold


def two_glitches():
    """Two 3 nm outliers 40 min apart: a spoofing sign without a storm (2 events within 60 min)."""
    track = straight(120)
    track[30], track[70] = moved(track[30], 0, 3), moved(track[70], 180, 3)
    return track


def far_jump():
    track = straight(60)
    track[30:] = [moved(fix, 90, 38) for fix in track[30:]]
    return track


def reappearance(extra_nm):
    """A return after a 20 min gap; 18 nm puts it about 3 nm outside the reachable circle."""
    track = straight(30) + straight(10, lat=53.40, lon=-5.60, start=29 * 60 + 20 * 60)
    track[30:] = [moved(fix, 90, extra_nm) for fix in track[30:]]
    return track


def single_glitch():
    track = straight(60)
    track[30] = moved(track[30], 0, 3)
    return track


def speed_mismatch():
    track = straight(60)
    for fix in track[20:26]:
        fix["sog_kn"] = 2.0
    return track


TRACKS = {"two_glitches": two_glitches, "far_jump": far_jump, "two_places": two_places_track,
          "reappearance": lambda: reappearance(18), "single_glitch": single_glitch,
          "speed_mismatch": speed_mismatch, "clean": lambda: straight(60)}


def finding(track, space_weather=None):
    found = spoof.detect(vessel(track), {"space_weather": space_weather})
    return found[0] if found else None


class NoStormTests(unittest.TestCase):
    def test_below_g3_nothing_changes_by_a_byte(self):
        for name, make in TRACKS.items():
            before = json.dumps(spoof.detect(vessel(make()), {}))
            for state in QUIET:
                with self.subTest(track=name, kp=state and state["kp"]):
                    self.assertEqual(json.dumps(spoof.detect(vessel(make()), {"space_weather": state})), before)

    def test_g3_threshold(self):
        self.assertFalse(spoof.gnss_storm({"space_weather": weather(6.33)}))
        self.assertTrue(spoof.gnss_storm({"space_weather": weather(6.67)}))
        self.assertIsNone(spoof.gnss_storm({}))

    def test_demo_exercise_and_a1_unchanged_during_a_storm(self):
        for state in (None, STORM_G4, STORM_2024):
            exercise = next(item for item in build_assessments(SCENARIO, space_weather=state)["vessels"]
                            if item["mmsi"] == 999000001)
            self.assertEqual(exercise["assessment"]["level"], "high")
            self.assertEqual(exercise["assessment"]["basis"], "B4 I3 P3 A1 C0 = 11")
        alerts = json.dumps(build_alerts(SCENARIO), indent=1, ensure_ascii=False) + "\n"
        self.assertEqual(alerts, (ROOT / "demo/alerts.json").read_text(encoding="utf-8"))


class StormTests(unittest.TestCase):
    def test_single_vessel_jumps_are_not_a_spoofing_sign(self):
        self.assertEqual(finding(two_glitches())["obs"], {"spoof_signs": True})
        stormy = finding(two_glitches(), STORM_G4)
        self.assertEqual(stormy["obs"], {})
        self.assertEqual(stormy["strength"], spoof.WEAK_STRENGTH)
        self.assertIn("Geomagnetic storm G4 (Kp 8, NOAA SWPC, real): GNSS positions may be degraded — jump may "
                      "be GPS error, not spoofing.", stormy["reasons"][1])
        self.assertEqual(stormy["related"]["space_weather"]["not_counted"], 2)
        self.assertEqual([event["kind"] for event in stormy["related"]["events"]], ["outlier", "outlier"])

    def test_small_reappearance_is_not_a_sign_in_a_storm(self):
        track = reappearance(18)
        track[36] = moved(track[36], 0, 3)  # and one glitch 6 min after the return
        plain = finding(track)
        self.assertEqual([event["kind"] for event in plain["related"]["events"]], ["reappearance", "outlier"])
        self.assertLessEqual(plain["related"]["events"][0]["distance_nm"], spoof.GNSS_MAX_NM)
        self.assertEqual(plain["obs"], {"spoof_signs": True})  # 2 events within 60 min
        stormy = finding(track, STORM_G4)
        self.assertEqual(stormy["obs"], {})
        self.assertEqual(stormy["related"]["space_weather"]["not_counted"], 2)

    def test_two_places_still_counts_in_a_storm(self):
        for state in (STORM_G4, STORM_2024):
            stormy = finding(two_places_track(), state)
            self.assertEqual(stormy["obs"], {"spoof_signs": True})
            self.assertIn("noted, but a storm does not explain one identity reported in two places",
                          " ".join(stormy["reasons"]))

    def test_large_jump_still_counts_in_a_storm(self):
        stormy = finding(far_jump(), STORM_G4)
        self.assertEqual(stormy["obs"], {"spoof_signs": True})
        self.assertEqual(stormy["related"]["space_weather"]["not_counted"], 0)
        self.assertIn("does not explain an event over 5 nm", " ".join(stormy["reasons"]))

    def test_speed_mismatch_is_not_explained(self):
        plain, stormy = finding(speed_mismatch()), finding(speed_mismatch(), STORM_G4)
        self.assertEqual(stormy["obs"], plain["obs"])
        self.assertEqual(stormy["related"]["space_weather"]["not_counted"], 0)

    def test_historical_storm_is_labelled(self):
        self.assertEqual((STORM_2024["g"], STORM_2024["kp"]), (5, 9.0))
        text = " ".join(finding(single_glitch(), STORM_2024)["reasons"])
        self.assertIn("Geomagnetic storm G5 (Kp 9, GFZ Potsdam, real, historical)", text)

    def test_level_drops_without_rule_i2(self):
        context = context_from_scenario({}, space_weather=STORM_G4)
        plain = assess_vessel(vessel(two_glitches()), context_from_scenario({}))
        stormy = assess_vessel(vessel(two_glitches()), context)
        self.assertTrue(plain["observations"].get("spoof_signs"))
        self.assertFalse(stormy["observations"].get("spoof_signs"))
        self.assertIn("I2", [item["code"] for item in plain["assessment"]["factors"]])
        self.assertNotIn("I2", [item["code"] for item in stormy["assessment"]["factors"]])


if __name__ == "__main__":
    unittest.main()
