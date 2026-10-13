"""Assemble detector findings into one explainable risk level per vessel.

Each detector is ``detect(vessel, context) -> list[finding]``. A finding names
its detector, vessel, time and reasons, and its ``obs`` dict holds the
``argus.levels`` observation keys it fills. This module runs the registered
detectors, merges their observations, applies the small-vessel relevance rule
and scores the result with ``argus.levels.assess``.

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
from argus.levels import CRITICAL_ASSETS, LEVEL_NAMES, RANK, RULES_VERSION, assess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/brain/assessments.json"

# Observation keys that describe one line; merged only from cable-related findings.
CABLE_KEYS = ("eta_min", "distance_nm", "asset_class")

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
    return [{
        "detector": "legacy_cable_v1", "mmsi": vessel["mmsi"], "t": alert["t"],
        "position": [item["lat"], item["lon"]], "strength": alert["score"], "reasons": alert["reasons"],
        "related": {"cable_id": alert["segment_id"]}, "label": vessel.get("label", "simulated"), "obs": obs,
    }]


# Registered detectors. Connect a new one by adding it to this list.
DETECTORS = [
    legacy_cable_v1,
]


def _asset_weight(asset_class: str) -> int:
    return 2 if asset_class in CRITICAL_ASSETS else 1


def merge_observations(findings: list[dict]) -> dict:
    """Combine findings' ``obs`` into one observation set for ``argus.levels.assess``.

    Numbers take the maximum and flags are true if any finding sets them.
    ``eta_min``, ``distance_nm`` and ``asset_class`` come only from findings with
    a ``related.cable_id``: the soonest ETA, the nearest distance and the most
    critical line. Other values keep the first finding's value.
    """
    obs: dict = {}
    for finding in findings:
        on_cable = bool((finding.get("related") or {}).get("cable_id"))
        for key, value in (finding.get("obs") or {}).items():
            if value is None:
                continue
            if key in CABLE_KEYS:
                if not on_cable:
                    continue
                if key == "asset_class":
                    if key not in obs or _asset_weight(value) > _asset_weight(obs[key]):
                        obs[key] = value
                elif key not in obs or value < obs[key]:
                    obs[key] = value
            elif isinstance(value, bool):
                obs[key] = bool(obs.get(key)) or value
            elif isinstance(value, (int, float)):
                if key not in obs or value > obs[key]:
                    obs[key] = value
            elif key not in obs:
                obs[key] = value
    return obs


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cap_exception(ship_type, length_m: float, obs: dict) -> str | None:
    """Evidence that makes a small vessel relevant after all."""
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
    not dropped, and the cap is lifted by identity or bottom-gear evidence.
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


def assess_vessel(vessel: dict, context: dict, detectors: list | None = None) -> dict:
    """Run the detectors on one vessel and return its findings, observations, relevance and level."""
    findings: list[dict] = []
    for detector in DETECTORS if detectors is None else detectors:
        findings.extend(detector(vessel, context))
    observations = merge_observations(findings)
    rel = relevance(vessel, observations)
    return {"findings": findings, "observations": observations, "relevance": rel,
            "assessment": apply_relevance(assess(observations), rel)}


def context_from_scenario(scenario: dict, now: int | None = None) -> dict:
    return {"now": now, "cables": scenario.get("cables", []), "ports": scenario.get("ports", []),
            "anchorages": scenario.get("anchorages", []), "detections": scenario.get("detections", []),
            "weather": scenario.get("weather"), "assets": scenario.get("assets", [])}


def build_assessments(scenario: dict, now: int | None = None) -> dict:
    validate_scenario(scenario)
    context = context_from_scenario(scenario, now)
    vessels = []
    for vessel in scenario["vessels"]:
        result = assess_vessel(vessel, context)
        vessels.append({"mmsi": vessel["mmsi"], "name": vessel.get("name"),
                        "label": vessel.get("label", "simulated"), **result})
    vessels.sort(key=lambda item: (-item["assessment"]["rank"], item["mmsi"]))
    return {"generated_by": f"argus.assemble ({RULES_VERSION})", "scenario": scenario.get("name", "Scenario"),
            "now": now, "detectors": [detector.__name__ for detector in DETECTORS],
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
