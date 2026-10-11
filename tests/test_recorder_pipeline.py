"""Simulated recording fixtures: bounded reads preserve handoff/map semantics."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from argus.ingest.ais import import_file, normalise_rows
from recorder.recorder import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 10, 11, tzinfo=timezone.utc)


def fixture(index=0, **changes):
    return {"recv_utc": START + timedelta(seconds=index), "msg_type": "PositionReport",
            "mmsi": 999000001, "ship_name": "SIMULATED TEST", "lat": 53., "lon": -6.,
            "sog": 0., "cog": 0., "time_utc": None,
            "raw": "PRIVATE SIMULATED TEST NOT EXPORTED", **changes}


class RecorderPipelineTests(unittest.TestCase):
    def test_parquet_handoff_preserves_quality_and_duplicate_across_batch_boundary(self):
        rows = [fixture(index) for index in range(5000)]
        rows.extend([fixture(), fixture(msg_type="ShipStaticData")])
        expected = normalise_rows(rows, "simulated", "recorder")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), source, row_group_size=1500)
            actual = import_file(source, "simulated", "recorder")
        actual.pop("source")
        self.assertEqual(actual, expected)
        self.assertEqual(actual["quality"]["duplicates_removed"], 1)
        self.assertNotIn("PRIVATE SIMULATED", json.dumps(actual))

    def test_conflicting_fix_across_batches_keeps_global_row_number(self):
        rows = [fixture(index) for index in range(4096)] + [fixture(lon=-5.)]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), source)
            with self.assertRaisesRegex(ValueError, "AIS row 4098: conflicting AIS fixes"):
                import_file(source, "simulated", "recorder")

    def test_map_keeps_latest_received_fix_and_static_name_across_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "recording" / "2026-10-11"
            folder.mkdir(parents=True)
            first, second = folder / "first.parquet", folder / "second.parquet"
            rows = [fixture(index) for index in range(5000)]
            rows[-1] = fixture(5000, lat=54., lon=-7.)
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), first)
            pq.write_table(pa.Table.from_pylist([
                fixture(1, lat=52., lon=-5.),  # Older fix in a later file.
                fixture(5001, msg_type="ShipStaticData", ship_name="SIMULATED RENAMED", lat=None, lon=None),
                fixture(5002, mmsi=999000002, lat=91.),  # AIS unavailable position.
            ], schema=SCHEMA), second)
            os.utime(first, (first.stat().st_mtime - 1, first.stat().st_mtime - 1))
            result = subprocess.run([sys.executable, str(ROOT / "recorder/map.py"), str(folder.parent)],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            html = (root / "map.html").read_text()
        data = json.loads(re.search(r'<script type="application/json" id="recorded-data">(.*?)</script>', html, re.S)[1])
        self.assertEqual(len(data["ships"]), 1)
        ship = data["ships"][0]
        self.assertEqual((ship["lat"], ship["lon"], ship["name"]), (54., -7., "SIMULATED RENAMED"))
        self.assertEqual(ship["received_utc"], (START + timedelta(seconds=5000)).isoformat())
        self.assertEqual((ship["sog"], ship["cog"]), (0., 0.))
        self.assertNotIn("PRIVATE SIMULATED TEST NOT EXPORTED", html)


if __name__ == "__main__":
    unittest.main()
