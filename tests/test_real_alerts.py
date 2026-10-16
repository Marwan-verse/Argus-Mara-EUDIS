"""D107: real alerts between live AIS checks: bands, decisions, episodes and the signed log (no window)."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from argus.decision_log import DecisionLog
from argus.explain import explain, source
from argus.levels import LEVEL_NAMES
from argus.live_alerts import LiveTracks
from desktop_real_alerts import EPISODE_GAP_S, FORGET_S, RealAlerts, check

from test_live_alerts import IN_PORT, LOITERER, NOW, STATIC, TRANSIT, FakeDatabase, packet


def checked(*tracks, now=NOW, rpc=None):
    live = LiveTracks(rpc=rpc or FakeDatabase(packet(*tracks, static=STATIC)))
    with patch('argus.supabase_ais.linked', return_value=True), patch('argus.watchlist_data.load', return_value=None):
        return check(live, 'workspace', now=now)


BASE = checked(LOITERER)['items'][0]  # TEST LOITERER: two hours slow inside the Dublin–Holyhead corridor


def alert(level='high', score=9, raised_t=NOW - 1800):
    item = copy.deepcopy(BASE)
    item['assessment'].update(level=level, level_name=LEVEL_NAMES[level], score=score)
    item['raised_t'] = raised_t
    return item


def answer(*items, at=NOW):
    return {'state': 'ok', 'items': list(items), 'checked_t': at, 'ships': 2, 'near': 2, 'skipped': 0,
            'assessed': 2, 'truncated': False, 'seconds': 0.2}


ID = 'REAL-250000001'


class CheckTests(unittest.TestCase):
    def test_the_rules_run_on_real_ships_and_the_check_says_what_it_saw(self):
        result = checked(LOITERER, TRANSIT, IN_PORT)
        self.assertEqual(result['state'], 'ok')
        self.assertEqual([item['id'] for item in result['items']], [ID])
        self.assertEqual((result['ships'], result['assessed'], result['skipped']), (3, 2, 1))
        self.assertEqual(result['near'], 3)  # the harbour craft was near a route too
        self.assertEqual(BASE['label'], 'real')

    def test_a_computer_not_linked_or_a_failing_database_is_reported_not_raised(self):
        with patch('argus.supabase_ais.linked', return_value=False):
            self.assertEqual(check(LiveTracks(rpc=FakeDatabase()), 'workspace'), {'state': 'unlinked'})

        def missing(_payload):
            raise ValueError('Supabase request failed (HTTP 404)')
        result = checked(rpc=missing)
        self.assertEqual(result['state'], 'error')
        self.assertIn('argus_recent_tracks may not be installed', result['error'])

    def test_real_alerts_are_labelled_real_live_ais_in_the_review_window(self):
        about = source(BASE)
        self.assertEqual((about['tag'], about['long_tag'], about['short']), ('REAL', 'REAL · LIVE AIS', 'live AIS'))
        tags = [tag for tag, _text in explain(BASE)['labels']]
        self.assertEqual(tags[:4], ['SOURCE', 'REAL', 'ILLUSTRATIVE', 'ASSUMPTION'])
        self.assertNotIn('SIMULATED', tags)
        self.assertEqual(source({'id': 'SIM-01'})['tag'], 'SIM')


class RealAlertTests(unittest.TestCase):
    def setUp(self):
        self.real = RealAlerts()

    def test_an_alert_takes_its_level_band_and_only_a_human_sets_its_status(self):
        self.assertEqual(self.real.update(answer(alert())), {ID: 'new'})
        self.assertEqual((self.real.band(ID), self.real.detail(ID)), ('high', 'New · High 9'))
        self.assertEqual(self.real.items[ID]['track'][0], (LOITERER[-90][2], LOITERER[-90][3]))  # (lat, lon) points
        self.assertEqual(self.real.update(answer(alert(), at=NOW + 300)), {})
        self.assertEqual(self.real.state[ID]['status'], 'New')  # a check never sets a status
        self.real.decide(ID, 'Acknowledged', 'Acknowledged; monitoring', now=NOW + 310)
        self.assertEqual((self.real.band(ID), self.real.detail(ID)), ('high', 'Acknowledged · High 9'))
        self.real.update(answer(alert('low', 4), at=NOW + 600))
        self.assertEqual(self.real.band(ID), 'low')  # folded under LOW with the rest of the low band
        self.assertIn('Level fell to Low 4', [text for _t, text in self.real.log_lines(ID)])

    def test_a_rise_asks_for_review_again_and_a_rejection_does_not_hide_a_worse_level(self):
        self.real.update(answer(alert('medium', 7)))
        self.real.decide(ID, 'Rejected', 'Rejected: false alarm', reason='False alarm', now=NOW + 1)
        self.assertEqual((self.real.band(ID), self.real.detail(ID)), ('closed', 'Rejected · False alarm · Medium 7'))
        self.real.update(answer(alert('medium', 8), at=NOW + 300))
        self.assertEqual(self.real.band(ID), 'closed')  # the same activity stays rejected
        self.assertEqual(self.real.update(answer(alert('high', 10), at=NOW + 600)), {ID: 'reopened'})
        self.assertEqual((self.real.band(ID), self.real.state[ID]['status']), ('high', 'New'))
        self.assertTrue(self.real.attention(ID))
        self.assertTrue(self.real.detail(ID).startswith('⚠ Review again'))
        self.real.decide(ID, 'Escalated', 'Escalated to Duty officer', to='Duty officer', now=NOW + 610)
        self.assertEqual(self.real.detail(ID), 'Escalated · Duty officer · High 10')
        self.assertEqual(self.real.update(answer(alert('critical', 13), at=NOW + 900)), {ID: 'rose'})
        self.assertEqual(self.real.state[ID]['status'], 'Escalated')  # the status stays as the analyst left it
        self.assertTrue(self.real.state[ID]['review_again'])

    def test_a_cleared_alert_nobody_opened_latches_and_closes_once_reviewed(self):
        self.real.update(answer(alert()))
        self.real.update(answer(at=NOW + 300))
        self.assertEqual(self.real.band(ID), 'high')  # still shown: nobody has seen it
        self.assertTrue(self.real.attention(ID))
        self.assertRegex(self.real.detail(ID), r'^Cleared \d\d:\d\dZ · not reviewed · High 9$')
        self.real.decide(ID, 'Reviewed', 'Opened for review', now=NOW + 400)
        self.assertEqual(self.real.band(ID), 'closed')
        self.real.update(answer(alert(), at=NOW + 300 + EPISODE_GAP_S - 60))  # back within 30 min: same episode
        self.assertEqual((self.real.band(ID), self.real.state[ID]['status']), ('high', 'Reviewed'))
        self.real.update(answer(at=NOW + 2 * EPISODE_GAP_S))
        self.real.update(answer(at=NOW + 2 * EPISODE_GAP_S + FORGET_S + 1))
        self.assertNotIn(ID, self.real.items)  # forgotten six hours after it cleared

    def test_raised_again_after_the_gap_is_a_new_episode(self):
        self.real.update(answer(alert()))
        self.real.decide(ID, 'Acknowledged', 'Acknowledged; monitoring', now=NOW + 10)
        self.real.update(answer(at=NOW + 300))
        later = NOW + 300 + EPISODE_GAP_S + 60
        self.assertEqual(self.real.update(answer(alert(raised_t=later), at=later)), {ID: 'new'})
        self.assertEqual((self.real.band(ID), self.real.state[ID]['status']), ('high', 'New'))
        self.assertEqual(sum(text.startswith('Raised at') for _t, text in self.real.log_lines(ID)), 2)

    def test_a_failed_check_keeps_the_last_alerts_and_says_how_old_they_are(self):
        self.real.update(answer(alert()))
        self.real.update({'state': 'error', 'error': 'Cannot reach the Supabase database', 'checked_t': NOW + 300})
        self.assertIn(ID, self.real.items)
        self.assertEqual(self.real.state[ID]['cleared_t'], None)  # a failed check clears nothing
        text = self.real.status_text()
        self.assertIn('Last check failed: Cannot reach the Supabase database', text)
        self.assertIn('never evidence of intent', text)
        self.real.update({'state': 'unlinked'})
        self.assertIn('not linked to the team AIS database', self.real.status_text())


class SignedLogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.log = DecisionLog(Path(folder.name) / 'decision-log.jsonl')

    def sign(self, action, **extra):
        self.log.append(operator='analyst (this computer)', action=action, detail=f'{action} for the test', real=True,
                        simulated=False, alert=ID, vessel='TEST LOITERER', mmsi='250000001', level='high', score=9,
                        **extra)

    def test_decisions_signed_during_the_episode_are_restored_after_a_restart(self):
        self.sign('Escalated', to='Duty officer')
        self.log.append(operator='analyst', action='Acknowledged', detail='A simulated decision', simulated=True,
                        alert='SIM-01', vessel='FICTIONAL', level='high')
        real = RealAlerts()
        real.restore(self.log)
        self.assertIsNone(real.problem)
        now = time.time()
        real.update(answer(alert(raised_t=now - 3600), at=now))
        self.assertEqual((real.state[ID]['status'], real.state[ID]['to']), ('Escalated', 'Duty officer'))
        self.assertTrue(any('(signed log)' in text for _t, text in real.log_lines(ID)))
        later = RealAlerts()
        later.restore(self.log)
        later.update(answer(alert(raised_t=now + 2 * EPISODE_GAP_S), at=now + 2 * EPISODE_GAP_S))
        self.assertEqual(later.state[ID]['status'], 'New')  # a decision from before this episode does not carry over

    def test_a_restored_decision_below_the_current_level_asks_for_review_again(self):
        self.sign('Rejected', reason='False alarm')
        real = RealAlerts()
        real.restore(self.log)
        now = time.time()
        real.update(answer(alert('critical', 13, raised_t=now - 600), at=now))
        self.assertEqual((real.band(ID), real.state[ID]['status']), ('critical', 'New'))
        self.assertTrue(real.state[ID]['review_again'])

    def test_a_log_that_fails_its_check_restores_nothing(self):
        self.sign('Rejected', reason='False alarm')
        lines = self.log.path.read_text(encoding='utf-8').splitlines()
        lines[1] = lines[1].replace('False alarm', 'Duplicate alert')
        self.log.path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        real = RealAlerts()
        real.restore(self.log)
        real.update(answer(alert(raised_t=time.time() - 600), at=time.time()))
        self.assertEqual(real.state[ID]['status'], 'New')
        self.assertIn('did not verify', real.status_text())


if __name__ == '__main__':
    unittest.main()
