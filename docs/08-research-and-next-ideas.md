# 8. Research check and next ideas

*Checked 7 October 2026 against the linked primary sources. This is a research and implementation note, not a claim that the external datasets have already been downloaded or tested in this repository.*

## What the sources support

| Question | Source-backed finding | Practical consequence |
|---|---|---|
| Is this Challenge 3? | The [EUDIS challenge page](https://eudis-hackathon.eu/challenges/) says Challenge 3 is defined by the local organiser; the Irish wording is recorded in our event notes. | Keep the Irish challenge statement attributed to its local source, rather than describing it as the EU-wide Challenge 3 text. |
| Can we obtain infrastructure and traffic layers? | [EMODnet Human Activities](https://emodnet.ec.europa.eu/en/human-activities-1) lists cables, pipelines and shipping density with query and download services. [EMODnet service docs](https://emodnet.ec.europa.eu/en/emodnet-web-service-documentation) describe WFS and bathymetry coverage services. | Data should record dataset name, snapshot date, licence, geometry precision and transformation from GeoJSON order. A display route is not necessarily an engineering-grade cable position. |
| Can SAR detections show contacts without an AIS match? | [Global Fishing Watch API concepts](https://globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/key-concepts) documents the SAR dataset and `matched='false'`. Its [data caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats) warn about false detections, incomplete coverage and matching limits. | Call these **AIS-unmatched SAR contacts**. Investigate AIS reception and matching before calling one a vessel with its transmitter off. |
| Is vessel length exact enough to prove an identity mismatch? | GFW's [SAR caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats) note image-resolution and training-label limits for length estimates. | Treat a large length difference as an identity **flag for review**, with measurement uncertainty and source attached. |
| Is depth a precise anchor limit? | [EMODnet Bathymetry](https://emodnet.ec.europa.eu/en/bathymetry) provides a harmonised model; [service documentation](https://emodnet.ec.europa.eu/en/emodnet-web-service-documentation) explains grid services. | The current 250 m threshold is an assumption for the demo. Do not present it as a universal physical rule or a navigational safety boundary. |

## Suggested additions after the seven-beat replay works

1. **A provenance drawer.** Each visible claim opens its source, date and classification (`real`, `reconstructed`, `simulated`, `fictional`, `assumption`). This makes the mixed-data demo easier to defend in questions.
2. **Uncertainty beside every countdown.** Keep the expected and earliest ETAs, show when and from which fix they were calculated, and mark the 250 m anchor threshold as an assumption. Calibrate later against recorded tracks.
3. **A separate real observation card.** Show one reviewed GFW SAR contact with its scene time, matching status and caveats. Keep it separate from the fictional tanker so a judge cannot mistake the composite narrative for a real incident.
4. **A replay baseline.** Run the same archived AIS period through a plain cable geofence and the proposed rules. Report alert counts per day, coverage, exclusions and the inspection method. Do not claim a false-alarm rate without labelled outcomes.
5. **An evidence manifest.** For each exported page, list item source, retrieval time, processing step and hash. This is more useful than a bare hash chain with no provenance.

## Research tasks still open

- Verify the Irish local Challenge 3 wording and judging criteria from an accessible official Irish page or organisers' materials before using a direct quote on slides.
- Confirm access terms, rate limits and exact payload fields for any GFW API request with a real account before implementation.
- Select a specific EMODnet cable and bathymetry dataset version, inspect its Ireland coverage and attribution terms, then record the chosen snapshot in `docs/sources.md`.
- Confirm the Danish AIS archive's current download endpoint and reuse terms before promising it as the quantitative evaluation dataset.

Keep these tasks out of the critical path to the simulated end-to-end demo.
