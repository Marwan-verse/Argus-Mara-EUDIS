"""One stable incident per vessel: no duplicates, human-owned status, quiet suggestion and reopening."""

import copy
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from argus.incidents import (QUIET_CLOSE_S, all_incidents, new_state, run_scenario, set_status,
                             update_incidents)

ROOT = Path(__file__).resolve().parents[1]
MMSI = 999000099
INC = f"INC-{MMSI}-1"
ACTIVE = ("medium", "high", "critical")


def item(level, mmsi=MMSI, cable="cable-test"):
    factors = [{"code": "P2", "group": "proximity", "points": 3, "text": f"{level} test reason"}]
    return {"mmsi": mmsi, "name": "TEST VESSEL", "label": "simulated", "cable_id": cable,
            "assessment": {"level": level, "basis": f"{level} basis", "factors": factors}}


def step(state, level, now, **kwargs):
    return update_incidents(state, [item(level, **kwargs)], now)


class IncidentTests(unittest.TestCase):
    def test_low_is_observation_not_incident(self):
        state = step(new_state(), "low", 0)
        self.assertEqual(state["open"], {})

    def test_repeated_identical_updates_keep_one_incident(self):
        state = new_state()
        for now in range(0, 3600, 60):
            step(state, "high", now)
        self.assertEqual([inc["id"] for inc in all_incidents(state)], [INC])
        incident = state["open"][str(MMSI)]
        self.assertEqual(len(incident["history"]), 1)
        self.assertEqual((incident["opened_t"], incident["updated_t"]), (0, 3540))

    def test_history_records_only_level_changes_and_peak(self):
        state = new_state()
        for now, level in [(0, "low"), (60, "medium"), (120, "medium"), (180, "high"), (240, "medium")]:
            step(state, level, now)
        incident = state["open"][str(MMSI)]
        self.assertEqual([(h["t"], h["from"], h["to"]) for h in incident["history"]],
                         [(60, "low", "medium"), (180, "medium", "high"), (240, "high", "medium")])
        self.assertEqual((incident["level"], incident["peak_level"]), ("medium", "high"))

    def test_demo_scenario_has_one_incident_rising_to_high_then_critical(self):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        incidents = all_incidents(run_scenario(scenario, 60))
        ours = [inc for inc in incidents if inc["mmsi"] == 999000001]
        self.assertEqual(len(ours), 1)
        incident = ours[0]
        # High at the A1 alert; Critical once cable_risk's live ETA to the reachable section is 30 min or less.
        self.assertEqual(incident["peak_level"], "critical")
        self.assertEqual(incident["cable_id"], "cable-irish-sea-1")
        self.assertTrue(any(h["to"] == "high" and h["t"] <= 5400 for h in incident["history"]))
        self.assertTrue(any(h["to"] == "critical" and h["t"] > 5400 for h in incident["history"]))
        self.assertEqual(incident["status"], "New")

    def test_analyst_status_survives_updates(self):
        state = step(new_state(), "medium", 0)
        set_status(state, INC, "Reviewed")
        for now in range(60, 600, 60):
            step(state, "medium", now)
        incident = state["open"][str(MMSI)]
        self.assertEqual(incident["status"], "Reviewed")
        self.assertFalse(incident["needs_review_again"])

    def test_rise_after_acknowledged_needs_review_again(self):
        state = step(new_state(), "medium", 0)
        set_status(state, INC, "Acknowledged")
        step(state, "high", 60)
        incident = state["open"][str(MMSI)]
        self.assertEqual(incident["status"], "Acknowledged")
        self.assertTrue(incident["needs_review_again"])
        set_status(state, INC, "Escalated")
        self.assertFalse(incident["needs_review_again"])
        step(state, "high", 120)
        self.assertFalse(incident["needs_review_again"])

    def test_rise_while_new_does_not_flag(self):
        state = step(new_state(), "medium", 0)
        step(state, "critical", 60)
        self.assertFalse(state["open"][str(MMSI)]["needs_review_again"])

    def test_suggest_close_after_thirty_quiet_minutes_only(self):
        state = step(new_state(), "high", 0)
        step(state, "low", 600)
        incident = state["open"][str(MMSI)]
        self.assertEqual(incident["quiet_since_t"], 600)
        step(state, "none", 600 + QUIET_CLOSE_S - 60)
        self.assertFalse(incident["suggest_close"])
        step(state, "none", 600 + QUIET_CLOSE_S)
        self.assertTrue(incident["suggest_close"])
        self.assertIn(str(MMSI), state["open"])
        self.assertEqual(incident["reasons"], ["P2: high test reason"])
        step(state, "medium", 600 + QUIET_CLOSE_S + 60)
        self.assertEqual((incident["suggest_close"], incident["quiet_since_t"]), (False, None))

    def test_boundary_hovering_does_not_flicker(self):
        state = new_state()
        for index, now in enumerate(range(0, 7200, 60)):
            step(state, "medium" if index % 2 == 0 else "low", now)
        self.assertEqual(len(all_incidents(state)), 1)
        self.assertFalse(state["open"][str(MMSI)]["suggest_close"])

    def test_rejected_then_active_again_opens_new_incident(self):
        state = step(new_state(), "high", 0)
        set_status(state, INC, "Rejected", reason="Authorised operation")
        self.assertEqual(state["open"], {})
        step(state, "high", 60)
        self.assertEqual(state["open"], {}, "same activity continues: the rejection holds")
        step(state, "low", 120)
        step(state, "medium", 180)
        reopened = state["open"][str(MMSI)]
        self.assertEqual(reopened["id"], f"INC-{MMSI}-2")
        self.assertEqual(reopened["reopened_from"], INC)
        self.assertEqual(reopened["status"], "New")
        closed = state["closed"][0]
        self.assertEqual((closed["status"], closed["status_reason"], closed["closed_t"]),
                         ("Rejected", "Authorised operation", 0))

    def test_rejected_while_quiet_reopens_on_next_rise(self):
        state = step(new_state(), "high", 0)
        step(state, "low", 60)
        set_status(state, INC, "Rejected", reason="False alarm")
        step(state, "medium", 120)
        self.assertEqual(state["open"][str(MMSI)]["reopened_from"], INC)

    def test_status_validation(self):
        state = step(new_state(), "medium", 0)
        with self.assertRaises(ValueError):
            set_status(state, INC, "Closed")
        with self.assertRaises(ValueError):
            set_status(state, INC, "Rejected")
        with self.assertRaises(ValueError):
            set_status(state, INC, "Reviewed", reason="False alarm")
        with self.assertRaises(KeyError):
            set_status(state, f"INC-{MMSI}-7", "Reviewed")

    def test_time_cannot_go_backwards(self):
        state = step(new_state(), "medium", 600)
        with self.assertRaises(ValueError):
            step(state, "medium", 540)

    def test_state_is_json_ready(self):
        state = step(new_state(), "high", 0)
        set_status(state, INC, "Reviewed")
        self.assertEqual(json.loads(json.dumps(state)), state)

    def test_fifteen_thousand_vessels_per_step(self):
        levels = ("none", "low", "medium", "high", "critical")
        fleet = [item(levels[n % 5], mmsi=200000000 + n) for n in range(15000)]
        later = copy.deepcopy(fleet)
        for entry in later[::7]:
            entry["assessment"]["level"] = "high"
        state = new_state()
        start = time.perf_counter()
        update_incidents(state, fleet, 0)
        update_incidents(state, later, 60)
        elapsed = time.perf_counter() - start
        print(f" [15000 vessels, 2 steps: {elapsed * 1000:.0f} ms]", end=" ", file=sys.stderr)
        active = {e["mmsi"] for e in fleet + later if e["assessment"]["level"] in ACTIVE}
        self.assertEqual(len(state["open"]), len(active))

    def test_cli_writes_incidents_and_protects_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "incidents.json"
            run = subprocess.run([sys.executable, "-m", "argus.incidents", "--scenario", "demo/scenario.json",
                                  "--step", "60", "--output", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([inc["id"] for inc in data["incidents"]], ["INC-999000001-1"])
        refused = subprocess.run([sys.executable, "-m", "argus.incidents", "--output", "demo/alerts.json"],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)


if __name__ == "__main__":
    unittest.main()
