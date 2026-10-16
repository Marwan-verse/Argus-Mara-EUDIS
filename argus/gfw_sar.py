"""Global Fishing Watch radar (Sentinel-1 SAR) vessel detections beside Coast Watch.

A second satellite source next to optical Sentinel-2: radar sees through cloud.
GFW publishes detections about five days after each pass on 0.01 degree cells
(about 1.1 x 0.7 km at Irish latitudes) in hourly bins, each flagged as matched
or not matched to GFW's own AIS. This module fetches them for the ~40 km coastal
belt, finds the Sentinel-1 scene that imaged each cell in the public Copernicus
catalogue to get the acquisition time, and joins the team's AIS at that time with
the Coast Watch rules (argus.satellite_ais.historical_ais, 300 m gate, 1 km
alternatives), from the linked Supabase history or the local archive.

Every result is real but unreviewed: a lead for an analyst, never proof that a
transponder was switched off. The token comes from GFW_API_TOKEN or the OS
credential store (python scripts/configure_gfw.py); it is never printed, logged
or saved in results. GFW terms: non-commercial use only (CC BY-NC 4.0), and
"Powered by Global Fishing Watch" wherever the data is shown.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import threading
import zipfile
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from argus import satellite
from argus.provenance import now_utc, utc
from argus.satellite_ais import text
from argus.space import assignment, distance_km, finite, timestamp

API = 'https://gateway.api.globalfishingwatch.org/v3'
DATASET = 'public-global-sar-presence:latest'
SERVICE, ACCOUNT = 'ArgusMara.GFW', 'api-token'
TOKEN_FORMAT = re.compile(r'[A-Za-z0-9._~+/=-]{20,4096}')
VERSION = 'gfw-sar-radar-v1'
CELL_DEG = .01          # HIGH spatial resolution; GFW reports the cell centre
GATE_KM = .3            # Coast Watch association gate, measured from the cell edge
ALTERNATIVE_KM = 1      # Coast Watch alternative radius; any closer AIS blocks a lead
MIN_LIVE_FIXES = 20     # fixes within 10 min around; stale "last fix" rows cannot pass as reception
MAX_DAYS = 31
MAX_ROWS = 20000
LIMIT = 16*1024*1024
LEAD_KIND = 'radar_without_ais'
ATTRIBUTION = 'Powered by Global Fishing Watch'
ATTRIBUTION_URL = 'https://globalfishingwatch.org'
LICENCE = 'Global Fishing Watch API terms: non-commercial use only (CC BY-NC 4.0); attribution required'
CAVEAT = ('Radar detections published by Global Fishing Watch from Copernicus Sentinel-1. Positions are 0.01 degree '
          'cells; most vessels under 15 m are missed and nothing within 1 km of shore is classified. GFW matching uses '
          "its own AIS; the team's AIS reception is partial. A contact without AIS is a lead for review, not proof "
          'that a transponder was switched off.')
JOIN_FIELDS = ('status', 'team_ais', 'candidates', 'matched_mmsis', 'unexplained', 'same_identity_as_gfw')


def valid_token(token):
    return isinstance(token, str) and TOKEN_FORMAT.fullmatch(token.strip()) is not None


def get_token():
    """Environment first, then the OS credential store. Empty means radar is off."""
    token = os.environ.get('GFW_API_TOKEN', '').strip() or _keyring_token()
    if token and not valid_token(token):
        raise ValueError('Invalid Global Fishing Watch token format')
    return token


def token_source():
    if os.environ.get('GFW_API_TOKEN', '').strip():
        return 'environment (GFW_API_TOKEN)'
    return 'credential store (%s)' % SERVICE if _keyring_token() else None


def _keyring_token():
    try:
        import keyring
        return keyring.get_password(SERVICE, ACCOUNT) or ''
    except Exception:
        return ''


def save_token(token):
    if not valid_token(token):
        raise ValueError('Expected a Global Fishing Watch API token')
    try:
        import keyring
        backend = keyring.get_keyring()
        if backend.priority <= 0 or 'plaintext' in type(backend).__module__.lower():
            raise ValueError('Use the operating system credential store')
        keyring.set_password(SERVICE, ACCOUNT, token.strip())
    except Exception:
        raise ValueError('Cannot save securely in the system credential store; set GFW_API_TOKEN instead') from None


def configured():
    try:
        return bool(get_token())
    except ValueError:
        return False


def http_message(code):
    messages = {401: 'Global Fishing Watch refused the token (HTTP 401); run python scripts/configure_gfw.py',
                403: 'Global Fishing Watch denied access to SAR detections (HTTP 403)',
                422: 'Global Fishing Watch rejected the request (HTTP 422); check the dates',
                429: 'Global Fishing Watch runs one report at a time and limits daily requests (HTTP 429); '
                     'wait, then retry by hand',
                524: 'The report took longer than 100 s (HTTP 524); fetch fewer days'}
    if code in messages:
        return messages[code]
    if code >= 500:
        return 'Global Fishing Watch is unavailable (HTTP %d); no automatic retry' % code
    return 'Global Fishing Watch request failed (HTTP %d)' % code


def decode_report(raw):
    """JSON, or a ZIP that holds the JSON beside GFW's caveat files."""
    try:
        if raw[:2] == b'PK':
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                members = [m for m in archive.infolist() if m.filename.lower().endswith('.json') and not m.is_dir()]
                for member in members[:5]:
                    if member.file_size > LIMIT:
                        raise ValueError('oversized member')
                    with archive.open(member) as stream:
                        content = stream.read(LIMIT+1)
                    if len(content) > LIMIT:
                        raise ValueError('oversized member')
                    value = json.loads(content)
                    if isinstance(value, dict) and 'entries' in value:
                        return value
                raise ValueError('no report in archive')
        return json.loads(raw)
    except (ValueError, zipfile.BadZipFile, UnicodeError, OSError, RuntimeError, EOFError):
        raise ValueError('Cannot read the Global Fishing Watch response') from None


def report_http(url, body, token, timeout=120):
    """POST one 4Wings report, bounded like satellite.json_http; never echoes bodies or the token."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != urlsplit(API).hostname:
        raise ValueError('Only the Global Fishing Watch API over HTTPS is contacted')
    if not valid_token(token):
        raise ValueError('Invalid Global Fishing Watch token format')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
               'User-Agent': 'ArgusMaraRadar/1.0', 'Authorization': 'Bearer ' + token.strip()}
    data = json.dumps(body, allow_nan=False).encode()
    try:
        with build_opener(satellite.NoRedirect()).open(Request(url, data=data, headers=headers), timeout=timeout) as response:
            raw = response.read(LIMIT+1)
    except HTTPError as error:
        error.close()
        raise ValueError(http_message(error.code)) from None
    except (OSError, UnicodeError):
        raise ValueError('Cannot reach Global Fishing Watch') from None
    if len(raw) > LIMIT:
        raise ValueError('Global Fishing Watch response exceeds limit; fetch fewer days')
    return decode_report(raw)


@lru_cache(maxsize=1)
def _grid():
    return json.loads(Path(__file__).with_name('coastal_grid.json').read_text(encoding='utf-8'))


def coastal_bbox():
    """West, south, east, north of the Coast Watch planning grid (~40 km belt)."""
    boxes = [tile['bbox'] for tile in _grid()['tiles']]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


@lru_cache(maxsize=1)
def _tile_index():
    index = {}
    for tile in _grid()['tiles']:
        w, s, e, n = tile['bbox']
        for i in range(math.floor(s*10), math.floor(n*10)+1):
            for j in range(math.floor(w*10), math.floor(e*10)+1):
                index.setdefault((i, j), []).append((w, s, e, n, tile['id']))
    return index


def coastal_tile(lat, lon):
    """Coast Watch planning cell holding this point, or None (open sea, Britain)."""
    for w, s, e, n, identifier in _tile_index().get((math.floor(lat*10), math.floor(lon*10)), ()):
        if w <= lon <= e and s <= lat <= n:
            return identifier
    return None


def window(start=None, end=None, days=14, today=None):
    """Calendar days as GFW reads them: start included, end excluded (default: up to yesterday)."""
    today = today or datetime.now(timezone.utc).date()
    try:
        last = date.fromisoformat(end) if end else today
        first = date.fromisoformat(start) if start else last-timedelta(days=int(days))
    except (TypeError, ValueError):
        raise ValueError('Use calendar dates YYYY-MM-DD') from None
    if not timedelta(days=1) <= last-first <= timedelta(days=MAX_DAYS):
        raise ValueError('Choose 1 to %d days; the end date is excluded' % MAX_DAYS)
    if first < date(2017, 1, 1):
        raise ValueError('GFW radar detections start in 2017')
    return first.isoformat(), last.isoformat()


def report_request(start, end, area, matched):
    """4Wings report for one match state; matched rows are grouped by vessel for identity and time."""
    w, s, e, n = (float(v) for v in area)
    params = [('spatial-resolution', 'HIGH'), ('temporal-resolution', 'HOURLY'),
              ('datasets[0]', DATASET), ('date-range', '%s,%s' % (start, end)), ('format', 'JSON'),
              ('filters[0]', "matched='true'" if matched else "matched='false'")]
    if matched:
        params.append(('group-by', 'VESSEL_ID'))
    body = {'geojson': {'type': 'Polygon', 'coordinates': [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}
    return API+'/4wings/report?'+urlencode(params), body


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def hour_of(value):
    """'2026-10-10 18:00' (an HOURLY bin) -> start of that UTC hour; None without an hour."""
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}):\d{2}(?::\d{2}(?:\.\d+)?)?Z?', str(value or '').strip())
    if not match:
        return None
    try:
        return utc('%sT%s:00:00Z' % (match[1], match[2]))
    except ValueError:
        return None


def exact_time(row, hour):
    """Equal entry and exit times in one hourly bin are a single detection instant."""
    entry, leave = row.get('entryTimestamp'), row.get('exitTimestamp')
    try:
        if hour and isinstance(entry, str) and entry and entry == leave:
            moment = utc(entry)
            if 0 <= timestamp(moment)-timestamp(hour) < 3600:
                return moment
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def vessel_of(row):
    """GFW's AIS identity for a matched radar contact; GFW's match, not the team's."""
    mmsi = str(row.get('mmsi') or '').strip()
    identity = {'vessel_id': text(row.get('vesselId'), 64),
                'mmsi': mmsi.zfill(9) if mmsi.isdigit() and len(mmsi) <= 9 and int(mmsi) else None,
                'name': text(row.get('shipName'), 80), 'flag': text(row.get('flag'), 3),
                'imo': text(row.get('imo'), 12), 'call_sign': text(row.get('callsign'), 16),
                'vessel_type': text(row.get('vesselType'), 40), 'gear_type': text(row.get('geartype'), 40)}
    return {key: value for key, value in identity.items() if value}


def parse_report(packet, matched, area):
    """Normalise the documented {'entries': [{'public-global-sar-presence:vX': [...]}]} report."""
    entries = packet.get('entries') if isinstance(packet, dict) else None
    if not isinstance(entries, list):
        raise ValueError('Unexpected Global Fishing Watch report format')
    w, s, e, n = (float(v) for v in area)
    rows, datasets = {}, set()
    for entry in entries:
        for dataset, items in (entry.items() if isinstance(entry, dict) else ()):
            if not isinstance(dataset, str) or not dataset.startswith('public-global-sar-presence') or not isinstance(items, list):
                continue
            datasets.add(dataset[:80])
            for item in items:
                if len(rows) >= MAX_ROWS:
                    raise ValueError('More than %d radar rows; fetch fewer days' % MAX_ROWS)
                if not isinstance(item, dict):
                    continue
                try:
                    lat, lon = finite(item['lat'], 'lat'), finite(item['lon'], 'lon')
                    count = finite(item.get('detections', 1), 'detections')
                except (KeyError, ValueError, TypeError):
                    continue
                if not (s-.05 <= lat <= n+.05 and w-.05 <= lon <= e+.05) or not 1 <= count <= 1000:
                    continue
                hour = hour_of(item.get('date'))
                vessel = vessel_of(item) if matched else {}
                identity = [dataset[:80], hour, round(lat, 5), round(lon, 5), matched, vessel.get('vessel_id')]
                key = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()[:20]
                if key in rows:
                    rows[key]['detections'] = max(rows[key]['detections'], int(count))
                    continue
                rows[key] = {'id': 'gfw-'+key, 'source': 'Global Fishing Watch', 'sensor': 'Sentinel-1',
                             'dataset': dataset[:80], 'label': 'real', 'review_status': 'unreviewed',
                             'lat': round(lat, 5), 'lon': round(lon, 5), 'cell_deg': CELL_DEG,
                             'hour_utc': hour, 'detections': int(count), 'gfw_matched': bool(matched),
                             'gfw_vessel': vessel or None, 'gfw_time_utc': exact_time(item, hour)}
    return list(rows.values()), datasets


def outer_rings(geometry):
    kind, coordinates = geometry['type'], geometry['coordinates']
    polygons = [coordinates] if kind == 'Polygon' else coordinates if kind == 'MultiPolygon' else []
    rings = []
    for polygon in polygons[:8]:
        ring = [(finite(p[0], 'lon'), finite(p[1], 'lat')) for p in polygon[0][:2000]]
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def inside(ring, lon, lat):
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]+ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1+(lat-y1)*(x2-x1)/(y2-y1):
            hit = not hit
    return hit


def sentinel1_scenes(start, end, area, transport=None):
    """Start, end and footprint of every Sentinel-1 scene (public Copernicus catalogue, free)."""
    transport = transport or satellite.json_http
    features = []

    def capture(url):
        page = transport(url)
        if isinstance(page, dict) and isinstance(page.get('features'), list):
            features.extend(page['features'][:30])
        return page
    # Reuses the bounded, validated pagination of the Coast Watch catalogue search.
    satellite.search('Sentinel-1', area, start+'T00:00:00Z', end+'T00:00:00Z', transport=capture, all_pages=True)
    scenes = []
    for item in features:
        try:
            props = item['properties']
            first = timestamp(utc(props.get('start_datetime') or props['datetime']))
            last = timestamp(utc(props.get('end_datetime') or props['datetime']))
            rings = outer_rings(item['geometry'])
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue
        identifier = item.get('id')
        if (not 0 <= last-first <= 120 or not rings or not isinstance(identifier, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', identifier)):
            continue
        scenes.append({'id': identifier, 'start': first, 'end': last, 'rings': rings,
                       'orbit': text(props.get('sat:orbit_state'), 16), 'platform': text(props.get('platform'), 24)})
    return scenes


def acquisition_time(detection, scenes):
    """Detection instant from GFW, else the Sentinel-1 scene that imaged the cell in its hour."""
    lat, lon, half = detection['lat'], detection['lon'], detection.get('cell_deg', CELL_DEG)/2
    corners = [(lon, lat), (lon-half, lat-half), (lon-half, lat+half), (lon+half, lat-half), (lon+half, lat+half)]

    def covers(scene):
        return any(inside(ring, x, y) for ring in scene['rings'] for x, y in corners)
    if detection.get('gfw_time_utc'):
        moment = timestamp(detection['gfw_time_utc'])
        used = sorted(sc['id'] for sc in scenes if sc['start']-2 <= moment <= sc['end']+2 and covers(sc))
        return {'time_utc': detection['gfw_time_utc'], 'time_source': 'gfw_detection_timestamp',
                'time_uncertainty_s': 0, 'scene_ids': used}
    unresolved = {'time_utc': None, 'time_uncertainty_s': None, 'scene_ids': []}
    if not detection.get('hour_utc'):
        return {**unresolved, 'time_source': 'no_hour_in_report'}
    start = timestamp(detection['hour_utc'])
    hits = [sc for sc in scenes if sc['end'] >= start and sc['start'] < start+3600 and covers(sc)]
    if not hits:
        return {**unresolved, 'time_source': 'hour_bin_only'}
    first, last = min(sc['start'] for sc in hits), max(sc['end'] for sc in hits)
    if last-first > 120:
        return {**unresolved, 'time_source': 'several_passes_in_hour'}
    return {'time_utc': iso(round((first+last)/2)), 'time_source': 'sentinel1_scene_midpoint',
            'time_uncertainty_s': round((last-first)/2, 1), 'scene_ids': sorted(sc['id'] for sc in hits)}


def cell_distance_km(cell, position):
    """Ground distance from an AIS position to a GFW cell; zero inside the cell."""
    half = cell.get('cell_deg', CELL_DEG)/2
    lat, lon = finite(position['lat'], 'lat'), finite(position['lon'], 'lon')
    near = {'lat': min(max(lat, cell['lat']-half), cell['lat']+half),
            'lon': min(max(lon, cell['lon']-half), cell['lon']+half)}
    return distance_km(near, {'lat': lat, 'lon': lon})


def candidate_of(vessel, edge_km, when, assigned):
    track = vessel.get('track') or []
    nearest = min(track, key=lambda p: abs(timestamp(p['ts'])-when)) if track else None
    evidence = vessel.get('position_evidence') or {}
    return {'mmsi': vessel['mmsi'], 'name': vessel.get('name') or vessel['mmsi'],
            'distance_m': round(edge_km*1000, 1), 'within_gate': edge_km <= GATE_KM, 'assigned': assigned,
            'motion_consistent': evidence.get('kinematic_consistency') != 'exceeds_assumed_limit',
            'nearest_fix_offset_s': round(abs(timestamp(nearest['ts'])-when), 1) if nearest else None,
            'position': {'lat': vessel['position']['lat'], 'lon': vessel['position']['lon']},
            'position_evidence': evidence, 'broadcast_fields': vessel.get('broadcast_fields') or {},
            'identity_confirmed': False}


def associate_cells(group, ais, min_fixes=MIN_LIVE_FIXES):
    """One acquisition time: GFW identities first, then the one-to-one 300 m gate per radar target."""
    vessels = ais.get('vessels') or []
    coverage = ais.get('coverage') or {}
    live = (coverage.get('nearby_fixes') or 0) >= min_fixes
    summary = {'source': ais.get('source') or 'local archive', 'coverage': coverage.get('status'),
               'nearby_fixes': coverage.get('nearby_fixes'), 'eligible_vessels': len(vessels),
               'reception_live': live, 'note': coverage.get('database_note')}
    edge = [[cell_distance_km(d, v['position']) for v in vessels] for d in group]
    eligible = [(v.get('position_evidence') or {}).get('kinematic_consistency') != 'exceeds_assumed_limit' for v in vessels]
    bound, taken = [[] for _ in group], set()
    for i, d in enumerate(group):
        mmsi = (d.get('gfw_vessel') or {}).get('mmsi')
        options = [j for j, v in enumerate(vessels) if mmsi and v['mmsi'] == mmsi and j not in taken
                   and eligible[j] and edge[i][j] <= ALTERNATIVE_KM]
        if options:
            j = min(options, key=lambda j: edge[i][j])
            bound[i].append(j)
            taken.add(j)
    identified = set(taken)  # GFW already says which radar target these AIS ships are
    units = [i for i, d in enumerate(group) for _ in range(max(0, min(d['detections'], 5)-len(bound[i])))]
    free = [j for j in range(len(vessels)) if j not in taken]
    if units and free:
        penalty = len(units)+1
        costs = [[edge[i][j]/GATE_KM + distance_km(group[i], vessels[j]['position'])*1e-3
                  if edge[i][j] <= GATE_KM and eligible[j] else penalty*3 for j in free] + [penalty]*len(units)
                 for i in units]
        for row, col in enumerate(assignment(costs)):
            if col < len(free) and costs[row][col] < penalty:
                bound[units[row]].append(free[col])
                taken.add(free[col])
    for i, d in enumerate(group):
        when = timestamp(d['time_utc'])
        unexplained = max(0, min(d['detections'], 5)-len(bound[i]))
        # As in Coast Watch, a lost one-to-one contest is ambiguity, not a dark vessel; any
        # unexplained AIS within 1 km of the cell also keeps the contact out of the lead list.
        conflict = [j for j in range(len(vessels)) if j not in bound[i] and j not in identified and
                    (edge[i][j] <= GATE_KM or (j not in taken and edge[i][j] <= ALTERNATIVE_KM))]
        status = ('team_ais_match' if unexplained == 0 else 'no_contemporaneous_ais' if not live else
                  'nearby_ais_review' if conflict else 'no_team_ais')
        order = sorted((j for j in range(len(vessels)) if edge[i][j] <= ALTERNATIVE_KM), key=lambda j: edge[i][j])
        gfw_mmsi = (d.get('gfw_vessel') or {}).get('mmsi')
        d.update(status=status, unexplained=unexplained, team_ais=summary,
                 matched_mmsis=[vessels[j]['mmsi'] for j in bound[i]],
                 same_identity_as_gfw=None if not gfw_mmsi or not bound[i] else gfw_mmsi in {vessels[j]['mmsi'] for j in bound[i]},
                 candidates=[candidate_of(vessels[j], edge[i][j], when, j in bound[i]) for j in order[:5]])
    return group


def join_ais(detections, ais_lookup):
    """Group detections by acquisition time; one AIS lookup per time and area."""
    groups = {}
    for d in detections:
        if d.get('time_utc'):
            groups.setdefault(d['time_utc'], []).append(d)
        else:
            d.update(status='time_unresolved', unexplained=None, team_ais=None, matched_mmsis=[],
                     same_identity_as_gfw=None, candidates=[])
    pad = CELL_DEG/2+.02  # keeps AIS within 1 km of edge cells inside the area
    for when, group in sorted(groups.items()):
        area = [min(d['lon'] for d in group)-pad, min(d['lat'] for d in group)-pad,
                max(d['lon'] for d in group)+pad, max(d['lat'] for d in group)+pad]
        try:
            ais = ais_lookup(when, area)
        except (ValueError, OSError) as error:
            for d in group:
                d.update(status='ais_unavailable', unexplained=None, matched_mmsis=[], candidates=[],
                         same_identity_as_gfw=None, team_ais={'error': str(error)[:160]})
            continue
        associate_cells(group, ais)
    return detections


def workspace_lookup(root):
    """The Coast Watch AIS source: linked Supabase history, else the local archive.

    The database history starts on 15 Oct 2026, while GFW radar arrives days late.
    When the database has no live reception at a radar time, an imported archive
    (for example the Railway Parquet chunks) with more fixes is used instead.
    """
    from argus.satellite_ais import historical_ais
    from argus.satellite_workspace import SatelliteWorkspace
    workspace = SatelliteWorkspace(root)

    def lookup(when, area):
        ais = workspace.ais_for_scene({'label': 'real', 'acquired_utc': when, 'bbox': area})
        fixes = ais['coverage'].get('nearby_fixes') or 0
        if ais.get('source') != 'supabase' or fixes >= MIN_LIVE_FIXES:
            return ais
        try:
            local = historical_ais(workspace.archive_root, when, area)
        except ValueError:
            return ais
        if (local['coverage'].get('nearby_fixes') or 0) <= fixes:
            return ais
        local['coverage']['database_note'] = 'The team database has little AIS at this radar time; local archive used.'
        return local
    return lookup


def is_lead(detection):
    return detection.get('status') == 'no_team_ais' and detection.get('gfw_matched') is False


def lead_of(detection):
    count = detection.get('unexplained') or detection.get('detections') or 1
    return {'id': 'gfw:'+detection['id'][4:], 'kind': LEAD_KIND, 'radar': True,
            'title': 'Radar contact without AIS', 'name': 'Radar contact '+detection['id'][4:12],
            'mmsi': None, 'lat': detection['lat'], 'lon': detection['lon'],
            'acquired_utc': detection['time_utc'], 'sensor': 'Sentinel-1 radar via Global Fishing Watch',
            'source_label': 'real', 'label': 'real', 'review_status': 'unreviewed', 'identity_confirmed': False,
            'detection_id': detection['id'], 'scene_id': None, 'contact_id': None,
            'evidence_text': 'Radar %s · real GFW detection' % detection['time_utc'],
            'action_text': 'Show radar contact on map',
            'reason': ('Sentinel-1 radar detected %d vessel%s in a ~1 km cell. Global Fishing Watch found no AIS match '
                       "and the team's AIS has no vessel within 1 km at that time. Reception is partial; small or "
                       'non-AIS craft and radar clutter are possible.' % (count, '' if count == 1 else 's'))}


def evidence_key(detection):
    """Changes when the radar or AIS evidence behind a lead changes, reopening analyst reviews."""
    keep = {k: detection.get(k) for k in ('id', 'dataset', 'lat', 'lon', 'cell_deg', 'hour_utc', 'detections',
                                          'gfw_matched', 'gfw_vessel', 'time_utc', 'time_source', 'scene_ids',
                                          'status', 'unexplained', 'matched_mmsis')}
    keep['candidates'] = [{k: c.get(k) for k in ('mmsi', 'distance_m', 'position', 'within_gate')}
                          for c in detection.get('candidates') or []]
    keep['team_ais'] = {k: (detection.get('team_ais') or {}).get(k)
                        for k in ('source', 'coverage', 'nearby_fixes', 'eligible_vessels')}
    content = json.dumps({'version': VERSION, 'detection': keep}, sort_keys=True, allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def counts_of(rows, outside=0):
    return {'detection_rows': len(rows), 'radar_targets': sum(d['detections'] for d in rows),
            'gfw_unmatched_rows': sum(not d['gfw_matched'] for d in rows),
            'gfw_matched_rows': sum(bool(d['gfw_matched']) for d in rows),
            'leads': sum(is_lead(d) for d in rows), 'outside_coastal_belt': outside,
            'statuses': dict(Counter(d.get('status') for d in rows))}


def fetch(root, start, end, *, area=None, coastal_only=True, token=None, transport=None,
          catalogue=None, ais_lookup=None):
    """Fetch both match states, time each cell from Sentinel-1, join team AIS, save the window."""
    transport = transport or report_http
    token = token or get_token()
    if not token:
        raise ValueError('Global Fishing Watch is not connected; run python scripts/configure_gfw.py')
    start, end = window(start, end)
    area = [float(v) for v in (area or coastal_bbox())]
    rows, datasets = [], set()
    for matched in (False, True):  # sequential: GFW refuses a second concurrent report
        url, body = report_request(start, end, area, matched)
        found, names = parse_report(transport(url, body, token), matched, area)
        rows.extend(found)
        datasets |= names
    outside = 0
    if coastal_only:
        for d in rows:
            d['coastal_tile'] = coastal_tile(d['lat'], d['lon'])
        outside = sum(d['coastal_tile'] is None for d in rows)
        rows = [d for d in rows if d['coastal_tile']]
    catalogue_error = None
    try:
        scenes = sentinel1_scenes(start, end, area, catalogue) if rows else []
    except ValueError as error:
        scenes, catalogue_error = [], str(error)[:200]
    for d in rows:
        d.update(acquisition_time(d, scenes))
    join_ais(rows, ais_lookup or workspace_lookup(root))
    hours = [d.get('time_utc') or d.get('hour_utc') for d in rows if d.get('time_utc') or d.get('hour_utc')]
    result = {'version': VERSION, 'label': 'real', 'review_status': 'unreviewed',
              'source': 'Global Fishing Watch 4Wings API, SAR vessel detections from Copernicus Sentinel-1',
              'datasets': sorted(datasets), 'attribution': ATTRIBUTION, 'attribution_url': ATTRIBUTION_URL,
              'licence': LICENCE, 'window': {'start': start, 'end_exclusive': end}, 'area': area,
              'coastal_only': coastal_only, 'fetched_utc': now_utc(),
              'newest_detection_utc': max(hours, key=timestamp) if hours else None,
              'catalogue': {'source': satellite.SAR_CATALOGUE, 'scenes': len(scenes), 'error': catalogue_error},
              'request': {'dataset': DATASET, 'spatial_resolution': 'HIGH', 'temporal_resolution': 'HOURLY',
                          'filters': ["matched='false'", "matched='true'"], 'matched_group_by': 'VESSEL_ID'},
              'parameters': {'cell_deg': CELL_DEG, 'gate_m': GATE_KM*1000, 'alternative_m': ALTERNATIVE_KM*1000,
                             'min_live_fixes': MIN_LIVE_FIXES, 'max_interpolation_gap_s': 600,
                             'max_past_projection_age_s': 300, 'max_plausible_speed_kn': 80},
              'counts': counts_of(rows, outside), 'caveat': CAVEAT, 'detections': rows}
    return result, save_result(root, result)


def rejoin(root, ais_lookup=None):
    """Repeat the AIS comparison for saved detections; no Global Fishing Watch request."""
    lookup = ais_lookup or workspace_lookup(root)
    paths = []
    for path, result in load_results(root):
        rows = result.get('detections', [])
        for d in rows:
            for key in JOIN_FIELDS:
                d.pop(key, None)
        join_ais(rows, lookup)
        result['counts'] = counts_of(rows, result.get('counts', {}).get('outside_coastal_belt', 0))
        result['joined_utc'] = now_utc()
        satellite.atomic_json(path, result)
        paths.append(path)
    return paths


def save_result(root, result):
    path = Path(root)/'radar'/('gfw-%s_%s.json' % (result['window']['start'], result['window']['end_exclusive']))
    satellite.atomic_json(path, result)
    return path


def load_results(root):
    folder = Path(root)/'radar'
    results = []
    for path in sorted(folder.glob('gfw-*.json'))[:200] if folder.is_dir() else []:
        if not re.fullmatch(r'gfw-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.json', path.name):
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get('version') == VERSION and isinstance(value.get('detections'), list):
            results.append((path, value))
    return results


_cache, _cache_lock = {'key': None, 'rows': [], 'results': []}, threading.Lock()


def _saved(root):
    folder = Path(root)/'radar'
    try:
        key = (str(folder), tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                                  for p in sorted(folder.glob('gfw-*.json')))) if folder.is_dir() else (str(folder), ())
    except OSError:
        key = None
    with _cache_lock:
        if key is not None and _cache['key'] == key:
            return _cache['rows'], _cache['results']
    results = load_results(root)
    best = {}
    # A detection fetched in several windows keeps its newest copy.
    for _path, result in sorted(results, key=lambda item: item[1].get('fetched_utc') or ''):
        for d in result['detections']:
            if isinstance(d, dict) and isinstance(d.get('id'), str):
                best[d['id']] = d
    rows = sorted(best.values(), key=lambda d: (d.get('time_utc') or d.get('hour_utc') or '', d['id']), reverse=True)
    summaries = [{'window': r.get('window'), 'fetched_utc': r.get('fetched_utc'), 'counts': r.get('counts'),
                  'newest_detection_utc': r.get('newest_detection_utc'), 'datasets': r.get('datasets')}
                 for _path, r in results]
    with _cache_lock:
        _cache.update(key=key, rows=rows, results=summaries)
    return rows, summaries


def detections(root):
    return _saved(root)[0]


def detection(root, identifier):
    found = next((d for d in detections(root) if d['id'] == identifier), None)
    if found is None:
        raise ValueError('Radar contact is no longer saved; fetch radar detections again')
    return found


def summary(root):
    rows, windows = _saved(root)
    newest = [w['newest_detection_utc'] for w in windows if w.get('newest_detection_utc')]
    return {'detections': len(rows), 'leads': sum(is_lead(d) for d in rows),
            'statuses': dict(Counter(d.get('status') for d in rows)), 'windows': windows,
            'newest_detection_utc': max(newest, key=timestamp) if newest else None,
            'attribution': ATTRIBUTION, 'attribution_url': ATTRIBUTION_URL}


def radar_index(root):
    """Incidents rows: (lead, evidence key) for every radar contact without AIS."""
    return [(lead_of(d), evidence_key(d)) for d in detections(root) if is_lead(d)]


def map_index(root):
    points = [{'id': d['id'], 'lat': d['lat'], 'lon': d['lon'], 'cell_deg': d.get('cell_deg', CELL_DEG),
               'time_utc': d.get('time_utc'), 'hour_utc': d.get('hour_utc'), 'status': d.get('status'),
               'lead': is_lead(d), 'gfw_matched': d.get('gfw_matched'), 'detections': d.get('detections'),
               'gfw_name': (d.get('gfw_vessel') or {}).get('name') or (d.get('gfw_vessel') or {}).get('mmsi')}
              for d in detections(root)]
    return {'points': points, 'summary': summary(root)}


def find_lead(root, lead_id):
    if not isinstance(lead_id, str) or not re.fullmatch(r'gfw:[0-9a-f]{20}', lead_id):
        raise ValueError('Invalid radar review lead')
    for d in detections(root):
        if is_lead(d) and 'gfw:'+d['id'][4:] == lead_id:
            return lead_of(d), evidence_key(d)
    raise ValueError('Radar lead is no longer present; reload the radar evidence')


def check_token(token, transport=None, today=None):
    """One small report (Dublin Bay, one day about a week ago) proves the token reads SAR detections."""
    transport = transport or report_http
    day = (today or datetime.now(timezone.utc).date())-timedelta(days=8)
    area = [-6.3, 53.2, -5.9, 53.5]
    url, body = report_request(day.isoformat(), (day+timedelta(days=1)).isoformat(), area, False)
    rows, datasets = parse_report(transport(url, body, token), False, area)
    return {'datasets': sorted(datasets), 'test_day': day.isoformat(), 'radar_rows': len(rows)}


def main():
    parser = argparse.ArgumentParser(description='Global Fishing Watch radar contacts compared with the team AIS')
    parser.add_argument('--root', default=os.environ.get('ARGUS_SATELLITE_ROOT', 'data/satellite'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='token state (never the token), saved windows and counts')
    get = commands.add_parser('fetch', help='fetch the coastal belt and compare with AIS at each radar time')
    get.add_argument('--start', help='first day, YYYY-MM-DD')
    get.add_argument('--end', help='day after the last day, YYYY-MM-DD (excluded)')
    get.add_argument('--days', type=int, default=14, help='days before --end (default 14)')
    get.add_argument('--whole-bbox', action='store_true', help='keep detections outside the ~40 km Irish belt')
    commands.add_parser('rejoin', help='repeat the AIS comparison for saved detections; no GFW request')
    commands.add_parser('leads', help='list radar contacts without AIS')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            result = {'configured': configured(), 'token_source': token_source(), **summary(args.root)}
        elif args.command == 'fetch':
            start, end = window(args.start, args.end, args.days)
            report, path = fetch(args.root, start, end, coastal_only=not args.whole_bbox)
            result = {'saved': str(path), 'window': report['window'], 'datasets': report['datasets'],
                      'newest_detection_utc': report['newest_detection_utc'], 'catalogue': report['catalogue'],
                      'counts': report['counts'], 'attribution': ATTRIBUTION,
                      'leads': [{k: lead[k] for k in ('id', 'acquired_utc', 'lat', 'lon')}
                                for lead in map(lead_of, filter(is_lead, report['detections']))]}
        elif args.command == 'rejoin':
            result = {'rejoined': [str(path) for path in rejoin(args.root)], **summary(args.root)}
        else:
            result = [{k: lead[k] for k in ('id', 'acquired_utc', 'lat', 'lon', 'reason')}
                      for lead, _key in radar_index(args.root)]
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
