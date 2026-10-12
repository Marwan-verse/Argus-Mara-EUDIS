"""Prepare an attributed offline Irish port catalogue from Ireland's Marine Atlas.

Run with --fetch to download sources into ignored data/maps/. Includes the
Atlas commercial, fishing and ferry port records, not a completeness guarantee
for every pier, marina or landing place. Coordinates are display references.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "https://atlas.marine.ie/arcgis/rest/services/TransportNetworks/MapServer"
LAYERS = {7: "Ferry", 8: "Commercial", 9: "Fishing"}


def prepare(fetch=False):
    ports, details, sources = [], {}, []
    for layer, category in LAYERS.items():
        url = f"{SERVICE}/{layer}/query?" + urlencode({"where": "1=1", "outFields": "*",
            "outSR": 4326, "returnGeometry": "true", "f": "json"})
        path = ROOT / f"data/maps/irish-ports-{layer}.json"
        if fetch:
            with urlopen(Request(url, headers={"User-Agent": "ArgusMaraDataPrep/0.1"}), timeout=30) as response:
                raw = response.read(8 * 1024 * 1024)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        raw = path.read_bytes()
        data = json.loads(raw)
        if data.get("error") or data.get("exceededTransferLimit") or "features" not in data:
            raise ValueError(f"Incomplete Marine Atlas layer {layer}")
        sources.append({"category": category, "url": f"{SERVICE}/{layer}",
                        "query_url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                        "source_records": len(data['features'])})
        for feature in data['features']:
            fields, point = feature['attributes'], feature['geometry']
            if 'creativecommons.org/licenses/by/4.0' not in str(fields.get('licence', '')):
                raise ValueError('Port record lacks verified CC BY 4.0 terms')
            name = fields.get('geographicalName') or fields.get('portName') or fields.get('localId')
            lat, lon = float(point['y']), float(point['x'])
            if not name or not (51 <= lat <= 55.6 and -11 <= lon <= -5.3):
                continue
            county = str(fields.get('county', '')).casefold()
            name_source = str(fields.get('geographicalNameSourceOfName', ''))
            northern = 'Northern_Ireland' in name_source or any(c in county for c in ('antrim','armagh','down','derry','tyrone','fermanagh'))
            identifier = -(layer * 10000 + int(fields['OBJECTID']))
            ports.append([identifier, str(name).strip(), round(lat, 6), round(lon, 6), 'GB' if northern else 'IE'])
            details[str(identifier)] = {"source": "Ireland's Marine Atlas / Marine Irish Digital Atlas",
                "category": category, "source_url": f"{SERVICE}/{layer}",
                "licence": "CC BY 4.0", "source_record_id": fields['OBJECTID']}
    result = {"label": "real", "source": "Ireland's Marine Atlas / Marine Irish Digital Atlas",
        "licence": "CC BY 4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "accessed_date": "2026-10-12", "coordinate_order": "id,name,lat,lon,country_code",
        "caveat": "Historical catalogue reference locations, not surveyed berths or navigation fixes. "
                  "Commercial, fishing and ferry records may describe the same harbour; excludes marinas and individual piers.",
        "sources": sources, "count": len(ports), "ports": ports, "details": details}
    output = ROOT / 'ui/assets/irish_ports.json'
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f"Prepared {len(ports)} Irish coastal port records")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    prepare(parser.parse_args().fetch)
