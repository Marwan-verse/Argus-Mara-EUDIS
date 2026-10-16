"""route_check: declared AIS destination against the recent track (rule C3)."""
import json
from pathlib import Path
import unittest

from argus import assemble, brain_board
from argus.brain_board import _timed_track
from argus.detectors import route_check
from argus.detectors.route_check import match_destination
from argus.levels import assess

ROOT = Path(__file__).resolve().parents[1]


def check(destination, start, legs, label="simulated"):
    track = _timed_track(0, start, legs)
    vessel = {"mmsi": "999000055", "destination": destination, "track": track, "label": label}
    return route_check.detect(vessel, {"now": track[-1]["t"]})


class DestinationTests(unittest.TestCase):
    def test_locodes_names_and_from_to_text_name_one_port(self):
        for text in ("GBHLY", "GB HLY", "gbhly", "Holyhead", "IEDUB>GBHLY", "DUBLIN > HOLYHEAD"):
            port = match_destination(text, (53.3, -5.5))
            self.assertEqual((port["name"], port["country"]), ("Holyhead", "GB"), text)
        self.assertEqual(match_destination("Dún Laoghaire")["name"], "Dun Laoghaire")
        self.assertEqual(match_destination("Port of Le Havre")["country"], "FR")

    def test_generic_blank_or_unknown_text_is_never_guessed(self):
        for text in (None, "", "   ", "FOR ORDERS", "fishing grounds", "TBA", "XXABC", "SOMEWHERE NICE"):
            self.assertIsNone(match_destination(text), text)

    def test_a_shared_name_resolves_to_the_nearest_port(self):
        self.assertEqual(match_destination("BELFAST", (53.3, -5.5))["country"], "GB")
        self.assertEqual(match_destination("BELFAST", (44.0, -69.0))["country"], "US")

    def test_every_locode_in_the_table_resolves(self):
        for code, (country, _name) in route_check.LOCODES.items():
            port = match_destination(code)
            self.assertIsNotNone(port, code)
            self.assertEqual(port["country"], country, code)


class RouteCheckTests(unittest.TestCase):
    def test_moving_away_from_the_declared_port_sets_c3(self):
        found = check("GBHLY", (53.306, -5.489), [(40, 11.0, 340, None)], label="real")
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual(finding["detector"], "route_check")
        self.assertEqual(finding["obs"], {"route_inconsistent": True})
        self.assertEqual(finding["label"], "real")
        self.assertEqual(finding["related"]["port"], "Holyhead")
        self.assertGreaterEqual(finding["related"]["receded_nm"], route_check.MIN_RECEDE_NM)
        self.assertIn("for review", finding["reasons"][0])
        self.assertIn("Holyhead", finding["reasons"][0])
        self.assertNotIn("cable_id", finding["related"])  # a context cue, not tied to one line

    def test_innocent_tracks_stay_quiet(self):
        cases = {
            "heading to the port": ("GBHLY", (53.30, -5.60), [(40, 12.0, 85, None)]),
            "slow, waiting": ("GBHLY", (53.306, -5.489), [(40, 2.0, 340, None)]),
            "port behind Ireland": ("IEDUB", (53.30, -10.50), [(40, 12.0, 270, None)]),
            "just left that port": ("IEDUB", (53.345, -6.15), [(40, 12.0, 90, None)]),
            "manoeuvring by the port": ("GBHLY", (53.33, -4.75), [(40, 6.0, 300, None)]),
            "too short a track": ("GBHLY", (53.306, -5.489), [(12, 11.0, 340, None)]),
            "no destination": (None, (53.306, -5.489), [(40, 11.0, 340, None)]),
            "for orders": ("FOR ORDERS", (53.306, -5.489), [(40, 11.0, 340, None)]),
        }
        for name, (destination, start, legs) in cases.items():
            self.assertEqual(check(destination, start, legs), [], name)

    def test_fixes_after_now_are_ignored(self):
        track = _timed_track(0, (53.306, -5.489), [(40, 11.0, 340, None)])
        vessel = {"mmsi": "999000055", "destination": "GBHLY", "track": track}
        self.assertEqual(route_check.detect(vessel, {"now": 10 * 60}), [])

    def test_c3_adds_one_context_point_and_never_alerts_alone(self):
        result = assess({"route_inconsistent": True})
        self.assertEqual([(f["code"], f["points"], f["group"]) for f in result["factors"]], [("C3", 1, "context")])
        self.assertEqual(result["level"], "none")

    def test_registered_as_a_brain_detector(self):
        self.assertIn(route_check.detect, assemble.DETECTORS)


class WrongWayStoryTests(unittest.TestCase):
    def setUp(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        self.item = next(item for item in brain_board.build_board(scenario) if item["id"] == "SIM-55")

    def at(self, minute):
        brain_board.rescore_story(self.item, minute * 60)
        return self.item

    def test_story_declares_fishguard_and_stays_after_the_dublin_stories(self):
        self.assertEqual(self.item["destination"], "GBFIS")
        track = self.item["story"]["track"]
        self.assertGreaterEqual(track[0]["t"], 140 * 60)
        self.assertLessEqual(track[-1]["t"], 240 * 60)

    def test_watch_card_names_the_destination_cue_before_any_behaviour(self):
        item = self.at(195)
        self.assertEqual(item["assessment"]["level"], "none")
        self.assertIn("C3", [f["code"] for f in item["assessment"]["factors"]])
        self.assertTrue(item["title"].endswith("not heading to its declared destination"))

    def test_incident_includes_the_destination_point(self):
        item = self.at(215)
        codes = {f["code"]: f["points"] for f in item["assessment"]["factors"]}
        self.assertEqual(item["assessment"]["level"], "high")
        self.assertEqual(codes.get("C3"), 1)
        self.assertIn("route_check", item["detectors"])


if __name__ == "__main__":
    unittest.main()
