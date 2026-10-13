"""Who reaches a moving vessel in time: intercepts, limits, the no-response rule and assignments."""
import json
import unittest
from pathlib import Path

from argus import responders
from argus.brain_board import build_board
from argus.countdown import nm_between, step
from argus.incident_board import Replay, deadline_s
from argus.levels import assess
from argus.prediction import position_at

ROOT = Path(__file__).resolve().parents[1]
DRONE = {"id": "DX", "name": "Drone DX", "kind": "drone", "counts": True, "lat": 53.0, "lon": -6.0,
         "speed_kn": 60, "readiness_min": 5, "range_nm": 50, "max_wind_kn": 25}
SHIP = {"id": "SX", "name": "Ship SX", "kind": "ship", "counts": True, "lat": 53.0, "lon": -6.0,
        "speed_kn": 15, "readiness_min": 0}


def fleet(*assets):
    return {"label": "assumption", "assets": list(assets)}


class InterceptTests(unittest.TestCase):
    def test_a_moving_vessel_is_met_where_it_will_be_not_where_it_was(self):
        # 20 nm east of the drone, steaming further east at 12 kn.
        start = step(53.0, -6.0, 90, 20)
        position = responders.dead_reckoning(*start, 90, 12, 0)
        row = responders.assess_asset(DRONE, position, 0)
        static_s = 5 * 60 + 20 / 60 * 3600
        self.assertGreater(row["eta_s"], static_s)
        meet = position(row["eta_s"])
        self.assertAlmostEqual(row["meet"][1], meet[1], places=4)
        travelled = 5 * 60 + nm_between(53.0, -6.0, *meet) / 60 * 3600
        self.assertLessEqual(travelled, row["eta_s"])          # really there by then
        self.assertGreater(travelled, row["eta_s"] - 2 * 60)   # and not much earlier (60 s steps)

    def test_a_slow_ship_cannot_catch_a_faster_vessel_running_away(self):
        position = responders.dead_reckoning(*step(53.0, -6.0, 90, 10), 90, 20, 0)
        row = responders.assess_asset(SHIP, position, 0)
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("cannot reach", row["reason"])

    def test_a_dark_vessel_is_intercepted_at_its_predicted_position(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        track = scenario["vessels"][0]["track"]
        position = lambda t: (lambda fix: (fix["lat"], fix["lon"]))(position_at(track, t))
        drone = {**DRONE, "lat": 53.0, "lon": -5.6}
        row = responders.assess_asset(drone, position, 1900)  # AIS dark from 1800 to 3000
        met_t = 1900 + row["eta_s"]
        self.assertLess(met_t, 3000)
        fix = position_at(track, met_t)
        self.assertEqual(fix["status"], "predicted")
        self.assertEqual(row["meet"], [round(fix["lat"], 5), round(fix["lon"], 5)])

    def test_wind_grounds_drones_but_not_aircraft(self):
        position = responders.dead_reckoning(53.1, -6.0, 0, 0, 0)
        heli = {**DRONE, "id": "HX", "kind": "helicopter", "max_wind_kn": None, "range_nm": 200}
        result = responders.assess_fleet(fleet(DRONE, heli), position, 0, wind_kn=30)
        rows = {row["id"]: row for row in result["rows"]}
        self.assertEqual(rows["DX"]["status"], "unavailable")
        self.assertIn("wind 30 kn", rows["DX"]["reason"])
        self.assertEqual(rows["HX"]["status"], "eyes_on")
        self.assertEqual(responders.assess_asset(DRONE, position, 0, wind_kn=25)["status"], "eyes_on")

    def test_out_of_range_drone_and_vhf_are_unavailable(self):
        far = responders.dead_reckoning(*step(53.0, -6.0, 90, 70), 0, 0, 0)
        row = responders.assess_asset(DRONE, far, 0)
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("out of range (70 nm from base, limit 50 nm)", row["reason"])
        vhf = {"id": "VHF", "name": "VHF", "kind": "hail", "counts": False, "lat": 53.0, "lon": -6.0,
               "readiness_min": 2, "range_nm": 30}
        self.assertIn("out of VHF range", responders.assess_asset(vhf, far, 0)["reason"])

    def test_in_time_means_before_the_earliest_line_eta(self):
        position = responders.dead_reckoning(*step(53.0, -6.0, 90, 20), 0, 0, 0)
        eta = responders.assess_asset(DRONE, position, 0)["eta_s"]  # 25 min
        early = responders.assess_fleet(fleet(DRONE), position, 0, deadline_s=eta + 600)
        late = responders.assess_fleet(fleet(DRONE), position, 0, deadline_s=eta - 60)
        self.assertEqual((early["rows"][0]["status"], early["rows"][0]["margin_s"]), ("in_time", 600))
        self.assertFalse(early["no_response_in_time"])
        self.assertEqual((late["rows"][0]["status"], late["rows"][0]["margin_s"]), ("late", -60))
        self.assertTrue(late["no_response_in_time"])
        self.assertEqual(responders.summary_line(late), ("No responder in time · best DX 25 min, 1 min late", True))
        self.assertEqual(responders.summary_line(early), ("Drone DX · 25 min · in time (+10 min)", False))

    def test_look_only_assets_never_count_and_a_vessel_at_the_line_is_not_flagged(self):
        position = responders.dead_reckoning(53.05, -6.0, 0, 0, 0)
        vhf = {"id": "VHF", "name": "VHF", "kind": "hail", "counts": False, "lat": 53.0, "lon": -6.0,
               "readiness_min": 2, "range_nm": 30}
        sat = {"id": "SAT", "name": "Satellite", "kind": "satellite", "counts": False, "pass_times_s": [300]}
        result = responders.assess_fleet(fleet(vhf, sat), position, 0, deadline_s=3600)
        self.assertTrue(all(row["in_time"] for row in result["rows"]))
        self.assertTrue(result["no_response_in_time"])
        at_line = responders.assess_fleet(fleet(DRONE), position, 600, deadline_s=600)
        self.assertTrue(at_line["at_line"])
        self.assertFalse(at_line["no_response_in_time"])

    def test_an_asset_assigned_elsewhere_is_unavailable_and_its_own_eta_counts_from_dispatch(self):
        position = responders.dead_reckoning(*step(53.0, -6.0, 90, 20), 0, 0, 0)
        other = responders.assess_fleet(fleet(DRONE), position, 0, deadline_s=3600,
                                        busy={"DX": "INC-A-1"}, incident_id="INC-B-1")
        self.assertEqual(other["rows"][0]["reason"], "assigned to INC-A-1")
        self.assertTrue(other["no_response_in_time"])
        self.assertIn("DX assigned to INC-A-1", responders.summary_line(other)[0])
        own = responders.assess_fleet(fleet(DRONE), position, 600, deadline_s=3600, busy={"DX": "INC-A-1"},
                                      incident_id="INC-A-1", dispatched={"DX": 0})
        self.assertEqual((own["rows"][0]["status"], own["rows"][0]["eta_s"]), ("assigned", 25 * 60 - 600))


class ReplayResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        cls.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.start = min(alert["t"] for alert in cls.alerts)

    def setUp(self):
        self.items = build_board(self.scenario, self.alerts)
        self.by_id = {item["id"]: item for item in self.items}
        self.replay = Replay(self.items, self.scenario, self.start)
        self.replay.seek(self.start)

    def test_the_exercise_deadline_is_its_alert_eta(self):
        exercise = self.by_id["A1"]
        self.assertEqual(deadline_s(exercise, self.start + 600), self.start + self.alerts[0]["eta_earliest_s"])
        self.assertFalse(self.replay.responses["A1"]["no_response_in_time"])

    def test_no_responder_in_time_raises_the_level_once_with_a_note(self):
        heron = self.by_id["SIM-06"]
        result = self.replay.responses["SIM-06"]
        self.assertTrue(result["no_response_in_time"])
        self.assertTrue(heron["observations"]["no_response_in_time"])
        without = assess({**heron["observations"], "no_response_in_time": False})["level"]
        self.assertEqual((without, heron["assessment"]["level"]), ("high", "critical"))
        self.assertIn("Raised one level: no response asset can arrive before the earliest ETA.",
                      heron["assessment"]["notes"])
        self.replay.seek(self.start + 60)
        self.assertEqual(heron["assessment"]["notes"].count(
            "Raised one level: no response asset can arrive before the earliest ETA."), 1)

    def test_storm_grounds_every_drone_and_rewinding_keeps_the_setting(self):
        self.replay.storm = True
        self.replay.seek(self.start + 60)
        self.replay.seek(self.start)
        rows = [row for row in self.replay.responses["A1"]["rows"] if row["kind"] == "drone"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["reason"].startswith("wind 30 kn") for row in rows))


if __name__ == "__main__":
    unittest.main()
