"""Keep one updatable incident card per vessel across repeated assessments.

``argus.assemble`` recomputes every vessel's level at every live or replay
step. This module turns that stream into stable incidents a human can work on:

* An incident opens when a vessel's level reaches ``OPEN_LEVEL`` (Medium).
  Low is an observation, not an incident.
* A vessel has at most one open incident, ``INC-<mmsi>-<n>``. Later steps update
  it; they never create a duplicate.
* Brain sets the status "New" once, at creation. Only a human changes it, here
  through ``set_status``.
* A level rise after Reviewed, Acknowledged or Escalated sets
  ``needs_review_again``; the status stays as the analyst left it.
* ``QUIET_CLOSE_S`` below Medium sets ``suggest_close``. Nothing is closed or
  deleted automatically, so a level that hovers at the boundary does not flicker.
* Rejected closes the incident. A new one, with ``reopened_from``, opens only
  after the vessel has dropped below Medium and then reached it again, so a
  rejection does not bounce straight back while the same activity continues.

State is plain JSON-ready data. The output is a separate review file;
``demo/alerts.json`` is not touched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from argus.assemble import build_assessments
from argus.levels import RANK

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/brain/incidents.json"

# Same lists as the captain's alert panel (desktop_alerts.py). Copied, not
# imported, because that module loads tkinter.
STATUSES = ("New", "Reviewed", "Acknowledged", "Escalated", "Rejected")
REASONS = ("False alarm", "Known benign activity", "Authorised operation", "Duplicate alert")
REVIEWED = frozenset({"Reviewed", "Acknowledged", "Escalated"})

# Assumptions, not doctrine: Medium is where a human should look; 30 min quiet
# is long enough that a drop is not just one noisy step.
OPEN_LEVEL = "medium"
QUIET_CLOSE_S = 30 * 60
MAX_REASONS = 6


def new_state() -> dict:
    """Empty incident state. Keys of ``open``, ``counters``, ``last_level`` and ``hold`` are MMSIs as strings."""
    return {"now": None, "open": {}, "closed": [], "counters": {}, "last_level": {}, "hold": {}}


def _vessels(assessments) -> list[dict]:
    return assessments["vessels"] if isinstance(assessments, dict) else assessments


def _reasons(assessment: dict) -> list[str]:
    return [f"{factor['code']}: {factor['text']}" for factor in assessment.get("factors", [])][:MAX_REASONS]


def _open(state: dict, key: str, item: dict, level: str, previous: str, now: int, reopened_from) -> dict:
    n = state["counters"].get(key, 0) + 1
    state["counters"][key] = n
    assessment = item["assessment"]
    incident = {
        "id": f"INC-{item['mmsi']}-{n}", "mmsi": item["mmsi"], "name": item.get("name"),
        "label": item.get("label", "simulated"), "opened_t": now, "updated_t": now,
        "level": level, "peak_level": level, "cable_id": item.get("cable_id"), "reasons": _reasons(assessment),
        "history": [{"t": now, "from": previous, "to": level, "basis": assessment.get("basis")}],
        "status": "New", "status_reason": None, "status_log": [], "reviewed_level": None,
        "needs_review_again": False, "quiet_since_t": None, "suggest_close": False,
        "reopened_from": reopened_from, "closed_t": None,
    }
    state["open"][key] = incident
    return incident


def _update(incident: dict, item: dict, level: str, previous: str, now: int) -> None:
    assessment = item["assessment"]
    incident["updated_t"] = now
    if level != previous:
        incident["history"].append({"t": now, "from": previous, "to": level, "basis": assessment.get("basis")})
    incident["level"] = level
    if RANK[level] > RANK[incident["peak_level"]]:
        incident["peak_level"] = level
    if RANK[level] >= RANK[OPEN_LEVEL]:
        # Keep the cable and reasons of the last active step while the vessel is quiet.
        incident["cable_id"] = item.get("cable_id") or incident["cable_id"]
        incident["reasons"] = _reasons(assessment)
        incident["quiet_since_t"] = None
        incident["suggest_close"] = False
    else:
        if incident["quiet_since_t"] is None:
            incident["quiet_since_t"] = now
        incident["suggest_close"] = now - incident["quiet_since_t"] >= QUIET_CLOSE_S
    reviewed = incident["reviewed_level"]
    if incident["status"] in REVIEWED and reviewed is not None and RANK[level] > RANK[reviewed]:
        incident["needs_review_again"] = True


def update_incidents(state: dict | None, assessments, now: int) -> dict:
    """Fold one step of ``build_assessments`` output (or its ``vessels`` list) into ``state`` and return it.

    Work is one dict lookup per assessed vessel. Vessels missing from this step are left as they were.
    """
    state = new_state() if state is None else state
    if state["now"] is not None and now < state["now"]:
        raise ValueError(f"time went backwards ({now} < {state['now']}); start a new state to rewind a replay")
    state["now"] = now
    open_rank = RANK[OPEN_LEVEL]
    for item in _vessels(assessments):
        key = str(item["mmsi"])
        level = item["assessment"]["level"]
        previous = state["last_level"].get(key, "none")
        if level == "none":
            state["last_level"].pop(key, None)
        else:
            state["last_level"][key] = level
        incident = state["open"].get(key)
        if incident is not None:
            _update(incident, item, level, previous, now)
        elif key in state["hold"]:
            if RANK[level] < open_rank:
                del state["hold"][key]
        elif RANK[level] >= open_rank:
            last = state["counters"].get(key)
            _open(state, key, item, level, previous, now, f"INC-{item['mmsi']}-{last}" if last else None)
    return state


def _find_open(state: dict, incident_id: str) -> dict:
    mmsi = incident_id.rsplit("-", 1)[0].removeprefix("INC-")
    incident = state["open"].get(mmsi)
    if incident is None or incident["id"] != incident_id:
        raise KeyError(f"no open incident {incident_id}")
    return incident


def set_status(state: dict, incident_id: str, status: str, reason: str | None = None) -> dict:
    """Record an analyst decision. Rejected needs a reason from ``REASONS`` and closes the incident."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if status == "Rejected" and reason not in REASONS:
        raise ValueError(f"Rejected needs a reason from {REASONS}")
    if status != "Rejected" and reason is not None:
        raise ValueError("only Rejected takes a reason")
    incident = _find_open(state, incident_id)
    now = state["now"]
    incident["status"], incident["status_reason"] = status, reason
    incident["status_log"].append({"t": now, "status": status, "reason": reason})
    incident["reviewed_level"] = incident["level"] if status in REVIEWED else None
    incident["needs_review_again"] = False
    if status == "Rejected":
        key = str(incident["mmsi"])
        incident["closed_t"] = now
        state["closed"].append(state["open"].pop(key))
        if RANK[incident["level"]] >= RANK[OPEN_LEVEL]:
            state["hold"][key] = incident["id"]
    return incident


def all_incidents(state: dict) -> list[dict]:
    return sorted([*state["open"].values(), *state["closed"]], key=lambda inc: (inc["opened_t"], inc["id"]))


def run_scenario(scenario: dict, step: int = 60, state: dict | None = None) -> dict:
    """Step through a scenario from its first to its last fix and return the incident state."""
    if step <= 0:
        raise ValueError("step must be positive")
    times = [fix["t"] for vessel in scenario["vessels"] for fix in vessel["track"]]
    state = new_state() if state is None else state
    if not times:
        return state
    start, end = min(times), max(times)
    steps = list(range(start, end + 1, step))
    if steps[-1] != end:
        steps.append(end)
    for now in steps:
        update_incidents(state, build_assessments(scenario, now), now)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=ROOT / "demo/scenario.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--step", type=int, default=60, help="replay step in seconds")
    args = parser.parse_args()
    protected = {args.scenario.resolve(), (ROOT / "demo/alerts.json").resolve()}
    if args.output.resolve() in protected:
        parser.error("output must not overwrite the scenario or demo/alerts.json")
    try:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        state = run_scenario(scenario, args.step)
        incidents = all_incidents(state)
        result = {"generated_by": "argus.incidents", "scenario": scenario.get("name", "Scenario"),
                  "step_s": args.step, "now": state["now"],
                  "rules": {"open_level": OPEN_LEVEL, "quiet_close_s": QUIET_CLOSE_S},
                  "note": "Brain only opens and updates incidents; status is set by a human.",
                  "incidents": incidents}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Brain incidents failed: {error}\n")
    summary = ", ".join(f"{inc['id']} {inc['level']} (peak {inc['peak_level']})" for inc in incidents)
    print(f"Brain incidents -> {args.output} ({summary or 'no incidents'})")


if __name__ == "__main__":
    main()
