"""Interactive polish stays local and preserves observation/review semantics."""
import tkinter as tk
import unittest
from unittest.mock import patch

from argus.live_client import LiveState
from test_desktop_tools import fixture


class DesktopPolishTests(unittest.TestCase):
    def test_details_tooltips_and_motion_controls(self):
        import customtkinter as ctk
        from run_gui import ArgusApp, load_demo
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.attributes('-alpha', 0)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': '', 'ARGUS_REDUCED_MOTION': '0'}):
            app = ArgusApp(root, *load_demo())
        app.ais_tracker.cache_path = None
        app.ais_tracker.state = LiveState()
        try:
            root.update()
            tools = app.tools
            identifier = app.alert['id']
            details, _actions, button = tools.alert_details[identifier]
            self.assertEqual(details.winfo_manager(), '')
            tools.toggle_alert_details(identifier)
            self.assertEqual(details.winfo_manager(), 'pack')
            self.assertEqual(button.cget('text'), 'Hide details')
            tools.toggle_alert_details(identifier)
            self.assertEqual(details.winfo_manager(), '')
            self.assertIsNone(app.approved)

            icon = app.toolbar_buttons['ship']
            self.assertEqual(icon.cget('image').cget('size'), (18, 18))
            self.assertEqual(icon.cget('text'), '')
            tools.show_tooltip(icon, 'Ships / received observations')
            root.update_idletasks()
            self.assertTrue(tools.tooltip.winfo_ismapped())
            self.assertGreaterEqual(tools.tooltip.winfo_x(), 0)
            tools.hide_tooltip()
            self.assertFalse(tools.tooltip.winfo_ismapped())

            app.ais_tracker.state.apply(fixture())
            app.ais_tracker.update_header()
            self.assertEqual(app.feed_counts_label.cget('text'), '3 / 2')
            app._draw_map()
            stale = app.map.find_withtag('ais-ship:222222222')
            self.assertEqual(len(stale), 1)
            self.assertEqual(app.map.type(stale[0]), 'oval')
            self.assertEqual(app.map.itemcget(stale[0], 'outline'), '')
            self.assertEqual(app.utc_header.cget('font').cget('family'), 'Consolas')

            app.show_console_panel('Ship details')
            self.assertIn('details', tools.animations)
            app.hide_console_panel()
            self.assertNotIn('details', tools.animations)
            tools.reduced_motion.set(True)
            app.show_console_panel('Ship details')
            self.assertNotIn('details', tools.animations)
            tools.open_search()
            self.assertNotIn('search', tools.animations)
            tools.close_search()
            root.update()
            self.assertEqual(errors, [])
        finally:
            app.close()
