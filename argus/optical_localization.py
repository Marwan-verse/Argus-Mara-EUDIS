"""Independent pixel support for approximate optical model positions.

Compact water features are observations, not confirmed ships. AI hints may be
anchored only to a unique, uncontested feature. Original positions stay recorded.
"""
from collections import Counter
import math

from argus.satellite import pixel_location

VERSION = 'compact-water-anchors-v1'
SEARCH_RADIUS_PX = 32


def position_eligible(point):
    quality = point.get('localization')
    if not quality:  # Older/non-optical evidence retains its existing gates.
        return True
    return (isinstance(quality, dict) and quality.get('status') == 'anchored'
            and quality.get('water_mask_verified') is True)


def pixel_feature(point):
    """An unclassified bright spot (OPT-n) kept for review, not an AI observation of a vessel."""
    quality = point.get('localization')
    return (str(point.get('id', '')).startswith('OPT-')
            or isinstance(quality, dict) and quality.get('status') == 'feature_only')


def anchor_observations(scene, points, features, *, water_verified=False):
    width, height = scene['width'], scene['height']
    candidates = features.get('candidates', [])
    def locate(point):
        if scene.get('coordinate_space') == 'source_pixels':
            return {'coordinate_space': 'source_pixels'}
        return pixel_location(scene, point['x'], point['y'])
    possible = [[i for i, feature in enumerate(candidates)
                 if math.hypot((point['x']-feature['x'])*width,
                               (point['y']-feature['y'])*height) <= SEARCH_RADIUS_PX]
                for point in points]
    # Even an ambiguous hint contests a feature: do not arbitrarily choose a
    # different hint and present its location as independently corroborated.
    contested = Counter(i for options in possible for i in options)
    output, used = [], set()
    for point, options in zip(points, possible):
        status = ('clutter' if features.get('clutter') else 'unsupported' if not options else
                  'ambiguous' if len(options) != 1 else 'contested' if contested[options[0]] != 1 else 'anchored')
        quality = {'version': VERSION, 'status': status, 'search_radius_px': SEARCH_RADIUS_PX,
                   'water_mask_verified': water_verified, 'label': 'assumption',
                   'model_position': {k: point[k] for k in ('x', 'y', 'lat', 'lon') if k in point},
                   'caveat': 'Compact bright pixels can be wakes, glint or other objects. Pixel support does not confirm vessel identity.'}
        item = {**point, 'localization': quality}
        if status == 'anchored':
            index = options[0]
            feature = candidates[index]
            used.add(index)
            quality.update(feature_bounds_px=feature['bounds_px'], feature_pixel_count=feature['pixel_count'],
                           model_offset_px=math.hypot((point['x']-feature['x'])*width,
                                                     (point['y']-feature['y'])*height))
            item.update(x=feature['x'], y=feature['y'], source='tensorx_ai_pixel_supported', **locate(feature))
        output.append(item)
    # Preserve independent features the model missed or could not localize.
    # These remain review-only and cannot consume an AIS identity or raise a
    # dark-contact lead. They still veto an unsupported claim of image absence.
    for index, feature in enumerate(candidates):
        if index in used:
            continue
        output.append({**feature, **locate(feature), 'id': f'OPT-{index+1}',
                       'confidence': 'low', 'ts': scene.get('acquired_utc'),
                       'description': 'Unclassified compact optical feature; model/analyst vessel confirmation unavailable.',
                       'localization': {'version': VERSION, 'status': 'feature_only',
                                        'water_mask_verified': water_verified, 'label': 'assumption',
                                        'feature_bounds_px': feature['bounds_px']}})
    return {'version': VERSION, 'water_mask_verified': water_verified,
            'search_radius_px': SEARCH_RADIUS_PX, 'feature_count': len(candidates),
            'status_counts': dict(Counter(p['localization']['status'] for p in output)), 'contacts': output}


def localize_optical(scene, image, folder, points):
    from argus.satellite_screen import screen
    if scene.get('sensor') != 'Sentinel-2':
        return {'version': VERSION, 'contacts': list(points), 'status': 'not_optical'}
    if not scene.get('quality_sha256'):
        return {'version': VERSION, 'contacts': [{**point, 'localization': {
            'version': VERSION, 'status': 'quality_unavailable', 'water_mask_verified': False,
            'label': 'assumption'}} for point in points], 'status': 'quality_unavailable'}
    features = screen(scene, image, folder)
    return anchor_observations(scene, points, features, water_verified=True)
