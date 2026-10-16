"""Report evidence pack, template draft and the code layer of Check report (no network, no tkinter)."""
import json
import re
import unittest
from pathlib import Path

from argus.brain_board import build_board
from argus.report_ai import (TEMPLATE_LABEL, build_pack, check_report, extract, strip_label, suggest_category,
                             template_draft)
from argus.vessel_reports import CATEGORIES, make_report

ROOT = Path(__file__).resolve().parents[1]
LIVE = {"id": "250123456", "name": "NORTH QUAY", "label": "real", "lat": 53.3, "lon": -6.2}
RECORD = {"mmsi": "250123456", "name": "NORTH QUAY", "type": "Cargo", "sog_kn": 10.2, "cog_deg": 45.0,
          "received_utc": "2026-10-16T12:11:58Z", "destination": "DUBLIN", "ais_length_m": 120, "label": "real"}


def snapshot(item):
    identifier = str(item["alert"]["mmsi"]) if item.get("exercise") else str(item["id"])
    return {"id": identifier, "name": item["name"], "label": item["label"], "lat": item["lat"], "lon": item["lon"]}


def context(item):
    return {"replay_time": "T+01:30", "status": "New", "raised_min": 6,
            "incident": {"id": f"INC-{item['id']}-1", "status": "New", "peak_level": "critical",
                         "opened": "T+01:10", "status_reason": None},
            "responders": {"text": "Drone D2 · 18 min · in time (+42 min)", "warn": False, "deadline": "T+02:15"}}


class ReportAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
        alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
        cls.items = build_board(scenario, alerts)
        cls.by_id = {item["id"]: item for item in cls.items}

    def pack(self, identifier="SIM-50", with_context=True):
        item = self.by_id[identifier]
        return build_pack(snapshot(item), item, context(item) if with_context else {})

    def kinds(self, pack, text, category=None):
        return [finding["kind"] for finding in check_report(pack, text, category or pack["category"])["findings"]]

    def test_every_fact_has_an_id_and_a_label_and_the_level_is_brains(self):
        pack = self.pack("SIM-41")
        self.assertEqual([fact["id"] for fact in pack["facts"]], [f"E{n}" for n in range(1, len(pack["facts"]) + 1)])
        self.assertTrue(all(fact["label"] and fact["text"] for fact in pack["facts"]))
        self.assertEqual(pack["level"]["level"], self.by_id["SIM-41"]["assessment"]["level"])
        self.assertTrue(pack["simulated"])
        self.assertEqual(pack["facts"][0]["label"], "SIMULATED")
        self.assertIn("INC-SIM-41-1", " ".join(fact["text"] for fact in pack["facts"]))

    def test_template_draft_passes_its_own_check_for_every_board_contact(self):
        for item in self.items:
            for with_context in (True, False):
                with self.subTest(item=item["id"], context=with_context):
                    pack = build_pack(snapshot(item), item, context(item) if with_context else {})
                    draft = template_draft(pack)
                    self.assertEqual(check_report(pack, draft["text"], draft["category"])["findings"], [])
                    self.assertLessEqual(len(draft["text"]), 2000)
                    self.assertIn(draft["category"], CATEGORIES)
                    self.assertTrue(draft["text"].endswith(TEMPLATE_LABEL))
                    known = {fact["id"] for fact in pack["facts"]}
                    self.assertTrue(set(draft["evidence"]) <= known)
                    make_report(snapshot(item), draft["category"], draft["text"])  # the report format accepts it

    def test_draft_order_is_observed_why_uncertain_recommended(self):
        text = template_draft(self.pack("SIM-50"))["text"]
        heads = [text.index(head) for head in ("Observed:", "Why it matters:", "Uncertain:", "Recommended:")]
        self.assertEqual(heads, sorted(heads))
        self.assertIn("Brain level Medium, score 6", text)
        self.assertIn("not evidence of hostile intent", text)

    def test_wrong_times_positions_numbers_names_ids_and_level_are_found(self):
        pack = self.pack("SIM-50")
        text = ("Simulated contact VESNA DRIFT (SIM-50) at 53.60 N, 4.90 W at T+02:10 and 14:05 UTC, doing 15 kn, "
                "3 nm from EWIC. Brain level High. Also seen with NORTHERN STAR, MMSI 123456789.")
        kinds = self.kinds(pack, text)
        for kind in ("position", "time", "number", "name", "identity", "level"):
            self.assertIn(kind, kinds)
        self.assertEqual(kinds.count("time"), 2)
        self.assertEqual(kinds.count("number"), 2)

    def test_values_from_the_evidence_pass_with_rounding(self):
        pack = self.pack("SIM-50")
        text = ("Simulated contact VESNA DRIFT at 53.47 N, 4.91 W, replay time T+01:30, 2 nm from the EWIC line, "
                "SOG 12 kn. Brain level Medium; incident INC-SIM-50-1 opened T+01:10.")
        self.assertEqual(self.kinds(pack, text), [])

    def test_intent_needs_evidence_but_a_negated_intent_word_passes(self):
        pack = self.pack("SIM-50")
        base = "Simulated contact VESNA DRIFT, Brain level Medium. "
        self.assertEqual(self.kinds(pack, base + "This is deliberate sabotage of the cable."), ["intent", "intent"])
        self.assertEqual(self.kinds(pack, base + "There is no evidence of hostile intent or sabotage."), [])
        finding = check_report(pack, base + "A hostile vessel.", pack["category"])["findings"][0]
        self.assertTrue(finding["evidence"])

    def test_simulated_must_be_called_simulated_and_real_must_not(self):
        pack = self.pack("SIM-50")
        self.assertIn("label", self.kinds(pack, "VESNA DRIFT slowing near EWIC, Brain level Medium."))
        live = build_pack(LIVE, live=RECORD)
        self.assertFalse(live["simulated"])
        self.assertIn("label", self.kinds(live, "Simulated contact NORTH QUAY slowing."))
        self.assertEqual(self.kinds(live, "NORTH QUAY slowed to 10.2 kn off Dublin at 12:11 UTC."), [])

    def test_category_must_be_supported_and_is_suggested_from_the_groups(self):
        pack = self.pack("SIM-50")
        self.assertEqual(pack["category"], "Infrastructure concern")
        text = "Simulated contact VESNA DRIFT, Brain level Medium."
        self.assertEqual(self.kinds(pack, text, "AIS / identity concern"), ["category"])
        self.assertEqual(self.kinds(pack, text, "Other"), [])
        self.assertEqual(suggest_category(self.pack("SIM-49")), "Other")
        self.assertEqual(self.pack("SIM-49")["level"]["level"], "none")

    def test_live_vessel_gets_a_smaller_pack_and_a_draft_with_placeholders(self):
        pack = build_pack(LIVE, live=RECORD)
        self.assertEqual(pack["kind"], "live")
        self.assertIsNone(pack["level"])
        self.assertTrue(all(fact["label"] in ("REAL", "LIMITATION") for fact in pack["facts"]))
        draft = template_draft(pack)
        self.assertIn("No Brain assessment", draft["text"])
        self.assertIn("12:11:58 UTC", draft["text"])
        result = check_report(pack, draft["text"], draft["category"])
        self.assertEqual({finding["kind"] for finding in result["findings"]}, {"placeholder"})
        self.assertIn("category is not checked", result["notes"][0])
        minimal = build_pack({"id": "123456789", "name": "TEST CONTACT", "label": "simulated", "lat": 53.2,
                              "lon": -6.1})
        self.assertEqual(minimal["kind"], "minimal")
        self.assertTrue(minimal["simulated"])

    def test_empty_long_and_missing_parts_are_reported(self):
        pack = self.pack("SIM-50")
        self.assertEqual(self.kinds(pack, "  \n"), ["missing"])
        self.assertIn("length", self.kinds(pack, "Simulated VESNA DRIFT, Brain level Medium. " + "x" * 2000))
        missing = check_report(pack, "A simulated vessel slowed near the line.", "Other")["findings"]
        self.assertEqual([finding["kind"] for finding in missing], ["missing", "missing"])

    def test_extract_reads_replay_utc_dtg_and_coordinate_formats(self):
        found = extract("At T+01:30 (161212Z), 12:11 UTC, T+29 min, 53°28.3'N 004°54.4'W and 53.4715, -4.9062.")
        self.assertEqual([entry["minutes"] for entry in found["replay"]], [90, 29])
        self.assertEqual([entry["hm"] for entry in found["clock"]], [(12, 12), (12, 11)])
        self.assertEqual(len(found["coords"]), 2)
        self.assertAlmostEqual(found["coords"][0]["lat"], 53.4717, places=3)
        self.assertEqual(found["numbers"], [])

    def test_the_label_line_is_not_part_of_the_checked_body(self):
        draft = template_draft(self.pack("SIM-50"))["text"]
        self.assertNotIn(TEMPLATE_LABEL, strip_label(draft))
        self.assertFalse(re.search(r"\[[^\]]+\]", draft))


if __name__ == "__main__":
    unittest.main()
