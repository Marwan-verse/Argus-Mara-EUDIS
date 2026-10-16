"""Sanctions and shadow-fleet lists for the watchlist detector (rules C1, C2 and I5).

One keyless file, OpenSanctions ``maritime.csv``, merges the EU, UK, US,
Canadian, Swiss and UN sanctions lists, the shadow-fleet list of Ukraine's
military intelligence (GUR) and port-state-control detention and ban lists:
about 20,800 vessels, 7,300 of them with an MMSI. ``update`` checks it at most
once per UTC day, downloads a version only when OpenSanctions has published a
new one, and keeps it as a dated gzip copy in the ignored ``data/watchlist/``
folder. Everything else works offline from the newest copy. A small history
records the first and last list version that held each IMO and MMSI, so a
finding can say "on the list since ..." or "was on the list until ...".
``backfill`` seeds that history from older versions (OpenSanctions keeps about
100 daily versions).

The file has one row per source list, so one ship can fill several rows. Rows
are grouped by IMO number: a ship the EU lists without an MMSI is still found
by the MMSI that GUR or a port inspection recorded for the same IMO. Tiers:

* confirmed: on any sanctions list (OpenSanctions tag ``sanction``);
* suspected: in GUR's shadow fleet (``mare.shadow``) but not sanctioned. GUR
  often names a ship months before the EU or the UK sanctions it;
* noted: a port-state detention or ban, GUR's other marine vessels, or RUSI's
  reports on North Korea. Information for the vessel card, never points.

Matching is by MMSI or IMO only, never by name: GUR alone lists two different
"YANTAR", and the Russian intelligence ship Yantar (MMSI 273546520) is on no
list. A name only picks between records that share one MMSI, and a finding
warns when the AIS name differs from every listed name.

Data: OpenSanctions (https://www.opensanctions.org), CC BY-NC 4.0: free for
non-commercial use, with credit. A list entry is a lead for review, not proof.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import threading
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data/watchlist"
MID_FILE = Path(__file__).with_name("itu_mids.json")
INDEX_URL = "https://data.opensanctions.org/datasets/latest/maritime/index.json"
VERSIONS_URL = "https://data.opensanctions.org/artifacts/maritime/versions.json"
VERSION_URL = "https://data.opensanctions.org/artifacts/maritime/{version}/maritime.csv"
LIVE_FEED = "https://shared-live-ais-production.up.railway.app/api/v1/vessels"
ALLOWED_HOSTS = ("data.opensanctions.org", "shared-live-ais-production.up.railway.app")
USER_AGENT = "ArgusMara/1.0 (EUDIS Defence Hackathon team; watchlist detector)"
LICENCE = "CC BY-NC 4.0"
CREDIT = f"OpenSanctions, {LICENCE}"
SOURCE_PAGE = "https://www.opensanctions.org/datasets/maritime/"

MAX_CSV_BYTES = 64 * 1024 * 1024  # the file is about 5 MB
MAX_JSON_BYTES = 16 * 1024 * 1024  # index, versions and the live vessel list
MIN_VESSELS = 5000  # a real maritime.csv has about 20,800 vessels; far fewer means a broken download
KEEP_SNAPSHOTS = 60
COLUMNS = ("type", "caption", "imo", "risk", "countries", "flag", "mmsi", "id", "url", "datasets", "aliases")

GUR = "ua_war_sanctions"
TIERS = ("noted", "suspected", "confirmed")  # ascending
POINT_TIERS = ("suspected", "confirmed")
NOTED_RISKS = frozenset({"mare.detained", "reg.warn", "poi"})
NOTED_DATASETS = frozenset({"kp_rusi_reports"})
FLAG_HOPS = 5  # flags in GUR's record (current and former) that count as flag hopping
FILLER_MMSI = re.compile(r"[2-7]\d{2}0000\d{2}")  # e.g. 610000036, the number the tanker Blue used
BEACONS = {"970": "AIS-SART search-and-rescue transmitter", "972": "man-overboard (MOB) device",
           "974": "EPIRB-AIS emergency position beacon"}
NAME_PREFIXES = ("M V ", "M T ", "MV ", "MT ")

# Source list: short title, and the jurisdiction when the list is a sanctions list.
DATASETS = {
    "us_ofac_sdn": ("US OFAC SDN", "US"), "us_trade_csl": ("US Consolidated Screening List", "US"),
    "us_ofac_cons": ("US OFAC non-SDN", "US"), "us_cbp_forced_labor": ("US CBP withhold release orders", "US"),
    "eu_journal_sanctions": ("EU Official Journal", "EU"), "eu_sanctions_map": ("EU Sanctions Map", "EU"),
    "eu_fsf": ("EU Financial Sanctions Files", "EU"), "gb_fcdo_sanctions": ("UK Sanctions List", "UK"),
    "ca_dfatd_sema_sanctions": ("Canada SEMA", "Canada"), "ch_seco_sanctions": ("Swiss SECO", "Switzerland"),
    "un_1718_vessels": ("UN 1718 Committee", "UN"), "fr_tresor_gels_avoir": ("France Tresor freezes", "France"),
    "mc_fund_freezes": ("Monaco fund freezes", "Monaco"), "be_fod_sanctions": ("Belgium FPS Finance", "Belgium"),
    "ae_local_terrorists": ("UAE local terrorist list", "UAE"),
    GUR: ("Ukraine GUR War & Sanctions", None),
    "tokyo_mou_detention": ("Tokyo MoU detentions", None), "black_sea_mou_detention": ("Black Sea MoU detentions", None),
    "abuja_mou_detention": ("Abuja MoU detentions", None), "paris_mou_banned": ("Paris MoU banned ships", None),
    "ext_tokyo_mou_psc": ("Tokyo MoU inspections", None), "ext_abuja_mou_psc": ("Abuja MoU inspections", None),
    "kp_rusi_reports": ("RUSI reports on North Korea", None),
}


# ---------------------------------------------------------------- identities

def normalise_mmsi(value) -> str | None:
    """A 9-digit MMSI string, or None."""
    text = str(value if value is not None else "").strip()
    return text if re.fullmatch(r"\d{9}", text) else None


def normalise_imo(value) -> str | None:
    """A 7-digit IMO number string ("IMO9236353" -> "9236353"), or None."""
    text = re.sub(r"^IMO\s*", "", str(value if value is not None else "").strip().upper())
    return text if re.fullmatch(r"\d{7}", text) and text != "0000000" else None


def name_key(text) -> str:
    """Upper-case ASCII words without punctuation or an "MV"/"MT" prefix, for comparing names."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text).strip()
    for prefix in NAME_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix):]
    return text


@lru_cache(maxsize=1)
def _mid_table() -> dict:
    return json.loads(MID_FILE.read_text(encoding="utf-8"))


def country_name(code: str) -> str:
    return _mid_table()["names"].get(code, code.upper())


def countries(codes) -> str:
    return ", ".join(country_name(code) for code in codes)


def mid_info(mmsi) -> dict | None:
    """The country an MMSI's first three digits (MID) belong to, per ITU; None if not a ship number or unallocated."""
    mmsi = normalise_mmsi(mmsi)
    if mmsi is None or mmsi[0] not in "234567":
        return None
    entry = _mid_table()["mids"].get(mmsi[:3])
    return {"mid": mmsi[:3], **entry} if entry else None


def unallocated_mid(mmsi) -> bool:
    mmsi = normalise_mmsi(mmsi)
    return mmsi is not None and mmsi[0] in "234567" and mid_info(mmsi) is None


def beacon_kind(mmsi) -> str | None:
    """AIS-SART (970), man-overboard (972) or EPIRB-AIS (974) numbers belong to a beacon, not a ship."""
    mmsi = normalise_mmsi(mmsi)
    return BEACONS.get(mmsi[:3]) if mmsi else None


# ---------------------------------------------------------------- the list

def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


_FORMERLY = re.compile(r"\(\s*(?:formerly|f\.?k\.?a\.?)\s+([^)]*)\)", re.IGNORECASE)


def _caption(text: str) -> tuple[str, list[str]]:
    """'Aqua Titan (formerly Lang Ya)' -> ('Aqua Titan', ['Lang Ya'])."""
    former = [name.strip() for match in _FORMERLY.findall(text) for name in re.split(r"[,/]", match) if name.strip()]
    return _FORMERLY.sub("", text).strip(), former


def _new_record(key: str, imo: str | None) -> dict:
    return {"key": key, "imo": imo, "captions": Counter(), "gur_captions": [], "aliases": [], "mmsis": {},
            "flags": {}, "flag_history": set(), "gur_flag_unknown": False, "risks": set(), "datasets": set(),
            "sanctioned_by": set(), "urls": {}}


def _add_row(record: dict, row: dict) -> None:
    datasets = _split(row["datasets"])
    risks = set(_split(row["risk"]))
    caption, former = _caption(row["caption"])
    if caption:
        record["captions"][caption] += 1
        if GUR in datasets:
            record["gur_captions"].append(caption)  # GUR keeps names current; sanctions lists keep the old one
    record["aliases"] += former + [_caption(alias)[0] for alias in _split(row["aliases"])]
    for mmsi in _split(row["mmsi"]):
        if normalise_mmsi(mmsi):
            record["mmsis"].setdefault(mmsi, set()).update(datasets)
    for flag in _split(row["flag"]):
        record["flags"].setdefault(flag.lower(), set()).update(datasets)
    if GUR in datasets:
        record["flag_history"].update(code.lower() for code in _split(row["countries"]))
        if not _split(row["flag"]):
            record["gur_flag_unknown"] = True  # the GUR page says "Flag (Current): unknown"
    record["risks"] |= risks
    record["datasets"].update(datasets)
    if "sanction" in risks:
        record["sanctioned_by"].update(DATASETS.get(name, (name, name))[1] or name for name in datasets)
    for name in datasets:
        record["urls"].setdefault(name, row["url"])


def tier_of(record: dict) -> str:
    if "sanction" in record["risks"]:
        return "confirmed"
    if "mare.shadow" in record["risks"]:
        return "suspected"
    if record["risks"] & NOTED_RISKS or record["datasets"] & NOTED_DATASETS:
        return "noted"
    return "none"  # port inspections only: they link an IMO to an MMSI and say nothing bad


def _finish(record: dict) -> dict:
    """Turn the collected sets into sorted lists; the first name is GUR's current one when GUR lists the ship."""
    record["tier"] = tier_of(record)
    names, seen = [], set()
    captions = record["gur_captions"] + [name for name, _count in record["captions"].most_common()]
    for text in captions + record["aliases"]:
        key = name_key(text)
        if key and key not in seen:
            seen.add(key)
            names.append(text)
    order = sorted(record["datasets"], key=lambda name: DATASETS.get(name, (name,))[0])
    record.update(
        name=names[0] if names else "", names=names,
        mmsis={mmsi: sorted(sets) for mmsi, sets in sorted(record["mmsis"].items())},
        flags={flag: sorted(sets) for flag, sets in sorted(record["flags"].items())},
        flag_history=sorted(record["flag_history"]), risks=sorted(record["risks"]), datasets=order,
        lists=[DATASETS.get(name, (name,))[0] for name in order], sanctioned_by=sorted(record["sanctioned_by"]),
        url=record["urls"].get(GUR) or next(iter(record["urls"].values()), None))
    for field in ("captions", "gur_captions", "aliases", "urls"):
        del record[field]
    return record


def _decode(raw: bytes | str) -> str:
    return raw if isinstance(raw, str) else raw.decode("utf-8-sig")


def parse(raw: bytes | str, meta: dict | None = None, history: dict | None = None) -> "WatchList":
    """Build the vessel index from an OpenSanctions ``maritime.csv``; organisations are skipped."""
    reader = csv.DictReader(io.StringIO(_decode(raw), newline=""))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"not an OpenSanctions maritime.csv: missing columns {', '.join(missing)}")
    rows = [row for row in reader if row.get("type") == "VESSEL"]
    records: dict[str, dict] = {}
    by_imo: dict[str, str] = {}
    for row in rows:
        imo = normalise_imo(row["imo"])
        if imo:
            key = f"imo:{imo}"
            _add_row(records.setdefault(key, _new_record(key, imo)), row)
            by_imo[imo] = key
    by_mmsi: dict[str, list[str]] = {}
    for record in records.values():
        for mmsi in record["mmsis"]:
            by_mmsi.setdefault(mmsi, []).append(record["key"])
    for row in rows:
        if normalise_imo(row["imo"]):
            continue
        # No IMO: join the one record that already holds its MMSI, else start a record of its own.
        mmsis = [mmsi for mmsi in _split(row["mmsi"]) if normalise_mmsi(mmsi)]
        owners = {key for mmsi in mmsis for key in by_mmsi.get(mmsi, ())}
        key = owners.pop() if len(owners) == 1 else f"os:{row['id']}"
        record = records.setdefault(key, _new_record(key, None))
        _add_row(record, row)
        for mmsi in mmsis:
            if key not in by_mmsi.setdefault(mmsi, []):
                by_mmsi[mmsi].append(key)
    for record in records.values():
        _finish(record)
    return WatchList(records, by_imo, by_mmsi, meta or {}, history or {})


class WatchList:
    """The newest list copy, indexed by IMO and MMSI, with the snapshot history."""

    def __init__(self, records: dict, by_imo: dict, by_mmsi: dict, meta: dict, history: dict):
        self.records, self.by_imo, self.by_mmsi = records, by_imo, by_mmsi
        self.meta, self.history = meta, history

    def stats(self) -> dict:
        tiers = Counter(record["tier"] for record in self.records.values())
        return {"vessels": len(self.records), "with_mmsi": sum(1 for r in self.records.values() if r["mmsis"]),
                **{tier: tiers[tier] for tier in (*TIERS, "none")}}

    def _spans(self, key: str) -> dict:
        return (self.history.get("keys") or {}).get(key) or {}

    def oldest_version_date(self) -> str | None:
        dates = [version["date"] for version in self.history.get("versions") or []]
        return min(dates) if dates else None

    def _result(self, record: dict, matched_by: str, name) -> dict:
        spans = self._spans(record["key"])
        current = spans.get(record["tier"])
        latest = self.meta.get("date")
        previous = []  # a higher tier that ended before this list version, e.g. sanctions lifted
        if record["tier"] in TIERS and latest:
            rank = TIERS.index(record["tier"])
            previous = [{"tier": tier, "since": span[0], "until": span[1]} for tier, span in spans.items()
                        if tier in TIERS and TIERS.index(tier) > rank and span[1] < latest]
        first_listed = min((spans[tier][0] for tier in POINT_TIERS if tier in spans), default=None)
        agrees = None
        if name_key(name):
            agrees = name_key(name) in {name_key(listed) for listed in record["names"]}
        return {"status": "listed", "tier": record["tier"], "record": record, "matched_by": matched_by,
                "name_agrees": agrees, "since": current[0] if current else None, "first_listed": first_listed,
                "previous": previous, "list_date": latest, "list_version": self.meta.get("version"),
                "oldest_copy": self.oldest_version_date()}

    def match(self, mmsi=None, imo=None, name=None) -> dict | None:
        """The listed vessel with this IMO or MMSI. The name never makes a match; it only picks among records
        that share one MMSI. Returns None when nothing matches."""
        imo, mmsi = normalise_imo(imo), normalise_mmsi(mmsi)
        if imo and imo in self.by_imo and self.records[self.by_imo[imo]]["tier"] != "none":
            return self._result(self.records[self.by_imo[imo]], "IMO", name)
        keys = [key for key in self.by_mmsi.get(mmsi, ()) if self.records[key]["tier"] != "none"] if mmsi else []
        if len(keys) == 1:
            return self._result(self.records[keys[0]], "MMSI", name)
        if len(keys) > 1:
            named = [key for key in keys if name_key(name) and name_key(name) in
                     {name_key(listed) for listed in self.records[key]["names"]}]
            if len(named) == 1:
                return self._result(self.records[named[0]], "MMSI, name picks one of several", name)
            return {"status": "ambiguous", "candidates": [self.records[key] for key in keys], "matched_by": "MMSI",
                    "list_date": self.meta.get("date"), "list_version": self.meta.get("version")}
        for key in ([f"imo:{imo}"] if imo else []) + ([f"mmsi:{mmsi}"] if mmsi else []):
            spans = self._spans(key)
            listed = [(tier, spans[tier]) for tier in reversed(POINT_TIERS) if tier in spans]
            if listed:
                tier, (since, until) = listed[0]
                return {"status": "delisted", "tier": tier, "since": since, "until": until,
                        "list_date": self.meta.get("date"), "list_version": self.meta.get("version")}
        return None


def history_keys(watch: WatchList) -> dict[str, str]:
    """IMO, MMSI and record keys of every tiered vessel -> its tier, for the snapshot history."""
    keys: dict[str, str] = {}
    for record in watch.records.values():
        if record["tier"] not in TIERS:
            continue
        for key in [record["key"]] + [f"mmsi:{mmsi}" for mmsi in record["mmsis"]]:
            if key not in keys or TIERS.index(record["tier"]) > TIERS.index(keys[key]):
                keys[key] = record["tier"]
    return keys


def add_to_history(history: dict, watch: WatchList, version: str, day: str) -> dict:
    """Record that this list version (exported on ``day``) held these vessels; order of versions does not matter."""
    versions = history.setdefault("versions", [])
    if any(item["version"] == version for item in versions):
        return history
    versions.append({"version": version, "date": day})
    versions.sort(key=lambda item: (item["date"], item["version"]))
    spans = history.setdefault("keys", {})
    for key, tier in history_keys(watch).items():
        span = spans.setdefault(key, {}).setdefault(tier, [day, day])
        span[0], span[1] = min(span[0], day), max(span[1], day)
    return history


def flag_signs(record: dict, mmsi) -> list[str]:
    """Flag-risk signs (rule C2) for a listed vessel seen with this MMSI."""
    signs = []
    mid = mid_info(mmsi)
    flags = list(record["flags"])
    if mid and flags and not set(mid["iso"]) & set(flags):
        signs.append(f"its MMSI country code {mid['mid']} belongs to {mid['country']}, but the lists give its flag "
                     f"as {countries(flags)}")
    if len(record["flag_history"]) >= FLAG_HOPS:
        signs.append(f"GUR records {len(record['flag_history'])} flags for it ({countries(record['flag_history'])})")
    if record["gur_flag_unknown"]:
        signs.append("GUR lists its current flag as unknown or false")
    mmsi = normalise_mmsi(mmsi)
    if mmsi and FILLER_MMSI.fullmatch(mmsi):
        signs.append(f"its MMSI {mmsi} looks made up: four zeros follow the country code, like the 610000036 the "
                     "tanker Blue used under a false Benin flag")
    return signs


def former_names(record: dict, ais_name=None) -> list[str]:
    """Listed names other than the current one (the AIS name when it is listed, else the most common caption)."""
    keys = [name_key(name) for name in record["names"]]
    current = name_key(ais_name) if name_key(ais_name) in keys else (keys[0] if keys else "")
    return [name for name, key in zip(record["names"], keys) if key != current]


# ---------------------------------------------------------------- storage

def version_date(version: str) -> str:
    """'20261015150305-hxm' -> '2026-10-15', the day OpenSanctions exported that version."""
    digits = re.match(r"(\d{4})(\d{2})(\d{2})", version or "")
    if not digits:
        raise ValueError(f"unexpected OpenSanctions version {version!r}")
    return "-".join(digits.groups())


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _write_json(path: Path, value) -> None:
    _write_atomic(path, (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def _http_get(url: str, limit: int, timeout: float = 60) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to fetch {url}")
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"redirected to an unexpected address: {response.geturl()}")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url} is larger than {limit // (1024 * 1024)} MB")
    return data


def _snapshot_dir(root: Path) -> Path:
    return Path(root) / "snapshots"


def read_state(root=DEFAULT_DIR) -> dict:
    return _read_json(Path(root) / "state.json", {})


def read_history(root=DEFAULT_DIR) -> dict:
    return _read_json(Path(root) / "history.json", {})


def _prune(root: Path, keep: int) -> None:
    files = sorted(_snapshot_dir(root).glob("maritime-*.csv.gz"))
    for path in files[:-keep] if keep > 0 else []:
        path.unlink()


def update(root=DEFAULT_DIR, *, now: datetime | None = None, force: bool = False, transport=None,
           min_vessels: int = MIN_VESSELS) -> dict:
    """Check OpenSanctions at most once per UTC day; download and keep a new version only when there is one.

    ``transport(url, limit) -> bytes`` replaces HTTP in tests. A broken or
    suspiciously small file is refused and the previous copy stays in use.
    """
    root = Path(root)
    get = transport or _http_get
    now = now or datetime.now(timezone.utc)
    state = read_state(root)
    latest = state.get("latest") or {}
    have = latest.get("file") and (_snapshot_dir(root) / latest["file"]).is_file()
    if have and not force and state.get("checked_date") == now.date().isoformat():
        return {"action": "skipped", "reason": "already checked today", "latest": latest}
    index = json.loads(get(INDEX_URL, MAX_JSON_BYTES))
    version = str(index.get("version") or "")
    day = version_date(version)
    resource = next((item for item in index.get("resources") or [] if item.get("name") == "maritime.csv"), None)
    url = (resource or {}).get("url") or VERSION_URL.format(version=version)
    checked = {"checked_date": now.date().isoformat(), "checked_utc": now.isoformat(timespec="seconds")}
    if have and latest.get("version") == version and not force:
        _write_json(root / "state.json", {**state, **checked})
        return {"action": "unchanged", "latest": latest}
    raw = get(url, MAX_CSV_BYTES)
    raw = raw.encode("utf-8") if isinstance(raw, str) else raw
    watch = parse(raw)
    vessels = watch.stats()["vessels"]
    if vessels < min_vessels:
        raise ValueError(f"refusing a list with only {vessels} vessels (expected at least {min_vessels}); "
                         "the previous copy stays in use")
    name = f"maritime-{day}-{version}.csv.gz"
    if not re.fullmatch(r"maritime-[0-9-]+-[0-9A-Za-z-]+\.csv\.gz", name):
        raise ValueError(f"unexpected OpenSanctions version {version!r}")
    _write_atomic(_snapshot_dir(root) / name, gzip.compress(raw))
    history = add_to_history(read_history(root), watch, version, day)
    _write_json(root / "history.json", history)
    latest = {"version": version, "date": day, "file": name, "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
              "bytes": len(raw), "fetched_utc": now.isoformat(timespec="seconds"), **watch.stats()}
    _write_json(root / "state.json", {**state, **checked, "latest": latest, "source": SOURCE_PAGE,
                                      "licence": LICENCE, "credit": CREDIT})
    _prune(root, KEEP_SNAPSHOTS)
    _cache.clear()
    return {"action": "downloaded", "latest": latest}


def backfill(root=DEFAULT_DIR, *, every_days: int = 7, transport=None, min_vessels: int = MIN_VESSELS,
             limit: int = 20) -> list[str]:
    """Add older OpenSanctions versions, about one per ``every_days``, to the history (no copies are kept).

    So "on the list since" can reach back about three months instead of
    starting at the first daily download. Returns the versions added.
    """
    root = Path(root)
    get = transport or _http_get
    items = json.loads(get(VERSIONS_URL, MAX_JSON_BYTES)).get("items") or []
    history = read_history(root)
    known = {item["version"] for item in history.get("versions") or []}
    chosen, last = [], None
    for version in sorted(items):
        day = date.fromisoformat(version_date(version))
        if last is None or day - last >= timedelta(days=every_days):
            chosen.append(version)
            last = day
    if items and max(items) not in chosen:
        chosen.append(max(items))
    added = []
    for version in [version for version in chosen if version not in known][:limit]:
        watch = parse(get(VERSION_URL.format(version=version), MAX_CSV_BYTES))
        if watch.stats()["vessels"] < min_vessels:
            raise ValueError(f"version {version} has only {watch.stats()['vessels']} vessels; stopped")
        add_to_history(history, watch, version, version_date(version))
        _write_json(root / "history.json", history)
        added.append(version)
    _cache.clear()
    return added


_cache: dict = {}
_cache_lock = threading.Lock()


def load(root=None) -> WatchList | None:
    """The newest kept list copy with its history, or None when nothing was downloaded yet. Works offline."""
    root = Path(root or os.environ.get("ARGUS_WATCHLIST_DIR") or DEFAULT_DIR)
    state = read_state(root)
    latest = state.get("latest") or {}
    name = str(latest.get("file") or "")
    path = _snapshot_dir(root) / name if name and Path(name).name == name else None
    if path is None or not path.is_file():
        return None
    history_path = root / "history.json"
    stamp = (str(path), path.stat().st_mtime_ns, history_path.stat().st_mtime_ns if history_path.exists() else 0)
    with _cache_lock:
        if _cache.get("stamp") == stamp:
            return _cache["watch"]
    watch = parse(gzip.decompress(path.read_bytes()), meta=latest, history=read_history(root))
    with _cache_lock:
        _cache.update(stamp=stamp, watch=watch)
    return watch


# ---------------------------------------------------------------- live scan and command line

def scan_vessels(vessels: list[dict], watch: WatchList) -> dict:
    """Run the watchlist detector over received AIS contacts (e.g. the live feed) and group what it finds."""
    from argus.detectors import watchlist as detector
    from argus.levels import assess

    report = {"contacts": len(vessels), "list_date": watch.meta.get("date"), "credit": CREDIT,
              "confirmed": [], "suspected": [], "noted": [], "ambiguous": [], "delisted": [], "beacons": [],
              "number_notes": []}
    for vessel in vessels:
        contact = {"mmsi": vessel.get("mmsi"), "name": vessel.get("name"), "label": "real", "track": [],
                   "lat": vessel.get("lat"), "lon": vessel.get("lon")}
        for finding in detector.detect(contact, {"watchlist": watch}):
            related = finding["related"]
            kind = related.get("kind")
            entry = {"mmsi": finding["mmsi"], "ais_name": vessel.get("name"), "position": finding["position"],
                     "received_utc": vessel.get("received_utc"), "reasons": finding["reasons"], **related}
            if finding["obs"]:
                alone = assess(finding["obs"])
                entry["list_only_level"] = f"{alone['level_name']}: {alone['basis']}"
            group = {"listed": related.get("tier"), "beacon": "beacons", "number": "number_notes"}.get(kind, kind)
            report.setdefault(group, []).append(entry)
    for group in ("confirmed", "suspected", "noted"):
        report[group].sort(key=lambda item: item.get("received_utc") or "", reverse=True)
    return report


def _fetch_live(url: str) -> list[dict]:
    envelope = json.loads(_http_get(url, MAX_JSON_BYTES))
    vessels = envelope.get("vessels") if isinstance(envelope, dict) else None
    if not isinstance(vessels, list):
        raise ValueError("the live feed did not return a vessel list")
    return [vessel for vessel in vessels if isinstance(vessel, dict)]


def _print_scan(report: dict, show_noted: bool) -> None:
    print(f"{report['contacts']} AIS contacts checked against the list of {report['list_date']} ({report['credit']}).")
    for group, title in (("confirmed", "On a sanctions list"), ("suspected", "GUR shadow fleet, not sanctioned"),
                         ("ambiguous", "MMSI shared by several listed vessels"), ("delisted", "Formerly listed"),
                         ("beacons", "Possible distress beacons"), ("number_notes", "Invalid MMSI country code")):
        entries = report.get(group) or []
        print(f"\n{title}: {len(entries)}")
        for entry in entries:
            where = entry["position"]
            place = f" at {where[0]:.2f}, {where[1]:.2f}" if where else ""
            seen = f" last seen {entry['received_utc'][:16]}Z" if entry.get("received_utc") else ""
            level = f"  [{entry['list_only_level']} from list cues alone]" if entry.get("list_only_level") else ""
            print(f"  {entry['mmsi']} {entry.get('ais_name') or '(no name)'}{place}{seen}{level}")
            for reason in entry["reasons"]:
                print(f"      {reason}")
    noted = report.get("noted") or []
    print(f"\nInformation only (port-state detentions, GUR's other vessels, RUSI): {len(noted)}")
    for entry in noted if show_noted else []:
        print(f"  {entry['mmsi']} {entry.get('ais_name') or '(no name)'}: {entry['reasons'][0]}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=None, help="list folder (default data/watchlist)")
    commands = parser.add_subparsers(dest="command", required=True)
    updating = commands.add_parser("update", help="check OpenSanctions (at most once a day) and keep a new version")
    updating.add_argument("--force", action="store_true", help="check again today")
    backfilling = commands.add_parser("backfill", help="seed the history from older list versions")
    backfilling.add_argument("--every-days", type=int, default=7)
    commands.add_parser("status", help="show the kept list copy")
    checking = commands.add_parser("check", help="look up one MMSI or IMO")
    checking.add_argument("mmsi", nargs="?")
    checking.add_argument("--imo")
    checking.add_argument("--name", help="the AIS name, used only to pick between records and to warn")
    scanning = commands.add_parser("scan-live", help="check every contact in the team's live AIS feed")
    scanning.add_argument("--feed", default=LIVE_FEED)
    scanning.add_argument("--file", type=Path, help="a saved /api/v1/vessels response instead of the feed")
    scanning.add_argument("--all", action="store_true", help="also list the information-only matches")
    scanning.add_argument("--output", type=Path, help="write the report as JSON")
    args = parser.parse_args(argv)
    root = args.dir or Path(os.environ.get("ARGUS_WATCHLIST_DIR") or DEFAULT_DIR)
    try:
        if args.command == "update":
            result = update(root, force=args.force)
            latest = result["latest"]
            print(f"{result['action']}: OpenSanctions maritime {latest.get('version')} ({latest.get('date')}), "
                  f"{latest.get('vessels', '?')} vessels; {CREDIT}")
            return 0
        if args.command == "backfill":
            added = backfill(root, every_days=args.every_days)
            print(f"added {len(added)} older versions to the history: {', '.join(added) or 'none'}")
            return 0
        watch = load(root)
        if watch is None:
            print("No list copy yet: run  python -m argus.watchlist_data update", file=sys.stderr)
            return 1
        if args.command == "status":
            print(json.dumps({**watch.meta, "oldest_version_in_history": watch.oldest_version_date(),
                              "versions_in_history": len(watch.history.get("versions") or []),
                              "stats": watch.stats(), "credit": CREDIT}, indent=1))
            return 0
        if args.command == "check":
            from argus.detectors import watchlist as detector
            found = detector.detect({"mmsi": args.mmsi, "imo": args.imo, "name": args.name, "label": "real",
                                     "track": []}, {"watchlist": watch})
            if not found:
                print("Not on the list (matched by MMSI or IMO only, never by name).")
            for finding in found:
                print("\n".join(finding["reasons"]))
                print(json.dumps(finding["obs"]))
            return 0
        vessels = (json.loads(args.file.read_text(encoding="utf-8"))["vessels"] if args.file
                   else _fetch_live(args.feed))
        report = scan_vessels(vessels, watch)
        if args.output:
            _write_json(args.output, report)
        _print_scan(report, args.all)
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"watchlist: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
