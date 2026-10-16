"""Is this vessel on a sanctions or shadow-fleet list? (rules C1, C2 and I5)

Checks a received AIS vessel against the newest kept copy of the OpenSanctions
maritime list (``argus.watchlist_data``), by MMSI or IMO only, never by name.

* C1 (+2, context): on a sanctions list (confirmed), or in the shadow-fleet
  list of Ukraine's GUR without sanctions yet (suspected). Sets ``watchlist``.
* C2 (+1, context): flag risk on a listed vessel. Its MMSI's country code (the
  ITU MID table) is not a flag any list gives; GUR records five or more flags
  for it; GUR lists its current flag as unknown or false; or its MMSI looks
  made up (four zeros after the country code, like the 610000036 the tanker
  Blue used). Sets ``flag_risk``.
* I5 (+1, identity): former names the lists record. They carry no dates, so
  the finding says so instead of "in 12 months". Sets ``identity_changes``
  and ``identity_changes_basis``.

Information only, without points: port-state detentions and bans, GUR's other
marine vessels and RUSI's North Korea reports; a number that several listed
vessels share; a vessel taken off the lists; an MMSI whose country code ITU
never allocated; and AIS-SART, man-overboard and EPIRB-AIS beacons (MMSI 970,
972, 974): "possible distress beacon, check".

Only vessels labelled real or reconstructed are matched, so a fictional MMSI
never picks up a real ship's record. List cues are context: a listed ship that
passes calmly stays Low (docs/12-argus-mara-alert-levels.md). A list entry is a
lead for review, not proof. Data: OpenSanctions, CC BY-NC 4.0.
"""

from __future__ import annotations

from datetime import date

from argus import watchlist_data as lists

DETECTOR = "watchlist"
REAL_LABELS = frozenset({"real", "reconstructed"})
STRENGTH = {"confirmed": 1.0, "suspected": 0.7}
NAME_DOUBT = 0.6  # strength factor when the AIS name is not among the listed names
I5_BASIS = "former names recorded by the lists; dates not given"
NO_POINTS = "Information only, no points."
INSPECTIONS = frozenset({"ext_tokyo_mou_psc", "ext_abuja_mou_psc"})  # routine inspections say nothing bad
LEAD = "a lead for review, not proof"


def _when(day: str | None) -> str:
    """'2026-10-15' -> '15 Oct 2026'."""
    if not day:
        return "an unknown date"
    parsed = date.fromisoformat(day)
    return f"{parsed.day} {parsed:%b %Y}"


def _last_fix(vessel: dict, context: dict) -> tuple:
    now = context.get("now")
    track = [fix for fix in vessel.get("track") or [] if now is None or fix.get("t", 0) <= now]
    if track:
        return track[-1].get("t"), [track[-1]["lat"], track[-1]["lon"]]
    if vessel.get("lat") is not None and vessel.get("lon") is not None:
        return None, [vessel["lat"], vessel["lon"]]
    return None, None


def _finding(vessel: dict, where: tuple, kind: str, reasons: list[str], related: dict, obs: dict | None = None,
             strength: float = 0.0) -> dict:
    return {"detector": DETECTOR, "mmsi": vessel.get("mmsi"), "t": where[0], "position": where[1],
            "strength": strength, "reasons": reasons, "related": {"kind": kind, **related},
            "label": vessel.get("label", "simulated"), "obs": obs or {}}


def _who(record: dict) -> str:
    return record["name"] + (f" (IMO {record['imo']})" if record["imo"] else "")


def _names(names: list[str], limit: int = 5) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _since(result: dict) -> str:
    """When the kept list copies first held it, and any earlier GUR naming or lifted sanctions."""
    since, first, oldest = result["since"], result["first_listed"], result["oldest_copy"]
    if not since:
        return ""
    text = f" On the list since {_when(since)}" + (" or earlier (the oldest copy kept here)" if since == oldest else "")
    if result["tier"] == "confirmed" and first and first < since:
        text += f"; GUR named it from {_when(first)}, before the sanctions"
    for item in result["previous"]:
        text += f"; it was {item['tier']} from {_when(item['since'])} until {_when(item['until'])}"
    return text + "."


def _listed(vessel: dict, mmsi: str | None, result: dict, where: tuple) -> dict:
    record, tier = result["record"], result["tier"]
    copy = f"OpenSanctions list of {_when(result['list_date'])}, {lists.LICENCE}"
    related = {"tier": tier, "imo": record["imo"], "listed_name": record["name"], "listed_names": record["names"],
               "lists": record["lists"], "sanctioned_by": record["sanctioned_by"], "flags": list(record["flags"]),
               "flag_history": record["flag_history"], "mid": lists.mid_info(mmsi), "matched_by": result["matched_by"],
               "name_agrees": result["name_agrees"], "since": result["since"], "first_listed": result["first_listed"],
               "previous": result["previous"], "list_date": result["list_date"],
               "list_version": result["list_version"], "opensanctions_url": record["url"], "credit": lists.CREDIT}
    if tier not in lists.POINT_TIERS:
        sources = [lists.DATASETS.get(name, (name,))[0] for name in record["datasets"] if name not in INSPECTIONS]
        reason = (f"Record for the vessel card: {_who(record)} appears in {', '.join(sources)} "
                  f"(matched by {result['matched_by']}; {copy}). {NO_POINTS}")
        return _finding(vessel, where, "listed", [reason + _since(result)], related)
    if tier == "confirmed":
        summary = f"On a sanctions list ({', '.join(record['sanctioned_by'])}): {_who(record)}"
        if "mare.shadow" in record["risks"]:
            summary += ", also in GUR's shadow-fleet list"
    else:
        summary = (f"In the shadow-fleet list of Ukraine's GUR, not sanctioned yet: {_who(record)}. GUR often names "
                   "ships months before the EU or UK sanctions them")
    reasons = [f"{summary}. Matched by {result['matched_by']} ({copy}); {LEAD}.{_since(result)}"]
    obs = {"watchlist": True}
    if result["name_agrees"] is False:
        reasons.append(f"Its AIS name {str(vessel.get('name') or '').strip()} is not among the listed names "
                       f"({_names(record['names'])}): a spelling, a rename since listing, or the number now "
                       "belongs to another ship. Check the IMO before acting.")
    signs = lists.flag_signs(record, mmsi)
    if signs:
        obs["flag_risk"] = True
        reasons.append("Flag risk: " + "; ".join(signs) + ".")
    former = lists.former_names(record, vessel.get("name"))
    if former:
        obs.update(identity_changes=len(former), identity_changes_basis=I5_BASIS)
        reasons.append(f"Former names in the lists (dates not given): {_names(former)}.")
    related.update(flag_signs=signs, former_names=former)
    strength = STRENGTH[tier] * (NAME_DOUBT if result["name_agrees"] is False else 1.0)
    return _finding(vessel, where, "listed", reasons, related, obs, round(strength, 2))


def watchlist(vessel: dict, context: dict) -> list[dict]:
    """List, flag and beacon findings for one vessel; empty when nothing applies."""
    mmsi = lists.normalise_mmsi(vessel.get("mmsi"))
    where = _last_fix(vessel, context)
    beacon = lists.beacon_kind(mmsi)
    if beacon:
        reason = (f"Possible distress beacon, check: MMSI {mmsi} starts with {mmsi[:3]}, the number of an {beacon}, "
                  f"not a ship. Tests happen, but a live one can mean someone in distress. {NO_POINTS}")
        return [_finding(vessel, where, "beacon", [reason], {"beacon": beacon})]
    if vessel.get("label", "simulated") not in REAL_LABELS:
        return []  # fictional and simulated vessels are never compared with real lists
    watch = context["watchlist"] if "watchlist" in context else lists.load()
    result = watch.match(mmsi=mmsi, imo=vessel.get("imo"), name=vessel.get("name")) if watch else None
    if result and result["status"] == "listed":
        return [_listed(vessel, mmsi, result, where)]
    if result and result["status"] == "ambiguous":
        names = "; ".join(f"{_who(record)}, {record['tier']}" for record in result["candidates"])
        reason = (f"MMSI {mmsi} is recorded for {len(result['candidates'])} different listed vessels ({names}), and "
                  f"the AIS name does not pick one. Check the IMO before acting. {NO_POINTS}")
        related = {"candidates": [{"imo": r["imo"], "name": r["name"], "tier": r["tier"]} for r in result["candidates"]],
                   "list_date": result["list_date"], "credit": lists.CREDIT}
        return [_finding(vessel, where, "ambiguous", [reason], related)]
    if result and result["status"] == "delisted":
        reason = (f"Was on the {result['tier']} list from {_when(result['since'])} until {_when(result['until'])}; "
                  f"not on the OpenSanctions list of {_when(result['list_date'])}. {NO_POINTS}")
        related = {key: result[key] for key in ("tier", "since", "until", "list_date")}
        return [_finding(vessel, where, "delisted", [reason], {**related, "credit": lists.CREDIT})]
    if lists.unallocated_mid(mmsi):
        reason = (f"MMSI {mmsi} has country code {mmsi[:3]}, which ITU has not allocated: an invalid or made-up "
                  f"number. Check the vessel's identity. {NO_POINTS}")
        return [_finding(vessel, where, "number", [reason], {"mid": mmsi[:3]})]
    return []


detect = watchlist  # the package convention; the function name labels the assessments file
