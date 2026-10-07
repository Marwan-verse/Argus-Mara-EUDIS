#!/usr/bin/env python3
"""Check the two JSON files used by every Argus Mara workstream."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from argus.contracts import validate_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=ROOT / "demo/scenario.json")
    parser.add_argument("--alerts", type=Path, default=ROOT / "demo/alerts.json")
    args = parser.parse_args()
    try:
        vessels, alerts = validate_files(args.scenario, args.alerts)
    except (OSError, ValueError) as error:
        print(f"Contract check failed: {error}", file=sys.stderr)
        return 1
    print(f"Contract OK: {vessels} vessel(s), {alerts} alert(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
