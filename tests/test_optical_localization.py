"""Pixel support preserves uncertainty instead of snapping hints to arbitrary ships."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from argus.optical_localization import anchor_observations, position_eligible
from argus.satellite import atomic_json, pixel_location
from argus.satellite_ais import associate
from argus.satellite_compare import compare_review
from test_satellite import WHEN
from test_satellite_compare import vessel
from test_satellite_scan import image_fixture


class OpticalLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace, self.scene, _ = image_fixture(Path(self.temp.name)/'satellite')
        self.hint = {'id': 'AI-1', 'x': .7, 'y': .5, 'confidence': 'medium',
                     'description': 'Synthetic model hint', 'label': 'assumption', 'ts': WHEN,
                     **pixel_location(self.scene, .7, .5)}
        self.feature = {'x': .5, 'y': .5, 'bounds_px': [30,30,33,34], 'pixel_count': 12,
                        'label': 'assumption', 'source': 'compact_optical_feature'}

    def anchor(self, points=None, features=None, **options):
        return anchor_observations(self.scene, [self.hint] if points is None else points,
            {'candidates': [self.feature] if features is None else features, 'clutter': False}, **options)

    def test_unique_feature_preserves_original_hint_and_requires_verified_water(self):
        original = deepcopy(self.hint)
        result = self.anchor(water_verified=True)['contacts'][0]
        self.assertEqual(result['x'], .5)
        self.assertEqual(result['localization']['model_position']['x'], .7)
        self.assertEqual(self.hint, original)
        self.assertTrue(position_eligible(result))
        self.assertFalse(position_eligible(self.anchor()['contacts'][0]))

    def test_multiple_features_and_competing_hints_do_not_pick_arbitrary_anchors(self):
        ambiguous = self.anchor(features=[self.feature, {**self.feature, 'x': .6}], water_verified=True)
        self.assertEqual(ambiguous['contacts'][0]['localization']['status'], 'ambiguous')
        self.assertEqual(ambiguous['contacts'][0]['x'], .7)
        contested = self.anchor(points=[self.hint, {**self.hint, 'id': 'AI-2'}], water_verified=True)
        self.assertEqual(contested['status_counts'], {'contested': 2, 'feature_only': 1})
        self.assertFalse(any(position_eligible(p) for p in contested['contacts']))

    def test_feature_only_cannot_consume_identity_or_raise_silence_but_vetoes_absence(self):
        points = self.anchor(points=[], water_verified=True)['contacts']
        ship = vessel()
        ship['position'] = pixel_location(self.scene, .5, .5)
        ship['track'] = [{'ts': WHEN, **ship['position']}]
        ais = {'vessels': [ship], 'acquired_utc': WHEN}
        contacts = associate(points, ais)
        self.assertIsNone(contacts[0]['matched_mmsi'])
        result = compare_review(self.scene, contacts, ais, {'image_input_verified': True, 'contacts': []}, self.workspace.scenes)
        self.assertEqual(result['leads'], [])
        self.assertEqual(result['contact_checks'][0]['status'], 'optical_feature_unclassified')
        self.assertEqual(result['vessel_checks'][0]['status'], 'nearby_image_contact_review')

    def test_unique_anchor_can_match_but_ambiguous_hint_cannot(self):
        ship = vessel()
        ship['position'] = pixel_location(self.scene, .5, .5)
        ship['track'] = [{'ts': WHEN, **ship['position']}]
        ais = {'vessels': [ship], 'acquired_utc': WHEN}
        supported = associate(self.anchor(water_verified=True)['contacts'], ais)
        self.assertEqual(supported[0]['matched_mmsi'], ship['mmsi'])
        close_hint = {**self.hint, 'x': .51, **pixel_location(self.scene, .51, .5)}
        uncertain = associate(self.anchor(points=[close_hint], features=[self.feature, {**self.feature, 'x': .6}],
                                          water_verified=True)['contacts'], ais)
        self.assertTrue(all(p['matched_mmsi'] is None for p in uncertain))
        self.assertEqual(uncertain[0]['candidates'][0]['assessment'], 'visual_location_unverified')
        result = compare_review(self.scene, uncertain, ais, {'image_input_verified': True}, self.workspace.scenes)
        self.assertEqual(result['leads'], [])

    def test_free_rejoin_rebuilds_from_raw_model_output_without_compounding_anchors(self):
        atomic_json(self.workspace.root/'reviews'/(self.scene['id']+'.json'), {
            'scene': self.scene, 'visual': {'image_input_verified': True, 'contacts': [self.hint]},
            'contacts': [self.hint], 'ais': {'vessels': []}})
        with patch.object(self.workspace, 'ais_for_scene', return_value={'vessels': [], 'acquired_utc': WHEN}), \
                patch('argus.satellite_workspace.visual_analysis') as paid:
            first = self.workspace.review(self.scene['id'])
            second = self.workspace.review(self.scene['id'])
        self.assertEqual(first['contacts'], second['contacts'])
        self.assertEqual(second['visual']['contacts'][0]['x'], .7)
        self.assertEqual(second['contacts'][0]['localization']['model_position']['x'], .7)
        paid.assert_not_called()
