"""Evaluation accounting must not use truth labels to generate alerts."""
from copy import deepcopy
import unittest

from argus.evaluation import evaluate_cases, exercise_cases, summarize


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = exercise_cases()
        cls.result = evaluate_cases(cls.cases)

    def test_baseline_and_brain_results_are_reproducible(self):
        self.assertEqual(self.result, evaluate_cases(self.cases))
        self.assertEqual(self.result["brain"]["cases"], 5)
        self.assertGreater(self.result["brain"]["vessel_hours"], 0)
        self.assertEqual(len(self.result["dataset_sha256"]), 64)
        self.assertTrue(any(r["brain_lead_s"] is not None and r["brain_lead_s"] < 0 for r in self.result["rows"]))
        self.assertTrue(any(r["brain_lead_s"] is None for r in self.result["rows"]))

    def test_unknown_and_flipped_labels_never_change_detection(self):
        cases = deepcopy(self.cases)
        for case in cases:
            case["expected_review"] = None
        result = evaluate_cases(cases)
        self.assertEqual(result["brain"]["labelled_cases"], 0)
        self.assertIsNone(result["brain"]["precision"])
        for a, b in zip(self.result["rows"], result["rows"]):
            for key in ("brain_first_s", "baseline_first_s", "brain_episodes", "baseline_episodes", "brain_lead_s"):
                self.assertEqual(a[key], b[key])
        self.assertNotEqual(result["dataset_sha256"], self.result["dataset_sha256"])

    def test_empty_evaluation_has_no_fabricated_rate(self):
        result = summarize([], "brain")
        self.assertEqual(result["alert_episodes"], 0)
        self.assertIsNone(result["episodes_per_vessel_hour"])
        self.assertIsNone(result["recall"])


if __name__ == "__main__":
    unittest.main()
