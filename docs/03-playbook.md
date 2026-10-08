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
