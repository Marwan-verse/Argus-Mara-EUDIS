"""Opt-in satellite catalogue and georeferenced crops, separate from the demo.

Only public, allowlisted catalogues are contacted. Whole-scene quicklooks are
never treated as georeferenced vessel imagery. Rasterio is an optional extra.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from argus.provenance import now_utc, utc
from argus.space import finite

CATALOGUE = 'https://earth-search.aws.element84.com/v1'
SAR_CATALOGUE = 'https://stac.dataspace.copernicus.eu/v1'
IRISH_BBOX = [-18., 49., -4., 57.5]
COLLECTIONS = {'Sentinel-2': 'sentinel-2-l2a', 'Sentinel-1': 'sentinel-1-grd'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def json_http(url, payload=None, key=None, timeout=40):
    """Bounded JSON transport; never disclose upstream response bodies or keys."""
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS is required')
    headers = {'Accept': 'application/json', 'User-Agent': 'ArgusMaraSatellite/1.0'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    raw = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    if raw is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with build_opener(NoRedirect()).open(Request(url, data=raw, headers=headers), timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('Provider response exceeds limit')
            return json.loads(raw)
    except HTTPError as error:
        if error.code >= 500:
            raise ValueError(f'Provider image/API service is unavailable (HTTP {error.code}); no automatic retry') from None
        raise ValueError(f'Provider refused request (HTTP {error.code}); check access and credits') from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('Cannot read a secure provider response') from None


def bounds(value, *, small=False):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('Use west, south, east, north coordinates')
    w, s, e, n = [finite(v, 'bounds') for v in value]
    if not (-18 <= w < e <= -4 and 49 <= s < n <= 57.5):
        raise ValueError('Choose an area within Irish waters (-18..-4 longitude, 49..57.5 latitude)')
    # About 10 km each way: keep ships visible at 10 m sampling and limit cost.
    if small and ((e-w) * math.cos(math.radians((s+n)/2)) > .10 or n-s > .10):
        raise ValueError('Zoom in: the analysis area must be at most about 11 km across')
    return [w, s, e, n]


def search(sensor, area, start, end, transport=json_http, *, all_pages=False):
    area = bounds(area)
    if sensor not in COLLECTIONS:
        raise ValueError('Choose Sentinel-1 or Sentinel-2')
    first, last = datetime.fromisoformat(utc(start)), datetime.fromisoformat(utc(end))
    if not timedelta(0) < last-first <= timedelta(days=31):
        raise ValueError('Search a time window of 1 second to 31 days')
    base = SAR_CATALOGUE if sensor == 'Sentinel-1' else CATALOGUE
    query = urlencode({'collections': COLLECTIONS[sensor], 'bbox': ','.join(map(str, area)),
                       'datetime': utc(start)+'/'+utc(end), 'limit': 30,
                       'sortby': '-datetime' if sensor == 'Sentinel-1' else '-properties.datetime'})
    url = base+'/search?'+query
    scenes = []
    items, seen = [], set()
    for page in range(20 if all_pages else 1):
        if url in seen:
            raise ValueError('Catalogue repeated a page; coverage is incomplete')
        seen.add(url)
        result = transport(url)
        items.extend(result.get('features', [])[:30])
        following = next((link for link in result.get('links', []) if link.get('rel') == 'next'), None)
        if not all_pages or not following:
            break
        url = following.get('href', '')
        # Pagination is never permission to fetch an arbitrary provider URL.
        parsed, expected = urlsplit(url), urlsplit(base)
        if (parsed.scheme != 'https' or parsed.netloc != expected.netloc or
                parsed.path != expected.path+'/search' or parsed.fragment or
                following.get('method', 'GET') != 'GET'):
            raise ValueError('Unsupported catalogue pagination; coverage is incomplete')
    else:
        raise ValueError('Catalogue page limit reached; narrow the discovery window')
    for item in items:
        props = item.get('properties', {})
        if not props.get('datetime'):
            continue
        identifier = item.get('id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', identifier):
            continue
        scenes.append({'id': identifier, 'sensor': sensor, 'acquired_utc': utc(props['datetime']),
                       'bbox': item.get('bbox'), 'cloud_percent': props.get('eo:cloud_cover'),
                       'label': 'real', 'source': base,
                       'asset': item.get('assets', {}).get('visual', {}).get('href'),
                       'quality_asset': item.get('assets', {}).get('scl', {}).get('href'),
                       'data_access': 'Public optical COG' if sensor == 'Sentinel-2'
                                      else 'Import calibrated, terrain-corrected GeoTIFF; CDSE access required'})
    return sorted(scenes, key=lambda row: row['acquired_utc'], reverse=True)


def mercator(lon, lat):
    return 6378137 * math.radians(lon), 6378137 * math.log(math.tan(math.pi/4+math.radians(lat)/2))


def pixel_location(scene, x, y):
    """Normalized image coordinates -> actual crop grid -> WGS84 lat/lon."""
    x, y = finite(x, 'x'), finite(y, 'y')
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError('Model image coordinates must be in 0..1')
    left, bottom, right, top = scene['mercator_bounds']
    mx, my = left + x*(right-left), top-y*(top-bottom)
    return {'lat': math.degrees(2*math.atan(math.exp(my/6378137))-math.pi/2),
            'lon': math.degrees(mx/6378137)}


def raster_source(source):
    """Validate every raster input, including quality masks, before GDAL opens it."""
    source = str(source)
    remote = urlsplit(source)
    if remote.scheme and len(remote.scheme) != 1:
        allowed = {'sentinel-cogs.s3.us-west-2.amazonaws.com', 'sentinel-cogs.s3.amazonaws.com'}
        if (remote.scheme != 'https' or remote.hostname not in allowed or remote.username or
                remote.password or remote.port not in (None, 443) or remote.query or remote.fragment):
            raise ValueError('Only public Sentinel optical assets are fetched automatically')
    else:
        local = Path(source).resolve(strict=True)
        if local.suffix.lower() not in {'.tif', '.tiff'}:
            raise ValueError('Import a calibrated, terrain-corrected GeoTIFF')
        source = str(local)
    return source


def crop_scene(source, area, output_dir, *, scene_id, acquired_utc, sensor, label='real', quality_source=None):
    """Reproject a local GeoTIFF or allowlisted public RGB COG to a small grid."""
    area = bounds(area, small=True)
    if sensor not in COLLECTIONS or label not in {'real', 'reconstructed', 'simulated', 'fictional', 'assumption'}:
        raise ValueError('A valid sensor and evidence label are required')
    acquired_utc = utc(acquired_utc)
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.vrt import WarpedVRT
        from rasterio.transform import from_bounds
    except ImportError:
        raise ValueError('Install requirements-satellite.txt to read satellite rasters') from None
    from PIL import Image
    source = raster_source(source)
    quality_source = raster_source(quality_source) if quality_source is not None else None
    remote = urlsplit(source)
    w, s, e, n = area
    left, bottom = mercator(w, s)
    right, top = mercator(e, n)
    # Preserve roughly 10 m ground sampling; no whole-scene downsample detection.
    scale = math.cos(math.radians((s+n)/2))
    width = min(1024, max(64, math.ceil((right-left)*scale/10)))
    height = min(1024, max(64, math.ceil((top-bottom)*scale/10)))
    transform = from_bounds(left, bottom, right, top, width, height)
    quality_content = None
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
                          CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff',
                          GDAL_HTTP_TIMEOUT='30', GDAL_HTTP_MAX_RETRY='0',
                          GDAL_HTTP_FOLLOWLOCATION='NO', GDAL_CACHEMAX=32):
            with rasterio.open(source) as dataset:
                if not dataset.crs:
                    raise ValueError('Raster has no coordinate reference system')
                if sensor == 'Sentinel-2' and dataset.count < 3:
                    raise ValueError('Optical import needs three RGB bands')
                indexes = [1, 2, 3] if sensor == 'Sentinel-2' else [1]
                with WarpedVRT(dataset, crs='EPSG:3857', transform=transform,
                               width=width, height=height, resampling=Resampling.bilinear,
                               add_alpha=rasterio.enums.ColorInterp.alpha not in dataset.colorinterp) as vrt:
                    values = vrt.read(indexes=indexes, masked=True)
                valid = ~np.ma.getmaskarray(values).any(axis=0)
                valid &= np.isfinite(values.data).all(axis=0)
                if valid.mean() < .5:
                    raise ValueError('Less than half of this crop has valid imagery; choose an overlapping area')
                pixels = values.filled(0).astype('float32')
                if sensor == 'Sentinel-1':
                    # Display stretch only; no CFAR or ship-length measurement claimed.
                    finite_values = pixels[0][valid]
                    lo, hi = np.percentile(finite_values, (2, 99.5))
                    pixels = np.repeat(np.clip((pixels-lo)/max(hi-lo, 1e-8)*255, 0, 255), 3, axis=0)
                elif pixels.max() > 255:
                    lo, hi = np.percentile(pixels[:, valid], (2, 98))
                    pixels = np.clip((pixels-lo)/max(hi-lo, 1e-8)*255, 0, 255)
                pixels[:, ~valid] = 0
                buffer = BytesIO()
                Image.fromarray(pixels.transpose(1, 2, 0).astype('uint8')).save(buffer, format='PNG')
            if quality_source:
                with rasterio.open(quality_source) as dataset:
                    if not dataset.crs:
                        raise ValueError('Quality mask has no coordinate reference system')
                    with WarpedVRT(dataset, crs='EPSG:3857', transform=transform, width=width,
                                   height=height, resampling=Resampling.nearest, nodata=0) as vrt:
                        quality = vrt.read(1).astype('uint8')
                    quality[~valid] = 0
                    quality_buffer = BytesIO()
                    Image.fromarray(quality).save(quality_buffer, format='PNG')
                    quality_content = quality_buffer.getvalue()
    except rasterio.errors.RasterioError:
        raise ValueError('Cannot read georeferenced imagery; verify raster access, calibration and crop overlap') from None
    content = buffer.getvalue()
    image_hash = hashlib.sha256(content).hexdigest()
    identifier = hashlib.sha256((str(scene_id)+acquired_utc+image_hash+str(area)).encode()).hexdigest()[:24]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output/(identifier+'.png')).write_bytes(content)
    scene = {'id': identifier, 'product_id': str(scene_id)[:200], 'sensor': sensor, 'label': label,
             'source': 'Copernicus Sentinel / Element 84 Earth Search' if remote.scheme == 'https' else 'Operator-imported georeferenced raster',
             'acquired_utc': acquired_utc, 'bbox': area, 'mercator_bounds': [left, bottom, right, top],
             'width': width, 'height': height, 'image_sha256': image_hash,
             'valid_fraction': round(float(valid.mean()), 4), 'prepared_utc': now_utc(),
             'caveat': 'Image pixels are observations; AI contact locations are unvalidated assumptions. Cloud, land, wakes and radar clutter can cause false detections.'}
    if quality_content:
        (output/(identifier+'.quality.png')).write_bytes(quality_content)
        scene['quality_sha256'] = hashlib.sha256(quality_content).hexdigest()
        scene['quality_source'] = 'Sentinel-2 L2A scene classification; native 20 m, nearest-neighbour on crop grid'
    atomic_json(output/(identifier+'.json'), scene)
    return scene


def replace_file(source, target):
    """Same-volume publication, with write-through metadata on Windows (D57)."""
    import os
    if os.name != 'nt':
        source.replace(target)
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    move = kernel.MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    if not move(str(source.absolute()), str(target.absolute()), 0x1 | 0x8):
        raise ctypes.WinError(ctypes.get_last_error())


def atomic_json(path, value):
    import tempfile
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem+'-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers briefly deny replacement. Retrying this exact local
        # publication cannot repeat a request or charge. Persistent failure still
        # raises before any paid call whose reservation was not durable.
        import time
        for attempt in range(8):
            try:
                replace_file(temp, path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                    raise
                time.sleep(.02*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)
