# Anchor Watch: offline operator demo

The static HTML/CSS/JavaScript console reads `demo/scenario.json` and
`demo/alerts.json`. It starts paused at the alert so the assessment is immediately
reviewable. Press Restart, then Play, for the complete seven-beat story.

## Run

From the repository root:

```sh
python scripts/serve_demo.py
```

Open <http://127.0.0.1:8000/ui/>. Windows users can also double-click
`scripts/START-DEMO-WINDOWS.bat`. No dependencies to install, no backend, no build
step, and no outside network requests. Keep the local static server running while
presenting; opening `index.html` directly is not supported.

## Controls

- Play/Pause; Restart; 30×, 60× or 120× speed; time slider.
- Buttons 01–07 jump to the seven beats. The last beat opens the opportunity for a
  decision; the operator still has to review and approve explicitly.
- Layer switches control the AIS trail, radar, anchor reach and response assets.
- Zoom controls and Reset chart view operate on the local vector map.
- Evidence review explains provenance and uncertainty. After the alert fires,
  Export saves a self-contained HTML evidence record.
- Review response pauses the replay. An explicit acknowledgement is required
  before approving the simulated response. Approval opens its evidence record.
- Seeking or restarting clears approval. Approval otherwise survives forward
  playback for that run. Decisions are session-local and are lost on reload.
- Space toggles playback and arrow keys step a minute when a form, button or
  dialog is not focused. Escape closes dialogs.

The approval control stays visible on short desktop screens. The assessment and
left sidebar can scroll independently. The desktop target is at least 900 px wide;
mobile layout remains outside v1 scope.

## Honesty of the replay

Long AIS gaps stay empty, and trails are split across the gap. Radar is a separate,
timestamped historical observation; it does not become a moving AIS marker. The
countdowns display the supplied alert ETAs minus replay time, and response arrival
durations are compared against the remaining earliest crossing time. This does
not recalculate the vessel's prediction or run a detector in the browser.

The sample alert is a stub. It cites 9.1 kn at 75 minutes even though that speed
first appears at 90 minutes in the committed track. The console reports observed
speed up to the current time and retains the original claim, explicitly qualified,
in the evidence record. Claims about an unexplained slowdown or being inside an
anchor-reach zone also remain unvalidated scenario assertions. No contract files
have been changed by this interface.

The 228 m radar observation has no confirmed AIS association. Its possible length
discrepancy does not survive the Space module's assumed ±30 m radar uncertainty.
The review describes it accordingly. An unmatched radar contact or AIS gap is not
proof of hostile intent.

The contract's `evidence/A1.html` target remains unavailable. The working export is
a separate local record, not a claim that the target page exists.

## Space evidence handoff

`space/evidence.html`, `space/evidence.css` and `space/evidence.js` are local templates/assets
for `python3 -m argus.evidence`. Open the generated `data/sar/review/index.html`, rather than
the HTML template. The export runs before presentation; viewing it needs no Python service,
JSON fetch, map tiles or network access. Contact pages show source labels, catalogue coverage,
matching limitations, length uncertainty and a page-local review form. Review notes do not
survive a reload and do not authorize an operational response.

The exporter also supports `--scenario demo/scenario.json --output data/sar/demo-review`
for a separate fictional pack. Brain/Interface can resolve each sidecar `evidence_url` against
that pack root. The existing alert's `evidence/A1.html` placeholder is still unavailable;
connect it only when integrating the stage replay. See [Space instructions](../space/README.md).

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
