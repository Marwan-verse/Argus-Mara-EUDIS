"""Validated analyst reports, independent of detector scores and the replay clock."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import re
import unicodedata
from uuid import UUID, uuid4

CATEGORIES = ("Suspicious activity", "AIS / identity concern", "Unsafe navigation",
              "Infrastructure concern", "Other")
LABELS = {"real", "reconstructed", "simulated", "fictional", "assumption"}


def _text(value, maximum, title):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"{title} requires 1–{maximum} characters")
    if any(c not in "\n\t‌‍" and unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
        raise ValueError(f"{title} contains invisible or control characters")


def validate_report(report):
    """Validate on both endpoints; attribution comes from the authenticated sender."""
    if not isinstance(report, dict) or set(report) != {"id", "vessel", "category", "reason", "created_utc"}:
        raise ValueError("Invalid vessel report")
    try:
        if str(UUID(report["id"])) != report["id"]:
            raise ValueError
        stamp = datetime.fromisoformat(report["created_utc"])
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid report ID or UTC timestamp") from None
    if not isinstance(report["category"], str) or report["category"] not in CATEGORIES:
        raise ValueError("Choose a report category")
    _text(report["reason"], 2000, "Reason")
    vessel = report["vessel"]
    if not isinstance(vessel, dict) or set(vessel) != {"id", "name", "label", "lat", "lon"}:
        raise ValueError("Invalid reported vessel")
    if not isinstance(vessel["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", vessel["id"]):
        raise ValueError("Invalid vessel identity")
    _text(vessel["name"], 120, "Vessel name")
    if not isinstance(vessel["label"], str) or vessel["label"] not in LABELS:
        raise ValueError("Invalid vessel provenance")
    for key, limit in (("lat", 90), ("lon", 180)):
        value = vessel[key]
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError("Invalid report coordinates")
    return report


def make_report(vessel, category, reason):
    _text(reason, 2000, "Reason")
    report = {"id": str(uuid4()), "vessel": deepcopy(vessel), "category": category,
              "reason": reason.strip(), "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return validate_report(report)


class ReportStore:
    """In-memory incident inbox. Multiple analysts' reports group under one vessel."""
    def __init__(self):
        self.entries = []

    def add(self, report, sender, shared=False):
        validate_report(report)
        if any(entry["report"]["id"] == report["id"] and entry["sender"] == sender for entry in self.entries):
            return False
        self.entries.append({"report": deepcopy(report), "sender": sender, "shared": shared})
        self.entries = self.entries[-256:]
        return True

    def grouped(self):
        groups = {}
        for entry in self.entries:
            vessel = entry["report"]["vessel"]
            # A real and a fictional contact never merge merely because IDs match.
            key = (vessel["label"], vessel["id"])
            entries = groups.pop(key, [])
            entries.append(entry)
            groups[key] = entries
        return list(reversed(list(groups.values())))
