"""Satellite time/geometry, token accounting and native workflow regressions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from argus.satellite import bounds, crop_scene, mercator, pixel_location, search
from argus.satellite_ai import choose_model, exclusive, parse_result, read_ledger, visual_analysis
from argus.satellite_ais import associate, historical_ais
from argus.satellite_workspace import SatelliteWorkspace, DEFAULT_QUESTION

WHEN = '2026-10-13T12:00:00Z'
AREA = [-6.17, 53.30, -6.07, 53.36]
MODEL = 'qwen/qwen3.8-flash-next'


def fixture(root):
    buffer = BytesIO()
    Image.new('RGB', (64, 64), '#172836').save(buffer, format='PNG')
    image = buffer.getvalue()
    left, bottom = mercator(AREA[0], AREA[1])
    right, top = mercator(AREA[2], AREA[3])
    scene = {'id': 'a'*24, 'product_id': 'SYNTHETIC-TEST', 'sensor': 'Sentinel-2',
             'acquired_utc': WHEN, 'bbox': AREA, 'mercator_bounds': [left, bottom, right, top],
             'label': 'simulated', 'image_sha256': hashlib.sha256(image).hexdigest(),
             'width': 64, 'height': 64, 'prepared_utc': WHEN}
    workspace = SatelliteWorkspace(root)
    workspace.scenes.mkdir(parents=True)
    (workspace.scenes/(scene['id']+'.png')).write_bytes(image)
    (workspace.scenes/(scene['id']+'.json')).write_text(json.dumps(scene))
    return workspace, scene, image


class FakeTensorX:
    def __init__(self):
        self.paid = []
        self.fail = False

    def __call__(self, url, **kwargs):
        if url.endswith('/models'):
            return {'data': [{'id': MODEL}]}
        if url.endswith('/model/info'):
            return {'data': [{'model_name': MODEL, 'model_info': {'supports_vision': True,
                       'max_input_tokens': 256000, 'max_output_tokens': 8192}}]}
        self.paid.append(kwargs['payload'])
        if self.fail:
            raise ValueError('Synthetic timeout')
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'summary': 'Synthetic visual test only', 'contacts': [{'x': .5, 'y': .5,
                         'confidence': 'low', 'description': 'Synthetic test contact'}], 'limitations': ['Not real imagery']})}}],
                'usage': {'prompt_tokens': 300, 'completion_tokens': 100,
                          'prompt_tokens_details': {'image_tokens': 78}}}


class SatelliteTests(unittest.TestCase):
    def test_mapping_is_from_grid_and_not_model_geographic_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            _, scene, _ = fixture(Path(temp)/'satellite')
            northwest = pixel_location(scene, 0, 0)
            southeast = pixel_location(scene, 1, 1)
            self.assertAlmostEqual(northwest['lat'], AREA[3])
            self.assertAlmostEqual(northwest['lon'], AREA[0])
            self.assertAlmostEqual(southeast['lat'], AREA[1])
            self.assertAlmostEqual(southeast['lon'], AREA[2])
            for x in (-.1, 1.1, float('nan'), True):
                with self.assertRaises(ValueError):
                    pixel_location(scene, x, .5)
            with self.assertRaises(ValueError):
                parse_result({'summary': 'bad', 'contacts': [{'x': .5, 'y': .5, 'confidence': 'certain', 'description': 'bad'}]}, scene)

    def test_area_and_catalogue_are_bounded_and_ordered_by_acquisition(self):
        with self.assertRaises(ValueError):
            bounds([-18, 49, -4, 57], small=True)
        with self.assertRaises(ValueError):
            bounds([0, 0, 1, 1])
        rows = search('Sentinel-2', AREA, '2026-10-01T00:00:00Z', WHEN,
                      lambda url: {'features': [{'id': 'test2', 'properties': {'datetime': WHEN}},
                                                {'id': '../unsafe', 'properties': {'datetime': WHEN}},
                                                {'id': 'test1', 'properties': {'datetime': '2026-10-01T12:00:00Z'}}]})
        self.assertEqual([row['id'] for row in rows], ['test2', 'test1'])
        with self.assertRaises(ValueError):
            search('Sentinel-2', AREA, '2025-01-01T00:00:00Z', WHEN)

    def test_no_key_or_bad_metadata_never_spends(self):
        fake = FakeTensorX()
        with tempfile.TemporaryDirectory() as temp, patch('argus.satellite_ai.get_key', return_value=''):
            _, scene, image = fixture(Path(temp)/'satellite')
            with self.assertRaises(ValueError):
                visual_analysis(Path(temp)/'ai', scene, image, DEFAULT_QUESTION, transport=fake)
        self.assertEqual(fake.paid, [])
        def no_vision(url, **kwargs):
            value = fake(url, **kwargs)
            if url.endswith('/model/info'):
                value['data'][0]['model_info']['supports_vision'] = False
            return value
        with self.assertRaises(ValueError):
            choose_model('synthetic-key', no_vision)
        self.assertEqual(fake.paid, [])

    def test_cache_never_repeats_paid_request_even_when_preparation_time_changes(self):
        fake = FakeTensorX()
        with tempfile.TemporaryDirectory() as temp, patch('argus.satellite_ai.get_key', return_value='synthetic-key'):
            _, scene, image = fixture(Path(temp)/'satellite')
            result = visual_analysis(Path(temp)/'ai', scene, image, DEFAULT_QUESTION, transport=fake)
            scene['prepared_utc'] = '2026-10-14T12:00:00Z'
            again = visual_analysis(Path(temp)/'ai', scene, image, DEFAULT_QUESTION, transport=fake)
            self.assertTrue(again['cached'])
            self.assertEqual(result['cache_id'], again['cache_id'])
            self.assertEqual(len(fake.paid), 1)
            self.assertEqual(len(fake.paid[0]['messages']), 2)
            self.assertNotIn('tools', fake.paid[0])
            self.assertLessEqual(fake.paid[0]['max_tokens'], 1536)
            self.assertEqual(fake.paid[0]['reasoning_effort'], 'low')
            self.assertEqual(read_ledger(Path(temp)/'ai')['calls'], 1)

    def test_advertised_vision_cannot_select_glm_that_failed_live_validation(self):
        fake = FakeTensorX()
        def both_models(url, **kwargs):
            result = fake(url, **kwargs)
            if url.endswith('/models'):
                result['data'].append({'id': 'z-ai/glm-5.3-flash'})
            elif url.endswith('/model/info'):
                entry = deepcopy(result['data'][0])
                entry['model_name'] = 'z-ai/glm-5.3-flash'
                result['data'].append(entry)
            return result
        with tempfile.TemporaryDirectory() as temp, patch('argus.satellite_ai.get_key', return_value='synthetic-key'):
            _, scene, image = fixture(Path(temp)/'satellite')
            value = visual_analysis(Path(temp)/'ai', scene, image, DEFAULT_QUESTION, transport=both_models)
            self.assertEqual(value['model'], MODEL)
            self.assertEqual(fake.paid[0]['reasoning_effort'], 'low')

    def test_text_only_reply_never_becomes_zero_detected_ships(self):
        fake = FakeTensorX()
        def missing_image(url, **kwargs):
            result = fake(url, **kwargs)
            if url.endswith('/chat/completions'):
                result['usage'].pop('prompt_tokens_details')
            return result
        with tempfile.TemporaryDirectory() as temp, patch('argus.satellite_ai.get_key', return_value='synthetic-key'):
            _, scene, image = fixture(Path(temp)/'satellite')
            root = Path(temp)/'ai'
            with self.assertRaisesRegex(ValueError, 'contact results withheld'):
                visual_analysis(root, scene, image, DEFAULT_QUESTION, transport=missing_image)
            self.assertFalse((root/'cache').exists())
            self.assertGreater(read_ledger(root)['reserved_usd'], 0)

    def test_budget_failures_and_concurrent_calls_fail_closed(self):
        fake = FakeTensorX()
        with tempfile.TemporaryDirectory() as temp, patch('argus.satellite_ai.get_key', return_value='synthetic-key'):
            _, scene, image = fixture(Path(temp)/'satellite')
            root = Path(temp)/'ai'
            root.mkdir()
            (root/'budget.json').write_text(json.dumps({'reserved_usd': 19.99, 'reported_usd': 0, 'calls': 1}))
            with self.assertRaises(ValueError):
                visual_analysis(root, scene, image, DEFAULT_QUESTION, transport=fake)
            self.assertEqual(fake.paid, [])
            (root/'budget.json').write_text(json.dumps({'reserved_usd': 0, 'reported_usd': 0, 'calls': 0}))
            fake.fail = True
            with self.assertRaises(ValueError):
                visual_analysis(root, scene, image, DEFAULT_QUESTION, transport=fake)
            self.assertEqual(len(fake.paid), 1)
            self.assertGreater(read_ledger(root)['reserved_usd'], 0)
            self.assertEqual(read_ledger(root)['calls'], 1)
            with exclusive(root):
                with self.assertRaises(ValueError):
                    visual_analysis(root, scene, image, DEFAULT_QUESTION, transport=fake)
            self.assertEqual(len(fake.paid), 1)

    def test_current_ais_and_future_static_data_do_not_replace_history(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'ais.csv'
            path.write_text('mmsi,msg_type,lat,lon,sog,cog,time_utc,recv_utc,raw\n'
                            '123456789,PositionReport,53.33,-6.12,8,90,2026-10-15T12:00:00Z,2026-10-15T12:00:00Z,\n')
            result = historical_ais(temp, WHEN, AREA)
            self.assertEqual(result['coverage']['status'], 'unavailable')
            import csv
            rows = [dict(mmsi='123456789', msg_type='PositionReport', lat=53.33, lon=-6.12,
                         sog=8, cog=90, time_utc=WHEN, recv_utc=WHEN),
                    dict(mmsi='123456789', msg_type='ShipStaticData', recv_utc='2026-10-13T11:50:00Z',
                         raw=json.dumps({'Message': {'ShipStaticData': {'Name': 'PAST SHIP', 'Destination': 'IE DUB'}}})),
                    dict(mmsi='123456789', msg_type='ShipStaticData', recv_utc='2026-10-13T12:00:01Z',
                         raw=json.dumps({'Message': {'ShipStaticData': {'Destination': 'FUTURE'}}}))]
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
                writer.writeheader()
                writer.writerows(rows)
            result = historical_ais(temp, WHEN, AREA)
            vessel = result['vessels'][0]
            self.assertEqual(vessel['broadcast_fields']['destination']['value'], 'IE DUB')
            self.assertEqual(vessel['name'], 'PAST SHIP')
            self.assertNotIn('raw', json.dumps(result))
            contacts = associate([{'lat': 53.33, 'lon': -6.12}, {'lat': 53.33, 'lon': -6.12}], result)
            self.assertEqual(sum(c['matched_mmsi'] is not None for c in contacts), 1)
            self.assertTrue(all(c['identity_confirmed'] is False for c in contacts))

    def test_synthetic_raster_does_not_join_to_real_ship_positions(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace, scene, _ = fixture(Path(temp)/'satellite')
            with patch('argus.satellite_workspace.historical_ais') as archive:
                result = workspace.history(scene['id'])
            archive.assert_not_called()
            self.assertEqual(result['ais']['vessels'], [])

    def test_receipt_only_is_an_explicit_time_assumption_and_long_gaps_stay_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'ais.csv'
            path.write_text('mmsi,msg_type,lat,lon,sog,cog,time_utc,recv_utc\n'
                            f'123456789,PositionReport,53.33,-6.12,8,90,,{WHEN}\n')
            result = historical_ais(temp, WHEN, AREA)
            self.assertTrue(result['vessels'][0]['position_evidence']['observation_time_assumed'])
            path.write_text('mmsi,msg_type,lat,lon,sog,cog,time_utc,recv_utc\n'
                            '123456789,PositionReport,53.33,-6.12,8,90,2026-10-13T11:50:00Z,2026-10-13T11:50:00Z\n')
            self.assertEqual(historical_ais(temp, WHEN, AREA)['vessels'], [])

    def test_real_geotiff_reprojection_retains_pixel_grid_and_rejects_remote_urls(self):
        try:
            import numpy as np
            import rasterio
            from rasterio.transform import from_bounds
        except ImportError:
            self.skipTest('Optional satellite raster libraries not installed')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.tif'
            with rasterio.open(path, 'w', driver='GTiff', height=100, width=100, count=3,
                               dtype='uint8', crs='EPSG:4326', transform=from_bounds(*AREA, 100, 100)) as dataset:
                dataset.write(np.full((3, 100, 100), 64, dtype='uint8'))
            scene = crop_scene(path, AREA, Path(temp)/'out', scene_id='synthetic', acquired_utc=WHEN,
                               sensor='Sentinel-2', label='simulated')
            self.assertGreater(scene['valid_fraction'], .99)
            self.assertAlmostEqual(pixel_location(scene, 0, 0)['lat'], AREA[3])
            with self.assertRaisesRegex(ValueError, 'valid imagery'):
                crop_scene(path, [-6.3, 53.30, -6.2, 53.36], Path(temp)/'out',
                           scene_id='outside', acquired_utc=WHEN, sensor='Sentinel-2')
            for source in ('https://127.0.0.1/private.tif', 'file:///etc/passwd',
                           'https://sentinel-cogs.s3.us-west-2.amazonaws.com.evil.test/x.tif'):
                with self.assertRaises(ValueError):
                    crop_scene(source, AREA, Path(temp)/'out', scene_id='test', acquired_utc=WHEN, sensor='Sentinel-2')


if __name__ == '__main__':
    unittest.main()
