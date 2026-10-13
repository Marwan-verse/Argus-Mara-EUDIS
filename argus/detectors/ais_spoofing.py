"""Possible AIS spoofing: positions a real ship cannot physically produce.

Five checks run over one cleaned, time-ordered track:

a) ``jump_events``: an impossible jump between neighbouring fixes, or a single
   fix that jumps away and straight back (an outlier);
b) ``speed_mismatch_events``: the declared SOG disagrees with the speed the
   positions imply, several pairs in a row;
c) ``land_events``: a position well inside land, away from the coast and ports;
d) ``two_places_events``: one MMSI alternating between two far-apart places,
   as if two transmitters shared it;
e) ``reappearance_events``: a return after an AIS gap outside the reachable
   circle of ``argus.prediction.reappearance_check``.

One GPS glitch is normal, so ``persistence`` decides whether the events set
``spoof_signs`` (rule I2 in ``argus.levels``). Otherwise the finding stays a
weak cue without it. Every threshold below is an assumption, not a regulation
or a measured error rate. Findings say "possible spoofing, for review", never
that spoofing is confirmed.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from argus.countdown import NM_PER_DEG, nm_between
from argus.prediction import V_MAX_LOOKBACK_S, reappearance_check, v_max_kn

ROOT = Path(__file__).resolve().parents[2]
LAND_PATH = ROOT / "ui/assets/world_land.json"
PORTS_PATH = ROOT / "ui/assets/world_ports.json"
LAND_LEVEL = "50m"

# Thresholds (assumptions). They aim at what is physically impossible, not merely unusual.
JUMP_MIN_KN = 50.0  # no merchant or fishing vessel sustains 50 kn...
JUMP_SOG_FACTOR = 3.0  # ...nor three times its own declared speed
JUMP_MIN_NM = 1.0  # shorter steps can be GPS jitter
GAP_S = 10 * 60  # neighbours this far apart are an AIS gap, judged by check e) instead of a)
SPEED_DIFF_KN = 5.0
SPEED_PAIRS = 3
SPEED_MIN_S, SPEED_MAX_S = 30, 10 * 60  # closer fixes amplify GPS noise; farther ones hide turns
COAST_MARGIN_NM = 1.0  # the 1:50m coastline is coarse
PORT_MARGIN_NM = 2.0  # port points are not berths; docks and rivers can fall inside the land outline
TWO_PLACES_WINDOW_S = 30 * 60
REAPPEAR_MARGIN_NM = 1.0
PERSIST_EVENTS, PERSIST_WINDOW_S = 2, 60 * 60
STRONG_NM = 5.0
SOG_NOT_AVAILABLE = 102.3  # AIS value for "speed not available"
WEAK_STRENGTH = 0.25
MAX_EVENT_REASONS = 5
GRID_DEG = 0.5  # land and port lookup cells

DETECTOR = "ais_spoofing"


def clean_track(track: list[dict], now: float | None = None) -> list[dict]:
    """Fixes up to ``now`` with a usable position; SOG 102.3 or more ("not available") becomes None.

    AIS "position not available" (lat 91, lon 181) and the 0, 0 default are dropped.
    """
    fixes = []
    for fix in track:
        if now is not None and fix["t"] > now:
            break
        lat, lon = fix.get("lat"), fix.get("lon")
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        sog = fix.get("sog_kn")
        if sog is not None and not 0 <= sog < SOG_NOT_AVAILABLE:
            sog = None
        fixes.append({**fix, "sog_kn": sog})
    return fixes


def steps_between(fixes: list[dict]) -> list[dict]:
    """One entry per neighbouring pair: elapsed time, distance, implied and declared speed, jump flag."""
    steps = []
    for a, b in zip(fixes, fixes[1:]):
        dt = b["t"] - a["t"]
        nm = nm_between(a["lat"], a["lon"], b["lat"], b["lon"])
        kn = nm / (dt / 3600) if dt > 0 else math.inf
        declared = [fix["sog_kn"] for fix in (a, b) if fix["sog_kn"] is not None]
        limit = max(JUMP_MIN_KN, JUMP_SOG_FACTOR * max(declared, default=0))
        steps.append({"dt": dt, "nm": nm, "kn": kn, "limit": limit,
                      "sog": sum(declared) / len(declared) if declared else None,
                      "jump": dt < GAP_S and nm > JUMP_MIN_NM and kn > limit})
    return steps


def _event(kind: str, fix: dict, distance_nm: float | None, reason: str) -> dict:
    return {"kind": kind, "t": fix["t"], "position": [fix["lat"], fix["lon"]],
            "distance_nm": None if distance_nm is None else round(distance_nm, 2), "reason": reason}


def _v_max(fixes: list[dict], index: int) -> float:
    """``argus.prediction.v_max_kn`` over the hour before ``fixes[index]`` only, so the pass stays linear."""
    t, start = fixes[index]["t"], index
    while start > 0 and fixes[start - 1]["t"] >= t - V_MAX_LOOKBACK_S:
        start -= 1
    return v_max_kn(fixes[start:index + 1], t)


def _jump_text(step: dict) -> str:
    return (f"{step['nm']:.1f} nm in {step['dt']:.0f} s implies {step['kn']:.0f} kn; "
            f"limit {step['limit']:.0f} kn")


def _chains(fixes: list[dict], steps: list[dict]) -> list[list[tuple[int, int]]]:
    """Impossible jumps that come back, grouped into chains.

    A return is a pair of consecutive jumps ``(i, j)`` where the fix after jump
    ``j`` is reachable from the fix before jump ``i`` within 30 min: the track
    went somewhere impossible and came back. Returns that share a jump
    (A -> B -> A -> B) form one chain.
    """
    jumps = [index for index, step in enumerate(steps) if step["jump"]]
    chains: list[list[tuple[int, int]]] = []
    for i, j in zip(jumps, jumps[1:]):
        before, back = fixes[i], fixes[j + 1]
        elapsed = back["t"] - before["t"]
        reach = _v_max(fixes, i) * elapsed / 3600 + JUMP_MIN_NM
        if elapsed > TWO_PLACES_WINDOW_S or nm_between(before["lat"], before["lon"], back["lat"], back["lon"]) > reach:
            continue
        if chains and chains[-1][-1][1] == i:
            chains[-1].append((i, j))
        else:
            chains.append([(i, j)])
    return chains


def _is_two_places(chain: list[tuple[int, int]]) -> bool:
    """Two or more returns in a row, or one away stay of two or more self-consistent fixes."""
    return len(chain) >= 2 or chain[0][1] - chain[0][0] >= 2


def jump_events(fixes: list[dict], steps: list[dict]) -> list[dict]:
    """Check a): impossible jumps. A single fix that jumps away and straight back is one outlier event.

    Jumps that belong to a two-places pattern are left to ``two_places_events``.
    """
    events, used = [], set()
    for chain in _chains(fixes, steps):
        used.update(index for pair in chain for index in pair)
        if _is_two_places(chain):
            continue
        i = chain[0][0]
        events.append(_event("outlier", fixes[i + 1], steps[i]["nm"],
                             f"One fix {steps[i]['nm']:.1f} nm off the track and straight back "
                             f"(moved {_jump_text(steps[i])}); a single outlier, possibly a GPS glitch."))
    for index, step in enumerate(steps):
        if step["jump"] and index not in used:
            events.append(_event("jump", fixes[index + 1], step["nm"],
                                 f"Impossible position jump of {_jump_text(step)}."))
    return events


def two_places_events(fixes: list[dict], steps: list[dict]) -> list[dict]:
    """Check d): positions alternate between two far-apart places, as if two transmitters shared one MMSI."""
    events = []
    for chain in _chains(fixes, steps):
        if not _is_two_places(chain):
            continue
        jumps = sorted({index for pair in chain for index in pair})
        span_min = (fixes[jumps[-1] + 1]["t"] - fixes[jumps[0]]["t"]) / 60
        apart = max(steps[index]["nm"] for index in jumps)
        events.append(_event("two_places", fixes[jumps[0] + 1], apart,
                             f"Positions alternate between two places up to {apart:.1f} nm apart: {len(jumps)} "
                             f"impossible jumps with return in {span_min:.0f} min (limit {JUMP_MIN_KN:.0f} kn); "
                             "possibly two transmitters using one MMSI."))
    return events


def speed_mismatch_events(fixes: list[dict], steps: list[dict]) -> list[dict]:
    """Check b): declared SOG and position-derived speed differ by more than 5 kn in 3 pairs in a row.

    Pairs closer than 30 s are skipped (GPS noise dominates); pairs over 10 min,
    jumps and pairs without a declared speed break the run.
    """
    events, run, worst, end = [], 0, None, 0

    def close():
        if run >= SPEED_PAIRS:
            events.append(_event("speed_mismatch", fixes[end], None,
                                 f"Declared speed and position-derived speed differ by more than "
                                 f"{SPEED_DIFF_KN:g} kn in {run} fix pairs in a row (worst: declared "
                                 f"{worst['sog']:.1f} kn, positions imply {worst['kn']:.1f} kn)."))

    for index, step in enumerate(steps):
        if step["dt"] < SPEED_MIN_S and not step["jump"]:
            continue
        if (step["dt"] <= SPEED_MAX_S and not step["jump"] and step["sog"] is not None
                and abs(step["sog"] - step["kn"]) > SPEED_DIFF_KN):
            run, end = run + 1, index + 1
            if worst is None or abs(step["sog"] - step["kn"]) > abs(worst["sog"] - worst["kn"]):
                worst = step
            continue
        close()
        run, worst = 0, None
    close()
    return events


def _cell(value: float) -> int:
    return math.floor(value / GRID_DEG)


@lru_cache(maxsize=1)
def _land_index() -> tuple[dict, dict]:
    """Natural Earth land edges bucketed by grid cell, and by grid row for ray casting."""
    rings = json.loads(LAND_PATH.read_text(encoding="utf-8"))["levels"][LAND_LEVEL]
    cells: dict[tuple[int, int], list] = {}
    rows: dict[int, list] = {}
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (x1, y1) == (x2, y2):
                continue
            edge = (x1, y1, x2, y2)
            for row in range(_cell(min(y1, y2)), _cell(max(y1, y2)) + 1):
                rows.setdefault(row, []).append(edge)
                for col in range(_cell(min(x1, x2)), _cell(max(x1, x2)) + 1):
                    cells.setdefault((row, col), []).append(edge)
    return cells, rows


@lru_cache(maxsize=None)
def _centre_on_land(row: int, col: int) -> bool:
    """Even-odd ray cast eastwards from the cell centre; only edges in its grid row can cross the ray."""
    y, x = (row + 0.5) * GRID_DEG, (col + 0.5) * GRID_DEG
    inside = False
    for x1, y1, x2, y2 in _land_index()[1].get(row, ()):
        if (y1 > y) != (y2 > y) and x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
            inside = not inside
    return inside


def _side(px, py, qx, qy, rx, ry) -> bool:
    return (qx - px) * (ry - py) - (qy - py) * (rx - px) > 0


def _crosses(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    return (_side(ax, ay, bx, by, cx, cy) != _side(ax, ay, bx, by, dx, dy)
            and _side(cx, cy, dx, dy, ax, ay) != _side(cx, cy, dx, dy, bx, by))


def on_land(lat: float, lon: float) -> bool:
    """Inside the 1:50m land outline.

    The cell centre's answer is cached; the point flips it once per coast edge
    between the two. Most sea cells hold no edge and answer from the cache.
    """
    row, col = _cell(lat), _cell(lon)
    inside = _centre_on_land(row, col)
    cy, cx = (row + 0.5) * GRID_DEG, (col + 0.5) * GRID_DEG
    for x1, y1, x2, y2 in _land_index()[0].get((row, col), ()):
        if _crosses(cx, cy, lon, lat, x1, y1, x2, y2):
            inside = not inside
    return inside


def _segment_nm(lat, lon, x1, y1, x2, y2) -> float:
    scale = NM_PER_DEG * math.cos(math.radians(lat))
    ax, ay, bx, by = (x1 - lon) * scale, (y1 - lat) * NM_PER_DEG, (x2 - lon) * scale, (y2 - lat) * NM_PER_DEG
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    share = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * (bx - ax) + ay * (by - ay)) / length2))
    return math.hypot(ax + share * (bx - ax), ay + share * (by - ay))


def _around(index: dict, lat: float, lon: float):
    row, col = _cell(lat), _cell(lon)
    for r in (row - 1, row, row + 1):
        for c in (col - 1, col, col + 1):
            yield from index.get((r, c), ())


def coast_nm(lat: float, lon: float) -> float:
    """Distance to the nearest coast edge in this and the eight neighbouring cells.

    Exact up to one cell width (about 18 nm off Ireland); beyond that it returns
    the cell width, a lower bound, because a nearer edge may lie further out.
    """
    bound = GRID_DEG * NM_PER_DEG * math.cos(math.radians(lat))
    return min([bound] + [_segment_nm(lat, lon, *edge) for edge in _around(_land_index()[0], lat, lon)])


@lru_cache(maxsize=1)
def _port_index() -> dict:
    index: dict[tuple[int, int], list] = {}
    for _wpi, _name, lat, lon, _country in json.loads(PORTS_PATH.read_text(encoding="utf-8"))["ports"]:
        index.setdefault((_cell(lat), _cell(lon)), []).append((lat, lon))
    return index


def nearest_port_nm(lat: float, lon: float) -> float | None:
    """Distance to the nearest World Port Index port in this and the neighbouring cells, if any."""
    return min((nm_between(lat, lon, *port) for port in _around(_port_index(), lat, lon)), default=None)


def inland_nm(lat: float, lon: float) -> float | None:
    """Depth inside land, or None at sea, within 1 nm of the coast or within 2 nm of a port."""
    if not on_land(lat, lon):
        return None
    depth, port = coast_nm(lat, lon), nearest_port_nm(lat, lon)
    if depth <= COAST_MARGIN_NM or (port is not None and port <= PORT_MARGIN_NM):
        return None
    return depth


def _land_reason(fix: dict, depth: float) -> str:
    return (f"Position {fix['lat']:.3f}, {fix['lon']:.3f} lies {depth:.1f} nm inside land (Natural Earth "
            f"1:{LAND_LEVEL}), over {COAST_MARGIN_NM:g} nm from the coast and over {PORT_MARGIN_NM:g} nm "
            "from any listed port.")


def land_events(fixes: list[dict]) -> list[dict]:
    """Check c): fixes well inside land. A run of them in a row is one event, reported at its deepest fix."""
    events, current = [], None
    for fix in fixes:
        depth = inland_nm(fix["lat"], fix["lon"])
        if depth is None:
            current = None
        elif current is None:
            current = _event("on_land", fix, depth, _land_reason(fix, depth))
            events.append(current)
        elif depth > current["distance_nm"]:
            current.update(position=[fix["lat"], fix["lon"]], distance_nm=round(depth, 2),
                           reason=_land_reason(fix, depth))
    return events


def reappearance_events(fixes: list[dict], steps: list[dict]) -> list[dict]:
    """Check e): after a gap of 10 min or more, the return lies over 1 nm outside the reachable circle."""
    events = []
    for index, step in enumerate(steps):
        if step["dt"] < GAP_S:
            continue
        check = reappearance_check(fixes[index], fixes[index + 1], _v_max(fixes, index))
        excess = check["distance_nm"] - check["reachable_nm"]
        if check["verdict"] == "physically_inconsistent" and excess > REAPPEAR_MARGIN_NM:
            events.append(_event("reappearance", fixes[index + 1], excess,
                                 f"After a {step['dt'] / 60:.0f} min AIS gap: {check['note']}"))
    return events


def persistence(events: list[dict]) -> str | None:
    """Why the events count as a spoofing sign, or None when they may be one glitch.

    A sign: a two-places pattern; any event over 5 nm except a single outlier
    (which needs a second event); or 2 events at different times within 60 min.
    """
    if any(event["kind"] == "two_places" for event in events):
        return "one identity reported in two places"
    far = [event for event in events if event["kind"] != "outlier" and (event["distance_nm"] or 0) > STRONG_NM]
    if far:
        return f"an event over {STRONG_NM:g} nm ({far[0]['distance_nm']:.1f} nm)"
    times = sorted({event["t"] for event in events})
    for first, last in zip(times, times[PERSIST_EVENTS - 1:]):
        if last - first <= PERSIST_WINDOW_S:
            return f"{PERSIST_EVENTS} or more events within {PERSIST_WINDOW_S // 60} min"
    return None


def ais_spoofing(vessel: dict, context: dict) -> list[dict]:
    """One ``ais_spoofing`` finding per vessel with physically impossible positions; none for a clean track."""
    fixes = clean_track(vessel.get("track") or [], context.get("now"))
    steps = steps_between(fixes)
    events = (jump_events(fixes, steps) + two_places_events(fixes, steps) + speed_mismatch_events(fixes, steps)
              + land_events(fixes) + reappearance_events(fixes, steps))
    if not events:
        return []
    events.sort(key=lambda event: event["t"])
    lead = max(events, key=lambda event: (event["kind"] == "two_places", event["distance_nm"] or 0))
    why = persistence(events)
    if why:
        summary = f"Possible AIS spoofing, for review: {len(events)} inconsistent position event(s); {why}."
        strength = 0.9 if lead["kind"] == "two_places" else min(0.9, 0.5 + 0.1 * len(events))
    else:
        summary = (f"{len(events)} isolated event(s), possibly a GPS glitch: not a spoofing sign under the rule "
                   f"({PERSIST_EVENTS} events within {PERSIST_WINDOW_S // 60} min, or one over {STRONG_NM:g} nm). "
                   "For review.")
        strength = WEAK_STRENGTH
    reasons = [summary] + [event["reason"] for event in events[:MAX_EVENT_REASONS]]
    if len(events) > MAX_EVENT_REASONS:
        reasons.append(f"...and {len(events) - MAX_EVENT_REASONS} more event(s).")
    return [{
        "detector": DETECTOR, "mmsi": vessel["mmsi"], "t": lead["t"], "position": lead["position"],
        "strength": strength, "reasons": reasons,
        "related": {"events": [{key: event[key] for key in ("kind", "t", "position", "distance_nm")}
                               for event in events]},
        "label": vessel.get("label", "simulated"), "obs": {"spoof_signs": True} if why else {},
    }]


detect = ais_spoofing  # the package convention; the function name labels the assessments file
