"""Simulated alert board for the desktop console.

Every contact here is fictional and labelled ``simulated``: names, tracks and
observations are generated to demonstrate the risk levels in ``argus.levels``.
Line routes are illustrative, not surveyed positions. The board never reads live
AIS and never sends anything; the operator decides every action.
"""

from __future__ import annotations

import math
import random

from argus.countdown import step
from argus.levels import RANK, assess

SOURCE_NOTE = "Simulated alert data · fictional vessels and observations"

# Illustrative routes for familiar Irish links; display context only.
LINES = {
    "dublin-holyhead": ("Dublin–Holyhead telecom cable", "telecom",
                        [(53.35, -6.05), (53.36, -5.70), (53.37, -5.35), (53.35, -5.05), (53.33, -4.75)]),
    "ewic": ("EWIC power interconnector", "power",
             [(53.52, -6.08), (53.47, -5.30), (53.40, -4.40), (53.34, -3.42)]),
    "north-dublin": ("North Dublin cable cluster", "cluster",
                     [(53.43, -6.12), (53.50, -5.40), (53.62, -4.40), (53.74, -2.98)]),
    "ic2": ("Gas interconnector IC2", "gas",
            [(53.64, -6.21), (53.95, -5.60), (54.40, -4.95), (54.78, -4.13)]),
    "greenlink": ("Greenlink power interconnector", "power",
                  [(52.17, -6.83), (52.00, -6.20), (51.80, -5.50), (51.66, -5.06)]),
    "celtic": ("Celtic Interconnector route", "power",
               [(51.86, -7.98), (51.40, -7.60), (50.50, -6.60), (49.60, -5.60)]),
    "iris": ("Galway–Iceland link", "sole_link",
             [(53.25, -9.05), (53.35, -10.20), (53.90, -11.80), (55.00, -13.80)]),
    "mayo-atlantic": ("Mayo transatlantic cable", "transatlantic",
                      [(54.22, -9.22), (54.45, -10.30), (54.80, -11.80), (55.20, -14.00)]),
    "cork-atlantic": ("Cork transatlantic cable", "transatlantic",
                      [(51.64, -8.60), (51.45, -9.60), (51.20, -11.00), (50.90, -13.00)]),
    "moyle": ("Moyle power interconnector", "power", [(54.83, -5.73), (54.95, -5.35), (55.07, -4.98)]),
}

# (id, name, vessel type, length m, line, lat, lon, course, speed kn, minutes ago, track pattern,
#  title, recommendation, observations). Higher levels are hand-written scenarios.
SCENARIOS = [
    ("SIM-01", "ORLA BREEZE", "General cargo", 189, "ewic", 53.462, -5.15, 105, 6.8, 3, "drag",
     "Anchor dragging across the EWIC power cable",
     "Order the anchor raised on VHF 16, alert EirGrid and task the nearest aircraft or drone.",
     {"speed_drop_pct": 41, "course_change_deg": 26, "in_corridor": True, "ignored_instruction": True}),
    ("SIM-02", "KESTREL DAWN", "Research vessel", 86, "iris", 53.745, -11.35, 210, 0.3, 6, "hover",
     "Holding position 3 h over the Galway–Iceland link",
     "Request an Air Corps patrol and a satellite radar look; notify the link operator.",
     {"hover_hours": 3.2, "special_vessel": True, "deep_segment": True, "ais_gap_min": 35,
      "in_corridor": True, "watchlist": True}),
    ("SIM-03", "BRANDON GLEN", "Bulk carrier", 224, "north-dublin", 53.468, -5.72, 95, 4.1, 1, "drag",
     "Fibre sensing reports an impact beneath the ship",
     "Treat as possible damage: notify operators, preserve evidence and predict the next line on its track.",
     {"slow_over_corridor_min": 22, "in_corridor": True, "asset_vulnerable": True,
      "second_sensor": True, "fault_confirmed": True}),
    ("SIM-04", "MOY HARVESTER", "Trawler", 24, "north-dublin", 53.442, -5.95, 280, 3.2, 14, "passes",
     "Four trawl passes over the North Dublin cable cluster",
     "Call the skipper to keep clear of the charted cables and inform the cable operators.",
     {"passes_6h": 4, "in_corridor": True, "asset_vulnerable": True}),
    ("SIM-05", "ATLANTIC WREN", "General cargo", 138, "dublin-holyhead", 53.357, -5.93, 60, 1.6, 9, "anchor-drag",
     "Dragging at anchor near the Dublin–Holyhead cable in a gale",
     "Advise the master to heave up or veer cable and monitor the drift track.",
     {"dragging_at_anchor": True, "sog_kn": 1.6, "in_corridor": True, "gale_warning": True}),
    ("SIM-06", "GREY HERON", "Tanker", 244, "ic2", 54.075, -5.62, 120, 7.5, 18, "loiter",
     "Loitered 6 h beside the IC2 gas pipeline, now heading for it",
     "Shadow with the nearest asset, hail on VHF 16 and alert Gas Networks Ireland.",
     {"loiter_hours": 6, "ais_gap_min": 15, "identity_changes": 2, "eta_min": 33.5, "watchlist": True}),
    ("SIM-07", "CORRIB MIST", "Bulk carrier", 199, "greenlink", 51.83, -5.78, 300, 5.2, 22, "drag",
     "Slowing with an unsteady course 3 nm from Greenlink",
     "Hail on VHF 16 and ask the master to confirm both anchors are secured.",
     {"slowdown_near_corridor": True, "status_mismatch": True, "ais_gap_min": 12, "eta_min": 40}),
    ("SIM-08", "UNIDENTIFIED", "Radar contact", 112, "greenlink", 52.02, -6.05, 150, 3.0, 31, "line",
     "Satellite-radar contact without AIS near Greenlink",
     "Request a satellite look or aircraft to identify it; there is no AIS identity to call.",
     {"no_ais": True, "dark_radar_contact": True, "slowdown_near_corridor": True, "distance_nm": 1.5}),
    ("SIM-09", "HOLLY BAY", "General cargo", 112, "dublin-holyhead", 53.336, -6.00, 230, 0.1, 27, "anchor",
     "At anchor 0.8 nm from the Dublin–Holyhead cable under a gale warning",
     "Ask the master to keep an anchor watch and report any dragging immediately.",
     {"anchored_near_cable": True, "in_corridor": True, "gale_warning": True}),
    ("SIM-10", "NORTHERN SKUA", "Bulk carrier", 180, "dublin-holyhead", 53.362, -5.55, 85, 5.0, 12, "line",
     "Slow transit at 5 kn over the Dublin–Holyhead corridor",
     "Monitor; hail if speed falls further or the course becomes unsteady.",
     {"slow_over_corridor_min": 14, "in_corridor": True}),
    ("SIM-11", "TARA SOUND", "Tanker", 183, "ewic", 53.43, -4.62, 250, 6.1, 41, "line",
     "AIS gap of 25 min ended 3 nm from EWIC; slowed afterwards",
     "Check the gap against satellite radar and keep the vessel under watch.",
     {"ais_gap_min": 25, "slowdown_near_corridor": True, "distance_nm": 3}),
    ("SIM-12", "ARDMORE TIDE", "General cargo", 96, "north-dublin", 53.585, -5.05, 70, 6.4, 58, "line",
     "Renamed and reflagged this year; slowing near the North Dublin cluster",
     "Verify identity history and keep under watch while near the cluster.",
     {"identity_changes": 2, "slowdown_near_corridor": True, "distance_nm": 2.5, "asset_vulnerable": True}),
    ("SIM-13", "BLASKET SPRAY", "Fishing vessel", 21, "north-dublin", 53.452, -5.84, 95, 3.4, 36, "passes",
     "Two trawl passes over the North Dublin cable cluster",
     "Remind the skipper of the charted cable corridor; escalate if passes continue.",
     {"fishing_near_corridor": True, "in_corridor": True, "asset_vulnerable": True}),
    ("SIM-14", "CLARE VOYAGER", "Ro-ro cargo", 186, "dublin-holyhead", 53.31, -5.22, 75, 4.0, 47, "line",
     "Reports 'at anchor' while moving 4 kn near the Dublin–Holyhead cable",
     "Ask the vessel to correct its AIS status and confirm its intentions.",
     {"status_mismatch": True, "slowdown_near_corridor": True, "length_mismatch_pct": 27,
      "route_inconsistent": True, "distance_nm": 2.8}),
    ("SIM-15", "KILKEE ROSE", "Tanker", 228, "celtic", 51.31, -7.43, 200, 7.0, 52, "line",
     "Watch-listed tanker slowing 4 nm from the Celtic Interconnector route",
     "Keep under watch; prepare a hail if it turns towards the route.",
     {"slowdown_near_corridor": True, "identity_changes": 1, "distance_nm": 4, "watchlist": True}),
]

# Frequent minor alerts: (template, name, line, lat, lon, course, speed, minutes ago, value).
LOW_TEMPLATES = {
    "gap": ("Short AIS reception gap ({v} min) near the coast", "Probably a coverage gap; keep monitoring.",
            lambda v: {"ais_gap_min": v, "distance_nm": 3}),
    "jump": ("Single position jump, likely a GPS glitch", "Check the next fixes; no action unless it repeats.",
             lambda v: {"spoof_signs": True, "distance_nm": 4}),
    "length": ("Radar length differs {v}% from AIS, likely measurement noise", "Compare with the next satellite pass.",
               lambda v: {"length_mismatch_pct": v, "static_incomplete": True, "distance_nm": 4}),
    "watch": ("Watch-listed vessel transiting normally, {v} nm from the corridor", "Keep visible; no action needed.",
              lambda v: {"watchlist": True, "identity_changes": 1, "distance_nm": v}),
    "fishing": ("Single fishing pass {v} nm from the cable", "No action; escalates if it repeats over the corridor.",
                lambda v: {"fishing_near_corridor": True, "distance_nm": v}),
    "pilot": ("Brief slowdown at the pilot boarding area", "Expected port activity; no action.",
              lambda v: {"slowdown_near_corridor": True, "distance_nm": v}),
    "status": ("AIS status 'at anchor' while under way in a port approach", "Ask the vessel to correct its AIS status.",
               lambda v: {"status_mismatch": True, "static_incomplete": True, "distance_nm": v}),
    "destination": ("Destination blank and AIS dropped for {v} min", "Request voyage details if it approaches a line.",
                    lambda v: {"static_incomplete": True, "ais_gap_min": v, "distance_nm": 6}),
    "repair": ("Cable ship working on a notified repair (authorised)", "Authorised work; no action.",
               lambda v: {"hover_hours": v, "special_vessel": True, "deep_segment": True, "in_corridor": True,
                          "authorised": True}),
    "survey": ("Survey vessel running lines near the cable with consent (authorised)", "Authorised survey; no action.",
               lambda v: {"passes_6h": v, "in_corridor": True, "authorised": True}),
}
LOW_CONTACTS = [
    ("gap", "SILVER CURLEW", "Container ship", "dublin-holyhead", 53.28, -5.85, 120, 14.2, 7, 12),
    ("gap", "AMBER TERN", "General cargo", "greenlink", 52.10, -6.45, 200, 11.0, 19, 15),
    ("gap", "QUIET OTTER", "Tanker", "cork-atlantic", 51.55, -8.95, 250, 12.5, 33, 13),
    ("gap", "HAZEL WAKE", "Ro-ro cargo", "moyle", 54.90, -5.55, 60, 15.0, 44, 11),
    ("gap", "NORTH LANTERN", "Bulk carrier", "mayo-atlantic", 54.38, -9.85, 280, 10.8, 63, 17),
    ("jump", "SLOE BERRY", "Fishing vessel", "iris", 53.30, -9.60, 270, 8.0, 21, 0),
    ("jump", "PALE GULL", "Passenger ferry", "dublin-holyhead", 53.38, -5.40, 100, 18.0, 52, 0),
    ("jump", "COPPER REEF", "Tug", "ic2", 53.75, -6.00, 30, 9.0, 88, 0),
    ("length", "MOSS HARBOUR", "General cargo", "celtic", 51.62, -7.80, 190, 11.4, 26, 31),
    ("length", "TIDE WREN", "Tanker", "cork-atlantic", 51.40, -10.10, 255, 12.1, 71, 28),
    ("length", "IVORY SKERRY", "Bulk carrier", "ewic", 53.38, -3.90, 270, 10.2, 96, 34),
    ("watch", "LOW CLOUD", "Tanker", "mayo-atlantic", 54.70, -11.20, 200, 12.8, 15, 6),
    ("watch", "BRACKEN SOUND", "Tanker", "iris", 53.60, -10.90, 190, 11.9, 49, 7),
    ("watch", "WILLOW FATHOM", "Tanker", "cork-atlantic", 51.05, -11.60, 230, 12.3, 120, 9),
    ("fishing", "SALT ROWAN", "Fishing vessel", "north-dublin", 53.56, -4.95, 140, 3.6, 24, 1.5),
    ("fishing", "EMBER PIER", "Fishing vessel", "greenlink", 51.92, -5.95, 300, 3.1, 57, 1.8),
    ("fishing", "LINEN BAY", "Fishing vessel", "ic2", 54.25, -5.25, 45, 3.9, 102, 2.2),
    ("pilot", "FERN CURRENT", "Container ship", "dublin-holyhead", 53.34, -6.08, 270, 4.5, 11, 1.2),
    ("pilot", "RAVEN SHOAL", "Bulk carrier", "cork-atlantic", 51.70, -8.25, 0, 5.0, 79, 2.5),
    ("status", "GLASS MERIDIAN", "General cargo", "moyle", 54.80, -5.80, 150, 6.0, 38, 1.0),
    ("status", "STONE PLOVER", "Ro-ro cargo", "greenlink", 52.15, -6.70, 120, 7.0, 133, 1.4),
    ("destination", "MIST KESTREL", "General cargo", "dublin-holyhead", 53.45, -5.60, 95, 10.5, 66, 11),
    ("repair", "CABLE WARDEN", "Cable ship", "cork-atlantic", 51.30, -10.60, 90, 0.4, 140, 9),
    ("survey", "SEABED LARK", "Survey vessel", "mayo-atlantic", 54.50, -10.60, 260, 4.5, 170, 6),
]


def _track(lat, lon, course, speed, pattern, seed):
    """A short fictional track ending at the current position, for display only."""
    rnd = random.Random(seed)
    reverse = (course + 180) % 360
    if pattern == "hover":
        return [(lat + rnd.uniform(-0.004, 0.004), lon + rnd.uniform(-0.006, 0.006)) for _ in range(10)] + [(lat, lon)]
    if pattern in ("anchor", "anchor-drag"):
        points = []
        for index in range(12):
            angle = math.radians(200 + index * 14)
            points.append((lat + 0.004 * math.cos(angle), lon + 0.007 * math.sin(angle)))
        if pattern == "anchor-drag":
            points.extend(step(lat, lon, reverse, 0.4 - index * 0.03) for index in range(10))
        return points + [(lat, lon)]
    if pattern == "loiter":
        centre = step(lat, lon, reverse, 2.0)
        ring = [step(*centre, angle, 1.2) for angle in range(0, 375, 15)]
        return ring + [step(lat, lon, reverse, distance) for distance in (1.5, 1.0, 0.5)] + [(lat, lon)]
    if pattern == "passes":
        points, here = [], (lat, lon)
        for leg in range(4):
            heading = course if leg % 2 else reverse
            here = step(*here, heading, 1.6)
            points.append(here)
            here = step(*here, (course + 90) % 360, 0.25)
            points.append(here)
        return list(reversed(points)) + [(lat, lon)]
    points = []
    for index in range(12, 0, -1):
        wobble = rnd.uniform(-12, 12) if pattern == "drag" and index < 6 else 0
        points.append(step(lat, lon, (reverse + wobble) % 360, speed * index * 5 / 60))
    return points + [(lat, lon)]


def _item(identifier, name, kind, length, line_id, lat, lon, course, speed, minutes, pattern,
          title, recommendation, observations, label="simulated"):
    line_name, asset_class, _path = LINES[line_id]
    observations = {"asset_class": asset_class, **observations}
    return {"id": identifier, "label": label, "name": name, "vessel_type": kind, "length_m": length,
            "line_id": line_id, "line_name": line_name, "lat": lat, "lon": lon, "cog_deg": course,
            "sog_kn": speed, "raised_min_ago": minutes, "title": title, "recommendation": recommendation,
            "eta_start_min": observations.get("eta_min"), "observations": observations,
            "track": _track(lat, lon, course, speed, pattern, identifier),
            "assessment": assess(observations)}


def exercise_item(scenario: dict, alert: dict) -> dict:
    """Score the fictional exercise alert with the same rules, at its alert fix."""
    vessel = next(v for v in scenario["vessels"] if v["mmsi"] == alert["mmsi"])
    fix = next((f for f in vessel["track"] if f["t"] == alert["t"]), vessel["track"][-1])
    seen = alert.get("observations", {})
    radar = next((d for d in scenario.get("detections", []) if d.get("t") == seen.get("radar_contact_t")), None)
    observations = {
        "speed_drop_pct": seen.get("speed_drop_percent", 0), "course_change_deg": seen.get("course_change_deg", 0),
        "ais_gap_min": (seen.get("gap_end_t", 0) - seen.get("gap_start_t", 0)) / 60,
        "dark_radar_contact": seen.get("radar_association") == "unconfirmed",
        "eta_min": alert["eta_earliest_s"] / 60, "distance_nm": alert["distance_km"] / 1.852,
        "asset_class": "telecom",
    }
    if radar and radar.get("length_m") and vessel.get("ais_length_m"):
        observations["length_mismatch_pct"] = abs(radar["length_m"] - vessel["ais_length_m"]) / vessel["ais_length_m"] * 100
    cable = next((c for c in scenario["cables"] if c["id"] == alert["segment_id"]), {})
    track = [(f["lat"], f["lon"]) for f in vessel["track"] if f["t"] <= alert["t"]]
    return {"id": alert["id"], "label": "fictional", "exercise": True, "alert": alert,
            "name": alert["vessel_name"], "vessel_type": vessel.get("type", "Vessel").title(),
            "length_m": vessel.get("ais_length_m"), "line_id": alert["segment_id"],
            "line_name": cable.get("name", "Illustrative cable"), "lat": fix["lat"], "lon": fix["lon"],
            "cog_deg": fix["cog_deg"], "sog_kn": fix["sog_kn"], "raised_min_ago": 0,
            "title": "Fictional exercise: slowdown and turn towards a cable after an AIS gap",
            "recommendation": "Open the exercise replay to review the countdown and response options.",
            "eta_start_min": None, "observations": observations, "track": track[-40:],
            "assessment": assess(observations)}


def build_board(scenario: dict | None = None, alerts: list | None = None) -> list[dict]:
    """Return the fictional exercise alerts and simulated contacts, sorted by severity."""
    items = [exercise_item(scenario, alert) for alert in (alerts or [])] if scenario else []
    items.extend(_item(*row) for row in SCENARIOS)
    for index, (template, name, kind, line_id, lat, lon, course, speed, minutes, value) in enumerate(LOW_CONTACTS, 16):
        title, recommendation, observe = LOW_TEMPLATES[template]
        pattern = "hover" if template == "repair" else "passes" if template == "survey" else "line"
        items.append(_item(f"SIM-{index:02d}", name, kind, 0, line_id, lat, lon, course, speed, minutes, pattern,
                           title.format(v=value), recommendation, observe(value)))
    return sorted(items, key=sort_key)


def update(items: list[dict], elapsed_s: float) -> list[str]:
    """Count simulated ETAs down from board start; return IDs whose level changed."""
    changed = []
    for item in items:
        start = item.get("eta_start_min")
        if start is None:
            continue
        item["observations"]["eta_min"] = max(0.0, start - elapsed_s / 60)
        before = item["assessment"]["level"]
        item["assessment"] = assess(item["observations"])
        if item["assessment"]["level"] != before:
            changed.append(item["id"])
    return changed


def line_path(line_id: str, scenario: dict | None = None) -> list[tuple[float, float]]:
    if line_id in LINES:
        return LINES[line_id][2]
    cable = next((c for c in (scenario or {}).get("cables", []) if c["id"] == line_id), None)
    return [tuple(point) for point in cable["path"]] if cable else []


def sort_key(item: dict) -> tuple:
    """Severity first; within a level, a contact already in the corridor, then the soonest ETA."""
    assessment = item["assessment"]
    eta = 0.0 if item["observations"].get("in_corridor") else item["observations"].get("eta_min")
    return (-RANK[assessment["level"]], eta if eta is not None else 1e9, -assessment["score"],
            item.get("raised_min_ago", 0), item["id"])
