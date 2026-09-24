# 4. Work plan: ANCHOR WATCH (Challenge 3)

The team is versatile, so the work is split by **workstream**, not by skill. Each workstream has one owner, plus a buddy if the team is bigger.

**Rule #1: always have a demo that runs end to end.** Build a thin slice through the whole system first, then make each part smarter.

## 4.1 Scope: what goes in the demo

**Must have** (the demo breaks without it):
- A map showing cables and pipelines, with anchor-reachable segments highlighted, and ship traffic, live or replayed.
- A scenario replay: the tanker goes dark, satellite radar re-acquires it, it shows anchor-drag behaviour, and an alert fires.
- An alert card with a **countdown to the cable** and "why" chips explaining the alert.
- An action panel showing the ETAs of the C295 aircraft, the ship and the next satellite pass, and whether each **arrives in time**.
- An evidence pack (one HTML page).
- Two numbers:
  - false alarms per day compared with the naive geofence;
  - warning time on a reconstructed incident.

**Should have** (this is what makes it special):
- The identity check from space: ship length on radar vs the length declared in AIS.
- Custody through AIS gaps, on real data.
- A learned behaviour score, not hand-tuned thresholds.
- The *Eagle S* replay with a measured warning time.

**Nice to have** (only if you're ahead):
- A watch-officer brief from an LLM on TensorX.
- The threat forecast, days ahead.
- A Sea-Scan cue (simulated).
- The "Who launched it?" module.

**Out of scope:**
- Training deep models from scratch.
- Global coverage.
- User accounts, a mobile app, 3D.
- A live satellite-tasking integration.

## 4.2 Architecture: so everyone can work in parallel

```
connectors ─────────► local store ─────────► engine ─────────► API ─────────► map UI
AIS live + history    (DuckDB/Parquet)       tracks, detectors  (FastAPI)      (MapLibre + deck.gl)
cables, pipelines     positions, vessels,    risk + reasons,    /vessels       ships, cables, alerts,
depth, sanctions,     segments, detections,  countdown,         /alerts        countdown, action panel,
Sentinel-1 radar      risk list, weather     response options,  /segments      replay controls,
weather                                      evidence pack      /evidence/{id} evidence page
                                  ▲
                 scenario generator / replay
                 (feeds the engine as if it were live)
```

**Agree these contracts on day one.** Each workstream can then build against stub data until the real pieces arrive.

Tables:
- `positions(mmsi, ts, lat, lon, sog, cog, heading, nav_status)`
- `vessels(mmsi, imo, name, ship_type, length_m, flag)`
- `segments(id, name, kind, geometry, min_depth_m, anchor_reachable, criticality)`
- `detections(ts, lat, lon, length_m, source, matched_mmsi)`
- `risk_list(imo, mmsi, list_name, reason)`

Alert JSON:
```json
{
  "id": "…", "mmsi": 0, "name": "…", "ship_type": "tanker",
  "score": 0.92, "reasons": ["speed 3x below class norm", "course variance x6", "sanctions-listed", "anchor-reachable depth"],
  "segment_id": "…", "distance_km": 12.0, "eta_minutes": 95,
  "position": [lat, lon], "predicted_track": [[lat, lon, "ts"], …],
  "options": [{"asset": "C295 (Casement)", "eta_minutes": 70, "in_time": true}, …],
  "evidence_url": "/evidence/…"
}
```

## 4.3 Workstreams

### A. Data: "everything flows"

- **A1. Live AIS.** Subscribe to aisstream.io with a bounding box around Ireland and write to `positions` and `vessels`.
  - **Start a 24/7 recorder today**, on a small cloud VM, a Raspberry Pi or a spare laptop. By 15 Oct you will have three weeks of *your own* Irish traffic data for learning "normal" behaviour and measuring false alarms.
- **A2. Historical AIS.** Pull a larger sample from the Danish Maritime Authority or NOAA, to learn normal speeds by ship type.
- **A3. Infrastructure layer.**
  - Load EMODnet telecom cables, power cables and pipelines.
  - Sample the depth along each segment from EMODnet Bathymetry and set `anchor_reachable` with a configurable threshold (start at 250 m).
  - Set criticality weights by hand: gas interconnectors and power links high.
- **A4. Risk lists.** Load the EU, UK and OFAC sanctioned-vessel lists (by IMO number) into `risk_list`.
- **A5. (Optional) Weather context** from the Marine Institute buoys.

**Done when:** the API returns ships in Irish waters and segments with the anchor-reachable flag, and at least one week of AIS is stored.

### B. Brain: "notice, score, count down"

- **B1. Track builder:** per-vessel tracks, plus gaps (AIS silent for more than N minutes).
- **B2. The naive baseline to beat:** a geofence that fires on anything under 6 kn within 1 km of a cable.
- **B3. Detectors v1 (rules):**
  - anchor-drag signature: speed well below the norm for the ship's type, speed oscillation and course wobble, sustained over time;
  - loitering over a segment;
  - an AIS gap that starts or ends near infrastructure;
  - impossible position jumps.
- **B4. Risk score** with human-readable reasons (the "why" chips).
- **B5. Countdown:** a predicted track, the first crossing of an anchor-reachable segment, and the distance and ETA to it.
- **B6. Response options:**
  - **Assets:** a C295 at Casement Aerodrome, Naval Service ships (simulated positions), a drone, and the next satellite pass (from Space).
  - For each asset, compare its ETA with the countdown and set `in_time`.
- **B7. At the event, v2:**
  - Replace the thresholds with a learned score, e.g. gradient boosting on the B3 features.
  - Add context suppression for anchorages, storms and fishing grounds.

**Done when:** the scenario fires one alert with the right countdown and options, and the false alarms per day are computed for both the baseline and our method on the stored week.

### C. Space: "see what AIS hides"

- **C1. Get the scenes.** Download Sentinel-1 radar scenes over Irish waters from the Copernicus Data Space Ecosystem, for dates your recorder covers. The alternative is Global Fishing Watch's radar vessel detections.
- **C2. Detect ships** on the sea, with land masked out. Use ESA SNAP's built-in ship-detection tool or a simple CFAR threshold in Python. Estimate a rough length for each ship.
- **C3. Match detections to AIS** at the moment the image was taken:
  - Unmatched detections are **dark ships**.
  - Link them back to ships in an AIS gap by checking who could physically have reached that point.
- **C4. Identity check from space:** compare the radar length with the AIS-declared length and flag big mismatches.
- **C5. Satellite passes:** compute the next Sentinel-1 overpass (acquisition plan permitting) over a predicted position, using CelesTrak orbit data and Skyfield. Feed it into B6.

**Done when:**
- one real scene over Irish waters shows matched vs dark ships on the map;
- the length check works on a few real ships;
- pass times appear in the action panel.

### D. Interface and demo: "what the judges see"

- **D1. Map:** coastline, cables and pipelines (anchor-reachable segments glow), ships, tracks, radar detections.
- **D2. Replay controls:** play, pause, ×60 speed, jump to a moment.
- **D3. Alert card** with a live countdown and the "why" chips.
- **D4. Action panel:** in time ✅ / ❌, plus an "approve" button.
- **D5. Evidence page:** timeline, track snapshot, radar image chip, raw messages, and a hash so tampering is detectable.
- **D6. Offline mode** and a demo reset button.

**Done when:** the 90-second demo runs end to end with no internet.

### E. Story and proof: the team lead

- **E1. Kickoff.** Assign owners, set up a board (GitHub Projects), and hold two 30-minute syncs a week.
- **E2. Scenarios** (together with B):
  - the fictional tanker scenario;
  - an *Eagle S* reconstruction from public reporting (speed and course profile, timeline).
- **E3. Talk to 1–2 real operators:** someone ex-Naval Service, a Coast Guard watch officer, or a cable-operator engineer. Ask:
  - What decision do you need to make, and how fast?
  - How many false alarms would you tolerate?
- **E4. Organisers:** the judging rubric, pitch format, drone rules, internet, and whether mentors are available on Day 1.
- **E5. Pitch material:** pitch v1 → v2, a one-page summary for judges, and the backup video.
- **E6. Prior-work record:** keep `PRIOR_WORK.md` up to date, and run `git tag pre-hackathon` on 14 Oct. The tag is your proof of what existed before the event.
- **E7. Follow-on funding:** for the Defence Innovation Challenge (closes 29 Oct), find an academic lead now. Also open conversations with TensorX and the Defence Forces RTI unit.

## 4.4 Timeline

| Date | Milestone ("done" = you can demo it) |
|---|---|
| **Sun 27 Sep** | Kickoff done; schemas agreed; accounts created; **AIS recorder running 24/7**; each workstream has a "hello world" |
| **Sun 4 Oct** | Thin slice end to end: AIS → store → API → map with ships and cables; baseline plus first detector; one Sentinel-1 scene processed |
| **Thu 8 Oct** | Scenario replay; alert with countdown; action panel with ETAs; *Eagle S* reconstruction v1 |
| **Mon 12 Oct** | Custody through gaps; identity check; evidence pack; first numbers (false alarms per day for both methods, warning time); pitch v1 |
| **Wed 14 Oct** | Two full dry runs; backup video; offline data cache; pitch v2; **`git tag pre-hackathon`** |
| **Thu 15 Oct** | Mentor interviews first, then adjust; learned score; context suppression |
| **Fri 16 Oct** | Final metrics; UI polish; feature freeze around 17:00; record video; rehearsal |
| **Sat 17 Oct** | Rehearse five times; pitch; network |

## 4.5 Adjusting to team size

| People | Split |
|---|---|
| 3 | Data + Space · Brain · Interface. The lead also owns Story. |
| 4 | Data + Space · Brain · Interface · Lead |
| 5 | A · B · C · D · Lead (E) |
| 6–10 | Split Brain (detectors / countdown + response), Space (radar detection / passes + identity check) and Interface (map / evidence + replay). Add a dedicated "proof" person for metrics and incident reconstructions. |

## 4.6 Rules that keep you on track

- **Always keep a working end-to-end demo**, even an ugly one.
- **Stub, then replace.** Build behind the agreed schemas with fake data until the real piece arrives. In the final demo, label everything *real*, *reconstructed* or *simulated*.
- **Every Sunday:** run the full demo and record it.
- **Cut, don't stretch.** If a should-have isn't working by 12 Oct, drop it.
