# Vessel imagery and internet-cable risk demo pack

Nazar's imagery task: **six cable-risk demonstration cards** using real offshore
satellite vessel imagery, with clearly labelled simulated internet cables and
behavior. Two use Dublin coastal contacts and four use comparable dark North Sea
water off the Netherlands. The source imagery, original locations and historical
dates are retained; North Sea images are not presented as Irish observations.

**Start with [the internet-cable risk contact sheet](cable-risk/contact-sheet.png).**
The individual risk cards are 1200 × 900 PNGs, ready for slides or a fictional
investigation view. Cyan marks an exercise fibre-optic cable, red marks an exercise
track/course, and yellow outlines the selected vessel-shaped pixels. The cable
and behavior are simulated; the underwater cable is not visible in the satellite
image and its route is not a real surveyed cable location.

| Figure | Fictional vessel | Cable-risk scenario | Image |
|---|---|---|---|
| R01 | WICKLOW STAR / AM-IE-003 | Course change towards an internet cable | [PNG](cable-risk/R01-AM-IE-003.png) |
| R02 | HOWTH VOYAGER / AM-IE-004 | Loitering beside an internet cable | [PNG](cable-risk/R02-AM-IE-004.png) |
| R03 | NORTHSEA KESTREL / AM-NS-001 | Approaching an internet-cable corridor | [PNG](cable-risk/R03-AM-NS-001.png) |
| R04 | GREY HORIZON / AM-NS-002 | Repeated passes across an internet cable | [PNG](cable-risk/R04-AM-NS-002.png) |
| R05 | SHELF TRADER / AM-NS-003 | AIS unavailable near an internet cable | [PNG](cable-risk/R05-AM-NS-003.png) |
| R06 | DEEPWATER FINCH / AM-NS-004 | Contact inside an internet-cable corridor | [PNG](cable-risk/R06-AM-NS-004.png) |

The pack also includes **ten labelled source-image cards**, two Irish location
overviews and [an Irish vessel contact sheet](contact-sheet.png). Each source-image
card is 1200 × 800 pixels and includes its name/code, real location, date
availability, evidence labels and credit. The four Irish port contacts below
remain useful as normal-traffic comparisons; the risk cards use offshore contacts.

| Demo code | Fictional name | Real image location | Labelled image |
|---|---|---|---|
| AM-IE-001 | LIFFEY DAWN | Dublin Port | [PNG](vessels/AM-IE-001-liffey-dawn.png) |
| AM-IE-002 | HARBOUR FINCH | Dublin Port | [PNG](vessels/AM-IE-002-harbour-finch.png) |
| AM-IE-003 | WICKLOW STAR | Dublin Bay | [PNG](vessels/AM-IE-003-wicklow-star.png) |
| AM-IE-004 | HOWTH VOYAGER | Irish Sea off Dublin, east of Howth | [PNG](vessels/AM-IE-004-howth-voyager.png) |
| AM-IE-005 | LEE HORIZON | Cork Harbour, south of Lough Mahon | [PNG](vessels/AM-IE-005-lee-horizon.png) |
| AM-IE-006 | ATLANTIC ROWAN | Cork Harbour, eastern waterfront | [PNG](vessels/AM-IE-006-atlantic-rowan.png) |
| AM-NS-001 | NORTHSEA KESTREL | North Sea off the Netherlands | [PNG](vessels/AM-NS-001-northsea-kestrel.png) |
| AM-NS-002 | GREY HORIZON | North Sea off the Netherlands | [PNG](vessels/AM-NS-002-grey-horizon.png) |
| AM-NS-003 | SHELF TRADER | North Sea off the Netherlands | [PNG](vessels/AM-NS-003-shelf-trader.png) |
| AM-NS-004 | DEEPWATER FINCH | North Sea off the Netherlands | [PNG](vessels/AM-NS-004-deepwater-finch.png) |

Locate the contacts on the [Dublin overview](overviews/dublin-port-and-bay.png)
and [Cork overview](overviews/cork-harbour.png). These are optical images, not radar
images or live observations. The ships' actual identities and types are unverified.
The AM-IE / AM-NS codes are local demo IDs, not MMSIs or IMO numbers.

## Evidence and dates

- **Real:** the satellite pixels and their Irish coastal setting.
- **Fictional:** all assigned vessel names and demo codes.
- **Assumption:** manual selection of the vessel-shaped objects, without AIS matching.
- **Simulated:** internet-cable corridors, historical/projected tracks, loitering,
  course changes and AIS availability in the six cable-risk figures.

The Dublin source credits **2020** Sentinel data but gives no exact acquisition
date. Its publication on 16 December 2022 is recorded separately in the manifest.
The Cork source explicitly dates acquisition to **23 June 2026** and publication
to 1 July 2026. Neither scene is from the current Irish AIS recording.
The North Sea source credits **2016** data and was published on 4 October 2019;
its exact acquisition date is unavailable. It is a published false-colour
Sentinel-2 composite including near-infrared. Its colors are kept as supplied.

No ship pixels are synthesized, recoloured, sharpened or enhanced. The source
regions are displayed with nearest-neighbor enlargement and annotation outlines;
enlarging them adds no resolution. A single image cannot demonstrate unexpected
movement, loitering, AIS switch-off, spoofing or proximity to an underwater cable.
The six risk cards supply that separately labelled fictional scenario as visual
overlays, not new detector outputs or historical evidence of an incident. No
geographic distance, cable crossing time or operational risk level is derived
from source-image pixels. Human review remains visible on the risk cards.

## Sources and reuse

1. **Dublin:** [ESA — Dublin, Ireland](https://www.esa.int/ESA_Multimedia/Images/2022/12/Dublin_Ireland).
   Credit: “Contains modified Copernicus Sentinel data (2020), processed by ESA”.
   Use under [CC BY-SA 3.0 IGO](https://creativecommons.org/licenses/by-sa/3.0/igo/).
   The four Dublin cards, Dublin overview and their image adaptations retain that
   licence. Keep the credit and licence with reused images.
2. **Cork:** [EU Space — Cork ahead of Ireland's Presidency](https://eu-space.europa.eu/components/earth-observation-copernicus/image-of-the-day/cork-ahead-irelands-presidency-council-eu).
   Credit: “European Union, Copernicus Sentinel-2 imagery”. Its linked
   [EU legal notice](https://european-union.europa.eu/legal-notice_en) permits reuse
   of EU-owned content under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
   unless otherwise indicated. The image is credited to the European Union.
3. **North Sea:** [ESA — The Netherlands](https://www.esa.int/ESA_Multimedia/Images/2019/10/The_Netherlands).
   Credit: “Contains modified Copernicus Sentinel data (2016), processed by ESA”.
   Use under [CC BY-SA 3.0 IGO](https://creativecommons.org/licenses/by-sa/3.0/igo/).
   The four North Sea source cards and all six cable-risk cards retain that licence.

Changes by Argus Mara: selected display regions, enlargement, yellow outlines,
fictional names/codes and caption layout; risk figures add simulated cable and
behavior overlays. Both combined contact sheets are distributed under CC BY-SA
3.0 IGO, retaining the separate Cork credit where applicable. No ESA/EU endorsement is
implied. [manifest.json](manifest.json) records source and download URLs, source
hashes, selected pixel regions, output hashes and per-vessel demonstration notes.

## Handoff to Adam and Misha

Adam can insert the cable-risk PNGs directly into slides and use their contact sheet
to choose a vessel. Keep the provenance and attribution captions visible.

Misha can use `risk_scenarios[].image_path` in a **fictional investigation** view,
resolve `vessel_code` against `vessels[]`, and use `vessels[].image_path` for the
corresponding source-image card. Paths are relative to this folder.
An image name is not a confirmed ship identity. The current desktop photo slot
expects a photograph of a specific live MMSI, so this pack is not assigned to live
AIS contacts or to the fictional CORMORANT STAR replay. The application and shared
`demo/scenario.json` / `demo/alerts.json` contracts are unchanged.

## Verify or rebuild

View the committed PNGs with any image viewer; no server, Python package or internet
connection is needed. Validate the distributed files from the repository root:

```bash
python3 scripts/prepare_vessel_imagery.py --check
```

Rebuilding requires **Pillow and matplotlib for preparation only**. If they are
already available, run:

```bash
# Download the three exact reviewed source rasters, then render the figures.
python3 scripts/prepare_vessel_imagery.py --fetch

# Re-render using the existing local source files, without network access.
python3 scripts/prepare_vessel_imagery.py
```

Original rasters stay under ignored `data/satellite-imagery/`. Only the selected,
attributed presentation figures belong in this pack. Source hashes must match the
reviewed manifest; if a provider replaces a file, review it before updating its
hash or selection coordinates. No app/runtime requirements are added.
