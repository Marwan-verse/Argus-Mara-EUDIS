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

``update`` is a pure function of the board time, so a replay can move the
board forwards or backwards; ``rescore_exercise`` re-scores the exercise
vessel at a replay time.

AIS ship types, classes and radar lengths below are assumptions for fictional
contacts. Nothing here reads live AIS or sends anything.
"""

from __future__ import annotations

from argus import alert_board
from argus.alert_board import LINES, _item, sort_key
from argus.assemble import apply_relevance, assess_vessel, context_from_scenario
from argus.countdown import step
from argus.detectors import ais_spoofing
from argus.levels import assess

# Assumed AIS ship type codes for the board's display types.
SHIP_TYPES = {
    "Trawler": 30, "Fishing vessel": 30, "Sailing yacht": 36, "Pleasure craft": 37, "Motor yacht": 37,
    "Pilot boat": 50, "Tug": 52, "Passenger ferry": 60, "General cargo": 70, "Container ship": 70,
    "Bulk carrier": 70, "Ro-ro cargo": 70, "Tanker": 80,
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

# Board-only detectors whose reasons are already the item's title; other detectors' reasons become notes.
QUIET_DETECTORS = frozenset({"alert_board_simulated", "legacy_cable_v1"})
DETECTOR_NOTE_REASONS = 4


def _vessel(item: dict, ais_class: str) -> dict:
    return {"mmsi": item["id"], "name": item["name"], "ship_type": SHIP_TYPES.get(item["vessel_type"]),
            "ais_class": ais_class, "ais_length_m": item.get("length_m") or None, "destination": None,
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
    obs = finding.get("obs") or {}
    return {"detector": finding["detector"], "label": finding.get("label"),
            "cable_id": (finding.get("related") or {}).get("cable_id"), "reasons": list(finding["reasons"]),
            "eta_min": obs.get("eta_min"), "distance_nm": obs.get("distance_nm"),
            "in_corridor": obs.get("in_corridor")}


def _rescore(item: dict, result: dict) -> None:
    notes = _detector_notes(result["findings"])
    item.update(observations=result["observations"], assessment=_with_notes(result["assessment"], notes),
                relevance=result["relevance"], cable_id=result["cable_id"], detector_notes=notes,
                detectors=[f["detector"] for f in result["findings"]],
                findings=[_finding_summary(f) for f in result["findings"]])


def build_board(scenario: dict | None = None, alerts: list | None = None) -> list[dict]:
    """Same items as ``alert_board.build_board`` plus eight extras, scored through ``argus.assemble``."""
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
    context = context_from_scenario(scenario) if scenario else {}
    for item in items:
        if item.get("exercise"):
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
