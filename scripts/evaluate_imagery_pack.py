"""Selected-object recovery check on clean, hash-verified imagery-pack crops.

Default: prepare/score only. --analyse explicitly runs up to ten existing bounded
vision requests, using the shared pilot ledger. Failure stops further paid work.
The pack's manual selections are assumptions, not exhaustive independent labels.
"""
import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import warnings

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from argus.satellite import atomic_json
from argus.satellite_ai import visual_analysis
from argus.satellite_workspace import DEFAULT_QUESTION


def prepare(pack, output, repository=ROOT):
    sources = {source['id']: source for source in pack['sources']}
    cases = []
    for vessel in pack['vessels']:
        source = sources[vessel['source_id']]
        path = (repository/source['raw_path']).resolve()
        if not path.is_relative_to((repository/'data').resolve()):
            raise ValueError('Raw imagery must stay inside the private data folder')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['raw_sha256']:
            raise ValueError('Source imagery hash changed; do not score altered presentation figures')
        box = vessel['crop_bounds_px']
        target = vessel['vessel_bounds_px']
        if not (box[0] <= target[0] < target[2] <= box[2] and box[1] <= target[1] < target[3] <= box[3]):
            raise ValueError('Selected object bounds must lie inside the clean source crop')
        # These are exact source-pixel crops, with no outline, caption, resampling
        # or simulated overlays. Expected large source sizes are hash-verified.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if list(image.size) != source['source_size_px']:
                    raise ValueError('Source raster dimensions changed')
                if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                    raise ValueError('Source crop is outside the raster')
                crop = image.crop(box).convert('RGB')
        raw = BytesIO()
        crop.save(raw, 'PNG')
        pixels = raw.getvalue()
        image_hash = hashlib.sha256(pixels).hexdigest()
        identifier = hashlib.sha256((source['raw_sha256']+str(box)).encode()).hexdigest()[:24]
        scene = {'id': identifier, 'image_sha256': image_hash, 'width': crop.width, 'height': crop.height,
                 'sensor': source['sensor'], 'coordinate_space': 'source_pixels',
                 'acquired_utc': None, 'label': 'real'}
        output.mkdir(parents=True, exist_ok=True)
        (output/(identifier+'.png')).write_bytes(pixels)
        cases.append({'scene': scene, 'source_id': source['id'], 'source_sha256': source['raw_sha256'],
                      'source_url': source['source_url'], 'credit': source['credit'],
                      'license': source['license'], 'license_url': source['license_url'],
                      'source_acquired_date': source.get('acquired_date'),
                      'selection_label': 'assumption', 'all_visible_contacts_labeled': False,
                      'target': {'x': ((target[0]+target[2])/2-box[0])/crop.width,
                                 'y': ((target[1]+target[3])/2-box[1])/crop.height}})
    atomic_json(output/'dataset.json', {'version': 'imagery-selected-recovery-v1', 'cases': cases,
                'caveat': 'Partial manually selected vessel-shaped objects; not exhaustive ship labels. No geographic coordinates, AIS association or threat labels.'})
    return cases


def score(cases, output, tolerance_px=5):
    if not math.isfinite(tolerance_px) or not 0 < tolerance_px <= 30:
        raise ValueError('Use a positive source-pixel tolerance no greater than 30')
    rows = []
    for case in cases:
        scene = case['scene']
        path = output/(scene['id']+'.result.json')
        record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if record and record.get('image_sha256') != scene['image_sha256']:
            raise ValueError('Saved predictions do not belong to these exact source pixels')
        visual = record.get('visual') or {}
        verified = visual.get('image_input_verified') is True
        distances = [math.hypot((p['x']-case['target']['x'])*scene['width'],
                                 (p['y']-case['target']['y'])*scene['height'])
                     for p in visual.get('contacts', [])] if verified else []
        error = min(distances) if distances else None
        recovered = error is not None and error <= tolerance_px
        rows.append({'scene_id': scene['id'], 'source_id': case['source_id'],
                     'attempted': bool(record), 'verified': verified, 'model': visual.get('model'),
                     'cache_id': visual.get('cache_id'), 'target_recovered': recovered,
                     'nearest_target_error_px': error,
                     'extra_contacts_unreviewed': max(0, len(distances)-int(recovered)),
                     'error': record.get('error')})
    attempted, verified = sum(r['attempted'] for r in rows), sum(r['verified'] for r in rows)
    recovered = sum(r['target_recovered'] for r in rows)
    return {'version': 'imagery-selected-recovery-v1', 'selected_objects': len(cases),
            'attempted_cases': attempted, 'pending_cases': len(cases)-attempted,
            'verified_cases': verified, 'selected_objects_recovered': recovered,
            'pipeline_selected_recovery': recovered/attempted if attempted else None,
            'verified_selected_recovery': recovered/verified if verified else None,
            'tolerance_source_px': tolerance_px, 'cases': rows,
            'not_established': ['full-image precision', 'full-image recall', 'vessel identity', 'AIS silence', 'threat detection accuracy'],
            'caveat': 'Exploratory recovery of partial manual selections. No display annotations were sent. Selection and dataset bias prevent general accuracy claims.'}


def local_baseline(cases, output, tolerance_px=5):
    """Unmasked existing optical features: location recovery, not vessel accuracy."""
    import numpy as np
    from argus.satellite_screen import compact_features
    rows = []
    for case in cases:
        scene = case['scene']
        features = compact_features((output/(scene['id']+'.png')).read_bytes(),
                                    np.ones((scene['height'], scene['width']), dtype=bool))
        distances = [math.hypot((p['x']-case['target']['x'])*scene['width'],
                                (p['y']-case['target']['y'])*scene['height']) for p in features['candidates']]
        error = min(distances) if distances else None
        rows.append({'scene_id': scene['id'], 'candidate_count': features['candidate_count'],
                     'nearest_target_error_px': error, 'clutter': features['clutter'],
                     'target_recovered': error is not None and error <= tolerance_px})
    return {'method': 'existing_compact_optical_features', 'selected_objects': len(cases),
            'selected_objects_recovered': sum(r['target_recovered'] for r in rows), 'cases': rows,
            'caveat': 'All pixels eligible for this exploratory baseline. Land, wakes, glint and structures are NOT classified; extra features are unreviewed, not known false positives.'}


def anchored_baseline(cases, output, tolerance_px=5):
    """Replay cached hints against independent pixels without another model call."""
    import numpy as np
    from argus.optical_localization import anchor_observations
    from argus.satellite_screen import compact_features
    rows = []
    for case in cases:
        scene = case['scene']
        path = output/(scene['id']+'.result.json')
        record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if record and record.get('image_sha256') != scene['image_sha256']:
            raise ValueError('Saved predictions do not belong to these exact source pixels')
        visual = record.get('visual') or {}
        features = compact_features((output/(scene['id']+'.png')).read_bytes(),
                                    np.ones((scene['height'], scene['width']), dtype=bool))
        localized = anchor_observations(scene, visual.get('contacts', []) if
            visual.get('image_input_verified') is True else [], features, water_verified=False)
        distances = [math.hypot((p['x']-case['target']['x'])*scene['width'],
                                (p['y']-case['target']['y'])*scene['height'])
                     for p in localized['contacts'] if p['localization']['status'] == 'anchored']
        error = min(distances) if distances else None
        rows.append({'scene_id': scene['id'], 'status_counts': localized['status_counts'],
                     'nearest_target_error_px': error,
                     'target_recovered': error is not None and error <= tolerance_px})
    return {'method': 'cached_model_unique_compact_feature_anchors', 'selected_objects': len(cases),
            'selected_objects_recovered': sum(r['target_recovered'] for r in rows), 'cases': rows,
            'water_mask_verified': False,
            'caveat': 'Exploratory cached-output replay; source images lack water masks. These anchors are ineligible for operational AIS identity/absence claims. No precision/recall established.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/validation/imagery-pack')
    parser.add_argument('--analyse', action='store_true')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--tolerance-px', type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error('Use a limit of 1–10 images')
    pack = json.loads((ROOT/'demo/imagery/manifest.json').read_text(encoding='utf-8'))
    cases = prepare(pack, args.output)
    if args.analyse:
        for case in cases[:args.limit]:
            scene = case['scene']
            path = args.output/(scene['id']+'.result.json')
            if path.exists():
                # A stored failure is held too: never auto-repeat uncertain paid work.
                continue
            try:
                visual = visual_analysis(ROOT/'data/satellite/ai', scene,
                    (args.output/(scene['id']+'.png')).read_bytes(), DEFAULT_QUESTION)
                atomic_json(path, {'image_sha256': scene['image_sha256'], 'visual': visual})
                print('Saved bounded review', scene['id'], flush=True)
            except (ValueError, OSError) as error:
                atomic_json(path, {'image_sha256': scene['image_sha256'], 'error': str(error)[:300]})
                print('Stopped after failed review; no automatic retry:', str(error)[:200], flush=True)
                break
    report = score(cases, args.output, args.tolerance_px)
    report['local_feature_baseline'] = local_baseline(cases, args.output, args.tolerance_px)
    report['anchored_baseline'] = anchored_baseline(cases, args.output, args.tolerance_px)
    atomic_json(args.output/'report.json', report)
    print(json.dumps({key: report[key] for key in ('selected_objects', 'attempted_cases', 'verified_cases',
                     'selected_objects_recovered', 'pipeline_selected_recovery', 'not_established')}))


if __name__ == '__main__':
    main()
