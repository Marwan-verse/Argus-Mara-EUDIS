"""Bounded, public AIS state for the optional shared live service.

All calls belong on one asyncio event loop. ``ingest`` accepts recorder-schema
rows; it never retains raw messages. ``snapshot`` returns a JSON-safe dictionary
with ``vessels`` and ``meta``. Ages use the recorder's UTC receive time, not a
predicted ship position or an AIS second-of-minute timestamp.
"""

from collections import OrderedDict
from datetime import datetime, timezone
import json
import math


POSITION_TYPES = frozenset({"PositionReport", "StandardClassBPositionReport",
                            "ExtendedClassBPositionReport"})
STATIC_TYPES = frozenset({"ShipStaticData", "StaticDataReport"})
LABELS = frozenset({"real", "simulated", "fictional", "reconstructed", "assumption"})


def _utc(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None


def _number(value, lower, upper, inclusive=False):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < lower or (value > upper if inclusive else value >= upper):
        return None
    return value


def _integer(value, lower, upper):
    number = _number(value, lower, upper, inclusive=True)
    return int(number) if number is not None and number.is_integer() else None


def _name(value):
    if not isinstance(value, str):
        return None
    value = "".join(char for char in value if char.isprintable()).strip(" @")[:64]
    return value or None


def _metadata(row):
    """Read only explicit metadata fields; raw content never enters public state."""
    name, ship_type, length = _name(row.get("ship_name")), None, None
    try:
        raw = row.get("raw")
        message = json.loads(raw) if isinstance(raw, str) and len(raw) <= 65_536 else {}
        body = (message.get("Message") or {}).get(row.get("msg_type")) or {}
        if not isinstance(body, dict):
            return name, ship_type, length
        parts = [body] + [body[key] for key in ("ReportA", "ReportB")
                          if isinstance(body.get(key), dict)]
        for part in parts:
            name = _name(part.get("Name")) or name
            kind = _integer(part.get("Type", part.get("ShipType")), 1, 99)
            if kind is not None:
                ship_type = kind
            dimension = part.get("Dimension")
            if isinstance(dimension, dict):
                a = _number(dimension.get("A"), 0, 511, inclusive=True)
                b = _number(dimension.get("B"), 0, 511, inclusive=True)
                if a is not None and b is not None and a + b > 0:
                    length = a + b
    except (ValueError, TypeError, AttributeError, RecursionError):
        pass
    return name, ship_type, length


def _destination(row):
    """Message 5 destination is declared text, never an inferred port or route."""
    if row.get("msg_type") != "ShipStaticData":
        return False, None
    try:
        raw = row.get("raw")
        message = json.loads(raw) if isinstance(raw, str) and len(raw) <= 65_536 else {}
        body = (message.get("Message") or {}).get("ShipStaticData") or {}
        if isinstance(body, dict) and isinstance(body.get("Destination"), str):
            return True, _name(body["Destination"][:20])
    except (ValueError, TypeError, AttributeError, RecursionError):
        pass
    return False, None


class LiveState:
    """Latest observed position and identity, bounded by ``max_vessels``.

    Static observations can update identity but never position or position age.
    Older positions cannot overwrite newer fixes. Eviction discards public cache
    entries only; the private durable archive remains independent.
    """

    def __init__(self, max_vessels=5000, stale_seconds=900):
        if not isinstance(max_vessels, int) or isinstance(max_vessels, bool) or max_vessels < 1:
            raise ValueError("max_vessels must be a positive integer")
        if not math.isfinite(stale_seconds) or stale_seconds < 0:
            raise ValueError("stale_seconds must be finite and nonnegative")
        self.max_vessels = max_vessels
        self.stale_seconds = stale_seconds
        self._vessels = OrderedDict()
        self.accepted_rows = self.rejected_rows = self.evicted_contacts = 0

    def ingest(self, row):
        """Return a public upsert, or ``None`` for invalid/older/unhandled rows."""
        kind = row.get("msg_type")
        received = _utc(row.get("recv_utc"))
        mmsi = _integer(row.get("mmsi"), 1, 999_999_999)
        if received is None or mmsi is None or kind not in POSITION_TYPES | STATIC_TYPES:
            self.rejected_rows += 1
            return None
        if kind in POSITION_TYPES:
            lat = _number(row.get("lat"), -90, 90, inclusive=True)
            lon = _number(row.get("lon"), -180, 180, inclusive=True)
            if lat is None or lon is None:
                self.rejected_rows += 1
                return None
        self.accepted_rows += 1
        vessel = self._vessels.get(mmsi)
        if vessel is None:
            if len(self._vessels) >= self.max_vessels:
                self._vessels.popitem(last=False)
                self.evicted_contacts += 1
            vessel = {"mmsi": mmsi, "name": None, "ship_type": None, "ais_length_m": None,
                      "destination": None, "_destination": None,
                      "lat": None, "lon": None, "sog_kn": None, "cog_deg": None,
                      "heading_deg": None, "nav_status": None, "_position": None,
                      "_metadata": None, "_last": received, "label": "real"}
            self._vessels[mmsi] = vessel
        changed = False
        if kind in POSITION_TYPES and (vessel["_position"] is None or received >= vessel["_position"]):
            vessel.update(lat=lat, lon=lon, sog_kn=_number(row.get("sog"), 0, 102.3),
                          cog_deg=_number(row.get("cog"), 0, 360),
                          heading_deg=_integer(row.get("heading"), 0, 359),
                          nav_status=_integer(row.get("nav_status"), 0, 14), _position=received)
            changed = True
        name, ship_type, length = _metadata(row)
        if (name is not None or ship_type is not None or length is not None) and (
                vessel["_metadata"] is None or received >= vessel["_metadata"]):
            for field, value in (("name", name), ("ship_type", ship_type), ("ais_length_m", length)):
                if value is not None:
                    vessel[field] = value
            vessel["_metadata"] = received
            changed = True
        declared, destination = _destination(row)
        if declared and (vessel["_destination"] is None or received >= vessel["_destination"]):
            vessel["destination"] = destination
            vessel["_destination"] = received
            changed = True
        if changed:
            label = row.get("label", "real")
            vessel["label"] = label if isinstance(label, str) and label in LABELS else "real"
            vessel["_last"] = max(vessel["_last"], received)
            self._vessels.move_to_end(mmsi)
            return self._public(vessel, datetime.now(timezone.utc))
        return None

    def _public(self, vessel, now):
        age = max(0.0, (now - vessel["_position"]).total_seconds()) if vessel["_position"] else None
        return {**{key: value for key, value in vessel.items() if not key.startswith("_")},
                "mmsi": str(vessel["mmsi"]),
                "received_utc": _iso(vessel["_position"]),
                "metadata_received_utc": _iso(vessel["_metadata"]),
                "destination_received_utc": _iso(vessel["_destination"]),
                "age_s": age, "stale": age is None or age > self.stale_seconds}

    @property
    def contact_count(self):
        """Count contacts without constructing or exposing public observations."""
        return len(self._vessels)

    def contact_ids(self):
        """Return an isolated set of public IDs without calculating ages/fields."""
        return {str(mmsi) for mmsi in self._vessels}

    def snapshot(self, now=None):
        """Return isolated JSON-safe public dictionaries and cache counters."""
        now = datetime.now(timezone.utc) if now is None else _utc(now)
        if now is None:
            raise ValueError("snapshot time must be timezone-aware")
        vessels = [self._public(vessel, now) for vessel in self._vessels.values()]
        positions = [vessel for vessel in vessels if vessel["received_utc"] is not None]
        return {"vessels": vessels, "meta": {
            "contacts": len(vessels), "position_contacts": len(positions),
            "stale_contacts": sum(vessel["stale"] for vessel in positions),
            "accepted_rows": self.accepted_rows, "rejected_rows": self.rejected_rows,
            "evicted_contacts": self.evicted_contacts}}
