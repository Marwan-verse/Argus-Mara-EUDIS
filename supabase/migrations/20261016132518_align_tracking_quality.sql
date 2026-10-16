-- D97: raw corrections must remain evidence when normalized fixes conflict.
alter table argus.ais_observations add column position_received_utc timestamptz;
alter table argus.ais_observations add column lat double precision;
alter table argus.ais_observations add column lon double precision;

create function argus.observation_position_fields()
returns trigger language plpgsql set search_path = '' as $$
declare stamp text;
begin
  new.position_received_utc := null;
  new.lat := null;
  new.lon := null;
  stamp := coalesce(new.payload->>'received_utc', new.payload->>'recv_utc');
  -- Static-only messages, invalid timestamps and invalid coordinates remain
  -- archived; they simply cannot supply a position or conflict at a made-up time.
  begin
    if stamp !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$' then
      return new;
    end if;
    new.lat := (new.payload->>'lat')::double precision;
    new.lon := (new.payload->>'lon')::double precision;
    if new.lat between -90 and 90 and new.lon between -180 and 180 then
      new.position_received_utc := stamp::timestamptz;
    else
      new.lat := null;
      new.lon := null;
    end if;
  exception when invalid_text_representation or datetime_field_overflow or invalid_datetime_format or numeric_value_out_of_range then
    new.position_received_utc := null;
    new.lat := null;
    new.lon := null;
  end;
  return new;
end;
$$;
revoke all on function argus.observation_position_fields() from public,anon,authenticated;
create trigger ais_observation_position_fields before insert or update of payload
on argus.ais_observations for each row execute function argus.observation_position_fields();
update argus.ais_observations set payload = payload;
create index ais_observations_position_time_idx on argus.ais_observations(position_received_utc)
where position_received_utc is not null;

create or replace function argus.ais_candidates_at(t timestamptz, w double precision, s double precision,
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
where true
;
$$;
revoke all on function argus.ais_candidates_at(timestamptz,double precision,double precision,double precision,double precision,int,int) from public,anon,authenticated;
create function argus.ais_source_conflicts(t timestamptz, w double precision, s double precision,
                                         e double precision, n double precision)
returns table (mmsi text, reason text)
language sql stable security definer set search_path = '' as $$
with source_positions as (
 select p.mmsi,p.stream_id,p.received_utc,p.lat,p.lon,p.label from argus.ais_positions p
 where p.received_utc between t-interval '600 seconds' and t+interval '600 seconds'
   and p.lat between s-.25 and n+.25 and p.lon between w-.45 and e+.45
   and p.label in ('real','reconstructed')
 union
 select o.mmsi,o.stream_id,o.position_received_utc,o.lat,o.lon,o.label from argus.ais_observations o
 where o.position_received_utc between t-interval '600 seconds' and t+interval '600 seconds'
   and o.lat between s-.25 and n+.25 and o.lon between w-.45 and e+.45
), conflicts as (
 select p.mmsi,'conflicting_positions_at_same_time'::text reason from source_positions p
 group by p.mmsi,p.stream_id,p.received_utc having count(distinct (p.lat,p.lon)) > 1
 union
 select p.mmsi,'mixed_provenance'::text from source_positions p group by p.mmsi having count(distinct p.label)>1
 union
 select a.mmsi,'ambiguous_stream_epochs'::text from argus.ais_candidates_at(t,w,s,e,n) a
 group by a.mmsi having count(*)>1
)
select distinct c.mmsi,c.reason from conflicts c;
$$;
revoke all on function argus.ais_source_conflicts(timestamptz,double precision,double precision,double precision,double precision)
from public,anon,authenticated;
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
  exclusions jsonb;
  n_excluded int;
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
                     where st.mmsi = a.mmsi and st.stream_id = a.stream_id and st.field = 'name' and st.received_utc <= sc.acquired_utc and st.received_utc >= sc.acquired_utc - interval '24 hours'
                     order by st.received_utc desc limit 1) nm on true
  left join lateral (select st.value, st.received_utc from argus.ais_static st
                     where st.mmsi = a.mmsi and st.stream_id = a.stream_id and st.field = 'length_m' and st.received_utc <= sc.acquired_utc and st.received_utc >= sc.acquired_utc - interval '24 hours'
                     order by st.received_utc desc limit 1) ln on true;
  select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) into exclusions
  from argus.ais_source_conflicts(sc.acquired_utc,sc.bbox_w,sc.bbox_s,sc.bbox_e,sc.bbox_n) x;
  n_excluded := jsonb_array_length(exclusions);
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
    'excluded_vessels', exclusions,
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
      where c.scene_id = p_scene and c.label in ('real', 'assumption') and c.source <> 'simulated' and not c.id = any(used_c) and not c.overlap_ambiguous and verified and n_ais > 0 and n_excluded = 0
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
                        when n_excluded > 0 then 'Conflicting AIS source history: unmatched-contact leads withheld'
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

create or replace function argus.ais_at(t timestamptz, w double precision, s double precision,
                                        e double precision, n double precision,
                                        max_gap_s int default 600, max_age_s int default 300)
returns table (mmsi text, lat double precision, lon double precision, method text,
               fix_before timestamptz, fix_after timestamptz, nearest_offset_s double precision,
               sog_kn real, cog_deg real, nav_status smallint, stream_id text)
language sql stable security definer set search_path = '' as $$
 select a.* from argus.ais_candidates_at(t,w,s,e,n,max_gap_s,max_age_s) a
 where a.lat between s-.003 and n+.003 and a.lon between w-.005 and e+.005
 and not exists (select 1 from argus.ais_source_conflicts(t,w,s,e,n) x where x.mmsi=a.mmsi);
$$;
revoke all on function argus.ais_at(timestamptz,double precision,double precision,double precision,double precision,int,int)
from public,anon,authenticated;
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
    'excluded_vessels', (select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) from argus.ais_source_conflicts(p_t,p_w,p_s,p_e,p_n) x),
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


revoke all on function public.argus_ais_rows(timestamptz,double precision,double precision,double precision,double precision) from public,anon,authenticated;
grant execute on function public.argus_ais_rows(timestamptz,double precision,double precision,double precision,double precision) to service_role;
