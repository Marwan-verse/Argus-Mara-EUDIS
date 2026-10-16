"""marine_notice: real Irish Marine Notices explain the vessels they name (declared-work whitelist)."""
from datetime import date
import json
from pathlib import Path
import unittest

from argus.assemble import assess_vessel, declared_work
from argus.brain_board import build_board, rescore_story
from argus.detectors import marine_notice
from argus.explain import explain

ROOT = Path(__file__).resolve().parents[1]
RUSH = (53.54, -6.02)  # on the EWIC route of Marine Notice 49/2026, nearshore off Rush


def ship(name, call_sign, lat, lon, legs=None):
    """A vessel at one position, or on a survey run east along EWIC (one fix a minute at 3.5 kn)."""
    track = [{"t": minute * 60, "lat": lat, "lon": lon + minute * 0.001, "sog_kn": 3.5, "cog_deg": 90}
             for minute in range(legs or 1)]
    return {"mmsi": "999000100", "name": name, "call_sign": call_sign, "ship_type": 33, "ais_class": "A",
            "ais_length_m": 70, "track": track, "label": "simulated"}


def matches(vessel, day=None):
    context = {"date": day} if day else {}
    return [(finding["related"]["notice"], finding["related"]["match"]) for finding in
            marine_notice.detect(vessel, context)]


class DataTests(unittest.TestCase):
    def test_bundled_notices_are_real_and_complete(self):
        notices = marine_notice.load_notices()
        self.assertEqual(len(notices), 10)
        for notice in notices:
            self.assertEqual(notice["label"], "real")
            self.assertTrue(notice["url"].startswith("https://assets.gov.ie/"), notice["number"])
            self.assertTrue(notice["vessels"] and all(v["call_sign"] for v in notice["vessels"]), notice["number"])
            self.assertTrue(notice["areas"] and all(area["points"] for area in notice["areas"]), notice["number"])
            for area in notice["areas"]:
                for lat, lon in area["points"]:
                    self.assertTrue(49 < lat < 56 and -12 < lon < -3, (notice["number"], lat, lon))
        assets = {notice["asset"] for notice in notices}
        self.assertTrue({"EWIC", "Greenlink", "Celtic Interconnector", "Gas interconnectors IC1 and IC2",
                         "Corrib gas pipelines"} <= assets)
        self.assertEqual(marine_notice.source()["retrieved"], "2026-10-16")

    def test_only_the_ewic_survey_is_active_during_the_hackathon(self):
        active = [notice["number"] for notice in marine_notice.active_on(date(2026, 10, 16))]
        self.assertEqual(active, ["49/2026"])


class DetectorTests(unittest.TestCase):
    def test_named_vessel_inside_the_area_within_the_dates_is_explained(self):
        self.assertEqual(matches(ship("LADY KATHLEEN", "EIXT2", *RUSH), "2026-10-16"), [("49/2026", "named")])

    def test_dates_area_and_per_vessel_start_are_checked(self):
        self.assertEqual(matches(ship("LADY KATHLEEN", "EIXT2", *RUSH), "2026-12-20"),
                         [("49/2026", "named_elsewhere")])  # after 15 Nov plus a week of weather margin
        self.assertEqual(matches(ship("LADY KATHLEEN", "EIXT2", 51.8, -8.2), "2026-10-16"),
                         [("49/2026", "named_elsewhere")])  # off Cork, far from EWIC
        self.assertIn(("49/2026", "named_elsewhere"),
                      matches(ship("ROMAN REBEL", "2ICA5", 53.60, -5.30), "2026-10-16"))  # offshore starts 1 Nov
        self.assertIn(("49/2026", "named"), matches(ship("ROMAN REBEL", "2ICA5", 53.60, -5.30), "2026-11-05"))

    def test_an_unnamed_vessel_in_the_area_is_not_explained(self):
        found = marine_notice.detect(ship("SOME SHIP", "ZZZZ9", *RUSH), {"date": "2026-10-16"})
        self.assertEqual([(f["related"]["notice"], f["related"]["match"]) for f in found], [("49/2026", "unnamed")])
        self.assertEqual(found[0]["obs"], {})
        self.assertIn("names Lady Kathleen (EIXT2), Roman Rebel (2ICA5), not this vessel", found[0]["reasons"][1])

    def test_call_sign_wins_and_name_is_used_only_without_one(self):
        self.assertEqual(matches(ship("MV Calypso", None, 51.85, -7.79), "2026-05-16"), [("25/2026", "named")])
        self.assertEqual(matches(ship("CALYPSO", "OTHER1", 51.85, -7.79), "2026-05-16"), [("25/2026", "unnamed")])

    def test_a_replay_without_a_date_says_the_dates_were_not_checked(self):
        found = marine_notice.detect(ship("SEAPIPER", "5BEN6", 51.60, -7.81), {})
        self.assertEqual(found[0]["related"]["match"], "named")
        self.assertIn("not checked", found[0]["reasons"][-1])

    def test_unix_fix_times_give_the_day(self):
        vessel = ship("LADY KATHLEEN", "EIXT2", *RUSH)
        vessel["track"][0]["t"] = 1_792_152_000  # 2026-10-16 UTC
        self.assertEqual(matches(vessel), [("49/2026", "named")])


class RuleTests(unittest.TestCase):
    def test_a_notified_survey_over_the_cable_is_capped_at_low(self):
        vessel = ship("LADY KATHLEEN", "EIXT2", *RUSH, legs=40)
        cables = [{"id": "ewic", "name": "EWIC", "kind": "power", "label": "illustrative",
                   "path": [[53.526, -6.083], [53.552, -5.958], [53.603, -5.285]],
                   "anchor_reachable": None, "min_depth_m": None}]
        context = {"now": 39 * 60, "cables": cables, "date": "2026-10-16"}
        unexplained = assess_vessel({**vessel, "call_sign": "ZZZZ9"}, context)
        explained = assess_vessel(vessel, context)
        self.assertNotEqual(unexplained["assessment"]["level"], "low")
        self.assertEqual(explained["assessment"]["level"], "low")
        self.assertTrue(explained["declared_work"]["applied"])
        self.assertIn("Capped at Low: notified, authorised operation (repair or survey).",
                      explained["assessment"]["notes"])

    def test_evidence_against_the_vessel_lifts_the_cap(self):
        finding = {"detector": "marine_notice", "obs": {"notice_named": True},
                   "related": {"notice": "49/2026", "notice_label": "real"}}
        for obs in ({"fault_confirmed": True}, {"ais_gap_min": 25}, {"spoof_signs": True},
                    {"length_mismatch_pct": 40}, {"identity_changes": 1}, {"ignored_instruction": True}):
            work = declared_work([finding], obs)
            self.assertTrue(work["named"])
            self.assertFalse(work["applied"], obs)
            self.assertTrue(work["exception"], obs)
        self.assertTrue(declared_work([finding], {"slow_over_corridor_min": 30})["applied"])


class BoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.by_id = {item["id"]: item for item in build_board(scenario, alerts)}

    def test_survey_story_is_explained_by_the_exercise_notice(self):
        item = self.by_id["SIM-56"]
        rescore_story(item, 120 * 60)
        self.assertEqual(item["assessment"]["level"], "low")
        self.assertGreaterEqual(item["assessment"]["score"], 9)  # High without the notice
        why = explain(item)["declared_work"]
        self.assertEqual(why["status"], "explained")
        self.assertEqual(why["notices"][0]["label"], "EXERCISE")

    def test_ship_in_the_real_notice_area_is_not_explained(self):
        item = self.by_id["SIM-60"]
        rescore_story(item, 215 * 60)
        self.assertEqual(item["assessment"]["level"], "high")
        why = explain(item)["declared_work"]
        self.assertEqual(why["status"], "unnamed")
        self.assertIn("Marine Notice 49/2026", [notice["name"] for notice in why["notices"]])
        self.assertTrue(all(notice["label"] == "REAL" for notice in why["notices"]))
        self.assertIn("REAL", [tag for tag, _text in explain(item)["labels"]])


if __name__ == "__main__":
    unittest.main()
