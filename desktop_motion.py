"""Smooth map motion: while the operator drags or zooms, the chart moves as one picture.

Before, each mouse move and each zoom step re-created or moved all ~2,500 map items, and Tk
repainted every one of them (40-70 ms a frame on a Retina Mac). Now, when a motion starts, the
chart as drawn (tiles, land, cables, ships, alerts, labels; everything except window-fixed
overlays) is copied into one image by ``desktop_flatten`` and those items are removed:

* Drag: one ``canvas.move`` of that image per mouse event. When the drag rests or ends, the map is
  redrawn normally (filling the edges the drag uncovered) and, if still dragging, copied again
  while the pointer is still, so the next movement starts at once.
* Zoom: the image glides to the new scale in about a quarter of a second, timed by the clock and
  eased out, keeping the point under the pointer still. A step taken while one is running joins
  it, so wheel notches and pinches become one continuous movement. The view on screen is tracked
  as ``screen = a * drawn + t`` with a target ``A, T``. Then the map is redrawn crisp.
* Margin scale ticks stay live items: longitude ticks follow only sideways, latitude ticks only up
  and down. Window-fixed overlays (``chart-fixed``) never move.
* Redraw requests during motion (live AIS, arriving tiles, the replay) wait and run once at the end.

Geography is never approximated: ``map_center`` and ``map_zoom`` change exactly as before, and every
motion ends with the normal full draw.
"""
from __future__ import annotations

import time
import tkinter as tk

from PIL import Image, ImageColor, ImageTk

from desktop_flatten import Flattener

FIXED = "chart-fixed"  # Overlays tied to the window, not to the chart: titles, legends, scale bar
TILE = "map-tile"  # Raster tile images; each also carries "tile:z:x:y"
FLAT = "motion-flat"  # Items copied into the moving picture (and then removed)
PICTURE = "motion-picture"  # The one image shown while the chart moves
PAN_REST_MS = 120  # Redraw once the pointer rests this long during a drag
PAN_REDRAW_SHARE = 0.5  # ... or once the drag has uncovered this share of the view
ZOOM_SECONDS = 0.24  # Each zoom step glides this long; a new step continues the movement
ZOOM_TICK_MS = 8  # Ask for the next frame this soon; the canvas sets the real frame rate


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


class MapMotion:
    def __init__(self, app):
        self.app = app
        self.dragging = False
        self.offset = [0.0, 0.0]
        self.pan_after = None
        self.zoom_after = None
        self.zoom_state: dict | None = None
        self.pending_redraw = False
        self.drawing = False  # True while this module itself redraws the map
        self.picture: Image.Image | None = None  # The chart as drawn when the motion began
        self.photo: ImageTk.PhotoImage | None = None
        self.a, self.tx, self.ty = 1.0, 0.0, 0.0  # How the picture sits on screen now
        self.flattener: Flattener | None = None
        self.timings: list[float] = []  # Seconds spent copying the chart, for tests and tuning

    # ----- shared -------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.dragging or self.zoom_state is not None

    @property
    def animating(self) -> bool:
        return self.zoom_state is not None

    def defer(self) -> bool:
        """Called by _draw_map: True means 'skip now, redraw when the motion ends'."""
        if self.busy and not self.drawing:
            self.pending_redraw = True
            return True
        return False

    def _cancel(self, attribute: str) -> None:
        job = getattr(self, attribute)
        if job is not None:
            try:
                self.app.root.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def _sea(self):
        return ImageColor.getrgb(self.app.map.cget("bg"))

    def _image_source(self, name: str, tags: list[str]) -> Image.Image | None:
        """The PIL pixels behind a map image item: chart tiles, their stand-ins, the weather layer."""
        app = self.app
        for tag in tags:
            if tag.startswith("tile:"):
                key = tuple(int(part) for part in tag.split(":")[1:])
                pixels = getattr(app, "_tile_pixels", {}).get(key)
                if pixels is None:
                    pixels = getattr(app, "_tile_fallback_pixels", {}).get(key)
                if pixels is None:
                    path = app._tile_path(key)
                    if path.exists():
                        try:
                            with Image.open(path) as opened:
                                pixels = opened.convert("RGB")
                        except (OSError, ValueError):
                            pixels = None
                return pixels
            if tag == "weather-overlay":
                overlay = getattr(app, "_weather_overlay", None) or {}
                return overlay.get("pil")
        return None

    def _flatten(self) -> None:
        """Replace the chart's items with one picture of them (fixed overlays and margin ticks stay)."""
        if self.picture is not None:
            return
        canvas = self.app.map
        started = time.perf_counter()
        if self.flattener is None or self.flattener.canvas is not canvas:
            self.flattener = Flattener(canvas, self._image_source)
        # Tag expressions cannot start from "all", so tag every item, then take the tag off what stays.
        canvas.addtag_withtag(FLAT, "all")
        for keep in (FIXED, "ruler-x", "ruler-y", PICTURE):
            canvas.dtag(keep, FLAT)
        width, height = self.app._map_size
        self.picture = self.flattener.render(FLAT, (width, height), self._sea())
        canvas.delete(FLAT)
        self.photo = ImageTk.PhotoImage(self.picture, master=canvas)
        canvas.create_image(0, 0, anchor="nw", image=self.photo, tags=(PICTURE,))
        if canvas.find_withtag("map-sea"):
            canvas.tag_raise(PICTURE, "map-sea")
        else:
            canvas.tag_lower(PICTURE)
        self.a, self.tx, self.ty = 1.0, 0.0, 0.0
        self.timings.append(time.perf_counter() - started)
        del self.timings[:-20]

    def _restore(self) -> None:
        """Back to normal drawing: drop the picture and redraw the map."""
        self.app.map.delete(PICTURE)
        self.picture = None
        self.photo = None
        self.offset = [0.0, 0.0]
        self.pending_redraw = False
        self.drawing = True  # Draws through even mid-drag (a rest, or a zoom that ended during a drag)
        try:
            self.app._draw_map(force_static=True)
        finally:
            self.drawing = False
        self.app._schedule_tile_refresh()

    def _move_rulers(self, dx: float, dy: float) -> None:
        canvas = self.app.map
        canvas.move("ruler-x", dx, 0)  # Top scale: longitude ticks slide sideways only
        canvas.move("ruler-y", 0, dy)  # Left scale: latitude ticks slide up and down only

    # ----- pan ----------------------------------------------------------------------------
    def start_pan(self) -> None:
        self.finish_zoom()
        self.dragging = True
        self.offset = [0.0, 0.0]

    def pan(self, dx: float, dy: float) -> None:
        if not dx and not dy:
            return
        self._flatten()
        self.app.map.move(PICTURE, dx, dy)
        self._move_rulers(dx, dy)
        self.tx += dx
        self.ty += dy
        self.offset[0] += dx
        self.offset[1] += dy
        width, height = self.app._map_size
        self._cancel("pan_after")
        if abs(self.offset[0]) > width * PAN_REDRAW_SHARE or abs(self.offset[1]) > height * PAN_REDRAW_SHARE:
            self._pan_rest()
        else:
            self.pan_after = self.app.root.after(PAN_REST_MS, self._pan_rest)

    def _pan_rest(self) -> None:
        """The drag paused (or went far): draw the map properly, and get the next picture ready."""
        self.pan_after = None
        self._restore()
        if self.dragging:
            self._flatten()  # While the pointer is still, so the next movement starts at once

    def end_pan(self) -> None:
        self._cancel("pan_after")
        moved = self.picture is not None or any(self.offset) or self.pending_redraw
        self.dragging = False
        if moved:
            self._restore()

    # ----- zoom ---------------------------------------------------------------------------
    def to_target(self, x: float, y: float) -> tuple[float, float]:
        """Where a point the operator sees now will sit once the running zoom lands.

        The map's centre and zoom already hold the target, so a zoom step taken mid-glide must find
        the geography under the pointer through this, not through the raw position.
        """
        state = self.zoom_state
        if state is None:
            return x, y
        drawn_x, drawn_y = (x - self.tx) / self.a, (y - self.ty) / self.a
        return state["A"] * drawn_x + state["TX"], state["A"] * drawn_y + state["TY"]

    def zoom(self, factor: float, x: float, y: float) -> None:
        """Zoom by ``factor`` keeping the point under (x, y) still; the caller has set the new zoom."""
        state = self.zoom_state
        if state is None:
            self._cancel("pan_after")
            self._flatten()
            canvas = self.app.map
            # A picture moved by a drag goes back to the corner; its offset becomes part of the view.
            coords = canvas.coords(PICTURE)
            if coords and (coords[0] or coords[1]):
                canvas.coords(PICTURE, 0, 0)
                self.photo.paste(self.frame(self.a, self.tx, self.ty))
            state = self.zoom_state = {"A": self.a, "TX": self.tx, "TY": self.ty}
        # The drawn point now under the pointer must end under the pointer.
        drawn_x, drawn_y = (x - self.tx) / self.a, (y - self.ty) / self.a
        state["A"] *= factor
        state["TX"], state["TY"] = x - state["A"] * drawn_x, y - state["A"] * drawn_y
        state["from"] = (self.a, self.tx, self.ty)
        state["started"] = time.perf_counter()
        if self.zoom_after is None:
            self._zoom_frame()

    def _zoom_frame(self) -> None:
        self.zoom_after = None
        state = self.zoom_state
        if state is None:
            return
        progress = min(1.0, (time.perf_counter() - state["started"]) / ZOOM_SECONDS)
        eased = ease_out(progress)
        a0, tx0, ty0 = state["from"]
        a = a0 * (state["A"] / a0) ** eased  # Even steps in scale, not in pixels
        if abs(a0 - state["A"]) > 1e-12:
            # Move along the path that keeps the zoom's fixed point still.
            cx, cy = (state["TX"] - tx0) / (a0 - state["A"]), (state["TY"] - ty0) / (a0 - state["A"])
            tx, ty = a0 * cx + tx0 - a * cx, a0 * cy + ty0 - a * cy
        else:
            tx, ty = tx0 + (state["TX"] - tx0) * eased, ty0 + (state["TY"] - ty0) * eased
        self._show(a, tx, ty)
        if progress >= 1.0:
            self.finish_zoom()
        else:
            self.zoom_after = self.app.root.after(ZOOM_TICK_MS, self._zoom_frame)

    def frame(self, a: float, tx: float, ty: float) -> Image.Image:
        """The picture as seen under ``screen = a * drawn + t``; uncovered parts are sea."""
        matrix = (1 / a, 0, -tx / a, 0, 1 / a, -ty / a)  # Each screen pixel shows drawn pixel (u - t) / a
        return self.picture.transform(self.picture.size, Image.Transform.AFFINE, matrix,
                                      resample=Image.Resampling.BILINEAR, fillcolor=self._sea())

    def _show(self, a: float, tx: float, ty: float) -> None:
        canvas = self.app.map
        if self.picture is not None and self.photo is not None:
            self.photo.paste(self.frame(a, tx, ty))  # In place: no new Tk image per frame
        k = a / self.a
        if abs(k - 1) > 1e-12:
            # Margin ticks: screen' = k * screen + (t - k * t_now), a scale by k about this origin.
            ox, oy = (tx - k * self.tx) / (1 - k), (ty - k * self.ty) / (1 - k)
            canvas.scale("ruler-x", ox, oy, k, 1)
            canvas.scale("ruler-y", ox, oy, 1, k)
        else:
            self._move_rulers(tx - self.tx, ty - self.ty)
        self.a, self.tx, self.ty = a, tx, ty

    def finish_zoom(self) -> None:
        if self.zoom_state is None:
            return
        self._cancel("zoom_after")
        self.zoom_state = None
        self._restore()
