"""Live geomagnetic storm status over Ireland: context for electrical cable alarms, never a ship detector.

Sources (keyless; requested only while the operator has live magnetics switched on):

* NOAA SWPC 1-minute estimated planetary Kp, https://services.swpc.noaa.gov/json/planetary_k_index_1m.json
  (US government data, credit NOAA SWPC). The estimate restarts at every 3-hour Kp boundary (00, 03,
  06 … UTC), so the status reads the maximum over the current and the previous 3-hour interval.
* INTERMAGNET 1-minute variation data from the Valentia observatory (VAL, Co. Kerry, run by
  Met Éireann) through the BGS Geomagnetism Information Node, IAGA-2002 text. CC BY-NC 4.0: credit
  INTERMAGNET, BGS and Met Éireann; commercial use needs Met Éireann's permission. ``99999.00`` marks
  a missing value; F is always missing, so only H is used, as minute-to-minute differences.

What it can say. The observatory is tens to hundreds of kilometres from any cable at sea, where a
vessel's field is effectively zero: a steel hull's anomaly falls off as 1/r³, so a seabed sensor sees a
200 m ship only within about 0.5–1 km and a 20 t anchor within about 115–250 m. A storm is therefore
only a possible natural explanation for *electrical* cable anomalies (power-feed excursions, converter
or transformer trips) near the time of a sharp field change. It never explains a physical break with a
vessel overhead, and it never raises, lowers or clears an alert. Label: real data; the tiers are a team
assumption combining SWPC's G-scale with dH/dt thresholds from the space-weather literature.

Usage: python -m argus.geomag
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
GIN_URL = ("https://imag-data.bgs.ac.uk/GIN_V1/GINServices?Request=GetData&format=iaga2002&testObsys=0"
           "&observatoryIagaCode=VAL&samplesPerDay=minute&publicationState=best-avail"
           "&dataStartDate={day}&dataDuration={days}&orientation=native")
KP_SOURCE = "NOAA SWPC estimated Kp (1-minute)"
VAL_SOURCE = "INTERMAGNET Valentia (VAL) via BGS GIN, Met Éireann"
ATTRIBUTION = "NOAA SWPC · INTERMAGNET/BGS/Met Éireann Valentia (CC BY-NC 4.0)"
USER_AGENT = "ArgusMaraDesktop/0.3 (hackathon demo; geomagnetic context display)"
MAX_BYTES = 2 * 1024 * 1024
MISSING = 88888.0  # IAGA-2002 pads gaps with 88888 or 99999

KP_INTERVAL_S = 3 * 3600
DHDT_WINDOW_S = 60 * 60  # the dH/dt peak is looked for in the last hour
KP_STALE_S = 15 * 60
VAL_STALE_S = 30 * 60
REFRESH_KP_S = 60
REFRESH_VAL_S = 5 * 60
NATURAL_WINDOW_MIN = 15  # tier 2+: electrical alarms within this many minutes of the dH/dt peak

# (tier, name, minimum Kp, minimum |dH/dt| nT/min); any one trigger is enough. Team assumption.
TIERS = (
    (3, "Severe", 8.0, 300.0),
    (2, "Strong", 7.0, 90.0),
    (1, "Active", 5.0, 18.0),
)
EFFECTS = {
    0: "No space-weather explanation for cable alarms now.",
    1: "Context only: geomagnetic activity is raised. Alerts are unchanged.",
    2: ("Electrical cable alarms within ±15 min of the field-change peak may be natural. Nothing is cleared; "
        "a physical break with a vessel present stays a lead."),
    3: ("Expect electrical alarms on several assets at once. An isolated physical fault with a vessel present "
        "stays a priority lead."),
}
PHYSICS = ("Magnetics cannot watch the sea: a steel hull's field falls off as 1/r³, so a seabed sensor sees "
           "a 200 m ship only within about 0.5–1 km and a 20 t anchor within about 115–250 m.")


def _utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_kp(text: str | bytes) -> list[dict]:
    """SWPC 1-minute rows as ``{"time", "kp"}`` (the estimated Kp), sorted by time."""
    rows = []
    for row in json.loads(text):
        value = row.get("estimated_kp", row.get("kp_index"))
        if value is None or row.get("time_tag") is None:
            continue
        value = float(value)
        if math.isfinite(value):
            rows.append({"time": _utc(row["time_tag"]), "kp": value})
    return sorted(rows, key=lambda row: row["time"])


def parse_iaga2002(text: str | bytes, component: str = "H") -> list[dict]:
    """IAGA-2002 data lines as ``{"time", "value"}`` for one component (``value`` is None when missing)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    rows, column = [], None
    for line in text.splitlines():
        if line.startswith("DATE"):
            names = line.replace("|", "").split()[3:]
            column = next((index for index, name in enumerate(names) if name.endswith(component)), None)
        elif column is not None and line[:4].isdigit():
            parts = line.split()
            if len(parts) < 4 + column:
                continue
            value = float(parts[3 + column])
            rows.append({"time": datetime.fromisoformat(f"{parts[0]}T{parts[1][:8]}").replace(tzinfo=timezone.utc),
                         "value": None if value >= MISSING or not math.isfinite(value) else value})
    return rows


def dh_dt(rows: list[dict]) -> list[dict]:
    """|ΔH| per minute between consecutive valid minutes, stamped with the later minute."""
    valid = [row for row in rows if row["value"] is not None]
    out = []
    for before, after in zip(valid, valid[1:]):
        if after["time"] - before["time"] == timedelta(minutes=1):
            out.append({"time": after["time"], "nt_per_min": abs(after["value"] - before["value"])})
    return out


def kp_interval_start(moment: datetime) -> datetime:
    """Start of the 3-hour Kp interval that contains ``moment``."""
    moment = moment.astimezone(timezone.utc)
    return moment.replace(hour=moment.hour - moment.hour % 3, minute=0, second=0, microsecond=0)


def rolling_kp(rows: list[dict], now: datetime) -> dict | None:
    """Largest estimated Kp since the start of the previous 3-hour interval; the estimate restarts each interval."""
    since = kp_interval_start(now) - timedelta(seconds=KP_INTERVAL_S)
    recent = [row for row in rows if since <= row["time"] <= now + timedelta(minutes=2)]
    if not recent:
        return None
    peak = max(recent, key=lambda row: (row["kp"], row["time"]))
    return {"kp": peak["kp"], "time": peak["time"], "latest": recent[-1]["kp"], "latest_time": recent[-1]["time"]}


def tier_for(kp: float | None, dhdt: float | None) -> tuple[int, str, list[str]]:
    """The highest tier any available input reaches, with the triggers that reached it."""
    for tier, name, kp_min, dhdt_min in TIERS:
        reasons = []
        if kp is not None and kp >= kp_min:
            reasons.append(f"Kp {kp:.2f} ≥ {kp_min:g}")
        if dhdt is not None and dhdt >= dhdt_min:
            reasons.append(f"Valentia dH/dt {dhdt:.1f} ≥ {dhdt_min:g} nT/min")
        if reasons:
            return tier, name, reasons
    return 0, "Quiet", []


def assess(kp_rows: list[dict] | None, val_rows: list[dict] | None, now: datetime | None = None) -> dict | None:
    """Storm status from whatever inputs are present; None when there is nothing to judge."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    kp = rolling_kp(kp_rows or [], now)
    changes = [row for row in dh_dt(val_rows or []) if now - timedelta(seconds=DHDT_WINDOW_S) <= row["time"] <= now]
    valid = [row for row in val_rows or [] if row["value"] is not None and row["time"] <= now]
    if kp is None and not valid:
        return None
    peak = max(changes, key=lambda row: (row["nt_per_min"], row["time"])) if changes else None
    tier, name, reasons = tier_for(kp["kp"] if kp else None, peak["nt_per_min"] if peak else None)
    notes = []
    if kp is None:
        notes.append("No Kp from NOAA SWPC: tier from Valentia only.")
    elif (now - kp["latest_time"]).total_seconds() > KP_STALE_S:
        notes.append(f"NOAA SWPC Kp is {_age(now, kp['latest_time'])} old.")
    if not valid:
        notes.append("No Valentia data: tier from Kp only.")
    else:
        if (now - valid[-1]["time"]).total_seconds() > VAL_STALE_S:
            notes.append(f"Valentia data are {_age(now, valid[-1]['time'])} old.")
        if not changes:
            notes.append("No two consecutive Valentia minutes in the last hour: dH/dt unknown.")
    effect = EFFECTS[tier]
    if tier >= 2 and peak is not None:
        effect = effect.replace("the field-change peak", f"the field-change peak at {peak['time']:%H:%M} UTC")
    return {
        "time": now, "tier": tier, "name": name, "reasons": reasons, "effect": effect, "notes": notes,
        "kp": kp["kp"] if kp else None, "kp_time": kp["time"] if kp else None,
        "kp_latest": kp["latest"] if kp else None, "kp_latest_time": kp["latest_time"] if kp else None,
        "dhdt": peak["nt_per_min"] if peak else None, "dhdt_time": peak["time"] if peak else None,
        "val_last_time": valid[-1]["time"] if valid else None, "val_last_h": valid[-1]["value"] if valid else None,
        "label": "real", "attribution": ATTRIBUTION,
    }


def _age(now: datetime, then: datetime) -> str:
    minutes = max(0, round((now - then).total_seconds() / 60))
    return f"{minutes} min" if minutes < 120 else f"{minutes / 60:.0f} h"


def summary(status: dict | None) -> str:
    """One line for the header chip, e.g. ``Quiet · Kp 0.3 · dH/dt 2 nT/min``."""
    if not status:
        return "Magnetic data unavailable"
    parts = [status["name"]]
    if status.get("kp") is not None:
        parts.append(f"Kp {status['kp']:.1f}")
    if status.get("dhdt") is not None:
        parts.append(f"dH/dt {status['dhdt']:.0f} nT/min")
    return " · ".join(parts)


def _read(url: str, timeout: float, opener) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("geomagnetic response larger than expected")
    return body


def fetch_kp(timeout: float = 20, opener=urlopen) -> list[dict]:
    rows = parse_kp(_read(KP_URL, timeout, opener))
    if not rows:
        raise ValueError("NOAA SWPC returned no Kp rows")
    return rows


def valentia_url(now: datetime) -> str:
    """Today's file, starting yesterday shortly after midnight UTC so the last hour is complete."""
    now = now.astimezone(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=1) if now - midnight < timedelta(seconds=DHDT_WINDOW_S + 600) else now
    days = 2 if start.date() != now.date() else 1
    return GIN_URL.format(day=start.date().isoformat(), days=days)


def fetch_valentia(now: datetime | None = None, timeout: float = 30, opener=urlopen) -> list[dict]:
    rows = parse_iaga2002(_read(valentia_url(now or datetime.now(timezone.utc)), timeout, opener))
    if not any(row["value"] is not None for row in rows):
        raise ValueError("Valentia returned no valid minutes")
    return rows


def to_json(status: dict) -> dict:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in status.items()}


def from_json(record: dict) -> dict:
    return {key: _utc(value) if key.endswith("time") and isinstance(value, str) else value
            for key, value in record.items()}


def save_cache(path: Path, status: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(to_json(status), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_cache(path: Path) -> dict | None:
    try:
        return from_json(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def main() -> int:
    now = datetime.now(timezone.utc)
    kp_rows = val_rows = None
    try:
        kp_rows = fetch_kp()
    except Exception as error:  # report and carry on with Valentia
        print(f"NOAA SWPC Kp unavailable: {type(error).__name__}: {error}")
    try:
        val_rows = fetch_valentia(now)
    except Exception as error:
        print(f"Valentia unavailable: {type(error).__name__}: {error}")
    status = assess(kp_rows, val_rows, now)
    if status is None:
        print("No geomagnetic data.")
        return 1
    print(f"{now:%Y-%m-%d %H:%M} UTC · tier {status['tier']} {summary(status)}")
    if status["kp_time"]:
        print(f"Kp max since {kp_interval_start(now) - timedelta(hours=3):%H:%M} UTC: {status['kp']:.2f} "
              f"at {status['kp_time']:%H:%M} UTC; latest {status['kp_latest']:.2f}")
    if status["val_last_time"]:
        print(f"Valentia last valid minute {status['val_last_time']:%H:%M} UTC, H {status['val_last_h']:.2f} nT")
    for line in status["reasons"] + status["notes"] + [status["effect"], PHYSICS, "Source: " + ATTRIBUTION]:
        print(" ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
