"""Cable risk from the recent track: behaviour and proximity per line, no AIS gap needed.

For every line in ``context["cables"]`` this detector reads the last three
hours of fixes up to ``context["now"]`` (six hours for passes, as rule B5 says)
and fills the ``argus.levels`` keys for that line:

* behaviour: anchor-drag pattern (B1: speed drop and course change, or a
  reduced speed held under way on a steady course away from ports), moving
  while reporting "at anchor" (B2), loitering (B4), repeated passes (B5), slow
  over the corridor (B6), anchored near the line (B7), bottom fishing (B10) and
  an unexplained slowdown (B11);
* proximity: ``in_corridor``, ``distance_nm`` and ``eta_min``, measured to the
  section where an anchor can reach the seabed. The projected crossing must lie
  on that section, not merely on a cable that has one. A dark vessel (no fix
  for 10 min) gets the worst-case ``earliest_possible_contact_s`` instead;
* the line: ``asset_class``, ``asset_vulnerable`` and ``method_possible``
  (False when only a section deeper than the anchor cutoff is near).

One finding per line the vessel is near, with ``related.cable_id``. A line
without a known depth (the illustrative routes) is assumed anchor-reachable
along its whole path, and the finding says so. Every threshold below is a team
assumption, not regulation or measured physics. Findings say "for review,
cause unknown"; they never state intent.
"""

from __future__ import annotations

import math
from statistics import median

from argus.countdown import _cross_fraction, nm_between, step
from argus.detectors.ais_spoofing import nearest_port_nm
from argus.levels import CRITICAL_ASSETS
from argus.prediction import (anchor_reachable_path, distance_to_path_nm, earliest_possible_contact_s,
                              v_max_kn)

DETECTOR = "cable_risk"

# Thresholds (assumptions).
WINDOW_S = 3 * 3600  # recent behaviour
PASSES_WINDOW_S = 6 * 3600  # rule B5 counts passes in 6 h
ANCHOR_REACH_CUTOFF_M = 250  # same cutoff as argus.brain
DARK_S = 10 * 60  # no fix for this long: the vessel is dark
NEAR_ETA_MIN, NEAR_NM = 360, 5.0  # a finding only for lines this close (P3 in argus.levels)
CORRIDOR_NM = 1.0
EARLIEST_SPEED_FACTOR = 1.2  # same as argus.brain's earliest ETA
HORIZON_S, LEG_S = 3 * 3600, 15 * 60  # same horizon as argus.countdown.project_to_cable, in 15 min legs
ETA_MIN_KN = 2.0  # slower, a projected course is noise (a drifting or circling ship): distance and corridor speak
BASELINE_GAP_S = 30 * 60  # baseline speed and course: fixes older than this...
BASELINE_MIN_FIXES = 5  # ...at least this many of them
BASELINE_MIN_KN = 5.0  # a slowdown needs a vessel that was under way
RECENT_S = 10 * 60  # current speed: median of these minutes
TURN_S = 30 * 60  # course change looked for in these minutes
DROP_PCT, TURN_DEG = 20, 20  # B1 and B11, as argus.levels scores them
DRAG_NEAR_NM, DRAG_NEAR_ETA_MIN = 5.0, 120  # B1 counts only this close to the section
DRAG_MIN_KN = 3.0  # B1 is a pattern under way (now and through the 30 min); slower is loitering (B4) or anchoring (B7)
# B1 without a turn: an anchor dragged behind a ship on its normal course. Public reporting on Eagle S gives
# only "12 to 9 kn"; any yaw is our assumption, so a steady course must not hide the pattern.
DRAG_HOLD_S = 15 * 60  # the reduced speed, still under way, held this long
PORT_EXCLUSION_NM = 5.0  # ships slow to enter or leave port, and cables land near ports: no steady-drag B1 here
SLOWDOWN_NM = 5.0  # B11
DRAG_ANCHOR_KN, DRAG_ANCHOR_NM, DRAG_ANCHOR_MOVED_NM = 0.5, 2.0, 0.2  # B2
LOITER_KN, LOITER_NM, LOITER_HOURS = 3.0, 2.0, 1.0  # B4
PASSES_MIN = 3  # B5
SLOW_KN, SLOW_MIN = 6.0, 10  # B6, in the 1 nm corridor
ANCHORED_KN, ANCHORED_HOLD_S = 0.5, 20 * 60  # B7: "at anchor" status, or this slow this long
FISHING_TYPE, FISHING_KN, FISHING_NM, FISHING_MIN = 30, (2.0, 5.0), 2.0, 30  # B10
MAX_INTERVAL_S = 120  # a longer gap between fixes adds at most this to a duration
GAP_S = 10 * 60  # a longer gap breaks a loiter or anchor hold
AT_ANCHOR = {"1", "at anchor", "anchored"}


def _asset_class(kind) -> str:
    """The line's kind as argus.levels names it; an unknown kind counts as telecom (as in legacy_cable_v1)."""
    return kind if kind == "telecom" or kind in CRITICAL_ASSETS else "telecom"


def reach_section(cable: dict) -> tuple[list, str]:
    """(path where an anchor can reach the seabed, why). Empty when the line is deeper than the cutoff."""
    depth = cable.get("min_depth_m")
    if depth is not None and depth > ANCHOR_REACH_CUTOFF_M:
        return [], f"minimum depth {depth:g} m is deeper than the assumed {ANCHOR_REACH_CUTOFF_M} m anchor reach"
    path = [list(point) for point in cable["path"]]
    if cable.get("anchor_reachable"):
        section = anchor_reachable_path(cable)
        return section, (f"anchor-reachable section (minimum depth {depth:g} m; {ANCHOR_REACH_CUTOFF_M} m reach "
                         "is an assumption)" if depth is not None else "marked anchor-reachable section")
    if depth is not None:
        return path, f"minimum depth {depth:g} m is within the assumed {ANCHOR_REACH_CUTOFF_M} m anchor reach"
    return path, "depth unknown on this illustrative route: assumed anchor-reachable along its whole path"


def _window(track: list[dict], now: float, span_s: float) -> list[dict]:
    return [fix for fix in track if now - span_s <= fix["t"] <= now and fix.get("lat") is not None]


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _mean_course(courses: list[float]) -> float:
    x = sum(math.cos(math.radians(c)) for c in courses)
    y = sum(math.sin(math.radians(c)) for c in courses)
    return math.degrees(math.atan2(y, x)) % 360


def _at_anchor(fix: dict, vessel: dict) -> bool:
    status = fix.get("nav_status", vessel.get("nav_status"))
    return status is not None and str(status).strip().lower() in AT_ANCHOR


def _minutes(fixes: list[dict], keep) -> float:
    """Minutes spent on fixes where ``keep(fix)``; each fix counts until the next, at most MAX_INTERVAL_S."""
    total = 0
    for a, b in zip(fixes, fixes[1:]):
        if keep(a):
            total += min(b["t"] - a["t"], MAX_INTERVAL_S)
    return total / 60


def _longest_run_s(fixes: list[dict], keep) -> float:
    """Longest unbroken span of fixes where ``keep(fix)``, broken by a gap over GAP_S."""
    best, start, last = 0, None, None
    for fix in fixes:
        if keep(fix) and (last is None or fix["t"] - last["t"] <= GAP_S):
            start = fix if start is None else start
            best = max(best, fix["t"] - start["t"])
        else:
            start = fix if keep(fix) else None
        last = fix
    return best


def speed_and_course(fixes: list[dict], now: float) -> dict | None:
    """Cruising vs current speed and the largest course change in the last TURN_S; None without a baseline.

    Cruising speed is the highest RECENT_S median before the last BASELINE_GAP_S, so the slowdown itself
    does not pull the baseline down; its course is the mean course of that stretch (the latest one when
    several are within 0.5 kn of the highest).
    """
    base = [f for f in fixes if f["t"] <= now - BASELINE_GAP_S and f.get("sog_kn") is not None]
    recent = [f for f in fixes if f["t"] > now - RECENT_S and f.get("sog_kn") is not None]
    if len(base) < BASELINE_MIN_FIXES or not recent:
        return None
    blocks = []
    for index, fix in enumerate(base):
        block = [f for f in base[:index + 1] if f["t"] >= fix["t"] - RECENT_S]
        blocks.append((median(f["sog_kn"] for f in block), block))
    top = max(speed for speed, _ in blocks)
    base_kn, block = next((speed, block) for speed, block in reversed(blocks) if speed >= top - 0.5)
    now_kn = median(f["sog_kn"] for f in recent)
    if base_kn < BASELINE_MIN_KN:
        return None
    course = _mean_course([f["cog_deg"] for f in block if f.get("cog_deg") is not None] or [0])
    window = [f for f in fixes if f["t"] > now - TURN_S and f.get("cog_deg") is not None]
    turning = [f["cog_deg"] for f in window]
    off_course = max((_angle(c, course) for c in turning), default=0)
    spread = max((_angle(a, b) for a in turning for b in turning), default=0)  # yaw within the last 30 min
    return {"base_kn": base_kn, "now_kn": now_kn, "drop_pct": (base_kn - now_kn) / base_kn * 100,
            "turn_deg": max(off_course, spread), "base_course": course,
            "turn_kn": median(f["sog_kn"] for f in window if f.get("sog_kn") is not None) if window else 0,
            "slow_run_s": _slow_run_s(fixes, base_kn)}


def _slow_run_s(fixes: list[dict], base_kn: float) -> float:
    """How long the track has stayed reduced but under way, up to its last fix.

    Reduced: at least DROP_PCT below the cruising speed; under way: above
    DRAG_MIN_KN. A gap over GAP_S or one fix outside the band ends the run.
    """
    ceiling = base_kn * (1 - DROP_PCT / 100)
    run_start = last = None
    for fix in reversed(fixes):
        sog = fix.get("sog_kn")
        if sog is None or not DRAG_MIN_KN < sog <= ceiling or (last is not None and last["t"] - fix["t"] > GAP_S):
            break
        run_start = fix
        last = fix
    return 0 if run_start is None else fixes[-1]["t"] - run_start["t"]


def _passes(fixes: list[dict], path: list) -> int:
    count = 0
    for a, b in zip(fixes, fixes[1:]):
        p, q = (a["lat"], a["lon"]), (b["lat"], b["lon"])
        if any(_cross_fraction(p, q, s, e) is not None for s, e in zip(path, path[1:])):
            count += 1
    return count


def crossing_s(lat: float, lon: float, course_deg: float, sog_kn: float, path: list,
               horizon_s: int = HORIZON_S, leg_s: int = LEG_S) -> int | None:
    """Seconds to the first crossing of ``path`` at constant course and speed within the horizon, else None.

    The same estimate as ``argus.countdown.project_to_cable`` on its local approximation, in 15 min legs
    instead of 60 s steps (they agree within about 15 s over 3 h), so ten lines a replay step stay cheap.
    """
    here = (lat, lon)
    for start in range(0, horizon_s, leg_s):
        span = min(leg_s, horizon_s - start)
        end = step(*here, course_deg, sog_kn * span / 3600)
        fractions = [fraction for a, b in zip(path, path[1:])
                     if (fraction := _cross_fraction(here, end, a, b)) is not None]
        if fractions:
            return int(start + min(fractions) * span)
        here = end
    return None


def eta_to(last: dict, path: list, now: float, track: list[dict]) -> tuple[float | None, str | None]:
    """Minutes from ``now`` to the earliest crossing of ``path``, and how it was estimated."""
    if not path:
        return None, None
    since = now - last["t"]
    if since > DARK_S:
        v_max = v_max_kn(track, last["t"])
        seconds = earliest_possible_contact_s(last, v_max, path) - since
        return max(0.0, seconds / 60), (f"dark {since // 60:.0f} min: worst case straight line at assumed "
                                        f"v_max {v_max:.0f} kn from the last fix")
    sog, cog = last.get("sog_kn"), last.get("cog_deg")
    if not sog or sog < ETA_MIN_KN or cog is None:
        return None, None
    earliest_s = crossing_s(last["lat"], last["lon"], cog, sog * EARLIEST_SPEED_FACTOR, path)
    if earliest_s is None:
        return None, None
    expected_s = crossing_s(last["lat"], last["lon"], cog, sog, path)
    expected = f"{(expected_s - since) / 60:.0f} min" if expected_s is not None else "beyond 3 h"
    return max(0.0, (earliest_s - since) / 60), (f"constant course {cog:.0f}° at {EARLIEST_SPEED_FACTOR}× "
                                                 f"{sog:.1f} kn (expected at observed speed: {expected})")


def _behaviour(vessel: dict, fixes: list[dict], passes_fixes: list[dict], path: list, dist: list[float],
               eta: float | None, now: float, motion: dict | None) -> tuple[dict, list[str]]:
    """Behaviour keys and reasons for one line; ``dist[i]`` is fix i's distance to ``path`` in nm.

    ``motion`` is the vessel's ``speed_and_course``, the same for every line.
    """
    obs, reasons = {}, []
    near = dict(zip((id(f) for f in fixes), dist))
    within = lambda nm: (lambda f: near[id(f)] <= nm)  # noqa: E731
    last_nm = dist[-1]

    if motion and motion["drop_pct"] >= DROP_PCT:
        close = last_nm <= DRAG_NEAR_NM or (eta is not None and eta <= DRAG_NEAR_ETA_MIN)
        under_way = min(motion["now_kn"], motion["turn_kn"]) > DRAG_MIN_KN  # yawed while under way, not circling
        port_nm = nearest_port_nm(fixes[-1]["lat"], fixes[-1]["lon"])
        near_port = port_nm is not None and port_nm <= PORT_EXCLUSION_NM
        steady = close and under_way and motion["slow_run_s"] >= DRAG_HOLD_S and not near_port
        if close and motion["turn_deg"] >= TURN_DEG and under_way:
            obs.update(speed_drop_pct=round(motion["drop_pct"]), course_change_deg=round(motion["turn_deg"]))
            reasons.append(f"Speed fell {motion['drop_pct']:.0f}% ({motion['base_kn']:.1f} → {motion['now_kn']:.1f} kn) "
                           f"and course varied {motion['turn_deg']:.0f}° in {TURN_S // 60} min "
                           f"(rule: ≥{DROP_PCT}% and ≥{TURN_DEG}° while under way above {DRAG_MIN_KN:g} kn) "
                           f"{last_nm:.1f} nm from the line; cause unknown.")
        elif steady:
            obs.update(drag_signature=True, speed_drop_pct=round(motion["drop_pct"]))
            if round(motion["turn_deg"]):
                obs["course_change_deg"] = round(motion["turn_deg"])
            reasons.append(f"Speed held {motion['drop_pct']:.0f}% below cruise ({motion['base_kn']:.1f} → "
                           f"{motion['now_kn']:.1f} kn) for {motion['slow_run_s'] / 60:.0f} min while under way on a "
                           f"steady course, {last_nm:.1f} nm from the line (rule: ≥{DROP_PCT}% for "
                           f"≥{DRAG_HOLD_S // 60} min above {DRAG_MIN_KN:g} kn, no turn needed, not within "
                           f"{PORT_EXCLUSION_NM:g} nm of a port); cause unknown.")
        elif last_nm <= SLOWDOWN_NM:
            obs["slowdown_near_corridor"] = True
            reasons.append(f"Speed fell {motion['drop_pct']:.0f}% ({motion['base_kn']:.1f} → {motion['now_kn']:.1f} kn) "
                           f"{last_nm:.1f} nm from the line (rule: ≥{DROP_PCT}% within {SLOWDOWN_NM:g} nm); "
                           "cause unknown.")
            if near_port and close and under_way and motion["slow_run_s"] >= DRAG_HOLD_S:
                reasons.append(f"Not scored as an anchor drag: {port_nm:.1f} nm from a port (within "
                               f"{PORT_EXCLUSION_NM:g} nm ships slow to enter or leave).")

    last = fixes[-1]
    recent = [f for f in fixes if f["t"] >= now - RECENT_S]
    if _at_anchor(last, vessel) and (last.get("sog_kn") or 0) >= DRAG_ANCHOR_KN and last_nm <= DRAG_ANCHOR_NM:
        moved = nm_between(recent[0]["lat"], recent[0]["lon"], last["lat"], last["lon"])
        if moved >= DRAG_ANCHOR_MOVED_NM:
            obs.update(dragging_at_anchor=True, sog_kn=last["sog_kn"])
            reasons.append(f"Reports 'at anchor' but moves {last['sog_kn']:.1f} kn and drifted {moved:.2f} nm in "
                           f"{RECENT_S // 60} min, {last_nm:.1f} nm from the line (rule: ≥{DRAG_ANCHOR_KN} kn, "
                           f"≥{DRAG_ANCHOR_MOVED_NM} nm, within {DRAG_ANCHOR_NM:g} nm); cause unknown.")

    def loitering(f):
        return (f.get("sog_kn") or 0) <= LOITER_KN and near[id(f)] <= LOITER_NM and not _at_anchor(f, vessel)
    loiter_h = _longest_run_s(fixes, loitering) / 3600
    if loiter_h >= LOITER_HOURS:
        obs["loiter_hours"] = round(loiter_h, 1)
        reasons.append(f"Held at {LOITER_KN:g} kn or less within {LOITER_NM:g} nm of the line for {loiter_h:.1f} h "
                       f"(rule: ≥{LOITER_HOURS:g} h); cause unknown.")

    passes = _passes(passes_fixes, path)
    if passes >= PASSES_MIN:
        obs["passes_6h"] = passes
        reasons.append(f"Crossed the line {passes}× in {PASSES_WINDOW_S // 3600} h (rule: ≥{PASSES_MIN}); "
                       "cause unknown.")

    slow_min = _minutes(fixes, lambda f: (f.get("sog_kn") or 0) <= SLOW_KN and within(CORRIDOR_NM)(f)
                        and not _at_anchor(f, vessel))  # at anchor is B7
    if slow_min >= SLOW_MIN:
        obs["slow_over_corridor_min"] = round(slow_min)
        reasons.append(f"{slow_min:.0f} min at {SLOW_KN:g} kn or less inside the {CORRIDOR_NM:g} nm corridor "
                       f"(rule: ≥{SLOW_MIN} min); cause unknown.")

    still = _longest_run_s(fixes, lambda f: (f.get("sog_kn") or 0) < ANCHORED_KN)
    anchored = (_at_anchor(last, vessel) and (last.get("sog_kn") or 0) < DRAG_ANCHOR_KN) or (
        still >= ANCHORED_HOLD_S and (last.get("sog_kn") or 0) < ANCHORED_KN)
    if anchored and last_nm <= CORRIDOR_NM:
        obs["anchored_near_cable"] = True
        reasons.append(f"At anchor {last_nm:.2f} nm from the line (rule: within {CORRIDOR_NM:g} nm).")

    if str(vessel.get("ship_type")) == str(FISHING_TYPE):
        low, high = FISHING_KN
        fishing_min = _minutes(fixes, lambda f: low <= (f.get("sog_kn") or 0) <= high and within(FISHING_NM)(f))
        if fishing_min >= FISHING_MIN:
            obs["fishing_near_corridor"] = True
            reasons.append(f"Fishing vessel at trawling speed ({low:g}-{high:g} kn) for {fishing_min:.0f} min within "
                           f"{FISHING_NM:g} nm (rule: ≥{FISHING_MIN} min); cause unknown.")
    return obs, reasons


def _line_finding(vessel: dict, cable: dict, fixes: list[dict], passes_fixes: list[dict], now: float,
                  motion: dict | None) -> dict | None:
    last = fixes[-1]
    section, depth_note = reach_section(cable)
    full = [list(point) for point in cable["path"]]
    eta, method = eta_to(last, section, now, fixes)
    reach_nm = distance_to_path_nm(last["lat"], last["lon"], section)[0] if section else math.inf
    feasible = reach_nm <= NEAR_NM or (eta is not None and eta <= NEAR_ETA_MIN)
    path = section if feasible else full
    if not feasible:
        eta, method = eta_to(last, full, now, fixes)
        nm = distance_to_path_nm(last["lat"], last["lon"], full)[0]
        if nm > NEAR_NM and (eta is None or eta > NEAR_ETA_MIN):
            return None
        if section:
            depth_note = f"only the line outside its {depth_note} is near"
    dist = [distance_to_path_nm(f["lat"], f["lon"], path)[0] for f in fixes]
    obs, reasons = _behaviour(vessel, fixes, passes_fixes, path, dist, eta, now, motion)
    distance_nm, closest = distance_to_path_nm(last["lat"], last["lon"], path)
    name = cable.get("name", cable["id"])
    obs.update(distance_nm=round(distance_nm, 2), asset_class=_asset_class(cable.get("kind")),
               method_possible=feasible)
    if distance_nm <= CORRIDOR_NM:
        obs["in_corridor"] = True
    if eta is not None:
        obs["eta_min"] = round(eta, 1)
    if cable.get("asset_vulnerable") or cable.get("vulnerable"):
        obs["asset_vulnerable"] = True
    cues = len(reasons)
    where = (f"inside the {CORRIDOR_NM:g} nm corridor" if obs.get("in_corridor")
             else f"{distance_nm:.1f} nm from the line")
    summary = (f"Cable risk, for review: {cues} behaviour cue(s) near {name}, {where}; cause unknown."
               if cues else f"Near {name} ({where}) with no behaviour cue; proximity alone does not raise the level.")
    reasons.insert(0, summary)
    if eta is not None:
        reasons.append(f"Earliest crossing of the {'anchor-reachable section' if feasible else 'line'} in "
                       f"{eta:.0f} min: {method}. A planning estimate, not a prediction of intent.")
    reasons.append(("Anchor can reach the seabed here: " if feasible else "Damage by anchor unlikely here: ")
                   + depth_note + ".")
    return {"detector": DETECTOR, "mmsi": vessel["mmsi"], "t": int(now), "position": [last["lat"], last["lon"]],
            "strength": round(min(0.9, 0.3 + 0.2 * cues), 2) if cues else 0.1, "reasons": reasons,
            "related": {"cable_id": cable["id"], "closest_point": [round(closest[0], 5), round(closest[1], 5)],
                        "section": "anchor-reachable" if feasible else "too deep for an anchor"},
            "label": vessel.get("label", "simulated"), "obs": obs}


def cable_risk(vessel: dict, context: dict) -> list[dict]:
    """One ``cable_risk`` finding per line the vessel is near; none when it is far from every line."""
    track = vessel.get("track") or []
    now = context.get("now")
    if now is None:
        now = track[-1]["t"] if track else None
    if now is None:
        return []
    passes_fixes = _window(track, now, PASSES_WINDOW_S)
    fixes = [fix for fix in passes_fixes if fix["t"] >= now - WINDOW_S]
    if not fixes:
        return []
    findings, motion = [], speed_and_course(fixes, now)
    for cable in context.get("cables", []):
        if len(cable.get("path") or []) < 2:
            continue
        finding = _line_finding(vessel, cable, fixes, passes_fixes, now, motion)
        if finding:
            findings.append(finding)
    return findings


detect = cable_risk  # the package convention; the function name labels the assessments file
