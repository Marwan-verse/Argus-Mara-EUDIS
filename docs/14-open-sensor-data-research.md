# 14. Open sensor data: magnetic field, aircraft, radar — what can improve Argus Mara

*Research by Nazar Kyrychenko (Brain), 16 October 2026. "Probed" means an anonymous request from the
team laptop succeeded on 16 Oct 2026; everything else comes from the linked documentation and was not
re-tested. Nothing here is implemented yet. The earlier space-weather (Kp) idea was removed: it only
explained GPS errors indirectly and made the spoofing rule harder to explain.*

## Short answer

1. **The magnetic field cannot track ships with open data.** Drop it (details below).
2. **Aircraft ADS-B is the best new open source for us**, in two ways:
   - **real positions of our own responders**. The Air Corps C295 maritime patrol aircraft and the Coast Guard helicopters broadcast ADS-B;
   - **a direct, measured GNSS-quality signal** over the Irish Sea, from the integrity values aircraft report.
3. **There is no open radar** (coastal, HF or military) for the Irish Sea. Satellite radar stays the only
   radar: Sentinel-1 through GFW detections (already planned in [doc 10](10-space-dataset-plan.md)).
   New here: compute the **real next Sentinel-1 pass** from open orbit data instead of the assumed pass time in `argus/fleet.json`.

## Verdict per source

| Source | Open access | What it gives | Use for Argus Mara | Verdict |
|---|---|---|---|---|
| **adsb.lol** API `api.adsb.lol/v2/point/{lat}/{lon}/{nm}` | Probed: anonymous, JSON (readsb format). History dumps are ODbL; API terms not confirmed | Live aircraft: position, speed, callsign, registration, type, military flag (`dbFlags`), GNSS integrity `nic`/`rc`, accuracy `nac_p`, `sil` | Real responder positions; GNSS-interference indicator | **Do first** |
| **OpenSky Network** REST `states/all` | Probed: anonymous bbox query works. 400 credits/day anonymous, more when registered; OAuth2 for accounts; non-commercial free | Live state vectors (no NIC/NACp in REST) | Fallback for responder positions | Fallback |
| **CelesTrak** GP elements | Probed: JSON for SENTINEL-1C (62261) and 1D (66315) | Orbits, so pass times over a point | Real "next Sentinel-1 look" | **Do** |
| **ESA Sentinel-1 acquisition plans** (KML) | Public page lists 1C and 1D plans | Planned imaging swaths, ~3-week windows | Whether the pass actually images the Irish Sea | With CelesTrak |
| **GFW Events API** (gaps, loitering, encounters) | Free token, non-commercial. The gaps dataset is a *prototype* | Reviewed AIS-off, loitering and encounter events | Benchmark our gap and loiter detectors on real events | Do after the demo |
| **GFW SAR detections** | Already in `argus/ingest/gfw.py` | Radar contacts with or without AIS | Dark-vessel evidence | Already planned (doc 10) |
| **EMODnet Human Activities WFS** | Probed: 89 pipelines in the Irish Sea box (11 Irish); `platforms` and `windfarms` layers too; telecom-cable layers almost empty for Ireland | Real asset geometry | Real pipelines and platforms beside the illustrative cables | Do (Data workstream) |
| **EMODnet Bathymetry** | Open, documented | Depth along routes | Replace the 250 m anchor-reach assumption with per-segment depth | Open task since doc 08 |
| **VIIRS Boat Detection** (EOG) | Free account; public only after 45 days | Lit boats at night (mostly fishing) | Historical context only | Low |
| **Marine Institute SmartBay hydrophone** (ERDDAP, CC BY 4.0) | Open | Ambient sound level, Galway Bay only | Not near our cables | Low |
| **INSN seismic network** (FDSN code EI) | Open | Land seismometers | Cannot locate ships | No |
| **HF coastal radar** | No open Irish Sea feed found | Surface currents | Drift: use Copernicus Marine instead | No |
| **Umbra / Capella open SAR** (CC BY 4.0, AWS) | Open samples at fixed sites | Very high-resolution radar images | Pitch visuals only, not our area | No |
| **Kystverket (NO), Digitraffic (FI) AIS** | Open, live | AIS for Norway or the Baltic | Test detectors on more real traffic; not Irish | Optional |
| **INTERMAGNET Valentia** (BGS GIN, probed) | Open | Earth's magnetic field at one observatory | Cannot see ships | **Drop** |

## Why the magnetic field does not work

- A steel ship disturbs the magnetic field only close by. A vendor table gives about 0.5–1 nT for a
  1000-ton ship at 244 m. The anomaly falls with the cube of the distance: twice as far, eight times
  weaker. Airborne magnetic anomaly detection (used against submarines) works at hundreds of metres, not miles.
- The only open magnetic data near Ireland is observatory data (Valentia). It measures the whole
  Earth's field at one point on land and cannot see a ship in the Irish Sea.
- Seabed magnetometers along cables would work only within tens to hundreds of metres. No such open data exists;
  fibre sensing (Sea-Scan) already covers "something is on the cable".
- Magnetic maps are useful for **navigation without GPS** (MAGNAV, [doc 02](02-ideas.md) §3), a different challenge.

## Proposal 1: real responder positions from ADS-B

**Today:** `argus/fleet.json` puts every aircraft and helicopter at its base, with assumed readiness.

**Seen on 16 Oct 2026 at about 10:00 UTC** (`api.adsb.lol`, 250 nm around 53.4 N 6.0 W, 514 aircraft):

- callsign `C285`, type C295, registration `285`, military flag, airborne at 18 000 ft west of Kerry;
- `CGI115`, AW189, registration `EI-IRG`, the Shannon Coast Guard helicopter, low over the Shannon estuary;
- `IRL281`, PC-12 (Air Corps).

**Change:**
- if a fleet asset is airborne and seen, `argus.responders` uses its real position and ground speed. Readiness is 0, and the label is "real, ADS-B, seen N s ago";
- otherwise it keeps the base and the assumption.

**Limits:**
- military aircraft may switch ADS-B off; low helicopters far offshore may be out of receiver range;
- a position is not tasking: a human still decides who goes.

**Owner:** `argus/responders.py` and `fleet.json` are not in the Brain file list. They need an agreed owner.

## Proposal 2: measured GNSS quality from aircraft

**Idea:** every ADS-B v2 aircraft reports how good its GPS position is (`nic`, `nac_p`). When several
civil aircraft in one area report degraded values at the same time, that measures GNSS interference
directly. This is the method behind public GPS-jamming maps.

**Change:**
- a new layer gives "GNSS degraded in this area since HH:MM (k aircraft, real)";
- `ais_spoofing` then notes that AIS jumps in that area may come from GNSS jamming or spoofing nearby;
- interference near a cable is itself worth reporting. It is evidence, not an excuse.

**Limits:**
- in our sample, 79 of 514 aircraft had `nic` 0, mostly military types (Hawk, Lynx) that report no
  integrity at all;
- filter: ADS-B version 2, no military flag, at least 3 aircraft, a minimum time window;
- low NIC also comes from steep banking or equipment faults, so one aircraft proves nothing.

## Proposal 3: real next Sentinel-1 pass

**Today:** `fleet.json` has an assumed `pass_times_s`.

**Change:**
- propagate the CelesTrak elements of Sentinel-1C and 1D, and check the ESA acquisition plan KML for that swath;
- show "next possible radar look in 5 h 20 min (real orbit, plan checked)";
- needs an SGP4 library (`sgp4`, MIT licence), a new dependency.

## Proposal 4: benchmark detectors on GFW events

- Pull GFW gap, loitering and encounter events for Irish waters with a free token.
- Run our detectors on the same vessels' AIS and report agreement, not accuracy (GFW events are estimates and the gaps dataset is a prototype).

## Sources

- adsb.lol history and licence: <https://github.com/adsblol/globe_history_2025/releases>; API comparison <https://flyitalyadsb.com/en/dati/confronto/>
- readsb field meanings (nic, rc, nac_p): <https://www.adsbexchange.com/?p=1897>
- NIC-based GPS-jamming method and caveats: <https://flightradar24.com/data/gps-jamming>, <https://insidegnss.com/?p=191777>
- OpenSky REST limits: <https://flyitalyadsb.com/en/dati/confronto/> (secondary); docs copy <https://git.carrubanet.duckdns.org/VALLONGOL/SXXXXXXX_FlightMonitor/src/commit/894eb20e1d18849fce2bfc9bd15b82e175d90979/opensky-api-master/docs/free/rest.rst>
- Air Corps C295 MPA: <https://www.janes.com/defence-intelligence-insights/defence-news/defence/ireland-completes-receipt-of-c295-maritime-patrol-aircraft>, <https://www.navalnews.com/?p=46408>
- Coast Guard helicopter units: <https://www.helis.com/database/sqd/Dublin_Coast_Guard/>
- Sentinel-1 acquisition plans: <https://sentinels.copernicus.eu/copernicus/sentinel-1/acquisition-plans>; constellation change 2026: <https://dataspace.copernicus.eu/node/3949>
- CelesTrak GP data: <https://celestrak.org/NORAD/elements/gp.php?NAME=SENTINEL-1&FORMAT=json>
- GFW Events API: <https://globalfishingwatch.org/our-apis/documentation/docs/v3/events.md>; caveats <https://globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats>
- EMODnet Human Activities WFS: <https://ows.emodnet-humanactivities.eu/wfs?service=WFS&request=GetCapabilities>
- VIIRS Boat Detection: <https://payneinstitute.mines.edu/eog/viirs-boat-detection-vbd>
- SmartBay hydrophone: <https://erddap.marine.ie/erddap/info/galway_obs_hydrophone/index.html>
- INSN: <https://fdsn.org/networks/detail/EI/>
- Ship magnetic signature: <https://ftp.soest.hawaii.edu/pibhmc/Calibration_Manuals/maggy.pdf>, <https://www.liverpool.ac.uk/~cmi/mag/magInf.html>
- Umbra open SAR: <https://registry.opendata.aws/umbra-open-data/>; Capella: <https://registry.opendata.aws/capella_opendata/>
- Kystverket AIS: <https://kystverket.no/en/navigation-and-monitoring/ais/access-to-ais-data>; Digitraffic: <https://digitraffic.fi/en/marine-traffic>
