"""Presentation annotations cannot leak into the exploratory imagery check."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from argus.satellite import atomic_json
from scripts.evaluate_imagery_pack import prepare, score


class ImageryEvaluationTests(unittest.TestCase):
    def test_clean_crop_preserves_source_pixels_without_fake_geography_or_exhaustive_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'data/source.png'
            source.parent.mkdir()
            image = Image.new('RGB', (20, 20), '#173050')
            image.putpixel((8, 8), (255, 255, 255))
            image.save(source)
            pack = {'sources': [{'id': 'test', 'raw_path': 'data/source.png',
                'raw_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'source_size_px': [20, 20], 'sensor': 'synthetic test', 'source_url': 'https://example.invalid',
                'credit': 'Synthetic fixture', 'license': 'test', 'license_url': 'https://example.invalid'}],
                'vessels': [{'source_id': 'test', 'crop_bounds_px': [5, 5, 15, 15],
                             'vessel_bounds_px': [7, 7, 9, 9]}]}
            output = root/'data/evaluation'
            cases = prepare(pack, output, repository=root)
            scene = cases[0]['scene']
            with Image.open(output/(scene['id']+'.png')) as crop:
                self.assertEqual(crop.tobytes(), image.crop((5, 5, 15, 15)).tobytes())
            self.assertIsNone(scene['acquired_utc'])
            self.assertNotIn('mercator_bounds', scene)
            self.assertFalse(cases[0]['all_visible_contacts_labeled'])
            self.assertIsNone(score(cases, output)['pipeline_selected_recovery'])
            atomic_json(output/(scene['id']+'.result.json'), {'image_sha256': scene['image_sha256'],
                'visual': {'image_input_verified': True, 'contacts': [cases[0]['target'], {'x': 1, 'y': 1}]}})
            report = score(cases, output, tolerance_px=1)
            self.assertEqual(report['selected_objects_recovered'], 1)
            self.assertEqual(report['cases'][0]['extra_contacts_unreviewed'], 1)
            self.assertIn('full-image precision', report['not_established'])
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                prepare(pack, output, repository=root)
