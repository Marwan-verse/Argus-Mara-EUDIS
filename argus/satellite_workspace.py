"""File-based satellite workspace shared by the native client and optional SOC.

No changes to the two-file exercise contract; all rasters, archives, results and
cost records live under ignored/private data. Import is a host-side operation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from argus import satellite, supabase_ais
from argus.satellite_ais import ArchiveChanged, associate, attach_latest, historical_ais
from argus.satellite_ai import PILOT_USD, get_key, read_ledger, visual_analysis
from argus.fleet_history import FleetHistoryWorker
from argus.satellite_disposition import Dispositions, evidence_key

DEFAULT_QUESTION = 'Find possible vessels in this image and describe the visible evidence and uncertainty.'
PRIORITY_REASONS = {
    'ais_not_detected': ('high', 'AIS places a large vessel on fully clear water, but the image shows nothing within 1 km'),
    'radar_without_ais': ('medium', 'Radar sees a vessel with no AIS from Global Fishing Watch or the team feed'),
}
CONFIDENCE_PRIORITY = {'high': 'high', 'medium': 'medium', 'low': 'low'}


def with_priority(lead, confidences):
    """Add the AI contact confidence and a review priority for sorting/collapsing alert lists.

    Applied after the analyst evidence key is computed, so recorded outcomes stay valid.
    A lead whose confidence is unknown gets priority None: show it, do not collapse it.
    """
    confidence = confidences.get(lead.get('contact_id')) if lead.get('kind') == 'image_without_ais' else None
    if lead.get('kind') in PRIORITY_REASONS:
        priority, reason = PRIORITY_REASONS[lead['kind']]
    elif confidence in CONFIDENCE_PRIORITY:
        priority = CONFIDENCE_PRIORITY[confidence]
        reason = f'AI rated this image contact {confidence} confidence; no AIS within 300 m'
    else:
        priority, reason = None, 'Priority unknown'
    return {**lead, 'confidence': confidence, 'priority': priority, 'priority_reason': reason}


class SatelliteWorkspace:
    def __init__(self, root, archive_root=None):
        self.root = Path(root)
        self.scenes = self.root/'scenes'
        self.archive_root = Path(archive_root or os.environ.get('ARGUS_SATELLITE_AIS_DIR') or self.root.parent/'ais')
        self._comparison_retry_at = {}
        self.fleet = FleetHistoryWorker(self.root)
        self.dispositions = Dispositions(self.root)

    def status(self):
        from argus.satellite_scan import scan_status
        scan = scan_status(self.root)
        return {'configured': bool(get_key()), 'automatic': scan['enabled'], 'scan': scan, 'pilot_limit_usd': PILOT_USD,
                'budget': read_ledger(self.root/'ai'),
                'scene_count': len(self.list_scenes()),
                'archive_available': self.archive_root.is_dir() and any(self.archive_root.rglob('*.parquet')) or
                                     self.archive_root.is_dir() and any(self.archive_root.rglob('*.csv')) or
                                     self.archive_root.is_dir() and any(self.archive_root.rglob('*.json'))}

    def search(self, sensor, bbox, start, end):
        scenes = satellite.search(sensor, bbox, start, end)
        satellite.atomic_json(self.root/'catalogue.json', scenes)
        return scenes

    def prepare(self, product_id, bbox):
        if not isinstance(product_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', product_id):
            raise ValueError('Invalid scene identifier')
        catalogue = self.root/'catalogue.json'
        rows = json.loads(catalogue.read_text(encoding='utf-8')) if catalogue.exists() else []
        scene = next((r for r in rows if r['id'] == product_id), None)
        if not scene:
            raise ValueError('Search the catalogue again before loading this scene')
        if scene['sensor'] != 'Sentinel-2' or not scene['asset']:
            raise ValueError('SAR data needs calibrated, terrain-corrected GeoTIFF import on the host; a catalogue footprint is not usable radar pixels')
        self.check_capacity()
        return satellite.crop_scene(scene['asset'], bbox, self.scenes, scene_id=scene['id'],
                                    acquired_utc=scene['acquired_utc'], sensor=scene['sensor'], quality_source=scene.get('quality_asset'))

    def check_capacity(self):
        if len(self.list_scenes()) >= 200:
            raise ValueError('The workspace has reached its 200-crop limit; archive old crops on the host')
        size = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()) if self.root.exists() else 0
        if size > 512*1024*1024:
            raise ValueError('The satellite workspace has reached its 512 MB storage limit')

    def import_raster(self, path, bbox, acquired_utc, sensor, label):
        self.check_capacity()
        return satellite.crop_scene(path, bbox, self.scenes, scene_id=Path(path).name,
                                    acquired_utc=acquired_utc, sensor=sensor, label=label)

    def import_ais(self, source):
        source = Path(source)
        if source.suffix.lower() not in {'.csv', '.parquet', '.json'} or source.stat().st_size > 256*1024*1024:
            raise ValueError('Import AIS CSV, recorder Parquet or normalized JSON, at most 256 MB each')
        current = sum(p.stat().st_size for p in self.archive_root.rglob('*') if p.is_file()) if self.archive_root.exists() else 0
        if current + source.stat().st_size > 1024*1024*1024:
            raise ValueError('The AIS import folder would exceed its 1 GB limit')
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        self.archive_root.mkdir(parents=True, exist_ok=True)
        target = self.archive_root/(digest.hexdigest()+source.suffix.lower())
        if not target.exists():
            temporary = target.with_suffix('.tmp')
            shutil.copyfile(source, temporary)
            temporary.replace(target)
        return {'imported': True, 'sha256': digest.hexdigest(), 'bytes': source.stat().st_size}

    def list_scenes(self):
        if not self.scenes.exists():
            return []
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in self.scenes.glob('*.json')
                       if re.fullmatch(r'[0-9a-f]{24}\.json', p.name)],
                      key=lambda r: r['acquired_utc'], reverse=True)

    def scene(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{24}', identifier):
            raise ValueError('Invalid crop identifier')
        path = self.scenes/(identifier+'.json')
        if not path.exists():
            raise ValueError('Crop not found; load or import an image first')
        return json.loads(path.read_text(encoding='utf-8'))

    def image(self, identifier):
        scene = self.scene(identifier)
        data = (self.scenes/(identifier+'.png')).read_bytes()
        if hashlib.sha256(data).hexdigest() != scene['image_sha256']:
            raise ValueError('Satellite crop hash does not match its metadata')
        return data

    def analyse(self, identifier, question=DEFAULT_QUESTION, *, automatic=False):
        scene = self.scene(identifier)
        if automatic:
            if not scene.get('quality_sha256'):
                raise ValueError('Automatic optical reviews require a verified quality mask')
            from argus.satellite_screen import water_mask
            water_mask(scene, self.scenes)  # Validate before spending.
        # Load and validate the archive before paying; AI receives no AIS metadata.
        ais = self.ais_for_scene(scene)
        if len(ais['vessels']) > 1000:
            raise ValueError('Too many historical contacts; choose a smaller analysis area')
        from argus.satellite_adaptive import review_image
        dense = len(ais['vessels']) > 16
        if scene.get('quality_sha256') and not dense:
            from argus.satellite_screen import screen
            dense = screen(scene, self.image(identifier), self.scenes).get('candidate_count', 0) > 16
        visual = review_image(self.root/'ai', scene, self.image(identifier), question,
                              analyse=visual_analysis, dense=dense)
        points = visual['contacts']
        excluded = 0
        if scene.get('quality_sha256'):
            from argus.satellite_screen import retain_water_contacts
            points, excluded = retain_water_contacts(scene, points, self.scenes)
        elif automatic:
            raise ValueError('Automatic optical reviews require a verified quality mask')
        contacts = self.associate_current(points, ais, scene)
        result = {'scene': scene, 'visual': visual, 'contacts': contacts, 'ais': ais,
                  'budget': read_ledger(self.root/'ai'),
                  'assumptions': {'association_radius_km': .3, 'max_interpolation_gap_s': 600,
                                  'max_past_projection_age_s': 300},
                  'review_status': 'unreviewed',
                  'automatic': automatic, 'quality_excluded_contacts': excluded,
                  'caveat': 'Possible visual contacts and AIS associations require operator review. Unmatched does not mean hostile or deliberately dark. No operational response is sent.'}
        self.compare(result)
        if supabase_ais.linked(self.root):
            # Free and best-effort: the paid image request has already finished.
            result['database'] = supabase_ais.publish_review(scene, contacts, self.scenes, analysis=visual)
        satellite.atomic_json(self.root/'reviews'/(identifier+'.json'), result)
        return result

    def compare(self, review):
        from argus.provenance import now_utc
        from argus.satellite_compare import compare_review
        review['comparison'] = compare_review(review['scene'], review['contacts'], review['ais'],
                                               review.get('visual'), self.scenes)
        review['comparison_checked_utc'] = now_utc()
        return review

    def reconcile_reviews(self, limit=4):
        """Free bounded backlog: check unchecked images first, refresh old joins later.

        Runs on the satellite worker, never on the Tk event thread. Failed reads
        leave evidence intact and back off; this method never submits AI work.
        """
        from argus.space import timestamp
        from argus.satellite_compare import VERSION
        pending = []
        for path in (self.root/'reviews').glob('*.json'):
            if not re.fullmatch(r'[0-9a-f]{24}\.json', path.name):
                continue
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                if not self.has_visual_review(item):
                    continue
                checked = item.get('comparison_checked_utc')
                due = timestamp(checked) if checked and (item.get('comparison') or {}).get('version') == VERSION else 0
                if due < time.time()-300 and self._comparison_retry_at.get(path.stem, 0) <= time.monotonic():
                    pending.append((due, path.stem))
            except (OSError, ValueError, TypeError):
                continue
        for _, identifier in sorted(pending)[:limit]:
            try:
                self.review(identifier)
            except (OSError, ValueError, ImportError):
                self._comparison_retry_at[identifier] = time.monotonic()+300

    def comparison_index(self):
        """All saved review leads and per-vessel results, independent of demo alerts."""
        rows, vessels, pending, reviewed, image_contacts, no_ais, partial = [], [], 0, 0, 0, 0, 0
        for path in (self.root/'reviews').glob('*.json'):
            if not re.fullmatch(r'[0-9a-f]{24}\.json', path.name):
                continue
            try:
                review = json.loads(path.read_text(encoding='utf-8'))
                if not self.has_visual_review(review):
                    continue
                comparison = review.get('comparison')
                if not comparison:
                    pending += 1
                    continue
                reviewed += 1
                partial += bool(review.get('visual', {}).get('analysis_incomplete'))
                image_contacts += len(review.get('contacts', []))
                no_ais += not bool(review.get('ais', {}).get('vessels'))
                confidences = {c.get('id'): c.get('confidence') for c in review.get('contacts', [])}
                rows.extend(with_priority(self.dispositions.decorate(lead, evidence_key(review, lead)), confidences)
                            for lead in comparison.get('leads', []))
                vessels.extend({**v, 'scene_id': path.stem, 'acquired_utc': review['scene']['acquired_utc']}
                               for v in comparison.get('vessel_checks', []))
            except (OSError, ValueError, TypeError, KeyError):
                pending += 1
        # Global Fishing Watch radar contacts without AIS (D84) share the same analyst outcomes.
        try:
            from argus import gfw_sar
            radar, radar_summary = gfw_sar.radar_index(self.root), gfw_sar.summary(self.root)
        except (OSError, ValueError, TypeError, KeyError):
            radar, radar_summary = [], {}
        rows.extend(with_priority(self.dispositions.decorate(lead, key), {}) for lead, key in radar)
        return {'leads': sorted(rows, key=lambda r: (r['acquired_utc'], r['id']), reverse=True),
                'vessel_checks': vessels, 'reviews_checked': reviewed, 'reviews_pending': pending,
                'image_contacts': image_contacts, 'images_without_ais': no_ais,
                'partial_analysis_images': partial,
                'radar_detections': radar_summary.get('detections', 0), 'radar_leads': len(radar),
                'radar_newest_utc': radar_summary.get('newest_detection_utc'),
                'complete_vessel_census': False}

    def save_disposition(self, payload, actor):
        lead_id = payload.get('lead_id') if isinstance(payload, dict) else None
        if isinstance(lead_id, str) and lead_id.startswith('gfw:'):
            from argus import gfw_sar
            lead, key = gfw_sar.find_lead(self.root, lead_id)
            event = self.dispositions.save(lead, key, payload, actor)
            return {'saved': True, 'event': event, 'comparisons': self.comparison_index()}
        if not isinstance(lead_id, str) or not re.fullmatch(r'[0-9a-f]{24}:(ais|image):[A-Za-z0-9_.:-]{1,160}', lead_id):
            raise ValueError('Invalid satellite review lead')
        identifier = lead_id.split(':', 1)[0]
        path = self.root/'reviews'/(identifier+'.json')
        if not path.is_file():
            raise ValueError('Satellite review is no longer available')
        review = json.loads(path.read_text(encoding='utf-8'))
        lead = next((r for r in review.get('comparison', {}).get('leads', []) if r['id'] == lead_id), None)
        if lead is None:
            raise ValueError('Lead is no longer present; reload the current evidence')
        event = self.dispositions.save(lead, evidence_key(review, lead), payload, actor)
        return {'saved': True, 'event': event, 'comparisons': self.comparison_index()}

    def associate_current(self, points, ais, scene):
        from argus.satellite_capture import load_latest
        contacts = attach_latest(associate(points, ais), load_latest(self.root/'scan/latest_ais.json'), scene['acquired_utc'])
        for point in contacts:
            point['ambiguous'] = point.get('ambiguous', False) or point.get('overlap_ambiguous', False)
        return contacts

    def contacts(self):
        """Small map index; detailed AIS, image and latest positions load on click."""
        rows = []
        folder = self.root/'reviews'
        for path in sorted(folder.glob('*.json')) if folder.exists() else []:
            if not re.fullmatch(r'[0-9a-f]{24}\.json', path.name):
                continue
            review = json.loads(path.read_text(encoding='utf-8'))
            if (review.get('visual') or {}).get('image_input_verified') is not True:
                continue
            scene = review['scene']
            for point in review['contacts']:
                # Compact map/list index; full descriptions are loaded on click.
                rows.append({key: point[key] for key in ('id', 'lat', 'lon', 'confidence', 'label', 'ts', 'matched_mmsi')})
                rows[-1].update(scene_id=scene['id'], sensor=scene['sensor'])
        return sorted(rows, key=lambda r: r['ts'], reverse=True)

    @staticmethod
    def has_visual_review(review):
        from argus.satellite_adaptive import VERSION
        visual = review.get('visual') or {}
        return visual.get('image_input_verified') is True or visual.get('adaptive_version') == VERSION

    def history(self, identifier):
        scene = self.scene(identifier)
        return {'scene': scene, 'contacts': [], 'visual': None,
                'ais': self.ais_for_scene(scene),
                'review_status': 'unreviewed', 'caveat': 'Historical AIS at image acquisition UTC; partial reception coverage.'}

    def ais_for_scene(self, scene):
        if scene['label'] not in {'real', 'reconstructed'}:
            return {'vessels': [], 'archive_sha256': None,
                    'coverage': {'status': 'unavailable', 'eligible_vessels': 0, 'files_scanned': 0,
                                 'complete_regional_census': False,
                                 'caveat': 'Synthetic or unverified imagery cannot be associated with real archived AIS.'}}
        note = None
        if supabase_ais.linked(self.root):
            # The team database records the Railway feed every 30 s even when no
            # app is open, so it is preferred over this computer's own capture.
            try:
                ais = supabase_ais.historical_ais_from_database(scene['acquired_utc'], scene['bbox'])
                if ais['coverage'].get('database_position_rows'):
                    return ais
                note = 'The team database has no AIS near this acquisition time; local archive used.'
            except ValueError as error:
                note = 'Team database unavailable (%s); local archive used.' % str(error)[:120]
        try:
            ais = historical_ais(self.archive_root, scene['acquired_utc'], scene['bbox'])
        except ArchiveChanged:
            # Retry only the free file read, before visual_analysis is called.
            ais = historical_ais(self.archive_root, scene['acquired_utc'], scene['bbox'])
        if note:
            ais['coverage']['database_note'] = note
        return ais

    def review(self, identifier):
        self.scene(identifier)
        path = self.root/'reviews'/(identifier+'.json')
        if path.exists():
            review = json.loads(path.read_text(encoding='utf-8'))
            if self.has_visual_review(review):
                # No AI tokens: new archive imports/recordings can improve a
                # previous match, and latest fixes change independently of images.
                ais = self.ais_for_scene(review['scene'])
                review['ais'] = ais
                review['contacts'] = self.associate_current(review['contacts'], ais, review['scene'])
                self.compare(review)
                satellite.atomic_json(path, review)
                return review
        return self.history(identifier)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Host-side satellite imports; no paid AI calls')
    parser.add_argument('--root', default=os.environ.get('ARGUS_SATELLITE_ROOT', 'data/satellite'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    ais = commands.add_parser('import-ais')
    ais.add_argument('path', type=Path)
    raster = commands.add_parser('import-raster')
    raster.add_argument('path', type=Path)
    raster.add_argument('--bbox', required=True, type=float, nargs=4, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    raster.add_argument('--acquired-utc', required=True)
    raster.add_argument('--sensor', required=True, choices=['Sentinel-1', 'Sentinel-2'])
    raster.add_argument('--label', required=True, choices=['real', 'reconstructed', 'simulated', 'fictional', 'assumption'])
    args = parser.parse_args()
    workspace = SatelliteWorkspace(args.root)
    try:
        if args.command == 'import-ais':
            result = workspace.import_ais(args.path)
        elif args.command == 'import-raster':
            result = workspace.import_raster(args.path, args.bbox, args.acquired_utc, args.sensor, args.label)
        else:
            result = workspace.status()
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
