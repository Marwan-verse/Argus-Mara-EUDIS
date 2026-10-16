# Report assistant: Draft with AI, Check report and Save PDF

The **Report vessel** window (`desktop_reports.py`) helps the analyst write the
report, check it and export it before sending. It is opened from the review
window of an incident or from the card of a live AIS vessel. Decisions: D89
(draft and check), D95 (PDF and the 4,096-token output cap).

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

## Automatic report prefill (D111)

Opening Report vessel immediately fills an editable narrative and suggests a
category, using local code without an AI request. Eight sections cover vessel
and source, position and movement, assessment and incident, indicators and
findings, infrastructure and response context, evidence limits, suggested
follow-up and SOC analyst review. Facts retain their provenance labels. Missing
evidence is stated explicitly; follow-up is a proposal and analyst review stays
pending. Analysts can replace the entire narrative and change the category.

The narrative accepts up to 4,000 characters. Prefill retains whole facts within
both that limit and the existing encrypted message size limit, prioritizing
coverage across sections. If facts are omitted, the window says how many; the
PDF evidence appendix still holds the full pack. The shared report keys are
unchanged, but teammates need this version to receive narratives over the old
2,000-character limit. Draft with AI remains an optional shorter replacement;
Ctrl+Z restores the prior narrative. Creating or sharing remains explicit.

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

## Save PDF

`argus/report_pdf.py` draws A4 pages at 150 dpi with Pillow (already a
dependency). The pages are images, so the PDF text is not selectable. The
analyst chooses the file; nothing is sent.

- Header "Analyst report — draft for review", the data banner (SIMULATED,
  EXERCISE or REAL), vessel, category and incident.
- The analyst's text, then the status of the last Check report. If the text
  changed after the check, the PDF says "Not checked since the last edit".
- Appendix built by code from the pack, never by AI: (A) Brain's level and
  why, factors, findings, line, incident, who can reach it, recommendation;
  (B) identity, position, data labels and sources, with every fact ID;
  (C) how the text was produced: method, model, time, cost, or why AI was not
  used.

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
  4,096-token output cap (a reservation of about $0.003 for a Brain contact; raised from 2,048 by D95 after a live draft used 1,903). Valid usage then settles the call at
  the reported cost (as in D86). A failed or uncertain call keeps its whole
  reservation and is not retried. Usage above the reservation halts spending.
- **Cache:** by prompt version, model, evidence pack and text. A repeated
  draft or check is free and works offline.
- One request at a time (`data/report-ai/analysis.lock`). After a crash, make
  sure the app has stopped before removing the lock. Do not delete
  `budget.json` to reset spending.

## Evaluation, 16 October 2026

`python scripts/eval_report_ai.py` checks six replay stories offline (template);
`--live` calls Qwen (paid). Packs are scored at the end of each track, without
the panel's incident or responders. These are counts on six stories, not an
accuracy measure.

Two live runs on the same six stories:

| Story | Brain | Run 1 (prompt v1) | Run 2 (prompt v2) | Code check, run 2 | AI check, run 2 |
|---|---|---|---|---|---|
| SIM-53 normal transit | None | valid | valid | 0 | 0 |
| SIM-50 cable risk (EWIC) | Medium | valid | valid | 0 | 0 |
| SIM-51 holding, then anchoring | High | wrong JSON keys | valid | 0 | 0 |
| SIM-41 AIS gap, radar contact | High | echoed the input | valid | 0 | 1 unsupported |
| SIM-49 faulty AIS data | None | no category | valid | 0 | 0 |
| SIM-55 wrong destination | High | echoed the input | valid | 0 | 1 missing, 1 unsupported |

- **Run 1, prompt v1:** the user message was bare JSON. 2 of 6 drafts matched
  the schema. Four were rejected by code and never inserted: one used a
  `report` key, two echoed the request (one echo had a changed longitude), one
  had no category. The window inserted the template instead, as designed.
- **Run 2, prompt v2:** the task is stated in plain words before and after the
  data, the reply shape is spelled out, and every pack states that the system
  triggers no operational action. 6 of 6 drafts matched the schema and passed
  every code check (times, positions, numbers, names, IDs, level, intent words,
  data label); every cited evidence ID exists.
- **AI check, run 2:** 3 findings, none dropped by validation. Two say the
  evidence does not literally state "no evidence of hostile intent" (it says
  the level is not a probability of hostile intent); one says the SIM-55 draft
  leaves out that the ship turned away from its declared destination. They are
  suggestions for the analyst.
- **Output size:** one draft used 2,615 output tokens, above the old 2,048
  cap (D95 raised it to 4,096).
- **Latency, run 2:** draft 8–27 s, check 8–27 s. **Cost:** run 1 $0.0077
  (10 paid calls), run 2 $0.0124 (12 paid calls). The ledger holds $0.0222 for
  24 calls, all settled at the reported cost.

## Limits

The code check is a set of pattern rules. It reads common formats, not every
way of writing a value, and it does not prove the text correct. The AI layer
gives suggestions for the analyst, not a verdict. Nothing here triggers an
operational action. The report format (`argus/vessel_reports.py`) and the
encrypted SOC sharing are unchanged.

Tests: `tests/test_report_ai.py` (pack, template, code checks; Qwen on a fake
transport), `tests/test_report_pdf.py` (PDF content and pages) and `tests/test_desktop_reports.py` (the window with and without a
key).
