"""The signed decision log notices every change, removal or reordering and names it plainly."""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from argus.decision_log import DecisionLog, main, verify_lines


class DecisionLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "decision-log.jsonl"
        self.log = DecisionLog(self.path)
        for action, vessel in (("Acknowledged", "GREY HERON"), ("Escalated", "ORLA BREEZE"), ("Rejected", "HOLLY BAY")):
            self.log.append(operator="mykhailo", action=action, vessel=vessel, detail=f"{action} {vessel}")

    def tearDown(self):
        self.temp.cleanup()

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def write(self, lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_clean_log_verifies_with_key_and_seal(self):
        result = self.log.verify()
        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.count, 3)
        self.assertRegex(result.key, r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$")
        self.assertRegex(result.seal, r"^[0-9A-F]{4}-[0-9A-F]{4}$")
        self.assertIn("All 3 decisions verified", result.summary())
        self.assertEqual(json.loads(self.lines()[0])["kind"], "start")
        if os.name == "posix":
            self.assertEqual(self.log.key_path.stat().st_mode & 0o777, 0o600)

    def test_one_changed_letter_breaks_that_signature(self):
        lines = self.lines()
        lines[2] = lines[2].replace("ORLA BREEZE", "ORLA BREEZF")
        self.write(lines)
        result = self.log.verify()
        self.assertFalse(result.ok)
        self.assertEqual(result.problems[0], "Record 2: the signature does not match. The record was changed after signing.")
        self.assertEqual(result.bad, {2: "changed", 3: "link"})  # Record 3 only lost its link to record 2.

    def test_removed_or_reordered_records_break_the_chain(self):
        lines = self.lines()
        self.write(lines[:2] + lines[3:])
        self.assertIn("Records were removed or reordered", self.log.verify().problems[0])
        self.write([lines[0], lines[2], lines[1], lines[3]])
        self.assertIn("removed or reordered", self.log.verify().problems[0])

    def test_removing_the_last_record_changes_the_seal(self):
        seal = self.log.verify().seal
        self.write(self.lines()[:-1])
        shorter = self.log.verify()
        self.assertTrue(shorter.ok)  # Only the seal shows that the end is gone.
        self.assertNotEqual(shorter.seal, seal)

    def test_a_log_rewritten_with_another_key_is_reported(self):
        other = DecisionLog(Path(self.temp.name) / "other.jsonl")
        other.append(operator="someone", action="Rejected", vessel="ORLA BREEZE", detail="forged")
        forged = other.lines()
        self.assertTrue(verify_lines(forged).ok)  # Valid on its own, but signed by another key:
        result = verify_lines(forged, expected_key=self.log.public_key())
        self.assertFalse(result.ok)
        self.assertIn("not this computer's key", result.problems[0])

    def test_a_key_change_archives_the_old_log_and_names_it(self):
        old_seal = self.log.verify().seal
        self.log.key_path.unlink()
        fresh = DecisionLog(self.path)
        fresh.append(operator="mykhailo", action="Acknowledged", vessel="KESTREL DAWN", detail="after a new key")
        archived = [p for p in self.path.parent.iterdir() if p.name.startswith("decision-log-")]
        self.assertEqual(len(archived), 1)
        self.assertEqual(json.loads(fresh.lines()[0])["previous"], {"file": archived[0].name, "seal": old_seal})
        self.assertTrue(fresh.verify().ok)
        self.assertTrue(verify_lines(archived[0].read_text().splitlines()).ok)

    def test_unreadable_line_and_command_line_check(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["verify", str(self.path)]), 0)
        self.assertTrue(out.getvalue().startswith("OK: All 3 decisions verified"))
        lines = self.lines()
        lines[1] = lines[1][:-5]
        self.write(lines)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["verify", str(self.path)]), 1)
        self.assertIn("FAILED: Record 1 is not readable", out.getvalue())


if __name__ == "__main__":
    unittest.main()
