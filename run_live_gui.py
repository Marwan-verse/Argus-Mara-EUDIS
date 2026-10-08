"""Open the team's native dashboard on a read-only shared AIS server.

Usage: python run_live_gui.py --server https://your-service.up.railway.app
       python run_live_gui.py --server http://localhost:8000 --check

The offline exercise remains in run_gui.py. This separate mode shows received
observations only, including a clearly labelled simulated development feed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from argus.live_client import LivePoller, LiveState, fetch_json, server_url
import run_gui as ui

ROOT = Path(__file__).resolve().parent
FEED_STATUS = {"no_key": "Waiting for AIS key", "live": "Receiving AIS", "connecting": "Connecting",
               "reconnecting": "Reconnecting", "auth_error": "AIS authentication failed",
               "archive_error": "Archive unavailable", "stopping": "Stopping"}


def observation_age(seconds: float | None) -> str:
    if seconds is None:
        return "Unavailable"
    seconds = max(0, seconds)
    if seconds < 60:
        return "< 1 min"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes:02d} min"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours:02d} h"


class LiveAISApp(ui.ArgusApp):
    """The existing white shell, map navigation and directories in Live mode."""

    def __init__(self, root: ctk.CTk, address: str, poller: LivePoller | None = None):
        # The exercise constructor requires a fictional alert. Build the same
        # shell from neutral state without loading either exercise contract.
        self.root = root
        self.address = server_url(address)
        self.state = LiveState()
        self.connection = "connecting"
        self._ui_thread = threading.get_ident()
        self._closed = False
        self._last_render = 0
        self._server_clock_s = self.state.generated_s
        self._server_clock_monotonic = time.monotonic()
        self._fitted_initial = False
        self.selected_mmsi = None
        self.vessel = {"name": "Live AIS", "track": []}
        self.scenario = {"name": "Shared AIS observations", "vessels": [], "cables": [],
                         "detections": [], "assets": []}
        self.alert = self.cable = self.approved = None
        self.duration = 1
        self.position_s = 0
        self.rate = tk.IntVar(root, value=1)
        self.playing = False
        self._moving_scale = False
        self._map_size = (0, 0)
        self.map_center, self.map_zoom = (53.25, -10.75), 5
        self.map_mode = tk.StringVar(root, value="Offline coastline")
        self.map_layers = {name: tk.BooleanVar(root, value=enabled) for name, enabled in (
            ("Live AIS positions", True), ("World ports", True), ("Historical cable routes", False))}
        self.map_tool = None
        self.map_note_points, self.measure_points, self.measurement_line = [], [], []
        self._drag_state = None
        self.selected_port = self.selected_cable = None
        self._port_clusters = {}
        self._port_refresh_after = None
        self._static_key = None
        self._tile_images, self._tile_retry_after = {}, {}
        self._tile_pending = set()
        self._tile_queue = queue.Queue()
        self._tile_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="argus-unused-tile")
        self._tile_refresh_after = None
        self._tile_status = "Offline"
        self._tile_cache = ROOT / ".unused-map-cache"
        self._last_tile_key = None
        self._panel_widgets, self._panel_locations = {}, {}
        self._panel_titles = {"contacts": "Vessel directory", "timeline": "Connection",
            "responses": "Observation limits", "layers": "Map layers", "world_data": "Reference data",
            "ports": "Port directory", "cables": "Cable directory", "notes": "Map notes",
            "evidence": "Live data provenance"}
        self._decision_choice = tk.StringVar(root, value="")
        self._decision_acknowledged = tk.BooleanVar(root, value=False)
        self._dock_drag = None
        self._bottom_visible = False
        self._active_dock_location = "right"
        self._initial_split_set = False
        self.coastline = json.loads((ROOT / "ui/assets/coastline.json").read_text(encoding="utf-8"))
        self.coastline_rings = []
        for ring in self.coastline.get("rings", []):
            if len(ring) >= 3:
                lons, lats = zip(*ring)
                self.coastline_rings.append((ring, (min(lons), min(lats), max(lons), max(lats))))
        self.world_land, ports, cables = ui.load_world_assets(ROOT)
        self.world_ports, self.world_cables = ports["ports"], cables["cables"]
        self.land_rings = {}
        for level, rings in self.world_land["levels"].items():
            self.land_rings[level] = []
            for ring in rings:
                lons, lats = zip(*ring)
                self.land_rings[level].append((ring, (min(lons), min(lats), max(lons), max(lats))))
        super()._configure_window()
        self.root.title("Argus Mara — shared live AIS")
        super()._build_modern()
        self._adapt_live_shell()
        self.render()
        self.poller = poller or LivePoller(self.address)
        self.poller.start()
        self.root.after(150, self._poll_live)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _set_initial_split(self, _event=None):
        if hasattr(self, "main_split") and len(self.main_split.panes()) >= 2:
            super()._set_initial_split(_event)

    @staticmethod
    def _children(widget):
        for child in widget.winfo_children():
            yield child
            yield from LiveAISApp._children(child)

    def _adapt_live_shell(self):
        replacements = {
            "OPERATOR CONSOLE": "LIVE AIS CONSOLE", "Maritime situation": "Live maritime traffic",
            "Fictional replay  /  Irish Sea  /  operator review": "Shared server  /  received UTC  /  live observations",
            "WATCH STATUS": "CONNECTION", "EXPECTED TO CABLE": "MAPPED VESSELS",
            "DISTANCE AT ALERT": "TOTAL CONTACTS", "REPLAY BEAT": "FEED STATUS",
            "SIMULATED EXERCISE\nNo operational action sent": "LIVE AIS OBSERVATIONS\nReceived positions only",
            "◉   Vessel details": "◉   Vessel directory", "◷   Timeline": "◷   Connection",
            "▣   Evidence review": "▣   Data provenance", "✓   Response board": "✓   Observation limits",
            "⊞   Fit exercise": "⊞   Fit received AIS", "Situation map": "Live AIS map",
            "Operator panels": "Observation panels",
        }
        for widget in list(self._children(self.root)):
            if not isinstance(widget, (ctk.CTkLabel, ctk.CTkButton)):
                continue
            text = widget.cget("text")
            if text in replacements:
                widget.configure(text=replacements[text])
            if text == "  •  Live AIS":
                self.map_vessel_label = widget
            if text in ("Restart", "Jump to alert", "Speed"):
                widget.pack_forget()
        self.map_selector.configure(values=["Offline coastline"])
        self.speed_selector.pack_forget()
        self.timeline.pack_forget()
        # With no replay beats the upstream empty frame would keep its default
        # height. Hide it so Live retains a compact bottom tool strip.
        for child in self.timeline.master.winfo_children():
            if child not in (self.timeline, self.play_button.master):
                child.pack_forget()
        self.play_button.configure(text="Live", state="disabled")
        overview = self.root.nametowidget(self.right_notebook.tabs()[0])
        self.right_notebook.tab(overview, text="Live AIS")
        for child in overview.winfo_children():
            child.destroy()
        content = ctk.CTkScrollableFrame(overview, fg_color=ui.CARD, corner_radius=0)
        content.pack(fill="both", expand=True)
        ctk.CTkLabel(content, text="Shared live AIS", text_color=ui.INK,
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).pack(anchor="w", pady=(5, 10))
        self.live_status_label = self._info_label(content, ui.TEAL)
        ctk.CTkButton(content, text="Find a vessel by name or MMSI",
            command=lambda: self.open_window("contacts"), fg_color=ui.PURPLE).pack(fill="x", pady=12)
        ctk.CTkLabel(content, text="Selected vessel", text_color=ui.INK,
                     font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(anchor="w")
        self.selected_name_label = self._info_label(content, ui.INK)
        self.selected_fix_label = self._info_label(content, ui.INK)
        self.selected_age_label = self._info_label(content, ui.AMBER)
        ctk.CTkButton(content, text="Center selected vessel", command=self.center_vessel,
                     fg_color="#edf3fb", text_color=ui.TEAL).pack(fill="x", pady=10)
        self.live_note_label = self._info_label(content, ui.MUTED)
        self.live_note_label.configure(text="Markers show the latest received position, including old observations. "
            "No interpolation or predicted movement.\n\nNo detector, threat assessment, countdown or operational response "
            "is evaluated in this viewer. Grey markers exceed the server's freshness interval.\n\n"
            "History is recorded on the server; this window keeps only the latest observation per contact.")

    @staticmethod
    def _info_label(parent, color):
        label = ctk.CTkLabel(parent, text="", text_color=color, justify="left", wraplength=340,
                            font=ctk.CTkFont("Segoe UI", 11))
        label.pack(anchor="w", pady=(6, 8))
        return label

    def _resize_situation(self, event):
        for name in ("live_status_label", "selected_name_label", "selected_fix_label",
                     "selected_age_label", "live_note_label"):
            label = getattr(self, name, None)
            if label is not None:
                label.configure(wraplength=max(210, event.width - 52))

    def _poll_live(self):
        if self._closed:
            return
        assert threading.get_ident() == self._ui_thread, "Live updates must run on the Tk thread."
        changed = False
        while True:
            try:
                kind, value = self.poller.events.get_nowait()
            except queue.Empty:
                break
            if kind == "data":
                try:
                    applied = self.state.apply(value)
                    changed = applied or changed
                    if applied:
                        self._server_clock_s = self.state.generated_s
                        self._server_clock_monotonic = time.monotonic()
                    self.connection = "connected"
                except ValueError:
                    self.connection = "invalid response"
            else:
                self.connection = value
        now = datetime.now(timezone.utc).timestamp()
        if changed or now - self._last_render >= 1:
            self._last_render = now
            self.render()
            if changed:
                self._refresh_vessel_directory()
                if not self._fitted_initial and self._positions() and self._map_size[0] > 100:
                    self._fitted_initial = True
                    self.fit_map()
        self.root.after(150, self._poll_live)

    def _positions(self):
        return [v for v in self.state.vessels.values() if v["received_s"] is not None]

    def _age(self, vessel):
        stamp = vessel["received_s"]
        now = self._server_clock_s + time.monotonic() - self._server_clock_monotonic
        return None if stamp is None else max(0, now - stamp)

    def _selected(self):
        return self.state.vessels.get(self.selected_mmsi)

    def select_vessel(self, mmsi):
        self.selected_mmsi = mmsi if mmsi in self.state.vessels else None
        self.render()

    def render(self):
        if not hasattr(self, "selected_name_label"):
            return
        feed = self.state.feed
        now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M:%S UTC")
        self.time_label.configure(text=now)
        self.summary_state_label.configure(text=self.connection.title())
        self.summary_countdown_label.configure(text=f"{len(self._positions()):,}")
        self.summary_distance_label.configure(text=f"{len(self.state.vessels):,}")
        status = FEED_STATUS.get(feed["status"], feed["status"].replace("_", " ").title())
        self.summary_beat_label.configure(text=status)
        label = feed.get("label", "real").upper()
        received = feed.get("last_received_utc") or "Waiting for the first message"
        self.live_status_label.configure(text=f"{label} AIS · server {self.connection}\n"
            f"Feed: {status}\nLast message: {received}\n"
            f"Last position: {feed.get('last_position_utc') or 'Not received'}",
            text_color=ui.TEAL if self.connection == "connected" and feed["status"] == "live" else ui.AMBER)
        self.beat_label.configure(text=f"{label} · updates every 2 s")
        selected = self._selected()
        self.map_vessel_label.configure(text="  •  " + (selected["name"] if selected else
            f"{len(self.state.vessels):,} received contacts"))
        if selected is None:
            self.selected_name_label.configure(text="Select a marker or search the vessel directory.")
            self.selected_fix_label.configure(text="")
            self.selected_age_label.configure(text="")
        else:
            self.selected_name_label.configure(text=f"{selected['name']}\nMMSI {selected['mmsi']} · "
                f"{selected['type']} · {selected['label']}")
            if selected["received_s"] is None:
                self.selected_fix_label.configure(text="Static AIS particulars received; no position is available.")
                self.selected_age_label.configure(text="No received position")
            else:
                speed = "Unavailable" if selected["sog_kn"] is None else f"{selected['sog_kn']:.1f} kn"
                course = "Unavailable" if selected["cog_deg"] is None else f"{selected['cog_deg']:.1f}°"
                self.selected_fix_label.configure(text=f"Last received: {selected['received_utc']}\n"
                    f"{ui.coordinates(selected['lat'], selected['lon'])}\n"
                    f"Speed over ground: {speed}\nCourse over ground: {course}")
                self.selected_age_label.configure(text=f"Observation age: {observation_age(self._age(selected))}")
        self._refresh_vessel_values()
        self._draw_map()

    def _populate_panel(self, key, frame):
        if key in ("ports", "cables", "notes"):
            super()._populate_panel(key, frame)
            return
        ttk.Label(frame, text=self._panel_titles[key], style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        if key == "contacts":
            self._build_vessel_directory(frame)
        elif key == "layers":
            for name, variable in self.map_layers.items():
                ttk.Checkbutton(frame, text=name, variable=variable,
                    command=lambda: self._draw_map(force_static=True)).pack(anchor="w", pady=5)
            ttk.Label(frame, text="Ports and historical cable routes are display context only. "
                "They never calculate alerts or countdowns.", wraplength=340, style="Muted.TLabel").pack(pady=12)
        else:
            details = (f"Server: {self.address}\n\nLatest observations arrive over HTTPS; no AIS provider key "
                "is required or stored by the client. The server saves the archive independently of this window. "
                "The connection card shows upstream status and the latest received UTC.\n\n"
                "Every vessel carries a real or simulated provenance label. A stale marker does not prove AIS "
                "was intentionally switched off. Positions are never interpolated or predicted. No operational "
                "action is available.\n\nNatural Earth: public domain. NGA ports: real reference locations. "
                "Historical TeleGeography cables: reconstructed stylized display, CC BY-NC-SA 3.0; "
                "noncommercial only, disabled by default.")
            ttk.Label(frame, text=details, wraplength=340, justify="left", style="Muted.TLabel").pack(anchor="w")

    def _build_vessel_directory(self, frame):
        ttk.Label(frame, text="Search vessel name or MMSI. Static-only contacts have no map marker.",
                  wraplength=340, style="Muted.TLabel").pack(anchor="w")
        self.vessel_query = tk.StringVar(self.root)
        ttk.Entry(frame, textvariable=self.vessel_query).pack(fill="x", pady=10)
        self.vessel_count_label = ttk.Label(frame, style="Muted.TLabel")
        self.vessel_count_label.pack(anchor="w", pady=(0, 8))
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True)
        self.vessel_table = ttk.Treeview(holder, columns=("name", "mmsi", "speed", "age", "label"),
                                        show="headings", selectmode="browse", height=12)
        for column, title, width in (("name", "Vessel", 150), ("mmsi", "MMSI", 95),
                ("speed", "SOG", 65), ("age", "Fix age", 90), ("label", "Evidence", 75)):
            self.vessel_table.heading(column, text=title)
            self.vessel_table.column(column, width=width, minwidth=60, stretch=column == "name")
        vertical = ttk.Scrollbar(holder, orient="vertical", command=self.vessel_table.yview)
        horizontal = ttk.Scrollbar(holder, orient="horizontal", command=self.vessel_table.xview)
        self.vessel_table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        self.vessel_table.pack(fill="both", expand=True)
        self._table_refreshing = False
        self.vessel_table.bind("<<TreeviewSelect>>", self._directory_selection)
        self.vessel_table.bind("<Double-1>", lambda _event: self.center_vessel())
        self.vessel_query.trace_add("write", lambda *_: self._refresh_vessel_directory())
        ttk.Button(frame, text="Center selected vessel", command=self.center_vessel).pack(anchor="w", pady=10)
        self._refresh_vessel_directory()

    def _row(self, vessel):
        speed = "Unavailable" if vessel["sog_kn"] is None else f"{vessel['sog_kn']:.1f} kn"
        return (vessel["name"], vessel["mmsi"], speed,
                observation_age(self._age(vessel)), vessel["label"])

    def _refresh_vessel_directory(self):
        if not hasattr(self, "vessel_table") or not self.vessel_table.winfo_exists():
            return
        query = self.vessel_query.get().strip().casefold()
        vessels = sorted((v for v in self.state.vessels.values()
            if query in (v["name"] + " " + v["mmsi"]).casefold()),
            key=lambda v: (v["name"].casefold(), v["mmsi"]))
        desired = {v["mmsi"] for v in vessels}
        self._table_refreshing = True
        for identifier in self.vessel_table.get_children():
            if identifier not in desired:
                self.vessel_table.delete(identifier)
        for index, vessel in enumerate(vessels):
            identifier = vessel["mmsi"]
            if self.vessel_table.exists(identifier):
                self.vessel_table.item(identifier, values=self._row(vessel))
                self.vessel_table.move(identifier, "", index)
            else:
                self.vessel_table.insert("", "end", iid=identifier, values=self._row(vessel))
        if self.selected_mmsi in desired:
            self.vessel_table.selection_set(self.selected_mmsi)
        self.vessel_count_label.configure(text=f"{len(vessels):,} of {len(self.state.vessels):,} contacts")
        self._table_refreshing = False

    def _refresh_vessel_values(self):
        if hasattr(self, "vessel_table") and self.vessel_table.winfo_exists():
            for identifier in self.vessel_table.get_children():
                vessel = self.state.vessels.get(identifier)
                if vessel:
                    self.vessel_table.item(identifier, values=self._row(vessel))

    def _directory_selection(self, _event=None):
        if not self._table_refreshing:
            selection = self.vessel_table.selection()
            if selection:
                self.select_vessel(selection[0])

    def center_vessel(self):
        vessel = self._selected()
        if vessel and vessel["received_s"] is not None:
            self._change_map_center((vessel["lat"], vessel["lon"]))
        else:
            self.open_window("contacts")

    def fit_map(self):
        self._fit_points([(v["lat"], v["lon"]) for v in self._positions()])

    def _draw_map(self, force_static=False):
        if not hasattr(self, "map"):
            return
        width, height = self.map.winfo_width(), self.map.winfo_height()
        if width < 100 or height < 100:
            return
        self._map_size = (width, height)
        static_key = (width, height, self.map_zoom, self.map_center,
            self.map_layers["World ports"].get(), self.map_layers["Historical cable routes"].get(),
            self.selected_port, self.selected_cable)
        if force_static or self._static_key != static_key:
            self.map.delete("all")
            self.map.create_rectangle(0, 0, width, height, fill=ui.SEA, outline="")
            self._draw_graticule(width, height)
            self._draw_global_land(width, height)
            if self.map_layers["Historical cable routes"].get():
                self._draw_world_cables(width, height)
            if self.map_layers["World ports"].get():
                occupied = []
                for _priority, kind, name, x, y in self._draw_world_ports(width, height):
                    self._draw_map_callout(name, x, y, kind, occupied)
            self._static_key = static_key
        self.map.delete("live-ais")
        visible = 0
        if self.map_layers["Live AIS positions"].get():
            for vessel in self._positions():
                x, y = self._project(vessel["lat"], vessel["lon"])
                if not -15 <= x <= width + 15 or not -15 <= y <= height + 15:
                    continue
                visible += 1
                selected = vessel["mmsi"] == self.selected_mmsi
                age = self._age(vessel)
                color = ui.PURPLE if selected else "#789da9" if age > self.state.feed.get("stale_seconds", 900) else ui.TEAL
                radius = 7 if selected else 3.5
                tags = ("live-ais", "live-vessel:" + vessel["mmsi"])
                self.map.create_oval(x-radius, y-radius, x+radius, y+radius,
                    fill=color, outline="white", width=1, tags=tags)
                if selected:
                    self.map.create_text(x+12, y-12, text=f"{vessel['name']} · {vessel['label']}\n"
                        f"Age {observation_age(age)}", anchor="sw", fill=ui.INK,
                        font=("Segoe UI", 9), tags="live-ais")
        if not self._positions():
            self.map.create_text(width/2, height/2, text="Waiting for received AIS positions",
                fill=ui.MUTED, font=("Segoe UI", 14), tags="live-ais")
        for index, point in enumerate(self.map_note_points, 1):
            x, y = self._project(*point)
            self.map.create_text(x, y, text=f"● {index}", fill=ui.INK, tags="live-ais")
        for point in self.measure_points:
            x, y = self._project(*point)
            self.map.create_oval(x-4, y-4, x+4, y+4, fill=ui.AMBER, tags="live-ais")
        if self.measurement_line:
            self.map.create_line(*self._points(self.measurement_line), fill=ui.AMBER,
                width=2, dash=(5, 3), tags="live-ais")
        self.map_status_label.configure(text=f"{visible:,} markers in view · last received fixes · drag / scroll to zoom")
        attribution = "Natural Earth · public domain"
        if self.map_layers["World ports"].get():
            attribution += " · NGA ports"
        if self.map_layers["Historical cable routes"].get():
            attribution += " · historical cables: context"
        self.map_attribution_label.configure(text=attribution)

    def _inspect_map_item(self, event):
        for item in reversed(self.map.find_overlapping(event.x-6, event.y-6, event.x+6, event.y+6)):
            for tag in self.map.gettags(item):
                if tag.startswith("live-vessel:"):
                    self.select_vessel(tag.split(":", 1)[1])
                    return
        super()._inspect_map_item(event)

    def _map_motion(self, event):
        if not self.map_tool:
            for item in reversed(self.map.find_overlapping(event.x-4, event.y-4, event.x+4, event.y+4)):
                for tag in self.map.gettags(item):
                    if tag.startswith("live-vessel:"):
                        vessel = self.state.vessels.get(tag.split(":", 1)[1])
                        if vessel:
                            self.map_status_label.configure(text=f"{vessel['label'].title()} · {vessel['name']} · "
                                f"MMSI {vessel['mmsi']} · age {observation_age(self._age(vessel))}")
                            return
        super()._map_motion(event)

    def open_tools_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        for key, title in self._panel_titles.items():
            menu.add_command(label=title, command=lambda panel=key: self.open_window(panel, "bottom"))
        menu.add_separator()
        menu.add_command(label="Fit received AIS positions", command=self.fit_map)
        menu.add_command(label="Add session map note", command=lambda: self._set_map_tool("pin"))
        menu.add_command(label="Measure distance", command=lambda: self._set_map_tool("measure"))
        menu.add_command(label="Clear notes and measurement", command=self.clear_map_notes)
        menu.tk_popup(self.tools_plus.winfo_rootx(), self.tools_plus.winfo_rooty())

    def review_evidence(self):
        self.open_window("evidence", self._active_dock_location)

    def review_response(self):
        self.open_window("responses", self._active_dock_location)

    def _schedule_tile_refresh(self, delay_ms=240):
        pass  # Live viewer uses local reference geography only.

    def _change_map_mode(self, _value=None):
        self.map_mode.set("Offline coastline")
        self._draw_map(force_static=True)

    def _beats(self):
        return []

    def _space(self, _event):
        pass

    def _scale_changed(self, _value):
        pass

    def close(self):
        self._closed = True
        self.poller.stop()
        super().close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="Read-only shared HTTPS AIS server")
    parser.add_argument("--check", action="store_true", help="Check server access and local assets without opening a window")
    args = parser.parse_args()
    try:
        address = server_url(args.server)
        ui.load_world_assets(ROOT)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Unable to open shared AIS: {error}\n")
    if args.check:
        try:
            state = LiveState()
            state.apply(fetch_json(address + "/api/v1/vessels"))
        except Exception:
            parser.exit(1, "Shared AIS server is unavailable or returned invalid data.\n")
        positions = sum(vessel["received_s"] is not None for vessel in state.vessels.values())
        status = FEED_STATUS.get(state.feed["status"], "Status unavailable")
        print(f"Shared AIS server reachable: {len(state.vessels):,} contacts, {positions:,} mapped positions.\n"
              f"Feed: {status}. Provenance: {state.feed.get('label', 'real')}. No AIS provider key used.")
        return 0
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    LiveAISApp(root, address)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
