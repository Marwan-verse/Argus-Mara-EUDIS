"""Analyst outcomes never overwrite evidence, confirm identity, or survive changed evidence silently."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from argus.satellite import atomic_json
from argus.satellite_workspace import SatelliteWorkspace
from test_satellite import fixture


def lead_fixture(root):
    if (Path(root)/'scenes'/('a'*24+'.json')).exists():
        workspace = SatelliteWorkspace(root)
        scene = workspace.scene('a'*24)
    else:
        workspace, scene, _ = fixture(root)
    lead = {'id': scene['id']+':ais:111111111', 'scene_id':scene['id'], 'mmsi':'111111111',
            'name':'Synthetic test vessel', 'title':'AIS vessel not detected', 'reason':'Test evidence only.',
            'acquired_utc':scene['acquired_utc'], 'source_label':'real', 'review_status':'unreviewed'}
    review = {'scene':scene, 'visual':{'image_input_verified':True}, 'contacts':[], 'ais':{'vessels':[]},
              'comparison':{'version':'image-ais-review-v2', 'leads':[lead]}}
    atomic_json(workspace.root/'reviews'/(scene['id']+'.json'), review)
    return workspace, review


def payload(lead, **changes):
    return {'event_id':str(uuid4()), 'lead_id':lead['id'], 'evidence_key':lead['evidence_key'],
            'outcome':'reviewed_no_concern', 'reason':'Synthetic analyst reason for this test.', **changes}


class DispositionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace, self.review=lead_fixture(Path(self.temp.name)/'satellite')
        self.lead=self.workspace.comparison_index()['leads'][0]

    def tearDown(self):
        self.temp.cleanup()

    def test_saved_outcome_survives_restart_without_rewriting_detector_result(self):
        path=self.workspace.root/'reviews'/(self.review['scene']['id']+'.json')
        before=path.read_bytes()
        saved=self.workspace.save_disposition(payload(self.lead),'Analyst 42')
        self.assertFalse(saved['event']['operational_approval'])
        self.assertFalse(saved['event']['identity_confirmed'])
        self.assertEqual(saved['event']['lead_snapshot']['mmsi'], '111111111')
        self.assertEqual(before,path.read_bytes())
        lead=SatelliteWorkspace(self.workspace.root).comparison_index()['leads'][0]
        self.assertEqual(lead['review_status'],'reviewed_no_concern')
        self.assertEqual(lead['analyst_review']['actor'],'Analyst 42')

    def test_changed_evidence_reopens_and_stale_form_is_refused(self):
        self.workspace.save_disposition(payload(self.lead),'Analyst')
        self.review['scene']['image_sha256']='b'*64
        atomic_json(self.workspace.root/'reviews'/(self.review['scene']['id']+'.json'),self.review)
        current=self.workspace.comparison_index()['leads'][0]
        self.assertTrue(current['evidence_changed'])
        self.assertEqual(current['review_status'],'unreviewed')
        self.assertEqual(current['review_event_count'],1)
        with self.assertRaisesRegex(ValueError,'Evidence changed'):
            self.workspace.save_disposition(payload(self.lead),'Analyst')

    def test_exact_manual_retry_is_idempotent_and_conflicting_retry_is_refused(self):
        draft=payload(self.lead)
        first=self.workspace.save_disposition(draft,'Analyst')['event']
        second=self.workspace.save_disposition(draft,'Analyst')['event']
        self.assertEqual(first,second)
        with self.assertRaisesRegex(ValueError,'different review'):
            self.workspace.save_disposition({**draft,'reason':'Changed analyst reason.'},'Analyst')
        self.assertEqual(len(self.workspace.dispositions.events(self.lead['id'])),1)

    def test_concurrent_retries_publish_one_whole_immutable_event(self):
        draft=payload(self.lead)
        with ThreadPoolExecutor(max_workers=4) as executor:
            rows=list(executor.map(lambda _:self.workspace.save_disposition(draft,'Analyst')['event'],range(8)))
        self.assertTrue(all(r==rows[0] for r in rows))
        self.assertEqual(len(self.workspace.dispositions.events(self.lead['id'])),1)

    def test_malformed_or_forged_fields_and_missing_leads_are_rejected(self):
        for change in ({'actor':'forged'}, {'reason':'short'}, {'event_id':'../escape'},
                       {'outcome':'confirmed_hostile'}, {'lead_id':'../../escape'}):
            with self.assertRaises(ValueError):
                self.workspace.save_disposition(payload(self.lead,**change),'Analyst')
        with self.assertRaisesRegex(ValueError,'no longer present'):
            self.workspace.save_disposition(payload(self.lead,lead_id=self.review['scene']['id']+':ais:222222222'),'Analyst')

    def test_corrupt_audit_remains_visible_and_unreviewed(self):
        self.workspace.save_disposition(payload(self.lead),'Analyst')
        path=next(self.workspace.dispositions.folder(self.lead['id']).glob('*.json'))
        path.write_text('not json')
        row=self.workspace.comparison_index()['leads'][0]
        self.assertEqual(row['review_status'],'unreviewed')
        self.assertIn('cannot be read',row['review_error'])
        path.write_text(json.dumps({'lead_id':self.lead['id']}))
        row=self.workspace.comparison_index()['leads'][0]
        self.assertEqual(row['review_status'],'unreviewed')
        self.assertIn('cannot be read',row['review_error'])

    def test_latest_position_refresh_does_not_reopen_image_time_review(self):
        self.workspace.save_disposition(payload(self.lead),'Analyst')
        self.review['comparison_checked_utc']='2099-01-01T00:00:00Z'
        self.review['latest_positions']={'irrelevant':True}
        atomic_json(self.workspace.root/'reviews'/(self.review['scene']['id']+'.json'),self.review)
        row=self.workspace.comparison_index()['leads'][0]
        self.assertFalse(row['evidence_changed'])
        self.assertEqual(row['review_status'],'reviewed_no_concern')
