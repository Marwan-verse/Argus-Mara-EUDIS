# Browser and recorder tools

These are separate entry points supplied with the project, alongside the native app.

| Tool | Where to open it | What it does |
|---|---|---|
| Browser exercise | Run `python scripts/serve_demo.py`, then open `http://127.0.0.1:8000/ui/` | Plays the fictional map scenario, countdown, response comparison and evidence review; records explicit simulated approval and exports an HTML record. |
| Live AIS dashboard | The deployed live AIS service's browser page | Displays received contacts, search, map, selected-vessel information and feed status. |
| AIS recorder | `recorder/START-WINDOWS.bat` or `recorder/START-MAC-LINUX.command` | Records public AIS broadcasts to local files; needs the provider API key. |
| Recorder checks and map | `recorder/check.py` and `recorder/map.py` | Inspect recording health and produce a map preview. |
| Space evidence packs | Tools documented in `space/README.md` | Prepare attributed offline radar/AIS review packs with acquisition times, provenance, hashes and matching caveats. |
| SOC browser admin | `/admin/` on the private SOC server | Account, group and audit management for administrators. |

The browser exercise runs from committed local assets through the static server.
Open its served URL rather than double-clicking the HTML file. Recording and
private team services are independent of the fictional replay. Raw recordings,
downloaded imagery and credentials stay outside Git.

[Browser guide](../../ui/README.md) · [Recorder guide](../../recorder/README.md) · [Space guide](../../space/README.md) · [All categories](README.md)
