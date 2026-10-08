"""Build compact offline display layers; keep source downloads in ignored data/maps/.

Run ``python scripts/prepare_world_map.py --fetch`` to refresh the source snapshot.
The historical TeleGeography layer is CC BY-NC-SA 3.0 and display only. Its
stylized routes must never be used as surveyed cable positions or alert inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "maps"
ASSETS = ROOT / "ui" / "assets"
NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
WPI = "https://fgmod.nga.mil/nauticalpubs-feature/rest/services/WPI/World_Port_Index_Viewer/MapServer/0/query"
CABLES = "https://raw.githubusercontent.com/yvonne-lo/submarinecablemap/master/public/api/v2/cable/cable-geo.json"
USER_AGENT = "ArgusMaraDataPrep/0.1 (offline map asset preparation)"


def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=45) as response:
        return response.read()


def source_bytes(name: str, url: str, refresh: bool) -> bytes:
    path = RAW / name
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        data = fetch(url)
        path.write_bytes(data)
    return path.read_bytes()


def simplify(points: list, tolerance: float) -> list:
    """Iterative Ramer-Douglas-Peucker, preserving closed exterior rings."""
    if len(points) <= 3:
        return points
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        squared = dx * dx + dy * dy
        farthest, index = -1.0, None
        for i in range(first + 1, last):
            px, py = points[i]
            fraction = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / squared)) if squared else 0
            distance = math.hypot(px - ax - fraction * dx, py - ay - fraction * dy)
            if distance > farthest:
                farthest, index = distance, i
        if farthest > tolerance and index is not None:
            keep.add(index)
            pending.extend(((first, index), (index, last)))
    return [points[i] for i in sorted(keep)]


def point(lon: float, lat: float) -> list[float]:
    return [round(lon, 4), round(lat, 4)]


def write_asset(name: str, value: dict) -> None:
    target = ASSETS / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{target.relative_to(ROOT)}: {value['count']} features")


def build_land(refresh: bool) -> None:
    levels = {}
    hashes = {}
    for scale, tolerance in (("110m", 0.1), ("50m", 0.025)):
        name = f"ne_{scale}_admin_0_countries.geojson"
        raw = source_bytes(name, NATURAL_EARTH + name, refresh)
        hashes[scale] = hashlib.sha256(raw).hexdigest()
        features = json.loads(raw)["features"]
        rings = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            kind = geometry.get("type")
            polygons = geometry.get("coordinates", []) if kind == "MultiPolygon" else [geometry.get("coordinates", [])] if kind == "Polygon" else []
            for polygon in polygons:
                if not polygon or len(polygon[0]) < 4:
                    continue
                exterior = simplify(polygon[0], tolerance)
                if len(exterior) >= 4:
                    rings.append([point(lon, lat) for lon, lat in exterior])
        levels[scale] = rings
    write_asset("world_land.json", {
        "label": "real", "source": "Natural Earth admin-0 countries", "licence": "public domain",
        "source_url": "https://github.com/nvkelso/natural-earth-vector/tree/master/geojson",
        "source_sha256": hashes, "coordinate_order": "lon,lat",
        "caveat": "Simplified land display only; not a navigational chart.",
        "count": sum(map(len, levels.values())), "levels": levels,
    })


def build_ports(refresh: bool) -> None:
    path = RAW / "wpi_ports.json"
    if refresh or not path.exists():
        records = []
        for offset in range(0, 100000, 3000):
            query = urlencode({
                "where": "1=1", "outFields": "objectid,wpinumber,main_port_name,wpi_cc",
                "returnGeometry": "true", "outSR": "4326", "orderByFields": "objectid ASC",
                "resultOffset": str(offset), "resultRecordCount": "3000", "f": "json",
            })
            page = json.loads(fetch(WPI + "?" + query))
            if "error" in page:
                raise ValueError(f"NGA port query failed: {page['error']}")
            records.extend(page["features"])
            if len(page["features"]) < 3000:
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, separators=(",", ":")), encoding="utf-8")
    raw = path.read_bytes()
    features = json.loads(raw)
    seen = set()
    ports = []
    for feature in features:
        a, g = feature.get("attributes") or {}, feature.get("geometry") or {}
        name, number = a.get("main_port_name"), a.get("wpinumber")
        lon, lat = g.get("x"), g.get("y")
        if not name or number is None or lon is None or lat is None:
            continue
        if not (-180 <= lon <= 180 and -85.0511 <= lat <= 85.0511):
            continue
        if int(number) in seen:
            continue
        seen.add(int(number))
        ports.append([int(number), name, round(lat, 5), round(lon, 5), a.get("wpi_cc") or ""])
    if len(ports) < 3000:
        raise ValueError("The World Port Index download is unexpectedly incomplete")
    write_asset("world_ports.json", {
        "label": "real", "source": "NGA World Port Index Viewer", "licence": "US government public data",
        "source_url": WPI.rsplit("/query", 1)[0],
        "source_sha256": hashlib.sha256(raw).hexdigest(), "coordinate_order": "wpi,name,lat,lon,country_code",
        "caveat": "Port positions are reference locations, not precise berths or navigation fixes.",
        "count": len(ports), "ports": ports,
    })


def build_cables(refresh: bool) -> None:
    raw = source_bytes("cable-geo-v2.json", CABLES, refresh)
    data = json.loads(raw)
    cables = []
    for feature in data["features"]:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "MultiLineString":
            continue
        segments = []
        for line in geometry.get("coordinates", []):
            if len(line) < 2:
                continue
            simplified = simplify(line, 0.02)
            segments.append([point(lon, lat) for lon, lat in simplified])
        if segments:
            props = feature.get("properties") or {}
            cables.append({"name": props.get("name") or "Unnamed cable", "segments": segments})
    write_asset("world_cables.json", {
        "label": "reconstructed", "source": "TeleGeography Submarine Cable Map, historical v2 snapshot",
        "licence": "CC BY-NC-SA 3.0", "source_url": CABLES,
        "source_sha256": hashlib.sha256(raw).hexdigest(), "coordinate_order": "lon,lat",
        "caveat": "Stylized cable routes, including planned systems; not surveyed locations. Noncommercial display only. Never use for proximity alerts.",
        "count": len(cables), "cables": cables,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="refresh ignored raw downloads before rebuilding")
    args = parser.parse_args()
    build_land(args.fetch)
    build_ports(args.fetch)
    build_cables(args.fetch)


if __name__ == "__main__":
    main()
