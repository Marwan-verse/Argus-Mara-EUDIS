# 7. Codebase architecture and team contracts

## Private SOC companion (D52, 13 October)

An explicitly requested private companion adds account authorization and
E2EE rooms for 2–16 participants (D53), independently of the offline demo and public live AIS.
`argus/collab_store.py` owns SQLite accounts/RBAC; `argus/collab_server.py` relays
ciphertext; `argus/collab_crypto.py` and `collab_client.py` run on endpoints.
`desktop_soc.py` integrates native login, session creation/joining, communication
and administration. `soc/` provides an isolated Docker deployment behind HTTPS.
See [SOC security boundaries and handoff](../soc/README.md). Existing map pings
are shared annotations; no user-created threat alert or remote response is added.
Both demo JSON contracts remain unchanged. The browser frontend is unchanged.

*Proposed implementation structure, 7 October 2026. This follows decisions D13–D15 and D22. It does not change the seven-beat demo.*

## Browser frontend (D37, 9 October 2026)

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
