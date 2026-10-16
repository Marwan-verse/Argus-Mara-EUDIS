-- D98: endpoint reachability is not an exact AIS position or error probability.
create function argus.ais_temporal_support(identity_mmsi text, epoch text, t timestamptz,
                                           tb timestamptz, ta timestamptz, method text,
                                           estimate_lat double precision, estimate_lon double precision)
returns jsonb language sql stable security definer set search_path = '' as $$
with fixes as (
 select p.lat,p.lon,p.received_utc,abs(extract(epoch from t-p.received_utc))::float8 offset_s,
        80*1852*abs(extract(epoch from t-p.received_utc))/3600 radius_m
 from argus.ais_positions p where p.mmsi=identity_mmsi and p.stream_id=epoch
   and (p.received_utc=tb or (method like 'interpolated%' and p.received_utc=ta))
), summary as (
 select jsonb_agg(jsonb_build_object('lat',f.lat,'lon',f.lon,'offset_s',f.offset_s,'radius_m',f.radius_m)
                  order by f.received_utc) points,
        ceil(min(f.radius_m+extensions.st_distance(
          extensions.st_setsrid(extensions.st_makepoint(f.lon,f.lat),4326)::extensions.geography,
          extensions.st_setsrid(extensions.st_makepoint(estimate_lon,estimate_lat),4326)::extensions.geography))) radius
 from fixes f
)
select case when points is not null then jsonb_build_object('method','endpoint_reachability',
  'max_speed_kn',80,'fixes',points,'center_radius_m',radius,'label','assumption',
  'caveat','80 kn screening assumption; not a confidence interval. Receipt-time and sensor errors are not bounded.') end
from summary;
$$;
revoke all on function argus.ais_temporal_support(text,text,timestamptz,timestamptz,timestamptz,text,double precision,double precision)
from public,anon,authenticated;

create function argus.contact_in_temporal_support(contact extensions.geography, support jsonb, margin_m double precision)
returns boolean language sql immutable set search_path = '' as $$
 select case when jsonb_array_length(support->'fixes') > 0 then not exists (
   select 1 from jsonb_array_elements(support->'fixes') f where not extensions.st_dwithin(contact,
     extensions.st_setsrid(extensions.st_makepoint((f->>'lon')::float8,(f->>'lat')::float8),4326)::extensions.geography,
     (f->>'radius_m')::float8+margin_m)) end;
$$;
revoke all on function argus.contact_in_temporal_support(extensions.geography,jsonb,double precision)
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
    geog extensions.geography, name text, length_m double precision, static_age_h double precision, temporal_support jsonb
  ) on commit drop;
  truncate pg_temp.cmp_ais;
  insert into pg_temp.cmp_ais
  select a.mmsi, a.lat, a.lon, a.method, a.nearest_offset_s, a.sog_kn, a.nav_status,
         (extensions.st_setsrid(extensions.st_makepoint(a.lon, a.lat), 4326))::extensions.geography,
         nm.value, case when ln.value ~ '^[0-9]+(\.[0-9]+)?$' then ln.value::double precision end,
         extract(epoch from sc.acquired_utc - ln.received_utc) / 3600.0,
         argus.ais_temporal_support(a.mmsi,a.stream_id,sc.acquired_utc,a.fix_before,a.fix_after,a.method,a.lat,a.lon)
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
           (select count(*) from pg_temp.cmp_ais o where o.method not like '%motion_inconsistent' and (extensions.st_dwithin(c.geog, o.geog, gate_m) or argus.contact_in_temporal_support(c.geog,o.temporal_support,gate_m))) as within_gate
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
                                 'observed_areas', n_areas,
                                 'ais_temporally_uncertain', (select count(*) from pg_temp.cmp_ais where (temporal_support->>'center_radius_m')::float8>alt_m)),
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
        and not exists (select 1 from pg_temp.cmp_ais a where extensions.st_dwithin(c.geog, a.geog, gate_m))
        and not exists (select 1 from pg_temp.cmp_ais a where a.method not like '%motion_inconsistent' and argus.contact_in_temporal_support(c.geog,a.temporal_support,gate_m))), '[]'),
    'ais_not_seen', case when not coalesce(verified, false) or sc.review_evidence->'clear_footprint_radius_m' is distinct from '100'::jsonb or n_areas = 0 then '[]'::jsonb else coalesce((
      select jsonb_agg(jsonb_build_object(
               'mmsi', a.mmsi, 'name', a.name, 'ais_length_m', a.length_m, 'lat', a.lat, 'lon', a.lon,
               'ais_position_method', a.method, 'nearest_fix_offset_s', round(a.nearest_offset_s::numeric, 1),
               'temporal_support', a.temporal_support,
               'sog_kn', a.sog_kn, 'length_declared_hours_before', round(a.static_age_h::numeric, 1),
               'review', 'AIS places a large ship here, but no image contact was detected within ' || alt_m::int ||
                         ' m: detection misses remain possible; lead for review')
             order by a.length_m desc)
      from pg_temp.cmp_ais a
      where not a.mmsi = any(used_m)
        and a.method not like '%motion_inconsistent'
        and (a.temporal_support->>'center_radius_m')::float8 <= alt_m
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
      '80 kn endpoint reachability is a screening assumption, not a confidence interval. Receipt-time and sensor errors remain.',
      'A moving ship can appear shifted on a radar image by hundreds of metres.',
      'Small boats, cloud, glint, sea state and coastline cause misses and false contacts.',
      'Every item is a lead for human review, never proof of intent or of AIS switch-off.'));
  return result;
end;
$$;
revoke all on function argus.compare_scene(text, double precision, double precision, double precision) from public, anon, authenticated;

revoke all on function public.argus_save_scene(jsonb) from public,anon,authenticated;
grant execute on function public.argus_save_scene(jsonb) to service_role;
