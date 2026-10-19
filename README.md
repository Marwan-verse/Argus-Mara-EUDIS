# Argus Mara

**A maritime intelligence workspace for reviewing AIS, satellite imagery and infrastructure context around Ireland.**

Built for **EUDIS Defence Hackathon 2026 — Challenge 3: Space-Enabled Maritime Domain Awareness**. We are opening the project so others can inspect the implementation, reproduce the demo and contribute improvements.

Argus Mara brings received ship observations, dated satellite imagery, port and cable reference layers, explainable review leads and analyst reports into one native desktop application. It also includes an offline browser replay and optional, separately deployed data and collaboration services.

This is a hackathon research prototype, not a validated navigation, surveillance or operational decision system. An AIS gap, motion anomaly, list match or unmatched image contact is a **lead for human review**, not proof of identity or malicious intent. Human approval remains explicit; the application does not carry out operational responses.

## What we built

| Area | Implemented behavior |
| --- | --- |
| Maritime map | Ireland/world views, source-labelled chart and imagery layers, coordinate tools, port/cable directories and vessel cards. |
| AIS and history | Optional shared collector, timestamped received positions, declared speed/course/destination, local recorded tracks with gaps preserved, filters, search and fleet-history checks. |
| Satellite review | Sentinel-1/2 catalogue search, georeferenced imagery crops, saved reviews, image-acquisition-time AIS comparison and optional AI-assisted contact suggestions. Coast Watch organises coastal coverage and records coverage/quality gaps. |
| Review leads | Explainable rules over available observations, source-quality checks, separate real-data and fictional exercise queues, and optional watchlist/radar inputs. |
| Analyst reporting | Evidence-prefilled editable reports, uncertainty and provenance, optional AI drafting/checking, PDF output and explicit sharing controls. |
| Investigation lab | Source timelines, pairwise encounter review, fictional scenario branches and evaluation against authored exercise labels. |
| Collaboration | Optional private SOC relay, account/group permissions and endpoint-encrypted rooms with peer-code verification. Requires a separate deployment. |
| Offline exercise | A reproducible fictional scenario, countdown/planning assumptions, simulated responder comparison and a human-reviewed exercise record. |

The fictional replay is kept separate from real observations. Every evidence item should be labelled **real**, **reconstructed**, **simulated**, **fictional** or **assumption**. AI suggestions remain unreviewed assumptions until checked. The feature guides describe [the implementation and its limits](docs/features/README.md).

## Quick start: native desktop

Use **Python 3.12** with **Tkinter/Tcl-Tk**, Git and an internet connection for the first dependency installation. The base desktop code supports Python 3.10+, but optional imagery packages should use Python 3.12 or newer. Node, Docker and API keys are **not required for the offline exercise**.

Clone this repository using its GitHub **Code** button, then open a terminal in the repository root.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_gui.py --check
.\.venv\Scripts\python.exe run_gui.py --offline
```

Include **Tcl/Tk and IDLE** when installing Python. `RUN-GUI-WINDOWS.bat` is also available; its normal entrypoint offers sign-in or **Continue offline**. Update-and-run launchers pull the current branch before launching, so use the direct commands above for a fixed checkout.

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_gui.py --check
python run_gui.py --offline
```

On Debian/Ubuntu, install the matching `python3-tk` and `python3-venv` OS packages if missing. On macOS, use a Python distribution with working Tk; `python -m tkinter` should open a small test window. The optional `requirements-mac.txt` adds native gesture support.

`--offline` skips SOC sign-in and Docker. It does not disable every public map/catalogue request: chart tiles and satellite schedules can use the network. The bundled coastline, reference data and fictional replay work without external accounts; high-detail map tiles need to have been cached first. Select the offline coastline layer when disconnected. To suppress connected background features during a deterministic offline session, set:

```powershell
# PowerShell; use export NAME=value on macOS/Linux
$env:ARGUS_AIS_AUTOCONNECT = "0"
$env:ARGUS_SUPABASE_READ = "0"
$env:ARGUS_REAL_ALERTS = "0"
$env:ARGUS_SATELLITE_AUTOSTART = "0"
$env:ARGUS_S1_PLAN_NETWORK = "0"
```

Map caches live in your OS user-cache directory. `python scripts/prefetch_map_tiles.py --help` describes optional prefetching; respect map-provider usage and redistribution terms.

## Offline browser demo

```bash
python scripts/serve_demo.py
```

Open **http://127.0.0.1:8000/ui/**. Committed browser bundles run without Node or a frontend build. The server binds to loopback and serves the checkout for local development; do not expose it publicly or use it to host private files. This replay uses the committed fictional scenario, not your live AIS feed.

## Enable connected features

A fresh checkout contains **no maintainer service address or database access key**. Bring your own services and credentials. Live traffic, historical recordings and cached satellite reviews are not included. Missing data remains unavailable; installing the app cannot recreate earlier AIS coverage.

`.env.example` lists supported settings but **the Python app does not automatically load .env files**. Set environment variables in your shell/service, or use the interactive credential helpers. Never put secrets in command-line arguments, browser code, issues or commits.

### AIS collector and recording

1. For direct recording, obtain your own AISstream API key and follow [the recorder guide](recorder/README.md). Install `recorder/requirements.txt`; the launcher asks for the key privately and stores it in ignored `recorder/.apikey`. Recordings stay under ignored `data/`.
2. For a shared map/feed, deploy your own collector using [live/README.md](live/README.md). Its separate dependencies are in `live/requirements.txt`; Docker deployment requires a persistent archive volume and the provider key in the host's secret manager.
3. Set `ARGUS_LIVE_SERVER=https://your-ais-collector.example`, or enter your collector origin in the desktop AIS panel and connect. The same setting supplies Coast Watch's receipt-time AIS capture.
4. Alternatively run `python run_live_gui.py --server https://your-ais-collector.example` for the dedicated read-only view.

Reception is partial. A stale last fix is not a current position, and an archive contains only what its collector received while running.

### Satellite imagery and AI assistance

```bash
python -m pip install -r requirements-satellite.txt -r recorder/requirements.txt
```

Open **Satellite analysis** to search the catalogue, inspect source imagery and work with local reviews. Image-time comparison requires your own recorded AIS covering that time. For optional TensorX assistance, run `python scripts/configure_satellite.py`; it asks for a key without echoing it and stores it in the OS credential store. You can instead supply `TENSORX_API_KEY` through a private host environment.

Catalogue/imagery access and paid AI analysis are separate. AI requests can incur charges; starting **Coast Watch** enables automatic analysis under its local budget ledger, and an enabled scan may resume on later launches. Review the controls before starting, and set `ARGUS_SATELLITE_AUTOSTART=0` to prevent automatic resume. See [satellite setup, storage and budget behavior](docs/16-satellite-ai.md).

### Optional historical AIS database

Supabase is optional and belongs to the operator. Set `ARGUS_SUPABASE_URL` to your own project before running `python scripts/configure_supabase.py`. That helper stores a privileged key locally; use it only on a trusted workstation/host, never distribute it to users. Read-only clients can instead use an explicitly configured `ARGUS_SUPABASE_PUBLISHABLE_KEY` with the narrowly granted read functions on their own project. See [schema installation and permissions](supabase/README.md); database availability and capture history must be established separately.

### Optional radar, watchlists and collaboration

- **GFW radar:** `python scripts/configure_gfw.py` stores your own token securely. Follow [the radar guide](docs/19-gfw-radar.md). Published detections are delayed historical data, not a live radar sensor.
- **Watchlists:** `python -m argus.watchlist_data update` downloads an attributed OpenSanctions snapshot into ignored local storage. Check source terms before reuse; list associations require review.
- **SOC collaboration:** follow [soc/README.md](soc/README.md) for a separate Docker/HTTPS relay and [the local demonstration guide](soc/LOCAL-DEMO.md). Each participant needs an authorised account and must verify peer codes. No accounts, passwords, relay address or team database are bundled.

## Datasets and reuse

| Source | Used for | Important boundary |
| --- | --- | --- |
| AISstream / your collector | Received AIS positions, declarations and history | Your own key/service; partial reception. No private team archive is distributed. |
| NGA World Port Index | 3,805 bundled port reference entries | Public reference data; retain provenance. |
| Marine Atlas / MIDA | 142 Irish port records | CC BY 4.0; categories may represent the same harbour more than once. |
| TeleGeography historical cable snapshot | 497 reference route records | Reconstructed/historical, approximate geometry; **CC BY-NC-SA 3.0**, not surveyed asset locations. |
| Natural Earth | Coastline and coastal planning geometry | Public domain; simplified display/planning geometry. |
| EMODnet / Esri and other credited map providers | Online/cached chart and imagery backgrounds | Provider-specific attribution, usage and tile redistribution terms apply. |
| Copernicus Sentinel-1/2 | Radar/optical catalogue and imagery review | Acquisition time, image quality and coverage limits remain explicit. |
| Global Fishing Watch | Optional published radar vessel detections | Personal token, publication delay and provider terms. |
| OpenSanctions | Optional maritime list context | CC BY-NC 4.0 source terms; matching is a review lead. |

See [source notes](docs/sources.md), [reference-layer preparation](scripts/prepare_world_map.py) and [the labelled imagery pack](demo/imagery/README.md). The code licence does not replace any dataset, image, map-provider or dependency licence. In particular, the bundled non-commercial cable data and optional non-commercial sources require replacement or separate permission for commercial redistribution.

## Development and verification

Python owns analysis, detection, countdown and data preparation. Svelte 5 under `ui/src/` owns browser interfaces. The desktop is Python/CustomTkinter; Node is a development tool.

```bash
python run_gui.py --check
python scripts/check_contracts.py
python -m pip install -r requirements.txt -r live/requirements.txt -r soc/requirements.txt
python -m unittest discover -s tests -v
python scripts/check_public_release.py
```

Run tests from a clean checkout, or apply the background-disable settings above first so existing local capture/scan state cannot resume during desktop tests. Install the satellite and recorder requirements for optional imagery tests. On headless Linux, desktop tests require a display (for example Xvfb); some optional tests skip without their dependencies.

For browser development, install **Node 22+** and run from the repository root:

```bash
npm ci
npx playwright install chromium
npm run check
npm run build
npm test
npm run test:browser
```

Commit rebuilt browser bundles for offline use. Preserve the `demo/scenario.json` / `demo/alerts.json` interfaces, units and coordinate order. Read [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md) and [the architecture](docs/07-architecture.md) before changes. The optional [trailer project](trailer/README.md) has its own dependencies.

## Open-source release and security

Project-owned code is released under the [MIT licence](LICENSE); third-party assets retain their own terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Please report vulnerabilities privately using [SECURITY.md](SECURITY.md). Do not attach raw observations, credentials, account databases, private reports or logs to public issues. Maintainers must complete [the publication checklist](docs/open-source-release.md), including revoking historic database access, before changing repository visibility. Old Git history is not cleaned by deleting a key from the current files.

Thank you to EUDIS, our lecturer, mentors, teammates and everyone who shared their time and feedback during the hackathon.
