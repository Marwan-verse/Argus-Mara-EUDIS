# 3. Playbook: pitch, questions, demo rules

*Demo honesty addition, 7 October 2026:* the tanker, cable geometry, radar length and response speeds in `demo/` are simulated or assumed. Show those labels on screen. If a separate real SAR contact is added, introduce it with source, acquisition time and matching caveats; an AIS-unmatched detection does not establish deliberate transponder shutdown. The expected and earliest countdowns are model outputs, not guaranteed arrival times. The proposed provenance and uncertainty UI are described in [08-research-and-next-ideas.md](08-research-and-next-ideas.md).

This playbook is for **Argus Mara** (Challenge 3). The dated plan and checklists are in [04-work-plan.md](04-work-plan.md), and the build recipes are in [05-build-guide.md](05-build-guide.md).

## 3.1 Questions for the organisers (send this week)

Event questions go to the DCU:Innovate Hub contact on the official page.

1. What is the judging rubric and its weights? How long are the pitch and the Q&A? What must be submitted: deck, video, repo?
2. Does the jury try to spread the prizes across the three challenges?
3. Will any data, APIs, hardware or compute be provided during the event (TensorX credits, Defence Forces RTI data)?
4. Can we fly small drones on site? Glasnevin is about 5 km from Dublin Airport, so outdoor flights probably need clearance from the Irish Aviation Authority. We don't need drones for Argus Mara, but ask anyway.
5. Is the venue internet good enough for live data streams?
6. What are the dates of the pre-event drone workshops?
7. Will Department of Defence or Defence Forces mentors be available early on Day 1?

**Eligibility reminder:** every member must be 18+ and a citizen of the EU, Norway or Ukraine, and must bring a passport or national ID. IDs are checked on site.

## 3.2 Before the event: the habits that win

- **Talk to real operators.** Get 20 minutes each with one or two: a retired Naval Service officer, a Coast Guard watch officer, or a cable-operator engineer. Ask:
  - What do you watch?
  - What do you ignore?
  - What decision do you need to make, and how fast?
  - How many false alarms would you tolerate?
  - **Quote them in the pitch.**
- **Go to the drone workshops** if you are invited. Meet the RTI unit, Hextronics, Drone Space and the other teams.
- **Check the defence figures in Budget 2027** (early October) so your numbers are fresh.
- **Contact the Sea-Scan team** (plan §4.8), and **keep `PRIOR_WORK.md` current**.

## 3.3 Roles during the event and the pitch

| Workstream owner | During the pitch |
|---|---|
| **E. Story, the lead (you)** | Presents |
| D. Interface | Drives the demo |
| B. Brain | Takes detection, metrics and false-alarm questions |
| C. Space | Takes satellite and identity questions |
| A. Data | Standby on the backup screen recording; takes data-source questions |

## 3.4 The 4-minute pitch

Use the current [four-minute demonstration runbook](demo-runbook.md) for exact clicks,
timing and words. The earlier *Eagle S* and identity-mismatch talk track is superseded:
the fictional radar association is unconfirmed, the rule alert fires at minute 90,
and measured performance claims are pending validation.

| Time | Beat |
|---|---|
| 0:00–0:30 | State the operator decision and label the exercise fictional. |
| 0:30–1:05 | Show the AIS gap and separate radar contact without claiming identity. |
| 1:05–1:35 | Show the observed speed and course changes and the four review cues. |
| 1:35–2:15 | Explain expected and earliest countdown assumptions. |
| 2:15–2:45 | Compare assumed response arrival times. |
| 2:45–3:20 | Review uncertainty and record a simulated human decision. |
| 3:20–3:45 | Open the fictional Space review and export the decision record. |
| 3:45–4:00 | State what operational validation is still needed. |

### Who can reach it: the responder demo (about 2 minutes)

Run it in the desktop app (`RUN-GUI-WINDOWS.bat`) with the replay at the exercise
alert, T+01:30. Every contact is fictional; bases are public places, and every speed,
readiness time, range and drone site is a labelled assumption (D58).

| Click | What the judges see | Say |
|---|---|---|
| Open the Incidents panel. | Each card has a responder line: blue means someone arrives before the earliest line ETA, red "No responder in time" means nobody does, and the level is raised one step. | "For every incident we work out who can get eyes on the ship before it can reach the cable." |
| Click the CORMORANT STAR card, then press **Escalate**: the window shows **Who can reach it** above the escalation form. | Drone D1 from Howth, 31 min, in time by 30 min; every other asset with minutes, too late, or why it cannot go. The map shows the bases and a dashed route to the meeting point. | "We intercept a moving ship, even with AIS off: we aim where it will be, not where it was." |
| Point at the amber warning under D1. | "Only D1 reaches SEA LARK, AMBER SKERRY in time." | "Assets are shared. Before you send one, you see who you leave uncovered." |
| Press **Send** on D1. | SEA LARK turns Critical and AMBER SKERRY High; their cards say "No responder in time · D1 assigned to INC-…". The status line names them. | "The system shows the cost of a decision. A human still makes it." |
| Press **Recall** on D1, then **Send** on D2 (Wicklow Head, in time by 28 min). Press Play. | Everyone is covered again. On the map D2 shows *preparing*, then *en route*, then *on scene* with the ship. | "That is the better allocation, and you can watch it play out on the replay clock." |
| Optional: press **Storm 30 kn** (in the same Escalate view). | Every drone greys out ("wind 30 kn above the 25 kn drone limit"); a helicopter becomes the best option and more incidents turn Critical. | "In bad weather coverage shrinks, and the board says so honestly." |

Reset with the ↻ button in the Incidents panel. Send, Recall and Escalate are simulated
decisions written to the incident log; nothing is transmitted.

### Brain finds it from the track: the anchor-drag story (about 2 minutes)

Same app, same start: the replay at the exercise alert, T+01:30, at the default 60×
(one replay minute per second). VESNA DRIFT, HOLM SENTINEL, LAMBAY ROSE and SKERRIES
DART are fictional ships on fictional AIS tracks. Nobody wrote their observations:
at every replay step Brain's detectors read the track and score it against the
illustrative cable routes (D59). Their cards carry the tag **BRAIN** and the words
"from track"; the older simulated contacts say **SIM** and "hand-written".

| Click | What the judges see | Say |
|---|---|---|
| Click the **WATCH** tile in the Incidents panel. | VESNA DRIFT · BRAIN: "Under way at 12 kn, … nm from Dublin–Holyhead telecom cable: no behaviour cue". LAMBAY ROSE at anchor 3 nm from the line, also no cue. | "A ship near a cable is not an alarm. Ships cross cables all day." |
| Press **Play**. At T+01:50 VESNA DRIFT crosses the Dublin–Holyhead route at 12 kn. | It stays in Watch. SKERRIES DART, a 19 kn ferry, crosses three routes and stays in Watch too. | "Fast and straight across the line: nothing to explain." |
| Keep playing. At T+01:57 the card jumps up as an incident. | **High**, "Slowing and yawing across EWIC without an AIS gap", ETA about 27 min to EWIC, and a red line: "No responder in time · best D1 38 min, 11 min late". | "It slowed from 12 to 9 knots 5 nm from the interconnector, with no AIS gap. The old four-cue rule needed a gap and would have missed it." |
| At T+02:05 it turns **Critical**; the ETA counts down from about 21 min. | The card's timer runs in red. | "Now the course is unsteady too: speed down 25%, course swinging 26°, the anchor-drag pattern. And nobody can be there in time, so the level goes up one step." |
| Press **Pause** and click the card. | Review window tagged **BRAIN · FROM TRACK**. *Why this level*: +4 anchor-drag pattern, +4 reaches the anchor-reachable section in 20 min, +2 power interconnector. *Findings by detector*: "Cable risk from the track" with each number and its threshold. *Data labels*: SOURCE, SIMULATED, ILLUSTRATIVE, ASSUMPTION. | "Every point has a reason and a threshold you can argue with. Brain found this; we only wrote the ship's track." |
| Press **Escalate**. | *Who can reach it*: Drone D1 (Howth) 39 min, 18 min late; Rescue 116 49 min; Drone D2 50 min; the aircraft 61 min. | "Honest answer: nobody arrives before the anchor can reach the cable. That is why the level is Critical." |
| Press **Send** on D1, then **Play**. | Log: "Sent Drone D1: eyes on in 39 min, 18 min late". On the map D1 is *preparing*, then *en route*. At T+02:24 VESNA DRIFT is "In corridor" and back to **High** (the corridor rules score it now). D1 is *on scene* at about T+02:45. | "We still send the fastest asset: eyes on and evidence for the operator, even when we cannot prevent the contact." |
| Optional: click HOLM SENTINEL. | Medium at T+02:05: "Held at 3 kn or less within 2 nm of the line for 1.0 h". At about T+02:30 it anchors 0.9 nm from the North Dublin cluster and stays **High** (loitering, then anchored by the line). | "A second pattern from the same detector: loitering, then anchoring next to the cluster." |

Limits to say if asked: the routes are illustrative, so their depth is unknown and an
anchor is assumed to reach the seabed along the whole route. Every threshold is a team
assumption (D59), and the level is a rule outcome for review, not a probability of intent.
Reset with ↻; rewinding the slider replays the stories backwards too.

## 3.5 Hard questions to rehearse

1. **"Commercial AIS cable-watch services already exist (NKT, Sentinel Proactive, UltramapGlobal, Gatehouse). Why you?"**
   - They warn ships about accidental anchoring on behalf of one cable owner, and their existence proves the market.
   - Argus Mara is for the State: all seabed infrastructure at once, *adversarial* ships (dark, false identities, sanctioned), a countdown with response planning, fibre fusion, and it's sovereign.
2. **"How is this different from Windward, Kpler or Global Fishing Watch?"** Those are generic maritime-intelligence platforms. We work at cable-segment level with anchor-reach physics and feasibility-aware decisions, fuse Irish sensors, and run sovereign.
3. **"Isn't anchor-drag detection what Sea-Scan does?"**
   - Sea-Scan hears it *at the cable*. We see the ship coming hours earlier, name it, cover pipelines and power cables, and plan the response.
   - It works both ways: their fibre event triggers our identification, and our countdown tells their fibre where to listen. Our clean AIS tracks also improve their training labels.
4. **"Satellite data isn't real time."** Correct. The countdown runs on real-time AIS. Space gives custody and identity checks at each pass, and we plan the next look.
5. **"What if the ship turns off AIS or spoofs it?"** A reception gap is a review cue, not proof of switch-off. A separate radar contact can support a custody hypothesis only after time, position and measurement uncertainty are checked. The current fictional exercise does not demonstrate confirmed identity.
6. **"How many false alarms?"** No verified false-alarm rate is available yet. The rule produces review alerts in the fictional replay; measured rates require a labelled evaluation set. Do not turn an unlabelled alert count into a false-alarm claim.
7. **"AIS coverage far offshore?"** Terrestrial AIS near the coast today. Satellite AIS (Sentinel-1C/1D carry AIS receivers too) and EMSA feeds through the Defence Forces are on the roadmap.
8. **"What can Ireland legally do in its EEZ?"** The system informs and people decide. It supports hailing, notifying operators and partners, and evidence packs. Boarding-powers legislation is being drafted.
9. **"How good are your incident reconstructions?"** They are built from public reporting and clearly labelled. Validation on real data is step one of the RTI trial.
10. **"What's autonomous about it?"** Monitoring, custody, prediction and cueing run 24/7 without a human, within pre-approved rules. Actions stay human.
11. **"Business model?"** A State licence per region plus integration, with a commercial add-on per protected asset.
12. **"Will the team continue?"** Name who commits, plus DCU incubation, ESA BIC, the RTI trial, and the Sea-Scan pilot.

## 3.6 Demo rules

- **Have an offline replay mode.** Never depend on venue Wi-Fi, and cache every dataset locally.
- **Keep a screen recording of a working run** as the fallback, on a laptop and on a USB stick.
- **Use fictional vessel names** in scenarios, and label everything *real*, *reconstructed* or *simulated*. That includes the fibre cue.
- Show one screen, with big fonts, rehearsed clicks and a reset button.
- Keep the calculated countdown and response times on screen; do not display unmeasured performance numbers as results.
- **Never transmit radio signals** of any kind for testing. Use recorded data only.

## 3.7 What to bring

- Passports or national ID cards for everyone.
- Laptops and chargers, HDMI/USB-C adapters, and a 4G/5G hotspot.
- Offline data copies and the backup screen recording on USB.
- A printed one-page summary for judges, with a QR code to the demo video.

## 3.8 After the hackathon, where most of the value is

- **If you win:** EUDIS mentoring (about 40 h over about 2 months), then an EU-wide final judged on **progress**. Run the 8-week plan in [04-work-plan.md §4.7](04-work-plan.md).
- **Whatever you place:** ask about DCU:Innovate incubation, TensorX credits, and test and validation with the RTI unit. Those supports are open to several teams.
- **Research Ireland Defence Innovation Challenge 2026:** it closes 29 Oct, but the **intent-to-apply deadline was 15 Sep 2026**. It is only possible through a partner who already registered, e.g. ask the Sea-Scan team. Otherwise, aim for the next round.
