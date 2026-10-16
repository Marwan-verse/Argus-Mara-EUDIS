"""Download the detailed base maps for Irish waters ahead of time, so the demo runs without Wi-Fi.

Usage: python scripts/prefetch_map_tiles.py                     # both maps, zoom 5-10, about 3,400 tiles
       python scripts/prefetch_map_tiles.py --max-zoom 12 --bbox 53.0,-6.6,53.7,-5.8   # Dublin Bay in detail
       python scripts/prefetch_map_tiles.py --map tactical

Tiles go to the same cache the desktop app reads (~/.cache/ArgusMara/map-tiles, or
%LOCALAPPDATA%\\ArgusMara\\map-tiles on Windows). Tiles already on disk are skipped.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import desktop_basemap  # noqa: E402
from run_gui import tile_cache_root  # noqa: E402

IRISH_WATERS = (49.5, -16.0, 56.5, -4.0)  # south, west, north, east
MAPS = {"tactical": desktop_basemap.TACTICAL_MAP, "satellite": desktop_basemap.HD_IMAGERY}


def tile_range(south: float, west: float, north: float, east: float, z: int):
    def tile(lat, lon):
        n = 2 ** z
        x = int((lon + 180) / 360 * n)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
        return min(n - 1, max(0, x)), min(n - 1, max(0, y))
    x0, y0 = tile(north, west)
    x1, y1 = tile(south, east)
    return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def fetch(source, key) -> str:
    path = desktop_basemap.tile_path(tile_cache_root(), source, key)
    if path.exists():
        return "cached"
    data = desktop_basemap.fetch_tile(source, *key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".tmp").write_bytes(data)
    path.with_suffix(".tmp").replace(path)
    return "downloaded"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", choices=("both", *MAPS), default="both")
    parser.add_argument("--min-zoom", type=int, default=5)
    parser.add_argument("--max-zoom", type=int, default=10)
    parser.add_argument("--bbox", help="south,west,north,east in degrees (default: Irish waters)")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(",")) if args.bbox else IRISH_WATERS
    names = MAPS.values() if args.map == "both" else [MAPS[args.map]]
    jobs = []
    for name in names:
        source = desktop_basemap.SOURCES[name]
        for z in range(args.min_zoom, min(args.max_zoom, source.max_zoom) + 1):
            jobs.extend((source, key) for key in tile_range(*bbox, z))
    print(f"{len(jobs)} tiles to check · cache {tile_cache_root().parent}")
    counts = {"cached": 0, "downloaded": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, source, key): (source, key) for source, key in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                counts[future.result()] += 1
            except Exception as error:
                counts["failed"] += 1
                source, key = futures[future]
                print(f"  failed {source.id} {key}: {error}")
            if done % 200 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} · {counts['downloaded']} new · {counts['cached']} already cached · {counts['failed']} failed")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
