-- ARGUS MARA: AIS history copied from the team's public Railway feed every 30 s.
-- Tables live in schema "argus", which the REST API does not expose. Only
-- service_role wrappers in "public" (added later) can read or write them.

create extension if not exists postgis with schema extensions;
create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

create schema if not exists argus;
revoke all on schema argus from public, anon, authenticated;
grant usage on schema argus to service_role;

create table argus.ais_positions (
  mmsi text not null check (mmsi ~ '^[0-9]{9}$'),
  received_utc timestamptz not null,
  lat double precision not null check (lat between -90 and 90),
  lon double precision not null check (lon between -180 and 180),
  sog_kn real,
  cog_deg real,
  heading_deg smallint,
  nav_status smallint,
  stream_id text not null,
  label text not null default 'real' check (label in ('real', 'reconstructed')),
  timestamp_source text not null default 'received_time_assumption',
  inserted_utc timestamptz not null default now(),
  geog extensions.geography(Point, 4326) generated always as
    ((extensions.st_setsrid(extensions.st_makepoint(lon, lat), 4326))::extensions.geography) stored,
  primary key (mmsi, received_utc)
);
comment on table argus.ais_positions is
  'Real AIS positions received by the team Railway collector (AISstream, Ireland box). received_utc is the collector receipt time, not the AIS message time. Partial reception; missing rows never prove a ship was silent.';
create index ais_positions_received_idx on argus.ais_positions (received_utc);
create index ais_positions_geog_idx on argus.ais_positions using gist (geog);

create table argus.ais_static (
  mmsi text not null check (mmsi ~ '^[0-9]{9}$'),
  field text not null check (field in ('name', 'ship_type', 'length_m', 'destination')),
  value text,
  received_utc timestamptz not null,
  stream_id text,
  inserted_utc timestamptz not null default now(),
  primary key (mmsi, field, received_utc)
);
comment on table argus.ais_static is
  'Declared AIS particulars, one row per field and receipt time, so a past image is joined with the declaration known at that time.';

create table argus.ais_sync_state (
  id smallint primary key default 1 check (id = 1),
  source_url text not null,
  stream_id text,
  sequence bigint,
  pending_request_id bigint,
  pending_since timestamptz,
  last_ok_utc timestamptz,
  last_error text,
  last_error_utc timestamptz
);
insert into argus.ais_sync_state (id, source_url)
values (1, 'https://your-ais-collector.example');

create table argus.ais_sync_runs (
  id bigint generated always as identity primary key,
  run_utc timestamptz not null default now(),
  kind text not null,
  http_status int,
  contacts int,
  positions_new int,
  static_new int,
  stream_id text,
  sequence bigint,
  error text
);
create index ais_sync_runs_time_idx on argus.ais_sync_runs (run_utc);

alter table argus.ais_positions enable row level security;
alter table argus.ais_static enable row level security;
alter table argus.ais_sync_state enable row level security;
alter table argus.ais_sync_runs enable row level security;

-- Parse one Railway packet (/api/v1/vessels snapshot or /api/v1/updates).
-- Invalid rows are skipped, never guessed; duplicates are ignored.
-- (Replaced by 20261015174922_argus_ais_static_thinning.sql.)
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
  select r->>'mmsi', f.field,
         left(regexp_replace(f.value, '[[:cntrl:]]', '', 'g'), 80),
         f.received::timestamptz, stream
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
    and f.received::timestamptz <= now() + interval '60 seconds'
    and (f.value is not null or (f.field = 'destination' and r ? 'destination'))
  on conflict do nothing;
  get diagnostics n_static = row_count;

  return jsonb_build_object('kind', kind, 'contacts', jsonb_array_length(items),
                            'positions_new', n_pos, 'static_new', n_static,
                            'stream_id', stream, 'sequence', seq, 'generated_utc', generated);
end;
$$;

-- One step of the sync loop: collect the previous HTTP answer, then ask again.
create or replace function argus.ais_sync_tick()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  st argus.ais_sync_state;
  resp record;
  result jsonb;
  rid bigint;
  url text;
begin
  select * into st from argus.ais_sync_state where id = 1 for update skip locked;
  if not found then
    return jsonb_build_object('skipped', 'another tick is running');
  end if;

  if st.pending_request_id is not null then
    select r.status_code, r.content, r.error_msg, r.timed_out
      into resp
      from net._http_response as r
     where r.id = st.pending_request_id;
    if not found then
      if st.pending_since > now() - interval '2 minutes' then
        return jsonb_build_object('waiting_for', st.pending_request_id);
      end if;
      update argus.ais_sync_state
         set pending_request_id = null, last_error = 'HTTP request lost', last_error_utc = now()
       where id = 1;
      insert into argus.ais_sync_runs (kind, error) values ('error', 'HTTP request lost');
    elsif resp.status_code = 200 and resp.content is not null then
      begin
        result := argus.ingest_ais_packet(resp.content::jsonb);
        update argus.ais_sync_state
           set stream_id = result->>'stream_id',
               sequence = (result->>'sequence')::bigint,
               last_ok_utc = now(),
               pending_request_id = null
         where id = 1;
        insert into argus.ais_sync_runs (kind, http_status, contacts, positions_new, static_new, stream_id, sequence)
        values (result->>'kind', 200, (result->>'contacts')::int, (result->>'positions_new')::int,
                (result->>'static_new')::int, result->>'stream_id', (result->>'sequence')::bigint);
      exception when others then
        -- Start again from a full snapshot; duplicates are ignored on insert.
        update argus.ais_sync_state
           set pending_request_id = null, stream_id = null, sequence = null,
               last_error = left(sqlerrm, 500), last_error_utc = now()
         where id = 1;
        insert into argus.ais_sync_runs (kind, http_status, error) values ('error', 200, left(sqlerrm, 500));
      end;
    else
      update argus.ais_sync_state
         set pending_request_id = null,
             last_error = left(coalesce(resp.error_msg, 'HTTP ' || resp.status_code::text), 500),
             last_error_utc = now()
       where id = 1;
      insert into argus.ais_sync_runs (kind, http_status, error)
      values ('error', resp.status_code, left(coalesce(resp.error_msg, resp.content, 'no body'), 500));
    end if;
    select * into st from argus.ais_sync_state where id = 1;
  end if;

  url := st.source_url ||
         case when st.stream_id is null or st.sequence is null
              then '/api/v1/vessels'
              else '/api/v1/updates?stream_id=' || st.stream_id || '&after=' || st.sequence::text end;
  rid := net.http_get(
           url := url,
           headers := jsonb_build_object('User-Agent', 'ArgusMara-SupabaseSync/1.0 (hackathon AIS history)',
                                         'Accept', 'application/json'),
           timeout_milliseconds := 25000);
  update argus.ais_sync_state set pending_request_id = rid, pending_since = now() where id = 1;
  return jsonb_build_object('requested', url, 'request_id', rid);
end;
$$;

revoke all on function argus.ingest_ais_packet(jsonb) from public, anon, authenticated;
revoke all on function argus.ais_sync_tick() from public, anon, authenticated;

select cron.schedule('argus-ais-sync', '30 seconds', 'select argus.ais_sync_tick()');
