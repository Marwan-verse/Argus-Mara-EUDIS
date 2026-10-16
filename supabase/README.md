# Team database (Supabase)

An optional shared database for AIS history and satellite-versus-AIS comparison
(decision D74). The offline exercise does not use it.

**Pending D77 extension:** the new
`20261015201441_vessel_history_queue.sql` migration adds whole-fleet history
revision/lease tracking and five service-role APIs for the Python worker. It has
been tested in isolated PostgreSQL but **has not been applied to the hosted
project**; the current connector account cannot access Argus Mara. See
[fleet-history setup and verification](../docs/18-fleet-history.md). The original
four-function deployment described below remains the recorded hosted state.

**Pending D79 comparison hardening:**
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
row level security on. The only entry points are four `public.argus_*` functions
that only the secret key may call; the publishable key gets HTTP 401 (checked
15 October 2026).

## Limits

- AIS is only what the Railway collector receives from AISstream: partial coverage,
  and `received_utc` is the collector's receipt time, not the AIS message time.
- History starts on 15 October 2026 at 17:46 UTC, plus the last fix of every ship
  the collector had seen since 8 October. Older images have no AIS here.
- Positions are kept 14 days, plus two hours around every saved scene. Watch
  `database_mb` in `status` against the 500 MB free limit.
- A free project can be paused after a period without use; check it before an event.

The schema is in `migrations/`. The original D74 migrations were recorded as applied
on 15 October 2026; the D77 and D79 migrations above remain pending.
