# `demo/`: the contract everyone builds against

**Read this before you write a line of code.** It is two JSON files. They let all five
workstreams work at the same time, on day one, without waiting for each other.

| File | Answers | Owned by | Status |
|---|---|---|---|
| `scenario.json` | *What happened?* Ships, where they were, the cable, the radar detection, the response assets | **Data** | sample, replace with real geometry |
| `alerts.json` | *What did Argus Mara notice?* The alert, why, the countdown, who gets there in time | **Brain** | **stub** — replace with the real detector |

`make_scenario.py` writes both. Run it:

```bash
python3 demo/make_scenario.py
```

Nothing to install, and no internet needed.

## Why files and not a server

For the first demo there is **no backend**. The interface loads two JSON files and plays
them. That means:

- nothing to deploy, nothing to break on stage, and it works with the Wi-Fi off;
- Brain can work in Python while Interface works in JavaScript, and neither blocks the other;
- when the real engine is ready, it writes the same `alerts.json` and nothing in the
  interface changes. A live API endpoint comes later, after the demo already runs.

## The story the files tell

A fictional tanker, *CORMORANT STAR*, sails north through the Irish Sea.

| Time | What happens |
|---|---|
| 0–29 min | Normal passage, 12.0 kn |
| 29–50 min | **AIS goes silent** for 20 minutes |
| 40 min | **A radar image finds it anyway.** It measures 228 m, but it declared 180 m → identity mismatch |
| 50 min | AIS comes back. It has turned towards the shallow stretch over the cable |
| 70 min | It slows: 12 → 9.1 kn, course wobbling. This is the *Eagle S* signature |
| **75 min** | **ALERT.** Cable in **1 h 15 min**. Aircraft ✅ 39 min · patrol ship ❌ 232 min · VHF ❌ out of range · next satellite ❌ 250 min |
| 163 min | It would reach the cable |

That last line is the honest part: the countdown says **75 minutes** but the vessel really
arrives in **88**, because it keeps slowing after the alert. Countdown v1 sails the vessel
straight ahead at its current speed, so it errs early. Say so in the pitch — judges respect
a number that knows its own error.

## The shapes

`scenario.json`

```
t0_utc          when the scenario starts, as a real timestamp
replay_speed    60 = one minute of the story per second on screen
cables[]        id, name, kind, path[[lat,lon],...], anchor_reachable[[lat,lon],[lat,lon]], min_depth_m
vessels[]       mmsi, name, type, ais_length_m, flag, track[{t, lat, lon, sog_kn, cog_deg}]
                   t is seconds from t0. A jump in t IS the AIS gap - do not fill it in.
detections[]    t, lat, lon, length_m, source, scene_id, matched_mmsi   (radar)
assets[]        id, name, lat, lon, readiness_min, speed_kn             (response options)
```

`alerts.json`

```
alerts[]
  id, t                 when the alert fires, seconds from t0
  mmsi, vessel_name, state      WATCH | APPROACHING | ALERT | CONTACT | RESOLVED
  score                 0..1
  reasons[]             plain sentences. These become the chips on the alert card.
  segment_id            which cable is threatened
  distance_km
  eta_expected_s        >>> THE BIG COUNTDOWN <<<
  eta_earliest_s        the small print: "earliest 63 min"
  options[]             asset, eta_s, in_time (true = arrives before eta_earliest_s)
  evidence_url
```

## Rules for this folder

- **Never change a field name without telling the other workstream.** Add fields freely;
  renaming one breaks someone else's screen.
- Everything here is **simulated**. The vessel is fictional, the cable route is an
  illustrative straight line, and the asset speeds are assumptions. Every object carries a
  `label` field (`real` / `reconstructed` / `simulated` / `fictional` / `assumption`), and
  the interface must show it. This is a hackathon rule and a credibility win.
- When Data has the real cable routes and real depth, only `scenario.json` changes.
- When Brain has the real detector, only `alerts.json` changes.
