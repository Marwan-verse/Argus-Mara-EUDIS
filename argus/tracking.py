"""Conservative temporal support for acquisition-time AIS review.

These are reachable areas under a team speed assumption, not calibrated error
bars. Receipt-clock errors, sensor errors and unknown vessel dynamics remain.
"""
from bisect import bisect_left
import math

from argus.space import coordinates, distance_km, time_of

MAX_SUPPORT_SPEED_KN = 80.0


def temporal_support(track, when, position, t0=None):
    """Bound possible movement from the fixes used for an already eligible join.

    A short interpolation uses both endpoint circles; a projection uses only its
    preceding fix. Intersecting both circles retains turns instead of assuming
    that a straight line is the only possible track.
    """
    points = sorted(track, key=lambda point: time_of(point, t0))
    times = [time_of(point, t0) for point in points]
    index = bisect_left(times, when)
    if index < len(points) and times[index] == when:
        used = [points[index]]
    elif 0 < index < len(points) and times[index]-times[index-1] <= 600:
        used = points[index-1:index+1]
    elif index and 0 <= when-times[index-1] <= 300:
        used = [points[index-1]]
    else:
        return None
    fixes = []
    for point in used:
        lat, lon = coordinates(point)
        offset = abs(when-time_of(point, t0))
        fixes.append({'lat': lat, 'lon': lon, 'offset_s': offset,
                      'radius_m': MAX_SUPPORT_SPEED_KN*1852*offset/3600})
    # The intersection fits inside each endpoint circle; the smallest enclosing
    # radius around the estimated position is an upper bound, not a likelihood.
    radius = min(distance_km(position, fix)*1000+fix['radius_m'] for fix in fixes)
    return {'method': 'endpoint_reachability', 'max_speed_kn': MAX_SUPPORT_SPEED_KN,
            'fixes': fixes, 'center_radius_m': math.ceil(radius), 'label': 'assumption',
            'caveat': '80 kn is a screening assumption. This is not a confidence interval; receipt-time and sensor errors are not bounded.'}


def within_temporal_support(contact, evidence, margin_m=300):
    """Whether a contact could fit every supporting endpoint circle, or unknown."""
    support = evidence.get('temporal_support')
    if not support or not support.get('fixes'):
        return None
    return all(distance_km(contact, fix)*1000 <= fix['radius_m']+margin_m
               for fix in support['fixes'])
