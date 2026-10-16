# Report assistant: Draft with AI and Check report

The **Report vessel** window (`desktop_reports.py`) helps the analyst write the
report and check it before sending. It is opened from the review window of an
incident or from the card of a live AIS vessel. Decision: D89.

## Evidence pack

`argus/report_ai.py` builds the facts by code before anything is written:

- **Brain contact** (from the review window): identity, position and replay
  time, SOG/COG, the board summary, Brain's level and score with its factors
  and rules, the detector findings, the small-vessel rule, the line at risk,
  the incident and its status, who can reach it, the board recommendation, data
  issues and the data labels from `argus.explain`.
- **Live AIS vessel** (no Brain item): identity, last position and receive
  time, SOG/COG and declared destination. The pack says that AIS is
  self-reported and that the vessel has no Brain assessment.

Every fact has an ID (`E1`, `E2`, ...) and a label: SIMULATED, EXERCISE, REAL,
ILLUSTRATIVE, ASSUMPTION, RULE OUTCOME, DATA ISSUE or LIMITATION. The window
shows a one-line summary of the pack under the vessel name.

## Draft with AI

One text-only request to TensorX `qwen/qwen3.8-flash-next`. The pack goes in
as JSON data, not as instructions. The reply must be JSON: the draft, a
category from the report categories, and the fact IDs it used. The style is
English, dry and officer-like, in four parts: Observed, Why it matters,
Uncertain, Recommended (about 1,000 to 1,500 characters).

Code validates the reply before it reaches the text box. A draft is
**rejected** when it cites an unknown fact ID or none, uses a time, position,
number, name, ID or level that is not in the pack, states intent (hostile,
sabotage, deliberate, ...) without denying it, leaves out the data label
(simulated, exercise) or the vessel or Brain's level, or is too long. A
rejected draft is never inserted: the window inserts the template draft
instead and lists the reasons. An unsupported category is replaced with the
pack's suggestion. Brain's level is never assigned or changed.

Generated text ends with a label line: "AI-assisted draft · reviewed by
analyst" or "Template draft from system data · reviewed by analyst". The
analyst edits the text before sending; Ctrl+Z restores the previous text.

## Check report

Two layers, shown separately:

- **Code check (exact, no AI).** Times (replay `T+hh:mm`, UTC, DTG),
  positions, numbers with units (kn, nm, min, h, m, %, °), vessel names, IDs
  (SIM-, INC-, MMSI) and the level in the text must match the pack. Intent
  words need evidence the system never holds. A simulated contact must be
  called simulated and a real one must not. The category must be supported
  by Brain's groups. Placeholders such as `[state ...]` are flagged.
- **AI check (meaning).** Qwen looks for claims the evidence does not
  support, intent stated as fact, important facts left out and unclear
  wording. A finding is kept only if it quotes the report exactly, cites
  existing fact IDs and adds no value or name outside the pack or the text.
  Dropped findings are counted in the window.

## Offline, key, budget

- **Offline:** without a key, network or budget, Draft uses the template and
  Check runs the code layer only. The window says which was used and why.
- **Key:** `argus.satellite_ai.get_key` (`TENSORX_API_KEY`,
  `TENSORX_API_KEY_FILE` or the OS credential store). It is never logged,
  shown or stored with results.
- **Model:** listed by `/v1/models`, with limits in `/v1/model/info` and
  prices within the snapshot in `argus.satellite_ai.PRICES` (verified on
  15 October; it expires after 30 days). The model profile is rechecked every
  12 h. Vision is not required for these text calls.
- **Budget:** $2 in `data/report-ai/budget.json`, separate from the $20
  satellite pilot. Each call reserves its bound before sending: the request's
  UTF-8 bytes (a token is at least one byte) plus 256 tokens, and the
  2,048-token output cap: about $0.002 for a Brain contact. Valid usage then settles the call at
  the reported cost (as in D86). A failed or uncertain call keeps its whole
  reservation and is not retried. Usage above the reservation halts spending.
- **Cache:** by prompt version, model, evidence pack and text. A repeated
  draft or check is free and works offline.
- One request at a time (`data/report-ai/analysis.lock`). After a crash, make
  sure the app has stopped before removing the lock. Do not delete
  `budget.json` to reset spending.

## Limits

The code check is a set of pattern rules. It reads common formats, not every
way of writing a value, and it does not prove the text correct. The AI layer
gives suggestions for the analyst, not a verdict. Nothing here triggers an
operational action. The report format (`argus/vessel_reports.py`) and the
encrypted SOC sharing are unchanged.

Tests: `tests/test_report_ai.py` (pack, template, code checks; Qwen on a fake
transport) and `tests/test_desktop_reports.py` (the window with and without a
key).
