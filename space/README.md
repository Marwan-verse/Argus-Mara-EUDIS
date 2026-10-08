# Space workstream — Nazariy Buryak

The first implementation uses existing Global Fishing Watch (GFW) radar detections.
It needs no backend, image-processing packages or account for the offline example.
Run commands from the repository root with Python 3.9 or later.

## Update for teammates — 8 October 2026

The mentor-suggested dataset sources have been reviewed. The recommendation is to use
**GFW per-contact radar detections**, **Copernicus scene evidence**, then a small
**EMODnet context extract**. The complete source comparison, implementation order and
acceptance checks are in [the Space dataset plan](../docs/10-space-dataset-plan.md).

**Available now:** the offline association and length-review tools, two attributed historical
contacts, the Sentinel-1 catalogue importer, the separate 4Wings grid-report CLI, a normalized
AIS handoff, and offline evidence packs with hashed sources and explicit coverage.
**Still pending:** an adapter for the newer GFW export, actual overlapping Irish SAR/AIS
data, and a bounded EMODnet context extract. No newer export schema or account token was
available for this implementation; the verified historical CSV remains the supported source.

The two real contacts are from **2018 and 2021**; our Irish AIS recording began in **October
2026**. Keep them in separate historical examples. A real combined replay needs overlapping
AIS positions and radar acquisition times. GFW advertises roughly five-day SAR publication
delay; current regional availability and account access still need verification.

### Handoff to other workstreams

| Workstream | What Space supplies or needs |
|---|---|
| Data | Can normalize CSV fixes or the existing recorder's CSV/Parquet using `argus.ingest.ais`; see the schema below. Infrastructure, depth and the optional EMODnet extract remain Data's inputs. |
| Brain | Can consume the sidecar's association, custody candidates, length checks and unavailable reasons. Each exported contact has an `evidence_url`; Brain owns alert scores, countdowns and response ETAs. |
| Interface | Can link generated contact pages or reuse the local templates in `ui/space/`. The demo alert's existing placeholder is still unavailable until its owner connects it to the generated fictional pack. |
| Story/integration | Can use the two real contacts as historical examples, separate from the fictional tanker. Retain matching caveats and visible operator approval. |

Shared adapters and evidence handoffs can be developed together when they directly support
these tasks. Preserve the [two-file contract and change protocol](../docs/07-architecture.md).
Portable [codebase and interface skills](../docs/09-team-skills.md) are already in the repository
for teammates to install.

## Run offline

```bash
python3 -m argus.space --scenario demo/scenario.json --output data/sar/demo-space.json
python3 -m argus.ingest.gfw import space/examples/gfw-unmatched-contacts.csv --unmatched-only --output data/sar/real-contacts.json
python3 -m argus.space --scenario data/sar/real-contacts.json --output data/sar/real-space.json
python3 -m unittest discover -s tests -v
```

`demo/scenario.json` and `demo/alerts.json` remain the integration contract. Space writes
a **separate sidecar** with `detections`, retaining the existing contact fields and adding:

| Field | Meaning |
|---|---|
| `association` | `source_reported`, `local_ais_match`, or `unmatched` |
| `matched_mmsi` | A source-reported or locally associated MMSI; otherwise `null` |
| `provider_matched_mmsi` | The original provider association, unchanged by local matching |
| `association_label` | `reconstructed` for derived observed evidence; `simulated` for fictional/simulated input, or `assumption` |
| `association_evidence` | Association method, supplied/eligible AIS counts, position age or interpolation bracket, timestamp sources and receipt-time assumption |
| `dark_candidate` | No AIS association was found; review the contact |
| `length_check` | Check against the associated vessel's `ais_length_m`, or unavailable |
| `custody_candidates` | Reachable last-known vessels, each with a tentative length check |
| `unavailable_reasons` | Plain-language explanations of missing association, dimensions or scene evidence |
| `scene_evidence` | Evidence export only: scene acquisition interval and catalogue GeoJSON footprint, or an unavailable state |
| `evidence_url` | Evidence export only: page path relative to the generated pack root |

The sidecar also adds top-level `coverage`, `provenance`, `selection` and documented
`assumptions`. Readers may ignore these additive fields. `evidence_url` must be resolved
against the pack root; it is not relative to `demo/alerts.json`.

Brain can read these results; Interface can display the radar contact and review cue. This
command does not write alerts, change response ETAs or append historical contacts to the
fictional 2026 scenario. Real examples are a separate replay.

## Association and identity rules

- Interpolate AIS brackets only when the fixes are at most 600 seconds apart. Otherwise,
  project a past fix for at most 300 seconds. Never match against a future-only fix.
- Associate contacts within 1 km with a **one-to-one Hungarian assignment**, independently
  for each acquisition time and scene. Keep source-reported GFW associations.
- Real/reconstructed observations cannot locally associate with fictional/simulated AIS.
  Imported dimensions must be recorded at or before acquisition, no more than 24 hours old,
  and share the vessel's provenance. This expiry is an assumption, not an AIS standard.
  Legacy scenario dimensions require a past track fix within 30 minutes.
- A long AIS gap stays unmatched. For at most 30 minutes, list vessels reachable from their
  last fix assuming a maximum 30 kn speed. These are candidates, without a probability or
  a claim of regained identity. The speed, time limits and distance gate are assumptions.
- Flag a **possible length mismatch** when `abs(radar - AIS) > max(40 m, 25% of AIS length)`.
  Below 80 m or with missing/nonpositive lengths, the check is unavailable. Include the
  assumed ±30 m radar uncertainty and whether the discrepancy survives it.
- In the fictional demo, the 228 m contact has a plausible last-known candidate declaring
  180 m. The 48 m difference exceeds the 45 m nominal threshold, but does **not** survive
  the assumed radar uncertainty. It remains a tentative review cue.

## AIS handoff for Data

Normalized CSV columns are `mmsi,ts,lat,lon,sog_kn,cog_deg`. Optional columns are `name`,
`ais_length_m` and `label`. MMSI is nine digits; `ts` is ISO 8601 with an explicit UTC offset.
Lengths are metres and their row timestamps become the dimension observation times. Missing
dimensions stay unavailable. The default provenance label is required on the command line.

```bash
python3 -m argus.ingest.ais data/ais/fixes.csv --label real --output data/ais/handoff.json
python3 -m argus.ingest.ais data/ais/recording.parquet --schema recorder --label real --output data/ais/handoff.json
```

The recorder adapter selects position messages only. It uses `time_utc` where available,
otherwise labels `recv_utc` as an assumed observation time. Raw messages are excluded from
the handoff. AIS unavailable speed/course sentinels become `null`. Identical fixes are
deduplicated; conflicting fixes for one MMSI/time are rejected. Parquet uses the recorder's
existing optional `pyarrow` dependency; normalized CSV needs no packages. Mixed labels remain
visible per vessel and in `provenance_labels`; do not attach today's recording to the historical
contacts expecting an identity match.

## Generate an offline evidence pack

```bash
python3 -m argus.evidence
python3 -m argus.evidence --quicklook data/sar/sentinel1-quicklook.png
python3 -m argus.evidence --scenario demo/scenario.json --output data/sar/demo-review
```

The default pack is `data/sar/review/index.html`, with two historical contacts, source
attribution, scene coverage, length uncertainty and explicit unavailable states. The 2018
contact has bundled catalogue metadata; the 2021 contact does not. The quicklook must belong
to the single supplied scene. It is optional and must already exist locally.

`manifest.json` records input/output SHA-256 hashes, code hashes, filtering, acquisition ranges,
assumptions and licence/attribution. Source retrieval time is `null` when not recorded; the
export timestamp is separate. Coverage is sampled and never described as continuous. The
catalogue footprint is not GFW's processed detection footprint. Pages use local CSS/JS and
inline schematic maps, without external tiles or libraries. Open the generated `index.html`
directly or serve the repository root with `python3 -m http.server 8000`.

For an already normalized, contemporaneous contact file and AIS handoff:

```bash
python3 -m argus.evidence --contacts data/sar/contacts.json --ais data/ais/handoff.json --provenance data/sar/provenance.json --scene data/sar/scene.json --output data/sar/combined-review
```

Each contact page permits a **page-local** operator review note and printing. The note is not
persisted after reload and authorizes no operational action. Historical and fictional packs
stay separate. This export supplies the evidence handoff; the seven-beat stage replay and
connecting `demo/alerts.json` remain with Brain and Interface.

## Two verified real contacts

The original source rows are in [examples/gfw-unmatched-contacts.csv](examples/gfw-unmatched-contacts.csv).
They come from the public [Paolo et al. analysis dataset](https://doi.org/10.6084/m9.figshare.24309475.v4),
released under **CC BY 4.0**. Attribution: Paolo, Kroodsma, Davis and Hochberg (2024), Global
Fishing Watch. [provenance.json](examples/provenance.json) records the pinned download,
selection, and SHA-256 checksums.

| UTC acquisition | Position | Radar length estimate | Published category |
|---|---|---|---|
| 2021-09-05 18:07:10 | 53.222483 N, 5.398247 W, Irish Sea | 23.0 m | `unmatched` |
| 2018-11-13 18:14:33 | 51.391777 N, 5.993552 W, Celtic Sea | 128.5 m | `unmatched` |

Both have no published matched MMSI. **Unmatched is not evidence of hostile intent or
deliberate AIS shutdown**: reception gaps, vessels outside AIS requirements, detection errors
and association errors can all explain it. We have no declared AIS length for either contact,
so neither is presented as a real identity mismatch. The bounding box includes neighbouring
waters; it is not an Irish EEZ polygon. These two selected contacts are not a regional census.

Re-fetch the example without credentials (downloads only the first 10 MB of the 1.7 GB ZIP):

```bash
python3 -m argus.ingest.gfw public-example --output data/sar/gfw-example.json
```

The importer also accepts the full published per-contact CSV or a ZIP containing one CSV.
It validates the source category, preserves real timestamps and scene IDs, and filters to
`WEST SOUTH EAST NORTH` (default `-18 49 -4.5 57.5`). Other download schemas need an explicit
adapter; gridded reports are rejected as per-contact input.

The verified CSV adapter also supports `--start 2021-09-05 --end 2021-09-06` (start inclusive,
end exclusive, calendar dates mean midnight UTC). Contact IDs remain stable across filters.
Identical scene/time/position rows are deduplicated; conflicting records are rejected. Optional
matching, fishing and presence scores are preserved only when supplied by the source.

## Sentinel-1 scene preview

The Celtic Sea contact's scene was verified in the public Copernicus catalogue on 7 Oct 2026.
Its footprint covers the south-east Irish coast and adjacent waters. Download its metadata
and whole-scene quicklook without an account:

```bash
python3 -m argus.ingest.sentinel1 --scene S1A_IW_GRDH_1SDV_20181113T181420_20181113T181445_024573_02B292_EE59 --output data/sar/sentinel1-scene.json --quicklook data/sar/sentinel1-quicklook.png
```

Open the PNG locally. It is a **scene preview**, with insufficient detail to measure the
contact. The detections and length estimates come from GFW's published processing; we did
not calibrate a GRD image or run CFAR. Full imagery requires a Copernicus account and is
about 1.7 GB for this scene. See the official [OData download documentation](https://documentation.dataspace.copernicus.eu/APIs/OData.html#product-download).

If Python on macOS reports `CERTIFICATE_VERIFY_FAILED`, fix that Python installation's
certificate store. Where available, `SSL_CERT_FILE=/etc/ssl/cert.pem` uses the system CA
bundle. Keep certificate verification enabled.

## Current GFW API reports (optional account step)

Prepare a request offline:

```bash
python3 -m argus.ingest.gfw request --start 2026-09-01 --end 2026-09-08
```

To fetch it, set `GFW_API_TOKEN` in your environment and use `fetch` with the same date range.
The token is read only from the environment and never written to an output. Save credentials
in a git-ignored `.env` if needed; load them locally before running the command. The CLI does
not execute `.env` files.

```bash
python3 -m argus.ingest.gfw fetch --start 2026-09-01 --end 2026-09-08
```

This uses the [4Wings report endpoint](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report)
with `public-global-sar-presence:latest`, daily 0.01° cells and `matched='false'`. It saves the
provider's JSON or ZIP response intact, including caveats. Reports provide **gridded counts**,
not precise contacts, scene IDs or lengths. Use the per-contact download dataset for identity
checks; do not manufacture a vessel from each grid cell. See [GFW's explanation of API versus
download fields](https://globalfishingwatch.org/platform-update/2024-may-global-fishing-watch-apis-new-dataset-in-4wings-api-featuring-vessel-detections-from-sentinel-1-sar/).

## Workstream status

| Task | Status |
|---|---|
| Offline radar/AIS matching and identity check | Implemented and tested |
| One real unmatched radar example | Two published contacts verified and bundled |
| Sentinel-1 scene | Catalogue verified; public preview downloaded and inspected locally |
| GFW token and current Irish-region API pull | Request/fetch CLI ready; account step pending. Public-data path selected |
| Mentor dataset comparison and implementation plan | Documented 8 Oct; [plan and handoffs](../docs/10-space-dataset-plan.md) |
| Coverage manifest and AIS handoff | Implemented; CSV/recorder adapter and hashes, sampled coverage, timestamp/dimension safeguards |
| Newer GFW export adapter and recent combined replay | Pending actual export schema, access and overlapping data; no fabricated integration |
| Offline evidence pages for Brain and Interface | Implemented in `argus.evidence` and `ui/space/`; stage replay connection remains with its owners |
| Small EMODnet traffic-context extract | Planned after the core evidence handoff; coordinate with Data |
| Calibrated Sentinel-1 area crop | Optional account step; whole-scene preview already supported |
| Own ship detector or model training | Outside v1 under D15; published GFW detections remain the selected path |
| Ansys STK licence request | Optional, pending a SETU account; no dependency on it |

No satellite-pass ETA is inferred from a historical scene. The demo's next-look ETA remains
an explicitly labelled assumption.
