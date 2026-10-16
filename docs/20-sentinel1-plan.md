# Next Sentinel-1 look from ESA's acquisition plans (D89)

Radar sees ships through cloud and at night, including ships whose AIS is off.
Ireland is often cloudy, so the time of the next Sentinel-1 pass matters. Until
now the fleet file had one invented pass (`pass_times_s: [20400]`, labelled
assumption). `argus/s1_plan.py` replaces it with the real plan.

ESA publishes every planned Sentinel-1 data-take about three weeks ahead as
keyless KML files on
[Sentinel Online](https://sentinels.copernicus.eu/copernicus/sentinel-1/acquisition-plans).
Since early July 2026 these are S1C and S1D; S1A is retired.

## Where it shows

- **Incidents → an open incident → responders.** The `SAT` row is now the first
  planned swath that covers the vessel, for example
  `Sentinel-1D pass 18:06 UTC · frames ~19:06`. The check uses where the vessel
  is predicted to be when the satellite passes, at most 4 h ahead like every
  other asset. A later pass uses that 4 h position. `· swath edge` means the
  vessel is within 20 km of a swath edge, so it may be missed. The row still
  only looks and never counts as a responder.
- **◇ SAR next step.** The window opens with the countdown to the next look at
  the coast. It then lists the passes for the next 7 days, each with how many
  coastal cells it covers on each coast and when its frames should be online.
- **Command line.** `python -m argus.s1_plan next` prints the same text. Add
  `--lat 53.3 --lon -6.0` for one position, or `--at 2026-10-16T08:00:00Z` for
  another time.

## Keeping it current

- `python -m argus.s1_plan refresh` downloads, without a key, the newest plan of
  each active satellite plus older plans still in force now (four files, about
  12 MB). Files already cached are not downloaded again.
- Plans are kept in the ignored `data/s1_plan/`: the raw KML for audit and a
  parsed JSON beside it. The newest four per satellite are kept.
- Everything else works offline from that cache. When nothing is cached, the
  bundled `argus/s1_plan_snapshot.json` is used: an extract of ESA's real plans
  of 15 and 16 Oct 2026, covering 15 Oct 18:02 to 7 Nov 19:36 UTC.
- For a computer without access: download a KML in a browser, then run
  `python -m argus.s1_plan import <file.kml>`. `python -m argus.s1_plan snapshot`
  rebuilds the bundled extract from the cache.
- ESA re-issues plans, for example after emergency requests. Each moment is
  governed by the newest plan file of that satellite that covers it.

## How it works

- Each placemark is one data-take. It holds the satellite, mode (IW, EW or SM),
  polarisation, start and stop UTC, absolute and relative orbit, and a footprint
  ring. Only data-takes whose footprint touches Irish waters (18–4° W,
  49–57.5° N) are kept.
- **Real polygon intersection, not a vertex test.** ESA's footprints are long
  strips: edges reach 2,000 km and vertices often sit far from Ireland.
  - Edges are treated as great-circle arcs. A gnomonic projection centred on
    Ireland turns them into straight lines.
  - A pass counts for the coast when its polygon really intersects a Coast Watch
    grid cell (2,278 cells of about 8 km, 40 km belt). That is either a cell
    centre inside the swath, or an edge crossing near the swath's border.
  - For 16–23 Oct this finds S1D on 18 Oct at 06:38 UTC (1,112 coastal cells),
    which a vertex-in-box test missed.
- **Time over a position.** The time is interpolated along the strip. It starts
  at the ring's first vertex, where ESA's rings start, and runs towards the
  farthest vertex.
- **Frames online.** Pass time plus 1 h.

## Checked on 16 Oct 2026

- **Footprints.** The plan footprints were compared with the published GRD frames
  of two passes: S1C on 15 Oct at 18:13–18:15 and S1D on 16 Oct at 06:54–06:56.
  Frame corners lay within 20 km of the planned edges (median 7–12 km).
  Straight lon/lat edges were off by up to 39 km.
- **Times.** The predicted time over Dublin Bay on 15 Oct was 18:14:05. The frame
  that covers it ran 18:13:52–18:14:17. A 16 Oct frame centre was predicted at
  06:55:17, inside the frame's 06:55:11–06:55:36.
  `tests/test_s1_plan.py` repeats both checks on the bundled snapshot.
- **Revisit.** The plan gives the same pattern as 12 days of measured catalogue
  data (4–16 Oct):
  - Dublin Bay and the Celtic Sea get 8 looks in 12 days each (4 from S1C,
    4 from S1D), with gaps of 24 to 60 h.
  - Porcupine (13° W) gets 4 looks, plus 2 at a swath edge.
  - 15° W gets only 2 looks, both at an edge.
  - 17° W 53° N gets none.
- **Delay.** Frames reached the public Copernicus STAC catalogue 54–61 min after
  the S1C pass and 81–85 min after the S1D pass. In the OData catalogue, GRDH
  frames appeared after 36–61 min.

## Limits

- A plan is not an acquisition. Nothing here confirms that an image was taken or
  that a ship is in it.
- **Swath edges.** These are uncertain by about 20 km.
- **Area.** "The coast" means the Coast Watch grid, not the whole EEZ.
- **Wave mode.** These imagettes are not in the plans. EW strips are listed, but
  they rarely touch Irish waters.
- **Classic exercise window.** It reads the frozen demo contract
  (`demo/alerts.json`), which still lists its own assumed satellite option
  (250 min). Changing it needs the contract owners.
- **Source.** ESA Sentinel Online, Copernicus Sentinel-1 acquisition plans,
  public download without a key.
