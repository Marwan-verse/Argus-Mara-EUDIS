"""Acquisition-time comparison of every eligible AIS vessel and image contact.

Results are review leads, never confirmed identity, silence or false positions.
Visibility is checked at each vessel, including a conservative footprint, rather
than inferred from the scene's average cloud percentage.
"""
import math

from argus.satellite import mercator
from argus.space import distance_km, timestamp

VERSION = 'image-ais-review-v6'
MIN_LENGTH_M = 50
VISIBILITY_RADIUS_M = 100
ALTERNATIVE_KM = 1
BUSY_WATER_NOTE = (' Pixel check unavailable: over 100 bright spots in this image (waves, glint or boats),'
                   ' so the AI position is not pixel-confirmed.')


def visibility(scene, position, mask, radius_m=VISIBILITY_RADIUS_M):
    if mask is None or not scene.get('mercator_bounds'):
        return 'quality_unavailable'
    left, bottom, right, top = scene['mercator_bounds']
    x, y = mercator(position['lon'], position['lat'])
    h, w = mask.shape
    col, row = (x-left)/(right-left)*w, (top-y)/(top-bottom)*h
    # Web Mercator distance is larger than ground distance by sec(latitude).
    scale = max(.1, math.cos(math.radians(position['lat'])))
    dx = radius_m/scale/(right-left)*w
    dy = radius_m/scale/(top-bottom)*h
    x0, x1 = math.floor(col-dx), math.ceil(col+dx)
    y0, y1 = math.floor(row-dy), math.ceil(row+dy)
    if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
        return 'edge_or_outside_image'
    return 'clear_water' if mask[y0:y1+1, x0:x1+1].all() else 'obscured_or_not_water'


def analysis_coverage(scene, position, visual):
    """A vessel's full footprint must avoid every unfinished detail-window core."""
    if visual.get('analysis_windows') is None:
        return region_coverage(scene, visual, [0, 0, 1, 1])
    if not scene.get('mercator_bounds'):
        return 'image_analysis_coverage_unavailable'
    left, bottom, right, top = scene['mercator_bounds']
    x, y = mercator(position['lon'], position['lat'])
    px, py = (x-left)/(right-left), (top-y)/(top-bottom)
    ground_scale = max(.1, math.cos(math.radians(position['lat'])))
    dx, dy = VISIBILITY_RADIUS_M/ground_scale/(right-left), VISIBILITY_RADIUS_M/ground_scale/(top-bottom)
    return region_coverage(scene, visual, [px-dx, py-dy, px+dx, py+dy])


def region_coverage(scene, visual, extent):
    """Coverage state for a normalized rectangle, including its outer edges."""
    windows = visual.get('analysis_windows')
    if windows is None:
        if visual.get('adaptive_version') or visual.get('analysis_incomplete'):
            return 'image_analysis_coverage_unavailable'
        return 'contact_limit_reached' if (visual.get('contact_limit_reached') or len(visual.get('contacts', [])) >= 24) else 'complete'
    from argus.satellite_adaptive import VERSION as ADAPTIVE_VERSION
    if visual.get('adaptive_version') != ADAPTIVE_VERSION or not isinstance(windows, list) or len(windows) != 4:
        return 'image_analysis_coverage_unavailable'
    mx, my = (scene['width']//2)/scene['width'], (scene['height']//2)/scene['height']
    expected = ([0, 0, mx, my], [mx, 0, 1, my], [0, my, mx, 1], [mx, my, 1, 1])
    if any(not isinstance(w, dict) or w.get('core') != core for w, core in zip(windows, expected)):
        return 'image_analysis_coverage_unavailable'
    x0, y0, x1, y1 = extent
    if x0 < 0 or x1 > 1 or y0 < 0 or y1 > 1:
        return 'edge_or_outside_image'
    for window in windows:
        a, b, c, d = window['core']
        if a <= x1 and c >= x0 and b <= y1 and d >= y0:
            if window.get('status') == 'capped':
                return 'detail_window_capped'
            if window.get('status') != 'complete' or window.get('image_input_verified') is not True:
                return 'detail_window_unreviewed'
    return 'complete'


def compare_review(scene, contacts, ais, visual, folder):
    """List all image-time vessels, with an explicit result for each unchecked case."""
    from argus.satellite_screen import water_mask
    from argus.tracking import within_temporal_support
    from argus.optical_localization import position_eligible
    checks, leads, contact_checks = [], [], []
    result = {'version': VERSION, 'acquired_utc': scene['acquired_utc'],
              'scene_id': scene['id'], 'vessel_checks': checks, 'contact_checks': contact_checks, 'leads': leads,
              'parameters': {'minimum_length_m': MIN_LENGTH_M, 'visibility_radius_m': VISIBILITY_RADIUS_M,
                             'alternative_radius_m': ALTERNATIVE_KM*1000},
              'caveat': 'Partial AIS reception and unvalidated optical detection. Not detected does not mean absent; clear SCL does not rule out glint, haze or rough sea. Human review required.'}
    if scene.get('label') not in {'real', 'reconstructed'}:
        result['not_checked'] = 'Synthetic imagery cannot establish findings about real AIS.'
        return result
    if not ais.get('acquired_utc') or timestamp(ais['acquired_utc']) != timestamp(scene['acquired_utc']):
        result['not_checked'] = 'AIS acquisition time is missing or differs from the image.'
        return result
    verified = bool(visual and visual.get('image_input_verified') is True)
    mask, quality_error = None, None
    if scene.get('quality_sha256'):
        try:
            mask, _ = water_mask(scene, folder)
        except (ValueError, OSError, ImportError):
            quality_error = 'Quality mask unavailable or failed verification; negative comparisons withheld.'
    result['quality_note'] = quality_error
    vessels = ais.get('vessels', [])
    for vessel in vessels:
        position = vessel['position']
        length = vessel.get('broadcast_fields', {}).get('length_m', {}).get('value')
        nav = vessel.get('broadcast_fields', {}).get('nav_status', {}).get('value')
        state = 'not_checked'
        matches = [c for c in contacts if c.get('matched_mmsi') == vessel['mmsi'] and position_eligible(c)]
        nearby = [c for c in contacts if distance_km(position, c) <= ALTERNATIVE_KM]
        visible = visibility(scene, position, mask)
        coverage = analysis_coverage(scene, position, visual) if verified else 'image_not_analysed'
        support = vessel.get('position_evidence', {}).get('temporal_support')
        if not verified:
            state = 'image_not_analysed'
        elif vessel.get('position_evidence', {}).get('kinematic_consistency') == 'exceeds_assumed_limit':
            state = 'inconsistent_ais_motion'
        elif matches:
            state = 'ambiguous_match' if any(c.get('ambiguous') for c in matches) else 'provisional_match'
        elif nearby:
            state = 'nearby_image_contact_review'
        elif support and support['center_radius_m'] > ALTERNATIVE_KM*1000:
            state = 'ais_position_uncertain'
        elif coverage != 'complete':
            state = coverage
        elif visible != 'clear_water':
            state = visible
        elif isinstance(length, bool) or not isinstance(length, (int, float)) or not math.isfinite(length) or length < MIN_LENGTH_M:
            state = 'size_unknown_or_below_limit'
        elif nav in (5, '5'):
            state = 'moored_not_checked'
        else:
            state = 'ais_not_detected'
        check = {'mmsi': vessel['mmsi'], 'name': vessel.get('name') or vessel['mmsi'],
                 'lat': position['lat'], 'lon': position['lon'], 'status': state,
                 'visibility': visible, 'ais_length_m': length,
                 'position_evidence': vessel.get('position_evidence'), 'identity_confirmed': False,
                 'image_contact_ids': [c['id'] for c in nearby]}
        checks.append(check)
        if state == 'ais_not_detected':
            leads.append({**check, 'id': scene['id']+':ais:'+vessel['mmsi'], 'kind': state,
                          'title': 'AIS vessel not detected in clear-water image',
                          'reason': 'At image acquisition UTC, AIS places this vessel inside a clear-water footprint; no image contact within 1 km. Detection misses remain possible.',
                          'label': 'assumption', 'review_status': 'unreviewed'})
    for contact in contacts:
        # D109: over 100 bright spots ("clutter") means the D100 pixel check could not run,
        # which is no evidence against the AI position. Such an observation may still be a
        # review lead, marked as not pixel-confirmed, but it never claims an AIS identity.
        busy = (contact.get('localization') or {}).get('status') == 'clutter'
        if not verified:
            state = 'image_not_analysed'
        elif visual.get('image_status') == 'unusable':
            state = 'image_unusable'
        elif not position_eligible(contact) and not busy:
            state = 'optical_feature_unclassified' if contact['localization'].get('status') == 'feature_only' else 'image_location_unverified'
        elif contact.get('matched_mmsi') and not busy:
            state = 'provisional_match'
        elif contact.get('overlap_ambiguous'):
            state = 'duplicate_or_overlapping_observation'
        elif any(distance_km(contact, v['position']) <= .3 for v in vessels):
            # A failed one-to-one assignment is ambiguity, not a dark-vessel lead.
            state = 'nearby_ais_review'
        elif ais.get('coverage', {}).get('excluded_vessels'):
            # Removing ambiguous AIS must never manufacture a dark-ship claim.
            state = 'ais_history_conflict'
        elif any(v.get('position_evidence', {}).get('kinematic_consistency') != 'exceeds_assumed_limit'
                 and within_temporal_support(contact, v.get('position_evidence', {})) is True for v in vessels):
            state = 'ais_position_uncertain'
        elif not vessels:
            state = 'no_contemporaneous_ais'
        else:
            state = 'image_without_ais'
        contact_checks.append({'contact_id': contact['id'], 'status': state,
                               'identity_confirmed': False})
        if state == 'image_without_ais':
            leads.append({'id': scene['id']+':image:'+contact['id'], 'kind': 'image_without_ais',
                          'title': 'Image contact without a nearby AIS association',
                          'reason': 'No eligible AIS position within 300 m at acquisition UTC. Reception and image interpretation are incomplete.'
                                    + (BUSY_WATER_NOTE if busy else ''),
                          'lat': contact['lat'], 'lon': contact['lon'], 'mmsi': None,
                          'name': contact['id'], 'contact_id': contact['id'],
                          'label': 'assumption', 'review_status': 'unreviewed',
                          **({'pixel_support': 'unavailable_busy_water'} if busy else {})})
    for lead in leads:
        lead.update(scene_id=scene['id'], acquired_utc=scene['acquired_utc'], sensor=scene['sensor'],
                    source_label=scene['label'], identity_confirmed=False)
    result['counts'] = {'ais_vessels': len(checks), 'image_contacts': len(contacts), 'review_leads': len(leads)}
    return result
