# Measured performance improvements — 11 October 2026

The browser migration is described in `ui/README.md` and D37–D38. The next pass
keeps the existing Python runtime and removes repeated work in analysis, live
publication and recording exports. Both shared demo files remain unchanged.

## Changes

- `argus/brain.py` walks time-ordered fixes once to maintain the latest eligible
  AIS gap. Previously each fix scanned the earlier track again, giving quadratic
  work on long tracks. Gap thresholds, the 90-minute inclusive age boundary,
  first alert, reasons, crossing estimates and response options are preserved.
- `argus/live_state.py` exposes isolated contact IDs and a constant-time contact
  count. The live service uses these for publication, eviction, restart setup
  and health checks instead of building every contact's public fields and ages.
  Full snapshot requests still receive complete observations with current ages.
- `recorder/map.py` and `argus/ingest/ais.py` read explicitly allowed Parquet
  columns in batches of at most 4,096 rows. They preserve file order, timestamps,
  duplicate/conflict handling and private-field exclusion. The AIS handoff still
  retains its normalized output tracks; its total memory grows with that output.
  Batch reading uses the existing [PyArrow API](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html#pyarrow.parquet.ParquetFile.iter_batches).

## Local measurements

Run from the repository root with the existing `live/requirements.txt` installed:

```sh
.venv/bin/python scripts/measure_backend.py
```

All inputs are generated, explicitly simulated fixtures in temporary storage.
No provider key, external service, downloaded dataset or committed recording is
used. Counts can be changed with `--track-fixes`, `--contacts` and `--rows`.

| Workload | Before | After |
|---|---:|---:|
| Normal track scan, 4,000 fixes | 455.675 ms | 0.253 ms |
| Publish one changed contact in a 5,000-contact fleet | 12.476 ms | 0.436 ms |
| Build health response for that fleet | 12.185 ms | 0.006 ms |
| Export 100,000 recording rows, with allocation tracing enabled | 2,783.7 ms | 1,367.2 ms |
| Peak traced Python allocations for that export | 63.01 MiB | 14.42 MiB |

Detector timings are medians of three runs; live timings are medians of twenty.
The exporter is a single measured run. Allocation tracing changes runtime and
does not measure Arrow's native allocations or total process RSS. The track
fixture exercises a normal passage with no alert; it does not benchmark active
cable projections. Publish timings exclude disk journalling. These figures are
local lab results, not a claim about deployed capacity or real AIS reception.

## Verification and runtime choice

```sh
.venv/bin/python -m unittest discover -s tests
python3 scripts/check_contracts.py
npm test
npm run test:browser
```

Regression coverage includes unchanged committed alert output, gap eligibility
and expiry, linear track work, eviction/removal updates, restart and damaged
journal recovery, storage failures, shutdown during an unfinished durable write,
metadata-only contacts, conflicting fixes across batches and offline exports.

The durable archive still fsyncs each accepted journal record before publication;
its recovery, capacity and retention behaviour is unchanged. Evidence provenance
and explicit simulated operator approval are preserved.

The measurements support keeping Python for this build. A later Rust experiment
should target a function that remains expensive in a representative profile and
compare its output and end-to-end cost with the optimized Python implementation.
Large geometry/matching workloads are candidates to measure, not established
bottlenecks in the current two-file demo. A language migration would also need
the team's Windows/macOS distribution path and equivalent recovery tests.
