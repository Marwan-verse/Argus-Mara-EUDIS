"""Durable fleet history work, detector interpretation and uncapped directory pages."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from argus.fleet_history import FleetHistoryWorker, VERSION, analyse_history, source_health
from argus.satellite import atomic_json

MMSI = '123456789'
TOKEN = '22222222-2222-4222-8222-222222222222'
START = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def rows(count, **fields):
    return [{'mmsi': MMSI, 'received_utc': (START+timedelta(seconds=i*60)).isoformat(),
             'lat': 53.3, 'lon': -6.1, 'sog_kn': 0, 'cog_deg': 0, 'stream_id': 'one',
             'label': 'real', 'timestamp_source': 'received_time_assumption', **fields} for i in range(count)]


class Queue:
    def __init__(self, points, expected=None):
        self.rows, self.calls, self.result = points, [], None
        self.claimed = self.released = self.expired = self.lose_finish = False
        self.job = {'mmsi': MMSI, 'name': 'TEST SHIP', 'token': TOKEN, 'revision': 2,
                    'expected_rows': len(points) if expected is None else expected,
                    'rule_version': VERSION, 'cutoff_utc': '2026-12-31T00:00:00Z'}

    def __call__(self, name, payload):
        self.calls.append((name, deepcopy(payload)))
        if name == 'argus_history_claim':
            if self.claimed:
                return {'job': None}
            self.claimed = True
            return {'job': self.job}
        if name == 'argus_history_page':
            if self.expired:
                return {'lease_expired': True}
            after = payload['p_after']
            start = next((i+1 for i, row in enumerate(self.rows) if row['received_utc'] == after), 0)
            page = self.rows[start:start+1000]
            return {'mmsi': MMSI, 'rows': page, 'has_more': start+1000 < len(self.rows),
                    'next_after': page[-1]['received_utc'] if page else after}
        if name == 'argus_history_finish':
            self.result = payload['p_result']
            if self.lose_finish:
                self.lose_finish = False
                raise ValueError('Synthetic lost completion response')
            return {'saved': True}
        if name == 'argus_history_release':
            self.released = True
            return {'released': True}
        if name == 'argus_history_index':
            return {'vessels': [{'mmsi': MMSI, 'result': self.result, 'checked_utc': START.isoformat() if self.result else None,
                                 'new_evidence_pending': not bool(self.result), 'checking': not bool(self.result)}],
                    'next_after': None, 'summary': {'total_vessels': 1, 'checked_vessels': int(bool(self.result))}}
        raise AssertionError(name)


class FleetHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'satellite'
        self.linked = patch('argus.supabase_ais.linked', return_value=True)
        self.linked.start()
        self.addCleanup(self.linked.stop)

    def test_resume_at_last_durable_page_and_finish_all_rows(self):
        queue = Queue(rows(1001))
        worker = FleetHistoryWorker(self.root, call=queue)
        self.assertEqual(worker.step()['state'], 'checking')
        self.assertEqual(FleetHistoryWorker(self.root, call=queue).step()['state'], 'checked')
        self.assertEqual(queue.result['rows_checked'], 1001)
        self.assertEqual(queue.result['status'], 'no_rule_cues')
        self.assertFalse(worker.state_path.exists())
        self.assertFalse((worker.folder/TOKEN).exists())
        self.assertEqual(sum(n == 'argus_history_claim' for n, _ in queue.calls), 1)
        self.assertEqual(sum(n == 'argus_history_page' for n, _ in queue.calls), 2)
        self.assertEqual(sum(n == 'argus_history_index' for n, _ in queue.calls), 1)
        self.assertEqual(worker.page()['vessels'][0]['result']['rows_checked'], 1001)

    def test_checked_fleet_totals_do_not_imply_fresh_database_reception(self):
        now = START.timestamp()
        self.assertIn('unavailable', source_health({'checked_vessels': 2000}, now))
        self.assertIn('recent', source_health({'last_sync_utc': START.isoformat()}, now+60))
        self.assertIn('stale', source_health({'last_sync_utc': START.isoformat()}, now+301))
        self.assertIn('clock is ahead', source_health({'last_sync_utc': START.isoformat()}, now-61))
        self.assertIn('collector reports an error', source_health({'last_sync_utc': START.isoformat(), 'sync_error': 'failed'}, now))
        self.assertIn('Newest stored fix: stale', source_health({'last_sync_utc': START.isoformat(),
                      'newest_position_utc': (START-timedelta(hours=1)).isoformat()}, now))

    def test_lost_finish_response_retries_same_saved_result_without_rescanning(self):
        queue = Queue(rows(2))
        queue.lose_finish = True
        worker = FleetHistoryWorker(self.root, call=queue)
        self.assertEqual(worker.step()['state'], 'error')
        first = deepcopy(queue.result)
        self.assertEqual(FleetHistoryWorker(self.root, call=queue).step()['state'], 'checked')
        self.assertEqual(queue.result, first)
        self.assertEqual(sum(n == 'argus_history_page' for n, _ in queue.calls), 1)

    def test_crash_between_page_and_checkpoint_cannot_duplicate_or_skip_rows(self):
        queue = Queue(rows(1001))
        worker = FleetHistoryWorker(self.root, call=queue)
        failed = False
        def publish(path, value):
            nonlocal failed
            if path == worker.state_path and value.get('page') == 1 and not failed:
                failed = True
                raise OSError('Synthetic checkpoint failure')
            atomic_json(path, value)
        with patch('argus.fleet_history.atomic_json', side_effect=publish):
            self.assertEqual(worker.step()['state'], 'error')
        self.assertEqual(worker.step()['state'], 'checking')
        self.assertEqual(worker.step()['state'], 'checked')
        pages = [p for n, p in queue.calls if n == 'argus_history_page']
        self.assertIsNone(pages[0]['p_after'])
        self.assertEqual(pages[0], pages[1])
        self.assertEqual(queue.result['rows_checked'], 1001)

    def test_incomplete_snapshot_is_released_without_a_completed_check(self):
        queue = Queue(rows(2), expected=3)
        worker = FleetHistoryWorker(self.root, call=queue)
        self.assertEqual(worker.step()['state'], 'held')
        self.assertTrue(queue.released)
        self.assertIsNone(queue.result)
        self.assertFalse(worker.state_path.exists())

    def test_expired_lease_never_finishes_another_workers_claim(self):
        queue = Queue(rows(1001))
        worker = FleetHistoryWorker(self.root, call=queue)
        worker.step()
        queue.expired = True
        self.assertEqual(worker.step()['state'], 'waiting')
        self.assertIsNone(queue.result)
        self.assertFalse(worker.state_path.exists())

    def test_separate_streams_gaps_and_a_single_glitch_do_not_become_spoofing_claims(self):
        points = rows(2)
        points[1].update(lon=-8, stream_id='reset')
        result = analyse_history(MMSI, points)
        self.assertFalse(result['review_required'])
        self.assertEqual(result['epoch_count'], 2)
        points = rows(2)
        points[1]['received_utc'] = (START+timedelta(hours=3)).isoformat()
        self.assertEqual(analyse_history(MMSI, points)['received_gap_count'], 1)
        points = rows(3)
        points[1]['lon'] = -6.4
        result = analyse_history(MMSI, points)
        self.assertEqual(result['status'], 'isolated_cue')
        self.assertFalse(result['review_required'])

    def test_repeated_impossible_positions_create_dated_review_findings(self):
        points = rows(5)
        for i in (1, 3):
            points[i]['lon'] = -6.4
        result = analyse_history(MMSI, points)
        self.assertTrue(result['review_required'])
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['label'], 'assumption')
        self.assertEqual(result['source_labels'], ['real'])
        self.assertFalse(result['identity_confirmed'])
        self.assertTrue(all('received_utc' in event for event in result['findings']))

    def test_invalid_provenance_identity_or_duplicate_rows_cannot_be_completed(self):
        for points in [rows(2, label='simulated'), rows(2, mmsi='987654321'), rows(2, stream_id=''),
                       [rows(1)[0], rows(1)[0]]]:
            with self.assertRaises(ValueError):
                analyse_history(MMSI, points)

    def test_unlinked_workspaces_make_no_rpc_calls(self):
        queue = Queue([])
        with patch('argus.supabase_ais.linked', return_value=False):
            self.assertEqual(FleetHistoryWorker(self.root, call=queue).step()['state'], 'unlinked')
        self.assertEqual(queue.calls, [])

    def test_local_os_lock_prevents_two_clients_changing_one_checkpoint(self):
        worker = FleetHistoryWorker(self.root, call=Queue(rows(1)))
        other = FleetHistoryWorker(self.root, call=Queue(rows(1)))
        with worker.lock() as acquired:
            self.assertTrue(acquired)
            self.assertEqual(other.step()['state'], 'busy')
        self.assertEqual(other.step()['state'], 'checked')

    def test_directory_pages_include_every_vessel_and_mark_partial_inventory(self):
        worker = FleetHistoryWorker(self.root, call=None)
        entries = [{'mmsi': str(100000000+i), 'result': {'review_required': i == 100}}
                   for i in range(101)]
        packets = [{'vessels': entries[:100], 'next_after': entries[99]['mmsi'], 'summary': {'total_vessels': 101}},
                   {'vessels': entries[100:], 'next_after': None, 'summary': {'total_vessels': 101}}]
        with patch.object(worker, 'call', side_effect=packets):
            worker.refresh_index()
            self.assertFalse(worker.page()['inventory_complete'])
            worker.refresh_index()
        found, cursor = [], ''
        while True:
            packet = worker.page(cursor)
            found.extend(r['mmsi'] for r in packet['vessels'])
            cursor = packet['next_after']
            if not cursor:
                break
        self.assertEqual(found, [r['mmsi'] for r in entries])
        self.assertTrue(packet['inventory_complete'])
        self.assertEqual(len(worker.page(only_leads=True)['vessels']), 1)
        self.assertFalse(packet['complete_regional_census'])

    def test_new_mmsi_before_inventory_cursor_cannot_create_false_complete_coverage(self):
        worker = FleetHistoryWorker(self.root, call=None)
        packets = [
            {'vessels': [{'mmsi': '222222222'}], 'next_after': '222222222', 'summary': {'total_vessels': 2}},
            {'vessels': [{'mmsi': '333333333'}], 'next_after': None, 'summary': {'total_vessels': 3}},
            {'vessels': [{'mmsi': m} for m in ('111111111', '222222222', '333333333')],
             'next_after': None, 'summary': {'total_vessels': 3}}]
        with patch.object(worker, 'call', side_effect=packets):
            worker.refresh_index()
            worker.refresh_index()
            self.assertFalse(worker.page()['inventory_complete'])
            self.assertEqual(len(worker.page()['vessels']), 2)
            worker.refresh_index()
        self.assertTrue(worker.page()['inventory_complete'])
        self.assertEqual(len(worker.page()['vessels']), 3)

    def test_background_worker_checks_without_ui_refresh_and_stops_cleanly(self):
        import time
        queue = Queue(rows(2))
        worker = FleetHistoryWorker(self.root, call=queue)
        try:
            self.assertTrue(worker.start())
            first_thread = worker.thread
            self.assertTrue(worker.start())
            self.assertIs(worker.thread, first_thread)
            until = time.monotonic()+3
            while queue.result is None and time.monotonic() < until:
                time.sleep(.01)
            self.assertIsNotNone(queue.result)
        finally:
            worker.stop()
            if worker.thread:
                worker.thread.join(timeout=3)
        self.assertFalse(worker.thread.is_alive())
        self.assertFalse(worker.start())  # A late scan callback cannot restart a closed host.


if __name__ == '__main__':
    unittest.main()
