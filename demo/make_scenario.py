#!/usr/bin/env python3
"""Build the fictional demo scenario without overwriting Brain's alert file.

This is the *contract generator*, not the product. It writes two files that every
workstream builds against from day one:

    demo/scenario.json   what happened  (owned by Data)

Run it with:  python3 demo/make_scenario.py

Then run ``python -m argus.brain`` to generate ``demo/alerts.json`` from rules.

Everything here is SIMULATED. The vessel is fictional; the cable route is a
straight illustrative line, not a surveyed route.
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from argus.countdown import step

OUT = pathlib.Path(__file__).parent
T0 = "2026-10-16T08:00:00Z"
# --- the cable -------------------------------------------------------------
# Illustrative east-west route across the Irish Sea. Replace with the real
# EMODnet / TeleGeography geometry when Data has it.
CABLE = {
    "id": "cable-irish-sea-1",
    "name": "Dublin-Holyhead telecom link (illustrative route)",
    "kind": "telecom",
    "label": "simulated",
    "criticality": 0.8,
    "path": [[53.35, -6.05], [53.36, -5.70], [53.37, -5.35], [53.36, -5.00], [53.33, -4.75]],
    # which part of the route an anchor can reach (depth <= 250 m). Here: all of it.
    "anchor_reachable": [[53.35, -6.05], [53.33, -4.75]],
    "min_depth_m": 90,
}

# --- the vessel ------------------------------------------------------------
# Leg = (duration_s, speed_kn, course_deg, ais_on, note)
LEGS = [
    (1800, 12.0, 20.0, True, "normal passage"),
    (1200, 12.0, 20.0, False, "AIS switched off"),
    (1200, 12.0, 350.0, True, "AIS back on, now heading for the shallow stretch"),
    (1200, 11.0, 352.0, True, "slowing"),
    (5400, 9.1, 348.0, True, "9.1 kn, course wobbling - review cue; cause unknown"),
]
START = (52.90, -5.50)
STEP_S = 60


def build_track():
    lat, lon = START
    t = 0
    points = []
    for duration, sog, cog, ais_on, _note in LEGS:
        for i in range(duration // STEP_S):
            wobble = 8.0 * math.sin(t / 420.0) if sog < 10 else 0.0
            if ais_on:
                points.append({
                    "t": t,
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "sog_kn": round(sog, 1),
                    "cog_deg": round((cog + wobble) % 360, 1),
                })
            lat, lon = step(lat, lon, cog + wobble, sog * STEP_S / 3600.0)
            t += STEP_S
    return points


def position_at(points, t):
    return min(points, key=lambda p: abs(p["t"] - t))


def main():
    track = build_track()

    vessel = {
        "mmsi": 999000001,
        "name": "CORMORANT STAR",
        "label": "fictional",
        "type": "tanker",
        "ais_length_m": 180,
        "flag": "XX",
        "name_flag_history": ["3 names and 4 flags since 2021"],
        "track": track,
    }

    # Radar detection in the middle of the AIS gap: it is 228 m long, not 180 m.
    gap_mid_t = 2400
    gap_pos = position_at(track, 1740)          # last fix before the gap
    det_lat, det_lon = step(gap_pos["lat"], gap_pos["lon"], 20.0, 12.0 * (gap_mid_t - 1740) / 3600.0)
    detection = {
        "t": gap_mid_t,
        "lat": round(det_lat, 5),
        "lon": round(det_lon, 5),
        "length_m": 228,
        "source": "sentinel1",
        "scene_id": "S1A_IW_GRDH_SIMULATED",
        "matched_mmsi": None,
        "label": "simulated",
    }

    assets = [
        {"id": "mpa", "name": "Maritime patrol aircraft (Casement)", "lat": 53.30, "lon": -6.45,
         "readiness_min": 30, "speed_kn": 216, "label": "assumption"},
        {"id": "lev", "name": "Naval Service patrol ship (at sea)", "lat": 52.55, "lon": -6.05,
         "readiness_min": 20, "speed_kn": 15, "label": "assumption"},
        {"id": "vhf", "name": "VHF hail, Dublin coast radio", "lat": 53.35, "lon": -6.20,
         "readiness_min": 2, "speed_kn": None, "max_range_nm": 30, "label": "assumption"},
        {"id": "sat", "name": "Next Sentinel-1 look", "fixed_eta_min": 250, "label": "assumption"},
    ]

    scenario = {
        "name": "Scenario A - fictional cable approach in the Irish Sea",
        "label": "simulated",
        "provenance": {
            "dataset": "Argus Mara fictional exercise",
            "license": "Team-created simulated content",
            "attribution": "Argus Mara team",
            "selection": "One invented vessel, radar contact and illustrative cable; not a regional census",
        },
        "t0_utc": T0,
        "replay_speed": 60,
        "cables": [CABLE],
        "vessels": [vessel],
        "detections": [detection],
        "assets": assets,
    }
    (OUT / "scenario.json").write_text(json.dumps(scenario, indent=1) + "\n")

    print(f"scenario.json: {len(track)} AIS points, 1 cable, 1 radar detection")


if __name__ == "__main__":
    main()
