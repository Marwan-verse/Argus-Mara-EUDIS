"""Acquisition-time reverse checks must not turn missing evidence into alerts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from argus.satellite import atomic_json
from argus.satellite_compare import compare_review
from test_satellite import WHEN, fixture
from test_satellite_scan import RASTERS_AVAILABLE, image_fixture


def vessel(mmsi='123456789', lon=-6.12, **fields):
    return {'mmsi': mmsi, 'name': 'TEST SHIP', 'position': {'lat': 53.33, 'lon': lon},
            'broadcast_fields': {'length_m': {'value': 100, 'received_utc': WHEN}, **fields},
            'position_evidence': {'kinematic_consistency': 'within_assumed_limit'},
            'label': 'real'}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace, self.scene, _ = image_fixture(Path(self.temp.name)/'satellite', feature=False)
        self.ais = {'acquired_utc': WHEN, 'vessels': [vessel()], 'coverage': {'status': 'partial'}}
        self.visual = {'image_input_verified': True, 'contacts': []}

    def compare(self, contacts=()):
        return compare_review(self.scene, list(contacts), self.ais, self.visual, self.workspace.scenes)

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_clear_water_missing_large_ship_is_review_lead_and_all_ships_are_listed(self):
        self.ais['vessels'].append(vessel('987654321', lon=-6.13, length_m={'value': 12}))
        result = self.compare()
        self.assertEqual([v['status'] for v in result['vessel_checks']],
                         ['ais_not_detected', 'size_unknown_or_below_limit'])
        self.assertEqual(len(result['leads']), 1)
        self.assertFalse(result['leads'][0]['identity_confirmed'])
        self.assertEqual(result['leads'][0]['acquired_utc'], WHEN)

    def test_cloud_shadow_land_and_missing_quality_suppress_negative_leads(self):
        import hashlib
        from io import BytesIO
        from PIL import Image
        for scl in [0, 3, 4, 8, 9, 10, 11]:
            raw = BytesIO()
            Image.new('L', (64, 64), scl).save(raw, 'PNG')
            (self.workspace.scenes/(self.scene['id']+'.quality.png')).write_bytes(raw.getvalue())
            self.scene['quality_sha256'] = hashlib.sha256(raw.getvalue()).hexdigest()
            self.assertEqual(self.compare()['leads'], [], scl)
        self.scene['quality_sha256'] = 'invalid-hash'
        self.assertEqual(self.compare()['vessel_checks'][0]['status'], 'quality_unavailable')
        self.assertEqual(self.compare()['leads'], [])

    def test_missing_time_unverified_ai_and_saturated_output_cannot_claim_absence(self):
        self.visual['image_input_verified'] = False
        self.assertEqual(self.compare()['vessel_checks'][0]['status'], 'image_not_analysed')
        self.visual.update(image_input_verified=True, contact_limit_reached=True)
        self.assertEqual(self.compare()['vessel_checks'][0]['status'], 'contact_limit_reached')
        self.assertEqual(self.compare()['leads'], [])
        self.ais['acquired_utc'] = '2026-10-14T12:00:00Z'
        self.assertIn('differs', self.compare()['not_checked'])

    def test_unusable_image_is_abstention_and_cannot_supply_either_mismatch_lead(self):
        self.visual.update(image_status='unusable', analysis_incomplete=True)
        result = self.compare([{'id': 'AI-1', 'lat': 53.36, 'lon': -6.12}])
        self.assertEqual(result['leads'], [])
        self.assertEqual(result['contact_checks'][0]['status'], 'image_unusable')

    def test_nearby_or_ambiguous_contacts_never_create_false_absence(self):
        point = {'id': 'AI-1', 'lat': 53.33, 'lon': -6.12, 'matched_mmsi': None}
        result = self.compare([point])
        self.assertEqual(result['leads'], [])  # Assignment conflict is not a dark ship.
        self.assertEqual(result['vessel_checks'][0]['status'], 'nearby_image_contact_review')
        point.update(matched_mmsi='123456789', ambiguous=True)
        self.assertEqual(self.compare([point])['vessel_checks'][0]['status'], 'ambiguous_match')

    def test_no_ais_does_not_create_dark_vessel_claim(self):
        self.ais['vessels'] = []
        self.assertEqual(self.compare([{'id': 'AI-1', 'lat': 53.33, 'lon': -6.12}])['leads'], [])

    def test_temporal_uncertainty_withholds_both_mismatch_directions_without_widening_identity_gate(self):
        from argus.space import timestamp
        from argus.tracking import temporal_support
        from argus.satellite_ais import associate
        ship = self.ais['vessels'][0]
        ship['track'] = [{'ts': '2026-10-13T11:55:00Z', 'lat': 53.33, 'lon': -6.12,
                          'sog_kn': 0, 'cog_deg': 0}]
        ship['position_evidence']['temporal_support'] = temporal_support(ship['track'], timestamp(WHEN), ship['position'])
        point = {'id': 'AI-1', 'lat': 53.36, 'lon': -6.12}
        contacts = associate([point], self.ais)
        self.assertIsNone(contacts[0]['matched_mmsi'])
        self.assertEqual(contacts[0]['candidates'][0]['assessment'], 'reachable_time_uncertain')
        result = self.compare(contacts)
        self.assertEqual(result['leads'], [])
        self.assertEqual(result['vessel_checks'][0]['status'], 'ais_position_uncertain')
        self.assertEqual(result['contact_checks'][0]['status'], 'ais_position_uncertain')

    def test_excluded_ais_and_duplicate_ai_do_not_manufacture_dark_contacts(self):
        point = {'id': 'AI-1', 'lat': 53.33, 'lon': -6.15}
        self.ais['coverage']['excluded_vessels'] = [{'mmsi': '987654321', 'reason': 'conflicting_positions_at_same_time'}]
        result = self.compare([point])
        self.assertFalse(any(lead['kind'] == 'image_without_ais' for lead in result['leads']))
        self.assertEqual(result['contact_checks'][0]['status'], 'ais_history_conflict')
        self.ais['coverage'].pop('excluded_vessels')
        point['overlap_ambiguous'] = True
        result = self.compare([point])
        self.assertFalse(any(lead['kind'] == 'image_without_ais' for lead in result['leads']))
        self.assertEqual(result['contact_checks'][0]['status'], 'duplicate_or_overlapping_observation')

    def test_unsafe_motion_moored_missing_size_edges_and_synthetic_do_not_raise(self):
        cases = []
        bad = vessel()
        bad['position_evidence']['kinematic_consistency'] = 'exceeds_assumed_limit'
        cases.append(bad)
        cases.append(vessel(nav_status={'value': 5}))
        cases.append(vessel(length_m={'value': None}))
        cases.append(vessel(lon=self.scene['bbox'][0]))
        for entry in cases:
            self.ais['vessels'] = [entry]
            self.assertEqual(self.compare()['leads'], [])
        self.scene['label'] = 'simulated'
        self.assertIn('Synthetic', self.compare()['not_checked'])

    @unittest.skipUnless(RASTERS_AVAILABLE, 'Optional satellite raster readers not installed')
    def test_review_backlog_is_free_persisted_and_skips_already_checked_images(self):
        review = {'scene': self.scene, 'ais': self.ais, 'contacts': [], 'visual': self.visual}
        path = self.workspace.root/'reviews'/(self.scene['id']+'.json')
        atomic_json(path, review)
        with patch.object(self.workspace, 'ais_for_scene', return_value=self.ais) as history, \
                patch('argus.satellite_workspace.visual_analysis') as paid:
            self.workspace.reconcile_reviews()
            self.workspace.reconcile_reviews()
            history.assert_called_once()
            paid.assert_not_called()
        self.assertIn('comparison_checked_utc', json.loads(path.read_text()))
        index = self.workspace.comparison_index()
        self.assertEqual(index['reviews_checked'], 1)
        self.assertEqual(index['reviews_pending'], 0)
        self.assertEqual(len(index['vessel_checks']), 1)
        self.assertEqual(len(index['leads']), 1)
