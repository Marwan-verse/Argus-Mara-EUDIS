"""Smooth map motion: while the operator drags or zooms, the chart moves as one picture.

Before, each mouse move and each zoom step re-created or moved all ~2,500 map items, and Tk
repainted every one of them (40-70 ms a frame on a Retina Mac). Now, when a motion starts, the
chart as drawn (land, tiles, cables, ships, alerts, labels; everything except window-fixed
overlays) is copied into one picture by ``desktop_flatten`` and those items are removed.

The picture is bigger than the view by a quarter on every side. The extra ring is filled with
chart tiles already decoded in memory (``run_gui`` decodes the cached tiles around the view in
the background), so a drag or a zoom-out shows real chart at the edges instead of a blank.

* Drag: one ``canvas.move`` of the picture per mouse event. When the drag rests, or uses up the
  ring, the map is redrawn normally and copied again while the pointer is still, so the next
  movement starts at once.
* Zoom: the view glides to the new scale in about a quarter of a second, timed by the clock and
  eased out, keeping the point under the pointer still. A step taken while one is running joins
  it, so wheel notches and pinches become one continuous movement. The view on screen is tracked
  as ``screen = a * drawn + t`` with a target ``A, T``; each frame is one affine transform of the
  picture pasted into the same photo image. Then the map is redrawn crisp.
* Margin scale ticks stay live items: longitude ticks follow only sideways, latitude ticks only up
  and down; while zooming out they are hidden instead of crowding together. Window-fixed overlays
  (``chart-fixed``) never move.
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
MARGIN_SHARE = 0.25  # The picture reaches this share of the view beyond each edge
PAN_REST_MS = 120  # Redraw once the pointer rests this long during a drag
ZOOM_SECONDS = 0.24  # Each zoom step glides this long; a new step continues the movement
ZOOM_TICK_MS = 8  # Ask for the next frame this soon; the canvas sets the real frame rate
DISK_TILES_PER_PICTURE = 24  # Tiles not yet in memory that one picture may read from disk


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def margins(size: tuple[int, int]) -> tuple[int, int]:
    return round(size[0] * MARGIN_SHARE), round(size[1] * MARGIN_SHARE)


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
        self.picture: Image.Image | None = None  # The chart as drawn when the motion began, with its ring
        self.margin = (0, 0)  # Where the view starts inside the picture
        self.view = (0, 0)
        self.photo: ImageTk.PhotoImage | None = None  # Shows the whole picture while dragging
        self.view_photo: ImageTk.PhotoImage | None = None  # Shows one transformed view while zooming
        self.rulers_hidden = False
        self.a, self.tx, self.ty = 1.0, 0.0, 0.0  # How the drawn chart sits on screen now
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

    def _tile(self, key: tuple[int, int, int], disk: bool) -> Image.Image | None:
        app = self.app
        pixels = getattr(app, "_tile_pixels", {}).get(key)
        if pixels is None:
            pixels = getattr(app, "_tile_fallback_pixels", {}).get(key)
        if pixels is None and disk:
            path = app._tile_path(key)
            if path.exists():
                try:
                    with Image.open(path) as opened:
                        pixels = opened.convert("RGB")
                except (OSError, ValueError):
                    pixels = None
        return pixels

    def _image_source(self, name: str, tags: list[str]) -> Image.Image | None:
        """The PIL pixels behind a map image item: chart tiles, their stand-ins, the weather layer."""
        for tag in tags:
            if tag.startswith("tile:"):
                return self._tile(tuple(int(part) for part in tag.split(":")[1:]), disk=True)
            if tag == "weather-overlay":
                overlay = getattr(self.app, "_weather_overlay", None) or {}
                return overlay.get("pil")
        return None

    def _paste_tiles(self, picture: Image.Image) -> bool:
        """Lay the chart tiles of the view and its ring into the picture; False for vector maps."""
        app = self.app
        from run_gui import TILE_SIZE, geo_to_world, is_raster
        if not is_raster(app.map_mode.get()):
            return False
        width, height = self.view
        mx, my = self.margin
        center_x, center_y = geo_to_world(*app.map_center, app.map_zoom)
        tiles = app._visible_tiles(self.margin)
        # Nearest first, so a limited number of disk reads go where they are seen first.
        middle_x, middle_y = center_x / TILE_SIZE, center_y / TILE_SIZE
        tiles.sort(key=lambda t: (t[3] + .5 - middle_x) ** 2 + (t[4] + .5 - middle_y) ** 2)
        disk_reads = DISK_TILES_PER_PICTURE
        for z, tile_x, tile_y, x_absolute, y_absolute in tiles:
            key = (z, tile_x, tile_y)
            in_memory = key in getattr(app, "_tile_pixels", {}) or key in getattr(app, "_tile_fallback_pixels", {})
            if not in_memory and disk_reads <= 0:
                continue
            pixels = self._tile(key, disk=not in_memory)
            disk_reads -= not in_memory
            if pixels is not None:
                picture.paste(pixels, (round(x_absolute * TILE_SIZE - center_x + width / 2 + mx),
                                       round(y_absolute * TILE_SIZE - center_y + height / 2 + my)))
        return True

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
        self.view = tuple(self.app._map_size)
        self.margin = margins(self.view)
        picture = Image.new("RGB", (self.view[0] + 2 * self.margin[0], self.view[1] + 2 * self.margin[1]), self._sea())
        # Same order as the canvas: land, then chart tiles over it (with the ring), then everything else.
        self.flattener.render(f"{FLAT}&&map-land", picture, self.margin)
        if self._paste_tiles(picture):
            self.flattener.render(f"{FLAT}&&!map-land&&!{TILE}", picture, self.margin)
        else:
            self.flattener.render(f"{FLAT}&&!map-land", picture, self.margin)
        canvas.delete(FLAT)
        self.picture = picture
        self.photo = ImageTk.PhotoImage(picture, master=canvas)
        canvas.create_image(-self.margin[0], -self.margin[1], anchor="nw", image=self.photo, tags=(PICTURE,))
        self._place_picture()
        self.a, self.tx, self.ty = 1.0, 0.0, 0.0
        self.timings.append(time.perf_counter() - started)
        del self.timings[:-20]

    def _place_picture(self) -> None:
        canvas = self.app.map
        if canvas.find_withtag("map-sea"):
            canvas.tag_raise(PICTURE, "map-sea")
        else:
            canvas.tag_lower(PICTURE)

    def _restore(self) -> None:
        """Back to normal drawing: drop the picture and redraw the map."""
        self.app.map.delete(PICTURE)
        self.picture = None
        self.photo = None
        self.view_photo = None
        self.rulers_hidden = False
        self.offset = [0.0, 0.0]
        self.pending_redraw = False
        self.drawing = True  # Draws through even mid-drag (a rest, or a zoom that ended during a drag)
        try:
            # Show the tiles of the new view at once (decoded ones need no disk read), then draw once.
            self.app._update_visible_tiles(draw=False)
            self.app._draw_map(force_static=True)
        finally:
            self.drawing = False

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
        self._cancel("pan_after")
        mx, my = self.margin
        if abs(self.offset[0]) > mx or abs(self.offset[1]) > my:
            self._pan_rest()  # The ring is used up: draw the new view now
        else:
            self.pan_after = self.app.root.after(PAN_REST_MS, self._pan_rest)

    def _pan_rest(self) -> None:
        """The drag paused (or used up the ring): draw the map properly, and get the next picture ready."""
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
            # Zooming shows one view-sized frame at a time instead of the whole picture.
            canvas = self.app.map
            canvas.delete(PICTURE)
            self.view_photo = ImageTk.PhotoImage("RGB", self.view, master=canvas)
            canvas.create_image(0, 0, anchor="nw", image=self.view_photo, tags=(PICTURE,))
            self._place_picture()
            self.view_photo.paste(self.frame(self.a, self.tx, self.ty))
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
        """The view as seen under ``screen = a * drawn + t``; beyond the picture is sea."""
        mx, my = self.margin
        # Each screen pixel u shows drawn point (u - t) / a, found at that point plus the ring in the picture.
        matrix = (1 / a, 0, mx - tx / a, 0, 1 / a, my - ty / a)
        return self.picture.transform(self.view, Image.Transform.AFFINE, matrix,
                                      resample=Image.Resampling.BILINEAR, fillcolor=self._sea())

    def _show(self, a: float, tx: float, ty: float) -> None:
        canvas = self.app.map
        if self.picture is not None and self.view_photo is not None:
            self.view_photo.paste(self.frame(a, tx, ty))  # In place: no new Tk image per frame
        k = a / self.a
        if abs(k - 1) > 1e-12:
            # Margin ticks: screen' = k * screen + (t - k * t_now), a scale by k about this origin.
            ox, oy = (tx - k * self.tx) / (1 - k), (ty - k * self.ty) / (1 - k)
            canvas.scale("ruler-x", ox, oy, k, 1)
            canvas.scale("ruler-y", ox, oy, 1, k)
        else:
            self._move_rulers(tx - self.tx, ty - self.ty)
        hide = a < 0.999  # Zooming out would crowd the ticks into an unreadable strip
        if hide != self.rulers_hidden:
            for tag in ("ruler-x", "ruler-y"):
                canvas.itemconfigure(tag, state="hidden" if hide else "normal")
            self.rulers_hidden = hide
        self.a, self.tx, self.ty = a, tx, ty

    def finish_zoom(self) -> None:
        if self.zoom_state is None:
            return
        self._cancel("zoom_after")
        self.zoom_state = None
        self._restore()
