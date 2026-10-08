"""Import GFW's per-contact CSV, or request a separate 4Wings grid report.

All commands use the Python standard library. Run with --help for examples.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import struct
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from argus.space import coordinates, finite, timestamp
from argus.provenance import now_utc, sha256, time_range


ARCHIVE_URL = "https://ndownloader.figshare.com/files/43882980"
ARTICLE_URL = "https://doi.org/10.6084/m9.figshare.24309475.v4"
PREFIX_BYTES = 10 * 1024 * 1024
EXAMPLE_SCENES = {
    "S1A_IW_GRDH_1SDV_20210905T180657_20210905T180722_039550_04ACA6_6EB4",
    "S1A_IW_GRDH_1SDV_20181113T181420_20181113T181445_024573_02B292_EE59",
}
IRISH_BBOX = (-18.0, 49.0, -4.5, 57.5)  # west, south, east, north; includes neighbouring waters
CONTACT_COLUMNS = {"scene_id", "timestamp", "lat", "lon", "length_m", "mmsi", "matched_category"}


def validate_columns(columns):
    if not CONTACT_COLUMNS.issubset(columns):
        raise ValueError("expected a per-contact GFW CSV with " + ", ".join(sorted(CONTACT_COLUMNS))
                         + "; 4Wings gridded reports cannot be used as individual contacts")


def bbox_values(values):
    west, south, east, north = [finite(v, "bbox") for v in values]
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be WEST SOUTH EAST NORTH in WGS84")
    return west, south, east, north


def normalise(row):
    """Published industrial_vessels CSV schema; absent AIS identity stays null."""
    validate_columns(row)
    lat, lon = coordinates(row)
    ts = datetime.fromtimestamp(timestamp(row["timestamp"]), timezone.utc).isoformat().replace("+00:00", "Z")
    category = row["matched_category"].strip()
    if category not in {"unmatched", "matched_fishing", "matched_nonfishing", "matched_unknown"}:
        raise ValueError(f"unknown GFW match category: {category!r}")
    mmsi_text = row["mmsi"].strip()
    mmsi = None
    if category != "unmatched":
        if not (mmsi_text.isdigit() and len(mmsi_text) == 9 and int(mmsi_text) != 0):
            raise ValueError("a matched contact must have a 9-digit MMSI")
        mmsi = int(mmsi_text)
    length = finite(row["length_m"], "length_m") if row["length_m"].strip() else None
    if length is not None and length <= 0:
        length = None
    if not row["scene_id"].strip():
        raise ValueError("a contact must have a source scene_id")
    return {"ts": ts, "lat": lat, "lon": lon, "length_m": length,
            "source": "gfw", "scene_id": row["scene_id"], "matched_mmsi": mmsi,
            "label": "real", "provider_match_category": category,
            "matching_score": finite(row["matching_score"], "matching_score") if row.get("matching_score") else None,
            "fishing_score": finite(row["fishing_score"], "fishing_score") if row.get("fishing_score") else None,
            "presence_score": finite(row["presence_score"], "presence_score") if row.get("presence_score") else None}


def date_bound(value):
    if value is None:
        return None
    # Calendar dates are explicitly midnight UTC; timestamp inputs need an offset.
    return timestamp(value + "T00:00:00Z" if len(value) == 10 else value)


def import_rows(rows, bbox=IRISH_BBOX, unmatched_only=False, start=None, end=None):
    west, south, east, north = bbox_values(bbox)
    first, last = date_bound(start), date_bound(end)
    if first is not None and last is not None and first >= last:
        raise ValueError("start must precede end (end is exclusive)")
    detections, seen, duplicates, input_rows = [], {}, 0, 0
    if isinstance(rows, csv.DictReader):
        validate_columns(rows.fieldnames or [])
    for line, row in enumerate(rows, 2):
        try:
            input_rows += 1
            validate_columns(row)
            lat, lon = coordinates(row)
            if not (south <= lat <= north and west <= lon <= east):
                continue
            detection = normalise(row)
            when = timestamp(detection["ts"])
            if (first is not None and when < first) or (last is not None and when >= last):
                continue
            if unmatched_only and detection["provider_match_category"] != "unmatched":
                continue
            # Stable identity across filters; do not turn the row number into an ID.
            identity = (detection["scene_id"], detection["ts"], detection["lat"], detection["lon"])
            if identity in seen:
                if seen[identity] != detection:
                    raise ValueError("conflicting records for the same scene/time/position")
                duplicates += 1
                continue
            seen[identity] = dict(detection)
            digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
            detection["id"] = "gfw-" + digest[:20]
            detections.append(detection)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"CSV row {line}: {exc}") from exc
    return {"name": "GFW historical radar contacts in the Irish-region bounding box",
            "label": "real", "bbox_west_south_east_north": list(bbox), "vessels": [],
            "caveat": "Unmatched means no AIS association in GFW's dataset; it does not establish deliberate AIS shutdown.",
            "source_schema": "gfw-analysis-csv-v1",
            "selection": {"start": start, "end_exclusive": end, "unmatched_only": unmatched_only,
                          "input_rows": input_rows, "duplicates_removed": duplicates,
                          "complete_regional_census": False},
            "coverage": time_range(detections),
            "detections": detections}


def import_file(path, bbox=IRISH_BBOX, unmatched_only=False, start=None, end=None):
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv") and not n.startswith("__MACOSX/")]
            if len(names) != 1:
                raise ValueError("ZIP must contain one per-contact CSV; extract and import monthly files separately")
            with archive.open(names[0]) as member, io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream:
                result = import_rows(csv.DictReader(stream), bbox, unmatched_only, start, end)
    else:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            result = import_rows(csv.DictReader(stream), bbox, unmatched_only, start, end)
    result["source_file"] = path.name
    result["source_sha256"] = sha256(path)
    return result


def public_example():
    """Read a bounded public ZIP prefix, keeping only complete CSV records.

    The archive is 1.7 GB; our two pinned source scenes occur in the first 10 MB.
    This deliberately avoids treating a truncated ZIP as a complete archive.
    """
    request = urllib.request.Request(ARCHIVE_URL, headers={"Range": f"bytes=0-{PREFIX_BYTES - 1}"})
    with urllib.request.urlopen(request, timeout=45) as response:
        prefix = response.read(PREFIX_BYTES)
    if prefix[:4] != b"PK\x03\x04" or len(prefix) < 30:
        raise ValueError("public archive is not a ZIP local-file prefix")
    header = struct.unpack("<4s5H3I2H", prefix[:30])
    method, name_len, extra_len = header[3], header[-2], header[-1]
    name = prefix[30:30 + name_len].decode()
    if method != 8 or name != "industrial_vessels_v20240102.csv":
        raise ValueError("public archive layout changed; download the CSV and use import instead")
    decoder = zlib.decompressobj(-15)
    text = decoder.decompress(prefix[30 + name_len + extra_len:]).decode("utf-8")
    text = text[:text.rfind("\n") + 1]  # discard incomplete last record
    rows = [r for r in csv.DictReader(io.StringIO(text))
            if r["scene_id"] in EXAMPLE_SCENES and r["matched_category"] == "unmatched"
            and 49 <= float(r["lat"]) <= 57.5 and -18 <= float(r["lon"]) <= -4.5]
    if not EXAMPLE_SCENES.issubset({r["scene_id"] for r in rows}):
        raise ValueError("pinned contacts missing from prefix; public archive layout may have changed")
    result = import_rows(rows, unmatched_only=True)
    result["provenance"] = {"dataset": "industrial_vessels_v20240102.csv", "article": ARTICLE_URL,
                            "download_url": ARCHIVE_URL, "license": "CC BY 4.0",
                            "attribution": "Paolo, Kroodsma, Davis and Hochberg (2024), Global Fishing Watch",
                            "bytes_read": len(prefix), "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
                            "selection": "Unmatched contacts from two pinned scenes inside the Irish-region bounding box; not a regional census."}
    result["provenance"]["retrieved_at_utc"] = now_utc()
    return result, rows


def report_request(start, end, bbox=IRISH_BBOX, unmatched_only=True):
    # ISO calendar dates keep query values predictable and make the range explicit.
    if datetime.strptime(start, "%Y-%m-%d") >= datetime.strptime(end, "%Y-%m-%d"):
        raise ValueError("start date must precede end date")
    west, south, east, north = bbox_values(bbox)
    polygon = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
               "geometry": {"type": "Polygon", "coordinates": [[[west, south], [east, south],
                           [east, north], [west, north], [west, south]]]}}]}
    params = {"spatial-resolution": "HIGH", "temporal-resolution": "DAILY",
              "datasets[0]": "public-global-sar-presence:latest", "date-range": f"{start},{end}",
              "format": "JSON", "spatial-aggregation": "false"}
    if unmatched_only:
        params["filters[0]"] = "matched='false'"
    return {"url": "https://gateway.api.globalfishingwatch.org/v3/4wings/report?" + urllib.parse.urlencode(params),
            "body": {"geojson": polygon}}


def fetch_report(request, output):
    token = os.environ.get("GFW_API_TOKEN", "").strip()
    if not token:
        raise ValueError("set GFW_API_TOKEN in your environment; public-example needs no token")
    req = urllib.request.Request(request["url"], data=json.dumps(request["body"]).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        content = response.read()
    # The API may deliver a ZIP with caveats, rather than a bare JSON document.
    output = output.with_suffix(".zip" if content.startswith(b"PK") else ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return output


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="import per-contact CSV or single-CSV ZIP")
    importer.add_argument("input", type=Path)
    importer.add_argument("--output", type=Path, default=Path("data/sar/gfw-contacts.json"))
    importer.add_argument("--bbox", nargs=4, type=float, default=IRISH_BBOX, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    importer.add_argument("--unmatched-only", action="store_true")
    importer.add_argument("--start", help="inclusive UTC timestamp or YYYY-MM-DD")
    importer.add_argument("--end", help="exclusive UTC timestamp or YYYY-MM-DD")
    example = commands.add_parser("public-example", help="retrieve pinned historical contacts without an account")
    example.add_argument("--output", type=Path, default=Path("data/sar/gfw-example.json"))
    example.add_argument("--raw-csv", type=Path, help="also save the original source rows")
    for command in ("request", "fetch"):
        report = commands.add_parser(command, help="prepare or fetch an aggregate 4Wings report")
        report.add_argument("--start", required=True, help="YYYY-MM-DD")
        report.add_argument("--end", required=True, help="YYYY-MM-DD")
        report.add_argument("--bbox", nargs=4, type=float, default=IRISH_BBOX)
        report.add_argument("--all-contacts", action="store_true", help="include matched detections too")
        report.add_argument("--output", type=Path, default=Path(f"data/sar/gfw-{command}.json"))
    args = parser.parse_args()
    try:
        if args.command == "import":
            if args.input.resolve() == args.output.resolve():
                raise ValueError("output must differ from the source CSV")
            result = import_file(args.input, args.bbox, args.unmatched_only, args.start, args.end)
            write_json(args.output, result)
        elif args.command == "public-example":
            if args.raw_csv and args.raw_csv.resolve() == args.output.resolve():
                raise ValueError("raw CSV and JSON output paths must differ")
            result, rows = public_example()
            write_json(args.output, result)
            if args.raw_csv:
                args.raw_csv.parent.mkdir(parents=True, exist_ok=True)
                with args.raw_csv.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
        else:
            request = report_request(args.start, args.end, args.bbox, not args.all_contacts)
            if args.command == "request":
                write_json(args.output, request)
            else:
                args.output = fetch_report(request, args.output)
        print(f"Saved {args.output}")
    except urllib.error.HTTPError as exc:
        parser.exit(1, f"GFW HTTP {exc.code}; check token, date range and API access. No response secrets are logged.\n")
    except (ValueError, KeyError, TypeError, OSError, zlib.error) as exc:
        parser.exit(1, f"GFW import failed: {exc}\n")


if __name__ == "__main__":
    main()
