"""Magnetics panel: live geomagnetic storm context and the seabed search planner; display only.

Two real uses of magnetics, neither of which watches the sea:

* **Storm status (real data, opt-in).** NOAA SWPC Kp and the Valentia observatory's minute-by-minute
  field change, polled only while the operator switches live magnetics on. A header chip shows the tier.
  It is context for electrical cable alarms and never raises, lowers or clears an alert.
* **Seabed search plan (planning estimate).** For the exercise vessel or the selected alert, a corridor
  along the track from the slowdown to the cable crossing and on to where speed recovered, with line
  spacing, lines, line-km and hours per magnetometer platform, ranked search points and a GeoJSON export.
  Every number is a team assumption (``argus.survey_plan``).
"""

from __future__ import annotations

import queue
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from argus import geomag, survey_plan
from argus.alert_board import line_path
from argus.provenance import write_json

TIER_COLOURS = {0: "#8fd3b0", 1: "#e1b164", 2: "#f0904f", 3: "#ef5f5f"}
PLAN, PLAN_LINE, MUTED, INK, CONTROL, BG = "#e1b164", "#f3d7a6", "#a8b6c2", "#e4ebf0", "#1c2a36", "#0b1118"
TAG = "seabed-plan"
WRAP = 390
PLATFORM_NAMES = {"usv": "USV tow, 10 m above seabed", "auv": "AUV, 5 m above seabed",
                  "drone": "Drone, 15 m above sea"}


def _number(text: str, what: str) -> float | None:
    text = text.strip().replace(",", ".").removesuffix("m").removesuffix("t").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{what} must be a number") from None
    if value <= 0:
        raise ValueError(f"{what} must be more than zero")
    return value


class DesktopMagnetics:
    def __init__(self, app, data_dir: Path, fetch_kp=None, fetch_valentia=None):
        self.app = app
        root = app.root
        self.data_dir = Path(data_dir)
        self.cache_path = self.data_dir / "geomag-latest.json"
        self.fetch_kp = fetch_kp or geomag.fetch_kp
        self.fetch_valentia = fetch_valentia or geomag.fetch_valentia
        self.live = tk.BooleanVar(root, value=False)
        self.status: dict | None = None
        self.cached = geomag.load_cache(self.cache_path)
        self.message = "Live magnetic data off · no network requests"
        self.kp_rows: list[dict] | None = None
        self.val_rows: list[dict] | None = None
        self._val_fetched = -1e9
        self.generation = 0
        self.queue: queue.Queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="argus-geomag")
        self._refresh_after = None
        self._poll_after = root.after(500, self._poll)
        self.chip = None
        self.frame = None
        self.storm_frame = None
        self.plan_frame = None
        self.source = tk.StringVar(root, value="exercise")
        self.depth = tk.StringVar(root, value="")
        self.mass = tk.StringVar(root, value=f"{survey_plan.DEFAULT_MASS_T:g}")
        self.platform = tk.StringVar(root, value=PLATFORM_NAMES["usv"])
        self.show_plan = tk.BooleanVar(root, value=True)
        self.plan: dict | None = None
        self.plan_error: str | None = None
        self.saved_path: Path | None = None

    # --- Panel -----------------------------------------------------------------------------------
    def build(self, frame) -> None:
        self.frame = frame
        self.storm_frame = ttk.Frame(frame)
        self.storm_frame.pack(fill="x", anchor="n")
        ttk.Separator(frame).pack(fill="x", pady=10)
        self.plan_frame = ttk.Frame(frame)
        self.plan_frame.pack(fill="both", expand=True, anchor="n")
        self.refresh_storm()
        self.refresh_plan()

    @staticmethod
    def _alive(widget) -> bool:
        try:
            return widget is not None and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _clear(self, widget) -> bool:
        if not self._alive(widget):
            return False
        for child in widget.winfo_children():
            child.destroy()
        return True

    def refresh_storm(self) -> None:
        frame = self.storm_frame
        if not self._clear(frame):
            return
        ttk.Label(frame, text="Magnetic storm status · real data", style="Heading.TLabel").pack(anchor="w")
        ttk.Checkbutton(frame, text="Live magnetic data (requests NOAA SWPC and BGS)", variable=self.live,
                        command=self.toggle_live).pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, text=self.message, style="Muted.TLabel", wraplength=WRAP).pack(anchor="w", pady=(2, 6))
        status = self.status if self.live.get() else None
        if status:
            ttk.Label(frame, text=f"Tier {status['tier']} · {geomag.summary(status)}",
                      foreground=TIER_COLOURS[status["tier"]], font=("Segoe UI Semibold", 13)).pack(anchor="w")
            lines = []
            if status["kp_time"]:
                since = geomag.kp_interval_start(status["time"]) - timedelta(seconds=geomag.KP_INTERVAL_S)
                lines.append(f"Kp, highest since {since:%H:%M} UTC: {status['kp']:.2f} at {status['kp_time']:%H:%M} UTC "
                             f"(latest {status['kp_latest']:.2f}; the estimate restarts every 3 h)")
            if status["val_last_time"]:
                change = (f"largest change in the last hour {status['dhdt']:.1f} nT/min at {status['dhdt_time']:%H:%M} UTC"
                          if status["dhdt"] is not None else "change in the last hour unknown")
                lines.append(f"Valentia: last minute {status['val_last_time']:%H:%M} UTC, {change}")
            lines += status["reasons"] + status["notes"]
            ttk.Label(frame, text="\n".join(lines), wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))
            ttk.Label(frame, text=status["effect"], wraplength=WRAP, justify="left",
                      foreground=TIER_COLOURS[status["tier"]] if status["tier"] else INK).pack(anchor="w", pady=(6, 0))
        elif self.cached:
            ttk.Label(frame, text=(f"Last saved status: {geomag.summary(self.cached)} · recorded "
                                   f"{self.cached['time']:%d %b %H:%M} UTC (real, not live)"),
                      style="Muted.TLabel", wraplength=WRAP, justify="left").pack(anchor="w")
        ttk.Label(frame, text="Context only: it never raises, lowers or clears an alert. " + geomag.PHYSICS,
                  style="Muted.TLabel", wraplength=WRAP, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, text="Source: " + geomag.ATTRIBUTION + ". Tiers are a team assumption.",
                  style="Muted.TLabel", wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))

    def refresh_plan(self) -> None:
        frame = self.plan_frame
        if not self._clear(frame):
            return
        ttk.Label(frame, text="Seabed search plan · planning estimate", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(frame, text=("After a suspected anchor drag: where to search for a lost anchor or chain with a "
                               "magnetometer, and how long it takes."),
                  style="Muted.TLabel", wraplength=WRAP, justify="left").pack(anchor="w", pady=(2, 6))
        sources = ttk.Frame(frame)
        sources.pack(anchor="w")
        ttk.Radiobutton(sources, text="Exercise vessel", variable=self.source, value="exercise").pack(side="left")
        alert = self.selected_alert()
        ttk.Radiobutton(sources, text="Selected alert" if alert else "Selected alert (select one first)",
                        variable=self.source, value="alert",
                        state="normal" if alert else "disabled").pack(side="left", padx=(10, 0))
        if not alert and self.source.get() == "alert":
            self.source.set("exercise")
        inputs = ttk.Frame(frame)
        inputs.pack(anchor="w", pady=(6, 0))
        ttk.Label(inputs, text="Water depth (m)").grid(row=0, column=0, sticky="w")
        depth = ttk.Entry(inputs, textvariable=self.depth, width=7)
        depth.grid(row=0, column=1, padx=(6, 14))
        ttk.Label(inputs, text="Anchor (t)").grid(row=0, column=2, sticky="w")
        ttk.Entry(inputs, textvariable=self.mass, width=5).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(inputs, text="Lines for").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(inputs, textvariable=self.platform, values=list(PLATFORM_NAMES.values()),
                     state="readonly", width=26).grid(row=1, column=1, columnspan=3, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Label(frame, text="Empty depth: the route's minimum depth, or 50 m if unknown (assumptions).",
                  style="Muted.TLabel", wraplength=WRAP).pack(anchor="w", pady=(2, 0))
        actions = ttk.Frame(frame)
        actions.pack(anchor="w", pady=(6, 0))
        ttk.Button(actions, text="Plan search", command=self.plan_search).pack(side="left")
        ttk.Button(actions, text="Clear", command=self.clear_plan).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(actions, text="Show on map", variable=self.show_plan,
                        command=self._redraw).pack(side="left", padx=(10, 0))
        if self.plan_error:
            ttk.Label(frame, text=self.plan_error, foreground=PLAN, wraplength=WRAP).pack(anchor="w", pady=(6, 0))
        result = self.plan
        if not result:
            return
        text = [result["subject"], result["start_reason"],
                (f"Corridor {result['length_km']:.1f} km × {result['width_m']:.0f} m: half-width "
                 f"{survey_plan.AIS_ERROR_M:g} m AIS error + {survey_plan.CHAIN_REACH_PER_DEPTH:g} × "
                 f"{result['depth_m']:g} m chain reach + {survey_plan.MARGIN_M:g} m margin; depth {result['depth_source']}."),
                (f"A {result['mass_t']:g} t anchor is detectable within about {result['r_max_m']:.0f} m "
                 f"at {result['threshold_nt']:g} nT.")]
        ttk.Label(frame, text="\n".join(line for line in text if line), wraplength=WRAP,
                  justify="left").pack(anchor="w", pady=(8, 4))
        table = ttk.Treeview(frame, columns=("platform", "spacing", "lines", "km", "hours"), show="headings", height=3)
        for column, title, width in (("platform", "Platform", 150), ("spacing", "Spacing", 62), ("lines", "Lines", 46),
                                     ("km", "Line-km", 62), ("hours", "Hours", 90)):
            table.heading(column, text=title)
            table.column(column, width=width, anchor="w", stretch=column == "platform")
        for row in result["platforms"]:
            if row["status"] == "cannot detect":
                values = (PLATFORM_NAMES[row["id"]], "—", "—", "—", "cannot detect")
            else:
                hours = f"{row['hours']:.1f}" + (f" · {row['sorties']} flights" if row.get("sorties") else "")
                if row["status"] != "ok":
                    hours += " · " + row["status"]
                values = (PLATFORM_NAMES[row["id"]], f"{row['spacing_m']:.0f} m", row["lines"], f"{row['line_km']:.0f}", hours)
            table.insert("", "end", values=values)
        table.pack(fill="x")
        notes = [row["note"] for row in result["platforms"] if row["note"]]
        priorities = []
        for item in result["priorities"]:
            box = item["box"]
            first = (f"; first {survey_plan.PRIORITY_BOX_KM:g} km: {box['hours']:.1f} h"
                     if box.get("hours") is not None else "")
            priorities.append(f"{item['rank']}. {item['text']} {item['lat']:.4f}, {item['lon']:.4f}{first}")
        ttk.Label(frame, text="\n".join(notes + priorities), wraplength=WRAP, justify="left").pack(anchor="w", pady=(6, 0))
        save = ttk.Frame(frame)
        save.pack(anchor="w", pady=(6, 0))
        ttk.Button(save, text="Save plan (GeoJSON)", command=self.save_plan).pack(side="left")
        if self.saved_path:
            ttk.Label(save, text=f"Saved {self.saved_path.name}", style="Muted.TLabel").pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="\n".join(result["notes"]), style="Muted.TLabel", wraplength=WRAP,
                  justify="left").pack(anchor="w", pady=(6, 0))

    # --- Live storm data -------------------------------------------------------------------------
    def toggle_live(self) -> None:
        self.generation += 1
        self._cancel_refresh()
        if self.live.get():
            self.message = "Loading NOAA SWPC Kp and Valentia…"
            self._show_chip()
            self._request(force_valentia=True)
        else:
            self.status, self.kp_rows, self.val_rows, self._val_fetched = None, None, None, -1e9
            self.message = "Live magnetic data off · no network requests"
            self._hide_chip()
        self.refresh_storm()

    def _cancel_refresh(self) -> None:
        if self._refresh_after is not None:
            try:
                self.app.root.after_cancel(self._refresh_after)
            except tk.TclError:
                pass
            self._refresh_after = None

    def _request(self, force_valentia: bool = False) -> None:
        generation = self.generation
        want_valentia = force_valentia or time.monotonic() - self._val_fetched >= geomag.REFRESH_VAL_S
        fetch_kp, fetch_valentia = self.fetch_kp, self.fetch_valentia

        def work() -> None:
            now = datetime.now(timezone.utc)
            result: dict = {"now": now}
            try:
                result["kp"] = fetch_kp()
            except Exception as error:  # network, HTTP and parse failures all mean "unavailable"
                result["kp_error"] = error
            if want_valentia:
                try:
                    result["val"] = fetch_valentia(now)
                except Exception as error:
                    result["val_error"] = error
            self.queue.put((generation, result))

        self.executor.submit(work)
        self._refresh_after = self.app.root.after(geomag.REFRESH_KP_S * 1000, self._request)

    def _poll(self) -> None:
        while True:
            try:
                generation, result = self.queue.get_nowait()
            except queue.Empty:
                break
            if generation == self.generation and self.live.get():
                self.apply(result)
        try:
            self._poll_after = self.app.root.after(500, self._poll)
        except tk.TclError:
            self._poll_after = None

    def apply(self, result: dict) -> None:
        """Merge one fetch into the kept rows and recompute the status on the UI thread."""
        if "kp" in result:
            self.kp_rows = result["kp"]
        if "val" in result:
            self.val_rows, self._val_fetched = result["val"], time.monotonic()
        status = geomag.assess(self.kp_rows, self.val_rows, result["now"])
        problems = [f"{name} unavailable ({type(result[key]).__name__})"
                    for key, name in (("kp_error", "NOAA SWPC"), ("val_error", "Valentia")) if key in result]
        if status:
            self.status = self.cached = status
            self.message = " · ".join([f"Updated {result['now']:%H:%M} UTC · Kp every minute, Valentia every 5 min"] + problems)
            try:
                geomag.save_cache(self.cache_path, status)
            except OSError:
                pass
        else:
            self.message = " · ".join(problems or ["Magnetic data unavailable"]) + " · retrying in 1 min"
        self._update_chip()
        self.refresh_storm()

    def _show_chip(self) -> None:
        bar = getattr(self.app, "header_bar", None)
        if bar is None or self.chip is not None:
            return
        self.chip = ctk.CTkLabel(bar, text="GEOMAG · loading", text_color=MUTED, fg_color=CONTROL, corner_radius=8,
                                 height=30, font=ctk.CTkFont("Segoe UI", 12), cursor="hand2")
        self.chip.pack(side="right", padx=6, ipadx=8)
        self.chip.bind("<Button-1>", lambda _event: self.app.open_window("magnetics"))

    def _update_chip(self) -> None:
        if not self._alive(self.chip):
            return
        status = self.status
        self.chip.configure(text="GEOMAG · " + geomag.summary(status) if status else "GEOMAG · unavailable",
                            text_color=TIER_COLOURS[status["tier"]] if status else MUTED)

    def _hide_chip(self) -> None:
        if self._alive(self.chip):
            self.chip.destroy()
        self.chip = None

    # --- Seabed search plan ----------------------------------------------------------------------
    def selected_alert(self) -> dict | None:
        board = getattr(self.app, "alert_board", None)
        selected = getattr(board, "selected", None)
        return board.by_id.get(selected) if board is not None and selected else None

    def plan_inputs(self) -> tuple[list, list, str, float | None]:
        """Track, cable path, a subject line and the route's minimum depth for the chosen source."""
        app = self.app
        if self.source.get() == "alert":
            item = self.selected_alert()
            if item is None:
                raise ValueError("Select an alert in the list first.")
            track = list(item.get("track") or []) + [(item["lat"], item["lon"])]
            path = line_path(item.get("line_id"), getattr(app, "scenario", None))
            if len(path) < 2:
                raise ValueError("The selected alert has no cable route to plan against.")
            cable = next((c for c in (getattr(app, "scenario", None) or {}).get("cables", [])
                          if c.get("id") == item.get("line_id")), {})
            return track, path, f"Alert: {item.get('title', item['id'])}", cable.get("min_depth_m")
        scenario = getattr(app, "scenario", None) or {}
        start = scenario.get("t0_utc")
        offset = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() if start else 0.0
        now = getattr(app, "position_s", None)
        track = [{**fix, "t": fix["t"] + offset} for fix in app.vessel["track"] if now is None or fix["t"] <= now]
        if not track:
            raise ValueError("The exercise vessel has no fixes yet at this replay time.")
        subject = (f"Exercise vessel {app.vessel.get('name', '')} at replay time ({app.vessel.get('label', 'simulated')}) · "
                   f"{app.cable.get('name', 'exercise cable')}")
        return track, app.cable["path"], subject, app.cable.get("min_depth_m")

    def plan_search(self) -> None:
        try:
            track, path, subject, route_depth = self.plan_inputs()
            depth = _number(self.depth.get(), "Water depth")
            mass = _number(self.mass.get(), "Anchor mass") or survey_plan.DEFAULT_MASS_T
            if depth is not None:
                source = "operator entry"
            elif route_depth:
                depth, source = float(route_depth), "the route's minimum depth (scenario)"
            else:
                source = ""
            platform = next((key for key, name in PLATFORM_NAMES.items() if name == self.platform.get()), "usv")
            self.plan = survey_plan.plan(track, path, depth_m=depth, mass_t=mass, platform_id=platform,
                                         subject=subject, depth_source=source)
            self.plan_error = None
        except ValueError as error:
            self.plan, self.plan_error = None, str(error)
        self.saved_path = None
        self.refresh_plan()
        self._redraw()

    def clear_plan(self) -> None:
        self.plan, self.plan_error, self.saved_path = None, None, None
        self.refresh_plan()
        self._redraw()

    def save_plan(self) -> Path | None:
        if not self.plan:
            return None
        path = self.data_dir / f"seabed-plan-{self.plan['created']:%Y%m%dT%H%M%SZ}.geojson"
        try:
            write_json(path, survey_plan.to_geojson(self.plan))
        except OSError as error:
            self.plan_error = f"Could not save the plan ({type(error).__name__})"
            path = None
        self.saved_path = path
        self.refresh_plan()
        return path

    # --- Map -------------------------------------------------------------------------------------
    def _redraw(self) -> None:
        draw = getattr(self.app, "_draw_map", None)
        if draw is not None:
            draw(force_static=True)

    def draw(self) -> None:
        result = self.plan
        if not result or not self.show_plan.get():
            return
        app, canvas = self.app, self.app.map
        corridor = result["corridor"]
        if len(corridor) > 2:
            canvas.create_line(*app._points(corridor + corridor[:1]), fill=PLAN, width=2, dash=(6, 4), tags=(TAG,))
        for line in result["lines"]:
            if len(line) > 1:
                canvas.create_line(*app._points(line), fill=PLAN_LINE, width=1, tags=(TAG,))
        for item in result["priorities"]:
            x, y = app._project(item["lat"], item["lon"])
            canvas.create_oval(x - 9, y - 9, x + 9, y + 9, fill=BG, outline=PLAN, width=2, tags=(TAG,))
            canvas.create_text(x, y, text=str(item["rank"]), fill=PLAN, font=("Segoe UI Semibold", 9), tags=(TAG,))
            if item["rank"] == 1 and getattr(app, "map_zoom", 0) >= 8:
                canvas.create_text(x + 14, y - 12, anchor="w", text="SEABED SEARCH PLAN · ASSUMPTIONS", fill=PLAN,
                                   font=("Segoe UI Semibold", 9), tags=(TAG,))

    def close(self) -> None:
        self.generation += 1
        self._cancel_refresh()
        if self._poll_after is not None:
            try:
                self.app.root.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        self._hide_chip()
