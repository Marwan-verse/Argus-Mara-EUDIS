"""Seabed magnetometer search plan after a suspected anchor drag: a planning estimate, never evidence.

The planner turns a vessel's AIS track, from the start of its slowdown to the cable crossing and on to
where its speed recovered (or its last fix), into a search corridor. For each survey platform it then
estimates line spacing, the number of lines, line-km and hours for a magnetometer search for the anchor,
fluke or chain the drag may have left behind. Investigators find the drag *scar* with side-scan or
multibeam sonar; a magnetometer finds the ferrous objects. No official account of the Baltic cases names
a magnetometer, so ARGUS presents this only as a search-planning aid.

Model (team assumptions, from the 15 Oct 2026 research on branch ``research-aircraft-magnetic``):

* corridor half-width w = AIS position error (50 m) + anchor-chain reach (3 × water depth) + margin (100 m);
* detection radius r_max = (100 · k · mass · f / threshold)^(1/3) with k = 610 A·m² per tonne (from the
  Geometrics G-882 detection table: a 20 t anchor gives 0.8–1.25 nT at 120 m), f = 1.5 for orientation and
  a 5 nT threshold (BOEM's minimum deflection for archaeological surveys);
* spacing s = 2 · √(r_max² − h²) for a sensor h metres above the seabed, so a target halfway between two
  lines is still detected; at h ≥ r_max the platform cannot detect the target;
* lines n = ⌈W / s⌉ + 1, line-km = n · L · 1.1 (10 % tie lines), hours = line-km / speed + (n − 1) · turn.

Worked example: a 10 km × 600 m corridor and a 10 t anchor need about 7 lines, 77 line-km and 10.7 h for a
USV towing a fish 10 m above the seabed at 4 kn. The Eagle S anchor lay at the far end of its trace, so
the plan ranks the cable crossing first and the point where speed recovered second.

Usage: python -m argus.survey_plan
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from statistics import median

AIS_ERROR_M = 50.0
CHAIN_REACH_PER_DEPTH = 3.0
MARGIN_M = 100.0
K_ANCHOR = 610.0  # A·m² per tonne of anchor
ORIENTATION_F = 1.5
THRESHOLD_NT = 5.0
TIE_LINES = 1.1
DEFAULT_DEPTH_M = 50.0
DEFAULT_MASS_T = 10.0
MAX_LINES = 400
MIN_LENGTH_KM = 1.0  # a single point still gets a 1 km box
PRIORITY_BOX_KM = 2.0  # each ranked point is estimated as a box this long, the first thing to search
M_PER_DEG = 111_195.0
KN_TO_KMH = 1.852

# Slowdown and recovery (assumptions, close to cable_risk's B1 thresholds).
BASELINE_GAP_S = 30 * 60  # the baseline speed comes from fixes at least this old...
BASELINE_S = 60 * 60  # ...and at most this much older again
BASELINE_MIN_FIXES = 3
BASELINE_MIN_KN = 5.0
SLOW_FACTOR = 0.8  # a 20 % drop starts the drag
STILL_SLOW_FACTOR = 0.85  # the run continues while the rolling median stays below this
RECOVERED_FACTOR = 0.9
FALLBACK_S = 60 * 60  # no slowdown found: start this long before the crossing
NEAR_LINE_M = 2000.0  # without a crossing, plan only for a vessel this close to the line

PLATFORMS = (
    {"id": "usv", "name": "USV towing a fish 10 m above the seabed", "above_seabed_m": 10.0,
     "speed_kmh": 4.0 * KN_TO_KMH, "turn_s": 180, "speed_text": "4 kn, 3 min turns"},
    {"id": "auv", "name": "AUV 5 m above the seabed", "above_seabed_m": 5.0,
     "speed_kmh": 3.0 * KN_TO_KMH, "turn_s": 120, "speed_text": "3 kn, 2 min turns"},
    {"id": "drone", "name": "Drone magnetometer 15 m above the sea", "altitude_m": 15.0,
     "speed_kmh": 8.0 * 3.6, "turn_s": 60, "speed_text": "8 m/s, 60 s turns", "endurance_min": 20,
     "max_depth_m": 30.0},
)
NOTES = (
    "Planning estimate: every width, radius, speed and time here is a team assumption, not a survey design.",
    "A magnetometer finds ferrous objects left behind (a lost anchor, a fluke, chain); the drag scar needs "
    "side-scan or multibeam sonar.",
    "A drone magnetometer (such as the 1.2 kg MagArrow II) only works in shallow water near a landfall.",
)


def detection_radius_m(mass_t: float = DEFAULT_MASS_T, threshold_nt: float = THRESHOLD_NT) -> float:
    return (100.0 * K_ANCHOR * mass_t * ORIENTATION_F / threshold_nt) ** (1 / 3)


def half_width_m(depth_m: float) -> float:
    return AIS_ERROR_M + CHAIN_REACH_PER_DEPTH * depth_m + MARGIN_M


def platform_row(platform: dict, length_km: float, width_m: float, depth_m: float, r_max_m: float) -> dict:
    """Spacing, lines, line-km and hours for one platform over one corridor."""
    height = platform["above_seabed_m"] if "above_seabed_m" in platform else platform["altitude_m"] + depth_m
    row = {"id": platform["id"], "name": platform["name"], "speed_text": platform["speed_text"],
           "sensor_height_m": height, "spacing_m": None, "lines": None, "line_km": None, "hours": None,
           "sorties": None, "status": "ok", "note": ""}
    if height >= r_max_m:
        row.update(status="cannot detect",
                   note=f"Sensor {height:.0f} m above the seabed; the target is detectable only within {r_max_m:.0f} m.")
        return row
    spacing = 2 * math.sqrt(r_max_m ** 2 - height ** 2)
    lines = math.ceil(width_m / spacing) + 1
    if lines > MAX_LINES:
        row.update(status="impractical", spacing_m=spacing, note=f"More than {MAX_LINES} lines.")
        return row
    line_km = lines * length_km * TIE_LINES
    hours = line_km / platform["speed_kmh"] + (lines - 1) * platform["turn_s"] / 3600
    row.update(spacing_m=spacing, lines=lines, line_km=line_km, hours=hours)
    if "endurance_min" in platform:
        row["sorties"] = math.ceil(hours * 60 / platform["endurance_min"])
    if depth_m > platform.get("max_depth_m", math.inf):
        row.update(status="impractical", note=f"Water deeper than {platform['max_depth_m']:.0f} m: shallow landfalls only.")
    return row


def estimate(length_km: float, width_m: float, depth_m: float, mass_t: float = DEFAULT_MASS_T,
             threshold_nt: float = THRESHOLD_NT, platforms=PLATFORMS) -> list[dict]:
    r_max = detection_radius_m(mass_t, threshold_nt)
    return [platform_row(platform, length_km, width_m, depth_m, r_max) for platform in platforms]


# --- Geometry in a local plane (metres east and north of a reference point) ------------------------

def _plane(reference: tuple[float, float]):
    lat0, lon0 = reference
    scale = math.cos(math.radians(lat0)) * M_PER_DEG

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        return (lon - lon0) * scale, (lat - lat0) * M_PER_DEG

    def to_geo(x: float, y: float) -> tuple[float, float]:
        return lat0 + y / M_PER_DEG, lon0 + x / scale

    return to_xy, to_geo


def _length_m(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _intersection(p, p2, q, q2) -> tuple[float, float] | None:
    """Fractions (t along p→p2, u along q→q2) where two segments cross, else None."""
    rx, ry = p2[0] - p[0], p2[1] - p[1]
    sx, sy = q2[0] - q[0], q2[1] - q[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-9:
        return None
    qpx, qpy = q[0] - p[0], q[1] - p[1]
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    return (t, u) if 0 <= t <= 1 and 0 <= u <= 1 else None


def _offset(points: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """The polyline shifted ``distance`` metres to its left (negative: right), with clamped mitres."""
    if len(points) < 2:
        return list(points)
    normals = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0) or 1.0
        normals.append((-(y1 - y0) / length, (x1 - x0) / length))
    out = []
    for index, (x, y) in enumerate(points):
        a = normals[max(0, index - 1)]
        b = normals[min(index, len(normals) - 1)]
        nx, ny = a[0] + b[0], a[1] + b[1]
        size = math.hypot(nx, ny)
        if size < 1e-9:
            nx, ny, mitre = b[0], b[1], 1.0
        else:
            nx, ny = nx / size, ny / size
            mitre = min(2.0, 1.0 / max(0.5, nx * b[0] + ny * b[1]))
        out.append((x + nx * distance * mitre, y + ny * distance * mitre))
    return out


def _fixes(track) -> list[dict]:
    """Normalise dict fixes or (lat, lon) pairs; drop repeats closer than 1 m."""
    out = []
    for fix in track:
        if isinstance(fix, dict):
            item = {"lat": float(fix["lat"]), "lon": float(fix["lon"]),
                    "t": fix.get("t"), "sog_kn": fix.get("sog_kn")}
        else:
            item = {"lat": float(fix[0]), "lon": float(fix[1]), "t": None, "sog_kn": None}
        if out and abs(out[-1]["lat"] - item["lat"]) < 1e-5 and abs(out[-1]["lon"] - item["lon"]) < 1e-5:
            out[-1].update({key: value for key, value in item.items() if value is not None})
            continue
        out.append(item)
    return out


def _rolling_median(values: list[float], index: int) -> float:
    return median(values[max(0, index - 1):index + 2])


def _slowdown(fixes: list[dict], last: int) -> tuple[int, float] | None:
    """Earliest fix 20 % slower than the speed 30–90 min earlier that stayed down until ``last``.

    Like cable_risk's B1, the baseline comes from older fixes, so a gradual slowdown (12, then 11, then
    9 kn) is still measured against the original speed.
    """
    speeds = [fix["sog_kn"] for fix in fixes]
    for index in range(1, last + 1):
        ages = [(fixes[index]["t"] - fixes[k]["t"], fixes[k]["sog_kn"]) for k in range(index)]
        before = [speed for age, speed in ages if BASELINE_GAP_S <= age <= BASELINE_GAP_S + BASELINE_S]
        if len(before) < BASELINE_MIN_FIXES:  # a short track: the last 30 min instead
            before = [speed for age, speed in ages if 0 < age <= BASELINE_GAP_S]
        if len(before) < BASELINE_MIN_FIXES:
            continue
        base = median(before)
        if base < BASELINE_MIN_KN or speeds[index] > SLOW_FACTOR * base:
            continue
        if all(_rolling_median(speeds, k) <= STILL_SLOW_FACTOR * base for k in range(index, last + 1)):
            return index, base
    return None


def select_segment(track, cable_path) -> dict:
    """The part of the track to search: slowdown start → crossing → speed recovery, with reasons."""
    fixes = _fixes(track)
    if not fixes:
        raise ValueError("no track to plan from")
    path = [(float(lat), float(lon)) for lat, lon in cable_path or []]
    to_xy, to_geo = _plane((fixes[-1]["lat"], fixes[-1]["lon"]))
    xy = [to_xy(fix["lat"], fix["lon"]) for fix in fixes]
    cable = [to_xy(lat, lon) for lat, lon in path]
    timed = all(fix["t"] is not None and fix["sog_kn"] is not None for fix in fixes)

    crossing = None  # (segment index, fraction, point in the plane)
    for index, (a, b) in enumerate(zip(xy, xy[1:])):
        hits = [hit for c, d in zip(cable, cable[1:]) if (hit := _intersection(a, b, c, d))]
        if hits:
            t = min(hit[0] for hit in hits)
            crossing = (index, t, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            break
    crossing_index = crossing[0] + 1 if crossing else len(fixes) - 1  # the first fix after the crossing

    start, base, start_reason = 0, None, "Speed history unavailable: the corridor covers the shown track."
    if timed:
        found = _slowdown(fixes, crossing[0] if crossing else len(fixes) - 1)  # slow up to the crossing
        if found:
            start, base = found
            start_reason = (f"Slowdown from {base:.0f} to {fixes[start]['sog_kn']:.0f} kn at "
                            f"{_clock(fixes[start]['t'])}, held until the "
                            f"{'cable crossing' if crossing else 'last fix'}.")
        else:
            limit = (fixes[crossing_index]["t"] if crossing else fixes[-1]["t"]) - FALLBACK_S
            start = next((k for k, fix in enumerate(fixes) if fix["t"] >= limit), 0)
            start_reason = ("No sustained slowdown found: the corridor starts 1 h before the "
                            f"{'cable crossing' if crossing else 'last fix'}.")

    end, recovery, recovery_reason = len(fixes) - 1, None, "End of the known track (last fix)."
    if crossing and timed and base:
        speeds = [fix["sog_kn"] for fix in fixes]
        for index in range(crossing_index, len(fixes)):
            if _rolling_median(speeds, index) >= RECOVERED_FACTOR * base:
                end, recovery = index, index
                recovery_reason = (f"Speed recovered to {fixes[index]['sog_kn']:.0f} kn at {_clock(fixes[index]['t'])}: "
                                   "the anchor may have been lost or raised here.")
                break
    if not crossing:
        end = len(fixes) - 1

    axis = xy[start:end + 1]
    if crossing and start <= crossing[0] < end:
        axis.insert(crossing[0] - start + 1, crossing[2])
    nearest = None
    if not crossing and cable:
        nearest = min(((math.dist(xy[end], point), point) for point in _densify(cable)), default=None)
        if nearest and nearest[0] > NEAR_LINE_M:
            raise ValueError(f"No cable crossing yet: the last fix is {nearest[0] / 1852:.1f} nm from the line. "
                             "The seabed search plan is for after a suspected drag across a cable.")
    elif not cable:
        raise ValueError("No cable route to plan against.")
    return {"fixes": fixes, "to_xy": to_xy, "to_geo": to_geo, "axis_xy": axis, "start": start, "end": end,
            "start_reason": start_reason, "crossing": to_geo(*crossing[2]) if crossing else None,
            "recovery": (fixes[recovery]["lat"], fixes[recovery]["lon"]) if recovery is not None else None,
            "recovery_reason": recovery_reason, "base_kn": base, "timed": timed,
            "nearest": (to_geo(*nearest[1]), nearest[0]) if nearest else None}


def _densify(points: list[tuple[float, float]], step: float = 100.0) -> list[tuple[float, float]]:
    out = []
    for a, b in zip(points, points[1:]):
        count = max(1, int(math.dist(a, b) // step))
        out.extend((a[0] + (b[0] - a[0]) * k / count, a[1] + (b[1] - a[1]) * k / count) for k in range(count))
    return out + points[-1:]


def _clock(t) -> str:
    if t is None:
        return "?"
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%H:%M UTC")


def plan(track, cable_path, depth_m: float | None = None, mass_t: float = DEFAULT_MASS_T,
         threshold_nt: float = THRESHOLD_NT, platform_id: str = "usv", subject: str = "",
         depth_source: str = "") -> dict:
    """Corridor, platform estimates, map geometry and ranked search points for one vessel track."""
    if depth_m is None:
        depth_m, depth_source = DEFAULT_DEPTH_M, depth_source or "assumed (route depth unknown)"
    if depth_m <= 0 or mass_t <= 0 or threshold_nt <= 0:
        raise ValueError("depth, anchor mass and threshold must be positive")
    segment = select_segment(track, cable_path)
    to_geo, axis = segment["to_geo"], segment["axis_xy"]
    w = half_width_m(depth_m)
    length_km = _length_m(axis) / 1000
    if len(axis) < 2 or length_km < MIN_LENGTH_KM:  # a point (or a stub): a 1 km box along the last course
        x, y = axis[-1]
        heading = _heading(segment) or 0.0
        half = MIN_LENGTH_KM * 500
        axis = [(x - half * math.sin(heading), y - half * math.cos(heading)),
                (x + half * math.sin(heading), y + half * math.cos(heading))]
        length_km = MIN_LENGTH_KM
    rows = estimate(length_km, 2 * w, depth_m, mass_t, threshold_nt)
    chosen = next((row for row in rows if row["id"] == platform_id), rows[0])
    lines = []
    if chosen["lines"]:
        count = chosen["lines"]
        offsets = [-w + 2 * w * k / (count - 1) for k in range(count)] if count > 1 else [0.0]
        lines = [[to_geo(*point) for point in _offset(axis, offset)] for offset in offsets]
    corridor = [to_geo(*point) for point in _offset(axis, w) + _offset(axis, -w)[::-1]]
    priorities = []
    if segment["crossing"]:
        priorities.append({"lat": segment["crossing"][0], "lon": segment["crossing"][1],
                           "text": "Cable crossing: search here first."})
    elif segment["nearest"]:
        (lat, lon), distance = segment["nearest"]
        priorities.append({"lat": lat, "lon": lon,
                           "text": f"Nearest point of the line, {distance:.0f} m from the last fix: search here first."})
    end = segment["fixes"][segment["end"]]
    priorities.append({"lat": segment["recovery"][0] if segment["recovery"] else end["lat"],
                       "lon": segment["recovery"][1] if segment["recovery"] else end["lon"],
                       "text": segment["recovery_reason"] + (" The Eagle S anchor lay at the far end of its trace."
                                                             if segment["recovery"] else "")})
    platform = next(item for item in PLATFORMS if item["id"] == chosen["id"])
    box = platform_row(platform, PRIORITY_BOX_KM, 2 * w, depth_m, detection_radius_m(mass_t, threshold_nt))
    for rank, item in enumerate(priorities, 1):
        item.update(rank=rank, box=box)
    return {
        "label": "assumption", "subject": subject, "created": datetime.now(timezone.utc),
        "depth_m": depth_m, "depth_source": depth_source or "operator entry", "mass_t": mass_t,
        "threshold_nt": threshold_nt, "r_max_m": detection_radius_m(mass_t, threshold_nt),
        "half_width_m": w, "width_m": 2 * w, "length_km": length_km, "platforms": rows,
        "platform_id": chosen["id"], "start_reason": segment["start_reason"], "priorities": priorities,
        "axis": [to_geo(*point) for point in axis], "corridor": corridor, "lines": lines, "notes": list(NOTES),
    }


def _heading(segment: dict) -> float | None:
    points = segment["axis_xy"] if len(segment["axis_xy"]) > 1 else [segment["to_xy"](f["lat"], f["lon"])
                                                                      for f in segment["fixes"][-2:]]
    if len(points) < 2:
        return None
    (x0, y0), (x1, y1) = points[-2], points[-1]
    return math.atan2(x1 - x0, y1 - y0)


def to_geojson(result: dict) -> dict:
    """The plan as GeoJSON (lon, lat order) for an evidence pack; every feature is labelled an assumption."""
    def ring(points):
        return [[round(lon, 6), round(lat, 6)] for lat, lon in points]

    common = {"label": "assumption", "source": "ARGUS MARA seabed search planner (planning estimate)"}
    features = [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring(result["corridor"] + result["corridor"][:1])]},
         "properties": {**common, "kind": "corridor", "width_m": round(result["width_m"]), "depth_m": result["depth_m"]}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring(result["axis"])},
         "properties": {**common, "kind": "track_axis", "length_km": round(result["length_km"], 2)}},
    ]
    features += [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": ring(line)},
                  "properties": {**common, "kind": "survey_line", "platform": result["platform_id"], "index": index}}
                 for index, line in enumerate(result["lines"], 1)]
    features += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(item["lon"], 6), round(item["lat"], 6)]},
                  "properties": {**common, "kind": "priority", "rank": item["rank"], "text": item["text"]}}
                 for item in result["priorities"]]
    return {"type": "FeatureCollection", "features": features,
            "properties": {**common, "subject": result["subject"], "created": result["created"].isoformat(),
                           "mass_t": result["mass_t"], "threshold_nt": result["threshold_nt"],
                           "detection_radius_m": round(result["r_max_m"], 1), "notes": result["notes"]}}


def table(rows: list[dict]) -> list[str]:
    lines = []
    for row in rows:
        if row["status"] == "cannot detect":
            lines.append(f"{row['name']}: cannot detect · {row['note']}")
            continue
        text = (f"{row['name']} ({row['speed_text']}): spacing {row['spacing_m']:.0f} m · {row['lines']} lines · "
                f"{row['line_km']:.0f} line-km · {row['hours']:.1f} h")
        if row.get("sorties"):
            text += f" · {row['sorties']} sorties"
        if row["status"] != "ok":
            text += f" · {row['status']}: {row['note']}"
        lines.append(text)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Worked example of the seabed search planner (assumptions).")
    parser.add_argument("--length-km", type=float, default=10.0)
    parser.add_argument("--width-m", type=float, default=600.0)
    parser.add_argument("--depth-m", type=float, default=20.0)
    parser.add_argument("--mass-t", type=float, default=DEFAULT_MASS_T)
    args = parser.parse_args()
    print(f"Corridor {args.length_km:g} km × {args.width_m:g} m, {args.depth_m:g} m water, {args.mass_t:g} t anchor, "
          f"detection radius {detection_radius_m(args.mass_t):.0f} m at {THRESHOLD_NT:g} nT")
    for line in table(estimate(args.length_km, args.width_m, args.depth_m, args.mass_t)):
        print(" ", line)
    for note in NOTES:
        print(" ", note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
