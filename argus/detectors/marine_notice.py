"""Is the vessel doing work that a Marine Notice declares? (declared-work whitelist)

The Irish Department of Transport publishes a Marine Notice for survey, repair
and cable or pipeline work at sea. Each notice names its vessels and call signs
and gives the dates and the work area. A survey ship running slow lines along a
cable looks like a threat to every behaviour rule, so Brain checks the notices
first. ``argus/marine_notices.json`` holds ten real 2026 notices for EWIC,
Greenlink, the Celtic Interconnector and the IC1, IC2 and Corrib gas pipelines.

One finding per notice the vessel touches:

* **named, inside the work area, within the dates**: ``notice_named``.
  ``argus.assemble`` then sets the ``authorised`` observation, which
  ``argus.levels`` caps at Low, unless identity or damage evidence says
  otherwise;
* **named but outside the area or the dates**: a reason only. The notice does
  not cover this position or day;
* **inside a work area but not named**: a reason only. A notice explains only
  the vessels it names.

Identity is the AIS call sign (Message 5), or the exact name when AIS sends no
call sign. Anyone can type a call sign into AIS, so a match is a reason for
review, not proof. A replay without a calendar date skips the date check and
says so. Work-area widths and date margins are team assumptions
(``assumptions`` in the data file).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import re

from argus.countdown import nm_between
from argus.detectors.ais_spoofing import clean_track
from argus.prediction import distance_to_path_nm

ROOT = Path(__file__).resolve().parents[2]
NOTICES_FILE = ROOT / "argus/marine_notices.json"

DETECTOR = "marine_notice"

# Notices say "subject to weather" (assumption): a notice counts from a day before its start to a week after its end.
EARLY_DAYS, LATE_DAYS = 1, 7
EPOCH_MIN_S = 1_000_000_000  # a fix time above this is Unix seconds; replay times are seconds from the start
NAME_PREFIXES = re.compile(r"^(MV|M V|MS|RV|R V|FV|F V|SV|LE|L E)\s+")
LABELS = {"real": "real", "fictional": "exercise"}


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, ...]:
    with open(path, encoding="utf-8") as handle:
        return tuple(json.load(handle)["notices"])


def load_notices(path: Path | str = NOTICES_FILE) -> list[dict]:
    """The real Marine Notices bundled with Argus."""
    return list(_load(str(path)))


@lru_cache(maxsize=4)
def source(path: Path | str = NOTICES_FILE) -> dict:
    """Where the bundled notices come from: source, collection URL, retrieval date, assumptions and count."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: data.get(key) for key in ("source", "collection_url", "retrieved", "assumptions")} | {
        "count": len(data["notices"])}


def active_on(day: date, notices: list[dict] | None = None) -> list[dict]:
    """The notices whose dates (with the weather margins) include ``day``."""
    found = []
    for notice in load_notices() if notices is None else notices:
        start, end = window(notice)
        if (start is None or day >= start) and (end is None or day <= end):
            found.append(notice)
    return found


def call_sign_key(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def name_key(value) -> str:
    text = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    return NAME_PREFIXES.sub("", text)


def named(notice: dict, vessel: dict) -> tuple[dict, str] | None:
    """The notice's entry for this vessel and how it matched ("call sign" or "name"), or None."""
    sign, name = call_sign_key(vessel.get("call_sign")), name_key(vessel.get("name"))
    for entry in notice["vessels"]:
        if sign:
            if call_sign_key(entry["call_sign"]) == sign:
                return entry, "call sign"
        elif name and name_key(entry["name"]) == name:
            return entry, "name"
    return None


def _inside_polygon(lat: float, lon: float, points: list) -> bool:
    inside = False
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:] + points[:1]):
        if (lat1 > lat) != (lat2 > lat) and lon < lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1):
            inside = not inside
    return inside


def area_distance_nm(lat: float, lon: float, area: dict) -> float:
    """How far outside the area's edge the point lies (0 or less: inside)."""
    points = area["points"]
    if area["kind"] == "point":
        return nm_between(lat, lon, *points[0]) - area["buffer_nm"]
    if area["kind"] == "polygon":
        if _inside_polygon(lat, lon, points):
            return -area["buffer_nm"]
        edge, _ = distance_to_path_nm(lat, lon, points + points[:1])
        return edge - area["buffer_nm"]
    distance, _ = distance_to_path_nm(lat, lon, points)
    return distance - area["buffer_nm"]


def notice_distance_nm(lat: float, lon: float, notice: dict) -> float:
    return min(area_distance_nm(lat, lon, area) for area in notice["areas"])


def fix_day(fix: dict, context: dict) -> date | None:
    """The calendar day of the fix: ``context["date"]`` (ISO) when given, else a Unix-time fix, else None."""
    if context.get("date"):
        return date.fromisoformat(str(context["date"])[:10])
    t = fix.get("t")
    if isinstance(t, (int, float)) and not isinstance(t, bool) and t >= EPOCH_MIN_S:
        return datetime.fromtimestamp(t, timezone.utc).date()
    return None


def window(notice: dict, entry: dict | None = None) -> tuple[date | None, date | None]:
    """First and last day the notice counts for this vessel, with the weather margins."""
    start = (entry or {}).get("valid_from") or notice.get("valid_from")
    end = notice.get("valid_to")
    return (date.fromisoformat(start) - timedelta(days=EARLY_DAYS) if start else None,
            date.fromisoformat(end) + timedelta(days=LATE_DAYS) if end else None)


def short_day(value: str | None) -> str:
    """"12 Oct 2026" (no leading zero on any platform)."""
    if not value:
        return "?"
    day = date.fromisoformat(value)
    return f"{day.day} {day:%b %Y}"


def dates_text(notice: dict, entry: dict | None = None) -> str:
    start = (entry or {}).get("valid_from") or notice.get("valid_from")
    return f"{short_day(start)} – {short_day(notice.get('valid_to'))}"


def vessel_text(entry: dict) -> str:
    return f"{entry['name'].title()} ({entry['call_sign']})"


def title(notice: dict) -> str:
    kind = "Exercise notice" if notice.get("label") == "fictional" else "Marine Notice"
    return f"{kind} {notice['number']}"


def _finding(vessel: dict, notice: dict, last: dict, match: str, obs: dict, reasons: list[str]) -> dict:
    return {"detector": DETECTOR, "mmsi": vessel.get("mmsi"), "t": last.get("t"),
            "position": [last["lat"], last["lon"]], "strength": 0.0, "reasons": reasons,
            "related": {"notice": notice["number"], "notice_title": notice["title"], "notice_url": notice.get("url"),
                        "notice_label": notice.get("label", "real"), "match": match},
            "label": notice.get("label", "real"), "obs": obs}


def assess_notice(vessel: dict, notice: dict, last: dict, day: date | None) -> dict | None:
    """The finding for one notice, or None when the notice neither names the vessel nor covers its position."""
    distance = notice_distance_nm(last["lat"], last["lon"], notice)
    inside = distance <= 0
    found = named(notice, vessel)
    head = f"{title(notice)} ({LABELS.get(notice.get('label'), 'real')}): {notice['title']}"
    if found:
        entry, how = found
        start, end = window(notice, entry)
        in_dates = day is None or ((start is None or day >= start) and (end is None or day <= end))
        who = f"Names {vessel_text(entry)}, matched by {how}" + (f"; {entry['role']}" if entry.get("role") else "")
        if inside and in_dates:
            if not notice.get("valid_from"):
                when = notice.get("end_note") or "The notice gives no work dates"
            elif day:
                when = f"Work dates {dates_text(notice, entry)} cover {short_day(day.isoformat())}"
            else:
                when = f"Replay has no calendar date: work dates {dates_text(notice, entry)} not checked"
            return _finding(vessel, notice, last, "named", {"notice_named": True},
                            [head, who, f"Inside the notified work area. {notice['area_note']}", when])
        why = (f"it is {distance:.1f} nm outside the work area" if not inside
               else f"{short_day(day.isoformat())} is outside the work dates ({dates_text(notice, entry)})")
        return _finding(vessel, notice, last, "named_elsewhere", {},
                        [head, f"{who}, but {why}: the notice does not cover it here"])
    if not inside:
        return None
    start, end = window(notice)
    if day is not None and ((start and day < start) or (end and day > end)):
        return None
    names = ", ".join(vessel_text(entry) for entry in notice["vessels"])
    reasons = [head, f"Inside its work area, but the notice names {names}, not this vessel. "
                     "A notice explains only the vessels it names"]
    if day is None and notice.get("valid_from"):
        reasons.append(f"Replay has no calendar date: work dates {dates_text(notice)} not checked")
    return _finding(vessel, notice, last, "unnamed", {}, reasons)


def marine_notice(vessel: dict, context: dict) -> list[dict]:
    """Findings for the notices that name this vessel or cover its last position."""
    fixes = clean_track(vessel.get("track") or [], context.get("now"))
    if not fixes:
        return []
    last = fixes[-1]
    day = fix_day(last, context)
    notices = list(context.get("notices") or []) + ([] if context.get("real_notices") is False else load_notices())
    found = [finding for notice in notices if (finding := assess_notice(vessel, notice, last, day))]
    order = {"named": 0, "named_elsewhere": 1, "unnamed": 2}
    return sorted(found, key=lambda finding: order[finding["related"]["match"]])


detect = marine_notice  # the package convention; the function name labels the assessments file
