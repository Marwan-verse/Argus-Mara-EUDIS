"""Regression checks for the planned Space handoff and offline evidence export."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from argus.evidence import EXAMPLES, ROOT, build_bundle, load_ais, source_link
from argus.ingest.ais import normalise_rows
from argus.ingest.gfw import import_rows
from argus.provenance import sha256, time_range, write_json
from argus.space import analyse, dimensions_at, timestamp


class SpaceHandoffTests(unittest.TestCase):
    def fix(self, **changes):
        return {"mmsi": "123456789", "ts": "2021-09-05T18:07:10Z", "lat": 53.2, "lon": -5.4,
                "sog_kn": 0, "cog_deg": 0, "ais_length_m": 100, **changes}

    def test_utc_normalization_duplicates_and_fractional_order(self):
        first = self.fix(ts="2021-09-05T19:07:10+01:00")
        result = normalise_rows([self.fix(ts="2021-09-05T18:07:10.1Z"), first, self.fix()], "real")
        self.assertEqual(result["quality"]["duplicates_removed"], 1)
        self.assertEqual(result["vessels"][0]["track"][0]["ts"], "2021-09-05T18:07:10Z")
        self.assertEqual(result["coverage"]["last_utc"], "2021-09-05T18:07:10.100000Z")
        with self.assertRaisesRegex(ValueError, "conflicting AIS"):
            normalise_rows([self.fix(), self.fix(lon=-5.5)], "real")

    def test_recorder_handoff_excludes_raw_and_marks_assumed_time(self):
        rows = [{"msg_type": "ShipStaticData", "raw": "ignored"},
                {"msg_type": "PositionReport", "mmsi": 123456789, "lat": 53.2, "lon": -5.4,
                 "time_utc": "2021-09-05 18:07:10.123456789 +0000 UTC", "raw": "secret not exported",
                 "sog": 102.3, "cog": 360},
                {"msg_type": "PositionReport", "mmsi": 123456789, "lat": 53.2, "lon": -5.4,
                 "recv_utc": "2021-09-05T18:07:11Z", "sog": 0, "cog": 0}]
        result = normalise_rows(rows, "real", "recorder")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(result["quality"]["nonposition_rows_skipped"], 1)
        self.assertEqual(result["quality"]["receipt_time_fixes"], 1)
        self.assertIsNone(result["vessels"][0]["track"][0]["sog_kn"])
        contact = {"ts": "2021-09-05T18:07:11Z", "lat": 53.2, "lon": -5.4, "label": "real"}
        sidecar = analyse({"label": "real", "detections": [contact], "vessels": result["vessels"]})
        self.assertTrue(sidecar["detections"][0]["association_evidence"]["observation_time_assumed"])

    def test_mixed_provenance_is_explicit(self):
        result = normalise_rows([self.fix(label="real"), self.fix(mmsi="987654321", label="fictional")], "real")
        self.assertEqual(result["label"], "assumption")
        self.assertEqual(result["provenance_labels"], ["fictional", "real"])
        with self.assertRaisesRegex(ValueError, "provenance"):
            normalise_rows([self.fix(), self.fix(ts="2021-09-05T18:07:11Z", label="fictional")], "real")

    def test_historical_contact_does_not_match_current_or_fictional_ais(self):
        contact = {"ts": "2021-09-05T18:07:10Z", "lat": 53.2, "lon": -5.4, "label": "real"}
        for fixes, label in [([self.fix(ts="2026-10-08T18:07:10Z")], "real"), ([self.fix()], "fictional")]:
            result = normalise_rows(fixes, label)
            sidecar = analyse({"label": "real", "detections": [contact], "vessels": result["vessels"]})
            self.assertEqual(sidecar["detections"][0]["association"], "unmatched")
            self.assertEqual(sidecar["detections"][0]["custody_candidates"], [])

    def test_provider_match_is_retained_without_future_dimensions(self):
        ais = normalise_rows([self.fix(ts="2026-10-08T18:07:10Z")], "real")
        contact = {"ts": "2021-09-05T18:07:10Z", "lat": 53.2, "lon": -5.4,
                   "length_m": 200, "matched_mmsi": 123456789, "label": "real"}
        result = analyse({"label": "real", "detections": [contact], "vessels": ais["vessels"]})["detections"][0]
        self.assertEqual(result["association"], "source_reported")
        self.assertEqual(result["provider_matched_mmsi"], 123456789)
        self.assertEqual(result["length_check"]["status"], "unavailable")

    def test_sourced_dimensions_expire_and_cannot_use_future_values(self):
        vessel = normalise_rows([self.fix()], "real")["vessels"][0]
        when = timestamp("2021-09-05T18:07:10Z")
        self.assertEqual(dimensions_at(vessel, when, None), 100)
        self.assertIsNone(dimensions_at(vessel, when - 1, None))
        self.assertIsNone(dimensions_at(vessel, when + 86401, None))
        vessel["dimension_history"][0]["label"] = "fictional"
        self.assertIsNone(dimensions_at(vessel, when, None))

    def test_contact_filters_deduplicate_with_stable_identity(self):
        with (EXAMPLES / "gfw-unmatched-contacts.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        all_contacts = import_rows(rows + [rows[0]])
        filtered = import_rows(rows, start="2021-09-05", end="2021-09-06")
        self.assertEqual(all_contacts["selection"]["duplicates_removed"], 1)
        self.assertEqual(filtered["detections"][0]["id"], all_contacts["detections"][0]["id"])
        self.assertEqual(len(import_rows(rows, end="2021-09-05")["detections"]), 1)
        with self.assertRaisesRegex(ValueError, "conflicting records"):
            import_rows(rows + [{**rows[0], "length_m": "999"}])
        with self.assertRaisesRegex(ValueError, "start must precede"):
            import_rows(rows, start="2021-09-06", end="2021-09-05")

    def test_empty_coverage_does_not_claim_continuity(self):
        self.assertEqual(time_range([])["observation_count"], 0)
        self.assertFalse(time_range([])["continuous_coverage"])


class EvidenceExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.output = self.root / "review"
        self.addCleanup(self.directory.cleanup)

    def bundled(self, **changes):
        return build_bundle(EXAMPLES / "gfw-unmatched-contacts.csv", self.output,
                            EXAMPLES / "provenance.json", [EXAMPLES / "sentinel1-scene.json"], **changes)

    def test_pack_is_attributed_hashed_offline_and_has_missing_scene_state(self):
        manifest = self.bundled()
        self.assertFalse(manifest["coverage"]["complete_regional_census"])
        self.assertIsNone(manifest["source_retrieved_at_utc"])
        sidecar = json.loads((self.output / "space.json").read_text())
        self.assertEqual({p["scene_evidence"]["status"] for p in sidecar["detections"]}, {"available", "unavailable"})
        for item in manifest["files"]:
            self.assertEqual(sha256(self.output / item["path"]), item["sha256"])
            if item["path"].endswith(".html"):
                page = (self.output / item["path"]).read_text()
                self.assertNotIn("{{", page)
                self.assertNotIn('src="https://', page)
                self.assertIn("Operator review required", page)
        self.assertEqual(manifest["coverage"]["radar"]["observation_count"], 2)
        self.assertEqual(manifest["provenance"]["license"], "CC BY 4.0")

    def test_default_examples_and_normalized_ais_remain_separate_in_time(self):
        ais_path = self.root / "ais.json"
        write_json(ais_path, normalise_rows([SpaceHandoffTests().fix(ts="2026-10-08T18:07:10Z")], "real"))
        self.bundled(ais_path=ais_path)
        detections = json.loads((self.output / "space.json").read_text())["detections"]
        self.assertTrue(all(p["matched_mmsi"] is None for p in detections))
        self.assertEqual(json.loads((self.output / "manifest.json").read_text())["coverage"]["ais"]["status"], "supplied")

    def test_bad_provenance_and_scene_time_fail_before_export(self):
        provenance = self.root / "provenance.json"
        write_json(provenance, {"source_rows_sha256": "wrong"})
        with self.assertRaisesRegex(ValueError, "checksum"):
            build_bundle(EXAMPLES / "gfw-unmatched-contacts.csv", self.output, provenance)
        self.assertFalse(self.output.exists())
        scene = json.loads((EXAMPLES / "sentinel1-scene.json").read_text())
        scene["product"]["ContentDate"]["Start"] = "2018-11-13T18:14:40Z"
        path = self.root / "scene.json"
        write_json(path, scene)
        with self.assertRaisesRegex(ValueError, "outside its supplied scene"):
            build_bundle(EXAMPLES / "gfw-unmatched-contacts.csv", self.output, scene_paths=[path])
        self.assertFalse(self.output.exists())

    def test_html_escapes_untrusted_source_text_and_links(self):
        scenario = self.root / "scenario.json"
        write_json(scenario, {"label": "fictional", "detections": [{"ts": "2026-10-08T00:00:00Z",
            "lat": 53, "lon": -5, "scene_id": '<script>alert("x")</script>'}],
            "provenance": {"article": "javascript:alert(1)", "attribution": "<img src=x onerror=alert(1)>"}})
        build_bundle(scenario, self.output)
        page = (self.output / "contacts/contact-0001.html").read_text()
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("javascript:", page)
        self.assertIn("source link unavailable", source_link("javascript:alert(1)", "Dataset"))

    def test_refresh_removes_stale_generated_pages_and_retains_extra_files(self):
        self.bundled()
        extra = self.output / "operator-notes.txt"
        extra.write_text("Retain this")
        scenario = self.root / "empty.json"
        write_json(scenario, {"label": "simulated", "detections": []})
        build_bundle(scenario, self.output)
        self.assertFalse((self.output / "contacts/contact-0001.html").exists())
        self.assertEqual(extra.read_text(), "Retain this")
        self.assertIn("not evidence of an empty sea", (self.output / "index.html").read_text())

    def test_output_cannot_replace_inputs_or_unowned_directory(self):
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            build_bundle(EXAMPLES / "gfw-unmatched-contacts.csv", EXAMPLES)
        self.output.mkdir()
        (self.output / "keep.txt").write_text("Keep")
        with self.assertRaisesRegex(ValueError, "output must be empty"):
            self.bundled()

    def test_demo_pack_preserves_shared_files_and_simulated_provenance(self):
        before = {name: sha256(ROOT / "demo" / name) for name in ("scenario.json", "alerts.json")}
        manifest = build_bundle(ROOT / "demo/scenario.json", self.output)
        self.assertEqual(manifest["coverage"]["ais"]["first_utc"], "2026-10-16T08:00:00Z")
        sidecar = json.loads((self.output / "space.json").read_text())
        self.assertEqual(sidecar["detections"][0]["association_label"], "simulated")
        self.assertTrue(sidecar["detections"][0]["custody_candidates"])
        self.assertEqual(before, {name: sha256(ROOT / "demo" / name) for name in before})

    def test_arbitrary_ais_json_is_rejected(self):
        path = self.root / "ais.json"
        write_json(path, {"vessels": []})
        with self.assertRaisesRegex(ValueError, "must be normalized"):
            load_ais(path)


if __name__ == "__main__":
    unittest.main()
