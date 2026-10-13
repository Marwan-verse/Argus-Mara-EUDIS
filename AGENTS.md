# Argus Mara repository guidance

Read `DECISIONS.md` and `demo/README.md` before changing code. The current build is a file-based, offline-first demo for EUDIS Challenge 3.

- Use Python for data preparation, the AIS recorder, detection and countdown logic. Use Svelte 5 for browser interfaces under `ui/src/` (D37), with the existing global CSS and pure JavaScript analysis helpers. Run `npm ci`, `npm run check`, `npm run build`, and `npm run test:browser` after browser changes. Commit compiled bundles for offline use; Node is a development tool only. Do not add a backend, database or authentication to the offline demo. Read the official Svelte skills in `skills/svelte-code-writer/` and `skills/svelte-core-bestpractices/` when editing Svelte.
- Treat `demo/scenario.json` and `demo/alerts.json` as the shared interface. Preserve existing field names, units and coordinate order. Run `scripts/check_contracts.py` after changing either file.
- Keep raw or downloaded data and secrets out of Git. `data/` and `recorder/.apikey` are ignored.
- Label evidence as `real`, `reconstructed`, `simulated`, `fictional` or `assumption`. An AIS gap or unmatched radar contact is a lead for review, not proof of malicious action.
- Keep operator approval visible. No automated operational response or kinetic action.
- Add a new row to `DECISIONS.md` when changing a team decision; do not rewrite earlier decisions.

The detailed layout and ownership rules are in `docs/07-architecture.md`. Shareable teammate skills are in `skills/`.
