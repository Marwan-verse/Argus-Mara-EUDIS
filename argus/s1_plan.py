"""Next Sentinel-1 radar look at the Irish coast, from ESA's published acquisition plans.

ESA publishes Sentinel-1 acquisition plans as keyless KML files about three weeks
ahead (``PAGE``). Every placemark is one planned data-take: satellite, mode,
polarisation, start and stop UTC, orbit and a footprint ring. ``refresh`` finds the
newest plan of each satellite still planning (plus older plans still in force now),
keeps the raw KML under ``data/s1_plan/`` and a parsed copy of the data-takes over
Irish waters beside it. Everything else works offline from that cache, or from the
bundled snapshot of real plans (``s1_plan_snapshot.json``) when nothing is cached.

* A newer plan file replaces an older one from its own start time: each moment is
  governed by the newest plan of that satellite that covers it.
* Footprint edges are great-circle arcs. They are straight lines in a gnomonic
  projection centred on Ireland, where the polygon tests run. A pass counts for the
  coast when its footprint polygon really intersects a Coast Watch grid cell, so a
  long strip that crosses the coast with no vertex near it still counts.
* Checked on 15-16 Oct 2026 against the published frames of two passes: frame
  corners lay within 20 km of the planned edges (straight lon/lat edges were off by
  up to 39 km). A position within ``EDGE_KM`` of an edge is "edge of swath".
* The time over a position is interpolated along the strip, from the ring's first
  vertex (where ESA's rings start) towards its farthest vertex.
* GRD frames reached the public Copernicus catalogue 36-85 min after the pass in
  checks on 15-16 Oct 2026, so frames are shown as online about 1 h later.

A plan is not an acquisition: ESA re-plans (for example for emergency requests) and
nothing here confirms that an image was taken. Label: real (published plan).
Run ``python -m argus.s1_plan refresh`` to download, ``python -m argus.s1_plan next``
to print the countdown.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET

from argus.satellite import IRISH_BBOX, NoRedirect

PAGE = 'https://sentinels.copernicus.eu/copernicus/sentinel-1/acquisition-plans'
DOCUMENTS = 'https://sentinels.copernicus.eu/documents/d/sentinel/'
HOST = 'sentinels.copernicus.eu'
NAME = re.compile(r's1([a-z])_mp_user_(\d{8}t\d{6})_(\d{8}t\d{6})')
KML = '{http://www.opengis.net/kml/2.2}'
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'data'/'s1_plan'
SNAPSHOT = Path(__file__).with_name('s1_plan_snapshot.json')
GRID = Path(__file__).with_name('coastal_grid.json')
VERSION = 's1-plan-v1'
LABEL = 'real'
PAGE_LIMIT = 4*1024*1024
KML_LIMIT = 16*1024*1024
KEEP = 4                # plan files kept per satellite in the cache
EDGE_KM = 20            # published frames vs planned edges, measured 15-16 Oct 2026
ONLINE_MIN = 60         # GRD frames in the public catalogue after a pass: 36-85 min measured
R_KM = 6371.0088
CENTRE = (53.4, -8.0)   # lat, lon: the island centre argus.satellite_scan.coast_for_bounds uses
FAR_COS = math.cos(math.radians(80))
HORIZON_DAYS = 21
CAVEAT = ('Planned Sentinel-1 data-takes from ESA acquisition plans, not confirmed images: ESA re-plans, and '
          'swath edges are uncertain by about %d km. Frames usually reach the public Copernicus catalogue about '
          '1 h after a pass (36-85 min measured on 15-16 Oct 2026).' % EDGE_KM)

_LAT0, _LON0 = math.radians(CENTRE[0]), math.radians(CENTRE[1])
_SIN0, _COS0 = math.sin(_LAT0), math.cos(_LAT0)


def epoch(value):
    """ESA writes UTC without an offset ('2026-10-16T18:00:23'); 'Z' and offsets are read too."""
    moment = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def iso(seconds):
    return datetime.fromtimestamp(round(seconds), timezone.utc).isoformat().replace('+00:00', 'Z')


def now_epoch():
    return datetime.now(timezone.utc).timestamp()


# Geometry. Gnomonic x, y are in Earth radii; near Ireland one unit is about R_KM.

def project(lon, lat):
    """Gnomonic x, y about Ireland, where great circles are straight lines; None beyond 80 degrees."""
    phi, delta = math.radians(lat), math.radians(lon)-_LON0
    cos_c = _SIN0*math.sin(phi)+_COS0*math.cos(phi)*math.cos(delta)
    if cos_c < FAR_COS:
        return None
    return (math.cos(phi)*math.sin(delta)/cos_c,
            (_COS0*math.sin(phi)-_SIN0*math.cos(phi)*math.cos(delta))/cos_c)


def _unit(lon, lat):
    phi, lam = math.radians(lat), math.radians(lon)
    return (math.cos(phi)*math.cos(lam), math.cos(phi)*math.sin(lam), math.sin(phi))


def _dot(a, b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]


def _cross3(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _angle(a, b):
    return math.atan2(math.sqrt(sum(v*v for v in _cross3(a, b))), _dot(a, b))


def inside(poly, x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]+poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1+(y-y1)*(x2-x1)/(y2-y1):
            hit = not hit
    return hit


def _side(o, a, b):
    return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])


def _segments_meet(p1, p2, q1, q2):
    d1, d2, d3, d4 = _side(q1, q2, p1), _side(q1, q2, p2), _side(p1, p2, q1), _side(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0) and d1 and d2) and ((d3 > 0) != (d4 > 0) and d3 and d4):
        return True

    def on(a, b, c, d):
        return d == 0 and min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
    return on(q1, q2, p1, d1) or on(q1, q2, p2, d2) or on(p1, p2, q1, d3) or on(p1, p2, q2, d4)


def _box(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_meet(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def polygons_intersect(a, b):
    """True when two simple plane polygons share any point: an edge crossing or one inside the other.

    Not a vertex test: a long swath crosses a small area with no vertex of
    either polygon inside the other, and only the edge crossings find it.
    """
    if not _boxes_meet(_box(a), _box(b)):
        return False
    if any(inside(b, *p) for p in a) or any(inside(a, *p) for p in b):
        return True
    edges_b = list(zip(b, b[1:]+b[:1]))
    return any(_segments_meet(p1, p2, q1, q2) for p1, p2 in zip(a, a[1:]+a[:1]) for q1, q2 in edges_b)


def _segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = dx*dx+dy*dy
    t = 0 if not length else max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def edge_km(poly, point):
    """Distance from a projected point to the nearest footprint edge, in km (gnomonic scale near Ireland)."""
    return min(_segment_distance(point, a, b) for a, b in zip(poly, poly[1:]+poly[:1]))*R_KM


@lru_cache(maxsize=4096)
def _prepared(ring):
    """Projected footprint, its box and the along-track axis; None for footprints reaching beyond 80 degrees.

    A data-take lasts at most about 14 minutes (about 5,800 km), so a footprint
    with a vertex 80 degrees from Ireland cannot also touch Irish waters.
    """
    poly = [project(lon, lat) for lon, lat in ring]
    if any(point is None for point in poly):
        return None
    start = _unit(*ring[0])
    far = max((_unit(*vertex) for vertex in ring[1:]), key=lambda v: _angle(start, v))
    normal = _cross3(start, far)
    size = math.sqrt(_dot(normal, normal))
    if not size:
        return None
    normal = tuple(v/size for v in normal)
    return {'poly': poly, 'box': _box(poly), 'start': start, 'ahead': _cross3(normal, start),
            'span': _angle(start, far)}


def _ring(take):
    return tuple((float(lon), float(lat)) for lon, lat in take['ring'])


def fraction(prepared, lon, lat):
    """Share of the strip's length, from its start, at which the satellite images this position."""
    point = _unit(lon, lat)
    angle = math.atan2(_dot(point, prepared['ahead']), _dot(point, prepared['start']))
    return min(1.0, max(0.0, angle/prepared['span']))


def _area(bbox, steps=8):
    """Plane polygon of a lon/lat box; its parallels are curves in the gnomonic plane, so sides are split."""
    w, s, e, n = bbox
    sides = ([(w+(e-w)*i/steps, s) for i in range(steps)]+[(e, s+(n-s)*i/steps) for i in range(steps)]
             +[(e-(e-w)*i/steps, n) for i in range(steps)]+[(w, n-(n-s)*i/steps) for i in range(steps)])
    return [project(lon, lat) for lon, lat in sides]


IRISH_WATERS = _area(IRISH_BBOX)


def over_irish_waters(ring):
    prepared = _prepared(tuple((float(lon), float(lat)) for lon, lat in ring))
    return prepared is not None and polygons_intersect(prepared['poly'], IRISH_WATERS)


def coast_of(lon, lat):
    """Planning sector of a cell centre, the rule of argus.satellite_scan.coast_for_bounds."""
    x, y = (lon-CENTRE[1])*math.cos(math.radians(CENTRE[0])), lat-CENTRE[0]
    if abs(y) >= abs(x):
        return 'North' if y >= 0 else 'South'
    return 'East' if x >= 0 else 'West'


@lru_cache(maxsize=1)
def coastal_cells():
    """Coast Watch planning cells (about 8 km, 40 km belt) projected once: id, coast, centre, corners, radius."""
    grid = json.loads(GRID.read_text(encoding='utf-8'))
    cells = []
    for tile in grid['tiles']:
        w, s, e, n = (float(v) for v in tile['bbox'])
        corners = [project(w, s), project(e, s), project(e, n), project(w, n)]
        centre = project((w+e)/2, (s+n)/2)
        radius = max(math.dist(centre, corner) for corner in corners)
        cells.append((tile['id'], coast_of((w+e)/2, (s+n)/2), centre, corners, radius, (w+e)/2, (s+n)/2))
    return tuple(cells), _box([corner for cell in cells for corner in cell[3]])


@lru_cache(maxsize=1024)
def _covered_cells(ring):
    """Coastal cells a footprint really intersects: centre inside, or an exact test near its edges."""
    prepared = _prepared(ring)
    cells, box = coastal_cells()
    if prepared is None or not _boxes_meet(prepared['box'], box):
        return ()
    poly, (x0, y0, x1, y1) = prepared['poly'], prepared['box']
    hits = []
    for cell in cells:
        (cx, cy), corners, radius = cell[2], cell[3], cell[4]
        if cx+radius < x0 or cx-radius > x1 or cy+radius < y0 or cy-radius > y1:
            continue
        if inside(poly, cx, cy):
            hits.append(cell)
        elif edge_km(poly, (cx, cy))/R_KM <= radius and polygons_intersect(poly, corners):
            hits.append(cell)
    return tuple(hits)


# ESA plan files.

def plan_name(name):
    """{'file', 'satellite', 'start', 'end'} from 's1d_mp_user_20261016t175423_20261105t200200', else None."""
    match = NAME.fullmatch(str(name))
    if not match:
        return None
    try:
        start, end = (datetime.strptime(value, '%Y%m%dt%H%M%S').replace(tzinfo=timezone.utc).timestamp()
                      for value in match.group(2, 3))
    except ValueError:
        return None
    if end <= start:
        return None
    return {'file': match[0], 'satellite': 'S1'+match[1].upper(), 'start': start, 'end': end}


def listed_plans(html):
    """Plan files named on the acquisition-plans page; links come in several forms, so names are matched."""
    found = {}
    for match in NAME.finditer(html):
        info = plan_name(match[0])
        if info:
            found[info['file']] = info
    return sorted(found.values(), key=lambda p: (p['satellite'], p['start'], p['end']))


def wanted(listed, now):
    """Per satellite still planning after now: the newest plan, plus older ones back to the one in force now."""
    chosen = []
    for satellite in sorted({plan['satellite'] for plan in listed}):
        plans = sorted((p for p in listed if p['satellite'] == satellite), key=lambda p: (p['start'], p['end']),
                       reverse=True)
        if plans[0]['end'] < now:
            continue  # retired or idle, like S1A since 29 Jun 2026
        for plan in plans[:KEEP]:
            chosen.append(plan)
            if plan['start'] <= now:
                break
    return chosen


def http_get(url, limit, timeout=60):
    """Bounded keyless GET from ESA Sentinel Online only; redirects are refused."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != HOST:
        raise ValueError('Only ESA Sentinel Online (%s) is contacted, over HTTPS' % HOST)
    request = Request(url, headers={'User-Agent': 'ArgusMaraS1Plan/1.0'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(limit+1)
    except HTTPError as error:
        error.close()
        raise ValueError('ESA Sentinel Online refused the request (HTTP %d)' % error.code) from None
    except (OSError, UnicodeError):
        raise ValueError('Cannot reach ESA Sentinel Online') from None
    if len(raw) > limit:
        raise ValueError('ESA response exceeds the size limit')
    return raw


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datatake(placemark):
    data = {item.get('name'): (item.findtext(KML+'value') or '').strip() for item in placemark.iter(KML+'Data')}
    satellite, mode = data.get('SatelliteId', ''), data.get('Mode', '')
    if not re.fullmatch(r'S1[A-Z]', satellite) or not re.fullmatch(r'[A-Z]{2,3}', mode):
        raise ValueError('not a Sentinel-1 data-take')
    start, stop = epoch(data['ObservationTimeStart']), epoch(data['ObservationTimeStop'])
    if not 0 < stop-start <= 3600:
        raise ValueError('implausible duration')
    ring_element = next(placemark.iter(KML+'LinearRing'), None)
    text = ring_element.findtext(KML+'coordinates') if ring_element is not None else ''
    ring = []
    for token in (text or '').split()[:200]:
        lon, lat = (float(value) for value in token.split(',')[:2])
        # Rings across the antimeridian keep going past -180 (-194.4 for 165.6); the geometry is periodic.
        if not (math.isfinite(lon) and math.isfinite(lat) and -360 <= lon <= 360 and -90 <= lat <= 90):
            raise ValueError('coordinates outside WGS84')
        ring.append([round(lon, 5), round(lat, 5)])
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise ValueError('no footprint')
    return {'satellite': satellite, 'datatake': re.sub(r'[^0-9A-Za-z]', '', data.get('DatatakeId', ''))[:12],
            'mode': mode, 'polarisation': re.sub(r'[^A-Z]', '', data.get('Polarisation', ''))[:4],
            'start_utc': iso(start), 'stop_utc': iso(stop),
            'orbit_absolute': _number(data.get('OrbitAbsolute')), 'orbit_relative': _number(data.get('OrbitRelative')),
            'ring': ring}


def parse_kml(raw):
    """Every readable data-take of one plan file, and the count of unreadable placemarks."""
    if len(raw) > KML_LIMIT:
        raise ValueError('Plan file exceeds the size limit')
    if re.search(rb'<!\s*(doctype|entity)', raw, re.IGNORECASE):
        raise ValueError('A plan file with a document type declaration is refused')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('Cannot read the Sentinel-1 plan file') from None
    takes, unreadable = [], 0
    for placemark in root.iter(KML+'Placemark'):
        try:
            takes.append(_datatake(placemark))
        except (KeyError, ValueError, TypeError, OverflowError):
            unreadable += 1
    return takes, unreadable


def plan_record(raw, name, fetched_utc):
    """Cache record of one plan file: provenance plus the data-takes over Irish waters."""
    info = plan_name(name)
    if info is None:
        raise ValueError('Not an ESA Sentinel-1 plan file name: %s' % name)
    takes, unreadable = parse_kml(raw)
    near = [take for take in takes if take['satellite'] == info['satellite'] and over_irish_waters(take['ring'])]
    return {'version': VERSION, 'file': info['file'], 'satellite': info['satellite'], 'label': LABEL,
            'plan_start_utc': iso(info['start']), 'plan_end_utc': iso(info['end']),
            'source_url': DOCUMENTS+info['file'], 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'fetched_utc': fetched_utc, 'datatakes_in_file': len(takes), 'unreadable_placemarks': unreadable,
            'area': 'Irish waters %s (west, south, east, north)' % IRISH_BBOX, 'datatakes': near}


def _publish(path, data):
    """Write next to the target, then replace it, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.stem+'-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def store(raw, name, cache=None, fetched_utc=None):
    """Parse a plan file and keep it in the cache: raw KML for audit, parsed record for use."""
    record = plan_record(raw, name, fetched_utc or iso(now_epoch()))
    cache = Path(CACHE if cache is None else cache)
    _publish(cache/(record['file']+'.kml'), raw)
    _publish(cache/(record['file']+'.json'), (json.dumps(record, allow_nan=False)+'\n').encode())
    return record


def prune(cache=None, keep=KEEP):
    """Keep the newest ``keep`` plan files per satellite; returns the names removed."""
    cache = Path(CACHE if cache is None else cache)
    infos = [info for info in (plan_name(path.stem) for path in cache.glob('s1?_mp_user_*.json')) if info]
    removed = []
    for satellite in {info['satellite'] for info in infos}:
        old = sorted((i for i in infos if i['satellite'] == satellite), key=lambda i: (i['start'], i['end']))[:-keep]
        for info in old:
            for suffix in ('.json', '.kml'):
                (cache/(info['file']+suffix)).unlink(missing_ok=True)
            removed.append(info['file'])
    return sorted(removed)


def refresh(cache=None, transport=None, now=None):
    """Download the plan files in force now and the newest ones (keyless). Already cached files are not fetched."""
    transport = transport or http_get
    now = now_epoch() if now is None else now
    html = transport(PAGE, PAGE_LIMIT).decode('utf-8', 'replace')
    listed = listed_plans(html)
    if not listed:
        raise ValueError('No Sentinel-1 plan files are listed on the ESA page')
    cache, fetched, kept = Path(CACHE if cache is None else cache), [], []
    for plan in wanted(listed, now):
        if (cache/(plan['file']+'.json')).is_file():
            kept.append(plan['file'])
            continue
        store(transport(DOCUMENTS+plan['file'], KML_LIMIT), plan['file'], cache, iso(now))
        fetched.append(plan['file'])
    return {'fetched': fetched, 'already_cached': kept, 'removed': prune(cache), 'listed': len(listed)}


def import_files(paths, cache=None):
    """Add plan KMLs downloaded by hand (for a machine without access); the file name must be ESA's."""
    records = []
    for path in paths:
        path = Path(path)
        name = path.name[:-4] if path.name.lower().endswith('.kml') else path.name
        raw = path.read_bytes()
        records.append(store(raw, name, cache))
    return records


# Loading and questions.

def _load_record(path):
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get('version') != VERSION or not plan_name(record.get('file')):
        return None
    return record


@lru_cache(maxsize=8)
def _loaded(state):
    """Plan records and the data-takes in force for one set of files (path, kind, mtime, size)."""
    plans = {}
    for path, kind, _, _ in state:
        if kind == 'snapshot':
            try:
                bundle = json.loads(Path(path).read_text(encoding='utf-8'))
            except (OSError, UnicodeError, ValueError):
                continue
            for record in bundle.get('plans', []) if isinstance(bundle, dict) else []:
                if isinstance(record, dict) and record.get('version') == VERSION and plan_name(record.get('file')):
                    plans[record['file']] = {**record, 'from': 'snapshot'}
        else:
            record = _load_record(path)
            if record:  # read after the snapshot, so a cached copy replaces the snapshot's
                plans[record['file']] = {**record, 'from': 'cache'}
    plans = tuple(sorted(plans.values(), key=lambda p: (p['satellite'], p['plan_start_utc'], p['file'])))
    return plans, tuple(governing(plans))


_STATE = {}  # (cache, snapshot) -> (checked at, state): files are looked at again after STAT_S
STAT_S = 5


def _state(cache=None, snapshot=None):
    """Files to read; None means the module's CACHE and SNAPSHOT (read at call time), False means none."""
    cache = CACHE if cache is None else cache
    snapshot = SNAPSHOT if snapshot is None else snapshot
    key, moment = (str(cache), str(snapshot)), monotonic()
    known = _STATE.get(key)
    if known and moment-known[0] < STAT_S:
        return known[1]
    state = _stat(cache, snapshot)
    _STATE[key] = (moment, state)
    return state


def _stat(cache, snapshot):
    paths = [(Path(snapshot), 'snapshot')] if snapshot and Path(snapshot).is_file() else []
    if cache and Path(cache).is_dir():
        paths += [(path, 'cache') for path in sorted(Path(cache).glob('s1?_mp_user_*.json'))]
    state = []
    for path, kind in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        state.append((str(path), kind, stat.st_mtime_ns, stat.st_size))
    return tuple(state)


def load_plans(cache=None, snapshot=None):
    """Cached plan records, plus the bundled snapshot for files not in the cache. Reread only when files change.

    None means the module's CACHE and SNAPSHOT; pass False to leave one out.
    """
    return list(_loaded(_state(cache, snapshot))[0])


def _takes(plans):
    return _loaded(_state())[1] if plans is None else governing(plans)


def governing(plans):
    """Data-takes in force: each moment belongs to the newest plan file of that satellite that covers it."""
    takes = {}
    for plan in plans:
        start, end = epoch(plan['plan_start_utc']), epoch(plan['plan_end_utc'])
        newer = [(epoch(other['plan_start_utc']), epoch(other['plan_end_utc'])) for other in plans
                 if other['satellite'] == plan['satellite']
                 and (other['plan_start_utc'], other['file']) > (plan['plan_start_utc'], plan['file'])]
        for take in plan['datatakes']:
            moment = epoch(take['start_utc'])
            if not start <= moment <= end or any(s <= moment <= e for s, e in newer):
                continue
            takes[(take['satellite'], take['start_utc'], take['mode'])] = {
                **take, 'plan_file': plan['file'], 'start': moment, 'stop': epoch(take['stop_utc'])}
    return sorted(takes.values(), key=lambda take: (take['start_utc'], take['satellite']))


def coverage(plans):
    """Per satellite: the span the loaded plans cover and where they came from."""
    result = {}
    for plan in plans:
        row = result.setdefault(plan['satellite'], {'from_utc': plan['plan_start_utc'], 'to_utc': plan['plan_end_utc'],
                                                    'files': [], 'sources': set()})
        row['from_utc'] = min(row['from_utc'], plan['plan_start_utc'])
        row['to_utc'] = max(row['to_utc'], plan['plan_end_utc'])
        row['files'].append(plan['file'])
        row['sources'].add(plan.get('from', 'cache'))
    for row in result.values():
        row['sources'] = sorted(row['sources'])
    return result


def _public(take):
    return {key: take[key] for key in ('satellite', 'mode', 'polarisation', 'datatake', 'start_utc', 'stop_utc',
                                       'orbit_relative', 'orbit_absolute', 'plan_file') if key in take}


def coast_pass(take):
    """When and where one data-take images the Coast Watch grid; None when it misses the coast."""
    ring = _ring(take)
    cells = _covered_cells(ring)
    if not cells:
        return None
    prepared = _prepared(ring)
    start, stop = epoch(take['start_utc']), epoch(take['stop_utc'])
    times = [start+fraction(prepared, cell[5], cell[6])*(stop-start) for cell in cells]
    counts = Counter(cell[1] for cell in cells)
    return {**_public(take), 'label': LABEL, 'over_coast_from_utc': iso(min(times)),
            'over_coast_to_utc': iso(max(times)), 'cells': len(cells), 'cells_total': len(coastal_cells()[0]),
            'coasts': {coast: counts[coast] for coast in ('North', 'East', 'South', 'West') if counts[coast]},
            'frames_online_utc': iso(max(times)+ONLINE_MIN*60)}


def upcoming(now=None, days=7, plans=None):
    """Planned passes that image the coastal grid from now on (one still over the coast counts), soonest first."""
    now = now_epoch() if now is None else now
    result = []
    for take in _takes(plans):
        if take['stop'] < now or take['start'] > now+days*86400:
            continue
        summary = coast_pass(take)
        if summary and epoch(summary['over_coast_to_utc']) >= now:
            result.append(summary)
    return result


def look_at(take, lat, lon):
    """How one data-take sees a position: time over it, inside or at the edge of the swath; None when it misses."""
    prepared, point = _prepared(_ring(take)), project(lon, lat)
    if prepared is None or point is None:
        return None
    within = inside(prepared['poly'], *point)
    edge = edge_km(prepared['poly'], point)
    if not within and edge >= EDGE_KM:
        return None
    start, stop = epoch(take['start_utc']), epoch(take['stop_utc'])
    return {'time': start+fraction(prepared, lon, lat)*(stop-start),
            'swath': 'inside' if within and edge >= EDGE_KM else 'edge', 'edge_km': round(edge, 1),
            'inside_plan_footprint': within}


def _where(position, moment):
    here = position(moment) if callable(position) else position
    if here is None:
        return None
    lat, lon = (float(value) for value in here)
    return (lat, lon) if math.isfinite(lat) and math.isfinite(lon) else None


def next_look(position, after=None, plans=None, horizon_days=HORIZON_DAYS):
    """First planned data-take that images a position: (lat, lon), or a function of UTC epoch seconds for a
    moving vessel, read at the time the satellite passes. None when no loaded plan covers it."""
    after = now_epoch() if after is None else after
    for take in _takes(plans):
        start, stop = take['start'], take['stop']
        if stop < after or start > after+horizon_days*86400:
            continue
        here = _where(position, (start+stop)/2)
        look = look_at(take, *here) if here else None
        if look and callable(position):  # once more where the vessel is when the satellite passes over it
            here = _where(position, look['time'])
            look = look_at(take, *here) if here else None
        if look is None or look['time'] < after:
            continue
        return {**_public(take), **look, 'label': LABEL, 'time_utc': iso(look['time']), 'lat': round(here[0], 5),
                'lon': round(here[1], 5), 'frames_online_utc': iso(look['time']+ONLINE_MIN*60)}
    return None


def no_look_reason(after, plans=None):
    """Why next_look found nothing: no plan for that time, or no planned look up to the plan's end."""
    spans = coverage(load_plans() if plans is None else plans)
    if not spans:
        return 'no Sentinel-1 plan loaded (python -m argus.s1_plan refresh)'
    first = min(epoch(row['from_utc']) for row in spans.values())
    last = max(epoch(row['to_utc']) for row in spans.values())
    if after > last:
        return 'Sentinel-1 plan ends %s; refresh it' % short(last)
    if after < first:
        return 'no Sentinel-1 plan before %s' % short(first)
    return 'no planned Sentinel-1 look at this position before %s' % short(last)


def replay_look(position, now_s, t0_utc, plans=None):
    """next_look on the exercise replay clock: replay seconds after ``t0_utc`` in, ``t_s`` out."""
    t0 = epoch(t0_utc)
    look = next_look(lambda moment: position(moment-t0), t0+now_s, plans)
    if look is not None:
        look['t_s'] = look['time']-t0
    return look


# Text for people.

def short(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%a %d %b %H:%M UTC')


def clock(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%H:%M')


def duration(seconds):
    minutes = max(0, int(round(seconds/60)))
    if minutes < 60:
        return '%d min' % minutes
    hours, minutes = divmod(minutes, 60)
    return '%d h %02d min' % (hours, minutes) if hours < 48 else '%d d %d h' % divmod(hours, 24)


def satellite_name(code):
    return 'Sentinel-' + code[1:] if code.startswith('S1') else code


def span(item):
    """'18:01-18:02', or one time when the pass crosses the coast within the minute."""
    first, last = clock(epoch(item['over_coast_from_utc'])), clock(epoch(item['over_coast_to_utc']))
    return first if first == last else '%s-%s' % (first, last)


def pass_line(item):
    first = epoch(item['over_coast_from_utc'])
    coasts = ', '.join('%s %d' % (coast, count) for coast, count in item['coasts'].items())
    return '%s %s UTC  %s %s %s  %s cells (%s)  frames ~%s UTC' % (
        datetime.fromtimestamp(first, timezone.utc).strftime('%a %d %b'), span(item), item['satellite'], item['mode'],
        item['polarisation'], item['cells'], coasts, clock(epoch(item['frames_online_utc'])))


def summary(now=None, days=7, plans=None):
    """Lines for the desktop app: the countdown to the next look at the coast, the passes, the plans used."""
    now = now_epoch() if now is None else now
    plans = load_plans() if plans is None else plans
    lines = ['SENTINEL-1 RADAR LOOKS AT THE IRISH COAST · real ESA acquisition plan (planned, not confirmed)']
    if not plans:
        return lines+['No plan loaded. Run: python -m argus.s1_plan refresh']
    passes = upcoming(now, days, plans)
    if passes:
        first = passes[0]
        start = epoch(first['over_coast_from_utc'])
        when = 'now' if start <= now else 'in ' + duration(start-now)
        lines.append('Next Sentinel-1 look at the coast %s: %s %s, over the coast %s UTC (%d of %d coastal cells).'
                     % (when, satellite_name(first['satellite']), first['mode'], span(first), first['cells'],
                        first['cells_total']))
        lines.append('Frames usually online about 1 h after a pass (~%s UTC); 36-85 min measured on 15-16 Oct 2026.'
                     % clock(epoch(first['frames_online_utc'])))
        lines += ['', 'Upcoming passes over the coastal grid, next %d days:' % days]
        lines += ['  ' + pass_line(item) for item in passes]
    else:
        lines.append('No planned look at the coast in the next %d days (%s).' % (days, no_look_reason(now, plans)))
    lines.append('')
    for satellite, row in sorted(coverage(plans).items()):
        lines.append('%s plan %s to %s (%s): %s' % (satellite, short(epoch(row['from_utc'])),
                                                     short(epoch(row['to_utc'])), ', '.join(row['sources']),
                                                     row['files'][-1]))
    lines.append(CAVEAT)
    lines.append('Refresh: python -m argus.s1_plan refresh · source: ' + PAGE)
    return lines


def row_name(look, now):
    """Responder-row name of a planned look, e.g. 'Sentinel-1D pass 18:06 UTC · frames ~19:06'."""
    when = look['time']
    day = '' if datetime.fromtimestamp(when, timezone.utc).date() == datetime.fromtimestamp(now, timezone.utc).date() \
        else datetime.fromtimestamp(when, timezone.utc).strftime('%a ')
    name = '%s pass %s%s UTC · frames ~%s' % (satellite_name(look['satellite']), day, clock(when),
                                             clock(epoch(look['frames_online_utc'])))
    return name + (' · swath edge' if look['swath'] == 'edge' else '')


def window_text(now=None):
    """The block shown above the SAR next-step notes; never raises, never downloads."""
    try:
        return '\n'.join(summary(now))
    except Exception as error:  # the app window must open even with a damaged cache
        return 'Sentinel-1 plan unavailable: %s' % (str(error)[:200] or type(error).__name__)


def snapshot(path=None, cache=None):
    """Write the bundled offline snapshot from the cached plan records."""
    path, cache = Path(SNAPSHOT if path is None else path), Path(CACHE if cache is None else cache)
    plans = [_load_record(p) for p in sorted(cache.glob('s1?_mp_user_*.json'))]
    plans = [plan for plan in plans if plan]
    if not plans:
        raise ValueError('No cached plans; run refresh first')
    bundle = {'version': VERSION, 'label': LABEL, 'source': PAGE, 'caveat': CAVEAT,
              'note': 'Data-takes over Irish waters only; rebuild with python -m argus.s1_plan snapshot',
              'plans': plans}
    _publish(path, (json.dumps(bundle, indent=1, allow_nan=False)+'\n').encode())
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('refresh', help='download the newest ESA plan files (keyless)')
    take = commands.add_parser('import', help='add plan KML files downloaded by hand')
    take.add_argument('files', nargs='+')
    show = commands.add_parser('next', help='print the countdown and the upcoming passes')
    show.add_argument('--at', help='UTC time instead of now, e.g. 2026-10-16T08:00:00Z')
    show.add_argument('--days', type=int, default=7)
    show.add_argument('--lat', type=float)
    show.add_argument('--lon', type=float)
    commands.add_parser('snapshot', help='rebuild the bundled snapshot from the cache')
    args = parser.parse_args(argv)
    if args.command == 'refresh':
        print(json.dumps(refresh(), indent=1))
    elif args.command == 'import':
        for record in import_files(args.files):
            print('%s: %d of %d data-takes over Irish waters' % (record['file'], len(record['datatakes']),
                                                                 record['datatakes_in_file']))
    elif args.command == 'snapshot':
        print('%d plans written to %s' % (len(snapshot()['plans']), SNAPSHOT))
    else:
        moment = epoch(args.at) if args.at else now_epoch()
        print('\n'.join(summary(moment, args.days)))
        if args.lat is not None and args.lon is not None:
            look = next_look((args.lat, args.lon), moment)
            if look:
                print('\nAt %.4f, %.4f: %s %s at %s UTC (in %s, %s of swath), frames ~%s UTC' % (
                    args.lat, args.lon, satellite_name(look['satellite']), look['mode'], look['time_utc'][:16],
                    duration(look['time']-moment), look['swath'], clock(epoch(look['frames_online_utc']))))
            else:
                print('\nAt %.4f, %.4f: %s' % (args.lat, args.lon, no_look_reason(moment)))


if __name__ == '__main__':
    main()
