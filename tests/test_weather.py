"""Met Éireann forecast parsing and the desktop toggle, without network access."""

import queue
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock

from argus import weather
from run_gui import ArgusApp

SAMPLE = b"""<weatherdata created="2026-10-09T08:34:41Z"><product class="pointData">
<time datatype="forecast" from="2026-10-09T09:00:00Z" to="2026-10-09T09:00:00Z"><location latitude="53.3600" longitude="-5.7000">
<temperature id="TTT" unit="celsius" value="13.6"/><windDirection id="dd" deg="288.2" name="W"/>
<windSpeed id="ff" mps="8.6" beaufort="5" name="Fresh breeze"/><windGust id="ff_gust" mps="16.7"/>
<pressure id="pr" unit="hPa" value="1010.3"/><cloudiness id="NN" percent="5.4"/></location></time>
<time datatype="forecast" from="2026-10-09T08:00:00Z" to="2026-10-09T09:00:00Z"><location latitude="53.3600" longitude="-5.7000">
<precipitation unit="mm" value="0.0" probability="1.3"/><symbol id="Sun" number="1"/></location></time>
<time datatype="forecast" from="2026-10-09T10:00:00Z" to="2026-10-09T10:00:00Z"><location latitude="53.3600" longitude="-5.7000">
<temperature id="TTT" unit="celsius" value="12.1"/><windDirection id="dd" deg="270.0" name="W"/>
<windSpeed id="ff" mps="12.0" beaufort="6" name="Strong breeze"/><windGust id="ff_gust" mps="18.0"/>
<pressure id="pr" unit="hPa" value="1009.8"/><cloudiness id="NN" percent="NaN"/></location></time>
<time datatype="forecast" from="2026-10-09T07:00:00Z" to="2026-10-09T10:00:00Z"><location latitude="53.3600" longitude="-5.7000">
<precipitation unit="mm" value="3.0"/><symbol id="Rain" number="9"/></location></time>
<time datatype="forecast" from="2026-10-09T09:00:00Z" to="2026-10-09T10:00:00Z"><location latitude="53.3600" longitude="-5.7000">
<precipitation unit="mm" value="0.8" probability="60.0"/><symbol id="Rain" number="9"/></location></time>
</product></weatherdata>"""


class ForecastParsingTests(unittest.TestCase):
    def test_parses_hourly_points_with_hourly_precipitation(self):
        forecast = weather.parse_forecast(SAMPLE)
        first, second = forecast["points"]
        self.assertEqual(first["time"], datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
        self.assertEqual((first["wind_dir"], first["wind_mps"], first["beaufort"]), ("W", 8.6, 5))
        self.assertEqual(first["precip_mm"], 0.0)
        self.assertEqual(second["precip_mm"], 0.8)  # the 1 h interval, not the 3 h one
        self.assertEqual(second["symbol"], "Rain")
        self.assertIsNone(second["cloud_pct"])  # NaN from the API means missing
        self.assertEqual(weather.field_values(second), (90.0, 0.8, True))

    def test_current_conditions_and_caution(self):
        forecast = weather.parse_forecast(SAMPLE)
        now = weather.current_conditions(forecast, datetime(2026, 10, 9, 10, 30, tzinfo=timezone.utc))
        self.assertEqual(now["beaufort"], 6)
        self.assertIn("ETAs unchanged", weather.caution(now))
        self.assertIsNone(weather.caution(forecast["points"][0]))
        self.assertEqual(weather.summary(now), "W 23 kn (Bft 6), gusts 35 kn · 12 °C · 0.8 mm/h · 1010 hPa")
        early = datetime(2026, 10, 9, 6, tzinfo=timezone.utc)
        self.assertEqual(weather.upcoming(forecast, 1, early), [forecast["points"][0]])

    def test_fetch_labels_real_data_and_uses_documented_url(self):
        opener = Mock(return_value=BytesIO(SAMPLE))
        forecast = weather.fetch_forecast(53.36, -5.7, opener=opener)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast?lat=53.3600;long=-5.7000")
        self.assertEqual((forecast["label"], len(forecast["points"])), ("real", 2))


class OverlayFieldTests(unittest.TestCase):
    def test_grid_is_clipped_to_coverage_and_capped(self):
        step, lats, lons = weather.grid_for_view(52.5, 53.8, -7.0, -4.0)
        self.assertLessEqual(len(lats) * len(lons), weather.MAX_GRID_POINTS)
        self.assertTrue(lats[0] <= 52.5 and lats[-1] >= 53.8 and lons[0] <= -7.0 and lons[-1] >= -4.0)
        self.assertEqual(round(lats[1] - lats[0], 4), step)
        _step, wide_lats, wide_lons = weather.grid_for_view(-80, 80, -180, 180)
        self.assertTrue(50.0 <= wide_lats[0] < wide_lats[-1] <= 60.0 and -20.0 <= wide_lons[0] < wide_lons[-1] <= 1.0)
        self.assertLessEqual(len(wide_lats) * len(wide_lons), weather.MAX_GRID_POINTS)
        self.assertIsNone(weather.grid_for_view(40, 45, -10, -5))

    def test_numbers_win_and_symbols_are_marked_estimated(self):
        self.assertEqual(weather.field_values({"cloud_pct": 40.0, "precip_mm": 1.2, "symbol": "Rain"}), (40.0, 1.2, False))
        self.assertEqual(weather.field_values({"symbol": "LightRainSun"}), (60.0, 0.5, True))
        self.assertEqual(weather.symbol_estimate("Cloud"), (90.0, 0.0))
        self.assertIsNone(weather.field_values({"temperature_c": 12.0}))

    def test_images_fade_out_where_points_are_missing(self):
        lats, lons = [53.0, 53.5], [-6.0, -5.5, -5.0]
        values = {(lat, lon): (100.0, 8.0) for lat in lats for lon in lons[:2]}
        cloud, rain, mask = weather.field_images(lats, lons, values)
        self.assertEqual(cloud.size, (3, 8))
        self.assertEqual((mask.getpixel((0, 4)), mask.getpixel((2, 4))), (255, 0))
        overlay = weather.colorize(cloud, rain, mask)
        self.assertEqual(overlay.mode, "RGBA")
        self.assertGreater(overlay.getpixel((0, 4))[3], 150)
        self.assertEqual(overlay.getpixel((2, 4))[3], 0)
        self.assertEqual(weather.rain_colour(weather.rain_level(0.0))[3], 0)

    def test_wind_arrows_point_downwind_and_colour_by_strength(self):
        towards, kn = weather.wind_vector({"wind_dir_deg": 270.0, "wind_mps": 8.6})
        self.assertEqual((towards, round(kn)), (90.0, 17))  # a westerly blows towards the east
        self.assertIsNone(weather.wind_vector({"symbol": "Rain"}))
        self.assertEqual([weather.wind_colour(kn) for kn in (5, 15, 25, 40)],
                         [colour for _limit, colour, _label in weather.WIND_BANDS])


class DesktopWeatherToggleTests(unittest.TestCase):
    def toggle_app(self, enabled):
        app = ArgusApp.__new__(ArgusApp)
        app.root = Mock()
        app.live_weather = Mock(get=Mock(return_value=enabled))
        app.weather_label = Mock()
        app.weather_point = (53.36, -5.7)
        app._weather = None
        app._weather_generation = 0
        app._weather_refresh_after = None
        app._weather_queue = queue.Queue()
        app._weather_executor = Mock()
        app._panel_widgets = {}
        app._weather_grid_pending = set()
        app._weather_grid_cache = {}
        app._update_weather_grid = Mock()
        app._draw_map = Mock()
        return app

    def test_switching_off_makes_no_request_and_drops_late_results(self):
        app = self.toggle_app(enabled=False)
        app._weather_queue.put(("point", 0, weather.parse_forecast(SAMPLE), None))
        app._weather_queue.put(("grid", 0, (53.0, -6.0), weather.parse_forecast(SAMPLE), False))
        app._toggle_weather()
        app._poll_weather()
        app._weather_executor.submit.assert_not_called()
        self.assertIsNone(app._weather)
        self.assertEqual(app._weather_grid_cache, {})

    def test_turning_on_a_weather_layer_turns_on_live_weather(self):
        app = ArgusApp.__new__(ArgusApp)
        app.live_weather = Mock(get=Mock(return_value=False))
        app.map_layers = {"Wind": Mock(get=Mock(return_value=True))}
        app._toggle_weather = Mock()
        app._weather_layer_changed("Wind")
        app.live_weather.set.assert_called_once_with(True)
        app._toggle_weather.assert_called_once()

    def test_switching_on_requests_once_and_shows_result(self):
        app = self.toggle_app(enabled=True)
        app._toggle_weather()
        app._weather_executor.submit.assert_called_once()
        forecast = weather.parse_forecast(SAMPLE)
        forecast["fetched"] = datetime(2026, 10, 9, 9, 5, tzinfo=timezone.utc)
        app._weather_field_version = 0
        app._weather_queue.put(("point", app._weather_generation, forecast, None))
        app._weather_queue.put(("grid", app._weather_generation, (53.0, -6.0), forecast, False))
        app._poll_weather()
        self.assertIs(app._weather_grid_cache[(53.0, -6.0)][1], forecast)
        self.assertEqual(app._weather_field_version, 1)
        self.assertIs(app._weather, forecast)
        self.assertIn("kn", app.weather_label.configure.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
