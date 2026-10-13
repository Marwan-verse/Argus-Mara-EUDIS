# Sources

## Irish coastal vessel presentation imagery (13 October 2026)

- [ESA — Dublin, Ireland](https://www.esa.int/ESA_Multimedia/Images/2022/12/Dublin_Ireland)
  — full-resolution Sentinel-2 optical raster, credited as 2020 data and published
  16 December 2022; exact acquisition date is unavailable. The page explicitly
  offers CC BY-SA 3.0 IGO. Four selected vessel figures and a location overview
  retain attribution and real-pixel / fictional-identity labels.
- [EU Space — Cork ahead of Ireland's Presidency](https://eu-space.europa.eu/components/earth-observation-copernicus/image-of-the-day/cork-ahead-irelands-presidency-council-eu)
  — Sentinel-2 image acquired 23 June 2026 and published 1 July 2026, credited to
  the European Union. Its linked [EU legal notice](https://european-union.europa.eu/legal-notice_en)
  permits reuse of EU-owned content under CC BY 4.0 unless otherwise indicated.
  Two selected vessel figures and a location overview retain that credit.
- [ESA — The Netherlands](https://www.esa.int/ESA_Multimedia/Images/2019/10/The_Netherlands)
  — Sentinel-2 optical false-colour composite including near-infrared, credited as
  2016 data and published 4 October 2019, offered under CC BY-SA 3.0 IGO. Four
  manually selected offshore contacts provide comparable dark northern European
  water; their real location remains the North Sea off the Netherlands.

The final [offline image pack](../demo/imagery/README.md) and
[manifest](../demo/imagery/manifest.json) record downloads, hashes, selected source
pixel bounds, output hashes, licences and changes. Original rasters remain under
ignored `data/satellite-imagery/`. These historical optical figures have no AIS
association. Six derived cable-risk figures add explicit simulated internet-cable
corridors and behavior, without georeferencing or a measured real cable distance.
They are presentation scenarios, not Brain detections or historical incidents.

## Space dataset review (8 October 2026)

These primary-source checks support the [Space dataset plan](10-space-dataset-plan.md).
They describe provider documentation; new account access, export schemas and Irish-region
availability remain to be verified before integration.

- [GFW per-contact SAR detections and footprints](https://globalfishingwatch.org/platform-update/2024-may-data-download-portal-new-dataset-released-featuring-vessel-detections-from-sentinel-1-sar/) — newer download fields and advertised publication delay.
- [GFW 4Wings reports](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report) and [API/download differences](https://globalfishingwatch.org/platform-update/2024-may-global-fishing-watch-apis-new-dataset-in-4wings-api-featuring-vessel-detections-from-sentinel-1-sar/) — grid-cell reports must remain separate from per-contact evidence.
- [GFW data caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats) — matching, acquisition coverage, false detections and estimated lengths.
- [Copernicus Sentinel-1 GRD processing](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html) and [area-request examples](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S1GRD.html) — calibration options and authenticated requests for selected areas.
- [EMODnet vessel-density metadata, revised 6 December 2025](https://ows.emodnet-humanactivities.eu/geonetwork/srv/api/records/0f2f3ff1-30ef-49e1-96e7-8ca78d58a07c) — 2017–2024 coverage, 1 km cells, density units, EPSG:3035, CC BY 4.0 and the 2024 satellite-coverage caveat.
- [Copernicus Marine Irish-region wave reanalysis](https://data.marine.copernicus.eu/product/IBI_MULTIYEAR_WAV_005_006/description) and [Toolbox introduction](https://help.marine.copernicus.eu/en/articles/7949409-copernicus-marine-toolbox-introduction) — modelled environmental context and account-based spatial/temporal subsets.
- [NOAA vessel traffic](https://coast.noaa.gov/digitalcoast/data/vesseltraffic.html) and [Danish historical AIS](https://www.dma.dk/safety-at-sea/navigational-information/ais-data) — public AIS sources with different geographic coverage; D19 selects Denmark for evaluation.
- [Kpler historical AIS](https://www.kpler.com/product/maritime/historical-ais) and [data services](https://www.kpler.com/product/maritime/data-services) — commercial historical access and filtering; no suitable demo export/licence has been obtained.
- [EOS LandViewer catalogue](https://eos.com/find-satellite/), [Esri Wayback explanation](https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/mapping/use-world-imagery-wayback) and [Soar Atlas download guide](https://about.soaratlas.com/blogs/how-to-get-free-satellite-imagery) — comparison/reference tools; distinguish basemap publication from acquisition and optical imagery from SAR.

## Source checks for the current build (7 October 2026)

- [EUDIS 2026 challenge page](https://eudis-hackathon.eu/challenges/) — EU-wide Challenge 3 is defined by each local organiser; the Irish maritime text needs an Irish source for direct quotation.
- [EMODnet Human Activities](https://emodnet.ec.europa.eu/en/human-activities-1) — cables, pipelines and shipping-density themes, with query/download services.
- [EMODnet service documentation](https://emodnet.ec.europa.eu/en/emodnet-web-service-documentation) and [Bathymetry](https://emodnet.ec.europa.eu/en/bathymetry) — vector and gridded depth access; record exact layer/version and licence when importing.
- [Global Fishing Watch API key concepts](https://globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/key-concepts) — SAR dataset and `matched='false'` filter; [data caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats) cover false positives, coverage and vessel-length limits.

The conclusions and proposed implementation choices from these checks are in [08-research-and-next-ideas.md](08-research-and-next-ideas.md). The older source list below is retained for historical reference; it is not a blanket verification of each claim.

This research was done on 24 Sep 2026. Most official sites couldn't be opened directly from the research environment. Event facts therefore come from the Irish edition's website source code, and the other facts come from search-result summaries of the pages below. Anything marked † in the docs was not re-verified.

## The event

- The Irish edition's website source, which mirrors the official page (index.html, updated 8 Sep 2026): https://github.com/fergal-adams/eudis-hackathon-ireland
- Official Irish page: https://dcuinnovate.com/eudis-hackathon/. More information on Notion: https://app.notion.com/p/EUDIS-Defence-Hackathon-2026-IRELAND-395608fde7e6805ea432c284d301b21b
- DCU:Innovate announcement: https://www.dcuinnovate.com/updates/ireland-s-first-defence-hackathon
- EUDIS challenges: https://eudis-hackathon.eu/challenges/
- EC announcements:
  - https://defence-industry-space.ec.europa.eu/registrations-are-now-open-5th-eudis-defence-hackathon-2026-08-31_en
  - https://defence-industry-space.ec.europa.eu/eight-host-organisations-5th-eudis-defence-hackathon-are-officially-confirmed-2026-06-18_en
- EUDIS mentoring: https://eudis-hackathon.eu/mentorship/
- "Mature teams" mentoring: https://eudis-hackathon.eu/eudis-defence-hackathon-2026-empowering-mature-teams-through-follow-on-mentoring/
- Terms and conditions: https://eudis-hackathon.eu/wp-content/uploads/2026/03/EUDIS-Defence-Hackathon-2026_TC.pdf
- Organisers on wanting "working prototypes": https://www.groundstation.space/hackathons/testing-defence-solutions-in-a-real-operational-setting-why-startups-and-smes-join-the-eudis-defence-hackathon/
- Other hosts' local challenges:
  - Sweden: https://liu.se/en/event/eudis-defence-hackathon-2026-sweden
  - Latvia: https://www.liaa.gov.lv/en/article/university-latvia-invites-teams-across-europe-join-eudis-defence-hackathon-2026-latvia
  - Portugal: https://eco.sapo.pt/2026/08/18/startup-leiria-abre-candidaturas-para-edicao-portuguesa-do-hackathon-de-defesa-europeu/
  - Austria: https://www.wko.at/ktn/news/eudis-defence-hackathon-2026-in-klagenfurt
- TensorX: https://www.siliconrepublic.com/start-ups/tensor-x-dublin-ireland-ai-infrastructure-eu-europe-us
- Deloitte Ireland (Kieran O'Neill): https://www.linkedin.com/posts/kieran-o-neill-72322b34_having-our-own-irish-defence-industry-base-activity-7495480494852132864-lAMN

## Past winners

- Autumn 2025 EU-wide final: https://defence-industry-space.ec.europa.eu/eudis-hackathon-autumn-2025-edition-eu-wide-pitching-competition-winnerseudis-hackathon-autumn-2025-2026-01-23_en
- EDF Info Days pitch (Trusk, RAID, True Sight): https://eudis-hackathon.eu/from-hackathon-winners-to-the-european-stage-three-eudis-teams-pitch-at-the-edf-info-days/
- Trusk: https://www.groundstation.space/hackathons/after-eudis-hackathon-success-dutch-team-trusk-selected-for-eu-defence-accelerator/
- Spring 2026: https://defence-industry-space.ec.europa.eu/eudis-defence-hackathon-spring-2026-meet-winning-teams-driving-innovation-airspace-defence-2026-03-30_en
- Scaled Autonomy (live flight): https://www.groundstation.space/defence/scaled-autonomy-demonstrates-the-worlds-first-autonomous-fpv-interceptor-drone-at-eudis-hackathon-netherlands/
- Spring 2025: https://defence-industry-space.ec.europa.eu/bringing-bold-ideas-frontline-eudis-hackathon-spring-edition-winners-announced-2025-07-15_en
- 2024 edition: https://defence-industry-space.ec.europa.eu/eudis-hackathon-2024-winning-teams-showcase-cutting-edge-innovations-warsaws-deep-tech-summit-2024-10-30_en
- EDTH winner with "23% faster than lawnmower search": https://github.com/JKKDY/EDTH-optimal-search

## Irish context

- Defence Forces using AI to cover shortfalls (EEZ about 7× land; 8 ships, crews for about 2; GUARD): https://www.irishtimes.com/ireland/2026/05/16/robots-in-the-military-how-the-defence-forces-is-using-ai-to-cover-shortfalls-in-resources-and-personnel/
- Subsea cables choke point:
  - https://www.irishexaminer.com/news/arid-41618941.html
  - https://www.csis.org/analysis/strategic-future-subsea-cables-ireland-case-study
- *Yantar* off Ireland (Nov 2024): https://www.irishexaminer.com/news/arid-41517743.html
- Shadow-fleet convoy west of Ireland (Apr 2026): https://www.irishtimes.com/ireland/2026/04/04/convoy-of-russian-shadow-fleet-tankers-monitored-off-west-coast/
- Naval Service boarding powers: https://www.irishtimes.com/ireland/2026/03/11/new-legal-powers-will-allow-naval-service-to-board-vessels-including-russias-shadow-fleet/
- National Maritime Security Strategy (Feb 2026):
  - https://www.gov.ie/en/department-of-defence/press-releases/minister-mcentee-launches-first-ever-national-maritime-security-strategy/
  - https://www.navaltoday.com/2026/02/26/ireland-launches-first-ever-national-maritime-security-strategy/
- Radar programme: https://defencematters.eu/ireland-thales-long-range-radar-air-surveillance/
- Drones during Zelensky's visit (Dec 2025):
  - https://www.thejournal.ie/drones-analysis-william-butler-yeats-dublin-6893629-Dec2025/
  - https://www.irishtimes.com/ireland/2025/12/04/drones-spotted-near-zelenskiys-flight-path-to-dublin-triggering-major-security-alert/
- Counter-drone buying:
  - https://www.irishtimes.com/ireland/2025/12/10/new-19m-anti-drone-capability-to-be-available-to-defence-forces-for-eu-presidency/
  - https://www.irishtimes.com/ireland/2026/07/10/drone-hunter-unmanned-aerial-weapons-to-guard-skies-during-irelands-eu-presidency/
- Offshore gap "procurement under way": https://www.irishexaminer.com/news/politics/arid-41908663.html
- Scorpion vehicles with AI slew-to-cue: https://www.irishtimes.com/ireland/2026/05/15/new-army-vehicles-under-french-deal-can-automatically-target-perceived-threats-using-ai/
- Sea-Scan and the Defence Innovation Challenge:
  - https://www.researchireland.ie/news/defence-innovation-challenge-winners/
  - https://www.siliconrepublic.com/innovation/trinitys-sea-scan-team-awarded-defence-innovation-challenge-winning-project-ai
- Defence Innovation Challenge 2026 (closes 29 Oct 2026): https://www.researchireland.ie/news/defence-innovation-challenge-2026/
- GUARD project: https://theguardproject.com/

## Challenge 3 deep dive (added 24 Sep 2026)

- **National Maritime Security Strategy 2026–2030:**
  - https://www.gov.ie/en/department-of-defence/publications/national-maritime-security-strategy-20262030/
  - Eolas: https://www.eolasmagazine.ie/government-publishes-first-national-maritime-security-strategy/
  - The planned centre: https://www.irishexaminer.com/news/spotlight/arid-41822300.html
- **Sea-Scan:**
  - Paper (weakly supervised DAS; 97.8% detection at 1.98% false triggers; ECOC 2026): https://arxiv.org/abs/2606.21326
  - DAS–AIS association on the Dublin–North Wales link: https://arxiv.org/abs/2607.02536
  - Project pages: https://www.tcd.ie/e3/news/sea-scan-project-to-uncover-dark-vessels-in-irish-waters-using-fibre-optic-cables/ and https://www.tcd.ie/scss/news/2025/sea-scan-project/
  - Innovation Award 2026: https://www.adaptcentre.ie/news-and-events/sea-scan-project-wins-innovation-award-at-2026-analytics-ai-awards/
- **Emerald Bridge Fibres** (Dublin–Holyhead): https://www.submarinecablemap.com/submarine-cable/emerald-bridge-fibres
- **Tanker *Blue*** (false flag, AIS off before the Irish EEZ, Aug 2025):
  - https://maritime-executive.com/article/ireland-tracks-shadow-tanker-as-it-avoids-sailing-the-english-channel
  - https://www.irishtimes.com/ireland/2025/08/08/russian-oil-tanker-operating-under-false-flag-enters-irish-controlled-waters/
- **Shadow fleet off the west coast** (2026): https://www.marineinsight.com/shipping-news/shadow-fleet-tankers-seen-along-irish-coast-as-they-avoid-english-channel/
- **EU defence ministers in Wicklow** (31 Aug–1 Sep 2026):
  - https://irish-presidency.consilium.europa.eu/en/events/informal-meeting-of-defence-ministers-fac-defence/
  - https://www.globalsecurity.org/military/library/news/2026/09/mil-260901-eeas01.htm
- ***Eagle S*** (speed 12→9 kn; drag line about 90 km):
  - https://gcaptain.com/baltic-sea-cable-probe-finnish-investigators-suspect-shadow-tanker-eagle-s-dragged-anchor-for-60-miles/
  - https://en.wikipedia.org/wiki/2024_Estlink_2_incident
- **Research Ireland Defence Innovation Challenge 2026** (intent deadline 15 Sep; closes 29 Oct): https://www.researchireland.ie/news/defence-innovation-challenge-2026/
- **Commercial AIS cable-watch services:**
  - NKT: https://www.nkt.com/products-solutions/lifecycle-cable-services/cable-monitoring-solutions/offshore/ais-subsea-asset-protection
  - Gatehouse: https://gatehousemaritime.com/solutions/critical-offshore-and-subsea-infrastructure-protection/monitor-protect-subsea-cables-and-pipelines/
  - Sentinel Proactive: https://sentinelproactive.com/industries/submarine-cables/
  - UltramapGlobal: https://ultramapglobal.com/
  - OSI: https://oceanspecialists.com/services/osi-cable-protection-services/
  - FiberSense: https://fibersense.com/digitalmarine/
- **Space layer:**
  - Sentinel-1D launch (6-day cycle with 1C; AIS payload): https://www.nasaspaceflight.com/2025/11/sentinel-1d-launch/
  - EMSA Copernicus Maritime Surveillance: https://www.emsa.europa.eu/copernicus.html
  - Ubotica CogniSAT-6 dark-vessel detection: https://ubotica.com/illuminating-the-invisible-how-ubotica-is-revolutionising-dark-vessel-detection/

## Battlefield and EU context

- Baltic GNSS interference, 122,607 flights in Jan–Apr 2025: https://www.gpsworld.com/123000-flights-disrupted-by-gnss-jamming/
- Poland GNSS disruption (2026): https://www.euronews.com/my-europe/2026/08/25/phones-drones-and-ships-running-blind-as-gps-malfunctions-across-poland
- 14-state maritime GNSS/AIS letter (Jan 2026): https://insidegnss.com/baltic-and-north-sea-states-warn-on-gnss-jamming-ais-spoofing-and-shadow-fleet-risks/
- Swarmer (fielded swarms are typically 3–8 drones): https://www.defenseone.com/business/2025/09/ukrainian-startup-has-re-invented-drone-swarming/408099/
- AI terminal guidance raising hit rates: https://thedefensepost.com/2025/11/19/ai-upgrade-ukrainian-drones/
- Jamming degrading GPS-guided munitions: https://www.washingtonpost.com/world/2024/05/24/russia-jamming-us-weapons-ukraine/
- Galileo OSNMA: https://www.euspa.europa.eu/newsroom-events/news/testing-operations-galileo-osnma-service-now-available-users

## Open data and tools named in the ideas

- **Ship tracking (AIS):**
  - Live: https://aisstream.io
  - Historical, Danish Maritime Authority: http://aisdata.ais.dk/
  - Historical, NOAA MarineCadastre: https://hub.marinecadastre.gov
- **Satellite:**
  - Copernicus Data Space Ecosystem (Sentinel-1/2): https://dataspace.copernicus.eu
  - Global Fishing Watch APIs: https://globalfishingwatch.org/our-apis/
  - Orbits and passes: CelesTrak https://celestrak.org, Skyfield https://rhodesmill.org/skyfield/
- **Infrastructure and seabed:**
  - EMODnet Human Activities (cables, pipelines): https://emodnet.ec.europa.eu/en/human-activities
  - EMODnet Bathymetry: https://emodnet.ec.europa.eu/en/bathymetry
  - INFOMAR: https://www.infomar.ie
- **Weather and ocean:**
  - Marine Institute ERDDAP: https://erddap.marine.ie
  - Copernicus Marine: https://marine.copernicus.eu
  - OpenDrift (including the Leeway SAR model): https://opendrift.github.io
- **Sanctions lists:** https://www.sanctionsmap.eu
- **Optimisation and quantum:**
  - D-Wave Ocean: https://docs.ocean.dwavesys.com
  - dwave-samplers (simulated annealing, simulated quantum annealing via `PathIntegralAnnealingSampler`): https://github.com/dwavesystems/dwave-samplers
  - D-Wave examples (routing, placement): https://github.com/dwave-examples
  - simulated-bifurcation (quantum-inspired, GPU): https://github.com/bqth29/simulated-bifurcation-algorithm
  - qiskit-algorithms: https://github.com/qiskit-community/qiskit-algorithms. The older Qiskit Optimization (https://github.com/qiskit-community/qiskit-optimization) was archived in Jul 2026; pin 0.7.0 if you use it.
  - CUDA-Q: https://github.com/NVIDIA/cuda-quantum
  - OpenQAOA: https://github.com/entropicalabs/openqaoa
  - Pulser (neutral-atom emulator, maximum-independent-set problems): https://github.com/pasqal-io/Pulser
  - QOBLIB (benchmarking methodology): https://github.com/ZIB-AOPT/QOBLIB
  - OR-Tools: https://developers.google.com/optimization
  - CBBA in Python: https://github.com/zehuilu/CBBA-Python
- **Swarm simulators:**
  - swarm-rescue (IP Paris; 2D SAR with no-GPS, no-comms and kill zones): https://github.com/emmanuel-battesti/swarm-rescue
  - VMAS: https://github.com/proroklab/VectorizedMultiAgentSimulator
  - PX4 multi-vehicle Gazebo: https://github.com/PX4/PX4-Autopilot/blob/main/docs/en/sim_gazebo_gz/multi_vehicle_simulation.md
  - Crazyswarm2: https://github.com/IMRCLab/crazyswarm2
- **Magnetic navigation:**
  - MagNav.jl and the MagNav Challenge data: https://github.com/MIT-AI-Accelerator/MagNav.jl
  - MagNav flight data on Zenodo: https://zenodo.org/records/12723700
  - US Air Force real-time MagNav demonstration: https://www.af.mil/News/Article-Display/Article/3408951/magnav-project-successfully-demonstrates-real-time-magnetic-navigation/
  - GSI Tellus: https://www.gsi.ie
  - INTERMAGNET (Valentia observatory): https://intermagnet.org
  - EMAG2v3: https://www.ncei.noaa.gov/products/earth-magnetic-model-anomaly-grid-2
- **GNSS spoofing and jamming data:**
  - Jammertest 2025: https://zenodo.org/records/21332689
  - Jammertest 2024: https://zenodo.org/records/15911359
  - FGI-JSDR: https://www.maanmittauslaitos.fi/en/research/research/gnss-specialists/fgi-gnss-jamming-and-spoofing-dataset-repository-fgi-jsdr
- **Visual geo-localisation, if you go the visual route:**
  - UAV-VisLoc: https://github.com/IntelliSensing/UAV-VisLoc
  - MegaLoc: https://github.com/gmberton/MegaLoc
  - AnyLoc: https://github.com/AnyLoc/AnyLoc
  - LightGlue: https://github.com/cvg/LightGlue
  - Aerial localisation dataset index: https://github.com/michaelschleiss/awesome-aerial-localization-datasets
- **Sensor-error simulators:**
  - gnss-ins-sim: https://github.com/Aceinna/gnss-ins-sim
  - pyins: https://github.com/nmayorov/pyins
  - kshana (young; check its outputs): https://github.com/ashfordeOU/kshana
- **Drone autopilots:** PX4 https://px4.io, ArduPilot https://ardupilot.org

## Offline interface display sources (8 October 2026)

- **Natural Earth 1:10m admin-0 countries**, Ireland and United Kingdom exterior rings simplified for the demo chart. Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_10m_admin_0_countries.geojson. Terms: https://www.naturalearthdata.com/about/terms-of-use/ (public domain). The raw file stays under ignored `data/maps/`; the prepared asset `ui/assets/coastline.json` records its SHA-256. Preparation: `scripts/prepare_demo_map.py`. This is display geometry, not a navigational chart, cable route or bathymetry source.
- **Natural Earth 1:110m and 1:50m admin-0 countries** provide the native app's global offline land display. Public domain: https://github.com/nvkelso/natural-earth-vector and https://www.naturalearthdata.com/about/terms-of-use/. `scripts/prepare_world_map.py` simplifies exterior rings into `ui/assets/world_land.json`; source SHA-256 values are embedded. Display geometry only, not a navigational chart.
- **NGA World Port Index Viewer** supplies global port reference points: https://fgmod.nga.mil/nauticalpubs-feature/rest/services/WPI/World_Port_Index_Viewer/MapServer/0. The compact `ui/assets/world_ports.json` contains 3,805 named points, WPI numbers and country codes. Source: real public US government data; points do not imply precise berth locations.
- **Historical TeleGeography Submarine Cable Map v2 snapshot** supplies 497 stylized cable system routes: https://github.com/yvonne-lo/submarinecablemap and https://raw.githubusercontent.com/yvonne-lo/submarinecablemap/master/public/api/v2/cable/cable-geo.json. The snapshot README states CC BY-NC-SA 3.0. The prepared `ui/assets/world_cables.json` is marked reconstructed. TeleGeography says its map routes are stylized, not surveyed cable positions: https://www2.telegeography.com/submarine-cable-faqs-frequently-asked-questions. Some systems may be planned. Display only; never use for alerts, crossing estimates or navigation. Commercial distribution needs a different source or permission.
- **NASA Earthdata GIBS Blue Marble Next Generation** provides optional global online imagery tiles: https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/. Tiles are cached only as viewed; they are neither live imagery nor used for detection. NASA data use guidance: https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy.
- **Kongsberg Foresight Traffic Display**, visual and workflow reference only: https://www.kongsberg.com/what-we-do/ocean-space/surveillance-monitoring/foresight/traffic-display/. Its chart-first view, selected-contact information and operational controls informed the console layout. No vendor assets copied.
- **Wärtsilä Navi-Harbour VTMS**, operator workflow reference only: https://www.wartsila.com/marine/products/port-optimisation/vtms. Sensor observations, traffic context and reviewable alerts informed the layout. No vendor assets copied.
