"""Live HTTP/collector integration with synthetic, labelled AIS only."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
import websockets

from argus.live_archive import ArchiveError
from argus.live_server import Config, create_app, SERVICE_KEY


def row(mmsi=999000001, lon=-6.0):
    return {"recv_utc": datetime.now(timezone.utc), "msg_type": "PositionReport",
            "mmsi": mmsi, "ship_name": "SYNTHETIC TEST", "lat": 53.0, "lon": lon,
            "sog": 0, "cog": 0, "heading": 511, "nav_status": 0,
            "time_utc": None, "raw": json.dumps({"private_test_field": "ARCHIVE_ONLY"})}


class LiveServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = TestServer(create_app(Config(Path(self.temp.name), label="simulated",
                                                   publish_seconds=.02, history_batches=2)))
        await self.server.start_server()
        self.service = self.server.app[SERVICE_KEY]
        self.http = ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.server.close()
        self.temp.cleanup()

    async def get(self, path):
        async with self.http.get(self.server.make_url(path)) as response:
            return response.status, await response.json()

    async def test_http_destination_is_declared_text_and_keeps_position_time(self):
        # Exercise the collector -> public HTTP -> client boundary independently
        # of platform-specific durable directory fsync (covered by archive tests).
        from argus.live_client import validate_envelope
        fix = row()
        declaration = {**row(), 'msg_type': 'ShipStaticData',
            'raw': json.dumps({'Message': {'ShipStaticData': {
                'Destination': 'DUBLIN@@', 'PrivateTestField': 'ARCHIVE_ONLY'}}})}
        with patch.object(self.service.archive, 'append'):
            await self.service.accept(fix)
            initial = (await asyncio.wait_for(self.get('/api/v1/vessels'), timeout=5))[1]
            await self.service.accept(declaration)
            received = (await asyncio.wait_for(self.get('/api/v1/vessels'), timeout=5))[1]
        contact = validate_envelope(received)['rows'][0]
        self.assertEqual(contact['destination'], 'DUBLIN')
        self.assertEqual(contact['received_utc'], initial['vessels'][0]['received_utc'])
        self.assertIsNotNone(contact['destination_received_utc'])
        self.assertNotIn('ARCHIVE_ONLY', json.dumps(received))

    async def test_no_key_is_empty_and_process_ready(self):
        status, data = await self.get("/api/v1/vessels")
        self.assertEqual(status, 200)
        self.assertEqual(data["vessels"], [])
        self.assertEqual(data["feed"]["status"], "no_key")
        self.assertEqual(data["feed"]["label"], "simulated")
        self.assertTrue((await self.get("/healthz"))[1]["process_ready"])
        async with self.http.get(self.server.make_url("/api/v1/vessels"),
                                 headers={"Origin": "https://future-team-ui.example"}) as response:
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    async def test_missing_persistent_mount_prevents_collection(self):
        await self.server.close()
        with patch("argus.live_server.mounted_volume", return_value=False):
            self.server = TestServer(create_app(Config(Path(self.temp.name),
                                      api_key="synthetic-test-value", require_volume=True)))
        await self.server.start_server()
        self.service = self.server.app[SERVICE_KEY]
        health = (await self.get("/healthz"))[1]
        self.assertFalse(health["persistent_volume_verified"])
        self.assertEqual(health["feed"]["status"], "archive_error")
        self.assertEqual(len(self.service.tasks), 2)
        self.assertEqual(self.service.snapshot()["vessels"], [])

    async def test_two_readers_delta_reset_and_private_fields(self):
        await self.service.accept(row())
        first = (await self.get("/api/v1/vessels"))[1]
        second = (await self.get("/api/v1/vessels"))[1]
        self.assertEqual([{k: v for k, v in item.items() if k != "age_s"} for item in first["vessels"]],
                         [{k: v for k, v in item.items() if k != "age_s"} for item in second["vessels"]])
        self.assertEqual(first["vessels"][0]["sog_kn"], 0)
        self.assertNotIn("raw", first["vessels"][0])
        self.assertNotIn("ARCHIVE_ONLY", json.dumps(first))
        cursor = f"/api/v1/updates?stream_id={first['stream_id']}&after={first['sequence']}"
        await self.service.accept(row(lon=-6.1))
        update = (await self.get(cursor))[1]
        self.assertNotIn("vessels", update)
        self.assertEqual(update["upserts"][0]["lon"], -6.1)
        for lon in (-6.2, -6.3, -6.4):
            await self.service.accept(row(lon=lon))
            await self.service.publish()
        self.assertIn("vessels", (await self.get(cursor))[1])
        self.assertIn("vessels", (await self.get("/api/v1/updates?stream_id=old&after=0"))[1])
        for path in ("/data/ais", "/recorder/.apikey", "/.git/config", "/assets/world_cables.json"):
            async with self.http.get(self.server.make_url(path)) as response:
                self.assertEqual(response.status, 404)

    async def test_sse_snapshot_resume_and_limit(self):
        self.service.config.max_clients = 1
        await self.service.accept(row())
        response = await self.http.get(self.server.make_url("/api/v1/events"))
        try:
            packet = await self.read_event(response)
            self.assertIn("event: snapshot", packet)
            initial_id = next(line[4:] for line in packet.splitlines() if line.startswith("id: "))
            await self.service.accept(row(lon=-6.2))
            packet = await self.read_event(response)
            self.assertIn("event: update", packet)
            self.assertIn('"lon":-6.2', packet)
            async with self.http.get(self.server.make_url("/api/v1/events")) as extra:
                self.assertEqual(extra.status, 503)
        finally:
            response.close()
        # Closing a TCP reader is recognized on the next bounded write.
        await self.service.accept(row(lon=-6.3))
        await self.service.publish()
        await asyncio.sleep(.05)
        self.service.config.max_clients = 2
        response = await self.http.get(self.server.make_url("/api/v1/events"),
                                       headers={"Last-Event-ID": initial_id})
        try:
            packet = await self.read_event(response)
            self.assertIn('"lon":-6.3', packet)
        finally:
            response.close()

    @staticmethod
    async def read_event(response):
        async def read():
            lines = []
            while True:
                line = (await response.content.readline()).decode()
                if not line:
                    raise AssertionError("SSE closed before an event")
                lines.append(line)
                if line == "\n":
                    packet = "".join(lines)
                    if "data:" in packet:
                        return packet
                    lines = []
        return await asyncio.wait_for(read(), 3)

    async def test_archive_failure_prevents_public_update(self):
        def fail(_):
            raise ArchiveError("synthetic storage failure")
        self.service.archive.append = fail
        with self.assertRaises(ArchiveError):
            await self.service.accept(row())
        self.assertEqual(self.service.snapshot()["vessels"], [])

    async def test_restart_restores_durable_state_new_epoch(self):
        await self.service.accept(row())
        original = self.service.stream_id
        await self.server.close()
        self.server = TestServer(create_app(Config(Path(self.temp.name), label="simulated")))
        await self.server.start_server()
        self.service = self.server.app[SERVICE_KEY]
        restored = (await self.get("/api/v1/vessels"))[1]
        self.assertNotEqual(original, restored["stream_id"])
        self.assertEqual(restored["vessels"][0]["mmsi"], "999000001")
        self.assertEqual(restored["vessels"][0]["label"], "simulated")

    async def test_bad_cursor(self):
        async with self.http.get(self.server.make_url("/api/v1/updates?after=oops")) as response:
            self.assertEqual(response.status, 400)

    async def test_cancelled_append_joins_writer_before_shutdown_flush(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original_append, original_flush = self.service.archive.append, self.service.archive.flush
        def slow_append(record):
            entered.set()
            release.wait(3)
            original_append(record)
            finished.set()
        def checked_flush():
            self.assertTrue(finished.is_set(), "flush raced the durable writer")
            original_flush()
        self.service.archive.append = slow_append
        task = asyncio.create_task(self.service.accept(row()))
        await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        self.service.archive.flush = checked_flush
        shutdown = asyncio.create_task(self.service.close())
        await asyncio.sleep(.02)
        self.assertFalse(shutdown.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await shutdown
        # Restore the actual method so test teardown can safely flush again.
        self.service.archive.flush = original_flush

    async def test_eviction_removals_and_history_byte_bound(self):
        self.service.state.max_vessels = 1
        self.service.config.history_bytes = 1
        await self.service.accept(row())
        first = (await self.get("/api/v1/vessels"))[1]
        await self.service.accept(row(mmsi=999000002))
        await self.service.publish()
        delta = self.service.updates(first["stream_id"], first["sequence"])
        self.assertEqual(delta["removals"], ["999000001"])
        self.assertEqual(len(self.service.history), 1)

    async def test_health_and_eviction_publish_do_not_materialize_the_fleet(self):
        await self.service.accept(row())
        first = (await self.get("/api/v1/vessels"))[1]
        self.service.state.max_vessels = self.service.config.max_vessels = 1
        with patch.object(self.service.state, "snapshot", side_effect=AssertionError("unneeded full fleet snapshot")):
            await self.service.accept(row(mmsi=999000002))
            await self.service.accept(row(mmsi=999000003))
            await self.service.publish()
            status, health = await self.get("/healthz")
            self.assertEqual((status, health["contacts"]), (200, 1))
            delta = self.service.updates(first["stream_id"], first["sequence"])
            self.assertEqual([v["mmsi"] for v in delta["upserts"]], ["999000003"])
            self.assertIn("999000001", delta["removals"])

    async def test_single_upstream_for_multiple_viewers_and_auth_failure(self):
        connections = 0
        subscribed = asyncio.Event()
        key = "synthetic-test-value"
        async def source(ws):
            nonlocal connections
            connections += 1
            subscription = json.loads(await ws.recv())
            self.assertEqual(subscription["APIKey"], key)
            subscribed.set()
            await ws.send(json.dumps({"MessageType": "PositionReport",
                                      "MetaData": {"MMSI": 999000002, "ShipName": "SYNTHETIC"},
                                      "Message": {"PositionReport": {"Latitude": 53, "Longitude": -7,
                                                                     "Sog": 0, "Cog": 0}}}))
            await asyncio.sleep(.08)
            await ws.send(json.dumps({"error": "invalid API key " + key}))
            await ws.wait_closed()
        async with websockets.serve(source, "127.0.0.1", 0) as upstream:
            port = upstream.sockets[0].getsockname()[1]
            await self.server.close()
            self.server = TestServer(create_app(Config(Path(self.temp.name), api_key=key,
                                  upstream_url=f"ws://127.0.0.1:{port}", label="simulated")))
            await self.server.start_server()
            self.service = self.server.app[SERVICE_KEY]
            await asyncio.wait_for(subscribed.wait(), 3)
            for _ in range(100):
                if self.service.feed["status"] == "auth_error":
                    break
                await asyncio.sleep(.01)
            for _ in range(2):
                data = (await self.get("/api/v1/vessels"))[1]
                self.assertEqual(data["feed"]["status"], "auth_error")
                self.assertEqual(data["vessels"][0]["label"], "simulated")
                self.assertNotIn(key, json.dumps(data))
            self.assertEqual(connections, 1)


if __name__ == "__main__":
    unittest.main()
