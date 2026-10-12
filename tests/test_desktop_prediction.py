"""The desktop replay shows a labelled predicted area during the AIS gap, never a fake fix."""

import unittest
from unittest.mock import Mock

from run_gui import ArgusApp, REAPPEARANCE_SHOW_S, load_demo


class DesktopPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario, cls.alerts, _ = load_demo()

    def app_at(self, position_s):
        app = ArgusApp.__new__(ArgusApp)
        app.scenario = self.scenario
        app.vessel = self.scenario["vessels"][0]
        app.cable = self.scenario["cables"][0]
        app.position_s = position_s
        app.map = Mock()
        app._map_size = (900, 700)
        app.map_center = (53.05, -5.42)
        app.map_zoom = 9
        for name in ("state_label", "earliest_label", "distance_label"):
            setattr(app, name, Mock())
        return app

    def test_prediction_exists_only_inside_the_gap(self):
        self.assertIsNone(self.app_at(1740)._dark_state())
        self.assertIsNone(self.app_at(3000)._dark_state())
        dark = self.app_at(2400)._dark_state()
        self.assertEqual(dark["position"]["status"], "predicted")
        self.assertEqual(dark["countdown"]["last_fix_t"], 1740)

    def test_gap_draws_circle_cone_and_labelled_marker(self):
        app = self.app_at(2400)
        labels = []
        app._draw_dark_prediction(app._dark_state(), labels)
        app.map.create_polygon.assert_called_once()
        self.assertEqual(app.map.create_polygon.call_args.kwargs["stipple"], "gray25")
        dashed = [c for c in app.map.create_oval.call_args_list if c.kwargs.get("dash")]
        self.assertEqual(len(dashed), 2)
        self.assertIn("PREDICTED", labels[0][2])
        self.assertIn("±2.8 nm", labels[0][2])

    def test_return_verdict_is_shown_for_a_limited_time(self):
        self.assertIsNone(self.app_at(2400)._reappearance())
        check = self.app_at(3000)._reappearance()
        self.assertEqual((check["before"]["t"], check["after"]["t"], check["verdict"]), (1740, 3000, "consistent"))
        labels = []
        self.app_at(3060)._draw_reappearance(labels)
        self.assertIn("CONSISTENT", labels[0][2])
        labels = []
        self.app_at(3000 + REAPPEARANCE_SHOW_S + 60)._draw_reappearance(labels)
        self.assertEqual(labels, [])

    def test_panel_shows_worst_case_countdown_while_dark(self):
        app = self.app_at(2400)
        app._render_prediction_status()
        self.assertIn("predicted\nWorst-case cable contact in 01:19:14",
                      app.state_label.configure.call_args.kwargs["text"])
        self.assertIn("Worst-case cable contact in 01:19:14", app.earliest_label.configure.call_args.kwargs["text"])
        self.assertIn("not observed", app.distance_label.configure.call_args.kwargs["text"])
        app = self.app_at(3600)
        app._render_prediction_status()
        app.earliest_label.configure.assert_not_called()
        self.assertIn("consistent", app.distance_label.configure.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
