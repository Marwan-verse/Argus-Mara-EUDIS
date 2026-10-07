# Ship recorder ("the tracker")

Records the live position of every ship around Ireland and saves it to files on your computer.

**Is this spying?** No. Ships broadcast their position publicly by radio (AIS) — that is how
sites like MarineTraffic work. aisstream.io relays those public broadcasts for free.

---

## Start it — two clicks

**1. Get a free key.** Open <https://aisstream.io>, sign in with GitHub, copy the API key.
Keep it to yourself: never commit it, never paste it in chat.

**2. Get this project onto your computer.**

- **On a Mac, prefer `git clone`** — files that arrive through git carry no quarantine flag, so
  macOS will not block them:
  ```bash
  git clone https://github.com/classified-mick/Defence-Hackaton.git
  ```
- Otherwise [download the ZIP](https://github.com/classified-mick/Defence-Hackaton/archive/refs/heads/main.zip)
  and unzip it. On a Mac this triggers the Gatekeeper block described below — fixable in about
  ten seconds, but cloning avoids it entirely.

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

### If your computer refuses to open the file

Both operating systems block files downloaded from the internet that nobody has paid to sign.
It is not a sign that anything is wrong — these launchers are short text files you can open in
Notepad or TextEdit and read in full.

**Windows:** "Windows protected your PC" → **More info** → **Run anyway**.

**Mac:** *"Apple could not verify that this file is free of malware"*, with the buttons *Move to
Trash* and *Done*.

> **Do not click *Move to Trash*** — that deletes the file. Click **Done**.

The old trick of right-clicking and choosing *Open* **no longer works**; Apple removed it in
macOS 15 (Sequoia). Two ways out:

**Fastest, and it fixes the whole folder at once.** Open Terminal (Spotlight → type `Terminal`),
type this with a space at the end, then **drag the project folder from Finder into the Terminal
window** so the path fills itself in, and press Enter:

```bash
xattr -r -d com.apple.quarantine 
```

That strips the "downloaded from the internet" flag. Double-clicking works normally afterwards,
for good.

**Without Terminal:**
1. Double-click the file, let it fail, click **Done**.
2. Straight away, open **System Settings → Privacy & Security**, scroll to the **Security**
   section. A line names the blocked file with an **Open Anyway** button. *(It only appears if
   you tried to open the file in the last hour, so do this right after step 1.)*
3. Click it, enter your password, then double-click the file again and choose **Open**.

## Leaving it running for days on your own laptop

That works, and the script handles most of it:

- **Idle sleep, on a Mac:** handled. The start file runs the recorder under `caffeinate -i`, so
  the machine will not fall asleep on its own while it records. Note this is macOS only, and
  `-i` covers *idle* sleep — closing the lid still sleeps it.
- **Idle sleep, on Windows:** **not** handled, there is no `caffeinate`. Do it once by hand:
  Settings → System → Power → *Screen and sleep* → set the sleep options to **Never** when
  plugged in. Thirty seconds, and it stays set.
- **Crashes:** handled. If the recorder dies for a reason it cannot recover from itself, the
  start file waits ten seconds and launches it again, forever.
- **Dropped connections:** handled. The recorder reconnects by itself and keeps what it had.

**What is still on you, and what actually breaks a long run:**

1. **The computer restarting itself for updates overnight.** This is the usual way a multi-day
   recording dies quietly. On Windows: Settings → Windows Update → **Pause updates**. On a Mac:
   System Settings → General → Software Update → turn off automatic install.
2. **Power.** Keep it plugged in. A laptop that reaches a low battery will sleep whatever else
   is set.
3. **Nobody noticing.** Glance at the window once a day, or run `check.py` (below). It takes
   five seconds and tells you when the last file was written.

**And if it does stop for a while, nothing is ruined.** We measure false alarms on the Danish
archive, not on this recording — this one only has to show the detector also works on Irish
traffic. A missing night costs us very little.

If you would rather not babysit it at all, a small cloud server is €4–6/month — see *Keeping it
running after reboots* below.

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
- **Disk:** measured at **about 82 bytes per message** once Parquet and zstd have compressed it
  — roughly 8× smaller than the raw JSON aisstream sends. So **1 million messages ≈ 82 MB**.
  How many messages a day we actually get depends on how much traffic the coastal receivers hear;
  at 2 million a day that is ~165 MB/day and ~1.3 GB over eight days. Keep a few GB free and get
  the real figure from `check.py` after the first day.

## If something goes wrong

| You see | What it means |
|---|---|
| `Python is not installed` | Install it from <https://www.python.org/downloads/>. On Windows, **tick "Add python.exe to PATH"** on the first screen, then double-click the start file again |
| macOS: *Apple could not verify…* | Gatekeeper. See *If your computer refuses to open the file* above. Do not click *Move to Trash* |
| `aisstream rejected the API key` | Wrong or expired key. Delete the file `recorder/.apikey` and start again — it will ask for a new one |
| `connection lost … reconnecting` | Normal now and then. It reconnects by itself and keeps what it had |
| `Recorder stopped unexpectedly. Starting it again…` | Also fine. Something killed the process; the start file is bringing it back |
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
