"""Optional link to the team's Supabase database: AIS history and satellite comparison.

The database copies the team's public Railway AIS feed by itself every 30 seconds
(pg_cron + pg_net, see supabase/migrations), so AIS history keeps growing while
every laptop is closed. This module only reads AIS at an image's acquisition
time, saves image scenes and contacts, and asks the database to compare both
ways. Nothing is sent unless a Supabase secret key is configured through
ARGUS_SUPABASE_KEY, ARGUS_SUPABASE_KEY_FILE or the OS credential store
(python scripts/configure_supabase.py). Never put the key in Git, chat or
command arguments: it can read and write the whole database.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_URL = 'https://zibmytppznydhlggzlaq.supabase.co'
SERVICE, ACCOUNT = 'ArgusMara.Supabase', 'secret-key'
LIMIT = 16 * 1024 * 1024
KEY_FORMAT = re.compile(r'sb_secret_[A-Za-z0-9_-]{16,200}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
# The recorder/capture CSV columns read by argus.satellite_ais.historical_ais.
CSV_FIELDS = ['mmsi', 'msg_type', 'lat', 'lon', 'sog', 'cog', 'recv_utc', 'time_utc', 'timestamp_source',
              'stream_id', 'ship_name', 'ship_type', 'length_m', 'destination', 'nav_status', 'label',
              'present_fields']
SENSORS = {'Sentinel-1', 'Sentinel-2'}
MERCATOR_R = 6378137.0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def base_url():
    url = os.environ.get('ARGUS_SUPABASE_URL', DEFAULT_URL).strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.path:
        raise ValueError('ARGUS_SUPABASE_URL must be an https://<project>.supabase.co address')
    return url


def valid_key(key):
    return isinstance(key, str) and KEY_FORMAT.fullmatch(key.strip()) is not None


def get_key():
    """Environment, then a host secret file, then the OS credential store. Empty means off."""
    key = os.environ.get('ARGUS_SUPABASE_KEY', '').strip()
    path = os.environ.get('ARGUS_SUPABASE_KEY_FILE')
    if not key and path:
        try:
            key = Path(path).read_text(encoding='utf-8').strip()
        except OSError:
            raise ValueError('Cannot read the Supabase secret file') from None
    if not key:
        key = _keyring_password()
    if key and not valid_key(key):
        raise ValueError('Invalid Supabase secret key format')
    return key


def _keyring_password():
    try:
        import keyring
        return keyring.get_password(SERVICE, ACCOUNT) or ''
    except Exception:
        return ''


def save_key(key):
    if not valid_key(key):
        raise ValueError('Expected a Supabase secret key (sb_secret_...) or the legacy service_role key')
    try:
        import keyring
        backend = keyring.get_keyring()
        if backend.priority <= 0 or 'plaintext' in type(backend).__module__.lower():
            raise ValueError('Use the operating system credential store')
        keyring.set_password(SERVICE, ACCOUNT, key.strip())
    except Exception:
        raise ValueError('Cannot save securely in the system credential store; use ARGUS_SUPABASE_KEY_FILE') from None


def configured():
    try:
        return bool(get_key())
    except ValueError:
        return False


LINK_FILE = 'database.link'


def linked(root):
    """Use the database only for a workspace explicitly linked to it.

    A stored key alone is not enough, so test runs in temporary folders can never
    write into the team database. scripts/configure_supabase.py writes the link
    file into data/satellite; a Docker host sets ARGUS_SUPABASE_LINK=1 instead.
    """
    if os.environ.get('ARGUS_SUPABASE_LINK') == '1' or (Path(root)/LINK_FILE).is_file():
        return configured()
    return False


def link(root):
    path = Path(root)/LINK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'url': base_url(), 'note': 'Coast Watch uses the team Supabase database. '
                                'Delete this file to stop.'}, indent=2) + '\n', encoding='utf-8')
    return path


def headers_for(key):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
               'User-Agent': 'ArgusMara-Supabase/1.0', 'apikey': key}
    # New sb_secret_ keys are not JWTs and are refused in Authorization.
    if not key.startswith('sb_'):
        headers['Authorization'] = 'Bearer ' + key
    return headers


def http_rpc(url, payload, key, timeout=30):
    """POST one PostgREST RPC call; never echo response bodies or the key."""
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS is required')
    body = json.dumps(payload, allow_nan=False).encode()
    try:
        with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers_for(key)), timeout=timeout) as response:
            raw = response.read(LIMIT + 1)
    except HTTPError as error:
        if error.code in (401, 403):
            raise ValueError('Supabase refused the key (HTTP %d); check the secret key' % error.code) from None
        raise ValueError('Supabase request failed (HTTP %d)' % error.code) from None
    except (OSError, UnicodeError):
        raise ValueError('Cannot reach the Supabase database') from None
    if len(raw) > LIMIT:
        raise ValueError('Supabase response exceeds limit')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Cannot read the Supabase response') from None


def rpc(name, payload, *, transport=http_rpc):
    if not re.fullmatch(r'argus_[a-z_]{3,40}', name):
        raise ValueError('Unknown database function')
    key = get_key()
    if not key:
        raise ValueError('Supabase is not configured; run python scripts/configure_supabase.py')
    return transport(base_url() + '/rest/v1/rpc/' + name, payload, key)


def status(*, transport=http_rpc):
    return rpc('argus_ais_status', {}, transport=transport)


def ais_rows(acquired_utc, area, *, transport=http_rpc):
    w, s, e, n = (float(v) for v in area)
    return rpc('argus_ais_rows', {'p_t': acquired_utc, 'p_w': w, 'p_s': s, 'p_e': e, 'p_n': n}, transport=transport)


def write_rows_csv(rows, path):
    with Path(path).open('w', encoding='utf-8', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            if isinstance(row, dict):
                writer.writerow({key: '' if row.get(key) is None else row[key] for key in CSV_FIELDS})


def historical_ais_from_database(acquired_utc, area, *, transport=http_rpc):
    """The same join as argus.satellite_ais.historical_ais, fed from the database."""
    from argus.satellite_ais import historical_ais
    packet = ais_rows(acquired_utc, area, transport=transport)
    rows = packet.get('rows') if isinstance(packet, dict) else None
    if not isinstance(rows, list):
        raise ValueError('Unexpected Supabase AIS response')
    excluded = packet.get('excluded_vessels', [])
    reasons = {'conflicting_positions_at_same_time', 'mixed_provenance', 'ambiguous_stream_epochs'}
    if not isinstance(excluded, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('mmsi'), str) or
            not re.fullmatch(r'[0-9]{9}', item['mmsi']) or
            item.get('reason') not in reasons for item in excluded):
        raise ValueError('Invalid Supabase AIS source-quality evidence')
    positions = sum(1 for row in rows if isinstance(row, dict) and row.get('msg_type') == 'PositionReport')
    with tempfile.TemporaryDirectory(prefix='argus-supabase-ais-') as folder:
        write_rows_csv(rows, Path(folder)/'supabase_ais.csv')
        result = historical_ais(folder, acquired_utc, area)
    blocked = {item['mmsi'] for item in excluded}
    result['vessels'] = [v for v in result['vessels'] if v['mmsi'] not in blocked]
    combined = result['coverage'].get('excluded_vessels', []) + excluded
    result['coverage'].update(excluded_vessels=[dict(mmsi=m, reason=r) for m, r in
                              sorted({(item['mmsi'], item['reason']) for item in combined})],
                              eligible_vessels=len(result['vessels']),
                              status='partial' if result['vessels'] else 'unavailable')
    result['source'] = 'supabase'
    result['coverage'].update(source='Team Supabase database (Railway AIS feed copied every 30 s)',
                              database_position_rows=positions)
    return result


def confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    value = value/100 if 1 < value <= 100 else value
    return round(float(value), 3) if 0 <= value <= 1 else None


def scene_payload(scene, contacts, observed_areas=(), source='argus-coast-watch', *, analysis=None):
    sensor = scene.get('sensor') if scene.get('sensor') in SENSORS else 'other'
    real = scene.get('label') in {'real', 'reconstructed'}
    items = []
    for index, point in enumerate(contacts or []):
        lat, lon = point.get('lat'), point.get('lon')
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)):
            continue
        items.append({'external_id': str(point.get('id') or index)[:120], 'lat': lat, 'lon': lon,
                      'overlap_ambiguous': point.get('overlap_ambiguous') is True,
                      'source': point.get('source') if point.get('source') in {'compact_optical_feature', 'tensorx_ai_pixel_supported'} else 'tensorx_ai',
                      'localization': point.get('localization') or {},
                      'label': 'assumption', 'confidence': confidence(point.get('confidence')),
                      'note': str(point.get('description') or '')[:300] or None})
    return {'id': scene['id'], 'sensor': sensor, 'acquired_utc': scene['acquired_utc'],
            'bbox': [float(v) for v in scene['bbox']], 'source': source,
            'label': 'real' if real else 'simulated', 'contacts': items,
            'review_evidence': {'version': 'image-ais-review-v2',
                                'image_input_verified': bool(analysis and analysis.get('image_input_verified') is True),
                                'image_status': (analysis or {}).get('image_status', 'limited'),
                                'clear_footprint_radius_m': 100},
            'observed_areas': [[float(v) for v in area] for area in observed_areas]}


def save_scene(scene, contacts, observed_areas=(), *, analysis=None, transport=http_rpc):
    return rpc('argus_save_scene', {'payload': scene_payload(scene, contacts, observed_areas, analysis=analysis)}, transport=transport)


def compare_scene(scene_id, gate_m=300, alt_m=1000, min_length_m=50, *, transport=http_rpc):
    return rpc('argus_compare_scene', {'p_scene': scene_id, 'gate_m': gate_m, 'alt_m': alt_m,
                                       'min_length_m': min_length_m}, transport=transport)


def _lon(x):
    return math.degrees(x/MERCATOR_R)


def _lat(y):
    return math.degrees(2*math.atan(math.exp(y/MERCATOR_R)) - math.pi/2)


def observed_rectangles(scene, folder, tiles=16, min_fraction=1.0, *, analysis=None):
    """Tiles of the crop where the quality mask says the sea was clearly visible.

    The crop grid is Web Mercator (argus.satellite.crop_scene), so a tile is a
    longitude/latitude rectangle. Cloud, land and shadow tiles are left out, so
    the database never asks why a ship was "not seen" under a cloud.
    """
    if not scene.get('quality_sha256') or not scene.get('mercator_bounds'):
        return []
    from argus.satellite_screen import water_mask
    from argus.satellite_compare import region_coverage, VISIBILITY_RADIUS_M
    import numpy as np
    mask, _ = water_mask(scene, Path(folder))
    height, width = mask.shape
    left, bottom, right, top = (float(v) for v in scene['mercator_bounds'])
    scale = min(math.cos(math.radians(v)) for v in (scene['bbox'][1], scene['bbox'][3]))
    # One additional pixel covers continuous positions at a published rectangle's
    # inclusive boundary, not only the centres of its source pixels.
    rx = math.ceil(VISIBILITY_RADIUS_M/scale/(right-left)*width)+1
    ry = math.ceil(VISIBILITY_RADIUS_M/scale/(top-bottom)*height)+1
    if 2*rx >= width or 2*ry >= height:
        return []
    # Every exported AIS centre must have a full clear footprint, including
    # beyond its tile edge. Summed-area erosion avoids a large rank filter.
    integral = np.pad(mask.astype('int64'), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    dx, dy = 2*rx+1, 2*ry+1
    sums = integral[dy:, dx:]-integral[:-dy, dx:]-integral[dy:, :-dx]+integral[:-dy, :-dx]
    safe = np.zeros_like(mask)
    safe[ry:height-ry, rx:width-rx] = sums == dx*dy
    mask = safe
    areas = []
    for i in range(tiles):
        r0, r1 = i*height//tiles, (i+1)*height//tiles
        for j in range(tiles):
            c0, c1 = j*width//tiles, (j+1)*width//tiles
            block = mask[r0:r1, c0:c1]
            if block.size and block.all():
                extent = [(c0-rx)/width, (r0-ry)/height, (c1+rx)/width, (r1+ry)/height]
                if analysis is not None and region_coverage(scene, analysis, extent) != 'complete':
                    continue
                x0, x1 = left + c0*(right-left)/width, left + c1*(right-left)/width
                y0, y1 = top - r1*(top-bottom)/height, top - r0*(top-bottom)/height
                # Round inward; never expand a clear tile over excluded pixels.
                areas.append([math.ceil(_lon(x0)*1e6)/1e6, math.ceil(_lat(y0)*1e6)/1e6,
                              math.floor(_lon(x1)*1e6)/1e6, math.floor(_lat(y1)*1e6)/1e6])
    return areas


def summary(comparison):
    if not isinstance(comparison, dict):
        return None
    return {'counts': comparison.get('counts'),
            'matches': len(comparison.get('matches') or []),
            'seen_without_ais': len(comparison.get('seen_without_ais') or []),
            'ais_not_seen': len(comparison.get('ais_not_seen') or []),
            'not_checked': comparison.get('not_checked')}


def publish_review(scene, contacts, folder, *, analysis=None, transport=http_rpc):
    """Save one reviewed crop and its AI contacts, then compare with database AIS. Never raises."""
    if not configured():
        return {'saved': False, 'reason': 'Supabase not configured'}
    try:
        areas = observed_rectangles(scene, folder, analysis=analysis) if analysis and analysis.get('image_input_verified') is True else []
        saved = save_scene(scene, contacts, areas, analysis=analysis, transport=transport)
        comparison = compare_scene(scene['id'], transport=transport) if scene.get('label') in {'real', 'reconstructed'} else None
        return {'saved': True, **(saved if isinstance(saved, dict) else {}), 'summary': summary(comparison),
                'comparison': comparison}
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'saved': False, 'error': str(error)[:200]}


def main():
    parser = argparse.ArgumentParser(description='Team Supabase database: AIS history and satellite comparison')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='sync health, row counts and database size')
    compare = commands.add_parser('compare', help='compare a saved scene with AIS at its acquisition time')
    compare.add_argument('scene')
    compare.add_argument('--gate-m', type=float, default=300)
    compare.add_argument('--alt-m', type=float, default=1000)
    compare.add_argument('--min-length-m', type=float, default=50)
    at = commands.add_parser('ais-at', help='AIS vessels at a time inside a box (same rules as Coast Watch)')
    at.add_argument('--time', required=True, help='ISO UTC, e.g. 2026-10-16T11:32:01Z')
    at.add_argument('--bbox', required=True, type=float, nargs=4, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    push = commands.add_parser('push-reviews', help='save existing Coast Watch reviews into the database')
    push.add_argument('--root', default=os.environ.get('ARGUS_SATELLITE_ROOT', 'data/satellite'))
    args = parser.parse_args()
    try:
        if args.command == 'status':
            result = status()
        elif args.command == 'compare':
            result = compare_scene(args.scene, args.gate_m, args.alt_m, args.min_length_m)
        elif args.command == 'ais-at':
            ais = historical_ais_from_database(args.time, args.bbox)
            result = {'coverage': ais['coverage'],
                      'vessels': [{'mmsi': v['mmsi'], 'name': v['name'], 'position': v['position']} for v in ais['vessels']]}
        else:
            result = []
            folder = Path(args.root)
            for path in sorted((folder/'reviews').glob('*.json')):
                review = json.loads(path.read_text(encoding='utf-8'))
                if (review.get('visual') or {}).get('image_input_verified') is not True:
                    continue
                outcome = publish_review(review['scene'], review.get('contacts'), folder/'scenes', analysis=review.get('visual'))
                result.append({'scene': review['scene']['id'], 'saved': outcome.get('saved'),
                               'summary': outcome.get('summary'), 'error': outcome.get('error')})
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
