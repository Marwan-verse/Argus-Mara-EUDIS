# `argus/`: Python analysis

This package holds shared contract validation, Space's offline radar/AIS analysis
(`space.py` and `ingest/`), and Brain's explainable alert and countdown code
(`brain.py` and `countdown.py`). Run `python -m argus.brain` after preparing the
scenario; `demo/make_scenario.py` no longer overwrites Brain's alert. See the
[Space handoff](../space/README.md) for its separate sidecar and examples.

Space additions: `ingest/ais.py` normalizes attributed CSV/recorder positions and timestamped
dimensions; `provenance.py` supplies UTC, coverage and checksum helpers; `evidence.py` exports
hashed offline evidence packs using browser templates in `ui/space/`. Historical
or downloaded packs write under ignored `data/`; the fictional stage pack is
committed under `ui/evidence/`. They preserve both shared demo files.

`brain.py` uses four review cues: observed slowdown, heading change, an earlier
AIS reception gap and a constant-course projected crossing of an assumed shallow
section. Its `score` counts satisfied cues; it is not a threat probability.
`countdown.py` also calculates assumed response arrival times. Additional modules
are unnecessary for this v1 replay.

Keep input and output in the two JSON files described in [`demo/README.md`](../demo/README.md). Do not make the interface import Python or depend on a live service. See [`docs/07-architecture.md`](../docs/07-architecture.md) for units, ownership and change rules.
