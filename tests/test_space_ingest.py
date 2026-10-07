import csv
import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from unittest.mock import patch

from argus.ingest.gfw import fetch_report, import_file, import_rows, normalise, report_request
from argus.ingest.sentinel1 import download_quicklook, scene_url
from argus.space import analyse, timestamp


ROOT = Path(__file__).resolve().parents[1]
ROW = {"scene_id": "S1A_IW_GRDH_EXAMPLE", "timestamp": "2021-09-05 18:07:10+00:00",
       "lat": "53.22", "lon": "-5.4", "length_m": "128.5", "mmsi": "",
       "matched_category": "unmatched", "matching_score": "0.000002", "fishing_score": "0.96"}


class IngestTests(unittest.TestCase):
    def test_unmatched_is_real_contact_without_invented_identity(self):
        detection = normalise(ROW)
        self.assertIsNone(detection["matched_mmsi"])
        self.assertEqual(detection["label"], "real")
        self.assertEqual(detection["ts"], "2021-09-05T18:07:10Z")

    def test_provider_category_overrides_weak_mmsi_candidate(self):
        self.assertIsNone(normalise({**ROW, "mmsi": "123456789"})["matched_mmsi"])
        matched = normalise({**ROW, "mmsi": "123456789", "matched_category": "matched_nonfishing"})
        self.assertEqual(matched["matched_mmsi"], 123456789)
        with self.assertRaises(ValueError):
            normalise({**ROW, "matched_category": "matched_nonfishing"})

    def test_filter_and_invalid_data(self):
        result = import_rows([ROW, {**ROW, "lat": "0"},
                              {**ROW, "mmsi": "123456789", "matched_category": "matched_unknown"}],
                             unmatched_only=True)
        self.assertEqual(len(result["detections"]), 1)
        for bad in ({**ROW, "lat": "nan"}, {**ROW, "timestamp": "2021-09-05"},
                    {**ROW, "matched_category": "not-known"}):
            with self.assertRaises(ValueError):
                import_rows([bad])
        with self.assertRaises(ValueError):
            normalise({"date": "2021-09-05", "lat": 53, "lon": -6, "detections": 2})
        with self.assertRaises(ValueError):
            import_rows(csv.DictReader(io.StringIO("date,lat,lon,detections\n")))

    def test_csv_and_zip_import(self):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(ROW))
        writer.writeheader()
        writer.writerow(ROW)
        with tempfile.TemporaryDirectory() as tmp:
            csv_path, zip_path = Path(tmp) / "contacts.csv", Path(tmp) / "contacts.zip"
            csv_path.write_text(stream.getvalue())
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("contacts.csv", stream.getvalue())
            self.assertEqual(import_file(csv_path)["detections"], import_file(zip_path)["detections"])

    def test_report_uses_unmatched_filter_and_lon_lat_polygon(self):
        request = report_request("2026-09-01", "2026-09-08")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request["url"]).query)
        self.assertEqual(query["datasets[0]"], ["public-global-sar-presence:latest"])
        self.assertEqual(query["filters[0]"], ["matched='false'"])
        ring = request["body"]["geojson"]["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], [-18.0, 49.0])
        self.assertEqual(ring[0], ring[-1])
        with self.assertRaises(ValueError):
            report_request("2026-10-07", "2026-10-01")

    def test_missing_token_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "GFW_API_TOKEN"):
                fetch_report(report_request("2026-09-01", "2026-09-08"), Path("unused"))
            network.assert_not_called()

    def test_scene_query_and_injection_rejected(self):
        url = scene_url("S1A_IW_GRDH_1SDV_EXAMPLE")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query["$filter"], ["Name eq 'S1A_IW_GRDH_1SDV_EXAMPLE.SAFE'"])
        with self.assertRaises(ValueError):
            scene_url("scene' or 1 eq 1")

    def test_quicklook_accepts_binary_png_and_uses_correct_extension(self):
        content = b"\x89PNG\r\n\x1a\nexample"
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = content
            output = download_quicklook("https://catalogue.dataspace.copernicus.eu/preview", Path(tmp) / "preview.jpg")
            self.assertEqual(output.suffix, ".png")
            self.assertEqual(output.read_bytes(), content)

    def test_committed_real_example_has_source_and_no_false_identity(self):
        source = ROOT / "space/examples/gfw-unmatched-contacts.csv"
        contacts = import_file(source, unmatched_only=True)
        self.assertGreaterEqual(len(contacts["detections"]), 2)
        results = analyse(contacts)
        self.assertTrue(all(d["label"] == "real" and d["dark_candidate"] for d in results["detections"]))
        provenance = json.loads((ROOT / "space/examples/provenance.json").read_text())
        self.assertEqual(provenance["license"], "CC BY 4.0")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), provenance["source_rows_sha256"])
        scene = json.loads((ROOT / "space/examples/sentinel1-scene.json").read_text())["product"]
        contact = next(d for d in contacts["detections"] if d["scene_id"] + ".SAFE" == scene["Name"])
        self.assertLessEqual(timestamp(scene["ContentDate"]["Start"]), timestamp(contact["ts"]))
        self.assertLessEqual(timestamp(contact["ts"]), timestamp(scene["ContentDate"]["End"]))


if __name__ == "__main__":
    unittest.main()
