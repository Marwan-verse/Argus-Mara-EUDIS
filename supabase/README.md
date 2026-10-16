# Team database (Supabase)

An optional shared database for AIS history and satellite-versus-AIS comparison
(decision D74). The offline exercise does not use it.

## Current deployment — 16 October 2026 (D89)

The active project is **argus-mara** in **marwan-verse's projects**, region
**eu-west-1 (Ireland)**, project ID `zibmytppznydhlggzlaq`:
`https://zibmytppznydhlggzlaq.supabase.co`.
[Open the project](https://supabase.com/dashboard/project/zibmytppznydhlggzlaq).
The previous `lcpgnzvkntqdhejrsgpa` project was inaccessible to the connected
account and was not modified. The Python client's default now uses the new
project; an explicit `ARGUS_SUPABASE_URL` still overrides it.

All six existing schema migrations and
`20261016130559_preserve_ship_history.sql` plus
`20261016132518_align_tracking_quality.sql` are deployed on the new project.
The subsequent `20261016133900_temporal_tracking_support.sql` adds endpoint
reachability to both comparison directions. `20261016135525_vision_image_usability.sql`
withholds image-based leads when the review declares the image unusable.
`20261016140530_optical_pixel_support.sql` preserves optical localization metadata
and withholds matches/dark-contact leads from unsupported or unclassified features.
All are deployed screening assumptions for review, not calibrated tracking accuracy.
The initial satellite migration was applied as `argus_satellite_compare_keep_history`,
with its retention function replaced by a no-op and retention cron omitted;
the forward preservation migration records that final policy for future installs.
**No AIS history is automatically deleted.** This supersedes the original
14-day deletion policy below. Storage still grows and must be monitored; the
existing motion-review worker checks a rolling 14-day window, while older
received observations remain stored.

`argus.ais_observations` retains complete received ship objects, including
fields not normalized into the position/static tables, metadata-only updates
and corrections. SHA-256 keys deduplicate exact repeated objects within a
stream. These are the Railway feed's partial snapshots/updates, not every
original AIS radio message. Extra declarations are preserved as supplied,
not validated identities. The private table has RLS and no public access.

The 11,989 real rows in this computer's `data/ais/capture/` recordings from
8–15 October were imported using `scripts/export_ship_history_sql.py`.
Imports retain original CSV fields and the source file's SHA-256 in
`ais_observations`, plus queryable positions and supported static declarations.
Import export time is `source_generated_utc`; original receipt times stay in
the payload and normalized tables. Generated SQL contains private observation
data and stays under ignored `data/ship-history-import/`. Batches are atomic
and idempotent. No older continuous voyage history is inferred from the
collector's previously retained last fixes.

The cloud collector runs every 30 seconds without the desktop. Desktop
history checks still need **Connect team database** with a secret key belonging
to this new project, entered only in the masked native prompt. The connection
marker `data/satellite/database.link` is a local setting, not the database.
No local key was available to connect this computer automatically. SOC hosts
likewise need the new project's URL/key in their existing private configuration.

D91 makes complete raw correction objects part of acquisition-time source-quality
checks. Conflicting positions and competing stream epochs appear in the private
AIS RPC's `excluded_vessels`; the Python handoff and direct SQL comparison both
withhold unsupported unmatched-image leads. SQL name/length lookups remain
within the selected epoch. The initial hosted backlog of 2,043 ships was checked
and saved through the existing lease APIs and Python rules at the 16 October
13:33:30 UTC sync checkpoint. This was a one-time connector run; automatic future
Python checks still need the configured desktop/SOC worker.

Validation: hosted status and archive counts, active sync cron, absence of a
retention cron, private-schema/RPC grants, RLS and the Supabase security advisor;
`node tests/test_ship_history_db.mjs` verifies no deletion, complete objects,
corrections, duplicate imports and SQL escaping in isolated PostgreSQL.

## Original deployment record — 15 October 2026

The following records describe the previous project and its then-pending work;
the deployment above supersedes them.

**D77 extension:** the new
`20261015201441_vessel_history_queue.sql` migration adds whole-fleet history
revision/lease tracking and five service-role APIs for the Python worker. It has
been tested in isolated PostgreSQL but **has not been applied to the hosted
project**; the current connector account cannot access Argus Mara. See
[fleet-history setup and verification](../docs/18-fleet-history.md). The original
four-function deployment described below remains the recorded hosted state.

**D79 comparison hardening:**
`20261015221628_align_satellite_ais_comparison.sql` adds verified-image manifests,
100 m clear-footprint flags, epoch/motion/24-hour static gates, and competing-contact
protection. Apply after D77. Legacy scenes cannot generate leads until republished
with a current verified review; obsolete contacts/visibility are replaced atomically.
`tests/test_satellite_compare_db.mjs` executes these migrations in isolated
PostgreSQL/PostGIS. This migration has not been applied to the hosted project.

- **Project:** `argus-mara` in the "Argus Mara" organisation, region eu-west-1
  (Ireland), free plan with a 500 MB database. API URL:
  `https://lcpgnzvkntqdhejrsgpa.supabase.co`.
- **AIS comes in by itself.** Every 30 seconds `pg_cron` runs
  `argus.ais_sync_tick()`. It asks the team's Railway feed for changes
  (`/api/v1/updates`, or the full `/api/v1/vessels` snapshot after a restart)
  through `pg_net`, then stores new positions in `argus.ais_positions` and changed
  ship particulars in `argus.ais_static`. No laptop has to stay on, and Railway was
  not changed. Each run is logged in `argus.ais_sync_runs`.
- **Satellite side:** `argus.sat_scenes` (one image or crop with its acquisition
  UTC), `argus.sat_contacts` (objects found on it) and `argus.sat_observed_areas`
  (where the sea was actually visible). `argus.compare_scene(id)` compares both ways
  at acquisition time: contacts with no AIS within 300 m are possible dark ships;
  ships of at least 50 m that AIS places in a visible part of the image, with
  nothing within 1 km, are possible false AIS positions. Both are leads for review.

## Connect a computer

1. Supabase dashboard → project `argus-mara` → Project Settings → API Keys →
   Secret keys: create or copy a secret key (`sb_secret_...`). It can read and
   write the whole database: never paste it into chat, Git or a command line.
2. Run `python scripts/configure_supabase.py` and paste the key when asked. It is
   checked with one free call, saved in the system credential store, and
   `data/satellite/database.link` is created. Delete that file to unlink.
3. Check: `python -m argus.supabase_ais status`.

From then on Coast Watch takes acquisition-time AIS from the database (falling back
to local files) and saves every new review there. Older reviews:
`python -m argus.supabase_ais push-reviews`. One scene:
`python -m argus.supabase_ais compare <scene-id>`.

Docker satellite host: add `ARGUS_SUPABASE_LINK=1` and `ARGUS_SUPABASE_KEY=...` to
the ignored `data/satellite-host/tensorx.env` (`scripts/configure_supabase.py --host`
checks the key and prints the lines), then rebuild the host.

## Security

Tables live in the private `argus` schema, which the REST API does not serve, with
row level security on. The entry points are the explicitly granted `public.argus_*` functions
that only the secret key may call; the publishable key gets HTTP 401 (checked
15 October 2026).

## Limits

- AIS is only what the Railway collector receives from AISstream: partial coverage,
  and `received_utc` is the collector's receipt time, not the AIS message time.
- Cloud collection starts on 16 October, supplemented by the 11,989 imported
  real capture rows from 8�15 October. Older images still need acquisition-day AIS.
- Received history is retained without automatic deletion (D89). Watch
  `database_mb` in `status` against the 500 MB free limit.
- A free project can be paused after a period without use; check it before an event.

The schema is in `migrations/`. Deployment status for the active project is recorded above. Historical setup
notes for the inaccessible original project do not describe the active project.
