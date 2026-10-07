# 4. The plan: Argus Mara, from today to the pitch

*Rewritten 7 October 2026. The previous day-by-day schedule is superseded — see
[DECISIONS.md](../DECISIONS.md) D11 and D17. The Russian short version, which is the one the
team reads, is [plan-ru.md](plan-ru.md).*

**Where we are:** our place is confirmed (DCU, 1 Oct: *"Congratulations on being accepted"*;
over 20 teams). Nothing is built yet. **Eight days** remain.

**Goal:** win Dublin with a live demo of the Argus Mara countdown, two hard numbers, and a
visible link to Trinity's Sea-Scan.

---

## 4.1 The one rule

> **Assemble the whole demo first, then make it good.**

Ugly, on invented data, but complete — from the first ship on the map to the operator pressing
*approve*. After that, replace one invented part per day with a real one. If a replacement
fails, the working demo is still there.

The opposite order — four perfect components assembled at the end — is how teams arrive at a
hackathon with nothing that switches on.

## 4.2 Who owns what

| Workstream | Owners | Scope |
|---|---|---|
| **Story + integration** | **Mykhailo** (captain) | Pitch, organisers, demo script. Checks every evening that the demo still runs end to end |
| **Data** | **Ihor Maslovskyi** + **Bohdan** | Ships, cables, seabed depth, the scenario file |
| **Brain** | **Nazar Kyrychenko** + **Myroslav** | Detectors, the countdown, response ETAs, the two numbers |
| **Space** | **Nazariy Buryak** | Dark ships and the identity check from radar |
| **Interface** | **Adam Pohořilský** + **Marwan** | Map, alert card with the live countdown, action panel, evidence page |

**Why pairs.** One person who gets stuck goes quiet for two days; two people talk, and talking
unsticks them. Space is a single owner because it is the one piece nobody else depends on.

## 4.3 How the workstreams stay unblocked

Two files, agreed once, already in [`demo/`](../demo/) with worked examples:

| File | Answers | Written by | Read by |
|---|---|---|---|
| `demo/scenario.json` | *What happened* | Data | Interface, Brain |
| `demo/alerts.json` | *What Argus Mara noticed* | Brain | Interface |

**No backend in v1.** The interface loads two JSON files and plays them: nothing to deploy,
nothing to break on stage, and it runs offline. A live API comes later, only once the demo
already runs. Add fields freely; never rename one without telling the other workstream. Full
contract in [`demo/README.md`](../demo/README.md).

## 4.4 The stages

There is no hour-by-hour schedule — we do not yet know what will take how long. **Two hard
deadlines only**, in bold.

### Stage 1 — now: each workstream builds its own piece

Nobody waits for anybody; everyone already has the sample files.

- **Data:** start the recorder; get the cable routes and bathymetry (see §4.5).
- **Brain:** `argus/brain.py` — read `scenario.json`, write `alerts.json`. One rule to start:
  *inside the anchor-reach zone and speed fell sharply with no reason*. Countdown v1: project
  the vessel straight ahead and find where it crosses the cable. A working implementation is
  already in `demo/make_scenario.py` → `project_to_cable()`; take it.
- **Interface:** map of Ireland from a **local** coastline file (no web tiles — it must run
  offline), the cable as a line, a vessel moving through the scenario points.
- **Space:** Copernicus account; download and open one Sentinel-1 scene over the Irish Sea.
- **Mykhailo:** pitch outline, demo script as numbered beats.

### Stage 2 — **hard deadline: the demo runs end to end by the end of the weekend**

Everyone joins and runs it together. The seven beats, in order:

1. A map of Ireland with the cable on it.
2. The tanker sails, switches off AIS, disappears.
3. A radar detection appears — it is still there.
4. AIS returns; it has turned toward the shallow stretch over the cable.
5. It slows. **The alert card appears, countdown ticking: 1:15:00 to the cable.**
6. Options: aircraft ✅ 39 min · patrol ship ❌ 232 min · VHF ❌ out of range · next satellite ❌ 250 min.
7. *Approve* is pressed.

All on invented data — fine, and honest, because the screen says **simulated**. The moment it
runs, **record it on a phone**. That video is the fallback for the rest of the week.

Until this works, no new work starts.

### Stage 3 — replace the invented parts with real ones

One at a time; the demo must not stay broken for more than about an hour.

- **Data:** real cable geometry, real depth, so the sub-segments an anchor can reach glow.
  Real recorded traffic playing around the fictional tanker.
- **Brain:** countdown v2 — ~50 perturbed futures (speed ±20%, course ±5°) instead of one
  straight line. Big number expected, small print "earliest 1:03". The uncertainty is a
  credibility win, not a weakness.
- **Space:** find **one real** case — a radar contact with no AIS, or a length that does not
  match the declared one. One real example outweighs ten invented ones.
- **Interface:** alert card with reason chips, state badge, evidence page.

**The two numbers**, which must end up on screen, not just in the talk:
1. **False alarms per day**, ours against a plain geofence baseline.
2. **Warning time on the *Eagle S* reconstruction** — minutes from our first alert to the
   cable crossing.

### Stage 4 — **hard deadline: feature freeze, Tuesday 13 October evening**

Anything not working is cut, without debate. Fixes only after that.

Wednesday 14 October: two full dry runs **with the Wi-Fi off**, timed at 4 minutes for pitch
plus demo; record the proper backup video onto two laptops and a USB stick; pitch said aloud
five times; fill in `PRIOR_WORK.md` and push `git tag pre-hackathon`; passports and chargers.

### Stage 5 — the hackathon, 15–17 October

| Day | Plan |
|---|---|
| **Thu** | **First two hours: do not code.** Interview the mentors (Department of Defence, the RTI unit, TCD if present). Ask what they actually need, write down three changes, make exactly those. Our advantage is that ours already runs while others are still assembling. |
| **Fri** | Numbers and polish. **Freeze at 17:00.** Record the final video; rehearse with a mentor watching. |
| **Sat** | Fixes only. Rehearse five times. Pitch. Then collect contacts: Department of Defence, the RTI unit, TCD, TensorX, the Irish Space Association, Deloitte. |

## 4.5 Data: what already exists, so we do not record it ourselves

We checked. Several usable public archives exist, but each gives only part of the picture, so
we use more than one.

| Source | What it gives | Who needs it |
|---|---|---|
| **Global Fishing Watch API** (globalfishingwatch.org/our-apis) | Free for non-commercial use. Vessels detected by **satellite radar**, including *unmatched* detections — radar contacts that are not broadcasting AIS. Covers Irish waters. Also AIS-derived vessel presence, 2012 to ~96 h ago | **Space** — real dark ships without processing a single scene. The single biggest shortcut available to us |
| **EMODnet Human Activities** vessel density (emodnet-humanactivities.eu) | Free. Monthly 1×1 km shipping-density grids by ship type, all EU waters including Ireland. GeoTIFF | **Data** — map background, and "what is normal here" |
| **Danish Maritime Authority** open AIS (dma.dk → AIS data) | Free raw per-vessel AIS as CSV. **Danish waters, not Irish** | **Brain** — a large, real dataset to tune the detector and count false alarms on. The Baltic is also where the cable incidents happened |
| **Our own recorder** (`recorder/`, aisstream.io) | Live Irish traffic, right now | **Data** — the live picture in the demo |
| *Backup live feeds* | AISHub (free if you contribute a receiver); Open Waters AIS, which is aisstream-compatible, so `ARGUS_AIS_URL` can point the existing recorder straight at it | **Data**, if the aisstream key is slow to arrive |

**We found no free archive of raw *Irish* AIS.** So we split it honestly:

- tune the detector and measure false alarms on the **Danish** data, which is large and real;
- show on **our own Irish recording** that it also works on Irish traffic.

Say exactly that to the judges. It is stronger than "we have a week of our own data".

**Still start the recorder today** — it takes about 20 minutes ([recorder/README.md](../recorder/README.md)) —
because it gives the demo a live picture and Global Fishing Watch lags by about four days, and
because "we run our own receiver" is a good line. But it is no longer the week's critical task.

> The Danish AIS page could not be opened from our build environment (the network policy blocks
> it). Check the current download URL and date range from your own machine before relying on it.

## 4.6 What we are deliberately NOT building

Agreed in advance so it is not re-argued every day: no learned/ML detector (**rules only**, which
also explain better to judges); no LLM brief; nothing airborne; no tasking of new satellite
imagery; no real Sea-Scan integration (a **simulated** fibre feed, clearly labelled); no
database, authentication, mobile layout or design system. If someone proposes one, the answer
is "after the hackathon".

## 4.7 What the organisers are offering (from their emails)

- **TensorX:** AI credits, and the €4000 third prize.
- **CADFEM / Ansys STK:** a free licence for satellite mission-design software, one per team.
  Potentially useful to Space for computing the real "next satellite look" over a position.
  **Requires a university or company email — Gmail is not accepted.** We have `@setu.ie`
  addresses. Contact: Linda Sweeney, `Lsweeney@cadfem.ie`.
- **Visiativ / SolidWorks:** support available; not relevant to us (no CAD in this project).
- An organisers' webinar ran on 7 October, 11:00. If we missed it, ask Kevin Littlewood
  (`kevin.littlewood@dcu.ie`) for the recording — it covered all the event details.

## 4.8 Sea-Scan (Trinity): worth sending, not worth waiting for

**This is optional.** It is a ten-minute email with a possible upside, not a dependency. Nothing
in the build waits on it, and we do not chase a reply.

- **Without any consent** we may say *"designed to complement Sea-Scan"*. That needs nobody's
  permission and is enough for the pitch.
- **If they reply** and agree, we may upgrade to *"designed with input from the Sea-Scan team
  (TCD)"*, which is a genuine differentiator with a jury that funded them. If they do not reply
  before the event, nothing is lost.
- **Never** claim a partnership or endorsement without written consent, use their data or logo,
  or present their numbers as ours.

Their papers, for background: *Sea-Scan: weakly supervised fibre-sensing (DAS) dark-vessel
detection*, arXiv 2606.21326 †; *DAS–AIS association patterns on the Dublin–North Wales link*,
arXiv 2607.02536 †. Addresses for Prof. Marco Ruffini and Dr John Kennedy are on the TCD staff
pages.

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
> Would you be open to a short call this week? We would value your advice, and we would like your permission before mentioning Sea-Scan by name in our pitch. If there is interest, we would be glad to explore a small joint pilot after the event.
>
> Kind regards,
> [Name] · [team] · [phone]

## 4.9 Rhythm

- **A short call every evening.** Everyone shares a screen — showing, not describing. If you are
  stuck, say so on the call, not in a message at 2 a.m.
- **Stub first, replace second.** Build behind the two JSON files with fake data until the real
  piece arrives.
- **Cut, don't stretch.** Anything not working at the freeze is dropped.
- **Label everything** on screen: *real*, *reconstructed*, *simulated*, *fictional*, *assumption*.

## 4.10 The finish line

- [ ] The 7-step demo runs **offline**, end to end.
- [ ] Both numbers on screen: false alarms per day vs the geofence, and *Eagle S* warning time.
- [ ] At least **one real example** of a dark ship or an identity mismatch.
- [ ] The evidence pack opens.
- [ ] The 4-minute pitch rehearsed 5+ times, the backup video, the one-pager.
- [ ] Prior work declared (`pre-hackathon` tag plus `PRIOR_WORK.md`).
- [ ] Sea-Scan mentioned with the right, consent-based wording.

## 4.11 After the hackathon

- **If we win**, EUDIS mentoring follows (about 40 h over about 2 months), then the EU-wide
  final, judged on **progress**: validation with the RTI unit on unclassified historical data; a
  joint pilot with Sea-Scan on the Dublin–Holyhead corridor; satellite-AIS integration; a letter
  of intent from a cable or energy operator; an ESA BIC application.
- **Whatever we place:** ask for DCU incubation, TensorX credits, and test and validation with
  the RTI unit.
