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
begin
  select * into sc from argus.sat_scenes where id = p_scene;
  if not found then
    raise exception 'unknown scene %', p_scene;
  end if;

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
                     where st.mmsi = a.mmsi and st.field = 'name' and st.received_utc <= sc.acquired_utc
                     order by st.received_utc desc limit 1) nm on true
  left join lateral (select st.value, st.received_utc from argus.ais_static st
                     where st.mmsi = a.mmsi and st.field = 'length_m' and st.received_utc <= sc.acquired_utc
                     order by st.received_utc desc limit 1) ln on true;
  select count(*) into n_ais from pg_temp.cmp_ais;
  select count(*) into n_contacts from argus.sat_contacts where scene_id = p_scene;
  select count(*) into n_areas from argus.sat_observed_areas where scene_id = p_scene;

  for pair in
    select c.id as cid, c.external_id, a.mmsi, a.name, a.length_m, a.method, a.nearest_offset_s,
           extensions.st_distance(c.geog, a.geog) as d,
           (select count(*) from pg_temp.cmp_ais o where extensions.st_dwithin(c.geog, o.geog, gate_m)) as within_gate
    from argus.sat_contacts c
    join pg_temp.cmp_ais a on extensions.st_dwithin(c.geog, a.geog, gate_m)
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
               'nearest_ais_m', (select round(min(extensions.st_distance(c.geog, a.geog))::numeric, 1) from pg_temp.cmp_ais a),
               'candidates_within_alt', (select coalesce(jsonb_agg(jsonb_build_object(
                    'mmsi', a.mmsi, 'name', a.name,
                    'distance_m', round(extensions.st_distance(c.geog, a.geog)::numeric, 1))
                    order by extensions.st_distance(c.geog, a.geog)), '[]')
                  from pg_temp.cmp_ais a where extensions.st_dwithin(c.geog, a.geog, alt_m)),
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
      from pg_temp.cmp_ais a
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
revoke all on function argus.compare_scene(text, double precision, double precision, double precision) from public, anon, authenticated;
