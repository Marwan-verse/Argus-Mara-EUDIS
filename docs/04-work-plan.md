# 4. The plan: Argus Mara, from today to the pitch

**Goal:** win Dublin (1st place: €10k plus EUDIS mentoring). We do it with a **live demo of the Argus Mara countdown**, two hard numbers, and a visible link to Trinity's Sea-Scan.

**Rule #1: always have a demo that runs end to end.** Build the thin slice first, then make each part smarter.

## 4.0 At a glance

| Phase | Dates | Goal | Done when… (checked at the demo run) |
|---|---|---|---|
| **0. Set-up** | Thu 24 – Sun 27 Sep | Everyone can start | The AIS recorder is running 24/7; the data contracts are committed; the map shows cables; one radar scene is opened; emails are sent to the organisers and Sea-Scan |
| **1. Skeleton** | Mon 28 Sep – Sun 4 Oct | A thin slice end to end | Live ships and glowing cables on the map; one rule-based alert with a countdown; one radar scene with matched and dark ships |
| **2. The countdown** | Mon 5 – Thu 8 Oct | The heart works | The full scenario plays: tanker, alert, countdown, action panel, approve |
| **3. Space and proof** | Fri 9 – Mon 12 Oct | Special features and numbers | Dark custody and the identity check work on real examples; the evidence pack opens; both headline numbers are on screen |
| **4. Rehearse** | Tue 13 – Wed 14 Oct | Nothing can break | Two offline dry runs in a row; backup video recorded; `git tag pre-hackathon` pushed |
| **5. Hackathon** | Thu 15 – Sat 17 Oct | Make it impressive, pitch it | Pitch delivered; contacts collected |
| **6. After** | From 18 Oct | Turn the win into progress | An 8-week progress plan is running |

**Workstreams (one owner each):**
- **A. Data:** everything flows.
- **B. Brain:** notice, score, count down.
- **C. Space:** see what AIS hides.
- **D. Interface:** what the judges see.
- **E. Story:** the team lead.

How to build each piece is in [05-build-guide.md](05-build-guide.md).

---

## 4.1 Phase 0: Set-up (Thu 24 – Sun 27 Sep)

**E. Story (you)**
- [ ] 60-minute kickoff: walk through [DECISIONS.md](../DECISIONS.md), give workstreams A–D an owner each, and fix the rhythm (§4.9).
- [ ] Create a GitHub Project board with the tasks from this plan.
- [ ] Email the organisers the questions in [03-playbook.md §3.1](03-playbook.md).
- [ ] Email the Sea-Scan team, using the template in §4.8.
- [ ] Create `PRIOR_WORK.md` in the repo.

**A. Data**
- [ ] Get an aisstream.io API key and **start the AIS recorder 24/7** for a box around Ireland (§1 of the build guide). ← *the most important task of the week*
- [ ] Download cable and pipeline routes (EMODnet, TeleGeography) and bathymetry (EMODnet or GEBCO) for Irish waters.

**B. Brain**
- [ ] Commit the data contracts as code (the schemas and the alert JSON, §2 of the build guide).
- [ ] From public reporting, write down the speed and course profile and the timeline of *Eagle S*, *Yi Peng 3* and *Newnew Polar Bear*.

**C. Space**
- [ ] Create a Copernicus Data Space account. Download one Sentinel-1 scene over Irish waters that your recorder covers, and open it.
- [ ] Get a Global Fishing Watch API token and pull its radar vessel detections for Irish waters for one recent week.

**D. Interface**
- [ ] Build the map skeleton (MapLibre + deck.gl) with the coastline and a static cable layer, plus a FastAPI app shell serving stub data.

## 4.2 Phase 1: Skeleton (Mon 28 Sep – Sun 4 Oct)

- **A:**
  - [ ] A store (DuckDB over the recorder's Parquet files).
  - [ ] API endpoints `/vessels` and `/segments`.
  - [ ] An `anchor_reachable` flag for each cable segment.
  - [ ] Sanctions lists loaded.
- **B:**
  - [ ] Track builder with gap detection.
  - [ ] Naive geofence baseline.
  - [ ] **Anchor-drag detector v1** (rules).
  - [ ] **Countdown v1**: straight-line projection to the first anchor-reachable segment.
- **C:**
  - [ ] Ship detection on one scene.
  - [ ] Length estimate for each detection.
  - [ ] Match against AIS at the time the image was taken, giving a list of dark ships.
- **D:**
  - [ ] Live and replayed ships on the map.
  - [ ] Anchor-reachable cable segments glow.
  - [ ] Alert list panel and replay controls v1.
- **E:**
  - [ ] Book operator interview #1.
  - [ ] Write the scenario script v1 (see [02-ideas.md](02-ideas.md), the demo).
  - [ ] Pitch outline v0.

**Sunday 4 Oct demo run:** live ships plus glowing cables, one real alert with a countdown, and one radar scene showing matched and dark ships.

## 4.3 Phase 2: The countdown (Mon 5 – Thu 8 Oct)

- **B:**
  - [ ] **Countdown v2**: the state machine (WATCH → APPROACHING → ALERT → CONTACT → RESOLVED), with an uncertainty cone giving an *earliest* and an *expected* ETA.
  - [ ] **Response options** with ETAs and `in_time`.
  - [ ] Context suppression v1: anchorages, port approaches, storms.
- **A:**
  - [ ] **Scenario generator**: a fictional tanker injected into real traffic, with the *Eagle S*-like profile (12→9 kn, course wobble).
  - [ ] A replay engine that feeds the engine as if it were live.
- **C:**
  - [ ] The "next satellite look" at a predicted position, from ESA's Sentinel-1 acquisition plans or orbit data. Feed it into the options.
- **D:**
  - [ ] **Alert card with a live countdown** and the "why" chips.
  - [ ] Action panel ✅/❌ with an "approve" button.
  - [ ] Jump-to-moment in replay.
- **E:**
  - [ ] Operator interview #1 done. Change the action cards based on what you hear.
  - [ ] Pitch v0.5.

**Thursday 8 Oct demo run:** the whole storyline plays from the tanker to "approve".

## 4.4 Phase 3: Space and proof (Fri 9 – Mon 12 Oct)

- **C:**
  - [ ] **Custody through gaps** (reachability plus radar match), in the scenario and on at least one real example.
  - [ ] **Identity check** (radar vs AIS length) on real ships.
  - [ ] Flag and name history from the risk lists.
- **B:**
  - [ ] **Metrics harness**, covering:
    - false alarms per day (ours vs the geofence) on the recorded weeks;
    - precision and recall on synthetic anchor-drag episodes;
    - **warning time on the *Eagle S* reconstruction**.
- **D:**
  - [ ] **Evidence pack** page.
  - [ ] The "confirmed by fibre" chip and the CONTACT state.
- **A:**
  - [ ] **Sea-Scan adapter**: the fibre-event schema, plus converting a distance along the cable (km) to a map position.
  - [ ] Simulated fibre events for the scenario.
  - [ ] **Offline cache** of all demo data.
- **E:**
  - [ ] Pitch v1 with real numbers, Q&A cards and a one-page summary.
  - [ ] Check the defence numbers in Budget 2027.
  - [ ] Follow up with Sea-Scan.

**Monday 12 Oct demo run:** all 8 demo steps run, numbers are on screen, and the evidence pack opens. **Anything not working today is cut.**

## 4.5 Phase 4: Rehearse (Tue 13 – Wed 14 Oct)

- [ ] Two full dry runs with the Wi-Fi **off**, timed at 4 minutes for the pitch plus demo.
- [ ] Fixes only.
- [ ] Record the backup video, and keep it on a laptop and a USB stick.
- [ ] E: pitch v2; update `PRIOR_WORK.md`; **`git tag pre-hackathon` and push it**; print the one-pagers; check that everyone's ID is packed.

## 4.6 Phase 5: The hackathon (Thu 15 – Sat 17 Oct)

| Day | Plan |
|---|---|
| **Thu** | Set up. **First 2 hours: interview the mentors** (Department of Defence, the RTI unit, TCD if present) and note three changes. Then build the learned anchor-drag score and context suppression v2. The LLM brief on TensorX is optional. |
| **Fri** | Final metrics and UI polish. **Freeze features at 17:00.** Record the final video, then rehearse with a mentor watching. |
| **Sat** | Fixes only. Rehearse five times. Pitch. Then network, and **collect contacts** (Department of Defence, the RTI unit, TCD, TensorX, the Irish Space Association, Deloitte). |

Deliverables: the live demo, slides, the video, and the repo. The `pre-hackathon` tag shows what existed before; everything after it was built at the event.

## 4.7 Phase 6: After the hackathon

- **If you win**, EUDIS mentoring follows (about 40 h over about 2 months), then the EU-wide final, which is judged on **progress**. Run an 8-week plan:
  1. Validation with the RTI unit on unclassified historical data.
  2. **A joint pilot with Sea-Scan on the Dublin–Holyhead corridor** (Emerald Bridge Fibres), where they already have fibre-sensing data.
  3. A satellite-AIS integration.
  4. One letter of intent from a cable or energy operator.
  5. An ESA BIC application.
- **Whatever you place:** ask for DCU incubation, TensorX credits, and test and validation with the RTI unit.

## 4.8 The Sea-Scan (Trinity) partnership

**Why:** Research Ireland and the Defence Forces funded Sea-Scan, and the jury knows it. "We join it up" beats "we compete with it".

**Steps:**
1. **Read their two papers first:**
   - *Sea-Scan: weakly supervised fibre-sensing (DAS) dark-vessel detection*, arXiv 2606.21326.
   - *DAS–AIS association patterns on the Dublin–North Wales link*, arXiv 2607.02536.
2. **Email by Sun 27 Sep** to Prof. Marco Ruffini (School of Computer Science and Statistics) and Dr John Kennedy (School of Engineering), both at TCD. Their addresses are on the TCD staff pages.
3. **Follow up on Fri 2 Oct** and ask for a 20-minute call.
4. **On the call, ask:**
   - (a) Are we OK to name Sea-Scan as complementary?
   - (b) Would you give us informal advice?
   - (c) Would you be interested in a joint pilot on the Dublin–Holyhead corridor after the event?
   - (d) Did you register an intent for the Defence Innovation Challenge 2026, and could a space-cueing work package fit?
   - (e) What does your fibre-event output look like? Our adapter should match it.
5. **Wording in the pitch:**
   - With written consent: *"designed with input from the Sea-Scan team (TCD)"*.
   - Otherwise: *"designed to complement Sea-Scan"*.

**Don'ts:**
- Don't claim a partnership or endorsement without written consent.
- Don't use their data or logo without permission.
- Never present their numbers as ours.

**Email template:**

> **Subject:** Argus Mara — a space/AIS early-warning layer designed to complement Sea-Scan (EUDIS hackathon, DCU, 15–17 Oct)
>
> Dear Prof. Ruffini and Dr Kennedy,
>
> I lead a team competing in Challenge 3 ("Space-Enabled Maritime Domain Awareness", set by the Department of Defence) at the EUDIS Defence Hackathon at DCU on 15–17 October.
>
> We are building **Argus Mara**, an early-warning layer for Ireland's undersea cables and pipelines. It watches AIS and satellite radar and spots vessels whose behaviour matches past cable incidents, such as the *Eagle S* speed-drop and anchor-drag pattern. It then shows the watch officer a **countdown to the threatened cable** and which response assets can arrive in time.
>
> We have read your Sea-Scan work, including the DAS–AIS association study on the Dublin–North Wales link. We see the two systems as complementary: Sea-Scan hears what happens at the cable, while Argus Mara sees vessels coming hours earlier and can name them. The link works in both directions: a fibre event can cue identification, and an Argus Mara countdown can cue a fibre segment. Argus Mara's cleaned AIS tracks could also provide better labels.
>
> Would you be open to a 20-minute call in the next two weeks? We would value your advice, and we would like your permission before mentioning Sea-Scan by name in our pitch. If there is interest, we would be glad to explore a small joint pilot after the event.
>
> Kind regards,
> [Name] · [team] · [phone]

## 4.9 Rhythm and rules

- **Syncs:**
  - Tuesday and Friday: 30-minute sync.
  - **Sunday:** full demo run, recorded.
  - Keep the board up to date daily.
- **Stub, then replace.** Build behind the agreed contracts with fake data until the real piece arrives. In the final demo, label everything *real*, *reconstructed* or *simulated*.
- **Cut, don't stretch.** Anything not working on 12 Oct is dropped.
- **Adjusting to team size:**

| People | Split |
|---|---|
| 3 | Data + Space · Brain · Interface; the lead also owns Story |
| 4 | Data + Space · Brain · Interface · Lead |
| 5 | A · B · C · D · Lead |
| 6–10 | Split Brain (detectors / countdown + response), Space (detection / passes + identity) and Interface (map / evidence + replay). Add a "proof" person for metrics. |

## 4.10 The finish line (17 Oct checklist)

- [ ] The 8-step demo runs **offline**, end to end.
- [ ] Two numbers on screen: **false alarms per day (ours vs the geofence)** and **warning time on the *Eagle S* replay**.
- [ ] Dark custody and the identity check shown on at least **one real example**.
- [ ] The evidence pack opens.
- [ ] The 4-minute pitch rehearsed 5+ times, the backup video, and the one-pager.
- [ ] Prior work declared (the tag plus `PRIOR_WORK.md`).
- [ ] Sea-Scan mentioned with the right, consent-based wording.
