"""Native replay behavior shared with the JSON exercise, without a display."""

import unittest
from html import unescape
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from run_gui import (ArgusApp, MAX_IMAGERY_ZOOM, MAX_MAP_ZOOM, MIN_MAP_ZOOM,
                     ONLINE_MAP, fix_at, load_demo, response_status,
                     trail_sections, world_to_geo)


class DesktopReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario, cls.alerts, _ = load_demo()
        cls.track = cls.scenario["vessels"][0]["track"]

    def test_ais_gap_has_no_invented_fix_or_joined_trail(self):
        self.assertIsNone(fix_at(self.track, 2400))
        sections = trail_sections(self.track, 3000)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][-1], (self.track[29]["lat"], self.track[29]["lon"]))

    def test_alert_uses_observed_fix_and_timely_options(self):
        alert = self.alerts["alerts"][0]
        self.assertEqual(alert["t"], 5400)
        self.assertEqual(fix_at(self.track, alert["t"])["sog_kn"], 9.1)
        statuses = {option["asset"]: response_status(option, alert["eta_earliest_s"])
                    for option in alert["options"]}
        self.assertEqual(sum(status == "In time" for status in statuses.values()), 2)

    def test_saved_decision_record_is_standalone_and_explicit(self):
        app = ArgusApp.__new__(ArgusApp)
        app.scenario = self.scenario
        app.alert = self.alerts["alerts"][0]
        app.vessel = self.scenario["vessels"][0]
        app.cable = self.scenario["cables"][0]
        app.position_s = app.alert["t"]
        app.approved = {"time": app.position_s, "asset": "VHF hail, Dublin coast radio",
                        "assumed_arrival_s": 120, "label": "simulated"}
        app.root = None
        with TemporaryDirectory() as directory:
            output = Path(directory) / "record.html"
            with patch("run_gui.filedialog.asksaveasfilename", return_value=str(output)), \
                    patch("run_gui.messagebox.showinfo"):
                app.save_record()
            record = output.read_text(encoding="utf-8")
        self.assertIn("VHF hail, Dublin coast radio", record)
        self.assertIn("No operational action was sent", record)
        self.assertIn('"eta_expected_s": 4411', unescape(record))
        self.assertIn("<!doctype html>", record)


class DesktopMapScrollTests(unittest.TestCase):
    def scroll_app(self):
        app = ArgusApp.__new__(ArgusApp)
        app._last_scroll_zoom = (0.0, 0)
        app._zoom_at = Mock()
        app.root = Mock()
        return app

    def wheel_event(self, delta=0, **changes):
        return SimpleNamespace(**{"delta": delta, "num": "??", "state": 0,
                                  "x": 260, "y": 140, **changes})

    def packed_scroll(self, horizontal, vertical):
        value = ((horizontal & 0xffff) << 16) | (vertical & 0xffff)
        return value if value < 0x80000000 else value - 0x100000000

    def test_wheel_notches_zoom_immediately_in_both_directions(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", return_value=10.0):
            for delta in (120, 120, -120):
                self.assertEqual(app._mouse_wheel(self.wheel_event(delta)), "break")
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 260, 140), call(1, 260, 140), call(-1, 260, 140)])

    def test_linux_wheel_buttons_do_not_depend_on_delta(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", return_value=10.0):
            self.assertEqual(app._mouse_wheel(self.wheel_event(num=4)), "break")
            self.assertEqual(app._mouse_wheel(self.wheel_event(num=5)), "break")
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 260, 140), call(-1, 260, 140)])

    def test_bound_wheel_direction_handles_tk9_remapped_button_numbers(self):
        app = self.scroll_app()
        self.assertEqual(app._mouse_wheel(self.wheel_event(num=8), 1), "break")
        self.assertEqual(app._mouse_wheel(self.wheel_event(num=9), -1), "break")
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 260, 140), call(-1, 260, 140)])

    def test_zero_and_shift_horizontal_wheel_events_do_not_zoom(self):
        app = self.scroll_app()
        for event in (self.wheel_event(0), self.wheel_event(120, state=1),
                      self.wheel_event(-1, state=1)):
            with self.subTest(delta=event.delta, state=event.state):
                self.assertEqual(app._mouse_wheel(event), "break")
        app._zoom_at.assert_not_called()
        self.assertEqual(app._last_scroll_zoom, (0.0, 0))

    def test_precise_wheel_burst_is_limited_and_uses_current_cursor(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", side_effect=(.01, .03, .08, .161)):
            for x in (100, 110, 120, 130):
                self.assertEqual(app._mouse_wheel(self.wheel_event(1, x=x)), "break")
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 100, 140), call(1, 130, 140)])
        # A gesture must not leave delayed zoom work after the user stops.
        app.root.after.assert_not_called()
        app.root.after_idle.assert_not_called()

    def test_precise_scroll_reversal_responds_without_waiting(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", side_effect=(10.0, 10.02, 10.03, 10.04)):
            for delta in (1, 1, -1, 1):
                app._zoom_from_scroll(delta, 260, 140, precise=True)
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 260, 140), call(-1, 260, 140), call(1, 260, 140)])

    def test_precise_scroll_resumes_after_the_rate_limit(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", side_effect=(10.0, 10.1, 10.151, 11.0)):
            for _ in range(4):
                app._zoom_from_scroll(-2, 260, 140, precise=True)
        self.assertEqual(app._zoom_at.call_count, 3)
        app._zoom_at.assert_called_with(-1, 260, 140)

    def test_coarse_scroll_is_not_rate_limited(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", return_value=10.0):
            for _ in range(3):
                app._zoom_from_scroll(120, 260, 140, precise=False)
        self.assertEqual(app._zoom_at.call_args_list, [call(1, 260, 140)] * 3)

    def test_touchpad_decodes_vertical_direction_independently_of_horizontal(self):
        app = self.scroll_app()
        with patch("run_gui.time.monotonic", side_effect=(10.0, 10.2)):
            for horizontal, vertical in ((-3, 5), (4, -5)):
                event = self.wheel_event(self.packed_scroll(horizontal, vertical))
                self.assertEqual(app._touchpad_scroll(event), "break")
        self.assertEqual(app._zoom_at.call_args_list,
                         [call(1, 260, 140), call(-1, 260, 140)])

    def test_horizontal_only_touchpad_scroll_does_not_zoom(self):
        app = self.scroll_app()
        for horizontal in (-30, 0, 30):
            with self.subTest(horizontal=horizontal):
                event = self.wheel_event(self.packed_scroll(horizontal, 0))
                self.assertEqual(app._touchpad_scroll(event), "break")
        app._zoom_at.assert_not_called()
        self.assertEqual(app._last_scroll_zoom, (0.0, 0))

    def map_app(self, zoom=8, mode="Offline coastline"):
        app = ArgusApp.__new__(ArgusApp)
        app.map_zoom = zoom
        app.map_center = (53.15, -5.55)
        app._map_size = (860, 520)
        app.map_mode = SimpleNamespace(get=lambda: mode)
        app._draw_map = Mock()
        app._schedule_tile_refresh = Mock()
        app._schedule_port_directory = Mock()
        app.port_visible = SimpleNamespace(get=lambda: False)
        return app

    def test_zoom_keeps_the_geographic_point_under_the_cursor(self):
        app = self.map_app()
        x, y = 130, 170
        before = world_to_geo(*app._world_at(x, y), app.map_zoom)
        app._zoom_at(1, x, y)
        after = world_to_geo(*app._world_at(x, y), app.map_zoom)
        self.assertEqual(app.map_zoom, 9)
        self.assertAlmostEqual(before[0], after[0], places=10)
        self.assertAlmostEqual(before[1], after[1], places=10)
        app._draw_map.assert_called_once_with(force_static=True)
        app._schedule_tile_refresh.assert_called_once_with()

    def test_zoom_clamps_to_offline_imagery_and_minimum_limits(self):
        cases = (("Offline coastline", MAX_MAP_ZOOM - 1, 10, MAX_MAP_ZOOM),
                 (ONLINE_MAP, MAX_IMAGERY_ZOOM - 1, 10, MAX_IMAGERY_ZOOM),
                 ("Offline coastline", MIN_MAP_ZOOM + 1, -10, MIN_MAP_ZOOM))
        for mode, initial, amount, expected in cases:
            with self.subTest(mode=mode, amount=amount):
                app = self.map_app(initial, mode)
                app._zoom_at(amount, 130, 170)
                self.assertEqual(app.map_zoom, expected)

    def test_zoom_at_a_limit_does_not_move_the_map_or_request_tiles(self):
        for mode, zoom, amount in (("Offline coastline", MAX_MAP_ZOOM, 1),
                                   (ONLINE_MAP, MAX_IMAGERY_ZOOM, 1),
                                   ("Offline coastline", MIN_MAP_ZOOM, -1)):
            with self.subTest(mode=mode, zoom=zoom):
                app = self.map_app(zoom, mode)
                center = app.map_center
                app._zoom_at(amount, 130, 170)
                self.assertEqual(app.map_center, center)
                self.assertEqual(app.map_zoom, zoom)
                app._draw_map.assert_not_called()
                app._schedule_tile_refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
