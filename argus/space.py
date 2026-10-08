"""Radar/AIS association and length checks; no image processing or backend.

Run: python3 -m argus.space --scenario demo/scenario.json --output data/sar/space.json
The scenario contract is read-only. Results are a separate, additive sidecar.
"""

import argparse
import bisect
import json
import math
from datetime import datetime
from pathlib import Path


def finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def coordinates(point):
    lat, lon = finite(point["lat"], "lat"), finite(point["lon"], "lon")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordinates are outside WGS84")
    return lat, lon


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return dt.timestamp()


def time_of(point, t0=None):
    if "ts" in point:
        return timestamp(point["ts"])
    if "t" in point:
        return (timestamp(t0) if t0 else 0) + finite(point["t"], "t")
    raise ValueError("a point needs ts, or t relative to the scenario")


def distance_km(a, b):
    lat1, lon1 = coordinates(a)
    lat2, lon2 = coordinates(b)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def project(point, seconds):
    """Great-circle dead reckoning; return None for missing/invalid AIS motion."""
    if point.get("sog_kn") is None or point.get("cog_deg") is None:
        return None
    speed, course = finite(point["sog_kn"], "sog_kn"), finite(point["cog_deg"], "cog_deg")
    if not (0 <= speed < 102.3 and 0 <= course < 360):
        return None  # AIS unavailable-value sentinels are not real motion.
    lat, lon = map(math.radians, coordinates(point))
    bearing = math.radians(course)
    arc = speed * 1.852 * seconds / 3600 / 6371.0088
    lat2 = math.asin(math.sin(lat) * math.cos(arc)
                     + math.cos(lat) * math.sin(arc) * math.cos(bearing))
    lon2 = lon + math.atan2(math.sin(bearing) * math.sin(arc) * math.cos(lat),
                           math.cos(arc) - math.sin(lat) * math.sin(lat2))
    return {"lat": math.degrees(lat2), "lon": (math.degrees(lon2) + 180) % 360 - 180}


def position_at(track, when, t0=None, max_gap_s=600, max_age_s=300):
    """Interpolate short brackets; only extrapolate a recent *past* fix.

    A long AIS silence is never interpolated into a confident AIS match.
    """
    points = sorted(track, key=lambda p: time_of(p, t0))
    times = [time_of(p, t0) for p in points]
    i = bisect.bisect_left(times, when)
    if i < len(points) and times[i] == when:
        coordinates(points[i])
        return points[i]
    if i == 0:
        return None
    before = points[i - 1]
    if i < len(points) and 0 < times[i] - times[i - 1] <= max_gap_s:
        after = points[i]
        fraction = (when - times[i - 1]) / (times[i] - times[i - 1])
        lat1, lon1 = coordinates(before)
        lat2, lon2 = coordinates(after)
        dlon = (lon2 - lon1 + 180) % 360 - 180
        return {"lat": lat1 + fraction * (lat2 - lat1),
                "lon": (lon1 + fraction * dlon + 180) % 360 - 180}
    age = when - times[i - 1]
    return project(before, age) if age <= max_age_s else None


def length_check(radar_m, ais_m, uncertainty_m=30):
    """Nominal rule from build guide §8; a flag is a review cue, not proof."""
    uncertainty_m = finite(uncertainty_m, "uncertainty_m")
    if uncertainty_m < 0:
        raise ValueError("uncertainty_m must be non-negative")
    if radar_m is None or ais_m is None:
        return {"status": "unavailable", "mismatch": None}
    radar_m, ais_m = finite(radar_m, "radar length"), finite(ais_m, "AIS length")
    if radar_m <= 0 or ais_m <= 0:
        return {"status": "unavailable", "mismatch": None}
    if min(radar_m, ais_m) < 80:
        return {"status": "below_supported_size", "mismatch": None}
    delta, threshold = abs(radar_m - ais_m), max(40, 0.25 * ais_m)
    mismatch = delta > threshold
    return {"status": "possible_mismatch" if mismatch else "consistent",
            "mismatch": mismatch, "radar_length_m": radar_m, "ais_length_m": ais_m,
            "difference_m": round(delta, 3), "threshold_m": round(threshold, 3),
            "uncertainty_m": uncertainty_m,
            "exceeds_threshold_after_uncertainty": delta - uncertainty_m > threshold}


def assignment(costs):
    """Rectangular Hungarian minimum-cost assignment (rows <= columns)."""
    n = len(costs)
    if not n:
        return []
    m = len(costs[0])
    if m < n or any(len(row) != m for row in costs):
        raise ValueError("assignment needs a rectangular matrix with rows <= columns")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        mins, used = [math.inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < mins[j]:
                        mins[j], way[j] = cur, j0
                    if mins[j] < delta:
                        delta, j1 = mins[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    mins[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1
    result = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def custody_candidates(detection, vessels, when, t0, max_speed_kn=30, horizon_s=1800):
    """Bounded reachability candidates in a gap; never assert identity/probability."""
    candidates = []
    for vessel in vessels:
        past = [p for p in vessel.get("track", []) if time_of(p, t0) <= when]
        if not past or position_at(vessel.get("track", []), when, t0) is not None:
            continue
        last = max(past, key=lambda p: time_of(p, t0))
        age = when - time_of(last, t0)
        radius = max_speed_kn * 1.852 * age / 3600
        distance = distance_km(last, detection)
        if age <= horizon_s and distance <= radius:
            check = length_check(detection.get("length_m"), dimensions_at(vessel, when, t0))
            predicted = project(last, age)
            candidates.append({"mmsi": vessel["mmsi"], "status": "candidate_only",
                               "last_fix_age_s": round(age), "distance_from_last_fix_km": round(distance, 3),
                               "reachable_radius_km": round(radius, 3), "max_speed_kn": max_speed_kn,
                               "projection_error_km": round(distance_km(predicted, detection), 3) if predicted else None,
                               "length_check": check})
    return candidates


def dimensions_at(vessel, when, t0):
    """Imported dimensions expire after 24h and must not come from the future.

    Legacy scenario dimensions are constants, but still need a contemporaneous
    track before they can be compared with a source-reported historical contact.
    """
    if "dimension_history" in vessel:
        history = [item for item in vessel["dimension_history"]
                   if 0 <= when - time_of(item, t0) <= 86400
                   and item.get("label", vessel.get("label")) == vessel.get("label")]
        return max(history, key=lambda item: time_of(item, t0))["ais_length_m"] if history else None
    past = [point for point in vessel.get("track", []) if 0 <= when - time_of(point, t0) <= 1800]
    return vessel.get("ais_length_m") if past else None


def compatible_labels(detection, vessel, default):
    observed = {"real", "reconstructed"}
    return ((detection.get("label", default) in observed)
            == (vessel.get("label", default) in observed))


def position_method(track, when, t0):
    points = sorted(track, key=lambda point: time_of(point, t0))
    times = [time_of(point, t0) for point in points]
    i = bisect.bisect_left(times, when)
    if i < len(times) and times[i] == when:
        method, used = {"position_method": "observed_fix", "age_s": 0}, [points[i]]
    elif 0 < i < len(times) and times[i] - times[i - 1] <= 600:
        method, used = {"position_method": "short_bracket_interpolation", "bracket_s": times[i] - times[i - 1]}, points[i - 1:i + 1]
    else:
        method, used = {"position_method": "past_fix_projection", "age_s": when - times[i - 1]}, [points[i - 1]]
    method["timestamp_sources"] = sorted({p.get("timestamp_source", "observation_time") for p in used})
    method["observation_time_assumed"] = "received_time_assumption" in method["timestamp_sources"]
    return method


def analyse(scenario, match_radius_km=1.0):
    match_radius_km = finite(match_radius_km, "match_radius_km")
    if match_radius_km <= 0:
        raise ValueError("match_radius_km must be positive")
    t0, vessels = scenario.get("t0_utc"), scenario.get("vessels", [])
    default_label = scenario.get("label", "assumption")
    if len({str(v["mmsi"]) for v in vessels}) != len(vessels):
        raise ValueError("duplicate vessel MMSI")
    groups, results = {}, []
    for index, detection in enumerate(scenario.get("detections", [])):
        coordinates(detection)
        when = time_of(detection, t0)
        result = dict(detection)
        source_mmsi = detection.get("matched_mmsi") or None
        result.update({"id": detection.get("id", f"SAR-{index + 1}"),
                       "label": detection.get("label", default_label),
                       "provider_matched_mmsi": source_mmsi,
                       "matched_mmsi": source_mmsi,
                       "association": "source_reported" if source_mmsi else "unmatched",
                       "length_check": {"status": "unavailable", "mismatch": None},
                       "custody_candidates": [], "unavailable_reasons": [],
                       "association_label": "reconstructed" if detection.get("label", default_label) in {"real", "reconstructed"}
                                            else "assumption" if detection.get("label", default_label) == "assumption" else "simulated"})
        results.append(result)
        groups.setdefault((when, detection.get("scene_id")), []).append(index)
    by_mmsi = {str(v["mmsi"]): v for v in vessels}
    for (when, _scene), indices in groups.items():
        reserved = {str(results[i]["matched_mmsi"]) for i in indices if results[i]["matched_mmsi"]}
        available = [(v, position_at(v.get("track", []), when, t0))
                     for v in vessels if str(v["mmsi"]) not in reserved]
        available = [(v, pos) for v, pos in available if pos is not None]
        pending = [i for i in indices if not results[i]["matched_mmsi"]]
        # Each row gets an unmatched dummy column. Penalty first maximises the
        # number of gated matches, then minimises total normalised distance.
        penalty = len(pending) + 1
        costs = []
        for i in pending:
            distances = [distance_km(results[i], pos) for _, pos in available]
            costs.append([d / match_radius_km if d <= match_radius_km
                          and compatible_labels(results[i], v, default_label) else penalty * 3
                          for d, (v, _pos) in zip(distances, available)] + [penalty] * len(pending))
        for row, (i, col) in enumerate(zip(pending, assignment(costs))):
            if col < len(available) and costs[row][col] <= 1:
                vessel, pos = available[col]
                results[i].update({"matched_mmsi": vessel["mmsi"], "association": "local_ais_match",
                                   "match_distance_km": round(distance_km(results[i], pos), 3)})
        for i in indices:
            result = results[i]
            vessel = by_mmsi.get(str(result["matched_mmsi"]))
            if vessel and compatible_labels(result, vessel, default_label):
                result["length_check"] = length_check(result.get("length_m"), dimensions_at(vessel, when, t0))
            result["association_evidence"] = {"method": result["association"],
                "ais_vessels_supplied": len(vessels), "eligible_unreserved_positions": len(available)}
            if result["association"] == "local_ais_match":
                result["association_evidence"].update(position_method(vessel.get("track", []), when, t0))
            result["dark_candidate"] = result["matched_mmsi"] is None
            if result["dark_candidate"]:
                candidates = [v for v in vessels if compatible_labels(result, v, default_label)]
                result["custody_candidates"] = custody_candidates(result, candidates, when, t0)
                result["unavailable_reasons"].append(
                    "No AIS input supplied." if not vessels else
                    "No eligible contemporaneous AIS position." if not available else
                    "No compatible AIS association within the distance gate and one-to-one assignment.")
            if result["length_check"]["mismatch"] is None:
                result["unavailable_reasons"].append(
                    "Length comparison is below the supported 80 m size." if result["length_check"]["status"] == "below_supported_size"
                    else "No comparable radar length and contemporaneous declared AIS dimensions.")
    return {"generated_by": "argus.space", "label": scenario.get("label", "unlabelled"),
            "scenario": scenario.get("name"),
            "assumptions": {"match_radius_km": match_radius_km, "max_interpolation_gap_s": 600,
                            "max_extrapolation_age_s": 300, "custody_max_speed_kn": 30,
                            "custody_horizon_s": 1800, "radar_length_uncertainty_m": 30,
                            "max_dimension_age_s": 86400},
            "coverage": {"radar_observations": len(results), "ais_vessels": len(vessels),
                         "ais_fixes": sum(len(v.get("track", [])) for v in vessels),
                         "complete_regional_census": False},
            "provenance": scenario.get("provenance"), "selection": scenario.get("selection"),
            "caveat": "An unmatched radar contact is a review candidate, not proof of AIS shutdown or hostile intent.",
            "detections": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("demo/scenario.json"))
    parser.add_argument("--output", type=Path, default=Path("data/sar/space.json"))
    parser.add_argument("--match-radius-km", type=float, default=1.0)
    args = parser.parse_args()
    try:
        if args.scenario.resolve() == args.output.resolve():
            raise ValueError("output must differ from the input scenario")
        result = analyse(json.loads(args.scenario.read_text()), args.match_radius_km)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Space analysis failed: {exc}\n")
    print(f"{len(result['detections'])} detections -> {args.output}")


if __name__ == "__main__":
    main()
