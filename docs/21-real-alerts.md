# Real alerts from live AIS (D95)

The exercise's alert rules now also run on **real ships**. `argus/live_alerts.py` reads the team AIS database. The database copies the Railway feed every 30 seconds, so this works even when no laptop was recording.

Each real ship that is near one of the illustrative cable routes (`argus.alert_board.LINES`: Greenlink, EWIC, Dublin–Holyhead, Celtic Interconnector and the rest) is passed through the same detectors and levels as the exercise, via `argus.assemble`:
- `cable_risk`: loitering, slow over the corridor, drift, repeated passes;
- `ais_spoofing`;
- `route_check` (C3);
- the watch lists (D87);
- the original four-cue rule.

Every result is labelled **real** and worded *for review*. A level is a rule outcome on public AIS and approximate routes, never evidence of intent, and nothing is sent anywhere.

## How it works

1. `LiveTracks.refresh()` calls the read-only database function `public.argus_recent_tracks`, added by migration `20261016134500`.
   - The first call loads the last **3 hours** of fixes for Irish waters. On 16 Oct this was about 6,000 fixes from about 230 ships, 0.5 MB in 0.5 s.
   - Later calls ask only for fixes since the newest one already held (with a 2-minute overlap), about **20 KB** every 5 minutes.
   - The older `argus_ais_rows` sends 24 h of static history with every call (about 1.5 MB), so polling it would use up the free plan's traffic within days.
2. `vessels()` keeps a ship only if:
   - it reported in the last 30 minutes;
   - it came within **6 nm** of a route in the last hour;
   - it is **not harbour craft**. Harbour craft means within 2.5 nm of a World Port Index port, inside a harbour or estuary that the 1:50m coastline counts as land, or reporting "moored" for the whole last hour.
   
   AIS "not available" speed (102.3 kn) and course (360°) values are dropped rather than guessed.
3. `assess()` runs the detectors and turns every level above None into an item. Items have the same shape as `argus.brain_board` items, with `label: "real"`, id `REAL-<MMSI>`, the threatened route and the latest position.
4. `python -m argus.live_alerts` prints the real alerts the rules give right now. It only reads; `--json` prints the items.

## First check on live data (16 Oct 2026, about 14:30 UTC)

| Step | Count |
|---|---|
| Ships in Irish waters, last 3 h | 233 |
| Near a route | 37 |
| Harbour craft left out (19 at ports, 3 inside harbours) | 22 |
| Assessed | 15 |
| **Real alerts** | **2** |

The two alerts:
- **High:** a 27 m vessel held at 3 kn or less for 1.8 h inside the Celtic Interconnector corridor, 20 nm from any port.
- **Low:** a 22 m vessel slow inside the Cork transatlantic corridor.

Without the harbour rule, the same data gave 6 alerts, 4 of them tugs and pilot boats working in Dublin, Cork and Milford Haven harbours.

## Limits

- The routes are illustrative, not surveyed cable positions. Proximity numbers are therefore approximate.
- AIS reception is partial, and some ships do not report at all.
- The deployed Railway build does not send voyage destinations, so `route_check` (C3) cannot fire for real ships until it is redeployed.
- Only three hours of history are used, so the six-hour repeated-pass rule sees only part of a pattern.
- The harbour rule can hide a real event inside a port. It is a team assumption, chosen to keep the queue readable.
- A ship working on a cable (survey or repair) also triggers the rules. Analysts record that as an outcome.
