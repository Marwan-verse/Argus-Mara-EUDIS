"""Draw the latest position of every ship heard in the last hour on a map (writes map.html).

Run:  python recorder/map.py [data/ais] [minutes]
Then open map.html in a browser.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/ais")
minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 60
files = sorted(root.glob("*/*.parquet"), key=lambda f: f.stat().st_mtime)
if not files:
    sys.exit(f"No data in {root} yet. Is the recorder running?")

cutoff = time.time() - (minutes + 10) * 60  # a file covers up to 10 minutes before it is written
recent = [str(f) for f in files if f.stat().st_mtime >= cutoff] or [str(files[-1])]


def recording_rows(paths):
    """Read only display columns, converting at most 4096 rows at a time."""
    columns = ["recv_utc", "msg_type", "mmsi", "ship_name", "lat", "lon", "sog", "cog"]
    for path in paths:
        with pq.ParquetFile(path) as parquet:
            for batch in parquet.iter_batches(batch_size=4096, columns=columns):
                yield from batch.to_pylist()


names, latest = {}, {}
for r in recording_rows(recent):
    if r["ship_name"]:
        names[r["mmsi"]] = r["ship_name"]
    lat, lon = r["lat"], r["lon"]
    # AIS uses 91 / 181 for "position not available"
    if r["msg_type"] not in POSITION_TYPES or lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        continue
    if r["mmsi"] not in latest or r["recv_utc"] > latest[r["mmsi"]]["recv_utc"]:
        latest[r["mmsi"]] = r

ships = [{
    "mmsi": mmsi,
    "name": names.get(mmsi, ""),
    "lat": round(r["lat"], 5),
    "lon": round(r["lon"], 5),
    "sog": r["sog"] if r["sog"] is not None and r["sog"] < 102.2 else None,  # 102.3 = not available
    "cog": r["cog"] if r["cog"] is not None and r["cog"] < 360 else None,      # 360 = not available
    "seen": f"{r['recv_utc']:%H:%M} UTC",
    "received_utc": r["recv_utc"].isoformat(),
} for mmsi, r in latest.items()]

# Embed the compiled Svelte UI and reference geometry: the preview works offline.
REPO = Path(__file__).resolve().parents[1]
payload = {
    "ships": ships,
    "generated": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
    "assets": {
        "land": json.loads((REPO / "ui/assets/world_land.json").read_text()),
        "ports": {"ports": []},
    },
}
# Radio-broadcast names must never terminate the inert JSON script element.
data = json.dumps(payload).replace("<", "\\u003c")
styles = (REPO / "ui/live/live.css").read_text(encoding="utf-8")
bundle = (REPO / "ui/recorder.js").read_text(encoding="utf-8")
page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Argus Mara · recorded AIS</title><style>" + styles + "</style></head>"
        "<body><div id=\"app\"></div><script type=\"application/json\" id=\"recorded-data\">"
        + data + "</script><script>" + bundle + "</script></body></html>")
out = Path("map.html")
out.write_text(page, encoding="utf-8")
print(f"{len(ships)} ships -> {out.resolve()} (open it in a browser)")
