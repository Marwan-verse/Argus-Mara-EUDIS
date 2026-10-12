"""Bounded local received-fix history. No route prediction or departure inference."""
from collections import OrderedDict
import math

from argus.live_client import MAX_VESSELS, utc_timestamp

MAX_POINTS = 720
MAX_TOTAL_POINTS = 100_000
RETENTION_SECONDS = 24 * 3600
GAP_SECONDS = 900


class ReceivedTracks:
    def __init__(self):
        self.tracks = OrderedDict()
        self.total = 0

    def capture(self, vessels, stream_id, now):
        self.prune(now, set(vessels))
        for mmsi, vessel in vessels.items():
            stamp = vessel['received_s']
            if stamp is None or stamp < now - RETENTION_SECONDS:
                continue
            points = self.tracks.setdefault(mmsi, [])
            # Repeated snapshots/static reports do not create invented fixes.
            if points and stamp <= points[-1]['received_s']:
                continue
            point = {key: vessel[key] for key in ('lat', 'lon', 'received_utc', 'received_s', 'label')}
            point['stream_id'] = stream_id
            points.append(point)
            self.total += 1
            if len(points) > MAX_POINTS:
                points.pop(0)
                self.total -= 1
            self.tracks.move_to_end(mmsi)
        self.bound()

    def prune(self, now, contacts=None):
        cutoff = now - RETENTION_SECONDS
        for mmsi, points in list(self.tracks.items()):
            if contacts is not None and mmsi not in contacts:
                self.total -= len(self.tracks.pop(mmsi))
                continue
            index = 0
            while index < len(points) and points[index]['received_s'] < cutoff:
                index += 1
            if index:
                del points[:index]
                self.total -= index
            if not points:
                self.tracks.pop(mmsi)

    def bound(self):
        while self.total > MAX_TOTAL_POINTS or len(self.tracks) > MAX_VESSELS:
            _mmsi, points = self.tracks.popitem(last=False)
            self.total -= len(points)

    def restore(self, payload, vessels, now):
        """Ignore damaged local history atomically, retaining the valid snapshot."""
        if not isinstance(payload, dict) or len(payload) > MAX_VESSELS:
            return
        restored = OrderedDict()
        total = 0
        try:
            for mmsi, rows in payload.items():
                if mmsi not in vessels:
                    continue
                if not isinstance(rows, list) or len(rows) > MAX_POINTS:
                    return
                points = []
                for row in rows:
                    lat, lon = row['lat'], row['lon']
                    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)):
                        return
                    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or row['label'] not in ('real', 'simulated'):
                        return
                    stamp = utc_timestamp(row['received_utc'])
                    if points and stamp <= points[-1]['received_s']:
                        return
                    if stamp > vessels[mmsi]['received_s']:
                        return
                    stream = row['stream_id']
                    if not isinstance(stream, str) or not 1 <= len(stream) <= 128:
                        return
                    points.append({'lat': lat, 'lon': lon, 'received_utc': row['received_utc'],
                                   'received_s': stamp, 'label': row['label'], 'stream_id': stream})
                restored[mmsi] = points
                total += len(points)
                if total > MAX_TOTAL_POINTS:
                    return
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        self.tracks, self.total = restored, total
        self.prune(now, set(vessels))

    def sections(self, mmsi):
        """Break long reception gaps, stream/provenance changes and date-line wraps."""
        sections = []
        for point in self.tracks.get(mmsi, []):
            previous = sections[-1][-1] if sections else None
            if previous is None or point['received_s'] - previous['received_s'] > GAP_SECONDS or (
                    point['stream_id'] != previous['stream_id'] or point['label'] != previous['label'] or
                    abs(point['lon'] - previous['lon']) > 180):
                sections.append([])
            sections[-1].append(point)
        return sections
