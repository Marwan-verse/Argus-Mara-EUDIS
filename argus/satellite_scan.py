"""Opt-in, resumable coastal image queue and independent private AIS capture.

Catalogue discovery is free every 30 minutes. Each new tile/product is attempted
once. A durable 'processing' record precedes any paid call: interrupted or failed
requests are never automatically resubmitted. The existing global $20 ledger and
AI exclusive lock apply to both manual and automatic reviews.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading

from argus import satellite
from argus.provenance import now_utc
from argus.satellite_capture import AISCapture
from argus.satellite_ai import AnalysisBusy
from argus.satellite_screen import REVISION, quality_preview, screen
from argus.space import timestamp

COASTS = ('North', 'East', 'South', 'West')


def coast_for_bounds(area):
    """Planning sectors around the island's centre, not jurisdiction borders."""
    west, south, east, north = area
    x = ((west+east)/2+8)*math.cos(math.radians(53.4))
    y = (south+north)/2-53.4
    if abs(y) >= abs(x):
        return 'North' if y >= 0 else 'South'
    return 'East' if x >= 0 else 'West'


def coast_progress(layout, state):
    result = {side: {'total_tiles': 0, 'covered_tiles': 0, 'queued': 0,
                     'obscured': 0, 'held': 0, 'active': 0} for side in COASTS}
    sides = {tile['id']: coast_for_bounds(tile['bbox']) for tile in layout['tiles']}
    for side in sides.values():
        result[side]['total_tiles'] += 1
    for tile, row in state.get('coverage', {}).items():
        side = sides.get(tile)
        if side:
            result[side]['covered_tiles'] += 1
            result[side]['obscured'] += row.get('status') == 'unobservable_water'
    for job in state.get('jobs', {}).values():
        side = sides.get(job.get('tile'))
        if not side and job.get('bbox'):
            side = coast_for_bounds(job['bbox'])
        if side:
            result[side]['queued'] += job['status'] == 'queued'
            result[side]['active'] += job['status'] == 'processing'
            result[side]['held'] += job['status'] in {'failed_review_required', 'interrupted_review_required', 'clutter_review_required', 'partial_review_required'}
    return result


def read_state(root):
    path = Path(root)/'scan/state.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'enabled': False, 'jobs': {}, 'coverage': {}, 'last_discovery_utc': None, 'message': 'Coastal scan is off'}


def grid():
    return json.loads(Path(__file__).with_name('coastal_grid.json').read_text(encoding='utf-8'))


FRESH_DEFAULT_H = 36  # run_gui.py --coast-watch (SATELLITE-WATCH launchers)


def max_image_age():
    """Optional fresh-image window; run_gui.py --coast-watch sets it, unset keeps seven days."""
    raw = os.environ.get('ARGUS_SATELLITE_MAX_IMAGE_AGE_H', '').strip()
    if not raw:
        return None
    try:
        hours = float(raw)
    except ValueError:
        raise ValueError('ARGUS_SATELLITE_MAX_IMAGE_AGE_H must be a number of hours') from None
    if not 6 <= hours <= 168:
        raise ValueError('ARGUS_SATELLITE_MAX_IMAGE_AGE_H must be between 6 and 168 hours')
    return timedelta(hours=hours)


def scan_status(root):
    path = Path(root)/'scan/summary.json'
    if path.exists():
        result = json.loads(path.read_text(encoding='utf-8'))
        result['running'] = (result.get('enabled', False) and (Path(root)/'scan/worker.lock').exists() and
                             timestamp(now_utc())-timestamp(result['updated_utc']) < 180)
        return result
    layout = grid()
    return {'enabled': False, 'running': False, 'total_tiles': len(layout['tiles']), 'covered_tiles': 0,
            'queued': 0, 'statuses': {}, 'scope': layout['scope'], 'message': 'Coastal scan is off',
            'coasts': coast_progress(layout, {}), 'next_coast': 'North',
            'catalogue_interval_s': 1800, 'ais_interval_s': 60, 'pilot_limit_usd': 20}


class CoastalScan:
    def __init__(self, workspace):
        self.workspace = workspace
        self.folder = workspace.root/'scan'
        self.layout = grid()
        self.state = read_state(workspace.root)
        self.guard = threading.RLock()
        self.halt = threading.Event()
        self.thread = None
        self.capture = AISCapture(workspace)
        self.lease = self.folder/'worker.lock'

    def publish(self):
        # Callers hold guard; the file is atomically visible to other processes.
        satellite.atomic_json(self.folder/'state.json', self.state)
        statuses = Counter(row['status'] for row in self.state['jobs'].values())
        summary = {key: self.state.get(key) for key in
                   ('enabled', 'analysis_paused', 'message', 'last_discovery_utc', 'last_tile_utc', 'ais', 'ais_error', 'history', 'tiles_without_image')}
        summary.update({'updated_utc': now_utc(), 'statuses': dict(statuses),
                        'coasts': coast_progress(self.layout, self.state),
                        'next_coast': self.state.get('next_coast', 'North'),
                        'total_tiles': len(self.layout['tiles']), 'covered_tiles': len(self.state['coverage']),
                        'queued': statuses['queued'], 'scope': self.layout['scope'],
                        'catalogue_interval_s': 1800, 'ais_interval_s': 60, 'pilot_limit_usd': 20,
                        'caveat': 'Rolling optical screening, not a census. Clouds, 10 m resolution, triage and missing AIS cause missed contacts. SAR is available through calibrated imports.'})
        satellite.atomic_json(self.folder/'summary.json', summary)

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                if self.halt.is_set():
                    raise ValueError('The previous scan is stopping; wait for its current request to finish')
                if self.state.get('analysis_paused'):
                    from argus.satellite_ai import PILOT_USD, read_ledger
                    ledger = read_ledger(self.workspace.root/'ai')
                    if ledger.get('halted') or ledger['reserved_usd'] >= PILOT_USD-.06:
                        raise ValueError('Pilot ceiling reached; AIS recording continues. Preserve the budget ledger.')
                    self.state.update(analysis_paused=False, message='Resuming queued images; failed attempts remain held for review')
                    self.publish()
                return scan_status(self.workspace.root)
            from argus.satellite_ai import get_key
            if not get_key():
                raise ValueError('Connect TensorX before starting automatic coastal review')
            # Fail before any network request if raster extras are unavailable.
            try:
                import numpy  # noqa: F401
                import rasterio  # noqa: F401
            except ImportError:
                raise ValueError('Install requirements-satellite.txt in this app or use the satellite Docker image') from None
            self.folder.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(self.lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise ValueError('A coastal worker already owns this workspace, or stopped unexpectedly. Check the host before clearing scan/worker.lock') from None
            os.close(fd)
            self.state = read_state(self.workspace.root)
            for job in self.state['jobs'].values():
                if job['status'] == 'processing':
                    job.update(status='interrupted_review_required', error='Interrupted attempt; no automatic paid retry')
            self.state.update(enabled=True, message='Discovering new coastal images; recording partial AIS reception')
            self.halt.clear()
            try:
                self.publish()
                # A normal window close signals halt, then lets any in-flight
                # paid request publish its result and release locks before exit.
                self.thread = threading.Thread(target=self.run, daemon=False, name='argus-coastal-scan')
                self.thread.start()
            except Exception:
                self.lease.unlink(missing_ok=True)
                raise
        return scan_status(self.workspace.root)

    def stop(self, *, suspend=False):
        with self.guard:
            self.halt.set()
            if not suspend:
                self.state['enabled'] = False
                self.state['message'] = 'Stopped. An in-flight request may finish; no further image will be submitted.'
                # Another process owns the lease: never overwrite its queue.
                if self.thread and self.thread.is_alive() or not self.lease.exists():
                    self.publish()
                else:
                    raise ValueError('Stop the scan in the application or SOC host that started it')
        return scan_status(self.workspace.root)

    def discover(self, now=None, search=satellite.search):
        now = now or datetime.now(timezone.utc)
        last = self.state.get('last_discovery_utc')
        start = max(now-timedelta(days=7), datetime.fromtimestamp(timestamp(last), timezone.utc)-timedelta(days=2)) if last else now-timedelta(days=7)
        # A fresh window keeps a first start from paying for older images that
        # predate the AIS history they would be compared with.
        fresh = max_image_age()
        if fresh:
            start = max(start, now-fresh)
        boxes = [tile['bbox'] for tile in self.layout['tiles']]
        region = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        rows = search('Sentinel-2', region, start.isoformat(), now.isoformat(), all_pages=True)
        usable = [row for row in rows if row.get('asset') and row.get('quality_asset') and
                  isinstance(row.get('bbox'), list) and len(row['bbox']) == 4 and timestamp(row['acquired_utc']) <= now.timestamp()]
        with self.guard:
            added = 0
            missing = 0
            for tile in self.layout['tiles']:
                w, s, e, n = tile['bbox']
                candidates = [r for r in usable if r['bbox'][0] < e and r['bbox'][2] > w and r['bbox'][1] < n and r['bbox'][3] > s]
                # Cold start reviews the newest image per area, rather than
                # spending on a week of older repeats. Thereafter queue arrivals.
                candidates.sort(key=lambda r: r['acquired_utc'], reverse=True)
                if not candidates:
                    missing += 1
                if not last:
                    candidates = candidates[:1]
                    if candidates:
                        self.state.setdefault('bootstrap_floor', {})[tile['id']] = candidates[0]['acquired_utc']
                passes = set()
                for row in candidates:
                    floor = self.state.get('bootstrap_floor', {}).get(tile['id'])
                    if floor and timestamp(row['acquired_utc']) < timestamp(floor):
                        continue
                    pass_id = row['acquired_utc'][:16]
                    if pass_id in passes:
                        continue  # Overlapping granules from the same minute.
                    passes.add(pass_id)
                    identity = tile['id']+'|'+pass_id
                    key = hashlib.sha256(identity.encode()).hexdigest()[:24]
                    if key not in self.state['jobs']:
                        if len(self.state['jobs']) >= 20000:
                            raise ValueError('Coastal queue reached 20,000 attempts; archive the workspace before resuming')
                        self.state['jobs'][key] = {'tile': tile['id'], 'bbox': tile['bbox'], 'product': row,
                                                  'status': 'queued', 'revision': REVISION}
                        added += 1
            window = f' · images from the last {fresh.total_seconds()/3600:g} h' if fresh else ''
            self.state.update(last_discovery_utc=now.isoformat(), tiles_without_image=missing,
                              message=f'{added} new image areas queued; working around the coast{window}')
            self.publish()
        return added

    def process_one(self):
        with self.guard:
            if self.state.get('analysis_paused'):
                return False
            if (self.workspace.root/'ai/analysis.lock').exists():
                self.state['message'] = 'Waiting for the active image analysis. If it was interrupted, check the host before clearing ai/analysis.lock. AIS capture continues.'
                self.publish()
                return False
            pending = [(key, job) for key, job in self.state['jobs'].items() if job['status'] == 'queued']
            if not pending:
                return False
            # Every available side gets a turn. Clearer imagery is prioritised
            # only WITHIN that side, so one region cannot monopolise the queue.
            cursor = self.state.get('next_coast', 'North')
            start = COASTS.index(cursor) if cursor in COASTS else 0
            for offset in range(len(COASTS)):
                side = COASTS[(start+offset) % len(COASTS)]
                regional = [(key, job) for key, job in pending if coast_for_bounds(job['bbox']) == side]
                if regional:
                    pending = regional
                    self.state['next_coast'] = COASTS[(start+offset+1) % len(COASTS)]
                    break
            def priority(pair):
                job = pair[1]
                cloud = job['product'].get('cloud_percent')
                cloud = cloud if isinstance(cloud, (int, float)) and 0 <= cloud <= 100 else 100
                return (job['tile'] in self.state['coverage'], int(cloud)//20,
                        -timestamp(job['product']['acquired_utc']), job['tile'])
            pending.sort(key=priority)
            key, job = pending[0]
            job.update(status='processing', started_utc=now_utc())
            self.state['message'] = 'Checking '+coast_for_bounds(job['bbox'])+' coast · '+job['tile']+' · '+job['product']['acquired_utc']
            self.publish()  # Durable BEFORE any paid call. Never auto-retry errors.
        paid_stage = False
        try:
            product = job['product']
            preview = quality_preview(product['quality_asset'], job['bbox'])
            if not preview['load_rgb']:
                with self.guard:
                    job.update(status='unobservable_water', screening=preview, contacts=0)
                    self.state['coverage'][job['tile']] = {'acquired_utc': product['acquired_utc'],
                                                          'status': job['status'], 'screening': preview, 'scene_id': None}
                    self.state['last_tile_utc'] = now_utc()
                    self.publish()
                return True
            with tempfile.TemporaryDirectory(prefix='crop-', dir=self.folder) as temp:
                folder = Path(temp)
                scene = satellite.crop_scene(product['asset'], job['bbox'], folder, scene_id=product['id'],
                        acquired_utc=product['acquired_utc'], sensor='Sentinel-2', quality_source=product['quality_asset'])
                triage = screen(scene, (folder/(scene['id']+'.png')).read_bytes(), folder)
                # A simple bright-feature filter misses dark/low-contrast ships.
                # Known image-time AIS must still get an actual image review;
                # triage's empty result is never evidence of clear water.
                if triage['status'] == 'no_local_candidates':
                    historical = self.workspace.ais_for_scene(scene)
                    triage['ais_vessels_at_acquisition'] = len(historical['vessels'])
                    if historical['vessels']:
                        triage.update(send_to_ai=True, status='ais_expected_image_review')
                with self.guard:
                    job['screening'] = triage
                if self.halt.is_set():
                    with self.guard:
                        job['status'] = 'queued'  # No paid request has been submitted.
                        self.publish()
                    return False
                if triage['send_to_ai']:
                    self.workspace.check_capacity()
                    self.workspace.scenes.mkdir(parents=True, exist_ok=True)
                    for path in folder.iterdir():
                        shutil.copyfile(path, self.workspace.scenes/path.name)
                    with self.guard:
                        job['paid_attempt_utc'] = now_utc()
                        self.publish()
                    paid_stage = True
                    result = self.workspace.analyse(scene['id'], automatic=True)
                    with self.guard:
                        partial = result.get('visual', {}).get('analysis_incomplete', False)
                        job.update(status='partial_review_required' if partial else 'review_ready',
                                   scene_id=scene['id'], contacts=len(result['contacts']))
                        if result.get('visual', {}).get('paid_work_held'):
                            self.state['analysis_paused'] = True
                            self.state['message'] = 'AI detail review paused; completed windows are saved and AIS capture continues. Review held windows before further paid work.'
                else:
                    with self.guard:
                        job.update(status=triage['status'], contacts=0)
            with self.guard:
                self.state['coverage'][job['tile']] = {'acquired_utc': product['acquired_utc'], 'status': job['status'],
                                                       'screening': triage, 'scene_id': job.get('scene_id')}
                self.state['last_tile_utc'] = now_utc()
                self.publish()
        except AnalysisBusy:
            # Lock contention is provably unsubmitted work, unlike a timeout
            # after the provider may have received and charged a request.
            with self.guard:
                job.update(status='queued')
                job.pop('paid_attempt_utc', None)
                self.state['message'] = 'Manual analysis is using the AI slot; queued coastal work will resume afterwards'
                self.publish()
            return False
        except Exception as error:
            from argus.satellite_ai import PILOT_USD, read_ledger
            with self.guard:
                job.update(status='failed_review_required', error=str(error)[:300] if isinstance(error, ValueError) else
                           'Cannot process this image area; check raster access or host storage')
                self.state['message'] = job['error']
                ledger = read_ledger(self.workspace.root/'ai')
                if paid_stage or ledger.get('halted') or ledger['reserved_usd'] >= PILOT_USD-.06 or 'storage limit' in job['error'] or 'crop limit' in job['error']:
                    self.state['analysis_paused'] = True
                    self.state['message'] = 'AI paused for review; AIS recording continues. '+job['error']
                self.publish()
        return True

    def capture_loop(self):
        while not self.halt.is_set():
            try:
                result = self.capture.capture()
                with self.guard:
                    self.state.update(ais=result, ais_error=None)
                    self.publish()
            except Exception as error:
                with self.guard:
                    self.state['ais_error'] = str(error)[:250] if isinstance(error, ValueError) else 'AIS feed unavailable; previous fixes retained'
                    self.publish()
            self.halt.wait(60)

    def run(self):
        recorder = threading.Thread(target=self.capture_loop, daemon=True, name='argus-coastal-ais')
        recorder.start()
        self.workspace.fleet.start()
        try:
            while not self.halt.is_set():
                last = self.state.get('last_discovery_utc')
                if not last or timestamp(now_utc())-timestamp(last) >= 1800:
                    try:
                        self.discover()
                    except Exception as error:
                        with self.guard:
                            self.state['message'] = str(error)[:250] if isinstance(error, ValueError) else 'Catalogue unavailable; queued images retained'
                            self.publish()
                        if self.halt.wait(60):
                            break
                        continue
                if self.halt.is_set():
                    break
                if not self.process_one():
                    self.halt.wait(30)
                else:
                    self.halt.wait(2)
        finally:
            self.halt.set()
            recorder.join(timeout=45)
            self.lease.unlink(missing_ok=True)

    def resume(self):
        if self.state.get('enabled') and os.environ.get('ARGUS_SATELLITE_AUTOSTART', '1') != '0':
            return self.start()
