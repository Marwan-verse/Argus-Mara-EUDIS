"""Trackpad scrolling moves lists by the reported pixels; pinches step the map zoom."""
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.live_client import LiveState
from desktop_gestures import PinchZoom, install_touchpad_scroll, scroll_deltas, scroll_frame, scrollable_under


class GestureTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes('-alpha', 0)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': ''}):
            self.app = ArgusApp(self.root, *load_demo())
        self.app.ais_tracker.cache_path = None
        self.app.ais_tracker.state = LiveState()
        self.root.update()

    def tearDown(self):
        if hasattr(self, 'app'):
            self.root.update()
            self.assertEqual(self.errors, [])
            self.app.close()

    def test_two_finger_scroll_moves_the_alert_list(self):
        board = self.app.alert_board
        self.assertEqual(scroll_deltas(self.root, (3 << 16) | (-12 & 0xffff)), (3.0, -12.0))
        self.assertIs(scrollable_under(board.list.canvas), board.list)
        self.assertIs(scrollable_under(board.list), board.list)
        self.assertIsNone(scrollable_under(self.app.map))
        canvas = board.list.canvas
        self.assertEqual(canvas.canvasy(0), 0)
        self.assertTrue(scroll_frame(board.list, 120))
        self.assertAlmostEqual(canvas.canvasy(0), 120, delta=2)
        scroll_frame(board.list, -500)
        self.assertEqual(canvas.canvasy(0), 0)
        self.assertIsInstance(install_touchpad_scroll(self.root), bool)

    def test_pinch_steps_the_zoom_only_over_the_map(self):
        app = self.app
        time.sleep(0.3)  # Let the scheduled first fit of Ireland run before measuring zoom.
        self.root.update()
        pinch = PinchZoom(app) if not hasattr(app, 'pinch') else app.pinch
        width, height = app.map.winfo_width(), app.map.winfo_height()
        # Hidden Windows windows cannot own the real pointer. Keep hit testing
        # deterministic without moving the user's cursor or depending on focus.
        pointer_patch = patch.object(self.root, 'winfo_pointerxy', return_value=(
            app.map.winfo_rootx() + width // 2, app.map.winfo_rooty() + height // 2))
        containing_patch = patch.object(self.root, 'winfo_containing', return_value=app.map)
        pointer_patch.start()
        containing = containing_patch.start()
        self.addCleanup(pointer_patch.stop)
        self.addCleanup(containing_patch.stop)
        zoom = app.map_zoom
        pinch.apply(0.1)
        self.assertEqual(app.map_zoom, zoom)
        pinch.apply(0.15)
        self.assertEqual(app.map_zoom, zoom + 1)
        pinch.apply(-0.5)
        self.assertEqual(app.map_zoom, zoom - 1)
        containing.return_value = app.alerts_panel
        pinch.apply(0.6)
        self.assertEqual(app.map_zoom, zoom - 1)


if __name__ == '__main__':
    unittest.main()
