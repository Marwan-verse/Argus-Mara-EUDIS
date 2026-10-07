#!/usr/bin/env python3
"""Build the demo scenario and a stub alert file.

This is the *contract generator*, not the product. It writes two files that every
workstream builds against from day one:

    demo/scenario.json   what happened  (owned by Data)
    demo/alerts.json     what Argus Mara noticed  (owned by Brain -- this is a STUB)

Run it with:  python3 demo/make_scenario.py

Brain replaces the alert part with the real detector + countdown, keeping the same
JSON shape. Interface never has to care which one wrote the file.

Everything here is SIMULATED. The vessel is fictional; the cable route is a
straight illustrative line, not a surveyed route.
"""
import json
import math
import pathlib

OUT = pathlib.Path(__file__).parent
T0 = "2026-10-16T08:00:00Z"
NM_PER_DEG = 60.0


def step(lat, lon, course_deg, distance_nm):
    """Dead-reckon one step. Flat-earth is fine over 30 nm."""
    r = math.radians(course_deg)
    lat2 = lat + (distance_nm * math.cos(r)) / NM_PER_DEG
    lon2 = lon + (distance_nm * math.sin(r)) / (NM_PER_DEG * math.cos(math.radians(lat)))
    return lat2, lon2


def nm_between(a_lat, a_lon, b_lat, b_lon):
    dlat = (b_lat - a_lat) * NM_PER_DEG
    dlon = (b_lon - a_lon) * NM_PER_DEG * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dlat, dlon)


# --- the cable -------------------------------------------------------------
# Illustrative east-west route across the Irish Sea. Replace with the real
# EMODnet / TeleGeography geometry when Data has it.
CABLE = {
    "id": "cable-irish-sea-1",
    "name": "Dublin-Holyhead telecom link (illustrative route)",
    "kind": "telecom",
    "label": "reconstructed",
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
    (5400, 9.1, 348.0, True, "9.1 kn, course wobbling - anchor-drag signature"),
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


def segments_cross(p1, p2, q1, q2):
    """Do segment p1-p2 and segment q1-q2 cross? Returns the fraction along p1-p2, or None."""
    def d(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = d(q1, q2, p1), d(q1, q2, p2)
    d3, d4 = d(p1, p2, q1), d(p1, p2, q2)
    if (d1 > 0) == (d2 > 0) or (d3 > 0) == (d4 > 0):
        return None
    return abs(d1) / (abs(d1) + abs(d2))


def project_to_cable(lat, lon, cog_deg, sog_kn, cable_path, horizon_s=3 * 3600, step_s=60):
    """Countdown v1: sail straight ahead and see when we hit the cable.

    This is the whole of countdown v1. Countdown v2 (Brain, days 3-4) replaces the
    single straight line with ~50 perturbed futures (speed +-20%, course +-5 deg) and
    reports the earliest crossing of any of them as `eta_earliest_s`.
    """
    here = (lat, lon)
    for t in range(0, horizon_s, step_s):
        nxt = step(here[0], here[1], cog_deg, sog_kn * step_s / 3600.0)
        for a, b in zip(cable_path, cable_path[1:]):
            frac = segments_cross(here, nxt, a, b)
            if frac is not None:
                cross = (here[0] + (nxt[0] - here[0]) * frac, here[1] + (nxt[1] - here[1]) * frac)
                return int(t + step_s * frac), cross
        here = nxt
    return None, None


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
        "name": "Scenario A - anchor drag over the Irish Sea cable",
        "label": "simulated",
        "t0_utc": T0,
        "replay_speed": 60,
        "cables": [CABLE],
        "vessels": [vessel],
        "detections": [detection],
        "assets": assets,
    }
    (OUT / "scenario.json").write_text(json.dumps(scenario, indent=1) + "\n")

    # ---- STUB brain: one alert, fired when the vessel is slow inside the zone ----
    t_alert = 4500
    pos = position_at(track, t_alert)
    eta_expected_s, cross = project_to_cable(
        pos["lat"], pos["lon"], pos["cog_deg"], pos["sog_kn"], CABLE["path"])
    eta_earliest_s, _ = project_to_cable(
        pos["lat"], pos["lon"], pos["cog_deg"], pos["sog_kn"] * 1.2, CABLE["path"])
    assert eta_expected_s is not None, "the vessel never reaches the cable - fix the track"
    cross_lat, cross_lon = cross
    dist_nm = nm_between(pos["lat"], pos["lon"], cross_lat, cross_lon)

    options = []
    for a in assets:
        if a.get("fixed_eta_min") is not None:
            eta_s = a["fixed_eta_min"] * 60
        elif a["speed_kn"] is None:
            d = nm_between(a["lat"], a["lon"], pos["lat"], pos["lon"])
            eta_s = a["readiness_min"] * 60 if d <= a["max_range_nm"] else None
        else:
            d = nm_between(a["lat"], a["lon"], cross_lat, cross_lon)
            eta_s = int(a["readiness_min"] * 60 + d / a["speed_kn"] * 3600)
        options.append({
            "asset": a["name"],
            "eta_s": eta_s,
            "in_time": bool(eta_s is not None and eta_s <= eta_earliest_s),
            "label": "assumption",
        })

    alerts = {
        "generated_by": "demo/make_scenario.py (STUB - Brain replaces this)",
        "scenario": "Scenario A",
        "alerts": [{
            "id": "A1",
            "t": t_alert,
            "mmsi": vessel["mmsi"],
            "vessel_name": vessel["name"],
            "state": "ALERT",
            "score": 0.82,
            "reasons": [
                "speed dropped 12.0 -> 9.1 kn with no reason (no port, no weather, no traffic)",
                "inside the anchor-reach zone (seabed <= 250 m)",
                "AIS gap of 20 min, 14 km from the cable",
                "radar length 228 m vs AIS 180 m - identity mismatch",
            ],
            "segment_id": CABLE["id"],
            "distance_km": round(dist_nm * 1.852, 1),
            "eta_expected_s": eta_expected_s,
            "eta_earliest_s": eta_earliest_s,
            "options": options,
            "evidence_url": "evidence/A1.html",
        }],
    }
    (OUT / "alerts.json").write_text(json.dumps(alerts, indent=1) + "\n")

    print(f"scenario.json: {len(track)} AIS points, 1 cable, 1 radar detection")
    print(f"alerts.json:   alert at t+{t_alert // 60} min, "
          f"cable in {eta_expected_s // 60} min (earliest {eta_earliest_s // 60} min)")
    for o in alerts["alerts"][0]["options"]:
        mark = "YES" if o["in_time"] else "no "
        eta = f"{o['eta_s'] // 60} min" if o["eta_s"] is not None else "out of range"
        print(f"  [{mark}] {o['asset']}: {eta}")


if __name__ == "__main__":
    main()
