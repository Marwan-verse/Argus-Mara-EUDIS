"""Stopped away from ports: a stop at sea, not at a port or an anchorage, raises rule B12."""

import unittest

from argus import assemble
from argus.assemble import assess_vessel
from argus.countdown import step
from argus.detectors import stop_off_port
from argus.levels import assess

OPEN_SEA = (53.50, -4.80)  # between EWIC and the North Dublin cluster; Holyhead is about 12 nm away
DUBLIN_BAY = (53.30, -6.06)  # inside the rough Dublin Bay anchorage
OFF_HOLYHEAD = (53.33, -4.68)  # about 2 nm from the Holyhead port point


def track(start, legs, interval=60):
    """Fixes once a minute from ``start``; legs are (minutes, sog kn, cog deg)."""
    (lat, lon), fixes, t = start, [], 0
    for minutes, sog, cog in legs:
        for _ in range(minutes):
            fixes.append({"t": t, "lat": lat, "lon": lon, "sog_kn": sog, "cog_deg": cog})
            lat, lon = step(lat, lon, cog, sog * interval / 3600)
            t += interval
    return fixes


def arrive_and_stop(spot, stop_min, approach_min=30, sog=11.0):
    """Approach ``spot`` from the south-west at ``sog`` and stop there for ``stop_min`` minutes."""
    start = step(*spot, 225, sog * approach_min / 60)
    return track(start, [(approach_min, sog, 45), (stop_min, 0.1, 45)])


def vessel(fixes, ship_type=70):
    return {"mmsi": 999000077, "name": "TEST PUFFIN", "ship_type": ship_type, "ais_class": "A",
            "ais_length_m": 150, "track": fixes, "label": "simulated"}


def detect(fixes, now=None, **context):
    return stop_off_port.detect(vessel(fixes), {"now": now, **context})


class StopOffPortTests(unittest.TestCase):
    def test_a_stop_at_sea_for_half_an_hour_scores_b12(self):
        [finding] = detect(arrive_and_stop(OPEN_SEA, 46))
        self.assertEqual(finding["detector"], "stop_off_port")
        self.assertEqual(finding["obs"], {"stopped_offport_min": 45})
        self.assertNotIn("cable_id", finding["related"])  # proximity comes from cable_risk
        self.assertIn("Stopped at sea for 45 min", finding["reasons"][0])
        self.assertIn("Holyhead", finding["reasons"][0])
        factor = next(f for f in assess(finding["obs"])["factors"] if f["code"] == "B12")
        self.assertEqual(factor["points"], 2)

    def test_two_hours_stopped_scores_three_points(self):
        [finding] = detect(arrive_and_stop(OPEN_SEA, 151))
        self.assertEqual(finding["obs"]["stopped_offport_min"], 150)
        self.assertEqual(finding["strength"], 0.6)
        factor = next(f for f in assess(finding["obs"])["factors"] if f["code"] == "B12")
        self.assertEqual((factor["points"], factor["text"]), (3, "Stopped 2.5 h away from any port or designated anchorage"))

    def test_short_stops_and_moving_vessels_give_nothing(self):
        self.assertEqual(detect(arrive_and_stop(OPEN_SEA, 20)), [])
        moving_again = track(step(*OPEN_SEA, 225, 5.5), [(30, 11.0, 45), (60, 0.1, 45), (5, 8.0, 90)])
        self.assertEqual(detect(moving_again), [])

    def test_ports_and_anchorages_are_expected_places_to_stop(self):
        self.assertEqual(detect(arrive_and_stop(DUBLIN_BAY, 90)), [])
        self.assertEqual(detect(arrive_and_stop(OFF_HOLYHEAD, 90)), [])
        scenario_anchorage = [{"name": "Exercise anchorage", "lat": OPEN_SEA[0], "lon": OPEN_SEA[1], "radius_nm": 1.0}]
        self.assertEqual(detect(arrive_and_stop(OPEN_SEA, 90), anchorages=scenario_anchorage), [])
        scenario_port = [{"name": "Exercise pier", "lat": OPEN_SEA[0] + 0.02, "lon": OPEN_SEA[1]}]
        self.assertEqual(detect(arrive_and_stop(OPEN_SEA, 90), ports=scenario_port), [])

    def test_fishing_vessels_stop_at_sea_as_part_of_their_work(self):
        fixes = arrive_and_stop(OPEN_SEA, 90)
        self.assertEqual(stop_off_port.detect(vessel(fixes, ship_type=30), {}), [])

    def test_a_long_reception_gap_ends_the_stop(self):
        fixes = arrive_and_stop(OPEN_SEA, 60)
        later = [{**fix, "t": fix["t"] + 3600} for fix in fixes[-20:]]  # 40 min gap, then 20 min stopped
        self.assertEqual(detect(fixes + later), [])
        self.assertEqual(stop_off_port.latest_stop(fixes + later)[0]["t"], later[0]["t"])

    def test_missing_speed_is_taken_from_the_positions(self):
        fixes = [{key: value for key, value in fix.items() if key != "sog_kn"} for fix in arrive_and_stop(OPEN_SEA, 47)]
        [finding] = detect(fixes)  # the first stopped fix still shows the approach speed from the positions
        self.assertEqual(finding["obs"]["stopped_offport_min"], 45)

    def test_only_fixes_up_to_now_count(self):
        fixes = arrive_and_stop(OPEN_SEA, 90)
        self.assertEqual(detect(fixes, now=30 * 60 + 20 * 60), [])  # 20 min into the stop
        [finding] = detect(fixes, now=30 * 60 + 40 * 60)
        self.assertEqual(finding["obs"]["stopped_offport_min"], 40)

    def test_registered_and_merged_with_the_cable_cues(self):
        self.assertIn(stop_off_port.detect, assemble.DETECTORS)
        line = {"id": "test-line", "name": "Test line", "kind": "power", "label": "simulated",
                "path": [[OPEN_SEA[0] - 4 / 60, -5.5], [OPEN_SEA[0] - 4 / 60, -4.2]], "anchor_reachable": None,
                "min_depth_m": None}
        result = assess_vessel(vessel(arrive_and_stop(OPEN_SEA, 46)), {"cables": [line]})
        codes = {factor["code"] for factor in result["assessment"]["factors"] if factor["points"]}
        self.assertTrue({"B12", "P3", "A1"} <= codes, codes)
        self.assertEqual(result["assessment"]["level"], "medium")


if __name__ == "__main__":
    unittest.main()
