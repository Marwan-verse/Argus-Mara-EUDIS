"""Repeatable local work benchmarks using simulated rows and temporary storage.

Run .venv/bin/python scripts/measure_backend.py. Publish timings exclude journal
I/O; recorder peak memory counts traced Python allocations, not total RSS.
"""
import argparse
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import runpy
from statistics import median
import sys
import tempfile
from time import perf_counter
import tracemalloc
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from argus.brain import detect_vessel
from argus.live_server import Config, LiveService, SERVICE_KEY, health


def timed(function, repeats):
    times = []
    for _ in range(repeats):
        start = perf_counter()
        function()
        times.append((perf_counter() - start) * 1000)
    return round(median(times), 3)


async def live_work(directory, contacts):
    service = LiveService(Config(Path(directory), label="simulated"))
    received = datetime.now(timezone.utc)
    for index in range(contacts):
        upsert = service.state.ingest({
            "recv_utc": received, "msg_type": "PositionReport", "mmsi": 999000000 + index,
            "ship_name": "SIMULATED BENCHMARK", "label": "simulated", "lat": 53., "lon": -6.,
            "sog": 0., "cog": 0., "raw": "{}",
        })
    service.published_ids = {v["mmsi"] for v in service.state.snapshot()["vessels"]}
    publish_times, health_times = [], []
    request = SimpleNamespace(app={SERVICE_KEY: service})
    for _ in range(20):
        service.dirty = {upsert["mmsi"]: upsert}
        start = perf_counter()
        await service.publish()
        publish_times.append((perf_counter() - start) * 1000)
        start = perf_counter()
        await health(request)
        health_times.append((perf_counter() - start) * 1000)
    return {"fleet_contacts": contacts, "single_contact_publish_ms": round(median(publish_times), 3),
            "health_response_ms": round(median(health_times), 3)}


def recorder_work(directory, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder = Path(directory) / "recording" / "2026-10-11"
    folder.mkdir(parents=True)
    received = datetime.now(timezone.utc)
    pq.write_table(pa.table({
        "recv_utc": [received + timedelta(milliseconds=index) for index in range(rows)],
        "msg_type": ["PositionReport"] * rows,
        "mmsi": [999000000 + index % 1000 for index in range(rows)],
        "ship_name": ["SIMULATED BENCHMARK"] * rows,
        "lat": [53.] * rows, "lon": [-6.] * rows, "sog": [0.] * rows, "cog": [0.] * rows,
    }), folder / "fixture.parquet")
    original_dir, original_args = Path.cwd(), sys.argv
    try:
        os.chdir(directory)
        sys.argv = [str(ROOT / "recorder/map.py"), str(folder.parent)]
        tracemalloc.start()
        start = perf_counter()
        with redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT / "recorder/map.py"), run_name="__main__")
        elapsed = (perf_counter() - start) * 1000
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sys.argv = original_args
        os.chdir(original_dir)
    return {"input_rows": rows, "export_ms_with_tracing": round(elapsed, 1),
            "peak_python_mib": round(peak / 1024 ** 2, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-fixes", type=int, default=4000)
    parser.add_argument("--contacts", type=int, default=5000)
    parser.add_argument("--rows", type=int, default=100000)
    args = parser.parse_args()
    if min(args.track_fixes, args.contacts, args.rows) < 1 or args.contacts > 5000:
        parser.error("positive counts are required; contacts must be at most 5000")
    vessel = {"mmsi": 999000001, "name": "SIMULATED BENCHMARK", "track": [
        {"t": index * 60, "lat": 53., "lon": -6., "sog_kn": 12., "cog_deg": 0.}
        for index in range(args.track_fixes)]}
    detector = {"track_fixes": args.track_fixes,
                "normal_passage_scan_ms": timed(lambda: detect_vessel(vessel, [], [], [], "A1"), 3)}
    with tempfile.TemporaryDirectory(prefix="argus-backend-benchmark-") as directory:
        result = {"fixture_label": "simulated", "detector": detector,
                  "live": asyncio.run(live_work(directory, args.contacts)),
                  "recorder": recorder_work(directory, args.rows)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
