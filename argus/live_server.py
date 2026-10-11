"""Optional shared AIS companion: one collector, private archive, public read API.

Run ``python -m argus.live_server``. The AIS key is read only from the environment;
the offline demo and the interactive recorder's key file are never loaded.
"""

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid

from aiohttp import web
import websockets

from argus.live_archive import ArchiveError, LiveArchive
from argus.live_state import LiveState, POSITION_TYPES
from recorder.recorder import BOX, TYPES, URL, FatalError, to_row


ROOT = Path(__file__).resolve().parents[1]
SERVICE_KEY = web.AppKey("live_service", object)
LOG = logging.getLogger("argus.live")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mounted_volume(path):
    """Recognize Linux bind mounts too; ismount alone misses same-device mounts."""
    if os.path.ismount(path):
        return True
    try:
        target = str(Path(path).resolve())
        with Path("/proc/self/mountinfo").open() as entries:
            for entry in entries:
                fields = entry.split()
                if len(fields) < 6:
                    continue
                mount = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
                if mount == target:
                    return True
    except OSError:
        pass
    return False


@dataclass
class Config:
    archive_dir: Path
    api_key: str = field(default="", repr=False)
    upstream_url: str = URL
    label: str = "real"
    max_vessels: int = 5000
    stale_seconds: int = 900
    archive_bytes: int = 450 * 1024 * 1024
    flush_seconds: float = 300
    publish_seconds: float = 1
    history_batches: int = 300
    history_bytes: int = 4 * 1024 * 1024
    max_clients: int = 32
    reconnect_seconds: float = 5
    require_volume: bool = False

    @classmethod
    def from_env(cls):
        label = os.environ.get("ARGUS_AIS_LABEL", "real")
        if label not in {"real", "simulated"}:
            raise ValueError("ARGUS_AIS_LABEL must be real or simulated")
        url = os.environ.get("ARGUS_AIS_URL", URL)
        # A production secret must never be sent to an unencrypted upstream.
        if not url.startswith("wss://"):
            raise ValueError("ARGUS_AIS_URL must use wss://")
        return cls(
            archive_dir=Path(os.environ.get("ARGUS_AIS_DIR", "data/live-ais")),
            api_key=os.environ.get("AISSTREAM_API_KEY", "").strip(),
            upstream_url=url, label=label,
            require_volume=os.environ.get("ARGUS_REQUIRE_VOLUME", "0") == "1",
        )


class LiveService:
    def __init__(self, config):
        self.config = config
        self.state = LiveState(config.max_vessels, config.stale_seconds)
        self.archive = LiveArchive(config.archive_dir, flush_seconds=config.flush_seconds,
                                   max_archive_bytes=config.archive_bytes)
        self.archive_lock = asyncio.Lock()
        self.stream_id = uuid.uuid4().hex
        self.sequence = 0
        self.history = deque(maxlen=config.history_batches)
        self.history_sizes = deque(maxlen=config.history_batches)
        self.changed = asyncio.Condition()
        self.dirty = {}
        self.published_ids = set()
        self.status_dirty = False
        self.feed = {"status": "connecting" if config.api_key else "no_key",
                     "label": config.label, "last_received_utc": None,
                     "last_position_utc": None, "stale_seconds": config.stale_seconds,
                     "coverage": "AISstream public AIS; Ireland bounding box; reception varies",
                     "archive_status": "ready", "archived_rows_this_run": 0}
        self.volume_verified = mounted_volume("/data") if config.require_volume else None
        self.tasks = []
        self.clients = 0
        self.ready = False
        self.stopping = False
        self.started = time.monotonic()

    async def disk_call(self, function, *args):
        """A cancelled coroutine must join its writer before releasing the lock."""
        async with self.archive_lock:
            operation = asyncio.create_task(asyncio.to_thread(function, *args))
            try:
                return await asyncio.shield(operation)
            except asyncio.CancelledError:
                # to_thread keeps running after cancellation. Joining it here
                # prevents shutdown flush from racing an unfinished append.
                with suppress(Exception):
                    await operation
                raise

    def set_status(self, status):
        if self.feed["status"] != status:
            self.feed["status"] = status
            self.status_dirty = True

    async def start(self):
        try:
            if self.config.require_volume and not self.volume_verified:
                raise ArchiveError("Persistent volume is required")
            # Restore incrementally on the loop; no unbounded full archive load.
            def restore_batch(iterator):
                rows = []
                for _ in range(1024):
                    try:
                        rows.append(next(iterator))
                    except StopIteration:
                        break
                return rows
            await self.disk_call(self.archive.recover)
            iterator = iter(self.archive.recent_rows(max_age_hours=48))
            while rows := await asyncio.to_thread(restore_batch, iterator):
                for row in rows:
                    row["label"] = self.config.label
                    self.state.ingest(row)
            self.published_ids = self.state.contact_ids()
        except ArchiveError:
            self.feed["archive_status"] = "error"
            self.set_status("archive_error")
            LOG.error("Private archive could not be restored; collection is stopped")
        self.ready = True
        self.tasks = [asyncio.create_task(self.publisher()), asyncio.create_task(self.flusher())]
        if self.config.api_key and self.feed["archive_status"] == "ready":
            self.tasks.append(asyncio.create_task(self.collector()))

    async def close(self):
        self.stopping = True
        self.set_status("stopping")
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task
        try:
            await self.disk_call(self.archive.flush)
        except ArchiveError:
            LOG.error("Private archive flush failed; its journal was retained")
        async with self.changed:
            self.changed.notify_all()

    async def accept(self, row):
        # Serialize all archive access. Public visibility follows durable append.
        try:
            await self.disk_call(self.archive.append, row)
        except ArchiveError:
            self.feed["archive_status"] = "error"
            self.set_status("archive_error")
            raise
        row["label"] = self.config.label
        upsert = self.state.ingest(row)
        self.feed["last_received_utc"] = utc_now()
        self.feed["archived_rows_this_run"] += 1
        if upsert:
            self.dirty[upsert["mmsi"]] = upsert
            if len(self.dirty) > self.config.max_vessels:
                current_ids = self.state.contact_ids()
                self.dirty = {mmsi: v for mmsi, v in self.dirty.items() if mmsi in current_ids}
            if row["msg_type"] in POSITION_TYPES:
                self.feed["last_position_utc"] = upsert["received_utc"]
        self.set_status("live")

    async def collector(self):
        backoff = self.config.reconnect_seconds
        while not self.stopping:
            self.set_status("connecting" if self.feed["last_received_utc"] is None else "reconnecting")
            received_any = False
            try:
                async with websockets.connect(self.config.upstream_url, ping_interval=20,
                                              ping_timeout=60, max_size=65_536,
                                              max_queue=16, open_timeout=20) as ws:
                    await ws.send(json.dumps({"APIKey": self.config.api_key,
                                              "BoundingBoxes": BOX, "FilterMessageTypes": TYPES}))
                    async for raw in ws:
                        try:
                            row = to_row(raw)
                        except (ValueError, TypeError, AttributeError):
                            continue
                        await self.accept(row)
                        received_any = True
            except FatalError:
                # Provider exceptions can embed request content. Never log them.
                self.set_status("auth_error")
                LOG.error("AIS provider rejected authentication; update the private Railway variable")
                return
            except ArchiveError:
                self.feed["archive_status"] = "error"
                self.set_status("archive_error")
                LOG.error("Private archive is unavailable or full; collection is stopped and history retained")
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.warning("AIS provider disconnected; reconnecting automatically")
            self.set_status("reconnecting")
            if received_any:
                backoff = self.config.reconnect_seconds
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

    async def publish(self):
        if not self.dirty and not self.status_dirty:
            return
        current = self.state.contact_ids()
        self.sequence += 1
        batch = {**self.envelope(), "feed": dict(self.feed),
                 "upserts": [v for mmsi, v in self.dirty.items() if mmsi in current],
                 "removals": sorted(self.published_ids - current)}
        self.history.append(batch)
        self.history_sizes.append(len(json.dumps(batch, separators=(",", ":"))))
        while len(self.history) > 1 and sum(self.history_sizes) > self.config.history_bytes:
            self.history.popleft()
            self.history_sizes.popleft()
        self.published_ids = current
        self.dirty.clear()
        self.status_dirty = False
        async with self.changed:
            self.changed.notify_all()

    async def publisher(self):
        while True:
            await asyncio.sleep(self.config.publish_seconds)
            await self.publish()

    async def flusher(self):
        while True:
            await asyncio.sleep(self.config.flush_seconds)
            try:
                await self.disk_call(self.archive.flush)
            except ArchiveError:
                self.feed["archive_status"] = "error"
                self.set_status("archive_error")
                # Stop the upstream collector without stopping the read API.
                if len(self.tasks) > 2:
                    self.tasks[2].cancel()
                return

    def envelope(self):
        return {"schema_version": 1, "stream_id": self.stream_id,
                "sequence": self.sequence, "generated_utc": utc_now()}

    def snapshot(self):
        return {**self.envelope(), "feed": dict(self.feed), **self.state.snapshot()}

    def updates(self, stream_id, after):
        if (stream_id != self.stream_id or after < 0 or after > self.sequence or
                (self.history and after < self.history[0]["sequence"] - 1)):
            return self.snapshot()
        upserts, removals = {}, set()
        for batch in self.history:
            if batch["sequence"] <= after:
                continue
            for mmsi in batch["removals"]:
                upserts.pop(mmsi, None)
                removals.add(mmsi)
            for vessel in batch["upserts"]:
                removals.discard(vessel["mmsi"])
                upserts[vessel["mmsi"]] = vessel
        return {**self.envelope(), "feed": dict(self.feed),
                "upserts": list(upserts.values()), "removals": sorted(removals)}


def response_json(data):
    response = web.json_response(data, dumps=lambda value: json.dumps(value, allow_nan=False,
                                                                     separators=(",", ":")))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.enable_compression()
    return response


async def vessels(request):
    service = request.app[SERVICE_KEY]
    # Flush pending upserts to give snapshots a consistent resume cursor.
    await service.publish()
    return response_json(service.snapshot())


async def updates(request):
    service = request.app[SERVICE_KEY]
    try:
        after = int(request.query.get("after", "-1"))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid cursor") from None
    await service.publish()
    return response_json(service.updates(request.query.get("stream_id"), after))


async def health(request):
    service = request.app[SERVICE_KEY]
    return response_json({"process_ready": service.ready, "feed": dict(service.feed),
                          "archive": service.archive.stats(),
                          "persistent_volume_verified": service.volume_verified,
                          "contacts": service.state.contact_count,
                          "uptime_s": round(time.monotonic() - service.started)})


async def events(request):
    service = request.app[SERVICE_KEY]
    if service.clients >= service.config.max_clients:
        raise web.HTTPServiceUnavailable(text="Live viewer limit reached; retry shortly",
                                         headers={"Retry-After": "5"})
    cursor = request.headers.get("Last-Event-ID", "")
    stream_id, _, number = cursor.partition(":")
    try:
        after = int(number)
    except ValueError:
        after = -1
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-store",
                                           "Access-Control-Allow-Origin": "*",
                                           "X-Accel-Buffering": "no"})
    service.clients += 1
    try:
        await response.prepare(request)
        await response.write(b"retry: 2000\n\n")
        while not service.stopping:
            await service.publish()
            packet = service.updates(stream_id, after)
            event = "snapshot" if "vessels" in packet else "update"
            if event == "snapshot" or packet["sequence"] != after:
                encoded = json.dumps(packet, allow_nan=False, separators=(",", ":"))
                payload = f"id: {service.stream_id}:{packet['sequence']}\nevent: {event}\ndata: {encoded}\n\n".encode()
                await asyncio.wait_for(response.write(payload), timeout=10)
                stream_id, after = service.stream_id, packet["sequence"]
            try:
                async with service.changed:
                    # Check under the condition to avoid losing a publish wakeup.
                    if service.sequence == after and not service.stopping:
                        await asyncio.wait_for(service.changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                heartbeat = {**service.envelope(), "sequence": after, "feed": dict(service.feed)}
                payload = "event: status\ndata: " + json.dumps(heartbeat, separators=(",", ":")) + "\n\n"
                await asyncio.wait_for(response.write(payload.encode()), timeout=10)
    except (ConnectionResetError, BrokenPipeError, asyncio.TimeoutError, asyncio.CancelledError):
        pass
    finally:
        service.clients -= 1
    return response


async def asset(request):
    # Explicit allowlist; never expose the repository, private volume or key file.
    routes = {"/": ROOT / "ui/live/index.html", "/live.css": ROOT / "ui/live/live.css",
              "/live.mjs": ROOT / "ui/live/dashboard.mjs",
              "/assets/world_land.json": ROOT / "ui/assets/world_land.json",
              "/assets/world_ports.json": ROOT / "ui/assets/world_ports.json",
              "/assets/mark.svg": ROOT / "ui/assets/mark.svg"}
    path = routes[request.path]
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


def create_app(config):
    app = web.Application(client_max_size=1024)
    app[SERVICE_KEY] = LiveService(config)
    for path in ("/", "/live.css", "/live.mjs", "/assets/world_land.json",
                 "/assets/world_ports.json", "/assets/mark.svg"):
        app.router.add_get(path, asset)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/v1/vessels", vessels)
    app.router.add_get("/api/v1/updates", updates)
    app.router.add_get("/api/v1/events", events)

    async def lifecycle(application):
        service = application[SERVICE_KEY]
        await service.start()
        try:
            yield
        finally:
            await service.close()
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Disable access logs: URL query strings are not useful collector diagnostics.
    web.run_app(create_app(Config.from_env()), host="0.0.0.0",
                port=int(os.environ.get("PORT", "8080")), access_log=None,
                shutdown_timeout=15, print=None)


if __name__ == "__main__":
    main()
