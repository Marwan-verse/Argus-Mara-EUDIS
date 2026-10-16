# Live review goal: acceptance evidence and remaining work

**16 October update:** D95 deployed the complete database schema to
`zibmytppznydhlggzlaq`, imported 11,989 local capture rows and verified automatic
collection. The older project-access blockers below are historical. Native/host
workers still need the new project's private key. D96's ongoing tracking,
dark-contact, AI and Brain audit is in [the improvement record](20-tracking-brain-improvements.md);
neither database deployment nor pipeline regression tests prove detector accuracy.

The requested outcome remains: check every boat's stored history once if unchecked,
make real evidence feed Incidents, expand and improve satellite review, list all
boats, join images to AIS at the same time/location, and check AIS positions not
detected in genuinely observable imagery. Continue improving until the user stops
the goal. This file tracks progress, not a claim that the whole goal is complete.

| Requirement | Current evidence | Remaining acceptance work |
|---|---|---|
| Every boat's stored history checked and remembered | D77 migration, resumable Python worker, database revision/lease watermarks, paginated fleet directory and motion findings are implemented and tested locally | Apply the migration to the correct hosted project; verify the whole backlog, update latency, multi-client locks and real-data outcomes. A local implementation is not evidence that the hosted fleet has been checked. |
| Accurate evidence in Incidents | Separate paginated satellite/AIS lead section, visible with fictional alerts hidden; image evidence opens on click | D80 adds saved reasoned analyst outcomes with changed-evidence reopening and authenticated host attribution. Verify on the configured shared host with genuine contemporaneous AIS; fleet finding dispositions remain outstanding. |
| More area | Reproducible 40 km coastal belt: 2,278 8 km cells; four-coast rotation retained | Verify discovery on the updated shared host and observe actual coverage; the EEZ is not covered. |
| More accurate AI | D78 adds bounded overlapping detail windows, acquisition/grid-preserving remapping, held-window recovery and per-footprint coverage gates; synthetic pipeline tests pass | Empirical precision/recall, duplicate rate and association error on held-out human-reviewed imagery still need measurement. Lossless crops do not increase sensor resolution. |
| Every boat listed | Contact list pages all retained observations without a 5,000-row cutoff; D78 supports four detail windows with explicit cap/duplicate flags. D77 pages recorded MMSIs and history states | A detail window still caps at 24 contacts, and small/obscured boats may be invisible. Verify the directory against the hosted inventory and keep partial inventories explicit. No exhaustive optical census is established. |
| Same-time / same-place AIS matching | Python joins database rows at acquisition UTC with provenance and motion gates; adaptive windows retain the original date/grid | D79 migration now enforces SQL motion/static-age/assignment-conflict and verified-image gates in isolated PostgreSQL/PostGIS tests. Apply it and verify the hosted end-to-end flow; SQL greedy association can still differ from Python global assignment. |
| AIS reports vessel but image does not detect it | Per-vessel clear-water 100 m footprint, size/motion/analysis limits and 1 km contact exclusion; explicit review wording | SCL cannot guarantee all weather/sea/glint effects are absent. Field validation and human review remain essential. |

On this checkout, eight saved reviews were present. The samples inspected were
acquired on 13 October 2026 and contained zero eligible AIS vessels. The database
guide records collection beginning 15 October. Current fixes cannot be backdated
onto these images. This is missing evidence, not evidence of dark vessels or safe
traffic.

A real public-feed check at 21:54 UTC on 15 October returned 1,964 records,
including 1,125 retained declared lengths and 199 fixes received within fifteen
minutes. An isolated private validation capture was compared against all eight
saved 13 October image times: zero eligible contemporaneous vessels were found.
This verifies current reception and a truthful missing-history result, not the
hosted database contents or image-detector accuracy. Details stay in ignored
`data/validation/live_reception.json`; raw data is not committed. The client/capture
length-field loss found during this check is fixed, with a versioned daily CSV
and tests for future declarations, cleared dimensions and metadata-only contacts.

Database access audit: the Supabase connector refused the read query, and both
sandboxed and host-side `argus.supabase_ais status` reported no configured key.
`data/satellite/database.link` was absent. Listing accessible projects confirmed
that the connector account does not list Argus Mara. The D77 migration was
generated with the official CLI and passes isolated PostgreSQL execution tests;
it has not been applied to the hosted database. No production deployment has
been performed. Configure the intended workspace
with `scripts/configure_supabase.py` (secret entered locally, never in chat), or
restore connector access, to verify the live database and apply further schema
work. The goal remains active; this access issue does not block local work.

D79 (`20261015221628_align_satellite_ais_comparison.sql`) also remains unapplied.
It adds explicit image-review manifests, preserves overlap ambiguity, clears obsolete
contacts/visibility when a scene is republished, and withholds leads from legacy
unverified scenes. Its isolated test executes the original satellite migrations and
the new migration with actual PostGIS, including provenance, time/motion gates,
24-hour declarations, competing contacts, clear-footprint flags and role restrictions.
This is SQL regression evidence, not a field detector benchmark or hosted result.

D80 adds file-based analyst dispositions for satellite leads. The native form shows
the most recent outcome/reason, while all immutable events remain under private
`analyst_reviews/` on that workspace (local or shared host). These notes do not
replicate between independent workspaces through Supabase. False-detection,
association-error and reviewed/no-concern outcomes can be hidden from the active
queue without deleting evidence; insufficient-evidence and follow-up remain open.
Any changed acquisition evidence reopens a lead, and corrupt audit data leaves it
visible and unreviewed. Exact manual retries are idempotent, with a short OS lock
and atomic JSON publication. No operational approval or identity confirmation is
created. Detector accuracy and deployment remain unverified.
