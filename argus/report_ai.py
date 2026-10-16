"""Evidence pack, template draft and code checks for the analyst's vessel report.

Code builds the facts; a language model may only write them up. The pack is
read from a Brain board item (``argus.explain``) with the Incidents panel's
incident, status and who can reach it, or, for a live AIS vessel without a
Brain item, from its last AIS record. Every fact has an ID (E1, E2, ...) and a
data label.

The code check compares a report text with the pack: replay or UTC times,
positions, numbers with units, vessel names, IDs and the level must come from
the pack; intent words (hostile, sabotage, ...) need evidence the system never
holds; a simulated contact must be called simulated and a real one must not.
Brain's level is authoritative: nothing here assigns or changes it, and
nothing triggers an operational action. No tkinter here.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from argus.explain import explain
from argus.vessel_reports import CATEGORIES

PACK_VERSION = 1
REASON_LIMIT = 2000
TARGET_LENGTH = 1500
TEMPLATE_LABEL = "Template draft from system data · reviewed by analyst"
AI_LABEL = "AI-assisted draft · reviewed by analyst"
DATA_TAGS = {"simulated": "SIMULATED", "fictional": "EXERCISE", "real": "REAL"}
LEVELS = ("none", "low", "medium", "high", "critical")
LEVEL_NAMES = {"none": "None", "low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}


# ----- evidence pack -------------------------------------------------------------------

def position_text(lat: float, lon: float) -> str:
    return f"{abs(lat):.4f} {'N' if lat >= 0 else 'S'}, {abs(lon):.4f} {'E' if lon >= 0 else 'W'}"


def _motion_text(sog, cog) -> str:
    speed = "SOG not available" if sog is None else f"SOG {sog:.1f} kn"
    course = "COG not available" if cog is None else f"COG {cog:03.0f}°"
    return f"{speed}, {course}"


class _Facts:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, topic: str, label: str, text: str) -> str:
        identifier = f"E{len(self.items) + 1}"
        self.items.append({"id": identifier, "topic": topic, "label": label, "text": text.strip()})
        return identifier


def build_pack(vessel: dict, item: dict | None = None, context: dict | None = None,
               live: dict | None = None) -> dict:
    """The evidence a report may rest on. ``vessel`` is the report's snapshot (id, name, label, lat, lon)."""
    if item is not None:
        return _board_pack(vessel, item, context or {})
    return _live_pack(vessel, live)


def _board_pack(vessel: dict, item: dict, context: dict) -> dict:
    why = explain(item)
    assessment = item["assessment"]
    tag = DATA_TAGS.get(item.get("label"), str(item.get("label") or "").upper())
    facts = _Facts()
    kind = "Exercise contact" if item.get("exercise") else "Simulated contact"
    ids = item["id"] if vessel["id"] == item["id"] else f"{item['id']}, MMSI {vessel['id']}"
    details = [item["vessel_type"]] + ([f"{item['length_m']:.0f} m"] if item.get("length_m") else [])
    facts.add("identity", tag, f"{kind} {item['name']} ({ids}), {', '.join(details)}")
    facts.add("source", "SOURCE", why["source"]["text"])
    where = f"Position {position_text(vessel['lat'], vessel['lon'])}"
    if context.get("replay_time"):
        where += f" at replay time {context['replay_time']}"
    facts.add("position", tag, where)
    facts.add("motion", tag, _motion_text(item.get("sog_kn"), item.get("cog_deg")))
    if item.get("destination"):
        facts.add("destination", tag, f"Declared AIS destination {item['destination']}")
    if context.get("raised_min") is not None:
        facts.add("raised", tag, f"Contact raised {context['raised_min']} min before the replay time")
    facts.add("summary", tag, f"Board summary: {item['title']}")
    incident = context.get("incident")
    level = assessment["level"]
    peak = incident["peak_level"] if incident and LEVELS.index(incident["peak_level"]) > LEVELS.index(level) else None
    text = f"Brain level {assessment['level_name']}, score {assessment['score']} ({assessment['basis']})"
    if peak:
        text += f"; incident peak {LEVEL_NAMES[peak]}"
    facts.add("level", "RULE OUTCOME", text)
    for group in why["groups"]:
        for factor in group["factors"]:
            if factor["points"]:
                facts.add("factor", tag, f"{factor['code']} (+{factor['points']}, {group['title']}): {factor['text']}")
    for note in why["rules"]:
        facts.add("rule", "RULE OUTCOME", note)
    for finding in why["findings"]:
        reasons = "; ".join(reason.rstrip(".") for reason in finding["reasons"][:4])
        facts.add("finding", finding["label"] or tag, f"{finding['title']}: {reasons}"[:600])
    small = why["small_vessel"]
    if small:
        facts.add("small_vessel", "ASSUMPTION", f"Small-vessel rule: {small['reason']}. {small['outcome']}")
    line = why["line"]
    if line["id"]:
        facts.add("line", "ILLUSTRATIVE", f"Line at risk: {line['name']}, {line['where']}")
    for other in line["others"]:
        facts.add("line_other", "ILLUSTRATIVE", f"Other line named by a detector: {other['name']}, {other['where']}")
    if incident:
        text = f"Incident {incident['id']}, status {incident['status']}"
        if incident.get("opened"):
            text += f", opened {incident['opened']}"
        if incident.get("status_reason"):
            text += f"; reason: {incident['status_reason']}"
        facts.add("incident", "RULE OUTCOME", text)
    elif context.get("status"):
        facts.add("incident", "RULE OUTCOME", f"No open incident: {context['status']} (Low is an observation, not an incident)")
    response = context.get("responders")
    if response:
        text = f"Who can reach it (exercise assumptions): {response['text']}"
        if response.get("deadline"):
            text += f"; earliest line ETA {response['deadline']}"
        facts.add("responders", "ASSUMPTION", text)
    if item.get("recommendation"):
        facts.add("recommendation", tag, f"Board recommendation, hand-written for this {kind.lower()}: "
                                         f"{item['recommendation']}")
    for issue in why["data_issues"]:
        facts.add("data_issue", "DATA ISSUE", issue)
    for label_tag, text in why["labels"]:
        if label_tag != "SOURCE":
            facts.add("data_label", label_tag, text)
    groups = {group["key"]: group["points"] for group in why["groups"]}
    pack = {"version": PACK_VERSION, "kind": "board", "vessel": dict(vessel), "item_id": item["id"],
            "label": item.get("label"), "data_tag": tag, "simulated": item.get("label") != "real",
            "level": {"level": level, "name": assessment["level_name"], "score": assessment["score"],
                      "peak": peak}, "groups": groups,
            "detectors": [finding["detector"] for finding in why["findings"]],
            "line": line["name"] if line["id"] else None, "replay_time": context.get("replay_time"),
            "facts": facts.items}
    pack["category"] = suggest_category(pack)
    pack["summary"] = (f"{tag} · Brain {assessment['level_name']}, score {assessment['score']}"
                       + (f" · as of {context['replay_time']}" if context.get("replay_time") else "")
                       + f" · {len(facts.items)} facts")
    return pack


def _utc_text(value) -> str | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
    return f"{stamp:%H:%M:%S} UTC on {stamp.day} {stamp:%b %Y}"


def _live_pack(vessel: dict, live: dict | None) -> dict:
    """A vessel without a Brain item: identity, position and AIS only."""
    tag = DATA_TAGS.get(vessel["label"], str(vessel["label"]).upper())
    facts = _Facts()
    live = live or {}
    real = vessel["label"] == "real"
    what = "Live AIS contact" if real else f"{vessel['label'].capitalize()} contact"
    details = [f"MMSI {vessel['id']}" if real else vessel["id"]]
    if live.get("type") and live["type"] != "Unavailable":
        details.append(live["type"])
    if live.get("ais_length_m"):
        details.append(f"declared length {live['ais_length_m']:.0f} m")
    facts.add("identity", tag, f"{what} {vessel['name']} ({', '.join(details)})")
    where = f"{'Last AIS position' if real else 'Position'} {position_text(vessel['lat'], vessel['lon'])}"
    received = _utc_text(live["received_utc"]) if live.get("received_utc") else None
    if received:
        where += f", received {received}"
    facts.add("position", tag, where)
    if live:
        facts.add("motion", tag, _motion_text(live.get("sog_kn"), live.get("cog_deg")))
    if live.get("destination"):
        facts.add("destination", tag, f"Declared AIS destination {live['destination']}")
    if real:
        facts.add("ais_limit", "LIMITATION", "AIS is self-reported: identity, position and destination are not verified")
    facts.add("no_brain", "LIMITATION", "No Brain assessment: this vessel is not scored by the incident detector, "
                                        "so the report rests on the analyst's own observation")
    pack = {"version": PACK_VERSION, "kind": "live" if live else "minimal", "vessel": dict(vessel),
            "item_id": None, "label": vessel["label"], "data_tag": tag, "simulated": not real, "level": None,
            "groups": {}, "detectors": [], "line": None, "replay_time": None, "facts": facts.items}
    pack["category"] = suggest_category(pack)
    pack["summary"] = f"{tag} · no Brain assessment · {'AIS record' if live else 'snapshot only'} · {len(facts.items)} facts"
    return pack


def suggest_category(pack: dict) -> str:
    """A category the facts support; the analyst may choose another."""
    groups, detectors = pack["groups"], set(pack["detectors"])
    if groups.get("B") and (groups.get("P") or groups.get("A")):
        return "Infrastructure concern"
    if groups.get("I") or "ais_spoofing" in detectors:
        return "AIS / identity concern"
    if any(groups.values()):
        return "Suspicious activity"
    return "Other"


def _supported(pack: dict, category: str) -> bool:
    groups, detectors = pack["groups"], set(pack["detectors"])
    topics = {fact["topic"] for fact in pack["facts"]}
    return {"Infrastructure concern": bool(groups.get("P") or groups.get("A")),
            "AIS / identity concern": bool(groups.get("I") or "ais_spoofing" in detectors or "data_issue" in topics),
            "Unsafe navigation": bool(groups.get("B")),
            "Suspicious activity": any(groups.values())}.get(category, True)


def fact_ids(pack: dict, topic: str) -> list[str]:
    return [fact["id"] for fact in pack["facts"] if fact["topic"] == topic]


def fact_text(pack: dict, topic: str) -> str | None:
    found = [fact["text"] for fact in pack["facts"] if fact["topic"] == topic]
    return found[0] if found else None


# ----- template draft ------------------------------------------------------------------

def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def template_draft(pack: dict) -> dict:
    """Officer-style draft written by code from the pack alone: observed, why, uncertain, recommended."""
    # (section, text, evidence IDs, optional): optional parts are dropped, last first, to stay near the target.
    parts: list[tuple[str, str, list[str], bool]] = []

    def add(section, topic, optional=False, text=None):
        found = [fact for fact in pack["facts"] if fact["topic"] == topic]
        if found:
            parts.append((section, text or _sentence(found[0]["text"]), [found[0]["id"]], optional))

    add("Observed", "identity")
    add("Observed", "position")
    add("Observed", "motion")
    add("Observed", "destination", True)
    add("Observed", "summary")
    factors = [fact for fact in pack["facts"] if fact["topic"] == "factor"]
    if factors:
        parts.append(("Observed", "Brain indicators: " + "; ".join(
            fact["text"].split(": ", 1)[1] for fact in factors[:4]) + ".", [fact["id"] for fact in factors[:4]], True))
    for fact in [fact for fact in pack["facts"] if fact["topic"] == "data_issue"]:
        parts.append(("Observed", _sentence(fact["text"]), [fact["id"]], False))
    add("Why it matters", "level")
    add("Why it matters", "line")
    add("Why it matters", "incident")
    add("Why it matters", "responders", True)
    add("Why it matters", "no_brain", text="No Brain assessment is available for this vessel; "
                                            "[state what you observed and why it matters].")
    labels = [fact for fact in pack["facts"] if fact["topic"] == "ais_limit" or fact["topic"] == "data_label"
              and fact["label"] in ("SIMULATED", "EXERCISE", "ILLUSTRATIVE")]
    for fact in labels[:3]:
        parts.append(("Uncertain", _sentence(fact["text"]), [fact["id"]], fact["label"] == "ILLUSTRATIVE"))
    add("Uncertain", "small_vessel", True)
    parts.append(("Uncertain", "Cause and intent are unknown; unusual behaviour is not evidence of hostile intent.",
                  [], False))
    recommendation = [fact for fact in pack["facts"] if fact["topic"] == "recommendation"]
    if recommendation:
        parts.append(("Recommended", _sentence(recommendation[0]["text"]), [recommendation[0]["id"]], False))
    else:
        parts.append(("Recommended", "[State the follow-up you request].", [], False))
    parts.append(("Recommended", "Decision rests with the duty officer; no operational action has been taken.",
                  [], False))

    def assemble(chosen):
        sections = []
        for name in ("Observed", "Why it matters", "Uncertain", "Recommended"):
            texts = [text for section, text, _ids, _optional in chosen if section == name]
            if texts:
                sections.append(f"{name}: " + " ".join(texts))
        return "\n".join(sections)

    chosen = list(parts)
    while len(assemble(chosen)) > TARGET_LENGTH and any(part[3] for part in chosen):
        last = max(index for index, part in enumerate(chosen) if part[3])
        chosen.pop(last)
    body = assemble(chosen)
    room = REASON_LIMIT - len(TEMPLATE_LABEL) - 4
    if len(body) > room:
        body = body[:room].rsplit(". ", 1)[0] + "."
    evidence = sorted({identifier for part in chosen for identifier in part[2]}, key=lambda value: int(value[1:]))
    return {"text": f"{body}\n\n— {TEMPLATE_LABEL}", "category": pack["category"], "evidence": evidence,
            "method": "template", "model": None,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ----- extraction shared by the pack and the checks ----------------------------------------

_REPLAY = re.compile(r"\bT\s?([+−-])\s?(\d{1,3})(?::(\d{2}))?(?::\d{2})?(\s?min\b)?")
_CLOCK = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?![\d:])(?:\s?(?:UTC|Z)\b)?")
_DTG = re.compile(r"\b\d{2}([01]\d|2[0-3])([0-5]\d)Z\b")
_COORD_DM = re.compile(r"(\d{1,2})\s?°\s?(\d{1,2}(?:\.\d+)?)\s?['′]?\s?([NS])[\s,;/]+(\d{1,3})\s?°\s?"
                       r"(\d{1,2}(?:\.\d+)?)\s?['′]?\s?([EW])")
_COORD_HEMI = re.compile(r"(\d{1,2}\.\d+)\s?°?\s?([NS])[\s,;/]+(\d{1,3}\.\d+)\s?°?\s?([EW])")
_COORD_SIGNED = re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{3,})\s?,\s?(-?\d{1,3}\.\d{3,})(?!\d|\.\d)")
_DURATION = re.compile(r"(?<![\w.])(\d+)\s?h\s(\d{1,2})\s?min\b")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(knots?|kn|kts?|nautical miles?|nmi|nm|NM|km|minutes?|mins?|min|"
                     r"hours?|hrs?|h|metres?|meters?|m|%|°|degrees?|deg)(?![A-Za-z])")
_PREFIXED = re.compile(r"\b(SOG|COG|score|course|heading)\s?(?:of\s)?(\d+(?:\.\d+)?)(?![\d.]*\s?(?:kn|knots|°|deg))",
                       re.IGNORECASE)
_IDS = re.compile(r"\b(SIM-\d{2,3}|INC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b|(?<![\d.])(\d{9})(?!\d|\.\d)")
_NAME = re.compile(r"\b[A-Z][A-Z'’-]{2,}(?:[ \t]+[A-Z][A-Z'’-]{2,})+\b")
_LEVEL = re.compile(r"\b(?:(critical|high|medium|low|none)\s+(?:level|severity|alert|priority)\b|"
                    r"(?:level|severity|priority|peak)\s?(?:is|of|was|:|=|at|now|raised to|assessed as)?\s?"
                    r"(critical|high|medium|low|none)\b|(?:raised|capped|lowered) to (critical|high|medium|low)\b)",
                    re.IGNORECASE)
_INTENT = re.compile(r"\b(hostile|sabotag\w*|saboteurs?|attack(?:s|ed|ing)?|malicious(?:ly)?|deliberate(?:ly)?|"
                     r"intentional(?:ly)?|on purpose|espionage|spying|enemy|adversar(?:y|ies|ial)|terroris[tm]s?|"
                     r"covert(?:ly)?|hybrid threat|threat actor)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(no|not|without|never|nor|cannot|can't|isn't|unknown|unconfirmed|unlikely|"
                       r"rule out|ruled out|absence of)\b", re.IGNORECASE)
_SIMULATED = re.compile(r"\b(simulat\w*|fictional|exercise)\b", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\[[^\]]{3,}\]")
UNITS = {"kn": "kn", "knot": "kn", "knots": "kn", "kt": "kn", "kts": "kn", "nm": "nm", "nmi": "nm",
         "nautical mile": "nm", "nautical miles": "nm", "km": "km", "%": "%", "°": "deg", "deg": "deg",
         "degree": "deg", "degrees": "deg", "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m"}
COMMON_CAPS = {"AIS", "VHF", "UTC", "MMSI", "ETA", "SOG", "COG", "SAR", "IMO", "EEZ", "BRAIN", "SIMULATED", "REAL",
               "EXERCISE", "FICTIONAL", "ILLUSTRATIVE", "ASSUMPTION", "RULE", "OUTCOME", "SOURCE", "DATA", "ISSUE",
               "LIMITATION", "NOTE", "ACTION", "NOT", "AND", "THE", "FOR", "REVIEW", "DRAFT", "REPORT", "ANALYST",
               "OBSERVED", "WHY", "MATTERS", "UNCERTAIN", "RECOMMENDED", "URGENT", "IMMEDIATE", "NONE", "LOW",
               "MEDIUM", "HIGH", "CRITICAL", "LEVEL", "VESSEL", "SHIP", "CABLE", "LINE", "CONTACT", "INCIDENT",
               "OFFICER", "DUTY", "NOTICE", "WARNING", "UNKNOWN", "UNVERIFIED", "CONFIRMED", "STATUS", "NEW"}


def _mask(text: str, span: tuple[int, int]) -> str:
    return text[:span[0]] + " " * (span[1] - span[0]) + text[span[1]:]


def _decimals(value: str) -> int:
    return len(value.split(".", 1)[1]) if "." in value else 0


def extract(text: str) -> dict:
    """Times, positions, numbers with units, IDs, caps names, level words and intent words found in ``text``."""
    found = {"replay": [], "clock": [], "coords": [], "numbers": [], "ids": [], "names": [], "levels": [],
             "intent": []}
    work = text
    for pattern in (_COORD_DM, _COORD_HEMI, _COORD_SIGNED):
        for match in pattern.finditer(work):
            groups = match.groups()
            if pattern is _COORD_DM:
                lat = int(groups[0]) + float(groups[1]) / 60
                lon = int(groups[3]) + float(groups[4]) / 60
                lat, lon = (-lat if groups[2] == "S" else lat), (-lon if groups[5] == "W" else lon)
                precision = 10 ** -_decimals(groups[1]) / 60
            elif pattern is _COORD_HEMI:
                lat = float(groups[0]) * (-1 if groups[1] == "S" else 1)
                lon = float(groups[2]) * (-1 if groups[3] == "W" else 1)
                precision = 10 ** -min(_decimals(groups[0]), _decimals(groups[2]))
            else:
                lat, lon = float(groups[0]), float(groups[1])
                precision = 10 ** -min(_decimals(groups[0]), _decimals(groups[1]))
            if abs(lat) <= 90 and abs(lon) <= 180:
                found["coords"].append({"quote": match.group(0), "lat": lat, "lon": lon, "precision": precision})
                work = _mask(work, match.span())
    for match in _REPLAY.finditer(work):
        sign = -1 if match.group(1) in "−-" else 1
        hours_minutes = match.group(3) is not None
        minutes = int(match.group(2)) * 60 + int(match.group(3)) if hours_minutes else int(match.group(2))
        found["replay"].append({"quote": match.group(0).strip(), "minutes": sign * minutes})
        work = _mask(work, match.span())
    for pattern in (_DTG, _CLOCK):
        for match in pattern.finditer(work):
            found["clock"].append({"quote": match.group(0).strip(), "hm": (int(match.group(1)), int(match.group(2)))})
            work = _mask(work, match.span())
    for match in _IDS.finditer(work):
        found["ids"].append(match.group(1) or match.group(2))
        work = _mask(work, match.span())
    # Durations are compared in minutes; "tol" is half the last digit the text shows.
    for match in _DURATION.finditer(work):
        found["numbers"].append({"quote": match.group(0), "unit": "min",
                                 "value": int(match.group(1)) * 60 + int(match.group(2)), "tol": 0.5})
        work = _mask(work, match.span())
    for match in _NUMBER.finditer(work):
        raw, unit = match.group(1), match.group(2)
        value, tol = float(raw), 0.5 * 10 ** -_decimals(raw)
        if unit.lower().startswith("min"):
            unit = "min"
        elif unit.lower() in ("h", "hr", "hrs", "hour", "hours"):
            # A whole number of hours is a rounding: "2 h" may stand for 1 h 31 min to 2 h 29 min.
            unit, value, tol = "min", value * 60, (30 if "." not in raw else tol * 60)
        else:
            unit = UNITS.get(unit if unit in UNITS else unit.lower(), unit.lower())
        found["numbers"].append({"quote": match.group(0), "unit": unit, "value": value, "tol": tol})
        work = _mask(work, match.span())
    for match in _PREFIXED.finditer(work):
        unit = {"sog": "kn", "score": "score"}.get(match.group(1).lower(), "deg")
        raw = match.group(2)
        found["numbers"].append({"quote": match.group(0), "unit": unit, "value": float(raw),
                                 "tol": 0.5 * 10 ** -_decimals(raw)})
    found["names"] = [match.group(0) for match in _NAME.finditer(text)
                      if not set(re.split(r"[\s'’-]+", match.group(0))) <= COMMON_CAPS]
    found["levels"] = [{"quote": match.group(0), "level": next(g for g in match.groups() if g).lower()}
                       for match in _LEVEL.finditer(text)]
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        for match in _INTENT.finditer(sentence):
            before = sentence[max(0, match.start() - 60):match.start()]
            after = sentence[match.end():match.end() + 30]
            if not _NEGATION.search(before) and not re.match(r"\s*(?:intent\s)?(?:unknown|not established)", after):
                found["intent"].append({"quote": match.group(0), "sentence": sentence.strip()})
    return found


def allowed(pack: dict) -> dict:
    """Everything the facts state, plus the report's own vessel snapshot."""
    vessel = pack["vessel"]
    joined = "\n".join(fact["text"] for fact in pack["facts"])
    found = extract(joined)
    found["coords"].append({"quote": "", "lat": vessel["lat"], "lon": vessel["lon"], "precision": 0})
    found["ids"] = set(found["ids"]) | {str(vessel["id"])} | ({pack["item_id"]} if pack["item_id"] else set())
    found["names"] = {name.upper() for name in found["names"]} | {str(vessel["name"]).upper()}
    levels = {entry["level"] for entry in found["levels"]}
    if pack["level"]:
        levels |= {pack["level"]["level"]} | ({pack["level"]["peak"]} if pack["level"]["peak"] else set())
    found["levels"] = levels
    return found


# ----- code check --------------------------------------------------------------------------

def strip_label(text: str) -> str:
    """The report body without the generated-text label line."""
    lines = [line for line in text.splitlines() if TEMPLATE_LABEL not in line and AI_LABEL not in line]
    return "\n".join(lines).strip()


def _finding(kind, quote, problem, fix, evidence=()):
    return {"layer": "code", "kind": kind, "quote": quote, "problem": problem, "fix": fix, "evidence": list(evidence)}


def _number_ok(entry: dict, choices: list[dict]) -> bool:
    return any(choice["unit"] == entry["unit"]
               and abs(entry["value"] - choice["value"]) <= max(entry["tol"], choice["tol"]) + 1e-9
               for choice in choices)


def _coord_ok(entry: dict, choices: list[dict]) -> bool:
    for choice in choices:
        north = (entry["lat"] - choice["lat"]) * 60
        east = (entry["lon"] - choice["lon"]) * 60 * math.cos(math.radians(choice["lat"]))
        # Half a nautical mile, or the rounding the text itself shows, whichever is larger.
        if math.hypot(north, east) <= max(0.5, entry["precision"] * 60):
            return True
    return False


def check_report(pack: dict, text: str, category: str) -> dict:
    """Exact comparison of the report text with the pack. Each finding cites the evidence it relies on."""
    findings = []
    body = strip_label(text or "")
    ok = allowed(pack)
    position_ids = fact_ids(pack, "position")
    identity_ids = fact_ids(pack, "identity")
    if not body:
        findings.append(_finding("missing", "", "The report text is empty.", "Write or draft the report.", ()))
        return {"layer": "code", "consistent": False, "findings": findings, "notes": []}
    if len(text.strip()) > REASON_LIMIT:
        findings.append(_finding("length", "", f"The text is {len(text.strip())} characters; the limit is "
                                               f"{REASON_LIMIT}.", "Shorten the text.", ()))
    found = extract(body)
    time_ids = position_ids + fact_ids(pack, "incident") + fact_ids(pack, "responders")
    allowed_replay = {entry["minutes"] for entry in ok["replay"]}
    for entry in found["replay"]:
        if entry["minutes"] not in allowed_replay:
            now = f" (the pack is as of {pack['replay_time']})" if pack.get("replay_time") else ""
            findings.append(_finding("time", entry["quote"], f"Replay time not in system data{now}.",
                                     "Use a time from the evidence or remove it.", time_ids))
    allowed_clock = {entry["hm"] for entry in ok["clock"]}
    for entry in found["clock"]:
        if entry["hm"] not in allowed_clock:
            findings.append(_finding("time", entry["quote"], "Time not in system data.",
                                     "Use the AIS receive time from the evidence or remove it.", position_ids))
    for entry in found["coords"]:
        if not _coord_ok(entry, ok["coords"]):
            here = position_text(pack["vessel"]["lat"], pack["vessel"]["lon"])
            findings.append(_finding("position", entry["quote"], "Position not in system data.",
                                     f"Use the reported position {here}.", position_ids))
    for entry in found["numbers"]:
        if not _number_ok(entry, ok["numbers"]):
            findings.append(_finding("number", entry["quote"].strip(), "Value not in system data.",
                                     "Use the value from the evidence or remove it.",
                                     fact_ids(pack, "motion") + fact_ids(pack, "factor")[:2]))
    for identifier in found["ids"]:
        if identifier not in ok["ids"]:
            findings.append(_finding("identity", identifier, "ID not in system data for this vessel.",
                                     f"This report is about {pack['vessel']['id']}.", identity_ids))
    for name in found["names"]:
        if name.upper() not in ok["names"]:
            findings.append(_finding("name", name, "Name not in system data; if it is a vessel, it is not the "
                                                   "reported one.", f"The reported vessel is {pack['vessel']['name']}.",
                                     identity_ids))
    for entry in found["levels"]:
        if entry["level"] not in ok["levels"]:
            level = pack["level"]
            fix = (f"Brain level is {level['name']}; the level is Brain's and is not changed in a report."
                   if level else "This vessel has no Brain level; describe the observation instead.")
            findings.append(_finding("level", entry["quote"], "Level differs from Brain.", fix, fact_ids(pack, "level")))
    for entry in found["intent"]:
        evidence = [fact["id"] for fact in pack["facts"] if fact["label"] == "RULE OUTCOME"][-1:]
        findings.append(_finding("intent", entry["quote"], "Intent stated without evidence: the system holds no "
                                                          "evidence of intent.",
                                 "State the observed behaviour; say intent is unknown.", evidence))
    if pack["simulated"] and not _SIMULATED.search(body):
        findings.append(_finding("label", "", f"The text does not say the contact is {pack['label']}.",
                                 f"Add the data label ({pack['data_tag']}).", identity_ids))
    if not pack["simulated"] and re.search(r"\b(simulated|fictional)\b", body, re.IGNORECASE):
        findings.append(_finding("label", "simulated", "The text calls a real AIS contact simulated.",
                                 "Remove it: this is live AIS (REAL).", identity_ids))
    name, identifier = str(pack["vessel"]["name"]), str(pack["vessel"]["id"])
    if name.lower() not in body.lower() and identifier not in body:
        findings.append(_finding("missing", "", "The vessel is not named.", f"Name {name} ({identifier}).", identity_ids))
    if pack["level"] and not found["levels"]:
        level = pack["level"]
        findings.append(_finding("missing", "", "Brain level is not stated.",
                                 f"Add: Brain level {level['name']}, score {level['score']}.", fact_ids(pack, "level")))
    for match in _PLACEHOLDER.finditer(body):
        findings.append(_finding("placeholder", match.group(0), "Placeholder left in the text.",
                                 "Replace it with your observation or remove it.", ()))
    notes = []
    if category not in CATEGORIES:
        findings.append(_finding("category", category, "Unknown category.", "Choose a listed category.", ()))
    elif pack["kind"] != "board":
        notes.append("No Brain assessment for this vessel: the category is not checked.")
    elif not _supported(pack, category):
        findings.append(_finding("category", category, "The system data has no evidence for this category.",
                                 f"Suggested: {pack['category']}.", fact_ids(pack, "level")))
    return {"layer": "code", "consistent": not findings, "findings": findings, "notes": notes}
