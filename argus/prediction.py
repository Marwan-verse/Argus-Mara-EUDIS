"""Where a vessel could be while its AIS is dark, from the last observed fix.

Two layers, both planning estimates on the local flat approximation used by
``countdown.py`` (not navigation calculations):

* likely cone: last course +/- 30 degrees at 0.7-1.1 x last speed over ground;
* reachable circle: anything within v_max x elapsed time of the last fix.

Every number below is a team assumption, not vessel-specific physics. The
cone says where the vessel probably is; only the circle bounds where it can be.
Positions are [latitude, longitude]; speeds are knots; times are seconds.

Try it on the demo scenario:  python -m argus.prediction --t 1740 2400 3000
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from argus.countdown import NM_PER_DEG, nm_between, step

CONE_HALF_ANGLE_DEG = 30.0
CONE_SPEED_FACTORS = (0.7, 1.1)
V_MAX_FACTOR = 1.2
V_MAX_LOOKBACK_S = 60 * 60
DEFAULT_V_MAX_KN = 15.0
MAX_INTERPOLATION_GAP_S = 120  # Same as ui/replay.mjs fixAt and run_gui.fix_at.

ASSUMPTIONS = {
    "cone": f"Last course +/-{CONE_HALF_ANGLE_DEG:.0f} deg at {CONE_SPEED_FACTORS[0]}-"
            f"{CONE_SPEED_FACTORS[1]} x last speed over ground; assumption, not a confidence bound.",
    "v_max": f"Larger of {V_MAX_FACTOR} x the fastest speed seen in the last "
             f"{V_MAX_LOOKBACK_S // 60} min and {DEFAULT_V_MAX_KN:.0f} kn; assumption.",
    "geometry": "Local flat approximation; illustrative routes, not navigation.",
}


def _local_xy(lat, lon, ref_lat, ref_lon):
    """Nautical miles east (x) and north (y) of a reference point."""
    return ((lon - ref_lon) * NM_PER_DEG * math.cos(math.radians(ref_lat)),
            (lat - ref_lat) * NM_PER_DEG)


def _from_local_xy(x, y, ref_lat, ref_lon):
    return (ref_lat + y / NM_PER_DEG,
            ref_lon + x / (NM_PER_DEG * math.cos(math.radians(ref_lat))))


def bearing_deg(a_lat, a_lon, b_lat, b_lon):
    """Initial course from a to b in degrees true on the local flat approximation."""
    x, y = _local_xy(b_lat, b_lon, a_lat, a_lon)
    return math.degrees(math.atan2(x, y)) % 360


def _angle_difference(a, b):
    return abs((a - b + 180) % 360 - 180)


def _has_course(fix):
    return fix.get("sog_kn") is not None and fix["sog_kn"] > 0 and fix.get("cog_deg") is not None


def last_fix_at(track, t):
    """Latest observed fix at or before t; tracks are time-ordered by contract."""
    found = None
    for fix in track:
        if fix["t"] > t:
            break
        found = fix
    return found


def v_max_kn(track, t, lookback_s=V_MAX_LOOKBACK_S, default_kn=DEFAULT_V_MAX_KN):
    """Assumed top speed: V_MAX_FACTOR x recent fastest observed SOG, never below default."""
    speeds = [fix["sog_kn"] for fix in track
              if t - lookback_s <= fix["t"] <= t and fix.get("sog_kn") is not None]
    if not speeds:
        return default_kn
    return max(V_MAX_FACTOR * max(speeds), default_kn)


def predict(last_fix, t, v_max):
    """Likely cone and reachable circle at time t from one observed fix.

    The centre is dead reckoned at the last course and speed. Without a usable
    speed or course only the reachable circle is returned (cone is None) and
    the centre stays at the last fix.
    """
    elapsed_s = t - last_fix["t"]
    if elapsed_s < 0:
        raise ValueError("prediction time is before the last observed fix")
    hours = elapsed_s / 3600
    lat, lon = last_fix["lat"], last_fix["lon"]
    cone = None
    centre = (lat, lon)
    if _has_course(last_fix):
        sog, cog = last_fix["sog_kn"], last_fix["cog_deg"]
        centre = step(lat, lon, cog, sog * hours)
        near_nm, far_nm = (factor * sog * hours for factor in CONE_SPEED_FACTORS)
        cone = {
            "course_deg": cog,
            "half_angle_deg": CONE_HALF_ANGLE_DEG,
            "near_nm": round(near_nm, 3),
            "far_nm": round(far_nm, 3),
            "polygon": _cone_polygon(lat, lon, cog, near_nm, far_nm),
        }
    return {
        "t": t,
        "from_fix_t": last_fix["t"],
        "elapsed_s": elapsed_s,
        "lat": centre[0],
        "lon": centre[1],
        "cone": cone,
        "reachable": {"lat": lat, "lon": lon, "radius_nm": round(v_max * hours, 3), "v_max_kn": v_max},
        "label": "predicted",
        "assumptions": ASSUMPTIONS,
    }


def _cone_polygon(lat, lon, course_deg, near_nm, far_nm, arc_steps=6):
    """Closed outline of the cone sector as [lat, lon] points for the map."""
    left, right = course_deg - CONE_HALF_ANGLE_DEG, course_deg + CONE_HALF_ANGLE_DEG
    angles = [left + (right - left) * i / arc_steps for i in range(arc_steps + 1)]
    outer = [step(lat, lon, angle, far_nm) for angle in angles]
    inner = [step(lat, lon, angle, near_nm) for angle in reversed(angles)]
    ring = [[round(p[0], 5), round(p[1], 5)] for p in outer + inner]
    return ring + [ring[0]]


def position_at(track, t, v_max=None):
    """Vessel position at time t for replay and intercept simulations.

    Returns an observed or interpolated fix (never across a gap longer than
    MAX_INTERPOLATION_GAP_S), otherwise a prediction from the last fix before t.
    ``uncertainty_nm`` is 0 for observations and the reachable radius otherwise.
    Returns None before the first fix.
    """
    if not track or t < track[0]["t"]:
        return None
    before = last_fix_at(track, t)
    if before["t"] == t:
        return {**before, "status": "observed", "uncertainty_nm": 0.0, "label": "observed"}
    after = next((fix for fix in track if fix["t"] > t), None)
    if after is not None and after["t"] - before["t"] <= MAX_INTERPOLATION_GAP_S:
        fraction = (t - before["t"]) / (after["t"] - before["t"])
        return {**before, "t": t,
                "lat": before["lat"] + (after["lat"] - before["lat"]) * fraction,
                "lon": before["lon"] + (after["lon"] - before["lon"]) * fraction,
                "status": "interpolated", "uncertainty_nm": 0.0, "label": "observed"}
    speed = v_max if v_max is not None else v_max_kn(track, before["t"])
    prediction = predict(before, t, speed)
    return {"t": t, "lat": prediction["lat"], "lon": prediction["lon"],
            "status": "predicted", "uncertainty_nm": prediction["reachable"]["radius_nm"],
            "label": "predicted", "prediction": prediction}


def _segment_closest(px, py, ax, ay, bx, by):
    """Fraction along a-b of the closest point to p, and that point."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    fraction = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return fraction, ax + dx * fraction, ay + dy * fraction


def _closest_on_path(path, lat, lon):
    """(distance nm, closest [lat, lon], distance nm along the path) for a point."""
    best = None
    along = 0.0
    for a, b in zip(path, path[1:]):
        ax, ay = _local_xy(*a, lat, lon)
        bx, by = _local_xy(*b, lat, lon)
        fraction, cx, cy = _segment_closest(0.0, 0.0, ax, ay, bx, by)
        leg = nm_between(*a, *b)
        distance = math.hypot(cx, cy)
        if best is None or distance < best[0]:
            best = distance, list(_from_local_xy(cx, cy, lat, lon)), along + leg * fraction
        along += leg
    return best


def distance_to_path_nm(lat, lon, path):
    """Shortest distance from a point to a polyline, and the closest [lat, lon]."""
    if not path:
        raise ValueError("path has no points")
    if len(path) == 1:
        return nm_between(lat, lon, *path[0]), list(path[0])
    distance, closest, _ = _closest_on_path(path, lat, lon)
    return distance, closest


def _point_along(path, distance_nm):
    along = 0.0
    for a, b in zip(path, path[1:]):
        leg = nm_between(*a, *b)
        if leg > 0 and along + leg >= distance_nm:
            fraction = (distance_nm - along) / leg
            return [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction]
        along += leg
    return list(path[-1])


def anchor_reachable_path(cable):
    """Part of the cable path between the first and last anchor_reachable points.

    The scenario contract lists that section as [lat, lon] points on the route.
    Returns [] when no section is marked.
    """
    section = cable.get("anchor_reachable") or []
    path = cable["path"]
    if len(section) < 2 or len(path) < 2:
        return [list(point) for point in section]
    start, end = sorted(_closest_on_path(path, *point)[2] for point in (section[0], section[-1]))
    clipped = [_point_along(path, start)]
    along = 0.0
    for a, b in zip(path, path[1:]):
        along += nm_between(*a, *b)
        if start < along < end:
            clipped.append(list(b))
    clipped.append(_point_along(path, end))
    return clipped


def earliest_possible_contact_s(last_fix, v_max, path):
    """Worst-case seconds after last_fix until the vessel could reach the path.

    Straight line at v_max to the closest point; ignores course, so it is a
    lower bound for review, not an expected arrival.
    """
    if v_max is None or v_max <= 0:
        raise ValueError("v_max must be positive")
    distance_nm, _ = distance_to_path_nm(last_fix["lat"], last_fix["lon"], path)
    return int(distance_nm / v_max * 3600)


def dark_countdown(track, cable, now_s, v_max=None):
    """Countdown to the earliest possible contact with the anchor-reachable section.

    Works while AIS is dark: it uses only fixes observed at or before now_s.
    Returns None before the first fix or when no section is marked.
    """
    fix = last_fix_at(track, now_s)
    path = anchor_reachable_path(cable)
    if fix is None or not path:
        return None
    speed = v_max if v_max is not None else v_max_kn(track, fix["t"])
    distance_nm, closest = distance_to_path_nm(fix["lat"], fix["lon"], path)
    earliest_s = earliest_possible_contact_s(fix, speed, path)
    return {
        "segment_id": cable["id"],
        "last_fix_t": fix["t"],
        "since_last_fix_s": now_s - fix["t"],
        "distance_nm": round(distance_nm, 2),
        "closest_point": [round(closest[0], 5), round(closest[1], 5)],
        "v_max_kn": speed,
        "earliest_contact_t": fix["t"] + earliest_s,
        "remaining_s": max(0, fix["t"] + earliest_s - now_s),
        "label": "predicted",
        "method": "Straight line at assumed v_max from the last observed fix; a worst case, not an expected arrival.",
    }


def reappearance_check(last_fix, new_fix, v_max):
    """Compare a returning fix with what the last fix before the gap allows.

    * outside the reachable circle: physically inconsistent (possible position
      spoofing or identity reuse) under the assumed v_max;
    * inside the circle but outside the likely cone: manoeuvred while dark;
    * otherwise consistent. A cue for review, never a finding of intent.
    """
    elapsed_s = new_fix["t"] - last_fix["t"]
    if elapsed_s <= 0:
        raise ValueError("new fix must be later than the last fix")
    distance_nm = nm_between(last_fix["lat"], last_fix["lon"], new_fix["lat"], new_fix["lon"])
    hours = elapsed_s / 3600
    reachable_nm = v_max * hours
    in_cone = None
    if _has_course(last_fix):
        near_nm, far_nm = (factor * last_fix["sog_kn"] * hours for factor in CONE_SPEED_FACTORS)
        off_course = _angle_difference(bearing_deg(last_fix["lat"], last_fix["lon"],
                                                   new_fix["lat"], new_fix["lon"]),
                                       last_fix["cog_deg"])
        in_cone = near_nm <= distance_nm <= far_nm and off_course <= CONE_HALF_ANGLE_DEG
    if distance_nm > reachable_nm:
        verdict = "physically_inconsistent"
        note = (f"Moved {distance_nm:.1f} nm in {elapsed_s // 60} min, needing "
                f"{distance_nm / hours:.1f} kn against an assumed maximum of {v_max:.1f} kn; "
                "possible position spoofing or identity reuse, cause unknown.")
    elif in_cone is False:
        verdict = "manoeuvred_while_dark"
        note = "Reachable, but outside the likely cone from the last course and speed; cause unknown."
    else:
        verdict = "consistent"
        note = ("Within the reachable circle and the likely cone." if in_cone
                else "Within the reachable circle; no cone without a last course and speed.")
    return {
        "verdict": verdict,
        "elapsed_s": elapsed_s,
        "distance_nm": round(distance_nm, 2),
        "reachable_nm": round(reachable_nm, 2),
        "required_speed_kn": round(distance_nm / hours, 1),
        "v_max_kn": v_max,
        "in_cone": in_cone,
        "note": note,
        "label": "predicted",
    }


# --- command line: explore the prediction on a scenario file --------------

ROOT = Path(__file__).resolve().parents[1]


def last_gap(track, t):
    """Latest (before, after) pair too far apart to interpolate, ending at or before t."""
    found = None
    for before, after in zip(track, track[1:]):
        if after["t"] > t:
            break
        if after["t"] - before["t"] > MAX_INTERPOLATION_GAP_S:
            found = before, after
    return found


def report(scenario, t, mmsi=None, v_max=None, reappear=None):
    """Everything the module says about one vessel at time t, as plain data.

    ``reappear`` is an optional (lat, lon) where the vessel is assumed to show
    up at time t; otherwise the latest observed AIS gap ending by t is checked.
    """
    vessel = next((item for item in scenario["vessels"] if mmsi is None or item["mmsi"] == mmsi), None)
    if vessel is None:
        raise ValueError(f"no vessel with MMSI {mmsi}")
    track = vessel["track"]
    if reappear is not None:
        before = next((fix for fix in reversed(track) if fix["t"] < t), None)
        if before is None:
            raise ValueError("no AIS fix before the reappearance time")
        pair = before, {"t": t, "lat": reappear[0], "lon": reappear[1]}
    else:
        pair = last_gap(track, t)
    reappearance = None
    if pair is not None:
        before, after = pair
        speed = v_max if v_max is not None else v_max_kn(track, before["t"])
        reappearance = {"from_t": before["t"], "to_t": after["t"], "hypothetical": reappear is not None,
                        **reappearance_check(before, after, speed)}
    return {
        "t": t,
        "vessel": {"mmsi": vessel["mmsi"], "name": vessel.get("name"), "label": vessel.get("label")},
        "position": position_at(track, t, v_max),
        "countdowns": [countdown for countdown in
                       (dark_countdown(track, cable, t, v_max) for cable in scenario["cables"])
                       if countdown is not None],
        "reappearance": reappearance,
    }


def _clock(seconds):
    seconds = int(round(seconds))
    return f"T+{seconds // 60}:{seconds % 60:02d}"


def _minutes(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60} min {seconds % 60:02d} s"


def format_report(result):
    """Readable text for one report(); every estimate is labelled predicted."""
    vessel, position = result["vessel"], result["position"]
    lines = [f"{vessel['name']} (MMSI {vessel['mmsi']}, {vessel['label']}) at {_clock(result['t'])} ({result['t']} s)"]
    if position is None:
        lines.append("Position      none: before the first AIS fix")
    elif position["status"] != "predicted":
        course = position.get("cog_deg")
        lines.append(f"Position      {position['status'].upper()} AIS  {position['lat']:.5f}, {position['lon']:.5f}"
                     f"  sog {position.get('sog_kn')} kn, cog {course if course is not None else '-'}")
    else:
        prediction = position["prediction"]
        cone = prediction["cone"]
        lines += [
            f"Position      PREDICTED  {position['lat']:.5f}, {position['lon']:.5f}  +/-{position['uncertainty_nm']:.2f} nm",
            f"              last AIS fix {_clock(prediction['from_fix_t'])}, dark for {_minutes(prediction['elapsed_s'])}",
            f"Likely cone   course {cone['course_deg']:05.1f} +/-{cone['half_angle_deg']:.0f} deg, "
            f"{cone['near_nm']:.2f}-{cone['far_nm']:.2f} nm from the last fix" if cone
            else "Likely cone   none: no usable last speed and course",
            f"Reachable     up to {prediction['reachable']['radius_nm']:.2f} nm "
            f"at assumed v_max {prediction['reachable']['v_max_kn']:.1f} kn",
        ]
    for countdown in result["countdowns"]:
        lines += [
            f"Countdown     {countdown['segment_id']}: earliest possible contact "
            f"{_clock(countdown['earliest_contact_t'])}, {_minutes(countdown['remaining_s'])} left",
            f"              worst case: straight line {countdown['distance_nm']:.1f} nm at "
            f"{countdown['v_max_kn']:.1f} kn from the fix at {_clock(countdown['last_fix_t'])}",
        ]
    check = result["reappearance"]
    if check is None:
        lines.append("Reappearance  no AIS gap ended by this time")
    else:
        kind = "hypothetical fix" if check["hypothetical"] else "AIS gap"
        cone_text = {True: "in likely cone", False: "outside likely cone", None: "no cone"}[check["in_cone"]]
        lines += [
            f"Reappearance  {kind} {_clock(check['from_t'])} -> {_clock(check['to_t'])}: {check['verdict'].upper()}",
            f"              moved {check['distance_nm']:.2f} nm of {check['reachable_nm']:.2f} nm reachable, "
            f"needed {check['required_speed_kn']:.1f} kn; {cone_text}",
            f"              {check['note']}",
        ]
    return "\n".join(lines)


def _times(tokens):
    """Seconds from tokens like 2400 or START:END:STEP (END included)."""
    times = []
    for token in tokens:
        try:
            parts = [int(part) for part in token.split(":")]
        except ValueError:
            parts = []
        if len(parts) == 1:
            times.append(parts[0])
        elif len(parts) == 3 and parts[2] > 0:
            times.extend(range(parts[0], parts[1] + 1, parts[2]))
        else:
            raise ValueError(f"bad time {token!r}: use SECONDS or START:END:STEP")
    return times


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Predict where a dark vessel can be and how soon it could reach a cable.",
        epilog="Examples: --t 2400 | --t 1500:3300:300 | --t 3000 --reappear 53.2 -5.4 | --json",
    )
    parser.add_argument("--scenario", type=Path, default=ROOT / "demo/scenario.json")
    parser.add_argument("--t", nargs="+", default=["2400"], metavar="SECONDS",
                        help="scenario time(s) in seconds, or START:END:STEP")
    parser.add_argument("--mmsi", type=int, help="vessel to report (default: the first one)")
    parser.add_argument("--v-max", type=float, help="override the assumed maximum speed in knots")
    parser.add_argument("--reappear", nargs=2, type=float, metavar=("LAT", "LON"),
                        help="pretend AIS returns at this position at --t")
    parser.add_argument("--json", action="store_true", help="print raw data instead of text")
    args = parser.parse_args(argv)
    try:
        times = _times(args.t)
        if args.reappear and len(times) != 1:
            raise ValueError("--reappear needs exactly one --t")
        if args.v_max is not None and args.v_max <= 0:
            raise ValueError("--v-max must be positive")
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        results = [report(scenario, t, args.mmsi, args.v_max, args.reappear) for t in times]
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Prediction failed: {error}\n")
    if args.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))
    else:
        print("\n\n".join(format_report(result) for result in results))
        print("\nPositions marked PREDICTED are planning estimates from stated assumptions on fictional data.")


if __name__ == "__main__":
    main()
