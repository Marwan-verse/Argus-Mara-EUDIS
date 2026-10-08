"""Prepare the local display geometry from Natural Earth's public-domain countries.

Raw download stays in data/maps/countries.geojson. This is a display asset,
not a navigational chart, surveyed cable route or bathymetry layer.
"""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/maps/countries.geojson"
TARGET = ROOT / "ui/assets/coastline.json"


def simplify(points, tolerance=0.002):
    if len(points) <= 2:
        return points
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    distances = []
    for p in points[1:-1]:
        fraction = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length)) if length else 0
        distances.append(math.hypot(p[0] - a[0] - fraction * dx, p[1] - a[1] - fraction * dy))
    maximum = max(distances, default=0)
    if maximum <= tolerance:
        return [a, b]
    index = distances.index(maximum) + 1
    return simplify(points[:index + 1], tolerance)[:-1] + simplify(points[index:], tolerance)


def main():
    raw = SOURCE.read_bytes()
    data = json.loads(raw)
    rings = []
    for feature in data["features"]:
        if feature["properties"].get("ADMIN") not in {"Ireland", "United Kingdom"}:
            continue
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for polygon in polygons:
            ring = polygon[0]
            if max(p[0] for p in ring) < -11 or min(p[0] for p in ring) > 2 or max(p[1] for p in ring) < 49 or min(p[1] for p in ring) > 59:
                continue
            rings.append([[round(x, 5), round(y, 5)] for x, y in simplify(ring)])
    result = {"label": "real", "source": "Natural Earth 1:10m admin-0 countries", "licence": "public domain",
              "source_url": "https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_10m_admin_0_countries.geojson",
              "source_sha256": hashlib.sha256(raw).hexdigest(), "coordinate_order": "lon,lat",
              "caveat": "Simplified display geometry; not for navigation.", "rings": rings}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Prepared {len(rings)} local coastline rings -> {TARGET}")


if __name__ == "__main__":
    main()
