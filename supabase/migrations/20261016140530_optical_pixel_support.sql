-- D94: independent pixel evidence and model positions remain auditable.
alter table argus.sat_contacts add column localization jsonb not null default '{}'::jsonb;
alter table argus.sat_contacts drop constraint sat_contacts_source_check;
alter table argus.sat_contacts add constraint sat_contacts_source_check check
  (source in ('tensorx_ai', 'local_screen', 'manual', 'gfw', 'cfar', 'simulated',
              'tensorx_ai_pixel_supported', 'compact_optical_feature'));
create or replace function argus.contact_position_eligible(quality jsonb)
returns boolean language sql immutable set search_path = '' as $$
  select coalesce(quality = '{}'::jsonb or
    (quality->>'status' = 'anchored' and quality->'water_mask_verified' = 'true'::jsonb), false);
$$;
revoke all on function argus.contact_position_eligible(jsonb) from public, anon, authenticated;

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
    insert into argus.sat_contacts (scene_id, external_id, lat, lon, source, label, confidence, length_m, note, overlap_ambiguous, localization)
    select sid, left(c->>'external_id', 120), (c->>'lat')::double precision, (c->>'lon')::double precision,
           c->>'source', c->>'label',
           case when jsonb_typeof(c->'confidence') = 'number' then (c->>'confidence')::real end,
           case when jsonb_typeof(c->'length_m') = 'number' then (c->>'length_m')::real end,
           left(c->>'note', 300), coalesce(c->'overlap_ambiguous' = 'true'::jsonb, false), case when jsonb_typeof(c->'localization') = 'object' then c->'localization' else '{}'::jsonb end
    from jsonb_array_elements(payload->'contacts') c
    where jsonb_typeof(c->'lat') = 'number' and jsonb_typeof(c->'lon') = 'number'
    on conflict (scene_id, external_id) do update
      set lat = excluded.lat, lon = excluded.lon, source = excluded.source, label = excluded.label,
          confidence = excluded.confidence, length_m = excluded.length_m, note = excluded.note, overlap_ambiguous = excluded.overlap_ambiguous, localization = excluded.localization;
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
  verified := sc.label = 'real' and sc.review_evidence->>'version' = 'image-ais-review-v2' and sc.review_evidence->'image_input_verified' = 'true'::jsonb
              and coalesce(sc.review_evidence->>'image_status','limited') <> 'unusable';

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
      and argus.contact_position_eligible(c.localization)
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
      where c.scene_id = p_scene and c.label in ('real', 'assumption') and c.source <> 'simulated' and not c.id = any(used_c) and not c.overlap_ambiguous and argus.contact_position_eligible(c.localization) and verified and n_ais > 0 and n_excluded = 0
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
    'not_checked', case when sc.review_evidence->>'image_status' = 'unusable' then 'Image was unusable: all review leads withheld'
                        when not coalesce(verified, false) then 'Image verification unavailable or simulated scene: review leads withheld'
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
