# Argus Mara alert levels

How Argus Mara gives a vessel near a cable or pipeline its alert level, and how the
docked alert panel in the desktop app works. Rules version: **levels v1.1**
(`argus/levels.py`). Decisions D47 and D61 in [DECISIONS.md](../DECISIONS.md).

A level answers one question: **how much attention does this line need now?** It does
not say the crew is guilty, and it is a rule outcome, not a probability of hostile
intent. A prepared crew can tell a plausible story, so the rules score what the ship
does, how close it is and what it could damage. Every point is listed next to the
alert, so an operator can see exactly why it has its level.

Everything on the panel today is **simulated**: fictional vessels and observations on
illustrative line routes. No live detector feeds it yet, and no decision leaves the
operator's computer.

## Score and bands

**Score = Behaviour (B) + Identity (I) + Proximity (P) + Line at risk (A) + Context (C)**

| Score | Level |
|---|---|
| 0–2 | None (not listed) |
| 3–5 | Low |
| 6–8 | Medium |
| 9–11 | High |
| 12 and above | Critical |

## Points

| Group | Cue | Points |
|---|---|---|
| **B · Behaviour**, max 6. The strongest pattern scores in full; each extra pattern adds 1. | Anchor-drag pattern under way: speed falls 20% or more and course turns 20° or more | 4 |
| | Moving while reporting "at anchor": the anchor is dragging | 4 |
| | Holding position 1 h or more over a deep cable, vessel able to launch underwater vehicles | 4 |
| | Loitering or circling 1 h or more beside the line | 3 |
| | Three or more passes over the same segment in 6 h | 3 |
| | 10 min or more at 6 kn or less over the corridor, with no stated reason | 3 |
| | Anchored within 1 nm of the line | 2 |
| | Bottom-fishing pattern within 2 nm | 2 |
| | Unexplained slowdown within 5 nm | 2 |
| | Stopped 2 h or more away from any port or designated anchorage (30 min or more: 2) | 3 |
| | Stayed 1 h or more inside the protection zone around a coastal site | 3 |
| | Slowed over these lines on earlier voyages; AIS status contradicts the movement | +1 each |
| **I · Identity and data**, max 3 | No AIS from a radar contact, or AIS silent 10 min or more near the line | 2 |
| | Spoofing signs: impossible jump, or two positions for one identity | 2 |
| | Satellite-radar contact without matching AIS | 1 |
| | Radar length differs more than 25% from the AIS length | 1 |
| | Name, flag or MMSI changed in the last 12 months | 1 |
| | Static AIS data incomplete: destination or IMO missing | 1 |
| **P · Proximity**, counts only when B + I is 2 or more | Inside the 1 nm corridor or a site's zone, or 30 min or less from an anchor-reachable section | 4 |
| | Reaches the line within 2 h | 3 |
| | Reaches the line within 6 h, or is within 5 nm of the line or the site's zone | 1 |
| **A · Line at risk**, counts only when B + I is 2 or more | Gas pipeline, power interconnector, only link on its route, cluster of three or more lines, transatlantic cable | 2 |
| | Telecom cable with alternative routes | 1 |
| | Exposed, shallow-buried or previously damaged segment | +1 |
| | Site at risk: naval base, or cable or pipeline landfall | 2 |
| | Site at risk: offshore wind farm | 1 |
| **C · Context**, max 3 | On a sanctions or shadow-fleet watch list | 2 |
| | A second sensor (fibre or radar) reports activity at the line | 2 |
| | Recent flag change or opaque ownership | 1 |
| | Declared destination does not match the route | 1 |
| | Gale warning in the sea area, which raises anchor-drag risk | 1 |

Proximity and the line at risk count only with a behaviour or identity cue, so a
normal ship passing an important cable does not raise an alert.

## Gates and overrides

Gates stop one noisy signal from producing a high level. Overrides apply after them.

| Rule | Effect |
|---|---|
| No behaviour cue (B = 0) | Stops at Medium |
| High needs B ≥ 3, a damage method possible at this depth, and P ≥ 3 (the line within 2 h) | Otherwise Medium |
| Critical needs the High gate and P = 4 (in the corridor or within 30 min) | Otherwise High |
| A line fault or fibre impact is reported at this position and time | Critical |
| The vessel ignored a recorded warning or instruction near the line | Critical |
| No response option arrives before the earliest ETA | One level up (Medium → High, High → Critical) |
| Authorised operation: a notified repair or survey | Capped at Low |

## Worked examples

| Case | Basis | Level |
|---|---|---|
| Exercise contact CORMORANT STAR: 24% slowdown and 30° turn, 20 min AIS gap, unmatched radar contact, ETA 61 min, telecom cable | B4 I3 P3 A1 C0 = 11 | High; Critical once the ETA is 30 min or less |
| Research vessel holding 3 h over a deep only link, 35 min AIS gap, watch-listed | B4 I2 P4 A2 C2 = 14 | Critical |
| Trawler making four passes over a cable cluster with an exposed segment | B3 I0 P4 A3 C0 = 10 | High |
| Ship anchored near a telecom cable under a gale warning | B2 I0 P4 A1 C1 = 8 | Medium; High once it drags |
| Watch-listed tanker with a recent flag change, transiting normally 4 nm away | B0 I1 P0 A0 C3 = 4 | Low: proximity does not count without behaviour or identity |
| Ferry on its usual route through the corridor | 0 | None: not listed |

## Coastal sites, stops and loitering

`argus/sites.py` adds two detectors that work on a timed AIS track (time, position,
speed). Both run on the fictional tracks of the four coastal-site contacts, so their
cues come from code, not hand-written observations.

- **Stopped away from ports.** The vessel has been at 0.5 kn or less up to its latest
  fix, and that fix is more than 3 nm from every port in the bundled NGA World Port
  Index and Marine Atlas files and from the edge of a rough designated anchorage
  (Dublin Bay, Cork Harbour, Shannon Estuary, Waterford Harbour). Fishing vessels are
  skipped because they stop at sea for work. A reception gap over 30 min ends the stop.
- **Loitering at a site.** The vessel has stayed inside the site's zone continuously up
  to its latest fix. A ship crossing a 2 nm zone at 10 kn is inside for about 24 min,
  so an hour or more means it stayed, whatever its speed.

| Site | Kind | Zone |
|---|---|---|
| Haulbowline naval base | Naval base | 1 nm |
| EWIC landfall, Rush | Landfall | 2 nm |
| Greenlink landfall, Baginbun | Landfall | 2 nm |
| IC2 gas landfall, Gormanston | Landfall | 2 nm |
| Transatlantic cable landfall, Killala Bay | Landfall | 2 nm |
| Arklow Bank offshore wind farm | Wind farm | 2 nm |

Positions are approximate public locations; landfalls sit where the illustrative routes
reach the shore. Zones and anchorages are design choices, not charted limits. Selecting
a site contact draws its zone as a dashed ring labelled "approximate zone"; the review
window shows **In zone** or the distance to the zone. Haulbowline sits inside a busy
harbour, so the stop rule never fires there (Cobh is a port) and harbour traffic would
make the loiter rule noisy without a list of expected vessels.

## The alert panel

| Part | Behaviour |
|---|---|
| Place | Docked between the left icon rail and the map; the map uses the remaining width. The **!** icon or **×** hides it, and dragging its right edge resizes it. |
| Order | Critical → High → Medium → Low. Within a level, a vessel already in the corridor comes first, then the soonest ETA, then the higher score. |
| Counters | One counter per level above the list. Click one to show only that level; click it again or **show all** to clear. |
| Sort | Severity (grouped by level), Time to asset, or Newest. |
| Row | Level code (CRIT, HIGH, MED, LOW) and score; vessel name, age and a **SIM** (or **EXERCISE**) mark; the situation; in corridor, distance or a live ETA; review status. |
| Review window | Click a row or a map marker. It shows the level and its place on the score scale, the asset at risk, the time to the asset, the **indicators** behind the level with their points, any rule that capped or raised it, the recommended action and the log. The map moves the vessel into view beside the window. **Show on map** fits the track and the asset. Escape closes it. |
| Decisions | **Acknowledge**: seen and watching. **Escalate** to the duty officer, the line operator, the Irish Coast Guard (MRCC) or Naval Service operations, with an optional note. **Reject** as a false alarm, known benign activity, an authorised operation or a duplicate; the card moves to **Closed** and leaves the map. **Reopen** undoes a decision. |
| Statuses | New → Reviewed (opened) → Acknowledged, Escalated or Rejected. The footer counts each status. |
| Trackpad | Two-finger scrolling moves the queue and the review window. On macOS, pinching zooms the map at the pointer; this uses the optional PyObjC package in `requirements-mac.txt`, which `UPDATE-AND-RUN-MAC.command` installs. |
| Live countdown | ETAs count down every second and the contact is re-scored. GREY HERON goes from High to Critical about 3.5 minutes after start; its card flashes and the change is logged. |
| Map | Markers are coloured by level; Critical ones pulse. High and Critical names carry a **SIM** label, the selected vessel shows its track and its line (marked "illustrative route"), and a **SIMULATED** badge sits in the corner. **Sim alerts** in the legend or Map layers hides them. |
| Exercise | The fictional exercise alert is on the same list with the same rules. **Open replay** starts the existing countdown replay with its response options. |
| Restart | The ↻ button restarts the simulation: countdowns and decisions reset. |

Decisions are recorded only for the current session on this computer. Nothing is sent
to anyone, and a human decides every action.

## The simulated board

The board holds 45 items: the fictional exercise alert from the demo files, 15
hand-written scenarios, 4 coastal-site contacts scored from fictional tracks and 25
frequent minor alerts. Minor alerts are the most common,
as in real operations: short reception gaps, GPS glitches, measurement noise,
watch-listed ships in normal transit, pilot-area slowdowns and notified repair or
survey work and stops in open water. At start it shows 3 Critical, 7 High, 10 Medium
and 25 Low.

| ID | Vessel | Situation | Basis | Level |
|---|---|---|---|---|
| SIM-02 | KESTREL DAWN | Holding position 3 h over the Galway–Iceland link | B4 I2 P4 A2 C2 = 14 | Critical |
| SIM-03 | BRANDON GLEN | Fibre sensing reports an impact beneath the ship | B3 I0 P4 A3 C2 = 12 | Critical (fault override) |
| SIM-01 | ORLA BREEZE | Anchor dragging across the EWIC power cable | B4 I0 P4 A2 C0 = 10 | Critical (ignored instruction) |
| SIM-05 | ATLANTIC WREN | Dragging at anchor near the Dublin–Holyhead cable in a gale | B4 I0 P4 A1 C1 = 10 | High |
| SIM-04 | MOY HARVESTER | Four trawl passes over the North Dublin cable cluster | B3 I0 P4 A3 C0 = 10 | High |
| SIM-06 | GREY HERON | Loitered 6 h beside the IC2 gas pipeline, now heading for it | B3 I3 P3 A2 C2 = 13 | High; Critical when within 30 min |
| SIM-07 | CORRIB MIST | Slowing with an unsteady course 3 nm from Greenlink | B3 I2 P3 A2 C0 = 10 | High |
| SIM-41 | VELVET PETREL | Circling 2.5 h off Haulbowline naval base after a 30 min AIS gap | B3 I2 P4 A2 C0 = 11 | High |
| SIM-44 | MERROW LIGHT | Stopped 2.5 h off the Greenlink landfall beach, away from any port | B4 I0 P4 A2 C0 = 10 | High |
| A1 | CORMORANT STAR | Fictional exercise: slowdown and turn towards a cable after an AIS gap | B4 I3 P3 A1 C0 = 11 | High |
| SIM-13 | BLASKET SPRAY | Two trawl passes over the North Dublin cable cluster | B2 I0 P4 A3 C0 = 9 | Medium (High gate not met) |
| SIM-10 | NORTHERN SKUA | Slow transit at 5 kn over the Dublin–Holyhead corridor | B3 I0 P4 A1 C0 = 8 | Medium |
| SIM-09 | HOLLY BAY | At anchor 0.8 nm from the Dublin–Holyhead cable under a gale warning | B2 I0 P4 A1 C1 = 8 | Medium |
| SIM-08 | UNIDENTIFIED | Satellite-radar contact without AIS near Greenlink | B2 I3 P1 A2 C0 = 8 | Medium |
| SIM-15 | KILKEE ROSE | Watch-listed tanker slowing 4 nm from the Celtic Interconnector route | B2 I1 P1 A2 C2 = 8 | Medium |
| SIM-11 | TARA SOUND | AIS gap of 25 min ended 3 nm from EWIC; slowed afterwards | B2 I2 P1 A2 C0 = 7 | Medium |
| SIM-14 | CLARE VOYAGER | Reports "at anchor" while moving 4 kn near the Dublin–Holyhead cable | B3 I1 P1 A1 C1 = 7 | Medium |
| SIM-42 | HALCYON REACH | Circling 1.6 h inside the Arklow Bank wind farm with no notified work | B3 I0 P4 A1 C0 = 8 | Medium |
| SIM-43 | SORREL ISLE | Stopped 2 h 20 min in Killala Bay, 1 nm outside the cable landfall zone | B3 I1 P1 A2 C0 = 7 | Medium |
| SIM-12 | ARDMORE TIDE | Renamed and reflagged this year; slowing near the North Dublin cluster | B2 I1 P1 A3 C0 = 7 | Medium |

Vessel names are fictional. Line routes are rough illustrative paths for familiar
Irish links (EWIC, Greenlink, the Celtic Interconnector, IC2, the Moyle interconnector,
the Galway–Iceland link and others), not surveyed positions. Positions stay at the
alert fix; only the two contacts with an ETA count down.

## Limits

- Thresholds and points are design choices for the demo. They need tuning with
  operators and real data before any operational use.
- The level is a rule outcome, not a measured probability. A Low is not "safe" and a
  Critical is not proof of sabotage.
- "A damage method possible at this depth" defaults to yes; depth data is not yet wired in.
- The stop and loiter detectors run only on fictional tracks; they are not yet wired to
  received live AIS. Small boats landing on a beach often carry no AIS at all.
- No live AIS or radar detector feeds this board yet. Received live AIS on the map is
  separate and never scored.

## Files and tests

| File | Role |
|---|---|
| `argus/levels.py` | Rules: points, caps, gates, overrides and bands |
| `argus/sites.py` | Coastal sites, anchorages, and the stop and site-loiter detectors |
| `argus/alert_board.py` | The simulated board: scenarios, coastal-site contacts, minor alerts, tracks and the countdown update |
| `desktop_alerts.py` | Docked panel, review window and map markers |
| `desktop_gestures.py` | Two-finger scrolling on Tk 9 and pinch-to-zoom on macOS |
| `tests/test_levels.py` | Rule cases, including every worked example above |
| `tests/test_sites.py` | Stop and loiter detection, port and anchorage exclusions, and the new rule cues |
| `tests/test_alert_board.py` | Labels, sorting, counts and the countdown raising a level |
| `tests/test_desktop_alerts.py` | Panel, decisions, filters, map markers and hiding the panel |
| `tests/test_desktop_gestures.py` | Trackpad scrolling of the queue and pinch zoom steps |

Run them with `python -m unittest discover -s tests`.
