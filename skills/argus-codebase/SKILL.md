---
name: argus-codebase
description: Work on Argus Mara's Python analysis, demo JSON contract, or repository structure while preserving its file-based hackathon demo.
---

# Argus Mara codebase

Use Python 3 for data preparation, AIS ingest, detection and countdown logic. Use the existing `demo/scenario.json` and `demo/alerts.json` files as the v1 integration boundary. Read `DECISIONS.md`, `demo/README.md` and `docs/07-architecture.md` in the repository before changing the shape or meaning of that boundary.

Keep Brain logic in `argus/`, sample generation in `demo/`, independent AIS recording in `recorder/`, and reusable integration checks in `scripts/`. Do not add a backend, database, authentication or build system for v1 unless the team explicitly changes D14–D15.

Preserve seconds, knots, kilometres and `[lat, lon]` scenario paths; GeoJSON uses the reverse coordinate order. Keep source/provenance labels visible. Treat AIS gaps and AIS-unmatched SAR contacts as uncertain observations, not proof of hostile behaviour. Run `python scripts/check_contracts.py` after editing either JSON file, and keep the offline replay working.

When a change affects another workstream, update the contract docs and record the decision rather than silently changing a key. For research-backed data choices, consult `docs/08-research-and-next-ideas.md` and add exact dataset attribution to `docs/sources.md`.
