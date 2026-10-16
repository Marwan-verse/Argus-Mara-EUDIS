# Tracking, dark-contact detection and Brain improvement evidence

The active objective is to improve tracking, detection of "black knights",
AI implementation and all aspects of Brain. Here "black knights" is interpreted
as vessels with missing or inconsistent AIS identity, not a confirmed hostile
category. This is an ongoing work record, not a completion declaration.

## 16 October: input quality and honest association (D96)

- Brain's shared spoofing/route track cleaner sorts valid fixes before applying
  a replay cutoff, rejects nonfinite/boolean coordinates and timestamps,
  deduplicates same-position receipt times, and treats contradictory motion
  declarations as unknown. Simultaneous contradictory positions are withheld
  from motion calculations and retained as a weak source-quality cue. They
  cannot create an invented infinite-speed traversal or alone set spoof_signs.
- An acquisition-time archive join excludes only an ambiguous vessel instead
  of failing the whole image. Equal timestamps from separate stream epochs
  stay separate, and static declarations cannot cross epochs. Mixed provenance
  is explicit. Exclusions appear in coverage and prevent new unmatched-image
  leads, because missing an ambiguous track is not evidence of AIS absence.
- Image/AIS comparison v3 records a status for every image contact, including
  missing history, conflicting history, duplicate observations and nearby AIS.
  Independent eligible AIS-vessel checks remain available. Incidents reports
  the number of images with conflicting history.
- Vision prompt v3 requests a contact-cap flag; parsing preserves it even below
  24 returned contacts, so detail review/negative-evidence gates see the cap.
  Invalid coordinate schemas and nontext limitations fail explicitly. Exact
  repeated image positions from one model window stay listed with ambiguity
  flags; they do not become multiple dark-vessel leads. The same flagging runs
  on saved reviews during free reassociation. No paid validation was run.

Local received-data execution check: `data/validation/tracking-audit.json`
records 3,831 position rows for 1,920 MMSIs, no duplicate/conflicting receipt
rows, no execution errors, 276 no-rule-cue results and 1,644 insufficient-history
results. This archive is too sparse to establish precision, recall or a false
alarm rate. No-rule-cue results are not safety clearances. The script that
produced the report did not change hosted fleet-check watermarks.

## 16 October: hosted quality parity and initial fleet checks (D97)

`20261016132518_align_tracking_quality.sql` is deployed on the active project.
It indexes valid receipt-time coordinates from complete archived observations,
including raw corrections that cannot coexist under the normalized position
table's primary key. Invalid timestamps/positions remain archived without
becoming usable positions. Source conflicts, mixed provenance and competing
stream epochs exclude the identity from acquisition-time matching. A competing
epoch just outside the image still prevents selecting an identity inside it.
Both direct SQL comparison and the Python database handoff receive explicit
exclusions; unmatched-image leads are withheld when exclusions make AIS absence
uncertain. Name/length declarations in SQL now belong to the selected stream.
No existing API names or units changed, and private helpers grant no public access.

Actual PostgreSQL/PostGIS regression tests cover corrections, invalid dates,
epoch ambiguity, outside-image competing epochs, metadata isolation and role
restrictions. Python tests verify exclusion propagation and reject malformed
quality evidence. The hosted database returned 79 eligible positions in an
Irish acquisition-time query and no source conflicts on that particular sample;
this is execution evidence, not proof the feed is free of errors.

The initial hosted fleet backlog was processed through the existing
`argus_history_claim/page/finish` RPCs and actual Python `analyse_history` rules.
No source key was exported, no paid AI was called, and intermediate received
data stayed under ignored `data/validation/`. At the checkpoint with last sync
`2026-10-16T13:33:30.324018Z`, all 2,043 recorded ships had a saved result,
never_checked and new_evidence_pending were zero, and no leases remained active.
Results: 1,558 insufficient_history, 484 no_rule_cues, one isolated_cue and
zero review_required. This is not a safety clearance or detector-accuracy result.
Incoming evidence requeues ships normally. This one-time connector run is not
a continuously deployed worker; desktop/SOC credentials are still required for
ongoing automatic Python checks and local cache refresh.

## 16 October: temporal support (D98)

Acquisition-time joins now retain endpoint reachability in `argus/tracking.py`.
A short interpolation uses the intersection of the two supporting fix circles;
a projection uses its preceding fix. Each circle uses the existing 80 kn team
screening assumption and the absolute fix-to-image time offset. These are not
calibrated confidence intervals and do not bound receipt-clock or sensor errors.
The center-radius field is an enclosing upper bound derived from the endpoints,
not the predicted vessel's likely path.

The identity match gate stays at 300 m. A contact outside it but inside temporal
support is an uncertain candidate, including beyond the previous 1 km list
cutoff. It cannot become an unmatched-image lead merely because the projected
course missed it. Missing-detection leads are also withheld when temporal support
extends beyond the 1 km alternative search. Exact fixes and sufficiently recent
projections still support review. Native evidence shows the support radius and
uses separation, rather than calling the modeled position ground truth.

`20261016133900_temporal_tracking_support.sql` is deployed and applies the same
gates to hosted comparison. A live sample returned support for all 75 eligible
positions queried. PostgreSQL/PostGIS tests verify old projections, long brackets,
recent supported projections and the unchanged identity gate. Python tests cover
turns, both endpoint constraints, exact observations and expired/future-only fixes.

## 16 October: imagery-pack evaluation and unusable-image abstention (D99)

The user identified `demo/imagery/` as existing evaluation material. Its manifest
contains ten manually selected vessel-shaped regions, labelled assumptions, on
real published pixels. It is not an exhaustive reference set. The original source
rasters were fetched with the existing hash-verifying downloader; private clean
crops contain no outlines, captions, fictional names or simulated cables/tracks.
They retain source-pixel dimensions, attribution and licenses. No coordinates or
acquisition times were invented for these non-georeferenced presentation sources.

Ten bounded Qwen requests under the existing shared ledger completed with image
token accounting. At a fixed five-source-pixel center tolerance, **0/10** selected
objects were recovered. One output described a visibly detailed port crop as
uniformly dark. These are exploratory selected-object/localization results, not
overall vessel precision/recall or proof that the manual selections are all valid.
The requests used the v3 prompt; they were not automatically rerun after changes.
The provider-reported ledger increment was about $0.0037; conservative reservations
increased by $0.531968. The shared ledger ended at 24 calls and $1.591296 reserved.

The existing compact optical triage, with its thresholds unchanged, recovered
**6/10** selections at the same tolerance. This unmasked comparison can include
land and port structures; its other features are unreviewed, not established false
positives. `satellite_screen.compact_features` now exposes source-pixel locations
for the same components the triage already counted. These components are not automatically classified as ships. D100 adds independent
pixel support as described below; held-out validation is still required.

Vision prompt v4 adds usable/limited/unusable image status. Unusable output is an
abstention: contacts remain in `withheld_contacts` for audit instead of becoming
published ship observations, detail windows cannot establish negative evidence,
and comparison withholds both mismatch directions. The corresponding hosted
`20261016135525_vision_image_usability.sql` migration applies that gate to SQL.
Future results also record prompt/profile revision and input-image hash.

`argus/vision_evaluation.py` provides separate full-reference scoring using
maximum-cardinality one-to-one matching. Duplicates are false positives; misses
are false negatives; partial/capped output stays evaluated; unusable/withheld
output counts as pipeline misses, with a separate verified-model recall.
It rejects missing human-review assertions, duplicated scenes and changed images.
The eight saved operational reviews have templates but no complete human labels;
their accuracy fields correctly remain null.

Reproduce without paying for new requests:

```powershell
.venv/Scripts/python.exe scripts/evaluate_imagery_pack.py
.venv/Scripts/python.exe scripts/evaluate_vision.py --prepare --manifest data/validation/new-vision-labels.json
# Fill independent visible-contact labels in the manifest before scoring.
.venv/Scripts/python.exe scripts/evaluate_vision.py --manifest data/validation/new-vision-labels.json
```

Clean sources/crops, cached model answers and reports remain in ignored
`data/satellite-imagery/` and `data/validation/`. `--analyse` explicitly requests
up to ten bounded reviews, stops on failure, and skips completed/held results.

## Independent optical locations (D100)

New Sentinel-2 reviews retain raw model hints and their original coordinates.
Only a unique, uncontested compact feature within an assumed 32 source pixels
can anchor a hint. A verified scene water mask is also required before it can
claim a provisional AIS match or unmatched-image lead. Multiple possible features,
competing hints, missing masks and clutter remain unresolved. Additional compact
features are visible as **unclassified**, not detected ships. They cannot consume
AIS identities or raise dark-contact leads, but nearby pixels veto unsupported
claims that the image contains no contact. The 300 m AIS identity gate is unchanged.
Legacy/non-optical evidence keeps its existing gates.

A free replay of the ten saved model answers recovers **4/10** selected centers
within the original five-source-pixel tolerance after unique anchoring. Raw model
positions remain 0/10; unclassified feature recovery remains 6/10. This sample
informed development and is not held-out validation. These original source images
have no water masks, so replay anchors are deliberately **ineligible** for
operational associations. No additional model request was made. The script now
reports the anchored replay separately from raw/model and feature-only results.

Free saved-review rejoin reconstructs support from raw model output instead of
anchoring an already moved point. Original coordinates, pixel bounds and offsets
stay auditable. Native detail labels distinguish unclassified features.
`20261016140530_optical_pixel_support.sql` is deployed: private contacts retain
localization JSON, and hosted match/dark-contact gates enforce eligibility while
all nearby image evidence still vetoes image-absence claims. Isolated PostGIS
checks cover eligibility, metadata retention, source types and public-role denial.

### Busy water and the coastal map (D109)

`compact_features` stops at 101 bright spots and marks the image as clutter. In
such a busy image the pixel check above cannot run. On 16 Oct this left the ten
13 Oct Dublin Bay images with no leads at all. The AI had made 47 observations
there; the earlier v2 rules gave 25 leads, v5 gave 0. The coastal map also drew
692 unclassified spots as diamonds.

Comparison v6 treats a clutter observation as **not pixel-confirmed**, not as
unsupported:

- It can still raise an `image_without_ais` review lead. The lead carries
  `pixel_support: unavailable_busy_water` and a sentence in `reason` and
  `priority_reason`.
- It never claims an AIS identity. Within 300 m of an AIS position it stays
  `nearby_ais_review`, and it never counts as a vessel's match.
- Unsupported, ambiguous and contested observations keep the D100 gate.

The coastal map, the Coast Watch list and the SOC `contacts` index show AI
observations only. Unclassified spots stay in each image's own review. When an
image has more than 12, they are drawn as small marks without labels.

The free background pass re-checks saved reviews under v6 without new AI calls.
On the same ten images it gives 22 leads: 21 low and 1 medium. The hosted SQL
comparison (`argus.contact_position_eligible`) still applies the stricter D100
gate to clutter observations.

## Acceptance work still required for the full objective

| Area | Evidence required before calling it improved end to end |
|---|---|
| Tracking | Acquisition-time error and identity-switch rates on labeled tracks; uncertainty across gaps, turns and receipt-time jitter; epoch/provenance consistency in local and hosted joins; retention/import checks; freshness and throughput on the actual collector. |
| Dark-contact detection | Human-reviewed optical/radar fixtures with matched, unmatched, obscured and reception-gap cases; precision/recall and withheld-case counts by sensor/size/coverage; no conversion of missing evidence or association conflicts into confirmed silence. |
| AI implementation | Held-out visual localization, duplicate and miss rates; genuine cap/partial-result handling; model and prompt provenance; budget/crash/cache behavior; accuracy comparison against the non-AI screen. Verified image-token accounting does not establish detection quality. |
| All aspects of Brain | Detector-by-detector scenario coverage and meaningful negative controls for spoofing, route deviation, stopping, loitering and cable-risk cues; scoring and evidence-correlation audit; countdown/prediction uncertainty; sustained history-worker throughput; explainable operator review with no automatic action. |
| Product integration | Native map/list/review evidence stays consistent, offline exercise remains usable, hosted comparison semantics match Python, and changed evidence invalidates obsolete outcomes appropriately. |

Remaining engineering work includes held-out localization validation, calibration of temporal uncertainty, robust data
quality across every registered detector, empirical vision evaluation, global
assignment parity (SQL still uses greedy association), and sustained live worker
throughput. The new hosted database exists (D95) and the initial hosted backlog
has been checked (D97); this computer still requires its project-specific secret
key for the native worker. Local work is not blocked by that configuration step.
