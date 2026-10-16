"""Read-only shared AIS client. No provider keys, Tk calls or archive downloads."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import queue
import threading
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

MAX_VESSELS = 5_000
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


def server_url(value: str) -> str:
    """Require HTTPS; permit plain HTTP only for loopback development."""
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
        raise ValueError("Enter a valid HTTPS server address.")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError("Enter a valid HTTPS server address.") from error
    if (not parts.hostname or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or "\\" in value
            or parts.scheme not in ("https", "http")):
        raise ValueError("Use an HTTPS address without credentials, query or fragment.")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Public servers must use HTTPS.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("The server port is invalid.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def utc_timestamp(value: object) -> float:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError("Observation timestamps must be UTC strings.")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError
        return stamp.timestamp()
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError("Observation timestamps must be valid UTC values.") from error


def _number(value: object, low: float, high: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def _mmsi(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 9 or not value.isascii()
            or not value.isdigit() or int(value) == 0):
        raise ValueError("Vessels must have valid decimal MMSIs.")
    # Providers often serialize an integer, losing the leading zeroes used by
    # shore stations. The display and removal IDs use the canonical nine digits.
    return value.zfill(9)


def _text(value: object, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError("Vessel particulars must be text or numeric codes.")
    return "".join(char for char in str(value) if char.isprintable())[:limit].strip()


def validate_envelope(payload: object) -> dict:
    """Validate the complete response before any caller replaces visible state."""
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1):
        raise ValueError("Unsupported live AIS schema.")
    sequence = payload.get("sequence")
    stream_id = payload.get("stream_id")
    if (not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0
            or not isinstance(stream_id, str) or not 1 <= len(stream_id) <= 128):
        raise ValueError("The stream cursor is invalid.")
    if "generated_utc" in payload:
        generated_s = utc_timestamp(payload["generated_utc"])
    else:
        generated_s = datetime.now(timezone.utc).timestamp()
    feed = payload.get("feed")
    if not isinstance(feed, dict) or not isinstance(feed.get("status"), str):
        raise ValueError("The feed status is missing.")
    clean_feed = {"status": _text(feed["status"], 64), "label": feed.get("label", "real")}
    if clean_feed["label"] not in ("real", "simulated"):
        raise ValueError("The feed provenance label is invalid.")
    stale_seconds = feed.get("stale_seconds", 900)
    if not _number(stale_seconds, 0, 365 * 86400):
        raise ValueError("The feed freshness interval is invalid.")
    clean_feed["stale_seconds"] = stale_seconds
    for key in ("last_received_utc", "last_position_utc"):
        value = feed.get(key)
        if value is not None:
            utc_timestamp(value)
        clean_feed[key] = value
    for key in ("messages", "position_messages", "vessels", "archive_files"):
        value = feed.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            clean_feed[key] = value
    snapshot = "vessels" in payload
    rows = payload.get("vessels" if snapshot else "upserts")
    removals = [] if snapshot else payload.get("removals", [])
    if (not isinstance(rows, list) or len(rows) > MAX_VESSELS
            or not isinstance(removals, list) or len(removals) > MAX_VESSELS):
        raise ValueError("The live response is too large or incomplete.")
    clean_rows, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid vessel record.")
        mmsi = _mmsi(row.get("mmsi"))
        if mmsi in seen:
            raise ValueError("Repeated MMSI in the live response.")
        seen.add(mmsi)
        has_position = row.get("lat") is not None or row.get("lon") is not None
        if has_position and (not _number(row.get("lat"), -90, 90) or not _number(row.get("lon"), -180, 180)):
            raise ValueError("Invalid received vessel coordinates.")
        received = row.get("received_utc")
        received_s = utc_timestamp(received) if received is not None else None
        if has_position != (received_s is not None):
            raise ValueError("Coordinates must include their received UTC timestamp.")
        metadata_received = row.get("metadata_received_utc")
        if metadata_received is not None:
            utc_timestamp(metadata_received)
        destination_received = row.get("destination_received_utc")
        if destination_received is not None:
            utc_timestamp(destination_received)
        for key, maximum in (("sog_kn", 102.2), ("cog_deg", 359.9)):
            if row.get(key) is not None and not _number(row[key], 0, maximum):
                raise ValueError("Invalid AIS speed or course.")
        nav_status = row.get('nav_status')
        if nav_status is not None and (type(nav_status) is not int or not 0 <= nav_status <= 14):
            raise ValueError('Invalid AIS navigation status.')
        length = row.get('ais_length_m')
        if length is not None and (not _number(length, 0, 1022) or length <= 0):
            raise ValueError('Invalid AIS declared length.')
        if row.get("label") not in ("real", "simulated"):
            raise ValueError("The AIS provenance label is missing.")
        clean = {
            "mmsi": mmsi, "name": _text(row.get("name"), 128) or "Name unavailable",
            "type": _text(row.get("ship_type", row.get("type")), 80) or "Unavailable",
            "lat": row.get("lat"), "lon": row.get("lon"), "sog_kn": row.get("sog_kn"),
            "cog_deg": row.get("cog_deg"), "received_utc": received,
            "received_s": received_s, "metadata_received_utc": metadata_received,
            "destination": _text(row.get("destination"), 20).strip(" @") or None,
            "destination_received_utc": destination_received,
            "nav_status": nav_status,
            "label": row["label"],
        }
        if 'ais_length_m' in row:
            clean['ais_length_m'] = length
        clean_rows.append(clean)
    clean_removals = [_mmsi(value) for value in removals]
    if seen.intersection(clean_removals) or len(set(clean_removals)) != len(clean_removals):
        raise ValueError("Conflicting vessel removals.")
    return {"schema_version": 1, "stream_id": stream_id, "sequence": sequence,
            "feed": clean_feed, "snapshot": snapshot, "rows": clean_rows,
            "removals": clean_removals, "generated_s": generated_s}


class LiveState:
    """Bounded latest observations. Updates and resets replace state atomically."""

    def __init__(self):
        self.stream_id = None
        self.sequence = 0
        self.vessels: dict[str, dict] = {}
        self.generated_s = datetime.now(timezone.utc).timestamp()
        self.feed = {"status": "connecting", "last_received_utc": None, "last_position_utc": None}

    def apply(self, payload: object) -> bool:
        envelope = validate_envelope(payload)
        snapshot = envelope["snapshot"]
        if not snapshot and envelope["stream_id"] != self.stream_id:
            raise ValueError("The live stream changed; request a fresh snapshot.")
        if (self.stream_id == envelope["stream_id"] and envelope["sequence"] < self.sequence):
            return False
        vessels = {} if snapshot else dict(self.vessels)
        for mmsi in envelope["removals"]:
            vessels.pop(mmsi, None)
        for row in envelope["rows"]:
            previous = vessels.get(row["mmsi"])
            if (previous is None or previous["received_s"] is None
                    or row["received_s"] is not None and row["received_s"] >= previous["received_s"]):
                vessels[row["mmsi"]] = row
            elif previous is not None:
                # New particulars can arrive without a new position; retain the
                # last observed fix while updating the name and type.
                vessels[row["mmsi"]] = {**previous, "name": row["name"], "type": row["type"],
                    **({'ais_length_m': row['ais_length_m']} if 'ais_length_m' in row else {}),
                    "metadata_received_utc": row["metadata_received_utc"],
                    "destination": row["destination"],
                    "destination_received_utc": row["destination_received_utc"]}
            if previous is not None and previous.get('metadata_received_utc') and (
                    not row.get('metadata_received_utc') or
                    utc_timestamp(previous['metadata_received_utc']) > utc_timestamp(row['metadata_received_utc'])):
                for key in ('name', 'type', 'metadata_received_utc', 'ais_length_m'):
                    if key in previous:
                        vessels[row['mmsi']][key] = previous[key]
            if previous is not None and previous.get("destination_received_utc") and (
                    row["destination_received_utc"] is None or
                    utc_timestamp(previous["destination_received_utc"]) > utc_timestamp(row["destination_received_utc"])):
                vessels[row["mmsi"]].update(destination=previous["destination"],
                    destination_received_utc=previous["destination_received_utc"])
        if len(vessels) > MAX_VESSELS:
            raise ValueError("The live vessel limit was exceeded.")
        self.vessels = vessels
        self.feed = envelope["feed"]
        self.generated_s = envelope["generated_s"]
        self.stream_id, self.sequence = envelope["stream_id"], envelope["sequence"]
        return True


def fetch_json(url: str) -> object:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ArgusMaraLive/1.0"})
    with urlopen(request, timeout=5) as response:
        # A public HTTPS endpoint must not redirect the client to plain HTTP.
        final = urlsplit(response.url)
        if urlsplit(url).scheme == "https" and final.scheme != "https":
            raise ValueError("The live endpoint must remain on HTTPS.")
        server_url(urlunsplit((final.scheme, final.netloc, final.path, "", "")))
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("The live response is too large.")
    return json.loads(raw)


class LivePoller:
    """Network worker writes a bounded queue; the UI thread alone applies events."""

    def __init__(self, address: str, interval: float = 2, fetch=fetch_json):
        self.address = server_url(address)
        self.interval = max(.1, interval)
        self.fetch = fetch
        self.events: queue.Queue = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="argus-live-client", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _emit(self, event):
        while not self._stop.is_set():
            try:
                self.events.put(event, timeout=.1)
                return
            except queue.Full:
                continue

    def _run(self):
        stream_id, sequence = None, 0
        while not self._stop.is_set():
            path = "/api/v1/vessels" if stream_id is None else "/api/v1/updates?" + urlencode({
                "stream_id": stream_id, "after": sequence})
            try:
                payload = self.fetch(self.address + path)
                envelope = validate_envelope(payload)
                if (not envelope["snapshot"] and envelope["stream_id"] != stream_id
                        or stream_id == envelope["stream_id"] and envelope["sequence"] < sequence):
                    raise ValueError("The server cursor changed.")
                self._emit(("data", payload))
                stream_id, sequence = envelope["stream_id"], envelope["sequence"]
            except Exception:
                # Do not expose transport exceptions, URLs or server error bodies.
                self._emit(("connection", "reconnecting"))
                stream_id, sequence = None, 0
            self._stop.wait(self.interval)
