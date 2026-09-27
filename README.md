# ARGUS MARA: our EUDIS Defence Hackathon project

> *"Ireland can crew two ships. Argus Mara gives them a hundred eyes."*

**What it is:** an AI early-warning system for Ireland's undersea internet cables and gas and power lines. It works like this:
- It watches ships using their public AIS signals and satellite radar.
- It spots dangerous behaviour: dragging an anchor, switching the transponder off, faking an identity.
- It then starts a **countdown to the cable at risk** and shows which response can get there in time.
- **A human always decides.**

**Where and when:** the EUDIS Defence Hackathon at DCU:Innovate Hub, Dublin, **15–17 October 2026**. We are in **Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness".

**Team:** the Cyber team, captained by Mykhailo.

**Status:** we have applied and are waiting for the organisers to confirm our place. We are building now: work done before the event is allowed as long as we declare it.

---

## The demo the judges will see

1. **A map of Ireland:** ships move live, cables lie on the seabed, and the shallow areas where an anchor can reach the seabed glow.
2. **A tanker switches off its transponder.** The tanker is fictional; this is a simulated scenario.
3. **A satellite radar image finds it again.** Its size doesn't match what it claimed, so Argus Mara flags an **identity mismatch**.
4. **It heads for shallow water over a cable.** Its speed drops from 12 to 9 knots and its course wobbles. That is exactly what *Eagle S* did before it cut Baltic cables in December 2024.
5. **An alert appears:** "cable in 1 h 20 min", with the responses that arrive in time (aircraft ✅, ship ❌…).
6. **The officer approves**, and an evidence pack is generated.

## The plan

| When | Goal | Done when… |
|---|---|---|
| **Now (27–28 Sep)** | Get started | Team call held; roles taken; **ship recorder running 24/7**; accounts created |
| **Week 1 (28 Sep – 4 Oct)** | Skeleton | Ships and cables on the map; first simple alert with a countdown; first satellite image processed. *Check: Sun 4 Oct* |
| **Week 2 (5 – 12 Oct)** | The countdown and space | The whole demo story plays end to end; identity check; evidence pack; our two numbers. *Check: Mon 12 Oct; anything not working is cut* |
| **13 – 14 Oct** | Rehearse | Two dry runs with no internet; backup video; 4-minute pitch; `git tag pre-hackathon` |
| **15 – 17 Oct** | The hackathon | Thu: talk to mentors first. Fri: polish, feature freeze at 17:00. Sat: pitch. |

The detailed version is in [docs/04-work-plan.md](docs/04-work-plan.md), and the Russian version is in [docs/plan-ru.md](docs/plan-ru.md).

## Workstreams: pick one

| Workstream | In plain words | First tasks | Owner |
|---|---|---|---|
| **Data** | Collects everything: ships, cables, seabed depth, sanctions lists | Run the recorder; download cables and depth; load sanctions lists | *free* |
| **Brain** | Notices suspicious behaviour and runs the countdown | Track builder; simple anchor-drag rule; countdown v1 | *free* |
| **Space** | Satellite radar: finds ships with their transponder off and checks their size | Copernicus account; detect ships in one Sentinel-1 image; match them with AIS | *free* |
| **Interface** | What the judges see: map, alert card, buttons | Map with ships and cables; alert card with a ticking countdown | *free* |
| **Story** | Pitch, organisers, experts, partners | Emails to the organisers and to Sea-Scan; talk to a maritime expert | Mykhailo |

"How to build it" for every piece is in [docs/05-build-guide.md](docs/05-build-guide.md).

## Open tasks (this week)

- [ ] **Start the ship recorder** on an always-on machine: [recorder/README.md](recorder/README.md). *Owner:* ___
- [ ] Download cable and pipeline routes (EMODnet Human Activities, TeleGeography). *Owner:* ___
- [ ] Download seabed depth (EMODnet Bathymetry or GEBCO) and mark the cable sections shallower than 250 m. *Owner:* ___
- [ ] Write the data contracts (build guide §2). *Owner:* ___
- [ ] Build the map skeleton: coastline, cables and ships (MapLibre + deck.gl). *Owner:* ___
- [ ] Create a Copernicus account and open one Sentinel-1 radar image over Irish waters. *Owner:* ___
- [ ] Get a Global Fishing Watch API token and pull radar vessel detections for Irish waters. *Owner:* ___
- [ ] Collect public facts on *Eagle S*, *Yi Peng 3* and *Newnew Polar Bear* (speed, course, timeline). *Owner:* ___
- [ ] Email the organisers our questions ([playbook §3.1](docs/03-playbook.md)). *Owner:* Mykhailo
- [ ] Email the Sea-Scan team at Trinity ([template in plan §4.8](docs/04-work-plan.md)). *Owner:* Mykhailo
- [ ] Find one maritime expert for a 20-minute chat. *Owner:* Mykhailo
- [ ] Create `PRIOR_WORK.md`, our record of what we built before the event. *Owner:* Mykhailo

## Rules we follow

- **A human decides every action.** Nothing kinetic, and no weapons.
- **Public data only.** Use fictional ship names in demo scenarios, and label everything *real*, *reconstructed* or *simulated*.
- **Never commit secrets** such as API keys; use environment variables.
- **Don't call Trinity's Sea-Scan our partner** unless their team agrees in writing.
- **Always keep a demo that runs end to end**, even an ugly one. Cut, don't stretch.

## What's in this repo

| Path | What |
|---|---|
| [recorder/](recorder/) | The ship recorder (runs 24/7), plus a health check and a map preview |
| [DECISIONS.md](DECISIONS.md) | Decisions we've made, and why |
| [docs/01-hackathon-analysis.md](docs/01-hackathon-analysis.md) | The event, the judges, past winners, Irish context |
| [docs/02-ideas.md](docs/02-ideas.md) | The full Argus Mara brief (§1) |
| [docs/03-playbook.md](docs/03-playbook.md) | The 4-minute pitch, hard questions, demo rules |
| [docs/04-work-plan.md](docs/04-work-plan.md) | The detailed plan with dates and checklists |
| [docs/05-build-guide.md](docs/05-build-guide.md) | How to build each part |
| [docs/06-challenge-3-deep-dive.md](docs/06-challenge-3-deep-dive.md) | Everything about our challenge |
| [docs/plan-ru.md](docs/plan-ru.md) | The plan in Russian, in simple words |
| [docs/sources.md](docs/sources.md) | Sources |
