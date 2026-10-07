# 5. Build guide: how to build Argus Mara

*Scope note, 7 October 2026:* the broad layout and recipes below are a design backlog, not a request to create every module now. Decisions D14–D15 set a smaller v1: `demo/` JSON, Python `argus/`, and a static `ui/`. See [07-architecture.md](07-architecture.md) for the current structure and [08-research-and-next-ideas.md](08-research-and-next-ideas.md) for checked source caveats. The existing `recorder/recorder.py` is the maintained recorder; the short example in §1 is illustrative.

These are practical recipes for each component, in the order you'll need them. The **what and when** is in [04-work-plan.md](04-work-plan.md).

Everything here uses open data and open-source tools. Numbers marked *(assumption)* are placeholders: make them configurable and say so in the demo.

---

## 0. Repo layout (suggested)

```
argus-mara/
  demo/            # the frozen contract: scenario.json + alerts.json (+ generator). START HERE
  recorder/        # AIS recorder (runs 24/7)
  data/            # local store (git-ignored): ais/, cables/, bathy/, sar/, lists/
  argus/
    contracts.py   # schemas + alert model (pydantic)
    ingest/        # loaders: AIS, cables, depth, sanctions, weather, GFW/Sentinel-1
    tracks.py      # track builder, gaps
    detectors.py   # anchor-drag, loitering, gaps near infra, spoofing, identity
    reach.py       # anchor-reachable segments + zone
    countdown.py   # prediction, state machine, ETAs
    response.py    # assets, ETAs, in_time
    space.py       # SAR detection, length, AIS matching, custody, passes
    fibre.py       # Sea-Scan adapter (fibre events)
    evidence.py    # evidence pack + hash chain
    metrics.py     # baselines, false alarms/day, warning time, P/R
    api.py         # FastAPI
  scenarios/       # fictional tanker, Eagle S-profile reconstruction, replay engine
  ui/              # MapLibre + deck.gl front end
  PRIOR_WORK.md
```

## 1. The AIS recorder: start it today

It records Irish traffic 24/7 from aisstream.io's free websocket.
- **Why raw:** it stores the messages **raw**, so you can parse them later however you like.
- **Where to run it:** any always-on machine, such as a small cloud VM, a Raspberry Pi or a spare laptop.
- **How much disk:** expect up to a few GB of compressed Parquet over three weeks.

```python
# recorder/recorder.py   pip install websockets pyarrow
import asyncio, json, os, time
import websockets, pyarrow as pa, pyarrow.parquet as pq

API_KEY = os.environ["AISSTREAM_API_KEY"]
BOX = [[[49.0, -18.0], [57.5, -4.5]]]          # [[lat_min, lon_min], [lat_max, lon_max]] around Ireland
TYPES = ["PositionReport", "StandardClassBPositionReport", "ShipStaticData"]
OUT = "data/ais"; os.makedirs(OUT, exist_ok=True)

async def record():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
        await ws.send(json.dumps({"APIKey": API_KEY, "BoundingBoxes": BOX,
                                  "FilterMessageTypes": TYPES}))   # must be sent within ~3 s
        batch, t0 = [], time.time()
        async for raw in ws:
            m = json.loads(raw)
            batch.append({"recv": time.time(), "type": m.get("MessageType"),
                          "meta": json.dumps(m.get("MetaData")), "msg": json.dumps(m.get("Message"))})
            if time.time() - t0 > 600:                                # flush every 10 min
                pq.write_table(pa.Table.from_pylist(batch), f"{OUT}/{int(t0)}.parquet",
                               compression="zstd")
                batch, t0 = [], time.time()

while True:                                                           # reconnect forever
    try:
        asyncio.run(record())
    except Exception as e:
        print("reconnecting after:", e); time.sleep(5)
```

- **Run it:** `AISSTREAM_API_KEY=… nohup python recorder/recorder.py &`, or as a systemd service.
- **Check it:** look at the file count every day.
- **Check the fields:** confirm the exact field names in the aisstream.io docs before you write the parser.

## 2. Data contracts: agree them on day one

**For the v1 demo these are already frozen as two JSON files in [`demo/`](../demo/)** —
`scenario.json` (*what happened*, owned by Data) and `alerts.json` (*what Argus Mara noticed*,
owned by Brain). There is no backend in v1: the interface reads both files and plays them. Read
[`demo/README.md`](../demo/README.md) before writing any code, and run
`python3 demo/make_scenario.py` to see worked values.

The richer schemas below are where those two files grow to once the demo runs. Put them in
`argus/contracts.py` (pydantic). Every workstream builds against these, with stub data at first.

- `positions(mmsi, ts, lat, lon, sog_kn, cog_deg, heading_deg, nav_status)`
- `vessels(mmsi, imo, name, ship_type, length_m, flag, name_flag_history)`
- `segments(id, asset_name, kind[telecom|power|gas], geometry, min_depth_m, anchor_reachable, criticality)`
- `detections(ts, lat, lon, length_m, source[sentinel1|gfw], scene_id, matched_mmsi)`
- `fibre_events(ts, cable_id, position_km, cls[vessel|anchor|trawl|unknown], confidence)`
- `Alert{id, mmsi, name, state, score, reasons[], segment_id, distance_km, eta_expected_min, eta_earliest_min, options[{asset, eta_min, in_time}], evidence_url}`

## 3. Infrastructure layer and the anchor-reach zone

1. **Load the routes.**
   - EMODnet Human Activities has telecom cables, power cables and pipelines. For telecom, add TeleGeography's submarine cable map GeoJSON (non-commercial licence; credit it).
   - Tag the assets that matter most: the gas interconnectors, EWIC, Greenlink, and the transatlantic landings.
2. **Reproject to metres.** Use Irish Transverse Mercator (EPSG:2157) or UTM 29N (EPSG:32629).
3. **Sample the depth along each route.** Take a point every ~250 m from EMODnet Bathymetry or GEBCO (rasterio `sample`), and split each route into sub-segments.
4. **Anchor-reachable** means depth ≤ threshold. Start at **250 m** *(assumption)* and make it configurable. You can later scale it with ship size, since bigger ships carry longer anchor chains.
5. **Display:** draw the ≤ 250 m contour as the "anchor-reach zone" band. Sub-segments inside it glow.
6. **Criticality weights** are set by hand: gas and power 1.0, transatlantic telecom 0.8, regional telecom 0.6 *(assumption)*.

## 4. Tracks and features

Build per-vessel tracks (by MMSI), sorted and de-duplicated, with implausible points dropped. Then compute these features over 10–30-minute windows:
- **Speed drop:** speed compared with the ship's own median over the last hour.
- **Speed oscillation:** the standard deviation of speed over 10 minutes.
- **Course wobble:** the circular standard deviation of course, and |heading − course|.
- **Rate of turn.**
- **Distance to the nearest anchor-reachable sub-segment**, and whether the ship is inside the anchor-reach zone.
- **Distance to the nearest port or designated anchorage.**
- **Local traffic density.**
- **Wind and wave context** from the nearest buoy.
- **Navigation status.** "At anchor" while moving is itself suspicious.
- **Gaps:** AIS silence longer than N minutes *in an area where your recorder normally hears ships*. Build a coverage map from your own data, so that "no coverage" isn't mistaken for "switched off".

## 5. Anchor-drag detector

**v1: rules.** Flag it if the ship is inside the anchor-reach zone, is a merchant ship, and **its speed falls ≥ 20% below its own last-hour median with no reason**. "No reason" means:
- not near a port or anchorage;
- calm weather;
- no dense traffic;
- no course change explaining the slowdown.

Add points for speed oscillation and heading/course divergence. This is the *Eagle S* signature: **12 → 9 knots**, with engine RPM falling, just before the first cable break.

**v2: learned, at the event.**
- **Model:** gradient boosting (LightGBM) on the §4 features.
- **Positives:** synthetic anchor-drag episodes injected into real tracks. Scale the speed by 0.6–0.85, add oscillation and heading–course divergence, then recompute the positions.
- **Negatives:** real normal traffic from your recorder.
- **Validation:** the reconstructed incidents.
- **Threshold:** calibrate it to a target false-alarm rate, e.g. at most one per day for the whole Irish zone *(assumption; ask the operators)*.

**Other detectors**, all with human-readable reasons:
- loitering over a segment;
- survey-like lawnmower tracks over a cable;
- an AIS gap starting or ending within X km of infrastructure;
- impossible jumps (implied speed above 40 kn);
- identity mismatch (§8).

## 6. The countdown: the heart

For each vessel, on every new position:
1. **Project it forward**, every minute out to a 3-hour horizon, using its current speed and course plus rate of turn.
2. **Build an uncertainty cone** by sampling about 50 perturbed futures: speed ±20%, course ±(5° + 2°/10 min). Both *(assumption)*.
3. **Intersect them with the anchor-reachable sub-segments**, buffered by 500 m, using a shapely `STRtree`.
   - **ETA_expected** = the crossing time of the nominal path.
   - **ETA_earliest** = the earliest crossing among the sampled futures.
4. **State machine:**

| State | Meaning |
|---|---|
| WATCH | No crossing within the horizon |
| APPROACHING | The cone reaches an anchor-reachable segment within 3 h |
| ALERT | A behaviour detector fires inside the zone, or the risk score is above the threshold |
| CONTACT | A fibre event matches, or the vessel is on the segment buffer |
| RESOLVED | Left the zone, cleared by an operator, or an action was taken |

5. **While the ship is dark**, keep projecting from the last fix with a cone that widens over time. A radar detection resets it.
6. **Show** `ETA_expected` as the big countdown, with the earliest time in small print: "1 h 20 (earliest 58 min)".

## 7. Response options: "what can get there in time"

Put the assets in a config file (YAML). All of these are *assumptions* to confirm with mentors:
- **C295 maritime patrol aircraft**, at Casement Aerodrome, Baldonnel (≈ 53.30 N, 6.45 W). 30 min readiness, about 400 km/h transit.
- **Naval Service ships:** simulated positions (2 at sea), about 15 kn.
- **Drone** (GUARD-type) from a ship: about 100 km/h, with an endurance cap.
- **Hailing on VHF 16:** possible if the ship is within about 30 nautical miles of a coast radio station (Malin Head, Valentia, Dublin area).
- **Satellites:** the next Sentinel-1 look from ESA's published acquisition plans, plus a latency. For commercial SAR tasking, use "hours".

For each option, `eta_min = readiness + distance / speed`:

| Condition | Badge |
|---|---|
| eta ≤ ETA_earliest | ✅ |
| eta ≤ ETA_expected | ⚠️ |
| otherwise | ❌ |

## 8. Space: dark ships, custody, identity

1. **Get the radar scenes.**
   - Search and download Sentinel-1 IW GRD scenes from the Copernicus Data Space Ecosystem (OData API or openEO).
   - Choose scenes that overlap your recorded AIS.
   - **Faster path:** Global Fishing Watch radar vessel detections, which come with length estimates and AIS matches.
2. **Detect ships.**
   - Pre-processing: orbit file, calibration, land mask.
   - Then either **ESA SNAP's Ship Detection** tool, or a two-parameter CFAR on the calibrated backscatter (σ⁰) with a guard window, in Python.
3. **Estimate length.** Take each detection's connected component, fit an oriented bounding box, and multiply the long axis by the ~10 m pixel spacing. Treat the result as ±20–30 m. It is only good for ships longer than about 80 m.
4. **Match to AIS.**
   - Interpolate every AIS track to the image time.
   - Match with the Hungarian algorithm inside about 1 km.
   - Detections left unmatched are **AIS-unmatched SAR contacts**. Check coverage, classification and matching before describing an individual vessel as deliberately dark.
5. **Keep custody.** For each ship in an AIS gap, compute the area it could have reached (max speed × time since last fix). A dark detection inside that area, with a matching length and heading, gives "custody regained (p = …)".
6. **Identity check.** Flag a mismatch if |L_radar − L_AIS| > max(40 m, 25%). Also flag flag/name changes and sanctions hits from the risk lists (e.g. *Blue*: four identities and six flags since 2020).
7. **Next look.** ESA's Sentinel-1 acquisition-plan KML files show which areas get imaged when. Feed the next look into §7.

## 9. The Sea-Scan adapter: fibre ↔ Argus Mara

- **Input.** `fibre_events(ts, cable_id, position_km, cls, confidence)`. Convert the km to a map position with shapely `line.interpolate(km * 1000)`, on the cable geometry in metres.
- **Fibre → Argus Mara.**
  - Find AIS vessels within about 2 km and ±10 min of the event, and name them.
  - If there are none, it is a **dark contact**: check custody candidates and the next radar look, then raise an alert.
- **Argus Mara → fibre.** When a countdown turns APPROACHING, emit a *watch request* `{cable_id, km_from, km_to, eta_window, vessel}`.
- **Labels.** Export cleaned tracks, reconstructed gaps and radar confirmations. This addresses the "imperfect AIS labels" problem named in Sea-Scan's papers.
- **Demo.** Generate **simulated** fibre events from the scenario and label them clearly. Use Sea-Scan's real output format only if their team provides it.

## 10. Evidence pack

- **Format:** an HTML page (Jinja2), exportable as a ZIP.
- **Contents:**
  - a timeline of events;
  - a map snapshot;
  - the raw AIS messages;
  - radar image chips with scene IDs;
  - detector outputs and reasons;
  - the operator's decisions.
- **Tamper evidence:** hash each item with SHA-256 and chain the hashes (`h_i = sha256(h_{i-1} + item_i)`), then print the final hash on the page.

## 11. Metrics: your two headline numbers and the rest

| Metric | Script | Notes |
|---|---|---|
| **False alarms per day** | Run the detectors over the recorded weeks. Count alerts per day for Argus Mara and for the geofence baseline. Hand-check the top 20. | Headline number #1 |
| **Warning time** | Replay the reconstructed *Eagle S* profile. Minutes from the first alert to each cable crossing. | Headline number #2 |
| Detector precision and recall | On the held-out synthetic episodes | Show the ROC curve |
| Custody accuracy | Simulate gaps in real tracks, then re-acquire with radar | % correct identity |
| Latency | AIS message to alert | Seconds |

## 12. The interface

- **Offline map.** No web tiles: use a coastline GeoJSON (Natural Earth, or OSM-derived) on a dark background, so the demo works without internet.
- **deck.gl layers:**
  - `PathLayer`: cables, glowing where anchor-reachable;
  - `ScatterplotLayer` / `IconLayer`: ships, with dark contacts as hollow;
  - `TripsLayer`: replay;
  - `PolygonLayer`: anchor-reach zone and uncertainty cone.
- **Alert card.** The countdown ticks locally from the ETA, with reason chips and state badges.
- **Action panel.** ✅ / ⚠️ / ❌ badges, an "approve" button, and a link to the evidence pack.
- **Replay controls.** Play, pause, ×60 speed, jump to a moment, and a reset button.

## 13. Optional: the watch-officer brief (LLM)

- **Endpoint:** if TensorX exposes an OpenAI-compatible endpoint, send it the structured alert JSON only.
- **Prompt rule:** "use only these facts; cite the item id for each sentence."
- **Display:** show the brief with its citations, and never let it invent facts.
- **Pitch point:** sovereign EU inference, zero data retention.
