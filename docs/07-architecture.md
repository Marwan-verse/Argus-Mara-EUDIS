# 7. Codebase architecture and team contracts

*Proposed implementation structure, 7 October 2026. This follows decisions D13–D15 and D22. It does not change the seven-beat demo.*

## The shortest path to the working demo

The project has two runtime halves. Python prepares a scenario and computes alerts. A browser presents both files and records a human's simulated decision. The interface should be served as static files from the repository root for local development; a local static server is not an application backend. Once assets are downloaded, the demo must run with external Wi-Fi disabled.

```text
recorder/       live AIS capture; independent from the stage demo
data/           ignored local recordings and downloaded datasets
demo/           committed scenario.json and alerts.json; the v1 contract
argus/          Python contract checks and Space analysis; Brain-owned ETA code next
space/          Space sidecar examples, provenance and handoff
ui/             Interface-owned static HTML, CSS, JS and local map assets next
scripts/        cross-workstream checks and local development helpers
skills/         downloadable teammate instructions
docs/           research, decisions, plan and build guidance
```

**Languages:** Python 3 for ingest, geometry, rules, ETAs and contract generation. Browser JavaScript, HTML and CSS for replay. JSON is the boundary. Keep v1 dependency-free where practical. The recorder's `websockets` and `pyarrow` dependencies stay in `recorder/requirements.txt`; they do not become interface requirements.

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
- `evidence_url` is a future interface target. The stub alert points to `evidence/A1.html`, which does not exist yet. The UI should show an unavailable state until an evidence page is implemented.

Run `python scripts/check_contracts.py` after editing either JSON file. The checker tests structure and cross-file references; it cannot establish that an estimate is scientifically accurate.

## Change protocol

Add optional fields without breaking readers. To rename, remove or reinterpret an existing field, first write a decision in `DECISIONS.md`, update `demo/README.md`, update the checker and generator, then change the writers and readers together. Keep a known-good copy of both JSON files for the offline demo. Do not silently replace the simulated route with an unsourced or sensitive route.

## Next code tasks, by dependency

*Interface update, 8 October 2026 (D27):* `ui/index.html`, `styles.css`, `app.mjs`
and `replay.mjs` now implement the seven-beat offline console. Run
`python scripts/serve_demo.py` and open `/ui/`. Natural Earth display geometry is
bundled locally. Evidence review and HTML export work; the old stub evidence URL
is still unavailable. Operator decisions are simulated, session-local, and clear
when the replay is sought or restarted. The Brain detector and updated countdown
calculations remain pending.

1. Interface owns a local coastline asset and a static replay that handles the AIS gap, radar contact, alert and approval.
2. Brain moves the projection helper from `demo/make_scenario.py` into a reusable `argus/countdown.py`, while writing the same `alerts.json` shape.
3. Data replaces the illustrative cable and depth only after source, licence and provenance are recorded.
4. Space's two public examples remain a separate story from the fictional tanker. The Interface can add one reviewed example after its observation time, source and matching uncertainty are clear in the evidence.

The larger module list in `05-build-guide.md` is a post-demo option. Avoid creating empty folders for those future components.

## Space evidence addition — 8 October 2026

Space writes an optional sidecar and local evidence pack with `argus.evidence`; the two shared
demo files retain their existing fields and meaning. Browser templates live in `ui/space/`,
normalized AIS ingest in `argus/ingest/ais.py`, and generated/downloaded material in ignored
`data/`. See [Space's additive fields and commands](../space/README.md#run-offline).

The sidecar preserves provider associations separately from local ones, records association
method and timing assumptions, and exposes missing-evidence reasons. Exported `evidence_url`
paths resolve against the pack root. Brain may choose a generated page when writing its alert;
Interface owns linking that page from the stage replay. The current sample alert remains a
placeholder. Historical packs and fictional packs are separate. Real/reconstructed contacts
cannot locally match fictional/simulated AIS; sourced dimensions expire after an assumed
24 hours and cannot come from future observations. A page-local operator acknowledgement
persists only until reload and never triggers a response.
