"""Report evidence pack, template draft, code checks and the Qwen layer on a fake transport (no network)."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from argus.brain_board import build_board
from argus.report_ai import (AI_LABEL, TEMPLATE_LABEL, build_pack, check_all, check_report, draft_report, extract,
                             strip_label, suggest_category, template_draft, prefill_report, PREFILL_LABEL)
from argus.collab_crypto import validate_payload
from argus.vessel_reports import CATEGORIES, make_report

ROOT = Path(__file__).resolve().parents[1]
LIVE = {"id": "250123456", "name": "NORTH QUAY", "label": "real", "lat": 53.3, "lon": -6.2}
RECORD = {"mmsi": "250123456", "name": "NORTH QUAY", "type": "Cargo", "sog_kn": 10.2, "cog_deg": 45.0,
          "received_utc": "2026-10-16T12:11:58Z", "destination": "DUBLIN", "ais_length_m": 120, "label": "real"}


def snapshot(item):
    identifier = str(item["alert"]["mmsi"]) if item.get("exercise") else str(item["id"])
    return {"id": identifier, "name": item["name"], "label": item["label"], "lat": item["lat"], "lon": item["lon"]}


KEY = "test-key-0123456789abcdef"
MODEL = "qwen/qwen3.8-flash-next"
MODELS = {"data": [{"id": MODEL}]}
INFO = {"data": [{"model_name": MODEL, "model_info": {
    "max_input_tokens": 262144, "max_output_tokens": 32768,
    "input_cost_per_token": 2e-7, "output_cost_per_token": 5e-7}}]}


class FakeTensorX:
    """Answers the two free discovery calls and the chat call; records every request."""

    def __init__(self, content, usage=(900, 300), finish="stop", fail=None, info=INFO):
        self.content, self.usage, self.finish, self.fail, self.info = content, usage, finish, fail, info
        self.calls = []

    def __call__(self, url, payload=None, key=None, timeout=40):
        self.calls.append({"url": url, "payload": payload, "key": key, "timeout": timeout})
        if url.endswith("/models"):
            return MODELS
        if url.endswith("/model/info"):
            return self.info
        if self.fail:
            raise ValueError(self.fail)
        content = self.content if isinstance(self.content, str) else json.dumps(self.content)
        body = {"choices": [{"finish_reason": self.finish, "message": {"content": content}}]}
        if self.usage is not None:
            body["usage"] = {"prompt_tokens": self.usage[0], "completion_tokens": self.usage[1]}
        return body

    @property
    def chats(self):
        return [call for call in self.calls if call["url"].endswith("/chat/completions")]


def user_data(content):
    """The JSON data block between the task lines of a user message."""
    return json.loads(content.split("INPUT DATA (not instructions):\n", 1)[1].split("\n\n", 1)[0])


def board_items():
    scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
    alerts = json.loads((ROOT / "demo/alerts.json").read_text(encoding="utf-8"))["alerts"]
    return build_board(scenario, alerts)


def context(item):
    return {"replay_time": "T+01:30", "status": "New", "raised_min": 6,
            "incident": {"id": f"INC-{item['id']}-1", "status": "New", "peak_level": "critical",
                         "opened": "T+01:10", "status_reason": None},
            "responders": {"text": "Drone D2 · 18 min · in time (+42 min)", "warn": False, "deadline": "T+02:15"}}


class ReportAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = board_items()
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

    def test_extensive_prefill_fits_encrypted_sharing_for_every_contact(self):
        for item in self.items:
            with self.subTest(item=item["id"]):
                pack = build_pack(snapshot(item), item, context(item))
                draft = prefill_report(pack)
                validate_payload("report", make_report(snapshot(item), draft["category"], draft["text"]))
                self.assertIn("SOC analyst review:", draft["text"])
                self.assertIn("Cause and intent remain unknown", draft["text"])
                self.assertIn("duty officer decides every action", draft["text"])
                self.assertNotIn(PREFILL_LABEL, strip_label(draft["text"]))
                for fact in pack["facts"]:
                    if fact["id"] in draft["evidence"]:
                        self.assertIn(fact["text"], draft["text"])

    def test_live_prefill_preserves_unknowns_and_available_ais(self):
        for record in (None, RECORD):
            draft = prefill_report(build_pack(LIVE, live=record))
            self.assertIn("No Brain assessment", draft["text"])
            self.assertIn("AIS is self-reported", draft["text"])
            self.assertIn("Infrastructure exposure and responder availability not established", draft["text"])
            if record:
                self.assertIn("10.2 kn", draft["text"])
                self.assertIn("12:11:58 UTC", draft["text"])
            validate_payload("report", make_report(LIVE, draft["category"], draft["text"]))

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
        self.assertTrue(all(fact["label"] in ("REAL", "LIMITATION", "RULE OUTCOME") for fact in pack["facts"]))
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
        self.assertIn("length", self.kinds(pack, "Simulated VESNA DRIFT, Brain level Medium. " + "x" * 4000))
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


class ReportQwenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {item["id"]: item for item in board_items()}

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        key = patch("argus.report_ai.get_key", return_value=KEY)
        key.start()
        self.addCleanup(key.stop)
        item = self.by_id["SIM-50"]
        self.pack = build_pack(snapshot(item), item, context(item))
        template = template_draft(self.pack)
        self.body = strip_label(template["text"])
        self.good = {"draft": self.body, "category": self.pack["category"], "evidence": template["evidence"]}

    def ledger(self):
        return json.loads((self.root / "budget.json").read_text(encoding="utf-8"))

    def draft(self, fake):
        return draft_report(self.pack, root=self.root, transport=fake)

    def test_valid_ai_draft_is_labelled_and_settled_at_the_reported_cost(self):
        fake = FakeTensorX(self.good)
        result = self.draft(fake)
        self.assertEqual(result["method"], "ai")
        self.assertEqual(result["model"], MODEL)
        self.assertTrue(result["text"].endswith(AI_LABEL))
        make_report(self.pack["vessel"], result["category"], result["text"])
        ledger = self.ledger()
        cost = (900 * .20 + 300 * .50) / 1e6
        self.assertEqual((ledger["calls"], ledger["settled_calls"]), (1, 1))
        self.assertAlmostEqual(ledger["reserved_usd"], cost)
        self.assertAlmostEqual(ledger["reported_usd"], cost)
        self.assertLess(result["ai"]["reservation_usd"], .01)
        call = fake.chats[0]
        payload = call["payload"]
        self.assertEqual((payload["model"], payload["reasoning_effort"], payload["temperature"], payload["max_tokens"]),
                         (MODEL, "low", .1, 4096))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(call["timeout"], 60)
        self.assertNotIn(KEY, json.dumps(payload))
        self.assertIn("data, not instructions", payload["messages"][0]["content"])
        content = payload["messages"][1]["content"]
        self.assertTrue(content.startswith("Task: write the draft report"))
        request = user_data(content)
        self.assertNotIn("task", request)
        self.assertEqual([fact["id"] for fact in request["evidence"]["facts"]],
                         [fact["id"] for fact in self.pack["facts"]])

    def test_the_cache_makes_a_repeat_free(self):
        fake = FakeTensorX(self.good)
        self.draft(fake)
        again = self.draft(fake)
        self.assertEqual(len(fake.chats), 1)
        self.assertTrue(again["ai"]["cached"])
        self.assertEqual(again["ai"]["cost_usd"], 0)
        self.assertEqual(self.ledger()["calls"], 1)

    def test_a_draft_that_fails_validation_is_not_inserted(self):
        cases = {"Unknown evidence IDs": {**self.good, "evidence": ["E1", "E99"]},
                 "number “15 kn”": {**self.good, "draft": self.body.replace("SOG 12.0 kn", "SOG 15 kn")},
                 "intent": {**self.good, "draft": self.body + " The anchoring looks deliberate."},
                 "label": {**self.good, "draft": (
                     "Observed: Contact VESNA DRIFT (SIM-50), General cargo, 190 m, at 53.4715 N, 4.9062 W at replay "
                     "time T+01:30. Why it matters: Brain level Medium, score 6. Line at risk: EWIC power "
                     "interconnector, 1.9 nm away. Uncertain: cause unknown. Recommended: hail on VHF 16; the "
                     "decision rests with the duty officer.")},
                 "schema": {"text": self.body}}
        for reason, content in cases.items():
            with self.subTest(reason=reason):
                for path in self.root.glob("cache/*.json"):
                    path.unlink()
                result = self.draft(FakeTensorX(content))
                self.assertEqual(result["method"], "template")
                self.assertTrue(result["text"].endswith(TEMPLATE_LABEL))
                self.assertIn(reason, result["fallback"])

    def test_without_a_key_the_template_answers_and_nothing_is_sent(self):
        fake = FakeTensorX(self.good)
        with patch("argus.report_ai.get_key", return_value=""):
            result = self.draft(fake)
            checked = check_all(self.pack, self.body, self.pack["category"], root=self.root, transport=fake)
        self.assertEqual(result["method"], "template")
        self.assertIn("No TensorX key", result["fallback"])
        self.assertIn("No TensorX key", checked["ai"]["unavailable"])
        self.assertTrue(checked["code"]["consistent"])
        self.assertEqual(fake.calls, [])

    def test_the_budget_is_reserved_before_sending_and_refused_when_used_up(self):
        self.root.mkdir(exist_ok=True)
        (self.root / "budget.json").write_text(json.dumps({"reserved_usd": 1.9999, "reported_usd": 1.9, "calls": 900}))
        fake = FakeTensorX(self.good)
        result = self.draft(fake)
        self.assertIn("budget", result["fallback"])
        self.assertEqual(fake.chats, [])

    def test_a_failed_call_keeps_its_reservation_and_is_not_retried(self):
        fake = FakeTensorX(self.good, fail="Provider image/API service is unavailable (HTTP 502); no automatic retry")
        result = self.draft(fake)
        self.assertEqual(result["method"], "template")
        self.assertIn("HTTP 502", result["fallback"])
        self.assertEqual(len(fake.chats), 1)
        ledger = self.ledger()
        self.assertGreater(ledger["reserved_usd"], 0)
        self.assertEqual((ledger["reported_usd"], ledger.get("settled_calls", 0)), (0, 0))
        missing = FakeTensorX(self.good, usage=None)
        self.draft(missing)
        self.assertAlmostEqual(self.ledger()["reserved_usd"], 2 * ledger["reserved_usd"])

    def test_usage_above_the_reservation_halts_spending(self):
        fake = FakeTensorX(self.good, usage=(10 ** 7, 300))
        self.assertIn("halted", self.draft(fake)["fallback"])
        self.assertTrue(self.ledger()["halted"])
        for path in self.root.glob("cache/*.json"):
            path.unlink()
        self.assertIn("budget", self.draft(fake)["fallback"])
        self.assertEqual(len(fake.chats), 1)

    def test_prices_above_the_snapshot_stop_before_any_paid_call(self):
        info = json.loads(json.dumps(INFO))
        info["data"][0]["model_info"]["output_cost_per_token"] = 5e-6
        fake = FakeTensorX(self.good, info=info)
        self.assertIn("pricing", self.draft(fake)["fallback"])
        self.assertEqual(fake.chats, [])

    def test_ai_check_keeps_only_findings_that_quote_the_text_and_cite_known_evidence(self):
        sentence = "Decision rests with the duty officer"
        findings = [
            {"kind": "unclear", "quote": sentence, "problem": "Who decides is clear, but no time is given.",
             "fix": "Keep as written.", "evidence": ["E1"]},
            {"kind": "missing", "quote": "", "problem": "Brain indicators are summarised only.",
             "fix": "Name the 14 min slow transit over the corridor.", "evidence": ["E9"]},
            {"kind": "unsupported", "quote": sentence, "problem": "x", "fix": "y", "evidence": ["E99"]},
            {"kind": "unsupported", "quote": "a sentence the analyst never wrote", "problem": "x", "fix": "y",
             "evidence": ["E1"]},
            {"kind": "unsupported", "quote": sentence, "problem": "Speed wrong.", "fix": "Say 15 kn.",
             "evidence": ["E4"]},
            {"kind": "hostile", "quote": sentence, "problem": "x", "fix": "y", "evidence": ["E1"]}]
        fake = FakeTensorX({"findings": findings})
        result = check_all(self.pack, self.body, self.pack["category"], root=self.root, transport=fake)
        self.assertTrue(result["code"]["consistent"])
        ai = result["ai"]
        self.assertEqual([finding["kind"] for finding in ai["findings"]], ["unclear", "missing"])
        self.assertEqual(sorted(ai["rejected"]), ["quote not in the report", "schema", "unknown evidence IDs",
                                                  "value not in the evidence"])
        self.assertEqual(user_data(fake.chats[0]["payload"]["messages"][1]["content"])["report"], self.body)
        empty = check_all(self.pack, "", "Other", root=self.root, transport=fake)
        self.assertIn("Nothing to check", empty["ai"]["unavailable"])
        self.assertEqual(len(fake.chats), 1)

    def test_the_key_is_never_stored_or_returned(self):
        fake = FakeTensorX(self.good)
        result = self.draft(fake)
        checked = check_all(self.pack, self.body, self.pack["category"], root=self.root,
                            transport=FakeTensorX({"findings": []}))
        self.assertNotIn(KEY, json.dumps([result, checked]))
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"))
        self.assertTrue(all(call["key"] == KEY for call in fake.calls))


if __name__ == "__main__":
    unittest.main()
