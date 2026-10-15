"""Cheap optical triage, NOT a validated or exhaustive ship detector.

Copernicus SCL: 6 water, 7 unclassified, 8/9 cloud, 10 cirrus. Clouds,
shadows and land are excluded conservatively, so nearshore ships can be missed.
Only compact high-contrast water features justify a paid image review.
"""
import hashlib
from io import BytesIO

REVISION = 'optical-water-triage-v1'


def quality_preview(source, area):
    """Read the small SCL window before paying bandwidth for an RGB crop."""
    import math
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.vrt import WarpedVRT
    from argus.satellite import bounds, mercator, raster_source
    w, s, e, n = bounds(area, small=True)
    left, bottom = mercator(w, s)
    right, top = mercator(e, n)
    scale = math.cos(math.radians((s+n)/2))
    width, height = min(512, max(32, math.ceil((right-left)*scale/20))), min(512, max(32, math.ceil((top-bottom)*scale/20)))
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff',
                          GDAL_HTTP_TIMEOUT='30', GDAL_HTTP_MAX_RETRY='0', GDAL_HTTP_FOLLOWLOCATION='NO', GDAL_CACHEMAX=32):
            with rasterio.open(raster_source(source)) as dataset:
                if not dataset.crs:
                    raise ValueError('Quality raster has no coordinate reference system')
                with WarpedVRT(dataset, crs='EPSG:3857', transform=from_bounds(left, bottom, right, top, width, height),
                               width=width, height=height, resampling=Resampling.nearest, nodata=0) as vrt:
                    scl = vrt.read(1)
    except rasterio.errors.RasterioError:
        raise ValueError('Cannot read satellite quality pixels; coverage remains incomplete') from None
    water = float((scl == 6).mean())
    return {'revision': REVISION, 'label': 'assumption', 'water_fraction': round(water, 4),
            'cloud_fraction': round(float(np.isin(scl, [8, 9, 10]).mean()), 4),
            'valid_fraction': round(float((scl > 0).mean()), 4), 'load_rgb': water >= .002,
            'status': 'quality_pass' if water >= .002 else 'unobservable_water', 'candidate_count': 0,
            'caveat': 'SCL preview only. Cloud, shadow, land and no-data are not ship-free observations.'}


def water_mask(scene, folder):
    from PIL import Image, ImageFilter
    import numpy as np
    path = folder/(scene['id']+'.quality.png')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != scene.get('quality_sha256'):
        raise ValueError('Satellite quality mask integrity check failed')
    scl = np.array(Image.open(BytesIO(raw)))
    if scl.shape != (scene['height'], scene['width']):
        raise ValueError('Satellite quality mask does not match the image grid')
    water = scl == 6
    # Permit unclassified bright objects only immediately surrounded by water.
    neighbourhood = np.array(Image.fromarray(water.astype('uint8')*255).filter(ImageFilter.BoxBlur(3)))
    eligible = water | ((scl == 7) & (neighbourhood > 140))
    unsafe = (~eligible).astype('uint8')*255
    excluded = np.array(Image.fromarray(unsafe).filter(ImageFilter.MaxFilter(7))) > 0
    return eligible & ~excluded, scl


def screen(scene, image, folder):
    from PIL import Image, ImageFilter
    import numpy as np
    allowed, scl = water_mask(scene, folder)
    pixels = np.array(Image.open(BytesIO(image)).convert('L'))
    stats = {'revision': REVISION, 'label': 'assumption', 'eligible_water_fraction': round(float(allowed.mean()), 4),
             'cloud_fraction': round(float(np.isin(scl, [8, 9, 10]).mean()), 4),
             'candidate_count': 0, 'exhaustive': False,
             'caveat': 'Experimental optical triage can miss dark, small, coastal or obscured vessels. No candidate is not evidence of no ships.'}
    if allowed.sum() < 1000:
        return {**stats, 'status': 'unobservable_water', 'send_to_ai': False}
    level = pixels[allowed].astype('float32')
    median = float(np.median(level))
    mad = float(np.median(abs(level-median)))
    background = np.array(Image.fromarray(pixels).filter(ImageFilter.BoxBlur(5))).astype('float32')
    possible = allowed & (pixels > max(65, median+max(25, 6*mad))) & (pixels.astype('float32')-background > 22)
    # Eight-connected components, bounded by the image size. Large patches are
    # clutter, not dozens of invented ship points.
    remaining = {int(y)*pixels.shape[1]+int(x) for y, x in zip(*np.nonzero(possible))}
    width, height = pixels.shape[1], pixels.shape[0]
    count = 0
    while remaining:
        seed = remaining.pop()
        stack, group = [seed], []
        while stack:
            value = stack.pop()
            group.append(value)
            y, x = divmod(value, width)
            for yy in range(max(0, y-1), min(height, y+2)):
                for xx in range(max(0, x-1), min(width, x+2)):
                    nxt = yy*width+xx
                    if nxt in remaining:
                        remaining.remove(nxt)
                        stack.append(nxt)
        if 2 <= len(group) <= 200:
            ys, xs = zip(*(divmod(p, width) for p in group))
            if max(max(xs)-min(xs)+1, max(ys)-min(ys)+1) <= 70:
                count += 1
        if count > 100:
            return {**stats, 'candidate_count': count, 'status': 'clutter_review_required', 'send_to_ai': False}
    return {**stats, 'candidate_count': count, 'status': 'possible_contacts' if count else 'no_local_candidates',
            'send_to_ai': count > 0}


def retain_water_contacts(scene, contacts, folder):
    allowed, _ = water_mask(scene, folder)
    retained, excluded = [], []
    for point in contacts:
        x = min(scene['width']-1, max(0, round(point['x']*(scene['width']-1))))
        y = min(scene['height']-1, max(0, round(point['y']*(scene['height']-1))))
        (retained if allowed[y, x] else excluded).append(point)
    return retained, len(excluded)
