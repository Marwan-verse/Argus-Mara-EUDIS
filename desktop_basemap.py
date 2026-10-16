"""Detailed raster charts and chart furniture for the professional console.

Two online base maps, both cached on this device after the first view:

* Tactical chart: EMODnet Bathymetry relief (seabed and land hillshade) recoloured into a dark
  night-chart palette. The land/water split and the drawn coastline come from Esri Ocean Base,
  and OpenSeaMap seamarks (buoys, lights) appear from zoom 11. EMODnet data is CC BY 4.0,
  OpenSeaMap is CC BY-SA 2.0.
* Satellite HD: Esri World Imagery, dimmed slightly so tracks and labels stay readable.

Both are display context only; nothing here feeds a detector or an alert.
The furniture (lat/lon margin scale, north arrow, cursor readout with MGRS, segmented
nautical scale bar) is drawn on the Tk canvas after the operational layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import math
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

TACTICAL_MAP = "Tactical chart · EMODnet"
HD_IMAGERY = "Satellite HD · Esri"
USER_AGENT = "ArgusMaraDesktop/0.4 (hackathon demo; tiles cached locally)"


@dataclass(frozen=True)
class TileSource:
    id: str
    name: str
    max_zoom: int
    ext: str
    title: str
    attribution: str


SOURCES = {
    TACTICAL_MAP: TileSource("tactical-emodnet", TACTICAL_MAP, 14, "png",
                             "TACTICAL CHART · EMODNET BATHYMETRY · DISPLAY ONLY",
                             "EMODnet Bathymetry CC BY 4.0 · Esri Ocean · OpenSeaMap CC BY-SA · Natural Earth · NGA · TeleGeography"),
    HD_IMAGERY: TileSource("satellite-esri", HD_IMAGERY, 17, "jpeg",
                           "SATELLITE HD · ESRI WORLD IMAGERY · DISPLAY ONLY",
                           "Esri, Maxar, Earthstar Geographics · Natural Earth · NGA · TeleGeography"),
}

RELIEF_URL = "https://tiles.emodnet-bathymetry.eu/2020/baselayer/web_mercator/{z}/{x}/{y}.png"
# Esri Ocean Base draws water in clear blue up to an OSM-quality shoreline; it only supplies the mask.
MASK_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
SEAMARK_URL = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
IMAGERY_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
SEAMARK_MIN_ZOOM = 11

# Night-chart palette, after the IHO S-52 dusk and night tables: near-black deep water,
# a lighter shelf, dim olive land, low-contrast lines.
DEEP = (7, 16, 25)
SHELF = (30, 64, 80)
LAND_DARK = (14, 16, 12)
LAND_LIGHT = (86, 88, 72)
COAST = (112, 146, 150)


def _ramp(low, high, start, stop, gamma):
    weights = [min(1.0, max(0.0, (v / 255 - start) / (stop - start))) ** gamma for v in range(256)]
    return [round(low[channel] + (high[channel] - low[channel]) * w) for channel in range(3) for w in weights]


SEA_RAMP = _ramp(DEEP, SHELF, .40, 1.0, 1.25)
LAND_RAMP = _ramp(LAND_DARK, LAND_LIGHT, .42, .98, 1.0)


def _get(url: str, timeout: float = 12) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as response:
        if not response.headers.get("Content-Type", "").lower().startswith("image/"):
            raise ValueError("Tile service returned something other than an image")
        return response.read(4 * 1024 * 1024)


def tactical_tile(relief: Image.Image, mask: Image.Image | None, seamarks: Image.Image | None = None,
                  smallest_water: int = 3) -> Image.Image:
    """Recolour an EMODnet relief tile into the dark chart palette.

    The mask is an Esri Ocean Base tile: blue water, near-neutral land. Without it, clearly
    blue relief pixels count as water, which misses the pale shallow strip along the shore.
    """
    relief = relief.convert("RGB")
    source = (mask if mask is not None else relief).convert("RGB")
    red, _green, blue = source.split()
    water = ImageChops.subtract(blue, red).point(lambda v: 255 if v > (15 if mask is not None else 8) else 0)
    # Drop river lines and specks narrower than smallest_water pixels; keep lakes and the sea.
    water = water.filter(ImageFilter.MinFilter(smallest_water)).filter(ImageFilter.MaxFilter(smallest_water))
    shade = relief.convert("L")
    shade = Image.merge("RGB", (shade, shade, shade))
    chart = Image.composite(shade.point(SEA_RAMP), shade.point(LAND_RAMP), water)
    edge = water.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 0 else 0)
    edge = edge.crop((1, 1, 255, 255)).crop((-1, -1, 255, 255))  # No false coast on the tile border
    chart.paste(COAST, mask=edge)
    if seamarks is not None:
        chart = chart.convert("RGBA")
        chart.alpha_composite(seamarks.convert("RGBA"))
        chart = chart.convert("RGB")
    return chart


def imagery_tile(image: Image.Image) -> Image.Image:
    image = ImageEnhance.Color(image.convert("RGB")).enhance(.72)
    return ImageEnhance.Brightness(image).enhance(.8)


def fetch_tile(source: TileSource, z: int, x: int, y: int) -> bytes:
    """Download one tile from the network and return the finished image file."""
    if source.id == "satellite-esri":
        image = imagery_tile(Image.open(BytesIO(_get(IMAGERY_URL.format(z=z, x=x, y=y)))))
        output = BytesIO()
        image.save(output, "JPEG", quality=88)
        return output.getvalue()
    relief = Image.open(BytesIO(_get(RELIEF_URL.format(z=z, x=x, y=y))))
    try:
        mask = Image.open(BytesIO(_get(MASK_URL.format(z=z, x=x, y=y))))
    except Exception:
        mask = None  # The relief alone still makes a usable chart.
    seamarks = None
    if z >= SEAMARK_MIN_ZOOM:
        try:
            seamarks = Image.open(BytesIO(_get(SEAMARK_URL.format(z=z, x=x, y=y), timeout=6)))
        except Exception:
            seamarks = None
    output = BytesIO()
    tactical_tile(relief, mask, seamarks, 5 if z <= 9 else 3).save(output, "PNG", optimize=True)
    return output.getvalue()


def tile_path(cache_root: Path, source: TileSource, key: tuple[int, int, int]) -> Path:
    z, x, y = key
    return cache_root.parent / source.id / str(z) / str(x) / f"{y}.{source.ext}"


# --- Coordinates -----------------------------------------------------------------------------

def degrees_minutes(value: float, positive: str, negative: str, degree_digits: int) -> str:
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(value)
    minutes = (value - degrees) * 60
    if minutes >= 59.995:
        degrees, minutes = degrees + 1, 0.0
    return f"{degrees:0{degree_digits}d}°{minutes:05.2f}′{hemisphere}"


def position_text(lat: float, lon: float) -> str:
    return f"{degrees_minutes(lat, 'N', 'S', 2)} {degrees_minutes(lon, 'E', 'W', 3)}"


def mgrs(lat: float, lon: float, digits: int = 5) -> str:
    """Military Grid Reference System for WGS84 (UTM band; polar UPS zones are not covered)."""
    if not -80 <= lat < 84:
        return "outside UTM"
    zone = int((lon + 180) // 6) + 1
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat < 84 and lon >= 0:
        zone = 31 if lon < 9 else 33 if lon < 21 else 35 if lon < 33 else 37 if lon < 42 else zone
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi = math.radians(lat)
    lam = math.radians(lon - ((zone - 1) * 6 - 180 + 3))
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    big_a = math.cos(phi) * lam
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    easting = k0 * n * (big_a + (1 - t + c) * big_a ** 3 / 6
                        + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * big_a ** 5 / 120) + 500000
    northing = k0 * (m + n * math.tan(phi) * (big_a ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * big_a ** 4 / 24
                                             + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * big_a ** 6 / 720))
    if lat < 0:
        northing += 10000000
    band = "CDEFGHJKLMNPQRSTUVWX"[min(19, int((lat + 80) // 8))]
    column = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")[(zone - 1) % 3][int(easting // 100000) - 1]
    row = "ABCDEFGHJKLMNPQRSTUV"[(int(northing // 100000) + (5 if zone % 2 == 0 else 0)) % 20]
    scale = 10 ** (5 - digits)
    east = int(easting % 100000) // scale
    north = int(northing % 100000) // scale
    return f"{zone}{band} {column}{row} {east:0{digits}d} {north:0{digits}d}"


def dtg(moment: datetime | None = None) -> str:
    """Date-time group, for example 161030ZOCT26."""
    moment = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{moment:%d%H%M}Z{moment:%b%y}".upper()


# --- Chart furniture -------------------------------------------------------------------------

MARGIN = 18
GRID = "#2a4654"
RULER_BG = "#070b0f"
RULER_INK = "#9fb3bd"
ACCENT = "#46d1c4"
# Menlo exists only on macOS; Windows has Consolas. A missing family would fall back to a proportional font.
MONO = "Menlo" if sys.platform == "darwin" else "Consolas"
FONT = (MONO, 8)
FONT_BOLD = (MONO, 9, "bold")
MARGIN_TAGS = ("chart-furniture", "chart-margin")


def _grid_step(span_degrees: float) -> float:
    """A round lat/lon spacing that gives about six lines across the view."""
    for step in (1 / 60, 2 / 60, 5 / 60, 10 / 60, 15 / 60, 30 / 60, 1, 2, 5, 10, 15, 30, 45):
        if span_degrees / step <= 7:
            return step
    return 90


def _label(value: float, positive: str, negative: str, step: float, degree_digits: int) -> str:
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(round(value * 60)) // 60
    minutes = int(round(value * 60)) % 60
    if step >= 1:
        return f"{degrees:0{degree_digits}d}°{hemisphere}"
    return f"{degrees:0{degree_digits}d}°{minutes:02d}′{hemisphere}"


def draw_grid(app, width: int, height: int, geo_to_world, world_to_geo, tile_size: int) -> None:
    """Lat/lon grid over the chart and a graduated margin scale on the top and left edges."""
    canvas, z = app.map, app.map_zoom
    world = tile_size * 2 ** z
    center_x, center_y = geo_to_world(*app.map_center, z)
    lon_left = ((center_x - width / 2) / world) * 360 - 180
    lon_right = ((center_x + width / 2) / world) * 360 - 180
    lat_top = world_to_geo(center_x, center_y - height / 2, z)[0]
    lat_bottom = world_to_geo(center_x, center_y + height / 2, z)[0]
    lon_step = _grid_step(lon_right - lon_left)
    lat_step = _grid_step(max(1e-6, lat_top - lat_bottom))
    canvas.create_rectangle(0, 0, width, MARGIN, fill=RULER_BG, outline="", tags=MARGIN_TAGS)
    canvas.create_rectangle(0, 0, MARGIN, height, fill=RULER_BG, outline="", tags=MARGIN_TAGS)
    first = math.ceil(lon_left / lon_step) * lon_step
    for index in range(80):
        lon = first + index * lon_step
        if lon > lon_right:
            break
        x = (lon + 180) / 360 * world - center_x + width / 2
        if x < MARGIN + 2:
            continue
        canvas.create_line(x, MARGIN, x, height, fill=GRID, dash=(2, 5), tags="chart-furniture")
        canvas.create_line(x, MARGIN - 6, x, MARGIN, fill=RULER_INK, tags=MARGIN_TAGS)
        canvas.create_text(x + 3, MARGIN / 2, text=_label(((lon + 180) % 360) - 180, "E", "W", lon_step, 3),
                           anchor="w", fill=RULER_INK, font=FONT, tags=MARGIN_TAGS)
        for minor in range(1, 5):
            minor_x = x + minor * lon_step / 5 / 360 * world
            if minor_x < width:
                canvas.create_line(minor_x, MARGIN - 3, minor_x, MARGIN, fill=RULER_INK, tags=MARGIN_TAGS)
    first = math.ceil(lat_bottom / lat_step) * lat_step
    for index in range(80):
        lat = first + index * lat_step
        if lat > lat_top:
            break
        if abs(lat) >= 85:
            continue
        y = geo_to_world(lat, 0, z)[1] - center_y + height / 2
        if y < MARGIN + 2:
            continue
        canvas.create_line(MARGIN, y, width, y, fill=GRID, dash=(2, 5), tags="chart-furniture")
        canvas.create_line(MARGIN - 6, y, MARGIN, y, fill=RULER_INK, tags=MARGIN_TAGS)
        canvas.create_text(MARGIN / 2, y - 3, text=_label(lat, "N", "S", lat_step, 2), angle=90,
                           anchor="w", fill=RULER_INK, font=FONT, tags=MARGIN_TAGS)
        for minor in range(1, 5):
            minor_y = geo_to_world(lat + minor * lat_step / 5, 0, z)[1] - center_y + height / 2
            if minor_y > MARGIN:
                canvas.create_line(MARGIN - 3, minor_y, MARGIN, minor_y, fill=RULER_INK, tags=MARGIN_TAGS)
    canvas.create_rectangle(0, 0, MARGIN, MARGIN, fill=RULER_BG, outline="", tags=MARGIN_TAGS)
    canvas.create_line(MARGIN, MARGIN, width, MARGIN, fill="#33505e", tags=MARGIN_TAGS)
    canvas.create_line(MARGIN, MARGIN, MARGIN, height, fill="#33505e", tags=MARGIN_TAGS)


def draw_north_arrow(canvas, x: float, y: float) -> None:
    radius = 22
    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline="#3b5967", width=1, tags="chart-furniture")
    for angle in range(0, 360, 30):
        inner = radius - (5 if angle % 90 == 0 else 3)
        rad = math.radians(angle)
        canvas.create_line(x + inner * math.sin(rad), y - inner * math.cos(rad),
                           x + radius * math.sin(rad), y - radius * math.cos(rad), fill="#5d7c89", tags="chart-furniture")
    canvas.create_polygon(x, y - radius + 4, x + 6, y + 2, x, y - 2, fill=ACCENT, outline="", tags="chart-furniture")
    canvas.create_polygon(x, y - radius + 4, x - 6, y + 2, x, y - 2, fill="#1f6f69", outline="", tags="chart-furniture")
    canvas.create_polygon(x, y + radius - 4, x + 6, y - 2, x, y + 2, fill="#4b5a62", outline="", tags="chart-furniture")
    canvas.create_polygon(x, y + radius - 4, x - 6, y - 2, x, y + 2, fill="#26323a", outline="", tags="chart-furniture")
    canvas.create_text(x, y - radius - 8, text="N", fill=ACCENT, font=FONT_BOLD, tags="chart-furniture")


def draw_scale_bar(canvas, width: int, height: int, lat: float, zoom: int, tile_size: int, card: str, line: str) -> None:
    """Segmented nautical-mile bar with kilometres underneath, like a paper chart."""
    km_per_pixel = math.cos(math.radians(lat)) * 40075.017 / (tile_size * 2 ** zoom)
    nm_per_pixel = km_per_pixel / 1.852
    target = nm_per_pixel * 150
    power = 10 ** math.floor(math.log10(max(target, 1e-6)))
    nm = next(v * power for v in (1, 2, 5, 10) if v * power >= target)
    pixels = nm / nm_per_pixel
    right, bottom = width - 72, height - 124  # Above the layer bar and the zoom buttons
    left = right - pixels
    canvas.create_rectangle(left - 10, bottom - 34, right + 12, bottom + 16, fill=card, outline=line, tags="chart-furniture")
    for part in range(4):
        x1 = left + pixels * part / 4
        canvas.create_rectangle(x1, bottom - 4, x1 + pixels / 4, bottom, outline="#c9d6dc",
                                fill="#c9d6dc" if part % 2 == 0 else card, tags="chart-furniture")
    canvas.create_text(left, bottom - 10, text="0", anchor="sw", fill=RULER_INK, font=FONT, tags="chart-furniture")
    canvas.create_text(right, bottom - 10, text=f"{nm:g} NM", anchor="se", fill="#dfe8ec", font=FONT_BOLD, tags="chart-furniture")
    canvas.create_text(right, bottom + 3, text=f"{nm * 1.852:.3g} km", anchor="ne", fill=RULER_INK, font=FONT, tags="chart-furniture")
    denominator = km_per_pixel * 1000 / 0.000264583  # 96 dpi screen pixel = 0.2646 mm
    ratio = f"1:{denominator / 1e6:.2f}M" if denominator >= 1e6 else f"1:{denominator / 1e3:.0f}k"
    canvas.create_text(left, bottom + 3, text=f"Z{zoom} · {ratio}", anchor="nw", fill=RULER_INK, font=FONT, tags="chart-furniture")


def readout_text(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "CURSOR  —  move over the chart"
    return f"{position_text(lat, lon)}   MGRS {mgrs(lat, lon, 4)}"


def draw_readout(app, width: int) -> None:
    lat, lon = getattr(app, "_cursor_geo", (None, None))
    text = readout_text(lat, lon)
    x = width - 12 - 215  # Top right, clear of the chart title and the tool rail below it
    app.map.create_rectangle(x - 215, MARGIN + 6, x + 215, MARGIN + 28, fill=RULER_BG, outline="#33505e",
                             tags=("chart-furniture", "chart-readout-box"))
    app.map.create_text(x, MARGIN + 17, text=text, fill="#dfe8ec", font=FONT_BOLD,
                        tags=("chart-furniture", "chart-readout"))


def update_readout(app, lat: float, lon: float) -> None:
    app._cursor_geo = (lat, lon)
    app.map.itemconfigure("chart-readout", text=readout_text(lat, lon))
    app.map.tag_raise("chart-readout-box")
    app.map.tag_raise("chart-readout")


def draw_frame(canvas, width: int, height: int) -> None:
    """Corner brackets around the chart, the usual mark of a tactical display."""
    length = 26
    for x, y, dx, dy in ((MARGIN + 4, MARGIN + 4, 1, 1), (width - 4, MARGIN + 4, -1, 1),
                         (MARGIN + 4, height - 4, 1, -1), (width - 4, height - 4, -1, -1)):
        canvas.create_line(x, y + dy * length, x, y, x + dx * length, y, fill=ACCENT, width=2, tags="chart-furniture")
