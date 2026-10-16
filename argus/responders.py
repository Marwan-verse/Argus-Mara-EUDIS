"""Who can get eyes on a moving vessel, and who gets there before it can reach a line.

For every asset in ``argus/fleet.json`` this module finds the first time ``t``
(searched in 60 s steps) at which

    readiness + distance(base -> vessel position at t) / speed <= t - now,

so the intercept follows the vessel while it moves, including a dark vessel
whose position is a prediction. An asset is *in time* when it arrives before the
earliest time the vessel can reach the line (``deadline_s``).

* Only physical assets (``counts`` in the fleet file: aircraft, helicopters,
  the patrol ship, drones) decide ``no_response_in_time``. A VHF hail and the
  next satellite look are listed but never count: a hail is not an intercept
  and a satellite only looks.
* The next satellite look comes from ESA's published Sentinel-1 acquisition
  plan (``argus.s1_plan``, D87): the first planned swath that covers where the
  vessel is predicted to be when the satellite passes (at most ``HORIZON_S``
  ahead; a later pass uses that position). Replay seconds count from the
  scenario's ``t0_utc``, which ``load_fleet`` hands to the plan.
* Drones are grounded above their wind limit; the wind is an exercise value,
  never live weather (``argus.weather`` does not change ETAs).
* An asset assigned to another incident is unavailable ("assigned to INC-...").
* A vessel already at the line (deadline now or past) has nobody "in time" by
  definition; that is not ``no_response_in_time``, because the corridor rules
  in ``argus.levels`` already score it.

Every speed, readiness, range and position is an assumption on the local flat
approximation of ``argus.countdown`` (planning estimates, not navigation).
Times are replay seconds; positions are (latitude, longitude).
"""

from __future__ import annotations

import json
from pathlib import Path

from argus import s1_plan
from argus.countdown import nm_between, step

FLEET_PATH = Path(__file__).with_name("fleet.json")
STEP_S = 60
COARSE_S = 600  # Assumption: search in 10 min strides, then refine to 60 s inside the stride.
HORIZON_S = 4 * 3600
KIND_SHORT = {"aircraft": "Aircraft", "helicopter": "Helicopter", "ship": "Patrol ship", "drone": "Drone",
              "hail": "VHF", "satellite": "Satellite"}


def load_fleet(path: Path = FLEET_PATH, t0_utc: str | None = None) -> dict:
    """The fleet file; ``t0_utc`` (the replay clock's start) lets a planned satellite look use real UTC."""
    fleet = json.loads(Path(path).read_text(encoding="utf-8"))
    if t0_utc:
        for asset in fleet["assets"]:
            if asset["kind"] == "satellite" and asset.get("plan"):
                asset["t0_utc"] = t0_utc
    return fleet


def dead_reckoning(lat: float, lon: float, cog_deg, sog_kn, t0: float):
    """Position function for a contact without a timed track: constant course and speed from (lat, lon) at t0."""
    def position(t: float):
        if not sog_kn or cog_deg is None:
            return lat, lon
        return step(lat, lon, cog_deg, sog_kn * (t - t0) / 3600)
    return position


def _reach_s(asset: dict, here) -> float:
    return asset["readiness_min"] * 60 + nm_between(asset["lat"], asset["lon"], *here) / asset["speed_kn"] * 3600


def intercept(asset: dict, position, start: float, horizon_s: int = HORIZON_S):
    """First (seconds after ``start``, meeting point) where the asset reaches the vessel, else (None, closest nm).

    A position farther than the asset's range from its base is never a meeting point.
    """
    limit = asset.get("range_nm")
    closest = float("inf")

    def ok(elapsed):
        nonlocal closest
        here = position(start + elapsed)
        if here is None:
            return None
        distance = nm_between(asset["lat"], asset["lon"], *here)
        closest = min(closest, distance)
        if limit is not None and distance > limit:
            return None
        return here if _reach_s(asset, here) <= elapsed else None

    first = int(asset["readiness_min"] * 60 // STEP_S * STEP_S)
    previous = first - STEP_S
    for coarse in range(first, horizon_s + 1, COARSE_S):
        if ok(coarse) is not None:
            for fine in range(max(first, previous + STEP_S), coarse + 1, STEP_S):
                meet = ok(fine)
                if meet is not None:
                    return fine, meet
        previous = coarse
    return None, closest


def _row(asset: dict, **values) -> dict:
    return {"id": asset["id"], "name": asset["name"], "kind": asset["kind"], "counts": bool(asset.get("counts")),
            "base": asset.get("base"), "lat": asset.get("lat"), "lon": asset.get("lon"),
            "label": asset.get("label", "assumption"), "eta_s": None, "meet": None, "in_time": None,
            "margin_s": None, "status": None, "reason": None, **values}


def assess_asset(asset: dict, position, now: float, deadline_s=None, wind_kn: float = 0,
                 busy: dict | None = None, incident_id: str | None = None, dispatched_t=None) -> dict:
    """One asset's answer for one vessel: eyes-on time, in time or not, or unavailable and why.

    ``busy`` maps asset ID to the incident it is assigned to. For the asset
    assigned to this incident, ``dispatched_t`` is when it was sent; its ETA
    then counts from that time, not from ``now``.
    """
    owner = (busy or {}).get(asset["id"])
    if owner is not None and owner != incident_id:
        # Busy elsewhere; keep whether it would have arrived in time, so only a real conflict is blamed.
        free = assess_asset(asset, position, now, deadline_s, wind_kn)
        return _row(asset, status="unavailable", reason=f"assigned to {owner}",
                    would_be_in_time=bool(free["in_time"]))
    if asset["kind"] == "drone" and wind_kn > asset.get("max_wind_kn", float("inf")):
        return _row(asset, status="unavailable",
                    reason=f"wind {wind_kn:g} kn above the {asset['max_wind_kn']:g} kn drone limit")
    start = dispatched_t if owner is not None and dispatched_t is not None else now
    named = {}
    if asset["kind"] == "satellite" and asset.get("plan"):
        if not asset.get("t0_utc"):
            return _row(asset, status="unavailable", reason="no replay clock for the Sentinel-1 plan")
        # Where the vessel is predicted to be when the satellite passes, at most HORIZON_S ahead like
        # every other asset; a later pass uses that position, not days of dead reckoning.
        look = s1_plan.replay_look(lambda t: position(min(t, start + HORIZON_S)), now, asset["t0_utc"])
        if look is None:
            return _row(asset, status="unavailable",
                        reason=s1_plan.no_look_reason(s1_plan.epoch(asset["t0_utc"]) + now))
        arrive, meet = look["t_s"], (look["lat"], look["lon"])
        named = {"name": s1_plan.row_name(look, s1_plan.epoch(asset["t0_utc"]) + now), "label": s1_plan.LABEL,
                 "look": {key: look[key] for key in ("satellite", "mode", "time_utc", "swath", "edge_km",
                                                     "frames_online_utc", "plan_file")}}
    elif asset["kind"] == "satellite":
        passes = [t for t in asset.get("pass_times_s", []) if t >= now]
        if not passes:
            return _row(asset, status="unavailable", reason="no pass scheduled")
        arrive = min(passes)
        meet = position(arrive)
    elif asset["kind"] == "hail":
        arrive = start + asset["readiness_min"] * 60
        meet = position(arrive)
        distance = nm_between(asset["lat"], asset["lon"], *meet) if meet else float("inf")
        if distance > asset["range_nm"]:
            return _row(asset, status="unavailable",
                        reason=f"out of VHF range ({distance:.0f} nm, limit {asset['range_nm']:g} nm)")
    else:
        elapsed, meet = intercept(asset, position, start)
        if elapsed is None:
            limit = asset.get("range_nm")
            if limit is not None and meet > limit:
                reason = f"out of range ({meet:.0f} nm from base, limit {limit:g} nm)"
            else:
                reason = f"cannot reach within {HORIZON_S // 3600} h"
            return _row(asset, status="unavailable", reason=reason)
        arrive = start + elapsed
    eta = max(0, int(arrive - now))
    meet = [round(meet[0], 5), round(meet[1], 5)] if meet else None
    if deadline_s is None:
        return _row(asset, status="assigned" if owner is not None else "eyes_on", eta_s=eta, meet=meet, **named)
    margin = int(deadline_s - arrive)
    status = "assigned" if owner is not None else ("in_time" if margin >= 0 else "late")
    return _row(asset, status=status, eta_s=eta, meet=meet, in_time=margin >= 0, margin_s=margin, **named)


def assess_fleet(fleet: dict, position, now: float, deadline_s=None, wind_kn: float = 0,
                 busy: dict | None = None, incident_id: str | None = None, dispatched: dict | None = None,
                 at_line_text: str = "vessel already at the line") -> dict:
    """Every asset's answer for one vessel, the best physical responder and the ``no_response_in_time`` flag.

    ``deadline_s`` is the replay time of the earliest possible line contact
    (None when the vessel is not approaching a line). ``at_line_text`` says why
    nobody can be in time once that moment has come: the vessel is in the
    corridor, or only its earliest possible ETA has passed.
    """
    rows = [assess_asset(asset, position, now, deadline_s, wind_kn, busy, incident_id,
                         (dispatched or {}).get(asset["id"])) for asset in fleet["assets"]]
    rows.sort(key=lambda row: (row["eta_s"] is None, row["eta_s"] if row["eta_s"] is not None else 0, row["id"]))
    physical = [row for row in rows if row["counts"] and row["eta_s"] is not None]
    at_line = deadline_s is not None and deadline_s <= now
    in_time = [row for row in physical if row["in_time"]]
    best = (in_time or physical or [None])[0]
    assigned = next((row for row in physical if row["status"] == "assigned"), None)
    blocked = [row for row in rows if row["counts"] and row.get("would_be_in_time")]
    return {"now": int(now), "deadline_s": None if deadline_s is None else int(deadline_s), "at_line": at_line,
            "at_line_text": at_line_text,
            "wind_kn": wind_kn, "rows": rows, "best": best, "assigned": assigned,
            "blocked_by": [f"{row['id']} {row['reason']}" for row in blocked],
            "no_response_in_time": deadline_s is not None and not at_line and not in_time,
            "label": fleet.get("label", "assumption")}


def minutes(seconds) -> int:
    return int(round(seconds / 60))


def summary_line(result: dict) -> tuple[str, bool]:
    """One card line and whether it is a warning, e.g. ``Drone D2 · 18 min · in time (+42 min)``."""
    best, assigned = result["best"], result["assigned"]
    shown = assigned or best
    if result["no_response_in_time"] and not (assigned and assigned["in_time"]):
        text = "No responder in time"
        if result["blocked_by"]:  # first, so a narrow card still shows why
            text += f" · {result['blocked_by'][0]}"
        if shown:
            text += f" · best {shown['id']} {minutes(shown['eta_s'])} min, {minutes(-shown['margin_s'])} min late"
        return text, True
    if shown is None:
        return "No physical responder can reach", True
    who = f"{KIND_SHORT[shown['kind']]} {shown['id']}" if shown["kind"] == "drone" else shown["id"]
    head = f"{'Sent: ' if assigned else ''}{who} · {minutes(shown['eta_s'])} min"
    if result["at_line"]:
        return f"{head} · {result.get('at_line_text', 'vessel already at the line')}", False
    if shown["margin_s"] is None:
        return f"{head} · eyes on", False
    return f"{head} · in time (+{minutes(shown['margin_s'])} min)", False


def row_text(row: dict) -> str:
    """One review-window line for an asset."""
    if row["status"] == "unavailable":
        return f"{row['id']}  {row['name']}: unavailable, {row['reason']}"
    wait = s1_plan.duration(row["eta_s"]) if row["kind"] == "satellite" else f"{minutes(row['eta_s'])} min"
    text = f"{row['id']}  {row['name']}: eyes on in {wait}"
    if row["margin_s"] is not None:
        verdict = (f"in time (+{minutes(row['margin_s'])} min)" if row["in_time"]
                   else f"too late ({minutes(-row['margin_s'])} min after the earliest line ETA)")
        text += f", {verdict}"
    if row["status"] == "assigned":
        text += " · SENT"
    if not row["counts"]:
        text += " · look only, does not count"
    return text
