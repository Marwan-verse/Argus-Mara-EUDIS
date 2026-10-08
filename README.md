# ARGUS MARA: our EUDIS Defence Hackathon project

> *"Ireland can crew two ships. Argus Mara gives them a hundred eyes."*

**What it is:** an AI early-warning system for Ireland's undersea internet cables and gas and power lines. It works like this:
- It watches ships using their public AIS signals and satellite radar.
- It spots dangerous behaviour: dragging an anchor, switching the transponder off, faking an identity.
- It then starts a **countdown to the cable at risk** and shows which response can get there in time.
- **A human always decides.**

**Where and when:** the EUDIS Defence Hackathon at DCU:Innovate Hub, Dublin, **15–17 October 2026**. We are in **Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness".

**Team:** the Cyber team, eight of us, captained by Mykhailo.

**Status (7 Oct 2026):** **our place is confirmed** — DCU wrote on 1 Oct, *"Congratulations on
being accepted"*; over 20 teams are taking part. The [Space tools](space/README.md) now run
offline with two published radar contacts; the full demo still needs integration. **Eight days**
remain. The sample JSON and AIS recorder exist, and the plan has been reset from today — see
[DECISIONS.md](DECISIONS.md) D11.

> **The one rule: assemble the whole demo first, then make it good.** Ugly, on invented data,
> but complete. Then replace one invented part per day with a real one. If a replacement fails,
> the working demo is still there.

---

## The demo the judges will see

1. **A map of Ireland:** ships move, cables lie on the seabed, and the shallow areas where an anchor can reach the seabed glow.
2. **A tanker switches off its transponder** and vanishes. The tanker is fictional; the scenario is simulated.
3. **A satellite radar image finds it again.** It measures 228 m but declared 180 m, so Argus Mara flags an **identity mismatch**.
4. **It heads for shallow water over a cable.** Its speed drops from 12 to 9.1 knots and its course wobbles. That is exactly what *Eagle S* did before it cut Baltic cables in December 2024.
5. **An alert appears, with a ticking countdown:** "cable in 1 h 15 min (earliest 1 h 03)".
6. **The response panel:** aircraft ✅ 39 min · patrol ship ❌ 232 min · VHF ❌ out of range · next satellite ❌ 250 min.
7. **The officer approves**, and an evidence pack is generated.

Beats 1–7 are already pinned down as data in [`demo/`](demo/) — run `python3 demo/make_scenario.py`
to see the exact numbers. Those two files are the contract the whole team builds against.

## The plan

No hour-by-hour schedule — we do not yet know what will take how long. **Two hard deadlines
only.**

| Stage | What happens |
|---|---|
| **1. Now** | Each workstream builds its own piece against the sample files. Nobody waits for anybody |
| **2. ⬅ hard deadline: Sun 11 Oct, evening** | **The demo runs end to end.** All seven beats, on invented data. Screen recording made. Until this works, no new work starts |
| **3. Then** | Replace invented parts with real ones, one at a time. Real cables and depth, countdown v2, one real space example, and the two numbers |
| **4. ⬅ hard deadline: Tue 13 Oct evening** | **Feature freeze.** Anything not working is cut. Wed: offline dry runs, final screen capture, `git tag pre-hackathon` |
| **5. 15–17 Oct** | The hackathon. Mentors first, build second. Freeze Fri 17:00. Pitch Sat |

Details in [docs/04-work-plan.md](docs/04-work-plan.md); the Russian version — the one to read
daily — is [docs/plan-ru.md](docs/plan-ru.md).

## Who owns what

| Workstream | Owners | In plain words | This week's job |
|---|---|---|---|
| **Story + integration** | **Mykhailo** (captain) | The pitch and the people | Organisers, demo script, **the AIS recorder on his own machine**; every evening checks the demo still runs |
| **Data** | **Adam Pohořilský** + **Marwan** | Collects everything: cables, seabed depth, traffic | Cable routes and depth; vessel-density grids; the scenario file |
| **Brain** | **Nazar Kyrychenko** + **Myroslav** | Notices suspicious behaviour and runs the countdown | Anchor-drag rule; countdown; response ETAs; the two numbers |
| **Space** | **Nazariy Buryak** | Satellite radar: reviews AIS-unmatched contacts and checks vessel size with uncertainty | Offline tools and two real contacts available; [dataset plan and evidence handoffs](space/README.md#update-for-teammates--8-october-2026) documented; implementation pending |
| **Interface** | **Ihor Maslovskyi** + **Bohdan** | What the judges see | Map, moving vessels, alert card with the live countdown, action panel, evidence page |

**Why pairs.** One person who gets stuck goes quiet for two days; two people talk, and talking
unsticks them. Space has a single owner because it is the one piece nobody else depends on.

**How we stay unblocked:** two JSON files, agreed once — `demo/scenario.json` (*what happened*,
written by Data) and `demo/alerts.json` (*what Argus Mara noticed*, written by Brain). The
interface reads both and plays them. **No backend in v1**, so there is nothing to deploy and
nothing to break on stage. Full contract: [demo/README.md](demo/README.md).

**Data we do not have to collect ourselves:** Global Fishing Watch has
satellite-radar detections over Irish waters including *AIS-unmatched* contacts that need review;
EMODnet has shipping-density grids for Irish waters; the Danish Maritime Authority publishes
free raw AIS, though for Danish waters. There is no free archive of raw *Irish* AIS, so we tune
the detector on the Danish data and show on our own recording that it works on Irish traffic.
Details and links: [plan §4.5](docs/04-work-plan.md).

"How to build it" for every piece is in [docs/05-build-guide.md](docs/05-build-guide.md).

## Open tasks

**Start now**

- [x] ~~Start the AIS recorder.~~ **Done — running since 7 Oct**, on Mykhailo's own Mac.
      It stays on until we leave for the event. [Instructions, if anyone else needs them](recorder/README.md).
- [ ] Confirm it is actually writing: `.venv/bin/python recorder/check.py` about fifteen minutes
      after starting, then once a day. *Owner:* **Mykhailo**
- [ ] Share a copy of `data/ais/` with Brain every couple of days (a zip in the team chat is
      fine — it is git-ignored and must never go to GitHub). *Owner:* **Mykhailo**
- [ ] Get a Global Fishing Watch API token and pull its **radar detections for Irish waters**,
      especially the *AIS-unmatched* contacts for review. **The request/fetch CLI is ready; the account step is
      pending.** The selected public-data path already supplies two historical contacts.
      API reports contain grid counts; per-contact downloads supply scene IDs and lengths.
      [Space instructions](space/README.md). *Owner:* **Nazariy**
- [x] Offline radar/AIS matching, custody candidates and the vessel-length review check:
      [`argus/space.py`](argus/space.py), with tests. *Owner:* **Nazariy**
- [x] Review the mentor-suggested SAR, imagery and maritime datasets; document source priorities,
      access limits and handoffs to Data, Brain and Interface. [Space dataset plan](docs/10-space-dataset-plan.md).
      *Owner:* **Nazariy**
- [ ] Extend Space with a coverage manifest, newer GFW export adapter, overlapping AIS input
      and offline evidence pages. **Planned; not yet implemented.** Keep the two historical
      contacts as the offline fallback. [Current status](space/README.md#workstream-status).
      *Owner:* **Nazariy**, with Data, Brain and Interface handoffs
- [ ] Download cable and pipeline routes (EMODnet, TeleGeography), seabed depth (GEBCO or
      EMODnet), and the EMODnet vessel-density grids. *Owners:* **Ihor, Bohdan**
- [ ] `argus/brain.py`: read `scenario.json` → write `alerts.json`. Slow-down rule plus
      countdown v1 — take `project_to_cable()` from `demo/make_scenario.py`.
      *Owners:* **Nazar K., Myroslav**
- [ ] `ui/index.html`: offline map, cable line, vessel moving through the scenario points.
      *Owners:* **Adam, Marwan**
- [ ] Pitch outline and the demo script as numbered beats. *Owner:* **Mykhailo**

**Then**

- [ ] Mark the cable sections shallower than 250 m — the anchor-reach zone. *Owners:* **Ihor, Bohdan**
- [ ] Countdown v2 with an uncertainty cone (≈50 futures). *Owners:* **Nazar K., Myroslav**
- [ ] The two numbers: false alarms per day vs a geofence, and *Eagle S* warning time.
      *Owners:* **Nazar K., Myroslav, Mykhailo**
- [x] Find **one real** unmatched radar contact: **two published GFW contacts**, with original
      rows, source attribution and checksums. These are review candidates, not proof of AIS
      shutdown. [Examples and limitations](space/README.md#two-verified-real-contacts).
      *Owner:* **Nazariy**
- [ ] `PRIOR_WORK.md`, our record of what we built before the event. *Owner:* **Mykhailo**

**Optional, ten minutes each — send and forget, nothing waits on these**

- [ ] Email the Sea-Scan team at Trinity ([why, and the template](docs/04-work-plan.md#48-sea-scan-trinity-worth-sending-not-worth-waiting-for)).
      Without any reply we may still say *"designed to complement Sea-Scan"*. *Owner:* **Mykhailo**
- [ ] Ask CADFEM for the free Ansys STK licence (satellite passes) — needs an `@setu.ie`
      address, not Gmail. *Owner:* **Mykhailo / Nazariy**
- [ ] If we missed the 7 Oct organisers' webinar, ask Kevin Littlewood for the recording.
      *Owner:* **Mykhailo**

**What we are deliberately NOT building:** a learned ML detector, an LLM brief, drones, new
satellite tasking, a real Sea-Scan integration, a database or logins. If someone proposes one,
the answer is "after the hackathon". ([plan §4.6](docs/04-work-plan.md))

## Rules we follow

- **A human decides every action.** Nothing kinetic, and no weapons.
- **Public data only.** Use fictional ship names in demo scenarios, and label everything *real*, *reconstructed* or *simulated*.
- **Never commit secrets** such as API keys; use environment variables.
- **Don't call Trinity's Sea-Scan our partner** unless their team agrees in writing.
- **Always keep a demo that runs end to end**, even an ugly one. Cut, don't stretch.
- **Every evening at 21:00, a 15-minute call.** Everyone shares a screen — showing, not
  describing. If you are stuck, say so on the call, not in a message at 2 a.m.

## What's in this repo

| Path | What |
|---|---|
| [recorder/](recorder/) | The ship recorder — double-click to start — plus a health check and a map preview |
| [demo/](demo/) | **The contract everyone builds against:** the scenario and alert files, with a generator |
| [space/](space/) | Nazariy's offline radar/AIS tools, real contact examples, and Space handoff instructions |
| [argus/](argus/) | Python analysis, Space importers and shared contract checks; Brain implementation goes here |
| [ui/](ui/) | Interface workstream's static browser entry point and offline assets |
| [DECISIONS.md](DECISIONS.md) | Decisions we've made, and why |
| [docs/01-hackathon-analysis.md](docs/01-hackathon-analysis.md) | The event, the judges, past winners, Irish context |
| [docs/02-ideas.md](docs/02-ideas.md) | The full Argus Mara brief (§1) |
| [docs/03-playbook.md](docs/03-playbook.md) | The 4-minute pitch, hard questions, demo rules |
| [docs/04-work-plan.md](docs/04-work-plan.md) | The detailed plan with dates and checklists |
| [docs/05-build-guide.md](docs/05-build-guide.md) | How to build each part |
| [docs/06-challenge-3-deep-dive.md](docs/06-challenge-3-deep-dive.md) | Everything about our challenge |
| [docs/plan-ru.md](docs/plan-ru.md) | The plan in Russian, in simple words |
| [docs/sources.md](docs/sources.md) | Sources |
| [docs/07-architecture.md](docs/07-architecture.md) | The current code layout, language choices, contract units and workstream ownership |
| [docs/08-research-and-next-ideas.md](docs/08-research-and-next-ideas.md) | Checked primary sources, caveats and suggested next improvements |
| [docs/09-team-skills.md](docs/09-team-skills.md) | How teammates download the repository skills |
| [docs/10-space-dataset-plan.md](docs/10-space-dataset-plan.md) | Space dataset comparison, implementation sequence and handoffs to Data, Brain and Interface |
| [skills/](skills/) | Portable codebase and interface skills for teammates |
| [scripts/check_contracts.py](scripts/check_contracts.py) | Checks the two demo JSON files before integration |
