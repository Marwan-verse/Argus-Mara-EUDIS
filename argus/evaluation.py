"""Reproducible exercise comparison, with episode counts and explicit label scope."""
from copy import deepcopy
from hashlib import sha256
import json
from statistics import mean

from argus.assemble import assess_vessel, context_from_scenario
from argus.brain_board import STORY_ITEMS, STORY_LINES, SHIP_TYPES
from argus.prediction import distance_to_path_nm

VERSION = "exercise-evaluation-v1"


def exercise_cases():
    """Story-authored review expectations; not real incident ground truth or a holdout set."""
    expectations = {"SIM-50": (True, "Fictional sustained slowdown toward a line"),
                    "SIM-51": (True, "Fictional holding and anchoring near a line"),
                    "SIM-52": (False, "Fictional routine anchorage outside the corridors"),
                    "SIM-53": (False, "Fictional steady ferry transit"),
                    "SIM-55": (True, "Fictional route deviation and slowdown near a line")}
    cases = []
    for row, ais_class, make_track in STORY_ITEMS:
        expected, reason = expectations[row[0]]
        vessel = {"mmsi": row[0], "name": row[1], "type": row[2], "ship_type": SHIP_TYPES.get(row[2]),
                  "ais_class": ais_class, "ais_length_m": row[3], "label": "fictional", "track": make_track()}
        if row[0] == "SIM-55":
            vessel["destination"] = "GBFIS"
        scenario = {"vessels": [vessel], "cables": deepcopy(STORY_LINES), "detections": [], "assets": []}
        cases.append({"id": row[0], "scenario": scenario, "vessel": vessel,
                      "expected_review": expected, "label_basis": reason})
    return cases


def _episodes(times, step=60):
    return sum(i == 0 or t - times[i-1] > step for i, t in enumerate(times))


def summarize(rows, prefix):
    labelled = [r for r in rows if isinstance(r.get("expected_review"), bool)]
    tp = sum(r["expected_review"] and r[f"{prefix}_first_s"] is not None for r in labelled)
    fp = sum(not r["expected_review"] and r[f"{prefix}_first_s"] is not None for r in labelled)
    fn = sum(r["expected_review"] and r[f"{prefix}_first_s"] is None for r in labelled)
    tn = len(labelled) - tp - fp - fn
    leads = [r[f"{prefix}_lead_s"] for r in rows if r[f"{prefix}_lead_s"] is not None]
    hours = sum(r["observed_duration_s"] for r in rows) / 3600
    episodes = sum(r[f"{prefix}_episodes"] for r in rows)
    return {"cases": len(rows), "labelled_cases": len(labelled), "alert_episodes": episodes,
            "vessel_hours": hours, "episodes_per_vessel_hour": episodes / hours if hours else None,
            "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "mean_lead_s": mean(leads) if leads else None, "lead_cases": len(leads)}


def evaluate_cases(cases):
    """Evaluate identical observed fixes; labels are used only after detection.

    Brain alerts at Medium or above; baseline at <=1 nm from the same physical
    line paths. Warning lead is to first observed entry into that corridor.
    No history is interpolated and per-case counts avoid repeated-alert inflation.
    """
    rows = []
    for case in cases:
        vessel, scenario = case["vessel"], case["scenario"]
        track = vessel["track"]
        brain, baseline = [], []
        first_entry = None
        for fix in track:
            now = fix["t"]
            context = context_from_scenario(scenario, now)
            if assess_vessel(vessel, context)["assessment"]["rank"] >= 2:
                brain.append(now)
            proximity = any(distance_to_path_nm(fix["lat"], fix["lon"], c["path"])[0] <= 1
                            for c in scenario["cables"] if len(c.get("path", [])) >= 2)
            if proximity:
                baseline.append(now)
                if first_entry is None:
                    first_entry = now
        row = {"id": case["id"], "name": vessel.get("name", case["id"]), "label": vessel["label"],
               "expected_review": case.get("expected_review"), "label_basis": case.get("label_basis", "Unlabelled"),
               "first_corridor_entry_s": first_entry,
               "observed_duration_s": sum(min(60, b["t"] - a["t"]) for a, b in zip(track, track[1:]))}
        for name, alerts in (("brain", brain), ("baseline", baseline)):
            first = alerts[0] if alerts else None
            row.update({f"{name}_first_s": first, f"{name}_episodes": _episodes(alerts),
                        f"{name}_lead_s": None if first is None or first_entry is None else first_entry - first})
        rows.append(row)
    digest = sha256(json.dumps(cases, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"version": VERSION, "dataset_sha256": digest, "rows": rows,
            "brain": summarize(rows, "brain"), "baseline": summarize(rows, "baseline"),
            "scope": "Authored fictional development scenarios; not an independent test or operational accuracy estimate.",
            "method": "Brain: Medium+; baseline: within 1 nm. One-minute observed fixes. Lead to first observed corridor entry; negative means late. Labels describe expected review, never hostile intent."}


if __name__ == "__main__":
    print(json.dumps(evaluate_cases(exercise_cases()), indent=2))
