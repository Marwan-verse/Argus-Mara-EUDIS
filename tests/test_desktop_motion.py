"""While the map moves it is one picture of everything on the chart; when it stops, every item is back where
the geography says. Nothing may stay behind at its old place (cables, ships and alerts used to stay put)."""
import gc
import sys
from types import SimpleNamespace
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.live_client import LiveState

KEEP = {'chart-fixed', 'ruler-x', 'ruler-y', 'motion-picture'}


class MapMotionTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        # Collect earlier tests' Tk objects here, on the main thread (see desktop_tk_safety).
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
        # A slow glide (1 s instead of 0.24 s) leaves time to look at it half way, even on a slow CI machine.
        glide = patch('desktop_motion.ZOOM_SECONDS', 1.0)
        glide.start()
        self.addCleanup(glide.stop)

    def mid_glide(self):
        deadline = time.monotonic() + 2
        while self.app.motion.animating and self.app.motion.a <= 1.0 and time.monotonic() < deadline:
            time.sleep(0.03)
            self.root.update()
        self.assertTrue(self.app.motion.animating, 'the glide ended before it could be checked')

    def tearDown(self):
        if hasattr(self, 'app'):
            self.root.update()
            self.assertEqual(self.errors, [])
            self.app.close()
            gc.collect()

    def event(self, x, y):
        return SimpleNamespace(x=x, y=y)

    def chart_items(self):
        canvas = self.app.map
        return [item for item in canvas.find_all() if not KEEP & set(canvas.gettags(item))]

    def cable_point(self):
        """A drawn vertex of a historical cable route well inside the view, and its geography."""
        from run_gui import world_to_geo
        canvas, (width, height) = self.app.map, self.app._map_size
        for item in canvas.find_all():
            if not any(tag.startswith('world-cable:') for tag in canvas.gettags(item)):
                continue
            coords = canvas.coords(item)
            for x, y in zip(coords[0::2], coords[1::2]):
                if 60 < x < width - 60 and 60 < y < height - 60:
                    return (x, y), world_to_geo(*self.app._world_at(x, y), self.app.map_zoom)
        self.fail('no cable route inside the view')

    def wait(self):
        deadline = time.monotonic() + 4
        while self.app.motion.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.motion.busy)

    def test_drag_moves_one_picture_of_the_whole_chart_then_redraws_it_in_place(self):
        app, canvas = self.app, self.app.map
        (x, y), place = self.cable_point()
        before = len(self.chart_items())
        self.assertGreater(before, 50)
        title = canvas.coords(canvas.find_withtag('map_title')[0])
        app._pan_start(self.event(300, 300))
        with patch.object(app, '_draw_map', wraps=app._draw_map) as draw:
            app._pan_move(self.event(340, 320))
            self.assertEqual(self.chart_items(), [], 'chart items stayed behind while the map moved')
            mx, my = app.motion.margin
            self.assertGreater(mx, 0)
            self.assertEqual(canvas.coords('motion-picture'), [40.0 - mx, 20.0 - my])
            self.assertNotEqual(app.motion.picture.getpixel((round(x) + mx, round(y) + my)), app.motion._sea(),
                                'the moving picture lacks the cable that was drawn there')
            self.assertEqual(canvas.coords(canvas.find_withtag('map_title')[0]), title)
            app._draw_map()  # A live AIS update during the drag waits for the drag to end
            self.assertTrue(app.motion.pending_redraw)
            app._pan_move(self.event(350, 320))
            self.assertEqual(canvas.coords('motion-picture'), [50.0 - mx, 20.0 - my])
            app._pan_end(self.event(350, 320))
            self.assertFalse(app.motion.busy)
            self.assertGreaterEqual(draw.call_count, 2)
        self.assertFalse(canvas.find_withtag('motion-picture'))
        self.assertGreater(len(self.chart_items()), 50)
        # The redraw puts the cable exactly where the drag took it.
        drawn = app._project(*place)
        self.assertAlmostEqual(drawn[0], x + 50, places=6)
        self.assertAlmostEqual(drawn[1], y + 20, places=6)
        self.assertEqual(canvas.coords(canvas.find_withtag('map_title')[0]), title)
        print(f"\nflatten {app.motion.timings[-1] * 1000:.1f} ms for {before} chart items", file=sys.stderr)

    def test_zoom_glides_one_picture_and_lands_with_everything_in_place(self):
        app, canvas = self.app, self.app.map
        (x, y), place = self.cable_point()
        px, py = 200, 160
        zoom = app.map_zoom
        app._zoom_at(1, px, py)
        self.assertTrue(app.motion.animating)
        self.mid_glide()
        self.assertEqual(self.chart_items(), [], 'chart items stayed behind during the zoom')
        self.assertTrue(canvas.find_withtag('motion-picture'))
        motion = app.motion
        self.assertTrue(1.0 < motion.a < 2.0, motion.a)
        frame = motion.frame(motion.a, motion.tx, motion.ty)
        self.assertEqual(frame.size, tuple(app._map_size))
        # The cable pixel of the picture shows up where the glide has taken it (bilinear: look around it).
        seen = (round(motion.a * round(x) + motion.tx), round(motion.a * round(y) + motion.ty))
        expected = motion.picture.getpixel((round(x) + motion.margin[0], round(y) + motion.margin[1]))
        around = [frame.getpixel((seen[0] + dx, seen[1] + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        self.assertTrue(any(all(abs(a - b) <= 40 for a, b in zip(pixel, expected)) for pixel in around),
                        f'{expected} not near {seen}: {around}')
        self.wait()
        self.assertEqual(app.map_zoom, zoom + 1)
        self.assertFalse(canvas.find_withtag('motion-picture'))
        self.assertGreater(len(self.chart_items()), 50)
        # Zoomed about the pointer: the cable vertex is now twice as far from it.
        drawn = app._project(*place)
        self.assertAlmostEqual(drawn[0], px + 2 * (x - px), places=6)
        self.assertAlmostEqual(drawn[1], py + 2 * (y - py), places=6)
        frames = len(motion.timings)
        print(f"\nzoom flatten {motion.timings[-1] * 1000:.1f} ms ({frames} pictures)", file=sys.stderr)

    def test_notches_during_a_glide_join_it_and_land_on_the_right_level(self):
        from run_gui import world_to_geo
        app = self.app
        x, y = 200, 160
        zoom = app.map_zoom
        under = world_to_geo(*app._world_at(x, y), app.map_zoom)
        app._zoom_at(1, x, y)
        self.root.update()
        app._zoom_at(1, x, y)
        self.root.update()
        self.assertTrue(app.motion.animating)
        self.assertEqual(len(app.motion.timings), 1, 'a joining step must not copy the chart again')
        app._zoom_at(-1, x, y)
        self.wait()
        self.assertEqual(app.map_zoom, zoom + 1)
        after = world_to_geo(*app._world_at(x, y), app.map_zoom)
        self.assertAlmostEqual(under[0], after[0], places=9)
        self.assertAlmostEqual(under[1], after[1], places=9)

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

    def test_a_zoom_during_a_drag_glides_from_where_the_drag_left_the_picture(self):
        app, canvas = self.app, self.app.map
        zoom = app.map_zoom
        app._pan_start(self.event(300, 300))
        app._pan_move(self.event(330, 300))
        app._zoom_at(1, 200, 160)
        self.assertTrue(app.motion.animating)
        self.assertEqual(canvas.coords('motion-picture'), [0.0, 0.0])
        self.assertEqual(self.chart_items(), [])
        app.motion.finish_zoom()
        self.assertGreater(len(self.chart_items()), 50, 'a zoom that ends mid-drag must still draw the map')
        app._pan_end(self.event(330, 300))
        self.assertFalse(app.motion.busy)
        self.assertEqual(app.map_zoom, zoom + 1)


if __name__ == '__main__':
    unittest.main()
