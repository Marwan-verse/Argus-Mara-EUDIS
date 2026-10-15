-- Conservative acquisition-time data quality and review evidence gates.
-- Legacy scenes have no verification manifest and cannot generate review leads.
alter table argus.sat_scenes add column review_evidence jsonb not null default '{}'::jsonb;
alter table argus.sat_contacts add column overlap_ambiguous boolean not null default false;

create or replace function argus.ais_at(t timestamptz, w double precision, s double precision,
                                        e double precision, n double precision,
                                        max_gap_s int default 600, max_age_s int default 300)
returns table (mmsi text, lat double precision, lon double precision, method text,
               fix_before timestamptz, fix_after timestamptz, nearest_offset_s double precision,
               sog_kn real, cog_deg real, nav_status smallint, stream_id text)
language sql stable security definer set search_path = '' as $$
with raw as (
  select p.* from argus.ais_positions p
  where p.received_utc between t - make_interval(secs => least(max_gap_s, 600)) and t + make_interval(secs => least(max_gap_s, 600))
    and p.lon between w-.45 and e+.45 and p.lat between s-.25 and n+.25
    and p.label in ('real', 'reconstructed')
), epochs as (
  select distinct r.mmsi, r.stream_id from raw r where r.stream_id is not null
), pairs as (
  select ep.mmsi, ep.stream_id, b.received_utc tb, b.lat latb, b.lon lonb,
    b.sog_kn sogb, b.cog_deg cogb, b.nav_status navb,
    a.received_utc ta, a.lat lata, a.lon lona
  from epochs ep
  left join lateral (select * from raw r where r.mmsi=ep.mmsi and r.stream_id=ep.stream_id and r.received_utc<=t order by r.received_utc desc limit 1) b on true
  left join lateral (select * from raw r where r.mmsi=ep.mmsi and r.stream_id=ep.stream_id and r.received_utc>=t order by r.received_utc limit 1) a on true
), rules as (
 select *, case when tb=t then 'exact_fix'
   when tb is not null and ta>tb and extract(epoch from ta-tb)<=least(max_gap_s,600) then 'interpolated'
   when tb is not null and extract(epoch from t-tb) between 0 and least(max_age_s,300)
     and sogb>=0 and sogb<102.3 and cogb>=0 and cogb<360 then 'projected' end method
 from pairs
), located as (
 select r.*, case when method='exact_fix' then extensions.st_setsrid(extensions.st_makepoint(lonb,latb),4326)
   when method='interpolated' then extensions.st_setsrid(extensions.st_makepoint(
     lonb + (lona-lonb)*extract(epoch from t-tb)/nullif(extract(epoch from ta-tb),0),
     latb + (lata-latb)*extract(epoch from t-tb)/nullif(extract(epoch from ta-tb),0)),4326)
   when method='projected' then extensions.st_project(
     extensions.st_setsrid(extensions.st_makepoint(lonb,latb),4326)::extensions.geography,
     sogb*1852*extract(epoch from t-tb)/3600.0, radians(cogb))::extensions.geometry end pos
 from rules r where method is not null
), unique_epoch as (
 select l.*, count(*) over(partition by l.mmsi) eligible_epochs from located l
), segments as (
 select r.*, lag(r.lat) over win prev_lat, lag(r.lon) over win prev_lon,
   lag(r.received_utc) over win prev_ts
 from raw r window win as (partition by r.mmsi,r.stream_id order by r.received_utc)
)
select u.mmsi, extensions.st_y(u.pos), extensions.st_x(u.pos), case when bad.motion_bad then u.method || '_motion_inconsistent' else u.method end, u.tb, u.ta,
 least(coalesce(extract(epoch from t-u.tb),1e9),coalesce(extract(epoch from u.ta-t),1e9))::float8,
 u.sogb, u.cogb, u.navb, u.stream_id
from unique_epoch u
cross join lateral (select exists (select 1 from segments z where z.mmsi=u.mmsi and z.stream_id=u.stream_id
   and extract(epoch from z.received_utc-z.prev_ts) between 0.000001 and 600
   and extensions.st_distance(extensions.st_setsrid(extensions.st_makepoint(z.lon,z.lat),4326)::extensions.geography,
                             extensions.st_setsrid(extensions.st_makepoint(z.prev_lon,z.prev_lat),4326)::extensions.geography)
       /extract(epoch from z.received_utc-z.prev_ts)*3600/1852 > 80) as motion_bad) bad
where u.eligible_epochs=1
 and extensions.st_y(u.pos) between s-.003 and n+.003 and extensions.st_x(u.pos) between w-.005 and e+.005
;
$$;
revoke all on function argus.ais_at(timestamptz,double precision,double precision,double precision,double precision,int,int) from public,anon,authenticated;

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

  delete from argus.sat_observed_areas where scene_id = sid;
  if jsonb_typeof(payload->'observed_areas') = 'array' then
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

  delete from argus.sat_contacts where scene_id = sid;
  if jsonb_typeof(payload->'contacts') = 'array' then
    insert into argus.sat_contacts (scene_id, external_id, lat, lon, source, label, confidence, length_m, note, overlap_ambiguous)
    select sid, left(c->>'external_id', 120), (c->>'lat')::double precision, (c->>'lon')::double precision,
           c->>'source', c->>'label',
           case when jsonb_typeof(c->'confidence') = 'number' then (c->>'confidence')::real end,
           case when jsonb_typeof(c->'length_m') = 'number' then (c->>'length_m')::real end,
           left(c->>'note', 300), coalesce(c->'overlap_ambiguous' = 'true'::jsonb, false)
    from jsonb_array_elements(payload->'contacts') c
    where jsonb_typeof(c->'lat') = 'number' and jsonb_typeof(c->'lon') = 'number'
    on conflict (scene_id, external_id) do update
      set lat = excluded.lat, lon = excluded.lon, source = excluded.source, label = excluded.label,
          confidence = excluded.confidence, length_m = excluded.length_m, note = excluded.note, overlap_ambiguous = excluded.overlap_ambiguous;
    get diagnostics n_contacts = row_count;
  end if;
  update argus.sat_scenes set review_evidence = case when jsonb_typeof(payload->'review_evidence') = 'object' then payload->'review_evidence' else '{}'::jsonb end where id = sid;
  return jsonb_build_object('scene', sid, 'contacts_saved', n_contacts, 'observed_areas_saved', n_areas);
end;
$$;


-- compare_scene builds a per-call temporary table, so it must be volatile and
-- refer to the table explicitly in pg_temp.
create or replace function argus.compare_scene(p_scene text, gate_m double precision default 300,
                                               alt_m double precision default 1000,
                                               min_length_m double precision default 50)
returns jsonb
language plpgsql
volatile
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
  verified boolean;
begin
  select * into sc from argus.sat_scenes where id = p_scene;
  if not found then
    raise exception 'unknown scene %', p_scene;
  end if;

  if gate_m is null or alt_m is null or min_length_m is null or not (gate_m > 0 and gate_m <= 1000 and alt_m >= gate_m and alt_m <= 5000 and min_length_m >= 50 and min_length_m <= 1022) then
    raise exception 'invalid comparison parameters';
  end if;
  verified := sc.label = 'real' and sc.review_evidence->>'version' = 'image-ais-review-v2' and sc.review_evidence->'image_input_verified' = 'true'::jsonb;

  create table if not exists pg_temp.cmp_ais (
    mmsi text primary key, lat double precision, lon double precision, method text,
    nearest_offset_s double precision, sog_kn real, nav_status smallint,
    geog extensions.geography, name text, length_m double precision, static_age_h double precision
  ) on commit drop;
  truncate pg_temp.cmp_ais;
  insert into pg_temp.cmp_ais
  select a.mmsi, a.lat, a.lon, a.method, a.nearest_offset_s, a.sog_kn, a.nav_status,
         (extensions.st_setsrid(extensions.st_makepoint(a.lon, a.lat), 4326))::extensions.geography,
         nm.value, case when ln.value ~ '^[0-9]+(\.[0-9]+)?$' then ln.value::double precision end,
         extract(epoch from sc.acquired_utc - ln.received_utc) / 3600.0
  from argus.ais_at(sc.acquired_utc, sc.bbox_w, sc.bbox_s, sc.bbox_e, sc.bbox_n) a
  left join lateral (select st.value from argus.ais_static st
                     where st.mmsi = a.mmsi and st.field = 'name' and st.received_utc <= sc.acquired_utc and st.received_utc >= sc.acquired_utc - interval '24 hours'
                     order by st.received_utc desc limit 1) nm on true
  left join lateral (select st.value, st.received_utc from argus.ais_static st
                     where st.mmsi = a.mmsi and st.field = 'length_m' and st.received_utc <= sc.acquired_utc and st.received_utc >= sc.acquired_utc - interval '24 hours'
                     order by st.received_utc desc limit 1) ln on true;
  select count(*) into n_ais from pg_temp.cmp_ais;
  select count(*) into n_contacts from argus.sat_contacts where scene_id = p_scene and label in ('real', 'assumption') and source <> 'simulated';
  select count(*) into n_areas from argus.sat_observed_areas where scene_id = p_scene;

  if verified then
  for pair in
    select c.id as cid, c.external_id, a.mmsi, a.name, a.length_m, a.method, a.nearest_offset_s,
           extensions.st_distance(c.geog, a.geog) as d,
           (select count(*) from pg_temp.cmp_ais o where extensions.st_dwithin(c.geog, o.geog, gate_m)) as within_gate
    from argus.sat_contacts c
    join pg_temp.cmp_ais a on extensions.st_dwithin(c.geog, a.geog, gate_m)
    where c.scene_id = p_scene and c.label in ('real', 'assumption') and c.source <> 'simulated'
      and a.method not like '%motion_inconsistent' and not c.overlap_ambiguous
    order by d, c.id, a.mmsi
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
  end if;

  result := jsonb_build_object(
    'scene', jsonb_build_object('id', sc.id, 'sensor', sc.sensor, 'acquired_utc', sc.acquired_utc,
                                'bbox', jsonb_build_array(sc.bbox_w, sc.bbox_s, sc.bbox_e, sc.bbox_n),
                                'label', sc.label, 'source', sc.source),
    'parameters', jsonb_build_object('gate_m', gate_m, 'alternative_m', alt_m, 'min_length_m', min_length_m,
                                     'max_interpolation_gap_s', 600, 'max_projection_age_s', 300),
    'counts', jsonb_build_object('ais_vessels_at_acquisition', n_ais, 'image_contacts', n_contacts,
                                 'ais_motion_ineligible', (select count(*) from pg_temp.cmp_ais where method like '%motion_inconsistent'),
                                 'observed_areas', n_areas),
    'matches', matches,
    'seen_without_ais', coalesce((
      select jsonb_agg(jsonb_build_object(
               'contact_id', c.id, 'external_id', c.external_id, 'lat', c.lat, 'lon', c.lon,
               'source', c.source, 'label', c.label, 'confidence', c.confidence,
               'nearest_ais_m', (select round(min(extensions.st_distance(c.geog, a.geog))::numeric, 1) from pg_temp.cmp_ais a),
               'candidates_within_alt', (select coalesce(jsonb_agg(jsonb_build_object(
                    'mmsi', a.mmsi, 'name', a.name,
                    'distance_m', round(extensions.st_distance(c.geog, a.geog)::numeric, 1))
                    order by extensions.st_distance(c.geog, a.geog)), '[]')
                  from pg_temp.cmp_ais a where extensions.st_dwithin(c.geog, a.geog, alt_m)),
               'review', case when n_ais = 0 then 'no AIS recorded at acquisition time: cannot judge'
                              else 'no eligible AIS vessel within the gate; partial reception, lead for review' end)
             order by c.id)
      from argus.sat_contacts c
      where c.scene_id = p_scene and c.label in ('real', 'assumption') and c.source <> 'simulated' and not c.id = any(used_c) and not c.overlap_ambiguous and verified and n_ais > 0
        and not exists (select 1 from pg_temp.cmp_ais a where extensions.st_dwithin(c.geog, a.geog, gate_m))), '[]'),
    'ais_not_seen', case when not coalesce(verified, false) or sc.review_evidence->'clear_footprint_radius_m' is distinct from '100'::jsonb or n_areas = 0 then '[]'::jsonb else coalesce((
      select jsonb_agg(jsonb_build_object(
               'mmsi', a.mmsi, 'name', a.name, 'ais_length_m', a.length_m, 'lat', a.lat, 'lon', a.lon,
               'ais_position_method', a.method, 'nearest_fix_offset_s', round(a.nearest_offset_s::numeric, 1),
               'sog_kn', a.sog_kn, 'length_declared_hours_before', round(a.static_age_h::numeric, 1),
               'review', 'AIS places a large ship here, but no image contact was detected within ' || alt_m::int ||
                         ' m: detection misses remain possible; lead for review')
             order by a.length_m desc)
      from pg_temp.cmp_ais a
      where not a.mmsi = any(used_m)
        and a.method not like '%motion_inconsistent'
        and a.length_m >= min_length_m and a.length_m <= 1022
        and coalesce(a.nav_status, -1) <> 5
        and exists (select 1 from argus.sat_observed_areas o
                    where o.scene_id = p_scene and o.quality = 'clear_water' and extensions.st_covers(o.area, a.geog))
        and not exists (select 1 from argus.sat_contacts c
                        where c.scene_id = p_scene and c.label in ('real', 'assumption') and c.source <> 'simulated' and extensions.st_dwithin(c.geog, a.geog, alt_m))), '[]') end,
    'not_checked', case when not coalesce(verified, false) then 'Image verification unavailable or simulated scene: review leads withheld'
                        when n_ais = 0 then 'No eligible AIS at acquisition UTC: cannot judge silence'
                        when sc.review_evidence->'clear_footprint_radius_m' is distinct from '100'::jsonb
                        then 'AIS-not-seen check skipped: clear 100 m footprint not verified'
                        when n_areas = 0
                        then 'AIS-not-seen check skipped: no observed clear-water area recorded for this scene' end,
    'caveats', jsonb_build_array(
      'AIS times are collector receipt times; reception is partial.',
      'A moving ship can appear shifted on a radar image by hundreds of metres.',
      'Small boats, cloud, glint, sea state and coastline cause misses and false contacts.',
      'Every item is a lead for human review, never proof of intent or of AIS switch-off.'));
  return result;
end;
$$;
revoke all on function argus.compare_scene(text, double precision, double precision, double precision) from public, anon, authenticated;

revoke all on function public.argus_save_scene(jsonb) from public,anon,authenticated;
grant execute on function public.argus_save_scene(jsonb) to service_role;
