# 4. The plan: Argus Mara, from today to the pitch

*Rewritten on 7 October 2026. The previous plan (phases starting 24 September) was not
executed and is superseded — see [DECISIONS.md](../DECISIONS.md) D11.*

**Where we are:** nothing is built yet. **Eight days** remain before the event
(15–17 October). The Russian short version, which is the one the team reads daily, is in
[plan-ru.md](plan-ru.md).

**Goal:** win Dublin with a **live demo of the Argus Mara countdown**, two hard numbers, and
a visible link to Trinity's Sea-Scan.

---

## 4.0 The one rule

> **A demo that runs end to end by Friday 9 October, 20:00.** Ugly. On invented data. But
> complete, from the first ship on the map to the operator pressing *approve*.

Every day after that, we replace one invented part with a real one. If a replacement fails,
we still have a working demo. That is how we make losing impossible.

The opposite order — four perfect components, assembled at the end — is how teams arrive at a
hackathon with nothing that switches on. We are not doing that.

## 4.1 Who owns what

| Workstream | Owners | Scope |
|---|---|---|
| **Story + integration** | **Mykhailo** (captain) | Pitch, organisers, Sea-Scan, demo script. Every evening: pulls everything together and checks the demo still runs end to end |
| **Data** | **Ihor Maslovskyi** + **Bohdan** | The AIS recorder 24/7. Cable routes and seabed depth. The scenario file |
| **Brain** | **Nazar Kyrychenko** + **Myroslav** | Detectors, the countdown, response-asset ETAs |
| **Space** | **Nazariy Buryak** | Sentinel-1: dark ships and the identity check |
| **Interface** | **Adam Pohořilský** + **Marwan** | Map, moving vessels, alert card with the live countdown, action panel, evidence page |

**Why pairs.** One person who gets stuck goes quiet for two days. Two people talk, and talking
unsticks them. Space is a single owner because it is the one piece nobody else depends on;
if it stalls, the captain joins, and if it stalls twice, we cut it to a screenshot.

## 4.2 How the workstreams stay unblocked

Two files, agreed once, and nothing else needs negotiating. Both already exist in
[`demo/`](../demo/) with worked examples:

| File | Answers | Written by | Read by |
|---|---|---|---|
| `demo/scenario.json` | *What happened* | Data | Interface, Brain |
| `demo/alerts.json` | *What Argus Mara noticed* | Brain | Interface |

**There is no backend in v1.** The interface loads two JSON files and plays them. Nothing to
deploy, nothing to break on stage, and it works offline. A live FastAPI endpoint comes later,
only once the demo already runs. Field names are frozen: add fields freely, never rename one
without telling the other workstream. Full contract in [`demo/README.md`](../demo/README.md).

## 4.3 At a glance

| When | Goal | Done when… |
|---|---|---|
| **Wed 7 Oct** (today) | Start | 40-minute call; roles taken; **the AIS recorder is recording**; emails sent; accounts created |
| **Thu 8 Oct** | Four pieces, built in parallel | Each workstream's piece runs on the sample files. Screens shared at 21:00 |
| **Fri 9 Oct** | **DEMO v1** | The whole 7-step story plays end to end at 20:00. Phone video recorded |
| **Sat 10 – Sun 11 Oct** | Make it real | Real cables, real depth, real traffic, countdown v2, one real space example. **DEMO v2** Sun 20:00 |
| **Mon 12 Oct** | The two numbers | Both numbers computed and **on screen** |
| **Tue 13 Oct** | Freeze | **Feature freeze 20:00.** Anything not working is cut. Runs with the Wi-Fi off |
| **Wed 14 Oct** | Rehearse | Two offline dry runs; backup video; pitch said aloud 5×; `git tag pre-hackathon`; `PRIOR_WORK.md` |
| **Thu 15 – Sat 17 Oct** | The hackathon | Mentors first, then build. Freeze Fri 17:00. Pitch Sat |

## 4.4 Wednesday 7 October — start

**Everyone:** a 40-minute call. Read this plan together. Each person says aloud what they will
do tomorrow. Everybody gets repo and chat access.

**Ihor — today, not tomorrow: start the AIS recorder.** Every hour of delay is an hour of
traffic we can never get back.
1. Get a free API key at aisstream.io (sign in with GitHub). Never commit it, never paste it in chat.
2. Find an always-on machine. A small cloud VM (Hetzner, DigitalOcean) at €4–6/month is ideal.
   A laptop sleeps, so use one only for a test.
3. `python3 -m pip install -r recorder/requirements.txt`, then
   `AISSTREAM_API_KEY=… nohup python3 recorder/recorder.py >> recorder.log 2>&1 &`
4. After 15 minutes, `python3 recorder/check.py`.

Full instructions in [`recorder/README.md`](../recorder/README.md). By the pitch we will have
**8 days** of our own traffic, not three weeks. That is still enough for false-alarms-per-day.
We say "eight days" on the slide — never round it up.

**Mykhailo — today:**
- Email the organisers the questions in [03-playbook.md §3.1](03-playbook.md), and **confirm
  our place is accepted**.
- Email the Sea-Scan team at TCD (template in §4.11).
- Create the accounts: Copernicus Data Space (hand to Nazariy), Global Fishing Watch.
- Create a board with the tasks below, one column per day.

## 4.5 Thursday 8 October — four pieces in parallel

Nobody waits for anybody. Everyone already has the sample files.

**Data (Ihor, Bohdan)**
- [ ] The recorder is confirmed recording, and `check.py` is clean.
- [ ] Download cable and pipeline routes (EMODnet Human Activities, TeleGeography) and
      bathymetry (GEBCO or EMODnet) for Irish waters. Download only — do not process yet.

**Brain (Nazar K., Myroslav)**
- [ ] `argus/brain.py`: read `scenario.json`, write `alerts.json`.
- [ ] Detector v1, one rule: *inside the anchor-reach zone, and speed fell more than 20% below
      the vessel's own last-hour median, with no port, weather or traffic reason.*
- [ ] Countdown v1: project the vessel straight ahead at its current speed and course, and find
      where it crosses the cable. **A working implementation is already in
      `demo/make_scenario.py` → `project_to_cable()`. Take it.**

**Interface (Adam, Marwan)**
- [ ] `ui/index.html`: MapLibre with a **local** coastline GeoJSON (no web tiles — the demo must
      run offline), the cable as a line, and a vessel moving through the points in
      `scenario.json`.
- [ ] Play / pause / restart controls. No alert card yet.

**Space (Nazariy)**
- [ ] Copernicus account working.
- [ ] Download **one** Sentinel-1 IW GRD scene over the Irish Sea, open it in ESA SNAP, screenshot it.
      That is today's whole target: see the picture.

**Mykhailo**
- [ ] Pitch outline, and the demo script written as numbered beats.

**21:00, 15 minutes: everyone shares a screen.** Showing, not describing.

## 4.6 Friday 9 October — DEMO v1 ⬅ the day that matters

Build in the morning. **At 20:00 everyone joins and runs it together**, start to finish:

1. A map of Ireland, with the cable drawn on it.
2. The tanker sails. It switches off AIS and disappears.
3. A radar detection appears — it is still there.
4. AIS returns. It has turned toward the shallow stretch over the cable.
5. It slows, 12 → 9.1 kn. **The alert card appears, with a countdown ticking: 1:15:00 to the cable.**
6. The options: aircraft ✅ 39 min · patrol ship ❌ 232 min · VHF ❌ out of range · next satellite ❌ 250 min.
7. *Approve* is pressed.

All of it on invented data. That is fine, and it is honest, because the screen says
**simulated**. The moment it runs, **record it on a phone** — that video is our fallback for
the rest of the week.

If it does not come together, Friday evening and Saturday morning go to nothing else. **No new
work starts until the demo runs end to end.**

## 4.7 Saturday 10 – Sunday 11 October — make it real

Replace invented parts with real ones, one at a time. The demo must not be broken for longer
than an hour at a stretch.

- **Data:** real cable geometry on the map. Sample depth along each route and mark the
  sub-segments under 250 m — they glow. Replay real recorded traffic around the fictional
  tanker, so the map looks like the sea actually looks.
- **Brain:** countdown v2 — not one straight line but ~50 perturbed futures (speed ±20%, course
  ±5°). Big number = expected, small print = "earliest 1:03". The uncertainty is a credibility
  win, not a weakness. Then response options with real geometry.
- **Space:** detect ships in the real scene (SNAP Ship Detection, or CFAR), estimate length,
  match against our recorded AIS at the scene timestamp. Find **one real** case of a length
  mismatch or a radar contact with no AIS. One real example outweighs ten invented ones.
  *Faster fallback if detection stalls: Global Fishing Watch radar detections come with length
  estimates and AIS matches already computed.*
- **Interface:** the alert card properly built — reason chips ("speed dropped 12 → 9.1 kn",
  "over the cable in shallow water", "AIS silent for 20 min"), state badge, and the evidence page.
- **Mykhailo:** pitch v1 and the hard-questions cards.

**Sunday 11 October, 20:00: DEMO v2** — the same seven beats, with real data inside.

## 4.8 Monday 12 October — the two numbers

Judges remember numbers, not features. We need exactly two, and both must be **on screen**:

1. **False alarms per day**, ours against a plain geofence baseline, measured over our 8 days
   of recording. Hand-check the top 20. *(Brain)*
2. **Warning time on the *Eagle S* reconstruction** — minutes from our first alert to the cable
   crossing, replaying its publicly reported profile. *(Brain + Mykhailo)*

## 4.9 Tuesday 13 October — freeze

**Feature freeze at 20:00.** Anything not working is cut, without debate. Fixes only from here.
In the evening, confirm the whole demo runs with the **Wi-Fi switched off**.

## 4.10 Wednesday 14 October — rehearse

- [ ] Two full offline dry runs, timed: 4 minutes for pitch plus demo.
- [ ] Record the proper backup video. Keep it on two laptops and a USB stick.
- [ ] Pitch said aloud **five times**. Print the one-pagers.
- [ ] Fill in `PRIOR_WORK.md`, then `git tag pre-hackathon` and push it. The organisers require
      us to declare what existed before the event.
- [ ] Passports, chargers, adapters, laptops charged.

## 4.11 Thursday 15 – Saturday 17 October — the hackathon

| Day | Plan |
|---|---|
| **Thu** | **First two hours: do not code.** Interview the mentors (Department of Defence, the RTI unit, TCD if present). Ask what they actually need. Write down three changes and make exactly those. This is our advantage: ours already runs while others are still assembling. |
| **Fri** | Numbers and polish. **Freeze at 17:00.** Record the final video, then rehearse with a mentor watching. |
| **Sat** | Fixes only. Rehearse five times. Pitch. Then collect contacts: Department of Defence, the RTI unit, TCD, TensorX, the Irish Space Association, Deloitte. |

Deliverables: the live demo, slides, the video, and the repo. The `pre-hackathon` tag shows
what existed beforehand; everything after it was built at the event.

## 4.12 What we are deliberately NOT building

Agreed in advance, so nobody reopens it mid-week:

- a learned (ML) anchor-drag model — **rules only**, which are also easier to explain to judges;
- the LLM watch-officer brief;
- anything airborne: drones, UAVs;
- tasking new satellite imagery — existing scenes only;
- a real Sea-Scan integration — a **simulated** fibre feed in a plausible shape, clearly labelled;
- a database, authentication, mobile layout, or a design system from scratch.

If someone proposes one of these, the answer is "after the hackathon".

## 4.13 The Sea-Scan (Trinity) partnership

**Why:** Research Ireland and the Defence Forces funded Sea-Scan, and the jury knows it.
"We join it up" beats "we compete with it".

**Steps:**
1. **Read their two papers first:**
   - *Sea-Scan: weakly supervised fibre-sensing (DAS) dark-vessel detection*, arXiv 2606.21326. †
   - *DAS–AIS association patterns on the Dublin–North Wales link*, arXiv 2607.02536. †
2. **Email today (7 Oct)** to Prof. Marco Ruffini (School of Computer Science and Statistics)
   and Dr John Kennedy (School of Engineering), both at TCD. Addresses are on the TCD staff pages.
3. **Follow up Friday 9 Oct**, asking for a 20-minute call before the event.
4. **On the call, ask:** (a) may we describe Sea-Scan as complementary? (b) would you give
   informal advice? (c) any interest in a joint pilot on the Dublin–Holyhead corridor after the
   event? (d) what does your fibre-event output look like, so our adapter matches it?
5. **Wording in the pitch:** with written consent, *"designed with input from the Sea-Scan team
   (TCD)"*. Otherwise, *"designed to complement Sea-Scan"*.

**Don'ts:** no claim of partnership or endorsement without written consent; no use of their data
or logo; never present their numbers as ours.

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
> Would you be open to a 20-minute call this week? We would value your advice, and we would like your permission before mentioning Sea-Scan by name in our pitch. If there is interest, we would be glad to explore a small joint pilot after the event.
>
> Kind regards,
> [Name] · [team] · [phone]

## 4.14 Rhythm

- **Every evening, 21:00, 15 minutes.** Everyone shares a screen. Showing, not describing.
  If you are stuck, say so on the call, not in a message at 2 a.m.
- **Stub first, replace second.** Build behind the agreed JSON files with fake data until the
  real piece arrives.
- **Cut, don't stretch.** Anything not working on Tuesday 13 Oct is dropped.
- **Label everything** on screen: *real*, *reconstructed*, *simulated*, *fictional*, *assumption*.

## 4.15 The finish line (17 Oct checklist)

- [ ] The 7-step demo runs **offline**, end to end.
- [ ] Two numbers on screen: **false alarms per day (ours vs the geofence)** and **warning time
      on the *Eagle S* replay**.
- [ ] At least **one real example** of a dark ship or an identity mismatch.
- [ ] The evidence pack opens.
- [ ] The 4-minute pitch rehearsed 5+ times, the backup video, and the one-pager.
- [ ] Prior work declared (`pre-hackathon` tag plus `PRIOR_WORK.md`).
- [ ] Sea-Scan mentioned with the right, consent-based wording.

## 4.16 After the hackathon

- **If we win**, EUDIS mentoring follows (about 40 h over about 2 months), then the EU-wide
  final, judged on **progress**. The 8-week plan: validation with the RTI unit on unclassified
  historical data; a joint pilot with Sea-Scan on the Dublin–Holyhead corridor; satellite-AIS
  integration; one letter of intent from a cable or energy operator; an ESA BIC application.
- **Whatever we place:** ask for DCU incubation, TensorX credits, and test and validation with
  the RTI unit.
