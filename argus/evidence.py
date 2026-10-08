"""Build a local Space evidence pack from attributed contacts and optional AIS.

Default inputs are the two bundled historical GFW examples. No network is used.
Generated pages are standalone static HTML with local CSS/JS and inline maps.
"""

import argparse
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from argus.ingest.gfw import import_file as import_contacts
from argus.ingest.ais import mmsi_value, motion
from argus.provenance import LABELS, now_utc, sha256, source_record, time_range, utc, write_json
from argus.space import analyse, coordinates, finite, time_of, timestamp


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "space/examples"
UI = ROOT / "ui/space"


def escape(value):
    return html.escape(str(value), quote=True)


def source_link(url, text):
    parsed = urlsplit(str(url or ""))
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        return escape(text) + " (source link unavailable)"
    return f'<a href="{escape(url)}" rel="noreferrer">{escape(text)}</a>'


def load_ais(path):
    data = json.loads(Path(path).read_text())
    if data.get("source_schema") not in {"argus-ais-csv-v1", "argus-recorder-v1"}:
        raise ValueError("AIS must be normalized with python3 -m argus.ingest.ais")
    if data.get("label") not in LABELS:
        raise ValueError("AIS handoff needs a valid provenance label")
    vessels = []
    for item in data["vessels"]:
        if item.get("label") not in LABELS:
            raise ValueError("AIS vessel needs a provenance label")
        vessel = {"mmsi": mmsi_value(item["mmsi"]), "name": item.get("name", "Name unavailable"),
                  "label": item["label"], "ais_length_m": None, "dimension_history": [], "track": []}
        for point in item["track"]:
            lat, lon = coordinates(point)
            if point.get("label") != vessel["label"]:
                raise ValueError("AIS point and vessel provenance disagree")
            vessel["track"].append({"ts": utc(point["ts"]), "lat": lat, "lon": lon,
                "sog_kn": motion(point.get("sog_kn"), "sog_kn", 102.3),
                "cog_deg": motion(point.get("cog_deg"), "cog_deg", 360), "label": point["label"],
                "timestamp_source": point.get("timestamp_source", "observation_time")})
        for dimension in item.get("dimension_history", []):
            length = finite(dimension["ais_length_m"], "ais_length_m")
            if length <= 0 or dimension.get("label") != vessel["label"]:
                raise ValueError("invalid sourced AIS dimension")
            vessel["dimension_history"].append({"ts": utc(dimension["ts"]), "ais_length_m": length,
                                                 "label": dimension["label"]})
        vessels.append(vessel)
    return vessels


def load_scenes(paths):
    scenes = {}
    for path in paths:
        metadata = json.loads(Path(path).read_text())
        if metadata.get("label", "real") not in LABELS:
            raise ValueError("scene metadata needs a valid provenance label")
        product = metadata["product"]
        scene_id = product["Name"].removesuffix(".SAFE")
        if scene_id in scenes:
            raise ValueError("duplicate scene metadata")
        start, end = utc(product["ContentDate"]["Start"]), utc(product["ContentDate"]["End"])
        if timestamp(start) > timestamp(end):
            raise ValueError("scene acquisition start is after its end")
        footprint = product.get("GeoFootprint")
        if footprint:
            if footprint.get("type") != "Polygon" or not footprint.get("coordinates"):
                raise ValueError("scene footprint must be a GeoJSON Polygon")
            for ring in footprint["coordinates"]:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("scene footprint ring must be closed")
                for lon, lat in ring:
                    coordinates({"lat": lat, "lon": lon})
        scenes[scene_id] = {"scene_id": scene_id, "label": metadata.get("label", "real"),
            "source": metadata.get("source"), "catalogue_url": metadata.get("catalogue_url"),
            "acquisition_start_utc": start, "acquisition_end_utc": end,
            "catalogue_footprint_geojson": footprint,
            "processed_detection_footprint": None, "verified_on": metadata.get("verified_on"),
            "caveat": "Catalogue footprint only; GFW's processed detection area may be smaller. A preview is not a vessel measurement."}
    return scenes


def attach_scenes(sidecar, scenes):
    for contact in sidecar["detections"]:
        scene = scenes.get(contact.get("scene_id"))
        contact["scene_evidence"] = {"status": "available", **scene} if scene else {"status": "unavailable"}
        if not scene:
            contact["unavailable_reasons"].append("No local catalogue metadata for this scene.")
            continue
        if not contact.get("ts"):
            raise ValueError("scene evidence needs an absolute UTC contact time")
        if not timestamp(scene["acquisition_start_utc"]) <= timestamp(contact["ts"]) <= timestamp(scene["acquisition_end_utc"]):
            raise ValueError("contact acquisition is outside its supplied scene time")


def map_svg(contact):
    """A north-up schematic in lon/lat, not a navigation or measurement tool."""
    lat, lon = coordinates(contact)
    geometry = contact["scene_evidence"].get("catalogue_footprint_geojson")
    ring = geometry["coordinates"][0] if geometry else []
    points = ring + [[lon, lat]]
    west, east = min(p[0] for p in points) - .03, max(p[0] for p in points) + .03
    south, north = min(p[1] for p in points) - .03, max(p[1] for p in points) + .03
    def xy(point):
        return (30 + 540 * (point[0] - west) / (east - west), 30 + 240 * (north - point[1]) / (north - south))
    outline = " ".join(f"{x:.2f},{y:.2f}" for x, y in map(xy, ring))
    x, y = xy([lon, lat])
    polygon = f'<polygon points="{outline}" class="footprint" />' if ring else ""
    return ('<svg viewBox="0 0 600 310" role="img" aria-label="Contact position and available catalogue footprint">'
            '<title>Contact position and catalogue scene footprint</title>' + polygon
            + f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6" class="contact" />'
            + '<text x="30" y="295">North ↑ · longitude / latitude · schematic only</text></svg>')


def facts(items):
    return '<dl>' + ''.join(f'<div><dt>{escape(key)}</dt><dd>{escape(value)}</dd></div>'
                           for key, value in items) + '</dl>'


def render(title, body, prefix=""):
    template = (UI / "evidence.html").read_text(encoding="utf-8")
    return template.replace("{{TITLE}}", escape(title)).replace("{{PREFIX}}", prefix).replace("{{BODY}}", body)


def contact_page(contact, sidecar, provenance, preview=None):
    association = {"source_reported": "Provider-reported AIS match", "local_ais_match": "Local AIS association",
                   "unmatched": "AIS-unmatched contact for review"}[contact["association"]]
    body = f'<h1>{escape(association)}</h1><p class="lead">{escape(contact["ts"])} · {escape(contact["label"])} observation</p>'
    body += '<p class="notice">Operator review required. An unmatched contact does not establish deliberate AIS shutdown or hostile intent.</p>'
    body += '<section><h2>Observation</h2>' + facts([
        ("Contact ID", contact["id"]), ("Position", f'{contact["lat"]:.6f}, {contact["lon"]:.6f} (lat, lon)'),
        ("Scene", contact.get("scene_id", "Unavailable")),
        ("Radar length estimate", f'{contact["length_m"]:.1f} m' if contact.get("length_m") else "Unavailable"),
        ("Provider MMSI", contact.get("provider_matched_mmsi") or "Not supplied"),
        ("Associated MMSI", contact.get("matched_mmsi") or "Unavailable"),
        ("Provider category", contact.get("provider_match_category", "Not supplied")),
        ("Association provenance", contact["association_label"])]) + '</section>'
    body += '<section><h2>Scene coverage</h2>' + map_svg(contact)
    scene = contact["scene_evidence"]
    if scene["status"] == "available":
        body += facts([("Acquisition start", scene["acquisition_start_utc"]), ("Acquisition end", scene["acquisition_end_utc"]),
                       ("Scene provenance", scene["label"]),
                       ("Catalogue checked", scene.get("verified_on") or "Date not supplied")])
        body += '<p>' + source_link(scene.get("catalogue_url"), "Copernicus catalogue reference") + '</p><p>' + escape(scene["caveat"]) + '</p>'
        if preview:
            body += f'<figure><img src="../{preview}" alt="Whole-scene Sentinel-1 preview" /><figcaption>Whole-scene preview only; not a calibrated vessel measurement.</figcaption></figure>'
    else:
        body += '<p>Catalogue footprint and imagery unavailable locally. The map shows the contact position only.</p>'
    body += '</section><section><h2>AIS association and length review</h2>'
    body += facts([(key.replace("_", " "), value) for key, value in contact["association_evidence"].items()])
    body += facts([(key.replace("_", " "), value) for key, value in contact["length_check"].items()])
    body += '<ul>' + ''.join('<li>' + escape(reason) + '</li>' for reason in contact["unavailable_reasons"]) + '</ul>'
    if contact["custody_candidates"]:
        body += '<h3>Reachable candidates; identity remains unconfirmed</h3>'
        for candidate in contact["custody_candidates"]:
            body += facts([(key.replace("_", " "), value) for key, value in candidate.items() if key != "length_check"])
            body += facts([(key.replace("_", " "), value) for key, value in candidate["length_check"].items()])
    body += '</section><section><h2>Sources and assumptions</h2><p>'
    body += source_link(provenance.get("article") or provenance.get("source_url"), "Detection dataset reference") + '</p>'
    body += facts([("Dataset", provenance.get("dataset", "Version not supplied")),
                   ("Licence", provenance.get("license", "Not supplied; verify reuse before sharing")),
                   ("Attribution", provenance.get("attribution", "Not supplied")),
                   ("Source retrieval UTC", provenance.get("retrieved_at_utc", "Not recorded; export time is not retrieval time"))])
    body += '<p>Selected observations; not a regional census. Missing detections do not prove an empty sea.</p>'
    body += facts([(key.replace("_", " "), value) for key, value in sidecar["assumptions"].items()]) + '</section>'
    body += '<section><h2>Record an operator review</h2><p>This acknowledgement is local to this page. It authorizes no operational response.</p>'
    body += '<form data-review><label>Review note <textarea name="note" maxlength="500" required></textarea></label>'
    body += '<label class="check"><input type="checkbox" name="caveats" required /> I have reviewed the sources and limitations.</label>'
    body += '<button type="submit">Record local review</button><p role="status" data-review-status></p></form></section>'
    return render(association, body, "../")


def build_bundle(input_path, output, provenance_path=None, scene_paths=(), ais_path=None, quicklook_path=None):
    input_path, output = Path(input_path), Path(output)
    scene_paths = list(map(Path, scene_paths))
    sources = [input_path] + scene_paths + [Path(p) for p in (provenance_path, ais_path, quicklook_path) if p]
    if any(path.resolve().is_relative_to(output.resolve()) for path in sources):
        raise ValueError("bundle output must not contain or overwrite an input")
    marker = output / "manifest.json"
    previous = {}
    if output.exists() and any(output.iterdir()):
        previous = json.loads(marker.read_text()) if marker.exists() else {}
        if previous.get("generated_by") != "argus.evidence":
            raise ValueError("output must be empty or a previously generated Space bundle")
    if input_path.suffix.lower() == ".json":
        scenario = json.loads(input_path.read_text())
    else:
        scenario = import_contacts(input_path)
    if scenario.get("label") not in LABELS:
        raise ValueError("input needs an explicit provenance label")
    provenance = json.loads(Path(provenance_path).read_text()) if provenance_path else scenario.get("provenance") or {}
    if provenance.get("source_rows_sha256") and provenance["source_rows_sha256"] != sha256(input_path):
        raise ValueError("source rows do not match their provenance checksum")
    scenario["provenance"] = provenance
    if ais_path:
        if scenario.get("vessels"):
            raise ValueError("supply AIS either inside the scenario or with --ais, not both")
        scenario["vessels"] = load_ais(ais_path)
    # Keep UTC available to the renderer without inventing an epoch for relative-only input.
    for contact in scenario.get("detections", []):
        if "ts" in contact:
            contact["ts"] = utc(contact["ts"])
        else:
            if not scenario.get("t0_utc"):
                raise ValueError("contacts need absolute ts or a scenario t0_utc")
            contact["ts"] = datetime.fromtimestamp(time_of(contact, scenario["t0_utc"]), timezone.utc).isoformat().replace("+00:00", "Z")
    sidecar = analyse(scenario)
    scenes = load_scenes(scene_paths)
    attach_scenes(sidecar, scenes)
    preview, preview_bytes = None, None
    if quicklook_path:
        if len(scenes) != 1:
            raise ValueError("a quicklook needs exactly one supplied scene")
        preview_bytes = Path(quicklook_path).read_bytes()
        suffix = ".png" if preview_bytes.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if preview_bytes.startswith(b"\xff\xd8\xff") else None
        if not suffix:
            raise ValueError("quicklook must be PNG or JPEG")
        preview = "assets/scene-preview" + suffix
    source_records = [source_record(input_path, "radar_input", scenario["label"])]
    for path in scene_paths:
        metadata = json.loads(path.read_text())
        source_records.append(source_record(path, "catalogue_metadata", metadata.get("label", "real")))
    if provenance_path:
        source_records.append(source_record(provenance_path, "radar_provenance", scenario["label"]))
    ais_provenance = None
    if ais_path:
        ais_data = json.loads(Path(ais_path).read_text())
        source_records.append(source_record(ais_path, "normalized_ais", ais_data["label"]))
        ais_provenance = {key: ais_data.get(key) for key in
                          ("source_schema", "source", "provenance_labels", "quality", "caveat")}
    if quicklook_path:
        source_records.append(source_record(quicklook_path, "scene_preview", next(iter(scenes.values()))["label"]))
    ais_points = [{"ts": datetime.fromtimestamp(time_of(point, scenario.get("t0_utc")), timezone.utc).isoformat()}
                  for vessel in scenario.get("vessels", []) for point in vessel.get("track", [])]
    if ais_points and not scenario.get("t0_utc") and any("ts" not in point
            for vessel in scenario.get("vessels", []) for point in vessel.get("track", [])):
        raise ValueError("AIS fixes need absolute ts or scenario t0_utc")
    pages, rows = {}, []
    for index, contact in enumerate(sidecar["detections"], 1):
        filename = f"contacts/contact-{index:04d}.html"
        contact["evidence_url"] = filename
        pages[filename] = contact_page(contact, sidecar, provenance, preview if contact.get("scene_id") in scenes else None)
        rows.append('<tr><td>' + f'<a href="{filename}">{escape(contact["ts"])}</a></td>'
                    + f'<td>{escape(contact["label"])}</td><td>{escape(contact["association"])}</td>'
                    + f'<td>{contact["lat"]:.5f}, {contact["lon"]:.5f}</td></tr>')
    body = '<h1>Space evidence review</h1><p class="lead">Radar observations, AIS associations and provenance</p>'
    body += '<p class="notice">Operator review required. Keep historical evidence separate from fictional scenarios; check each observation label.</p>'
    body += '<table><caption>Selected contacts; not a regional census</caption><thead><tr><th>Acquisition UTC</th><th>Label</th><th>Association</th><th>Position (lat, lon)</th></tr></thead><tbody>'
    body += ''.join(rows) + '</tbody></table>'
    if not rows:
        body += '<p>No contacts in this input. This is not evidence of an empty sea.</p>'
    body += '<h2>Coverage and limitations</h2>' + facts(list(sidecar["coverage"].items()))
    body += '<p>AIS positions outside the association window remain unavailable. Source-reported matches are preserved separately from local associations. All processing runs before presentation.</p>'
    pages["index.html"] = render("Space evidence review", body)
    output.mkdir(parents=True, exist_ok=True)
    for filename, content in pages.items():
        path = output / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (output / "assets").mkdir(exist_ok=True)
    for filename in ("evidence.css", "evidence.js"):
        shutil.copyfile(UI / filename, output / "assets" / filename)
    if preview:
        (output / preview).write_bytes(preview_bytes)
    write_json(output / "input.json", scenario)
    write_json(output / "space.json", sidecar)
    files = list(pages) + ["assets/evidence.css", "assets/evidence.js", "input.json", "space.json"] + ([preview] if preview else [])
    manifest = {"generated_by": "argus.evidence", "schema_version": 1, "generated_at_utc": now_utc(),
        "sources": source_records,
        "provenance": provenance, "ais_provenance": ais_provenance,
        "source_retrieved_at_utc": provenance.get("retrieved_at_utc"),
        "selection": scenario.get("selection"),
        "region_bbox_west_south_east_north": scenario.get("bbox_west_south_east_north"),
        "coverage": {"radar": time_range(sidecar["detections"]),
                     "ais": {**time_range(ais_points), "status": "supplied" if ais_points else "not_supplied"},
                     "complete_regional_census": False,
                     "catalogue_scenes_supplied": sorted(scenes), "processed_detection_footprints_supplied": False},
        "processing": ["Normalize contacts", "Associate contemporaneous AIS with documented gates",
                       "Compare available contemporaneous dimensions", "Attach catalogue scene evidence", "Export offline review pages"],
        "assumptions": sidecar["assumptions"],
        "implementation_sha256": {path: sha256(ROOT / path) for path in
                                  ("argus/space.py", "argus/evidence.py", "argus/ingest/gfw.py", "argus/ingest/ais.py", "argus/provenance.py")},
        "files": [{"path": filename, "sha256": sha256(output / filename)} for filename in sorted(files)],
        "caveat": sidecar["caveat"]}
    write_json(marker, manifest)
    # Retire only generated contact/preview files when refreshing this pack.
    # Extra files placed here by the user are left alone.
    for item in previous.get("files", []):
        filename = item.get("path", "")
        if filename not in files and re.fullmatch(r"contacts/contact-\d{4,}\.html|assets/scene-preview\.(png|jpg)", filename):
            stale = output / filename
            if stale.is_file() and not stale.is_symlink():
                stale.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--contacts", type=Path)
    group.add_argument("--scenario", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--scene", type=Path, action="append")
    parser.add_argument("--ais", type=Path, help="JSON from argus.ingest.ais")
    parser.add_argument("--quicklook", type=Path, help="local preview belonging to the single supplied scene")
    parser.add_argument("--output", type=Path, default=Path("data/sar/review"))
    args = parser.parse_args()
    source = args.scenario or args.contacts or EXAMPLES / "gfw-unmatched-contacts.csv"
    bundled = source.resolve() == (EXAMPLES / "gfw-unmatched-contacts.csv").resolve()
    try:
        build_bundle(source, args.output,
                     args.provenance or (EXAMPLES / "provenance.json" if bundled else None),
                     args.scene if args.scene is not None else [EXAMPLES / "sentinel1-scene.json"] if bundled else [],
                     args.ais, args.quicklook)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Evidence export failed: {exc}\n")
    print(f"Offline evidence -> {args.output / 'index.html'}")


if __name__ == "__main__":
    main()
