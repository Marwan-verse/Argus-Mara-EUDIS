"""The pro look (the default `python run_gui.py`) builds and draws on every desktop platform CI runs.

Every other window test builds the classic look, so without this one a Windows-only break in
the tactical chart, its fonts or its banners would go unnoticed. Tiles are generated locally:
the test makes no network requests.
"""
import copy
from io import BytesIO
import tempfile
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

from PIL import Image

from argus.live_client import LiveState


def fake_tile(_source, z, x, y) -> bytes:
    output = BytesIO()
    Image.new("RGB", (256, 256), (10 + z, 20, 30)).save(output, "PNG")
    return output.getvalue()


class ProLookTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        import desktop_pro
        import run_gui
        theme = copy.deepcopy(ctk.ThemeManager.theme)
        saved = {name: getattr(run_gui, name) for name in (*desktop_pro.PALETTE, "UI_EDITION")}

        def restore():
            for name, value in saved.items():
                setattr(run_gui, name, value)
            ctk.ThemeManager.theme.clear()
            ctk.ThemeManager.theme.update(theme)
        self.addCleanup(restore)
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes('-alpha', 0)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        desktop_pro.apply_palette()
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        for target, value in (('run_gui.tile_cache_root', lambda: Path(cache.name) / 'map-tiles' / 'nasa'),
                              ('desktop_basemap.fetch_tile', fake_tile)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.dict('os.environ', {'ARGUS_AIS_AUTOCONNECT': '0', 'ARGUS_UI_PREFERENCES': ''}):
            self.app = run_gui.ArgusApp(self.root, *run_gui.load_demo())
        self.app.ais_tracker.cache_path = None
        self.app.ais_tracker.state = LiveState()

    def tearDown(self):
        if hasattr(self, 'app'):
            self.root.update()
            self.assertEqual(self.errors, [])
            self.app.close()

    def wait_for_tiles(self):
        import time
        deadline = time.monotonic() + 5
        while not self.app._tile_images and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.05)

    def test_tactical_chart_banners_and_chart_furniture_draw(self):
        import desktop_basemap
        import run_gui
        app = self.app
        self.assertEqual(run_gui.UI_EDITION, 'pro')
        self.assertEqual(app.map_mode.get(), desktop_basemap.TACTICAL_MAP)
        self.root.update()
        self.assertTrue(all('UNCLASSIFIED' in banner.cget('text') for banner in app.marking_banners))
        self.wait_for_tiles()
        self.assertTrue(app._tile_images, 'no chart tile reached the map')
        app._draw_map()
        for tag in ('chart-margin', 'chart-readout', 'chart-furniture'):
            self.assertTrue(app.map.find_withtag(tag), tag)
        self.assertIn('CURSOR', app.map.itemcget('chart-readout', 'text'))
        self.assertIn('MGRS 29U PV', desktop_basemap.readout_text(53.35, -6.26))
        app._change_map_mode(desktop_basemap.HD_IMAGERY)
        self.wait_for_tiles()
        self.assertTrue(app._tile_images)
        self.assertLessEqual(app.map_zoom, desktop_basemap.SOURCES[desktop_basemap.HD_IMAGERY].max_zoom)

    @unittest.skipUnless(sys.platform in ('darwin', 'win32'), 'Only macOS and Windows ship a known monospace family')
    def test_the_chart_font_exists_on_this_platform(self):
        import desktop_basemap
        self.assertIn(desktop_basemap.MONO, tkfont.families(self.root))


if __name__ == '__main__':
    unittest.main()
