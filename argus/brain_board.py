"""The simulated alert board, scored through Brain's assembler.

``argus.alert_board`` builds the fictional exercise item and the simulated
contacts. Here every item is re-scored through ``argus.assemble``: the exercise
vessel runs the registered detectors on the scenario, and each simulated item's
hand-written observations enter as findings. The small-vessel relevance rule
then caps or explains the level. Five extra simulated items show the rules:
small craft that are capped or not (SIM-40 to SIM-43) and a ship approaching
two lines at once, scored for the more urgent one (SIM-44). Three more carry
fictional timed AIS tracks that the real ``ais_spoofing`` detector reads: one
identity in two places (SIM-45), a small craft with an inland fix (SIM-46) and
a single GPS glitch that must not count as spoofing (SIM-47). One more slows
towards a line, crosses it and moves away (SIM-48), so its incident goes quiet.

Four more are stories on the exercise replay clock (SIM-50 to SIM-53): fictional
AIS tracks, one fix a minute, that Brain itself scores at every replay step
with the registered detectors (``argus.assemble.DETECTORS``) against the
illustrative routes, like the exercise vessel. Nothing about them is written by
hand except the track: an anchor-drag approach to EWIC without an AIS gap
(SIM-50), a ship holding beside the North Dublin cable cluster and then
anchoring (SIM-51), and two innocent ones, a ship at anchor in Dublin Bay
outside every corridor (SIM-52) and a fast ferry crossing the lines (SIM-53).
SIM-49 is an innocent transit whose AIS feed is deliberately corrupted (missing
and "not available" positions, repeated and out-of-order times, "not
available" speed and course, numbers as text): Brain cleans it, scores it
without failing and reports what it ignored. The map and the card show the
cleaned track; Brain reads the track as received.

A fifth declares Fishguard as its AIS destination, then turns away from it
towards Greenlink and slows by the line (SIM-55, after the Dublin stories), so
``route_check`` adds rule C3.
Three more show the ``dark_vessel``, ``declared_vs_actual`` and
``stop_off_port`` detectors: a ship whose AIS goes silent on the approach to a
cable while a simulated satellite radar pass sees it (SIM-57), a ship that
declares Liverpool but turns towards the North Dublin cluster and reports "at
anchor" while still moving (SIM-58), and a ship stopped at sea between two
lines, away from any port or anchorage (SIM-59). A story's declared
destination and radar contacts are in ``STORY_EXTRAS``.

Two more show the Marine Notice rule (``argus.detectors.marine_notice``). A
survey vessel runs slow lines along EWIC and is named in a fictional exercise
notice, so Brain caps it at Low (SIM-56). A ship circles inside the work area of
the real Marine Notice 49/2026 off Rush, which names other vessels, so nothing
is explained and its level stands (SIM-60).

``update`` is a pure function of the board time, so a replay can move the
board forwards or backwards; ``rescore_exercise`` re-scores the exercise
vessel at a replay time.

AIS ship types, classes and radar lengths below are assumptions for fictional
contacts. Nothing here reads live AIS or sends anything.
"""

from __future__ import annotations

import math

from argus import alert_board
from argus.alert_board import LINES, _item, sort_key
from argus.assemble import apply_relevance, assess_vessel, clean_vessel, context_from_scenario
from argus.countdown import step
from argus.detectors import ais_spoofing
from argus.levels import assess

# Assumed AIS ship type codes for the board's display types.
SHIP_TYPES = {
    "Trawler": 30, "Fishing vessel": 30, "Sailing yacht": 36, "Pleasure craft": 37, "Motor yacht": 37,
    "Pilot boat": 50, "Tug": 52, "Passenger ferry": 60, "General cargo": 70, "Container ship": 70,
    "Bulk carrier": 70, "Ro-ro cargo": 70, "Tanker": 80, "Survey vessel": 33,
}

# Extra simulated items: (alert_board._item row, AIS class, findings about other lines as (line ID, obs)).
EXTRA_ITEMS = [
    (("SIM-40", "WHITE PETREL", "Sailing yacht", 11, "ewic", 53.47, -5.02, 140, 2.1, 8, "drag",
      "Sailing yacht slowing and turning over the EWIC corridor",
      "Small yacht: its anchor is unlikely to reach the cable. Monitor; no call needed.",
      {"speed_drop_pct": 38, "course_change_deg": 45, "in_corridor": True}), "B", []),
    (("SIM-41", "SEA LARK", "Pleasure craft", 14, "north-dublin", 53.52, -5.22, 80, 4.0, 16, "line",
      "Declared 14 m pleasure craft, radar measures 62 m, slowing towards the cable cluster",
      "Identity in doubt: request a satellite or aircraft look and hail on VHF 16.",
      {"slow_over_corridor_min": 18, "ais_gap_min": 20, "dark_radar_contact": True, "radar_length_m": 62,
       "length_mismatch_pct": 343, "eta_min": 45}), "B", []),
    (("SIM-42", "PORT RUNNER", "Pilot boat", 16, "dublin-holyhead", 53.345, -5.98, 300, 1.2, 4, "hover",
      "Pilot boat holding position inside the Dublin–Holyhead corridor",
      "Expected harbour work; no action unless it anchors.",
      {"loiter_hours": 1.5, "in_corridor": True}), "A", []),
    (("SIM-43", "LITTLE SKELLIG", "Motor yacht", 15, "north-dublin", 53.49, -5.45, 70, 1.8, 2, "drag",
      "Fibre sensing reports a fault beneath a 15 m motor yacht",
      "Treat as possible damage despite its size: notify the cable operators, preserve evidence "
      "and request identification.",
      {"slow_over_corridor_min": 12, "in_corridor": True, "second_sensor": True, "fault_confirmed": True}), "B", []),
    (("SIM-44", "MERIDIAN FERN", "Bulk carrier", 190, "dublin-holyhead", 53.32, -5.60, 20, 8.0, 5, "drag",
      "Slowing and turning 20 min from the Dublin–Holyhead cable; IC2 gas pipeline 5 h ahead",
      "Hail on VHF 16 and ask the master to confirm both anchors are secured before the cable.",
      {"speed_drop_pct": 24, "course_change_deg": 30, "eta_min": 20}), "A",
     [("ic2", {"eta_min": 300})]),
]


def _straight(lat, lon, course, speed_kn, count, interval_s=60):
    """A fictional straight track: ``count`` fixes ``interval_s`` apart, declaring its true speed."""
    fixes = []
    for index in range(count):
        here = step(lat, lon, course, speed_kn * index * interval_s / 3600)
        fixes.append({"t": index * interval_s, "lat": round(here[0], 5), "lon": round(here[1], 5),
                      "sog_kn": speed_kn, "cog_deg": course})
    return fixes


def _moved(fix: dict, course: float, distance_nm: float) -> None:
    fix["lat"], fix["lon"] = (round(value, 5) for value in step(fix["lat"], fix["lon"], course, distance_nm))


def _two_places_track():
    """From fix 31 on, every other fix is reported 12 nm north of the ship, as by a second transmitter."""
    track = _straight(53.40, -5.62, 95, 11.0, 41)
    for fix in track[31::2]:
        _moved(fix, 0, 12)
    return track


def _small_craft_track():
    """Moves at 9 kn but declares 2 kn for six fixes; one later fix lies inland on the Isle of Man."""
    track = _straight(53.50, -5.40, 80, 9.0, 30)
    for fix in track[10:16]:
        fix["sog_kn"] = 2.0
    track[25].update(lat=54.23, lon=-4.53)
    return track


def _glitch_track():
    """One fix 2.5 nm off a steady track and straight back: a single outlier, not a spoofing sign."""
    track = _straight(51.98, -6.30, 250, 12.0, 30)
    _moved(track[20], 340, 2.5)
    return track


# Simulated items scored on a fictional timed AIS track: (alert_board._item row, AIS class, track builder).
# The row's position is replaced by the track's last fix.
TRACK_ITEMS = [
    (("SIM-45", "AMBER SKERRY", "Bulk carrier", 185, "dublin-holyhead", 0, 0, 95, 11.0, 6, "line",
      "Same MMSI reported in two places 12 nm apart while heading for the Dublin–Holyhead cable",
      "Identity in doubt: request a satellite radar look to see which position is real, then hail on VHF 16.",
      {"slowdown_near_corridor": True, "eta_min": 40}), "A", _two_places_track),
    (("SIM-46", "TALLOW FINCH", "Pleasure craft", 12, "north-dublin", 0, 0, 80, 9.0, 9, "line",
      "Declared 12 m pleasure craft: speed does not match its positions, and one fix lies inland on the Isle of Man",
      "Declared data in doubt despite the small size: request identification before the craft reaches the line.",
      {"slowdown_near_corridor": True, "eta_min": 50}), "B", _small_craft_track),
    (("SIM-47", "BEARA DAWN", "General cargo", 140, "greenlink", 0, 0, 250, 12.0, 15, "line",
      "One AIS fix 2.5 nm off a steady track, then straight back",
      "Likely a GPS glitch: monitor only.",
      {"eta_min": 70}), "A", _glitch_track),
]

# Simulated items that cross their line and move away: (alert_board._item row, AIS class,
# minutes after the ETA when the item is clear, observations then, title then).
PASSING_ITEMS = [
    (("SIM-48", "FAIR ISLE", "General cargo", 120, "greenlink", 51.95, -6.55, 110, 9.0, 3, "line",
      "Unexplained slowdown 25 min before the Greenlink power interconnector",
      "Watch the crossing; hail on VHF 16 if it slows further over the line.",
      {"slowdown_near_corridor": True, "eta_min": 25}), "A", 10,
     {"distance_nm": 3.0}, "Crossed Greenlink at steady speed and is moving away"),
]

# Illustrative routes as detector lines. Their depth is unknown, so cable_risk assumes an anchor
# reaches the seabed along the whole route and says so in its findings.
STORY_LINES = [{"id": line_id, "name": name, "kind": kind, "label": "illustrative",
                "path": [list(point) for point in path], "anchor_reachable": None, "min_depth_m": None}
               for line_id, (name, kind, path) in LINES.items()]


def _on_line(line_id: str, lon: float) -> float:
    """Latitude of an illustrative route at a longitude (routes run east-west)."""
    path = LINES[line_id][2]
    for (lat0, lon0), (lat1, lon1) in zip(path, path[1:]):
        if min(lon0, lon1) <= lon <= max(lon0, lon1):
            return lat0 + (lat1 - lat0) * (lon - lon0) / (lon1 - lon0)
    raise ValueError(f"{lon} is outside {line_id}")


def _timed_track(start_t: int, start: tuple[float, float], legs) -> list[dict]:
    """Fixes once a minute from replay time ``start_t``; legs are (minutes, SOG kn, COG or COG(minute), nav status)."""
    (lat, lon), t, fixes = start, start_t, []
    for minutes, sog, cog, status in legs:
        for minute in range(minutes):
            course = (cog(minute) if callable(cog) else cog) % 360
            fixes.append({"t": t, "lat": round(lat, 5), "lon": round(lon, 5), "sog_kn": sog,
                          "cog_deg": round(course, 1), **({"nav_status": status} if status else {})})
            lat, lon = step(lat, lon, course, sog / 60)
            t += 60
    return fixes


def _yaw(course: float):
    """An unsteady course: +/-15 degrees about ``course``."""
    return lambda minute: course + 15 * math.sin(minute / 2)


def _drag_story() -> list[dict]:
    """North across the Dublin–Holyhead route at 12 kn, then 9 kn with a yawing course onto EWIC; no AIS gap."""
    start = (_on_line("dublin-holyhead", -5.27) - 7 / 60, -5.27)
    return _timed_track(75 * 60, start, [(37, 12.0, 5, None), (6, 9.0, 5, None), (25, 9.0, _yaw(5), None),
                                         (15, 6.0, _yaw(5), None), (60, 12.0, 90, None)])


def _hold_story() -> list[dict]:
    """Arrives, circles at 0.8 kn 1.5 nm from the North Dublin cluster for 75 min, then anchors 0.8 nm from it."""
    spot = (_on_line("north-dublin", -5.0) + 1.5 / 60, -5.0)
    return _timed_track(50 * 60, step(*spot, 45, 2.5), [
        (15, 10.0, 225, None), (75, 0.8, lambda minute: minute * 6, None), (10, 4.0, 180, None),
        (90, 0.1, 180, "at anchor")])


def _anchorage_story() -> list[dict]:
    """At anchor in south Dublin Bay, about 3 nm from the nearest route, swinging on its anchor."""
    return _timed_track(80 * 60, (53.30, -6.06),
                        [(150, 0.1, lambda minute: 200 + 20 * math.sin(minute / 9), "at anchor")])


def _ferry_story() -> list[dict]:
    """A fast ferry crossing the lines towards the Isle of Man at a steady 19 kn."""
    return _timed_track(95 * 60, (53.33, -6.00), [(70, 19.0, 60, None)])


def _dirty_feed_story() -> list[dict]:
    """A steady 11 kn transit through the North Channel approach, as a faulty AIS feed delivers it.

    Damage, by fix: three positions missing or "not available" (lat 91 / lon 181), one 0,0
    default, two fixes received twice, one pair out of time order, speed "not available"
    (102.3) on one, course "not available" (360) on another, and speeds sent as text.
    """
    track = _timed_track(40 * 60, (53.62, -5.75), [(150, 11.0, 20, None)])
    track[12]["lat"] = None
    track[30].update(lat=91, lon=181)
    track[47]["lon"] = None
    track[60].update(lat=0, lon=0)
    track[75]["sog_kn"] = 102.3
    track[90]["cog_deg"] = 360
    for fix in track[100:110]:
        fix["sog_kn"] = str(fix["sog_kn"])
    track[120], track[121] = track[121], track[120]
    return track[:20] + [dict(track[19])] + track[20:80] + [dict(track[79])] + track[80:]


def _wrong_way_story() -> list[dict]:
    """Declares Fishguard and steams towards it across St George's Channel, then turns south-west away from it
    towards Greenlink and slows by the line. It starts after the scripted Dublin stories (T+02:20) and ends
    with them at T+04:00, far from their responders."""
    return _timed_track(140 * 60, (52.15, -5.95), [(20, 12.0, 95, None), (45, 11.0, 230, None),
                                                   (35, 5.0, _yaw(210), None)])
DARK_GAP_S = (80 * 60, 125 * 60)  # SIM-57's AIS is silent from minute 80 until minute 125
DARK_PASS_S = 110 * 60  # a simulated satellite radar pass sees it at minute 110


def _dark_truth() -> list[dict]:
    """Where SIM-57 really is: north at 12 kn towards the Dublin–Holyhead route, then 6 kn and yawing across it."""
    start = (_on_line("dublin-holyhead", -5.55) - 15 / 60, -5.55)
    return _timed_track(60 * 60, start, [(55, 12.0, 0, None), (10, 6.0, 0, None), (35, 6.0, _yaw(0), None),
                                         (20, 3.0, _yaw(0), None), (40, 12.0, 45, None)])


def _dark_story() -> list[dict]:
    """SIM-57's AIS: its true track with no fixes during the gap. The gap is not filled in."""
    return [fix for fix in _dark_truth() if not DARK_GAP_S[0] <= fix["t"] < DARK_GAP_S[1]]


def _dark_contacts() -> list[dict]:
    """One simulated radar contact at SIM-57's true position during its AIS gap; Space has matched no AIS to it."""
    fix = next(fix for fix in _dark_truth() if fix["t"] == DARK_PASS_S)
    return [{"t": DARK_PASS_S, "lat": fix["lat"], "lon": fix["lon"], "length_m": 196, "source": "sentinel1",
             "scene_id": "S1A_IW_GRDH_SIMULATED_SIM54", "matched_mmsi": None, "label": "simulated"}]


def _declaration_story() -> list[dict]:
    """Towards Liverpool at 12 kn, then north-west for an hour, then 'at anchor' while still making 4 kn over the lines."""
    return _timed_track(70 * 60, (53.25, -5.60), [(30, 12.0, 75, None), (60, 12.0, 320, None),
                                                  (45, 4.0, 320, "at anchor"), (30, 0.3, 320, "at anchor")])


def _stop_story() -> list[dict]:
    """North-east at 11 kn, then stopped for 2.5 h between EWIC and the North Dublin cluster, about 4 nm from each."""
    spot = (53.50, -4.80)
    return _timed_track(65 * 60, step(*spot, 225, 11.0 * 40 / 60), [(40, 11.0, 45, None), (150, 0.2, 45, None)])


def _survey_story() -> list[dict]:
    """Survey lines along EWIC at 3.5 kn towing side-scan sonar: east, step 0.2 nm south, west, and so on."""
    start = (_on_line("ewic", -5.80), -5.80)
    run, step_leg = (30, 3.5, 96, None), (3, 3.5, 186, None)
    back = (30, 3.5, 276, None)
    return _timed_track(60 * 60, start, [run, step_leg, back, step_leg, run, step_leg, back, step_leg, run])


def _notice_area_story() -> list[dict]:
    """Arrives off Rush and circles at 1 kn for 80 min inside the real Marine Notice 49/2026 work area."""
    spot = (53.536, -6.03)
    return _timed_track(100 * 60, step(*spot, 270, 2.0), [
        (12, 10.0, 90, None), (80, 1.0, lambda minute: minute * 5, None)])


# A fictional exercise notice in the format of a real Marine Notice, naming the SIM-56 survey vessel.
EXERCISE_NOTICES = [{
    "number": "EX 1/2026", "title": "EWIC exercise cable survey (fictional)", "url": None, "issued": None,
    "amended": None, "asset": "EWIC", "asset_kind": "power",
    "work": "Geophysical survey with towed side-scan sonar (fictional, for the exercise)",
    "valid_from": None, "valid_to": None, "end_note": "For the exercise replay only",
    "vessels": [{"name": "GANNET SOUNDER", "call_sign": "EXSIM56", "role": "survey vessel", "valid_from": None}],
    "areas": [{"kind": "route", "points": [[round(_on_line("ewic", lon), 5), lon] for lon in (-5.95, -5.60, -5.40)],
               "buffer_nm": 1.0}],
    "area_note": "Exercise work area: 1 nm either side of the illustrative EWIC route", "label": "fictional"}]


# Stories on the replay clock: (alert_board._item row, AIS class, track builder). The row's position,
# course and speed are replaced by the track at each replay time; observations come only from detectors.
STORY_ITEMS = [
    (("SIM-50", "VESNA DRIFT", "General cargo", 190, "ewic", 0, 0, 0, 0, 0, "line",
      "Slowing and yawing across EWIC without an AIS gap",
      "Hail on VHF 16 and ask the master to confirm both anchors are secured; send the nearest drone for eyes on.",
      {}), "A", _drag_story),
    (("SIM-51", "HOLM SENTINEL", "General cargo", 165, "north-dublin", 0, 0, 0, 0, 0, "line",
      "Holding beside the North Dublin cable cluster, then anchoring next to it",
      "Ask the master why the ship is holding there and to anchor clear of the charted cables.",
      {}), "A", _hold_story),
    (("SIM-52", "LAMBAY ROSE", "Bulk carrier", 210, "dublin-holyhead", 0, 0, 0, 0, 0, "line",
      "At anchor in Dublin Bay, outside every cable corridor",
      "Normal anchorage use; no action.",
      {}), "A", _anchorage_story),
    (("SIM-53", "SKERRIES DART", "Passenger ferry", 98, "north-dublin", 0, 0, 0, 0, 0, "line",
      "Fast ferry crossing the cable corridors at a steady speed",
      "Normal transit; no action.",
      {}), "A", _ferry_story),
    (("SIM-55", "SALTEE HERON", "General cargo", 120, "greenlink", 0, 0, 0, 0, 0, "line",
      "Declares Fishguard but turned away from it towards Greenlink and slowed by the line",
      "Ask the master on VHF 16 to confirm the destination and intentions; watch the Greenlink corridor.",
      {}), "A", _wrong_way_story),
    (("SIM-57", "MOURNE SHADE", "General cargo", 190, "dublin-holyhead", 0, 0, 0, 0, 0, "line",
      "AIS went silent on the approach to the Dublin–Holyhead cable; a satellite radar contact fits its track",
      "Compare the radar length with the declared one, hail on VHF 16 when AIS returns and send the nearest "
      "drone for eyes on.",
      {}), "A", _dark_story),
    (("SIM-58", "CALLOW BAY", "General cargo", 140, "north-dublin", 0, 0, 0, 0, 0, "line",
      "Declared Dublin to Liverpool but turned north-west, then reports 'at anchor' while moving over the cables",
      "Ask the master to confirm the destination and anchor status; request a satellite or drone look before "
      "the North Dublin cluster.",
      {}), "A", _declaration_story),
    (("SIM-59", "TUSKAR CALM", "Bulk carrier", 180, "ewic", 0, 0, 0, 0, 0, "line",
      "Stopped at sea between EWIC and the North Dublin cluster, away from any port or anchorage",
      "Hail on VHF 16 to ask why the ship is stopped; offer assistance if it reports engine trouble.",
      {}), "A", _stop_story),
    (("SIM-56", "GANNET SOUNDER", "Survey vessel", 72, "ewic", 0, 0, 0, 0, 0, "line",
      "Survey lines along EWIC at 3.5 kn, named in the exercise Marine Notice",
      "Declared work: confirm on VHF 16 that the ship is the notified survey vessel; no other action.",
      {}), "A", _survey_story),
    (("SIM-60", "ROCKABILL TERN", "General cargo", 110, "ewic", 0, 0, 0, 0, 0, "line",
      "Circling off Rush inside the Marine Notice 49/2026 work area, but not a notified vessel",
      "Not explained by the notice: hail on VHF 16 and ask why the ship is holding over EWIC.",
      {}), "A", _notice_area_story),
    (("SIM-49", "KESTREL MOOR", "General cargo", 150, "north-dublin", 0, 0, 0, 0, 0, "line",
      "Steady transit; its AIS feed has missing positions, repeated times and 'not available' values",
      "Normal transit; Brain ignored the faulty fixes and lists them in the review. Check the AIS receiver.",
      {}), "A", _dirty_feed_story),
]
# What a story's vessel declares and what a satellite sees, beyond its AIS track (fictional and simulated);
# builders, like the tracks, called once by build_board.
STORY_EXTRAS = {
    "SIM-57": {"detections": _dark_contacts},
    "SIM-58": {"destination": lambda: "IEDUB>GBLIV"},
}

STORY_DESTINATIONS = {"SIM-55": "GBFIS"}
# Fictional AIS call signs (Message 5) that the Marine Notice check reads.
STORY_CALL_SIGNS = {"SIM-56": "EXSIM56", "SIM-60": "EXSIM57"}
STORY_TRAIL_S = 3 * 3600  # the map trail shows the window the detectors read

# Board-only detectors whose reasons are already the item's title; other detectors' reasons become notes.
QUIET_DETECTORS = frozenset({"alert_board_simulated", "legacy_cable_v1"})
DETECTOR_NOTE_REASONS = 4


def _vessel(item: dict, ais_class: str) -> dict:
    return {"mmsi": item["id"], "name": item["name"], "ship_type": SHIP_TYPES.get(item["vessel_type"]),
            "ais_class": ais_class, "ais_length_m": item.get("length_m") or None,
            "destination": item.get("destination"), "call_sign": item.get("call_sign"),
            "nav_status": None, "track": [], "label": item["label"]}


def _board_findings(item: dict, other_lines=()):
    """A detector that reports the item's hand-written simulated observations, one finding per line."""
    def finding(line_id, obs, reason):
        return {"detector": "alert_board_simulated", "mmsi": item["id"], "t": 0,
                "position": [item["lat"], item["lon"]], "strength": 1.0, "reasons": [reason],
                "related": {"cable_id": line_id}, "label": item["label"], "obs": obs}

    def detect(vessel, context):
        found = [finding(item["line_id"], item["observations"], item["title"])]
        for line_id, obs in other_lines:
            name, asset_class, _path = LINES[line_id]
            found.append(finding(line_id, {"asset_class": asset_class, **obs}, f"Projected to reach {name}"))
        return found
    return detect


def _detector_notes(findings: list[dict]) -> list[str]:
    """Track detectors' reasons (summary first), shown under the indicators so a reviewer sees the numbers."""
    return [f"{finding['detector']}: {reason}" for finding in findings if finding["detector"] not in QUIET_DETECTORS
            for reason in finding["reasons"][:DETECTOR_NOTE_REASONS]]


def _with_notes(assessment: dict, notes: list[str]) -> dict:
    return {**assessment, "notes": assessment["notes"] + notes} if notes else assessment


def _finding_summary(finding: dict) -> dict:
    """What the review window shows of a finding: detector, data label, line and reasons."""
    obs, related = finding.get("obs") or {}, finding.get("related") or {}
    summary = {"detector": finding["detector"], "label": finding.get("label"), "t": finding.get("t"),
               "cable_id": related.get("cable_id"), "reasons": list(finding["reasons"]),
               "eta_min": obs.get("eta_min"), "distance_nm": obs.get("distance_nm"),
               "in_corridor": obs.get("in_corridor")}
    if related.get("notice"):
        summary["notice"] = {key: related.get(f"notice_{key}") for key in ("title", "url", "label")}
        summary["notice"].update(number=related["notice"], match=related.get("match"))
    return summary


def reassess(item: dict) -> None:
    """Score the item's current observations again, keeping the small-vessel rule and detector notes."""
    assessment = assess(item["observations"])
    if item.get("relevance"):
        assessment = apply_relevance(assessment, item["relevance"])
    item["assessment"] = _with_notes(assessment, item.get("detector_notes", []))


def _rescore(item: dict, result: dict) -> None:
    notes = _detector_notes(result["findings"])
    item.update(observations=result["observations"], assessment=_with_notes(result["assessment"], notes),
                relevance=result["relevance"], declared_work=result.get("declared_work"),
                cable_id=result["cable_id"], detector_notes=notes,
                detectors=[f["detector"] for f in result["findings"]],
                findings=[_finding_summary(f) for f in result["findings"]],
                data_quality=result.get("data_quality"), detector_errors=result.get("detector_errors", []))


def _received_by(fix, now) -> bool:
    """A received fix is in the feed by replay time ``now`` unless its numeric time is later."""
    t = fix.get("t") if isinstance(fix, dict) else None
    return not (isinstance(t, (int, float)) and not isinstance(t, bool) and t > now)


def story_vessel(item: dict, now: float | None = None) -> dict:
    """The fictional AIS vessel behind a story item, as the detectors read it: the track as received,
    up to replay time ``now`` when given."""
    received = item["story"].get("received", item["story"]["track"])
    if now is not None:
        received = [fix for fix in received if _received_by(fix, now)]
    return {**_vessel(item, item.get("ais_class", "A")), "track": received,
            "destination": item["story"].get("destination", item.get("destination"))}


def rescore_story(item: dict, now: float) -> None:
    """Score a story on its track up to replay time ``now`` with the registered detectors; move it on the map."""
    track = item["story"]["track"]
    _rescore(item, assess_vessel(story_vessel(item, now), {"now": int(now), "cables": STORY_LINES,
                     "notices": EXERCISE_NOTICES, "detections": item["story"].get("detections", [])}))
    seen = [fix for fix in track if fix["t"] <= now]
    if seen:
        last = seen[-1]
        item.update(lat=last["lat"], lon=last["lon"], cog_deg=last["cog_deg"], sog_kn=last["sog_kn"],
                    track=[(fix["lat"], fix["lon"]) for fix in seen if fix["t"] >= now - STORY_TRAIL_S][:-1])
    if item.get("cable_id") in LINES:
        item["line_id"], item["line_name"] = item["cable_id"], LINES[item["cable_id"]][0]
    # The story's title only once Brain sees behaviour or an identity cue (such as a dark radar contact);
    # before that the card says what it does see.
    if item["assessment"]["groups"]["B"] or item["assessment"]["groups"]["I"]:
        item["title"] = item["story"]["title"]
    else:
        distance = item["observations"].get("distance_nm")
        where = f"{distance:.1f} nm from {item['line_name']}" if distance is not None else "far from every line"
        doing = ("At anchor" if seen and last.get("nav_status") == "at anchor"
                 else "Not seen yet" if not seen else "Under way, speed not available" if last["sog_kn"] is None
                 else f"Under way at {last['sog_kn']:.0f} kn")
        cue = ("not heading to its declared destination" if item["observations"].get("route_inconsistent")
               else "no behaviour cue")
        item["title"] = f"{doing}, {where}: {cue}"


def build_board(scenario: dict | None = None, alerts: list | None = None) -> list[dict]:
    """Same items as ``alert_board.build_board`` plus twenty extras, scored through ``argus.assemble``.

    Story items are scored at the end of their track here; a replay scores them at its own time.
    """
    items = alert_board.build_board(scenario, alerts)
    other_lines, tracks = {}, {}
    for row, ais_class, others in EXTRA_ITEMS:
        items.append({**_item(*row), "ais_class": ais_class})
        other_lines[row[0]] = others
    for row, ais_class, make_track in TRACK_ITEMS:
        track = tracks[row[0]] = make_track()
        items.append({**_item(*row), "ais_class": ais_class, "lat": track[-1]["lat"], "lon": track[-1]["lon"],
                      "track": [(fix["lat"], fix["lon"]) for fix in track[:-1]]})
    for row, ais_class, clear_after_min, observations_then, title_then in PASSING_ITEMS:
        item = {**_item(*row), "ais_class": ais_class}
        item["passing"] = {"clear_min": item["eta_start_min"] + clear_after_min,
                           "before": (dict(item["observations"]), item["title"]),
                           "after": ({"asset_class": item["observations"]["asset_class"], **observations_then},
                                     title_then)}
        items.append(item)
    for row, ais_class, make_track in STORY_ITEMS:
        received = make_track()
        track = clean_vessel({"track": received})[0]["track"]  # what the map and card show
        extras = {key: make() for key, make in STORY_EXTRAS.get(row[0], {}).items()}
        items.append({**_item(*row), "ais_class": ais_class, "source": "track",
                      "destination": STORY_DESTINATIONS.get(row[0]), "call_sign": STORY_CALL_SIGNS.get(row[0]),
                      "story": {"track": track, "received": received, "start_s": track[0]["t"], "title": row[11], **extras}})
    context = context_from_scenario(scenario) if scenario else {}
    for item in items:
        if item.get("story"):
            rescore_story(item, item["story"]["track"][-1]["t"])
        elif item.get("exercise"):
            vessel = next(v for v in scenario["vessels"] if v["mmsi"] == item["alert"]["mmsi"])
            _rescore(item, assess_vessel(vessel, context))
        else:
            detector = _board_findings(item, other_lines.get(item["id"], ()))
            vessel = {**_vessel(item, item.get("ais_class", "A")), "track": tracks.get(item["id"], [])}
            _rescore(item, assess_vessel(vessel, {}, [detector, ais_spoofing.detect]))
    return sorted(items, key=sort_key)


def update(items: list[dict], elapsed_s: float) -> list[str]:
    """Count simulated ETAs down like ``alert_board.update``, keeping the small-vessel rule.

    ``elapsed_s`` may be negative (before the board start) or go backwards; the
    result depends only on it. A passing item takes its "after" observations
    once it is clear of the line.
    """
    before = {item["id"]: item["assessment"]["level"] for item in items}
    alert_board.update([item for item in items if "passing" not in item], elapsed_s)
    for item in items:
        passing = item.get("passing")
        if passing:
            clear = elapsed_s / 60 >= passing["clear_min"]
            observations, title = passing["after" if clear else "before"]
            item["observations"], item["title"] = dict(observations), title
            if not clear:
                item["observations"]["eta_min"] = max(0.0, item["eta_start_min"] - elapsed_s / 60)
            item["assessment"] = assess(item["observations"])
        if item.get("relevance") and (passing or item.get("eta_start_min") is not None):
            item["assessment"] = _with_notes(apply_relevance(item["assessment"], item["relevance"]),
                                             item.get("detector_notes", []))
    return [item["id"] for item in items if item["assessment"]["level"] != before[item["id"]]]


def rescore_exercise(item: dict, scenario: dict, now: float) -> None:
    """Score the exercise vessel on its track up to replay time ``now`` (None before its first fix)."""
    vessel = next(v for v in scenario["vessels"] if v["mmsi"] == item["alert"]["mmsi"])
    _rescore(item, assess_vessel(vessel, context_from_scenario(scenario, int(now))))
