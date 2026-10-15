"""Declared against actual: what the vessel says in AIS against what its track shows.

Two checks over the track up to ``context["now"]``:

* **Status against movement** (rule B9 in ``argus.levels``,
  ``status_mismatch``): the vessel reports "at anchor" or "moored" but has
  been moving for ``STATUS_MIN`` minutes or more: median SOG of at least
  ``STATUS_KN`` and ``STATUS_MOVED_NM`` covered. Near a line, ``cable_risk``
  scores the stronger anchor-drag pattern (B2) as well; this check holds
  anywhere.
* **Destination against course** (rule C3, ``route_inconsistent``): the
  declared destination names a port (``argus.detectors.places``), the vessel
  has been under way for the last ``ROUTE_WINDOW_S``, and over that time it
  steered more than ``ROUTE_OFF_DEG`` away from the port's bearing and opened
  the distance to it by ``ROUTE_OPENED_NM`` or more. Ships near a port
  manoeuvre and coastal routes bend, so the check is skipped within
  ``PORT_NM`` of any port at the start of the window and within
  ``DEST_NEAR_NM`` of the destination. A great-circle bearing ignores land: a
  route that must go round a headland can look wrong for a while, which is
  why the course must also open the distance for the whole hour.

An unresolved destination or a missing status gives nothing. Every threshold is
an assumption. A wrong status or an old destination is most often a crew data
entry slip; findings say "cause unknown".
"""

from __future__ import annotations

import math
from statistics import median

from argus.countdown import nm_between
from argus.detectors import places
from argus.prediction import bearing_deg

DETECTOR = "declared_vs_actual"

# Thresholds (assumptions).
STATUSES = {"1": "at anchor", "at anchor": "at anchor", "anchored": "at anchor", "5": "moored", "moored": "moored"}
STATUS_KN, STATUS_MIN, STATUS_MOVED_NM = 1.0, 10, 0.3
ROUTE_WINDOW_S = 60 * 60
ROUTE_MIN_FIXES = 5
ROUTE_KN = 5.0  # under way: median SOG over the window
ROUTE_OFF_DEG = 90  # steering further than this from the destination's bearing
ROUTE_OPENED_NM = 2.0  # and the distance to it grew at least this much
PORT_NM = 5.0  # leaving or entering a port bends the course
DEST_NEAR_NM = 20.0  # close to the destination ships manoeuvre to approach it


def _status(fix: dict, vessel: dict) -> str | None:
    value = fix.get("nav_status", vessel.get("nav_status"))
    return None if value is None else STATUSES.get(str(value).strip().lower())


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _mean_course(courses: list[float]) -> float:
    x = sum(math.cos(math.radians(c)) for c in courses)
    y = sum(math.sin(math.radians(c)) for c in courses)
    return math.degrees(math.atan2(y, x)) % 360


def status_mismatch(fixes: list[dict], vessel: dict) -> tuple[dict, list[str]]:
    """``status_mismatch`` and its reason when the latest run of anchored/moored fixes moves; else empty."""
    if not fixes:
        return {}, []
    status = _status(fixes[-1], vessel)
    if status is None:
        return {}, []
    run = []
    for fix in reversed(fixes):
        if _status(fix, vessel) != status:
            break
        run.append(fix)
    run.reverse()
    recent = [fix for fix in run if fix["t"] >= run[-1]["t"] - STATUS_MIN * 60]
    speeds = [fix["sog_kn"] for fix in recent if fix.get("sog_kn") is not None]
    if run[-1]["t"] - run[0]["t"] < STATUS_MIN * 60 or not speeds:
        return {}, []
    sog = median(speeds)
    moved = nm_between(recent[0]["lat"], recent[0]["lon"], recent[-1]["lat"], recent[-1]["lon"])
    if sog < STATUS_KN or moved < STATUS_MOVED_NM:
        return {}, []
    return {"status_mismatch": True}, [
        f"Reports '{status}' but moves at {sog:.1f} kn and covered {moved:.2f} nm in the last {STATUS_MIN} min "
        f"(rule: {STATUS_KN:g} kn or more and {STATUS_MOVED_NM:g} nm or more); cause unknown."]


def route_inconsistent(fixes: list[dict], vessel: dict, now: float, extra_ports=()) -> tuple[dict, list[str], dict]:
    """``route_inconsistent``, its reasons and the resolved port when the course leads away from it; else empty."""
    destination = vessel.get("destination")
    window = [fix for fix in fixes if fix["t"] >= now - ROUTE_WINDOW_S]
    if not destination or len(window) < ROUTE_MIN_FIXES or window[-1]["t"] - window[0]["t"] < 0.9 * ROUTE_WINDOW_S:
        return {}, [], {}
    first, last = window[0], window[-1]
    port = places.resolve_destination(destination, last["lat"], last["lon"])
    if port is None:
        return {}, [], {}
    speeds = [fix["sog_kn"] for fix in window if fix.get("sog_kn") is not None]
    courses = [fix["cog_deg"] for fix in window if fix.get("cog_deg") is not None]
    if not speeds or not courses or median(speeds) < ROUTE_KN:
        return {}, [], port
    near_start = places.nearest_port(first["lat"], first["lon"], extra_ports)
    if near_start and near_start[1] <= PORT_NM:
        return {}, [], port
    start_nm = nm_between(first["lat"], first["lon"], port["lat"], port["lon"])
    end_nm = nm_between(last["lat"], last["lon"], port["lat"], port["lon"])
    bearing = bearing_deg(last["lat"], last["lon"], port["lat"], port["lon"])
    course = _mean_course(courses)
    off = _angle(course, bearing)
    if end_nm <= DEST_NEAR_NM or off <= ROUTE_OFF_DEG or end_nm - start_nm < ROUTE_OPENED_NM:
        return {}, [], port
    minutes = (last["t"] - first["t"]) / 60
    return {"route_inconsistent": True}, [
        f"Declares destination '{destination}' ({port['name']}, {end_nm:.0f} nm away on bearing {bearing:.0f}°) "
        f"but held a mean course of {course:.0f}°, {off:.0f}° off, and moved {end_nm - start_nm:.1f} nm further "
        f"from it in {minutes:.0f} min (rule: more than {ROUTE_OFF_DEG}° off and {ROUTE_OPENED_NM:g} nm or more "
        f"further in {ROUTE_WINDOW_S // 60} min at {ROUTE_KN:g} kn or more); cause unknown.",
        f"Destination read as {port['how']}; the bearing is a straight line, not a charted route."], port


def declared_vs_actual(vessel: dict, context: dict) -> list[dict]:
    """One ``declared_vs_actual`` finding when the status or the destination contradicts the track; else none."""
    track = vessel.get("track") or []
    now = context.get("now")
    if now is None:
        now = track[-1]["t"] if track else None
    if now is None:
        return []
    fixes = [fix for fix in track if fix["t"] <= now and fix.get("lat") is not None]
    if not fixes:
        return []
    obs, reasons = status_mismatch(fixes, vessel)
    route_obs, route_reasons, port = route_inconsistent(fixes, vessel, now, context.get("ports"))
    obs.update(route_obs)
    reasons += route_reasons
    if not obs:
        return []
    last = fixes[-1]
    what = " and ".join(text for key, text in (("status_mismatch", "navigation status"),
                                               ("route_inconsistent", "declared destination")) if key in obs)
    verb = "contradict" if len(obs) == 2 else "contradicts"
    reasons.insert(0, f"Declared against actual, for review: the {what} {verb} the track.")
    related = {"declared_status": _status(last, vessel), "declared_destination": vessel.get("destination")}
    if route_obs:
        related["destination_port"] = {key: port[key] for key in ("name", "lat", "lon", "country")}
    return [{"detector": DETECTOR, "mmsi": vessel["mmsi"], "t": int(last["t"]), "position": [last["lat"], last["lon"]],
             "strength": 0.5 if len(obs) == 2 else 0.3, "reasons": reasons, "related": related,
             "label": vessel.get("label", "simulated"), "obs": obs}]


detect = declared_vs_actual  # the package convention; the function name labels the assessments file
