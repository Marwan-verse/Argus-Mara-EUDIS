-- ARGUS MARA: satellite scenes, image contacts and the AIS comparison.

create table argus.sat_scenes (
  id text primary key check (id ~ '^[A-Za-z0-9._:-]{3,200}$'),
  sensor text not null check (sensor in ('Sentinel-1', 'Sentinel-2', 'other')),
  acquired_utc timestamptz not null,
  bbox_w double precision not null,
  bbox_s double precision not null,
  bbox_e double precision not null,
  bbox_n double precision not null,
  cloud_pct real,
  source text not null,
  label text not null default 'real' check (label in ('real', 'simulated')),
  note text,
  added_utc timestamptz not null default now(),
  check (bbox_w >= -180 and bbox_e <= 180 and bbox_s >= -90 and bbox_n <= 90
         and bbox_w < bbox_e and bbox_s < bbox_n and bbox_e - bbox_w <= 5 and bbox_n - bbox_s <= 5)
);
comment on table argus.sat_scenes is 'One satellite image (or crop) with its acquisition UTC; footprint as a bounding box.';

create table argus.sat_observed_areas (
  id bigint generated always as identity primary key,
  scene_id text not null references argus.sat_scenes (id) on delete cascade,
  area extensions.geography(Polygon, 4326) not null,
  quality text not null default 'clear_water',
  added_utc timestamptz not null default now()
);
comment on table argus.sat_observed_areas is 'Parts of a scene where the sea was actually visible (no cloud, land or missing data). The AIS-not-seen check runs only here.';
create index sat_observed_areas_scene_idx on argus.sat_observed_areas (scene_id);
create index sat_observed_areas_area_idx on argus.sat_observed_areas using gist (area);

create table argus.sat_contacts (
  id bigint generated always as identity primary key,
  scene_id text not null references argus.sat_scenes (id) on delete cascade,
  external_id text,
  lat double precision not null check (lat between -90 and 90),
  lon double precision not null check (lon between -180 and 180),
  geog extensions.geography(Point, 4326) generated always as
    ((extensions.st_setsrid(extensions.st_makepoint(lon, lat), 4326))::extensions.geography) stored,
  source text not null check (source in ('tensorx_ai', 'local_screen', 'manual', 'gfw', 'cfar', 'simulated')),
  label text not null check (label in ('real', 'assumption', 'simulated')),
  confidence real check (confidence is null or confidence between 0 and 1),
  length_m real check (length_m is null or length_m > 0),
  note text,
  added_utc timestamptz not null default now(),
  unique (scene_id, external_id)
);
comment on table argus.sat_contacts is 'Ship-like objects found on a scene. AI or screening contacts are assumptions until a human reviews them.';
create index sat_contacts_scene_idx on argus.sat_contacts (scene_id);

alter table argus.sat_scenes enable row level security;
alter table argus.sat_observed_areas enable row level security;
alter table argus.sat_contacts enable row level security;

-- AIS position of every vessel at time t, using the same rules as argus/space.py:
-- interpolate between two fixes at most max_gap_s apart in one server stream,
-- or project the last fix at most max_age_s old with valid speed and course.
create or replace function argus.ais_at(t timestamptz, w double precision, s double precision,
                                        e double precision, n double precision,
                                        max_gap_s int default 600, max_age_s int default 300)
returns table (mmsi text, lat double precision, lon double precision, method text,
               fix_before timestamptz, fix_after timestamptz, nearest_offset_s double precision,
               sog_kn real, cog_deg real, nav_status smallint, stream_id text)
language sql
stable
security definer
set search_path = ''
as $$
  with near as (
    select distinct p.mmsi
    from argus.ais_positions p
    where p.received_utc between t - make_interval(secs => max_gap_s) and t + make_interval(secs => max_gap_s)
      and p.lon between w - 0.45 and e + 0.45
      and p.lat between s - 0.25 and n + 0.25
  ), pairs as (
    select nr.mmsi,
           b.received_utc as tb, b.lat as latb, b.lon as lonb, b.sog_kn as sogb, b.cog_deg as cogb,
           b.nav_status as navb, b.stream_id as sb,
           a.received_utc as ta, a.lat as lata, a.lon as lona, a.stream_id as sa
    from near nr
    left join lateral (
      select p.received_utc, p.lat, p.lon, p.sog_kn, p.cog_deg, p.nav_status, p.stream_id
      from argus.ais_positions p
      where p.mmsi = nr.mmsi and p.received_utc <= t and p.received_utc >= t - make_interval(secs => max_gap_s)
      order by p.received_utc desc limit 1) b on true
    left join lateral (
      select p.received_utc, p.lat, p.lon, p.stream_id
      from argus.ais_positions p
      where p.mmsi = nr.mmsi and p.received_utc >= t and p.received_utc <= t + make_interval(secs => max_gap_s)
      order by p.received_utc asc limit 1) a on true
  ), rules as (
    select *,
           (tb is not null and ta is not null and sb = sa
            and extract(epoch from ta - tb) <= max_gap_s) as can_interpolate,
           (tb is not null and extract(epoch from t - tb) <= max_age_s
            and sogb is not null and cogb is not null) as can_project
    from pairs
  ), positioned as (
    select mmsi,
           case when can_interpolate then
                  case when ta = tb then latb
                       else latb + (lata - latb) * extract(epoch from t - tb) / extract(epoch from ta - tb) end
                when can_project then
                  latb + sogb * extract(epoch from t - tb) / 3600.0 * cos(radians(cogb)) / 60.0
           end as lat,
           case when can_interpolate then
                  case when ta = tb then lonb
                       else lonb + (lona - lonb) * extract(epoch from t - tb) / extract(epoch from ta - tb) end
                when can_project then
                  lonb + sogb * extract(epoch from t - tb) / 3600.0 * sin(radians(cogb))
                         / (60.0 * greatest(cos(radians(latb)), 0.01))
           end as lon,
           case when can_interpolate then 'interpolated' when can_project then 'projected' end as method,
           tb as fix_before, ta as fix_after,
           least(coalesce(extract(epoch from t - tb), 1e9), coalesce(extract(epoch from ta - t), 1e9))::double precision
             as nearest_offset_s,
           sogb as sog_kn, cogb as cog_deg, navb as nav_status, coalesce(sb, sa) as stream_id
    from rules
  )
  select * from positioned
  where method is not null
    and lat between s - 0.003 and n + 0.003
    and lon between w - 0.005 and e + 0.005;
$$;

-- Compare one scene with AIS at its acquisition time, both ways:
--   matches              contact <-> AIS vessel within gate_m (greedy one-to-one)
--   seen_without_ais     contact with no AIS vessel within gate_m (possible dark ship)
--   ais_not_seen         AIS vessel inside an observed clear-water area, at least
--                        min_length_m long, not moored, with no contact within alt_m
-- Every item is a lead for human review, never proof.
-- (This first version was "stable"; 20261015174836_argus_compare_scene_volatile.sql replaces it.)
create or replace function argus.compare_scene(p_scene text, gate_m double precision default 300,
                                               alt_m double precision default 1000,
                                               min_length_m double precision default 50)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  sc argus.sat_scenes;
  pair record;
  used_c bigint[] := '{}';
  used_m text[] := '{}';
  matches jsonb := '[]';
  n_ais int;
  n_contacts int;
  n_areas int;
  result jsonb;
begin
  select * into sc from argus.sat_scenes where id = p_scene;
  if not found then
    raise exception 'unknown scene %', p_scene;
  end if;

  create temporary table if not exists cmp_ais (
    mmsi text primary key, lat double precision, lon double precision, method text,
    nearest_offset_s double precision, sog_kn real, nav_status smallint,
    geog extensions.geography, name text, length_m double precision, static_age_h double precision
  ) on commit drop;
  truncate cmp_ais;
  insert into cmp_ais
  select a.mmsi, a.lat, a.lon, a.method, a.nearest_offset_s, a.sog_kn, a.nav_status,
         (extensions.st_setsrid(extensions.st_makepoint(a.lon, a.lat), 4326))::extensions.geography,
         nm.value, case when ln.value ~ '^[0-9]+(\.[0-9]+)?$' then ln.value::double precision end,
         extract(epoch from sc.acquired_utc - ln.received_utc) / 3600.0
  from argus.ais_at(sc.acquired_utc, sc.bbox_w, sc.bbox_s, sc.bbox_e, sc.bbox_n) a
  left join lateral (select st.value from argus.ais_static st
                     where st.mmsi = a.mmsi and st.field = 'name' and st.received_utc <= sc.acquired_utc
                     order by st.received_utc desc limit 1) nm on true
  left join lateral (select st.value, st.received_utc from argus.ais_static st
                     where st.mmsi = a.mmsi and st.field = 'length_m' and st.received_utc <= sc.acquired_utc
                     order by st.received_utc desc limit 1) ln on true;
  select count(*) into n_ais from cmp_ais;
  select count(*) into n_contacts from argus.sat_contacts where scene_id = p_scene;
  select count(*) into n_areas from argus.sat_observed_areas where scene_id = p_scene;

  for pair in
    select c.id as cid, c.external_id, a.mmsi, a.name, a.length_m, a.method, a.nearest_offset_s,
           extensions.st_distance(c.geog, a.geog) as d,
           (select count(*) from cmp_ais o where extensions.st_dwithin(c.geog, o.geog, gate_m)) as within_gate
    from argus.sat_contacts c
    join cmp_ais a on extensions.st_dwithin(c.geog, a.geog, gate_m)
    where c.scene_id = p_scene
    order by d
  loop
    if not pair.cid = any(used_c) and not pair.mmsi = any(used_m) then
      used_c := used_c || pair.cid;
      used_m := used_m || pair.mmsi;
      matches := matches || jsonb_build_object(
        'contact_id', pair.cid, 'external_id', pair.external_id, 'mmsi', pair.mmsi, 'name', pair.name,
        'ais_length_m', pair.length_m, 'distance_m', round(pair.d::numeric, 1),
        'ais_position_method', pair.method, 'nearest_fix_offset_s', round(pair.nearest_offset_s::numeric, 1),
        'ambiguous', pair.within_gate > 1,
        'association', 'provisional_spatiotemporal_match', 'identity_confirmed', false);
    end if;
  end loop;

  result := jsonb_build_object(
    'scene', jsonb_build_object('id', sc.id, 'sensor', sc.sensor, 'acquired_utc', sc.acquired_utc,
                                'bbox', jsonb_build_array(sc.bbox_w, sc.bbox_s, sc.bbox_e, sc.bbox_n),
                                'label', sc.label, 'source', sc.source),
    'parameters', jsonb_build_object('gate_m', gate_m, 'alternative_m', alt_m, 'min_length_m', min_length_m,
                                     'max_interpolation_gap_s', 600, 'max_projection_age_s', 300),
    'counts', jsonb_build_object('ais_vessels_at_acquisition', n_ais, 'image_contacts', n_contacts,
                                 'observed_areas', n_areas),
    'matches', matches,
    'seen_without_ais', coalesce((
      select jsonb_agg(jsonb_build_object(
               'contact_id', c.id, 'external_id', c.external_id, 'lat', c.lat, 'lon', c.lon,
               'source', c.source, 'label', c.label, 'confidence', c.confidence,
               'nearest_ais_m', (select round(min(extensions.st_distance(c.geog, a.geog))::numeric, 1) from cmp_ais a),
               'candidates_within_alt', (select coalesce(jsonb_agg(jsonb_build_object(
                    'mmsi', a.mmsi, 'name', a.name,
                    'distance_m', round(extensions.st_distance(c.geog, a.geog)::numeric, 1)) order by extensions.st_distance(c.geog, a.geog)), '[]')
                  from cmp_ais a where extensions.st_dwithin(c.geog, a.geog, alt_m)),
               'review', case when n_ais = 0 then 'no AIS recorded at acquisition time: cannot judge'
                              else 'no AIS vessel within the gate: possible dark vessel, lead for review' end)
             order by c.id)
      from argus.sat_contacts c
      where c.scene_id = p_scene and not c.id = any(used_c)), '[]'),
    'ais_not_seen', case when n_areas = 0 then '[]'::jsonb else coalesce((
      select jsonb_agg(jsonb_build_object(
               'mmsi', a.mmsi, 'name', a.name, 'ais_length_m', a.length_m, 'lat', a.lat, 'lon', a.lon,
               'ais_position_method', a.method, 'nearest_fix_offset_s', round(a.nearest_offset_s::numeric, 1),
               'sog_kn', a.sog_kn, 'length_declared_hours_before', round(a.static_age_h::numeric, 1),
               'review', 'AIS says a large ship was here, but the image shows nothing within ' || alt_m::int ||
                         ' m: possible false AIS position, lead for review')
             order by a.length_m desc)
      from cmp_ais a
      where not a.mmsi = any(used_m)
        and a.length_m >= min_length_m
        and coalesce(a.nav_status, -1) <> 5
        and exists (select 1 from argus.sat_observed_areas o
                    where o.scene_id = p_scene and extensions.st_covers(o.area, a.geog))
        and not exists (select 1 from argus.sat_contacts c
                        where c.scene_id = p_scene and extensions.st_dwithin(c.geog, a.geog, alt_m))), '[]') end,
    'not_checked', case when n_areas = 0
                        then 'AIS-not-seen check skipped: no observed clear-water area recorded for this scene' end,
    'caveats', jsonb_build_array(
      'AIS times are collector receipt times; reception is partial.',
      'A moving ship can appear shifted on a radar image by hundreds of metres.',
      'Small boats, cloud, glint, sea state and coastline cause misses and false contacts.',
      'Every item is a lead for human review, never proof of intent or of AIS switch-off.'));
  return result;
end;
$$;

-- Service-role API used by the desktop app and the satellite host.
create or replace function public.argus_ais_rows(p_t timestamptz, p_w double precision, p_s double precision,
                                                 p_e double precision, p_n double precision)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with pos as (
    select p.* from argus.ais_positions p
    where p.received_utc between p_t - interval '600 seconds' and p_t + interval '600 seconds'
      and p.lon between p_w - 0.45 and p_e + 0.45 and p.lat between p_s - 0.25 and p_n + 0.25
  ), stat as (
    select st.* from argus.ais_static st
    where st.mmsi in (select distinct mmsi from pos)
      and st.received_utc between p_t - interval '24 hours' and p_t
  )
  select jsonb_build_object(
    'source', 'Supabase argus.ais_positions (copied from the team Railway feed)',
    'acquired_utc', p_t,
    'rows', coalesce((select jsonb_agg(r) from (
        select jsonb_build_object('mmsi', mmsi, 'msg_type', 'PositionReport', 'lat', lat, 'lon', lon,
                                  'sog', sog_kn, 'cog', cog_deg, 'nav_status', nav_status,
                                  'recv_utc', to_char(received_utc at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
                                  'time_utc', '', 'timestamp_source', timestamp_source,
                                  'stream_id', stream_id, 'label', label) as r
        from pos
        union all
        select jsonb_build_object('mmsi', mmsi, 'msg_type', 'ShipStaticData',
                                  'recv_utc', to_char(received_utc at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
                                  'stream_id', stream_id, 'label', 'real',
                                  'present_fields', field,
                                  case field when 'name' then 'ship_name' else field end,
                                  case when field in ('ship_type', 'length_m') and value ~ '^[0-9]+(\.[0-9]+)?$'
                                       then to_jsonb(value::numeric) else to_jsonb(value) end)
        from stat) x), '[]'::jsonb));
$$;

create or replace function public.argus_save_scene(payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  ts_re constant text := '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$';
  sid text := payload->>'id';
  b jsonb := payload->'bbox';
  n_contacts int := 0;
  n_areas int := 0;
begin
  if coalesce(payload->>'acquired_utc', '') !~ ts_re then
    raise exception 'acquired_utc must be an ISO UTC time';
  end if;
  if jsonb_typeof(b) <> 'array' or jsonb_array_length(b) <> 4 then
    raise exception 'bbox must be [west, south, east, north]';
  end if;
  insert into argus.sat_scenes (id, sensor, acquired_utc, bbox_w, bbox_s, bbox_e, bbox_n,
                                cloud_pct, source, label, note)
  values (sid, payload->>'sensor', (payload->>'acquired_utc')::timestamptz,
          (b->>0)::double precision, (b->>1)::double precision, (b->>2)::double precision, (b->>3)::double precision,
          case when jsonb_typeof(payload->'cloud_pct') = 'number' then (payload->>'cloud_pct')::real end,
          coalesce(payload->>'source', 'unknown'), coalesce(payload->>'label', 'real'), left(payload->>'note', 500))
  on conflict (id) do update
    set sensor = excluded.sensor, acquired_utc = excluded.acquired_utc,
        bbox_w = excluded.bbox_w, bbox_s = excluded.bbox_s, bbox_e = excluded.bbox_e, bbox_n = excluded.bbox_n,
        cloud_pct = excluded.cloud_pct, source = excluded.source, label = excluded.label, note = excluded.note;

  if jsonb_typeof(payload->'observed_areas') = 'array' then
    delete from argus.sat_observed_areas where scene_id = sid;
    insert into argus.sat_observed_areas (scene_id, area, quality)
    select sid,
           (extensions.st_makeenvelope((a->>0)::double precision, (a->>1)::double precision,
                                       (a->>2)::double precision, (a->>3)::double precision, 4326))::extensions.geography,
           'clear_water'
    from jsonb_array_elements(payload->'observed_areas') a
    where jsonb_typeof(a) = 'array' and jsonb_array_length(a) = 4
      and (a->>0)::double precision < (a->>2)::double precision
      and (a->>1)::double precision < (a->>3)::double precision;
    get diagnostics n_areas = row_count;
  end if;

  if jsonb_typeof(payload->'contacts') = 'array' then
    insert into argus.sat_contacts (scene_id, external_id, lat, lon, source, label, confidence, length_m, note)
    select sid, left(c->>'external_id', 120), (c->>'lat')::double precision, (c->>'lon')::double precision,
           c->>'source', c->>'label',
           case when jsonb_typeof(c->'confidence') = 'number' then (c->>'confidence')::real end,
           case when jsonb_typeof(c->'length_m') = 'number' then (c->>'length_m')::real end,
           left(c->>'note', 300)
    from jsonb_array_elements(payload->'contacts') c
    where jsonb_typeof(c->'lat') = 'number' and jsonb_typeof(c->'lon') = 'number'
    on conflict (scene_id, external_id) do update
      set lat = excluded.lat, lon = excluded.lon, source = excluded.source, label = excluded.label,
          confidence = excluded.confidence, length_m = excluded.length_m, note = excluded.note;
    get diagnostics n_contacts = row_count;
  end if;
  return jsonb_build_object('scene', sid, 'contacts_saved', n_contacts, 'observed_areas_saved', n_areas);
end;
$$;

create or replace function public.argus_compare_scene(p_scene text, gate_m double precision default 300,
                                                      alt_m double precision default 1000,
                                                      min_length_m double precision default 50)
returns jsonb
language sql
security definer
set search_path = ''
as $$
  select argus.compare_scene(p_scene, gate_m, alt_m, min_length_m);
$$;

create or replace function public.argus_ais_status()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'last_ok_utc', s.last_ok_utc, 'last_error', s.last_error, 'last_error_utc', s.last_error_utc,
    'stream_id', s.stream_id, 'sequence', s.sequence,
    'positions', (select count(*) from argus.ais_positions),
    'positions_last_hour', (select count(*) from argus.ais_positions where received_utc > now() - interval '1 hour'),
    'vessels_last_hour', (select count(distinct mmsi) from argus.ais_positions where received_utc > now() - interval '1 hour'),
    'oldest_utc', (select min(received_utc) from argus.ais_positions),
    'newest_utc', (select max(received_utc) from argus.ais_positions),
    'scenes', (select count(*) from argus.sat_scenes),
    'contacts', (select count(*) from argus.sat_contacts),
    'database_mb', round(pg_database_size(current_database()) / 1048576.0, 1),
    'free_plan_limit_mb', 500)
  from argus.ais_sync_state s where s.id = 1;
$$;

-- Keep 14 days of positions (plus two hours around every saved scene) and 3 days of sync logs.
create or replace function argus.ais_retention()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  n_pos int;
  n_runs int;
begin
  delete from argus.ais_positions p
  where p.received_utc < now() - interval '14 days'
    and not exists (select 1 from argus.sat_scenes s
                    where p.received_utc between s.acquired_utc - interval '2 hours'
                                             and s.acquired_utc + interval '2 hours');
  get diagnostics n_pos = row_count;
  delete from argus.ais_sync_runs where run_utc < now() - interval '3 days';
  get diagnostics n_runs = row_count;
  return jsonb_build_object('positions_deleted', n_pos, 'runs_deleted', n_runs);
end;
$$;

revoke all on function argus.ais_at(timestamptz, double precision, double precision, double precision, double precision, int, int) from public, anon, authenticated;
revoke all on function argus.compare_scene(text, double precision, double precision, double precision) from public, anon, authenticated;
revoke all on function argus.ais_retention() from public, anon, authenticated;
revoke all on function public.argus_ais_rows(timestamptz, double precision, double precision, double precision, double precision) from public, anon, authenticated;
revoke all on function public.argus_save_scene(jsonb) from public, anon, authenticated;
revoke all on function public.argus_compare_scene(text, double precision, double precision, double precision) from public, anon, authenticated;
revoke all on function public.argus_ais_status() from public, anon, authenticated;
grant execute on function public.argus_ais_rows(timestamptz, double precision, double precision, double precision, double precision) to service_role;
grant execute on function public.argus_save_scene(jsonb) to service_role;
grant execute on function public.argus_compare_scene(text, double precision, double precision, double precision) to service_role;
grant execute on function public.argus_ais_status() to service_role;

select cron.schedule('argus-ais-retention', '17 3 * * *', 'select argus.ais_retention()');
