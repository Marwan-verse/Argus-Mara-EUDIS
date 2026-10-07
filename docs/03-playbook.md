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

| Time | Beat | Talk track (adapt freely) |
|---|---|---|
| 0:00–0:30 | **Hook** | "August 2025. A sanctioned tanker called *Blue* switched off its transponder before entering Irish waters. It has had four identities and six flags in five years. Since March, an unprecedented number of ships like it have sailed past our west coast. On Christmas Day 2024, a ship like that, the *Eagle S*, slowed from 12 to 9 knots in the Gulf of Finland and dragged its anchor about 90 kilometres across the seabed. It cut a power cable and several data cables. The signal was there. **Nobody was counting down.**" |
| 0:30–0:55 | **Irish stakes** | "About eleven transatlantic cables. The pipelines that bring most of our gas. A sea area seven times our land. And crews for two ships at sea. The new Maritime Security Strategy asks for three things: protecting undersea infrastructure, better maritime awareness, and a national maritime security centre for faster decisions. The problem isn't data. It's attention and time." |
| 0:55–1:10 | **Solution** | "**Ireland can crew two ships. Argus Mara gives them a hundred eyes.** It watches every ship, every minute. When one becomes a threat, it starts a **countdown to the cable it threatens**, and it shows what can get there in time." |
| 1:10–2:40 | **Live demo** | The 8 steps in [02-ideas.md](02-ideas.md): dark tanker → radar regains it → identity mismatch → it turns towards the shelf → the countdown → *Eagle S* signature → action panel → "confirmed by fibre" → evidence pack. |
| 2:40–3:10 | **Proof** | False alarms per day against the geofence baseline, warning time on the *Eagle S* replay, and the dark-period custody rate. |
| 3:10–3:35 | **Fit and path** | "Argus Mara complements Trinity's Sea-Scan. They hear the cable; we see the ship coming and name it. It runs on open and space data and on sovereign EU compute. Next: a trial with the RTI unit on historical data, and a joint pilot with Sea-Scan on the Dublin–Holyhead link." *Say "joint pilot" only if they agreed; otherwise say "designed to complement Sea-Scan".* |
| 3:35–3:50 | **Honesty and team** | What existed before (the `pre-hackathon` tag) vs what was built here, and who you are. |
| 3:50–4:00 | **Ask** | "Six weeks with the RTI unit on historical data, and your help connecting Argus Mara to the future national maritime security centre." |

## 3.5 Hard questions to rehearse

1. **"Commercial AIS cable-watch services already exist (NKT, Sentinel Proactive, UltramapGlobal, Gatehouse). Why you?"**
   - They warn ships about accidental anchoring on behalf of one cable owner, and their existence proves the market.
   - Argus Mara is for the State: all seabed infrastructure at once, *adversarial* ships (dark, false identities, sanctioned), a countdown with response planning, fibre fusion, and it's sovereign.
2. **"How is this different from Windward, Kpler or Global Fishing Watch?"** Those are generic maritime-intelligence platforms. We work at cable-segment level with anchor-reach physics and feasibility-aware decisions, fuse Irish sensors, and run sovereign.
3. **"Isn't anchor-drag detection what Sea-Scan does?"**
   - Sea-Scan hears it *at the cable*. We see the ship coming hours earlier, name it, cover pipelines and power cables, and plan the response.
   - It works both ways: their fibre event triggers our identification, and our countdown tells their fibre where to listen. Our clean AIS tracks also improve their training labels.
4. **"Satellite data isn't real time."** Correct. The countdown runs on real-time AIS. Space gives custody and identity checks at each pass, and we plan the next look.
5. **"What if the ship turns off AIS or spoofs it?"** Custody through the dark with radar, the identity check (radar length vs AIS length, flag and name history), spoofing detectors, and fibre fusion.
6. **"How many false alarms?"** Give the measured rate and the ratio against the naive geofence, then say plainly where it was measured: tuned and counted on the Danish Maritime Authority's free raw AIS archive, which is large and real, and confirmed on our own live recording of Irish traffic. Never inflate our own recording into "weeks" — it is days, and the split is more credible than the claim would be. Then explain the context suppression.
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
- Keep the headline numbers **on screen** at the end of the demo.
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
