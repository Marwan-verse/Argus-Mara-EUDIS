# 6. Challenge 3 deep dive: "Space-Enabled Maritime Domain Awareness"

*Research snapshot: 24 Sep 2026. † = not re-verified. Links are in [sources.md](sources.md).*

## 6.1 The challenge text, phrase by phrase

> Develop an **autonomous or AI-enabled capability** that uses **data from space and/or remote sensors** to **detect, monitor, interpret or predict** activity **in real time** within the **maritime environment**.

| Phrase | What it means for us | How Argus Mara answers |
|---|---|---|
| "autonomous **or** AI-enabled" | AI is enough, and autonomy is a bonus that fits the event theme | It monitors, keeps custody and predicts 24/7 with no human. It can automatically cue sensors (a satellite look, a fibre segment, a drone) within pre-approved rules. A human approves actions. |
| "data from **space** and/or **remote sensors**" | The space part must be *visible*, not decoration | Sentinel-1 radar re-acquires dark ships; the identity check compares radar length with AIS length; the next satellite look is planned. Remote sensors are AIS and fibre sensing (Sea-Scan). |
| "**detect, monitor, interpret or predict**" | Most entries will do one of these | We do all four: **detect** (dark ships, behaviours), **monitor** (custody), **interpret** ("why" chips, identity), **predict** (the countdown). |
| "in **real time**" | Be honest about latency | AIS streams in real time, and the countdown updates on every message. Radar is periodic (hours), so we say so and plan around it. |
| "within the **maritime environment**" | Surface *and* seabed | Surface through AIS and radar; the seabed through anchor-reach physics and fibre cues. |

## 6.2 Coverage of the nine focus areas

| Focus area (from the challenge) | Argus Mara feature | Demo moment | Strength |
|---|---|---|---|
| Protection of critical undersea infrastructure | Segment-level risk, anchor-reach physics, the countdown | The glowing shelf and the countdown | ●●● |
| Detection of suspicious maritime behaviour | Anchor-drag (*Eagle S* signature), loitering, survey patterns, going dark | The speed drop from 12 to 9 kn | ●●● |
| Autonomous surveillance of large ocean areas | 24/7 monitoring, custody through gaps, automatic sensor cueing | Custody regained after going dark | ●●○ |
| Space-enabled ISR | Sentinel-1 re-acquisition, satellite-look planning | "Next look 18:40" | ●●● |
| AI-assisted interpretation of satellite imagery | Ship detection, length estimate, identity check | "Radar 245 m vs AIS 110 m" | ●●○ |
| Maritime anomaly detection | Learned behaviour score, measured false alarms against a baseline | The false-alarms-per-day number | ●●● |
| Predictive risk modelling | The countdown's uncertainty cone; the threat forecast (stretch) | "1 h 20 (earliest 58 min)" | ●●● |
| Multi-domain data fusion | AIS + radar + seabed depth + infrastructure + sanctions + weather + fibre | "Confirmed by fibre" | ●●● |
| Decision support for commanders and operators | Action panel ✅/❌ against the countdown; evidence pack; grounded brief | Approve → evidence pack | ●●● |

## 6.3 What the Department of Defence is really asking

- **Its own strategy.** The **National Maritime Security Strategy 2026–2030** (published Feb 2026) defines maritime domain awareness as understanding activity on, above and below the sea.
  - It proposes a **national maritime security centre** that joins civilian and military sources into one picture, for **faster decision-making**. The Naval Service operations centre is expected to evolve into that wider maritime operations centre, whole-of-government (defence, justice, transport, energy, cyber, foreign affairs).
  - **Space-based monitoring** is named as an area to develop, including cooperation with other countries.
  - **Implication:** pitch Argus Mara as *the decision layer that centre will need*: a shared picture for several agencies, with a clock on it.
- **Its Presidency agenda.** EU defence ministers met in **Wicklow on 31 Aug–1 Sep 2026** under Ireland's Presidency. The agenda included **the role of outer space in security and defence** and **maritime security**, including the growing threats to cables and pipelines from drones, mines and sabotage. Challenge 3 sits exactly where those two items meet.
- **Its real constraints:**
  - 8 ships, but crews for about 2 at sea.
  - No military primary radar until 2027–28.
  - Boarding powers are still being legislated.
  - **Implication:** the scarce resource is *attention and assets*, not data. Help them spend both well.
- **Its sensitivities.** Ireland supports meaningful human control over autonomy †. Keep every action human-approved, non-kinetic and auditable.

## 6.4 Timeline: why this is urgent now

| When | Event |
|---|---|
| Oct 2023 | *Newnew Polar Bear* damages the Balticconnector gas pipeline and cables with its anchor † |
| Nov 2024 | The Russian spy ship *Yantar* loiters near cables and a gas pipeline off Ireland, flying drones |
| Nov 2024 | *Yi Peng 3* cable cuts in the Baltic † |
| 25 Dec 2024 | ***Eagle S*** cuts Estlink 2 and telecom cables. Speed fell **12 → 9 kn** just before the first break; the drag line was **about 90 km (≈50 nautical miles)** |
| Feb 2025 | EU Action Plan on Cable Security † |
| Aug 2025 | The sanctioned tanker ***Blue*** (falsely flagged; **4 identities and 6 flags since 2020**) switches off AIS before entering Ireland's EEZ |
| 1 Dec 2025 | Drones circle LÉ William Butler Yeats off Dublin during President Zelensky's visit |
| Jan 2026 | A tanker pursued by the US heads for Irish waters and is monitored off the coast |
| Feb 2026 | **Sea-Scan wins** the Defence Innovation Challenge; the **National Maritime Security Strategy** is published |
| Mar 2026 | The boarding-powers bill is announced. From late March, **shadow-fleet tankers reroute west of Ireland** to avoid UK waters. |
| Apr 2026 | A convoy of 5 sanctioned tankers is monitored off the west coast |
| May 2026 | The Irish Times reports the Defence Forces are using AI to cover shortfalls in resources and personnel |
| Jun–Jul 2026 | Sea-Scan papers: weakly supervised fibre-sensing (DAS) detection (accepted at ECOC 2026), and DAS–AIS association on the Dublin–North Wales link |
| 31 Aug–1 Sep 2026 | EU defence ministers meet in Wicklow (space plus maritime security) |
| **15–17 Oct 2026** | **The hackathon** |
| Nov 2026 | CCW Review Conference on autonomous weapons † |

## 6.5 The space layer: what's real in 2026

- **Sentinel-1 radar:**
  - 1C (Dec 2024) and **1D (launched 4 Nov 2025)** fly 180° apart on a **6-day repeat cycle**. At Irish latitudes, overlapping passes mean more frequent looks †.
  - Radar sees **through cloud and at night**, which is essential over Ireland.
  - **1C and 1D also carry AIS receivers**, useful for matching radar targets to AIS if that data is available to you †.
- **Sentinel-2 optical:** useful when it's clear, which is rare over Ireland. Don't rely on it.
- **Commercial SAR** (ICEYE and others) can be tasked for faster revisit. The latency is hours †.
- **EMSA's Copernicus Maritime Surveillance service** already gives member-state authorities satellite products for maritime security, including vessel detection with Sentinel-1 as the main radar source (the CleanSeaNet service).
  - **Deployment story:** in real use, Argus Mara would ingest the EMSA products Irish authorities can already access.
- **On-board AI in orbit:** Ubotica's CogniSAT-6 has detected every vessel in a 20 × 40 km zone within about 90 seconds, on the satellite itself. It has also told apart AIS-broadcasting ships from dark ones in a single pass.
  - **Roadmap:** on-orbit alerts cut space latency from hours to minutes. Ubotica is an event sponsor.
- **Honest limits:**
  - Radar gives a *snapshot*, not a track.
  - Length estimates are ±20–30 m.
  - Small boats are hard to see.
  - Revisit is hours to days.
  - That is why the **countdown runs on AIS**, and space provides **custody and identity checks**.

## 6.6 The in-situ layer: Sea-Scan (TCD)

- **What it is.** Existing telecom fibre becomes a continuous sensor: distributed acoustic sensing plus state-of-polarisation sensing, with meter-scale resolution over hundreds of kilometres. It detects vessel noise, anchor drops, trawling and deliberate interference.
- **Results from their paper:**
  - **97.8% detection at a 1.98% false-trigger rate.**
  - Trained with *weak supervision from imperfect AIS labels*.
  - It found dark-vessel events in unlabelled data.
  - Accepted at ECOC 2026.
- **The Dublin–North Wales study.** On Emerald Bridge Fibres (about 120 km, Clonshaugh ↔ Holyhead, co-owned by ESB and Zayo), fibre signals were compared with AIS. The patterns ranged from clear matches to offset, ambiguous, **AIS-incomplete**, **AIS-silent-candidate**, and non-vessel confounders.
  - Their conclusion: interpretation "is complicated by imperfect AIS reporting".
- **Where Argus Mara helps:**
  - cleaner AIS tracks and reconstructed gaps, which means better labels;
  - radar confirmation of AIS-silent candidates;
  - naming the vessel behind a fibre event;
  - a countdown that tells the fibre system *where and when* to look.
- **Where Sea-Scan helps us:** it hears what AIS and space can't, at the cable itself.
- **Recognition:**
  - Sea-Scan won the Innovation Award at the 2026 Analytics & AI Awards.
  - It was a finalist at the 2026 Ireland eGovernment Awards.
  - **The jury will know this project.** Joining it up is our strongest move.

## 6.7 Competitive landscape

| Category | Players | What they do | Our difference |
|---|---|---|---|
| Commercial AIS "cable watch" | NKT, Sentinel Proactive, UltramapGlobal (since 2009), Gatehouse Maritime, Ocean Specialists (OSI), AssetMonitor | Protection zones around one owner's cables. They warn ships' bridges before accidental anchoring. Gatehouse adds radar and satellite feeds. | **For the State:** all infrastructure at once, *adversarial* behaviour (dark ships, false identities, the sanctioned fleet), **a countdown with response planning**, fibre fusion, sovereign. Their existence **proves the market**. |
| Fibre sensing | Sea-Scan (TCD), FiberSense | Detect activity at the cable | A partner layer: we cue it, name its contacts, and improve its labels |
| Maritime-intelligence platforms | Windward, Kpler, Global Fishing Watch | Generic risk scoring and vessel intelligence | Infrastructure-specific physics and feasibility-aware decisions; open data; sovereign |
| On-orbit detection | Ubotica (CogniSAT-6) | Detects ships, including dark ones, on the satellite | An input stream for us; a roadmap partner |
| EU services | EMSA Copernicus Maritime Surveillance, CleanSeaNet | Satellite products for authorities | A data source in deployment |

## 6.8 Questions a Challenge 3 jury will ask, and our answers

1. **"What exactly is space-enabled here?"** Radar re-acquisition of dark ships, the identity check from radar length, and next-look planning. On the roadmap: on-orbit alerts (Ubotica) and satellite AIS.
2. **"Satellite data isn't real time."** Correct. The countdown runs on real-time AIS, and space gives custody and identity at each pass. We plan the next look instead of pretending it's continuous.
3. **"What's autonomous?"** 24/7 monitoring, custody and prediction, plus automatic cueing within rules approved in advance. Actions stay human.
4. **"How would the Defence Forces use it tomorrow?"** In the Naval Service operations centre, and later the national maritime security centre, with EMSA feeds and their own AIS. An RTI trial on historical data comes first.
5. **"Why not buy NKT, Gatehouse or Windward?"** They protect assets for owners. We plan the State's response to adversarial ships. It's sovereign, and it plugs in Irish sensors like Sea-Scan.
6. **"How do you know the anchor-drag detector works?"** Use the *Eagle S* profile replay, synthetic injections with precision and recall, and false alarms per day on real Irish traffic against a baseline.
7. **"What about data sovereignty?"** Open data, deployable on-premises, and optional LLM on sovereign EU compute (TensorX).
8. **"Relationship with Sea-Scan?"** Complementary: a two-way cue plus better labels. We contacted the team (say this only if true, and only with their consent for anything more).

## 6.9 Risks in the challenge itself, and how to handle them

- **"Just another dashboard."** Lead with the **countdown and the numbers**, not the map.
- **The jury prefers tangible autonomy** (drones). Show automatic cueing of GUARD-type drones and satellite looks within human-approved rules.
- **Over-promising space.** Say plainly what radar can and cannot do (§6.5). The honesty earns trust.
- **Stepping on Sea-Scan.** Never claim to replace fibre sensing, and get their consent before naming them as partners.
