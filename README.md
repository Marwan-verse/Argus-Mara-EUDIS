# ARGUS MARA: our EUDIS Defence Hackathon project

**Private SOC collaboration:** the native app supports authenticated two-device
sessions for 2–16 participants, encrypted chat/contact exchange and sharing of its existing map Ping.
Start `RUN-SOC-WINDOWS.bat` or `sh RUN-SOC-MAC-LINUX.command` to require login.
See [SOC deployment, groups and encryption](soc/README.md). The regular offline
demo remains available without private credentials or a server. `python run_gui.py`
shows sign-in with **Continue offline** (one window, no Docker) and **Start local
server + two sign-in windows**. See [automatic local startup](soc/LOCAL-DEMO.md).

For two computers using a VS Code/GitHub forwarded link, start
`HOST-SOC-FORWARDED-WINDOWS.bat` on the account-owning machine and follow
[the forwarded-port guide](soc/FORWARDED-PORT.md). Both native clients sign in
to the same forwarded HTTPS URL with their existing SOC accounts.

**Satellite analysis:** the native radar button opens public Sentinel catalogue
search, small georeferenced optical/SAR crops, acquisition-time archived AIS and
manual TensorX vision review. **Coast Watch → Start scan** enables rolling new-image
screening around Ireland’s ~40 km coastal belt and continuous private AIS capture.
Click an amber lead for its source pixels, image-time AIS candidates and latest
received positions. AI contacts are unreviewed assumptions, with cached
results and a conservative $20 pilot ceiling. Run `INSTALL-SATELLITE-WINDOWS.bat`
once for optional image readers. **One click:** `SATELLITE-WATCH-MAC.command` or
`SATELLITE-WATCH-WINDOWS.bat` installs the readers, asks once for the TensorX and team
database keys and opens the app with Coast Watch running on images from the last 36 h
(D83). See [setup and open-source accuracy plan](docs/16-satellite-ai.md).

**Team database (optional):** the Supabase project `argus-mara` copies the shared
Railway AIS feed every 30 seconds by itself, so Coast Watch can compare any image
with AIS at its acquisition time even when no laptop was recording, both ways:
image contacts without AIS, and large ships whose AIS position shows nothing on the
image. Link a computer with `python scripts/configure_supabase.py`. See
[the database guide](supabase/README.md) and D74.

**Radar contacts (optional, D84):** Global Fishing Watch publishes Sentinel-1 radar
vessel detections, and radar sees through cloud. Connect a free non-commercial token
once with `python scripts/configure_gfw.py`, then press **Coast Watch → Fetch radar**
(or run `python -m argus.gfw_sar fetch`). Each radar cell is compared with the team AIS
at the radar time. *Radar contact without AIS* leads are violet on the map and listed in
Incidents. Detections arrive 4–5 days late. Powered by Global Fishing Watch. See
[how it works and what was checked](docs/19-gfw-radar.md).

**Magnetics (optional, D91):** the magnet button on the left rail opens two real uses of
magnetics; neither watches the sea, because a ship's field fades as 1/r³ (a seabed sensor
sees a 200 m ship only within about 0.5–1 km). *Live magnetic data*, off by default, polls
NOAA SWPC Kp and the Valentia observatory and shows a storm tier in the header: context
for electrical cable alarms that never changes an alert. *Plan search* turns the exercise
vessel's or the selected alert's track (slowdown → cable crossing → speed recovery) into a
magnetometer search corridor with lines, line-km and hours per platform, ranked search
points and a GeoJSON export to `data/magnetics/`; every number is a labelled assumption.
`python -m argus.geomag` prints the live status; `python -m argus.survey_plan` the worked example.

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

**Irish vessel images for the demonstration:** [Nazar's offline image pack](demo/imagery/README.md)
contains six internet-cable risk demo cards, ten labelled vessel close-ups from
Ireland and the North Sea, two Irish overviews and contact sheets. The imagery is
real; names/codes are fictional and cable/behavior overlays are simulated.
Sources, dates and reuse terms are included with the images.

**Run the native desktop application:** double-click `RUN-GUI-WINDOWS.bat` on Windows.
It creates an ignored `.venv` and installs the UI packages on first run. In a Git clone,
`UPDATE-AND-RUN-WINDOWS.bat` (Windows) or `UPDATE-AND-RUN-MAC.command` (macOS) first pulls
the latest commits of the checked-out branch, then starts the app. Alternatively,
create a virtual environment, run `python -m pip install -r requirements.txt`, then
`python run_gui.py`. The app needs Python 3.10+ with Tkinter (Tcl/Tk) enabled; on
Windows, include **Tcl/Tk and IDLE** in the Python installer. Use
`python run_gui.py --check` to validate the local inputs without opening a window.

The app opens in the **tactical chart** look: a detailed dark chart built from EMODnet
Bathymetry relief (seabed and land), a satellite HD layer (Esri World Imagery, street level),
a lat/lon margin scale, cursor position with MGRS, a nautical-mile scale bar and marking
banners. Both maps are online and cached on the device; run
`python scripts/prefetch_map_tiles.py` once before a demo to store Irish waters (about
3,200 tiles, about 100 MB) for offline use. The **original look** stays available:
`UPDATE-AND-RUN-OLD-MAC.command`, `UPDATE-AND-RUN-OLD-WINDOWS.bat`,
`RUN-GUI-OLD-WINDOWS.bat`, or `python run_gui.py --old`.
CustomTkinter styles the native dashboard and Pillow displays NASA JPEG imagery; the
same two JSON files drive the replay. Choose **Continue offline** or use
`python run_gui.py --offline` for a single session without Docker. The local
two-window option starts the separate SOC Docker stack when selected.
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
These additions remain offline. The desktop now uses the dark console theme
described in the integrated AIS section below.

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
      pending.** The live client that compares them with team AIS is `argus/gfw_sar.py` (D84).
      The selected public-data path already supplies two historical contacts.
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
| [docs/12-argus-mara-alert-levels.md](docs/12-argus-mara-alert-levels.md) | How alert levels are scored and how the docked alert panel works |
| [docs/demo-runbook.md](docs/demo-runbook.md) | Four-minute click and talk script, offline acceptance and fallback steps |
| [docs/one-pager.md](docs/one-pager.md) | Current demonstrated capability and explicit validation limits |
| [docs/ui-skills-survey.md](docs/ui-skills-survey.md) | UI skills and tools ranked for this static offline console |
| [PRIOR_WORK.md](PRIOR_WORK.md) | Draft declaration of work completed before the event |
| [skills/](skills/) | Portable codebase and interface skills for teammates |
| [scripts/check_contracts.py](scripts/check_contracts.py) | Checks the two demo JSON files before integration |

## Integrated desktop AIS and SAR next step (12 October)

Launch `RUN-GUI-WINDOWS.bat`. The native layout now follows the Osiris reference:
a full-window chart, compact gold identity header, UTC/feed readouts, narrow icon
rails, bottom map-mode controls and floating panels. The old sidebar, summary
cards and permanent assessment column are removed from the main application.
F11 toggles fullscreen.

The application automatically connects to the team's shared service at
`https://shared-live-ais-production.up.railway.app`. It starts with the Irish
coastal region in view and draws every received position, independent of the
90-row directory page. Green ships have fresh fixes, muted ships are stale and
gold identifies the selected boat. Shapes follow received AIS course when
available; positions are never predicted. Provider reception is incomplete;
these are all received contacts, not a claim to observe every ship at sea.

Click any ship to open its name, MMSI, received UTC and evidence label. The
triangle icon opens the directory. Search any contact by name or MMSI, use
**Center selected** or **Fit AIS**, and use **Show more** to extend the directory.
The latest validated snapshot is cached in ignored
`data/desktop/ais_latest.json` for immediate display and offline use, with its
actual timestamps. Cached observations are never presented as a live connection.
An alternative service can be entered in the directory or supplied through
`ARGUS_LIVE_SERVER`; switching services clears the previous service's contacts.
Disconnect clears displayed contacts and stops polling.

Selecting a ship also draws its **recorded path** in gold, with a marker at the
first retained fix. Other ships' paths stay hidden. **Clear ship selection**
removes the path; **Show selected ship path** toggles it and **Fit recorded path**
frames the received fixes. Local history survives app restarts in the same
ignored cache, with limits of 24 hours, 720 fixes per ship and 100,000 fixes in
total. Older contacts can be evicted to stay within the limit. Long gaps (over
15 minutes), source-stream changes and provenance changes break the line.
The starting fix describes where local recording began; a departure port is
unknown and voyages before recording cannot be recovered from the public feed.

**Declared destination** shows the vessel's unverified AIS Message 5 text and
its separate received UTC, following the
[USCG Message 5 definition](https://www.navcen.uscg.gov/ais-class-a-static-voyage-message-5).
No destination line or future route is invented. Until a declaration is received
(or when the service has not yet deployed the optional field), it reads
**Not reported**. Destination updates do not reset the age of a position fix.

The **EXERCISE** map control opens the fictional replay and its explicit operator
review. Exercise overlays and playback controls are hidden in the initial Irish
AIS view. Hiding the exercise returns to Ireland. Live AIS never changes the
fictional countdown or creates a live threat score or operational response.

The diamond icon opens the [SAR next-step plan](docs/08-sar-next-step.md). Raw
SAR detection remains planned work. Local display geometry and the fictional
contracts stay usable without a live connection.

### Irish ports and left alerts panel

The **Alerts** panel is docked between the left icon rail and the map. It lists
labelled simulated contacts and the fictional exercise alert, sorted Critical to
Low, and opens a review window to acknowledge, escalate or reject each one. See
[Argus Mara alert levels](docs/12-argus-mara-alert-levels.md) for the scoring rules
and the panel. Live AIS is not scored; no live threat assessment or operational
action is created.

Irish ports are displayed by default. The offline layer adds all 142 commercial,
fishing and ferry records from the Marine Irish Digital Atlas layers served by
[Ireland's Marine Atlas](https://atlas.marine.ie/arcgis/rest/services/TransportNetworks/MapServer),
alongside 21 NGA Irish reference records. Multiple categories can refer to the same
harbour; this is not a count of unique ports or an exhaustive list of every pier
or marina. These are historical catalogue locations, not surveyed navigation
fixes. The source records specify **CC BY 4.0**; attribution and source hashes
are stored in `ui/assets/irish_ports.json`.

Click a port to inspect its source/category and center it, or open the anchor
icon for the directory (initially filtered to **Irish coast**). **Irish coast ports
only** in Map layers can be turned off for the global NGA layer.

Rebuild the derived catalogue with `python scripts/prepare_irish_ports.py --fetch`.
Downloaded source responses stay in ignored `data/maps/`; the compact attributed
reference layer is bundled for offline use.

### Desktop navigation and review controls

- **Ship filters:** the AIS panel's **Filters** tab controls fresh fixes, reported
  vessel type and minimum/maximum speed in knots. Filters affect both the directory
  and map. Missing speeds do not match an active speed range; invalid limits show
  an explanation. Reset restores all contacts. AIS type codes are displayed using
  broad [USCG AIS type labels](https://www.navcen.uscg.gov/ais-class-a-static-voyage-message-5).
- **Selected ship:** the details tab shows speed, course, type, source, received
  UTC and fix age. **Follow selected ship** recentres on received fixes only.
  Panning, opening an exercise, fitting a view or choosing a search result stops
  following. No movement is predicted.
- **Alert review:** every alert card has **New**, **Reviewed**, **Acknowledged**,
  **Escalated** and **Rejected** states with summary counts. Opening a card
  reviews it, and review must precede acknowledgement. These states last for the
  session and never approve an operational response; the existing explicit
  simulated response approval remains separate.
- **Legend:** the bottom **Ships**, **Stale**, **Ports** and **Cables** switches
  directly control the map. **SAR demo** controls the simulated radar layer while
  the fictional exercise is open. Stale toggles the same freshness filter as the
  AIS panel.
- **Saved views:** the left round view icon opens Irish coast, Irish Sea, Western
  approaches, Dublin Bay and Cork Harbour presets. Save the current centre and
  zoom with a name; open or delete a custom saved view from the same panel.
- **Panel layout:** drag the right edge of Alerts or the left edge of the detail
  panel to resize. The Alerts **×** and **!** icon hide/show the left panel; the
  detail **×** hides the right panel. Panel widths and alert visibility are saved.
- **Global search:** click **Search Ctrl+K** or press **Ctrl+K**. Search vessel
  names, MMSIs, vessel types, ports and saved views, or enter latitude/longitude
  such as `53.35, -6.25` or `53.35N 6.25W`. Use Up/Down and Enter to select;
  Escape closes search. Searching includes all contacts regardless of map filters;
  selecting a ship restores its visibility and clears ship filters.

View, layout and filter preferences are saved only in ignored
`data/desktop/ui_preferences.json`. Contact observations retain their source UTC
and provenance; the shared scenario and alert JSON files are unchanged.

### Desktop visual polish

The desktop uses Segoe UI for controls and prose, with monospace UTC, counts and
countdowns. Original locally rendered outline icons share an 18 px size and
consistent stroke. Gold marks controls and selected boats, cyan marks reference selections, alert
levels use red, orange, amber and blue, and quieter neutral colours describe
ordinary layers.

The exercise alert card keeps its countdown. **Details** expands the trigger
explanation and review-state selector; **Open replay** opens the same fictional
exercise. Observation age and operator approval remain
explicit. The header separates connection status, received/fresh counts and UTC.

Stale ship fixes use smaller muted dots; selected boats retain a gold ring.
Ordinary port markers have no bright borders, and historical cable lines are
thinner and muted. Hover over an icon for its tooltip. Buttons and search fields
have visible keyboard focus. Panel and search opening transitions last about
130 ms; **Reduce panel motion** in Map layers disables them and is saved locally.

### Click-to-open vessel card

Click a received boat marker to open a white, draggable vessel card over the
chart, following the supplied reference layout. Its header shows the name/type;
Irish ship-station MMSIs (MID 250) get an Irish flag, following the
[ITU MID table](https://www.itu.int/gladapp/Allocation/MIDs). Other identities
retain an AIS badge. The selected marker has a bold outlined name and a gold
past track. Closing the card clears the selection and path.

The card shows the first locally recorded fix, declared destination, received
age/UTC, speed/course and reported navigation status using
[USCG AIS status codes](https://www.navcen.uscg.gov/ais-class-a-reports).
The voyage arrow is a schematic summary; it does not represent voyage progress
or predict a route. Departure port remains unknown. ETA and draught read as
unavailable because the shared feed does not currently supply them.

**Past track** toggles the selected history. **Vessel details** opens the full
AIS details tab. **Measure route** activates the existing two-point map distance
tool. **Add to fleet** saves the MMSI in the ignored local AIS cache; click again
to remove it. These controls do not dispatch an operational action.

For a vessel photograph, place an operator-supplied JPEG or PNG at
`data/desktop/vessel_photos/<nine-digit-MMSI>.jpg` (or `.jpeg` / `.png`). Images
stay local and ignored. Without a matching photograph, the card displays a
labelled placeholder. The reference screenshot's photograph is not reused for
other vessels. The card scrolls and stays within the viewport after dragging,
resizing or Windows display scaling.

### Map ping

The target-shaped **Ping** button sits directly below the ruler on the right
toolbar. Click it, then click a map position to show a labelled cyan ping for
15 seconds. Panning and zooming keep it anchored to that coordinate. Click Ping
again while armed to cancel, or press **Escape** on the map to clear it. A new
ping replaces the previous one. **Reduce panel motion** also stops the ping's
pulsing rings. Pings are local operator annotations; they are not sent to a
ship or another team member and do not create an alert.

### Docked alert board (simulated)

The left **Alerts** panel is the main working list. It shows 45 labelled items:
the fictional exercise alert, 15 hand-written scenarios, 4 coastal-site contacts
(stopped away from ports, or loitering by a naval base, landfall or wind farm) and 25
frequent minor alerts, sorted Critical → High → Medium → Low. Click a level counter to filter, or change the
sort to time to the asset or newest. Click a row or a map marker to open its review
window: the score scale, the indicators behind the level, the time to the asset, the
recommended action and the log. **Acknowledge**, **Escalate** (duty officer, line
operator, Irish Coast Guard (MRCC) or Naval Service operations) and **Reject** (with a
reason) are recorded for the session only; nothing is sent. Countdowns run live, so
GREY HERON rises from High to Critical after about 3.5 minutes; ↻ restarts the
simulation. Map markers use the level colours, carry **SIM** labels and sit under a
**SIMULATED** corner badge; **Sim alerts** in the legend hides them. On a trackpad,
two fingers scroll the queue, and on macOS a pinch zooms the map. Pinching needs the
optional PyObjC package in `requirements-mac.txt`; `UPDATE-AND-RUN-MAC.command`
installs it on its next run. Full rules:
[Argus Mara alert levels](docs/12-argus-mara-alert-levels.md).
