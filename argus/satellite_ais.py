"""Join satellite acquisition UTC to private AIS archives without leaking raw AIS.

Read CSV/Parquet recorder exports or the existing normalized AIS handoff JSON.
Static data is selected as-of acquisition; current destination never substitutes.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from argus.ingest.ais import POSITION_TYPES, mmsi_value, motion
from argus.provenance import utc
from argus.space import assignment, coordinates, distance_km, finite, position_at, position_method, timestamp

STATIC_TYPES = {'ShipStaticData', 'StaticDataReport'}
FIELDS = {'name', 'call_sign', 'imo', 'ship_type', 'destination', 'eta', 'draught_m',
          'length_m', 'width_m', 'nav_status', 'heading_deg', 'sog_kn', 'cog_deg', 'ship_type_description'}


class ArchiveChanged(ValueError):
    """A free read raced a recorder append; no AI request has been submitted."""


def text(value, limit=80):
    return ''.join(c for c in str(value or '') if c.isprintable()).strip(' @')[:limit] or None


def metadata(row):
    """Whitelist only broadcast fields; raw provider objects stay on disk."""
    result = {key: row[key] for key in FIELDS if row.get(key) is not None}
    for output, field in [('heading_deg', 'heading'), ('sog_kn', 'sog'), ('cog_deg', 'cog'),
                          ('length_m', 'ais_length_m')]:
        if row.get(field) is not None:
            result[output] = row[field]
    if row.get('ship_name'):
        result['name'] = text(row['ship_name'])
    raw = row.get('raw')
    try:
        body = (json.loads(raw).get('Message') or {}) if isinstance(raw, str) else {}
        report = body.get('ShipStaticData') or body.get('StaticDataReport') or {}
        report = {**report, **(report.get('ReportA') or {}), **(report.get('ReportB') or {})}
        for output, field in [('name', 'Name'), ('call_sign', 'CallSign'), ('imo', 'ImoNumber'),
                              ('ship_type', 'Type'), ('destination', 'Destination'),
                              ('draught_m', 'MaximumStaticDraught')]:
            if report.get(field) is not None:
                result[output] = report[field]
        eta = report.get('Eta')
        if isinstance(eta, dict):
            result['eta'] = {k: eta[k] for k in ('Month', 'Day', 'Hour', 'Minute')
                             if isinstance(eta.get(k), int) and not isinstance(eta[k], bool)}
        dimension = report.get('Dimension') or {}
        if all(isinstance(dimension.get(k), (int, float)) for k in ('A', 'B', 'C', 'D')):
            result['length_m'] = dimension['A'] + dimension['B']
            result['width_m'] = dimension['C'] + dimension['D']
    except (ValueError, TypeError, AttributeError):
        pass
    for key in ('name', 'call_sign', 'destination', 'ship_type_description'):
        if key in result:
            result[key] = text(result[key], 80 if key == 'name' else 32)
    for key in FIELDS - {'name', 'call_sign', 'destination', 'eta', 'ship_type_description'}:
        if key in result:
            try:
                value = finite(result[key], key)
                result[key] = value if 0 <= value <= 1_000_000_000 else None
            except (ValueError, TypeError):
                result[key] = None
    if 'eta' in result and not isinstance(result['eta'], (str, dict)):
        result.pop('eta')
    explicit = set(str(row.get('present_fields') or '').split(',')) & FIELDS
    for key in explicit:
        result.setdefault(key, None)
    return {key: value for key, value in result.items() if value is not None or key in explicit}


def row_time(value):
    if hasattr(value, 'isoformat'):
        value = value.isoformat()
    value = re.sub(r'\s+([+-]\d{2})(\d{2})$', r'\1:\2', str(value).removesuffix(' UTC'))
    return utc(value)


def archive_rows(path):
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Split AIS archive files into chunks smaller than 256 MB')
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            yield from csv.DictReader(stream)
    elif path.suffix.lower() == '.parquet':
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise ValueError('Parquet AIS imports need recorder/requirements.txt; CSV is also supported') from None
        columns = {'mmsi', 'msg_type', 'ship_name', 'lat', 'lon', 'sog', 'cog', 'heading',
                   'nav_status', 'time_utc', 'recv_utc', 'raw'}
        with pq.ParquetFile(path) as parquet:
            for batch in parquet.iter_batches(batch_size=4096, columns=sorted(columns & set(parquet.schema.names))):
                yield from batch.to_pylist()
    elif path.suffix.lower() == '.json':
        pack = json.loads(path.read_text(encoding='utf-8'))
        for vessel in pack.get('vessels', []):
            for point in vessel.get('track', []):
                yield {**point, 'mmsi': vessel['mmsi'], 'label': point.get('label', vessel.get('label'))}
            # Undated vessel-level particulars must not be stamped onto every
            # old track point. Only explicitly dated static evidence is eligible.
            for key, field in vessel.get('broadcast_fields', {}).items():
                if key in FIELDS and isinstance(field, dict) and field.get('received_utc'):
                    yield {'mmsi': vessel['mmsi'], 'label': vessel.get('label'), 'msg_type': 'ShipStaticData',
                           'recv_utc': field['received_utc'], key: field.get('value'), 'present_fields': key}
    else:
        raise ValueError('Use an AIS CSV, recorder Parquet or normalized handoff JSON')


def historical_ais(root, acquired_utc, area):
    when = timestamp(acquired_utc)
    w, s, e, n = area
    vessels, fixes, earliest, latest, count = {}, 0, None, None, 0
    paths = sorted(p for p in Path(root).rglob('*') if p.is_file() and p.suffix.lower() in {'.csv', '.parquet', '.json'}) if Path(root).exists() else []
    # Our daily capture partitions cannot contain reception times outside their
    # named day. Imports remain fully scanned; do not trust arbitrary filenames.
    paths = [p for p in paths if p.parent != Path(root)/'capture' or
             not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.csv', p.name) or
             when-2*86400 <= timestamp(p.stem+'T00:00:00Z') <= when+86400]
    if len(paths) > 300:
        raise ValueError('Select an AIS archive folder with at most 300 files')
    if sum(path.stat().st_size for path in paths) > 1024*1024*1024:
        raise ValueError('Select at most 1 GB of AIS archives around the acquisition day')
    digest = hashlib.sha256()
    for path in paths:
        initial = path.stat()
        # Include content in evidence identity, not just filesystem modification time.
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        for row in archive_rows(path):
            count += 1
            if count > 2_000_000:
                raise ValueError('AIS archive scan limit reached; narrow the archive to the acquisition day')
            try:
                label = row.get('label', 'real') or 'real'
                if label not in {'real', 'reconstructed'}:
                    continue  # Never match exercise positions to real satellite pixels.
                received = row.get('recv_utc') or row.get('ts') or row.get('time_utc')
                received_s = timestamp(row_time(received))
                if not when-86400 <= received_s <= when+600:
                    continue
                mmsi = str(mmsi_value(row['mmsi'])).zfill(9)
                vessel = vessels.setdefault(mmsi, {'mmsi': mmsi, 'track': [], 'static': [], 'label': label})
                kind = row.get('msg_type')
                if kind in STATIC_TYPES and received_s <= when:
                    vessel['static'].append((received_s, metadata(row)))
                elif kind in POSITION_TYPES or (not kind and row.get('ts')):
                    raw_time = row.get('ts') or row.get('time_utc') or received
                    ts = row_time(raw_time)
                    t = timestamp(ts)
                    if abs(t-when) > 600:
                        continue
                    lat, lon = coordinates(row)
                    if not w-.45 <= lon <= e+.45 or not s-.25 <= lat <= n+.25:
                        continue
                    point = {'ts': ts, 'lat': lat, 'lon': lon,
                             'sog_kn': motion(row.get('sog_kn', row.get('sog')), 'speed', 102.3),
                             'cog_deg': motion(row.get('cog_deg', row.get('cog')), 'course', 360),
                             'label': label, 'timestamp_source': row.get('timestamp_source') or
                             ('received_time_assumption' if not row.get('time_utc') and not row.get('ts') else 'provider_reported_time')}
                    point['stream_id'] = row.get('stream_id') or 'imported'
                    vessel['track'].append(point)
                    if received_s <= when:
                        vessel['static'].append((received_s, metadata(row)))
                    earliest, latest = min(earliest or t, t), max(latest or t, t)
                    fixes += 1
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
        final = path.stat()
        if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise ArchiveChanged('AIS recording changed during this free historical join; open the review again')
    eligible = []
    for vessel in vessels.values():
        unique = {}
        for point in vessel['track']:
            prior = unique.get(point['ts'])
            if prior is not None and (prior['lat'], prior['lon']) != (point['lat'], point['lon']):
                raise ValueError('Conflicting archived AIS positions for one MMSI/time; review the archive')
            unique[point['ts']] = point
        vessel['track'] = sorted(unique.values(), key=lambda p: timestamp(p['ts']))
        epochs = {}
        for point in vessel['track']:
            epochs.setdefault(point['stream_id'], []).append(point)
        alternatives = [(track, position_at(track, when)) for track in epochs.values()]
        alternatives = [(track, pos) for track, pos in alternatives if pos is not None]
        if len(alternatives) != 1:
            continue  # Never interpolate across stream resets or choose conflicting sources.
        vessel['track'], position = alternatives[0]
        if position is None or not w-.005 <= position['lon'] <= e+.005 or not s-.003 <= position['lat'] <= n+.003:
            continue
        values = {}
        for received, fields in sorted(vessel.pop('static'), key=lambda p: p[0]):
            for key, value in fields.items():
                values[key] = {'value': value, 'received_utc': datetime.fromtimestamp(received, timezone.utc).isoformat()}
        vessel.update({'position': position, 'position_evidence': position_method(vessel['track'], when, None),
                       'broadcast_fields': values, 'name': values.get('name', {}).get('value') or str(vessel['mmsi'])})
        speeds = [distance_km(a, b)/((timestamp(b['ts'])-timestamp(a['ts']))/3600)/1.852
                  for a, b in zip(vessel['track'], vessel['track'][1:])
                  if 0 < timestamp(b['ts'])-timestamp(a['ts']) <= 600]
        vessel['position_evidence'].update({'implied_segment_speed_kn': round(max(speeds), 2) if speeds else None,
             'max_plausible_segment_speed_kn': 80,
             'kinematic_consistency': 'exceeds_assumed_limit' if speeds and max(speeds) > 80 else 'within_assumed_limit' if speeds else 'unavailable',
             'caveat': '80 kn is a team screening assumption. Scene acquisition UTC is not per-pixel timing; reception timestamps and straight-line motion introduce uncertainty.'})
        eligible.append(vessel)
    return {'vessels': eligible, 'archive_sha256': digest.hexdigest(), 'acquired_utc': acquired_utc,
            'coverage': {'status': 'partial' if eligible else 'unavailable', 'eligible_vessels': len(eligible),
                         'nearby_fixes': fixes, 'files_scanned': len(paths),
                         'first_fix_utc': datetime.fromtimestamp(earliest, timezone.utc).isoformat() if earliest else None,
                         'last_fix_utc': datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None,
                         'complete_regional_census': False,
                         'caveat': 'Reception coverage is incomplete. Missing AIS does not establish deliberate silence.'}}


def associate(contacts, ais, radius_km=.3):
    vessels = ais['vessels']
    penalty = len(contacts)+1
    costs = [[distance_km(contact, vessel['position'])/radius_km
              if distance_km(contact, vessel['position']) <= radius_km and vessel['position_evidence'].get('kinematic_consistency') != 'exceeds_assumed_limit' else penalty*3
              for vessel in vessels] + [penalty]*len(contacts) for contact in contacts]
    result = []
    for contact, col in zip(contacts, assignment(costs)):
        item = {**contact, 'association': 'no_contemporaneous_ais' if not vessels else 'unmatched_review_lead',
                'matched_mmsi': None, 'identity_confirmed': False, 'review_status': 'unreviewed', 'candidates': []}
        when = timestamp(ais.get('acquired_utc') or contact.get('ts')) if ais.get('acquired_utc') or contact.get('ts') else None
        for vessel in vessels:
            distance = distance_km(contact, vessel['position'])
            if distance > 1:
                continue
            nearest = min(vessel['track'], key=lambda p: abs(timestamp(p['ts'])-when)) if when is not None else None
            offset = abs(timestamp(nearest['ts'])-when) if nearest else None
            evidence = vessel['position_evidence']
            motion_ok = evidence.get('kinematic_consistency') != 'exceeds_assumed_limit'
            item['candidates'].append({'mmsi': vessel['mmsi'], 'name': vessel['name'],
                    'distance_m': round(distance*1000, 1), 'within_gate': distance <= radius_km, 'motion_consistent': motion_ok,
                    'nearest_fix_offset_s': round(offset, 1) if offset is not None else None,
                    'position': vessel['position'], 'position_evidence': evidence,
                    'broadcast_fields': vessel['broadcast_fields'],
                    'assessment': 'motion_inconsistent_review_required' if not motion_ok else
                                  'spatially_consistent_time_assumed' if distance <= radius_km and evidence.get('observation_time_assumed') else
                                  'spatially_consistent' if distance <= radius_km else 'outside_300m_gate',
                    'identity_confirmed': False})
        item['candidates'] = sorted(item['candidates'], key=lambda c: c['distance_m'])[:5]
        item['ambiguous'] = sum(c['within_gate'] and c['motion_consistent'] for c in item['candidates']) > 1
        if col < len(vessels) and costs[len(result)][col] <= 1:
            item.update({'association': 'provisional_spatiotemporal_match', 'matched_mmsi': vessels[col]['mmsi'],
                         'distance_km': round(distance_km(contact, vessels[col]['position']), 4),
                         'position_evidence': vessels[col]['position_evidence']})
        result.append(item)
    return result


def attach_latest(contacts, latest, acquired_utc, now=None):
    """Current AIS is a separate observation, never an acquisition-time fix."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    by_mmsi = {str(r['mmsi']).zfill(9): r for r in latest.get('vessels', []) if r.get('label') == 'real'}
    result = []
    for point in contacts:
        candidates = []
        for candidate in point.get('candidates', []):
            item = {**candidate, 'latest': None}
            row = by_mmsi.get(str(candidate['mmsi']).zfill(9))
            if row and row.get('received_utc') and row.get('lat') is not None and row.get('lon') is not None:
                received = timestamp(row['received_utc'])
                elapsed = received-timestamp(acquired_utc)
                if received <= now+60:
                    displacement = distance_km(candidate['position'], row)
                    speed = displacement/(elapsed/3600)/1.852 if elapsed > 0 else None
                    item['latest'] = {**row, 'age_s': max(0, round(now-received)), 'stale': now-received > 600,
                        'after_image': elapsed > 0, 'displacement_km': round(displacement, 3),
                        'minimum_average_speed_kn': round(speed, 2) if speed is not None else None,
                        'travel_consistency': 'exceeds_assumed_80kn_limit' if speed is not None and speed > 80 else
                                              'within_assumed_limit' if speed is not None else 'no_later_fix',
                        'caveat': 'Straight-line displacement is a lower bound, not a recorded voyage or identity proof. Reception time may differ from observation time.'}
            candidates.append(item)
        result.append({**point, 'candidates': candidates})
    return result
