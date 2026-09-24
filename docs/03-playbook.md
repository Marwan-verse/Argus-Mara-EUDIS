# 3. Playbook: from today (24 Sep) to the podium (17 Oct)

The plan is written for the recommended idea, **ANCHOR WATCH**. The other ideas follow the same rhythm with different milestones.

## 3.1 This week (24–30 Sep)

- [ ] **Pick the idea** using the guide at the end of [02-ideas.md](02-ideas.md). Write a one-page brief covering the problem, the user, the demo moment, the headline metric and the ask.
- [ ] **Lock the team.** The allowed size is 3–10; 4–6 works best. Check each person now:
  - [ ] 18 or older.
  - [ ] **A citizen of an EU member state, Norway or Ukraine**, and able to bring a passport or national ID. IDs are checked on site. UK-only or other non-EU nationals are not eligible, even if they live in Ireland.
  - [ ] Available on site for all 2.5 days.
- [ ] **Email the organisers.** Event questions go to the DCU:Innovate Hub contact on the official page. Ask:
  1. What is the judging rubric and its weights? How long is the pitch and the Q&A? What must be submitted: deck, video, repo?
  2. Does the jury try to spread the prizes across the three challenges?
  3. Will any data, APIs, hardware or compute be provided during the event (TensorX credits, Defence Forces RTI data)?
  4. Can we fly small drones on site, indoors or outdoors? Glasnevin is about 5 km from Dublin Airport, so outdoor flights are probably inside controlled airspace or a drone restriction zone and need clearance from the Irish Aviation Authority (IAA).
  5. Is the venue internet good enough for live data streams?
  6. What are the dates of the pre-event drone workshops?
  7. Will Defence Forces or Department of Defence mentors be available early on Day 1?
- [ ] **Get data accounts and API keys.**
  - ANCHOR WATCH: aisstream.io, Global Fishing Watch API, Copernicus Data Space Ecosystem, EMODnet downloads.
  - ONE SHIP: Copernicus Marine; optionally D-Wave Leap or IBM Quantum.
  - MAGNAV ÉIRE: MagNav.jl data, GSI Tellus grids, INTERMAGNET.
- [ ] **Start a `PRIOR_WORK.md` file and commit from day one.** The organisers want a clear line between what existed before and what was built at the event. Dated commits are the easiest proof.

## 3.2 Weeks 2–3 (1–14 Oct): build the core, declared as prior work

| By | ANCHOR WATCH milestone |
|---|---|
| 4 Oct | Live and historical AIS ingest. Cable, pipeline and depth layers. A map shows live traffic over the cable corridors. |
| 8 Oct | Rule-based detectors plus the naive geofence baseline. Scenario generator (fictional vessel names; incident profiles reconstructed from public reporting). Replay mode. |
| 12 Oct | First Sentinel-1 ingest and match against AIS. First alert card with a time-to-crossing. One week of historical AIS processed for false-alarm statistics. |
| 14 Oct | Full end-to-end dry run. Pitch v1. Backup demo video v1. Data cached for offline use. |

Alongside the build:
- **Go to the drone workshops.** Meet the Defence Forces RTI unit, Hextronics, Drone Space and the other teams.
- **Get 20 minutes with one real operator.** A retired Naval Service officer, a Coast Guard watch officer, or a cable-operator engineer would all do. Ask:
  - What do you watch?
  - What do you ignore?
  - What decision do you need to make, and how fast?
  - Quote them in the pitch.
- **Check the defence figures in Budget 2027** (early October) so your numbers are fresh on the day.
- **Line up an academic partner at an eligible Irish research body now** † if you want to apply to the Research Ireland Defence Innovation Challenge on 29 Oct.

Milestones for the other ideas:
- **ONE SHIP:**
  - By 4 Oct: drift sim with OpenDrift and the probability map.
  - By 8 Oct: IAMSAR baseline, plus the Monte Carlo harness.
  - By 12 Oct: QUBO and classical solvers benchmarked; comms-loss fallback.
  - By 14 Oct: dry run.
- **MAGNAV ÉIRE:**
  - By 4 Oct: MagNav.jl baseline reproduced.
  - By 8 Oct: particle filter on the Challenge flight data.
  - By 12 Oct: Tellus map loaded and upward-continued; spoofing detector.
  - By 14 Oct: dry run.

## 3.3 The 2.5 days

| When | Focus |
|---|---|
| **Day 1 (Thu)**, first 2 hours | Set up the demo machine with offline data. **Interview at least three mentors, starting with the Defence Forces and Department of Defence.** Test the operator workflow and the action cards on them, then adjust. |
| Day 1, rest | Learned behaviour scoring and satellite-radar fusion/custody. End-to-end run #1 by the evening. Agree a cut list. |
| **Day 2 (Fri)**, morning | Prediction, course-of-action cards, evidence pack |
| Day 2, afternoon | Backtests and false-alarm statistics, then UI polish. **Freeze features at about 17:00**; after that, only demo polish. |
| Day 2, evening | Record the backup video. Pitch v2. Rehearse with a mentor watching. |
| **Day 3 (Sat)** | Fixes only. Rehearse five times with a timer. Prepare Q&A cards. Pitch. Then network with the RTI unit, the Department, Deloitte, TensorX and the Irish Space Association, and **collect follow-up contacts**. |

## 3.4 Roles (team of 5)

The team is versatile, so assign owners by workstream. [04-work-plan.md](04-work-plan.md) has the full split, the tasks and the timeline. Roles during the pitch:

| Role | Owns | During the pitch |
|---|---|---|
| **Lead (you)** | Problem, users, mentor interviews, business model, pitch | Presents |
| Data engineer | AIS and satellite-radar pipelines, replay, offline data | Standby on the backup video |
| ML / analytics | Detectors, risk model, prediction, backtests | Takes technical questions |
| Geospatial / space | Sentinel-1 processing, fusion, satellite passes | Takes space questions |
| Front end | Map, action cards, evidence pack | Drives the demo |

## 3.5 The 4-minute pitch (ANCHOR WATCH)

| Time | Beat | Talk track (adapt freely) |
|---|---|---|
| 0:00–0:25 | **Hook** | "Christmas Day 2024. A tanker called *Eagle S* dragged its anchor across the floor of the Gulf of Finland and cut a power cable and four data cables †. Its slow, strange track was visible in public ship data while it happened. Nobody was watching that signal. Since March, ships from the same shadow fleet sail past the west of Ireland." |
| 0:25–0:55 | **Irish stakes** | "About eleven transatlantic cables. The pipelines that bring most of our gas. A sea area seven times our land. And crews for two ships at sea. The Maritime Security Strategy asks us to protect undersea infrastructure and improve maritime awareness. The problem isn't data. It's attention and time." |
| 0:55–1:10 | **Solution** | "ANCHOR WATCH watches every ship, every minute, and tells the watch officer three things: which ship matters, which cable is at risk and when, and what can get there in time." |
| 1:10–2:40 | **Live demo** | Dark tanker → satellite radar regains it → anchor-drag alert with ETA → action cards → evidence pack. |
| 2:40–3:10 | **Proof** | Warning time on the reconstructed incidents, false alarms per day against the geofence baseline, dark-period custody rate. |
| 3:10–3:35 | **Fit and path** | "It complements Sea-Scan and GUARD, runs on open and space data, and uses sovereign EU compute. Next: a trial with the RTI unit on historical data, a Defence Innovation Challenge application, and cable operators as commercial buyers." |
| 3:35–3:50 | **Honesty and team** | What existed before vs what was built here, and who you are. |
| 3:50–4:00 | **Ask** | "Six weeks with the RTI unit on historical data, and one introduction to a cable operator." |

## 3.6 Hard questions to rehearse

1. **"How is this different from Windward, Kpler or Global Fishing Watch?"** They are generic maritime-risk platforms. Ours:
   - works at cable-segment level, using anchor-reach physics;
   - predicts, and checks which responses can arrive in time;
   - fuses Irish in-situ sensing such as Sea-Scan;
   - is sovereign and can run on premises.
2. **"Isn't anchor-drag detection what Sea-Scan does?"** Sea-Scan hears it *at the cable*. We see the ship coming hours earlier, know who it is, cover pipelines and power cables without fibre sensing, and recommend a response. Together they give cue-then-verify.
3. **"What if the ship turns off AIS or spoofs it?"** Custody through the dark with satellite radar, spoofing detectors, commercial radar-satellite tasking, and fusion with fibre sensing.
4. **"How many false alarms?"** Give the measured rate on a week of real traffic and the ratio against the naive baseline. Explain the context suppression.
5. **"AIS coverage far offshore?"** Terrestrial AIS near the coast today. Satellite AIS, and EMSA feeds through the Defence Forces, on the roadmap.
6. **"What can Ireland legally do in its EEZ?"** The system informs; people decide. It supports hailing, notifying operators and partners, and evidence packs. Boarding-powers legislation is being drafted.
7. **"Why would a cable operator pay?"** Most faults are accidental, from anchors and fishing gear. Repairs are slow and expensive †.
8. **"How good are your incident reconstructions?"** They are built from public reporting and clearly labelled. Validation on real data is step one of the trial.
9. **"What's autonomous about it?"** Monitoring, custody, prediction and recommendation run around the clock without a human. Sensors can be cued automatically within pre-approved rules. Actions stay with a human.
10. **"Data sensitivity?"** Public data only in the prototype, deployable on sovereign or on-premises compute.
11. **"Business model?"** A subscription per protected asset or area, plus integration.
12. **"Will the team continue?"** Name who commits, plus DCU incubation and the next funding deadline.

**If you pitch ONE SHIP or MAGNAV, add the quantum question: "Why quantum?"**
- Answer with what you measured: QUBO vs classical, the optimality gap, runtime, and where classical still wins.
- For MagNav, the value of quantum sensors is being absolute and drift-free, not the noise floor.
- **Never claim more than you measured.**

## 3.7 Demo rules

- **Have an offline replay mode.** Never depend on venue Wi-Fi. Cache every dataset locally.
- **Keep a recorded backup video**, on a laptop and on a USB stick.
- **Use fictional vessel names** in scenarios, and label everything *real*, *reconstructed* or *simulated*.
- Show one screen, with big fonts, rehearsed clicks and a reset button.
- Keep the headline number **on screen** at the end of the demo.
- **Never transmit jamming or spoofing signals, even "just to test".** It is illegal. Use recorded datasets or simulator fault injection instead.
- **No outdoor flying without organiser and IAA clearance.** Plan for indoor flights, the simulator, or recorded flight logs.

## 3.8 What to bring

- Passports or national ID cards for everyone.
- Laptops and chargers, HDMI/USB-C adapters, and a 4G/5G hotspot.
- Offline data copies and the backup video on USB.
- A printed one-page summary for judges, with a QR code to the demo video.

## 3.9 After the hackathon, where most of the value is

- **29 Oct: Research Ireland Defence Innovation Challenge 2026 closes.** It offers up to €220k over 13 months plus a €1m prize phase, and Area 1 is space-based situational awareness. It needs an eligible Irish research-body lead †.
- **If you win:** EUDIS mentoring (about 40 h over about 2 months), then an EU-wide final judged on *progress*. Arrive with an eight-week plan:
  - an RTI trial on historical, unclassified data;
  - one letter of intent from a cable or energy operator;
  - a satellite-AIS integration;
  - an ESA BIC application.
- **Whatever you place:** ask about DCU:Innovate incubation, TensorX credits and RTI test and validation. Those supports are open to several teams, not only the winner.
