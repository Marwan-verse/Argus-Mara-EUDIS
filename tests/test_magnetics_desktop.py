"""Magnetics panel logic without a window: the opt-in storm feed, the planner inputs, export and map drawing."""

import json
import queue
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from argus import geomag
from desktop_magnetics import TAG, DesktopMagnetics
from test_survey_plan import CABLE, drag_track

UTC = timezone.utc


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def panel(folder=None, app=None):
    magnetics = DesktopMagnetics.__new__(DesktopMagnetics)
    magnetics.app = app or SimpleNamespace(root=Mock(), _draw_map=Mock())
    magnetics.data_dir = Path(folder or tempfile.gettempdir())
    magnetics.cache_path = magnetics.data_dir / "geomag-latest.json"
    magnetics.fetch_kp, magnetics.fetch_valentia = Mock(), Mock()
    magnetics.live = Var(False)
    magnetics.status = magnetics.cached = None
    magnetics.message = ""
    magnetics.kp_rows = magnetics.val_rows = None
    magnetics._val_fetched = -1e9
    magnetics.generation = 0
    magnetics.queue = queue.Queue()
    magnetics.executor = Mock()
    magnetics._refresh_after = magnetics._poll_after = None
    magnetics.chip = None
    magnetics.source, magnetics.depth, magnetics.mass = Var("exercise"), Var(""), Var("10")
    magnetics.platform = Var("USV tow, 10 m above seabed")
    magnetics.show_plan = Var(True)
    magnetics.plan = magnetics.plan_error = magnetics.saved_path = None
    magnetics.refresh_storm = Mock()
    magnetics.refresh_plan = Mock()
    magnetics._show_chip, magnetics._hide_chip, magnetics._update_chip = Mock(), Mock(), Mock()
    return magnetics


def exercise_app(position_s=None):
    track = [{**fix, "t": fix["t"] - drag_track()[0]["t"]} for fix in drag_track()]
    return SimpleNamespace(
        root=Mock(), _draw_map=Mock(), position_s=position_s,
        scenario={"t0_utc": "2026-10-17T08:00:00Z", "cables": [{"id": "line-x", "path": [list(p) for p in CABLE]}]},
        vessel={"name": "FICTIONAL TEST", "label": "simulated", "track": track},
        cable={"id": "line-x", "name": "Test line", "path": [list(p) for p in CABLE], "min_depth_m": 40})


class StormFeedTests(unittest.TestCase):
    def test_switching_on_requests_once_and_off_drops_late_results(self):
        magnetics = panel()
        magnetics.live.set(True)
        magnetics.toggle_live()
        magnetics.executor.submit.assert_called_once()
        magnetics._show_chip.assert_called_once()
        magnetics.app.root.after.assert_called_once()  # the next refresh
        magnetics.live.set(False)
        magnetics.toggle_live()
        self.assertEqual(magnetics.message, "Live magnetic data off · no network requests")
        magnetics._hide_chip.assert_called_once()
        magnetics.queue.put((1, {"now": datetime.now(UTC), "kp": []}))  # from before switching off
        magnetics.apply = Mock()
        magnetics._poll()
        magnetics.apply.assert_not_called()

    def test_results_set_the_status_chip_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            magnetics = panel(folder)
            now = datetime(2026, 10, 16, 12, 6, tzinfo=UTC)
            values = [{"time": datetime(2026, 10, 16, 12, minute, tzinfo=UTC), "value": 19640.0 + 30 * minute}
                      for minute in range(5)]
            magnetics.apply({"now": now, "kp": [{"time": now, "kp": 2.0}], "val": values})
            self.assertEqual((magnetics.status["tier"], magnetics.status["name"]), (1, "Active"))
            self.assertTrue(magnetics.message.startswith("Updated 12:06 UTC"))
            magnetics._update_chip.assert_called_once()
            self.assertEqual(geomag.load_cache(magnetics.cache_path)["tier"], 1)
            magnetics.apply({"now": now, "kp_error": OSError("down")})  # keeps the last Valentia rows
            self.assertIn("NOAA SWPC unavailable (OSError)", magnetics.message)
            self.assertEqual(magnetics.status["dhdt"], 30.0)


class PlannerTests(unittest.TestCase):
    def test_exercise_plan_uses_replay_time_and_route_depth(self):
        magnetics = panel(app=exercise_app())
        track, path, subject, depth = magnetics.plan_inputs()
        self.assertEqual(track[0]["t"], datetime(2026, 10, 17, 8, 0, tzinfo=UTC).timestamp())
        self.assertIn("FICTIONAL TEST", subject)
        self.assertEqual(depth, 40)
        magnetics.plan_search()
        self.assertIsNone(magnetics.plan_error)
        self.assertEqual(magnetics.plan["depth_source"], "the route's minimum depth (scenario)")
        self.assertEqual(magnetics.plan["width_m"], 2 * (50 + 3 * 40 + 100))
        magnetics.app._draw_map.assert_called_with(force_static=True)

    def test_before_the_crossing_the_plan_explains_itself(self):
        magnetics = panel(app=exercise_app(position_s=30 * 60))
        magnetics.plan_search()
        self.assertIsNone(magnetics.plan)
        self.assertTrue(magnetics.plan_error.startswith("No cable crossing yet"))

    def test_typed_values_are_checked(self):
        magnetics = panel(app=exercise_app())
        magnetics.depth.set("deep")
        magnetics.plan_search()
        self.assertEqual(magnetics.plan_error, "Water depth must be a number")
        magnetics.depth.set("25 m")
        magnetics.mass.set("20")
        magnetics.plan_search()
        self.assertEqual((magnetics.plan["depth_m"], magnetics.plan["mass_t"]), (25.0, 20.0))
        self.assertEqual(magnetics.plan["depth_source"], "operator entry")

    def test_selected_alert_plans_from_its_shown_track(self):
        app = exercise_app()
        item = {"id": "a1", "title": "Loitering near Test line", "line_id": "line-x",
                "track": [(53.40, -5.33), (53.40, -5.31)], "lat": 53.40, "lon": -5.295}
        app.alert_board = SimpleNamespace(selected="a1", by_id={"a1": item})
        magnetics = panel(app=app)
        magnetics.source.set("alert")
        track, path, subject, depth = magnetics.plan_inputs()
        self.assertEqual(track[-1], (53.40, -5.295))
        self.assertEqual(subject, "Alert: Loitering near Test line")
        self.assertEqual(path, CABLE)
        app.alert_board.selected = None
        with self.assertRaisesRegex(ValueError, "Select an alert"):
            magnetics.plan_inputs()

    def test_save_and_draw(self):
        with tempfile.TemporaryDirectory() as folder:
            app = exercise_app()
            app.map = Mock()
            app.map_zoom = 9
            app._project = lambda lat, lon: (lon * 100, -lat * 100)
            app._points = lambda points: [value for lat, lon in points for value in app._project(lat, lon)]
            magnetics = panel(folder, app)
            magnetics.plan_search()
            path = magnetics.save_plan()
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["type"], "FeatureCollection")
            self.assertEqual(saved["properties"]["label"], "assumption")
            magnetics.draw()
            lines = [call for call in app.map.create_line.call_args_list if call.kwargs.get("tags") == (TAG,)]
            self.assertEqual(len(lines), 1 + len(magnetics.plan["lines"]))  # corridor plus survey lines
            self.assertEqual(app.map.create_oval.call_count, len(magnetics.plan["priorities"]))
            app.map.reset_mock()
            magnetics.show_plan.set(False)
            magnetics.draw()
            app.map.create_line.assert_not_called()


if __name__ == "__main__":
    unittest.main()
