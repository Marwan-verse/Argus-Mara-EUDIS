# 2. The ideas

The briefs below are ranked. There is one recommendation (★), the best alternative for each of the other two challenges, and two wildcards. Each brief covers the problem, what to build, the demo, how to prove it works, the data, the team it needs, the market, the risks, and why it can win.

> **One story behind all three.**
> - Ireland has a vast sea, a few crewed ships, critical infrastructure on the seabed, and a hostile fleet sailing past it.
> - Autonomy multiplies the people Ireland has.
> - Whichever challenge you pick, tell that story. It is the one the jury lives with.

| # | Idea | Challenge | One line | Best if your team is mostly… |
|---|---|---|---|---|
| ★1 | **ANCHOR WATCH** | 3: Space-enabled maritime domain awareness | Sees the ship coming *before* its anchor hits the cable, and tells the watch officer what can get there in time | software, data, AI, geospatial |
| 2 | **ONE SHIP, TWENTY EYES** | 2: Swarm coordination | Lets one patrol ship and one operator run 10–20 drones that keep working when comms are jammed. Allocation is solved with quantum optimisation and benchmarked honestly. | drones, robotics, simulation, operations research |
| 3 | **MAGNAV ÉIRE** | 1: Navigation without GNSS | "Navigate by the rocks": quantum-ready magnetic navigation on Ireland's own national magnetic map, plus a detector for when GNSS starts lying | estimation, physics, signal processing, quantum |
| W1 | SWARM-AS-GPS | 1 or 2 | A swarm that becomes its own positioning constellation in a jammed area | robotics researchers with ranging hardware |
| W2 | WHO LAUNCHED IT? | 3 | Works out which vessel launched the drones seen at sea (Dublin, Dec 2025) | data or AI teams that want an unusual angle |

---

## ★ 1. ANCHOR WATCH: early warning for Ireland's undersea lifelines (Challenge 3)

> *"Sea-Scan hears the anchor on the cable. ANCHOR WATCH sees the ship coming hours before, knows who it is, and tells you what can get there in time."*

In seamanship, an *anchor watch* is the lookout kept at night to catch a dragging anchor. This is that watch for the nation's seabed.

### What makes it special: five things the judges will remember

1. **A countdown, not a map.** Other teams will show ships on a map. Every ship ANCHOR WATCH flags gets a **timer to the cable it threatens**, and every response option shows whether it beats that timer.
2. **Anchor physics.** An anchor can only reach the seabed where the water is shallow enough, roughly the continental shelf. So you watch only the segments that can physically be hit, which means far fewer false alarms.
3. **An identity check from space.** Satellite radar gives a rough size for every ship, to within tens of metres. If a 250 m tanker claims in its AIS messages to be a 60 m fishing boat, it is lying, and you flag it.
4. **Sea-Scan's partner, not its rival.** Sea-Scan listens to the cable itself. ANCHOR WATCH sees the ship hours earlier, from far away, and knows who it is.
5. **Proof on a real case.** Replay the *Eagle S* incident and show when your alarm would have fired, well before the cable broke.

### The problem

- **The assets are critical.** About 11 transatlantic fibre cables pass through or near Irish waters. So do the gas pipelines that bring most of Ireland's gas † and the power interconnectors (EWIC, Greenlink, and the Celtic Interconnector in about 2027–28 †).
- **The threat is live and nearby.**
  - The *Yantar* loitered near cables and a pipeline off Ireland in Nov 2024, flying drones.
  - Since Mar 2026, **Russia's sanctioned shadow-fleet tankers route west of Ireland**, some in convoy. That is the class of ship that cut Baltic cables by dragging anchors (*Eagle S*, Dec 2024 †).
- **There are very few people to watch.**
  - The EEZ is about 7× Ireland's land area.
  - The Naval Service has **8 ships but crews for about 2 at sea**.
  - There is no military primary radar until 2027–28 and no subsea surveillance †.
- **The gap is attention and time, not data.**
  - In the Baltic cases, the tell-tale behaviour was visible in ordinary ship-tracking data while it happened †. The alarm came when the cable failed.
  - Most cable faults worldwide are caused *accidentally* by anchors and fishing gear †. Early warning is worth money even when there is no sabotage.
- **It is the Department of Defence's own brief.** The National Maritime Security Strategy (Feb 2026) has two relevant objectives:
  - Objective 2: protect critical undersea infrastructure.
  - Objective 3: improve maritime domain awareness.

### What you build

`ingest → keep custody → spot behaviour → score risk → predict → recommend → evidence`

1. **A fused maritime picture.** Combine:
   - live ship-tracking (AIS) data;
   - vessel detections from Sentinel-1 radar satellites;
   - vessel risk lists (EU, UK and US sanctions; reflagging; age);
   - cable and pipeline routes;
   - seabed depth;
   - weather.
2. **Custody through the dark.** When a ship switches its AIS off, keep its identity:
   - Predict its possible positions from its last known motion.
   - Re-acquire it with satellite radar. Radar sees through cloud and at night, which matters in Ireland.
   - Radar detections that match no AIS signal are *dark vessels*. The system links them back to known tracks by checking which ships could physically have reached that point.
3. **Behaviour detectors, all explainable:**
   - **Anchor-drag signature:** a merchant ship underway at an unusually low speed for its type and route, with speed oscillations and heading/course divergence, sustained over kilometres. The thresholds should be learned, not guessed.
   - Loitering or slow transit over infrastructure.
   - Survey-like patterns over a cable by a vessel that isn't a survey ship.
   - AIS switched off or on near infrastructure.
   - Ship-to-ship rendezvous.
   - Identity or position spoofing: impossible jumps, conflicting vessel IDs (MMSIs).
   - **Identity check from space:** compare the ship length measured on satellite radar with the length the ship declares in AIS. A big mismatch means a false identity.
4. **Risk that is aware of the infrastructure:**
   - Only count seabed an anchor can physically reach (a depth mask). The continental shelf matters; the deep Atlantic mostly doesn't.
   - Weight each cable or pipeline segment by how critical it is.
   - Factor in the vessel's risk profile.
   - Use context to suppress false alarms: storm shelter, designated anchorages, pilot boats, normal fishing grounds.
5. **Prediction.** Time until the vessel reaches the nearest at-risk segment, which segment it is, and where the vessel will be when each response asset could arrive.
6. **Decision support.** Course-of-action cards, each showing whether it arrives before the crossing:
   - hail on VHF channel 16;
   - notify the cable or energy operator and the maritime security centre;
   - the next free satellite radar pass, or a commercial SAR tasking;
   - an Air Corps C295 sortie;
   - the nearest Naval Service ship;
   - a ship-launched drone (for example GUARD).
7. **A one-click evidence pack.** A timeline, track, imagery chips and raw messages, hash-chained so they can't be altered unnoticed. It is for the Gardaí, legal follow-up and partners. The boarding-powers legislation is being drafted now.
8. **Optional: a watch-officer brief.**
   - An LLM running on **sovereign EU compute (TensorX)** summarises the alerts in plain language.
   - It is strictly grounded in the structured alert data, and every sentence cites the evidence behind it.
   - Keep it a garnish, not the product.

**It connects to what Ireland already funds:**
- **Sea-Scan** (fibre sensing on the cable): a Sea-Scan alert makes ANCHOR WATCH rank the candidate vessels nearby. An ANCHOR WATCH alert puts that cable segment on high alert. This is multi-domain fusion, one of the challenge bullets.
- **GUARD** (long-endurance ship-launched drones) is the obvious asset for getting eyes on a vessel.

### The 90-second demo

The scenario is *clearly labelled as simulated*, uses a fictional vessel name, and is set among real AIS traffic around Ireland.

1. A map of Ireland with the cable and pipeline corridors. Anchor-reachable segments glow. Live ship traffic is moving.
2. **T+0:** a sanctions-listed tanker (fictional name) transits north-west of Mayo with a convoy, then **goes dark**.
3. **T+2h:** a Sentinel-1 pass finds an unmatched radar target on its projected track. ANCHOR WATCH says: *"custody regained, 93% match"*.
4. **T+3h:** AIS returns. The ship is at 4.1 kn where its peers do 12 kn, with oscillating speed, over about 120 m of water (within anchor reach), heading for a cable. **Alert:** *"Anchor-drag signature. 12 km to the shelf segment. Crossing ETA 1 h 35."*
   - Explanation chips show why: *speed 3× below class norm · course variance ×6 · sanctions-listed · anchor-reachable depth*.
5. **The action panel** shows what can arrive in time:
   - Hail now ✅
   - Notify operator ✅
   - C295 from Baldonnel, ETA 1 h 10 ✅
   - Naval Service ship, ETA 6 h ❌
   - Next free radar pass 18:40 ❌, so request commercial radar (SAR) tasking ✅
6. The operator approves. The evidence pack is generated, and the brief is read out in one sentence.

### How you prove it: numbers against a baseline

| Metric | How | Baseline |
|---|---|---|
| **Warning time** | Replay tracks reconstructed from public reporting of *Eagle S*, *Yi Peng 3* and *Newnew Polar Bear*. Measure minutes from alert to cable crossing. | "Detect on damage" = 0 min |
| **False alarms per day** | Run a week of real AIS around Ireland and check the top alerts by hand | Naive geofence: "any vessel under 6 kn within 1 km of a cable" |
| **Dark-period custody** | Share of AIS gaps bridged by a radar re-acquisition in replay | Tracks dropped at the gap |
| **Latency** | Time from AIS message to alert | — |

### Data (all open; register for keys this week)

| Need | Source |
|---|---|
| Live AIS | aisstream.io (free websocket API with global terrestrial coverage) |
| Historical AIS (training, false-alarm tests) | Danish Maritime Authority AIS archive; NOAA MarineCadastre |
| Satellite radar and optical | Copernicus Data Space Ecosystem (Sentinel-1 radar, Sentinel-2 optical); Global Fishing Watch radar vessel detections and AIS gap events (free for non-commercial use) |
| Cables and pipelines | EMODnet Human Activities (telecom cables, power cables, pipelines) |
| Seabed depth | EMODnet Bathymetry; INFOMAR (Irish seabed mapping) |
| Vessel risk | EU sanctions vessel annex (Reg. 833/2014), UK and OFAC lists |
| Weather context | Met Éireann; Marine Institute weather buoys (ERDDAP) |
| Satellite passes | CelesTrak orbit data (TLEs) + Skyfield |

**Stack:** Python (FastAPI, Polars/DuckDB, GeoPandas/Shapely, H3), scikit-learn/LightGBM, Skyfield, and a MapLibre GL + deck.gl front end. Optionally, an OpenAI-compatible LLM endpoint (TensorX).

### Build plan

- **Before the event** (declare this as prior work): data connectors, the infrastructure and depth layers, a map UI skeleton with replay, a first rule-based detector, and a scenario generator.
- **At the event:** the learned behaviour scoring, radar-satellite fusion and custody, prediction and course-of-action cards, the evidence pack, backtest numbers, polish and the pitch.

### Team (4–6)

- **Data engineer:** AIS streaming and storage.
- **ML / analytics:** behaviour models and backtests.
- **Geospatial / satellite radar:** Sentinel-1 detections and fusion.
- **Front end:** map, replay and action cards.
- **Lead (you):** the operator story, mentor interviews, business model, pitch.
- **Bonus:** anyone with Naval Service, Coast Guard or shipping experience.

### Market and follow-on

**Buyers:**
- The Department of Defence and Defence Forces (National Maritime Security Strategy).
- The Irish Coast Guard.
- Cable and energy asset owners (EirGrid interconnectors, Gas Networks Ireland, cable operators and hyperscalers).
- Insurers and offshore wind (Ireland targets 5 GW by 2030 †).
- EU coastal states (the Baltic especially) and EU security agencies. The EU Action Plan on Cable Security (Feb 2025 †) creates demand.

**Money:**
- **Research Ireland Defence Innovation Challenge 2026:** Area 1 is space-based situational awareness. It **closes 29 Oct** and needs an eligible Irish research-body lead †.
- **ESA BIC:** your product runs on space data.
- EUDIS mentoring.
- The European Defence Fund, which needs a consortium of 3+ entities from 3 countries.
- TensorX credits and a Defence Forces RTI trial.

**Model:** a subscription per protected asset or area, plus integration.

### Risks and mitigations

- **AIS coverage thins far offshore.** Plan a satellite-AIS partner for the roadmap. In the demo, operate near the coast.
- **Radar-satellite revisit gaps.** Recommend commercial tasking and fuse with fibre sensing.
- **False alarms.** Use an explainable ranking, contextual suppression, and a measured false-alarm rate.
- **"Isn't this Windward, Kpler or Global Fishing Watch?"** Those are generic maritime-risk platforms. Your answer:
  - ANCHOR WATCH is **infrastructure-centric**: segment-level risk with anchor-reach physics.
  - It is **predictive, with feasibility-aware decision support**.
  - It **fuses Irish in-situ sensors** like Sea-Scan.
  - It is **sovereign and deployable on premises**.
- **Sensitivity.** Use public data only. Fictional names in scenarios. Human decides; nothing kinetic.

### Why it can win

- **Technological maturity:** it is software-only, so it can be built for real in three weeks plus the event. It gives a live, end-to-end demo with real numbers.
- **Operational relevance:** it is the Department of Defence's own challenge and maps to two strategy objectives. The shadow-fleet threat is topical in October 2026.
- **Market potential:** defence *and* commercial buyers, since accidental damage alone justifies it, plus a sovereign angle.
- **Every sponsor can say yes:** DoD (their challenge), DF RTI (a trial), ISA/ESA BIC and Ubotica (space data), TensorX (sovereign AI), Deloitte (buyer and integration), Research Ireland (Area 1).
- **EU level:** the Baltic states lived this threat, so relevance is obvious to every Member State.

**Stretch modules:**
- **Threat forecast, like a weather forecast.** A watchlist of sanctioned vessels heading for Irish waters, built from their AIS departures and past routes. It shows who will pass the Irish shelf in the next few days and which satellite passes will cover them, so scarce ships and aircraft can be planned ahead.
- **A second mission on the same engine:** "Which vessels could have launched the drones seen at sea?" (see W2).

---

## 2. ONE SHIP, TWENTY EYES: a ship-launched swarm for the empty sea (Challenge 2)

> *"Ireland can crew two ships. Let each one see like twenty."*

### The problem

- **Few ships, huge area.** A patrol ship's own sensors cover a circle of a few tens of nautical miles †. With 8 ships, crews for about 2, and an EEZ 7× the land area, most of the sea is unwatched most of the time.
- **Ireland is building the drones.** GUARD (Tyndall, DF-funded) makes long-endurance drones that launch from Naval Service ships in rough seas. But **one crew can't hand-fly ten drones**, so the missing layer is the *swarm brain*.
- **Real swarms are small.** Fielded swarms in Ukraine are typically **3–8 drones** (Swarmer). Coordinating larger swarms under jamming is the open gap.
- The Defence Forces is explicitly using AI "to cover shortfalls in resources and personnel".

### What you build

The software layer that lets **one operator supervise 10–20 drones**.

- **Mission modes.** Pick *one* for the demo:
  1. **Search and rescue (SAR):** a person in the water off the Irish coast. This mode best shows the maths, and it is emotionally resonant.
  2. **Identify contacts of interest:** dark vessels cued by satellite or AIS. This links to Challenge 3.
  3. **Cable-corridor patrol.**
- **Where to look (SAR mode).** Real drift science:
  - **OpenDrift's Leeway model** (the standard used in Norwegian SAR), driven by Copernicus Marine currents and Met Éireann winds.
  - A probability map that updates with **Bayesian search theory**: each fruitless search lowers the probability in that cell. The same maths located the wreck of Air France 447 †.
- **Who looks where: optimisation using quantum simulation.**
  - **Get the maths right first.** A plain one-drone-per-sector assignment is solved exactly and instantly by the classical Hungarian algorithm. A **QUBO** (the problem format quantum and quantum-inspired solvers take) only makes sense once you add the pairwise terms that make the real problem hard:
    - overlapping coverage, since two drones searching adjacent cells gain less than double;
    - keeping a relay chain back to the ship connected;
    - deconflicting airspace and radio channels.
  - Solve it several ways:
    - simulated annealing;
    - **simulated quantum annealing** (`PathIntegralAnnealingSampler` in D-Wave's `dwave-samplers`). This is literally "optimisation using quantum simulation", and it runs on a laptop.
    - **QAOA on a statevector simulator**, for small instances only (a laptop manages about 20–26 qubits, e.g. 4 drones × 5 sectors);
    - quantum-inspired simulated bifurcation (GPU) and, if you get access, D-Wave's hybrid solver.
  - Benchmark against CP-SAT or HiGHS (optimum or bound), greedy and a CBBA auction, with equal time budgets. Report the optimality gap, the share of feasible answers and the time to reach a target gap.
  - **Optional quantum-native twist:** treat relay placement as a *weighted maximum independent set*. Neutral-atom quantum computers solve that natively, and you can run it on Pasqal's Pulser emulator.
  - Motion inside each sector stays classical. This hybrid split is honest and standard.
- **When comms break.**
  - **CBBA runs on board**, is decentralised, and survives lost links.
  - **The QUBO re-planner runs on the ship** whenever links are up. It doesn't depend on a particular solver, so it is ready for real quantum hardware.
  - When links drop (range limits or a jamming zone), drones fall back to the auction with whichever neighbours they can reach.
  - Lost-link behaviour: finish the current plan, go to a rendezvous, then return. **Never engage.**
- **Human on the loop.**
  - The operator sets intent and constraints ("search here; keep 2 nm from vessel X; return with 20% battery").
  - The operator approves any vessel investigation, and can recall everything.
  - Full logs.

### The demo

- An 8–12-drone sim off Galway Bay or Howth, with the drift cloud evolving, drones fanning out, and live re-allocation when a jamming zone appears.
- Then the moment of detection.
- Show two panels side by side: the swarm vs the **IAMSAR standard search pattern** (the International Aeronautical and Maritime SAR manual's parallel-track or expanding-square search).

### How you prove it

- **Search performance:** median time-to-find and P(success) at 60 minutes over **500 Monte Carlo drift scenarios**, vs the IAMSAR pattern using the same drones.
  - The target is a result like the EDTH winner's "23% faster than lawnmower".
- **Resilience:** P(success) as the link-loss rate goes from 0% to 80%.
- **Quantum, honestly:** a solver table with optimality gap and runtime by instance size, and a clear statement of where classical still wins.

### Data and tools

- **Drift and ocean data:** OpenDrift; Copernicus Marine (CMEMS); Met Éireann; EMODnet coastline.
- **Solvers:**
  - `dwave-samplers` for simulated annealing and simulated quantum annealing;
  - `simulated-bifurcation`, quantum-inspired, on GPU;
  - QAOA via qiskit-algorithms, PennyLane, CUDA-Q or OpenQAOA. Note that qiskit-optimization was archived in Jul 2026, so pin 0.7.0 if you use it.
  - OR-Tools CP-SAT for the classical ground truth.
  - For a fair benchmark, follow the QOBLIB methodology.
- **Simulation:**
  - A lightweight 2D Python sim for the Monte Carlo runs.
  - For a quick start, the **swarm-rescue** simulator (IP Paris) already has 10-drone SAR with no-GPS, no-comms and kill zones.
  - For visuals, use deck.gl, or PX4/ArduPilot SITL + Gazebo for 3–5 vehicles.
- **Compute:** ask TensorX whether their credits include raw GPU access. If so, use it for GPU quantum-circuit simulation (CUDA-Q or cuQuantum), which is a nice sponsor tie-in.
- **Optional hardware:** 2–3 small drones executing the allocation indoors, if the venue allows. Ask at the drone workshops.

### Team

- A simulation or robotics developer.
- An optimisation or operations-research person, ideally curious about quantum.
- A front-end developer.
- The lead.

### Market and follow-on

- Navies and coast guards (the Irish Coast Guard, RNLI †, EMSA).
- Offshore wind operations and maintenance.
- Mountain and wildfire search.
- Partnering with GUARD is the natural path.
- Also a candidate for the Defence Innovation Challenge 2026 (defence capability development, or societal resilience).

### Risks

- **Quantum over-claim.** Benchmark honestly.
- **Simulation-only demo.** Add a small real flight, or a replay of a real flight log.
- **Scope creep.** Stick to one mission mode.

### Why it can win

- It targets the crewing crisis directly, and it builds on Ireland's own GUARD programme.
- It is one of the few entries likely to treat the quantum requirement *properly*.
- The drift-science realism plus the IAMSAR baseline gives the jury a hard number.

---

## 3. MAGNAV ÉIRE: navigate by the rocks (Challenge 1)

> *"Cameras can't see through Irish cloud. Radio can be jammed. The magnetism of the rocks under your feet can't be."*

### Why this and not visual navigation

- **Visual navigation is the crowded default**: Auterion, Spleenlab, and dozens of Ukrainian modules. It struggles at night, in cloud and fog, and over water, which describes the Irish operating environment.
- **Magnetic-anomaly navigation is different:**
  - It is passive: it emits nothing, so it can't be detected and can't be jammed.
  - It works in all weather.
  - It is the one quantum-sensor navigation method that has been **flight-tested** (Q-CTRL, SandboxAQ †).
  - There is no European sovereign equivalent yet †.
- **Ireland already has the map.** The Geological Survey's **Tellus** programme flew *low-altitude* airborne magnetic surveys over most of the island †. It is open data, and a national asset nobody uses for navigation.
- **Quantum sensor data you really use.** The scalar magnetometers used in airborne surveys (caesium vapour) are *optically pumped atomic sensors*, which is quantum sensing. The public **MIT/USAF MagNav Challenge** flight dataset contains exactly this kind of data. That answers the challenge's "develop or use data from quantum sensors" honestly.

### What you build

1. **A navigation filter.** It matches magnetometer readings against the map, running on top of the inertial navigation (a particle filter or EKF).
   - It uses realistic motion-sensor error models: MEMS vs navigation-grade vs **cold-atom quantum accelerometer**.
   - It uses realistic magnetometer models: fluxgate vs **optically pumped**.
   - **An honest nuance to show:** gyro drift dominates horizontal error, so a quantum accelerometer alone doesn't fix it. Model a *hybrid*: a classical accelerometer running at a high rate, with a cold-atom sensor correcting its bias.
2. **Real-flight validation** on the MagNav Challenge data (MagNav.jl). This includes correcting for the aircraft's own magnetic interference (Tolles–Lawson compensation).
3. **An Irish scenario** on the Tellus map:
   - The map is upward-continued to flight altitude.
   - The daily magnetic variation is removed using **Valentia Observatory** (INTERMAGNET) data.
   - Uncertainty is inflated during geomagnetic storms.
4. **"Detect the lie."** Compare GNSS with the inertial/magnetic solution and catch a slow *drag-off* spoof, the hardest kind to spot.
5. **A navigability map of Ireland**, with a route planner that trades distance for accuracy. For example: "Route B is 6% longer, but error stays under 60 m."

### The demo

1. The same flight twice, side by side. The GNSS spoof starts at minute 3.
   - The baseline drone is quietly dragged kilometres off course.
   - MAGNAV ÉIRE raises a spoofing alarm and navigates on, with its particle cloud locked to the magnetic landscape.
2. A slider switches sensor quality (fluxgate → optically pumped → future) to show what quantum sensors actually buy you.
3. The navigability heat map of Ireland.

### How you prove it

- Position error over time vs inertial-only dead reckoning, on real flight data.
- Time to detect the spoof, and its false-alarm rate, measured on **real spoofing recordings** (Jammertest 2024/2025 from Norway, the Finnish FGI-JSDR repository, TEXBAT). Synthetic attacks are too easy to catch.
- How accuracy changes with altitude and sensor noise.
- **Be honest:** the biggest gains come from compensation and map quality, not the magnetometer's noise floor. The quantum sensor's advantage is being *absolute and drift-free*. That honesty will impress the quantum experts in the room.

### Data and tools

- **Maps and flight data:**
  - MagNav.jl, which has a Docker image and ready-made EKF and particle filters, compensation models and a Cramér–Rao bound.
  - The MagNav Challenge flight data, about 0.1–0.2 GB per flight and auto-downloaded.
  - GSI Tellus magnetic grids.
  - EMAG2v3, a global magnetic grid, for offshore and high altitude.
  - INTERMAGNET Valentia (VAL) observatory data.
  - The Copernicus DEM (elevation).
- **Sensor-error simulators:** gnss-ins-sim and pyins. The young kshana simulator has MEMS, tactical and cold-atom sensor models; check its outputs before relying on it.
- **Closing the loop in an autopilot simulation:**
  - Feed your position fix into PX4 (external global-position fusion) or ArduPilot (`GPS_INPUT`, EKF3 source switching).
  - Inject faults with ArduPilot's `SIM_GPS1_JAM` and `SIM_GPS1_GLTCH` settings.
  - PX4 already carries jamming and spoofing states in its `GNSS_INTEGRITY` message.
- **Code:** Python or Julia with NumPy/SciPy and FilterPy.

### Team

- 1–2 people who know estimation (Kalman or particle filters).
- A geophysics or signal-processing person.
- A geospatial or visualisation person.
- The lead.

### Market and follow-on

- **Customers:** resilient navigation for drones, aircraft and ships.
- **Product:** "navigation-grade magnetic maps as a service" for Europe.
- **Funding routes:** ESA NAVISP †, the European Defence Fund, a DF RTI flight trial, and the Tyndall quantum ecosystem.

### Risks

- **Magnetic interference from motors on small multirotors.** Target fixed-wing or VTOL aircraft with a sensor boom first, and validate on real survey data.
- **Estimation expertise.** It is the most technically demanding idea, so it needs someone who has built filters before.

### Variants

- **Seabed terrain navigation** using INFOMAR bathymetry for uncrewed surface and underwater vessels inspecting cables. Underwater there is *never* GNSS.
- **Ship-relative navigation** so GUARD-type drones can find a moving deck when GNSS is jammed.

### Why now

- The US Air Force has demonstrated real-time MagNav.
- In Sep 2026, a DIU/Honeywell airliner flight reportedly navigated for more than 4 hours without GPS †.
- Q-CTRL has shown GPS-free quantum *gravimetric* navigation at sea.
- Aircraft-scale MagNav is maturing fast. Drone-scale MagNav and planning routes around navigation quality are still open, and that is your niche.

### Why it can win

- It is the most **novel** entry likely in the room.
- It is visibly Irish: it uses national map data and the Valentia observatory.
- It hits the challenge's quantum-sensor sentence *exactly*.

---

## Wildcards

### W1. SWARM-AS-GPS (Challenge 1 or 2)

In a jammed area, the swarm becomes its own positioning constellation:
- A few members keep a trusted position fix: at the edge of the jammed bubble, over magnetically rich ground, or tethered to a ship.
- The others locate themselves using drone-to-drone ultra-wideband (UWB) ranging plus camera-and-motion-sensor odometry.
- A distributed factor graph fuses the measurements.
- The swarm reshapes its geometry to keep position uncertainty low (the same idea as GNSS "dilution of precision").
- Choosing **which drones act as anchors or relays** is a natural QUBO.

It is elegant and bridges both challenges. The risk is high: it needs ranging hardware or a very good simulation to convince.

**Starting points:**
- The MILUV multi-drone ranging-and-vision dataset.
- TIERS' open-source cooperative ranging code.
- A Crazyflie with the Loco (UWB) positioning deck, if you can borrow one.

**Pitfalls:**
- Ranges measured while drones move are biased.
- Re-sharing the same information makes the filter over-confident. Use covariance intersection to avoid it.

### W2. WHO LAUNCHED IT? (Challenge 3)

- **The incident.** On 1 Dec 2025, drones orbited LÉ William Butler Yeats off Dublin for about 2 hours, and the operator is still unidentified. In Denmark (Sep 2025), a tanker was suspected of launching drones †.
- **The idea.** Fuse drone sightings (radar, camera or RF bearings, even eyewitness reports) with the AIS and satellite-radar vessel picture. From the drones' endurance and speed, compute which vessels were within launch range at launch time. Rank them by behaviour history, and produce an attribution lead with an evidence pack for the Gardaí.
- **Caveats.** It is sensitive (the investigation is ongoing), and real drone-track data is scarce. It works best as a **second mission on the ANCHOR WATCH engine**.

---

## Ideas to avoid, and why

| Tempting idea | Why not |
|---|---|
| Another satellite-image ship detector as *the* product | The most common C3 entry. Global Fishing Watch already does it globally, and Research Ireland's Defence Innovation Challenge (run with the Defence Forces) just funded Sea-Scan for dark-vessel detection. Use a detector as an *input*, not your headline. |
| Counter-drone interceptor | It was the *previous* edition's theme and other hosts' local challenge. Ireland has already bought Sky Warden and Drone Hunter. It doesn't answer this challenge set. |
| An LLM chatbot "for commanders" as the product | Judges have seen dozens. It is fine as a grounded feature, never as the core. |
| Anything framed as autonomous targeting or lethal swarms | It clashes with Ireland's stance on meaningful human control, with the CCW Review Conference a month later †. |
| Quantum as decoration | The Dublin audience will probe it, and a hollow claim sinks credibility for the whole pitch. |
| A "digital twin of the Irish Sea" that does everything | It proves nothing. Winners prove one layer with numbers. |

## Scorecard (5 = best)

| | ★ ANCHOR WATCH | ONE SHIP, TWENTY EYES | MAGNAV ÉIRE |
|---|---|---|---|
| Operational relevance to an Irish jury | 5 | 4.5 | 3 |
| Polished demo achievable (3 weeks + 2.5 days) | 5 | 4 | 3 |
| Market potential / dual use | 5 | 4 | 4 |
| Novelty vs likely competitors | 4 | 3.5 | 5 |
| Sponsor and follow-on fit | 5 | 4 | 3.5 |
| Execution safety (5 = safest) | 4.5 | 3.5 | 2.5 |
| **Total** | **28.5** | **23.5** | **21** |

## Choosing

- **Mostly software, data or AI people:** ANCHOR WATCH.
- **Drone, robotics or simulation people, plus someone who enjoys optimisation:** ONE SHIP, TWENTY EYES.
- **Someone who has built Kalman or particle filters, or a physicist or quantum person:** MAGNAV ÉIRE.
- **The team already has a prototype of anything close:** adapt it to the nearest idea. Maturity beats novelty. Declare what existed before.
