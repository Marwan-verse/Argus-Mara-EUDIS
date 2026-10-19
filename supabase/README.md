# Optional AIS / satellite history database

The offline application does not require Supabase. Public source contains no project URL or access key. Create and operate your own project; a new database has no historical AIS until your collector has supplied it or you import your own records.

## Install the schema

Use the official Supabase CLI or your reviewed database migration process to apply **all files in `migrations/` in filename order** to a dedicated project. Migrations use Postgres functions plus `pg_cron` and `pg_net`; check extension availability first. Do not point an unreviewed installation at an existing unrelated database.

The initial AIS migration intentionally contains `https://your-ais-collector.example`. Replace that configuration on your own database with your own collector origin:

```sql
update argus.ais_sync_state
set source_url = 'https://your-ais-collector.example'
where id = 1;
```

Use your real HTTPS origin instead of the example. Check `argus_ais_status()` for errors, fresh receipt times and increasing position counts. A successful schema migration alone does not prove collection is working. Keep your collector running with persistent storage; partial polling is not a complete radio AIS archive.

## Connect a trusted workstation or host

Set `ARGUS_SUPABASE_URL=https://your-project.supabase.co` in the process environment, then run:

```bash
python scripts/configure_supabase.py
```

The helper asks for your secret key without echoing it, validates it against the explicit project and saves it in the OS credential store. It records the project in ignored `data/satellite/database.link`, keeping each key with its project. `ARGUS_SUPABASE_KEY_FILE` or a privately supplied `ARGUS_SUPABASE_KEY` are host alternatives. Never place a privileged key in a browser bundle, public repository or distributed client configuration.

The Docker satellite host uses the separately documented ignored host environment file. Set the URL there as well as `ARGUS_SUPABASE_LINK=1` and its private key.

## Archive access is private by default

The final `restrict_public_archive_reads` migration revokes the historic anonymous/authenticated archive-read grants and leaves them available to `service_role`. The original team-only read-key design is no longer a public distribution default. The private `argus` tables retain RLS and their existing access boundaries.

For an intentionally public/read-only deployment, an administrator must explicitly review what those functions expose before granting them to `anon`. A locally configured `ARGUS_SUPABASE_PUBLISHABLE_KEY` plus `ARGUS_SUPABASE_URL` can then read the four allowlisted functions; this does not grant writes. Do not grant anonymous access to a private archive merely to make a client connect.

## Existing deployments before public GitHub release

Apply the final restriction migration on every relevant old project and revoke the previously bundled publishable key in its owning project's dashboard. Revocation is necessary because the old key remains recoverable in Git history. The current connected tooling account cannot access that owning project; no remote revocation is claimed by this repository change.

Verify access as an administrator without exposing data:

```sql
select p.oid::regprocedure::text as function,
       has_function_privilege('anon', p.oid, 'execute') as anon_can_execute,
       has_function_privilege('authenticated', p.oid, 'execute') as authenticated_can_execute
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in ('argus_ais_status', 'argus_ais_rows', 'argus_recent_tracks', 'argus_history_index');
```

Both permission columns must be false for the private archive. Also verify the retired key fails a request to those functions. Keep the evidence of this check private; do not paste keys or observation payloads into an issue.

## Retention and limits

History is retained without automatic deletion by the preservation migration. Monitor storage and backup/restore behavior for your own plan. Original receipt times, stream identifiers, source-quality exclusions and unknown image-time coverage must remain visible. Current positions cannot identify a historical image contact without contemporaneous evidence.
