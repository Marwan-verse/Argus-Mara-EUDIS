"""Kp parsing, the NOAA G-scale and the never-blocking loader; no test touches the network."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from argus import space_weather as sw

RECENT = json.loads(sw.RECENT_SNAPSHOT.read_text(encoding="utf-8"))
STORM = json.loads(sw.STORM_SNAPSHOT.read_text(encoding="utf-8"))


def no_network(*args, **kwargs):
    raise AssertionError("tests must not open the network")


class SnapshotTests(unittest.TestCase):
    def test_snapshots_are_labelled_real_with_source_and_date(self):
        for data, source in ((RECENT, ("NOAA SWPC", "GFZ Potsdam")), (STORM, ("GFZ Potsdam",))):
            self.assertEqual(data["label"], "real")
            self.assertIn(data["source"], source)
            self.assertTrue(data["source_url"].startswith("https://"))
            self.assertTrue(data["licence"])
            self.assertRegex(data["retrieved_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertTrue(data["raw"])

    def test_parse_swpc_snapshot(self):
        if RECENT["source"] != "NOAA SWPC":
            self.skipTest("recent snapshot came from the GFZ fallback")
        series = sw.parse_swpc(RECENT["raw"])
        self.assertEqual(series, RECENT["kp"])
        self.assertGreater(len(series), 40)  # 3-hourly values for about a week
        self.assertTrue(all(0 <= row["kp"] <= 9 and row["t"].endswith("Z") for row in series))
        self.assertEqual([row["t"] for row in series], sorted(row["t"] for row in series))

    def test_parse_swpc_formats_and_bad_rows(self):
        objects = [{"time_tag": "2026-10-15T03:00:00", "Kp": 4.67}, {"time_tag": "2026-10-15T00:00:00", "Kp": 2.0},
                   {"time_tag": "2026-10-15T06:00:00", "Kp": None}, {"time_tag": "bad", "Kp": 3}, "junk"]
        table = [["time_tag", "Kp", "a_running", "station_count"], ["2026-10-15 00:00:00.000", "2.00", "7", "8"],
                 ["2026-10-15 03:00:00.000", "4.67", "39", "8"]]
        expected = [{"t": "2026-10-15T00:00:00Z", "kp": 2.0}, {"t": "2026-10-15T03:00:00Z", "kp": 4.67}]
        self.assertEqual(sw.parse_swpc(objects), expected)
        self.assertEqual(sw.parse_swpc(table), expected)
        for bad in ({}, [], [{"time_tag": "x", "Kp": "y"}], [["a", "b"], [1, 2]]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sw.parse_swpc(bad)

    def test_parse_gfz_storm_snapshot(self):
        series = sw.parse_gfz(STORM["raw"])
        self.assertEqual(series, STORM["kp"])
        self.assertEqual(series[0]["t"], "2024-05-09T00:00:00Z")
        self.assertEqual(max(row["kp"] for row in series), 9.0)
        self.assertEqual(sw.peak(STORM), "2024-05-11T00:00:00Z")
        self.assertEqual(set(STORM["raw"]["status"]), {"def"})  # definitive values, not nowcast
        with self.assertRaises(ValueError):
            sw.parse_gfz({"datetime": [], "Kp": []})


class ScaleTests(unittest.TestCase):
    def test_kp_to_g(self):
        cases = {0: 0, 3.0: 0, 4.33: 0, 4.67: 1, 5.0: 1, 5.33: 1, 5.67: 2, 6.33: 2, 6.67: 3, 7.0: 3, 7.33: 3,
                 7.67: 4, 8.0: 4, 8.33: 4, 8.67: 4, 9.0: 5}
        for kp, level in cases.items():
            with self.subTest(kp=kp):
                self.assertEqual(sw.g_level(kp), level)

    def test_kp_text_uses_thirds(self):
        self.assertEqual([sw.kp_text(kp) for kp in (0, 0.33, 2.0, 4.67, 5.33, 8.67, 9.0)],
                         ["0", "0+", "2", "5-", "5+", "9-", "9"])

    def test_navigation_impact_follows_noaa_scale(self):
        self.assertIsNone(sw.nav_impact(2))
        self.assertIn("intermittent", sw.nav_impact(3))
        self.assertIn("hours", sw.nav_impact(4))
        self.assertIn("days", sw.nav_impact(5))
        self.assertFalse(sw.describe(6.33)["gnss_caution"])
        self.assertTrue(sw.describe(6.67)["gnss_caution"])

    def test_headlines(self):
        quiet = sw.status({"kp": [{"t": "2026-10-15T12:00:00Z", "kp": 3.0}], "source": "NOAA SWPC",
                           "source_url": sw.SWPC_URL}, "live")
        self.assertEqual(sw.headline(quiet), "Space weather: Kp 3 (quiet) · NOAA SWPC · 12:00 UTC · real")
        storm = sw.status({"kp": [{"t": "2026-10-15T12:00:00Z", "kp": 8.0}], "source": "NOAA SWPC",
                           "source_url": sw.SWPC_URL}, "live")
        self.assertEqual(sw.headline(storm), "Geomagnetic storm G4 (Kp 8): satellite navigation may be degraded "
                                             "for hours · NOAA SWPC · 12:00 UTC · real")


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cache = Path(self.folder.name) / "cache/kp_recent.json"
        sw.urlopen, self._urlopen = no_network, sw.urlopen

    def tearDown(self):
        sw.urlopen = self._urlopen
        self.folder.cleanup()

    def weather(self, fetch, **paths):
        return sw.SpaceWeather(fetch=fetch, cache_path=self.cache, refresh_s=3600, **paths)

    def test_no_network_falls_back_to_snapshot_without_waiting(self):
        def offline():
            raise OSError("network blocked")

        weather = self.weather(offline)
        started = time.monotonic()
        weather.start()
        state = weather.current()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(state["origin"], "snapshot")
        self.assertEqual(state["t"], RECENT["kp"][-1]["t"])
        self.assertFalse(weather.refresh())
        self.assertIn("network blocked", weather.last_error)
        self.assertFalse(self.cache.exists())
        weather.stop()

    def test_slow_network_never_blocks_current(self):
        release = threading.Event()

        def slow():
            release.wait(5)
            raise TimeoutError("timed out")

        weather = self.weather(slow).start()
        started = time.monotonic()
        self.assertEqual(weather.current()["origin"], "snapshot")
        self.assertLess(time.monotonic() - started, 0.5)
        release.set()
        weather.stop()

    def test_live_fetch_is_used_and_cached(self):
        live = sw.snapshot([{"t": "2030-01-01T00:00:00Z", "kp": 8.0}], "NOAA SWPC", sw.SWPC_URL, [])
        weather = self.weather(lambda: live)
        self.assertTrue(weather.refresh())
        state = weather.current()
        self.assertEqual((state["origin"], state["g"], state["kp"]), ("live", 4, 8.0))
        again = self.weather(no_network)  # next start without network: the newer cache wins over the snapshot
        self.assertEqual(again.current()["origin"], "cache")
        self.assertEqual(again.current()["t"], "2030-01-01T00:00:00Z")

    def test_broken_files_are_ignored(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("{not json", encoding="utf-8")
        broken = Path(self.folder.name) / "broken.json"
        broken.write_text(json.dumps({"kp": [{"t": 1, "kp": "x"}]}), encoding="utf-8")
        weather = self.weather(no_network, snapshot_path=broken, storm_path=broken)
        self.assertIsNone(weather.current())
        self.assertIsNone(weather.storm_2024())

    def test_fetch_recent_falls_back_to_gfz_then_fails_cleanly(self):
        asked = []

        class Answer:
            def __init__(self, body):
                self.body = json.dumps(body).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return self.body

        def gfz_only(request, timeout):
            asked.append((request.full_url, timeout))
            if "swpc" in request.full_url:
                raise OSError("blocked")
            return Answer(STORM["raw"])

        data = sw.fetch_recent(opener=gfz_only)
        self.assertEqual((data["source"], data["label"]), ("GFZ Potsdam", "real"))
        self.assertEqual([timeout for _, timeout in asked], [sw.TIMEOUT_S, sw.TIMEOUT_S])
        self.assertIn("kp.gfz.de", asked[1][0])
        with self.assertRaises(AssertionError):  # both sources unreachable: the error reaches the loader
            sw.fetch_recent()
        weather = sw.SpaceWeather(cache_path=self.cache)  # the default fetch, still without network
        self.assertFalse(weather.refresh())
        self.assertEqual(weather.current()["origin"], "snapshot")

    def test_storm_2024_is_the_real_peak(self):
        state = self.weather(no_network).storm_2024()
        self.assertEqual((state["kp"], state["g"], state["origin"]), (9.0, 5, "historical"))
        self.assertEqual(state["t"], "2024-05-11T00:00:00Z")
        self.assertTrue(state["gnss_caution"])
        self.assertIn("real, historical", sw.headline(state))


if __name__ == "__main__":
    unittest.main()
