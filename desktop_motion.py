"""Smooth map motion: dragging slides the drawn chart, zooming animates, full redraws only when needed.

Before, every mouse move while dragging and every zoom step deleted and re-created the whole map,
2,500 items and about 40-70 ms each time, so panning stuttered and zoom jumped. Now:

* Pan: one ``canvas.move`` per mouse event shifts what is already drawn (fixed overlays stay put,
  margin scale ticks slide along their own edge). The full redraw that fills in new edges and
  re-culls runs when the drag pauses, when it has moved a good part of the view, and on release.
* Zoom: the view glides to the new scale in about a quarter of a second, timed by the clock and
  eased out, keeping the point under the pointer still. A step taken while one is running joins
  it, so wheel notches and pinches become one continuous movement. Vector items scale with
  ``canvas.scale``; the raster chart scales as one image built from the cached tiles. Text keeps
  its size, as on professional charts. The real redraw at the new zoom follows.
* Other redraw requests (live AIS, arriving tiles) wait until the motion ends, so a drag or an
  animation is never interrupted by a full redraw.

Geography is never approximated: ``map_center`` and ``map_zoom`` change exactly as before, and the
final frame is always a normal full draw.
"""
from __future__ import annotations

import time
import tkinter as tk

from PIL import Image, ImageColor, ImageTk

FIXED = "chart-fixed"  # Overlays tied to the window, not to the chart: titles, legends, scale bar
TILE = "map-tile"  # Raster tile images, replaced by one scaled image while zooming
PAN_IDLE_MS = 110  # Redraw once the pointer rests this long during a drag
PAN_REDRAW_SHARE = 0.35  # ... or once the drag has moved this share of the view
ZOOM_SECONDS = 0.24  # Each zoom step glides this long; a new step continues the movement
ZOOM_TICK_MS = 8  # Ask for the next frame this soon; the frame rate is whatever the canvas allows


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

    # ----- shared -------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.dragging or self.zoom_state is not None

    def defer(self) -> bool:
        """Called by _draw_map: True means 'skip now, redraw when the motion ends'."""
        if self.busy:
            self.pending_redraw = True
            return True
        return False

    def _shift(self, dx: float, dy: float) -> None:
        canvas = self.app.map
        canvas.move("all", dx, dy)
        canvas.move(FIXED, -dx, -dy)
        canvas.move("ruler-x", 0, -dy)  # Top scale: longitude ticks slide sideways only
        canvas.move("ruler-y", -dx, 0)  # Left scale: latitude ticks slide up and down only

    def _cancel(self, attribute: str) -> None:
        job = getattr(self, attribute)
        if job is not None:
            try:
                self.app.root.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def _redraw(self) -> None:
        self.offset = [0.0, 0.0]
        self.pending_redraw = False
        self.app._draw_map(force_static=True)
        self.app._schedule_tile_refresh()

    # ----- pan ----------------------------------------------------------------------------
    def start_pan(self) -> None:
        self.finish_zoom()
        self.dragging = True
        self.offset = [0.0, 0.0]

    def pan(self, dx: float, dy: float) -> None:
        if not dx and not dy:
            return
        self._shift(dx, dy)
        self.offset[0] += dx
        self.offset[1] += dy
        width, height = self.app._map_size
        self._cancel("pan_after")
        if abs(self.offset[0]) > width * PAN_REDRAW_SHARE or abs(self.offset[1]) > height * PAN_REDRAW_SHARE:
            self._pan_redraw()
        else:
            self.pan_after = self.app.root.after(PAN_IDLE_MS, self._pan_redraw)

    def _pan_redraw(self) -> None:
        self.pan_after = None
        dragging, self.dragging = self.dragging, False  # Let this one draw through
        try:
            self._redraw()
        finally:
            self.dragging = dragging

    def end_pan(self) -> None:
        self._cancel("pan_after")
        moved = any(self.offset) or self.pending_redraw
        self.dragging = False
        if moved:
            self._redraw()

    # ----- zoom ---------------------------------------------------------------------------
    def snapshot(self) -> Image.Image | None:
        """The raster chart as now drawn; take it before the zoom level changes."""
        width, height = self.app._map_size
        return self._raster_snapshot(width, height, ImageColor.getrgb(self.app.map.cget("bg")))

    @property
    def animating(self) -> bool:
        return self.zoom_state is not None

    def to_target(self, x: float, y: float) -> tuple[float, float]:
        """Where a point the operator sees now will sit once the running zoom lands.

        The map's centre and zoom already hold the target, so a zoom step taken mid-animation
        must find the geography under the pointer through this, not through the raw position.
        """
        state = self.zoom_state
        if state is None:
            return x, y
        original_x, original_y = (x - state["tx"]) / state["a"], (y - state["ty"]) / state["a"]
        return state["A"] * original_x + state["TX"], state["A"] * original_y + state["TY"]

    def zoom(self, factor: float, x: float, y: float, raster: Image.Image | None) -> None:
        """Zoom by ``factor`` keeping the point under (x, y) still; the caller has set the new zoom.

        The view on screen is the drawn chart under an affine map ``screen = a * drawn + t``; the
        target is ``A, T``. A step taken while one is animating composes onto the target and the
        motion continues from where it is, so several wheel notches or a pinch become one movement.
        """
        state = self.zoom_state
        if state is None:
            canvas = self.app.map
            if raster is not None:
                canvas.delete(TILE, "map-land")  # The one scaled image stands in for both
                item = canvas.create_image(0, 0, anchor="nw", tags=("zoom-raster",))
                canvas.tag_raise(item, "map-sea")
            state = self.zoom_state = {"a": 1.0, "tx": 0.0, "ty": 0.0, "A": 1.0, "TX": 0.0, "TY": 0.0,
                                       "raster": raster, "photo": None, "sea": ImageColor.getrgb(canvas.cget("bg"))}
        # The drawn point now under the pointer must end under the pointer.
        drawn_x, drawn_y = (x - state["tx"]) / state["a"], (y - state["ty"]) / state["a"]
        state["A"] *= factor
        state["TX"], state["TY"] = x - state["A"] * drawn_x, y - state["A"] * drawn_y
        state["from"] = (state["a"], state["tx"], state["ty"])
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
        self._apply(state, a, tx, ty)
        if state["raster"] is not None:
            self._draw_raster(state)
        if progress >= 1.0:
            self.finish_zoom()
        else:
            self.zoom_after = self.app.root.after(ZOOM_TICK_MS, self._zoom_frame)

    def _apply(self, state: dict, a: float, tx: float, ty: float) -> None:
        """Move every chart item from the current affine map to (a, tx, ty)."""
        canvas = self.app.map
        k = a / state["a"]
        if abs(k - 1) > 1e-12:
            # screen' = k * screen + (t - k * t_now), i.e. a scale by k about this origin:
            ox, oy = (tx - k * state["tx"]) / (1 - k), (ty - k * state["ty"]) / (1 - k)
            canvas.scale("all&&!chart-fixed&&!ruler-x&&!ruler-y&&!zoom-raster", ox, oy, k, k)
            canvas.scale("ruler-x", ox, oy, k, 1)
            canvas.scale("ruler-y", ox, oy, 1, k)
        else:
            dx, dy = tx - state["tx"], ty - state["ty"]
            canvas.move("all&&!chart-fixed&&!ruler-x&&!ruler-y&&!zoom-raster", dx, dy)
            canvas.move("ruler-x", dx, 0)
            canvas.move("ruler-y", 0, dy)
        state["a"], state["tx"], state["ty"] = a, tx, ty

    def finish_zoom(self) -> None:
        if self.zoom_state is None:
            return
        self._cancel("zoom_after")
        self.zoom_state = None
        self.app.map.delete("zoom-raster")
        self._redraw()

    def _raster_snapshot(self, width: int, height: int, sea: tuple) -> Image.Image | None:
        """The visible raster chart as one image, assembled from cached tiles at the current zoom."""
        app = self.app
        from run_gui import TILE_SIZE, geo_to_world, is_raster
        if not is_raster(app.map_mode.get()) or width < 10 or height < 10:
            return None
        center_x, center_y = geo_to_world(*app.map_center, app.map_zoom)
        image = Image.new("RGB", (int(width), int(height)), sea)
        found = False
        for z, tile_x, tile_y, x_absolute, y_absolute in app._visible_tiles():
            at = (int(x_absolute * TILE_SIZE - center_x + width / 2), int(y_absolute * TILE_SIZE - center_y + height / 2))
            tile = getattr(app, "_tile_pixels", {}).get((z, tile_x, tile_y))
            if tile is None:
                path = app._tile_path((z, tile_x, tile_y))
                if not path.exists():
                    continue
                try:
                    with Image.open(path) as opened:
                        tile = opened.convert("RGB")
                except (OSError, ValueError):
                    continue
            image.paste(tile, at)
            found = True
        return image if found else None

    def _draw_raster(self, state: dict) -> None:
        raster, a = state["raster"], state["a"]
        # Each window pixel u shows drawn pixel (u - t) / a; outside the drawn view is sea.
        matrix = (1 / a, 0, -state["tx"] / a, 0, 1 / a, -state["ty"] / a)
        frame = raster.transform(raster.size, Image.Transform.AFFINE, matrix, resample=Image.Resampling.BILINEAR,
                                 fillcolor=state["sea"])
        state["photo"] = ImageTk.PhotoImage(frame, master=self.app.map)
        self.app.map.itemconfigure("zoom-raster", image=state["photo"])
