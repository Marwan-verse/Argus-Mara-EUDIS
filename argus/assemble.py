"""Assemble detector findings into one explainable risk level per vessel.

Each detector is ``detect(vessel, context) -> list[finding]``. A finding names
its detector, vessel, time and reasons, and its ``obs`` dict holds the
``argus.levels`` observation keys it fills. This module runs the registered
detectors, merges their observations, applies the small-vessel relevance rule
and scores the result with ``argus.levels.assess``.

Two rules for detector authors:

* ``eta_min``, ``distance_nm``, ``asset_class``, ``in_corridor`` and
  ``method_possible`` count only when the finding names ``related.cable_id``.
  They are then taken together from the single most urgent cable, never mixed
  across cables.
* Put a radar-measured length in ``obs["radar_length_m"]``. The small-vessel
  filter uses it to see that a vessel declared small is really large.

The output is a separate review file. ``demo/alerts.json`` is not touched, and a
level is a rule outcome, not a probability of hostile intent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from argus.alert_board import exercise_item
from argus.brain import detect_vessel
from argus.contracts import validate_scenario
from argus.detectors import ais_spoofing, cable_risk, dark_vessel, declared_vs_actual, stop_off_port
from argus.levels import CRITICAL_ASSETS, LEVEL_NAMES, RANK, RULES_VERSION, assess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/brain/assessments.json"

# Observation keys that describe one line. They come only from findings with a
# related.cable_id, and all of them from the same, most urgent cable.
# method_possible is False when only a section too deep for an anchor is near.
CABLE_KEYS = ("in_corridor", "eta_min", "distance_nm", "asset_class", "method_possible")

# Small-vessel relevance. These thresholds are assumptions, not regulation:
# small craft rarely carry anchors or gear heavy enough to damage a buried line.
SMALL_CLASS_B_MAX_M = 30
SMALL_TYPE_MAX_M = 50
FISHING_SHIP_TYPE = 30
SMALL_SHIP_TYPES = frozenset({FISHING_SHIP_TYPE, 36, 37, *range(50, 60)})  # fishing, sailing, pleasure, special craft
LENGTH_EVIDENCE_RATIO = 1.25  # radar >= 25% longer than declared; same margin as rule I4 in argus.levels
FISHING_PASSES_MIN = 3  # same count as rule B5 in argus.levels


def legacy_cable_v1(vessel: dict, context: dict) -> list[dict]:
    """The four-cue rule from ``argus.brain``, mapped to levels like the alert board's exercise item."""
    now = context.get("now")
    track = vessel["track"] if now is None else [fix for fix in vessel["track"] if fix["t"] <= now]
    cables, detections = context.get("cables", []), context.get("detections", [])
    alert = detect_vessel({**vessel, "track": track}, cables, context.get("assets", []), detections, "A1")
    if alert is None:
        return []
    item = exercise_item({"vessels": [vessel], "cables": cables, "detections": detections}, alert)
    obs = dict(item["observations"])
    radar_t = alert["observations"].get("radar_contact_t")
    radar = next((d for d in detections if radar_t is not None and d.get("t") == radar_t), None)
    if radar and radar.get("length_m"):
        obs["radar_length_m"] = radar["length_m"]
    # exercise_item always says "telecom"; score the alerted cable's own kind instead.
    # Assumption: a kind argus.levels does not name (not telecom or a CRITICAL_ASSETS key) counts as telecom.
    kind = next((c.get("kind") for c in cables if c["id"] == alert["segment_id"]), None)
    obs["asset_class"] = kind if kind == "telecom" or kind in CRITICAL_ASSETS else "telecom"
    return [{
        "detector": "legacy_cable_v1", "mmsi": vessel["mmsi"], "t": alert["t"],
        "position": [item["lat"], item["lon"]], "strength": alert["score"], "reasons": alert["reasons"],
        "related": {"cable_id": alert["segment_id"]}, "label": vessel.get("label", "simulated"), "obs": obs,
    }]


# Registered detectors. Connect a new one by adding it to this list.
DETECTORS = [
    legacy_cable_v1,
    ais_spoofing.detect,
    cable_risk.detect,
    stop_off_port.detect,
    dark_vessel.detect,
    declared_vs_actual.detect,
]
# Registered detectors not run on scenario files (the fictional exercise) until the team agrees: dark_vessel
# would raise the exercise to Medium at T+40, when the radar sees it in its AIS gap, instead of at the agreed
# T+90 alert (decision D63). Empty the tuple to run it there too; stories and other contacts always run it.
HELD_FROM_SCENARIO = ("dark_vessel",)


def _asset_weight(asset_class: str) -> int:
    return 2 if asset_class in CRITICAL_ASSETS else 1


def _urgency(line: dict) -> tuple:
    """Sort key: a line an anchor can damage first, then inside the corridor, the soonest ETA, the nearest
    distance and the most critical line."""
    eta, distance = line.get("eta_min"), line.get("distance_nm")
    return (line.get("method_possible") is False, not line.get("in_corridor"), float("inf") if eta is None else eta,
            float("inf") if distance is None else distance, -_asset_weight(line.get("asset_class")))


def threatened_cable(findings: list[dict]) -> tuple[str | None, dict]:
    """Pick the one line under threat; return its cable ID and its ``CABLE_KEYS`` values.

    Findings naming the same ``related.cable_id`` are combined first (in the
    corridor or damage feasible if any says so, soonest ETA, nearest distance,
    most critical class). The most urgent cable then wins; ties keep the first one found.
    """
    lines: dict[str, dict] = {}
    for finding in findings:
        cable_id = (finding.get("related") or {}).get("cable_id")
        if not cable_id:
            continue
        line = lines.setdefault(cable_id, {})
        for key in CABLE_KEYS:
            value = (finding.get("obs") or {}).get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                line[key] = bool(line.get(key)) or value
            elif key == "asset_class":
                if key not in line or _asset_weight(value) > _asset_weight(line[key]):
                    line[key] = value
            elif key not in line or value < line[key]:
                line[key] = value
    if not lines:
        return None, {}
    cable_id = min(lines, key=lambda identifier: _urgency(lines[identifier]))
    return cable_id, lines[cable_id]


def merge_observations(findings: list[dict]) -> dict:
    """Combine findings' ``obs`` into one observation set for ``argus.levels.assess``.

    Numbers take the maximum and flags are true if any finding sets them.
    ``eta_min``, ``distance_nm``, ``asset_class``, ``in_corridor`` and
    ``method_possible`` count only when the finding names ``related.cable_id``,
    and all five come together from
    the most urgent cable (see ``threatened_cable``). A radar-measured length
    belongs in ``radar_length_m``; the small-vessel filter reads it. Other
    values keep the first finding's value.
    """
    obs: dict = {}
    for finding in findings:
        for key, value in (finding.get("obs") or {}).items():
            if value is None or key in CABLE_KEYS:
                continue
            if isinstance(value, bool):
                obs[key] = bool(obs.get(key)) or value
            elif isinstance(value, (int, float)):
                if key not in obs or value > obs[key]:
                    obs[key] = value
            elif key not in obs:
                obs[key] = value
    obs.update(threatened_cable(findings)[1])
    return obs


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cap_exception(ship_type, length_m: float, obs: dict) -> str | None:
    """Evidence that makes a small vessel relevant after all.

    Recorded facts come first: the small-vessel cap is an assumption and must
    not override a reported line fault or ignored instruction from argus.levels.
    """
    if obs.get("fault_confirmed"):
        return "a line fault is reported at this position and time"
    if obs.get("ignored_instruction"):
        return "the vessel did not comply with a recorded instruction near the line"
    radar_length = obs.get("radar_length_m")
    if radar_length and radar_length >= length_m * LENGTH_EVIDENCE_RATIO:
        return (f"radar measured {radar_length:.0f} m against a declared {length_m:g} m, "
                "so the declared identity is in doubt")
    if obs.get("spoof_signs"):
        return "position jumps or a duplicate identity put the declared data in doubt"
    if ship_type == FISHING_SHIP_TYPE and ((obs.get("passes_6h") or 0) >= FISHING_PASSES_MIN
                                           or obs.get("fishing_near_corridor") or obs.get("in_corridor")):
        return "fishing vessel working at the line; bottom gear can damage cables"
    return None


def relevance(vessel: dict, observations: dict | None = None) -> dict:
    """Decide whether a vessel is small and whether its level is capped at Low.

    Small: AIS class B under 30 m, or ship type 30/36/37/50-59 under 50 m.
    Unknown or zero length is never treated as small. Small vessels are kept,
    not dropped, and the cap is lifted by a reported line fault, an ignored
    instruction, identity evidence or bottom-gear evidence.
    """
    obs = observations or {}
    length = vessel.get("ais_length_m")
    ship_type = _as_int(vessel.get("ship_type"))
    reason = None
    if isinstance(length, (int, float)) and length > 0:
        if str(vessel.get("ais_class", "")).upper() == "B" and length < SMALL_CLASS_B_MAX_M:
            reason = f"AIS class B, declared length {length:g} m, under {SMALL_CLASS_B_MAX_M} m"
        elif ship_type in SMALL_SHIP_TYPES and length < SMALL_TYPE_MAX_M:
            reason = f"AIS ship type {ship_type}, declared length {length:g} m, under {SMALL_TYPE_MAX_M} m"
    if reason is None:
        return {"small": False, "cap": None, "reason": None, "exception": None}
    exception = _cap_exception(ship_type, length, obs)
    return {"small": True, "cap": None if exception else "low", "reason": reason, "exception": exception}


def apply_relevance(assessment: dict, rel: dict) -> dict:
    if not rel["small"]:
        return assessment
    notes = list(assessment["notes"])
    result = {**assessment, "notes": notes}
    if rel["exception"]:
        notes.append(f"Small-vessel cap not applied: {rel['exception']}.")
    elif RANK[assessment["level"]] > RANK[rel["cap"]]:
        result.update(level=rel["cap"], level_name=LEVEL_NAMES[rel["cap"]], rank=RANK[rel["cap"]])
        notes.append(f"Capped at Low: small vessel ({rel['reason']}). Assumption: its anchor and gear "
                     "are unlikely to damage the line.")
    return result


def registered(context: dict) -> list:
    """The registered detectors this context runs: all of them, less any it holds (``context["held"]``)."""
    held = context.get("held", ())
    return [detector for detector in DETECTORS if detector.__name__ not in held]


def assess_vessel(vessel: dict, context: dict, detectors: list | None = None) -> dict:
    """Run the detectors on one vessel and return its findings, threatened cable, observations, relevance and level.

    Without ``detectors`` the registered ones run, less any the context holds.
    """
    findings: list[dict] = []
    for detector in registered(context) if detectors is None else detectors:
        findings.extend(detector(vessel, context))
    observations = merge_observations(findings)
    rel = relevance(vessel, observations)
    return {"findings": findings, "cable_id": threatened_cable(findings)[0], "observations": observations,
            "relevance": rel, "assessment": apply_relevance(assess(observations), rel)}


def context_from_scenario(scenario: dict, now: int | None = None) -> dict:
    return {"now": now, "cables": scenario.get("cables", []), "ports": scenario.get("ports", []),
            "anchorages": scenario.get("anchorages", []), "detections": scenario.get("detections", []),
            "weather": scenario.get("weather"), "assets": scenario.get("assets", []), "held": HELD_FROM_SCENARIO}


def build_assessments(scenario: dict, now: int | None = None) -> dict:
    """Assess every vessel, and every radar contact that no AIS vessel can explain (``dark_vessel``)."""
    validate_scenario(scenario)
    context = context_from_scenario(scenario, now)
    contacts = ([] if dark_vessel.DETECTOR in context["held"]
                else dark_vessel.radar_only_vessels(scenario["vessels"], context["detections"], now))
    vessels = []
    for vessel in scenario["vessels"] + contacts:
        result = assess_vessel(vessel, context)
        vessels.append({"mmsi": vessel["mmsi"], "name": vessel.get("name"),
                        "label": vessel.get("label", "simulated"), **result})
    vessels.sort(key=lambda item: (-item["assessment"]["rank"], str(item["mmsi"])))  # radar-only IDs are text
    return {"generated_by": f"argus.assemble ({RULES_VERSION})", "scenario": scenario.get("name", "Scenario"),
            "now": now, "detectors": [detector.__name__ for detector in registered(context)],
            "note": "Levels are rule outcomes for human review, not probabilities of hostile intent.",
            "vessels": vessels}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=ROOT / "demo/scenario.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--now", type=int, help="replay time in seconds; fixes after it are ignored")
    args = parser.parse_args()
    protected = {args.scenario.resolve(), (ROOT / "demo/alerts.json").resolve()}
    if args.output.resolve() in protected:
        parser.error("output must not overwrite the scenario or demo/alerts.json")
    try:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        result = build_assessments(scenario, args.now)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Brain assembly failed: {error}\n")
    levels = ", ".join(f"{item['mmsi']} {item['assessment']['level']}" for item in result["vessels"])
    print(f"Brain assessments -> {args.output} ({levels or 'no vessels'})")


if __name__ == "__main__":
    main()
