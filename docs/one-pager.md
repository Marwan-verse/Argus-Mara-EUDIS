# Argus Mara — Anchor Watch

**An offline early-warning exercise for decisions near undersea infrastructure.**

Argus Mara replays AIS fixes and separate radar observations, identifies review cues, estimates time to an illustrative cable crossing, and compares assumed response arrival times. A watch officer reviews the evidence and explicitly approves any simulated response. No operational action is sent.

## What the current demonstration shows

- A fictional vessel has a 20-minute AIS reception gap. The map leaves that gap empty.
- A separate simulated radar contact appears. Association with the vessel and any length discrepancy remain uncertain.
- At the first observed 9.1 kn fix, four explainable rule cues trigger a review alert: slowdown, heading change, earlier AIS gap, and projected crossing of an assumed anchor-reachable section.
- The expected countdown is **1 h 13 min 31 s**; the earliest planning estimate is **1 h 1 min 15 s** under a 20% faster-speed assumption.
- The operator compares assumed aircraft, ship, VHF, and satellite timings, selects a response, reviews uncertainty, and records a simulated decision.

## What is real today

The browser console, Python rules, countdown, response timing, local map asset, contract checks, and offline evidence pages run from repository files. The Space workstream has two attributed historical radar contacts in a **separate** review pack. Those contacts are not evidence about the fictional vessel.

## Validation still needed

Measured alert rates and false alarms require labelled outcomes. Operational use would require validated cable/depth geometry, response capabilities, radar associations, and testing with the responsible authorities. The demo makes none of those claims.

**Run:** `python scripts/serve_demo.py`, then open `http://127.0.0.1:8000/ui/`. No external network or application backend is required. See [the four-minute runbook](demo-runbook.md) and [the decisions log](../DECISIONS.md).
