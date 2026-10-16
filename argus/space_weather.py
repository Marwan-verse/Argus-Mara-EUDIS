"""Planetary Kp index and the NOAA G-scale: is satellite navigation (GNSS) likely degraded right now?

During a geomagnetic storm GNSS receivers can lose accuracy, so AIS positions (which come from
GPS on board) may jump without any spoofing. This module only tells Brain and the operator what
the space weather is; it never raises an alert by itself.

Sources (open data, label "real"):

* NOAA SWPC planetary K-index, 3-hourly, last 7 days:
  https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json (US Government, public domain).
* GFZ Potsdam Kp, the definitive index, also the historical storm of 10-11 May 2024 (Kp 9, G5):
  https://kp.gfz.de/app/json/ (CC BY 4.0, credit GFZ Potsdam). Fallback when NOAA is unreachable.
* G-scale and its effects: NOAA Space Weather Scales, https://www.swpc.noaa.gov/noaa-scales-explanation.

Kp comes in thirds (5- = 4.67, 5o = 5.00, 5+ = 5.33). Assumption: 5- already counts as Kp 5, so the
G thresholds below start at the "minus" third; 9- (8.67) stays G4, as the NOAA scale says
("Kp = 8, including a 9-").

The app never waits for the network: ``SpaceWeather.start()`` fetches in a background thread with a
short timeout, and ``current()`` answers at once from the newest of live data, the local cache in
``data/space_weather/`` (git-ignored) and the snapshot saved in the repository.

Usage: python -m argus.space_weather            (show the current status; fetches once)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
RECENT_SNAPSHOT = SNAPSHOT_DIR / "kp_recent.json"
STORM_SNAPSHOT = SNAPSHOT_DIR / "kp_storm_2024-05.json"
CACHE_PATH = ROOT / "data/space_weather/kp_recent.json"

SWPC_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
GFZ_URL = "https://kp.gfz.de/app/json/?start={start}&end={end}&index=Kp{status}"
SCALES_URL = "https://www.swpc.noaa.gov/noaa-scales-explanation"
SOURCES = {
    "NOAA SWPC": {"url": SWPC_URL, "licence": "US Government work, public domain",
                  "name": "NOAA SWPC planetary K-index"},
    "GFZ Potsdam": {"url": "https://kp.gfz.de/", "licence": "CC BY 4.0 (credit GFZ Potsdam)",
                    "name": "GFZ Potsdam geomagnetic Kp index"},
}
STORM_2024 = {"start": "2024-05-09T00:00:00Z", "end": "2024-05-12T23:59:59Z"}
USER_AGENT = "ArgusMaraDesktop/0.3 (hackathon demo; space weather display)"
TIMEOUT_S = 5
REFRESH_S = 30 * 60
log = logging.getLogger(__name__)

# Lowest Kp of each G level (thirds notation; see the module docstring for the assumption).
G_THRESHOLDS = ((5, 9.0), (4, 7.67), (3, 6.67), (2, 5.67), (1, 4.67))
G_NAMES = {0: "no storm", 1: "minor", 2: "moderate", 3: "strong", 4: "severe", 5: "extreme"}
# Effect on satellite navigation, as the NOAA Space Weather Scales describe each level (paraphrased).
NAV_IMPACT = {
    0: None,
    1: None,
    2: None,
    3: "satellite navigation may have intermittent problems",
    4: "satellite navigation may be degraded for hours",
    5: "satellite navigation may be degraded for days",
}
# Assumption (ours, not NOAA's): from this level Brain treats a single vessel's position jump as
# possibly GNSS error. Ireland is mid-latitude, where the effects are weaker than near the poles.
GNSS_CAUTION_G = 3


def _utc_text(text: str) -> str:
    """ISO time as "YYYY-MM-DDTHH:MM:SSZ" (SWPC sends no zone, GFZ sends Z; both are UTC)."""
    moment = datetime.fromisoformat(text.strip().replace(" ", "T").replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kp(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) and 0 <= number <= 9 else None


def _series(pairs) -> list[dict]:
    """Sorted ``[{"t", "kp"}]`` from (time, value) pairs; unreadable rows are skipped, a repeated time keeps the last."""
    rows = {}
    for t, value in pairs:
        kp = _kp(value)
        if kp is None or not isinstance(t, str):
            continue
        try:
            rows[_utc_text(t)] = kp
        except ValueError:
            continue
    return [{"t": t, "kp": rows[t]} for t in sorted(rows)]


def parse_swpc(data) -> list[dict]:
    """NOAA SWPC ``noaa-planetary-k-index.json``: a list of objects, or the older header-row table."""
    if not isinstance(data, list):
        raise ValueError("SWPC Kp: expected a list")
    if data and isinstance(data[0], list):  # older format: [["time_tag", "Kp", ...], [...], ...]
        header = data[0]
        if "time_tag" not in header or "Kp" not in header:
            raise ValueError("SWPC Kp: header has no time_tag and Kp")
        t_at, kp_at = header.index("time_tag"), header.index("Kp")
        pairs = ((row[t_at], row[kp_at]) for row in data[1:] if isinstance(row, list) and len(row) > max(t_at, kp_at))
    else:
        pairs = ((row.get("time_tag"), row.get("Kp")) for row in data if isinstance(row, dict))
    series = _series(pairs)
    if not series:
        raise ValueError("SWPC Kp: no readable values")
    return series


def parse_gfz(data) -> list[dict]:
    """GFZ ``/app/json/`` answer: ``{"datetime": [...], "Kp": [...], "status": [...]}``."""
    if not isinstance(data, dict) or not isinstance(data.get("datetime"), list) or not isinstance(data.get("Kp"), list):
        raise ValueError("GFZ Kp: expected datetime and Kp lists")
    series = _series(zip(data["datetime"], data["Kp"]))
    if not series:
        raise ValueError("GFZ Kp: no readable values")
    return series


def g_level(kp: float | None) -> int:
    """NOAA G level 0-5 for one Kp value (0 = no storm)."""
    if kp is None:
        return 0
    return next((level for level, lowest in G_THRESHOLDS if kp >= lowest - 1e-6), 0)


def kp_text(kp: float) -> str:
    """Kp in the familiar thirds notation: 4.67 -> "5-", 5.0 -> "5", 5.33 -> "5+"."""
    whole, third = divmod(round(kp * 3), 3)
    return f"{whole + 1}-" if third == 2 else f"{whole}+" if third == 1 else f"{whole}"


def nav_impact(level: int) -> str | None:
    return NAV_IMPACT.get(level)


def describe(kp: float) -> dict:
    """Level, name and navigation effect for one Kp value."""
    level = g_level(kp)
    return {"kp": kp, "kp_text": kp_text(kp), "g": level, "g_name": G_NAMES[level],
            "storm": level >= 1, "nav_impact": nav_impact(level), "gnss_caution": level >= GNSS_CAUTION_G}


def snapshot(series: list[dict], source: str, request_url: str, raw, retrieved: datetime | None = None,
             note: str | None = None) -> dict:
    """The saved form: real values with their source, link, licence and retrieval time."""
    info = SOURCES[source]
    result = {"label": "real", "source": source, "source_name": info["name"], "source_url": request_url,
              "licence": info["licence"], "scales_url": SCALES_URL,
              "retrieved_utc": (retrieved or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "kp": series, "raw": raw}
    if note:
        result["note"] = note
    return result


def _get_json(url: str, timeout: float, opener=None) -> object:
    opener = opener or urlopen  # looked up at call time, so tests can block the network
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def gfz_url(start: str, end: str, definitive: bool = False) -> str:
    return GFZ_URL.format(start=start, end=end, status="&status=def" if definitive else "")


def fetch_recent(timeout: float = TIMEOUT_S, opener=None, now: datetime | None = None) -> dict:
    """Last days of Kp: NOAA SWPC first, GFZ Potsdam if NOAA fails. Raises if both fail."""
    try:
        raw = _get_json(SWPC_URL, timeout, opener)
        return snapshot(parse_swpc(raw), "NOAA SWPC", SWPC_URL, raw, now)
    except Exception as error:  # any network or format failure: try the second source
        log.info("NOAA SWPC Kp unavailable (%s); trying GFZ", error)
    now = now or datetime.now(timezone.utc)
    start = datetime.fromtimestamp(now.timestamp() - 7 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    url = gfz_url(start, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    raw = _get_json(url, timeout, opener)
    return snapshot(parse_gfz(raw), "GFZ Potsdam", url, raw, now)


def fetch_storm_2024(timeout: float = 30, opener=None) -> dict:
    """Definitive GFZ Kp for the 10-11 May 2024 storm (G5), with a day either side."""
    url = gfz_url(STORM_2024["start"], STORM_2024["end"], definitive=True)
    raw = _get_json(url, timeout, opener)
    return snapshot(parse_gfz(raw), "GFZ Potsdam", url, raw,
                    note="Historical storm of 10-11 May 2024, definitive values. In the demo it is laid over "
                         "the fictional exercise for illustration only.")


def load_snapshot(path: Path) -> dict | None:
    """A saved snapshot, or None if it is missing or unreadable (never raises)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("kp"), list) or not data["kp"]:
        return None
    try:
        data["kp"] = _series((row["t"], row["kp"]) for row in data["kp"])
    except (KeyError, TypeError):
        return None
    return data if data["kp"] else None


def status(data: dict, origin: str, at: str | None = None) -> dict:
    """What to show: the 3-hour interval at ``at`` (default the latest), with level, source and origin.

    ``origin`` is "live", "cache" or "snapshot" (repository copy, possibly old) or "historical".
    """
    series = data["kp"]
    row = series[-1]
    if at is not None:
        at = _utc_text(at)
        row = next((item for item in reversed(series) if item["t"] <= at), series[0])
    return {**describe(row["kp"]), "t": row["t"], "label": data.get("label", "real"), "source": data["source"],
            "source_url": data["source_url"], "licence": data.get("licence"), "scales_url": SCALES_URL,
            "retrieved_utc": data.get("retrieved_utc"), "origin": origin}


def peak(data: dict) -> str:
    """Time of the first interval with the highest Kp (for the historical storm)."""
    top = max(item["kp"] for item in data["kp"])
    return next(item["t"] for item in data["kp"] if item["kp"] == top)


def headline(state: dict) -> str:
    """One display line, e.g. "Space weather: Kp 3 (quiet) · NOAA SWPC · 12:00 UTC · real"."""
    when = datetime.fromisoformat(state["t"].replace("Z", "+00:00"))
    stamp = when.strftime("%H:%M UTC") if state["origin"] in ("live", "cache") else when.strftime("%d %b %Y %H:%M UTC")
    origin = {"live": "real", "cache": "real, cached", "snapshot": "real, saved snapshot",
              "historical": "real, historical"}.get(state["origin"], state["label"])
    if state["storm"]:
        lead = f"Geomagnetic storm G{state['g']} (Kp {state['kp_text']})"
        if state["nav_impact"]:
            lead += f": {state['nav_impact']}"
    else:
        lead = f"Space weather: Kp {state['kp_text']} ({'active' if state['kp'] >= 4 else 'quiet'})"
    return f"{lead} · {state['source']} · {stamp} · {origin}"


class SpaceWeather:
    """Current Kp without ever blocking the caller.

    ``current()`` returns at once: live data once a background fetch succeeded, else the local cache,
    else the repository snapshot. ``start()`` begins the background refresh (every ``REFRESH_S``).
    """

    def __init__(self, fetch=fetch_recent, cache_path: Path = CACHE_PATH, snapshot_path: Path = RECENT_SNAPSHOT,
                 storm_path: Path = STORM_SNAPSHOT, refresh_s: float = REFRESH_S):
        self._fetch, self.cache_path, self.refresh_s = fetch, Path(cache_path), refresh_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._live = None
        self.last_error = None
        self._fallback = None
        cached = load_snapshot(self.cache_path)
        saved = load_snapshot(snapshot_path)
        if cached and (not saved or cached["kp"][-1]["t"] >= saved["kp"][-1]["t"]):
            self._fallback = (cached, "cache")
        elif saved:
            self._fallback = (saved, "snapshot")
        self._storm = load_snapshot(storm_path)

    def start(self) -> "SpaceWeather":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="argus-space-weather", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def refresh(self) -> bool:
        """One fetch (blocking: call it off the UI thread). True on success."""
        try:
            data = self._fetch()
        except Exception as error:  # never let a network or format failure escape to the app
            self.last_error = f"{type(error).__name__}: {error}"
            log.info("space weather fetch failed: %s", self.last_error)
            return False
        with self._lock:
            self._live = data
            self.last_error = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as error:
            log.info("space weather cache not written: %s", error)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            self._stop.wait(self.refresh_s)

    def current(self) -> dict | None:
        """Latest status (never waits), or None if there is no live data, cache or snapshot at all."""
        with self._lock:
            live = self._live
        if live is not None:
            return status(live, "live")
        if self._fallback is not None:
            return status(*self._fallback)
        return None

    def storm_2024(self) -> dict | None:
        """The real May 2024 storm at its peak, for the demo switch; None if the snapshot is missing."""
        if self._storm is None:
            return None
        return status(self._storm, "historical", at=peak(self._storm))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="do not fetch; show cache or snapshot")
    args = parser.parse_args()
    weather = SpaceWeather()
    if not args.offline and not weather.refresh():
        print(f"Fetch failed ({weather.last_error}); showing saved data.")
    state = weather.current()
    print(headline(state) if state else "No space weather data at all.")
    storm = weather.storm_2024()
    if storm:
        print("Demo storm:", headline(storm))


if __name__ == "__main__":
    main()
