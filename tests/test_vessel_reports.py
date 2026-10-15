"""Analyst reports validate before sending and remain separate from detector levels."""
from copy import deepcopy
import unittest

from argus.collab_crypto import validate_payload
from argus.vessel_reports import CATEGORIES, ReportStore, make_report

VESSEL = {"id": "123456789", "name": "TEST CONTACT", "label": "simulated", "lat": 53.2, "lon": -6.1}


class VesselReportTests(unittest.TestCase):
    def test_every_category_including_other_requires_a_written_reason(self):
        for category in CATEGORIES:
            for reason in ("", " \n\t "):
                with self.subTest(category=category, reason=reason), self.assertRaises(ValueError):
                    make_report(VESSEL, category, reason)
            report = make_report(VESSEL, category, "Observed repeated turns beside the cable.")
            self.assertEqual(validate_payload("report", report), report)
        self.assertIn("Other", CATEGORIES)

    def test_received_reports_reject_invalid_fields_and_unsafe_text(self):
        original = make_report(VESSEL, "Other", "Please verify this observation.")
        invalid = [{**original, "category": []}, {**original, "category": "Unknown"},
                   {**original, "reason": " "}, {**original, "reason": "x" * 2001},
                   {**original, "reason": "hidden\u202etext"}, {**original, "created_utc": "yesterday"},
                   {**original, "created_utc": "2026-10-15T12:00:00"}, {**original, "id": "bad"},
                   {**original, "sender": "spoofed analyst"}]
        for change in ({"lat": True}, {"lon": float("nan")}, {"lat": 91}, {"label": "confirmed threat"}):
            invalid.append({**original, "vessel": {**VESSEL, **change}})
        for report in invalid:
            with self.subTest(report=report), self.assertRaises(ValueError):
                validate_payload("report", report)

    def test_duplicate_delivery_groups_vessel_and_preserves_separate_authors(self):
        report = make_report(VESSEL, "Suspicious activity", "Unexplained circling.")
        store = ReportStore()
        self.assertTrue(store.add(report, "alice", shared=True))
        self.assertFalse(store.add(deepcopy(report), "alice", shared=True))
        self.assertTrue(store.add(report, "bob", shared=True))
        self.assertEqual(len(store.grouped()), 1)
        report["reason"] = "Changed after submission"
        self.assertEqual(store.entries[0]["report"]["reason"], "Unexplained circling.")
        real = make_report({**VESSEL, "label": "real"}, "Other", "Check the received AIS contact.")
        store.add(real, "alice")
        self.assertEqual(len(store.grouped()), 2)
