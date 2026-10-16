"""Open the app (pro look), zoom and drag it, and save screenshots of each stage plus timings.

Usage: python scripts/visual_motion_check.py OUTPUT_FOLDER

For CI (.github/workflows/visual-check.yml) and anyone who wants to see the motion without
watching it live. It shows a real window, so do not run it on a machine where that is unwelcome.
Screens are grabbed with Pillow's ImageGrab (Windows and macOS); the moving picture and one glide
frame are also saved straight from desktop_motion, so the result is useful even where the
screen cannot be grabbed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ARGUS_AIS_AUTOCONNECT", "0")
os.environ.setdefault("ARGUS_UI_PREFERENCES", "")
os.environ["ARGUS_REDUCED_MOTION"] = "0"


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "visual-check")
    output.mkdir(parents=True, exist_ok=True)
    import customtkinter as ctk
    from PIL import ImageGrab
    import desktop_motion
    import desktop_pro
    import run_gui

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    desktop_pro.apply_palette()
    root = ctk.CTk()
    app = run_gui.ArgusApp(root, *run_gui.load_demo())
    root.minsize(900, 600)
    root.geometry("1020x740+0+0")  # GitHub's Windows desktop is 1024 x 768
    root.attributes("-topmost", True)
    root.lift()
    report = {"frames": [], "flatten_ms": [], "events": []}

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    def shot(name: str) -> None:
        root.update()
        x, y = app.map.winfo_rootx(), app.map.winfo_rooty()
        width, height = app.map.winfo_width(), app.map.winfo_height()
        try:
            ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(output / f"{name}.png")
        except Exception as error:  # A headless machine: the saved pictures below still show the motion
            report["events"].append(f"{name}: screen grab failed: {error}")

    # Time every glide frame.
    show = desktop_motion.MapMotion._show

    def timed(self, a, tx, ty):
        started = time.perf_counter()
        show(self, a, tx, ty)
        root.update_idletasks()  # Include Tk's repaint of the frame
        report["frames"].append(round((time.perf_counter() - started) * 1000, 1))
    desktop_motion.MapMotion._show = timed

    pump(12)  # Tiles download on a fresh machine
    app.fit_ireland()
    pump(8)
    report["chart_items"] = len(app.map.find_all())
    shot("01-before")
    width, height = app._map_size
    x, y = width * 0.55, height * 0.5

    # One zoom step: look half way and at the end.
    app._zoom_at(1, x, y)
    pump(0.10)
    shot("02-zoom-in-mid")
    if app.motion.picture is not None:
        app.motion.picture.save(output / "02-moving-picture.png")
        app.motion.frame(app.motion.a, app.motion.tx, app.motion.ty).save(output / "02-glide-frame.png")
    pump(1.5)
    shot("03-zoom-in-end")

    # Three quick notches: one continuous glide.
    for _ in range(3):
        app._zoom_at(1, x, y)
        pump(0.06)
    shot("04-three-notches-mid")
    pump(1.5)
    shot("05-three-notches-end")

    # Drag 200 px to the left and 80 px up in small steps.
    event = type("Event", (), {})
    start = event()
    start.x, start.y = int(x), int(y)
    app._pan_start(start)
    for step in range(1, 21):
        move = event()
        move.x, move.y = int(x - 10 * step), int(y - 4 * step)
        app._pan_move(move)
        pump(0.016)
    shot("06-drag-mid")
    app._pan_end(move)
    pump(1.5)
    shot("07-drag-end")

    # Zoom back out with a chain of notches.
    for _ in range(4):
        app._zoom_at(-1, x, y)
        pump(0.05)
    shot("08-zoom-out-mid")
    pump(1.5)
    shot("09-zoom-out-end")

    report["flatten_ms"] = [round(value * 1000, 1) for value in app.motion.timings]
    report["prepare_ms"] = round(app.motion.prepare_seconds * 1000, 1)
    (output / "timings.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
