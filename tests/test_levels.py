"""Risk levels follow the documented points, gates, overrides and caps."""
import unittest

from argus.levels import assess


class LevelTests(unittest.TestCase):
    def check(self, observations, level, score=None):
        result = assess(observations)
        self.assertEqual(result["level"], level, result["basis"] + " " + " ".join(result["notes"]))
        if score is not None:
            self.assertEqual(result["score"], score, result["basis"])
        return result

    def test_exercise_alert_is_high_then_critical_near_the_cable(self):
        exercise = {"speed_drop_pct": 24, "course_change_deg": 30, "ais_gap_min": 20,
                    "dark_radar_contact": True, "length_mismatch_pct": 26.7, "eta_min": 61,
                    "asset_class": "telecom"}
        result = self.check(exercise, "high", 11)
        self.assertEqual(result["basis"], "B4 I3 P3 A1 C0 = 11")
        self.check({**exercise, "eta_min": 25}, "critical", 12)

    def test_watch_listed_transit_without_behaviour_stays_low(self):
        result = self.check({"identity_changes": 1, "watchlist": True, "flag_risk": True,
                             "distance_nm": 4, "asset_class": "telecom"}, "low", 4)
        proximity = next(f for f in result["factors"] if f["group"] == "proximity")
        self.assertEqual(proximity["points"], 0)
        self.assertIn("counts only with", proximity["text"])

    def test_repeated_trawling_over_a_cluster_is_high(self):
        self.check({"passes_6h": 4, "in_corridor": True, "asset_class": "cluster",
                    "asset_vulnerable": True}, "high", 10)

    def test_anchored_ship_in_a_gale_is_medium_until_it_drags(self):
        anchored = {"anchored_near_cable": True, "in_corridor": True, "asset_class": "telecom",
                    "gale_warning": True}
        self.check(anchored, "medium", 8)
        self.check({**anchored, "anchored_near_cable": False, "dragging_at_anchor": True, "sog_kn": 1.4},
                   "high", 10)

    def test_research_vessel_holding_over_a_deep_link_is_critical(self):
        self.check({"hover_hours": 3, "special_vessel": True, "deep_segment": True, "ais_gap_min": 35,
                    "in_corridor": True, "asset_class": "sole_link", "watchlist": True}, "critical", 14)

    def test_normal_ferry_is_not_listed(self):
        self.check({"in_corridor": True, "asset_class": "telecom"}, "none", 0)

    def test_gates_overrides_and_caps(self):
        # Two fishing passes reach the High band but lack a strong behaviour pattern.
        gated = self.check({"fishing_near_corridor": True, "in_corridor": True, "asset_class": "cluster",
                            "asset_vulnerable": True}, "medium", 9)
        self.assertTrue(any("High requires" in note for note in gated["notes"]))
        # Identity and context alone never exceed Medium.
        self.check({"no_ais": True, "spoof_signs": True, "in_corridor": True, "asset_class": "power",
                    "watchlist": True}, "medium", 11)
        self.check({"slowdown_near_corridor": True, "distance_nm": 2, "ignored_instruction": True,
                    "asset_class": "telecom"}, "critical")
        self.check({"slowdown_near_corridor": True, "ais_gap_min": 15, "distance_nm": 3,
                    "asset_class": "power", "no_response_in_time": True}, "high")
        self.check({"hover_hours": 5, "special_vessel": True, "deep_segment": True, "in_corridor": True,
                    "asset_class": "transatlantic", "authorised": True}, "low")


if __name__ == "__main__":
    unittest.main()
