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
table = pq.read_table(recent, columns=["recv_utc", "msg_type", "mmsi", "ship_name", "lat", "lon", "sog", "cog"])

names, latest = {}, {}
for r in table.to_pylist():
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
} for mmsi, r in latest.items()]

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Argus Mara · ships around Ireland</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}
#info{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;padding:8px 12px;
border-radius:6px;font:14px system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)}</style>
</head><body><div id="map"></div><div id="info"></div>
<script>
const ships = __DATA__;
// Ship names come from radio broadcasts anyone can send, so escape them before showing.
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const map = L.map("map").setView([53.4, -8.0], 6);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
for (const s of ships) {
  const slow = s.sog !== null && s.sog < 3;
  L.circleMarker([s.lat, s.lon], {radius: 4, weight: 1, color: slow ? "#c2410c" : "#1d4ed8", fillOpacity: 0.8})
    .bindPopup(`<b>${esc(s.name) || "(no name)"}</b><br>MMSI ${esc(s.mmsi)}<br>` +
               `${s.sog ?? "?"} kn · ${s.cog ?? "?"}°<br>seen ${esc(s.seen)}`)
    .addTo(map);
}
document.getElementById("info").textContent =
  `${ships.length} ships · generated __TIME__ · orange = slower than 3 kn`;
</script></body></html>
"""

out = Path("map.html")
data = json.dumps(ships).replace("</", "<\\/")
out.write_text(PAGE.replace("__DATA__", data).replace("__TIME__", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"),
               encoding="utf-8")
print(f"{len(ships)} ships → {out.resolve()} (open it in a browser)")
