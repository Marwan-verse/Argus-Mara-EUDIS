"""Automatic coverage, paid-call isolation and acquisition-time ship custody."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
from importlib.util import find_spec
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from argus.satellite import atomic_json, replace_file, search
from argus.satellite_ais import associate, attach_latest, historical_ais
from argus.satellite_capture import AISCapture, load_latest
from argus.satellite_ai import exclusive
from argus.satellite_scan import COASTS, CoastalScan, coast_for_bounds, coast_progress, grid, read_state, scan_status
from argus.satellite_screen import retain_water_contacts, screen
from argus.space import timestamp
from test_live_client import snapshot, vessel
from test_satellite import AREA, WHEN, fixture

RASTERS_AVAILABLE = all(find_spec(name) is not None for name in ('numpy', 'rasterio'))


def image_fixture(folder, *, clouds=False, feature=True):
    workspace, scene, _ = fixture(folder)
    scene['label'] = 'real'
    image = Image.new('RGB', (64, 64), (15, 25, 35))
    if feature:
        ImageDraw.Draw(image).rectangle((30, 30, 32, 33), fill=(220, 220, 220))
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    raw = buffer.getvalue()
    quality = BytesIO()
    Image.new('L', (64, 64), 9 if clouds else 6).save(quality, format='PNG')
    scene.update(image_sha256=hashlib.sha256(raw).hexdigest(), quality_sha256=hashlib.sha256(quality.getvalue()).hexdigest())
    (workspace.scenes/(scene['id']+'.png')).write_bytes(raw)
    (workspace.scenes/(scene['id']+'.quality.png')).write_bytes(quality.getvalue())
    atomic_json(workspace.scenes/(scene['id']+'.json'), scene)
    return workspace, scene, raw


class CoastalScanTests(unittest.TestCase):
    def regional_engine(self, root, sides=COASTS):
        workspace, _, _ = fixture(root)
        engine = CoastalScan(workspace)
        locations = {'North': (-7.5, 55.2), 'East': (-6.1, 53.3), 'South': (-8.5, 51.6), 'West': (-10.1, 53.7)}
        tiles = []
        for side in sides:
            lon, lat = locations[side]
            for index in range(2):
                area = [lon-.03, lat-.03, lon+.03, lat+.03]
                key = side+str(index)
                self.assertEqual(coast_for_bounds(area), side)
                tiles.append({'id': key, 'bbox': area})
                engine.state['jobs'][key] = {'tile': key, 'bbox': area, 'status': 'queued',
                     'product': {'acquired_utc': WHEN, 'cloud_percent': 0 if side == 'East' else 100,
                                 'quality_asset': 'synthetic', 'id': key}}
        engine.layout = {'tiles': tiles, 'scope': 'Synthetic regional scheduling test'}
        return engine

    def test_each_coast_gets_a_turn_even_when_only_the_east_is_clear(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = self.regional_engine(Path(temp)/'satellite')
            checked = []
            def preview(source, area):
                checked.append(coast_for_bounds(area))
                return {'load_rgb': False}
            with patch('argus.satellite_scan.quality_preview', side_effect=preview):
                self.assertTrue(engine.process_one())
                # The cursor survives restart, and old unvisited regions remain queued.
                restarted = CoastalScan(engine.workspace)
                restarted.layout = engine.layout
                for _ in range(7):
                    self.assertTrue(restarted.process_one())
            self.assertEqual(checked, list(COASTS)*2)
            progress = scan_status(engine.workspace.root)['coasts']
            self.assertTrue(all(progress[side]['covered_tiles'] == 2 for side in COASTS))
            self.assertFalse((engine.workspace.root/'ai/budget.json').exists())

    def test_empty_sides_are_skipped_and_a_failed_side_cannot_block_others(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = self.regional_engine(Path(temp)/'satellite', ('East', 'West'))
            checked = []
            def preview(source, area):
                side = coast_for_bounds(area)
                checked.append(side)
                if len(checked) == 1:
                    raise ValueError('Synthetic missing raster')
                return {'load_rgb': False}
            with patch('argus.satellite_scan.quality_preview', side_effect=preview):
                for _ in range(4):
                    self.assertTrue(engine.process_one())
                self.assertFalse(engine.process_one())
            self.assertEqual(checked, ['East', 'West', 'East', 'West'])
            self.assertEqual(coast_progress(engine.layout, engine.state)['East']['held'], 1)

    def test_windows_reader_lock_retries_only_the_local_atomic_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'status.json'
            error = PermissionError('Synthetic Windows reader lock')
            error.winerror = 32
            calls = []
            def transient(source, target):
                calls.append(True)
                if len(calls) == 1:
                    raise error
                replace_file(source, target)
            with patch('argus.satellite.replace_file', side_effect=transient), patch('time.sleep'):
                atomic_json(path, {'complete': True})
            self.assertEqual(json.loads(path.read_text()), {'complete': True})
            self.assertEqual(len(calls), 2)
            with patch('argus.satellite.replace_file', side_effect=error) as failing, patch('time.sleep'):
                with self.assertRaises(PermissionError):
                    atomic_json(path, {'complete': False})
            self.assertEqual(failing.call_count, 8)
            self.assertEqual(json.loads(path.read_text()), {'complete': True})

    def test_grid_covers_four_coasts_and_northern_ireland_without_land_border(self):
        layout = grid()
        self.assertGreater(layout['removed_shared_border_edges'], 100)
        self.assertGreater(len(layout['tiles']), 500)
        for lon, lat in [(-6.1, 53.3), (-9.9, 53.9), (-8.3, 51.7), (-6.5, 55.2)]:
            self.assertTrue(any(w <= lon <= e and s <= lat <= n for w, s, e, n in (t['bbox'] for t in layout['tiles'])))
        # Inland border at Clones is not interpreted as an Irish shoreline.
        self.assertFalse(any(w <= -7.23 <= e and s <= 54.18 <= n for w, s, e, n in (t['bbox'] for t in layout['tiles'])))

    def test_catalogue_pagination_is_complete_or_explicitly_fails_closed(self):
        pages = []
        def provider(url):
            pages.append(url)
            return {'features': [{'id': 'page'+str(len(pages)), 'properties': {'datetime': WHEN}}],
                    'links': [{'rel': 'next', 'href': 'https://earth-search.aws.element84.com/v1/search?next=2'}] if len(pages) == 1 else []}
        result = search('Sentinel-2', AREA, '2026-10-12T12:00:00Z', WHEN, provider, all_pages=True)
        self.assertEqual(len(result), 2)
        with self.assertRaisesRegex(ValueError, 'pagination'):
            search('Sentinel-2', AREA, '2026-10-12T12:00:00Z', WHEN,
                   lambda url: {'features': [], 'links': [{'rel': 'next', 'href': 'https://127.0.0.1/private'}]}, all_pages=True)

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_clouds_and_empty_water_never_trigger_paid_review(self):
        with tempfile.TemporaryDirectory() as temp:
            for clouds, feature, expected in [(True, True, False), (False, False, False), (False, True, True)]:
                workspace, scene, raw = image_fixture(Path(temp)/f'{clouds}-{feature}', clouds=clouds, feature=feature)
                self.assertEqual(screen(scene, raw, workspace.scenes)['send_to_ai'], expected)
                kept, excluded = retain_water_contacts(scene, [{'x': .5, 'y': .5}], workspace.scenes)
                self.assertEqual(len(kept), 0 if clouds else 1)
                if clouds:
                    self.assertEqual(excluded, 1)
            (workspace.scenes/(scene['id']+'.quality.png')).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                screen(scene, raw, workspace.scenes)

    def test_discovery_deduplicates_restart_and_queues_only_new_acquisitions(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            engine = CoastalScan(workspace)
            engine.layout = {'tiles': [{'id': 'one', 'bbox': AREA}], 'scope': 'Synthetic test only'}
            rows = [{'id': 'NEW', 'bbox': AREA, 'asset': 'test', 'quality_asset': 'quality', 'acquired_utc': WHEN},
                    {'id': 'OLD', 'bbox': AREA, 'asset': 'test', 'quality_asset': 'quality', 'acquired_utc': '2026-10-12T12:00:00Z'}]
            now = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)
            self.assertEqual(engine.discover(now, lambda *a, **k: rows), 1)
            restarted = CoastalScan(workspace)
            restarted.layout = engine.layout
            # Incremental discovery also sees yesterday; it must not backfill it
            # after a cold-start policy chose the newest per cell.
            self.assertEqual(restarted.discover(now, lambda *a, **k: rows), 0)
            newer = {**rows[0], 'id': 'LATER', 'acquired_utc': '2026-10-13T12:30:00Z'}
            self.assertEqual(restarted.discover(now, lambda *a, **k: [newer, *rows[:1]]), 1)
            self.assertEqual(scan_status(workspace.root)['queued'], 2)
            self.assertFalse(workspace.root.joinpath('ai/budget.json').exists())

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_processing_is_durable_before_paid_work_and_failure_pauses_ai_only(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, scene, raw = image_fixture(Path(temp)/'satellite')
            engine = CoastalScan(workspace)
            engine.folder.mkdir(exist_ok=True)
            product = {'id': 'TEST', 'asset': 'test', 'quality_asset': 'test', 'acquired_utc': WHEN}
            engine.state['jobs'] = {'one': {'tile': 'test', 'bbox': AREA, 'product': product, 'status': 'queued'}}
            engine.state['enabled'] = True
            def crop(_source, _area, output, **kwargs):
                for path in workspace.scenes.iterdir():
                    (output/path.name).write_bytes(path.read_bytes())
                return scene
            def paid(*args, **kwargs):
                state = read_state(workspace.root)
                self.assertEqual(state['jobs']['one']['status'], 'processing')
                self.assertIn('paid_attempt_utc', state['jobs']['one'])
                raise ValueError('Synthetic provider failure')
            with patch('argus.satellite_scan.quality_preview', return_value={'load_rgb': True}), \
                    patch('argus.satellite_scan.satellite.crop_scene', side_effect=crop), patch.object(workspace, 'analyse', side_effect=paid) as analyse:
                self.assertTrue(engine.process_one())
                self.assertEqual(analyse.call_count, 1)
                self.assertFalse(engine.process_one())
            state = read_state(workspace.root)
            self.assertTrue(state['enabled'])  # AIS/free discovery continue.
            self.assertTrue(state['analysis_paused'])
            self.assertEqual(state['jobs']['one']['status'], 'failed_review_required')
            self.assertFalse(engine.halt.is_set())

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_ais_expected_vessel_bypasses_empty_bright_feature_triage(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, scene, _ = image_fixture(Path(temp)/'satellite', feature=False)
            engine = CoastalScan(workspace)
            engine.folder.mkdir(exist_ok=True)
            engine.state['jobs'] = {'one': {'tile': 'test', 'bbox': AREA, 'status': 'queued',
                'product': {'id': 'TEST', 'asset': 'test', 'quality_asset': 'test', 'acquired_utc': WHEN}}}
            def crop(_source, _area, output, **kwargs):
                for path in workspace.scenes.iterdir():
                    (output/path.name).write_bytes(path.read_bytes())
                return scene
            with patch('argus.satellite_scan.quality_preview', return_value={'load_rgb': True}), \
                    patch('argus.satellite_scan.satellite.crop_scene', side_effect=crop), \
                    patch.object(workspace, 'ais_for_scene', return_value={'vessels': [{'mmsi': '123456789'}]}), \
                    patch.object(workspace, 'analyse', return_value={'contacts': []}) as analyse:
                self.assertTrue(engine.process_one())
                analyse.assert_called_once_with(scene['id'], automatic=True)
            self.assertEqual(engine.state['jobs']['one']['status'], 'review_ready')
            self.assertEqual(engine.state['jobs']['one']['screening']['status'], 'ais_expected_image_review')

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_partial_adaptive_result_is_saved_and_pauses_paid_work_while_ais_can_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, scene, _ = image_fixture(Path(temp)/'satellite')
            engine = CoastalScan(workspace)
            engine.folder.mkdir(exist_ok=True)
            engine.state['jobs'] = {'one': {'tile': 'test', 'bbox': AREA, 'status': 'queued',
                'product': {'id': 'TEST', 'asset': 'test', 'quality_asset': 'test', 'acquired_utc': WHEN}}}
            def crop(_source, _area, output, **kwargs):
                for path in workspace.scenes.iterdir():
                    (output/path.name).write_bytes(path.read_bytes())
                return scene
            result = {'contacts': [], 'visual': {'analysis_incomplete': True, 'paid_work_held': True}}
            with patch('argus.satellite_scan.quality_preview', return_value={'load_rgb': True}), \
                    patch('argus.satellite_scan.satellite.crop_scene', side_effect=crop), \
                    patch.object(workspace, 'analyse', return_value=result):
                self.assertTrue(engine.process_one())
            self.assertEqual(engine.state['jobs']['one']['status'], 'partial_review_required')
            self.assertTrue(engine.state['analysis_paused'])
            self.assertFalse(engine.halt.is_set())

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_interrupted_attempt_is_held_and_never_resubmitted_on_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            engine = CoastalScan(workspace)
            engine.state['jobs']['one'] = {'status': 'processing'}
            engine.publish()
            with patch('argus.satellite_ai.get_key', return_value='synthetic'), patch.object(engine, 'run'):
                engine.start()
                engine.thread.join()
            self.assertEqual(read_state(workspace.root)['jobs']['one']['status'], 'interrupted_review_required')
            # Mocked worker did not run its finally block.
            engine.lease.unlink()

    def test_manual_analysis_lock_waits_without_downloading_or_spending(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            engine = CoastalScan(workspace)
            engine.state['jobs']['one'] = {'status': 'queued'}
            with exclusive(workspace.root/'ai'), patch('argus.satellite_scan.quality_preview') as preview:
                self.assertFalse(engine.process_one())
            preview.assert_not_called()
            self.assertEqual(read_state(workspace.root)['jobs']['one']['status'], 'queued')
            self.assertFalse((workspace.root/'ai/budget.json').exists())


class SatelliteCustodyTests(unittest.TestCase):
    def real_snapshot(self, **fields):
        return snapshot(generated_utc=WHEN, feed={'status': 'live', 'label': 'real'},
            vessels=[vessel(label='real', lat=53.33, lon=-6.12, sog_kn=8, cog_deg=90,
                           received_utc=WHEN, metadata_received_utc=WHEN,
                           destination='DUBLIN', destination_received_utc='2026-10-13T12:00:01Z')], **fields)

    def test_capture_deduplicates_and_future_destination_is_not_joined_to_past(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            capture = AISCapture(workspace)
            payload = self.real_snapshot()
            first = capture.capture(lambda _: payload, now=timestamp(WHEN)+10)
            second = capture.capture(lambda _: payload, now=timestamp(WHEN)+11)
            self.assertGreater(first['recorded_rows'], 0)
            self.assertEqual(second['recorded_rows'], 0)
            historical = historical_ais(workspace.archive_root, WHEN, AREA)
            ship = historical['vessels'][0]
            self.assertTrue(ship['position_evidence']['observation_time_assumed'])
            self.assertNotIn('destination', ship['broadcast_fields'])
            self.assertEqual(ship['name'], 'TEST CONTACT')
            self.assertEqual(ship['broadcast_fields']['ship_type_description']['value'], 'Cargo')
            self.assertIn('DUBLIN', json.dumps(load_latest(capture.path)))
            with self.assertRaisesRegex(ValueError, 'stale'):
                capture.capture(lambda _: payload, now=timestamp(WHEN)+700)

    def test_length_capture_preserves_old_headers_and_never_backdates_or_keeps_cleared_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            capture = AISCapture(workspace)
            folder = workspace.archive_root/'capture'
            folder.mkdir(parents=True)
            legacy = folder/'2026-10-13.csv'
            original = 'mmsi,msg_type,lat,lon,sog,cog,recv_utc\n'
            legacy.write_text(original)
            packet = self.real_snapshot()
            packet['vessels'][0].update(ais_length_m=180, metadata_received_utc='2026-10-13T11:50:00Z')
            capture.capture(lambda _: packet, now=timestamp(WHEN)+10)
            historical = historical_ais(workspace.archive_root, WHEN, AREA)
            self.assertEqual(historical['vessels'][0]['broadcast_fields']['length_m']['value'], 180)
            self.assertEqual(legacy.read_text(), original)
            self.assertTrue((folder/'2026-10-13.v2.csv').exists())
            packet['sequence'] += 1
            packet['vessels'][0].update(ais_length_m=250, metadata_received_utc='2026-10-13T12:00:01Z')
            capture.capture(lambda _: packet, now=timestamp(WHEN)+10)
            self.assertEqual(historical_ais(workspace.archive_root, WHEN, AREA)['vessels'][0]['broadcast_fields']['length_m']['value'], 180)
            packet['sequence'] += 1
            packet['vessels'][0].update(ais_length_m=None, metadata_received_utc=WHEN)
            capture.capture(lambda _: packet, now=timestamp(WHEN)+10)
            self.assertIsNone(historical_ais(workspace.archive_root, WHEN, AREA)['vessels'][0]['broadcast_fields']['length_m']['value'])

    def test_static_only_contacts_keep_metadata_without_inventing_a_position(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            capture = AISCapture(workspace)
            packet = self.real_snapshot()
            packet['vessels'][0].update(lat=None, lon=None, received_utc=None, ais_length_m=180,
                                        metadata_received_utc='2026-10-13T11:59:00Z')
            result = capture.capture(lambda _: packet, now=timestamp(WHEN))
            self.assertEqual(result['latest_vessels'], 1)
            self.assertIsNone(load_latest(capture.path)['vessels'][0]['lat'])
            self.assertEqual(historical_ais(workspace.archive_root, WHEN, AREA)['vessels'], [])
            packet['sequence'] += 1
            packet['vessels'][0].update(lat=53.33, lon=-6.12, received_utc=WHEN)
            capture.capture(lambda _: packet, now=timestamp(WHEN)+1)
            ship = historical_ais(workspace.archive_root, WHEN, AREA)['vessels'][0]
            self.assertEqual(ship['broadcast_fields']['length_m']['value'], 180)

    def test_stream_reset_never_creates_an_interpolated_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [dict(mmsi='123456789', msg_type='PositionReport', lat=53.33, lon=-6.12, sog=8, cog=90,
                         recv_utc='2026-10-13T11:50:01Z', stream_id='one'),
                    dict(mmsi='123456789', msg_type='PositionReport', lat=53.33, lon=-6.11, sog=8, cog=90,
                         recv_utc='2026-10-13T12:00:01Z', stream_id='two')]
            with (root/'history.csv').open('w', newline='') as out:
                writer = csv.DictWriter(out, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(historical_ais(root, WHEN, AREA)['vessels'], [])

    def test_candidate_ranking_ambiguity_motion_and_current_fix_are_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, _, _ = fixture(Path(temp)/'satellite')
            capture = AISCapture(workspace)
            capture.capture(lambda _: self.real_snapshot(), now=timestamp(WHEN)+10)
            ais = historical_ais(workspace.archive_root, WHEN, AREA)
            other = deepcopy(ais['vessels'][0])
            other.update(mmsi='987654321', name='ANOTHER SHIP')
            other['position']['lon'] += .001
            ais['vessels'].append(other)
            contact = {'id': 'AI-1', 'ts': WHEN, 'lat': 53.33, 'lon': -6.12}
            result = associate([contact], ais)[0]
            self.assertTrue(result['ambiguous'])
            self.assertEqual(result['matched_mmsi'], '123456789')
            self.assertEqual(result['candidates'][0]['nearest_fix_offset_s'], 0)
            latest = {'vessels': [{**self.real_snapshot()['vessels'][0], 'lon': -6.02,
                                  'received_utc': '2026-10-13T13:00:00Z'}]}
            updated = attach_latest([result], latest, WHEN, timestamp('2026-10-13T14:00:00Z'))[0]
            current = updated['candidates'][0]['latest']
            self.assertTrue(current['stale'])
            self.assertGreater(current['displacement_km'], 6)
            self.assertLess(current['minimum_average_speed_kn'], 10)
            self.assertEqual(updated['candidates'][0]['position']['lon'], -6.12)
            ais['vessels'][0]['position_evidence']['kinematic_consistency'] = 'exceeds_assumed_limit'
            checked = associate([contact], ais)[0]
            self.assertEqual(checked['matched_mmsi'], '987654321')
            self.assertEqual(checked['candidates'][0]['assessment'], 'motion_inconsistent_review_required')

    def test_impossible_bracket_motion_cannot_identify_a_satellite_contact(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'history.csv'
            path.write_text('mmsi,msg_type,lat,lon,sog,cog,time_utc,recv_utc\n'
                            '123456789,PositionReport,53.33,-6.30,8,90,2026-10-13T11:59:00Z,2026-10-13T11:59:00Z\n'
                            '123456789,PositionReport,53.33,-5.94,8,90,2026-10-13T12:01:00Z,2026-10-13T12:01:00Z\n')
            ais = historical_ais(temp, WHEN, AREA)
            self.assertEqual(len(ais['vessels']), 1)
            self.assertGreater(ais['vessels'][0]['position_evidence']['implied_segment_speed_kn'], 80)
            point = associate([{'lat': 53.33, 'lon': -6.12, 'ts': WHEN}], ais)[0]
            self.assertIsNone(point['matched_mmsi'])
            self.assertFalse(point['candidates'][0]['motion_consistent'])

    def test_undated_current_json_particulars_are_not_backdated(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'history.json').write_text(json.dumps({'vessels': [{'mmsi': '123456789',
                'label': 'real', 'name': 'CURRENT NAME', 'destination': 'CURRENT DESTINATION',
                'track': [{'ts': WHEN, 'lat': 53.33, 'lon': -6.12}]}]}))
            ship = historical_ais(temp, WHEN, AREA)['vessels'][0]
            self.assertNotEqual(ship['name'], 'CURRENT NAME')
            self.assertNotIn('destination', ship['broadcast_fields'])


if __name__ == '__main__':
    unittest.main()
