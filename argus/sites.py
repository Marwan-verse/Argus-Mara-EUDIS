"""Sensitive coastal sites and two AIS behaviour detectors for the alert levels.

``stopped_minutes`` finds a vessel stopped away from every port and designated
anchorage; ``loiter_hours`` finds one staying inside the protection zone around a
site. ``observe`` turns a timed track into observations for ``argus.levels.assess``.

Site positions are approximate public locations: line landfalls follow the
illustrative routes in ``argus.alert_board``, and the zones are design choices.
Anchorages are rough areas, not charted limits. Nothing here is a surveyed position.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from argus.countdown import nm_between, step

ROOT = Path(__file__).resolve().parents[1]

# id: (name, asset class, lat, lon, zone radius nm). Approximate public locations.
SITES = {
    "haulbowline": ("Haulbowline naval base", "naval_base", 51.837, -8.300, 1.0),
    "rush-landfall": ("EWIC landfall, Rush", "landfall", 53.52, -6.08, 2.0),
    "baginbun-landfall": ("Greenlink landfall, Baginbun", "landfall", 52.17, -6.83, 2.0),
    "gormanston-landfall": ("IC2 gas landfall, Gormanston", "landfall", 53.64, -6.21, 2.0),
    "killala-landfall": ("Transatlantic cable landfall, Killala Bay", "landfall", 54.22, -9.22, 2.0),
    "arklow-bank": ("Arklow Bank offshore wind farm", "wind_farm", 52.79, -5.94, 2.0),
}

# (name, lat, lon, radius nm): rough designated anchorage areas where waiting is expected.
ANCHORAGES = [
    ("Dublin Bay anchorage", 53.33, -6.07, 2.5),
    ("Cork Harbour outer anchorage", 51.76, -8.25, 2.5),
    ("Shannon Estuary anchorage", 52.58, -9.50, 3.0),
    ("Waterford Harbour anchorage", 52.17, -6.95, 1.5),
]

PORT_NM = 3.0          # a stop closer than this to a port or anchorage edge is expected
STOP_KN = 0.5          # at or below this speed the vessel counts as stopped
MAX_FIX_GAP_S = 1800   # a longer reception gap ends a stretch; nothing is assumed across it


def load_ports(paths=(ROOT / "ui/assets/irish_ports.json", ROOT / "ui/assets/world_ports.json")) -> list[tuple]:
    """(name, lat, lon) for every port in the bundled reference files."""
    ports = []
    for path in paths:
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))["ports"]
        except (OSError, ValueError, KeyError):
            continue
        ports.extend((row[1], row[2], row[3]) for row in rows)
    return ports


def zone_path(site_id: str, points: int = 36) -> list[tuple[float, float]]:
    """A closed ring around the site at its zone radius, for drawing."""
    _name, _kind, lat, lon, radius = SITES[site_id]
    return [step(lat, lon, index * 360 / points, radius) for index in range(points + 1)]


def nearest_site(lat: float, lon: float) -> tuple[str, float]:
    """The closest site and its distance in nm from its centre."""
    return min(((site_id, nm_between(lat, lon, site[2], site[3])) for site_id, site in SITES.items()),
               key=lambda pair: pair[1])


def near_port(lat: float, lon: float, ports) -> str | None:
    """Name of a port or anchorage the position is expected to be waiting at, else None."""
    for name, a_lat, a_lon, radius in ANCHORAGES:
        if nm_between(lat, lon, a_lat, a_lon) <= radius + PORT_NM:
            return name
    for name, p_lat, p_lon in ports:
        if abs(lat - p_lat) < 0.2 and nm_between(lat, lon, p_lat, p_lon) <= PORT_NM:
            return name
    return None


def _latest_stretch(fixes, inside) -> list[dict]:
    """The run of fixes ending at the latest one for which ``inside`` holds, unbroken by long gaps."""
    stretch = []
    for fix in reversed(fixes):
        if not inside(fix) or (stretch and stretch[-1]["t"] - fix["t"] > MAX_FIX_GAP_S):
            break
        stretch.append(fix)
    return stretch


def stopped_minutes(fixes, ports, vessel_type: str = "") -> float:
    """Minutes the vessel has been stopped at its latest fix, away from any port or anchorage.

    Fishing vessels are skipped: they stop at sea as part of their work. Returns 0
    when the vessel is moving, near a port or anchorage, or the stop cannot be timed.
    """
    if not fixes or "fish" in vessel_type.lower():
        return 0.0
    stretch = _latest_stretch(fixes, lambda fix: (fix.get("sog_kn") or 0) <= STOP_KN)
    if len(stretch) < 2 or near_port(fixes[-1]["lat"], fixes[-1]["lon"], ports):
        return 0.0
    return (stretch[0]["t"] - stretch[-1]["t"]) / 60


def loiter_hours(fixes, site_id: str) -> float:
    """Hours the vessel has stayed inside the site's zone up to its latest fix.

    A ship crossing a 2 nm zone at 10 kn is inside for about 24 min, so an hour or
    more means it stayed, whatever its speed.
    """
    _name, _kind, lat, lon, radius = SITES[site_id]
    stretch = _latest_stretch(fixes, lambda fix: nm_between(fix["lat"], fix["lon"], lat, lon) <= radius)
    if len(stretch) < 2:
        return 0.0
    return (stretch[0]["t"] - stretch[-1]["t"]) / 3600


def observe(fixes, ports, vessel_type: str = "") -> dict:
    """Observations for ``assess`` from a timed track: the nearest site, zone, loiter and stop."""
    last = fixes[-1]
    site_id, distance = nearest_site(last["lat"], last["lon"])
    radius = SITES[site_id][4]
    observations = {"site_id": site_id, "asset_class": SITES[site_id][1]}
    if distance <= radius:
        observations["in_zone"] = True
    else:
        observations["distance_nm"] = round(distance - radius, 1)
    hours = loiter_hours(fixes, site_id)
    if hours >= 1:
        observations["site_loiter_hours"] = round(hours, 1)
    minutes = stopped_minutes(fixes, ports, vessel_type)
    if minutes >= 30:
        observations["stopped_offport_min"] = round(minutes)
    return observations


def circle_track(lat, lon, radius_nm, hours, speed_kn=3.0, every_s=180) -> list[dict]:
    """A fictional timed track circling a point at ``speed_kn``, for simulated contacts and tests."""
    turn = math.degrees(speed_kn * every_s / 3600 / radius_nm)
    return [{"t": index * every_s, "sog_kn": speed_kn,
             **dict(zip(("lat", "lon"), step(lat, lon, (index * turn) % 360, radius_nm)))}
            for index in range(int(hours * 3600 / every_s) + 1)]


def stop_track(lat, lon, course, minutes, approach_kn=8.0, every_s=180) -> list[dict]:
    """A fictional timed track: 30 min of approach on ``course`` then a stop at the position."""
    approach = [{"t": index * every_s, "sog_kn": approach_kn,
                 **dict(zip(("lat", "lon"), step(lat, lon, (course + 180) % 360,
                                                approach_kn * (1800 - index * every_s) / 3600)))}
                for index in range(1800 // every_s)]
    stop = [{"t": 1800 + index * every_s, "sog_kn": 0.1, "lat": lat, "lon": lon}
            for index in range(int(minutes * 60 / every_s) + 1)]
    return approach + stop
