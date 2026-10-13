"""Map drawing for dark-vessel predictions in the desktop shell; display only.

Shared by the fictional replay and received AIS contacts. Every shape here is a
labelled planning estimate from ``argus.prediction``, never an observed fix.
Tk canvases have no transparency, so the cone uses a colour pre-blended with
the sea and is drawn underneath tracks, cables and labels.
"""
from __future__ import annotations

import math
import tkinter as tk

from argus.prediction import predict, v_max_kn

AMBER = "#e1b164"
CONE_FILL = "#46443a"
CONE_EDGE = "#c99d55"
WORST = "#ff7a59"
INK = "#e4ebf0"
CARD = "#141e28"
SEA_OUTLINE = "#0b1118"
LIVE_MAX_DARK_S = 3 * 3600  # Beyond this the circle is too wide to help a reviewer.
LIVE_MIN_COURSE_KN = 1.0  # Below this AIS course over ground is mostly noise.
LABEL_MIN_RADIUS_PX = 70  # Smaller areas rely on the banner legend instead of colliding labels.


def live_prediction(vessel, now, stale_seconds):
    """Prediction for a received AIS contact whose last fix is stale, else None."""
    stamp = vessel.get("received_s")
    if stamp is None or vessel.get("lat") is None or vessel.get("lon") is None:
        return None
    dark_s = now - stamp
    if dark_s <= stale_seconds or dark_s > LIVE_MAX_DARK_S:
        return None
    speed = vessel.get("sog_kn")
    moving = speed is not None and speed >= LIVE_MIN_COURSE_KN
    last = {"t": stamp, "lat": vessel["lat"], "lon": vessel["lon"],
            "sog_kn": speed if moving else None, "cog_deg": vessel.get("cog_deg") if moving else None}
    return predict(last, now, v_max_kn([{"t": stamp, "sog_kn": speed}], stamp))


def extent_points(prediction, min_radius_nm=2.0):
    """North, south, east and west edges of the reachable circle, for fitting the map."""
    reach = prediction["reachable"]
    radius = max(reach["radius_nm"], min_radius_nm)
    dlon = radius / (60 * math.cos(math.radians(reach["lat"])))
    return [(reach["lat"] + radius / 60, reach["lon"]), (reach["lat"] - radius / 60, reach["lon"]),
            (reach["lat"], reach["lon"] + dlon), (reach["lat"], reach["lon"] - dlon)]


def _radius_px(app, lat, lon, radius_nm):
    _, cy = app._project(lat, lon)
    _, north_y = app._project(lat + radius_nm / 60, lon)
    return abs(cy - north_y)


def outlined_text(canvas, x, y, text, fill=INK, size=10, anchor="center", tags=()):
    """Readable over land, sea and imagery without a filled box."""
    font = ("Segoe UI Semibold", size)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        canvas.create_text(x + dx, y + dy, text=text, fill=SEA_OUTLINE, font=font, anchor=anchor,
                           justify="center", tags=tags)
    canvas.create_text(x, y, text=text, fill=fill, font=font, anchor=anchor, justify="center", tags=tags)


def draw_areas(app, prediction, tags=()):
    """Underlay: the circle it could reach and the cone where it most likely is."""
    canvas = app.map
    reach = prediction["reachable"]
    cx, cy = app._project(reach["lat"], reach["lon"])
    radius = _radius_px(app, reach["lat"], reach["lon"], reach["radius_nm"])
    if radius > 3:
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                           outline=AMBER, width=1.5, dash=(5, 5), tags=tags)
        if radius > LABEL_MIN_RADIUS_PX:
            outlined_text(canvas, cx, cy - radius - 9, f"could reach · max {reach['v_max_kn']:.0f} kn",
                          fill=AMBER, size=9, tags=tags)
    cone = prediction["cone"]
    if cone and radius > 3:
        canvas.create_polygon(*app._points(cone["polygon"]), fill=CONE_FILL, outline=CONE_EDGE,
                              width=1.5, joinstyle=tk.ROUND, tags=tags)
        middle = cone["polygon"][len(cone["polygon"]) // 4]  # Middle of the outer arc.
        mx, my = app._project(*middle)
        if radius > LABEL_MIN_RADIUS_PX:
            dx, dy = mx - cx, my - cy
            length = math.hypot(dx, dy) or 1
            outlined_text(canvas, mx + dx / length * 16, my + dy / length * 16, "likely area",
                          fill=CONE_EDGE, size=9, tags=tags)


def draw_worst_case(app, prediction, countdown, tags=()):
    """Straight line from the last fix to the closest cable point used by the countdown."""
    x1, y1 = app._project(prediction["reachable"]["lat"], prediction["reachable"]["lon"])
    x2, y2 = app._project(*countdown["closest_point"])
    app.map.create_line(x1, y1, x2, y2, fill=WORST, width=2, dash=(8, 5), arrow=tk.LAST,
                        arrowshape=(11, 13, 5), tags=tags)
    minutes = math.ceil(countdown["remaining_s"] / 60)
    outlined_text(app.map, (x1 + x2) / 2 + 10, (y1 + y2) / 2, f"worst case:\ncable in {minutes} min",
                  fill=WORST, size=9, anchor="w", tags=tags)


def draw_marker(app, prediction, last_point=True, tags=()):
    """Direction of travel and the best-guess position; returns its screen point.

    ``last_point`` adds a "last AIS" dot, unless the caller already draws the contact there.
    """
    canvas = app.map
    reach = prediction["reachable"]
    lx, ly = app._project(reach["lat"], reach["lon"])
    x, y = app._project(prediction["lat"], prediction["lon"])
    if math.hypot(x - lx, y - ly) > 18:
        canvas.create_line(lx, ly, x, y, fill=AMBER, width=2, dash=(6, 4), arrow=tk.LAST,
                           arrowshape=(10, 12, 4), tags=tags)
    if last_point:
        canvas.create_oval(lx - 5, ly - 5, lx + 5, ly + 5, fill=CARD, outline=INK, width=2, tags=tags)
        outlined_text(canvas, lx, ly + 15, "last AIS", size=9, tags=tags)
    canvas.create_oval(x - 12, y - 12, x + 12, y + 12, outline=AMBER, width=2, dash=(4, 3), tags=tags)
    canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=AMBER, outline="", tags=tags)
    return x, y


def draw_banner(app, prediction, tags=()):
    """Top-centre legend so every shape on the map is explained in place."""
    canvas = app.map
    width = app._map_size[0]
    minutes = math.ceil(prediction["elapsed_s"] / 60)
    v_max = prediction["reachable"]["v_max_kn"]
    title = f"AIS LOST {minutes} MIN AGO  ·  POSITION PREDICTED, NOT OBSERVED"
    left, top, right, bottom = width / 2 - 330, 26, width / 2 + 330, 92
    canvas.create_rectangle(left, top, right, bottom, fill=CARD, outline=AMBER, width=2, tags=tags)
    canvas.create_text(width / 2, top + 17, text=title, fill=AMBER, font=("Segoe UI Semibold", 12), tags=tags)
    row_y = top + 45
    font = ("Segoe UI", 11)
    x = left + 22
    canvas.create_polygon(x, row_y - 8, x + 20, row_y - 8, x + 15, row_y + 8, x + 5, row_y + 8,
                          fill=CONE_FILL, outline=CONE_EDGE, width=1.5, tags=tags)
    canvas.create_text(x + 28, row_y, text="likely: last course ±30°", anchor="w", fill=INK, font=font, tags=tags)
    x += 225
    canvas.create_oval(x, row_y - 9, x + 18, row_y + 9, outline=AMBER, dash=(3, 3), width=1.5, tags=tags)
    canvas.create_text(x + 26, row_y, text=f"could reach: max {v_max:.0f} kn", anchor="w", fill=INK,
                       font=font, tags=tags)
    x += 220
    canvas.create_oval(x, row_y - 9, x + 18, row_y + 9, outline=AMBER, dash=(4, 3), width=2, tags=tags)
    canvas.create_oval(x + 6, row_y - 3, x + 12, row_y + 3, fill=AMBER, outline="", tags=tags)
    canvas.create_text(x + 26, row_y, text="best guess", anchor="w", fill=INK, font=font, tags=tags)
