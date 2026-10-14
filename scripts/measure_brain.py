"""How long Brain takes to score a large fleet: every registered detector, then the level.

Run .venv\\Scripts\\python.exe scripts/measure_brain.py (or --vessels 1000 for a quick check).

All vessels and tracks are generated, explicitly simulated fixtures: straight tracks
around Ireland, most of them far from every line, about 15% near one, some of
those slowing. Track generation is not timed. The lines are the illustrative
routes the replay stories use plus the exercise cable. These are local lab
timings for one process, not a claim about a deployed system or real AIS volume.
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from argus.assemble import DETECTORS, apply_relevance, merge_observations, relevance  # noqa: E402
from argus.brain_board import STORY_LINES  # noqa: E402
from argus.countdown import step  # noqa: E402
from argus.detectors.ais_spoofing import on_land  # noqa: E402
from argus.levels import assess  # noqa: E402

BBOX = (50.5, 56.0, -12.0, -4.5)  # south, north, west, east


def lines() -> list[dict]:
    scenario = json.loads((ROOT / "demo/scenario.json").read_text(encoding="utf-8"))
    return STORY_LINES + scenario["cables"]


def _sea_point(rng: random.Random) -> tuple[float, float]:
    while True:
        lat, lon = rng.uniform(*BBOX[:2]), rng.uniform(*BBOX[2:])
        if not on_land(lat, lon):
            return lat, lon


def _near_line(rng: random.Random, cables: list[dict]) -> tuple[float, float]:
    path = rng.choice(cables)["path"]
    index = rng.randrange(len(path) - 1)
    share = rng.random()
    (a_lat, a_lon), (b_lat, b_lon) = path[index], path[index + 1]
    lat, lon = a_lat + (b_lat - a_lat) * share, a_lon + (b_lon - a_lon) * share
    return step(lat, lon, rng.uniform(0, 360), rng.uniform(0, 4))


def _at_sea(lat: float, lon: float, course: float, cruise: float, minutes: int) -> bool:
    """Start, middle and end of the straight track are at sea (a ship does not sail across Ireland)."""
    return all(not on_land(*step(lat, lon, course, cruise * minutes / 60 * share)) for share in (0, 0.5, 1))


def make_vessel(index: int, cables: list[dict], minutes: int, interval_s: int, seed: int) -> dict:
    rng = random.Random(seed * 1_000_003 + index)
    near = rng.random() < 0.15
    while True:
        lat, lon = _near_line(rng, cables) if near else _sea_point(rng)
        course, cruise = rng.uniform(0, 360), rng.uniform(6, 18)
        lat, lon = step(lat, lon, course + 180, cruise * minutes / 60 * 0.5)  # centre the track on the point
        if _at_sea(lat, lon, course, cruise, minutes):
            break
    slow_from = rng.randrange(minutes // 2, minutes) if near and rng.random() < 0.3 else None
    track, t = [], 0
    for minute in range(0, minutes * 60 // interval_s):
        sog = cruise * 0.7 if slow_from is not None and minute * interval_s >= slow_from * 60 else cruise
        track.append({"t": t, "lat": lat, "lon": lon, "sog_kn": round(sog, 1), "cog_deg": round(course, 1)})
        lat, lon = step(lat, lon, course, sog * interval_s / 3600)
        t += interval_s
    return {"mmsi": 900_000_000 + index, "name": f"SIM {index}", "ship_type": rng.choice([70, 80, 60, 30, 37]),
            "ais_class": "A", "ais_length_m": rng.choice([24, 90, 180, 250]), "track": track, "label": "simulated"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vessels", type=int, default=15_000)
    parser.add_argument("--minutes", type=int, default=180, help="track length per vessel")
    parser.add_argument("--interval", type=int, default=60, help="seconds between fixes")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    cables = lines()
    per_detector, levels = Counter(), Counter()
    scoring_s = findings_total = 0.0
    for index in range(args.vessels):
        vessel = make_vessel(index, cables, args.minutes, args.interval, args.seed)
        context = {"now": vessel["track"][-1]["t"], "cables": cables, "detections": [], "assets": []}
        started = perf_counter()
        findings = []
        for detector in DETECTORS:
            mark = perf_counter()
            findings.extend(detector(vessel, context))
            per_detector[detector.__name__] += perf_counter() - mark
        observations = merge_observations(findings)
        assessment = apply_relevance(assess(observations), relevance(vessel, observations))
        scoring_s += perf_counter() - started
        findings_total += len(findings)
        levels[assessment["level"]] += 1

    print(f"Simulated fleet: {args.vessels} vessels, {args.minutes} min of fixes every {args.interval} s, "
          f"{len(cables)} lines")
    print(f"Brain scoring: {scoring_s:.2f} s total, {scoring_s / args.vessels * 1000:.2f} ms per vessel")
    for name, seconds in per_detector.most_common():
        print(f"  {name:18} {seconds:7.2f} s  ({seconds / args.vessels * 1000:.2f} ms per vessel)")
    print(f"Findings: {int(findings_total)}; levels: "
          + ", ".join(f"{level} {levels[level]}" for level in ("none", "low", "medium", "high", "critical")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
