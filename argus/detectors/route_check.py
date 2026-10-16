"""Is the vessel heading towards the destination it declares in AIS? (rule C3)

AIS Message 5 carries a destination the crew types by hand. This detector reads
it as a port: a UN/LOCODE from the short table below, or a port name in the
bundled Irish port list and World Port Index. It then compares the last 30
minutes of the track with the straight line to that port. A ship that is under
way, has covered real ground and has moved away from its declared port (the
distance grew and its course points more than 90 degrees off the port) gets
``route_inconsistent``, which ``argus.levels`` scores as C3 (+1, context group).

The straight line is a fair test only where it stays at sea. If it crosses land
the ship has to go round, so the check is skipped. It is also skipped close to
the port (ships manoeuvre there), shortly after leaving the declared port (the
destination is often not yet updated), and for blank, unknown or "FOR ORDERS"
style text: a destination is never guessed. Every threshold is a team
assumption. The finding says "for review": an out-of-date destination is the
most common innocent explanation, so C3 only adds to other cues.
"""

from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
import re
from statistics import median
import unicodedata

from argus.countdown import nm_between
from argus.detectors.ais_spoofing import clean_track, on_land

ROOT = Path(__file__).resolve().parents[2]
PORT_FILES = ((ROOT / "ui/assets/irish_ports.json", "Irish port list"),
              (ROOT / "ui/assets/world_ports.json", "World Port Index"))

DETECTOR = "route_check"

# Thresholds (assumptions).
WINDOW_S = 30 * 60  # the recent track that is compared with the line to the port
MIN_SPAN_S = 20 * 60  # the window must really cover this long
MIN_FIXES = 4
UNDER_WAY_KN = 4.0  # median speed in the window; slower ships may be waiting or drifting
MIN_TRAVEL_NM = 3.0  # it must have covered real ground
AWAY_DEG = 90.0  # course more than this off the bearing to the port...
MIN_RECEDE_NM = 1.0  # ...and the distance to the port grew at least this much
NEAR_PORT_NM = 10.0  # inside this a ship manoeuvres, waits for a pilot or anchors
DEPARTED_S, DEPARTED_NM = 6 * 3600, 5.0  # left the declared port recently: destination likely not updated
LAND_STEP_NM = 2.0  # spacing of the land check along the line to the port
LAND_SKIP_NM = 5.0  # port points often lie inside a harbour or river; ignore land this close to them
MAX_LAND_SAMPLES = 250

# Text that names no single port.
NOT_A_PORT = {"", "FOR ORDERS", "ORDERS", "TBA", "TBC", "TBN", "UNKNOWN", "NONE", "NIL", "NA", "N A", "SEA", "AT SEA",
              "FISHING", "FISHING GROUND", "FISHING GROUNDS", "TRIALS", "SEA TRIALS", "PATROL", "SAR", "OFFSHORE",
              "ANCHORAGE", "ANCHOR", "WAITING", "STANDBY"}
# UN/LOCODEs for ports these waters see often: code -> (country, port name in the bundled lists).
LOCODES = {
    "IEDUB": ("IE", "Dublin"), "IEORK": ("IE", "Cork"), "IEROS": ("IE", "Rosslare"),
    "IEWAT": ("IE", "Waterford"), "IEGWY": ("IE", "Galway"), "IEFOV": ("IE", "Foynes"),
    "IELMK": ("IE", "Limerick"), "IEDRO": ("IE", "Drogheda"),
    "GBHLY": ("GB", "Holyhead"), "GBLIV": ("GB", "Liverpool"), "GBHYM": ("GB", "Heysham"),
    "GBBEL": ("GB", "Belfast"), "GBLAR": ("GB", "Larne"), "GBFIS": ("GB", "Fishguard"),
    "GBMLF": ("GB", "Milford Haven"), "GBGLW": ("GB", "Glasgow"), "GBBRS": ("GB", "Bristol"),
    "GBSOU": ("GB", "Southampton"), "GBFXT": ("GB", "Felixstowe"), "IMDGS": ("IM", "Douglas"),
    "NLRTM": ("NL", "Rotterdam"), "DEHAM": ("DE", "Hamburg"), "FRLEH": ("FR", "Le Havre"),
}


def _norm(text) -> str:
    """Upper-case ASCII words: accents, brackets and punctuation removed, "PORT OF" dropped."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^PORT OF ", "", text)


@lru_cache(maxsize=1)
def _ports() -> dict:
    """Normalised port name -> list of (id, name, lat, lon, country, source). Irish list first."""
    index: dict[str, list] = {}
    for path, source in PORT_FILES:
        for port_id, name, lat, lon, country in json.loads(path.read_text(encoding="utf-8"))["ports"]:
            index.setdefault(_norm(name), []).append((port_id, name, lat, lon, country, source))
    return index


def bearing_deg(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Direction from a to b, 0-360 degrees, on the same local approximation as ``nm_between``."""
    dlon = (b_lon - a_lon) * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.degrees(math.atan2(dlon, b_lat - a_lat)) % 360


def angle_between(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def match_destination(text, near: tuple[float, float] | None = None) -> dict | None:
    """The port a declared AIS destination names, or None when it is blank, generic or unknown.

    "FROM>TO" keeps the last part. A LOCODE must be in ``LOCODES``; a name must
    match a bundled port exactly. Several ports with one name: the nearest to
    ``near`` wins.
    """
    raw = str(text or "").upper()
    part = _norm(raw.split(">")[-1])
    if part in NOT_A_PORT:
        return None
    code = part.replace(" ", "")
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", code) and code in LOCODES:
        country, name = LOCODES[code]
        candidates = [port for port in _ports().get(_norm(name), []) if port[4] == country]
    else:
        candidates = _ports().get(part, [])
    if not candidates:
        return None
    if near is not None:
        candidates = sorted(candidates, key=lambda port: nm_between(near[0], near[1], port[2], port[3]))
    port_id, name, lat, lon, country, source = candidates[0]
    return {"id": port_id, "name": name, "lat": lat, "lon": lon, "country": country, "source": source,
            "text": str(text).strip()}


def line_crosses_land(lat: float, lon: float, port: dict) -> bool:
    """Whether the straight line to the port passes over land away from both ends."""
    total = nm_between(lat, lon, port["lat"], port["lon"])
    samples = min(MAX_LAND_SAMPLES, int(total / LAND_STEP_NM))
    for index in range(1, samples):
        share = index / samples
        here = share * total
        if here < 1.0 or total - here < LAND_SKIP_NM:
            continue
        if on_land(lat + share * (port["lat"] - lat), lon + share * (port["lon"] - lon)):
            return True
    return False


def route_check(vessel: dict, context: dict) -> list[dict]:
    """One finding when the ship has been moving away from its declared port; none otherwise."""
    fixes = clean_track(vessel.get("track") or [], context.get("now"))
    if not fixes or not vessel.get("destination"):
        return []
    last = fixes[-1]
    port = match_destination(vessel["destination"], (last["lat"], last["lon"]))
    if port is None:
        return []
    window = [fix for fix in fixes if fix["t"] >= last["t"] - WINDOW_S]
    first = window[0]
    if len(window) < MIN_FIXES or last["t"] - first["t"] < MIN_SPAN_S:
        return []
    speeds = [fix["sog_kn"] for fix in window if fix.get("sog_kn") is not None]
    if not speeds or median(speeds) < UNDER_WAY_KN:
        return []
    travel = sum(nm_between(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(window, window[1:]))
    start_nm = nm_between(first["lat"], first["lon"], port["lat"], port["lon"])
    now_nm = nm_between(last["lat"], last["lon"], port["lat"], port["lon"])
    if travel < MIN_TRAVEL_NM or now_nm <= NEAR_PORT_NM:
        return []
    if any(nm_between(fix["lat"], fix["lon"], port["lat"], port["lon"]) <= DEPARTED_NM
           for fix in fixes if fix["t"] >= last["t"] - DEPARTED_S):
        return []  # it has just left that port
    course = bearing_deg(first["lat"], first["lon"], last["lat"], last["lon"])
    to_port = bearing_deg(last["lat"], last["lon"], port["lat"], port["lon"])
    receded = now_nm - start_nm
    if angle_between(course, to_port) <= AWAY_DEG or receded < MIN_RECEDE_NM:
        return []
    if line_crosses_land(last["lat"], last["lon"], port):
        return []  # the route has to go round land; a straight line says nothing
    minutes = round((last["t"] - first["t"]) / 60)
    source = f"{port['source']}" + (f" {port['id']}" if port["source"] == "World Port Index" else "")
    reasons = [
        f"Not heading to its declared destination, for review: \"{port['text']}\" is read as {port['name']} "
        f"({port['country']}, {source}), {now_nm:.1f} nm away on bearing {to_port:03.0f}°.",
        f"In the last {minutes} min it covered {travel:.1f} nm on course {course:03.0f}° and got "
        f"{receded:.1f} nm farther from that port.",
        "The straight line to the port stays at sea, so going round land does not explain it. "
        "The destination may simply be out of date, or the ship may be waiting or re-routed.",
    ]
    return [{
        "detector": DETECTOR, "mmsi": vessel["mmsi"], "t": last["t"], "position": [last["lat"], last["lon"]],
        "strength": round(min(1.0, receded / travel), 2), "reasons": reasons,
        "related": {"destination": port["text"], "port": port["name"], "port_country": port["country"],
                    "port_source": port["source"], "port_id": port["id"], "distance_nm": round(now_nm, 1),
                    "bearing_to_port_deg": round(to_port), "course_deg": round(course),
                    "receded_nm": round(receded, 1), "window_min": minutes},
        "label": vessel.get("label", "simulated"), "obs": {"route_inconsistent": True},
    }]


detect = route_check  # the package convention; the function name labels the assessments file
