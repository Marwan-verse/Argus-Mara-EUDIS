"""Health check for the AIS recorder: is it still writing, and what has it recorded today?

Run:  python recorder/check.py [data/ais]
"""
import sys
import time
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/ais")
files = sorted(root.glob("*/*.parquet"))
if not files:
    sys.exit(f"No data in {root} yet. Is the recorder running? It saves a file every 10 minutes.")

days = sorted({f.parent.name for f in files})
size_mb = sum(f.stat().st_size for f in files) / 1e6
print(f"{len(files)} files · {size_mb:.1f} MB · {len(days)} day(s): {days[0]} … {days[-1]}")

age_min = (time.time() - max(f.stat().st_mtime for f in files)) / 60
status = "OK" if age_min < 20 else "WARNING: nothing new for a while, check that the recorder is running"
print(f"newest file written {age_min:.0f} min ago → {status}")

today = [str(f) for f in files if f.parent.name == days[-1]]
table = pq.read_table(today, columns=["recv_utc", "msg_type", "mmsi"])
span = pc.min_max(table["recv_utc"]).as_py()
ships = pc.count_distinct(table["mmsi"]).as_py()
print(f"{days[-1]}: {table.num_rows:,} messages from {ships:,} ships, "
      f"{span['min']:%H:%M}–{span['max']:%H:%M} UTC")
for row in sorted(table.group_by("msg_type").aggregate([("mmsi", "count")]).to_pylist(),
                  key=lambda r: -r["mmsi_count"]):
    print(f"  {row['msg_type'] or '?':<30} {row['mmsi_count']:>12,}")
