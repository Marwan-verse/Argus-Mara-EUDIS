# Argus Mara repository guidance

Read `DECISIONS.md` and `demo/README.md` before changing code. The current build is a file-based, offline-first demo for EUDIS Challenge 3.

- Use Python for data preparation, the AIS recorder, detection and countdown logic. Use browser JavaScript, HTML and CSS for the interface. Do not add a backend, database, authentication or a build system to v1.
- Treat `demo/scenario.json` and `demo/alerts.json` as the shared interface. Preserve existing field names, units and coordinate order. Run `scripts/check_contracts.py` after changing either file.
- Keep raw or downloaded data and secrets out of Git. `data/` and `recorder/.apikey` are ignored.
- Label evidence as `real`, `reconstructed`, `simulated`, `fictional` or `assumption`. An AIS gap or unmatched radar contact is a lead for review, not proof of malicious action.
- Keep operator approval visible. No automated operational response or kinetic action.
- Add a new row to `DECISIONS.md` when changing a team decision; do not rewrite earlier decisions.

The detailed layout and ownership rules are in `docs/07-architecture.md`. Shareable teammate skills are in `skills/`.
