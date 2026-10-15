"""Ports, anchorages and declared destinations for the Brain detectors.

Port points come from the two bundled reference files: Ireland's Marine Atlas
(``ui/assets/irish_ports.json``) and the NGA World Port Index
(``ui/assets/world_ports.json``). Both are catalogue locations, not berths.
The rough anchorages below are design choices, not charted limits. A scenario
can add its own as ``context["ports"]`` (dicts with ``name``, ``lat``, ``lon``)
and ``context["anchorages"]`` (dicts with ``name``, ``lat``, ``lon``,
``radius_nm``).

A declared destination is free text typed by the crew (AIS message 5). It is
resolved to a port only when the text names one plainly: a UN/LOCODE from the
short list below or a port name in the reference files. Anything else stays
unresolved, and no detector guesses.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from argus.countdown import nm_between

ROOT = Path(__file__).resolve().parents[2]
PORT_FILES = (ROOT / "ui/assets/irish_ports.json", ROOT / "ui/assets/world_ports.json")
GRID_DEG = 0.5  # port lookup cells

# Rough designated anchorage areas where waiting is expected (assumptions, not charted limits).
ANCHORAGES = (
    {"name": "Dublin Bay anchorage", "lat": 53.33, "lon": -6.07, "radius_nm": 2.5},
    {"name": "Cork Harbour outer anchorage", "lat": 51.76, "lon": -8.25, "radius_nm": 2.5},
    {"name": "Shannon Estuary anchorage", "lat": 52.58, "lon": -9.50, "radius_nm": 3.0},
    {"name": "Waterford Harbour anchorage", "lat": 52.17, "lon": -6.95, "radius_nm": 1.5},
)

# UN/LOCODEs often typed as AIS destinations around Ireland: a short hand list, not the full code list.
LOCODES = {
    "IEDUB": "Dublin", "IEORK": "Cork", "IEROS": "Rosslare", "IEWAT": "Waterford", "IEDRO": "Drogheda",
    "IEFOY": "Foynes", "IEGWY": "Galway", "GBHLY": "Holyhead", "GBLIV": "Liverpool", "GBHYM": "Heysham",
    "GBBEL": "Belfast", "IMDGS": "Douglas", "FRCER": "Cherbourg", "FRROS": "Roscoff",
}
# Words that do not tell ports apart in a name ("Dover Harbor" is "Dover").
NAME_NOISE = {"PORT", "HARBOR", "HARBOUR", "OF", "THE"}


def normalise(text: str) -> str:
    """Upper case ASCII words: accents dropped, punctuation and noise words removed."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.sub(r"[^A-Z0-9]+", " ", ascii_text.upper()).split()
    return " ".join(word for word in words if word not in NAME_NOISE)


@lru_cache(maxsize=1)
def reference_ports() -> tuple[tuple[str, float, float, str], ...]:
    """(name, lat, lon, country code) for every port in the bundled reference files."""
    ports = []
    for path in PORT_FILES:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))["ports"]
        except (OSError, ValueError, KeyError):
            continue
        ports.extend((str(row[1]), float(row[2]), float(row[3]), str(row[4])) for row in rows)
    return tuple(ports)


def _cell(value: float) -> int:
    return int(value // GRID_DEG)


@lru_cache(maxsize=1)
def _grid() -> dict:
    grid: dict[tuple[int, int], list] = {}
    for port in reference_ports():
        grid.setdefault((_cell(port[1]), _cell(port[2])), []).append(port)
    return grid


@lru_cache(maxsize=1)
def _by_name() -> dict:
    names: dict[str, list] = {}
    for port in reference_ports():
        names.setdefault(normalise(port[0]), []).append(port)
    return names


def nearest_port(lat: float, lon: float, extra=()) -> tuple[str, float] | None:
    """(name, nm) of the nearest port in the neighbouring 0.5° cells, from the reference files and ``extra``.

    The cells reach at least 18 nm at Irish latitudes; None means no port that close.
    """
    row, col = _cell(lat), _cell(lon)
    near = [port for r in (row - 1, row, row + 1) for c in (col - 1, col, col + 1) for port in _grid().get((r, c), ())]
    near += [(port.get("name", "port"), port["lat"], port["lon"], "") for port in extra or ()]
    found = min(((name, nm_between(lat, lon, p_lat, p_lon)) for name, p_lat, p_lon, _cc in near),
                key=lambda pair: pair[1], default=None)
    return found


def anchorage_at(lat: float, lon: float, margin_nm: float = 0.0, extra=()) -> dict | None:
    """The anchorage the position lies in (or within ``margin_nm`` of), else None."""
    for area in (*ANCHORAGES, *(extra or ())):
        if nm_between(lat, lon, area["lat"], area["lon"]) <= area.get("radius_nm", 0) + margin_nm:
            return area
    return None


def resolve_destination(text, lat: float, lon: float) -> dict | None:
    """The port a declared destination names, as {name, lat, lon, country, how}, or None.

    "FROM>TO" text keeps the part after the last ">". A UN/LOCODE from the
    short list wins; otherwise the whole text must equal a port's name. When
    two ports share the name, the one nearest the vessel is taken.
    """
    if not text or not str(text).strip():
        return None
    target = str(text).split(">")[-1]
    compact = re.sub(r"[^A-Z]", "", target.upper())
    candidates, how = [], ""
    if compact in LOCODES:
        name, country = LOCODES[compact], compact[:2]
        candidates = [port for port in _by_name().get(normalise(name), []) if port[3] == country]
        how = f"UN/LOCODE {compact}"
    if not candidates:
        candidates, how = _by_name().get(normalise(target), []), "port name"
    if not candidates:
        return None
    name, p_lat, p_lon, country = min(candidates, key=lambda port: nm_between(lat, lon, port[1], port[2]))
    return {"name": name, "lat": p_lat, "lon": p_lon, "country": country, "how": how}
