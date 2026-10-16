import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desktop_basemap as basemap
from run_gui import MAX_IMAGERY_ZOOM, MAX_MAP_ZOOM, ONLINE_MAP, is_raster, max_zoom_for


class CoordinateTests(unittest.TestCase):
    def test_mgrs_matches_reference_values(self):
        # Reference values from the `mgrs` package (GeoTrans), 10 m precision.
        cases = {(53.3498, -6.2603): "29U PV 8235 1468", (51.5, -9.8): "29U MT 4447 0573",
                 (54.0, -12.5): "28U FE 6385 8641", (-33.9, 151.2): "56H LH 3356 4747",
                 (60.1, 5.3): "32V KM 9431 6830"}
        for (lat, lon), expected in cases.items():
            self.assertEqual(basemap.mgrs(lat, lon, 4), expected)

    def test_position_and_dtg_formats(self):
        self.assertEqual(basemap.position_text(53.5, -6.25), "53°30.00′N 006°15.00′W")
        self.assertEqual(basemap.dtg(datetime(2026, 10, 16, 10, 30, tzinfo=timezone.utc)), "161030ZOCT26")


class ChartTileTests(unittest.TestCase):
    def test_mask_decides_water_and_land_and_draws_a_coast(self):
        relief = Image.new("RGB", (256, 256), (230, 232, 236))  # Pale: shallow water or bright rock
        mask = Image.new("RGB", (256, 256), (240, 239, 234))  # Esri Ocean land colour
        mask.paste((200, 220, 238), (0, 0, 128, 256))  # Left half is water
        tile = basemap.tactical_tile(relief, mask)
        water, land = tile.getpixel((40, 128)), tile.getpixel((220, 128))
        self.assertGreater(water[2], water[0])  # Blue-dominant sea
        self.assertGreaterEqual(land[0], land[2])  # Olive-grey land
        self.assertEqual(tile.getpixel((127, 128)), basemap.COAST)
        self.assertNotEqual(tile.getpixel((0, 128)), basemap.COAST)  # No false coast on the tile border


class ZoomLimitTests(unittest.TestCase):
    def test_each_base_map_has_its_own_zoom_limit(self):
        self.assertEqual(max_zoom_for("Offline coastline"), MAX_MAP_ZOOM)
        self.assertEqual(max_zoom_for(ONLINE_MAP), MAX_IMAGERY_ZOOM)
        self.assertEqual(max_zoom_for(basemap.HD_IMAGERY), 17)
        self.assertTrue(is_raster(basemap.TACTICAL_MAP))
        self.assertFalse(is_raster("Offline coastline"))


if __name__ == "__main__":
    unittest.main()
