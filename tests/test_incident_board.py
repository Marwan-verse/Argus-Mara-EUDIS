"""Panel incidents: one incident per board contact, events for the panel, decisions via argus.incidents."""
import copy
import json
import unittest
from pathlib import Path

from argus.brain_board import build_board, update
from argus.incident_board import Tracker, feed, vessel_key
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


if __name__ == "__main__":
    unittest.main()
