"""Simulated fixtures only: public AIS sanitation and observation semantics."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from argus.live_state import LiveState


START = datetime(2026, 10, 9, tzinfo=timezone.utc)


def position(**overrides):
    return {"recv_utc": START, "msg_type": "PositionReport", "mmsi": 123456789,
            "ship_name": "SIMULATED TEST", "lat": 53.0, "lon": -6.0, "sog": 0.0,
            "cog": 0.0, "heading": 0, "nav_status": 0, "raw": "{}",
            "label": "simulated", **overrides}


def static(body, **overrides):
    row = position(**{"msg_type": "ShipStaticData", "recv_utc": START + timedelta(minutes=5), **overrides})
    row["raw"] = json.dumps({"Message": {row["msg_type"]: body}})
    return row


class LiveStateTests(unittest.TestCase):
    def test_static_updates_identity_without_refreshing_position_age(self):
        state = LiveState(stale_seconds=60)
        state.ingest(position())
        update = state.ingest(static({"Name": "TEST VESSEL", "Type": 70,
                                     "Dimension": {"A": 80, "B": 20}}, lat=10, lon=10))
        self.assertEqual((update["lat"], update["lon"]), (53, -6))
        contact = state.snapshot(START + timedelta(minutes=6))["vessels"][0]
        self.assertEqual(contact["age_s"], 360)
        self.assertTrue(contact["stale"])
        self.assertEqual(contact["ais_length_m"], 100)
        self.assertEqual(contact["ship_type"], 70)
        self.assertEqual(contact["received_utc"], "2026-10-09T00:00:00.000Z")
        self.assertEqual(contact["metadata_received_utc"], "2026-10-09T00:05:00.000Z")
        self.assertEqual(contact["label"], "simulated")

    def test_static_only_contact_has_no_position(self):
        state = LiveState()
        state.ingest(static({"Name": "STATIC TEST", "Type": 60}))
        contact = state.snapshot(START)["vessels"][0]
        self.assertIsNone(contact["lat"])
        self.assertIsNone(contact["received_utc"])
        self.assertIsNone(contact["age_s"])
        self.assertEqual(state.snapshot()["meta"]["position_contacts"], 0)

    def test_class_b_static_parts_are_observed_metadata(self):
        state = LiveState()
        state.ingest(static({"ReportA": {"Name": "CLASS B TEST"}}, msg_type="StaticDataReport"))
        state.ingest(static({"ReportB": {"ShipType": 37, "Dimension": {"A": 5, "B": 7}}},
                            msg_type="StaticDataReport", ship_name=None))
        contact = state.snapshot()["vessels"][0]
        self.assertEqual((contact["name"], contact["ship_type"], contact["ais_length_m"]),
                         ("CLASS B TEST", 37, 12))

    def test_unavailable_navigation_fields_are_null_true_zero_is_retained(self):
        state = LiveState()
        state.ingest(position())
        zero = state.snapshot()["vessels"][0]
        self.assertEqual((zero["sog_kn"], zero["cog_deg"], zero["heading_deg"]), (0, 0, 0))
        state.ingest(position(sog=102.3, cog=360, heading=511, nav_status=15))
        unknown = state.snapshot()["vessels"][0]
        for field in ("sog_kn", "cog_deg", "heading_deg", "nav_status"):
            self.assertIsNone(unknown[field])
        state.ingest(position(sog=float("nan"), cog=float("inf"), heading=-1))
        json.dumps(state.snapshot(), allow_nan=False)

    def test_invalid_positions_never_create_contact(self):
        state = LiveState()
        for override in ({"lat": float("nan")}, {"lon": 181}, {"lat": 91},
                         {"lon": float("inf")}, {"mmsi": 0}, {"mmsi": True},
                         {"recv_utc": START.replace(tzinfo=None)}, {"msg_type": "SubscriptionConfirmation"}):
            self.assertIsNone(state.ingest(position(**override)))
        self.assertEqual(state.snapshot()["vessels"], [])
        self.assertEqual(state.snapshot()["meta"]["rejected_rows"], 8)

    def test_older_observation_cannot_move_ship_or_regress_identity(self):
        state = LiveState()
        state.ingest(position(recv_utc=START + timedelta(minutes=2), ship_name="NEW TEST"))
        self.assertIsNone(state.ingest(position(lat=40, ship_name="OLD TEST")))
        contact = state.snapshot()["vessels"][0]
        self.assertEqual((contact["lat"], contact["name"]), (53, "NEW TEST"))

    def test_cache_is_bounded_and_public_snapshot_is_isolated(self):
        state = LiveState(max_vessels=2)
        for mmsi in (111111111, 222222222, 333333333):
            state.ingest(position(mmsi=mmsi, private_key="SIMULATED DO NOT EXPORT", raw='{"private":"example"}'))
        snapshot = state.snapshot()
        self.assertEqual([vessel["mmsi"] for vessel in snapshot["vessels"]], ["222222222", "333333333"])
        self.assertEqual(snapshot["meta"]["evicted_contacts"], 1)
        self.assertNotIn("raw", snapshot["vessels"][0])
        self.assertNotIn("private_key", snapshot["vessels"][0])
        snapshot["vessels"][0]["lat"] = 0
        self.assertEqual(state.snapshot()["vessels"][0]["lat"], 53)


if __name__ == "__main__":
    unittest.main()
