"""Stopped away from ports: a vessel stopped at sea, not at a port or an anchorage.

Ships stop to wait for a berth, a pilot or orders, and they do it in ports and
designated anchorages. A ship stopped in open water is unusual and worth a
look, more so near a cable. This detector reads the track up to
``context["now"]`` and finds the latest unbroken stop: fixes at
``STOP_KN`` or less, with no reception gap over ``MAX_FIX_GAP_S``. When the
stop has lasted ``STOP_MIN`` minutes or more and its position is more than
``PORT_NM`` from every port and anchorage (``argus.detectors.places``), it
fills ``stopped_offport_min`` for rule B12 in ``argus.levels``.

The finding names no cable: line proximity comes from ``cable_risk``, so a
ship stopped far from every line stays a low-level lead. Fishing vessels are
skipped because stopping at sea is part of their work. Every threshold below
is a team assumption, not regulation. Findings say "cause unknown"; engine
trouble, waiting for orders and bad weather are all ordinary reasons.
"""

from __future__ import annotations

from statistics import median

from argus.countdown import nm_between
from argus.detectors import places

DETECTOR = "stop_off_port"

# Thresholds (assumptions).
STOP_KN = 0.5  # at or below this speed the vessel counts as stopped
STOP_MIN = 30  # rule B12 starts here; it gives more points from 2 h
PORT_NM = 3.0  # a stop this close to a port or an anchorage's edge is expected
MAX_FIX_GAP_S = 30 * 60  # a longer reception gap ends a stop; nothing is assumed across it
WINDOW_S = 24 * 3600  # the longest stop looked back on
FISHING_TYPE = 30


def _speed(fix: dict, before: dict | None) -> float | None:
    """Reported SOG, or the speed the positions imply when SOG is missing."""
    if fix.get("sog_kn") is not None:
        return fix["sog_kn"]
    if before is None or fix["t"] <= before["t"]:
        return None
    return nm_between(before["lat"], before["lon"], fix["lat"], fix["lon"]) / ((fix["t"] - before["t"]) / 3600)


def latest_stop(fixes: list[dict]) -> list[dict]:
    """The run of stopped fixes ending at the latest fix, oldest first; empty when the vessel moves."""
    run: list[dict] = []
    for index in range(len(fixes) - 1, -1, -1):
        fix = fixes[index]
        speed = _speed(fix, fixes[index - 1] if index else None)
        if speed is None or speed > STOP_KN or (run and run[-1]["t"] - fix["t"] > MAX_FIX_GAP_S):
            break
        run.append(fix)
    return run[::-1]


def stop_off_port(vessel: dict, context: dict) -> list[dict]:
    """One ``stop_off_port`` finding while the vessel is stopped away from ports and anchorages; else none."""
    if str(vessel.get("ship_type")) == str(FISHING_TYPE):
        return []
    track = vessel.get("track") or []
    now = context.get("now")
    if now is None:
        now = track[-1]["t"] if track else None
    if now is None:
        return []
    fixes = [fix for fix in track if now - WINDOW_S <= fix["t"] <= now and fix.get("lat") is not None]
    stop = latest_stop(fixes)
    if len(stop) < 2:
        return []
    minutes = (stop[-1]["t"] - stop[0]["t"]) / 60
    if minutes < STOP_MIN:
        return []
    last = stop[-1]
    anchorage = places.anchorage_at(last["lat"], last["lon"], PORT_NM, context.get("anchorages"))
    port = places.nearest_port(last["lat"], last["lon"], context.get("ports"))
    if anchorage or (port and port[1] <= PORT_NM):
        return []
    speeds = [fix["sog_kn"] for fix in stop if fix.get("sog_kn") is not None]
    sog = median(speeds) if speeds else 0.0
    drift_nm = nm_between(stop[0]["lat"], stop[0]["lon"], last["lat"], last["lon"])
    duration = f"{minutes / 60:.1f} h" if minutes >= 120 else f"{minutes:.0f} min"
    where = (f"{port[1]:.1f} nm from the nearest port ({port[0]})" if port
             else "far from every port in the reference files")
    reasons = [
        f"Stopped at sea for {duration}, {where} and outside every known anchorage; cause unknown.",
        f"Median {sog:.1f} kn, drifted {drift_nm:.2f} nm since the stop began (rule: {STOP_KN:g} kn or less for "
        f"{STOP_MIN} min or more, over {PORT_NM:g} nm from a port or anchorage; fishing vessels skipped).",
        "Ports are catalogue points and anchorages rough areas, not charted limits.",
    ]
    return [{"detector": DETECTOR, "mmsi": vessel["mmsi"], "t": int(last["t"]), "position": [last["lat"], last["lon"]],
             "strength": 0.6 if minutes >= 120 else 0.4, "reasons": reasons,
             "related": {"stop_started_t": int(stop[0]["t"]), "nearest_port": port[0] if port else None,
                         "nearest_port_nm": round(port[1], 1) if port else None},
             "label": vessel.get("label", "simulated"), "obs": {"stopped_offport_min": round(minutes)}}]


detect = stop_off_port  # the package convention; the function name labels the assessments file
