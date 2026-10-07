# ARGUS MARA: our EUDIS Defence Hackathon project

> *"Ireland can crew two ships. Argus Mara gives them a hundred eyes."*

**What it is:** an AI early-warning system for Ireland's undersea internet cables and gas and power lines. It works like this:
- It watches ships using their public AIS signals and satellite radar.
- It spots dangerous behaviour: dragging an anchor, switching the transponder off, faking an identity.
- It then starts a **countdown to the cable at risk** and shows which response can get there in time.
- **A human always decides.**

**Where and when:** the EUDIS Defence Hackathon at DCU:Innovate Hub, Dublin, **15–17 October 2026**. We are in **Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness".

**Team:** the Cyber team, eight of us, captained by Mykhailo.

**Status (7 Oct 2026):** nothing is built yet, and **eight days** remain. The plan has been
reset from today — see [DECISIONS.md](DECISIONS.md) D11. Work done before the event is allowed
as long as we declare it.

> **The one rule: a demo that runs end to end by Friday 9 October, 20:00.** Ugly, on invented
> data, but complete. Every day after that we replace one invented part with a real one. If a
> replacement fails, we still have a working demo.

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

| When | Goal | Done when… |
|---|---|---|
| **Wed 7 Oct** (today) | Start | 40-minute call; roles taken; **the AIS recorder is recording**; emails sent; accounts created |
| **Thu 8 Oct** | Four pieces, in parallel | Each workstream's piece runs on the sample files. Screens shared at 21:00 |
| **Fri 9 Oct** | **DEMO v1** | The 7-step story plays end to end at 20:00. Phone video recorded |
| **Sat 10 – Sun 11 Oct** | Make it real | Real cables, real depth, real traffic, countdown v2, one real space example. **DEMO v2** Sun 20:00 |
| **Mon 12 Oct** | The two numbers | False alarms/day and *Eagle S* warning time, both on screen |
| **Tue 13 Oct** | Freeze | **Feature freeze 20:00.** Anything not working is cut. Runs with the Wi-Fi off |
| **Wed 14 Oct** | Rehearse | Two offline dry runs; backup video; pitch said aloud 5×; `git tag pre-hackathon` |
| **Thu 15 – Sat 17 Oct** | The hackathon | Mentors first, then build. Freeze Fri 17:00. Pitch Sat |

The detailed version is in [docs/04-work-plan.md](docs/04-work-plan.md), and the Russian
version — the one to read daily — is in [docs/plan-ru.md](docs/plan-ru.md).

## Who owns what

| Workstream | Owners | In plain words | This week's job |
|---|---|---|---|
| **Story + integration** | **Mykhailo** (captain) | The pitch and the people | Organisers, Sea-Scan, demo script; every evening pulls it together and checks the demo still runs |
| **Data** | **Ihor Maslovskyi** + **Bohdan** | Collects everything: ships, cables, seabed depth | Recorder running 24/7; cable routes and depth; the scenario file |
| **Brain** | **Nazar Kyrychenko** + **Myroslav** | Notices suspicious behaviour and runs the countdown | Anchor-drag rule; countdown; response ETAs; the two numbers |
| **Space** | **Nazariy Buryak** | Satellite radar: finds ships with the transponder off and checks their size | One Sentinel-1 scene; dark-ship detection; identity check |
| **Interface** | **Adam Pohořilský** + **Marwan** | What the judges see | Map, moving vessels, alert card with the live countdown, action panel, evidence page |

**Why pairs.** One person who gets stuck goes quiet for two days; two people talk, and talking
unsticks them. Space has a single owner because it is the one piece nobody else depends on.

**How we stay unblocked:** two JSON files, agreed once — `demo/scenario.json` (*what happened*,
written by Data) and `demo/alerts.json` (*what Argus Mara noticed*, written by Brain). The
interface reads both and plays them. **No backend in v1**, so there is nothing to deploy and
nothing to break on stage. Full contract: [demo/README.md](demo/README.md).

"How to build it" for every piece is in [docs/05-build-guide.md](docs/05-build-guide.md).

## Open tasks

**Today (Wed 7 Oct) — these three block everything else**

- [ ] **Start the AIS recorder** on an always-on machine: [recorder/README.md](recorder/README.md).
      Every hour of delay is an hour of traffic we can never get back. *Owner:* **Ihor**
- [ ] Email the organisers our questions and **confirm our place is accepted**
      ([playbook §3.1](docs/03-playbook.md)). *Owner:* **Mykhailo**
- [ ] Email the Sea-Scan team at Trinity ([template in plan §4.13](docs/04-work-plan.md)).
      *Owner:* **Mykhailo**

**Thursday 8 Oct**

- [ ] Download cable and pipeline routes (EMODnet, TeleGeography) and seabed depth (GEBCO or
      EMODnet). Download only, no processing. *Owners:* **Ihor, Bohdan**
- [ ] `argus/brain.py`: read `scenario.json` → write `alerts.json`. Slow-down rule + countdown v1
      (take `project_to_cable()` from `demo/make_scenario.py`). *Owners:* **Nazar K., Myroslav**
- [ ] `ui/index.html`: offline map, cable line, vessel moving through the scenario points.
      *Owners:* **Adam, Marwan**
- [ ] Copernicus account; download and open **one** Sentinel-1 scene over the Irish Sea.
      *Owner:* **Nazariy**
- [ ] Pitch outline and the demo script as numbered beats. *Owner:* **Mykhailo**

**Later in the week**

- [ ] Mark the cable sections shallower than 250 m — the anchor-reach zone. *Owners:* **Ihor, Bohdan**
- [ ] Countdown v2 with an uncertainty cone (≈50 futures). *Owners:* **Nazar K., Myroslav**
- [ ] Find **one real** dark ship or length mismatch in the Sentinel-1 scene. *Owner:* **Nazariy**
- [ ] Collect public facts on *Eagle S* (speed, course, timeline) for the warning-time number.
      *Owner:* **Mykhailo**
- [ ] Find one maritime expert for a 20-minute chat. *Owner:* **Mykhailo**
- [ ] Create `PRIOR_WORK.md`, our record of what we built before the event. *Owner:* **Mykhailo**

**What we are deliberately NOT building:** a learned ML detector, an LLM brief, drones, new
satellite tasking, a real Sea-Scan integration, a database or logins. If someone proposes one,
the answer is "after the hackathon". ([plan §4.12](docs/04-work-plan.md))

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
| [recorder/](recorder/) | The ship recorder (runs 24/7), plus a health check and a map preview |
| [demo/](demo/) | **The contract everyone builds against:** the scenario and alert files, with a generator |
| [DECISIONS.md](DECISIONS.md) | Decisions we've made, and why |
| [docs/01-hackathon-analysis.md](docs/01-hackathon-analysis.md) | The event, the judges, past winners, Irish context |
| [docs/02-ideas.md](docs/02-ideas.md) | The full Argus Mara brief (§1) |
| [docs/03-playbook.md](docs/03-playbook.md) | The 4-minute pitch, hard questions, demo rules |
| [docs/04-work-plan.md](docs/04-work-plan.md) | The detailed plan with dates and checklists |
| [docs/05-build-guide.md](docs/05-build-guide.md) | How to build each part |
| [docs/06-challenge-3-deep-dive.md](docs/06-challenge-3-deep-dive.md) | Everything about our challenge |
| [docs/plan-ru.md](docs/plan-ru.md) | The plan in Russian, in simple words |
| [docs/sources.md](docs/sources.md) | Sources |
