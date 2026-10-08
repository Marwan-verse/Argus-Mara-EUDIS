"""Normalize Data's AIS CSV, or the existing recorder's CSV/Parquet export.

No raw messages or credentials enter the handoff. Parquet optionally uses the
recorder's existing pyarrow dependency; CSV needs only Python's standard library.
"""

import argparse
import csv
import re
from pathlib import Path

from argus.provenance import LABELS, source_record, time_range, utc, write_json
from argus.space import coordinates, finite, timestamp


POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}


def mmsi_value(value):
    value = str(value).strip()
    if not value.isdigit() or len(value) != 9 or int(value) == 0:
        raise ValueError("MMSI must be nine digits and nonzero")
    return int(value)


def motion(value, name, limit):
    if value is None or value == "":
        return None
    number = finite(value, name)
    if number == limit:
        return None  # AIS unavailable-value sentinels.
    if not 0 <= number < limit:
        raise ValueError(f"{name} outside the AIS range")
    return number


def normalise_rows(rows, label, schema="normalized"):
    if label not in LABELS:
        raise ValueError("an explicit provenance label is required")
    if schema not in {"normalized", "recorder"}:
        raise ValueError("schema must be normalized or recorder")
    vessels, seen, duplicates, skipped, receipt_times = {}, {}, 0, 0, 0
    for line, row in enumerate(rows, 2):
        try:
            if schema == "recorder" and row.get("msg_type") not in POSITION_TYPES:
                skipped += 1
                continue
            identity = mmsi_value(row["mmsi"])
            row_label = row.get("label") or label
            if row_label not in LABELS:
                raise ValueError("invalid point provenance label")
            raw_time = row.get("ts") if schema == "normalized" else row.get("time_utc")
            time_source = "observation_time"
            if schema == "recorder":
                if not raw_time:
                    raw_time, time_source = row.get("recv_utc"), "received_time_assumption"
                    receipt_times += 1
                # aisstream timestamps may append the literal zone name.
                raw_time = str(raw_time).removesuffix(" UTC")
                # aisstream also uses Go's timestamp layout with a space before
                # +0000 and nanosecond precision. Keep its explicit UTC offset.
                raw_time = re.sub(r"\s+([+-]\d{2})(\d{2})$", r"\1:\2", raw_time)
            if hasattr(raw_time, "isoformat"):
                raw_time = raw_time.isoformat()
            lat, lon = coordinates(row)
            point = {"ts": utc(raw_time), "lat": lat, "lon": lon,
                     "sog_kn": motion(row.get("sog_kn" if schema == "normalized" else "sog"), "sog_kn", 102.3),
                     "cog_deg": motion(row.get("cog_deg" if schema == "normalized" else "cog"), "cog_deg", 360),
                     "label": row_label, "timestamp_source": time_source}
            dimension = row.get("ais_length_m")
            length = finite(dimension, "ais_length_m") if dimension not in (None, "") else None
            if length is not None and length <= 0:
                raise ValueError("ais_length_m must be positive when supplied")
            key = (identity, point["ts"])
            record = (point, length)
            if key in seen:
                if seen[key] != record:
                    raise ValueError("conflicting AIS fixes for the same MMSI and UTC time")
                duplicates += 1
                continue
            seen[key] = record
            vessel = vessels.setdefault(identity, {"mmsi": identity,
                "name": row.get("name") or row.get("ship_name") or "Identity name unavailable",
                "label": row_label, "ais_length_m": None, "dimension_history": [], "track": []})
            if vessel["label"] != row_label:
                raise ValueError("cannot combine different provenance labels for one MMSI")
            vessel["track"].append(point)
            if length is not None:
                vessel["dimension_history"].append({"ts": point["ts"], "ais_length_m": length,
                                                     "label": row_label})
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"AIS row {line}: {exc}") from exc
    for vessel in vessels.values():
        vessel["track"].sort(key=lambda point: timestamp(point["ts"]))
        vessel["dimension_history"].sort(key=lambda item: timestamp(item["ts"]))
        if vessel["dimension_history"]:
            vessel["ais_length_m"] = vessel["dimension_history"][-1]["ais_length_m"]
    points = [point for vessel in vessels.values() for point in vessel["track"]]
    labels = {vessel["label"] for vessel in vessels.values()}
    pack_label = next(iter(labels)) if len(labels) == 1 else "assumption" if labels else label
    return {"name": "Normalized AIS handoff", "label": pack_label,
            "provenance_labels": sorted(labels),
            "source_schema": "argus-ais-csv-v1" if schema == "normalized" else "argus-recorder-v1",
            "vessels": sorted(vessels.values(), key=lambda vessel: vessel["mmsi"]),
            "coverage": time_range(points),
            "quality": {"duplicates_removed": duplicates, "nonposition_rows_skipped": skipped,
                        "receipt_time_fixes": receipt_times},
            "caveat": "AIS reception gaps are not proof of deliberate shutdown. Received-time fixes use an assumed observation time."}


def import_file(path, label, schema="normalized"):
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        if schema != "recorder":
            raise ValueError("Parquet supports the recorder schema only")
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ValueError("Parquet needs the recorder's pyarrow; use a CSV export for a dependency-free handoff") from exc
        # Explicit columns exclude raw messages and any future secret-bearing columns.
        rows = pq.read_table(path, columns=["mmsi", "msg_type", "ship_name", "lat", "lon",
                                          "sog", "cog", "time_utc", "recv_utc"]).to_pylist()
        result = normalise_rows(rows, label, schema)
    else:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            result = normalise_rows(csv.DictReader(stream), label, schema)
    result["source"] = source_record(path, "ais_input", result["label"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--label", required=True, choices=sorted(LABELS))
    parser.add_argument("--schema", choices=["normalized", "recorder"], default="normalized")
    parser.add_argument("--output", type=Path, default=Path("data/ais/handoff.json"))
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("output must differ from the input")
        result = import_file(args.input, args.label, args.schema)
        write_json(args.output, result)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"AIS import failed: {exc}\n")
    print(f"{len(result['vessels'])} vessels -> {args.output}")


if __name__ == "__main__":
    main()
