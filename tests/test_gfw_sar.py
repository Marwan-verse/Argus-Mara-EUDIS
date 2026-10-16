"""Global Fishing Watch radar contacts: token, report parsing, radar timing and the AIS join, all offline."""
from contextlib import redirect_stdout
from datetime import date
import gc
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

from argus import gfw_sar, supabase_ais
from argus.space import timestamp
from argus.satellite_workspace import SatelliteWorkspace
from test_supabase_ais import FakeDatabase

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'eyJhbGciOiJSUzI1NiJ9.' + 'a'*40 + '.synthetic-test-' + 'b'*20  # not a real token
SECRET = 'sb_secret_' + 'x'*24
NO_TOKEN = {'GFW_API_TOKEN': '', 'ARGUS_SUPABASE_KEY': SECRET, 'ARGUS_SUPABASE_KEY_FILE': '', 'ARGUS_SUPABASE_LINK': ''}
START, END = '2026-10-10', '2026-10-12'
SCENE_START, SCENE_END, SCENE_TIME = '2026-10-10T18:05:20Z', '2026-10-10T18:05:46Z', '2026-10-10T18:05:33Z'
EXACT_TIME = '2026-10-10T18:05:41Z'


def report(rows, version='v4.0'):
    """Shape of the documented 4Wings report (docs examples 8 and 9); latest is v4.0 since Feb 2026."""
    return {'total': 1, 'limit': None, 'offset': None, 'nextOffset': None, 'metadata': {},
            'entries': [{'public-global-sar-presence:'+version: rows}]}


UNMATCHED = report([
    {'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.40, 'lon': -5.95},  # no AIS near: lead
    {'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.33, 'lon': -6.12},  # team AIS inside the cell
    {'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.25, 'lon': -5.90},  # team AIS 600 m outside it
    {'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.20, 'lon': -5.20},  # mid Irish Sea, outside the belt
    {'date': '2026-10-11 07:00', 'detections': 1, 'lat': 53.45, 'lon': -5.98},  # no Sentinel-1 scene that hour
])
MATCHED = report([{'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.50, 'lon': -6.00,
                   'vesselId': 'f00-synthetic', 'mmsi': '250000001', 'shipName': 'GFW TEST SHIP', 'flag': 'IRL',
                   'callsign': 'EI0000', 'entryTimestamp': EXACT_TIME, 'exitTimestamp': EXACT_TIME}])


def stac_scene(identifier, start, end, ring):
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    return {'type': 'Feature', 'id': identifier, 'bbox': [min(lons), min(lats), max(lons), max(lats)],
            'geometry': {'type': 'Polygon', 'coordinates': [ring]},
            'properties': {'datetime': start, 'start_datetime': start, 'end_datetime': end,
                           'sat:orbit_state': 'ascending', 'platform': 'sentinel-1c'}}


EAST = [[-7.2, 52.4], [-4.9, 52.4], [-4.9, 54.3], [-7.2, 54.3], [-7.2, 52.4]]
WEST = [[-12.0, 51.8], [-8.1, 51.8], [-8.1, 53.8], [-12.0, 53.8], [-12.0, 51.8]]
CATALOGUE = {'type': 'FeatureCollection', 'links': [{'rel': 'self', 'href': 'https://stac.dataspace.copernicus.eu/v1/search'}],
             'features': [stac_scene('S1C_IW_GRDH_1SDV_SYNTHETIC_EAST', SCENE_START, SCENE_END, EAST),
                          stac_scene('S1C_IW_GRDH_1SDV_SYNTHETIC_WEST', '2026-10-11T06:54:58Z', '2026-10-11T06:55:23Z', WEST)]}


def catalogue(url):
    if not url.startswith('https://stac.dataspace.copernicus.eu/v1/search?'):
        raise AssertionError(url)
    return CATALOGUE


class FakeGFW:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, body, token):
        self.calls.append((url, body, token))
        return self.answers.pop(0)


def iso(seconds):
    return gfw_sar.iso(seconds).replace('Z', '.000Z')


def ais_rows():
    """What public.argus_ais_rows returns around the radar time (synthetic positions)."""
    def fix(mmsi, lat, lon, at, sog=8):
        return {'mmsi': mmsi, 'msg_type': 'PositionReport', 'lat': lat, 'lon': lon, 'sog': sog, 'cog': 90,
                'nav_status': 0, 'recv_utc': at, 'time_utc': '', 'timestamp_source': 'received_time_assumption',
                'stream_id': 'synthetic', 'label': 'real'}
    rows = [fix('234000001', 53.3302, -6.1215, '2026-10-10T18:05:00.000Z'),
            fix('234000001', 53.3302, -6.1185, '2026-10-10T18:06:00.000Z'),
            fix('234000002', 53.2604, -5.9000, '2026-10-10T18:05:20.000Z', sog=0),
            fix('234000002', 53.2604, -5.9000, '2026-10-10T18:05:50.000Z', sog=0),
            {'mmsi': '234000001', 'msg_type': 'ShipStaticData', 'recv_utc': '2026-10-10T17:00:00.000Z',
             'stream_id': 'synthetic', 'label': 'real', 'present_fields': 'name', 'ship_name': 'TEST AIS SHIP'}]
    # A lane about 12 km away keeps reception visibly live around the radar time.
    centre = timestamp(SCENE_TIME)
    rows += [fix('234000009', 53.62, -6.0+second*1e-5, iso(centre-600+second), sog=1) for second in range(0, 1200, 30)]
    return {'rows': rows}


def database_lookup(fake):
    def lookup(when, area):
        return supabase_ais.historical_ais_from_database(when, area, transport=fake)
    return lookup


def fetched(root, database=None):
    database = database or FakeDatabase(ais_rows())
    gfw = FakeGFW(UNMATCHED, MATCHED)
    with patch.dict(os.environ, NO_TOKEN):
        result, path = gfw_sar.fetch(root, START, END, token=TOKEN, transport=gfw, catalogue=catalogue,
                                     ais_lookup=database_lookup(database))
    return result, path, gfw, database


def by_cell(result):
    return {(d['lat'], d['lon']): d for d in result['detections']}


class TokenTests(unittest.TestCase):
    def test_environment_first_then_credential_store_and_never_echoed(self):
        with patch.dict(os.environ, {'GFW_API_TOKEN': TOKEN}):
            self.assertEqual(gfw_sar.get_token(), TOKEN)
            self.assertEqual(gfw_sar.token_source(), 'environment (GFW_API_TOKEN)')
        with patch.dict(os.environ, {'GFW_API_TOKEN': ''}), patch('argus.gfw_sar._keyring_token', return_value=TOKEN):
            self.assertTrue(gfw_sar.configured())
            self.assertEqual(gfw_sar.token_source(), 'credential store (ArgusMara.GFW)')
        with patch.dict(os.environ, {'GFW_API_TOKEN': ''}), patch('argus.gfw_sar._keyring_token', return_value=''):
            self.assertFalse(gfw_sar.configured())
            with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, 'not connected'):
                gfw_sar.fetch(temp, START, END, transport=FakeGFW())
        bad = 'line\nbreak ' + 'x'*30
        with patch.dict(os.environ, {'GFW_API_TOKEN': bad}), self.assertRaises(ValueError) as caught:
            gfw_sar.get_token()
        self.assertNotIn('xxxx', str(caught.exception))
        self.assertFalse(gfw_sar.valid_token('short'))

    def test_transport_is_https_gfw_only_and_hides_bodies_and_token(self):
        url, body = gfw_sar.report_request(START, END, gfw_sar.coastal_bbox(), False)
        with patch('argus.gfw_sar.build_opener', side_effect=AssertionError('no network')):
            for bad in ('http://gateway.api.globalfishingwatch.org/v3/4wings/report', 'https://example.com/v3/4wings/report'):
                with self.assertRaisesRegex(ValueError, 'Only the Global Fishing Watch API'):
                    gfw_sar.report_http(bad, body, TOKEN)

        class Opener:
            def __init__(self, error=None, content=b''):
                self.error, self.content, self.requests = error, content, []

            def open(self, request, timeout):
                self.requests.append((request, timeout))
                if self.error:
                    raise self.error
                return Response(self.content)

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False
        refused = HTTPError(url, 401, 'Unauthorized', {}, BytesIO(b'{"detail": "' + TOKEN.encode() + b'"}'))
        with patch('argus.gfw_sar.build_opener', return_value=Opener(refused)):
            with self.assertRaisesRegex(ValueError, 'HTTP 401') as caught:
                gfw_sar.report_http(url, body, TOKEN)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn('detail', str(caught.exception))
        for code, text in [(429, 'one report at a time'), (524, 'fewer days'), (503, 'no automatic retry')]:
            with patch('argus.gfw_sar.build_opener', return_value=Opener(HTTPError(url, code, 'x', {}, None))):
                with self.assertRaisesRegex(ValueError, text):
                    gfw_sar.report_http(url, body, TOKEN)
        opener = Opener(content=json.dumps(UNMATCHED).encode())
        with patch('argus.gfw_sar.build_opener', return_value=opener):
            self.assertEqual(gfw_sar.report_http(url, body, TOKEN), UNMATCHED)
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertEqual(json.loads(request.data), body)
        self.assertGreater(timeout, 100)  # GFW itself gives up after 100 s with HTTP 524

    def test_zip_reports_are_read_with_a_bound(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('caveats.txt', 'Provider caveats')
            archive.writestr('report.json', json.dumps(UNMATCHED))
        self.assertEqual(gfw_sar.decode_report(buffer.getvalue()), UNMATCHED)
        empty = BytesIO()
        with zipfile.ZipFile(empty, 'w') as archive:
            archive.writestr('caveats.txt', 'no report')
        for raw in (empty.getvalue(), b'<html>gateway error</html>'):
            with self.assertRaisesRegex(ValueError, 'Cannot read'):
                gfw_sar.decode_report(raw)


class RequestTests(unittest.TestCase):
    def test_window_is_calendar_days_with_end_excluded(self):
        self.assertEqual(gfw_sar.window(days=14, today=date(2026, 10, 16)), ('2026-10-02', '2026-10-16'))
        self.assertEqual(gfw_sar.window('2026-10-02', '2026-10-16'), ('2026-10-02', '2026-10-16'))
        for start, end in [('2026-10-16', '2026-10-16'), ('2026-09-01', '2026-10-16'), ('2016-12-30', '2017-01-02')]:
            with self.assertRaises(ValueError):
                gfw_sar.window(start, end)

    def test_report_asks_for_documented_sar_cells_hours_and_match_state(self):
        area = gfw_sar.coastal_bbox()
        url, body = gfw_sar.report_request(START, END, area, False)
        self.assertTrue(url.startswith('https://gateway.api.globalfishingwatch.org/v3/4wings/report?'))
        for part in ('spatial-resolution=HIGH', 'temporal-resolution=HOURLY', 'format=JSON',
                     'datasets%5B0%5D=public-global-sar-presence%3Alatest', 'date-range=2026-10-10%2C2026-10-12',
                     'filters%5B0%5D=matched%3D%27false%27'):
            self.assertIn(part, url)
        self.assertNotIn('group-by', url)
        ring = body['geojson']['coordinates'][0]
        self.assertEqual((body['geojson']['type'], ring[0], ring[-1]), ('Polygon', ring[-1], [area[0], area[1]]))
        matched, _ = gfw_sar.report_request(START, END, area, True)
        self.assertIn('group-by=VESSEL_ID', matched)
        self.assertIn('matched%3D%27true%27', matched)
        self.assertEqual(area, [-11.183323, 51.024075, -4.810031, 55.767158])

    def test_parse_keeps_real_rows_hours_identity_and_exact_times(self):
        area = gfw_sar.coastal_bbox()
        rows, datasets = gfw_sar.parse_report(UNMATCHED, False, area)
        self.assertEqual(datasets, {'public-global-sar-presence:v4.0'})
        self.assertEqual(len(rows), 5)
        first = rows[0]
        self.assertEqual((first['hour_utc'], first['label'], first['review_status'], first['gfw_matched']),
                         ('2026-10-10T18:00:00Z', 'real', 'unreviewed', False))
        self.assertIsNone(first['gfw_time_utc'])
        self.assertEqual(gfw_sar.parse_report(UNMATCHED, False, area)[0][0]['id'], first['id'])  # stable id
        matched, _ = gfw_sar.parse_report(MATCHED, True, area)
        self.assertEqual(matched[0]['gfw_vessel'], {'vessel_id': 'f00-synthetic', 'mmsi': '250000001',
                         'name': 'GFW TEST SHIP', 'flag': 'IRL', 'call_sign': 'EI0000'})
        self.assertEqual(matched[0]['gfw_time_utc'], EXACT_TIME)
        noisy = report([{'date': '2026-10-10 18:00', 'detections': 2, 'lat': 53.5, 'lon': -6.0,
                         'entryTimestamp': '2026-10-10T18:05:41Z', 'exitTimestamp': '2026-10-10T18:20:00Z'},
                        {'date': '2026-10-10 18:00', 'detections': 1, 'lat': 60.0, 'lon': -6.0},
                        {'date': '2026-10-10 18:00', 'detections': 'many', 'lat': 53.0, 'lon': -6.0},
                        'not a row'], version='v3.0')
        rows, _ = gfw_sar.parse_report({**noisy, 'entries': noisy['entries'] + [{'public-global-presence:v4.0': [{}]}]}, True, area)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['gfw_time_utc'])  # two instants: only the hourly bin is known
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            gfw_sar.parse_report({'error': 'Unauthorized'}, False, area)
        with patch('argus.gfw_sar.MAX_ROWS', 2), self.assertRaisesRegex(ValueError, 'fewer days'):
            gfw_sar.parse_report(UNMATCHED, False, area)


class RadarTimeTests(unittest.TestCase):
    def test_cells_take_the_sentinel1_scene_time_or_stay_unresolved(self):
        scenes = gfw_sar.sentinel1_scenes(START, END, gfw_sar.coastal_bbox(), catalogue)
        self.assertEqual([s['id'] for s in scenes], ['S1C_IW_GRDH_1SDV_SYNTHETIC_EAST', 'S1C_IW_GRDH_1SDV_SYNTHETIC_WEST'])
        rows, _ = gfw_sar.parse_report(UNMATCHED, False, gfw_sar.coastal_bbox())
        timed = gfw_sar.acquisition_time(rows[0], scenes)
        self.assertEqual(timed, {'time_utc': SCENE_TIME, 'time_source': 'sentinel1_scene_midpoint',
                                 'time_uncertainty_s': 13.0, 'scene_ids': ['S1C_IW_GRDH_1SDV_SYNTHETIC_EAST']})
        self.assertEqual(gfw_sar.acquisition_time(rows[-1], scenes)['time_source'], 'hour_bin_only')
        matched, _ = gfw_sar.parse_report(MATCHED, True, gfw_sar.coastal_bbox())
        exact = gfw_sar.acquisition_time(matched[0], scenes)
        self.assertEqual((exact['time_utc'], exact['time_uncertainty_s']), (EXACT_TIME, 0))
        later = dict(scenes[0], id='S1D_LATER_PASS', start=scenes[0]['start']+1800, end=scenes[0]['end']+1800)
        self.assertEqual(gfw_sar.acquisition_time(rows[0], scenes+[later])['time_source'], 'several_passes_in_hour')
        next_slice = dict(scenes[0], id='S1C_NEXT_SLICE', start=scenes[0]['start']+25, end=scenes[0]['end']+25)
        overlap = gfw_sar.acquisition_time(rows[0], [scenes[0], next_slice])
        self.assertEqual((overlap['time_uncertainty_s'], len(overlap['scene_ids'])), (25.5, 2))


class JoinTests(unittest.TestCase):
    def test_fetch_compares_each_radar_cell_with_database_ais_at_radar_time(self):
        with tempfile.TemporaryDirectory() as temp:
            result, path, gfw, database = fetched(temp)
            self.assertEqual(path.name, 'gfw-2026-10-10_2026-10-12.json')
            self.assertEqual(json.loads(path.read_text())['counts'], result['counts'])
        self.assertEqual([call[2] for call in gfw.calls], [TOKEN, TOKEN])
        self.assertIn('matched%3D%27false%27', gfw.calls[0][0])
        self.assertIn('matched%3D%27true%27', gfw.calls[1][0])
        self.assertNotIn(TOKEN, json.dumps(result))
        rpc_times = sorted({payload['p_t'] for url, payload, key in database.calls})
        self.assertTrue(all(url.endswith('/rest/v1/rpc/argus_ais_rows') for url, _payload, _key in database.calls))
        self.assertEqual(rpc_times, [SCENE_TIME, EXACT_TIME])
        cells = by_cell(result)
        self.assertNotIn((53.2, -5.2), cells)
        self.assertEqual(result['counts']['outside_coastal_belt'], 1)
        dark, matched_ais, nearby = cells[(53.4, -5.95)], cells[(53.33, -6.12)], cells[(53.25, -5.9)]
        self.assertEqual((dark['status'], dark['time_utc'], dark['team_ais']['reception_live']),
                         ('no_team_ais', SCENE_TIME, True))
        self.assertTrue(gfw_sar.is_lead(dark))
        self.assertEqual((matched_ais['status'], matched_ais['matched_mmsis']), ('team_ais_match', ['234000001']))
        self.assertEqual(matched_ais['candidates'][0]['name'], 'TEST AIS SHIP')
        self.assertEqual(matched_ais['candidates'][0]['distance_m'], 0)
        self.assertEqual(nearby['status'], 'nearby_ais_review')
        self.assertAlmostEqual(nearby['candidates'][0]['distance_m'], 600, delta=15)
        self.assertEqual(cells[(53.45, -5.98)]['status'], 'time_unresolved')
        gfw_ship = cells[(53.5, -6.0)]
        self.assertEqual((gfw_ship['status'], gfw_ship['gfw_matched'], gfw_sar.is_lead(gfw_ship)), ('no_team_ais', True, False))
        self.assertEqual(result['counts']['leads'], 1)
        self.assertEqual(result['newest_detection_utc'], '2026-10-11T07:00:00Z')
        self.assertEqual(result['attribution'], 'Powered by Global Fishing Watch')
        self.assertEqual(result['label'], 'real')

    def test_without_live_reception_nothing_becomes_a_dark_lead(self):
        rows = [row for row in ais_rows()['rows'] if row['mmsi'] != '234000009']
        with tempfile.TemporaryDirectory() as temp:
            result, *_ = fetched(temp, FakeDatabase({'rows': rows}))
        cells = by_cell(result)
        self.assertEqual(cells[(53.4, -5.95)]['status'], 'no_contemporaneous_ais')
        self.assertEqual(cells[(53.33, -6.12)]['status'], 'team_ais_match')  # a positive match still counts
        self.assertEqual(result['counts']['leads'], 0)

    def test_gfw_identity_binds_first_and_contests_or_fast_ais_block_leads(self):
        def vessel(mmsi, lat, lon, fast=False):
            return {'mmsi': mmsi, 'name': mmsi, 'position': {'lat': lat, 'lon': lon},
                    'track': [{'ts': SCENE_TIME, 'lat': lat, 'lon': lon}], 'broadcast_fields': {},
                    'position_evidence': {'position_method': 'observed_fix',
                                          'kinematic_consistency': 'exceeds_assumed_limit' if fast else 'within_assumed_limit'}}
        cell = {'lat': 53.5, 'lon': -6.0, 'cell_deg': .01, 'detections': 1, 'time_utc': SCENE_TIME}
        group = [dict(cell, id='gfw-unmatched', gfw_matched=False),
                 dict(cell, id='gfw-matched', gfw_matched=True, gfw_vessel={'mmsi': '250000001'})]
        live = {'nearby_fixes': 50, 'status': 'partial'}
        gfw_sar.associate_cells(group, {'vessels': [vessel('250000001', 53.5001, -6.0001)], 'coverage': live})
        # The AIS ship belongs to GFW's matched contact; the other radar target stays unexplained.
        self.assertEqual((group[1]['status'], group[1]['same_identity_as_gfw']), ('team_ais_match', True))
        self.assertEqual(group[0]['status'], 'no_team_ais')
        fast = [dict(cell, id='gfw-fast', gfw_matched=False)]
        gfw_sar.associate_cells(fast, {'vessels': [vessel('234000003', 53.5, -6.0, fast=True)], 'coverage': live})
        self.assertEqual(fast[0]['status'], 'nearby_ais_review')
        self.assertFalse(fast[0]['candidates'][0]['motion_consistent'])
        pair = [dict(cell, id='gfw-a', gfw_matched=False), dict(cell, id='gfw-b', gfw_matched=False, lon=-5.999)]
        gfw_sar.associate_cells(pair, {'vessels': [vessel('234000004', 53.5, -5.9995)], 'coverage': live})
        self.assertEqual(sorted(d['status'] for d in pair), ['nearby_ais_review', 'team_ais_match'])

    def test_failed_ais_lookup_is_reported_not_turned_into_leads(self):
        rows, _ = gfw_sar.parse_report(UNMATCHED, False, gfw_sar.coastal_bbox())
        for d in rows:
            d.update(gfw_sar.acquisition_time(d, gfw_sar.sentinel1_scenes(START, END, gfw_sar.coastal_bbox(), catalogue)))
        def broken(when, area):
            raise ValueError('Cannot reach the Supabase database')
        gfw_sar.join_ais(rows, broken)
        self.assertEqual({d['status'] for d in rows}, {'ais_unavailable', 'time_unresolved'})
        self.assertFalse(any(gfw_sar.is_lead(d) for d in rows))


class WorkspaceTests(unittest.TestCase):
    def test_linked_workspace_reuses_coast_watch_ais_source(self):
        real = supabase_ais.historical_ais_from_database
        fake = FakeDatabase(ais_rows())
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, NO_TOKEN), \
                patch('argus.supabase_ais.historical_ais_from_database',
                      side_effect=lambda when, area: real(when, area, transport=fake)) as remote:
            supabase_ais.link(temp)
            ais = gfw_sar.workspace_lookup(temp)(SCENE_TIME, [-6.2, 53.3, -6.0, 53.4])
        self.assertEqual(remote.call_args.args[0], SCENE_TIME)
        self.assertEqual((ais['source'], [v['mmsi'] for v in ais['vessels']]), ('supabase', ['234000001']))

    def test_radar_passes_before_the_database_history_use_an_imported_archive(self):
        real = supabase_ais.historical_ais_from_database
        sparse = FakeDatabase({'rows': ais_rows()['rows'][:2]})  # stale "last fix" rows only
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(os.environ, {**NO_TOKEN, 'ARGUS_SATELLITE_AIS_DIR': str(Path(temp)/'ais')}), \
                patch('argus.supabase_ais.historical_ais_from_database',
                      side_effect=lambda when, area: real(when, area, transport=sparse)):
            root = Path(temp)/'satellite'
            supabase_ais.link(root)
            lookup = gfw_sar.workspace_lookup(root)
            self.assertEqual(lookup(SCENE_TIME, [-6.2, 53.3, -6.0, 53.4])['source'], 'supabase')  # nothing better
            (Path(temp)/'ais').mkdir()
            supabase_ais.write_rows_csv(ais_rows()['rows'], Path(temp)/'ais'/'railway-archive.csv')
            ais = lookup(SCENE_TIME, [-6.2, 53.3, -6.0, 53.4])
        self.assertIn('local archive used', ais['coverage']['database_note'])
        self.assertGreaterEqual(ais['coverage']['nearby_fixes'], gfw_sar.MIN_LIVE_FIXES)
        self.assertEqual([v['mmsi'] for v in ais['vessels']], ['234000001'])

    def test_radar_leads_join_incidents_with_analyst_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'satellite'
            fetched(root)
            workspace = SatelliteWorkspace(root)
            index = workspace.comparison_index()
            self.assertEqual((index['radar_detections'], index['radar_leads']), (5, 1))
            lead = next(r for r in index['leads'] if r.get('radar'))
            self.assertEqual((lead['title'], lead['label'], lead['review_status'], lead['acquired_utc']),
                             ('Radar contact without AIS', 'real', 'unreviewed', SCENE_TIME))
            self.assertRegex(lead['id'], r'^gfw:[0-9a-f]{20}$')
            payload = {'event_id': '00000000-0000-4000-8000-000000000001', 'lead_id': lead['id'],
                       'evidence_key': lead['evidence_key'], 'outcome': 'reviewed_no_concern',
                       'reason': 'Synthetic test: research vessel known to the analyst.'}
            saved = workspace.save_disposition(payload, 'Local analyst')
            self.assertEqual(saved['event']['lead_snapshot']['detection_id'], lead['detection_id'])
            reviewed = next(r for r in saved['comparisons']['leads'] if r['id'] == lead['id'])
            self.assertEqual(reviewed['review_status'], 'reviewed_no_concern')
            with self.assertRaisesRegex(ValueError, 'Invalid radar'):
                workspace.save_disposition({**payload, 'lead_id': 'gfw:not-hex'}, 'Local analyst')
            # More AIS evidence at the same radar time reopens the analyst outcome.
            busier = ais_rows()
            lane = busier['rows'][-1]
            busier['rows'] += [dict(lane, recv_utc=iso(timestamp(SCENE_TIME)-585+30*i), lon=-5.99+i*1e-5) for i in range(5)]
            gfw_sar.rejoin(root, database_lookup(FakeDatabase(busier)))
            reopened = next(r for r in workspace.comparison_index()['leads'] if r['id'] == lead['id'])
            self.assertEqual((reopened['review_status'], reopened['evidence_changed']), ('unreviewed', True))
            # An AIS ship inside the radar cell at that time removes the lead.
            busier['rows'].append(dict(lane, mmsi='234000010', recv_utc='2026-10-10T18:05:33.000Z', lat=53.4, lon=-5.951))
            gfw_sar.rejoin(root, database_lookup(FakeDatabase(busier)))
            self.assertEqual(workspace.comparison_index()['radar_leads'], 0)
            self.assertEqual(gfw_sar.summary(root)['statuses']['team_ais_match'], 2)

    def test_newest_fetch_wins_and_files_never_hold_the_token(self):
        with tempfile.TemporaryDirectory() as temp:
            first, *_ = fetched(temp)
            second_rows = report([{'date': '2026-10-10 18:00', 'detections': 1, 'lat': 53.40, 'lon': -5.95}])
            with patch.dict(os.environ, NO_TOKEN):
                gfw_sar.fetch(temp, '2026-10-10', '2026-10-11', token=TOKEN, transport=FakeGFW(second_rows, report([])),
                              catalogue=catalogue, ais_lookup=database_lookup(FakeDatabase(ais_rows())))
            self.assertEqual(len(list((Path(temp)/'radar').glob('gfw-*.json'))), 2)
            self.assertEqual(len(gfw_sar.detections(temp)), len(first['detections']))
            for path in (Path(temp)/'radar').glob('*.json'):
                self.assertNotIn(TOKEN, path.read_text())


class CommandTests(unittest.TestCase):
    def run_main(self, *arguments):
        output = StringIO()
        with patch.object(sys, 'argv', ['gfw_sar', *arguments]), redirect_stdout(output):
            gfw_sar.main()
        return output.getvalue()

    def test_status_and_leads_never_print_the_token(self):
        with tempfile.TemporaryDirectory() as temp:
            fetched(temp)
            with patch.dict(os.environ, {'GFW_API_TOKEN': TOKEN}):
                status = json.loads(self.run_main('--root', temp, 'status'))
                leads = json.loads(self.run_main('--root', temp, 'leads'))
            self.assertEqual((status['configured'], status['token_source'], status['leads']),
                             (True, 'environment (GFW_API_TOKEN)', 1))
            self.assertNotIn(TOKEN, json.dumps(status) + json.dumps(leads))
            self.assertEqual(len(leads), 1)

    def test_configure_script_checks_then_saves_without_printing(self):
        spec = spec_from_file_location('configure_gfw_under_test', ROOT/'scripts/configure_gfw.py')
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        output = StringIO()
        with patch.object(module, 'getpass', return_value=TOKEN), patch.object(sys, 'argv', ['configure_gfw.py']), \
                patch('argus.gfw_sar.check_token', return_value={'datasets': ['public-global-sar-presence:v4.0'],
                                                                'test_day': '2026-10-08', 'radar_rows': 3}) as check, \
                patch('argus.gfw_sar.save_token') as save, redirect_stdout(output):
            self.assertEqual(module.main(), 0)
        check.assert_called_once_with(TOKEN)
        save.assert_called_once_with(TOKEN)
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertIn('Powered by Global Fishing Watch', output.getvalue())
        with patch.object(module, 'getpass', return_value='not a token'), patch.object(sys, 'argv', ['configure_gfw.py']), \
                patch('argus.gfw_sar.save_token') as save, patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                module.main()
        save.assert_not_called()

    def test_check_token_uses_one_small_recent_report(self):
        gfw = FakeGFW(report([]))
        result = gfw_sar.check_token(TOKEN, transport=gfw, today=date(2026, 10, 16))
        self.assertEqual(result, {'datasets': ['public-global-sar-presence:v4.0'], 'test_day': '2026-10-08', 'radar_rows': 0})
        self.assertIn('date-range=2026-10-08%2C2026-10-09', gfw.calls[0][0])


class RadarDesktopTests(unittest.TestCase):
    def setUp(self):
        gc.collect()

    def test_radar_markers_details_and_incident_review(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        from desktop_evidence_review import EvidenceReview
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.attributes('-alpha', 0)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': '',
                                          'ARGUS_SATELLITE_AUTOSTART': '0', 'GFW_API_TOKEN': ''}), \
                patch('argus.satellite_workspace.get_key', return_value=''), \
                patch('argus.gfw_sar._keyring_token', return_value=''):
            workspace_root = Path(temp)/'satellite'
            result, *_ = fetched(workspace_root)
            app = ArgusApp(root, *load_demo())
            satellite, board = app.satellite, app.alert_board
            try:
                satellite.watch_at = float('inf')  # this test drives the watch packet itself
                deadline = time.monotonic()+5
                while satellite.watch_future is not None and time.monotonic() < deadline:
                    root.update()
                satellite.workspace = SatelliteWorkspace(workspace_root)
                app.open_window('satellite')
                satellite.apply_radar({**gfw_sar.map_index(workspace_root), 'configured': True})
                self.assertIn('1 without AIS (leads)', satellite.radar_status.get())
                lead = next(d for d in result['detections'] if gfw_sar.is_lead(d))
                satellite.show_radar_point({'id': lead['id']})
                root.update()
                self.assertTrue(app.map.find_withtag('radar-contact-'+lead['id']))
                details = satellite.details.get('1.0', 'end')
                self.assertIn('RADAR CONTACT WITHOUT AIS', details)
                self.assertIn('Team AIS at radar time', details)
                self.assertIn('Powered by Global Fishing Watch', details)
                self.assertIn('Powered by Global Fishing Watch', app.map_attribution_label.cget('text'))
                satellite.show_radar.set(False)
                satellite.redraw()
                self.assertFalse(app.map.find_withtag('radar-contact-'+lead['id']))
                satellite.show_radar.set(True)
                board.refresh_evidence(satellite.workspace.comparison_index())
                buttons = [w for w in board.evidence_frame.winfo_children() if isinstance(w, tk.Button)]
                card = next(w for w in buttons if 'Radar contact without AIS' in w.cget('text'))
                self.assertIn('Show radar contact on map', card.cget('text'))
                self.assertIn('radar detections (Global Fishing Watch)', board.evidence_status)
                satellite.selected_radar = None
                card.invoke()
                root.update()
                self.assertEqual(satellite.selected_radar, lead['id'])
                form = EvidenceReview(board, next(r for r in board.evidence_leads if r.get('radar')))
                form.outcome.set('Insufficient evidence')
                form.reason.insert('1.0', 'Synthetic test analyst outcome for a radar contact.')
                form.save()
                deadline = time.monotonic()+5
                while form.window.winfo_exists() and time.monotonic() < deadline:
                    root.update()
                self.assertFalse(form.window.winfo_exists())
                radar_lead = next(r for r in board.evidence_leads if r.get('radar'))
                self.assertEqual(radar_lead['review_status'], 'insufficient_evidence')
                root.update()
                self.assertEqual(errors, [])
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
