"""Temporal support uses feasible endpoint areas, never invented exact tracks."""
import unittest

from argus.space import position_at
from argus.tracking import temporal_support, within_temporal_support


class TrackingSupportTests(unittest.TestCase):
    def evidence(self, track, when):
        return {'temporal_support': temporal_support(track, when, position_at(track, when))}

    def test_exact_fix_has_zero_temporal_displacement_but_not_claimed_sensor_accuracy(self):
        point = {'t': 100, 'lat': 53, 'lon': -6}
        support = self.evidence([point], 100)
        self.assertEqual(support['temporal_support']['center_radius_m'], 0)
        self.assertTrue(within_temporal_support(point, support))
        self.assertFalse(within_temporal_support({'lat': 53.01, 'lon': -6}, support))
        self.assertIn('not a confidence interval', support['temporal_support']['caveat'])

    def test_projected_course_does_not_rule_out_a_turn(self):
        track = [{'t': 0, 'lat': 53, 'lon': -6, 'sog_kn': 10, 'cog_deg': 90}]
        support = self.evidence(track, 300)
        self.assertGreater(support['temporal_support']['center_radius_m'], 1000)
        self.assertTrue(within_temporal_support({'lat': 53.04, 'lon': -6}, support))

    def test_both_bracketing_fixes_constrain_the_possible_position(self):
        track = [{'t': 0, 'lat': 53, 'lon': -6}, {'t': 600, 'lat': 53.1, 'lon': -6}]
        support = self.evidence(track, 300)
        self.assertTrue(within_temporal_support({'lat': 53.05, 'lon': -6}, support))
        self.assertFalse(within_temporal_support({'lat': 52.9, 'lon': -6}, support))
        self.assertEqual(len(support['temporal_support']['fixes']), 2)

    def test_future_only_and_expired_positions_do_not_get_support(self):
        point = {'t': 100, 'lat': 53, 'lon': -6, 'sog_kn': 10, 'cog_deg': 90}
        self.assertIsNone(temporal_support([point], 0, point))
        self.assertIsNone(temporal_support([point], 401, point))
        self.assertIsNone(within_temporal_support(point, {}))
