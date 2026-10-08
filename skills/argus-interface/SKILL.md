---
name: argus-interface
description: Build Argus Mara's static browser replay and evidence UI from the shared demo JSON files, with offline operation and clear data provenance.
---

# Argus Mara interface

Use browser JavaScript, HTML and CSS in `ui/`. Read `demo/README.md` for the two file shapes and `docs/07-architecture.md` for units and ownership. The interface consumes `demo/scenario.json` and `demo/alerts.json`; it does not require a live Python process or external map tiles during the stage demo.

Show the seven beats in the README in sequence. Keep a true AIS gap: hide the AIS vessel marker during the missing fixes and show the radar detection as a separate observation. Display both expected and earliest countdowns, option availability, source labels and the human approval step. Brain now generates the alert at the first observed 9.1 kn fix (minute 90). Its score counts rule cues, not threat probability. Avoid fixed phrases or times that disagree with the JSON.

The fictional alert's `evidence_url` points to a generated page under `ui/evidence/`. Check that the page is available before linking it. Keep the operator's exported decision record separate, and keep historical radar contacts separate from the fictional replay.

Keep any map data, fonts and libraries needed for the presentation local. A local static file server for development is fine; test with Wi-Fi disabled. Do not change JSON field names from the interface side without coordinating with Data and Brain and updating the contract check.
