# How to detect suspicious maritime activities with SAR satellites

Argus Mara next-step plan — 12 October 2026

Goal: put one independently reviewed historical SAR contact beside AIS observations in the desktop app. A candidate for review is the output, not a finding of hostile intent. Live AIS integration is available now; raw SAR processing and historical contact integration below are planned work.

## First delivery before the 13 October feature freeze

Use the existing published-contact path in D23/D26 first. Space selects one historical Global Fishing Watch (GFW) detection for which coordinates, acquisition UTC, source and reuse terms are available. Data checks for AIS observations overlapping that acquisition; today's live AIS cannot validate a historical scene. Brain reviews the association and uncertainty. Interface imports the reviewed offline evidence pack as a separate historical case. Captain signs off the provenance and demo narrative.

If overlapping AIS or export rights are unavailable, show a sourced historical detection with “association unavailable” and retain the fictional replay. Do not substitute grid counts or scene-preview pixels for an individual measured contact. Do not promise a new raw-image detector before freeze.

## Open materials and access

| Material | Purpose | Access and constraint |
|---|---|---|
| Copernicus Sentinel-1 Level-1 GRD | Radar scene and acquisition metadata | Free/open satellite data; downloads generally require a free CDSE account and credentials. Catalogue discovery and authenticated download are separate steps. |
| ESA SNAP / Sentinel-1 Toolbox | Open-source calibration, masking and ocean object detection | Install from ESA; save version and processing graph. Its CFAR detector assumes calibrated input. |
| Global Fishing Watch published SAR detections | Fast, reviewed reference contact and comparison | Public viewing does not imply unrestricted redistribution; record the selected dataset's licence and any account/export requirements. API grid layers are not precise contact lists. |
| Existing normalized AIS imports and private recorder archive | Historical acquisition-time comparison | Retain source, received UTC and coverage. Danish public AIS is a fallback for methodology evaluation, not evidence of Irish traffic. Check archive reuse terms. |
| Natural Earth and EMODnet bathymetry | Land mask and environmental context | Natural Earth is public domain; record the specific EMODnet product's attribution/terms and resolution. Coarse depth does not establish anchor reach at a contact. |
| Python, Rasterio, GeoPandas, Shapely and QGIS | Local preparation, geometry and independent visual inspection | Open-source tools; pin versions in a separate SAR environment. Downloaded scenes and derived real-data packs remain in ignored `data/sar/`. |

Sources checked on 12 October 2026:

- Copernicus data access: https://www.copernicus.eu/en/copernicus-satellite-data-access
- CDSE catalogue and downloads: https://documentation.dataspace.copernicus.eu/APIs/OData.html
- ESA SNAP: https://step.esa.int/main/
- ESA ocean object detector: https://step.esa.int/main/wp-content/help/versions/9.0.0/snap-toolboxes/org.esa.s1tbx.s1tbx.op.feature.extraction.ui/operators/ObjectDetection.html
- ESA ship-detection tutorial: https://eo4society.esa.int/wp-content/uploads/2022/01/OCEA01_ShipDetection_Trieste.pdf
- GFW SAR layer: https://globalfishingwatch.org/platform-update/new-detections-from-synthetic-aperture-radar/
- GFW limitations: https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats

## Raw-scene pilot after freeze

1. Space + Data: choose one Irish Sea scene with contemporaneous AIS coverage, plus a separate held-out scene. Record product ID, footprint, start/end UTC, mode, polarization, orbit, pixel spacing versus effective resolution, source URL, download date, licence and SHA-256. Gate: actual access and time overlap verified, no credential in Git.
2. Space: follow ESA's GRD workflow in SNAP: orbit application where available, applicable border/thermal noise removal, radiometric calibration to linear sigma-nought, geographic land masking and CFAR ocean object detection. Verify the operator sequence and geocoding against the tutorial for the selected product; preserve the graph XML and parameter values. Avoid unvalidated smoothing that erases small ships. Gate: a geolocated candidate table and thumbnails that another teammate can reproduce.
3. Space: visually review candidate patches against land, ports, offshore structures, wakes and noisy sea clutter. Record retained and rejected candidates with reasons. Report apparent extent and uncertainty only when measured on calibrated/geocoded pixels; a whole-scene preview is insufficient for length. Gate: independent review of every retained candidate in the pilot.
4. Data: normalize acquisition-time AIS with `argus/ingest/ais.py`. Preserve gaps, coverage and observation times; never bridge a long gap or use future dimensions. Existing dimension expiry is an assumed 24 hours (D26), not a sensor guarantee. Gate: counts and UTC range documented; unavailable coverage remains explicit.
5. Brain + Space: reuse `argus/space.py` to compare nearby acquisition-time observations. Use documented time/position uncertainty and plausible motion bounds, including geolocation error and AIS age. Do not adopt an arbitrary universal match radius. Preserve provider matches separately from local candidate associations. Show ambiguous, matched, unmatched and coverage-unavailable cases. Gate: parameters justified on the first scene and unchanged on the held-out scene.
6. Brain: review explainable cues such as an AIS reception gap, repeat proximity, course/speed changes or radar/AIS dimension disagreement beyond stated uncertainty. These are review leads. Do not infer fishing, anchor deployment, sabotage or deliberate AIS switch-off from one unmatched contact. Gate: benign alternatives and missing evidence recorded for each cue.
7. Interface: expose separate historical SAR and acquisition-time AIS layers, an acquisition UTC badge, scene footprint, uncertainty and a source-linked evidence panel. Build through the existing optional Space sidecar; preserve `demo/scenario.json` and `demo/alerts.json`. Never match real contacts to fictional ships or apply fictional countdowns to them. Gate: offline pack opens after network removal; operator acknowledgement sends no action.

## Team handoff and verification

| Owner | Deliverable | Acceptance |
|---|---|---|
| Space — Nazariy | Contact sidecar, scene manifest, processing graph, review patches | Source hashes, coordinates and acquisition UTC agree; missing measurements explicitly null |
| Data — Ihor and Bohdan | Normalized AIS file and coverage note | Observation UTC overlap verified; coordinate order and knots preserved |
| Brain — Nazar and Myroslav | Association report and review cues | Uncertainty assumptions visible; ambiguous cases retained; no threat-probability claim |
| Interface — Adam and Marwan | Historical-case layer and evidence review | Separate from live and fictional observations; offline opening and visible provenance |
| Captain — Mykhailo | Reviewed demo case and wording | Only verified capabilities claimed; human approval visible |

Reuse the current pack workflow (see `space/README.md`) before adding a new importer:

```text
python -m argus.evidence --scenario demo/scenario.json --output ui/evidence
python scripts/check_contracts.py
python -m unittest discover -s tests
```

The first command regenerates the fictional fallback only. Real SAR packs use the documented Space handoff and ignored `data/sar/`; they must not overwrite `ui/evidence/` with downloaded material. Native smoke check: `python run_gui.py --check`. Browser changes, if later needed, require the full npm checks in AGENTS.md and regenerated committed bundles.

Measure reviewed candidate counts per scene, false positives per scene/sea area, matching rate only where AIS coverage is adequate, ambiguous counts and processing time. State the vessel-size and sea-state limits. Detection recall needs an independent truth set; AIS-unmatched counts alone cannot establish it. Preserve a held-out scene and report small sample size rather than extrapolating operational accuracy.

## Definition of done

One reproducible historical case opens offline with its SAR acquisition time, review patch or attributed published contact, overlapping AIS or explicit missing coverage, association method, uncertainty, provenance, source/licence and human review record. The familiar fictional demo still passes its contracts. No automated operational response exists.
