"""Checks that the shared-file guard catches cross-workstream breakage."""

import copy
import json
import unittest
from pathlib import Path

from argus.contracts import validate_alerts, validate_scenario


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        cls.alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))

    def test_committed_demo_files_are_compatible(self):
        validate_scenario(self.scenario)
        validate_alerts(self.alerts, self.scenario)

    def test_out_of_range_latitude_is_caught(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["cables"][0]["path"][0] = [-181, 53]
        with self.assertRaisesRegex(ValueError, "latitude"):
            validate_scenario(scenario)

    def test_alert_cannot_reference_a_missing_cable(self):
        alerts = copy.deepcopy(self.alerts)
        alerts["alerts"][0]["segment_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "absent"):
            validate_alerts(alerts, self.scenario)

    def test_response_badge_must_match_earliest_eta(self):
        alerts = copy.deepcopy(self.alerts)
        alerts["alerts"][0]["options"][0]["in_time"] = False
        with self.assertRaisesRegex(ValueError, "in_time"):
            validate_alerts(alerts, self.scenario)


if __name__ == "__main__":
    unittest.main()
