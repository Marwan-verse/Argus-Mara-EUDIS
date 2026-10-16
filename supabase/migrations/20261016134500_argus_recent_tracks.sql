-- D95 live real alerts: recent tracks of the ships in an area, read only.
--
-- argus_ais_rows returns +/-10 min around one moment together with 24 h of static
-- history, which is about 1.5 MB for Irish waters. The alert rules instead need each
-- ship's last few hours of fixes, fetched incrementally, plus only its latest
-- name, type and length. This returns positions received at or after p_since
-- (never more than 12 h back), newest first when the row limit cuts the window,
-- and the latest value of each static field from the last 7 days.

create or replace function public.argus_recent_tracks(p_since timestamptz, p_w double precision, p_s double precision,
                                                      p_e double precision, p_n double precision,
                                                      p_limit int default 20000)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with bounded as (
    select greatest(p_since, now() - interval '12 hours') as since, least(greatest(coalesce(p_limit, 20000), 1), 50000) as cap
  ), pos as (
    select p.mmsi, p.received_utc, p.lat, p.lon, p.sog_kn, p.cog_deg, p.heading_deg, p.nav_status
    from argus.ais_positions p, bounded b
    where p.received_utc >= b.since
      and p.lon between p_w and p_e and p.lat between p_s and p_n
    order by p.received_utc desc
    limit (select cap from bounded)
  ), stat as (
    select distinct on (st.mmsi, st.field) st.mmsi, st.field, st.value
    from argus.ais_static st
    where st.mmsi in (select distinct mmsi from pos)
      and st.received_utc >= now() - interval '7 days'
    order by st.mmsi, st.field, st.received_utc desc
  )
  select jsonb_build_object(
    'source', 'Supabase argus.ais_positions (copied from the team Railway feed)',
    'since', (select since from bounded),
    'generated_utc', now(),
    'truncated', (select count(*) from pos) >= (select cap from bounded),
    -- [mmsi, received epoch s, lat, lon, sog kn, cog deg, heading deg, nav status], oldest first
    'positions', coalesce((select jsonb_agg(jsonb_build_array(mmsi, extract(epoch from received_utc), lat, lon,
                                                              sog_kn, cog_deg, heading_deg, nav_status)
                                            order by received_utc) from pos), '[]'::jsonb),
    'static', coalesce((select jsonb_object_agg(mmsi, fields)
                        from (select mmsi, jsonb_object_agg(field, value) as fields from stat group by mmsi) s),
                       '{}'::jsonb));
$$;

revoke all on function public.argus_recent_tracks(timestamptz, double precision, double precision, double precision,
                                                  double precision, int) from public, anon, authenticated;
grant execute on function public.argus_recent_tracks(timestamptz, double precision, double precision, double precision,
                                                    double precision, int) to service_role;
