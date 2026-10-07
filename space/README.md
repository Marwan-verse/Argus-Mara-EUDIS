# Space workstream — Nazariy Buryak

The first implementation uses existing Global Fishing Watch (GFW) radar detections.
It needs no backend, image-processing packages or account for the offline example.
Run commands from the repository root with Python 3.9 or later.

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
| `dark_candidate` | No AIS association was found; review the contact |
| `length_check` | Check against the associated vessel's `ais_length_m`, or unavailable |
| `custody_candidates` | Reachable last-known vessels, each with a tentative length check |

Brain can read these results; Interface can display the radar contact and review cue. This
command does not write alerts, change response ETAs or append historical contacts to the
fictional 2026 scenario. Real examples are a separate replay.

## Association and identity rules

- Interpolate AIS brackets only when the fixes are at most 600 seconds apart. Otherwise,
  project a past fix for at most 300 seconds. Never match against a future-only fix.
- Associate contacts within 1 km with a **one-to-one Hungarian assignment**, independently
  for each acquisition time and scene. Keep source-reported GFW associations.
- A long AIS gap stays unmatched. For at most 30 minutes, list vessels reachable from their
  last fix assuming a maximum 30 kn speed. These are candidates, without a probability or
  a claim of regained identity. The speed, time limits and distance gate are assumptions.
- Flag a **possible length mismatch** when `abs(radar - AIS) > max(40 m, 25% of AIS length)`.
  Below 80 m or with missing/nonpositive lengths, the check is unavailable. Include the
  assumed ±30 m radar uncertainty and whether the discrepancy survives it.
- In the fictional demo, the 228 m contact has a plausible last-known candidate declaring
  180 m. The 48 m difference exceeds the 45 m nominal threshold, but does **not** survive
  the assumed radar uncertainty. It remains a tentative review cue.

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
| Full GRD download, calibration and own ship detector | Pending account/image-processing work; GFW is the selected shortcut |
| Ansys STK licence request | Optional, pending a SETU account; no dependency on it |

No satellite-pass ETA is inferred from a historical scene. The demo's next-look ETA remains
an explicitly labelled assumption.
