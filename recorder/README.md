# Ship recorder ("the tracker")

This records the live position of every ship around Ireland, 24/7. By the hackathon we will have weeks of **our own data**. We use it to learn what "normal" traffic looks like, and to measure how many false alarms Argus Mara raises.

**Is this spying?** No. Ships broadcast their position publicly by radio (AIS); that is how sites like MarineTraffic work. aisstream.io relays these public broadcasts over the internet for free.

## Start it (about 15 minutes)

1. **Get a free API key.** Sign in at <https://aisstream.io> with GitHub and copy your API key. Keep it secret: never commit it or post it in Discord.
2. **Pick a machine that is always on.** A small cloud Linux server is best; a basic VPS costs roughly €4–6/month, and free tiers work too. A laptop goes to sleep, so use one only for testing. You need Python 3.9 or newer.
3. **Install:**
   ```bash
   git clone https://github.com/classified-mick/Defence-Hackaton.git
   cd Defence-Hackaton
   python3 -m pip install -r recorder/requirements.txt
   ```
4. **Test it for a minute** in the foreground:
   ```bash
   AISSTREAM_API_KEY=your-key python3 recorder/recorder.py
   ```
   - You should see `connected … recording…`.
   - A file is saved every 10 minutes.
   - Ctrl+C stops it and saves what it has.
5. **Run it in the background.** It keeps going after you log out:
   ```bash
   AISSTREAM_API_KEY=your-key nohup python3 recorder/recorder.py >> recorder.log 2>&1 &
   ```

## Check that it works

| Command | What it shows |
|---|---|
| `python3 recorder/check.py` | Files, size, and today's messages and ships. It warns you if nothing new was written for 20 minutes. |
| `python3 recorder/map.py` | Writes `map.html`. Open it to see every ship heard in the last hour. |
| `tail -f recorder.log` | The live log |

## Keep it running after reboots (optional, systemd)

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
ExecStart=/usr/bin/python3 recorder/recorder.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then run `sudo systemctl daemon-reload && sudo systemctl enable --now argus-recorder`. The logs are at `journalctl -u argus-recorder -f`.

## What gets saved

- **Where:** `data/ais/<date>/<time>.parquet`, with a new file about every 10 minutes. The `data/` folder is git-ignored, so the data never goes to GitHub.
- **Columns:**
  - `recv_utc`, `msg_type`, `mmsi` (the ship's ID);
  - `ship_name`, `lat`, `lon`;
  - `sog` (speed in knots), `cog` (course), `heading`, `nav_status`;
  - `time_utc`, and `raw` (the original message, so nothing is lost).
- **Area:** 49–57.5°N, 18–4.5°W. That covers Irish waters, the Irish Sea and the western approaches.
- **Disk:** plan on a few hundred MB per day, and keep at least 20 GB free. Check the real number with `check.py` after day one.

## Troubleshooting

| You see | Meaning |
|---|---|
| `aisstream rejected the API key` | The key is wrong or expired. Get a new one at aisstream.io. |
| `connection lost … reconnecting` | Normal now and then. It reconnects by itself and saves what it had. |
| Few ships far offshore | Also normal. Coastal receivers only hear ships near the coast. |

**For developers:**
- `ARGUS_AIS_URL` points the recorder at a local test server.
- `ARGUS_FLUSH_SECONDS=10` saves more often.
- `ARGUS_AIS_DIR` changes the output folder.
