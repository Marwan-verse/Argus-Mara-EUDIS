# `ui/`: static stage interface

This folder is reserved for the Interface workstream (Adam and Marwan). Add browser HTML, CSS, JavaScript and local map assets here. The first deliverable is the seven-beat replay in the root README, using `demo/scenario.json` and `demo/alerts.json` as input.

For development, serve the repository root with a simple local static server and open `/ui/`. Browser `file://` pages commonly cannot fetch neighbouring JSON files, so opening `index.html` directly is not the acceptance check. A local static server is compatible with the no-backend v1 decision, and it continues to work with external Wi-Fi disabled.

The interface must show a real AIS gap, a separate radar observation, expected and earliest countdowns, response options, provenance labels and a human approval action. Keep libraries, map geometry and fonts local before the offline dry run. See [`demo/README.md`](../demo/README.md), [`docs/07-architecture.md`](../docs/07-architecture.md) and the portable [`argus-interface` skill](../skills/argus-interface/SKILL.md).

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
