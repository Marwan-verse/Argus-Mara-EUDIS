"""Immutable, host-local analyst notes, separate from computed evidence."""
import hashlib
from datetime import datetime, timezone
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
import re
from uuid import UUID

from argus.satellite import atomic_json

OUTCOMES = {
    'needs_follow_up': 'Needs follow-up',
    'insufficient_evidence': 'Insufficient evidence',
    'image_false_detection': 'Image false detection',
    'association_error': 'Association error',
    'reviewed_no_concern': 'Reviewed — no concern identified',
    'unreviewed': 'Reopen for review',
}
CLOSED_OUTCOMES = {'image_false_detection', 'association_error', 'reviewed_no_concern'}


def evidence_key(review, lead):
    # Refresh timestamps/latest positions are not acquisition-time evidence.
    contacts = [{k: c.get(k) for k in ('id', 'lat', 'lon', 'matched_mmsi', 'ambiguous', 'overlap_ambiguous')}
                for c in review.get('contacts', [])]
    vessels = [{k: v.get(k) for k in ('mmsi', 'position', 'position_evidence', 'broadcast_fields', 'track')}
               for v in review.get('ais', {}).get('vessels', [])]
    content = {'lead': lead, 'scene': review['scene'], 'contacts': contacts, 'vessels': vessels,
               'version': review.get('comparison', {}).get('version')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, allow_nan=False).encode()).hexdigest()


class Dispositions:
    def __init__(self, root):
        self.root = Path(root)/'analyst_reviews'

    def folder(self, lead_id):
        return self.root/hashlib.sha256(lead_id.encode()).hexdigest()

    def events(self, lead_id):
        rows = []
        for path in self.folder(lead_id).glob('*.json'):
            if not re.fullmatch(r'[0-9a-f-]{36}\.json', path.name):
                continue
            try:
                event = json.loads(path.read_text(encoding='utf-8'))
                if (event['lead_id'] != lead_id or event['event_id'] != path.stem
                        or event['outcome'] not in OUTCOMES
                        or not re.fullmatch(r'[0-9a-f]{64}', event['evidence_key'])
                        or not all(isinstance(event[k], str) and event[k] for k in ('saved_utc', 'actor', 'reason'))):
                    raise ValueError('Invalid analyst review record')
                rows.append(event)
            except (OSError, ValueError, KeyError, TypeError):
                # Corrupt audit data cannot silently turn into a clean review.
                raise ValueError('Analyst review record cannot be read; check the host audit files') from None
        return sorted(rows, key=lambda r: (r['saved_utc'], r['event_id']))

    def decorate(self, lead, key):
        try:
            events = self.events(lead['id'])
        except ValueError as error:
            return {**lead, 'evidence_key': key, 'review_status': 'unreviewed',
                    'review_error': str(error), 'analyst_review': None, 'evidence_changed': True}
        latest = events[-1] if events else None
        changed = bool(latest and latest['evidence_key'] != key)
        state = 'unreviewed' if changed or not latest else latest['outcome']
        return {**lead, 'evidence_key': key, 'analyst_review': latest,
                'review_status': state, 'evidence_changed': changed,
                'review_event_count': len(events)}

    @contextmanager
    def lock(self, lead_id):
        folder = self.folder(lead_id)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder/'audit.lock').open('a+b') as stream:
            if stream.seek(0, 2) == 0:
                stream.write(b'0')
                stream.flush()
            deadline = time.monotonic()+3
            while True:
                stream.seek(0)
                try:
                    if sys.platform == 'win32':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError('Another analyst review is saving; retry manually') from None
                    time.sleep(.05)
            try:
                yield
            finally:
                stream.seek(0)
                if sys.platform == 'win32':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def save(self, lead, key, payload, actor):
        with self.lock(lead['id']):
            return self._save(lead, key, payload, actor)

    def _save(self, lead, key, payload, actor):
        if not isinstance(payload, dict) or set(payload) != {'event_id', 'lead_id', 'evidence_key', 'outcome', 'reason'}:
            raise ValueError('Expected lead, evidence, outcome, reason and request identifier')
        try:
            identifier = str(UUID(payload['event_id']))
            if identifier != payload['event_id']:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid review request identifier') from None
        if payload['lead_id'] != lead['id']:
            raise ValueError('Unknown satellite review lead')
        outcome, reason = payload['outcome'], payload['reason']
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise ValueError('Choose an analyst outcome')
        if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 2000 or '\x00' in reason:
            raise ValueError('Write a reason of 8–2000 characters')
        if not isinstance(actor, str) or not 1 <= len(actor) <= 160:
            raise ValueError('Authenticated analyst identity is required')
        folder = self.folder(lead['id'])
        target = folder/(identifier+'.json')
        wanted = {'event_id': identifier, 'lead_id': lead['id'], 'evidence_key': payload['evidence_key'],
                  'outcome': outcome, 'reason': reason.strip(), 'actor': actor}
        def existing():
            event = json.loads(target.read_text(encoding='utf-8'))
            if any(event.get(k) != v for k, v in wanted.items()):
                raise ValueError('This request identifier already records a different review')
            return event
        if target.exists():
            return existing()  # Exact manual retry after a lost reply is free/idempotent.
        if payload['evidence_key'] != key:
            raise ValueError('Evidence changed; reload the lead before saving your review')
        history = self.events(lead['id'])
        if len(history) >= 200:
            raise ValueError('Review audit limit reached for this lead; archive the host records')
        folder.mkdir(parents=True, exist_ok=True)
        event = {**wanted, 'saved_utc': datetime.now(timezone.utc).isoformat(), 'label': 'assumption',
                 'lead_snapshot': lead, 'identity_confirmed': False, 'operational_approval': False}
        atomic_json(target, event)
        return event
