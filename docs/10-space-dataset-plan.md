# 10. Space dataset plan

*Research checked 8 October 2026. Owner: Nazariy Buryak. Status: proposed implementation;
this document records the research and handoff plan, not completed integrations.*

## Recommended scope

Use published **Global Fishing Watch (GFW) per-contact SAR detections** as the primary radar
input, **Copernicus Sentinel-1** for acquisition metadata and supporting imagery, and a small
**EMODnet** extract for geographic context. Build on the existing importers and Space sidecar.
Complete the core evidence handoff before adding context layers.

This follows D14, D15, D19, D23 and D25 in [DECISIONS.md](../DECISIONS.md): Python prepares
files, the browser presents them offline, and an operator decides. Consuming GFW's published
model outputs fits this plan; training our own detector remains outside v1. The existing
[demo contract](../demo/README.md) and [architecture](07-architecture.md) remain the boundaries.

## What already works

- `argus/space.py` associates radar and AIS observations and reports uncertain custody and
  length-review candidates in a separate sidecar.
- `argus/ingest/gfw.py` imports the pinned published per-contact CSV schema and can retrieve
  two selected historical contacts without credentials. Its request/fetch commands support
  a separate 4Wings grid report.
- `argus/ingest/sentinel1.py` retrieves scene metadata and an optional whole-scene quicklook.
- `space/examples/` contains two attributed contacts, provenance and one scene's metadata.

The current examples do not demonstrate independent ship detection from imagery or a real
vessel identity mismatch. Their timestamps are in 2018 and 2021, while the team's Irish AIS
recorder began in October 2026. No temporal overlap has been established. Actual downloaded
regional exports, account access and newer payload schemas still need inspection.

## Source comparison

The priorities below are implementation recommendations based on the linked documentation.
They are not claims that an authenticated request or regional download has succeeded.

| Source | Documented capability and access | Efficient use |
|---|---|---|
| [GFW per-contact downloads](https://globalfishingwatch.org/platform-update/2024-may-data-download-portal-new-dataset-released-featuring-vessel-detections-from-sentinel-1-sar/) | Updated vessel detections, provider AIS associations, estimated lengths and score fields; separate detection footprints are available as WKT. The provider advertises about a five-day delay. Newer exports require an explicit schema adapter. | Primary radar source. Inspect one available export and select a small Irish-region sample, retaining the bundled contacts as the account-free fallback. Verify account requirements, licence and actual date coverage. |
| [GFW 4Wings reports](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report) | Reports aggregate detections into grid cells; reported coordinates are cell centres. The CLI uses an API token. | Optional regional summaries. Never convert a cell count into a precise contact, scene ID or measured length. |
| [Copernicus Sentinel-1](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html) | The Process API returns selected areas with documented calibration and processing options. Its [examples](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S1GRD.html) require an OAuth client. Existing catalogue metadata/quicklook retrieval needs no account for the pinned example. | Verify scene identity, time and coverage first. A small calibrated crop is an optional later addition; a whole-scene quicklook cannot measure a vessel. |
| [EMODnet vessel density](https://ows.emodnet-humanactivities.eu/geonetwork/srv/api/records/0f2f3ff1-30ef-49e1-96e7-8ca78d58a07c) | Monthly and annual GeoTIFF grids cover 2017–2024 at 1 km resolution, in hours per square kilometre per month. Metadata specifies EPSG:3035 and CC BY 4.0. It flags reduced satellite AIS coverage from June 2024. | Export a small region and preserve units, period and projection. Prefer a documented earlier baseline, such as 2023, for general context; where historical comparison matters, use the corresponding available period. Low density is not an anomaly label. |
| [Copernicus Marine](https://data.marine.copernicus.eu/product/IBI_MULTIYEAR_WAV_005_006/description) | The Irish-region wave reanalysis supplies historical modelled conditions. The [Toolbox](https://help.marine.copernicus.eu/en/articles/7949409-copernicus-marine-toolbox-introduction) supports subsets by area, time and variable using a free account. | Optional environmental evidence for one contact's time and location. Identify it as modelled context. Do not change behaviour scores or response ETAs without a justified rule and appropriate validation. |
| [NOAA AIS](https://coast.noaa.gov/digitalcoast/data/vesseltraffic.html) | Historical vessel traffic from US Coast Guard AIS is available in downloadable formats including CSV. This does not establish an Irish archive. | Defer a second AIS ingestion path: D19 already selects the [free Danish CSV archive](https://www.dma.dk/safety-at-sea/navigational-information/ais-data) for rule evaluation, with Irish recordings for local examples. |
| [Kpler historical AIS](https://www.kpler.com/product/maritime/historical-ais) and [data services](https://www.kpler.com/product/maritime/data-services) | Historical data supports area/time filtering and API access; pricing and access are commercial. No suitable export or demo licence has been obtained. | Potential later source of AIS contemporaneous with Irish SAR scenes. It is not a dependency for the public-data v1. A licensed commercial sample would need a recorded change to D6's public-data scope. |
| [EOS LandViewer](https://eos.com/find-satellite/) | Its catalogue lists Sentinel-1 SAR alongside optical sources. | Optional browsing tool. Direct Copernicus access is the preferred integration path to avoid a duplicate provider adapter. |
| [ArcGIS Wayback](https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/mapping/use-world-imagery-wayback) | Archives versions of the World Imagery basemap. A version's publication date can differ from the underlying imagery's capture date. | Coastal or infrastructure reference, with capture metadata checked. Do not use the timeline as timestamped evidence of a moving vessel. |
| [Soar Atlas](https://about.soaratlas.com/blogs/how-to-get-free-satellite-imagery) | Its documented free satellite workflow chiefly uses Sentinel-2 and Landsat 8/9 and supports downloads. | Optional optical presentation context. It adds little to the selected radar ingestion path. |

## Implementation order

### Implementation update — 8 October 2026

| Item | Result |
|---|---|
| Source/coverage manifest | Implemented by `argus.evidence`: source/output/code hashes, source attribution, explicit selection and noncontinuous coverage. Unknown historical retrieval time stays unavailable. |
| Verified GFW CSV | Extended with UTC date filtering, stable IDs, deduplication and conflict rejection. Optional source scores are preserved. |
| Newer GFW export | Pending: no account token or actual newer export schema was available. No speculative adapter was added. |
| AIS handoff | Implemented for normalized CSV and recorder CSV/Parquet, preserving labels and dimension observation times; raw messages are excluded. Actual contemporaneous Irish data remains pending. |
| Evidence handoff | Implemented: static local pages, schematic scene footprints, optional previews, matching/length caveats, unavailable states and page-local review notes. Brain/Interface still own connecting their stage replay. |
| EMODnet context | Deferred to the optional Data context task; no density scoring or new GIS dependency was added to the core evidence pack. |

Commands and the additive field contract are in [Space's README](../space/README.md).
The original sequence below remains the reference for remaining work.

### 1. Reproducible source and coverage pack

Keep the two verified historical contacts as the guaranteed offline examples. Add a manifest
recording source/version, licence, retrieval time, acquisition times, regional selection,
processing steps and SHA-256 hashes. Distinguish a selected sample from a complete regional
dataset. Downloaded source material and credentials stay outside Git under the existing rules.

**Done when:** each example can be traced to its source and reproduced offline; missing
coverage is explicit. Sampling a ZIP prefix must not be presented as a regional census.

### 2. Newer GFW per-contact export adapter

Inspect an available newer export before defining its adapter in `argus/ingest/`. Preserve
provider identifiers, UTC acquisition time, coordinates, estimated length, association status
and documented quality fields. Filter a small region/time interval and deduplicate contacts.
Include matched and unmatched examples where the available export permits it. Keep the
existing static CSV adapter and the separate 4Wings report path working.

**Done when:** the inspected schema has regression coverage, invalid input is rejected, and
both provider matches and absent identities retain their documented meaning. If access is
unavailable, ship the manifest/evidence work using the existing contacts and report the adapter
as pending. Do not invent source rows to claim a completed integration.

### 3. AIS input handoff with Data

Agree a normalized AIS input containing MMSI, UTC time, latitude, longitude, speed in knots,
course in degrees and sourced vessel dimensions when available. Reuse the existing matching
rules only for observations with overlapping dates and plausible time/position gates. Preserve
source-reported associations separately from local associations. Missing vessel dimensions
make a length check unavailable.

**Done when:** incompatible historical/current data cannot accidentally form a local match;
real, reconstructed and simulated inputs remain distinguishable. A recent real replay is
conditional on actual SAR acquisitions and overlapping recorder coverage. The advertised
publication delay is not a promise of a usable scene before feature freeze.

### 4. Evidence handoff to Brain and Interface

Extend the Space sidecar with optional, documented provenance and coverage references,
association method and unavailable-data reasons. Prepare an offline evidence page showing a
contact's source, observation time, scene footprint or preview, matching result, and length
uncertainty. Browser presentation belongs in `ui/`; Python export belongs in `argus/`.

**Done when:** Brain can reference a review cue without changing its countdown/response
ownership, and Interface can display or link the evidence with external Wi-Fi disabled.
Keep historical contacts separate from the fictional tanker, and preserve visible operator
approval. Until evidence pages exist, keep the interface's unavailable state.

### 5. Bounded EMODnet context with Data

Choose one region and a documented density period. Produce a small offline extract with its
original units and metadata; convert EPSG:3035 at an explicit boundary. Coordinate public
infrastructure and bathymetry selections with Data. Record route precision and depth-model
limits; these are not engineering-grade cable locations or a universal anchor-reach rule.

**Done when:** a context layer has verified regional coverage and attribution, and can be
shown offline. Turning density into an anomaly score remains separate rule-development work.

### 6. Checks and integration

Implement on `feature/space-radar`, refreshing remote refs and incorporating current `main`
before changes. Commit coherent increments with their README/status updates. Keep the agreed
end-to-end demo and feature-freeze priorities ahead of optional datasets.

Check importer schemas, UTC handling, coordinate order, duplicates, date compatibility and
missing measurements. Run relevant existing tests after code changes and the contract checker
after either shared JSON file changes. Review an offline replay/evidence page. Keep all raw
downloads and secrets out of commits, and append a decision if an agreed team choice changes.

## Shared ownership

| Workstream | Integration |
|---|---|
| Space | Owns radar ingest, association results, scene provenance and this source plan. |
| Data | Supplies normalized AIS and owns the scenario, infrastructure and depth inputs. Collaborates on bounded context extracts. |
| Brain | Consumes Space review evidence; owns alert scoring, countdowns, response ETAs and `demo/alerts.json`. |
| Interface | Presents contacts, labels, uncertainty and operator approval; implements offline evidence presentation in `ui/`. |
| Story/integration | Maintains the distinction between historical evidence and the fictional narrative, and checks the complete demo. |

Shared adapters and evidence tasks may be implemented together where they directly serve
these handoffs. Optional fields need documentation; changes to existing keys, units or meaning
follow the [architecture change protocol](07-architecture.md#change-protocol).

## Interpretation limits

[GFW's caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats)
describe false detections, uneven coverage, shoreline exclusions and length-estimation limits.
An AIS-unmatched contact is a lead for review, not evidence of hostile intent or deliberate
shutdown. A missing contact is not proof that no vessel was present. Provider match labels
can check consistency of our processing, but are not independent ground truth for an accuracy
claim. False-alarm figures require labelled outcomes and belong to the Brain/Data evaluation.

Copernicus crops, Marine context and commercial AIS are optional improvements. None should
become a network dependency of the stage demo. Use the existing provenance values: `real`,
`reconstructed`, `simulated`, `fictional` and `assumption`.
