"""Render factual, labelled Irish vessel figures for the offline demo.

Raw published rasters stay in ignored data/satellite-imagery/. Only annotated
presentation figures are bundled under demo/imagery/. No detector, scenario,
live AIS identity or application dependency is changed.

Requires Pillow and matplotlib for preparation only. --check uses the standard
library and validates the already prepared pack without raw data or a network.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
import textwrap
import warnings
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "demo/imagery"
MANIFEST = PACK / "manifest.json"
YELLOW = "#ffdc58"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(sources):
    # certifi is optional: use the platform trust store if it is unavailable.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    for source in sources:
        path = ROOT / source["raw_path"]
        if path.exists() and digest(path) == source["raw_sha256"]:
            continue
        request = Request(source["download_url"], headers={
            "User-Agent": "ArgusMaraDataPrep/1.0 (educational satellite imagery)"})
        with urlopen(request, context=context, timeout=60) as response:
            raw = response.read(64 * 1024 * 1024 + 1)
        if hashlib.sha256(raw).hexdigest() != source["raw_sha256"]:
            raise ValueError(f"Source changed: {source['id']}; review it before updating the manifest")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        print(f"Downloaded {source['id']} to ignored {source['raw_path']}")


def check(pack):
    expected = {item["image_path"] for item in pack["vessels"] + pack["overviews"]}
    expected.add("contact-sheet.png")
    expected.update(item["image_path"] for item in pack.get("risk_scenarios", []))
    if pack.get("risk_scenarios"):
        expected.add("cable-risk/contact-sheet.png")
    outputs = {item["path"]: item for item in pack.get("outputs", [])}
    if set(outputs) != expected:
        raise ValueError("Manifest output list does not match the image pack")
    codes = [vessel["code"] for vessel in pack["vessels"]]
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate demo vessel code")
    sources = {source["id"]: source for source in pack["sources"]}
    vessels = {vessel["code"]: vessel for vessel in pack["vessels"]}
    for vessel in pack["vessels"]:
        source = sources[vessel["source_id"]]
        x0, y0, x1, y1 = vessel["crop_bounds_px"]
        bx0, by0, bx1, by1 = vessel["vessel_bounds_px"]
        width, height = source["source_size_px"]
        if not (0 <= x0 <= bx0 < bx1 <= x1 <= width and
                0 <= y0 <= by0 < by1 <= y1 <= height):
            raise ValueError(f"Invalid selection bounds: {vessel['code']}")
        if vessel["identity_label"] != "fictional" or source["imagery_label"] != "real":
            raise ValueError(f"Unexpected provenance: {vessel['code']}")
    for risk in pack.get("risk_scenarios", []):
        vessel = vessels[risk["vessel_code"]]
        if risk["label"] != "simulated" or risk["cable_label"] != "simulated":
            raise ValueError(f"Cable-risk overlay must be simulated: {risk['id']}")
        x0, y0, x1, y1 = vessel["crop_bounds_px"]
        for field in ("cable_path_px", "track_path_px", "projection_path_px"):
            if not all(x0 <= x < x1 and y0 <= y < y1 for x, y in risk[field]):
                raise ValueError(f"Overlay outside image region: {risk['id']}")
    for relative_path, output in outputs.items():
        path = PACK / relative_path
        if digest(path) != output["sha256"]:
            raise ValueError(f"Image hash mismatch: {relative_path}")
        if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a PNG: {relative_path}")
    print(f"Verified {len(pack['vessels'])} labelled vessels, {len(pack['overviews'])} overviews, "
          f"{len(pack.get('risk_scenarios', []))} simulated cable-risk figures and contact sheets")


def render(pack):
    # Keep development caches outside the repository and application runtime.
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "argus-imagery-mpl"))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "argus-imagery-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from PIL import Image
    import numpy as np

    sources = {source["id"]: source for source in pack["sources"]}
    rasters = {}
    for source in pack["sources"]:
        path = ROOT / source["raw_path"]
        if digest(path) != source["raw_sha256"]:
            raise ValueError(f"Source hash mismatch: {source['id']}")
        # The reviewed, hash-verified North Sea raster is just over Pillow's
        # warning threshold; retain the hard limit and silence only that warning.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(path)
        if list(image.size) != source["source_size_px"]:
            image.close()
            raise ValueError(f"Source size mismatch: {source['id']}")
        rasters[source["id"]] = image

    def region(ax, item):
        x0, y0, x1, y1 = item["crop_bounds_px"]
        ax.imshow(np.asarray(rasters[item["source_id"]].crop((x0, y0, x1, y1))),
                  extent=(x0, x1, y1, y0), interpolation="nearest")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y1, y0)
        ax.set_axis_off()

    def outline(ax, vessel, label=False, label_offset=(0, 10)):
        x0, y0, x1, y1 = vessel["vessel_bounds_px"]
        margin = 4
        ax.add_patch(Rectangle((x0 - margin, y0 - margin), x1 - x0 + 2 * margin,
                              y1 - y0 + 2 * margin, fill=False,
                              edgecolor=YELLOW, linewidth=1.6))
        if label:
            leader = {"arrowstyle": "-", "color": YELLOW, "lw": .8} if label_offset != (0, 10) else None
            ax.annotate(vessel["code"], ((x0+x1)/2, y0-margin), xytext=label_offset,
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=9, color=YELLOW,
                        arrowprops=leader,
                        bbox={"facecolor": "#142232", "edgecolor": "none", "pad": 3})

    def footer(fig, source):
        fig.text(.045, .077, source["credit"], fontsize=10, color="#374151")
        fig.text(.045, .046,
                 f"{source['license']} · Selected region and demo labels added · Source link in manifest.json",
                 fontsize=9, color="#4b5563")
        fig.text(.045, .018, "Optical imagery · Enlarged pixels add no detail · No verified AIS association or behavior",
                 fontsize=9, color="#4b5563")

    def risk_overlay(ax, risk, vessel, small=False):
        xs, ys = zip(*risk["cable_path_px"])
        ax.plot(xs, ys, color="#4ed6ff", linewidth=24, alpha=.18, solid_capstyle="round")
        ax.plot(xs, ys, color="#4ed6ff", linewidth=2.4, linestyle="--")
        ax.annotate("DEMO CABLE", (xs[0], ys[0]), xytext=(3, -14),
                    textcoords="offset points", fontsize=8 if small else 10,
                    color="#4ed6ff", bbox={"facecolor": "#142232", "edgecolor": "none", "pad": 3})
        if risk["track_path_px"]:
            tx, ty = zip(*risk["track_path_px"])
            ax.plot(tx, ty, color="#ff8c72", linestyle=":", linewidth=2, marker=".", markersize=4)
        if risk["projection_path_px"]:
            px, py = zip(*risk["projection_path_px"])
            ax.plot(px, py, color="#ff8c72", linestyle=":", linewidth=2)
            ax.annotate("", xy=(px[-1], py[-1]), xytext=(px[-2], py[-2]),
                        arrowprops={"arrowstyle": "->", "color": "#ff8c72", "lw": 2})
        outline(ax, vessel)

    outputs = []

    def save(fig, relative_path):
        path = PACK / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=100, facecolor="white", metadata={
            "Title": pack["title"],
            "Description": "Real satellite imagery; fictional demo names/codes. Cable-risk overlays are simulated. See manifest.json for per-image attribution.",
            "Sources": "\n".join(f"{source['credit']} | {source['source_url']} | {source['license']} | {source['license_url']}"
                                 for source in pack["sources"])})
        plt.close(fig)
        with Image.open(path) as image:
            size = list(image.size)
        outputs.append({"path": relative_path, "sha256": digest(path), "size_px": size})

    for vessel in pack["vessels"]:
        source = sources[vessel["source_id"]]
        fig = plt.figure(figsize=(12, 8))
        fig.text(.045, .94, f"{vessel['code']}  /  {vessel['demo_name']}", fontsize=23, weight="bold")
        fig.text(.045, .892, f"{vessel['location']} · {source['date_display']}", fontsize=13, color="#374151")
        fig.text(.045, .85, "IMAGERY: REAL    NAME / CODE: FICTIONAL    SELECTION: MANUAL", fontsize=10, color="#374151")
        ax = fig.add_axes((.045, .14, .91, .675))
        region(ax, vessel)
        outline(ax, vessel)
        footer(fig, source)
        save(fig, vessel["image_path"])

    for overview in pack["overviews"]:
        source = sources[overview["source_id"]]
        fig = plt.figure(figsize=(12, 8))
        fig.text(.045, .94, overview["title"], fontsize=23, weight="bold")
        fig.text(.045, .889, f"{source['date_display']} · Real imagery / fictional contact codes", fontsize=12)
        ax = fig.add_axes((.045, .14, .91, .70))
        region(ax, overview)
        for vessel in pack["vessels"]:
            if vessel["source_id"] == overview["source_id"]:
                offset = (-48, 30) if vessel["code"] == "AM-IE-001" else (0, 10)
                outline(ax, vessel, label=True, label_offset=offset)
        footer(fig, source)
        save(fig, overview["image_path"])

    fig, axes = plt.subplots(3, 2, figsize=(18, 18))
    fig.subplots_adjust(left=.055, right=.945, top=.83, bottom=.075, hspace=.42, wspace=.10)
    fig.text(.055, .955, "ARGUS MARA / Irish coastal vessel imagery", fontsize=27, weight="bold")
    fig.text(.055, .92, "Six manually selected contacts from Dublin and Cork · Nazar's demonstration image pack", fontsize=16)
    fig.text(.055, .891, "IMAGERY: REAL    NAMES / CODES: FICTIONAL    No verified AIS association or suspicious behavior", fontsize=12)
    irish_vessels = [vessel for vessel in pack["vessels"] if vessel["code"].startswith("AM-IE-")]
    for ax, vessel in zip(axes.flat, irish_vessels):
        source = sources[vessel["source_id"]]
        region(ax, vessel)
        outline(ax, vessel)
        ax.set_title(f"{vessel['code']} / {vessel['demo_name']}\n{vessel['location']}\n{source['date_display']}",
                     loc="left", fontsize=13, pad=12)
    fig.text(.055, .045, "Dublin: Contains modified Copernicus Sentinel data (2020), processed by ESA · CC BY-SA 3.0 IGO", fontsize=12)
    fig.text(.055, .025, "Cork: European Union, Copernicus Sentinel-2 imagery · CC BY 4.0 · Source links and changes in manifest.json", fontsize=12)
    save(fig, "contact-sheet.png")

    vessels = {vessel["code"]: vessel for vessel in pack["vessels"]}
    for risk in pack.get("risk_scenarios", []):
        vessel = vessels[risk["vessel_code"]]
        source = sources[vessel["source_id"]]
        fig = plt.figure(figsize=(12, 9))
        fig.text(.045, .95, f"{risk['id']} / {vessel['code']} / {vessel['demo_name']}", fontsize=22, weight="bold")
        fig.text(.045, .902, risk["title"], fontsize=19, color="#374151")
        fig.text(.045, .858, f"{vessel['location']} · {source['date_display']}", fontsize=11)
        fig.text(.045, .819, "IMAGERY: REAL    CABLE / TRACK / BEHAVIOR: SIMULATED    NAME: FICTIONAL", fontsize=10)
        ax = fig.add_axes((.045, .18, .65, .60))
        region(ax, vessel)
        risk_overlay(ax, risk, vessel)
        fig.text(.735, .72, "REVIEW CUE", fontsize=12, weight="bold")
        fig.text(.735, .675, textwrap.fill(risk["cue"], 32), fontsize=11, va="top", linespacing=1.6)
        fig.text(.735, .46, "OVERLAY KEY", fontsize=12, weight="bold")
        fig.text(.735, .415, "Cyan: exercise internet cable\nRed: exercise track / course\nYellow: selected vessel pixels",
                 fontsize=10, va="top", linespacing=1.8)
        fig.text(.735, .29, "No real cable location,\ndistance or risk level\nis established by this figure.",
                 fontsize=10, va="top", linespacing=1.7, color="#4b5563")
        fig.text(.045, .127, "SIMULATED DEMONSTRATION · Human review required before any response", fontsize=11, weight="bold")
        footer(fig, source)
        save(fig, risk["image_path"])

    if pack.get("risk_scenarios"):
        fig, axes = plt.subplots(3, 2, figsize=(18, 18))
        fig.subplots_adjust(left=.055, right=.945, top=.79, bottom=.075, hspace=.43, wspace=.13)
        fig.text(.055, .955, "ARGUS MARA / Internet-cable risk demonstration", fontsize=26, weight="bold")
        fig.text(.055, .915, "Real offshore satellite vessels · Ireland and comparable North Sea water", fontsize=17)
        fig.text(.055, .879, "IMAGERY: REAL    CABLES / TRACKS / BEHAVIOR: SIMULATED    VESSEL NAMES: FICTIONAL", fontsize=12)
        fig.text(.055, .852, "Cyan = exercise fibre-optic cable     Red = exercise route     Yellow = vessel pixels     Human review required", fontsize=12)
        for ax, risk in zip(axes.flat, pack["risk_scenarios"]):
            vessel = vessels[risk["vessel_code"]]
            region(ax, vessel)
            risk_overlay(ax, risk, vessel, small=True)
            location = "Dublin, Ireland" if vessel["code"].startswith("AM-IE-") else "North Sea, Netherlands (not Ireland)"
            ax.set_title(f"{risk['id']} / {vessel['code']} / {vessel['demo_name']}\n{risk['title']}\n{location}",
                         loc="left", fontsize=12, pad=12)
        fig.text(.055, .045, "Contains modified Copernicus Sentinel data (2020 / 2016), processed by ESA · CC BY-SA 3.0 IGO", fontsize=12)
        fig.text(.055, .025, "Historical imagery · Simulated cable/route overlays added · No real cable proximity measured · Sources and dates in manifest.json", fontsize=11)
        save(fig, "cable-risk/contact-sheet.png")

    for image in rasters.values():
        image.close()
    pack["outputs"] = outputs
    MANIFEST.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    check(pack)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download the two reviewed sources into ignored data/")
    parser.add_argument("--check", action="store_true", help="Validate bundled output hashes offline; no preparation dependencies")
    args = parser.parse_args()
    pack = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.check:
        check(pack)
        return
    if args.fetch:
        download(pack["sources"])
    render(pack)


if __name__ == "__main__":
    main()
