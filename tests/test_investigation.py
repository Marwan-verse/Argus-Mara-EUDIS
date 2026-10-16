"""Evidence boundaries and encounter review under incomplete observations."""
from copy import deepcopy
import unittest

from argus.investigation import epoch, pair_review, timeline, valid_track
from argus.scenario_lab import encounter_exercise
from argus.vessel_reports import make_report


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.vessels = encounter_exercise()

    def review(self, vessels=None, now=3600, **kwargs):
        return pair_review(self.vessels if vessels is None else vessels, now,
                           port_distance=kwargs.pop("port_distance", lambda *_: 100), **kwargs)

    def test_parallel_and_slow_meeting_have_support_and_no_threat_score(self):
        rows = self.review()
        self.assertEqual({r["kind"] for r in rows}, {"Parallel travel", "Possible rendezvous"})
        self.assertTrue(all(r["status"] == "For review" and len(r["samples"]) >= 16 for r in rows))
        self.assertTrue(all("score" not in r and "assessment" not in r for r in rows))

    def test_port_and_anchorage_encounters_stay_context_only(self):
        self.assertTrue(all(r["status"] == "Context only" for r in self.review(port_distance=lambda *_: 2)))
        point = self.vessels[0]["track"][0]
        rows = self.review(anchorages=[{"lat": point["lat"], "lon": point["lon"], "radius_nm": 20}])
        self.assertTrue(all(r["status"] == "Context only" for r in rows))

    def test_different_provenance_or_identity_never_pairs(self):
        a, b = deepcopy(self.vessels[:2])
        b["label"] = "real"
        self.assertEqual(self.review([a, b]), [])
        b["label"], b["mmsi"] = a["label"], a["mmsi"]
        self.assertEqual(self.review([a, b]), [])

    def test_sparse_or_asynchronous_positions_do_not_create_a_hold(self):
        for v in self.vessels:
            v["track"] = v["track"][::10]
        self.assertEqual(self.review(), [])
        a, b = encounter_exercise()[:2]
        a["track"] = a["track"][::3]
        b["track"] = [{**f, "t": f["t"] + 90} for f in b["track"][::3]]
        self.assertEqual(self.review([a, b]), [])

    def test_stream_reset_breaks_duration_and_future_fixes_are_hidden(self):
        for v in self.vessels:
            for f in v["track"]:
                f["stream_id"] = str(int(f["t"] // 600))
        self.assertEqual(self.review(), [])
        self.assertEqual(self.review(encounter_exercise(), now=300), [])

    def test_short_provenance_changes_cannot_be_bridged(self):
        for vessel in self.vessels:
            for fix in vessel["track"]:
                fix["label"] = "real" if fix["t"] % 600 == 0 else "fictional"
        self.assertEqual(self.review(), [])

    def test_repeated_approaches_need_observed_separation_not_missing_data(self):
        a, b = deepcopy(self.vessels[:2])
        for v in (a, b):
            v["track"] = [f for f in v["track"] if f["t"] % 1200 <= 300]
        self.assertFalse(any(r["kind"] == "Repeated close approaches" for r in self.review([a, b])))
        a, b = deepcopy(self.vessels[:2])
        from argus.countdown import step
        for v in (a, b):
            v["track"] = []
            for t in range(0, 7201, 60):
                lat, lon = step(53, -5.3, 90, 6*t/3600)
                v["track"].append({"t": t, "lat": lat, "lon": lon, "sog_kn": 6, "cog_deg": 90})
        for p, q in zip(a["track"], b["track"]):
            # A triangular separation: three measured approaches, each with a
            # sustained departure beyond 1 nm in between; speed remains valid.
            phase = (p["t"] % 1800) / 1800
            q["lat"] = p["lat"] + (.2 + 2 * (1-abs(2*phase-1))) / 60
        self.assertTrue(any(r["kind"] == "Repeated close approaches" for r in self.review([a, b], now=7200)))

    def test_timeline_preserves_report_time_and_source_without_mutation(self):
        vessel = deepcopy(self.vessels[0])
        vessel["track"] = [vessel["track"][0], vessel["track"][-1]]
        report = make_report({"id": vessel["mmsi"], "name": vessel["name"], "label": "fictional",
                              "lat": 53, "lon": -5}, "Other", "Review with the duty analyst")
        original = deepcopy(vessel)
        events = timeline(vessel, reports=[{"sender": "Analyst", "report": report}])
        self.assertEqual([e["kind"] for e in events], ["fix", "fix", "gap", "report"])
        self.assertEqual(events[-1]["t"], epoch(report["created_utc"]))
        events[0]["record"]["lat"] = 0
        self.assertEqual(vessel, original)

    def test_satellite_candidate_keeps_scene_and_contact_provenance(self):
        vessel = deepcopy(self.vessels[0])
        vessel["label"] = "real"
        observation = {"id": "contact", "acquired_utc": "2026-10-16T12:00:00Z", "scene_label": "real",
                       "label": "assumption", "lat": 53, "lon": -5, "matched_mmsi": vessel["mmsi"]}
        events = timeline(vessel, observations=[observation])
        self.assertEqual(events[-1]["label"], "assumption")
        self.assertIn("candidate identity", events[-1]["title"])
        observation["scene_label"] = "fictional"
        self.assertFalse(any(e["kind"] == "satellite" for e in timeline(vessel, observations=[observation])))
        observation["scene_label"], observation["matched_mmsi"] = "real", None
        self.assertFalse(any(e["kind"] == "satellite" for e in timeline(vessel, observations=[observation])))

    def test_bad_coordinates_and_times_fail_explicitly(self):
        vessel = deepcopy(self.vessels[0])
        vessel["track"][0]["lat"] = float("nan")
        with self.assertRaises(ValueError):
            valid_track(vessel)
        with self.assertRaises(ValueError):
            epoch("2026-10-16T12:00:00")
        with self.assertRaises(ValueError):
            self.review(self.vessels * 9)


if __name__ == "__main__":
    unittest.main()
