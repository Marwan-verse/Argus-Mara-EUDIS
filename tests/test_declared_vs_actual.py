"""Declared against actual: an 'at anchor' status while moving (B9), a destination the course leads away from (C3)."""

import unittest

from argus import assemble
from argus.countdown import step
from argus.detectors import declared_vs_actual, places
from argus.levels import assess

MID_SEA = (53.25, -5.60)  # east of Dublin, more than 5 nm from any port


def track(start, legs, interval=60):
    """Fixes once a minute from ``start``; legs are (minutes, sog kn, cog deg, nav status or None)."""
    (lat, lon), fixes, t = start, [], 0
    for minutes, sog, cog, status in legs:
        for _ in range(minutes):
            fixes.append({"t": t, "lat": lat, "lon": lon, "sog_kn": sog, "cog_deg": cog,
                          **({"nav_status": status} if status is not None else {})})
            lat, lon = step(lat, lon, cog, sog * interval / 3600)
            t += interval
    return fixes


def vessel(fixes, destination=None, nav_status=None):
    return {"mmsi": 999000055, "name": "TEST FULMAR", "ship_type": 70, "ais_class": "A", "ais_length_m": 140,
            "destination": destination, "nav_status": nav_status, "track": fixes, "label": "simulated"}


def detect(fixes, now=None, **kwargs):
    return declared_vs_actual.detect(vessel(fixes, **kwargs), {"now": now})


class StatusTests(unittest.TestCase):
    def test_at_anchor_while_under_way_is_a_status_mismatch(self):
        [finding] = detect(track(MID_SEA, [(30, 12.0, 320, None), (15, 4.0, 320, "at anchor")]))
        self.assertEqual(finding["obs"], {"status_mismatch": True})
        self.assertEqual(finding["related"]["declared_status"], "at anchor")
        self.assertIn("Reports 'at anchor' but moves at 4.0 kn", finding["reasons"][1])
        factor = next(f for f in assess(finding["obs"])["factors"] if f["code"] == "B9")
        self.assertEqual(factor["points"], 1)

    def test_numeric_moored_status_counts_too(self):
        [finding] = detect(track(MID_SEA, [(15, 3.0, 90, 5)]))
        self.assertIn("Reports 'moored'", finding["reasons"][1])

    def test_a_vessel_really_at_anchor_or_just_set_gives_nothing(self):
        self.assertEqual(detect(track(MID_SEA, [(60, 0.2, 0, "at anchor")])), [])
        self.assertEqual(detect(track(MID_SEA, [(30, 12.0, 320, None), (5, 4.0, 320, "at anchor")])), [])
        self.assertEqual(detect(track(MID_SEA, [(30, 12.0, 320, None)])), [])  # under way, no status
        self.assertEqual(detect(track(MID_SEA, [(30, 12.0, 320, 0)])), [])  # "under way using engine"

    def test_a_vessel_level_status_applies_to_every_fix(self):
        [finding] = detect(track(MID_SEA, [(15, 4.0, 320, None)]), nav_status="1")
        self.assertEqual(finding["obs"], {"status_mismatch": True})


class DestinationTests(unittest.TestCase):
    def test_a_course_away_from_the_declared_port_is_route_inconsistent(self):
        [finding] = detect(track(MID_SEA, [(65, 12.0, 320, None)]), destination="IEDUB>GBLIV")
        self.assertEqual(finding["obs"], {"route_inconsistent": True})
        self.assertEqual(finding["related"]["destination_port"]["name"], "Liverpool")
        self.assertIn("Declares destination 'IEDUB>GBLIV' (Liverpool", finding["reasons"][1])
        self.assertIn("UN/LOCODE GBLIV", finding["reasons"][2])
        factor = next(f for f in assess(finding["obs"])["factors"] if f["code"] == "C3")
        self.assertEqual(factor["points"], 1)

    def test_heading_for_the_declared_port_gives_nothing(self):
        self.assertEqual(detect(track(MID_SEA, [(65, 12.0, 75, None)]), destination="LIVERPOOL"), [])

    def test_unknown_destinations_slow_ships_and_short_tracks_give_nothing(self):
        away = [(65, 12.0, 320, None)]
        self.assertEqual(detect(track(MID_SEA, away), destination="FOR ORDERS"), [])
        self.assertEqual(detect(track(MID_SEA, away), destination=""), [])
        self.assertEqual(detect(track(MID_SEA, [(65, 3.0, 320, None)]), destination="GBLIV"), [])
        self.assertEqual(detect(track(MID_SEA, [(40, 12.0, 320, None)]), destination="GBLIV"), [])

    def test_leaving_port_and_nearing_the_destination_are_skipped(self):
        dublin = (53.35, -6.20)
        self.assertEqual(detect(track(dublin, [(65, 12.0, 90, None)]), destination="GBHLY"), [])  # bearing is fine
        self.assertEqual(detect(track(dublin, [(65, 12.0, 30, None)]), destination="IEROS"), [])  # starts in port
        near_liverpool = step(53.4167, -3.0, 280, 10)  # turning in Liverpool Bay, still within 20 nm
        self.assertEqual(detect(track(near_liverpool, [(65, 6.0, 270, None)]), destination="GBLIV"), [])

    def test_both_contradictions_make_one_finding(self):
        fixes = track(MID_SEA, [(60, 12.0, 320, None), (15, 4.0, 320, "at anchor")])
        [finding] = detect(fixes, destination="GBLIV")
        self.assertEqual(finding["obs"], {"status_mismatch": True, "route_inconsistent": True})
        self.assertIn("navigation status and declared destination contradict the track", finding["reasons"][0])
        self.assertEqual(finding["strength"], 0.5)

    def test_only_fixes_up_to_now_count(self):
        fixes = track(MID_SEA, [(30, 12.0, 320, None), (30, 4.0, 320, "at anchor")])
        self.assertEqual(detect(fixes, now=35 * 60), [])
        self.assertEqual(len(detect(fixes, now=45 * 60)), 1)

    def test_registered(self):
        self.assertIn(declared_vs_actual.detect, assemble.DETECTORS)


class DestinationTextTests(unittest.TestCase):
    def test_locodes_names_and_from_to_text(self):
        self.assertEqual(places.resolve_destination("GBLIV", 53.3, -5.6)["name"], "Liverpool")
        self.assertEqual(places.resolve_destination("IE DUB > GB HLY", 53.3, -5.6)["name"], "Holyhead")
        self.assertEqual(places.resolve_destination("dublin", 53.3, -5.6)["country"], "IE")
        self.assertEqual(places.resolve_destination("Dover Harbour", 51.0, 1.4)["name"], "Dover Harbor")

    def test_a_shared_name_resolves_to_the_nearest_port(self):
        self.assertEqual(places.resolve_destination("BELFAST", 54.0, -5.5)["country"], "GB")
        self.assertEqual(places.resolve_destination("BELFAST", 44.0, -68.0)["country"], "US")

    def test_free_text_stays_unresolved(self):
        for text in (None, "", "   ", "FOR ORDERS", "FISHING GROUNDS"):
            self.assertIsNone(places.resolve_destination(text, 53.3, -5.6), text)


if __name__ == "__main__":
    unittest.main()
