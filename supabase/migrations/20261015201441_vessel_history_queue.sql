-- Private whole-fleet history queue. Python computes the review findings.
-- No received-data gap is classified as malicious in SQL.

create table argus.vessel_history_checks (
  mmsi text primary key check (mmsi ~ '^[0-9]{9}$'),
  revision bigint not null default 1,
  checked_revision bigint not null default 0,
  checked_utc timestamptz,
  result jsonb,
  last_error text,
  retry_after timestamptz,
  lease_token uuid,
  lease_until timestamptz,
  claimed_revision bigint,
  rule_version text,
  cutoff_utc timestamptz,
  history_from timestamptz,
  expected_rows bigint,
  finished_token uuid
);
alter table argus.vessel_history_checks enable row level security;
create unique index vessel_history_lease_idx on argus.vessel_history_checks (lease_token) where lease_token is not null;
create unique index vessel_history_finished_idx on argus.vessel_history_checks (finished_token) where finished_token is not null;
revoke all on argus.vessel_history_checks from public, anon, authenticated;
comment on table argus.vessel_history_checks is
  'One row per recorded vessel, with a revision watermark and resumable exclusive lease. Result means rules checked partial received history, never a safety clearance.';

-- Revisions identify a stable evidence snapshot even when a later import adds
-- positions with earlier received timestamps. Transaction start times are not
-- a safe watermark for late commits. Constant defaults preserve old evidence.
alter table argus.ais_positions add column history_revision bigint not null default 0;
alter table argus.ais_static add column history_revision bigint not null default 0;

insert into argus.vessel_history_checks (mmsi)
select mmsi from argus.ais_positions union select mmsi from argus.ais_static;

create function argus.mark_history_dirty()
returns trigger language plpgsql security definer set search_path = '' as $$
declare rev bigint;
begin
  insert into argus.vessel_history_checks (mmsi) values (new.mmsi)
  on conflict (mmsi) do update set revision = argus.vessel_history_checks.revision + 1, retry_after = null
  returning revision into rev;
  if tg_table_name = 'ais_positions' then
    update argus.ais_positions set history_revision = rev
      where mmsi = new.mmsi and received_utc = new.received_utc;
  else
    update argus.ais_static set history_revision = rev
      where mmsi = new.mmsi and field = new.field and received_utc = new.received_utc;
  end if;
  return null;
end;
$$;
-- AFTER INSERT fires only for genuinely inserted rows, not duplicates skipped
-- by the collector's ON CONFLICT DO NOTHING path.
create trigger ais_position_history_dirty after insert on argus.ais_positions
for each row execute function argus.mark_history_dirty();
create trigger ais_static_history_dirty after insert on argus.ais_static
for each row execute function argus.mark_history_dirty();

create function argus.history_claim(p_rule_version text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare job argus.vessel_history_checks; display_name text;
begin
  if p_rule_version is null or length(p_rule_version) not between 1 and 80 then
    raise exception 'Invalid history rule version';
  end if;
  if p_rule_version <> 'fleet-received-history-v1' then
    raise exception 'Unsupported history rules; update the client and database together';
  end if;
  select * into job from argus.vessel_history_checks
  where (lease_until is null or lease_until < clock_timestamp())
    and (retry_after is null or retry_after < clock_timestamp())
    and (checked_revision < revision or result->>'version' is distinct from p_rule_version)
  order by checked_utc nulls first, mmsi
  limit 1 for update skip locked;
  if not found then
    return jsonb_build_object('job', null);
  end if;
  job.lease_token := gen_random_uuid();
  job.cutoff_utc := clock_timestamp();
  job.history_from := job.cutoff_utc - interval '14 days';
  job.claimed_revision := job.revision;
  select count(*) into job.expected_rows from argus.ais_positions
  where mmsi = job.mmsi and received_utc between job.history_from and job.cutoff_utc
    and history_revision <= job.claimed_revision;
  update argus.vessel_history_checks set
    lease_token = job.lease_token, lease_until = clock_timestamp() + interval '5 minutes',
    cutoff_utc = job.cutoff_utc, history_from = job.history_from,
    claimed_revision = job.claimed_revision, expected_rows = job.expected_rows,
    rule_version = p_rule_version where mmsi = job.mmsi;
  select value into display_name from argus.ais_static
    where mmsi = job.mmsi and field = 'name' and received_utc <= job.cutoff_utc
      and history_revision <= job.claimed_revision order by received_utc desc limit 1;
  return jsonb_build_object('job', jsonb_build_object(
    'mmsi', job.mmsi, 'name', coalesce(display_name, job.mmsi), 'token', job.lease_token,
    'revision', job.claimed_revision, 'cutoff_utc', job.cutoff_utc, 'history_from', job.history_from,
    'expected_rows', job.expected_rows, 'rule_version', p_rule_version));
end;
$$;

create function argus.history_page(p_token uuid, p_after timestamptz default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare job argus.vessel_history_checks; page jsonb; last_time timestamptz; more boolean;
begin
  select * into job from argus.vessel_history_checks where lease_token = p_token
    and lease_until > clock_timestamp() for update;
  if not found then return jsonb_build_object('lease_expired', true); end if;
  update argus.vessel_history_checks set lease_until = clock_timestamp() + interval '5 minutes'
    where mmsi = job.mmsi;
  select coalesce(jsonb_agg(to_jsonb(p) order by p.received_utc), '[]'), max(p.received_utc)
    into page, last_time from (
      select mmsi, received_utc, lat, lon, sog_kn, cog_deg, stream_id, label, timestamp_source
      from argus.ais_positions
      where mmsi = job.mmsi and received_utc between job.history_from and job.cutoff_utc
        and history_revision <= job.claimed_revision
        and (p_after is null or received_utc > p_after)
      order by received_utc limit 1000
    ) p;
  select exists(select 1 from argus.ais_positions
    where mmsi = job.mmsi and received_utc between job.history_from and job.cutoff_utc
      and history_revision <= job.claimed_revision and received_utc > coalesce(last_time, p_after, job.cutoff_utc)) into more;
  return jsonb_build_object('mmsi', job.mmsi, 'rows', page, 'has_more', more,
                           'next_after', coalesce(last_time, p_after));
end;
$$;

create function argus.history_finish(p_token uuid, p_result jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare job argus.vessel_history_checks; current_rows bigint;
begin
  -- A retry after a lost completion response must return success, even if a new
  -- worker has since leased this vessel to check newer evidence.
  if exists(select 1 from argus.vessel_history_checks where finished_token = p_token) then
    return (select jsonb_build_object('saved', true, 'already_saved', true, 'checked_utc', checked_utc,
                                     'new_evidence_pending', checked_revision < revision)
            from argus.vessel_history_checks where finished_token = p_token);
  end if;
  select * into job from argus.vessel_history_checks where lease_token = p_token
    and lease_until > clock_timestamp() for update;
  if not found then return jsonb_build_object('lease_expired', true); end if;
  if jsonb_typeof(p_result) is distinct from 'object'
     or p_result->>'mmsi' is distinct from job.mmsi
     or p_result->>'version' is distinct from job.rule_version
     or p_result->'completed' is distinct from 'true'::jsonb
     or jsonb_typeof(p_result->'review_required') is distinct from 'boolean'
     or jsonb_typeof(p_result->'rows_checked') is distinct from 'number'
     or coalesce(p_result->>'status', '') not in ('review_required', 'isolated_cue', 'insufficient_history', 'no_rule_cues')
     or (p_result->>'review_required')::boolean is distinct from (p_result->>'status' = 'review_required')
     or jsonb_typeof(p_result->'findings') is distinct from 'array'
     or jsonb_array_length(p_result->'findings') > 100
     or (p_result->>'rows_checked')::bigint is distinct from job.expected_rows
     or octet_length(p_result::text) > 131072 then
    raise exception 'Incomplete or invalid vessel history result';
  end if;
  select count(*) into current_rows from argus.ais_positions
    where mmsi = job.mmsi and received_utc between job.history_from and job.cutoff_utc
      and history_revision <= job.claimed_revision;
  if current_rows <> job.expected_rows then
    update argus.vessel_history_checks set lease_until = null, lease_token = null where mmsi = job.mmsi;
    return jsonb_build_object('snapshot_changed', true);
  end if;
  update argus.vessel_history_checks set checked_revision = job.claimed_revision,
    checked_utc = clock_timestamp(), result = p_result, lease_until = null, lease_token = null,
    finished_token = p_token, last_error = null, retry_after = null where mmsi = job.mmsi
    returning checked_utc into job.checked_utc;
  return jsonb_build_object('saved', true, 'checked_utc', job.checked_utc,
                           'new_evidence_pending', job.revision > job.claimed_revision);
end;
$$;

create function argus.history_release(p_token uuid, p_reason text)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  update argus.vessel_history_checks set lease_until = null, lease_token = null,
    last_error = left(p_reason, 300), retry_after = clock_timestamp() + interval '5 minutes'
  where lease_token = p_token;
  if not found then return jsonb_build_object('lease_expired', true); end if;
  return jsonb_build_object('released', true);
end;
$$;

create function argus.history_index(p_after text default '', p_limit int default 100, p_only_leads boolean default false)
returns jsonb language sql stable security definer set search_path = '' as $$
  with page as (
    select mmsi, checked_utc, checked_revision < revision as new_evidence_pending,
           lease_until > clock_timestamp() as checking, last_error, retry_after, result
    from argus.vessel_history_checks
    where mmsi > coalesce(p_after, '')
      and (not p_only_leads or result->>'review_required' = 'true')
    order by mmsi limit greatest(1, least(coalesce(p_limit, 100), 100))
  )
  select jsonb_build_object(
    'vessels', coalesce((select jsonb_agg(to_jsonb(p) order by p.mmsi) from page p), '[]'),
    'next_after', case when exists(select 1 from argus.vessel_history_checks
      where mmsi > (select max(mmsi) from page)
        and (not p_only_leads or result->>'review_required' = 'true')) then (select max(mmsi) from page) end,
    'summary', (select jsonb_build_object(
      'total_vessels', count(*), 'never_checked', count(*) filter (where checked_utc is null),
      'checked_vessels', count(*) filter (where checked_utc is not null),
      'new_evidence_pending', count(*) filter (where checked_revision < revision),
      'review_required', count(*) filter (where result->>'review_required' = 'true'),
      'last_sync_utc', (select last_ok_utc from argus.ais_sync_state where id = 1),
      'newest_position_utc', (select max(received_utc) from argus.ais_positions),
      'sync_error', (select case when last_ok_utc is null or last_error_utc > last_ok_utc then last_error end
                     from argus.ais_sync_state where id = 1),
      'complete_regional_census', false) from argus.vessel_history_checks));
$$;

create function public.argus_history_claim(p_rule_version text)
returns jsonb language sql security invoker set search_path = '' as $$ select argus.history_claim(p_rule_version); $$;
create function public.argus_history_page(p_token uuid, p_after timestamptz default null)
returns jsonb language sql security invoker set search_path = '' as $$ select argus.history_page(p_token, p_after); $$;
create function public.argus_history_finish(p_token uuid, p_result jsonb)
returns jsonb language sql security invoker set search_path = '' as $$ select argus.history_finish(p_token, p_result); $$;
create function public.argus_history_release(p_token uuid, p_reason text)
returns jsonb language sql security invoker set search_path = '' as $$ select argus.history_release(p_token, p_reason); $$;
create function public.argus_history_index(p_after text default '', p_limit int default 100, p_only_leads boolean default false)
returns jsonb language sql security invoker set search_path = '' as $$ select argus.history_index(p_after, p_limit, p_only_leads); $$;

revoke all on function argus.mark_history_dirty() from public, anon, authenticated;
revoke all on function argus.history_claim(text), argus.history_page(uuid,timestamptz),
  argus.history_finish(uuid,jsonb), argus.history_release(uuid,text), argus.history_index(text,int,boolean) from public, anon, authenticated;
revoke all on function public.argus_history_claim(text), public.argus_history_page(uuid,timestamptz),
  public.argus_history_finish(uuid,jsonb), public.argus_history_release(uuid,text), public.argus_history_index(text,int,boolean) from public, anon, authenticated;
grant execute on function argus.history_claim(text), argus.history_page(uuid,timestamptz),
  argus.history_finish(uuid,jsonb), argus.history_release(uuid,text), argus.history_index(text,int,boolean) to service_role;
grant execute on function public.argus_history_claim(text), public.argus_history_page(uuid,timestamptz),
  public.argus_history_finish(uuid,jsonb), public.argus_history_release(uuid,text), public.argus_history_index(text,int,boolean) to service_role;
