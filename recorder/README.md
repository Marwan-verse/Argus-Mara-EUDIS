# Ship recorder ("the tracker")

Records the live position of every ship around Ireland and saves it to files on your computer.

**Is this spying?** No. Ships broadcast their position publicly by radio (AIS) — that is how
sites like MarineTraffic work. aisstream.io relays those public broadcasts for free.

---

## Start it — two clicks

**1. Get a free key.** Open <https://aisstream.io>, sign in with GitHub, copy the API key.
Keep it to yourself: never commit it, never paste it in chat.

**2. Download this project.** [Download ZIP](https://github.com/classified-mick/Defence-Hackaton/archive/refs/heads/main.zip)
and unzip it. (Or `git clone` it if you prefer.)

**3. Open the `recorder` folder and double-click:**

| Your computer | Double-click this |
|---|---|
| Windows | `START-WINDOWS.bat` |
| Mac | `START-MAC-LINUX.command` |
| Linux | `START-MAC-LINUX.command` — first: right-click → Properties → Allow executing as program |

A black window opens. The first run takes about a minute while it sets itself up, then it asks
for your key **once**. Paste it, press Enter. It never asks again.

**That is it.** Leave the window open. You will see a line like this every ten minutes:

```
2026-10-07 18:40:12 UTC  saved  14231 messages -> data/ais/2026-10-07/184012_003.parquet
```

To stop: close the window.

> **Windows warning:** Windows may say "Windows protected your PC". That is because the file is
> not signed, not because it is dangerous — it is a six-line text file you can open in Notepad.
> Click **More info → Run anyway**.
>
> **Mac warning:** macOS may say it cannot verify the developer. Right-click the file →
> **Open** → **Open** again. You only do this once.

## Running it on your own laptop

That works. Two things to know:

- **A sleeping laptop records nothing.** Turn sleep off while it runs: on Windows, Settings →
  System → Power → *Screen and sleep* → set the sleep options to **Never** when plugged in. On a
  Mac the script already prevents idle sleep by itself, but closing the lid still sleeps it.
- **Gaps are not a disaster.** When the computer wakes up, the recorder reconnects on its own and
  carries on. A few hours missing overnight costs us very little.

If you later want it to run without anyone watching, put it on a small cloud server (€4–6/month)
— see *Keeping it running after reboots* below.

## Check that it is working

Open a second window in the project folder and run:

| Command | What it shows |
|---|---|
| `.venv/bin/python recorder/check.py` (Mac/Linux) · `.venv\Scripts\python recorder\check.py` (Windows) | Files, size, and today's messages and ships. Warns if nothing new was written for 20 minutes |
| same, but `recorder/map.py` | Writes `map.html`. Open it to see every ship heard in the last hour |

If `check.py` says *No data yet*, wait ten minutes — the first file takes that long.

## What gets saved

- **Where:** `data/ais/<date>/<time>.parquet`, a new file about every 10 minutes. `data/` is
  git-ignored, so the recording never goes to GitHub.
- **Columns:** `recv_utc`, `msg_type`, `mmsi` (the ship's ID), `ship_name`, `lat`, `lon`,
  `sog` (speed in knots), `cog` (course), `heading`, `nav_status`, `time_utc`, and `raw` (the
  original message, so nothing is lost if we change the parser later).
- **Area:** 49–57.5°N, 18–4.5°W — Irish waters, the Irish Sea and the western approaches.
- **Disk:** a few hundred MB per day. Keep at least 20 GB free. Check the real figure with
  `check.py` after the first day.

## If something goes wrong

| You see | What it means |
|---|---|
| `Python is not installed` | Install it from <https://www.python.org/downloads/>. On Windows, **tick "Add python.exe to PATH"** on the first screen, then double-click the start file again |
| `aisstream rejected the API key` | Wrong or expired key. Delete the file `recorder/.apikey` and start again — it will ask for a new one |
| `connection lost … reconnecting` | Normal now and then. It reconnects by itself and keeps what it had |
| Few ships far offshore | Also normal. Coastal receivers only hear ships near the coast |
| `Could not download the two libraries` | No internet, or a firewall. Try again on a different network |

## Keeping it running after reboots (optional, Linux server, systemd)

```ini
# /etc/systemd/system/argus-recorder.service
[Unit]
Description=Argus Mara AIS recorder
After=network-online.target
Wants=network-online.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/Defence-Hackaton
Environment=AISSTREAM_API_KEY=your-key
ExecStart=/home/YOUR_USER/Defence-Hackaton/.venv/bin/python recorder/recorder.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl daemon-reload && sudo systemctl enable --now argus-recorder`.
Logs: `journalctl -u argus-recorder -f`.

**For developers:**
- The key is read from `AISSTREAM_API_KEY`, else from `recorder/.apikey`, else asked for once and
  saved there. That file is git-ignored.
- `ARGUS_AIS_URL` points the recorder at a different feed or a local test server. Open Waters AIS
  is aisstream-compatible, so it works as a drop-in backup.
- `ARGUS_FLUSH_SECONDS=10` saves more often; `ARGUS_AIS_DIR` changes the output folder.
