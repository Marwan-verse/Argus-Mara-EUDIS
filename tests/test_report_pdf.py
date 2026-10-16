"""PDF export of the analyst report: content blocks from the pack, check status and a valid multi-page PDF."""
import re
import tempfile
import unittest
from pathlib import Path

from argus.report_ai import build_pack, check_report, template_draft
from argus.report_pdf import PAGE, blocks, check_status, render, save_pdf, text_hash
from tests.test_report_ai import LIVE, RECORD, board_items, context, snapshot


class ReportPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        item = {item["id"]: item for item in board_items()}["SIM-41"]
        cls.pack = build_pack(snapshot(item), item, context(item))
        cls.draft = template_draft(cls.pack)
        cls.generation = {key: cls.draft[key] for key in ("method", "model", "generated_utc", "evidence")}

    def check(self, text):
        return {"text_hash": text_hash(text),
                "result": {"code": check_report(self.pack, text, self.pack["category"]),
                           "ai": {"layer": "ai", "unavailable": "No TensorX key on this computer"}}}

    def texts(self, found, style=None):
        return [text for kind, text in found if style is None or kind == style]

    def test_blocks_hold_the_text_check_status_and_a_code_built_appendix(self):
        text = self.draft["text"]
        found = blocks(self.pack, text, self.pack["category"], check=self.check(text), generation=self.generation,
                       created_utc="2026-10-16T13:00:00+00:00")
        joined = "\n".join(self.texts(found))
        self.assertEqual(self.texts(found, "title"), ["Analyst report — draft for review"])
        self.assertIn("SIMULATED DATA", self.texts(found, "banner")[0])
        self.assertIn("Vessel: SEA LARK · SIM-41 · simulated", joined)
        self.assertIn("Incident INC-SIM-41-1", joined)
        self.assertIn("Template draft from system data · reviewed by analyst", joined)
        self.assertIn("Code check (exact, no AI): consistent with system data.", joined)
        self.assertIn("AI check (meaning): not run", joined)
        self.assertEqual([heading.split(" · ")[0] for heading in self.texts(found, "heading")],
                         ["Report", "Check status", "Appendix A", "Appendix B", "Appendix C"])
        for fact in self.pack["facts"]:
            self.assertIn(f"{fact['id']} [{fact['label']}]", joined)
        self.assertIn("Method: Template draft written by code from the evidence (no AI).", joined)
        self.assertIn("Human review required. No operational action has been triggered.", joined)

    def test_an_edit_after_the_check_is_reported_as_unchecked(self):
        check = self.check(self.draft["text"])
        self.assertIn("consistent", check_status(check, self.draft["text"])[0])
        self.assertIn("Not checked since the last edit", check_status(check, self.draft["text"] + " More.")[0])
        self.assertIn("Not checked", check_status(None, self.draft["text"])[0])
        found = blocks(self.pack, "Analyst's own words.", "Other")
        self.assertIn("Method: Written by the analyst (no draft tool used).", self.texts(found))

    def test_pdf_is_a4_paginated_and_labelled(self):
        long_text = "\n".join([self.draft["text"]] * 4)
        pages = render(blocks(self.pack, long_text, self.pack["category"]), "footer")
        self.assertGreaterEqual(len(pages), 3)
        self.assertTrue(all(page.size == PAGE for page in pages))
        with tempfile.TemporaryDirectory() as folder:
            path = save_pdf(Path(folder) / "report.pdf", self.pack, long_text, self.pack["category"],
                            check=self.check(long_text), generation=self.generation)
            raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertEqual(int(re.search(rb"/Count (\d+)", raw).group(1)), len(pages))
        self.assertTrue(b"/Title" in raw and b"/Author" in raw)

    def test_live_vessel_pdf_says_real_and_no_brain_assessment(self):
        pack = build_pack(LIVE, live=RECORD)
        found = blocks(pack, "NORTH QUAY slowed off Dublin.", "Other")
        joined = "\n".join(self.texts(found))
        self.assertIn("REAL AIS", self.texts(found, "banner")[0])
        self.assertIn("No Brain assessment", joined)
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(save_pdf(Path(folder) / "live.pdf", pack, "NORTH QUAY slowed off Dublin.", "Other")
                            .read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
