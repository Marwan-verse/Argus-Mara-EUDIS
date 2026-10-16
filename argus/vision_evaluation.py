"""Offline evaluation against independently supplied visible-contact labels.

No model calls, inferred reference labels or identity/intent claims. Matching
maximizes gated one-to-one detections before minimizing localization distance.
"""
import math
from statistics import median

from argus.satellite import pixel_location
from argus.space import assignment, distance_km


def evaluate_contacts(scene, truth, predictions, tolerance_m=100):
    if not isinstance(tolerance_m, (int, float)) or isinstance(tolerance_m, bool) or not math.isfinite(tolerance_m) or not 0 < tolerance_m <= 1000:
        raise ValueError('Choose a finite localization tolerance of 0–1000 m, excluding zero')
    if not isinstance(truth, list) or not isinstance(predictions, list) or max(len(truth), len(predictions)) > 1000:
        raise ValueError('Evaluation accepts at most 1,000 reference and predicted contacts per image')
    def locate(points):
        try:
            return [pixel_location(scene, point['x'], point['y']) for point in points]
        except (KeyError, TypeError):
            raise ValueError('Every contact needs fractional image x/y coordinates') from None
    reference, observed = locate(truth), locate(predictions)
    distances = [[distance_km(point, target)*1000 for target in reference] for point in observed]
    penalty = len(observed)+1
    costs = [[distance/tolerance_m if distance <= tolerance_m else penalty*3 for distance in row]
             + [penalty]*len(observed) for row in distances]
    matches, false_positives = [], []
    for index, col in enumerate(assignment(costs)):
        if col < len(reference) and distances[index][col] <= tolerance_m:
            matches.append({'prediction_index': index, 'reference_index': col,
                            'distance_m': distances[index][col]})
        else:
            false_positives.append(index)
    matched = {m['reference_index'] for m in matches}
    missed = [index for index in range(len(reference)) if index not in matched]
    excess = sum(any(d <= tolerance_m for d in distances[i]) for i in false_positives)
    errors = [m['distance_m'] for m in matches]
    return {'true_positives': len(matches), 'false_positives': len(false_positives),
            'false_negatives': len(missed), 'matches': matches,
            'false_positive_indices': false_positives, 'missed_reference_indices': missed,
            'excess_predictions_near_reference': excess,
            'precision': len(matches)/len(predictions) if predictions else None,
            'recall': len(matches)/len(reference) if reference else None,
            'median_localization_m': median(errors) if errors else None,
            'empty_scene_correct': not truth and not predictions,
            'tolerance_m': tolerance_m}


def evaluate_manifest(workspace, manifest, tolerance_m=100):
    if manifest.get('version') != 'vision-evaluation-v1' or not isinstance(manifest.get('cases'), list):
        raise ValueError('Invalid vision evaluation manifest')
    if len(manifest['cases']) > 1000:
        raise ValueError('Use at most 1,000 images per evaluation')
    cases, skipped, seen = [], [], set()
    for case in manifest['cases']:
        identifier = case['scene_id']
        if identifier in seen:
            raise ValueError('An evaluation scene may appear only once')
        seen.add(identifier)
        if case.get('reviewed') is not True:
            skipped.append({'scene_id': identifier, 'reason': 'reference_not_reviewed'})
            continue
        if (not isinstance(case.get('reviewer'), str) or not case['reviewer'].strip() or
                case.get('reference_source') != 'human' or case.get('all_visible_contacts_labeled') is not True):
            raise ValueError('Reviewed references require a human reviewer and complete visible-contact labels')
        scene = workspace.scene(identifier)
        # Actual input bytes must still match both the scene and the annotation.
        workspace.image(identifier)
        if case.get('image_sha256') != scene['image_sha256']:
            skipped.append({'scene_id': identifier, 'reason': 'reference_image_changed'})
            continue
        import json
        path = workspace.root/'reviews'/(identifier+'.json')
        review = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if review.get('scene', {}).get('image_sha256') != scene['image_sha256']:
            visual, state = {}, 'missing_or_changed_prediction_image'
        else:
            visual = review.get('visual') or {}
            state = 'unverified' if visual.get('image_input_verified') is not True else 'partial' if visual.get('analysis_incomplete') else 'capped' if visual.get('contact_limit_reached') else 'complete'
        verified = visual.get('image_input_verified') is True
        # Withheld output counts as pipeline misses, rather than quietly dropping
        # difficult images and inflating recall. Model-only scoring is separate.
        result = evaluate_contacts(scene, case.get('truth'), visual.get('contacts', []) if verified else [], tolerance_m)
        cases.append({'scene_id': identifier, 'sensor': scene['sensor'], 'label': scene['label'],
                      'model': visual.get('model'), 'cache_id': visual.get('cache_id'),
                      'prediction_state': state, 'abstained': not verified, **result})
    tp = sum(c['true_positives'] for c in cases)
    fp = sum(c['false_positives'] for c in cases)
    fn = sum(c['false_negatives'] for c in cases)
    verified = [c for c in cases if not c['abstained']]
    model_tp = sum(c['true_positives'] for c in verified)
    model_fn = sum(c['false_negatives'] for c in verified)
    return {'version': 'vision-evaluation-v1', 'reference_source': 'human labels asserted by the supplied manifest',
            'evaluated_images': len(cases), 'skipped_images': skipped,
            'abstained_images': sum(c['abstained'] for c in cases),
            'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
            'precision': tp/(tp+fp) if tp+fp else None,
            'pipeline_recall': tp/(tp+fn) if tp+fn else None,
            'verified_model_recall': model_tp/(model_tp+model_fn) if model_tp+model_fn else None,
            'cases': cases,
            'caveat': 'Metrics measure localization of labeled visible contacts only. Label quality, representativeness, hidden vessels and AIS identity require separate validation.'}
