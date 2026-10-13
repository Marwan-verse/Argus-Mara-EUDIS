"""The desktop replay shows a labelled predicted area during the AIS gap, never a fake fix."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import desktop_prediction
from desktop_ais import DesktopAIS
from run_gui import ArgusApp, REAPPEARANCE_SHOW_S, load_demo

NOW = 1_800_000_000.0
STALE_S = 900


def contact(age_s, sog=12.0, cog=90.0):
    return {"mmsi": "250000001", "lat": 53.3, "lon": -6.0, "sog_kn": sog, "cog_deg": cog,
            "received_s": NOW - age_s}


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

    def test_gap_draws_explained_areas_marker_and_worst_case(self):
        app = self.app_at(2900)
        app.map_zoom = 11  # Close enough for the in-place area labels.
        dark = app._dark_state()
        prediction = dark["position"]["prediction"]
        desktop_prediction.draw_areas(app, prediction)
        app.map.create_polygon.assert_called_once()
        self.assertEqual(app.map.create_polygon.call_args.kwargs["fill"], desktop_prediction.CONE_FILL)
        texts = [c.kwargs["text"] for c in app.map.create_text.call_args_list]
        self.assertIn("could reach · max 15 kn", texts)
        self.assertIn("likely area", texts)
        app.map.reset_mock()
        desktop_prediction.draw_worst_case(app, prediction, dark["countdown"])
        self.assertTrue(app.map.create_line.call_args.kwargs["arrow"])
        self.assertIn("worst case:\ncable in 71 min", [c.kwargs["text"] for c in app.map.create_text.call_args_list])
        app.map.reset_mock()
        desktop_prediction.draw_marker(app, prediction)
        desktop_prediction.draw_banner(app, prediction)
        texts = [c.kwargs["text"] for c in app.map.create_text.call_args_list]
        self.assertIn("last AIS", texts)
        self.assertIn("AIS LOST 20 MIN AGO  ·  POSITION PREDICTED, NOT OBSERVED", texts)

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


class LivePredictionTests(unittest.TestCase):
    def test_only_stale_and_recent_enough_contacts_are_predicted(self):
        self.assertIsNone(desktop_prediction.live_prediction(contact(STALE_S), NOW, STALE_S))
        self.assertIsNone(desktop_prediction.live_prediction(contact(4 * 3600), NOW, STALE_S))
        self.assertIsNone(desktop_prediction.live_prediction({**contact(1800), "received_s": None}, NOW, STALE_S))
        prediction = desktop_prediction.live_prediction(contact(1800), NOW, STALE_S)
        self.assertEqual(prediction["elapsed_s"], 1800)
        self.assertEqual(prediction["label"], "predicted")
        self.assertAlmostEqual(prediction["reachable"]["radius_nm"], 7.5)
        self.assertIsNotNone(prediction["cone"])

    def test_slow_contact_gets_circle_without_noisy_course(self):
        prediction = desktop_prediction.live_prediction(contact(1800, sog=0.4, cog=211.0), NOW, STALE_S)
        self.assertIsNone(prediction["cone"])
        self.assertEqual((prediction["lat"], prediction["lon"]), (53.3, -6.0))

    def test_extent_frames_the_reachable_circle(self):
        prediction = desktop_prediction.live_prediction(contact(1800), NOW, STALE_S)
        north, south, east, west = desktop_prediction.extent_points(prediction)
        self.assertAlmostEqual(north[0] - south[0], 15 / 60)
        self.assertAlmostEqual(east[0], 53.3)
        self.assertGreater(east[1], -6.0)
        self.assertLess(west[1], -6.0)

    def test_fast_contact_raises_assumed_maximum(self):
        prediction = desktop_prediction.live_prediction(contact(3600, sog=20.0), NOW, STALE_S)
        self.assertAlmostEqual(prediction["reachable"]["v_max_kn"], 24.0)

    def test_tracker_predicts_selected_contact_and_respects_layer(self):
        tracker = DesktopAIS.__new__(DesktopAIS)
        tracker.state = SimpleNamespace(vessels={"250000001": contact(1800)}, feed={"stale_seconds": STALE_S})
        layer = Mock(get=Mock(return_value=True))
        tracker.app = SimpleNamespace(map_layers={"Dark prediction": layer})
        tracker.selected = None
        self.assertIsNone(tracker.selected_prediction(NOW))
        tracker.selected = "250000001"
        self.assertEqual(tracker.selected_prediction(NOW)["elapsed_s"], 1800)
        layer.get.return_value = False
        self.assertIsNone(tracker.selected_prediction(NOW))


if __name__ == "__main__":
    unittest.main()
