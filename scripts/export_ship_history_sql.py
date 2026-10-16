"""Prepare private, bounded SQL batches for importing recorded AIS into Supabase.

No network or keys. Outputs contain real ship observations; keep them under data/.
Original rows and file hashes are retained, separate from normalized query fields.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from argus.satellite_ais import archive_rows, row_time


def number(value, low, high):
    try:
        result = float(value)
        return result if math.isfinite(result) and low <= result < high else None
    except (ValueError, TypeError):
        return None


def prepare(row, digest, generated):
    if row.get('label') not in {'real', 'reconstructed'}:
        raise ValueError('Archive rows must carry explicit real/reconstructed provenance')
    # ais_observations currently accepts real feed observations only.
    if row['label'] != 'real':
        raise ValueError('Reconstructed archives require a separate provenance-aware import')
    mmsi, stream = str(row.get('mmsi', '')), row.get('stream_id')
    if not re.fullmatch(r'[0-9]{9}', mmsi) or int(mmsi) == 0 or not stream:
        raise ValueError('Missing archive identity or stream epoch')
    received = row_time(row.get('recv_utc'))
    if datetime.fromisoformat(received.replace('Z', '+00:00')) > datetime.now(timezone.utc):
        raise ValueError('Archive receipt time is in the future')
    result = dict(mmsi=mmsi, stream=stream, received=received, generated=generated,
                  source='archive:sha256:'+digest, raw=row, label=row['label'], static=[])
    if row.get('msg_type') in {'PositionReport', 'StandardClassBPositionReport', 'ExtendedClassBPositionReport'}:
        lat, lon = number(row.get('lat'), -90, 90.000001), number(row.get('lon'), -180, 180.000001)
        if lat is None or lon is None:
            raise ValueError('Invalid archive position')
        result['position'] = dict(lat=lat, lon=lon, sog=number(row.get('sog'), 0, 102.3),
                                  cog=number(row.get('cog'), 0, 360),
                                  heading=number(row.get('heading'), 0, 360),
                                  nav=number(row.get('nav_status'), 0, 16))
    elif row.get('msg_type') == 'ShipStaticData':
        present = set((row.get('present_fields') or '').split(','))
        for field, column in [('name', 'ship_name'), ('ship_type', 'ship_type'),
                              ('length_m', 'length_m'), ('destination', 'destination')]:
            value = row.get(column)
            if value not in (None, '') or field in present:
                result['static'].append(dict(field=field, value=value or None))
    else:
        raise ValueError('Unsupported archive message type')
    return result


def batch_sql(rows):
    # SQL string escaping; never interpolate an unescaped source field into SQL.
    literal = "'" + json.dumps(rows, ensure_ascii=True, allow_nan=False).replace("'", "''") + "'"
    return "set standard_conforming_strings=on;\n" + f"""
with source as (select value as r from jsonb_array_elements({literal}::jsonb)),
raw_saved as (
  insert into argus.ais_observations
    (mmsi, stream_id, source_generated_utc, source_url, label, payload, payload_sha256)
  select r->>'mmsi', r->>'stream', (r->>'generated')::timestamptz, r->>'source', r->>'label',
         r->'raw', encode(sha256(convert_to((r->'raw')::text,'UTF8')),'hex') from source
  on conflict do nothing returning 1
), positions_saved as (
  insert into argus.ais_positions
    (mmsi,received_utc,lat,lon,sog_kn,cog_deg,heading_deg,nav_status,stream_id,label,timestamp_source)
  select r->>'mmsi',(r->>'received')::timestamptz,(r#>>'{{position,lat}}')::float8,
    (r#>>'{{position,lon}}')::float8,(r#>>'{{position,sog}}')::real,(r#>>'{{position,cog}}')::real,
    (r#>>'{{position,heading}}')::numeric::smallint,(r#>>'{{position,nav}}')::numeric::smallint,
    r->>'stream',r->>'label','received_time_assumption' from source where r ? 'position'
  on conflict do nothing returning 1
), static_saved as (
  insert into argus.ais_static (mmsi,field,value,received_utc,stream_id)
  select r->>'mmsi',f->>'field',f->>'value',(r->>'received')::timestamptz,r->>'stream'
  from source cross join lateral jsonb_array_elements(r->'static') f
  on conflict do nothing returning 1
)
select (select count(*) from raw_saved) as observations_added,
       (select count(*) from positions_saved) as positions_added,
       (select count(*) from static_saved) as particulars_added;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/ais')
    parser.add_argument('--output', type=Path, default=ROOT/'data/ship-history-import')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    generated = datetime.now(timezone.utc).isoformat()
    for path in sorted(args.source.rglob('*')):
        if path.suffix.lower() not in {'.csv', '.parquet'}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.extend(prepare(row, digest, generated) for row in archive_rows(path))
    for index, start in enumerate(range(0, len(rows), 250)):
        (args.output/f'batch-{index:04d}.sql').write_text(batch_sql(rows[start:start+250]), encoding='utf-8')
    print(json.dumps({'rows': len(rows), 'batches': math.ceil(len(rows)/250)}))


if __name__ == '__main__':
    main()
