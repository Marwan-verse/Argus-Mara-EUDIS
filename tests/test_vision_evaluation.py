"""Evaluation distinguishes pipeline misses, extra detections and missing labels."""
import tempfile
from pathlib import Path
import unittest

from argus.satellite import atomic_json
from argus.vision_evaluation import evaluate_contacts, evaluate_manifest
from test_satellite import fixture


class VisionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace, self.scene, _ = fixture(Path(self.temp.name)/'satellite')

    def manifest(self, truth, **updates):
        return {'version': 'vision-evaluation-v1', 'cases': [{
            'scene_id': self.scene['id'], 'image_sha256': self.scene['image_sha256'],
            'reviewed': True, 'reviewer': 'Synthetic test author', 'reference_source': 'human',
            'all_visible_contacts_labeled': True, 'truth': truth, **updates}]}

    def predictions(self, contacts, **updates):
        atomic_json(self.workspace.root/'reviews'/(self.scene['id']+'.json'), {
            'scene': self.scene, 'visual': {'image_input_verified': True, 'contacts': contacts, **updates}})

    def test_duplicates_are_false_positives_and_misses_are_not_hidden(self):
        point = {'x': .5, 'y': .5}
        result = evaluate_contacts(self.scene, [point, {'x': .9, 'y': .9}], [point, point])
        self.assertEqual((result['true_positives'], result['false_positives'], result['false_negatives']), (1, 1, 1))
        self.assertEqual(result['precision'], .5)
        self.assertEqual(result['recall'], .5)
        self.assertEqual(result['excess_predictions_near_reference'], 1)

    def test_global_assignment_avoids_a_greedy_missed_detection(self):
        result = evaluate_contacts(self.scene, [{'x': .4, 'y': .5}, {'x': .6, 'y': .5}],
                                   [{'x': .49, 'y': .5}, {'x': .3, 'y': .5}], tolerance_m=800)
        self.assertEqual(result['true_positives'], 2)

    def test_unverified_and_partial_outputs_remain_pipeline_misses(self):
        point = {'x': .5, 'y': .5}
        self.predictions([point], image_input_verified=False)
        result = evaluate_manifest(self.workspace, self.manifest([point]))
        self.assertEqual(result['abstained_images'], 1)
        self.assertEqual(result['pipeline_recall'], 0)
        self.assertIsNone(result['verified_model_recall'])
        self.predictions([], analysis_incomplete=True)
        result = evaluate_manifest(self.workspace, self.manifest([point]))
        self.assertEqual(result['cases'][0]['prediction_state'], 'partial')
        self.assertEqual(result['false_negatives'], 1)

    def test_unreviewed_or_changed_reference_cannot_produce_accuracy_claim(self):
        result = evaluate_manifest(self.workspace, self.manifest(None, reviewed=False))
        self.assertEqual(result['evaluated_images'], 0)
        self.assertIsNone(result['pipeline_recall'])
        result = evaluate_manifest(self.workspace, self.manifest([], image_sha256='changed'))
        self.assertEqual(result['skipped_images'][0]['reason'], 'reference_image_changed')
        with self.assertRaisesRegex(ValueError, 'human reviewer'):
            evaluate_manifest(self.workspace, self.manifest([], reviewer=None))

    def test_empty_reference_has_no_invented_perfect_recall_and_duplicate_scenes_are_rejected(self):
        result = evaluate_contacts(self.scene, [], [])
        self.assertIsNone(result['recall'])
        self.assertTrue(result['empty_scene_correct'])
        manifest = self.manifest([])
        manifest['cases'] *= 2
        with self.assertRaisesRegex(ValueError, 'only once'):
            evaluate_manifest(self.workspace, manifest)
