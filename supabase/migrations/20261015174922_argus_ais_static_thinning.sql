-- AISstream repeats the ship name with every position, so the feed's metadata
-- time moves on every fix. Store a declaration again only when its value
-- changes or the last stored copy is more than one hour older.
create or replace function argus.ingest_ais_packet(packet jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  ts_re constant text := '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$';
  items jsonb;
  kind text;
  generated timestamptz;
  stream text;
  seq bigint;
  n_pos int := 0;
  n_static int := 0;
begin
  if packet->>'schema_version' is distinct from '1' then
    raise exception 'unsupported AIS schema_version %', packet->>'schema_version';
  end if;
  if coalesce(packet #>> '{feed,label}', '') <> 'real' then
    raise exception 'AIS feed label is not real';
  end if;
  if coalesce(packet->>'generated_utc', '') !~ ts_re then
    raise exception 'AIS packet has no valid generated_utc';
  end if;
  generated := (packet->>'generated_utc')::timestamptz;
  if generated > now() + interval '60 seconds' or generated < now() - interval '10 minutes' then
    raise exception 'AIS packet clock is stale or in the future: %', generated;
  end if;
  stream := packet->>'stream_id';
  if stream is null or stream !~ '^[A-Za-z0-9_-]{1,64}$' then
    raise exception 'AIS packet has no valid stream_id';
  end if;
  seq := case when coalesce(packet->>'sequence', '') ~ '^[0-9]{1,18}$' then (packet->>'sequence')::bigint end;

  if jsonb_typeof(packet->'vessels') = 'array' then
    items := packet->'vessels'; kind := 'snapshot';
  elsif jsonb_typeof(packet->'upserts') = 'array' then
    items := packet->'upserts'; kind := 'updates';
  else
    raise exception 'AIS packet has neither vessels nor upserts';
  end if;

  insert into argus.ais_positions
    (mmsi, received_utc, lat, lon, sog_kn, cog_deg, heading_deg, nav_status, stream_id)
  select mmsi, received_utc, lat, lon, sog, cog, heading, nav, stream
  from (
    select r->>'mmsi' as mmsi,
           (r->>'received_utc')::timestamptz as received_utc,
           (r->>'lat')::double precision as lat,
           (r->>'lon')::double precision as lon,
           case when jsonb_typeof(r->'sog_kn') = 'number' and (r->>'sog_kn')::numeric >= 0
                     and (r->>'sog_kn')::numeric < 102.3 then (r->>'sog_kn')::real end as sog,
           case when jsonb_typeof(r->'cog_deg') = 'number' and (r->>'cog_deg')::numeric >= 0
                     and (r->>'cog_deg')::numeric < 360 then (r->>'cog_deg')::real end as cog,
           case when jsonb_typeof(r->'heading_deg') = 'number' and (r->>'heading_deg')::numeric >= 0
                     and (r->>'heading_deg')::numeric < 360 then round((r->>'heading_deg')::numeric)::smallint end as heading,
           case when jsonb_typeof(r->'nav_status') = 'number' and (r->>'nav_status')::numeric between 0 and 15
                     then (r->>'nav_status')::numeric::smallint end as nav
    from jsonb_array_elements(items) as r
    where jsonb_typeof(r) = 'object'
      and coalesce(r->>'label', 'real') = 'real'
      and coalesce(r->>'mmsi', '') ~ '^[0-9]{9}$'
      and jsonb_typeof(r->'lat') = 'number'
      and jsonb_typeof(r->'lon') = 'number'
      and coalesce(r->>'received_utc', '') ~ ts_re
  ) as p
  where lat between -90 and 90 and lon between -180 and 180
    and received_utc <= now() + interval '60 seconds'
  on conflict do nothing;
  get diagnostics n_pos = row_count;

  insert into argus.ais_static (mmsi, field, value, received_utc, stream_id)
  select d.mmsi, d.field, d.value, d.received, stream
  from (
    select r->>'mmsi' as mmsi, f.field,
           left(regexp_replace(f.value, '[[:cntrl:]]', '', 'g'), 80) as value,
           f.received::timestamptz as received
    from jsonb_array_elements(items) as r
    cross join lateral (values
        ('name', nullif(btrim(r->>'name'), ''), r->>'metadata_received_utc'),
        ('ship_type', case when jsonb_typeof(r->'ship_type') = 'number' then r->>'ship_type' end, r->>'metadata_received_utc'),
        ('length_m', case when jsonb_typeof(r->'ais_length_m') = 'number' then r->>'ais_length_m' end, r->>'metadata_received_utc'),
        ('destination', nullif(btrim(r->>'destination'), ''), r->>'destination_received_utc')
    ) as f(field, value, received)
    where jsonb_typeof(r) = 'object'
      and coalesce(r->>'label', 'real') = 'real'
      and coalesce(r->>'mmsi', '') ~ '^[0-9]{9}$'
      and coalesce(f.received, '') ~ ts_re
      and (f.value is not null or (f.field = 'destination' and r ? 'destination'))
  ) as d
  where d.received <= now() + interval '60 seconds'
    and not exists (
      select 1 from argus.ais_static x
      where x.mmsi = d.mmsi and x.field = d.field
        and x.value is not distinct from d.value
        and x.received_utc <= d.received
        and x.received_utc > d.received - interval '1 hour')
  on conflict do nothing;
  get diagnostics n_static = row_count;

  return jsonb_build_object('kind', kind, 'contacts', jsonb_array_length(items),
                            'positions_new', n_pos, 'static_new', n_static,
                            'stream_id', stream, 'sequence', seq, 'generated_utc', generated);
end;
$$;
revoke all on function argus.ingest_ais_packet(jsonb) from public, anon, authenticated;
