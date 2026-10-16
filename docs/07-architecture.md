# 7. Codebase architecture and team contracts

## Investigation lab (D110, 16 October)

`desktop_investigation.py` adds four local tabs: source timeline, pairwise
encounter review, an editable fictional branch, and evaluation against a
proximity baseline. `argus/investigation.py` preserves evidence provenance and
computes review-only pair patterns. `argus/scenario_lab.py` uses existing Brain
and responder calculations on observed branch fixes; hidden simulated motion
cannot enter those calculations. `argus/evaluation.py` records episode counts,
signed warning lead and case metrics against authored exercise labels. None
changes shared demo contracts or triggers operational action. See
[the lab guide](19-investigation-lab.md) for thresholds, limitations and validation.

## Private SOC companion (D52, 13 October)

An explicitly requested private companion adds account authorization and
E2EE rooms for 2–16 participants (D53), independently of the offline demo and public live AIS.
`argus/collab_store.py` owns SQLite accounts/RBAC; `argus/collab_server.py` relays
ciphertext; `argus/collab_crypto.py` and `collab_client.py` run on endpoints.
`desktop_soc.py` integrates native login, session creation/joining, communication
and administration. `soc/` provides an isolated Docker deployment behind HTTPS.
See [SOC security boundaries and handoff](../soc/README.md). Existing map pings
are shared annotations; no user-created threat alert or remote response is added.
Both demo JSON contracts remain unchanged. Private browser administration (D89)
serves fixed assets under `/admin/` through the SOC relay, with cookie sessions and
same-origin CSRF checks in `argus/admin_web.py`. It reuses the account/group
handlers and store; the static offline demo remains independent.
See [the browser panel guide](../soc/ADMIN-PANEL.md).

**Manual vessel reports (D67, 15 October):** `argus/vessel_reports.py` validates
structured analyst reports and groups an in-memory inbox by vessel identity and
provenance. `desktop_reports.py` provides the mandatory category/reason form and
review window; `desktop_alerts.py` shows reported vessels separately from replay
severity groups. `report` messages use the existing SOC E2EE path and
`contact.share` permission, with the authenticated sender name attached by the
receiving client. Reports do not enter Brain scoring, response dispatch or either
demo JSON file. They survive replay reset but remain session-local in memory.
This extends the annotation-only workflow described above.

D111 expands the native report narrative to 4,000 characters and prepopulates
eight editable sections from the local evidence pack, without a network or AI
call. Facts retain provenance, unknowns remain explicit and review stays pending.
Prefill respects the existing encrypted message budget; report keys and session
storage are unchanged. Analysts can replace the full narrative before submission.

*Proposed implementation structure, 7 October 2026. This follows decisions D13–D15 and D22. It does not change the seven-beat demo.*

## Browser frontend (D37, 9 October 2026)

The native Incidents panel has a saved **Show fictional / simulated alerts**
switch (D75). Turning it off hides replay incident cards, severity counts and
their map markers, while keeping analyst vessel reports visible. Live AIS supplies
map observations only: Brain's incident board still scores fictional replay tracks,
and Coast Watch comparison leads are shown separately in Incidents (D76). An empty
live incident queue is not a claim that received traffic is safe. `satellite_compare.py`
classifies every eligible image-time AIS vessel; saved review comparisons are
reconciled on the satellite worker without paid calls. The authenticated comparison
index feeds Incidents independently of its fictional replay filter.

D77 adds `argus/fleet_history.py` and a prepared Supabase migration for a private
per-MMSI history queue. SQL owns revision snapshots and leases; Python owns motion
detection. Atomic page checkpoints and a locally cached directory feed the native
Fleet history tab and a separate Incidents review section. Automatic free checks
are independent of paid image review, with the existing evidence permission on
the optional SOC endpoint. The hosted migration remains pending correct database
access; see [scope, recovery and verification](18-fleet-history.md).

D78 adds `argus/satellite_adaptive.py`: up to four overlapping detail windows on
crowded images, durable per-window paid-attempt state, original-grid coordinates
and local coverage gates. Partial windows never become empty-image evidence.
The map/list index retains all stored observations, with details loaded on click.
The Python live client preserves optional AIS length, and versioned capture CSVs
retain its supplied receipt time without altering older headers. Sensor accuracy
and legacy SQL-comparison alignment remain separate outstanding validation work.

All browser interactions use Svelte 5 components under `ui/src/`: offline replay,
live dashboard, local evidence review and recorder map preview. The esbuild script
compiles committed, self-contained bundles; Node 22+ is required for development,
not presentation or deployment. Run `npm ci`, `npm run check`, `npm run build`,
`npm test` and `npm run test:browser`. See `ui/README.md` for generated paths,
Chromium requirements and the offline export contract. The Python native companion
and data/detection/countdown modules keep their existing responsibilities.

## The shortest path to the working demo

The project has two runtime halves. Python prepares a scenario and computes alerts. A browser presents both files and records a human's simulated decision. The interface should be served as static files from the repository root for local development; a local static server is not an application backend. Once assets are downloaded, the demo must run with external Wi-Fi disabled.

**Native companion (D30, 8 October):** `run_gui.py` also reads the two committed JSON
files and opens a Tkinter application window. It keeps the AIS gap, separate radar
contact, countdown, response comparison, uncertainty and human approval. It starts no
web server and adds no dependency to the file contract. `RUN-GUI-WINDOWS.bat` is a
double-click launcher; the browser interface remains available for the original stage
workflow. The native shell uses CustomTkinter (D33) for light cards and controls; its
package is installed in an ignored virtual environment from the root `requirements.txt`.
The browser interface and the JSON contract do not depend on that package.

*Map navigation (D31, D34, 8 October):* drag to pan; use the wheel or map controls to zoom.
The local Natural Earth coastline covers the world and is the offline default. The
optional NASA Blue Marble imagery requests only visible tiles and caches them with
HTTP expiry/validators; missing imagery falls back to the local global map. Online
tiles disclose the visible area to NASA Earthdata and are display context only.
Offline layers show NGA World Port Index point locations and a historical,
stylized TeleGeography cable map snapshot under CC BY-NC-SA 3.0. The latter is
not surveyed geometry and cannot feed alerts or countdowns. The right-side plus opens
contacts, timeline, response, layer, note and evidence tabs inside the right pane. The
bottom plus opens the same panels in a lower workspace, alongside map tools. Both
splitters can be resized; drag tabs to reorder them or move them between panes, and
right-click a tab to move or close it. The Situation tab stays in the right pane.
Notes are session-local.

*Reference navigation (D35):* the native app adds searchable port and cable
directories to either dock. Port filters combine name/WPI search, country code
and an optional current-view restriction. Map markers select reference ports;
clusters zoom in. Selected historical cable routes can be framed across the date
line. `argus/map_view.py` holds display-only search and geographic extent helpers;
it is independent of Brain's countdown and changes neither shared JSON file.

*Live weather (D36, 9 October):* the map bar's "Live weather" switch, off by default,
requests the Met Éireann point forecast (`argus/weather.py`) at the exercise cable every
30 minutes. Its "Rain and cloud" layer samples up to 100 grid points over the visible view
and shades model-forecast cloud and rain (not radar) for now or up to 12 hours ahead; its "Wind"
layer draws downwind arrows coloured by speed. Map-bar "Rain" and "Wind" switches toggle each layer.
It shows current real weather, not the replay's, and is display-only: alerts,
countdowns, ETAs and both JSON files are unchanged.

*Magnetics (D91, 16 October):* `desktop_magnetics.py` is a rail panel with two parts.
Its opt-in storm feed (`argus/geomag.py`: NOAA SWPC 1-minute Kp with a rolling maximum
over the current and previous 3-hour interval, and Valentia 1-minute H from INTERMAGNET via
BGS GIN as |dH/dt|) shows tiers 0–3 in a header chip and caches the last status in
`data/magnetics/`. Its seabed search planner (`argus/survey_plan.py`) builds a corridor
from a track and a cable path and estimates magnetometer survey effort. Both are
display-only: no detector reads them, and alerts, countdowns, ETAs and both JSON files are
unchanged.

*Dark-vessel prediction (D51, 13 October):* the "Dark prediction" map layer, on by
default, replaces the withdrawn exercise marker during its AIS gap with a labelled
likely cone, reachable circle, best-guess position and a worst-case line and countdown
to the anchor-reachable section; when AIS returns, it shows the reappearance check.
The same areas appear for a selected live contact whose last fix is older than the
feed's stale threshold, up to 3 h, without any cable countdown. `argus/prediction.py`
computes; `desktop_prediction.py` draws. Alerts, ETAs and both JSON files are unchanged.

```text
recorder/       live AIS capture; independent from the stage demo
data/           ignored local recordings and downloaded datasets
demo/           committed scenario.json and alerts.json; the v1 contract
argus/          Python contract checks, Space analysis, Brain rules and countdown
space/          Space sidecar examples, provenance and handoff
ui/             Interface-owned static HTML, CSS, JS, map and fictional evidence
scripts/        cross-workstream checks and local development helpers
skills/         downloadable teammate instructions
docs/           research, decisions, plan and build guidance
```

**Languages:** Python 3 for ingest, geometry, rules, ETAs and contract generation. Browser JavaScript, HTML and CSS for replay. JSON is the boundary. The native desktop companion has one direct UI dependency in the root `requirements.txt`; the file contracts and browser demo remain independent. The recorder's `websockets` and `pyarrow` dependencies stay in `recorder/requirements.txt`; they do not become interface requirements.

## Ownership and flow

| Workstream | Writes | Reads | Integration rule |
|---|---|---|---|
| Data | `demo/scenario.json`, later local geometry imports | public datasets | Preserve the v1 keys and coordinate order |
| Brain | `demo/alerts.json`, `argus/` | scenario | Return reasons and seconds-based ETAs; no interface imports |
| Space | `argus/space.py`, `argus/ingest/`, `space/` sidecars | SAR and AIS material | Mark a source and confidence; do not treat unmatched as proven malicious |
| Interface | `ui/` | both JSON files | Show provenance and operator approval; no hidden live dependency |
| Story/integration | scenario narrative, demo script | complete replay | Run contract check and offline dry run |

The recorder and Space sidecar can continue independently. Do not make the demo wait for their network feeds. A downloaded or live dataset only replaces a simulated part after the complete scenario still plays.

## Frozen v1 details

- `t0_utc` is an ISO 8601 UTC timestamp. `t` is seconds after it, not an absolute timestamp.
- Scenario paths are `[latitude, longitude]`. This is the **opposite** of GeoJSON's `[longitude, latitude]`; convert explicitly at a library boundary.
- `sog_kn` and asset `speed_kn` are knots; `distance_km` is kilometres; `eta_*_s` and option `eta_s` are seconds. `replay_speed` is scenario seconds per wall-clock second.
- AIS gaps remain gaps in a track. The interface should hide the AIS marker during a gap and draw a radar detection separately, rather than interpolate a visible AIS position through it.
- The accepted provenance values are `real`, `reconstructed`, `simulated`, `fictional` and `assumption`. The scenario's top-level label and each object label are already present. An alert is derived from the labelled scenario; show the underlying labels with its evidence.
- `in_time` means an option's ETA is no later than `eta_earliest_s`. `eta_s: null` means unavailable or out of range.
- `evidence_url` is relative to `/ui/` in the stage replay. The fictional alert links to a committed, generated page under `ui/evidence/`; the UI checks its availability. Historical and downloaded evidence stays in ignored `data/`.

Run `python scripts/check_contracts.py` after editing either JSON file. The checker tests structure and cross-file references; it cannot establish that an estimate is scientifically accurate.

## Change protocol

Add optional fields without breaking readers. To rename, remove or reinterpret an existing field, first write a decision in `DECISIONS.md`, update `demo/README.md`, update the checker and generator, then change the writers and readers together. Keep a known-good copy of both JSON files for the offline demo. Do not silently replace the simulated route with an unsourced or sensitive route.

## Next code tasks, by dependency

*Interface update, 8 October 2026 (D27):* `ui/index.html`, `styles.css`, `app.mjs`
and `replay.mjs` now implement the seven-beat offline console. Run
`python scripts/serve_demo.py` and open `/ui/`. Natural Earth display geometry is
bundled locally. Evidence review and HTML export work. Operator decisions are
simulated, session-local, and clear when the replay is sought or restarted. D29
adds a rule-generated Brain alert and a bundled fictional Space review page.

1. Interface owns a local coastline asset and a static replay that handles the AIS gap, radar contact, alert and approval.
2. Brain's projection helper now lives in `argus/countdown.py`; `argus/brain.py` writes the same `alerts.json` shape. Its four-cue score is rule completeness, not a threat probability.
3. Data replaces the illustrative cable and depth only after source, licence and provenance are recorded.
4. Space's two public examples remain a separate story from the fictional tanker. The Interface can add one reviewed example after its observation time, source and matching uncertainty are clear in the evidence.

The larger module list in `05-build-guide.md` is a post-demo option. Avoid creating empty folders for those future components.

## Space evidence addition — 8 October 2026

Space writes an optional sidecar and local evidence pack with `argus.evidence`; the two shared
demo files retain their existing fields and meaning. Browser templates live in `ui/space/`,
normalized AIS ingest in `argus/ingest/ais.py`, and real/downloaded material in ignored
`data/`. The fictional stage pack is generated into `ui/evidence/` for offline distribution.
See [Space's additive fields and commands](../space/README.md#run-offline).

The sidecar preserves provider associations separately from local ones, records association
method and timing assumptions, and exposes missing-evidence reasons. Exported `evidence_url`
paths resolve against the pack root. Brain chooses the generated fictional page for its alert;
Interface links that page from the stage replay after a local availability check.
Historical packs and fictional packs are separate. Real/reconstructed contacts
cannot locally match fictional/simulated AIS; sourced dimensions expire after an assumed
24 hours and cannot come from future observations. A page-local operator acknowledgement
persists only until reload and never triggers a response.

## Optional native satellite workspace — 15 October 2026 (D70)

`desktop_satellite.py` adds catalogue search, bounded georeferenced image crops,
historical AIS and manual TensorX review. `argus/satellite*.py` keeps acquisition
geometry, archive joins, model validation, cost reservations and file caches apart
from the stage contracts and Brain rules. Data lives in ignored `data/` locally
or the private SOC's existing persistent volume. `argus/satellite_server.py` adds
authenticated intelligence endpoints to that companion only; it creates no
backend for the offline browser demo. The optional Docker image and Compose
override reuse the existing account relay and forwarded-port transport.

AI suggestions are assumptions and unreviewed; time/space associations never
confirm identity or intent. No AI call runs from map redraws or UI status refresh.
See [setup, evidence limits and open-source next steps](16-satellite-ai.md).

D72 adds `argus/satellite_scan.py`: a persisted, opt-in coastal image queue with
a single worker lease, 30-minute public catalogue discovery, quality-first optical
triage (`satellite_screen.py`) and a separate 60-second AIS snapshot recorder
(`satellite_capture.py`). The reproducible public-domain `argus/coastal_grid.json`
is included in the optional Docker image. Queue state and compact status are
atomic files under `data/satellite/scan/`; captures are dated private CSVs under
the archive directory. AI failure/budget limits pause paid processing while AIS
capture continues. The existing persistent ledger and exclusive AI lock remain
authoritative. There is no backend added to the offline browser demo.

`SatelliteWorkspace.contacts()` supplies a bounded map index; opening a contact
rejoins actual archive evidence and current captured AIS locally, without AI
tokens. A selected identity remains provisional. Stream epochs cannot be bridged,
undated static fields cannot be backdated, and invalid motion fails matching.
SOC read access requires `evidence.share`; starting/stopping shared cycles also
requires administrator status. A local scan runs with the desktop, a shared scan
with the existing private SOC host. Neither installs an OS scheduled task.

## Optional team database — 15 October 2026 (D74)

D95 (16 October) deploys the complete schema to the user-selected new project
`zibmytppznydhlggzlaq` in marwan-verse's projects, Ireland. The original project
is unchanged. `ais_observations` additionally preserves complete received ship
objects, and a forward migration disables automatic AIS history deletion.
`scripts/export_ship_history_sql.py` prepares private idempotent import batches
for the existing local capture archive; original CSV fields and source hashes
remain stored alongside normalized query fields. The history worker's 14-day
analysis window is separate from archive retention. See the current deployment
in `supabase/README.md`; desktop/host secrets remain required for their access.

`supabase/migrations/` holds the schema of the Supabase project `argus-mara`.
Inside the database, `pg_cron` and `pg_net` copy the Railway AIS feed every 30
seconds into the private `argus` schema; nothing on Railway changed.
`argus/supabase_ais.py` is the only client: it reads acquisition-time AIS rows in
the recorder CSV shape, so `argus.satellite_ais.historical_ais` applies the same
D70 rules, and it saves Coast Watch scenes, AI contacts and clear-water areas,
then asks `argus.compare_scene` for both comparison directions. It acts only in a
workspace with `database.link` (or `ARGUS_SUPABASE_LINK=1` on a host) and a secret
key from the credential store, so tests and the offline demo never touch it.
See [the database guide](../supabase/README.md).

D80: `argus/satellite_disposition.py` stores immutable, reasoned analyst outcomes
separately under the private satellite workspace. `desktop_evidence_review.py`
submits a local outcome or authenticated `POST /v1/satellite/dispositions` with
`evidence.share`; the host supplies actor identity. Acquisition evidence hashes
reopen changed leads. Notes do not replicate via Supabase or change computed
findings, scene JSON contracts, identity confidence or operational approval.
