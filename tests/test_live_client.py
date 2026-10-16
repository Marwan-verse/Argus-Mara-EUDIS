"""Shared AIS wire semantics, cursor recovery and client thread boundaries."""

from copy import deepcopy
import json
import queue
import threading
import unittest
from unittest.mock import patch

from argus.live_client import LivePoller, LiveState, fetch_json, server_url, validate_envelope


def vessel(identifier="123456789", **fields):
    return {"mmsi": identifier, "name": "TEST CONTACT", "ship_type": "Cargo",
            "lat": 53.0, "lon": -6.0, "sog_kn": None, "cog_deg": None,
            "received_utc": "2026-10-08T20:00:00Z", "label": "simulated", **fields}


def snapshot(**fields):
    return {"schema_version": 1, "stream_id": "session-one", "sequence": 1,
            "generated_utc": "2026-10-08T20:00:01Z",
            "feed": {"status": "live", "label": "simulated", "last_received_utc": None},
            "vessels": [vessel()], **fields}


def update(sequence=2, **fields):
    envelope = snapshot(sequence=sequence)
    envelope.pop("vessels")
    return {**envelope, "upserts": [], "removals": [], **fields}


class LiveClientTests(unittest.TestCase):
    def test_declared_length_is_preserved_and_old_static_metadata_cannot_regress_it(self):
        state = LiveState()
        state.apply(snapshot(vessels=[vessel(ais_length_m=180, metadata_received_utc='2026-10-08T20:00:00Z')]))
        state.apply(update(upserts=[vessel(ais_length_m=90, name='OLD NAME', received_utc='2026-10-08T20:02:00Z',
                                          metadata_received_utc='2026-10-08T19:00:00Z')]))
        self.assertEqual(state.vessels['123456789']['ais_length_m'], 180)
        self.assertEqual(state.vessels['123456789']['name'], 'TEST CONTACT')
        self.assertEqual(state.vessels['123456789']['received_utc'], '2026-10-08T20:02:00Z')
        state.apply(update(3, upserts=[vessel(ais_length_m=None, lat=None, lon=None, received_utc=None,
                                             metadata_received_utc='2026-10-08T20:03:00Z')]))
        self.assertIsNone(state.vessels['123456789']['ais_length_m'])
        self.assertNotIn('ais_length_m', validate_envelope(snapshot())['rows'][0])
        for value in (-1, 0, 1023, True, float('nan')):
            with self.assertRaises(ValueError):
                validate_envelope(snapshot(vessels=[vessel(ais_length_m=value)]))

    def test_destination_updates_without_moving_fix_and_cannot_regress(self):
        state = LiveState()
        state.apply(snapshot())
        self.assertIsNone(state.vessels['123456789']['destination'])
        state.apply(update(upserts=[vessel(destination='DUBLIN@@',
            destination_received_utc='2026-10-08T20:05:00Z', lat=None, lon=None, received_utc=None)]))
        row = state.vessels['123456789']
        self.assertEqual(row['destination'], 'DUBLIN')
        self.assertEqual(row['received_utc'], '2026-10-08T20:00:00Z')
        state.apply(update(3, upserts=[vessel(destination='OLDER',
            destination_received_utc='2026-10-08T20:04:00Z', received_utc='2026-10-08T20:06:00Z')]))
        self.assertEqual(state.vessels['123456789']['destination'], 'DUBLIN')
        state.apply(update(4, upserts=[vessel(destination=None,
            destination_received_utc='2026-10-08T20:07:00Z', lat=None, lon=None, received_utc=None)]))
        self.assertIsNone(state.vessels['123456789']['destination'])
        with self.assertRaises(ValueError):
            state.apply(update(5, upserts=[vessel(destination_received_utc='bad-time')]))

    def test_https_and_loopback_only(self):
        self.assertEqual(server_url("https://example.org/"), "https://example.org")
        self.assertEqual(server_url("http://[::1]:8080"), "http://[::1]:8080")
        for address in ("http://example.org", "file:///tmp/map", "https://user:secret@example.org",
                        "https://example.org?token=secret", "https://example.org/#fragment",
                        "https://example.org:70000", "https://example.org\n", "https://example.org\\path"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                server_url(address)

    def test_empty_and_static_only_contacts(self):
        state = LiveState()
        state.apply(snapshot(vessels=[]))
        self.assertEqual(state.vessels, {})
        static = vessel(lat=None, lon=None, received_utc=None,
                        metadata_received_utc="2026-10-08T20:00:00Z")
        state.apply(update(upserts=[static]))
        self.assertIsNone(state.vessels["123456789"]["received_s"])
        state.apply(update(3, upserts=[vessel()]))
        self.assertIsNotNone(state.vessels["123456789"]["received_s"])

    def test_leading_zero_shore_mmsi_removal_uses_canonical_identity(self):
        state = LiveState()
        state.apply(snapshot(vessels=[vessel("1234567")]))
        self.assertEqual(set(state.vessels), {"001234567"})
        state.apply(update(removals=["1234567"]))
        self.assertEqual(state.vessels, {})
        with self.assertRaises(ValueError):
            validate_envelope(snapshot(vessels=[vessel("0")]))

    def test_server_time_and_freshness_are_preserved_for_client_age(self):
        state = LiveState()
        state.apply(snapshot(feed={"status": "live", "stale_seconds": 300}))
        self.assertEqual(state.generated_s, 1791489601.0)
        self.assertEqual(state.feed["stale_seconds"], 300)

    def test_incremental_resume_and_removal(self):
        state = LiveState()
        state.apply(snapshot())
        state.apply(update(4, upserts=[vessel("987654321", lat=54.0)], removals=["123456789"]))
        self.assertEqual(set(state.vessels), {"987654321"})
        self.assertEqual(state.sequence, 4)
        self.assertFalse(state.apply(update(2, removals=["987654321"])))
        self.assertEqual(state.sequence, 4)
        self.assertEqual(len(state.vessels), 1)

    def test_reset_snapshot_can_replace_stream_and_remove_old_contacts(self):
        state = LiveState()
        state.apply(snapshot())
        with self.assertRaises(ValueError):
            state.apply(update(stream_id="new-stream"))
        self.assertEqual(state.stream_id, "session-one")
        state.apply(snapshot(stream_id="new-stream", sequence=0, vessels=[]))
        self.assertEqual(state.stream_id, "new-stream")
        self.assertEqual(state.vessels, {})

    def test_bad_response_does_not_partially_change_state_or_cursor(self):
        state = LiveState()
        state.apply(snapshot())
        before = deepcopy(state.vessels)
        with self.assertRaises(ValueError):
            state.apply(update(5, upserts=[vessel("987654321"), vessel(lat=91)]))
        self.assertEqual(state.vessels, before)
        self.assertEqual(state.sequence, 1)

    def test_position_age_not_reset_by_new_particulars(self):
        state = LiveState()
        state.apply(snapshot())
        state.apply(update(upserts=[vessel(name="NEW NAME", lat=None, lon=None, received_utc=None,
            metadata_received_utc="2026-10-08T20:01:00Z")]))
        row = state.vessels["123456789"]
        self.assertEqual(row["name"], "NEW NAME")
        self.assertEqual(row["received_utc"], "2026-10-08T20:00:00Z")
        self.assertEqual(row["lat"], 53.0)

    def test_validation_rejects_unknown_provenance_invalid_numbers_and_incomplete_positions(self):
        changes = [{"label": "fictional"}, {"lat": float("nan")}, {"sog_kn": True},
                   {"lon": 181}, {"received_utc": "2026-10-08T20:00:00"},
                   {"received_utc": "2026-10-08T21:00:00+01:00"}, {"lat": None},
                   {"cog_deg": 360}, {"mmsi": "not-an-id"}]
        for fields in changes:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_envelope(snapshot(vessels=[vessel(**fields)]))
        with self.assertRaises(ValueError):
            validate_envelope(snapshot(schema_version=True))
        with self.assertRaises(ValueError):
            validate_envelope(snapshot(vessels=[vessel(), vessel()]))
        with self.assertRaises(ValueError):
            validate_envelope(update(upserts=[vessel()], removals=["123456789"]))

    def test_simulated_labels_and_missing_fields_stay_visible(self):
        state = LiveState()
        state.apply(snapshot(vessels=[vessel(name=None, ship_type=None)]))
        self.assertEqual(state.feed["label"], "simulated")
        row = state.vessels["123456789"]
        self.assertEqual(row["label"], "simulated")
        self.assertEqual(row["name"], "Name unavailable")
        self.assertIsNone(row["sog_kn"])

    def test_navigation_status_keeps_true_zero_and_rejects_invalid_codes(self):
        clean = validate_envelope(snapshot(vessels=[vessel(nav_status=0)]))
        self.assertEqual(clean['rows'][0]['nav_status'], 0)
        for status in (True, 15, -1, 1.5):
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_envelope(snapshot(vessels=[vessel(nav_status=status)]))

    def test_polling_network_runs_off_main_thread_and_recovers_without_losing_cursor(self):
        calls, thread_ids = [], []
        main_thread = threading.get_ident()

        def fetch(address):
            calls.append(address)
            thread_ids.append(threading.get_ident())
            if len(calls) == 1:
                return snapshot()
            if len(calls) == 2:
                raise OSError("unavailable")
            return snapshot(stream_id="restarted", sequence=0, vessels=[])

        poller = LivePoller("https://example.org", interval=.1, fetch=fetch)
        poller.start()
        try:
            events = [poller.events.get(timeout=2) for _ in range(3)]
        finally:
            poller.stop()
            poller._thread.join(timeout=2)
        self.assertEqual([event[0] for event in events], ["data", "connection", "data"])
        self.assertTrue(all(identifier != main_thread for identifier in thread_ids))
        self.assertIn("after=1", calls[1])
        self.assertTrue(calls[2].endswith("/api/v1/vessels"))
        self.assertFalse(poller._thread.is_alive())

    def test_updates_query_is_allowed_by_transport_and_tls_is_preserved(self):
        class Response:
            url = "https://example.org/api/v1/updates?stream_id=one&after=1"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return json.dumps(update()).encode()
        with patch("argus.live_client.urlopen", return_value=Response()) as request:
            self.assertEqual(fetch_json(Response.url)["sequence"], 2)
            self.assertEqual(request.call_args.kwargs["timeout"], 5)
        Response.url = "http://example.org/api/v1/updates"
        with patch("argus.live_client.urlopen", return_value=Response()), self.assertRaises(ValueError):
            fetch_json("https://example.org/api/v1/updates")


if __name__ == "__main__":
    unittest.main()
