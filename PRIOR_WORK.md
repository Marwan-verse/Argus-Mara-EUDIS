# Prior work declaration — Argus Mara

Frozen on 15 October 2026. The tag `pre-hackathon` marks commit `e7ea692` (14 October 2026, 21:57 UTC), the last commit on `main` before the 15–17 October hackathon. Everything in that commit was built before the event. `git log pre-hackathon..main` lists the work added at the event. Git commits, not this summary, are the detailed record of authorship and timing.

## Built before the hackathon (in `pre-hackathon`)

- **Planning and research:** challenge choice, name, product decisions D1–D62, team plan, pitch research and sources in `DECISIONS.md`, `README.md` and `docs/`.
- **Demonstration contract and browser replay:** `demo/scenario.json`, `demo/alerts.json`, the scenario generator, `scripts/check_contracts.py` and the offline operator console in `ui/`, migrated to Svelte 5 (D14, D27–D29, D37–D38).
- **Data:** the Irish AIS recorder in `recorder/` (D10, D21); the shared live AIS service and feed in `live/` (D36, D40, D44); bundled Irish ports and the historical cable reference layer (D34–D35, D41).
- **Space:** importers, radar/AIS association, length review, two attributed historical contacts and offline evidence packs in `argus/` and `space/` (D23–D26); Nazar's attributed satellite image pack in `demo/imagery/` (D49–D50). Original downloaded rasters stay ignored under `data/`.
- **Brain:** the rule-based alert, countdown and responses (D29); alert levels v1 and the simulated alert board (D47); dark-vessel prediction (D51); incidents, the AIS spoofing and cable-risk detectors, responders that arrive in time, replay stories and faster scoring (D61–D62).
- **Native desktop application:** `run_gui.py` and `desktop_*.py`, with the map console, live AIS, weather, ports, vessel cards, map ping, docked alert panel and trackpad gestures (D30–D36, D39–D48).
- **Private SOC communication:** accounts, groups, end-to-end encrypted chat and pings for 2–16 people, the local Docker demonstration and launchers (D52–D54, D56–D57), and the security review fixes: typed safety codes, refusing invisible characters, per-address limits and staying signed in (D58–D60).
- **Checks:** automated tests in `tests/` and continuous integration on Ubuntu and Windows (D57).

## Written before the event but merged during it

- Adam's "stopped away from ports" and "loitering at a coastal site" alerts (D63): commit `aca223c`, written on 14 October 2026 at 18:48 UTC and merged into `main` on 15 October (`e12f1ae`).

## Limits

The fictional scenario, illustrative cable routes, simulated alerts and radar detections and assumed response assets are demonstration material, not operational validation. Real public data is labelled as real; secrets and downloaded data are kept out of Git.
