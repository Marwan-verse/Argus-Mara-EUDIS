#!/usr/bin/env python3
"""Refresh the two Kp snapshots saved in the repository (argus/snapshots/).

* kp_recent.json: the last days of Kp, NOAA SWPC (GFZ Potsdam if NOAA fails).
* kp_storm_2024-05.json: definitive GFZ Kp for the real storm of 10-11 May 2024 (G5).

Both are real open data with their source, link, licence and retrieval time. The app reads them
only when it has no live data. A source that fails leaves its old snapshot untouched.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus import space_weather  # noqa: E402


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    top = max(data["kp"], key=lambda row: row["kp"])
    print(f"{path.relative_to(ROOT)}: {len(data['kp'])} values from {data['source']} "
          f"({data['kp'][0]['t']} to {data['kp'][-1]['t']}, max Kp {space_weather.kp_text(top['kp'])} at {top['t']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=("recent", "storm"), help="refresh one snapshot")
    args = parser.parse_args()
    jobs = {"recent": (space_weather.RECENT_SNAPSHOT, lambda: space_weather.fetch_recent(timeout=20)),
            "storm": (space_weather.STORM_SNAPSHOT, space_weather.fetch_storm_2024)}
    failed = 0
    for name, (path, fetch) in jobs.items():
        if args.only and name != args.only:
            continue
        try:
            save(path, fetch())
        except Exception as error:  # report and keep the old snapshot
            failed += 1
            print(f"{name}: fetch failed ({type(error).__name__}: {error}); kept {path.relative_to(ROOT)}",
                  file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
