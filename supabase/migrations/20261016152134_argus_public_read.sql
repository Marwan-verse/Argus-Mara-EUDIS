-- D108: every teammate's app reads the team database without a secret key.
--
-- The project's publishable key ships in the private repository (argus/supabase_ais.py).
-- It may run only these four read-only functions:
--   * status, AIS at a moment, recent tracks for the real alerts;
--   * the fleet-history results directory.
-- Everything that writes stays service-role only: fleet-history claims, pages, results and
-- releases; satellite scenes; comparisons. The private tables keep RLS with no policies.

-- The fleet directory wrapper was security invoker, so the publishable role would also have
-- needed the private schema. As a definer wrapper it needs only its own grant.
create or replace function public.argus_history_index(p_after text default '', p_limit int default 100,
                                                      p_only_leads boolean default false)
returns jsonb language sql stable security definer set search_path = '' as $$
  select argus.history_index(p_after, p_limit, p_only_leads);
$$;
revoke all on function public.argus_history_index(text, int, boolean) from public, anon, authenticated;
grant execute on function public.argus_history_index(text, int, boolean) to anon, service_role;

grant execute on function public.argus_ais_status() to anon;
grant execute on function public.argus_ais_rows(timestamptz, double precision, double precision, double precision,
                                                double precision) to anon;
grant execute on function public.argus_recent_tracks(timestamptz, double precision, double precision, double precision,
                                                     double precision, int) to anon;
