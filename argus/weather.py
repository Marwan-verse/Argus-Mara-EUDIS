"""Live point forecast from the Met Éireann open-data forecast API; display only.

Source: https://data.gov.ie/dataset/met-eireann-forecast-api
Licence: Met Éireann Custom Open Data Licence (CC BY 4.0 terms); credit Met Éireann.

The forecast is real, current data for the requested point; the map overlay samples a
grid of points and is a model forecast, not radar. It is never the
weather during the fictional replay, and it never changes alerts, countdowns or
response ETAs. Any caution text is an assumption shown for the operator.

Usage: python -m argus.weather [LAT LON]
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

API_URL = "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast?lat={lat:.4f};long={lon:.4f}"
SOURCE_URL = "https://data.gov.ie/dataset/met-eireann-forecast-api"
ATTRIBUTION = "Met Éireann forecast · CC BY 4.0"
USER_AGENT = "ArgusMaraDesktop/0.3 (hackathon demo; live weather display)"
KNOTS_PER_MPS = 1.943844
REFRESH_S = 30 * 60


def forecast_url(lat: float, lon: float) -> str:
    return API_URL.format(lat=lat, lon=lon)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _number(element, attribute: str) -> float | None:
    if element is None or element.get(attribute) is None:
        return None
    value = float(element.get(attribute))
    return value if math.isfinite(value) else None  # the API sends NaN at its model edges


def parse_forecast(xml: bytes | str) -> dict:
    """Return hourly points sorted by time; precipitation comes from the hour ending then."""
    root = ET.fromstring(xml)
    points: dict[datetime, dict] = {}
    precipitation: dict[datetime, dict] = {}
    for time_element in root.iter("time"):
        location = time_element.find("location")
        if location is None:
            continue
        start, end = _utc(time_element.get("from")), _utc(time_element.get("to"))
        if start == end:
            wind_dir = location.find("windDirection")
            wind = location.find("windSpeed")
            points[end] = {
                "time": end,
                "temperature_c": _number(location.find("temperature"), "value"),
                "wind_dir_deg": _number(wind_dir, "deg"),
                "wind_dir": wind_dir.get("name") if wind_dir is not None else None,
                "wind_mps": _number(wind, "mps"),
                "beaufort": int(wind.get("beaufort")) if wind is not None and wind.get("beaufort") else None,
                "wind_name": wind.get("name") if wind is not None else None,
                "gust_mps": _number(location.find("windGust"), "mps"),
                "pressure_hpa": _number(location.find("pressure"), "value"),
                "humidity_pct": _number(location.find("humidity"), "value"),
                "cloud_pct": _number(location.find("cloudiness"), "percent"),
            }
        else:
            rain = location.find("precipitation")
            symbol = location.find("symbol")
            # Keep the shortest interval ending at each hour (the API repeats longer ones).
            if end not in precipitation or end - start < precipitation[end]["span"]:
                precipitation[end] = {
                    "span": end - start,
                    "precip_mm": _number(rain, "value"),
                    "precip_probability_pct": _number(rain, "probability"),
                    "symbol": symbol.get("id") if symbol is not None else None,
                }
    for end, values in precipitation.items():
        if end in points:
            points[end].update({key: value for key, value in values.items() if key != "span"})
    created = root.get("created")
    return {
        "created": _utc(created) if created else None,
        "points": [points[key] for key in sorted(points)],
    }


def fetch_forecast(lat: float, lon: float, timeout: float = 15, opener=urlopen) -> dict:
    request = Request(forecast_url(lat, lon), headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=timeout) as response:
        forecast = parse_forecast(response.read())
    if not forecast["points"]:
        raise ValueError("Met Éireann returned no forecast points")
    forecast.update({"lat": lat, "lon": lon, "fetched": datetime.now(timezone.utc),
                     "label": "real", "attribution": ATTRIBUTION})
    return forecast


def current_conditions(forecast: dict, now: datetime | None = None) -> dict:
    """The latest hourly point not after `now`, or the first one if all are in the future."""
    now = now or datetime.now(timezone.utc)
    past = [point for point in forecast["points"] if point["time"] <= now]
    return past[-1] if past else forecast["points"][0]


def upcoming(forecast: dict, hours: int = 12, now: datetime | None = None) -> list[dict]:
    first = current_conditions(forecast, now)
    points = forecast["points"]
    start = points.index(first)
    return points[start:start + hours]


def knots(mps: float | None) -> float | None:
    return None if mps is None else mps * KNOTS_PER_MPS


def summary(point: dict) -> str:
    parts = []
    if point.get("wind_mps") is not None:
        wind = f"{point.get('wind_dir') or ''} {knots(point['wind_mps']):.0f} kn".strip()
        if point.get("beaufort") is not None:
            wind += f" (Bft {point['beaufort']})"
        if point.get("gust_mps") is not None:
            wind += f", gusts {knots(point['gust_mps']):.0f} kn"
        parts.append(wind)
    if point.get("temperature_c") is not None:
        parts.append(f"{point['temperature_c']:.0f} °C")
    if point.get("precip_mm"):
        parts.append(f"{point['precip_mm']:.1f} mm/h")
    if point.get("pressure_hpa") is not None:
        parts.append(f"{point['pressure_hpa']:.0f} hPa")
    return " · ".join(parts) or "No values"


def caution(point: dict) -> str | None:
    """Operator hint from wind force; an assumption that never changes ETAs."""
    beaufort = point.get("beaufort")
    if beaufort is None:
        return None
    if beaufort >= 8:
        return "Gale force: small craft and boarding likely unsafe; helicopter limits may apply (assumption, ETAs unchanged)."
    if beaufort >= 6:
        return "Strong wind: small-boat response may be slower than assumed (assumption, ETAs unchanged)."
    return None


# --- Rain and cloud map overlay -------------------------------------------------
# The API serves single points, so the map samples a grid of them. Coverage was
# probed on 9 Oct 2026: HARMONIE (cloud % and rain mm) over Ireland and the Irish
# Sea, ECMWF (temperature and weather symbol only) out to this box, nothing beyond.
COVERAGE = (50.0, 60.0, -20.0, 1.0)  # south, north, west, east
GRID_STEPS = (0.1, 0.2, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
MAX_GRID_POINTS = 100
RAIN_LEGEND_MM = (0.1, 0.5, 1, 3, 6, 12)
_RAIN_TOP_MM = 16.0
_RAIN_STOPS = ((8, (168, 216, 255)), (40, (74, 155, 234)), (80, (46, 184, 114)),
               (130, (243, 210, 60)), (180, (240, 140, 42)), (230, (214, 47, 60)))


def grid_for_view(south: float, north: float, west: float, east: float) -> tuple[float, list[float], list[float]] | None:
    """Grid points (multiples of a step, so panning reuses cached points) covering a view."""
    south, north = max(south, COVERAGE[0]), min(north, COVERAGE[1])
    west, east = max(west, COVERAGE[2]), min(east, COVERAGE[3])
    if south >= north or west >= east:
        return None

    def axis(low: float, high: float, step: float, limit_low: float, limit_high: float) -> list[float]:
        first, last = math.floor(low / step) - 1, math.ceil(high / step) + 1
        values = [round(index * step, 4) for index in range(first, last + 1)]
        return [value for value in values if limit_low <= value <= limit_high]

    for step in GRID_STEPS:
        lats = axis(south, north, step, COVERAGE[0], COVERAGE[1])
        lons = axis(west, east, step, COVERAGE[2], COVERAGE[3])
        if len(lats) * len(lons) <= MAX_GRID_POINTS:
            break
    if len(lats) < 2 or len(lons) < 2:
        return None
    return step, lats, lons


def symbol_estimate(symbol: str | None) -> tuple[float, float] | None:
    """Rough (cloud %, rain mm/h) from a weather symbol id; an assumption for ECMWF points."""
    if not symbol:
        return None
    name = symbol.lower()
    showers = "sun" in name
    wet = any(word in name for word in ("rain", "drizzle", "sleet", "snow"))
    if "fog" in name:
        cloud = 100.0
    elif wet:
        cloud = 60.0 if showers else 90.0
    elif name == "cloud":
        cloud = 90.0
    elif "partlycloud" in name:
        cloud = 55.0
    elif "lightcloud" in name:
        cloud = 25.0
    else:
        cloud = 5.0
    if not wet:
        rain = 0.0
    elif "heavy" in name:
        rain = 6.0
    elif "light" in name:
        rain = 0.5
    elif "drizzle" in name:
        rain = 0.2
    else:
        rain = 2.0
    if "thunder" in name:
        rain = max(rain, 4.0)
    return cloud, rain


def field_values(point: dict) -> tuple[float, float, bool] | None:
    """(cloud %, rain mm/h, estimated) for one forecast hour; numbers win over symbols."""
    estimate = symbol_estimate(point.get("symbol"))
    cloud, rain = point.get("cloud_pct"), point.get("precip_mm")
    if cloud is not None and rain is not None:
        return cloud, rain, False
    if estimate is None:
        return None
    return (cloud if cloud is not None else estimate[0],
            rain if rain is not None else estimate[1], True)


def rain_level(mm: float) -> int:
    return round(255 * min(1.0, math.log1p(max(mm, 0.0)) / math.log1p(_RAIN_TOP_MM)))


def rain_colour(level: int) -> tuple[int, int, int, int]:
    if level < 3:
        return 0, 0, 0, 0
    if level < _RAIN_STOPS[0][0]:  # soft edge, so the 8-bit field shows no staircase
        return (*_RAIN_STOPS[0][1], round(110 * (level - 2) / (_RAIN_STOPS[0][0] - 2)))
    colour = _RAIN_STOPS[-1][1]
    for (low, start), (high, end) in zip(_RAIN_STOPS, _RAIN_STOPS[1:]):
        if level < high:
            fraction = (level - low) / (high - low)
            colour = tuple(round(a + (b - a) * fraction) for a, b in zip(start, end))
            break
    alpha = round(110 + 90 * min(1.0, (level - _RAIN_STOPS[0][0]) / 72))
    return (*colour, alpha)


# Upper bound in knots (exclusive) and colour, roughly Beaufort 0–3, 4–5, 6–7 and gale.
WIND_BANDS = ((11, "#2f9a8a", "<11"), (22, "#2556c8", "11–21"), (34, "#d9822b", "22–33"),
              (math.inf, "#c62f3c", "34+"))


def wind_vector(point: dict) -> tuple[float, float] | None:
    """(direction the wind blows TOWARDS in degrees, speed in knots); the API gives 'from'."""
    if point.get("wind_dir_deg") is None or point.get("wind_mps") is None:
        return None
    return (point["wind_dir_deg"] + 180) % 360, knots(point["wind_mps"])


def wind_colour(kn: float) -> str:
    return next(colour for limit, colour, _label in WIND_BANDS if kn < limit)


def _mercator(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _lat_from_mercator(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def field_images(lats: list[float], lons: list[float], values: dict, rows_per_cell: int = 4):
    """Three greyscale PIL images (cloud, rain level, data mask), north at the top.

    Columns sit on the grid longitudes. Rows are evenly spaced in Web Mercator
    between the half-cell edges, so a linear resize places them correctly on the map.
    `values` maps (lat, lon) to `field_values` output or None.
    """
    from PIL import Image

    step = lats[1] - lats[0]
    north, south = _mercator(lats[-1] + step / 2), _mercator(lats[0] - step / 2)
    rows = len(lats) * rows_per_cell
    cloud, rain, mask = [], [], []
    for row in range(rows):
        lat = _lat_from_mercator(north + (south - north) * (row + 0.5) / rows)
        position = min(max((lat - lats[0]) / step, 0.0), len(lats) - 1.0)
        below = min(int(position), len(lats) - 2)
        fraction = position - below
        for lon in lons:
            total = [0.0, 0.0, 0.0]
            for lat_key, weight in ((lats[below], 1 - fraction), (lats[below + 1], fraction)):
                value = values.get((lat_key, lon))
                if value is not None and weight:
                    total[0] += weight * value[0] * 2.55
                    total[1] += weight * rain_level(value[1])
                    total[2] += weight * 255
            cloud.append(round(total[0]))
            rain.append(round(total[1]))
            mask.append(round(total[2]))
    images = []
    for data in (cloud, rain, mask):
        image = Image.new("L", (len(lons), rows))
        image.putdata(data)
        images.append(image)
    return tuple(images)


def colorize(cloud, rain, mask):
    """RGBA overlay: translucent slate cloud with a radar-style rain scale on top."""
    from PIL import Image, ImageChops

    cloud_alpha = ImageChops.multiply(cloud.point(lambda v: round(v * 0.42)), mask)
    cloud_layer = Image.new("RGBA", cloud.size, (88, 101, 120, 0))
    cloud_layer.putalpha(cloud_alpha)
    lut = [rain_colour(level) for level in range(256)]
    channels = [rain.point([colour[index] for colour in lut]) for index in range(4)]
    channels[3] = ImageChops.multiply(channels[3], mask)
    return Image.alpha_composite(cloud_layer, Image.merge("RGBA", channels))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lat", nargs="?", type=float, default=53.36)
    parser.add_argument("lon", nargs="?", type=float, default=-5.7)
    args = parser.parse_args()
    forecast = fetch_forecast(args.lat, args.lon)
    now = current_conditions(forecast)
    print(f"{ATTRIBUTION} · real · {args.lat:.3f}, {args.lon:.3f}")
    print(f"{now['time']:%Y-%m-%d %H:%M} UTC  {summary(now)}")
    for point in upcoming(forecast, 12)[1:]:
        print(f"{point['time']:%H:%M} UTC  {summary(point)}")
    if caution(now):
        print(caution(now))


if __name__ == "__main__":
    main()
