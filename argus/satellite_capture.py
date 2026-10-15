"""Private, bounded receipt-time AIS recording from the team's fixed public feed.

Never backdates a fix or substitutes a current declaration for a past one.
No server-side AIS recording key is required; this is partial polled reception.
"""
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from argus.live_client import validate_envelope
from argus.provenance import now_utc
from argus.satellite import atomic_json, json_http
from argus.space import timestamp

FEED = 'https://shared-live-ais-production.up.railway.app/api/v1/vessels'
FIELDS = ['mmsi', 'msg_type', 'lat', 'lon', 'sog', 'cog', 'recv_utc', 'time_utc',
          'timestamp_source', 'stream_id', 'ship_name', 'ship_type_description', 'destination', 'nav_status', 'label', 'present_fields', 'length_m']


def load_latest(path):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {'vessels': []}


class AISCapture:
    def __init__(self, workspace):
        self.workspace = workspace
        self.path = workspace.root/'scan/latest_ais.json'

    def capture(self, transport=json_http, now=None):
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        envelope = validate_envelope(transport(FEED))
        if envelope['feed']['label'] != 'real':
            raise ValueError('Automatic capture requires a real AIS feed')
        if not envelope['snapshot']:
            raise ValueError('The AIS recorder requires a full snapshot')
        if envelope['generated_s'] > now+60 or now-envelope['generated_s'] > 600:
            raise ValueError('AIS snapshot clock is stale or in the future; recording paused')
        previous = load_latest(self.path)
        prior = {r['mmsi']: r for r in previous['vessels']}
        stream = envelope['stream_id']
        if stream == previous.get('stream_id') and envelope['sequence'] < previous.get('sequence', 0):
            raise ValueError('AIS sequence moved backwards; latest positions retained')
        rows, writes = [], {}
        for row in envelope['rows']:
            if row['label'] != 'real':
                continue
            received = row['received_s']
            if received is not None and received > now+60:
                continue
            row = {key: value for key, value in row.items() if key != 'received_s'}
            rows.append(row)
            old = prior.get(row['mmsi'], {}) if previous.get('stream_id') == stream else {}
            if old.get('received_utc') and (received is None or timestamp(old['received_utc']) > received):
                for key in ('received_utc', 'lat', 'lon', 'sog_kn', 'cog_deg', 'nav_status'):
                    row[key] = old[key]
            points = []
            if row['received_utc'] is not None and row['received_utc'] != old.get('received_utc'):
                points.append(dict(mmsi=row['mmsi'], msg_type='PositionReport', lat=row['lat'], lon=row['lon'],
                                   sog=row['sog_kn'], cog=row['cog_deg'], nav_status=row['nav_status'],
                                   recv_utc=row['received_utc'], time_utc='', timestamp_source='received_time_assumption',
                                   stream_id=stream, label='real'))
            # Each field keeps its own broadcast receipt time. In particular,
            # never stamp today's destination with the time of an old position.
            for field, received_key, target in [('name', 'metadata_received_utc', 'ship_name'),
                                                 ('type', 'metadata_received_utc', 'ship_type_description'),
                                                 ('ais_length_m', 'metadata_received_utc', 'length_m'),
                                                 ('destination', 'destination_received_utc', 'destination')]:
                if field == 'ais_length_m' and field not in row:
                    continue
                value, date = row.get(field), row.get(received_key)
                if (value or field in {'destination', 'ais_length_m'}) and date and timestamp(date) <= now+60 and (value, date) != (old.get(field), old.get(received_key)):
                    points.append(dict(mmsi=row['mmsi'], msg_type='ShipStaticData', recv_utc=date,
                                       stream_id=stream, label='real', present_fields='name' if target == 'ship_name' else target, **{target: value}))
            for point in points:
                day = datetime.fromtimestamp(timestamp(point['recv_utc']), timezone.utc).date().isoformat()
                writes.setdefault(day, []).append(point)
        folder = self.workspace.archive_root/'capture'
        folder.mkdir(parents=True, exist_ok=True)
        size = sum(p.stat().st_size for p in self.workspace.archive_root.rglob('*') if p.is_file())
        if size > 1024*1024*1024:
            raise ValueError('Private AIS archive reached 1 GB; archive it on the host to resume capture')
        written = 0
        for day, points in writes.items():
            # Keep the old daily CSV headers intact; both versions remain readable.
            path = folder/(day+'.v2.csv')
            if path.exists() and path.stat().st_size > 128*1024*1024:
                raise ValueError('Daily AIS capture reached 128 MB; archive it on the host to resume')
            new = not path.exists()
            with path.open('a', encoding='utf-8', newline='') as output:
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                if new:
                    writer.writeheader()
                writer.writerows(points)
                output.flush()
                os.fsync(output.fileno())
            written += len(points)
        result = {'vessels': rows, 'stream_id': stream, 'sequence': envelope['sequence'], 'captured_utc': now_utc(),
                  'feed': envelope['feed'], 'source': FEED,
                  'caveat': 'Partial polled AIS. Times are reception times, not guaranteed observation times. Latest received fixes may be stale.'}
        atomic_json(self.path, result)
        return {'recorded_rows': written, 'latest_vessels': len(rows), 'captured_utc': result['captured_utc']}
