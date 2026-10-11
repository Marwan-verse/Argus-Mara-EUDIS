"""Rule-based Anchor Watch alerts for the file-based offline demonstration.

The score is the fraction of four documented review cues met. It is not a
probability of hostile intent. No radar identity or motive is inferred here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from argus.contracts import validate_alerts, validate_scenario
from argus.countdown import nm_between, project_to_cable, response_options

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIX_INTERVAL_S = 60
MIN_GAP_S = 10 * 60
MIN_SPEED_DROP_FRACTION = 0.20
MIN_COURSE_CHANGE_DEG = 20
MAX_GAP_AGE_S = 90 * 60
ANCHOR_REACH_CUTOFF_M = 250  # Scenario assumption, not vessel-specific physics.


def course_difference(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def recent_gap(track, now_s):
    """Last observed reception gap; only fixes known at now_s may be used."""
    found = None
    for before, after in zip(track, track[1:]):
        if after["t"] > now_s:
            break
        silent_s = after["t"] - before["t"] - EXPECTED_FIX_INTERVAL_S
        if silent_s >= MIN_GAP_S and now_s - after["t"] <= MAX_GAP_AGE_S:
            found = before, after, silent_s
    return found


def _gap_windows(track):
    """Yield each observed fix with its latest eligible gap in one pass.

    Tracks are time-ordered by the scenario contract. A gap is first available
    at its returning fix and remains eligible at exactly MAX_GAP_AGE_S.
    """
    previous = latest = None
    for fix in track:
        if previous is not None:
            silent_s = fix["t"] - previous["t"] - EXPECTED_FIX_INTERVAL_S
            if silent_s >= MIN_GAP_S:
                latest = previous, fix, silent_s
        gap = latest if latest and fix["t"] - latest[1]["t"] <= MAX_GAP_AGE_S else None
        yield fix, gap
        previous = fix


def detect_vessel(vessel, cables, assets, detections, alert_id):
    """Return the earliest explainable alert for one vessel, or None."""
    track = vessel["track"]
    for fix, gap in _gap_windows(track):
        if gap is None:
            continue
        before, after, silent_s = gap
        if before["sog_kn"] <= 0 or fix["sog_kn"] is None:
            continue
        speed_drop = (before["sog_kn"] - fix["sog_kn"]) / before["sog_kn"]
        turn_deg = course_difference(before["cog_deg"], fix["cog_deg"])
        if speed_drop < MIN_SPEED_DROP_FRACTION or turn_deg < MIN_COURSE_CHANGE_DEG:
            continue
        for cable in cables:
            if not cable.get("anchor_reachable") or cable.get("min_depth_m", float("inf")) > ANCHOR_REACH_CUTOFF_M:
                continue
            expected_s, crossing = project_to_cable(
                fix["lat"], fix["lon"], fix["cog_deg"], fix["sog_kn"], cable["path"]
            )
            if expected_s is None:
                continue
            earliest_s, _ = project_to_cable(
                fix["lat"], fix["lon"], fix["cog_deg"], fix["sog_kn"] * 1.2, cable["path"]
            )
            if earliest_s is None:
                continue
            gap_start = before["t"] + EXPECTED_FIX_INTERVAL_S
            radar = next((item for item in detections
                          if gap_start <= item["t"] < after["t"] and item["t"] <= fix["t"]), None)
            drop_percent = round(speed_drop * 100)
            reasons = [
                f"Observed speed fell from {before['sog_kn']:.1f} kn at T+{before['t']//60} min "
                f"to {fix['sog_kn']:.1f} kn at T+{fix['t']//60} min ({drop_percent}%); cause unknown.",
                f"Observed heading differs by {turn_deg:.0f}° from the pre-gap fix; cause unknown.",
                f"AIS reception gap lasted {silent_s//60} min from T+{gap_start//60} to T+{after['t']//60} min; intent unknown.",
                f"Constant-course projection reaches an illustrative cable in {round(expected_s/60)} min. "
                "The 250 m anchor-reach cutoff is an assumption.",
            ]
            return {
                "id": alert_id,
                "t": fix["t"],
                "mmsi": vessel["mmsi"],
                "vessel_name": vessel["name"],
                "state": "ALERT",
                "score": 1.0,
                "score_basis": "4 of 4 rule cues met: slowdown, course change, prior AIS gap, projected crossing of an assumed anchor-reachable cable section. This is not a probability.",
                "reasons": reasons,
                "segment_id": cable["id"],
                "distance_km": round(nm_between(fix["lat"], fix["lon"], *crossing) * 1.852, 1),
                "eta_expected_s": expected_s,
                "eta_earliest_s": earliest_s,
                "eta_method": "Constant speed and course at the alert fix; earliest uses 20% higher speed. Neither is a calibrated confidence bound.",
                "options": response_options(assets, fix, crossing, earliest_s),
                "evidence_url": f"evidence/contacts/contact-{int(alert_id[1:]):04d}.html",
                "observations": {
                    "baseline_fix_t": before["t"],
                    "alert_fix_t": fix["t"],
                    "gap_start_t": gap_start,
                    "gap_end_t": after["t"],
                    "speed_drop_percent": drop_percent,
                    "course_change_deg": round(turn_deg, 1),
                    "radar_contact_t": radar["t"] if radar else None,
                    "radar_association": "unconfirmed" if radar and radar.get("matched_mmsi") is None else "source-reported" if radar else "unavailable",
                    "anchor_reach_label": "assumption",
                },
            }
    return None


def build_alerts(scenario):
    validate_scenario(scenario)
    alerts = []
    for vessel in scenario["vessels"]:
        alert = detect_vessel(vessel, scenario["cables"], scenario["assets"],
                              scenario["detections"], f"A{len(alerts) + 1}")
        if alert:
            alerts.append(alert)
    result = {"generated_by": "argus.brain (rules v1)", "scenario": scenario.get("name", "Scenario"),
              "alerts": sorted(alerts, key=lambda alert: alert["t"])}
    validate_alerts(result, scenario)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=ROOT / "demo/scenario.json")
    parser.add_argument("--output", type=Path, default=ROOT / "demo/alerts.json")
    args = parser.parse_args()
    if args.scenario.resolve() == args.output.resolve():
        parser.error("output must not overwrite the scenario")
    try:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        result = build_alerts(scenario)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Brain alert generation failed: {error}\n")
    print(f"Brain alerts -> {args.output} ({len(result['alerts'])} review alert(s))")


if __name__ == "__main__":
    main()
