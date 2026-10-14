"""Panel incidents: one incident per board contact, events for the panel, decisions via argus.incidents."""
import copy
import json
import unittest
from pathlib import Path

from argus.brain_board import build_board, update
from argus.incident_board import Replay, Tracker, feed, vessel_key
from argus.incidents import QUIET_CLOSE_S
from argus.levels import RANK

ROOT = Path(__file__).resolve().parents[1]


def contact(identifier, level):
    """A minimal board item at a given level."""
    return {"id": identifier, "name": identifier, "label": "simulated", "line_id": "ewic",
            "assessment": {"level": level, "factors": [], "basis": f"{level} test"}}


class IncidentBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        cls.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.board = build_board(cls.scenario, cls.alerts)

    def setUp(self):
        self.items = copy.deepcopy(self.board)
        self.by_id = {item["id"]: item for item in self.items}
        self.tracker = Tracker()
        self.events = self.tracker.step(self.items, 0)

    def test_medium_and_above_open_one_incident_each_and_low_is_watched(self):
        incident_items = [item for item in self.items if RANK[item["assessment"]["level"]] >= RANK["medium"]]
        self.assertEqual(len(self.tracker.state["open"]), len(incident_items))
        self.assertEqual(set(self.events), {item["id"] for item in incident_items})
        self.assertTrue(all(found == ["opened"] for found in self.events.values()))
        self.assertIsNone(self.tracker.status(self.by_id["SIM-40"]))  # capped small yacht: watched
        self.assertIsNone(self.tracker.status(self.by_id["SIM-47"]))  # lone GPS glitch: None
        self.assertEqual(self.tracker.status(self.by_id["SIM-41"]), "New")
        self.assertEqual(self.tracker.step(self.items, 1), {})  # a repeat step adds nothing

    def test_keys_and_ids(self):
        exercise = next(item for item in self.items if item.get("exercise"))
        self.assertEqual(vessel_key(exercise), "999000001")
        self.assertEqual(self.tracker.incident(exercise)["id"], "INC-999000001-1")
        self.assertEqual(self.tracker.incident(self.by_id["SIM-45"])["id"], "INC-SIM-45-1")
        row = next(row for row in feed(self.items) if row["mmsi"] == "SIM-45")
        self.assertEqual(row["cable_id"], "dublin-holyhead")

    def test_countdown_raises_and_a_reviewed_incident_asks_for_review_again(self):
        heron = self.by_id["SIM-06"]
        self.assertEqual(heron["assessment"]["level"], "high")
        self.tracker.decide(heron, "Reviewed")
        update(self.items, 4 * 60)
        events = self.tracker.step(self.items, 4 * 60)
        self.assertEqual(events["SIM-06"], ["raised", "review_again"])
        incident = self.tracker.incident(heron)
        self.assertEqual((incident["level"], incident["peak_level"], incident["status"]), ("critical", "critical", "Reviewed"))
        self.tracker.decide(heron, "Acknowledged")
        self.assertFalse(incident["needs_review_again"])

    def test_reject_needs_a_reason_and_closes_the_incident(self):
        lark = self.by_id["SIM-41"]
        with self.assertRaises(ValueError):
            self.tracker.decide(lark, "Rejected")
        self.tracker.decide(lark, "Rejected", "Known benign activity")
        self.assertEqual(self.tracker.status(lark), "Rejected")
        self.assertIsNone(self.tracker.open_incident(lark))
        self.assertEqual(self.tracker.incident(lark)["status_reason"], "Known benign activity")
        self.assertNotIn("SIM-41", self.tracker.step(self.items, 60))  # same activity does not reopen
        with self.assertRaises(KeyError):
            self.tracker.decide(lark, "Acknowledged")
        with self.assertRaises(KeyError):
            self.tracker.decide(self.by_id["SIM-40"], "Acknowledged")  # watched: no incident

    def test_quiet_incident_suggests_close_once(self):
        tracker = Tracker()
        boat = contact("SIM-90", "medium")
        self.assertEqual(tracker.step([boat], 0), {"SIM-90": ["opened"]})
        boat["assessment"] = {"level": "low", "factors": [], "basis": "low"}
        self.assertEqual(tracker.step([boat], 60), {})
        self.assertEqual(tracker.step([boat], 60 + QUIET_CLOSE_S), {"SIM-90": ["quiet"]})
        self.assertTrue(tracker.incident(boat)["suggest_close"])
        self.assertEqual(tracker.status(boat), "New")  # nothing closes on its own
        self.assertEqual(tracker.step([boat], 120 + QUIET_CLOSE_S), {})


class ReplayTests(unittest.TestCase):
    """The board on the exercise replay clock: forwards, backwards and decisions kept."""

    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        cls.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.start = min(alert["t"] for alert in cls.alerts)

    def setUp(self):
        self.items = build_board(self.scenario, self.alerts)
        self.by_id = {item["id"]: item for item in self.items}
        self.replay = Replay(self.items, self.scenario, self.start)

    def open_ids(self):
        return {incident["id"] for incident in self.replay.tracker.state["open"].values()}

    def test_contacts_appear_at_their_raise_time_and_the_exercise_at_its_alert(self):
        self.replay.seek(self.start - 30 * 60)
        self.assertFalse(self.replay.present(self.by_id["SIM-07"]))  # raised 22 min before the alert
        self.assertTrue(self.replay.present(self.by_id["SIM-11"]))   # raised 41 min before
        self.assertTrue(self.replay.present(self.by_id["A1"]))
        self.assertEqual(self.by_id["A1"]["assessment"]["level"], "none")
        self.assertNotIn("INC-999000001-1", self.open_ids())
        events, rewound = self.replay.seek(self.start)
        self.assertFalse(rewound)
        self.assertIn("opened", events["A1"])
        self.assertIn("opened", events["SIM-07"])
        self.assertEqual(self.replay.tracker.incident(self.by_id["A1"])["opened_t"], self.start)

    def test_forward_play_raises_then_quiets_the_passing_ship(self):
        self.replay.seek(self.start)
        ship = self.by_id["SIM-48"]
        # Medium by its indicators, raised to High: no responder reaches it before its line ETA.
        self.assertEqual(self.replay.tracker.incident(ship)["level"], "high")
        self.replay.seek(self.start + 35 * 60)  # clear of the line
        incident = self.replay.tracker.incident(ship)
        self.assertEqual((incident["level"], incident["suggest_close"]), ("none", False))
        events, _ = self.replay.seek(self.start + 65 * 60)
        self.assertEqual(events["SIM-48"], ["quiet"])
        self.assertTrue(incident["suggest_close"])
        self.assertEqual(self.replay.log["SIM-48"][-1], (self.start + 65 * 60, "Quiet 30 min below Medium: close?"))

    def levels(self, identifier, minutes):
        """The story's level at each replay minute (T+minute)."""
        found = []
        for minute in minutes:
            self.replay.seek(minute * 60)
            found.append(self.by_id[identifier]["assessment"]["level"])
        return found

    def test_anchor_drag_story_is_found_by_brain_from_its_track(self):
        drag = self.by_id["SIM-50"]
        self.assertEqual(self.levels("SIM-50", (74, 90, 116, 117, 125, 145)),
                         ["none", "none", "none", "high", "critical", "high"])
        # T+145: inside the EWIC corridor, scored from its own track by the registered detectors.
        self.assertEqual(drag["cable_id"], "ewic")
        self.assertTrue(drag["observations"]["in_corridor"])
        self.assertNotIn("alert_board_simulated", drag["detectors"])
        self.replay.seek(125 * 60)
        obs = drag["observations"]
        self.assertGreaterEqual(obs["speed_drop_pct"], 20)
        self.assertLessEqual(obs["eta_min"], 30)
        self.assertNotIn("ais_gap_min", obs)  # no AIS gap: the legacy rule could not see it
        # Critical because no physical responder reaches it before the earliest ETA.
        self.assertTrue(self.replay.responses["SIM-50"]["no_response_in_time"])
        self.assertEqual(self.replay.tracker.incident(drag)["cable_id"], "ewic")
        self.assertTrue(self.replay.present(drag))
        self.assertFalse((self.replay.seek(70 * 60), self.replay.present(drag))[1])  # its track starts at T+75

    def test_holding_story_loiters_then_anchors_next_to_the_cluster(self):
        self.assertEqual(self.levels("SIM-51", (90, 125)), ["low", "medium"])
        hold = self.by_id["SIM-51"]
        self.assertGreaterEqual(hold["observations"]["loiter_hours"], 1.0)
        self.replay.seek(155 * 60)
        self.assertEqual(hold["assessment"]["level"], "high")
        self.assertTrue(hold["observations"]["anchored_near_cable"])
        self.assertEqual(hold["cable_id"], "north-dublin")
        codes = {factor["code"] for factor in hold["assessment"]["factors"]}
        self.assertTrue({"B4", "B7"} <= codes)

    def test_innocent_stories_stay_at_low_or_below(self):
        for identifier in ("SIM-52", "SIM-53"):
            item = self.by_id[identifier]
            for minute in range(90, 176, 5):
                self.replay.seek(minute * 60)
                if self.replay.present(item):
                    self.assertLessEqual(RANK[item["assessment"]["level"]], RANK["low"], (identifier, minute))
        self.assertIsNone(self.replay.tracker.incident(self.by_id["SIM-53"]))

    def test_rewind_rebuilds_and_keeps_only_earlier_decisions(self):
        self.replay.seek(self.start)
        self.replay.decide(self.by_id["SIM-01"], "Escalated", "Escalated to MRCC", to="Irish Coast Guard (MRCC)")
        self.replay.seek(self.start + 10 * 60)
        self.replay.decide(self.by_id["SIM-41"], "Rejected", "Rejected", reason="False alarm")
        self.assertEqual(self.replay.tracker.status(self.by_id["SIM-41"]), "Rejected")
        events, rewound = self.replay.seek(self.start + 5 * 60)
        self.assertTrue(rewound)
        self.assertEqual(events, {})
        self.assertEqual(self.replay.tracker.status(self.by_id["SIM-01"]), "Escalated")
        self.assertEqual(self.replay.recipients, {"SIM-01": "Irish Coast Guard (MRCC)"})
        self.assertEqual(self.replay.tracker.status(self.by_id["SIM-41"]), "New")  # that decision was later
        self.assertEqual(len(self.replay.decisions), 1)
        self.replay.seek(self.start - 60 * 60)
        self.assertIsNone(self.replay.tracker.status(self.by_id["SIM-01"]))  # not raised yet: no incident
        self.assertEqual(self.replay.decisions, [])
        with self.assertRaises(KeyError):
            self.replay.decide(self.by_id["SIM-40"], "Acknowledged", "Acknowledged")


if __name__ == "__main__":
    unittest.main()
