"""The simulated alert board, scored through Brain's assembler.

``argus.alert_board`` builds the fictional exercise item and the simulated
contacts. Here every item is re-scored through ``argus.assemble``: the exercise
vessel runs the registered detectors on the scenario, and each simulated item's
hand-written observations enter as findings. The small-vessel relevance rule
then caps or explains the level. Five extra simulated items show the rules:
small craft that are capped or not (SIM-40 to SIM-43) and a ship approaching
two lines at once, scored for the more urgent one (SIM-44).

AIS ship types, classes and radar lengths below are assumptions for fictional
contacts. Nothing here reads live AIS or sends anything.
"""

from __future__ import annotations

from argus import alert_board
from argus.alert_board import LINES, _item, sort_key
from argus.assemble import apply_relevance, assess_vessel, context_from_scenario

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


def _rescore(item: dict, result: dict) -> None:
    item.update(observations=result["observations"], assessment=result["assessment"],
                relevance=result["relevance"], cable_id=result["cable_id"],
                detectors=[f["detector"] for f in result["findings"]])


def build_board(scenario: dict | None = None, alerts: list | None = None) -> list[dict]:
    """Same items as ``alert_board.build_board`` plus five extras, scored through ``argus.assemble``."""
    items = alert_board.build_board(scenario, alerts)
    other_lines = {}
    for row, ais_class, others in EXTRA_ITEMS:
        items.append({**_item(*row), "ais_class": ais_class})
        other_lines[row[0]] = others
    context = context_from_scenario(scenario) if scenario else {}
    for item in items:
        if item.get("exercise"):
            vessel = next(v for v in scenario["vessels"] if v["mmsi"] == item["alert"]["mmsi"])
            _rescore(item, assess_vessel(vessel, context))
        else:
            detector = _board_findings(item, other_lines.get(item["id"], ()))
            _rescore(item, assess_vessel(_vessel(item, item.get("ais_class", "A")), {}, [detector]))
    return sorted(items, key=sort_key)


def update(items: list[dict], elapsed_s: float) -> list[str]:
    """Count simulated ETAs down like ``alert_board.update``, keeping the small-vessel rule."""
    before = {item["id"]: item["assessment"]["level"] for item in items}
    alert_board.update(items, elapsed_s)
    for item in items:
        if item.get("relevance") and item.get("eta_start_min") is not None:
            item["assessment"] = apply_relevance(item["assessment"], item["relevance"])
    return [item["id"] for item in items if item["assessment"]["level"] != before[item["id"]]]
