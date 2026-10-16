"""D86: TensorX calls settle at their reported cost; uncertain calls keep the reservation."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from argus.satellite_ai import PILOT_USD, read_ledger, visual_analysis
from argus.satellite_workspace import DEFAULT_QUESTION
from test_satellite import FakeTensorX, fixture

# FakeTensorX advertises 256,000 input tokens and reports 300 prompt + 100 completion tokens.
RESERVE = (256000*.20+1536*.50)/1e6
ACTUAL = (300*.20+100*.50)/1e6


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        _, self.scene, self.image = fixture(Path(self.folder.name)/'satellite')
        self.root = Path(self.folder.name)/'ai'
        self.key = patch('argus.satellite_ai.get_key', return_value='synthetic-key')
        self.key.start()

    def tearDown(self):
        self.key.stop()
        self.folder.cleanup()

    def analyse(self, transport, question=DEFAULT_QUESTION):
        return visual_analysis(self.root, self.scene, self.image, question, transport=transport)

    def test_a_verified_call_is_settled_at_its_reported_cost(self):
        result = self.analyse(FakeTensorX())
        ledger = read_ledger(self.root)
        self.assertAlmostEqual(result['reported_cost_usd'], ACTUAL)
        self.assertAlmostEqual(ledger['reserved_usd'], ACTUAL)
        self.assertAlmostEqual(ledger['reported_usd'], ACTUAL)
        self.assertEqual((ledger['calls'], ledger['settled_calls']), (1, 1))

    def test_an_uncertain_call_keeps_its_whole_reservation(self):
        fake = FakeTensorX()
        fake.fail = True  # a timeout: the provider may have charged it
        with self.assertRaises(ValueError):
            self.analyse(fake)
        ledger = read_ledger(self.root)
        self.assertAlmostEqual(ledger['reserved_usd'], RESERVE)
        self.assertNotIn('settled_calls', ledger)

    def test_a_response_without_usage_keeps_its_whole_reservation(self):
        fake = FakeTensorX()
        def no_usage(url, **kwargs):
            result = fake(url, **kwargs)
            if url.endswith('/chat/completions'):
                result.pop('usage')
            return result
        with self.assertRaisesRegex(ValueError, 'reservation retained'):
            self.analyse(no_usage)
        self.assertAlmostEqual(read_ledger(self.root)['reserved_usd'], RESERVE)

    def test_usage_above_the_limits_halts_and_releases_nothing(self):
        fake = FakeTensorX()
        def oversized(url, **kwargs):
            result = fake(url, **kwargs)
            if url.endswith('/chat/completions'):
                result['usage']['prompt_tokens'] = 300000
            return result
        with self.assertRaisesRegex(ValueError, 'halted'):
            self.analyse(oversized)
        ledger = read_ledger(self.root)
        self.assertTrue(ledger['halted'])
        self.assertAlmostEqual(ledger['reserved_usd'], RESERVE)
        with self.assertRaisesRegex(ValueError, 'exhausted or halted'):
            self.analyse(FakeTensorX(), 'Count the visible vessels again')

    def test_far_more_checks_than_the_old_reservations_fit_under_the_ceiling(self):
        calls = int(PILOT_USD/RESERVE)+25  # the old accounting stopped before this many
        fake = FakeTensorX()
        for index in range(calls):
            self.analyse(fake, f'Find visible vessels, pass {index}')  # a new question, so no cache hit
        ledger = read_ledger(self.root)
        self.assertEqual((ledger['calls'], ledger['settled_calls']), (calls, calls))
        self.assertAlmostEqual(ledger['reserved_usd'], calls*ACTUAL, places=6)
        self.assertLess(ledger['reserved_usd'], 1)

    def test_a_tampered_settled_count_is_refused(self):
        self.root.mkdir()
        (self.root/'budget.json').write_text(json.dumps({'reserved_usd': 0, 'reported_usd': 0, 'calls': 1, 'settled_calls': 2}))
        with self.assertRaisesRegex(ValueError, 'Invalid budget ledger'):
            read_ledger(self.root)


if __name__ == '__main__':
    unittest.main()
