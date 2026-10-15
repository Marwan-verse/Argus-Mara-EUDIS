"""Resumable, free history checks for the private database's entire AIS fleet.

The database owns the queue and revision/lease watermarks. Python owns detection.
No image/model calls, threat probability or operational action is involved.
"""
from collections import defaultdict
from bisect import bisect_left
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import threading
import time
from uuid import UUID

from argus import supabase_ais
from argus.detectors import ais_spoofing as spoof
from argus.provenance import now_utc
from argus.satellite import atomic_json
from argus.space import timestamp

VERSION = 'fleet-received-history-v1'
MAX_ROWS = 500_000


def source_health(summary, now=None):
    """Freshness is independent of the number of vessels whose rules were checked."""
    now = time.time() if now is None else now
    stamp = summary.get('last_sync_utc')
    if not stamp:
        return 'Database sync: success time unavailable'
    try:
        age = now-timestamp(stamp)
    except (ValueError, TypeError):
        return 'Database sync: invalid success time'
    if age < -60:
        return 'Database sync clock is ahead; freshness unverified'
    text = f"Database sync: {'stale' if age > 300 else 'recent'} · {max(0, int(age))} s since success"
    if summary.get('sync_error'):
        text += ' · collector reports an error'
    newest = summary.get('newest_position_utc')
    if not newest:
        return text+'\nNewest stored fix: unavailable'
    try:
        fix_age = now-timestamp(newest)
    except (ValueError, TypeError):
        return text+'\nNewest stored fix: invalid time'
    if fix_age < -60:
        return text+'\nNewest stored fix clock is ahead; freshness unverified'
    return text+f"\nNewest stored fix: {'stale' if fix_age > 900 else 'recent'} · {max(0, int(fix_age))} s old"


def analyse_history(mmsi, rows, *, name=None, expected_rows=None, cutoff_utc=None):
    """Check all retained rows; never bridge server epochs or call a gap silence."""
    if not isinstance(mmsi, str) or not re.fullmatch(r'[0-9]{9}', mmsi):
        raise ValueError('Invalid history MMSI')
    if expected_rows is not None and len(rows) != expected_rows:
        raise ValueError('History snapshot is incomplete; vessel must remain unchecked')
    streams, times, labels, seen = defaultdict(list), [], set(), set()
    for row in rows:
        if row.get('mmsi') != mmsi or row.get('label') not in {'real', 'reconstructed'}:
            raise ValueError('History identity/provenance does not match the claimed vessel')
        t = timestamp(row['received_utc'])
        if cutoff_utc and t > timestamp(cutoff_utc):
            raise ValueError('History row is later than the snapshot cutoff')
        if t in seen:
            raise ValueError('Duplicate history time; snapshot was not consumed exactly once')
        seen.add(t)
        lat, lon = row.get('lat'), row.get('lon')
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon))
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError('Invalid position in the claimed history')
        speed = row.get('sog_kn')
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or not 0 <= speed < 102.3:
            speed = None
        stream = row.get('stream_id')
        if not isinstance(stream, str) or not stream:
            raise ValueError('History stream epoch is missing')
        streams[(stream, row['label'])].append({'t': t, 'lat': lat, 'lon': lon, 'sog_kn': speed})
        labels.add(row['label'])
        times.append(t)
    findings, events, gap_count, max_gap, usable = [], [], 0, 0, 0
    for fixes in streams.values():
        fixes = spoof.clean_track(sorted(fixes, key=lambda p: p['t']))
        usable += len(fixes)
        steps = spoof.steps_between(fixes)
        gaps = [s['dt'] for s in steps if s['dt'] >= spoof.GAP_S]
        gap_count += len(gaps)
        max_gap = max([max_gap, *gaps])
        # These checks use received motion only. Applying today's ship type to
        # an older voyage, or using coarse display coastlines, would add unjustified
        # precision. Gap/reappearance and land checks are deliberately not scored.
        group = (spoof.jump_events(fixes, steps) + spoof.two_places_events(fixes, steps)
                 + spoof.speed_mismatch_events(fixes, steps))
        event_times = sorted({e['t'] for e in group})
        for event in group:
            index = bisect_left(event_times, event['t'])
            repeated = ((index > 0 and event['t']-event_times[index-1] <= spoof.PERSIST_WINDOW_S) or
                        (index+1 < len(event_times) and event_times[index+1]-event['t'] <= spoof.PERSIST_WINDOW_S))
            events.append({**event, 'review_required': bool(spoof.persistence([event])) or repeated})
    events.sort(key=lambda e: e['t'])
    for event in events:
        findings.append({'kind': event['kind'], 'received_utc': datetime.fromtimestamp(event['t'], timezone.utc).isoformat(),
                         'lat': event['position'][0], 'lon': event['position'][1],
                         'distance_nm': event['distance_nm'], 'reason': event['reason'],
                         'review_required': event['review_required'], 'label': 'assumption'})
    review_required = any(f['review_required'] for f in findings)
    return {'version': VERSION, 'mmsi': mmsi, 'name': name or mmsi,
            'completed': True, 'rows_checked': len(rows), 'usable_fixes': usable,
            'status': 'review_required' if review_required else 'isolated_cue' if findings else
                      'insufficient_history' if usable < 2 else 'no_rule_cues',
            'review_required': review_required, 'checked_utc': now_utc(),
            'first_fix_utc': datetime.fromtimestamp(min(times), timezone.utc).isoformat() if times else None,
            'last_fix_utc': datetime.fromtimestamp(max(times), timezone.utc).isoformat() if times else None,
            'epoch_count': len(streams), 'received_gap_count': gap_count, 'largest_received_gap_s': max_gap,
            'invalid_default_fixes': len(rows)-usable, 'source_labels': sorted(labels),
            'findings': findings[-100:], 'finding_count': len(findings), 'findings_retained': min(100, len(findings)),
            'label': 'assumption', 'identity_confirmed': False,
            'caveat': 'Rules screen partial collector receipt-time AIS only. A reception gap is not proof of silence; no rule cues is not a safety clearance. Findings need analyst review.'}


class FleetHistoryWorker:
    """One resumable page per step; database leases coordinate different clients."""
    def __init__(self, root, *, call=None):
        self.root = Path(root)
        self.folder = self.root/'fleet_history'
        self.state_path = self.folder/'active.json'
        self.status_path = self.folder/'status.json'
        self.index_path = self.folder/'index.json'
        self.call = call or supabase_ais.rpc
        self.halt = threading.Event()
        self.thread = None
        self.guard = threading.Lock()
        self.closed = False

    def start(self):
        with self.guard:
            if self.closed:
                return False
            if self.thread and self.thread.is_alive():
                return True
            if not supabase_ais.linked(self.root):
                self.publish('unlinked', 'Link the team database to check every vessel history.')
                return False
            self.halt.clear()
            self.thread = threading.Thread(target=self.run, daemon=True, name='argus-fleet-history')
            self.thread.start()
            return True

    def stop(self):
        with self.guard:
            self.closed = True
            self.halt.set()

    def run(self):
        while not self.halt.is_set():
            result = self.step()
            # Make progress through the initial fleet rather than one vessel
            # every UI refresh. Idle/errors back off; every network read remains
            # bounded, and no paid model is called by this worker.
            self.halt.wait(.25 if result['state'] in {'checked', 'checking'} else 15)

    def status(self):
        if self.status_path.exists():
            return json.loads(self.status_path.read_text(encoding='utf-8'))
        return {'state': 'waiting', 'message': 'Fleet history has not been checked on this host yet.'}

    def publish(self, state, message, **values):
        result = {'state': state, 'message': message, 'updated_utc': now_utc(), **values}
        atomic_json(self.status_path, result)
        return result

    @staticmethod
    def token(value):
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError('Invalid database history lease')
        return value

    def step(self):
        if not supabase_ais.linked(self.root):
            return self.publish('unlinked', 'Link the team database to check every vessel history.')
        try:
            with self.lock() as acquired:
                if not acquired:
                    return {'state': 'busy', 'message': 'Another local worker is checking the vessel history.'}
                result = self._step()
                cache = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {}
                if not cache.get('inventory_complete') or time.time()-timestamp(cache.get('inventory_page_utc') or '1970-01-01T00:00:00Z') >= 30:
                    self.refresh_index()
                return result
        except (ValueError, OSError, KeyError, TypeError) as error:
            # Retain the checkpoint and successfully saved pages on transport or
            # publication failure. No claim is completed or replaced on timeout.
            message = str(error)[:200]
            if 'HTTP 404' in message:
                message = 'Fleet history API unavailable (HTTP 404); check the database migration.'
            return self.publish('error', message)

    def refresh_index(self):
        """One keyset page per step, with explicit initial inventory coverage."""
        cache = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {
            'vessels': {}, 'cursor': '', 'seen': [], 'inventory_complete': False}
        packet = self.call('argus_history_index', {'p_after': cache['cursor'], 'p_limit': 100, 'p_only_leads': False})
        rows = packet.get('vessels')
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Invalid fleet history directory page')
        previous = cache['cursor']
        for row in rows:
            mmsi = row.get('mmsi')
            if not isinstance(mmsi, str) or not re.fullmatch(r'[0-9]{9}', mmsi) or mmsi <= previous:
                raise ValueError('Invalid or unordered fleet directory identity')
            cache['vessels'][mmsi] = row
            cache['seen'].append(mmsi)
            previous = mmsi
        after = packet.get('next_after')
        if after is not None and (not rows or after != previous):
            raise ValueError('Fleet directory did not advance its cursor')
        if after is None:
            seen = set(cache['seen'])
            complete = len(seen) == packet.get('summary', {}).get('total_vessels')
            if complete:
                cache['vessels'] = {m: row for m, row in cache['vessels'].items() if m in seen}
            # A new MMSI can sort before the current cursor. Keep known rows and
            # do another cycle instead of claiming that an inconsistent page set
            # is the complete fleet, or deleting a just-completed local record.
            cache.update(cursor='', seen=[], inventory_complete=complete, inventory_cycle_utc=now_utc())
        else:
            cache['cursor'] = after
            if len(cache['vessels']) != packet.get('summary', {}).get('total_vessels'):
                cache['inventory_complete'] = False
        cache.update(summary=packet.get('summary', {}), updated_utc=now_utc(), inventory_page_utc=now_utc())
        atomic_json(self.index_path, cache)

    def cache_completed(self, job, result, answer):
        cache = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {
            'vessels': {}, 'cursor': '', 'seen': [], 'inventory_complete': False}
        if job['mmsi'] not in cache['vessels']:
            cache['inventory_complete'] = False
        cache['vessels'][job['mmsi']] = {'mmsi': job['mmsi'], 'checked_utc': answer.get('checked_utc') or result['checked_utc'],
            'new_evidence_pending': bool(answer.get('new_evidence_pending')), 'checking': False,
            'last_error': None, 'retry_after': None, 'result': result}
        cache['updated_utc'] = now_utc()
        atomic_json(self.index_path, cache)

    def page(self, after='', limit=50, only_leads=False):
        if after and (not isinstance(after, str) or not re.fullmatch(r'[0-9]{9}', after)):
            raise ValueError('Invalid fleet directory cursor')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Choose 1–50 fleet vessels per page')
        cache = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {}
        vessels = cache.get('vessels', {})
        found = [row for m, row in sorted(vessels.items()) if m > after and
                 (not only_leads or (row.get('result') or {}).get('review_required') is True)]
        rows = found[:limit]
        return {'vessels': rows, 'next_after': rows[-1]['mmsi'] if len(found) > limit else None,
                'after': after, 'only_leads': only_leads,
                'summary': cache.get('summary', {}), 'worker': self.status(),
                'inventory_complete': cache.get('inventory_complete', False),
                'inventory_vessels_cached': len(vessels), 'updated_utc': cache.get('updated_utc'),
                'complete_regional_census': False, 'source': 'team_database_cache'}

    @contextmanager
    def lock(self):
        """OS-released advisory lock: a crashed process cannot strand the queue."""
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder/'worker.lock').open('a+b') as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                stream.seek(0)
                if sys.platform == 'win32':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def discard_pages(self, token):
        """Delete only our generated intermediate pages for a resolved lease."""
        folder = self.folder/self.token(token)
        if folder.is_symlink() or folder.resolve().parent != self.folder.resolve():
            raise ValueError('History cache path is outside the workspace')
        if folder.exists():
            for path in folder.iterdir():
                if re.fullmatch(r'page-[0-9]{6}\.json|result\.json', path.name) and path.is_file():
                    path.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()

    def _step(self):
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
        else:
            claim = self.call('argus_history_claim', {'p_rule_version': VERSION})
            if not isinstance(claim, dict):
                raise ValueError('Invalid fleet history claim response')
            if not claim.get('job'):
                return self.publish('idle', 'No vessel history is ready; remaining work may be leased or held.', summary=claim.get('summary'))
            state = {'claim': claim['job'], 'cursor': None, 'page': 0, 'rows': 0, 'stage': 'fetch'}
            self.token(state['claim']['token'])
            atomic_json(self.state_path, state)
        job = state['claim']
        token = self.token(job['token'])
        if not isinstance(job.get('mmsi'), str) or not re.fullmatch(r'[0-9]{9}', job['mmsi']):
            raise ValueError('Invalid claimed vessel identity')
        folder = self.folder/token
        if state['stage'] == 'release':
            answer = self.call('argus_history_release', {'p_token': token, 'p_reason': state['error']})
            if not answer.get('released') and not answer.get('lease_expired'):
                raise ValueError('Database did not confirm the history release')
            self.state_path.unlink()
            self.discard_pages(token)
            return self.publish('held', state['error'], mmsi=job['mmsi'])
        if state['stage'] == 'fetch':
            packet = self.call('argus_history_page', {'p_token': token, 'p_after': state['cursor']})
            if packet.get('lease_expired'):
                self.state_path.unlink()
                self.discard_pages(token)
                return self.publish('waiting', 'History lease expired; the database will requeue the unfinished vessel.')
            rows = packet.get('rows')
            if not isinstance(rows, list) or len(rows) > 1000 or packet.get('mmsi') != job['mmsi']:
                raise ValueError('Invalid fleet history page')
            if not rows and packet.get('has_more'):
                raise ValueError('Empty history page cannot advance the cursor')
            last = timestamp(state['cursor']) if state['cursor'] else float('-inf')
            for row in rows:
                stamp = timestamp(row['received_utc'])
                if stamp <= last or row.get('mmsi') != job['mmsi']:
                    raise ValueError('History page is duplicated, unordered or has the wrong vessel')
                last = stamp
            if state['rows']+len(rows) > MAX_ROWS:
                return self.release(state, 'Vessel history exceeds the 500,000-row local capacity; it remains unchecked.')
            next_cursor = rows[-1]['received_utc'] if rows else state['cursor']
            if packet.get('next_after') != next_cursor:
                raise ValueError('History page cursor does not match its last row')
            # Retrying after a crash overwrites this same page. The checkpoint
            # advances only after durable publication, so rows cannot be skipped.
            atomic_json(folder/f"page-{state['page']:06d}.json", rows)
            state.update(cursor=next_cursor, page=state['page']+1, rows=state['rows']+len(rows),
                         stage='fetch' if packet.get('has_more') else 'analyse')
            atomic_json(self.state_path, state)
            if state['stage'] == 'fetch':
                return self.publish('checking', f"Checking {job['mmsi']} history", mmsi=job['mmsi'], rows_read=state['rows'])
        if state['stage'] == 'analyse':
            rows = []
            for number in range(state['page']):
                rows.extend(json.loads((folder/f'page-{number:06d}.json').read_text(encoding='utf-8')))
            try:
                result = analyse_history(job['mmsi'], rows, name=job.get('name'), expected_rows=job['expected_rows'],
                                         cutoff_utc=job['cutoff_utc'])
            except ValueError as error:
                return self.release(state, str(error))
            atomic_json(folder/'result.json', result)
            state['stage'] = 'finish'
            atomic_json(self.state_path, state)
        result = json.loads((folder/'result.json').read_text(encoding='utf-8'))
        answer = self.call('argus_history_finish', {'p_token': token, 'p_result': result})
        if answer.get('lease_expired') or answer.get('snapshot_changed'):
            self.state_path.unlink()
            self.discard_pages(token)
            return self.publish('waiting', 'History evidence changed before completion; vessel remains queued.')
        if answer.get('saved') is not True:
            raise ValueError('Database did not confirm the completed vessel history')
        self.cache_completed(job, result, answer)
        self.state_path.unlink()
        self.discard_pages(token)
        return self.publish('checked', f"Checked {job['mmsi']} history", mmsi=job['mmsi'], result_status=result['status'],
                            rows_checked=result['rows_checked'])

    def release(self, state, message):
        state.update(stage='release', error=message[:200])
        atomic_json(self.state_path, state)
        return self._step()
