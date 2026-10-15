"""Why a board contact has its level, arranged for the panel's review window.

Everything here is read from a scored board item (``argus.brain_board``): the
``argus.levels`` factors by group, the rules that capped or raised the level,
the detectors' findings, the small-vessel rule, the threatened line and any AIS
data Brain ignored or detector that failed on the vessel. Each
part carries a data label (simulated, exercise, real, illustrative, assumption)
so a reviewer can see what is invented, what is public data and what is our
own assumption. No tkinter here.
"""

from __future__ import annotations

from argus.alert_board import LINES
from argus.assemble import describe_data_quality
from argus.levels import BEHAVIOUR_CAP, CONTEXT_CAP, IDENTITY_CAP

GROUPS = (("B", "behaviour", "Behaviour", BEHAVIOUR_CAP), ("I", "identity", "Identity and data", IDENTITY_CAP),
          ("P", "proximity", "Proximity and time", None), ("A", "asset", "Line at risk", None),
          ("C", "context", "Context", CONTEXT_CAP))
DETECTORS = {
    "alert_board_simulated": "Board observations",
    "legacy_cable_v1": "Cable approach rule v1",
    "ais_spoofing": "AIS spoofing check",
    "cable_risk": "Cable risk from the track",
}
DATA_LABELS = {"simulated": "SIMULATED", "fictional": "EXERCISE", "real": "REAL"}
# Notes the small-vessel rule adds (argus.assemble.apply_relevance); shown in their own part.
SMALL_VESSEL_PREFIXES = ("Capped at Low: small vessel", "Small-vessel cap not applied")


def _line_name(line_id: str | None, item: dict) -> str:
    if line_id == item.get("line_id") or line_id is None:
        return item.get("line_name") or str(line_id)
    return LINES[line_id][0] if line_id in LINES else line_id


def _where(values: dict) -> str:
    if values.get("in_corridor"):
        return "inside its 1 nm corridor"
    eta = values.get("eta_min")
    if eta is not None:
        minutes = round(eta)
        return f"reached in {minutes} min" if minutes < 120 else f"reached in {minutes // 60} h {minutes % 60:02d} min"
    if values.get("distance_nm") is not None:
        return f"{values['distance_nm']:.1f} nm away"
    return "named by a detector"


def groups(item: dict) -> list[dict]:
    """The five ``argus.levels`` groups with their points, cap and factors (zero-point factors kept)."""
    assessment = item["assessment"]
    found = []
    for key, name, title, cap in GROUPS:
        factors = [factor for factor in assessment["factors"] if factor["group"] == name]
        found.append({"key": key, "title": title, "points": assessment["groups"][key], "cap": cap,
                      "factors": factors})
    return found


def rules(item: dict) -> list[str]:
    """Level rules that capped or raised the band (from ``argus.levels``), without detector or small-vessel notes."""
    detector_notes = set(item.get("detector_notes", ()))
    return [note for note in item["assessment"]["notes"]
            if note not in detector_notes and not note.startswith(SMALL_VESSEL_PREFIXES)]


def findings(item: dict) -> list[dict]:
    """One entry per detector: its readable name, data label and reasons (repeated reasons merged)."""
    merged: dict[str, dict] = {}
    for finding in item.get("findings", ()):
        entry = merged.setdefault(finding["detector"], {
            "detector": finding["detector"], "title": DETECTORS.get(finding["detector"], finding["detector"]),
            "label": DATA_LABELS.get(finding.get("label"), str(finding.get("label") or "").upper()), "reasons": []})
        for reason in finding["reasons"]:
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
    return list(merged.values())


def small_vessel(item: dict) -> dict | None:
    """The small-vessel rule's outcome, or None when the vessel is not small."""
    relevance = item.get("relevance") or {}
    if not relevance.get("small"):
        return None
    if relevance.get("exception"):
        outcome = f"Cap not applied: {relevance['exception']}."
    else:
        outcome = "Capped at Low: its anchor and gear are unlikely to damage the line."
    return {"capped": not relevance.get("exception"), "reason": relevance["reason"], "outcome": outcome}


def threatened_line(item: dict) -> dict:
    """The line the level is scored for, why it was chosen, and the other lines detectors named."""
    chosen = item.get("cable_id") or item.get("line_id")
    others = []
    for finding in item.get("findings", ()):
        line_id = finding.get("cable_id")
        if line_id and line_id != chosen and line_id not in [other["id"] for other in others]:
            others.append({"id": line_id, "name": _line_name(line_id, item), "where": _where(finding)})
    return {"id": chosen, "name": _line_name(chosen, item), "where": _where(item["observations"]),
            "others": others}


# Where a contact's observations come from: (short card tag, review-window tag, what it means).
SOURCES = {
    "story": ("BRAIN", "BRAIN · FROM TRACK",
              "Brain · from track: the registered detectors scored this fictional AIS track at the replay time"),
    "exercise": ("EXERCISE", "EXERCISE · FROM TRACK",
                 "Exercise · from track: the registered detectors scored the exercise vessel's AIS track"),
    "sim": ("SIM", "SIM · HAND-WRITTEN",
            "SIM · hand-written observations: the board's observations for this contact were written by hand"),
}


def source(item: dict) -> dict:
    """Where the contact's observations come from, for the card, the map label and the review window."""
    key = "story" if item.get("story") else "exercise" if item.get("exercise") else "sim"
    tag, long_tag, text = SOURCES[key]
    return {"key": key, "tag": tag, "long_tag": long_tag, "text": text,
            "short": "from track" if key != "sim" else "hand-written"}


def labels(item: dict) -> list[tuple[str, str]]:
    """Data labels for the review window: (tag, what it covers)."""
    found = [("SOURCE", source(item)["text"])]
    if item.get("story"):
        found.append(("SIMULATED", "Vessel and AIS track are fictional; no observation is written by hand"))
        found.append(("ILLUSTRATIVE", "The cable route is drawn for illustration"))
        found.append(("ASSUMPTION", "Route depth unknown: an anchor is assumed to reach the seabed along the whole "
                                    "route; AIS ship type and class are assumed for this fictional contact"))
    elif item.get("exercise"):
        found.append(("EXERCISE", "Fictional exercise vessel and track from the demo files"))
        found.append(("ILLUSTRATIVE", "The cable is fictional"))
    else:
        found.append(("SIMULATED", "Vessel, track and observations are fictional"))
        found.append(("ILLUSTRATIVE", "The cable route is drawn for illustration"))
        found.append(("ASSUMPTION", "AIS ship type, class and radar length are assumed for this fictional contact"))
    if small_vessel(item):
        found.append(("ASSUMPTION", "Small-vessel limits (class B under 30 m, small types under 50 m) are our "
                                    "assumption, not regulation"))
    if any("Natural Earth" in reason for finding in item.get("findings", ()) for reason in finding["reasons"]):
        found.append(("REAL", "Coastline for the on-land check: Natural Earth 1:50m public data"))
    found.append(("RULE OUTCOME", "The level is a rule outcome for human review, not a probability of hostile intent"))
    return found


def data_issues(item: dict) -> list[str]:
    """Review lines: the fixes Brain ignored when cleaning the track, then each detector that failed on it."""
    found = [describe_data_quality(item.get("data_quality"))]
    found += [f"Detector {error['detector']} failed on this vessel — not scored by it ({error['error']})"
              for error in item.get("detector_errors") or ()]
    return [line for line in found if line]


def explain(item: dict) -> dict:
    """Everything the review window shows under "Why this level"."""
    return {"basis": item["assessment"]["basis"], "groups": groups(item), "rules": rules(item),
            "findings": findings(item), "small_vessel": small_vessel(item), "line": threatened_line(item),
            "labels": labels(item), "source": source(item), "data_issues": data_issues(item)}
