"""Fetch public Sentinel-1 catalogue metadata and an optional scene quicklook.

The quicklook is a whole-scene preview, not calibrated imagery for measuring ships.
Full GRD downloads require a Copernicus account; GFW supplies our detections.
"""

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def scene_url(scene_id):
    name = scene_id if scene_id.endswith(".SAFE") else scene_id + ".SAFE"
    if not re.fullmatch(r"S1[ABCD]_IW_GRD[A-Z0-9_]+\.SAFE", name):
        raise ValueError("expected a Sentinel-1 IW GRD scene identifier")
    return CATALOGUE + "?" + urllib.parse.urlencode({"$filter": f"Name eq '{name}'", "$expand": "Assets"})


def fetch_scene(scene_id):
    url = scene_url(scene_id)
    with urllib.request.urlopen(url, timeout=30) as response:
        products = json.load(response)["value"]
    if len(products) != 1:
        raise ValueError(f"expected one catalogue product, found {len(products)}")
    product = products[0]
    quicklooks = [a["DownloadLink"] for a in product.get("Assets", []) if a["Type"] == "QUICKLOOK"]
    return {"label": "real", "source": "Copernicus Data Space Ecosystem", "catalogue_url": url,
            "product": product, "quicklook_url": quicklooks[0] if quicklooks else None,
            "caveat": "Metadata and whole-scene quicklook only. No calibrated image processing or ship-length measurement was performed."}


def download_quicklook(url, output):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "catalogue.dataspace.copernicus.eu":
        raise ValueError("unexpected public quicklook host")
    with urllib.request.urlopen(url, timeout=45) as response:
        content = response.read()
    # CDSE serves its PNG quicklooks as application/octet-stream.
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        output = output.with_suffix(".png")
    elif content.startswith(b"\xff\xd8\xff"):
        output = output.with_suffix(".jpg")
    else:
        raise ValueError("quicklook response was not an image")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/sar/sentinel1-scene.json"))
    parser.add_argument("--quicklook", type=Path, help="save the public whole-scene image preview")
    args = parser.parse_args()
    try:
        if args.quicklook and args.quicklook.resolve() == args.output.resolve():
            raise ValueError("quicklook and metadata output paths must differ")
        scene = fetch_scene(args.scene)
        if args.quicklook:
            if not scene["quicklook_url"]:
                raise ValueError("this product has no public quicklook")
            args.quicklook = download_quicklook(scene["quicklook_url"], args.quicklook)
            print(f"Saved whole-scene preview -> {args.quicklook}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(scene, indent=2) + "\n")
    except urllib.error.HTTPError as exc:
        parser.exit(1, f"Copernicus HTTP {exc.code}; full GRD imagery requires account access.\n")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Sentinel-1 catalogue lookup failed: {exc}\n")
    print(f"Saved scene metadata -> {args.output}")


if __name__ == "__main__":
    main()
