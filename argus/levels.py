"""Explainable risk levels for vessels near seabed infrastructure.

A level answers "how much attention does this line need now?", not "is the crew
guilty?". A prepared crew can supply a plausible story, so the rules score the
danger to the line from behaviour, physics, proximity and consequence.

Points come from documented observations in five groups: behaviour (B),
identity and data quality (I), proximity and time (P), the line at risk (A) and
context (C). Bands, gates and overrides stop one noisy signal from producing a
high level. The result is a rule outcome, not a probability of hostile intent.
"""

from __future__ import annotations

LEVELS = ("none", "low", "medium", "high", "critical")
LEVEL_NAMES = {"none": "None", "low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
RANK = {level: index for index, level in enumerate(LEVELS)}
BANDS = ((12, "critical"), (9, "high"), (6, "medium"), (3, "low"))
CRITICAL_ASSETS = {
    "gas": "gas pipeline", "power": "power interconnector", "sole_link": "only link on its route",
    "cluster": "cluster of three or more lines", "transatlantic": "transatlantic cable",
}
# Coastal sites from ``argus.sites``: label and points.
SITE_ASSETS = {"naval_base": ("naval base", 2), "landfall": ("cable or pipeline landfall", 2),
               "wind_farm": ("offshore wind farm", 1)}
BEHAVIOUR_CAP, IDENTITY_CAP, CONTEXT_CAP = 6, 3, 3
RULES_VERSION = "levels v1.1"


def _band(score: int) -> str:
    for minimum, level in BANDS:
        if score >= minimum:
            return level
    return "none"


def _capped(items, group, cap, factors):
    """Award points strongest first until the group cap; list every observed item."""
    total = 0
    for code, points, text in sorted(items, key=lambda item: -item[1]):
        awarded = max(0, min(points, cap - total))
        total += awarded
        suffix = "" if awarded == points else " (group limit reached)"
        factors.append({"code": code, "group": group, "points": awarded, "text": text + suffix})
    return total


def _behaviour(obs, factors):
    patterns = []
    drop, turn = obs.get("speed_drop_pct") or 0, obs.get("course_change_deg") or 0
    if obs.get("drag_signature") or (drop >= 20 and turn >= 20):
        detail = f"speed fell {drop:.0f}% and course changed {turn:.0f}°" if drop and turn else "slow, unsteady track across the line"
        patterns.append(("B1", 4, f"Anchor-drag pattern under way: {detail}"))
    if obs.get("dragging_at_anchor"):
        patterns.append(("B2", 4, f"Moving {obs.get('sog_kn', 1.0):.1f} kn while reporting 'at anchor': anchor dragging"))
    if (obs.get("hover_hours") or 0) >= 1 and obs.get("special_vessel") and obs.get("deep_segment"):
        patterns.append(("B3", 4, f"Held position {obs['hover_hours']:.1f} h over a deep cable; vessel can launch underwater vehicles"))
    if (obs.get("loiter_hours") or 0) >= 1:
        patterns.append(("B4", 3, f"Loitered or circled {obs['loiter_hours']:.1f} h beside the line"))
    if (obs.get("passes_6h") or 0) >= 3:
        patterns.append(("B5", 3, f"{obs['passes_6h']} passes over the same segment in 6 h"))
    if (obs.get("slow_over_corridor_min") or 0) >= 10:
        patterns.append(("B6", 3, f"{obs['slow_over_corridor_min']:.0f} min at 6 kn or less over the corridor without a stated reason"))
    if obs.get("anchored_near_cable"):
        patterns.append(("B7", 2, "Anchored within 1 nm of the line"))
    if obs.get("fishing_near_corridor"):
        patterns.append(("B10", 2, "Bottom-fishing pattern within 2 nm of the line"))
    if obs.get("slowdown_near_corridor"):
        patterns.append(("B11", 2, "Unexplained slowdown within 5 nm of the line"))
    stopped = obs.get("stopped_offport_min") or 0
    if stopped >= 30:
        hours = f"{stopped / 60:.1f} h" if stopped >= 120 else f"{stopped:.0f} min"
        patterns.append(("B12", 3 if stopped >= 120 else 2,
                         f"Stopped {hours} away from any port or designated anchorage"))
    if (obs.get("site_loiter_hours") or 0) >= 1:
        patterns.append(("B13", 3, f"Stayed {obs['site_loiter_hours']:.1f} h inside the protection zone around the site"))
    patterns.sort(key=lambda item: -item[1])
    total = 0
    for index, (code, points, text) in enumerate(patterns):
        awarded = points if index == 0 else 1
        factors.append({"code": code, "group": "behaviour", "points": awarded,
                        "text": text if index == 0 else text + " (additional pattern)"})
        total += awarded
    if (obs.get("prior_slowdowns") or 0) >= 1:
        factors.append({"code": "B8", "group": "behaviour", "points": 1,
                        "text": f"Slowed over these lines on {obs['prior_slowdowns']} earlier voyage(s)"})
        total += 1
    if obs.get("status_mismatch"):
        factors.append({"code": "B9", "group": "behaviour", "points": 1,
                        "text": "AIS navigation status contradicts the observed movement"})
        total += 1
    if total > BEHAVIOUR_CAP:
        factors.append({"code": "B*", "group": "behaviour", "points": BEHAVIOUR_CAP - total,
                        "text": f"Behaviour group limited to {BEHAVIOUR_CAP} points"})
        total = BEHAVIOUR_CAP
    return total


def _identity(obs, factors):
    items = []
    if obs.get("no_ais"):
        items.append(("I1", 2, "No AIS transmission from this radar contact"))
    elif (obs.get("ais_gap_min") or 0) >= 10:
        near = "site" if obs.get("asset_class") in SITE_ASSETS else "line"
        items.append(("I1", 2, f"AIS silent for {obs['ais_gap_min']:.0f} min near the {near}"))
    if obs.get("spoof_signs"):
        items.append(("I2", 2, "Impossible position jump or two positions for one identity"))
    if obs.get("dark_radar_contact"):
        items.append(("I3", 1, "Satellite-radar contact without matching AIS on the track"))
    if (obs.get("length_mismatch_pct") or 0) > 25:
        items.append(("I4", 1, f"Radar length differs {obs['length_mismatch_pct']:.0f}% from the AIS length"))
    if (obs.get("identity_changes") or 0) >= 1:
        items.append(("I5", 1, f"Name, flag or MMSI changed {obs['identity_changes']}× in 12 months"))
    if obs.get("static_incomplete"):
        items.append(("I6", 1, "Static AIS data incomplete: destination or IMO number missing"))
    return _capped(items, "identity", IDENTITY_CAP, factors)


def _proximity(obs, factors, counted):
    eta, distance = obs.get("eta_min"), obs.get("distance_nm")
    noun = "site's zone" if obs.get("asset_class") in SITE_ASSETS else "line"
    if obs.get("in_zone"):
        code, points, text = "P1", 4, "Inside the protection zone around the site"
    elif obs.get("in_corridor"):
        code, points, text = "P1", 4, "Inside the line's 1 nm corridor"
    elif eta is not None and eta <= 30:
        code, points, text = "P1", 4, f"Reaches an anchor-reachable section in {eta:.0f} min"
    elif eta is not None and eta <= 120:
        code, points, text = "P2", 3, f"Reaches the line in {eta:.0f} min"
    elif (eta is not None and eta <= 360) or (distance is not None and distance <= 5):
        code, points = "P3", 1
        text = f"Reaches the {noun} in {eta / 60:.1f} h" if eta is not None and eta <= 360 else f"{distance:.1f} nm from the {noun}"
    else:
        return 0
    if not counted:
        factors.append({"code": code, "group": "proximity", "points": 0,
                        "text": text + " (counts only with a behaviour or identity cue)"})
        return 0
    factors.append({"code": code, "group": "proximity", "points": points, "text": text})
    return points


def _asset(obs, factors, counted):
    asset = obs.get("asset_class")
    if not asset:
        return 0
    if asset in SITE_ASSETS:
        label, points = SITE_ASSETS[asset]
        items = [("A4", points, f"Site at risk: {label}")]
    else:
        label = CRITICAL_ASSETS.get(asset, "telecom cable with alternative routes")
        points = 2 if asset in CRITICAL_ASSETS else 1
        items = [("A1" if points == 2 else "A2", points, f"Line at risk: {label}")]
    if obs.get("asset_vulnerable"):
        items.append(("A3", 1, "Exposed, shallow-buried or previously damaged segment"))
    total = 0
    for code, value, text in items:
        awarded = value if counted else 0
        suffix = "" if counted else " (counts only with a behaviour or identity cue)"
        factors.append({"code": code, "group": "asset", "points": awarded, "text": text + suffix})
        total += awarded
    return total


def _context(obs, factors):
    items = []
    if obs.get("watchlist"):
        items.append(("C1", 2, "On a sanctions or shadow-fleet watch list"))
    if obs.get("flag_risk"):
        items.append(("C2", 1, "Recent flag change or opaque ownership"))
    if obs.get("route_inconsistent"):
        items.append(("C3", 1, "Declared destination does not match the route"))
    if obs.get("gale_warning"):
        items.append(("C4", 1, "Gale warning in this sea area raises anchor-drag risk"))
    if obs.get("second_sensor"):
        items.append(("C5", 2, "A second sensor (fibre or radar) reports activity at the line"))
    return _capped(items, "context", CONTEXT_CAP, factors)


def assess(obs: dict) -> dict:
    """Score one observation set. Missing keys mean "not observed"."""
    factors: list[dict] = []
    notes: list[str] = []
    b = _behaviour(obs, factors)
    i = _identity(obs, factors)
    counted = b + i >= 2
    p = _proximity(obs, factors, counted)
    a = _asset(obs, factors, counted)
    c = _context(obs, factors)
    score = b + i + p + a + c
    level = _band(score)

    method_possible = obs.get("method_possible", True)
    high_gate = b >= 3 and method_possible and p >= 3
    critical_gate = high_gate and p == 4  # in the corridor or zone, or within 30 min
    if b == 0 and RANK[level] > RANK["medium"]:
        level = "medium"
        notes.append("Capped at Medium: no behavioural indicator.")
    if RANK[level] >= RANK["high"] and not high_gate:
        level = "medium"
        notes.append("Capped at Medium: High requires a behavioural pattern, a feasible damage method at this "
                     "depth and the line within 2 h.")
    if level == "critical" and not critical_gate:
        level = "high"
        notes.append("Capped at High: Critical requires the vessel in the corridor or within 30 min of it.")

    if obs.get("fault_confirmed"):
        level = "critical"
        notes.append("Raised to Critical: line fault or fibre disturbance reported at this position and time.")
    if obs.get("ignored_instruction"):
        level = "critical"
        notes.append("Raised to Critical: vessel did not comply with a recorded instruction near the line.")
    if obs.get("no_response_in_time") and level in ("medium", "high"):
        level = LEVELS[RANK[level] + 1]
        notes.append("Raised one level: no response asset can arrive before the earliest ETA.")
    if obs.get("authorised") and RANK[level] > RANK["low"]:
        level = "low"
        notes.append("Capped at Low: notified, authorised operation (repair or survey).")

    return {"score": score, "level": level, "level_name": LEVEL_NAMES[level], "rank": RANK[level],
            "groups": {"B": b, "I": i, "P": p, "A": a, "C": c},
            "basis": f"B{b} I{i} P{p} A{a} C{c} = {score}",
            "factors": factors, "notes": notes, "rules": RULES_VERSION}
