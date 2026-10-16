"""Satellite/radar leads carry AI confidence and a review priority for the alert list (D87)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from argus.satellite import atomic_json
from argus.satellite_disposition import evidence_key
from argus.satellite_workspace import SatelliteWorkspace, with_priority

SCENE = {'id': 'a'*24, 'acquired_utc': '2026-10-13T11:46:34Z', 'sensor': 'Sentinel-2', 'label': 'real'}


def image_lead(contact_id):
    return {'id': SCENE['id']+':image:'+contact_id, 'kind': 'image_without_ais', 'contact_id': contact_id,
            'name': contact_id, 'mmsi': None, 'lat': 53.3, 'lon': -6.0, 'acquired_utc': SCENE['acquired_utc'],
            'label': 'assumption', 'review_status': 'unreviewed'}


class LeadPriorityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.workspace = SatelliteWorkspace(Path(self.folder.name)/'satellite')
        missing = {'id': SCENE['id']+':ais:305696000', 'kind': 'ais_not_detected', 'mmsi': '305696000',
                   'name': 'MONTJOLY', 'lat': 53.254, 'lon': -5.994, 'acquired_utc': SCENE['acquired_utc'],
                   'label': 'assumption', 'review_status': 'unreviewed'}
        self.leads = [image_lead('AI-1'), image_lead('AI-2'), image_lead('AI-3'), image_lead('AI-9'), missing]
        self.review = {'scene': SCENE, 'visual': {'image_input_verified': True}, 'ais': {'vessels': []},
                       'contacts': [{'id': 'AI-1', 'confidence': 'low'}, {'id': 'AI-2', 'confidence': 'high'},
                                    {'id': 'AI-3', 'confidence': 'medium'}],
                       'comparison': {'leads': self.leads, 'vessel_checks': []}}
        atomic_json(self.workspace.root/'reviews'/(SCENE['id']+'.json'), self.review)

    def tearDown(self):
        self.folder.cleanup()

    def index(self, radar=()):
        with patch('argus.gfw_sar.radar_index', return_value=list(radar)), patch('argus.gfw_sar.summary', return_value={}):
            return {lead['id']: lead for lead in self.workspace.comparison_index()['leads']}

    def test_image_leads_take_the_ai_confidence_and_a_missing_ais_ship_is_high(self):
        leads = self.index()
        found = {lead['name']: (lead['confidence'], lead['priority']) for lead in leads.values()}
        self.assertEqual(found, {'AI-1': ('low', 'low'), 'AI-2': ('high', 'high'), 'AI-3': ('medium', 'medium'),
                                 'AI-9': (None, None), 'MONTJOLY': (None, 'high')})
        self.assertIn('clear water', leads[SCENE['id']+':ais:305696000']['priority_reason'])

    def test_adding_priority_keeps_recorded_analyst_outcomes_valid(self):
        for original in self.leads:
            row = self.index()[original['id']]
            self.assertEqual(row['evidence_key'], evidence_key(self.review, original))
            self.assertFalse(row['evidence_changed'])

    def test_radar_leads_are_medium(self):
        radar = {'id': 'gfw:abc', 'kind': 'radar_without_ais', 'radar': True, 'contact_id': None,
                 'acquired_utc': '2026-10-15T06:30:00Z', 'name': 'Radar contact abc'}
        lead = self.index([(radar, 'k'*64)])['gfw:abc']
        self.assertEqual((lead['confidence'], lead['priority']), (None, 'medium'))

    def test_unknown_kinds_are_shown_not_collapsed(self):
        self.assertIsNone(with_priority({'kind': 'something_new'}, {})['priority'])


if __name__ == '__main__':
    unittest.main()
