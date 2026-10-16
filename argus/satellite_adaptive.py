"""Bounded, resumable detail-window review of crowded satellite crops.

Each component uses the existing verified image route, budget and cache. Failed
paid windows are held, never automatically resubmitted. Coordinates/date come
from the original raster grid, not the model. This is not an exhaustive census.
"""
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from argus.satellite import atomic_json, pixel_location
from argus.satellite_ai import AnalysisBusy, exclusive, read_ledger, MODEL_REVISION, PROMPT_VERSION
from argus.space import distance_km

VERSION = 'four-detail-windows-v1'
CORES = ((0., 0., .5, .5), (.5, 0., 1., .5), (0., .5, .5, 1.), (.5, .5, 1., 1.))


def detail_windows(scene, image):
    """Lossless source-pixel crops with overlap, each assigned a distinct core."""
    if hashlib.sha256(image).hexdigest() != scene['image_sha256']:
        raise ValueError('Adaptive source image hash mismatch')
    with Image.open(BytesIO(image)) as source:
        width, height = source.size
        if source.size != (scene['width'], scene['height']) or not 32 <= min(width, height) <= max(width, height) <= 1024:
            raise ValueError('Adaptive source image grid is invalid')
        source = source.convert('RGB')
        mx, my = width//2, height//2
        ox, oy = min(64, max(2, width//16)), min(64, max(2, height//16))
        boxes = ((0, 0, mx+ox, my+oy), (mx-ox, 0, width, my+oy),
                 (0, my-oy, mx+ox, height), (mx-ox, my-oy, width, height))
        rows = []
        left, bottom, right, top = scene['mercator_bounds']
        for index, (box, core) in enumerate(zip(boxes, CORES)):
            x0, y0, x1, y1 = box
            # Core boundaries follow the integer source-pixel split for odd grids.
            core = ((0 if index % 2 == 0 else mx/width), (0 if index < 2 else my/height),
                    (mx/width if index % 2 == 0 else 1), (my/height if index < 2 else 1))
            normalized = (x0/width, y0/height, x1/width, y1/height)
            raw = BytesIO()
            source.crop(box).save(raw, 'PNG')
            pixels = raw.getvalue()
            a, b = pixel_location(scene, normalized[0], normalized[1]), pixel_location(scene, normalized[2], normalized[3])
            child = {**scene, 'id': hashlib.sha256((scene['id']+'|'+str(box)).encode()).hexdigest()[:24],
                     'parent_scene_id': scene['id'], 'width': x1-x0, 'height': y1-y0,
                     'image_sha256': hashlib.sha256(pixels).hexdigest(),
                     'bbox': [a['lon'], b['lat'], b['lon'], a['lat']],
                     'mercator_bounds': [left+normalized[0]*(right-left), top-normalized[3]*(top-bottom),
                                         left+normalized[2]*(right-left), top-normalized[1]*(top-bottom)]}
            child.pop('quality_sha256', None)
            child.pop('quality_source', None)
            rows.append({'index': index, 'core': list(core), 'window': list(normalized), 'scene': child, 'image': pixels})
        return rows


def crowded(value):
    return value.get('contact_limit_reached') is True or len(value.get('contacts', [])) >= 24


def _global_points(scene, window, visual):
    result = []
    x0, y0, x1, y1 = window['window']
    for point in visual.get('contacts', []):
        x = x0+point['x']*(x1-x0)
        y = y0+point['y']*(y1-y0)
        location = pixel_location(scene, x, y)
        result.append({**point, **location, 'x': x, 'y': y, 'ts': scene['acquired_utc'],
                       'id': f"AI-Q{window['index']}-{point['id']}", 'origin_window': window['index']})
    return result


def review_image(root, scene, image, question, *, analyse, dense=False):
    """Up to one overview plus four detail calls, each independently budgeted."""
    root = Path(root)
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise ValueError('Use an analysis request of 1–500 characters')
    question = question.strip()
    overview = None
    if not dense:
        overview = analyse(root, scene, image, question)
        if not crowded(overview):
            return overview
    windows = detail_windows(scene, image)
    identity = json.dumps([VERSION, MODEL_REVISION, PROMPT_VERSION, question, {k: scene[k] for k in
                          ('image_sha256', 'mercator_bounds', 'acquired_utc', 'sensor', 'label')}], sort_keys=True)
    folder = root/'adaptive'/hashlib.sha256(identity.encode()).hexdigest()
    parts = [overview] if overview else []
    points = [{**p, 'origin_window': 'overview'} for p in overview.get('contacts', [])] if overview else []
    coverage, held = [], False
    with exclusive(root/'adaptive'):
        saved = {}
        for window in windows:
            path = folder/f"window-{window['index']}.json"
            if path.exists():
                entry = json.loads(path.read_text(encoding='utf-8'))
                if entry.get('image_sha256') != window['scene']['image_sha256']:
                    raise ValueError('Adaptive window checkpoint does not match its source pixels')
                if entry.get('status') == 'submitted':
                    entry.update(status='held', error='Interrupted paid window; charge state unconfirmed. No automatic retry.')
                    atomic_json(path, entry)
                saved[window['index']] = entry
                held |= entry.get('status') == 'held'
        for window in windows:
            index, child = window['index'], window['scene']
            path = folder/f'window-{index}.json'
            entry = saved.get(index, {})
            value = None
            if entry.get('status') == 'complete':
                value = {**entry['visual'], 'cached': True}
            elif held:
                entry = entry or {'status': 'pending', 'error': 'Paid review paused after an uncertain window.'}
            else:
                before = read_ledger(root)['calls']
                entry = {'status': 'submitted', 'image_sha256': child['image_sha256']}
                atomic_json(path, entry)  # Durable before the existing paid route.
                try:
                    value = analyse(root, child, window['image'], question)
                    if value.get('image_input_verified') is not True or len(value.get('contacts', [])) > 24:
                        raise ValueError('Detail-window image input/result was not verified')
                    entry.update(status='complete', visual=value)
                except AnalysisBusy:
                    entry['status'] = 'ready'
                    atomic_json(path, entry)
                    raise  # Provably unsubmitted; completed windows are reusable.
                except (ValueError, OSError) as error:
                    charged = read_ledger(root)['calls'] > before
                    entry.update(status='held' if charged else 'blocked', error=str(error)[:200])
                    held = True  # Stop subsequent paid windows for this request.
                atomic_json(path, entry)
            state = 'complete'
            if value is not None:
                if value.get('image_input_verified') is not True:
                    raise ValueError('Saved detail-window image input is unverified')
                parts.append(value)
                points.extend(_global_points(scene, window, value))
                if value.get('image_status') == 'unusable':
                    state = 'unusable'
                elif crowded(value):
                    state = 'capped'
            else:
                state = entry.get('status', 'pending')
            coverage.append({'core': window['core'], 'window': window['window'], 'status': state,
                             'image_input_verified': bool(value and value.get('image_input_verified')),
                             'error': entry.get('error')})
    # Preserve every reported observation. Nearby observations from different
    # windows are flagged for review rather than silently merged into one boat.
    for i, point in enumerate(points):
        for other in points[:i]:
            if point.get('origin_window') != other.get('origin_window') and distance_km(point, other) < .025:
                point['overlap_ambiguous'] = other['overlap_ambiguous'] = True
    for point in points:
        if point.get('overlap_ambiguous'):
            point['description'] = 'Possible duplicate across image windows. '+point.get('description', '')
    incomplete = any(w['status'] != 'complete' for w in coverage)
    return {'adaptive_version': VERSION, 'analysis_windows': coverage, 'analysis_incomplete': incomplete,
            'paid_work_held': held, 'contacts': points, 'image_input_verified': any(p.get('image_input_verified') for p in parts),
            'contact_limit_reached': any(w['status'] == 'capped' for w in coverage),
            'model': parts[0]['model'] if parts else 'unavailable',
            'summary': 'Four detail windows on the original acquisition-time image. '+
                       ('Some windows require review; no exhaustive vessel count.' if incomplete else 'All four requests returned below their contact caps; detection is still unvalidated.'),
            'limitations': ['Cloud, small vessels, wakes, glint and model errors can cause misses or false contacts.',
                            'Observations may overlap; all are listed and possible duplicates are flagged.',
                            'A failed or capped window cannot support a missing-detection lead.'],
            'reported_cost_usd': sum(p.get('reported_cost_usd', 0) for p in parts),
            'cached': bool(parts) and all(p.get('cached') for p in parts), 'label': 'assumption',
            'review_status': 'unreviewed'}
