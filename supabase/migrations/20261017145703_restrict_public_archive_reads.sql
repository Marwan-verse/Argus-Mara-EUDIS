-- Public-source release: archive reads must not inherit the old team-wide anon grants.
-- Apply on existing deployments before changing repository visibility. No data is deleted.
begin;
do $$
declare f record;
begin
  for f in
    select p.oid::regprocedure as signature
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname in
      ('argus_ais_status', 'argus_ais_rows', 'argus_recent_tracks', 'argus_history_index')
  loop
    execute format('revoke execute on function %s from public, anon, authenticated', f.signature);
    execute format('grant execute on function %s to service_role', f.signature);
  end loop;
end $$;
commit;
