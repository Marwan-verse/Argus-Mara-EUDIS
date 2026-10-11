# Anchor Watch: offline operator demo

The static HTML/CSS/JavaScript console reads `demo/scenario.json` and
`demo/alerts.json`. It starts paused at the alert so the assessment is immediately
reviewable. Press Restart, then Play, for the complete seven-beat story. The v1
stage view presents the earliest alert and its vessel; multi-contact navigation
is outside this frozen replay scope. Beat times and reason text come from the
shared files rather than fixed stub phrases.

## Run

From the repository root:

```sh
python scripts/serve_demo.py
```

Open <http://127.0.0.1:8000/ui/>. Windows users can also double-click
`scripts/START-DEMO-WINDOWS.bat`. The committed Svelte bundles need no runtime dependencies, backend or outside
network requests. Node is required only to develop and rebuild browser components. Keep the local static server running while
presenting; opening `index.html` directly is not supported.

## Develop the Svelte frontend

Use Node 22+ from the repository root:

```sh
npm ci
npm run check
npm run build
npm test
npm run test:browser
```

Source components live in `ui/src/`. The build writes self-contained, minified
bundles to `ui/app.mjs`, `ui/live/dashboard.mjs`, `ui/space/evidence.js`, and
`ui/recorder.js`, and refreshes the fictional evidence pack's script checksum.
Commit the source, lockfile and bundles together. Python's static server and
`live/Dockerfile` serve the bundles directly; no CDN or Node service is involved.
The replay and live data helpers remain pure JavaScript for their existing tests.
The live canvas renderer caches its basemap, projected positions and coastline
paths. Svelte owns dashboard controls and a shared live/recorder directory keyed
by MMSI. The directory initially renders 90 rows, offers more in batches of 90,
and searches every contact. Name order and search strings are rebuilt when
vessels change; feed heartbeats retain the same vessel array. The native Tkinter
applications remain Python.

Browser tests need the Python `.venv` dependencies (root and `live/requirements.txt`)
and Chromium. They use `/usr/bin/chromium` when installed; otherwise run
`npx playwright install chromium`. Tests start isolated local services on ports
8001 and 8081 with simulated observations and no provider credentials. The cloud
browser blocks `file://` navigation; export tests load the generated HTML and
its bundled assets directly with all network requests blocked.

The official skills are saved in `skills/svelte-code-writer/` and
`skills/svelte-core-bestpractices/`. `npm run check:skills` runs the official
Svelte autofixer and needs access to `svelte.dev` for its documentation index.
`npm run check` works locally and fails on compiler warnings.

A local two-second playback check at 30× found 4,712 workspace nodes added and
removed by the previous renderer, versus zero additions/removals by Svelte.
This demonstrates reduced DOM churn, not a general loading-speed benchmark;
the bundles include the Svelte runtime and are larger than the original scripts.

The 11 October follow-up measured unnecessary idle work with 5,000 explicitly
simulated contacts in local Chromium:

| Work measured | Before | After |
|---|---:|---:|
| Animation callbacks in one second of paused replay | 53 | 0 |
| Full-directory sorts across 12 feed heartbeats | 12 | 0 |
| Map redraws across those heartbeats | 14 | 0 |

These are work counters, not a general speed benchmark. Search round trips were
46 ms before and 54 ms after in these individual runs, so no search latency
improvement is claimed. Map redraws still occur for new observations, selection,
navigation, resizing and the 30-minute observation-age boundary. Paused or hidden
replays schedule no animation; returning to the tab resumes from its held time.
Closed evidence/response dialogs do not build their review content. Evidence
exports serialize the reviewed Svelte content into a standalone HTML record.

To repeat the measurement, start `python scripts/serve_demo.py --port 8002` and
`.venv/bin/python tests/serve_live_fixture.py` in separate terminals, then run
`npm run measure:frontend`. Chromium must be installed as for browser tests.
`DEMO_URL` and `LIVE_URL` can override the local URLs. The measurement substitutes
its own simulated snapshot and events; it never connects to a provider.

## Controls

- Play/Pause; Restart; 30×, 60× or 120× speed; time slider.
- Buttons 01–07 jump to the seven beats. The last beat opens the opportunity for a
  decision; the operator still has to review and approve explicitly.
- Layer switches control the AIS trail, radar, anchor reach and response assets.
- Zoom controls and Reset chart view operate on the local vector map.
- Evidence review explains provenance and uncertainty. After the alert fires,
  Export saves a self-contained HTML evidence record.
- Review response pauses the replay. The operator chooses one currently timely
  assumed response and explicitly acknowledges uncertainty before approving the
  simulated decision. Approval opens its evidence record.
- Seeking or restarting clears approval. Approval otherwise survives forward
  playback for that run. Decisions are session-local and are lost on reload.
- Playback holds while its browser tab is hidden and resumes when visible.
- Space toggles playback and arrow keys step a minute when a form, button or
  dialog is not focused. Escape closes dialogs.

The approval control stays visible on short desktop screens. The assessment and
left sidebar can scroll independently. The desktop target is at least 900 px wide;
mobile layout remains outside v1 scope.

## Honesty of the replay

Long AIS gaps stay empty, and trails are split across the gap. Radar is a separate,
timestamped simulated observation; it does not become a moving AIS marker. The
countdowns display the supplied alert ETAs minus replay time, and response arrival
durations are compared against the remaining earliest crossing time. This does
not recalculate the vessel's prediction or run a detector in the browser.

Brain generates the alert at the first observed 9.1 kn fix, minute 90. Its four
rule cues are documented in `argus/brain.py`; the score counts cues and is not a
threat probability. The cause of the slowdown and the anchor-reach applicability
remain unverified scenario assumptions.

The 228 m radar observation has no confirmed AIS association. Its possible length
discrepancy does not survive the Space module's assumed ±30 m radar uncertainty.
The review describes it accordingly. An unmatched radar contact or AIS gap is not
proof of hostile intent.

The alert links to the bundled fictional Space review at
`evidence/contacts/contact-0001.html`. The interface checks that the page exists.
The operator's downloaded decision record is a separate self-contained HTML file.

## Space evidence handoff

`space/evidence.html`, `space/evidence.css` and `space/evidence.js` are local templates/assets
for `python3 -m argus.evidence`. Open the generated `data/sar/review/index.html`, rather than
the HTML template. The export runs before presentation; viewing it needs no Python service,
JSON fetch, map tiles or network access. Contact pages show source labels, catalogue coverage,
matching limitations, length uncertainty and a page-local review form. Review notes do not
survive a reload and do not authorize an operational response.

The committed fictional pack is generated with
`python3 -m argus.evidence --scenario demo/scenario.json --output ui/evidence`.
Regenerate it after scenario changes. Historical or downloaded packs stay under
ignored `data/` and never share this fictional evidence URL. See
[Space instructions](../space/README.md).

## Local map asset

`assets/coastline.json` contains a simplified Natural Earth 1:10m country outline
for Ireland and the United Kingdom. It records the source URL, source SHA-256,
public-domain licence and `[lon, lat]` coordinate order. The renderer converts it
explicitly to the scenario's `[lat, lon]` convention. It is display geometry, not a
navigational chart or surveyed infrastructure.

To reproduce it, save the upstream file as the ignored
`data/maps/countries.geojson`, then run:

```sh
python scripts/prepare_demo_map.py
```

## Design references

The console follows the chart-first operational hierarchy seen in
[Kongsberg Traffic Display](https://www.kongsberg.com/what-we-do/ocean-space/surveillance-monitoring/foresight/traffic-display/)
and [Wärtsilä Navi-Harbour](https://www.wartsila.com/marine/products/port-optimisation/vtms):
geographic context, a selected contact, sensor observations, and explicit operator
actions. No vendor screenshots, icons or branded assets are included. Compact
rows, thin dividers, local system fonts and tabular numerals keep this a working
console rather than a marketing page. The current presentation uses a plain light
theme, a neutral map, standard grey controls and sentence-case labels. D28 records
the user's preference for basic utility software over the original dark theme.

## Checks

```sh
python scripts/check_contracts.py
python -m unittest discover -s tests
node tests/test_replay.mjs
```

The JavaScript checks exercise missing fixes, separated trails, response deadline
boundaries and countdown display. Node is only a test tool, not a demo dependency.
Acceptance also requires replaying the seven beats and exporting evidence with
external Wi-Fi disabled. The local static server must remain accessible.
