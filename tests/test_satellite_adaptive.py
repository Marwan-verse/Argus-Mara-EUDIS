"""Detail-window geography, budget reuse, failure holds and local coverage gates.

The provider is synthetic. These tests do not measure vessel-detection accuracy.
"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from argus.satellite import atomic_json, pixel_location
from argus.satellite_adaptive import detail_windows, review_image
from argus.satellite_ai import read_ledger, visual_analysis
from argus.satellite_compare import analysis_coverage, compare_review, visibility
from argus.satellite_screen import water_mask
from argus import supabase_ais
from test_satellite import FakeTensorX, DEFAULT_QUESTION, WHEN
from test_satellite_compare import vessel
from test_satellite_scan import image_fixture


class Provider(FakeTensorX):
    def __init__(self, *, count=1, cap_at=None, fail_at=None):
        super().__init__()
        self.count, self.cap_at, self.fail_at = count, cap_at, fail_at

    def __call__(self, url, **kwargs):
        value = super().__call__(url, **kwargs)
        if not url.endswith('/chat/completions'):
            return value
        number = len(self.paid)
        if number == self.fail_at:
            raise ValueError('Synthetic uncertain provider timeout')
        count = 24 if number == self.cap_at else self.count
        value['choices'][0]['message']['content'] = json.dumps({
            'summary': 'Synthetic provider points',
            'contacts': [{'x': .2+.6*i/max(1, count-1) if count > 1 else .5, 'y': .5,
                          'confidence': 'low', 'description': 'Synthetic test point'} for i in range(count)],
            'limitations': ['Synthetic response, no inference accuracy evidence']})
        return value


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace, self.scene, self.image = image_fixture(Path(self.temp.name)/'satellite')
        self.root = self.workspace.root/'ai'
        self.key = patch('argus.satellite_ai.get_key', return_value='synthetic-key')
        self.key.start()
        self.addCleanup(self.key.stop)

    def run_provider(self, provider, *, dense=True):
        return review_image(self.root, self.scene, self.image, DEFAULT_QUESTION, dense=dense,
                            analyse=lambda *args: visual_analysis(*args, transport=provider))

    def test_overlapping_crops_preserve_source_pixels_grid_and_acquisition_time(self):
        original = Image.new('RGB', (65, 63))
        original.putdata([(x, y, 100) for y in range(63) for x in range(65)])
        raw = BytesIO()
        original.save(raw, 'PNG')
        scene = {**self.scene, 'width': 65, 'height': 63, 'image_sha256': hashlib.sha256(raw.getvalue()).hexdigest()}
        windows = detail_windows(scene, raw.getvalue())
        for window in windows:
            child = window['scene']
            x0, y0, x1, y1 = window['window']
            image = Image.open(BytesIO(window['image']))
            self.assertEqual(image.getpixel((0, 0)), original.getpixel((round(x0*65), round(y0*63))))
            self.assertEqual(child['acquired_utc'], WHEN)
            self.assertNotIn('quality_sha256', child)
            expected = pixel_location(scene, (x0+x1)/2, (y0+y1)/2)
            mapped = pixel_location(child, .5, .5)
            self.assertAlmostEqual(expected['lat'], mapped['lat'])
            self.assertAlmostEqual(expected['lon'], mapped['lon'])
        self.assertLess(windows[0]['window'][0], windows[1]['window'][0])
        self.assertGreater(windows[0]['window'][2], windows[1]['window'][0])

    def test_dense_review_lists_more_than_24_observations_and_reuses_all_components(self):
        provider = Provider(count=10)
        result = self.run_provider(provider)
        self.assertEqual(len(provider.paid), 4)
        self.assertEqual(len(result['contacts']), 40)
        self.assertFalse(result['analysis_incomplete'])
        self.assertTrue(all(p['ts'] == WHEN for p in result['contacts']))
        self.assertEqual(read_ledger(self.root)['calls'], 4)
        with patch('argus.satellite_ai.get_key', return_value=''):
            cached = review_image(self.root, self.scene, self.image, DEFAULT_QUESTION, dense=True,
                                  analyse=lambda *args: self.fail('Completed component was submitted again'))
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['contacts'], result['contacts'])
        self.assertEqual(read_ledger(self.root)['calls'], 4)

    def test_saturated_overview_retains_its_observations_and_adds_four_detail_calls(self):
        provider = Provider(cap_at=1)
        result = self.run_provider(provider, dense=False)
        self.assertEqual(len(provider.paid), 5)
        self.assertEqual(len(result['contacts']), 28)
        self.assertEqual(sum(p.get('origin_window') == 'overview' for p in result['contacts']), 24)
        self.assertFalse(result['contact_limit_reached'])

    def test_uncertain_window_holds_further_paid_work_and_never_retries_it(self):
        provider = Provider(fail_at=2)
        result = self.run_provider(provider)
        self.assertTrue(result['paid_work_held'])
        self.assertEqual(len(provider.paid), 2)
        self.assertEqual([w['status'] for w in result['analysis_windows']], ['complete', 'held', 'pending', 'pending'])
        self.assertTrue(result['analysis_incomplete'])
        self.assertEqual(len(result['contacts']), 1)
        again = self.run_provider(provider)
        self.assertEqual(len(provider.paid), 2)
        self.assertEqual(read_ledger(self.root)['calls'], 2)
        self.assertEqual(again['contacts'], result['contacts'])
        review_image(self.root, self.scene, self.image, ' '+DEFAULT_QUESTION+' ', dense=True,
                     analyse=lambda *args: self.fail('Whitespace changed a held request identity'))

    def test_interrupted_submitted_window_cannot_be_automatically_paid_again(self):
        provider = Provider()
        self.run_provider(provider)
        path = next((self.root/'adaptive').glob('*/window-1.json'))
        entry = json.loads(path.read_text())
        entry['status'] = 'submitted'
        entry.pop('visual')
        atomic_json(path, entry)
        result = self.run_provider(provider)
        self.assertTrue(result['paid_work_held'])
        self.assertEqual(len(provider.paid), 4)
        self.assertEqual(result['analysis_windows'][1]['status'], 'held')

    def test_budget_exhaustion_keeps_completed_window_and_withholds_unreviewed_areas(self):
        self.root.mkdir()
        atomic_json(self.root/'budget.json', {'reserved_usd': 19.94, 'reported_usd': 0, 'calls': 0})
        provider = Provider()
        result = self.run_provider(provider)
        self.assertEqual(len(provider.paid), 1)
        self.assertTrue(result['analysis_incomplete'])
        self.assertLessEqual(read_ledger(self.root)['reserved_usd'], 20)
        self.assertEqual(result['analysis_windows'][0]['status'], 'complete')
        self.assertEqual(result['analysis_windows'][1]['status'], 'blocked')

    def test_only_fully_reviewed_clear_footprints_can_raise_negative_leads(self):
        visual = self.run_provider(Provider(cap_at=1))
        self.assertGreaterEqual(len(visual['contacts']), 24)
        points = [pixel_location(self.scene, .25, .25), pixel_location(self.scene, .75, .75),
                  pixel_location(self.scene, .5, .25)]
        ais_vessels = []
        for i, point in enumerate(points):
            row = vessel(str(100000000+i))
            row['position'] = point
            ais_vessels.append(row)
        ais = {'acquired_utc': WHEN, 'vessels': ais_vessels}
        result = compare_review(self.scene, [], ais, visual, self.workspace.scenes)
        self.assertEqual([r['status'] for r in result['vessel_checks']],
                         ['detail_window_capped', 'ais_not_detected', 'detail_window_capped'])
        self.assertEqual(len(result['leads']), 1)
        # A malformed saved partition cannot imply reviewed coverage.
        visual['analysis_windows'].pop()
        self.assertEqual(analysis_coverage(self.scene, points[1], visual), 'image_analysis_coverage_unavailable')

    def test_database_clear_areas_exclude_capped_and_unreviewed_detail_windows(self):
        visual = self.run_provider(Provider(cap_at=1))
        areas = supabase_ais.observed_rectangles(self.scene, self.workspace.scenes, tiles=8, analysis=visual)
        self.assertTrue(areas)
        for w, s, e, n in areas:
            point = {'lat': (s+n)/2, 'lon': (w+e)/2}
            self.assertEqual(analysis_coverage(self.scene, point, visual), 'complete')
        capped = {**visual, 'analysis_windows': None, 'contact_limit_reached': True}
        self.assertEqual(supabase_ais.observed_rectangles(self.scene, self.workspace.scenes, analysis=capped), [])

    def test_database_area_boundaries_have_complete_clear_footprints(self):
        quality = Image.new('L', (64, 64), 6)
        quality.paste(9, (40, 0, 64, 64))
        raw = BytesIO()
        quality.save(raw, 'PNG')
        (self.workspace.scenes/(self.scene['id']+'.quality.png')).write_bytes(raw.getvalue())
        self.scene['quality_sha256'] = hashlib.sha256(raw.getvalue()).hexdigest()
        mask, _ = water_mask(self.scene, self.workspace.scenes)
        areas = supabase_ais.observed_rectangles(self.scene, self.workspace.scenes)
        self.assertTrue(areas)
        for w, s, e, n in areas:
            for lon, lat in [(w, s), (w, n), (e, s), (e, n), ((w+e)/2, (s+n)/2)]:
                self.assertEqual(visibility(self.scene, {'lat': lat, 'lon': lon}, mask), 'clear_water')

    def test_workspace_preserves_a_held_first_window_without_inventing_an_empty_detection(self):
        provider = Provider(fail_at=1)
        ais = {'acquired_utc': WHEN, 'vessels': [vessel(str(100000000+i)) for i in range(17)],
               'coverage': {'status': 'partial'}}
        with patch.object(self.workspace, 'ais_for_scene', return_value=ais), \
                patch('argus.satellite_workspace.visual_analysis',
                      side_effect=lambda *args: visual_analysis(*args, transport=provider)), \
                patch('argus.supabase_ais.linked', return_value=False):
            result = self.workspace.analyse(self.scene['id'], automatic=True)
            self.assertFalse(result['visual']['image_input_verified'])
            self.assertTrue(result['visual']['analysis_incomplete'])
            self.assertTrue(all(r['status'] == 'image_not_analysed' for r in result['comparison']['vessel_checks']))
            saved = self.workspace.review(self.scene['id'])
            self.assertEqual(saved['visual']['analysis_windows'][0]['status'], 'held')
            self.assertEqual(self.workspace.comparison_index()['partial_analysis_images'], 1)
            self.assertEqual(self.workspace.contacts(), [])
        self.assertEqual(len(provider.paid), 1)

    def test_compact_index_does_not_silently_drop_contacts_after_5000(self):
        for i in range(60):
            identifier = f'{i:024x}'
            contacts = [{'id': f'AI-Q0-{j}', 'lat': 53.33, 'lon': -6.12, 'confidence': 'low',
                         'label': 'assumption', 'description': 'x'*400, 'ts': WHEN, 'matched_mmsi': None}
                        for j in range(96)]
            atomic_json(self.workspace.root/'reviews'/(identifier+'.json'),
                        {'scene': {**self.scene, 'id': identifier}, 'contacts': contacts,
                         'visual': {'image_input_verified': True}})
        index = self.workspace.contacts()
        self.assertEqual(len(index), 5760)
        self.assertNotIn('description', index[0])
        # The maximum 200 roots × 120 observations stays inside the native
        # satellite response limit when descriptions load only on selection.
        self.assertLess(len(json.dumps(index[:120]*200).encode()), 8*1024*1024)
