# Fleet-wide AIS history review

D77 adds a history queue for **every MMSI recorded in the team database**, including
vessels outside reviewed satellite images. This is a private companion feature;
the offline exercise and both demo JSON files remain unchanged.

## Deployment status and setup

The new migration is **prepared and locally tested, not applied to the hosted
Argus Mara database**. The connected Supabase account did not list that project;
only an unrelated inactive project was accessible. This checkout also had no
configured database key or link file. No other hosted project was changed.

1. With the correct Argus Mara database account, apply
   `supabase/migrations/20261015201441_vessel_history_queue.sql` once, after the
   existing four migrations. It adds private queue state and five service-role
   RPCs; the migration contains no credentials or data-source changes.
2. Update the native application and optional SOC satellite host together.
3. In a local native workspace, open **Satellite analysis → Fleet history →
   Connect team database**. Enter the secret in the masked native dialog, not in
   chat. It is verified with the existing status RPC, then saved in the OS
   credential store. `scripts/configure_supabase.py` remains available.
4. For a shared host use the existing ignored host environment configuration
   described in `supabase/README.md`. Only `evidence.share` users can read history
   through the SOC. Native clients use the host's cache and do not receive its key.
5. Check the Fleet history totals, worker message and inventory timestamp. Do
   not claim the whole fleet has been checked until `never_checked` is zero,
   the inventory is complete, and outstanding new-evidence checks are understood.

Linking a key does not install the migration. An HTTP 404 history status means
the new API is unavailable; confirm the project and migration. A database that
has only recent reception cannot establish a ship's older voyage history.

## What gets checked

`argus/fleet_history.py` uses Python motion rules already present in
`argus/detectors/ais_spoofing.py`: position jumps, repeated two-place patterns and
sustained disagreement between received movement and reported speed. It does not
apply today's vessel type to older observations or use display coastlines as
surveyed evidence. One isolated outlier remains an isolated cue. A reception gap
is counted as a coverage fact, never scored as deliberate AIS shutdown.

The initial scope is the **last 14 days of available received positions** for each
vessel. It is not a complete lifetime or voyage history. Every check records the
first/last retained fix, row count, stream epochs, gaps, findings and rule version.
Separate epochs and evidence provenance are never bridged. A vessel with too
little usable evidence is `insufficient_history`, not clean. `no_rule_cues` is not
a safety clearance. Findings are derived **assumptions** on real/reconstructed
received data; identity and intent remain unconfirmed.

The native **Fleet history** tab lists all cached recorded vessels in pages of
50, with checked/unchecked/checking/new-evidence states. Select one for dated
findings and coverage. The review filter exposes all retained motion-review
histories. Incidents shows the first page of these histories independently of
fictional alerts; **Open all vessel histories** reaches subsequent pages.

## Queue and recovery

The database creates a queue row for existing MMSIs and marks a new revision only
when a genuine position or static record is inserted. Duplicate collector packets
do not make checked histories dirty again. A check claims a five-minute renewable
lease on a fixed revision. Late imports with old timestamps belong to a later
revision and cannot silently enter an in-progress snapshot.

Python fetches ordered pages of 1,000 fixes. Each page is atomically saved before
its cursor advances. Interrupted downloads resume; a lost completion response
retries the exact saved result. The database verifies the expected snapshot row
count before accepting completion. Retention changes and incomplete results leave
the vessel unchecked. Invalid/oversized work is held for five minutes with a visible
reason, and fresh evidence makes it eligible again. The current local capacity is
500,000 rows for one vessel; exceeding it is explicit and never a complete check.

The private queue table uses RLS and is not exposed through REST. Public wrappers
run as invoker and can only be executed by `service_role`; internal queue functions
also grant no public/anon/authenticated execution. The rule version is pinned in
the database so mismatched client versions cannot repeatedly overwrite each
other's meanings. Updating rules requires updating the migration and clients.

A free worker progresses independently of image AI and UI refreshes. It paces
active work and backs off when idle or unavailable. An OS file lock protects local
checkpoints, and database leases coordinate separate hosts. The worker uses no AI
credits and dispatches no response. `ARGUS_SATELLITE_AUTOSTART=0` suppresses automatic
startup during maintenance. Closing the application/host requests worker stop;
an in-flight free request can finish and the lease preserves unfinished work.

The local inventory cache uses keyset pages. It marks initial or changing
inventories partial and detects new MMSIs inserted before a pagination cursor.
Directory pages are refreshed separately from checked results; they carry source
timestamps rather than claiming immediate global consistency.

Incidents and the fleet view distinguish database synchronization from actual
position reception. They show time since the last successful sync and the newest
stored fix separately; a successful poll does not make old AIS fresh. Five minutes
for sync and fifteen minutes for the newest fix are screening assumptions. Missing,
invalid or future timestamps remain explicit. Freshness ages even if the returned
cache contents have not changed. Neither clock proves complete regional coverage.

## Validation

The Python tests exercise actual motion rules, epoch separation, crash recovery,
lost responses, OS locking, pagination and worker shutdown. The native test opens
the real Fleet history widgets, selects evidence, pages the directory and opens
history from Incidents with fictional alerts hidden. API tests check login,
`evidence.share` and input bounds.

An isolated PostgreSQL engine executes the actual migration and tests backfill,
dirty revisions, duplicate packets, leases, late imports, page retries, incomplete
snapshot rejection, retention changes, result types and role restrictions:

```powershell
npm.cmd install --prefix data/sql-test-runtime --no-audit --no-fund @electric-sql/pglite@0.5.10
node tests/test_fleet_history_db.mjs
$env:PYTHONPATH = 'tests'
.venv/Scripts/python.exe -m unittest test_fleet_history test_fleet_history_desktop
```

Node is used only for this development test. The product worker is Python. This
isolated test uses minimal prior-table fixtures; it does not prove PostGIS/AIS
ingestion integration, true multi-connection lock contention, hosted throughput
or detector accuracy on real traffic. Those checks remain pending on the correct
hosted project. Full 14-day rechecks after new evidence are correct but may be
expensive; measure throughput before claiming timely fleet-wide coverage.
