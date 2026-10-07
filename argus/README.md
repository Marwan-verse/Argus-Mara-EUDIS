# `argus/`: Python analysis

This package holds shared contract validation and the Space workstream's offline radar/AIS analysis (`space.py` and `ingest/`). The Brain workstream's detector, countdown and response calculations belong here next; `demo/make_scenario.py` still generates the sample alert stub. See the [Space handoff](../space/README.md) for its current sidecar and examples.

Suggested next files, when their owners implement them:

- `brain.py`: command line entry point that reads a scenario and writes alerts.
- `countdown.py`: testable projection and ETA functions, extracted from the demo generator.
- `response.py`: response ETAs and arrival badges.
- `detectors.py`: explainable rules with evidence for each reason.

Keep input and output in the two JSON files described in [`demo/README.md`](../demo/README.md). Do not make the interface import Python or depend on a live service. See [`docs/07-architecture.md`](../docs/07-architecture.md) for units, ownership and change rules.
