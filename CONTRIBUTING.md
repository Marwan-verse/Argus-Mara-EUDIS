# Contributing to Argus Mara

This private repository is organized by workstream. Start with [the architecture](docs/07-architecture.md), [decisions](DECISIONS.md), and [demo contract](demo/README.md). Coordinate contract changes with Data, Brain, and Interface before editing shared JSON field names or units.

## Where changes belong

- `argus/`: Python analysis, detection, countdown, and shared contract code.
- `recorder/`: independent AIS recording and local data checks.
- `ui/`: browser JavaScript, HTML, CSS, and offline assets.
- `demo/`: the two JSON files that join the workstreams.
- `scripts/` and `tests/`: checks and regression tests.
- `docs/` and `skills/`: project decisions, architecture, and teammate guidance.

Keep v1 file based and runnable offline. Do not add a backend, database, login system, or build pipeline without a recorded team decision.

## Before requesting review

1. Keep changes focused and explain the affected demo beat or workstream.
2. Run `python scripts/check_contracts.py` and `python -m unittest discover -s tests -v` from the repository root. Note any check you could not run.
3. Keep raw data, downloaded data, API keys, `.env` files, and `recorder/.apikey` out of the diff. Use only public or fictional examples and cite real sources.
4. Preserve field names, units, and `[lat, lon]` order in `demo/scenario.json` and `demo/alerts.json`. Add a new decision row in `DECISIONS.md` when changing an agreed team decision.
5. Open a pull request with the result and a short test note. Ask the relevant workstream owner to review. During the hackathon, coordinate urgent integration changes directly with the captain.

For vulnerabilities or exposed secrets, use the private route in [SECURITY.md](SECURITY.md), not an issue.
