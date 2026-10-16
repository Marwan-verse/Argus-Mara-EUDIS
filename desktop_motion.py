"""Smooth map motion: dragging slides the drawn chart, zooming animates, full redraws only when needed.

Before, every mouse move while dragging and every zoom step deleted and re-created the whole map,
2,500 items and about 40-70 ms each time, so panning stuttered and zoom jumped. Now:

* Pan: one ``canvas.move`` per mouse event shifts what is already drawn (fixed overlays stay put,
  margin scale ticks slide along their own edge). The full redraw that fills in new edges and
  re-culls runs when the drag pauses, when it has moved a good part of the view, and on release.
* Zoom: the view scales around the pointer over a few frames with an ease-out curve. Vector
  items scale with ``canvas.scale``; the raster chart scales as one image built from the cached
  tiles. Text keeps its size, as on professional charts. The real redraw at the new zoom follows.
* Other redraw requests (live AIS, arriving tiles) wait until the motion ends, so a drag or an
  animation is never interrupted by a full redraw.

Geography is never approximated: ``map_center`` and ``map_zoom`` change exactly as before, and the
final frame is always a normal full draw.
"""
from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageColor, ImageTk

FIXED = "chart-fixed"  # Overlays tied to the window, not to the chart: titles, legends, scale bar
TILE = "map-tile"  # Raster tile images, replaced by one scaled image while zooming
PAN_IDLE_MS = 110  # Redraw once the pointer rests this long during a drag
PAN_REDRAW_SHARE = 0.35  # ... or once the drag has moved this share of the view
ZOOM_FRAMES = 8
ZOOM_FRAME_MS = 14


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

    def zoom(self, factor: float, x: float, y: float, raster: Image.Image | None) -> None:
        """Animate a zoom by ``factor`` around (x, y); the caller has already set the new zoom."""
        self.finish_zoom()
        canvas = self.app.map
        sea = ImageColor.getrgb(canvas.cget("bg"))
        if raster is not None:
            canvas.delete(TILE, "map-land")  # The one scaled image stands in for both
            item = canvas.create_image(0, 0, anchor="nw", tags=("zoom-raster",))
            canvas.tag_raise(item, "map-sea")
        self.zoom_state = {"factor": factor, "x": x, "y": y, "frame": 0, "scale": 1.0,
                           "raster": raster, "photo": None, "sea": sea}
        self._zoom_frame()

    def _zoom_frame(self) -> None:
        self.zoom_after = None
        state = self.zoom_state
        if state is None:
            return
        state["frame"] += 1
        target = state["factor"] ** ease_out(state["frame"] / ZOOM_FRAMES)
        step = target / state["scale"]
        state["scale"] = target
        canvas, x, y = self.app.map, state["x"], state["y"]
        # Everything tied to the chart scales; fixed overlays and the margin backgrounds do not.
        canvas.scale("all&&!chart-fixed&&!ruler-x&&!ruler-y&&!zoom-raster", x, y, step, step)
        canvas.scale("ruler-x", x, y, step, 1)
        canvas.scale("ruler-y", x, y, 1, step)
        if state["raster"] is not None:
            self._draw_raster(state)
        if state["frame"] >= ZOOM_FRAMES:
            self.finish_zoom()
        else:
            self.zoom_after = self.app.root.after(ZOOM_FRAME_MS, self._zoom_frame)

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
        raster, scale, x, y = state["raster"], state["scale"], state["x"], state["y"]
        # Each window pixel u shows old-view pixel x + (u - x) / scale; outside the old view is sea.
        matrix = (1 / scale, 0, x - x / scale, 0, 1 / scale, y - y / scale)
        frame = raster.transform(raster.size, Image.Transform.AFFINE, matrix, resample=Image.Resampling.BILINEAR,
                                 fillcolor=state["sea"])
        state["photo"] = ImageTk.PhotoImage(frame, master=self.app.map)
        self.app.map.itemconfigure("zoom-raster", image=state["photo"])
