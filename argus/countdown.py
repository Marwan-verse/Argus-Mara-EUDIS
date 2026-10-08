"""Small, dependency-free geometry and response timing for the offline replay.

These are planning estimates on an illustrative route, not navigation calculations.
Scenario paths use [latitude, longitude]; speeds are knots and times are seconds.
"""

from __future__ import annotations

import math

NM_PER_DEG = 60.0


def step(lat: float, lon: float, course_deg: float, distance_nm: float) -> tuple[float, float]:
    """Dead reckon a short leg using the same local approximation as the scenario."""
    angle = math.radians(course_deg)
    return (
        lat + distance_nm * math.cos(angle) / NM_PER_DEG,
        lon + distance_nm * math.sin(angle) / (NM_PER_DEG * math.cos(math.radians(lat))),
    )


def nm_between(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    dlat = (b_lat - a_lat) * NM_PER_DEG
    dlon = (b_lon - a_lon) * NM_PER_DEG * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dlat, dlon)


def _cross_fraction(p1, p2, q1, q2):
    """Fraction along p1-p2 where two short local segments intersect, if any."""
    def side(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
    d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
    if (d1 > 0) == (d2 > 0) or (d3 > 0) == (d4 > 0):
        return None
    return abs(d1) / (abs(d1) + abs(d2))


def project_to_cable(lat, lon, course_deg, sog_kn, cable_path, horizon_s=3 * 3600, step_s=60):
    """Project constant speed/course to the first cable crossing in the horizon."""
    if sog_kn is None or sog_kn <= 0:
        return None, None
    here = (lat, lon)
    for elapsed in range(0, horizon_s, step_s):
        nxt = step(*here, course_deg, sog_kn * step_s / 3600)
        for start, end in zip(cable_path, cable_path[1:]):
            fraction = _cross_fraction(here, nxt, start, end)
            if fraction is not None:
                crossing = (
                    here[0] + (nxt[0] - here[0]) * fraction,
                    here[1] + (nxt[1] - here[1]) * fraction,
                )
                return int(elapsed + step_s * fraction), crossing
        here = nxt
    return None, None


def response_options(assets, vessel_fix, crossing, earliest_s):
    """Calculate assumed arrival durations for a response initiated at the alert."""
    options = []
    for asset in assets:
        if asset.get("fixed_eta_min") is not None:
            eta_s = int(asset["fixed_eta_min"] * 60)
        elif asset.get("speed_kn") is None:
            distance_nm = nm_between(asset["lat"], asset["lon"], vessel_fix["lat"], vessel_fix["lon"])
            eta_s = int(asset["readiness_min"] * 60) if distance_nm <= asset["max_range_nm"] else None
        else:
            distance_nm = nm_between(asset["lat"], asset["lon"], *crossing)
            eta_s = int(asset["readiness_min"] * 60 + distance_nm / asset["speed_kn"] * 3600)
        options.append({
            "asset": asset["name"],
            "eta_s": eta_s,
            "in_time": eta_s is not None and eta_s <= earliest_s,
            "label": asset.get("label", "assumption"),
        })
    return options
