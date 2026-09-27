"""Argus Mara AIS recorder.

Listens 24/7 to live ship positions around Ireland (public AIS broadcasts,
relayed for free by aisstream.io) and saves them to Parquet files under
data/ais/<date>/.

Run:  AISSTREAM_API_KEY=<your key> python recorder/recorder.py
"""
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import websockets

API_KEY = os.environ.get("AISSTREAM_API_KEY", "").strip()
URL = os.environ.get("ARGUS_AIS_URL", "wss://stream.aisstream.io/v0/stream")
OUT = Path(os.environ.get("ARGUS_AIS_DIR", "data/ais"))
FLUSH_SECONDS = float(os.environ.get("ARGUS_FLUSH_SECONDS", "600"))
FLUSH_ROWS = 50_000

# [[lat_min, lon_min], [lat_max, lon_max]]: Irish waters, the Irish Sea and the western approaches
BOX = [[[49.0, -18.0], [57.5, -4.5]]]
TYPES = [
    "PositionReport",
    "StandardClassBPositionReport",
    "ExtendedClassBPositionReport",
    "ShipStaticData",
    "StaticDataReport",
]

SCHEMA = pa.schema([
    ("recv_utc", pa.timestamp("ms", tz="UTC")),
    ("msg_type", pa.string()),
    ("mmsi", pa.int64()),
    ("ship_name", pa.string()),
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("sog", pa.float64()),
    ("cog", pa.float64()),
    ("heading", pa.float64()),
    ("nav_status", pa.int64()),
    ("time_utc", pa.string()),
    ("raw", pa.string()),  # the full original message, so nothing is lost if parsing changes later
])


class FatalError(Exception):
    """An error retrying cannot fix, such as an invalid API key."""


def _num(value, cast):
    try:
        return None if value is None else cast(value)
    except (TypeError, ValueError):
        return None


def to_row(raw):
    """Turn one aisstream message into a row; the main fields are parsed, the rest stays in `raw`."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    msg = json.loads(raw)
    if "error" in msg:
        text = str(msg["error"])
        if "key" in text.lower():
            raise FatalError(f"aisstream rejected the API key: {text}")
        raise RuntimeError(f"aisstream error: {text}")
    msg_type = msg.get("MessageType")
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(msg_type) or {}
    return {
        "recv_utc": datetime.now(timezone.utc),
        "msg_type": msg_type,
        "mmsi": _num(meta.get("MMSI", body.get("UserID")), int),
        "ship_name": (str(meta.get("ShipName") or "").strip() or None),
        "lat": _num(body.get("Latitude", meta.get("latitude")), float),
        "lon": _num(body.get("Longitude", meta.get("longitude")), float),
        "sog": _num(body.get("Sog"), float),
        "cog": _num(body.get("Cog"), float),
        "heading": _num(body.get("TrueHeading"), float),
        "nav_status": _num(body.get("NavigationalStatus"), int),
        "time_utc": meta.get("time_utc"),
        "raw": raw,
    }


class Buffer:
    """Collects rows in memory and writes them to a new Parquet file every few minutes."""

    def __init__(self):
        self.rows = []
        self.started = time.time()

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= FLUSH_ROWS or time.time() - self.started >= FLUSH_SECONDS:
            self.flush()

    def flush(self):
        if self.rows:
            now = datetime.now(timezone.utc)
            folder = OUT / now.strftime("%Y-%m-%d")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{now:%H%M%S_%f}.parquet"
            tmp = path.with_suffix(".tmp")
            pq.write_table(pa.Table.from_pylist(self.rows, schema=SCHEMA), tmp, compression="zstd")
            tmp.rename(path)  # atomic: readers never see a half-written file
            print(f"{now:%Y-%m-%d %H:%M:%S} UTC  saved {len(self.rows):>6} messages -> {path}", flush=True)
        self.rows = []
        self.started = time.time()


async def stream(buf):
    async with websockets.connect(URL, ping_interval=20, ping_timeout=60) as ws:
        # aisstream expects the subscription within a few seconds of connecting
        await ws.send(json.dumps({"APIKey": API_KEY, "BoundingBoxes": BOX, "FilterMessageTypes": TYPES}))
        print(f"connected to {URL}, recording…", flush=True)
        async for raw in ws:
            buf.add(to_row(raw))


def _stop(*_):
    raise KeyboardInterrupt


def main():
    if not API_KEY:
        sys.exit("Set AISSTREAM_API_KEY first (a free key from https://aisstream.io).")
    signal.signal(signal.SIGTERM, _stop)  # `kill` or `systemctl stop` still saves the last batch
    buf = Buffer()
    backoff = 5
    try:
        while True:
            try:
                asyncio.run(stream(buf))
                print("stream closed by server; reconnecting in 5s", flush=True)
                backoff = 5
            except FatalError as err:
                buf.flush()
                sys.exit(str(err))
            except Exception as err:  # network drops, server restarts: save what we have and reconnect
                buf.flush()
                print(f"connection lost ({err!r}); reconnecting in {backoff}s", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
                continue
            buf.flush()
            time.sleep(5)
    except KeyboardInterrupt:
        buf.flush()
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
