"""Dark vessels: a satellite radar contact where AIS is silent.

Two cases, both read from ``context["detections"]`` (the scenario's radar
contacts) up to ``context["now"]``:

* **A vessel that went dark.** Its AIS had been silent for ``GAP_S`` or more
  when the satellite passed, and the contact lies where the vessel could have
  been: inside the reachable circle from its last fix before the pass and,
  once AIS has come back, within reach of the returning fix too. The finding
  fills ``ais_gap_min`` (rule I1 in ``argus.levels``), ``dark_radar_contact``
  (I3), ``radar_length_m`` and, when both lengths are known,
  ``length_mismatch_pct`` (I4).
* **A contact with no AIS at all.** ``radar_only_vessels`` turns each contact
  that no vessel's AIS can explain into a pseudo-vessel with one fix, which
  ``argus.assemble`` scores like any other vessel. Its finding fills
  ``no_ais`` (I1) and ``dark_radar_contact`` (I3); ``cable_risk`` then measures
  how close it is to each line.

A contact Space has matched to an AIS vessel (``matched_mmsi``) gives nothing.
Space owns that association; this detector reads one vessel at a time and
cannot see whether another, transmitting vessel was at the contact. Real or
reconstructed contacts never pair with fictional or simulated AIS
(``argus.space.compatible_labels``). Reachability uses the assumed top speed of
``argus.prediction`` (1.2 x the fastest SOG in the hour before, at least 15 kn),
the same circle the map draws for a dark vessel.

Every threshold is an assumption. An AIS gap is often only a reception gap, and
a contact is a custody candidate, not a confirmed identity: findings say "for
review" and never state that a transponder was switched off.
"""

from __future__ import annotations

from argus.countdown import nm_between
from argus.prediction import last_fix_at, v_max_kn
from argus.space import compatible_labels

DETECTOR = "dark_vessel"

# Thresholds (assumptions).
GAP_S = 10 * 60  # AIS silent this long at the pass: the vessel was dark (as cable_risk.DARK_S)
LOOKBACK_S = 6 * 3600  # contacts older than this are no longer looked at
REACH_MARGIN_NM = 1.0  # slack for radar geolocation and AIS timing
RADAR_ONLY_NAME = "Unidentified radar contact"
SOURCE_NAMES = {"sentinel1": "Sentinel-1 radar"}


def _visible(detections, now) -> list[dict]:
    """Contacts with a time and position, seen at or before ``now`` and within the look-back."""
    return [d for d in detections or () if d.get("t") is not None and d.get("lat") is not None
            and d.get("lon") is not None and (now is None or now - LOOKBACK_S <= d["t"] <= now)]


def _track(vessel: dict, now) -> list[dict]:
    return [fix for fix in vessel.get("track") or [] if fix.get("lat") is not None and (now is None or fix["t"] <= now)]


def reachable(track: list[dict], detection: dict) -> dict | None:
    """How the vessel could have been at the contact: last fix before it, next fix after it, distances; else None.

    ``track`` must hold only fixes already received. The contact must be within
    v_max x elapsed (+ margin) of the last fix before it and, when AIS has
    come back, of the first fix after it.
    """
    t = detection["t"]
    before = last_fix_at(track, t)
    if before is None:
        return None
    after = next((fix for fix in track if fix["t"] > t), None)
    v_max = v_max_kn(track, before["t"])
    from_nm = nm_between(before["lat"], before["lon"], detection["lat"], detection["lon"])
    reach_nm = v_max * (t - before["t"]) / 3600 + REACH_MARGIN_NM
    if from_nm > reach_nm:
        return None
    to_nm = None
    if after is not None:
        to_nm = nm_between(detection["lat"], detection["lon"], after["lat"], after["lon"])
        if to_nm > v_max * (after["t"] - t) / 3600 + REACH_MARGIN_NM:
            return None
    return {"before": before, "after": after, "v_max_kn": v_max, "from_nm": from_nm, "reach_nm": reach_nm,
            "to_nm": to_nm}


def radar_only_vessels(vessels: list[dict], detections: list[dict], now: int | None = None) -> list[dict]:
    """A one-fix pseudo-vessel for every contact no AIS vessel can explain.

    Explained: Space matched it (``matched_mmsi``), or some vessel with a
    compatible label could have reached it from its fixes around the pass
    (whether its AIS was on or silent).
    """
    contacts = []
    for index, detection in enumerate(_visible(detections, now)):
        if detection.get("matched_mmsi") is not None:
            continue
        if any(compatible_labels(detection, vessel, "simulated") and reachable(_track(vessel, now), detection)
               for vessel in vessels):
            continue
        name = detection.get("scene_id") or f"contact-{index + 1}"
        contacts.append({"mmsi": f"RADAR-{name}-{detection['t']}", "name": RADAR_ONLY_NAME, "radar_only": True,
                         "ship_type": None, "ais_class": None, "ais_length_m": None, "destination": None,
                         "nav_status": None, "detection": detection, "label": detection.get("label", "simulated"),
                         "track": [{"t": detection["t"], "lat": detection["lat"], "lon": detection["lon"]}]})
    return contacts


def _source(detection: dict) -> str:
    source = SOURCE_NAMES.get(detection.get("source"), detection.get("source") or "satellite radar")
    return f"{source} scene {detection['scene_id']}" if detection.get("scene_id") else source


def _contact(detection: dict) -> dict:
    return {"t": detection["t"], "position": [detection["lat"], detection["lon"]],
            "length_m": detection.get("length_m"), "source": detection.get("source"),
            "scene_id": detection.get("scene_id"), "label": detection.get("label")}


def _radar_only_finding(vessel: dict) -> dict:
    detection = vessel["detection"]
    length = detection.get("length_m")
    obs = {"no_ais": True, "dark_radar_contact": True}
    if length:
        obs["radar_length_m"] = length
    size = f"measured {length:g} m" if length else "length not measured"
    return {"detector": DETECTOR, "mmsi": vessel["mmsi"], "t": int(detection["t"]),
            "position": [detection["lat"], detection["lon"]], "strength": 0.6,
            "reasons": [f"Dark contact, for review: {_source(detection)} sees a vessel ({size}) that no AIS "
                        "vessel could have been; identity unknown.",
                        "No transmitting or recently silent AIS vessel could reach the contact at its assumed top "
                        f"speed (+{REACH_MARGIN_NM:g} nm slack), and Space has not matched it. A vessel outside the "
                        "AIS feed or a false radar detection are also possible."],
            "related": {"radar_contact": _contact(detection)}, "label": vessel.get("label", "simulated"), "obs": obs}


def _gap_finding(vessel: dict, detection: dict, how: dict, now: int) -> dict:
    before, after = how["before"], how["after"]
    gap_min = ((after["t"] if after else now) - before["t"]) / 60
    obs = {"ais_gap_min": round(gap_min), "dark_radar_contact": True}
    length, ais_length = detection.get("length_m"), vessel.get("ais_length_m")
    silent_min = (detection["t"] - before["t"]) / 60
    reasons = [f"Dark vessel, for review: AIS had been silent {silent_min:.0f} min when {_source(detection)} saw a "
               f"contact {how['from_nm']:.1f} nm from the last fix, inside the {how['reach_nm']:.1f} nm it could "
               "have covered; identity unconfirmed."]
    if after is None:
        reasons.append(f"AIS still silent, {gap_min:.0f} min since the last fix.")
    else:
        reasons.append(f"AIS came back after {gap_min:.0f} min, {how['to_nm']:.1f} nm from the contact: reachable, "
                       "so the contact may be this vessel.")
    if length:
        obs["radar_length_m"] = length
        if ais_length:
            pct = abs(length - ais_length) / ais_length * 100
            obs["length_mismatch_pct"] = round(pct, 1)
            reasons.append(f"Radar length {length:g} m against the declared {ais_length:g} m ({pct:.0f}% apart; "
                           "rule I4 counts more than 25%).")
    reasons.append(f"Assumed top speed {how['v_max_kn']:.0f} kn (+{REACH_MARGIN_NM:g} nm slack). A reception gap or "
                   "another dark vessel may explain the contact; cause unknown.")
    return {"detector": DETECTOR, "mmsi": vessel["mmsi"], "t": int(detection["t"]),
            "position": [detection["lat"], detection["lon"]], "strength": 0.7, "reasons": reasons,
            "related": {"radar_contact": _contact(detection), "gap_start_t": before["t"],
                        "gap_end_t": after["t"] if after else None},
            "label": vessel.get("label", "simulated"), "obs": obs}


def dark_vessel(vessel: dict, context: dict) -> list[dict]:
    """One ``dark_vessel`` finding per unmatched contact seen while this vessel's AIS was silent nearby."""
    if vessel.get("radar_only"):
        return [_radar_only_finding(vessel)]
    now = context.get("now")
    track = _track(vessel, now)
    detections = context.get("detections") or []
    if not track or not detections:
        return []
    if now is None:  # the whole record: up to the last fix or contact
        now = max([track[-1]["t"], *(d["t"] for d in detections if d.get("t") is not None)])
    findings = []
    for detection in _visible(detections, now):
        if detection.get("matched_mmsi") is not None or not compatible_labels(detection, vessel, "simulated"):
            continue
        how = reachable(track, detection)
        if how and detection["t"] - how["before"]["t"] >= GAP_S:
            findings.append(_gap_finding(vessel, detection, how, now))
    return findings


detect = dark_vessel  # the package convention; the function name labels the assessments file
