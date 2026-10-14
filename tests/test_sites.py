"""Stop and site-loiter detectors turn timed tracks into the documented observations."""
import unittest

from argus.countdown import nm_between
from argus.levels import assess
from argus.sites import (ANCHORAGES, SITES, circle_track, load_ports, loiter_hours, observe, stop_track,
                         stopped_minutes, zone_path)


class SiteDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ports = load_ports()

    def test_bundled_ports_load(self):
        self.assertGreater(len(self.ports), 1000)
        self.assertTrue(any(name == "Cobh" for name, _lat, _lon in self.ports))

    def test_stop_away_from_ports_is_timed(self):
        fixes = stop_track(54.25, -9.15, 150, 140)
        self.assertAlmostEqual(stopped_minutes(fixes, self.ports), 140, delta=3)  # 3 min fixes

    def test_stop_near_a_port_anchorage_or_by_a_fishing_vessel_is_ignored(self):
        self.assertEqual(stopped_minutes(stop_track(51.85, -8.30, 90, 120), self.ports), 0)  # Cobh
        name, lat, lon, _radius = ANCHORAGES[0]
        self.assertEqual(stopped_minutes(stop_track(lat, lon, 90, 120), self.ports), 0, name)
        self.assertEqual(stopped_minutes(stop_track(54.25, -9.15, 150, 140), self.ports, "Fishing vessel"), 0)

    def test_moving_vessel_or_long_gap_ends_the_stop(self):
        fixes = stop_track(54.25, -9.15, 150, 140)
        moving = fixes + [{**fixes[-1], "t": fixes[-1]["t"] + 180, "sog_kn": 6.0}]
        self.assertEqual(stopped_minutes(moving, self.ports), 0)
        gapped = fixes + [{**fixes[-1], "t": fixes[-1]["t"] + 3600}]
        self.assertEqual(stopped_minutes(gapped, self.ports), 0)

    def test_loiter_counts_time_inside_the_zone_only(self):
        _name, _kind, lat, lon, _radius = SITES["haulbowline"]
        self.assertAlmostEqual(loiter_hours(circle_track(lat, lon, 0.35, 2.5), "haulbowline"), 2.5, places=1)
        self.assertEqual(loiter_hours(circle_track(lat + 0.2, lon, 0.35, 2.5), "haulbowline"), 0)

    def test_transit_through_a_zone_is_not_loitering(self):
        _name, _kind, lat, lon, radius = SITES["arklow-bank"]
        transit = [{"t": index * 180, "lat": lat + (index - 10) * 0.025, "lon": lon, "sog_kn": 10.0}
                   for index in range(21)]
        self.assertLess(loiter_hours(transit[:11], "arklow-bank"), 1)
        self.assertNotIn("site_loiter_hours", observe(transit[:11], self.ports))

    def test_zone_ring_is_closed_at_the_radius(self):
        _name, _kind, lat, lon, radius = SITES["killala-landfall"]
        ring = zone_path("killala-landfall")
        self.assertEqual(ring[0], ring[-1])
        for point in ring:
            self.assertAlmostEqual(nm_between(lat, lon, *point), radius, places=2)

    def test_observations_score_with_the_documented_cues(self):
        fixes = circle_track(51.838, -8.305, 0.35, 2.5)
        observations = observe(fixes, self.ports, "Survey vessel")
        self.assertEqual(observations["site_id"], "haulbowline")
        self.assertTrue(observations["in_zone"])
        result = assess({**observations, "ais_gap_min": 30})
        self.assertEqual(result["basis"], "B3 I2 P4 A2 C0 = 11")
        self.assertEqual(result["level"], "high")
        codes = {factor["code"] for factor in result["factors"]}
        self.assertTrue({"B13", "P1", "A4"} <= codes)


class StopAndSiteRuleTests(unittest.TestCase):
    def test_stop_points_rise_after_two_hours(self):
        self.assertEqual(assess({"stopped_offport_min": 45})["groups"]["B"], 2)
        self.assertEqual(assess({"stopped_offport_min": 150})["groups"]["B"], 3)
        self.assertEqual(assess({"stopped_offport_min": 20})["groups"]["B"], 0)

    def test_stop_in_open_water_alone_is_not_listed(self):
        self.assertEqual(assess({"stopped_offport_min": 45})["level"], "none")

    def test_site_proximity_needs_a_behaviour_or_identity_cue(self):
        passing = assess({"in_zone": True, "asset_class": "naval_base"})
        self.assertEqual(passing["level"], "none")
        self.assertEqual(passing["score"], 0)

    def test_stop_inside_a_landfall_zone_is_high_and_critical_needs_more(self):
        observations = {"stopped_offport_min": 150, "site_loiter_hours": 2.5, "in_zone": True,
                        "asset_class": "landfall"}
        self.assertEqual(assess(observations)["basis"], "B4 I0 P4 A2 C0 = 10")
        self.assertEqual(assess(observations)["level"], "high")
        self.assertEqual(assess({**observations, "ais_gap_min": 40})["level"], "critical")

    def test_wind_farm_scores_less_than_a_landfall(self):
        observations = {"site_loiter_hours": 1.6, "in_zone": True}
        wind = assess({**observations, "asset_class": "wind_farm"})
        landfall = assess({**observations, "asset_class": "landfall"})
        self.assertEqual(wind["groups"]["A"], 1)
        self.assertEqual(landfall["groups"]["A"], 2)
        self.assertIn("Site at risk: offshore wind farm", [f["text"] for f in wind["factors"]])


if __name__ == "__main__":
    unittest.main()
