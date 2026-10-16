"""Dragging slides the drawn map without full redraws; an animated zoom lands exactly where an instant one did."""
import gc
from types import SimpleNamespace
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.live_client import LiveState


class MapMotionTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        # Collect earlier tests' Tk objects here, on the main thread. If a tile or weather worker
        # collects them instead, a Font.__del__ waits forever on its destroyed interpreter.
        gc.collect()
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes('-alpha', 0)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': '',
                                       'ARGUS_REDUCED_MOTION': '0'}):
            self.app = ArgusApp(self.root, *load_demo())
        self.app.ais_tracker.cache_path = None
        self.app.ais_tracker.state = LiveState()
        self.root.update()
        self.app._draw_map()

    def tearDown(self):
        if hasattr(self, 'app'):
            self.root.update()
            self.assertEqual(self.errors, [])
            self.app.close()
            gc.collect()  # This test's Tk objects too, before any worker thread runs

    def event(self, x, y):
        return SimpleNamespace(x=x, y=y)

    def test_drag_moves_items_defers_redraws_and_keeps_overlays_fixed(self):
        app = self.app
        canvas = app.map
        moving = next(item for item in canvas.find_all() if 'chart-fixed' not in canvas.gettags(item))
        fixed = canvas.find_withtag('map_title')[0]
        before_moving, before_fixed = canvas.coords(moving), canvas.coords(fixed)
        center = app.map_center
        app._pan_start(self.event(300, 300))
        with patch.object(app, '_draw_map', wraps=app._draw_map) as draw:
            app._pan_move(self.event(340, 320))
            self.assertEqual(canvas.coords(moving)[:2], [before_moving[0] + 40, before_moving[1] + 20])
            self.assertEqual(canvas.coords(fixed), before_fixed)
            app._draw_map()  # A live AIS update during the drag waits for the drag to end
            self.assertTrue(app.motion.pending_redraw)
            self.assertNotEqual(app.map_center, center)
            app._pan_end(self.event(340, 320))
            self.assertFalse(app.motion.busy)
            self.assertFalse(app.motion.pending_redraw)
            self.assertGreaterEqual(draw.call_count, 2)
        # The release redraws everything, so the title is a new item; it is still where it was.
        self.assertEqual(canvas.coords(canvas.find_withtag('map_title')[0]), before_fixed)

    def test_animated_zoom_ends_at_the_same_zoom_and_centre_as_an_instant_zoom(self):
        from run_gui import world_to_geo
        app = self.app
        x, y = 200, 160
        under = world_to_geo(*app._world_at(x, y), app.map_zoom)
        zoom = app.map_zoom
        app._zoom_at(1, x, y)
        self.assertTrue(app.motion.busy)
        deadline = time.monotonic() + 3
        while app.motion.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(app.motion.busy)
        self.assertEqual(app.map_zoom, zoom + 1)
        after = world_to_geo(*app._world_at(x, y), app.map_zoom)
        self.assertAlmostEqual(under[0], after[0], places=9)
        self.assertAlmostEqual(under[1], after[1], places=9)
        self.assertFalse(app.map.find_withtag('zoom-raster'))
        # Steps taken while a zoom glides join it: one movement, and the point under the pointer stays put.
        app._zoom_at(1, x, y)
        self.root.update()
        app._zoom_at(1, x + 30, y - 20)  # The pointer moved a little between wheel notches
        app._zoom_at(-1, x + 30, y - 20)
        self.assertTrue(app.motion.animating)
        deadline = time.monotonic() + 3
        while app.motion.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(app.map_zoom, zoom + 2)
        self.assertFalse(app.motion.busy)

    def test_a_point_seen_mid_glide_stays_under_the_pointer_when_zooming_again(self):
        from run_gui import world_to_geo
        app = self.app
        app._zoom_at(1, 220, 180)
        for _ in range(3):
            self.root.update()  # Part of the glide: what is on screen is not yet the target view
        seen = world_to_geo(*app._world_at(*app.motion.to_target(300, 200)), app.map_zoom)
        app._zoom_at(1, 300, 200)
        app.motion.finish_zoom()
        landed = world_to_geo(*app._world_at(300, 200), app.map_zoom)
        self.assertAlmostEqual(seen[0], landed[0], places=9)
        self.assertAlmostEqual(seen[1], landed[1], places=9)


if __name__ == '__main__':
    unittest.main()
