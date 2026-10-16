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
| | Name, flag or MMSI changed in the last 12 months, or former names recorded by a sanctions or shadow-fleet list (the lists give no dates) | 1 |
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

## Heading vs declared destination (rule C3)

`argus/detectors/route_check.py` checks whether a ship is going where its AIS says.
The crew types the destination by hand (AIS Message 5). The detector reads it as a
port: a UN/LOCODE from a short table (for example `GBHLY` Holyhead, `IEDUB` Dublin), or
a port name in the bundled Irish port list and World Port Index. "FROM>TO" text keeps
the last part. Blank, unknown or "FOR ORDERS"-style text is never guessed.

Over the last 30 minutes of the track it then asks: is the ship under way (median 4 kn
or more), has it covered at least 3 nm, and has it moved away from that port (course
more than 90° off the bearing to the port, and at least 1 nm farther from it)? If so it
sets C3, **+1 in the context group**. The check stays quiet:

- within 10 nm of the port, where ships manoeuvre, wait for a pilot or anchor;
- within 6 h of leaving the declared port, when the destination is often not yet updated;
- when the straight line to the port crosses land, because the ship has to go round;
- for slow, waiting or drifting ships.

C3 alone never raises an alert (it is context, and proximity counts only with a
behaviour or identity cue). It adds one point to a ship that is already behaving
suspiciously near a line, and its finding reads "for review": an out-of-date
destination is the most common innocent explanation. Every threshold is a team
assumption.

**SIM-55 SALTEE HERON** shows it on the replay. It declares Fishguard (`GBFIS`) and
steams towards it, then from T+02:40 turns south-west, away from Fishguard and
towards Greenlink. From about T+03:05 its watch card reads "not heading to its declared
destination" (C3 +1, level None). At about T+03:30 it slows by the line and becomes
High (B1 +4, P2 +3, A1 +2, C3 +1 = 10). It runs after the Dublin stories and in the
south, so it does not change their responders or timings.

## Sanctions and shadow-fleet lists (rules C1, C2 and I5)

`argus/detectors/watchlist.py` checks a received vessel against the newest kept copy of
the OpenSanctions maritime list (`argus/watchlist_data.py`). That one keyless file merges
the EU, UK, US, Canadian, Swiss and UN sanctions lists, the shadow-fleet list of Ukraine's
military intelligence (GUR) and port-state-control detentions and bans: about 20,800
vessels, 7,300 of them with an MMSI. It is free for non-commercial use with credit
(CC BY-NC 4.0), and every finding names it. Decision D87.

| Tier | Meaning | Points |
|---|---|---|
| Confirmed | On any sanctions list | C1 +2 |
| Suspected | In GUR's shadow fleet but not sanctioned (122 ships on 15 Oct 2026). GUR often names a ship months before the EU or UK. | C1 +2 |
| Noted | A port-state detention or ban, GUR's other marine vessels, or RUSI's North Korea reports | None: information for the vessel card |

For a confirmed or suspected ship:

- **C2 +1** when its MMSI's country code (the ITU MID table in `argus/itu_mids.json`) is
  not a flag any list gives, GUR records five or more flags for it, GUR lists its current
  flag as "unknown or false", or the MMSI looks made up (four zeros after the country
  code, like the 610000036 the tanker Blue used under a false Benin flag).
- **I5 +1** for the former names the lists record. They carry no dates, so the indicator
  reads "former names recorded by the lists; dates not given" instead of "in 12 months".

Matching uses the MMSI or the IMO number, **never the name**. GUR alone lists two
different YANTAR, and the Russian intelligence ship Yantar (MMSI 273546520) is on no list.
Rows are grouped by IMO, so a ship the EU lists without an MMSI is still found by the
MMSI that GUR or a port inspection recorded. A name only picks between records that share
one MMSI. When the AIS name is not among the listed names (GUR writes SKAUT where AIS says
SCOUT), the finding says so and asks for an IMO check before acting, but keeps the points.

Without points, as information only: AIS-SART, man-overboard and EPIRB-AIS numbers (MMSI
starting 970, 972 or 974) read "possible distress beacon, check"; an MMSI whose country
code ITU never allocated, a number that several listed ships share and a ship taken off the
lists each get a note. Only vessels labelled real or reconstructed are compared with the
lists, so the simulated board is unchanged. List cues are context: a listed tanker passing
calmly stays Low (B0 I1 P0 A0 C3 = 4).

Commands (the copies live in the git-ignored `data/watchlist/`):

```
python -m argus.watchlist_data update      # at most one check per UTC day; keeps a dated copy
python -m argus.watchlist_data backfill    # optional: about one older version a week, for "since" dates
python -m argus.watchlist_data scan-live   # every contact in the team's live AIS feed
python -m argus.watchlist_data check 613414602
```

Without a network the newest copy is used; without any copy the detector stays silent. A
history of list versions gives "on the list since ..." (the first kept version that holds
the ship, "or earlier" when that is the oldest copy) and "was on the list until ...". When
GUR named a ship before it was sanctioned, the finding says so.

On 16 Oct 2026 the team's live feed (2,037 contacts since 8 Oct) held 13 sanctioned and 6
suspected ships according to OpenSanctions, several of them west of Ireland near 12° W.
From list cues alone each is Low or None.

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
| Decision log | The shield button opens the **signed decision log**: who decided what, on which alert and when, newest first. Every decision, responder sent or recalled and restart is a record signed with this computer's Ed25519 key that also holds the hash of the record before it. **Verify signatures** checks them all: a changed record turns red (CHANGED AFTER SIGNING), the next one amber (LINK BROKEN). The **seal** of the last record changes if records are removed from the end, so note it down. **Show the file** opens `data/desktop/decision-log.jsonl` for the tamper demo. `python -m argus.decision_log verify` checks the file from a terminal. |

The review states belong to the current session. The signed decision log stays on this
computer. Nothing is sent to anyone, and a human decides every action.

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

## Brain detectors

`argus.assemble.DETECTORS` runs every registered detector on a vessel's track and
merges what they find into one set of observations for the rules above. Each finding
says which detector found it, when, where, why and how strong the evidence is.

| Detector | Looks for | Fills |
|---|---|---|
| `legacy_cable_v1` | The four-cue exercise rule from `argus/brain.py` | B1, I1, I3, I4, P, A |
| `cable_risk` | Behaviour per line from the recent track: anchor drag, loitering, passes, slow in the corridor, anchoring, fishing, slowdown; ETA to the anchor-reachable section | B1–B7, B10, B11, P, A |
| `ais_spoofing` | Impossible jumps, one identity in two places, speed that does not match the positions, fixes on land, an impossible return after a gap | I2 |
| `stop_off_port` | Stopped at 0.5 kn or less for 30 min or more, over 3 nm from every port (`ui/assets/irish_ports.json`, `world_ports.json`) and rough anchorage; fishing vessels skipped | B12 |
| `dark_vessel` | A satellite radar contact while the vessel's AIS was silent 10 min or more, inside its reachable circle (and within reach of the fix where AIS came back); also contacts no AIS vessel could have been | I1, I3, I4 |
| `declared_vs_actual` | Reports "at anchor" or "moored" while moving 1 kn or more for 10 min; a declared destination (port name or UN/LOCODE) the course has led away from for an hour | B9, C3 |

Only `cable_risk` and `legacy_cable_v1` name a line, so proximity and the line's
class always come from them. `dark_vessel` is held from the fictional exercise
(`HELD_FROM_SCENARIO`) until the team agrees to raise it earlier (D63).

Three replay stories show the new detectors on the board's replay clock, scored from
their tracks like SIM-50 to SIM-53:

| ID | Vessel | Story | Level over time |
|---|---|---|---|
| SIM-54 | MOURNE SHADE | AIS silent from T+80 to T+125 on the approach to the Dublin–Holyhead cable; a simulated Sentinel-1 contact at T+110 fits its track | None → Medium at T+110 (I1, I3, worst-case ETA) → Critical at T+132 (AIS back, slow and yawing) |
| SIM-55 | CALLOW BAY | Declares `IEDUB>GBLIV`, turns north-west, then reports "at anchor" while making 4 kn over the North Dublin cluster | C3 alone at T+145 (None) → Medium at T+164 → High at T+170 (B9) → Critical at T+173 |
| SIM-56 | TUSKAR CALM | Stops for 2.5 h about 4 nm from both EWIC and the North Dublin cluster, away from any port or anchorage | Low at T+109 → Medium at T+135 (B12) |

## Limits

- Thresholds and points are design choices for the demo. They need tuning with
  operators and real data before any operational use.
- The level is a rule outcome, not a measured probability. A Low is not "safe" and a
  Critical is not proof of sabotage.
- "A damage method possible at this depth" defaults to yes; depth data is not yet wired in.
- The stop and loiter detectors run only on fictional tracks; they are not yet wired to
  received live AIS. Small boats landing on a beach often carry no AIS at all.
- The destination check needs a declared destination. The deployed Railway feed does not
  send Message 5 destinations yet, so real ships get no C3 until it is redeployed.
- The list check matches live ships by MMSI only: the live stream carries no IMO or call
  sign yet, and adding them needs a Railway redeploy and a Supabase migration. Only about
  35% of listed ships have an MMSI in the lists, and a ship that takes a new MMSI is found
  again only once a list records the new number.
- No live AIS or radar detector feeds this board yet. Received live AIS on the map is
  separate and never scored.

## Files and tests

| File | Role |
|---|---|
| `argus/levels.py` | Rules: points, caps, gates, overrides and bands |
| `argus/sites.py` | Coastal sites, anchorages, and the stop and site-loiter detectors |
| `argus/detectors/route_check.py` | Declared AIS destination against the recent track (rule C3) |
| `argus/detectors/watchlist.py` | Sanctions and shadow-fleet lists, flag risk, former names and distress beacons (rules C1, C2, I5) |
| `argus/watchlist_data.py` | OpenSanctions copies, version history, ITU MID helpers and the `scan-live` command |
| `argus/itu_mids.json` | ITU MID table with ISO country codes |
| `argus/alert_board.py` | The simulated board: scenarios, coastal-site contacts, minor alerts, tracks and the countdown update |
| `desktop_alerts.py` | Docked panel, review window and map markers |
| `desktop_gestures.py` | Two-finger scrolling on Tk 9 and pinch-to-zoom on macOS |
| `argus/detectors/` | Brain detectors (`cable_risk`, `ais_spoofing`, `stop_off_port`, `dark_vessel`, `declared_vs_actual`) and the port, anchorage and destination lookup (`places.py`) |
| `argus/brain_board.py` | The board scored through Brain, with the replay stories |
| `tests/test_levels.py` | Rule cases, including every worked example above |
| `tests/test_sites.py` | Stop and loiter detection, port and anchorage exclusions, and the new rule cues |
| `tests/test_route_check.py` | Destination reading, heading-away cases, quiet cases and the SIM-55 story |
| `tests/test_watchlist.py` | Matching on 38 real list rows, tiers, flag signs, beacons, the once-a-day fetch and offline use |
| `tests/test_alert_board.py` | Labels, sorting, counts and the countdown raising a level |
| `tests/test_desktop_alerts.py` | Panel, decisions, filters, map markers and hiding the panel |
| `tests/test_desktop_gestures.py` | Trackpad scrolling of the queue and pinch zoom steps |
| `tests/test_stop_off_port.py`, `tests/test_dark_vessel.py`, `tests/test_declared_vs_actual.py` | The three detectors, their thresholds and what they must not flag |
| `tests/test_detector_stories.py` | SIM-54 to SIM-56 over time, and the innocent stories staying quiet |

Run them with `python -m unittest discover -s tests`.
