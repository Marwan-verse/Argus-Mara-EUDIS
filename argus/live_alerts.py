"""Real alerts: the exercise's alert rules applied to live ships near Irish cables (D104).

The team AIS database copies the Railway feed every 30 s. ``LiveTracks.refresh``
reads it through ``public.argus_recent_tracks``. The first call loads the last
three hours of fixes in Irish waters; later calls fetch only what arrived since.
Every ship that has reported in the last 30 min within a few nautical miles of a
route is assessed by the same detectors and levels as the exercise
(``argus.assemble``).

Items are labelled ``real`` and worded for review. A level is a rule outcome on
public AIS and on the illustrative cable routes of ``argus.alert_board.LINES``,
never a finding of intent. Nothing is sent anywhere, and reading is free.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import time

from argus import supabase_ais, watchlist_data
from argus.assemble import assess_vessel
from argus.brain_board import STORY_LINES, _detector_notes, _finding_summary, _with_notes
from argus.detectors.ais_spoofing import nearest_port_nm, on_land
from argus.prediction import distance_to_path_nm

AREA = (-14.5, 49.5, -2.9, 55.5)  # every route in alert_board.LINES, with a margin (west, south, east, north)
TRACK_S = 3*3600   # cable_risk reads three hours; repeated passes (six hours) are only partly seen
KEEP_S = 6*3600
FRESH_S = 30*60    # assess only ships that reported in the last 30 min
NEAR_NM = 6.0      # ... and came within this distance of a route in the last hour
OVERLAP_S = 120    # re-read the last two minutes, so late database inserts are not missed
PORT_NM = 2.5      # harbour work at a listed port is not assessed (team assumption)
MOORED = 5         # AIS navigational status "moored"
REFRESH_S = 300
SOURCE = 'Team AIS database (Railway feed copied every 30 s) · illustrative cable routes'
RECOMMENDATION = ('For review: open the track and AIS history and compare with other sources. '
                  'A rule outcome on public AIS, not evidence of intent; contact only through normal procedures.')
SHIP_TYPES = [(range(20, 30), 'Wing in ground'), (range(30, 31), 'Fishing vessel'), (range(31, 33), 'Tug'),
              (range(33, 34), 'Dredger'), (range(34, 35), 'Diving vessel'), (range(35, 36), 'Military vessel'),
              (range(36, 37), 'Sailing vessel'), (range(37, 38), 'Pleasure craft'), (range(40, 50), 'High-speed craft'),
              (range(50, 51), 'Pilot vessel'), (range(51, 52), 'Search and rescue'), (range(52, 53), 'Tug'),
              (range(53, 54), 'Port tender'), (range(55, 56), 'Law enforcement'), (range(58, 59), 'Medical transport'),
              (range(60, 70), 'Passenger ship'), (range(70, 80), 'Cargo ship'), (range(80, 90), 'Tanker')]


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def type_name(code):
    code = int(code) if isinstance(code, (int, float)) else None
    return next((name for codes, name in SHIP_TYPES if code in codes), 'Vessel')


class LiveTracks:
    """Recent fixes per MMSI, filled incrementally from the team database."""

    def __init__(self, rpc=None):
        self.rpc = rpc or (lambda payload: supabase_ais.rpc('argus_recent_tracks', payload))
        self.fixes, self.static, self.cursor = {}, {}, None

    def refresh(self, now=None):
        now = time.time() if now is None else now
        since = now-TRACK_S if self.cursor is None else max(now-TRACK_S, self.cursor-OVERLAP_S)
        w, s, e, n = AREA
        packet = self.rpc({'p_since': iso(since), 'p_w': w, 'p_s': s, 'p_e': e, 'p_n': n})
        if not isinstance(packet, dict) or not isinstance(packet.get('positions'), list):
            raise ValueError('Unexpected answer from argus_recent_tracks')
        added = 0
        for row in packet['positions']:
            if not isinstance(row, list) or len(row) < 8:
                continue
            mmsi, t, lat, lon, sog, cog, heading, nav = row[:8]
            t, lat, lon = number(t), number(lat), number(lon)
            if not isinstance(mmsi, str) or t is None or lat is None or lon is None:
                continue
            track = self.fixes.setdefault(mmsi, {})
            added += t not in track
            # AIS sends 102.3 kn, 360 deg and 511 deg for "not available".
            sog, cog, heading = number(sog), number(cog), number(heading)
            track[t] = {'t': t, 'lat': lat, 'lon': lon,
                        'sog_kn': sog if sog is not None and 0 <= sog < 102.2 else None,
                        'cog_deg': cog if cog is not None and 0 <= cog < 360 else None,
                        'heading_deg': heading if heading is not None and 0 <= heading < 360 else None,
                        'nav_status': None if nav is None else int(number(nav) or 0)}
            self.cursor = t if self.cursor is None else max(self.cursor, t)
        for mmsi, fields in (packet.get('static') or {}).items():
            if isinstance(fields, dict):
                self.static.setdefault(mmsi, {}).update(fields)
        for mmsi in list(self.fixes):
            kept = {t: fix for t, fix in self.fixes[mmsi].items() if t >= now-KEEP_S}
            if kept:
                self.fixes[mmsi] = kept
            else:
                del self.fixes[mmsi]
        return {'new_fixes': added, 'ships': len(self.fixes), 'truncated': bool(packet.get('truncated'))}

    def vessels(self, now=None):
        """Ships near a route that reported recently, in the shape argus.assemble expects.

        ``self.skipped`` counts ships left out as harbour craft: at a listed port, inside
        a harbour or estuary the 1:50m coastline counts as land, or moored for the last hour.
        """
        now = time.time() if now is None else now
        chosen, self.skipped = [], {'in_port': 0, 'in_harbour': 0, 'moored': 0}
        for mmsi, fixes in self.fixes.items():
            # The detectors were written for complete fixes (the scenario contract), so a fix
            # without speed or course is left out rather than guessed.
            track = [fixes[t] for t in sorted(fixes) if t <= now
                     and fixes[t]['sog_kn'] is not None and fixes[t]['cog_deg'] is not None]
            if not track or track[-1]['t'] < now-FRESH_S or not near_a_route(track, now):
                continue
            reason = harbour(track, now)
            if reason:
                self.skipped[reason] += 1
                continue
            static = self.static.get(mmsi, {})
            ship_type = number(static.get('ship_type'))
            chosen.append({'mmsi': mmsi, 'name': (static.get('name') or '').strip() or mmsi, 'label': 'real',
                           'ship_type': int(ship_type) if ship_type is not None else None,
                           'type': type_name(ship_type), 'ais_length_m': number(static.get('length_m')),
                           'track': track})
        return chosen


def harbour(track, now):
    """Why a ship counts as harbour craft, if it does (team assumptions, see the module docstring)."""
    last = track[-1]
    port = nearest_port_nm(last['lat'], last['lon'])
    if port is not None and port <= PORT_NM:
        return 'in_port'
    if on_land(last['lat'], last['lon']):
        return 'in_harbour'
    hour = [fix for fix in track if fix['t'] >= now-3600]
    if hour and all(fix['nav_status'] == MOORED for fix in hour):
        return 'moored'
    return None


def near_a_route(track, now):
    recent = [fix for fix in track if fix['t'] >= now-3600][-30:]
    return any(distance_to_path_nm(fix['lat'], fix['lon'], line['path'])[0] <= NEAR_NM
               for fix in recent for line in STORY_LINES)


_LOAD = object()


def assess(vessels, now=None, *, watchlist=_LOAD, detectors=None):
    """Rule outcomes for real ships; only levels above None become items."""
    now = time.time() if now is None else now
    context = {'now': now, 'cables': STORY_LINES, 'ports': [], 'anchorages': [], 'detections': [],
               'weather': None, 'assets': [], 'watchlist': watchlist_data.load() if watchlist is _LOAD else watchlist}
    items = []
    for vessel in vessels:
        result = assess_vessel(vessel, context, detectors)
        if result['assessment']['level'] == 'none':
            continue
        items.append(as_item(vessel, result, now))
    return sorted(items, key=lambda item: (-item['assessment']['rank'], -item['raised_t'], item['mmsi']))


def as_item(vessel, result, now):
    fix = vessel['track'][-1]
    line = next((line for line in STORY_LINES if line['id'] == result['cable_id']), None)
    findings = result['findings']
    strongest = max(findings, key=lambda f: (f.get('strength') or 0, len(f.get('reasons') or [])))
    raised = min((f['t'] for f in findings if number(f.get('t')) is not None), default=fix['t'])
    where = f" · {line['name']}" if line else ''
    return {'id': 'REAL-'+vessel['mmsi'], 'label': 'real', 'source': SOURCE, 'name': vessel['name'],
            'mmsi': vessel['mmsi'], 'vessel_type': vessel['type'], 'length_m': vessel['ais_length_m'],
            'lat': fix['lat'], 'lon': fix['lon'], 'sog_kn': fix['sog_kn'], 'cog_deg': fix['cog_deg'],
            'line_id': line['id'] if line else None, 'line_name': line['name'] if line else None,
            'asset_kind': line['kind'] if line else None, 'cable_id': result['cable_id'],
            'title': (strongest.get('reasons') or ['Alert rule cues near a cable route'])[0] + where,
            'assessment': _with_notes(result['assessment'], _detector_notes(findings)),
            'findings': [_finding_summary(f) for f in findings],
            'detectors': sorted({f['detector'] for f in findings}),
            'observations': result['observations'], 'relevance': result['relevance'],
            'recommendation': RECOMMENDATION, 'raised_t': raised,
            'raised_min_ago': max(0, round((now-raised)/60)), 'track': vessel['track'][-90:]}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Print the real alerts the rules give right now (read only).')
    parser.add_argument('--json', action='store_true', help='print the items as JSON')
    args = parser.parse_args(argv)
    tracks = LiveTracks()
    stats = tracks.refresh()
    vessels = tracks.vessels()
    items = assess(vessels)
    if args.json:
        print(json.dumps(items, indent=2, default=str))
        return 0
    print(f"{stats['ships']} ships in the last 3 h, {len(vessels)} near a cable route, {len(items)} real alerts"
          + (' (database answer truncated)' if stats['truncated'] else ''))
    for item in items:
        print(f"  {item['assessment']['level_name']:<8} {item['name'][:22]:<22} {item['mmsi']} "
              f"{(item['line_name'] or '-')[:30]:<30} {item['raised_min_ago']:>3} min · {item['title'][:90]}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
