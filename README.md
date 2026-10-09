# ARGUS MARA: our EUDIS Defence Hackathon project

> *"Ireland can crew two ships. Argus Mara gives them a hundred eyes."*

**What it is:** a rule-based early-warning demonstration for Ireland's undersea internet cables and gas and power lines. It works like this:
- It watches ships using their public AIS signals and satellite radar.
- It flags review cues such as speed changes, reception gaps and uncertain radar associations.
- It then starts a **countdown to the cable at risk** and shows which response can get there in time.
- **A human always decides.**

**Where and when:** the EUDIS Defence Hackathon at DCU:Innovate Hub, Dublin, **15–17 October 2026**. We are in **Challenge 3**, the Department of Defence's "Space-Enabled Maritime Domain Awareness".

**Team:** the Cyber team, eight of us, captained by Mykhailo.

**Status (8 Oct 2026):** **our place is confirmed**. The seven-beat offline interface,
rule-generated alert and fictional Space evidence page run together. The two published
historical radar contacts remain a separate review example; measured evaluation numbers
and external data replacement are pending. See [DECISIONS.md](DECISIONS.md) D29–D30.

**Run the native desktop application:** double-click `RUN-GUI-WINDOWS.bat` on Windows.
It creates an ignored `.venv` and installs the UI packages on first run. Alternatively,
create a virtual environment, run `python -m pip install -r requirements.txt`, then
`python run_gui.py`. The app needs Python 3.10+ with Tkinter (Tcl/Tk) enabled; on
Windows, include **Tcl/Tk and IDLE** in the Python installer. Use
`python run_gui.py --check` to validate the local inputs without opening a window.
CustomTkinter styles the native dashboard and Pillow displays NASA JPEG imagery; the
same two JSON files drive the replay. The application starts no web server.
The map is draggable and zoomable. Use the mouse wheel or scroll vertically with
two fingers on a trackpad over the map to zoom around the pointer; the `+` and `−`
buttons also remain available. **Offline coastline** covers the world without
internet; **NASA Blue Marble · online** requests only visible imagery tiles. Use
**World** to fit the globe and the map layers panel to show NGA World Port Index
points and historical, stylized submarine cable routes. These reference layers are
display context only; they do not feed the alert or countdown. The cable layer is
CC BY-NC-SA 3.0 and must be replaced or licensed for commercial distribution.
The right `+` opens tabs in a resizable side pane; the bottom `+` opens panels in a
resizable lower pane. Drag tabs to reorder or move them between panes, or right-click
a tab to move or close it. The lower-pane menu also includes map tools.

**Browse reference data:** open **Port directory** to search all 3,805 local ports
by name, WPI ID or country code. Filter by country or restrict the list to the
current map view. Select a row for coordinates and provenance; double-click it,
press Enter or choose **Center selected port** to locate it. Click a port marker
to inspect it, or a numbered cluster to zoom in. Port names appear at closer zooms.
**Cable directory** searches 497 historical route records and fits a selected
route, including systems crossing the date line. **Fit exercise** frames the
scenario track and cable. The scale bar and cursor coordinates help orientation.
These additions remain offline and preserve the white desktop interface.

**Optional shared live AIS:** [live/README.md](live/README.md) explains the single
Railway collector, private persistent archive, English browser map and live mode
of the team's native dashboard. Run `python run_live_gui.py --server https://YOUR-SERVER`
to receive the shared observations; `run_gui.py` remains the offline exercise.
Deploy the separate `feat/shared-live-ais` branch with a `/data` volume and put the
AIS key only in Railway Variables. A tested local service is not a confirmed
cloud deployment or proof of a working real feed. See decision D36.

> **The one rule: assemble the whole demo first, then make it good.** Ugly, on invented data,
> but complete. Then replace one invented part per day with a real one. If a replacement fails,
> the working demo is still there.

---

## Browser frontend development

The browser replay, live AIS console, evidence controls and recorder map export
use Svelte 5. Run `npm ci`, `npm run check`, `npm run build` and `npm run test:browser`
from the repository root. Committed bundles keep the offline demo and Python
server runnable without Node. See [the UI guide](ui/README.md) for setup and checks.

## The demo the judges will see

1. **A map of Ireland:** ships move, cables lie on the seabed, and the shallow areas where an anchor can reach the seabed glow.
2. **A fictional tanker enters a simulated AIS reception gap** and disappears from the AIS layer.
3. **A separate simulated radar contact appears.** Its 228 m length estimate and the tanker's 180 m AIS declaration warrant review; association and identity are unconfirmed.
4. **AIS returns and the vessel turns toward an illustrative cable.** Its observed speed reaches 9.1 kn at minute 90; the cause is unknown.
5. **The rule-generated alert appears, with a ticking countdown:** expected cable crossing in 1 h 13 min 31 s; earliest planning estimate 1 h 1 min 15 s.
6. **The response panel:** assumed aircraft and VHF responses arrive in time; the patrol ship and next satellite look do not.
7. **The officer approves**, and an evidence pack is generated.

Beats 1–7 are pinned down in [`demo/`](demo/). Regenerate with
`python3 demo/make_scenario.py`, then `python3 -m argus.brain`, and run
`python3 scripts/check_contracts.py`. The generator does not overwrite Brain's alert.

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
| **Data** | **Ihor Maslovskyi** + **Bohdan** | Collects everything: cables, seabed depth, traffic | Cable routes and depth; vessel-density grids; the scenario file |
| **Brain** | **Nazar Kyrychenko** + **Myroslav** | Notices suspicious behaviour and runs the countdown | Anchor-drag rule; countdown; response ETAs; the two numbers |
| **Space** | **Nazariy Buryak** | Satellite radar: reviews AIS-unmatched contacts and checks vessel size with uncertainty | Offline evidence packs, provenance manifest, AIS handoff and two real contacts implemented; [instructions and remaining dataset access](space/README.md#update-for-teammates--8-october-2026) |
| **Interface** | **Adam Pohořilský** + **Marwan** | What the judges see | Map, moving vessels, alert card with the live countdown, action panel, evidence page |

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
- [x] Extend Space with a coverage manifest, normalized AIS input and offline evidence pages.
      Run `python3 -m argus.evidence` for the two historical contacts; a separate fictional
      pack supports the demo handoff. [Instructions](space/README.md#generate-an-offline-evidence-pack).
      *Owner:* **Nazariy**, with Data, Brain and Interface handoffs
- [ ] Verify the newer GFW per-contact export schema and obtain overlapping SAR/AIS data.
      The verified historical CSV remains the fallback; the newer adapter and a recent real
      combined replay are pending. [Current status](space/README.md#workstream-status).
      *Owner:* **Nazariy**, with Data, Brain and Interface handoffs
- [ ] Download cable and pipeline routes (EMODnet, TeleGeography), seabed depth (GEBCO or
      EMODnet), and the EMODnet vessel-density grids. *Owners:* **Ihor, Bohdan**
- [x] `argus/brain.py`: read `scenario.json` → write `alerts.json` from four review cues;
      countdown v1 and response options are in `argus/countdown.py`.
      *Owners:* **Nazar K., Myroslav**
- [x] `ui/index.html`: offline map, cable line, vessel replay, approval and evidence export.
      *Owners:* **Adam, Marwan**
- [x] Four-minute [demo runbook](docs/demo-runbook.md) and [one-pager](docs/one-pager.md) drafted; live rehearsal and recording still required. *Owner:* **Mykhailo**

**Then**

- [ ] Mark the cable sections shallower than 250 m — the anchor-reach zone. *Owners:* **Ihor, Bohdan**
- [ ] Countdown v2 with an uncertainty cone (≈50 futures). *Owners:* **Nazar K., Myroslav**
- [ ] The two numbers: false alarms per day vs a geofence, and *Eagle S* warning time.
      *Owners:* **Nazar K., Myroslav, Mykhailo**
- [x] Find **one real** unmatched radar contact: **two published GFW contacts**, with original
      rows, source attribution and checksums. These are review candidates, not proof of AIS
      shutdown. [Examples and limitations](space/README.md#two-verified-real-contacts).
      *Owner:* **Nazariy**
- [x] [`PRIOR_WORK.md`](PRIOR_WORK.md) drafted from the pre-event repository; review and create the planned tag on 14 Oct. *Owner:* **Mykhailo**

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
| [docs/demo-runbook.md](docs/demo-runbook.md) | Four-minute click and talk script, offline acceptance and fallback steps |
| [docs/one-pager.md](docs/one-pager.md) | Current demonstrated capability and explicit validation limits |
| [docs/ui-skills-survey.md](docs/ui-skills-survey.md) | UI skills and tools ranked for this static offline console |
| [PRIOR_WORK.md](PRIOR_WORK.md) | Draft declaration of work completed before the event |
| [skills/](skills/) | Portable codebase and interface skills for teammates |
| [scripts/check_contracts.py](scripts/check_contracts.py) | Checks the two demo JSON files before integration |
