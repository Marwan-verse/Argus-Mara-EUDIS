# Prior work declaration — Argus Mara

*Draft as of 8 October 2026. Update against Git history and freeze this record on 14 October before creating the planned `pre-hackathon` tag. This document does not claim that the tag or final dry run already exists.*

## Built before the 15–17 October 2026 hackathon

- Challenge framing, name, product decisions, team plan, pitch research and source notes in `DECISIONS.md`, `README.md` and `docs/`.
- The file-based, fictional demonstration contract: `demo/scenario.json`, `demo/alerts.json`, the scenario generator and `scripts/check_contracts.py`.
- The independent Irish AIS recorder and its launcher/health-check scripts in `recorder/`. Its actual recorded coverage and data are local, unverified in this checkout and excluded from Git.
- Space importers, association and length-review code, two attributed historical contact examples, normalized AIS handoff and offline evidence exporter in `argus/`, `space/` and `ui/space/`.
- The static offline operator console and local coastline display geometry in `ui/`.
- The rule-based Brain alert, countdown and response calculations in `argus/brain.py` and `argus/countdown.py`; the corrected minute-90 fictional replay and bundled fictional Space page in `ui/evidence/`.
- Automated contract, Space, Brain and replay checks in `tests/`.

These are **pre-event** components. Git commits, not this summary, are the detailed record of authorship and timing. The fictional scenario, illustrative cable, simulated radar detection and assumed response assets are not operational validation.

## At the freeze on 14 October

1. Confirm the exact repository commit and all files included in the pre-event build.
2. Add any further pre-event changes to this declaration; keep raw/downloaded data and secrets out of Git.
3. Run the contract and test checks and complete an offline dry run.
4. Create `git tag pre-hackathon` at the reviewed commit and push the tag only after the team confirms the declaration and event rules.

Work built during the hackathon should be recorded after the tag so the boundary is clear.
