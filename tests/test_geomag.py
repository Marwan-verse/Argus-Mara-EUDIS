"""Geomagnetic storm status: parsing, the rolling Kp maximum, dH/dt and tiers, without network access."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from argus import geomag

UTC = timezone.utc


def at(hour, minute=0, day=16):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def kp_json(rows):
    return json.dumps([{"time_tag": f"{t:%Y-%m-%dT%H:%M:%S}", "kp_index": int(kp), "estimated_kp": kp,
                        "kp": f"{int(kp)}P"} for t, kp in rows])


IAGA = """ Format                 IAGA-2002                                    |
 Source of Data         Met Eireann                                  |
 IAGA Code              VAL                                          |
 Reported               HDZF                                         |
 Data Type              Variation                                    |
DATE       TIME         DOY     VALH      VALD      VALZ      VALF   |
2026-10-16 12:00:00.000 289     19640.00   -151.80  44957.00  99999.00
2026-10-16 12:01:00.000 289     19642.50   -151.80  44957.00  99999.00
2026-10-16 12:02:00.000 289     99999.00   -151.80  44957.00  99999.00
2026-10-16 12:03:00.000 289     19650.00   -151.80  44957.00  99999.00
2026-10-16 12:04:00.000 289     19630.00   -151.80  44957.00  99999.00
2026-10-16 12:05:00.000 289     99999.00  99999.00  99999.00  99999.00
"""


class ParsingTests(unittest.TestCase):
    def test_kp_rows_use_the_estimate_and_are_sorted(self):
        rows = geomag.parse_kp(kp_json([(at(12, 1), 0.67), (at(11, 59), 2.33)]))
        self.assertEqual([row["kp"] for row in rows], [2.33, 0.67])
        self.assertEqual(rows[0]["time"], at(11, 59))

    def test_iaga_rows_mark_sentinels_missing(self):
        rows = geomag.parse_iaga2002(IAGA)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0], {"time": at(12, 0), "value": 19640.0})
        self.assertIsNone(rows[2]["value"])
        self.assertIsNone(rows[5]["value"])

    def test_dh_dt_needs_consecutive_minutes(self):
        changes = geomag.dh_dt(geomag.parse_iaga2002(IAGA))
        self.assertEqual([(row["time"], row["nt_per_min"]) for row in changes],
                         [(at(12, 1), 2.5), (at(12, 4), 20.0)])  # 12:01 → 12:03 spans a gap


class RollingKpTests(unittest.TestCase):
    def test_maximum_survives_the_three_hour_restart(self):
        rows = geomag.parse_kp(kp_json([(at(8, 59), 6.0), (at(11, 58), 2.0), (at(11, 59), 2.33),
                                        (at(12, 0), 0.33), (at(12, 5), 0.67)]))
        kp = geomag.rolling_kp(rows, at(12, 6))
        self.assertEqual((kp["kp"], kp["time"]), (2.33, at(11, 59)))  # 08:59 is before the previous interval
        self.assertEqual((kp["latest"], kp["latest_time"]), (0.67, at(12, 5)))
        self.assertEqual(geomag.kp_interval_start(at(14, 59)), at(12, 0))


class TierTests(unittest.TestCase):
    def test_any_one_trigger_sets_the_tier(self):
        cases = [((4.9, 17.9), 0), ((5.0, None), 1), ((None, 18.0), 1), ((7.0, 0.0), 2),
                 ((None, 90.0), 2), ((8.0, 0.0), 3), ((None, 300.0), 3), ((None, None), 0)]
        for (kp, dhdt), tier in cases:
            with self.subTest(kp=kp, dhdt=dhdt):
                self.assertEqual(geomag.tier_for(kp, dhdt)[0], tier)
        self.assertEqual(geomag.tier_for(5.0, 20.0)[2], ["Kp 5.00 ≥ 5", "Valentia dH/dt 20.0 ≥ 18 nT/min"])

    def test_assessment_reads_both_feeds_and_says_what_is_stale(self):
        kp = geomag.parse_kp(kp_json([(at(11, 59), 2.33), (at(12, 5), 0.67)]))
        val = geomag.parse_iaga2002(IAGA)
        status = geomag.assess(kp, val, at(12, 6))
        self.assertEqual((status["tier"], status["name"]), (1, "Active"))
        self.assertEqual((status["dhdt"], status["dhdt_time"]), (20.0, at(12, 4)))
        self.assertEqual(status["val_last_time"], at(12, 4))
        self.assertEqual(status["notes"], [])
        self.assertEqual(status["label"], "real")
        later = geomag.assess(kp, val, at(13, 0))
        self.assertIn("NOAA SWPC Kp is 55 min old.", later["notes"])
        self.assertIn("Valentia data are 56 min old.", later["notes"])
        self.assertIsNone(geomag.assess(None, None, at(12, 6)))
        self.assertIn("No Valentia data", geomag.assess(kp, [], at(12, 6))["notes"][0])

    def test_strong_tier_names_the_peak_and_never_clears(self):
        val = [{"time": at(12, 0), "value": 19600.0}, {"time": at(12, 1), "value": 19700.0}]
        status = geomag.assess([], val, at(12, 5))
        self.assertEqual(status["tier"], 2)
        self.assertIn("peak at 12:01 UTC", status["effect"])
        self.assertIn("Nothing is cleared", status["effect"])
        self.assertEqual(geomag.summary(status), "Strong · dH/dt 100 nT/min")
        self.assertEqual(geomag.summary(None), "Magnetic data unavailable")


class FetchTests(unittest.TestCase):
    def test_fetches_use_the_documented_urls(self):
        opener = Mock(return_value=BytesIO(kp_json([(at(12, 0), 1.0)]).encode()))
        self.assertEqual(geomag.fetch_kp(opener=opener)[0]["kp"], 1.0)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, geomag.KP_URL)
        self.assertIn("ArgusMara", request.get_header("User-agent"))
        opener = Mock(return_value=BytesIO(IAGA.encode()))
        self.assertEqual(len(geomag.fetch_valentia(at(12, 6), opener=opener)), 6)
        self.assertIn("dataStartDate=2026-10-16&dataDuration=1", opener.call_args.args[0].full_url)

    def test_just_after_midnight_also_reads_yesterday(self):
        self.assertIn("dataStartDate=2026-10-15&dataDuration=2", geomag.valentia_url(at(0, 30)))
        self.assertIn("dataStartDate=2026-10-16&dataDuration=1", geomag.valentia_url(at(1, 20)))

    def test_oversized_or_empty_answers_are_errors(self):
        with self.assertRaises(ValueError):
            geomag.fetch_kp(opener=Mock(return_value=BytesIO(b" " * (geomag.MAX_BYTES + 1))))
        with self.assertRaises(ValueError):
            geomag.fetch_kp(opener=Mock(return_value=BytesIO(b"[]")))
        with self.assertRaises(ValueError):
            geomag.fetch_valentia(at(12, 0), opener=Mock(return_value=BytesIO(IAGA.splitlines()[0].encode())))

    def test_cache_round_trip_restores_times(self):
        status = geomag.assess([], geomag.parse_iaga2002(IAGA), at(12, 6))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "magnetics" / "geomag-latest.json"
            geomag.save_cache(path, status)
            self.assertEqual(geomag.load_cache(path), status)
            self.assertIsNone(geomag.load_cache(Path(folder) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
