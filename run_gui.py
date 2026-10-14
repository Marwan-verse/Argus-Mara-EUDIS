"""Run the Argus Mara fictional exercise as a native, offline desktop application.

Usage: python run_gui.py
       python run_gui.py --check   # validate local inputs without opening a window

CustomTkinter provides the native dashboard shell. This companion interface reads the same two
JSON contracts as the browser demo. The startup screen offers an isolated local
Docker SOC server or a single offline window. Global Natural Earth
geometry is the default; optional NASA imagery loads only the visible map tiles.
Optional live Met Éireann weather (a point summary plus rain/cloud shading and wind arrows
sampled on a grid) is off by default and is display context only.
The docked AIS tracker connects on demand to an existing shared service and draws
received observations independently of the fictional exercise and its countdown.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape
import json
import math
import os
from pathlib import Path
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from PIL import Image, ImageTk
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from argus import weather
from argus.contracts import validate_alerts, validate_scenario
from argus.countdown import step
from argus.map_view import coordinates, find_ports, geographic_extent, route_name, search_text
from argus.prediction import dark_countdown, last_gap, position_at, reappearance_check, v_max_kn
from desktop_ais import DesktopAIS
import desktop_prediction


ROOT = Path(__file__).resolve().parent
BG = "#0b1118"
CARD = "#141e28"
INK = "#e4ebf0"
MUTED = "#a8b6c2"
LINE = "#2c3d4c"
TEAL = "#47c7da"
AMBER = "#e1b164"
SEA = "#202d39"
PURPLE = "#d1b464"
CONTROL = "#1c2a36"
HOVER = "#283a4a"
MAX_AIS_GAP_S = 120
REAPPEARANCE_SHOW_S = 20 * 60  # How long the map keeps the AIS-return verdict.
TILE_SIZE = 256
MIN_MAP_ZOOM = 1
MAX_MAP_ZOOM = 13
MAX_IMAGERY_ZOOM = 8
ONLINE_MAP = "NASA Blue Marble · online"
TILE_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg"
TILE_USER_AGENT = "ArgusMaraDesktop/0.3 (local offline-first demo)"
WEATHER_HOURS = ("Now", "+1 h", "+2 h", "+3 h", "+6 h", "+9 h", "+12 h")


def tile_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".cache"
    return base / "ArgusMara" / "map-tiles" / "nasa-blue-marble"


def geo_to_world(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    world = TILE_SIZE * (2 ** zoom)
    sin_lat = math.sin(math.radians(lat))
    x = (lon + 180.0) / 360.0 * world
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * world
    return x, y


def world_to_geo(x: float, y: float, zoom: int) -> tuple[float, float]:
    world = TILE_SIZE * (2 ** zoom)
    lon = (x / world) * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * max(0.0, min(float(world), y)) / world
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, ((lon + 180) % 360) - 180


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def load_demo(root: Path = ROOT) -> tuple[dict, dict, dict]:
    scenario = json.loads((root / "demo/scenario.json").read_text(encoding="utf-8"))
    alerts = json.loads((root / "demo/alerts.json").read_text(encoding="utf-8"))
    coastline = json.loads((root / "ui/assets/coastline.json").read_text(encoding="utf-8"))
    validate_scenario(scenario)
    validate_alerts(alerts, scenario)
    if not alerts["alerts"]:
        raise ValueError("The demo has no alert to replay.")
    return scenario, alerts, coastline


def load_world_assets(root: Path = ROOT) -> tuple[dict, dict, dict]:
    land, ports, cables = (
        json.loads((root / f"ui/assets/{name}.json").read_text(encoding="utf-8"))
        for name in ("world_land", "world_ports", "world_cables")
    )
    if not land["levels"]["110m"] or not land["levels"]["50m"]:
        raise ValueError("The global land layer is empty")
    if len(ports["ports"]) != ports["count"] or len(cables["cables"]) != cables["count"]:
        raise ValueError("A global map layer is incomplete")
    return land, ports, cables


def load_irish_ports(root: Path = ROOT) -> dict:
    data = json.loads((root / "ui/assets/irish_ports.json").read_text(encoding="utf-8"))
    rows = data['ports']
    if data.get('label') != 'real' or data.get('count') != len(rows) or not rows:
        raise ValueError('The Irish port catalogue is incomplete')
    if len({p[0] for p in rows}) != len(rows):
        raise ValueError('Irish port identifiers must be unique')
    for identifier, name, lat, lon, country in rows:
        if (not isinstance(identifier, int) or not name or not (-90 <= lat <= 90 and -180 <= lon <= 180)
                or country not in ('IE', 'GB') or str(identifier) not in data['details']):
            raise ValueError('Invalid Irish port reference')
    return data


def clock(seconds: float) -> str:
    value = max(0, math.ceil(seconds))
    return f"{value // 3600:02d}:{value // 60 % 60:02d}:{value % 60:02d}"


def fix_at(track: list[dict], position_s: float) -> dict | None:
    """Interpolate short AIS intervals, but never invent a fix in a reception gap."""
    if not track or position_s < track[0]["t"] or position_s > track[-1]["t"]:
        return None
    before = track[0]
    for after in track:
        if after["t"] == position_s:
            return dict(after)
        if after["t"] > position_s:
            if after["t"] - before["t"] > MAX_AIS_GAP_S:
                return None
            fraction = (position_s - before["t"]) / (after["t"] - before["t"])
            return {
                **before,
                "t": position_s,
                "lat": before["lat"] + (after["lat"] - before["lat"]) * fraction,
                "lon": before["lon"] + (after["lon"] - before["lon"]) * fraction,
            }
        before = after
    return dict(before)


def trail_sections(track: list[dict], position_s: float) -> list[list[tuple[float, float]]]:
    sections: list[list[tuple[float, float]]] = []
    section: list[tuple[float, float]] = []
    previous = None
    for fix in track:
        if fix["t"] > position_s:
            break
        if previous and fix["t"] - previous["t"] > MAX_AIS_GAP_S:
            sections.append(section)
            section = []
        section.append((fix["lat"], fix["lon"]))
        previous = fix
    current = fix_at(track, position_s)
    if current and previous and current["t"] > previous["t"]:
        section.append((current["lat"], current["lon"]))
    if section:
        sections.append(section)
    return sections


def response_status(option: dict, earliest_s: float) -> str:
    if option["eta_s"] is None:
        return "Unavailable"
    return "In time" if option["eta_s"] <= earliest_s else "Too late"


class ArgusApp:
    def __init__(self, root: tk.Tk, scenario: dict, alerts: dict, coastline: dict, soc_client=None):
        self.root = root
        self.soc_client = soc_client
        self.soc_online = bool(soc_client)
        self.scenario = scenario
        self.coastline = coastline
        self.coastline_rings = []
        for ring in coastline.get("rings", []):
            if len(ring) >= 3:
                lons = [point[0] for point in ring]
                lats = [point[1] for point in ring]
                self.coastline_rings.append((ring, (min(lons), min(lats), max(lons), max(lats))))
        self.world_land, ports, cables = load_world_assets()
        self.world_ports = ports["ports"]
        irish = load_irish_ports()
        self.port_metadata = irish["details"]
        self.world_ports.extend(irish["ports"])
        self.irish_port_indices = {i for i, p in enumerate(self.world_ports)
                                  if p[4] == "IE" or str(p[0]) in self.port_metadata}
        self.world_cables = cables["cables"]
        self.selected_port = None
        self.selected_cable = None
        self._port_clusters = {}
        self._port_refresh_after = None
        self.land_rings = {}
        for level, rings in self.world_land["levels"].items():
            self.land_rings[level] = []
            for ring in rings:
                lons, lats = zip(*ring)
                self.land_rings[level].append((ring, (min(lons), min(lats), max(lons), max(lats))))
        self.alert = min(alerts["alerts"], key=lambda item: item["t"])
        self.alerts = alerts["alerts"]
        self.vessel = next(v for v in scenario["vessels"] if v["mmsi"] == self.alert["mmsi"])
        self.cable = next(c for c in scenario["cables"] if c["id"] == self.alert["segment_id"])
        self.duration = max(v["track"][-1]["t"] for v in scenario["vessels"] if v["track"])
        self.position_s = float(self.alert["t"])
        self.rate = tk.IntVar(value=int(scenario.get("replay_speed", 60)))
        self.playing = False
        self.last_frame = time.monotonic()
        self.approved: dict | None = None
        self._moving_scale = False
        self._map_size = (0, 0)
        self._last_second = -1
        self.map_center = (53.25, -11.25)
        self.map_zoom = 6
        self.map_mode = tk.StringVar(value="Offline coastline")
        self.map_layers = {name: tk.BooleanVar(value=True) for name in ("AIS track", "Dark prediction", "Radar contacts", "Cable", "Anchor reach", "Response assets", "World ports", "Historical cable routes", "Simulated alerts", "Rain and cloud", "Wind")}
        self.map_layers["World ports"].set(True)
        self.irish_ports_only = tk.BooleanVar(value=True)
        self.map_tool: str | None = None
        self._map_ping: tuple[float, float] | None = None
        self._ping_after = None
        self._ping_started = 0.0
        self.map_note_points: list[tuple[float, float]] = []
        self.measure_points: list[tuple[float, float]] = []
        self.measurement_line: list[tuple[float, float]] = []
        self._drag_state: dict | None = None
        self._tile_images: dict[tuple[int, int, int], tk.PhotoImage] = {}
        self._tile_pending: set[tuple[int, int, int]] = set()
        self._tile_retry_after: dict[tuple[int, int, int], float] = {}
        self._tile_queue: queue.Queue = queue.Queue()
        self._tile_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="argus-map-tile")
        self._tile_refresh_after = None
        self._tile_cache = tile_cache_root()
        self._tile_status = ""
        self._last_tile_key: tuple[int, float, float, int, int] | None = None
        # Live weather is opt-in so the exercise still runs with the network off.
        self.live_weather = tk.BooleanVar(value=False)
        self.weather_point = tuple(self.cable["path"][len(self.cable["path"]) // 2])
        self._weather: dict | None = None
        self._weather_status = "Live weather off · no network requests"
        self._weather_generation = 0
        self._weather_queue: queue.Queue = queue.Queue()
        self._weather_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="argus-weather")
        self._weather_refresh_after = None
        self.weather_hour = tk.StringVar(value="Now")
        self._weather_grid: tuple[float, list[float], list[float]] | None = None
        self._weather_grid_cache: dict[tuple[float, float], tuple[float, dict | None]] = {}
        self._weather_grid_pending: set[tuple[float, float]] = set()
        self._weather_grid_after = None
        self._weather_field_version = 0
        self._weather_field: dict | None = None
        self._weather_overlay: dict | None = None
        self._weather_view_key: tuple | None = None
        self._panel_widgets: dict[str, ttk.Frame] = {}
        self._panel_locations: dict[str, str] = {}
        self._panel_titles = {
            "contacts": "Vessel details", "timeline": "Timeline and events",
            "responses": "Response board", "layers": "Map layers",
            "world_data": "Global map data",
            "ports": "Port directory", "cables": "Cable directory",
            "notes": "Map notes", "evidence": "Evidence review",
            "decision": "Decision review", "weather": "Live weather",
            "ais": "AIS ship tracker", "sar_plan": "SAR next step",
            "views": "Saved map views",
        }
        self._decision_choice = tk.StringVar(value="")
        self._decision_acknowledged = tk.BooleanVar(value=False)
        self._dock_drag: dict | None = None
        self._bottom_visible = False
        self._active_dock_location = "right"
        self._initial_split_set = False
        self._configure_window()
        self.ais_tracker = DesktopAIS(self, cache_path=ROOT / "data/desktop/ais_latest.json")
        self._build_modern()
        self.render()
        self.root.after(80, self._tick)
        self.root.after(150, self._poll_tiles)
        self.root.after(500, self._poll_weather)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        from desktop_soc import DesktopSOC
        self.soc = DesktopSOC(self)

    def allowed(self, permission: str) -> bool:
        """Offline exercises use public demo files; SOC tools follow server grants."""
        client = getattr(self, 'soc_client', None)
        return client is None or (self.soc_online and client.user is not None and permission in client.user['permissions'])

    def require_tool(self, permission: str) -> bool:
        if self.allowed(permission):
            return True
        messagebox.showinfo('Tool unavailable', 'Your group does not have this tool, or the SOC connection needs to be restored.', parent=self.root)
        return False

    def _configure_window(self) -> None:
        self.root.title("Argus Mara — maritime intelligence")
        ctk.set_appearance_mode("dark")
        ctk.ThemeManager.theme['CTkFont']['family'] = 'Segoe UI'
        ctk.ThemeManager.theme['CTkFont']['size'] = 13
        for name, values in {
            'CTkButton': {'fg_color': [CONTROL, CONTROL], 'hover_color': [HOVER, HOVER], 'text_color': [INK, INK], 'corner_radius': 8},
            'CTkEntry': {'fg_color': [CONTROL, CONTROL], 'border_color': [LINE, LINE], 'text_color': [INK, INK], 'corner_radius': 8},
            'CTkOptionMenu': {'fg_color': [CONTROL, CONTROL], 'button_color': [CONTROL, CONTROL], 'button_hover_color': [HOVER, HOVER], 'text_color': [INK, INK]},
            'DropdownMenu': {'fg_color': [CARD, CARD], 'hover_color': [HOVER, HOVER], 'text_color': [INK, INK]},
        }.items():
            ctk.ThemeManager.theme[name].update(values)
        # Tk sizes point fonts by its own scaling (96 dpi by default), while CustomTkinter scales its
        # widgets by the Windows display scale. Match them, or plain tk text is half size at 200%.
        self.root.tk.call("tk", "scaling", 96 / 72 * ctk.ScalingTracker.get_window_scaling(self.root))
        self.root.geometry("1480x900")
        self.root.minsize(1100, 720)
        self.root.configure(fg_color=BG)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=CARD)
        style.configure("TLabel", background=CARD, foreground=INK, font=("Segoe UI", 11))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 19))
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Countdown.TLabel", font=("Consolas", 31, "bold"), foreground=INK)
        style.configure("TButton", font=("Segoe UI", 11), padding=(12, 8))
        style.configure("TButton", background=CONTROL, foreground=INK, bordercolor=LINE)
        style.map("TButton", background=[("active", HOVER)], foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=BG, foreground=INK, insertcolor=INK)
        style.configure('TEntry', font=('Segoe UI', 11), padding=7)
        style.map('TEntry', bordercolor=[('focus', TEAL), ('!focus', LINE)])
        style.configure('TCombobox', font=('Segoe UI', 11), fieldbackground=CONTROL,
                        foreground=INK, background=CONTROL, arrowcolor=INK, bordercolor=LINE)
        self.root.option_add('*TCombobox*Listbox.background', CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', INK)
        self.root.option_add('*TCombobox*Listbox.selectBackground', HOVER)
        self.root.option_add('*TCombobox*Listbox.selectForeground', INK)
        style.configure('TCheckbutton', font=('Segoe UI', 11))
        style.configure("TCheckbutton", foreground=INK)
        style.configure("TRadiobutton", foreground=INK)
        style.map("TCheckbutton", background=[("active", CONTROL)])
        style.map("TRadiobutton", background=[("active", CONTROL)])
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("TCheckbutton", background=CARD)
        style.configure("TRadiobutton", background=CARD)
        style.configure("Dock.TNotebook", background=CARD, borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure("Dock.TNotebook.Tab", padding=(12, 9), font=("Segoe UI", 11), background=CONTROL, foreground=MUTED)
        style.map("Dock.TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", TEAL)])
        style.configure("TNotebook", background=CARD, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 8), font=("Segoe UI", 9))
        style.configure("TPanedwindow", sashwidth=10, sashrelief="flat", background=BG)
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK, font=('Segoe UI', 11), rowheight=32, borderwidth=0)
        style.configure("Treeview.Heading", background=CONTROL, foreground=MUTED, font=("Segoe UI", 10))
        style.map("Treeview", background=[("selected", "#294254")], foreground=[("selected", INK)])
        self.root.bind("<space>", self._space)

    def _build_modern(self) -> None:
        if hasattr(self, "ais_tracker"):
            from desktop_console import build
            build(self)
        else:
            self._build_dashboard()

    def _build_dashboard(self) -> None:
        """Native dashboard shell around the existing map, replay and movable docks."""
        self.root.configure(fg_color=BG)
        shell = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        shell.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(shell, width=188, fg_color=CARD, corner_radius=0,
                               border_width=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(sidebar, text="◈", text_color=PURPLE,
                     font=ctk.CTkFont("Segoe UI Symbol", 32)).pack(anchor="w", padx=23, pady=(25, 0))
        ctk.CTkLabel(sidebar, text="ARGUS MARA", text_color=PURPLE,
                     font=ctk.CTkFont("Segoe UI", 18, "bold")).pack(anchor="w", padx=23)
        ctk.CTkLabel(sidebar, text="OPERATOR CONSOLE", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 9, "bold")).pack(anchor="w", padx=23, pady=(1, 18))

        def nav(text: str, action, selected: bool = False) -> None:
            ctk.CTkButton(sidebar, text=text, command=action, anchor="w", height=31,
                          corner_radius=5, font=ctk.CTkFont("Segoe UI", 11, "bold" if selected else "normal"),
                          fg_color="#293528" if selected else "transparent",
                          hover_color="#294254", text_color=PURPLE if selected else INK).pack(
                              fill="x", padx=13, pady=2)

        ctk.CTkLabel(sidebar, text="WORKSPACE", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(anchor="w", padx=23, pady=(0, 8))
        nav("◫   Situation", lambda: self.right_notebook.select(0), True)
        nav("◉   Vessel details", lambda: self.open_window("contacts"))
        if hasattr(self, "ais_tracker"):
            nav("△   AIS ship tracker", lambda: self.open_window("ais"))
            nav("◇   SAR next step", lambda: self.open_window("sar_plan"))
        nav("◷   Timeline", lambda: self.open_window("timeline"))
        nav("◇   Map layers", lambda: self.open_window("layers"))
        nav("⚓   Port directory", lambda: self.open_window("ports"))
        nav("⌁   Cable directory", lambda: self.open_window("cables"))
        nav("▣   Evidence review", self.review_evidence)
        nav("✓   Response board", lambda: self.open_window("responses"))
        nav("☁   Live weather", lambda: self.open_window("weather"))
        ctk.CTkFrame(sidebar, height=1, fg_color=LINE).pack(fill="x", padx=22, pady=12)
        ctk.CTkLabel(sidebar, text="MAP SHORTCUTS", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(anchor="w", padx=23, pady=(0, 8))
        nav("⌖   Center vessel", self.center_vessel)
        nav("⊞   Fit exercise", self.fit_map)
        nav("◎   World overview", self.fit_world)
        ctk.CTkLabel(sidebar, text="SIMULATED EXERCISE\nNo operational action sent",
                     text_color=MUTED, justify="left", font=ctk.CTkFont("Segoe UI", 10)).pack(
                         side="bottom", anchor="w", padx=23, pady=24)

        body = ctk.CTkFrame(shell, fg_color=BG, corner_radius=0)
        body.pack(side="left", fill="both", expand=True, padx=(12, 12), pady=(12, 10))
        header = ctk.CTkFrame(body, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(title_box, text="Maritime situation", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 23, "bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Fictional replay  /  Irish Sea  /  operator review",
                     text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(anchor="w")
        self.time_label = ctk.CTkLabel(header, text="", fg_color=CARD, corner_radius=14,
                                       text_color=INK, font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                       height=38)
        self.time_label.pack(side="right", padx=(10, 0), ipadx=12)

        metrics = ctk.CTkFrame(body, fg_color="transparent")
        metrics.pack(fill="x", pady=(0, 16))
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metric")

        def metric(column: int, caption: str, value: str, accent: str) -> ctk.CTkLabel:
            card = ctk.CTkFrame(metrics, fg_color=CARD, corner_radius=6, border_width=1, border_color=LINE)
            card.grid(row=0, column=column, sticky="ew", padx=(0, 9 if column < 3 else 0))
            ctk.CTkFrame(card, width=4, height=41, fg_color=accent, corner_radius=3).pack(
                side="left", padx=(13, 13), pady=13)
            words = ctk.CTkFrame(card, fg_color="transparent")
            words.pack(side="left", fill="x", expand=True, pady=10)
            ctk.CTkLabel(words, text=caption, text_color=MUTED,
                         font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(anchor="w")
            value_label = ctk.CTkLabel(words, text=value, text_color=INK,
                                       font=ctk.CTkFont("Segoe UI", 18, "bold"))
            value_label.pack(anchor="w", pady=(2, 0))
            return value_label

        self.summary_state_label = metric(0, "WATCH STATUS", "Under watch", PURPLE)
        self.summary_countdown_label = metric(1, "EXPECTED TO CABLE", "--:--:--", TEAL)
        self.summary_distance_label = metric(2, "DISTANCE AT ALERT", "20.6 km", "#56becb")
        self.summary_beat_label = metric(3, "REPLAY BEAT", "05 / 07", "#a6a2dc")

        self.workspace = ttk.Panedwindow(body, orient="vertical")
        self.workspace.pack(fill="both", expand=True)
        main = ttk.Panedwindow(self.workspace, orient="horizontal")
        self.main_split = main
        main.bind("<Configure>", self._set_initial_split, add="+")
        self.workspace.add(main, weight=4)

        left = ctk.CTkFrame(main, fg_color=CARD, corner_radius=6, border_width=1, border_color=LINE)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        map_head = ctk.CTkFrame(left, fg_color="transparent")
        map_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 9))
        ctk.CTkLabel(map_head, text="Situation map", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(side="left")
        ctk.CTkLabel(map_head, text="  •  " + self.vessel["name"], text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 11)).pack(side="left")
        self.weather_label = ctk.CTkLabel(map_head, text="", text_color=MUTED, cursor="hand2",
                                          font=ctk.CTkFont("Segoe UI", 11))
        self.weather_label.pack(side="right")
        self.weather_label.bind("<Button-1>", lambda _event: self.open_window("weather"))
        map_bar = ctk.CTkFrame(left, fg_color="transparent")
        map_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 9))
        self.map_selector = ctk.CTkOptionMenu(map_bar, variable=self.map_mode,
                                              values=["Offline coastline", ONLINE_MAP],
                                              command=self._change_map_mode, width=180, height=31,
                                              fg_color="#1a2c3b", button_color="#203747",
                                              button_hover_color="#294254", text_color=INK,
                                              dropdown_fg_color=CARD, dropdown_text_color=INK)
        self.map_selector.pack(side="left")
        ctk.CTkButton(map_bar, text="Ports", command=lambda: self.open_window("ports"),
                      width=58, height=31, fg_color="#1a2c3b", text_color=TEAL).pack(side="left", padx=6)
        ctk.CTkButton(map_bar, text="Layers", command=lambda: self.open_window("layers"),
                      width=58, height=31, fg_color="#1a2c3b", text_color=TEAL).pack(side="left")
        ctk.CTkSwitch(map_bar, text="Live weather", variable=self.live_weather,
                      command=self._toggle_weather, progress_color=TEAL, text_color=INK,
                      font=ctk.CTkFont("Segoe UI", 11)).pack(side="left", padx=(12, 0))
        for layer, caption in (("Rain and cloud", "Rain"), ("Wind", "Wind")):
            ctk.CTkSwitch(map_bar, text=caption, variable=self.map_layers[layer], width=40, switch_width=30,
                          command=lambda name=layer: self._weather_layer_changed(name),
                          progress_color=TEAL, text_color=INK,
                          font=ctk.CTkFont("Segoe UI", 11)).pack(side="left", padx=(8, 0))
        for text, action in (("−", lambda: self._zoom_by(-1)), ("+", lambda: self._zoom_by(1)),
                             ("⌂", self.fit_map), ("World", self.fit_world)):
            ctk.CTkButton(map_bar, text=text, command=action, width=53 if text == "World" else 32, height=31,
                          corner_radius=9, fg_color="#1a2c3b", hover_color="#294254",
                          text_color=TEAL, font=ctk.CTkFont("Segoe UI", 16)).pack(side="right", padx=(5, 0))
        self.map = tk.Canvas(left, bg=SEA, highlightthickness=0)
        self.map.grid(row=2, column=0, sticky="nsew", padx=12)
        self.map.bind("<Configure>", self._map_resized)
        self.map.bind("<ButtonPress-1>", self._pan_start)
        self.map.bind("<B1-Motion>", self._pan_move)
        self.map.bind("<ButtonRelease-1>", self._pan_end)
        self._last_scroll_zoom = (0.0, 0)
        self.map.bind("<MouseWheel>", self._mouse_wheel)
        self.map.bind("<Button-4>", lambda event: self._mouse_wheel(event, 1))
        self.map.bind("<Button-5>", lambda event: self._mouse_wheel(event, -1))
        try:
            # Tk 9 uses a separate event for precise two-finger scrolling.
            self.map.bind("<TouchpadScroll>", self._touchpad_scroll)
        except tk.TclError:
            pass  # Tk 8.6 delivers trackpad scrolling as MouseWheel instead.
        self.map.bind("<Motion>", self._map_motion)
        map_footer = ctk.CTkFrame(left, fg_color="transparent")
        map_footer.grid(row=3, column=0, sticky="ew", padx=17, pady=(8, 12))
        self.map_status_label = ctk.CTkLabel(map_footer, text="Drag to pan · wheel or two-finger scroll to zoom",
                                             text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10))
        self.map_status_label.pack(side="left")
        self.map_attribution_label = ctk.CTkLabel(map_footer, text="Natural Earth · public domain",
                                                  text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10))
        self.map_attribution_label.pack(side="right")

        panel = ctk.CTkFrame(main, fg_color=CARD, corner_radius=6, border_width=1, border_color=LINE)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        panel_toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        panel_toolbar.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 3))
        ctk.CTkLabel(panel_toolbar, text="Operator panels", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(side="left")
        self.windows_plus = ctk.CTkButton(panel_toolbar, text="+", command=self.open_windows_menu,
                                          width=32, height=30, corner_radius=9, fg_color=PURPLE, text_color=BG,
                                          hover_color="#80703c", font=ctk.CTkFont("Segoe UI", 19))
        self.windows_plus.pack(side="right", padx=(8, 0))
        self.close_panel_button = ctk.CTkButton(panel_toolbar, text="Close tab", command=self.close_current_panel,
                                                width=75, height=30, corner_radius=9, fg_color="#1a2c3b",
                                                hover_color="#294254", text_color=INK,
                                                font=ctk.CTkFont("Segoe UI", 11))
        self.close_panel_button.pack(side="right")
        self.right_notebook = ttk.Notebook(panel, style="Dock.TNotebook")
        self.right_notebook.grid(row=1, column=0, sticky="nsew", padx=13, pady=(0, 12))
        self._bind_dock(self.right_notebook)
        overview = ttk.Frame(self.right_notebook)
        self.right_notebook.add(overview, text="Situation")
        content = ctk.CTkScrollableFrame(overview, fg_color=CARD, corner_radius=0,
                                         scrollbar_button_color="#294254")
        content.pack(fill="both", expand=True)
        ctk.CTkLabel(content, text=self.vessel["name"], text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 20, "bold")).pack(anchor="w", pady=(5, 2))
        self.state_label = ctk.CTkLabel(content, text="", text_color=AMBER,
                                        font=ctk.CTkFont("Segoe UI", 11, "bold"))
        self.state_label.pack(anchor="w", pady=(0, 12))
        eta_card = ctk.CTkFrame(content, fg_color="#142837", corner_radius=13)
        eta_card.pack(fill="x", pady=(0, 13))
        ctk.CTkLabel(eta_card, text="EXPECTED TIME TO CABLE", text_color=MUTED,
                     font=ctk.CTkFont("Segoe UI", 10, "bold")).pack(anchor="w", padx=15, pady=(13, 0))
        self.countdown_label = ctk.CTkLabel(eta_card, text="", text_color=PURPLE,
                                           font=ctk.CTkFont("Consolas", 31, "bold"))
        self.countdown_label.pack(anchor="w", padx=15, pady=(0, 1))
        self.earliest_label = ctk.CTkLabel(eta_card, text="", text_color=INK,
                                          font=ctk.CTkFont("Segoe UI", 11, "bold"))
        self.earliest_label.pack(anchor="w", padx=15, pady=(0, 13))
        self.distance_label = ctk.CTkLabel(content, text="", text_color=MUTED,
                                          wraplength=340, justify="left", font=ctk.CTkFont("Segoe UI", 10))
        self.distance_label.pack(anchor="w", pady=(0, 17))
        ctk.CTkLabel(content, text="Review cues", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(anchor="w")
        self.reasons_label = ctk.CTkLabel(content, text="", wraplength=345, justify="left",
                                         text_color=INK, font=ctk.CTkFont("Segoe UI", 11))
        self.reasons_label.pack(anchor="w", fill="x", pady=(6, 15))
        ctk.CTkLabel(content, text="Response windows", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(anchor="w")
        self.options_label = ctk.CTkLabel(content, text="", wraplength=345, justify="left",
                                         text_color=INK, font=ctk.CTkFont("Segoe UI", 11))
        self.options_label.pack(anchor="w", fill="x", pady=(6, 12))
        self.approve_button = ctk.CTkButton(content, text="Review response", command=self.review_response,
                                            fg_color=PURPLE, text_color=BG, hover_color="#80703c", height=39,
                                            corner_radius=10, font=ctk.CTkFont("Segoe UI", 12, "bold"))
        self.approve_button.pack(fill="x", pady=(0, 7))
        self.approval_label = ctk.CTkLabel(content, text="Operator approval required", text_color=MUTED,
                                          wraplength=345, justify="left", font=ctk.CTkFont("Segoe UI", 10))
        self.approval_label.pack(anchor="w")
        ctk.CTkButton(content, text="Review evidence", command=self.review_evidence,
                      fg_color="#1a2c3b", hover_color="#294254", text_color=TEAL,
                      height=35, corner_radius=10).pack(fill="x", pady=(13, 5))
        ctk.CTkLabel(content, text="Radar association, speed change and vessel intent remain unconfirmed. No action is sent.",
                     text_color=MUTED, wraplength=345, justify="left",
                     font=ctk.CTkFont("Segoe UI", 10)).pack(anchor="w", pady=(5, 12))
        overview.bind("<Configure>", self._resize_situation, add="+")
        main.add(left, weight=7)
        main.add(panel, weight=4)

        self.bottom_dock = ctk.CTkFrame(self.workspace, fg_color=CARD, corner_radius=14,
                                        border_width=1, border_color=LINE)
        bottom_header = ctk.CTkFrame(self.bottom_dock, fg_color="transparent")
        bottom_header.pack(fill="x", padx=14, pady=(7, 3))
        ctk.CTkLabel(bottom_header, text="Bottom workspace", text_color=INK,
                     font=ctk.CTkFont("Segoe UI", 14, "bold")).pack(side="left")
        ctk.CTkButton(bottom_header, text="Move tabs right · close pane", command=self.move_bottom_tabs_right,
                      width=180, height=29, fg_color="#1a2c3b", text_color=INK,
                      hover_color="#294254").pack(side="right")
        self.bottom_notebook = ttk.Notebook(self.bottom_dock, style="Dock.TNotebook")
        self.bottom_notebook.pack(fill="both", expand=True, padx=13, pady=(0, 10))
        self._bind_dock(self.bottom_notebook)

        controls = ctk.CTkFrame(body, fg_color=CARD, corner_radius=6, border_width=1, border_color=LINE)
        controls.pack(fill="x", pady=(14, 0))
        row = ctk.CTkFrame(controls, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(11, 0))
        self.play_button = ctk.CTkButton(row, text="Play", command=self.toggle_play, width=75,
                                         height=33, fg_color=PURPLE, text_color=BG, hover_color="#80703c")
        self.play_button.pack(side="left")
        for title, action in (("Restart", lambda: self.seek(0)),
                              ("Jump to alert", lambda: self.seek(self.alert["t"]))):
            ctk.CTkButton(row, text=title, command=action, height=33, width=100,
                          fg_color="#1a2c3b", hover_color="#294254", text_color=INK).pack(side="left", padx=(7, 0))
        ctk.CTkLabel(row, text="Speed", text_color=MUTED).pack(side="left", padx=(17, 7))
        self.speed_selector = ctk.CTkOptionMenu(row, values=["1×", "30×", "60×", "120×", "240×"],
                                                command=lambda value: self.rate.set(int(value[:-1])),
                                                width=83, height=33, fg_color="#1a2c3b",
                                                button_color="#294254", button_hover_color="#294254",
                                                text_color=INK, dropdown_fg_color=CARD,
                                                dropdown_text_color=INK)
        self.speed_selector.set(f"{self.rate.get()}×")
        self.speed_selector.pack(side="left")
        self.beat_label = ctk.CTkLabel(row, text="", text_color=MUTED,
                                       font=ctk.CTkFont("Segoe UI", 11, "bold"))
        self.beat_label.pack(side="right", padx=(10, 1))
        self.tools_plus = ctk.CTkButton(row, text="+", command=self.open_tools_menu, width=33,
                                        height=33, corner_radius=9, fg_color=PURPLE, text_color=BG,
                                        hover_color="#80703c", font=ctk.CTkFont("Segoe UI", 19))
        self.tools_plus.pack(side="right", padx=(9, 0))
        ctk.CTkLabel(row, text="Bottom panel / tools", text_color=MUTED).pack(side="right")
        self.timeline = ctk.CTkSlider(controls, from_=0, to=self.duration, command=self._scale_changed,
                                      fg_color="#203747", progress_color=PURPLE,
                                      button_color=PURPLE, button_hover_color="#80703c", height=17)
        self.timeline.pack(fill="x", padx=19, pady=(14, 7))
        beats_row = ctk.CTkFrame(controls, fg_color="transparent")
        beats_row.pack(fill="x", padx=12, pady=(0, 11))
        for title, value in self._beats():
            ctk.CTkButton(beats_row, text=title, command=lambda t=value: self.seek(t),
                          height=27, width=96, corner_radius=8, fg_color="#1a2c3b",
                          hover_color="#294254", text_color=TEAL,
                          font=ctk.CTkFont("Segoe UI", 10)).pack(side="left", padx=(0, 5))
        self.root.after(180, self._set_initial_split)

    def _bind_dock(self, notebook: ttk.Notebook) -> None:
        notebook.bind("<ButtonPress-1>", self._dock_tab_press, add="+")
        notebook.bind("<B1-Motion>", self._dock_tab_motion, add="+")
        notebook.bind("<ButtonRelease-1>", self._dock_tab_release, add="+")
        notebook.bind("<Button-3>", self._dock_context_menu, add="+")
        notebook.bind("<<NotebookTabChanged>>", self._dock_tab_changed, add="+")

    def _resize_situation(self, event) -> None:
        wrap = max(210, event.width - 52)
        for label in (self.distance_label, self.reasons_label, self.options_label,
                      self.approval_label):
            label.configure(wraplength=wrap)

    def _set_initial_split(self, _event=None) -> None:
        if getattr(self, "console_layout", False):
            return
        width = self.main_split.winfo_width()
        # The horizontal paned window is added to the workspace before its
        # two child panes are built.  Tk can therefore send a Configure event
        # while it has no sash yet; defer positioning until both panes exist.
        if not self._initial_split_set and len(self.main_split.panes()) >= 2 and width > 700:
            self.main_split.sashpos(0, int(width * 0.63))
            self._initial_split_set = True

    def _beats(self) -> list[tuple[str, int]]:
        track = self.vessel["track"]
        gap = next((index for index in range(1, len(track)) if track[index]["t"] - track[index - 1]["t"] > MAX_AIS_GAP_S), None)
        gap_start = self.alert.get("observations", {}).get("gap_start_t", track[gap - 1]["t"] + 60 if gap else 0)
        gap_end = self.alert.get("observations", {}).get("gap_end_t", track[gap]["t"] if gap else 0)
        radar = next((item["t"] for item in self.scenario["detections"] if item["t"] <= self.alert["t"]), gap_start)
        return [("01 Start", 0), ("02 AIS gap", gap_start), ("03 Radar", radar),
                ("04 AIS returns", gap_end), ("05 Alert", self.alert["t"]),
                ("06 Options", self.alert["t"] + 1), ("07 Decision", self.alert["t"] + 2)]

    def open_windows_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False, font=("Segoe UI", 10))
        for key, title in self._panel_titles.items():
            menu.add_command(label=title, command=lambda panel=key: self.open_window(panel, "right"))
        menu.add_separator()
        menu.add_command(label="Move active tab to bottom", command=lambda: self.move_current_panel("bottom"))
        menu.tk_popup(self.windows_plus.winfo_rootx() - 245, self.windows_plus.winfo_rooty())

    def open_tools_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False, font=("Segoe UI", 10))
        menu.add_command(label="Add panel to bottom workspace", state="disabled")
        for key, title in self._panel_titles.items():
            menu.add_command(label=title, command=lambda panel=key: self.open_window(panel, "bottom"))
        menu.add_separator()
        menu.add_command(label="Center on vessel", command=self.center_vessel)
        menu.add_command(label="Fit exercise area", command=self.fit_map)
        menu.add_command(label="View whole world", command=self.fit_world)
        menu.add_separator()
        menu.add_command(label="Add map note…", command=lambda: self._set_map_tool("pin"))
        menu.add_command(label="Measure distance…", command=lambda: self._set_map_tool("measure"))
        menu.add_command(label="Clear map notes and measurement", command=self.clear_map_notes)
        menu.add_separator()
        for label, variable in self.map_layers.items():
            menu.add_checkbutton(label=label, variable=variable,
                                 command=lambda: self._draw_map(force_static=True))
        menu.tk_popup(self.tools_plus.winfo_rootx(), self.tools_plus.winfo_rooty() - 340)

    def _notebook_for(self, location: str) -> ttk.Notebook:
        if location == "bottom":
            self._ensure_bottom_visible()
            return self.bottom_notebook
        return self.right_notebook

    def _ensure_bottom_visible(self) -> None:
        if self._bottom_visible:
            return
        self.workspace.add(self.bottom_dock, weight=1)
        self._bottom_visible = True

        def set_bottom_height() -> None:
            height = self.workspace.winfo_height()
            if height > 300 and len(self.workspace.panes()) >= 2:
                self.workspace.sashpos(0, int(height * 0.68))

        self.root.after_idle(set_bottom_height)

    def _hide_bottom_if_empty(self) -> None:
        if self._bottom_visible and not self.bottom_notebook.tabs():
            self.workspace.forget(self.bottom_dock)
            self._bottom_visible = False

    def open_window(self, key: str, destination: str = "right") -> None:
        permission = {'evidence': 'evidence.share', 'sar_plan': 'evidence.share',
                      'decision': 'response.review', 'responses': 'response.review'}.get(key, 'map.view')
        if not self.require_tool(permission):
            return
        if key not in self._panel_titles:
            return
        target = self._notebook_for(destination)
        widget = self._panel_widgets.get(key)
        current_location = self._panel_locations.get(key)
        if widget is not None and current_location != destination:
            self._move_panel(key, destination)
            widget = self._panel_widgets[key]
            target = self._notebook_for(destination)
        elif widget is None:
            widget = ttk.Frame(target, padding=12 if getattr(self, 'console_layout', False) else 18)
            self._panel_widgets[key] = widget
            self._panel_locations[key] = destination
            self._populate_panel(key, widget)
            target.add(widget, text=self._panel_titles[key])
        elif key in ("notes", "evidence", "decision", "weather"):
            for child in widget.winfo_children():
                child.destroy()
            self._populate_panel(key, widget)
        target.select(widget)
        if getattr(self, "console_layout", False) and destination == "right":
            self.show_console_panel(self._panel_titles[key])
            if key in ("contacts", "timeline", "responses", "evidence", "decision"):
                self.enable_exercise()
        self._active_dock_location = destination
        self._update_close_panel_button()

    def _populate_panel(self, key: str, frame: ttk.Frame) -> None:
        titles = self._panel_titles
        if not getattr(self, 'console_layout', False):
            ttk.Label(frame, text=titles[key], style="Title.TLabel").pack(anchor="w", pady=(0, 10))

        if key == 'views':
            self.tools.build_views(frame)
        elif key == "ais":
            self.ais_tracker.build(frame)
        elif key == "sar_plan":
            text = tk.Text(frame, wrap="word", padx=15, pady=12, font=("Segoe UI", 11),
                           bg=CARD, fg=INK, insertbackground=INK, relief="flat")
            scrollbar = ttk.Scrollbar(frame, command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            text.pack(fill="both", expand=True)
            text.insert("1.0", (ROOT / "docs/08-sar-next-step.md").read_text(encoding="utf-8"))
            text.configure(state="disabled")
        elif key == "ports":
            self._build_port_directory(frame)
        elif key == "cables":
            self._build_cable_directory(frame)
        elif key == "evidence":
            ttk.Label(frame, text="Evidence review · simulated exercise", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
            text = tk.Text(frame, wrap="word", padx=15, pady=12, font=("Segoe UI", 10), bg=CARD, fg=INK)
            text.pack(fill="both", expand=True)
            text.insert("1.0", self._evidence_text())
            text.configure(state="disabled")
            actions = ttk.Frame(frame)
            actions.pack(fill="x", pady=(10, 0))
            ttk.Button(actions, text="Save HTML decision record", command=lambda: self.save_record(frame),
                       state="normal" if self._remaining() else "disabled").pack(side="right")

        elif key == "decision":
            remaining = self._remaining()
            available = [option for option in self.alert["options"]
                         if remaining and response_status(option, remaining[1]) == "In time"]
            if self.approved:
                ttk.Label(frame, text=f"Simulated response approved: {self.approved['asset']}",
                          style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
                ttk.Label(frame, text="This is an exercise record. No operational action was sent.",
                          style="Muted.TLabel", wraplength=520).pack(anchor="w")
            elif not remaining:
                ttk.Label(frame, text="Response choices become available after the alert fires.",
                          style="Muted.TLabel").pack(anchor="w")
            elif not available:
                ttk.Label(frame, text=f"Earliest cable crossing: {clock(remaining[1])} remaining.",
                          style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
                ttk.Label(frame, text="No listed response option is currently inside the earliest assumed arrival window.",
                          style="Muted.TLabel", wraplength=520).pack(anchor="w")
            else:
                ttk.Label(frame, text=f"Earliest cable crossing: {clock(remaining[1])} remaining.",
                          style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
                for option in available:
                    ttk.Radiobutton(frame,
                                    text=f"{option['asset']} · {math.ceil(option['eta_s'] / 60)} min assumed arrival",
                                    variable=self._decision_choice, value=option["asset"],
                                    command=lambda: refresh()).pack(anchor="w", pady=4)
                ttk.Label(frame, text="Identity, intent, cable geometry and response capabilities require verification. This records an exercise decision only; nothing operational is sent.",
                          wraplength=560, justify="left").pack(anchor="w", pady=(12, 8))

                def refresh() -> None:
                    current = self._remaining()
                    selected = next((item for item in available if item["asset"] == self._decision_choice.get()), None)
                    can_approve = bool(self._decision_acknowledged.get() and current and selected and
                                       response_status(selected, current[1]) == "In time")
                    approve.configure(state="normal" if can_approve else "disabled")

                def accept() -> None:
                    if not self.require_tool('response.review'):
                        return
                    current = self._remaining()
                    selected = next((item for item in available if item["asset"] == self._decision_choice.get()), None)
                    if not self._decision_acknowledged.get() or not current or not selected or \
                            response_status(selected, current[1]) != "In time":
                        return
                    self.approved = {"time": self.position_s, "asset": selected["asset"],
                                     "assumed_arrival_s": selected["eta_s"], "label": "simulated"}
                    self._close_panel("decision")
                    self.render()
                    self.review_evidence()

                ttk.Checkbutton(frame, text="I reviewed the uncertainty and approve a simulated response",
                                variable=self._decision_acknowledged, command=refresh).pack(anchor="w", pady=(4, 12))
                actions = ttk.Frame(frame)
                actions.pack(fill="x", pady=(8, 0))
                ttk.Button(actions, text="Cancel", command=lambda: self._close_panel("decision")).pack(side="right", padx=(8, 0))
                approve = ttk.Button(actions, text="Approve simulated response", state="disabled", command=accept)
                approve.pack(side="right")
                refresh()

        if key == "contacts":
            ttk.Label(frame, text="Scenario contacts · labels describe the exercise data", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
            table = ttk.Treeview(frame, columns=("source", "label", "time", "speed", "position"), show="headings", height=10)
            for column, text, width in (("source", "Contact", 180), ("label", "Evidence label", 100),
                                        ("time", "Last observation", 135), ("speed", "Speed", 80), ("position", "Position", 180)):
                table.heading(column, text=text)
                table.column(column, width=width, anchor="w")
            for vessel in self.scenario["vessels"]:
                fix = fix_at(vessel["track"], self.position_s)
                position = f"{fix['lat']:.3f}, {fix['lon']:.3f}" if fix else "AIS gap / unavailable"
                table.insert("", "end", iid=f"v-{vessel['mmsi']}", values=(f"{vessel['name']} · {vessel['mmsi']}", vessel.get("label", "unknown"), self._utc(fix["t"]) if fix else "No current fix", f"{fix['sog_kn']:.1f} kn" if fix else "—", position))
            table.pack(fill="both", expand=True)
            for detection in self.scenario["detections"]:
                table.insert("", "end", iid=f"r-{detection.get('id', detection['t'])}", values=(f"SAR contact · {detection.get('id', '?')}", detection.get("label", "unknown"), self._utc(detection["t"]), f"{detection.get('length_m', '?')} m", f"{detection['lat']:.3f}, {detection['lon']:.3f}"))
            ttk.Label(frame, text="Radar contacts remain separate from AIS vessel identities.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        elif key == "timeline":
            ttk.Label(frame, text="Double-click a beat to move the replay there.", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
            table = ttk.Treeview(frame, columns=("time", "beat", "detail"), show="headings", height=12)
            for column, text, width in (("time", "Scenario time", 120), ("beat", "Beat", 180), ("detail", "What is shown", 390)):
                table.heading(column, text=text)
                table.column(column, width=width, anchor="w")
            beat_descriptions = [
                "Fictional AIS track; no position is invented through a gap.",
                "AIS reception gap begins; the marker becomes a predicted area.",
                "Separate simulated radar observation appears.",
                "AIS returns after the gap.",
                "Rule-generated alert at the observed fix.",
                "Compare assumed response arrival with earliest estimate.",
                "Operator reviews and approves an exercise option.",
            ]
            for index, ((beat, value), description) in enumerate(zip(self._beats(), beat_descriptions)):
                table.insert("", "end", iid=str(index), values=(self._utc(value), beat, description))
            table.pack(fill="both", expand=True)
            def jump_to_beat(_event=None) -> None:
                selected = table.focus()
                if selected.isdigit():
                    self.seek(self._beats()[int(selected)][1])

            table.bind("<Double-1>", jump_to_beat)

        elif key == "responses":
            remaining = self._remaining()
            ttk.Label(frame, text=f"Earliest crossing: {clock(remaining[1])} remaining" if remaining else "Response ETAs become active when the alert fires.", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
            table = ttk.Treeview(frame, columns=("asset", "eta", "status", "label"), show="headings", height=10)
            for column, text, width in (("asset", "Response option", 280), ("eta", "Assumed ETA", 110), ("status", "Window", 110), ("label", "Provenance", 100)):
                table.heading(column, text=text)
                table.column(column, width=width, anchor="w")
            for option in self.alert["options"]:
                eta = "Unavailable" if option["eta_s"] is None else f"{math.ceil(option['eta_s'] / 60)} min"
                status = response_status(option, remaining[1]) if remaining else "Pending"
                table.insert("", "end", values=(option["asset"], eta, status, option.get("label", "assumption")))
            table.pack(fill="both", expand=True)
            ttk.Label(frame, text="All capability and arrival figures are assumptions; this panel sends no action.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        elif key == "layers":
            if hasattr(self, 'tools'):
                ttk.Checkbutton(frame, text='Reduce panel motion', variable=self.tools.reduced_motion,
                                command=self.tools.schedule_save).pack(anchor='w', pady=4)
            if hasattr(self, "irish_ports_only"):
                ttk.Checkbutton(frame, text="Irish coast ports only", variable=self.irish_ports_only,
                                command=lambda: self._draw_map(force_static=True)).pack(anchor="w", pady=4)
            ttk.Label(frame, text="Choose a map background and the overlays to show.", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
            ttk.Label(frame, text="Basemap", style="Heading.TLabel").pack(anchor="w")
            selector = ttk.Combobox(frame, textvariable=self.map_mode, values=("Offline coastline", ONLINE_MAP), state="readonly", width=31)
            selector.pack(anchor="w", pady=(5, 12))
            selector.bind("<<ComboboxSelected>>", self._change_map_mode)
            for label, variable in self.map_layers.items():
                ttk.Checkbutton(frame, text=label, variable=variable, command=lambda: self._draw_map(force_static=True)).pack(anchor="w", pady=4)
            ttk.Checkbutton(frame, text="Live weather · Met Éireann (online)", variable=self.live_weather,
                            command=self._toggle_weather).pack(anchor="w", pady=(10, 4))
            ttk.Button(frame, text="View the whole world", command=self.fit_world).pack(anchor="w", pady=(12, 4))
            ttk.Button(frame, text="Data sources and limitations", command=lambda: self.open_window("world_data", self._active_dock_location)).pack(anchor="w")
            ttk.Label(frame, text="NASA imagery requests only visible tiles. The global coastline, ports and historical cable routes are stored locally. Routes are stylized and must never be used for alerts.", style="Muted.TLabel", wraplength=550, justify="left").pack(anchor="w", pady=(14, 0))

        elif key == "world_data":
            sources = [
                ("World land", "Natural Earth · real public domain geometry. Simplified display map, not a navigational chart."),
                (f"Port records · {len(self.world_ports):,}", "NGA World Port Index plus Ireland's Marine Atlas / Marine Irish Digital Atlas (CC BY 4.0) · real reference locations. Points may not mark individual berths."),
                (f"Cable systems · {len(self.world_cables):,}", "Historical TeleGeography map snapshot · reconstructed, simplified stylized routes. CC BY-NC-SA 3.0 (creativecommons.org/licenses/by-nc-sa/3.0/); noncommercial display only. May include planned systems. Never use these lines for proximity alerts."),
                ("Imagery", "NASA Earthdata GIBS Blue Marble Next Generation · online display imagery. This imagery is not a live satellite feed."),
                ("Weather", "Met Éireann forecast API (data.gov.ie) · real live point forecast at the exercise cable, plus rain/cloud shading and wind arrows from a grid of model points (not radar), CC BY 4.0. Off by default; shows current weather, not the fictional replay's, and never changes alerts or ETAs."),
                ("Exercise overlays", "Fictional vessel, cable and response geometry is separate from the global reference layers. Operator approval remains required."),
            ]
            for heading, description in sources:
                ttk.Label(frame, text=heading, style="Heading.TLabel").pack(anchor="w", pady=(9, 2))
                ttk.Label(frame, text=description, style="Muted.TLabel", wraplength=520, justify="left").pack(anchor="w")

        elif key == "weather":
            self._build_weather_panel(frame)

        elif key == "notes":
            ttk.Label(frame, text="Map notes live for this session only.", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
            listbox = tk.Listbox(frame, font=("Segoe UI", 10), relief="flat", borderwidth=1,
                                 bg=CARD, fg=INK, selectbackground=HOVER, selectforeground=INK,
                                 highlightthickness=1, highlightbackground=LINE)
            listbox.pack(fill="both", expand=True)
            for index, (lat, lon) in enumerate(self.map_note_points, 1):
                listbox.insert("end", f"{index}.  {lat:.5f}°N, {lon:.5f}°W")
            actions = ttk.Frame(frame)
            actions.pack(fill="x", pady=(10, 0))
            ttk.Button(actions, text="Add note on map", command=lambda: self._set_map_tool("pin")).pack(side="left")

            def remove_selected() -> None:
                selection = listbox.curselection()
                if selection:
                    del self.map_note_points[selection[0]]
                    self._draw_map()
                    self.open_window("notes", self._panel_locations.get("notes", "right"))

            ttk.Button(actions, text="Remove selected", command=remove_selected).pack(side="left", padx=8)
            ttk.Button(actions, text="Clear all", command=self.clear_map_notes).pack(side="left")

    def _build_weather_panel(self, frame) -> None:
        lat, lon = self.weather_point
        ttk.Checkbutton(frame, text="Show live weather (requests the Met Éireann API)",
                        variable=self.live_weather, command=self._toggle_weather).pack(anchor="w")
        ttk.Label(frame, text=f"Point forecast at the exercise cable · {lat:.3f}, {lon:.3f}",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(frame, text=self._weather_status, style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(2, 10))
        hour_row = ttk.Frame(frame)
        hour_row.pack(anchor="w", pady=(0, 6))
        ttk.Label(hour_row, text="Rain, cloud and wind map hour").pack(side="left")
        hour = ttk.Combobox(hour_row, textvariable=self.weather_hour, values=WEATHER_HOURS, state="readonly", width=8)
        hour.pack(side="left", padx=(8, 0))
        hour.bind("<<ComboboxSelected>>", lambda _event: self._draw_map(force_static=True))
        if self.live_weather.get():
            grid = self._weather_grid
            if grid is None:
                overlay = "Map overlay: the view is outside Met Éireann coverage (50–60°N, 20°W–1°E)."
            else:
                total = len(grid[1]) * len(grid[2])
                loaded = sum(1 for lat in grid[1] for lon in grid[2] if (lat, lon) in self._weather_grid_cache)
                overlay = f"Map overlay: {loaded} of {total} grid points loaded · {grid[0]:g}° spacing"
            ttk.Label(frame, text=overlay, style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(0, 10))
        if not self.live_weather.get() or not self._weather:
            ttk.Label(frame, text="Real, current weather only. It is not the weather of the fictional replay and never changes alerts, countdowns or response ETAs.",
                      style="Muted.TLabel", wraplength=520, justify="left").pack(anchor="w")
            return
        now = weather.current_conditions(self._weather)
        ttk.Label(frame, text=weather.summary(now), style="Heading.TLabel", wraplength=520).pack(anchor="w")
        hint = weather.caution(now)
        if hint:
            ttk.Label(frame, text=hint, foreground=AMBER, wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))
        table = ttk.Treeview(frame, columns=("time", "wind", "gust", "temp", "rain"), show="headings", height=12)
        for column, text, width in (("time", "UTC", 70), ("wind", "Wind", 150), ("gust", "Gusts", 80),
                                    ("temp", "Temp", 70), ("rain", "Rain", 80)):
            table.heading(column, text=text)
            table.column(column, width=width, anchor="w")
        for point in weather.upcoming(self._weather, 24):
            wind = weather.knots(point.get("wind_mps"))
            gust = weather.knots(point.get("gust_mps"))
            table.insert("", "end", values=(
                f"{point['time']:%H:%M}",
                f"{point.get('wind_dir') or ''} {wind:.0f} kn · Bft {point.get('beaufort', '?')}" if wind is not None else "—",
                f"{gust:.0f} kn" if gust is not None else "—",
                f"{point['temperature_c']:.0f} °C" if point.get("temperature_c") is not None else "—",
                f"{point['precip_mm']:.1f} mm" if point.get("precip_mm") is not None else "—"))
        table.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(frame, text=f"Source: {weather.ATTRIBUTION} · {weather.SOURCE_URL}. Label: real. Cautions are assumptions; ETAs are unchanged.",
                  style="Muted.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(8, 0))

    def _toggle_weather(self) -> None:
        self._weather_generation += 1
        if self._weather_refresh_after:
            try:
                self.root.after_cancel(self._weather_refresh_after)
            except tk.TclError:
                pass
            self._weather_refresh_after = None
        if self.live_weather.get():
            self._weather_status = "Loading Met Éireann forecast…"
            self.weather_label.configure(text="☁ Loading weather…", text_color=MUTED)
            self._request_weather()
        else:
            self._weather = None
            self._weather_status = "Live weather off · no network requests"
            self.weather_label.configure(text="")
            self._weather_grid_pending.clear()
        self._weather_overlay = None
        self._refresh_weather_panel()
        self._draw_map(force_static=True)

    def _request_weather(self) -> None:
        generation = self._weather_generation
        lat, lon = self.weather_point

        def fetch() -> None:
            try:
                self._weather_queue.put(("point", generation, weather.fetch_forecast(lat, lon), None))
            except Exception as error:  # network, HTTP or XML problems all mean "unavailable"
                self._weather_queue.put(("point", generation, None, error))

        self._weather_executor.submit(fetch)
        self._update_weather_grid()  # also refreshes grid points older than 30 minutes
        self._weather_refresh_after = self.root.after(weather.REFRESH_S * 1000, self._request_weather)

    def _schedule_weather_grid(self, delay_ms: int = 700) -> None:
        if not self.live_weather.get():
            return
        if self._weather_grid_after is not None:
            try:
                self.root.after_cancel(self._weather_grid_after)
            except tk.TclError:
                pass
        self._weather_grid_after = self.root.after(delay_ms, self._update_weather_grid)

    def _update_weather_grid(self) -> None:
        """Request the grid points of the current view that are not cached or pending."""
        self._weather_grid_after = None
        if not self._weather_map_active() or not self._map_size[0]:
            return
        width, height = self._map_size
        center_x, center_y = geo_to_world(*self.map_center, self.map_zoom)
        if width >= TILE_SIZE * 2 ** self.map_zoom:
            west, east = -180.0, 180.0
            north, south = world_to_geo(0, center_y - height / 2, self.map_zoom)[0], world_to_geo(0, center_y + height / 2, self.map_zoom)[0]
        else:
            north, west = world_to_geo(center_x - width / 2, center_y - height / 2, self.map_zoom)
            south, east = world_to_geo(center_x + width / 2, center_y + height / 2, self.map_zoom)
            if west > east:
                west, east = -180.0, 180.0
        grid = weather.grid_for_view(south, north, west, east)
        if grid != self._weather_grid:
            self._weather_grid = grid
            self._weather_overlay = None
            self._draw_map(force_static=True)
        if grid is None:
            return
        generation, now = self._weather_generation, time.monotonic()
        for lat in grid[1]:
            for lon in grid[2]:
                key = (lat, lon)
                cached = self._weather_grid_cache.get(key)
                if key in self._weather_grid_pending or (cached and now - cached[0] < weather.REFRESH_S):
                    continue
                self._weather_grid_pending.add(key)
                self._weather_executor.submit(self._weather_grid_worker, generation, key)

    def _weather_grid_worker(self, generation: int, key: tuple[float, float]) -> None:
        try:
            forecast, retry = weather.fetch_forecast(*key), False
        except ValueError:  # outside the forecast area: nothing to retry
            forecast, retry = None, False
        except Exception:
            forecast, retry = None, True
        self._weather_queue.put(("grid", generation, key, forecast, retry))

    def _poll_weather(self) -> None:
        grid_changed = False
        while True:
            try:
                kind, generation, *message = self._weather_queue.get_nowait()
            except queue.Empty:
                break
            if generation != self._weather_generation or not self.live_weather.get():
                continue  # switched off (or on again) since this request started
            if kind == "grid":
                key, forecast, retry = message
                self._weather_grid_pending.discard(key)
                # A failed request is retried after two minutes instead of thirty.
                fetched = time.monotonic() - (weather.REFRESH_S - 120 if retry else 0)
                self._weather_grid_cache[key] = (fetched, forecast)
                grid_changed = True
                continue
            forecast, error = message
            if forecast:
                self._weather = forecast
                now = weather.current_conditions(forecast)
                self._weather_status = f"Met Éireann · updated {forecast['fetched']:%H:%M} UTC · refreshes every 30 min"
                self.weather_label.configure(text="☁ " + weather.summary(now),
                                             text_color=AMBER if weather.caution(now) else INK)
            else:
                self._weather_status = f"Weather unavailable ({type(error).__name__}) · retrying in 30 min"
                if not self._weather:
                    self.weather_label.configure(text="☁ Weather unavailable", text_color=MUTED)
            self._refresh_weather_panel()
        if grid_changed:
            self._weather_field_version += 1
            self._draw_map(force_static=True)
            self._refresh_weather_panel()
        self.root.after(500, self._poll_weather)

    def _weather_map_active(self) -> bool:
        return self.live_weather.get() and (self.map_layers["Rain and cloud"].get() or self.map_layers["Wind"].get())

    def _weather_layer_changed(self, layer: str) -> None:
        """Turning on a weather layer also turns on live weather, which it needs."""
        if self.map_layers[layer].get() and not self.live_weather.get():
            self.live_weather.set(True)
            self._toggle_weather()
        else:
            self._draw_map(force_static=True)

    def _weather_time(self) -> datetime:
        choice = self.weather_hour.get()
        offset = 0 if choice == "Now" else int(choice[1:].split()[0])
        return datetime.now(timezone.utc) + timedelta(hours=offset)

    def _weather_field_images(self) -> dict | None:
        """Cloud/rain/mask images and wind vectors for the current grid and forecast hour."""
        grid = self._weather_grid
        when = self._weather_time().replace(minute=0, second=0, microsecond=0)
        key = (grid, self._weather_field_version, when)
        if self._weather_field and self._weather_field["key"] == key:
            return self._weather_field
        step, lats, lons = grid
        values, winds, estimated = {}, [], False
        for lat in lats:
            for lon in lons:
                forecast = self._weather_grid_cache.get((lat, lon), (0, None))[1]
                if not forecast:
                    continue
                point = weather.current_conditions(forecast, when)
                result = weather.field_values(point)
                if result:
                    values[(lat, lon)] = result[:2]
                    estimated = estimated or result[2]
                vector = weather.wind_vector(point)
                if vector:  # ECMWF-only points carry no wind
                    winds.append((lat, lon, *vector))
        self._weather_field = {"key": key, "when": when, "estimated": estimated, "winds": winds,
                               "count": len(values) + len(winds),
                               "images": weather.field_images(lats, lons, values) if values else None}
        return self._weather_field

    def _draw_weather_overlay(self, width: int, height: int) -> None:
        if not self._weather_map_active():
            self._weather_view_key = None
            return
        view_key = (self.map_zoom, round(self.map_center[0], 3), round(self.map_center[1], 3), width, height)
        if view_key != self._weather_view_key:  # fetch the new view's grid once the map settles
            self._weather_view_key = view_key
            self._schedule_weather_grid()
        if not self._weather_grid or not self.map_layers["Rain and cloud"].get():
            return
        field = self._weather_field_images()
        if not field["images"]:
            return
        step, lats, lons = self._weather_grid
        z = self.map_zoom
        x0, y0 = geo_to_world(lats[-1] + step / 2, lons[0] - step / 2, z)
        x1, y1 = geo_to_world(lats[0] - step / 2, lons[-1] + step / 2, z)
        center_x, center_y = geo_to_world(*self.map_center, z)
        world = TILE_SIZE * 2 ** z
        shift = round((center_x - (x0 + x1) / 2) / world) * world
        x0, x1 = x0 + shift, x1 + shift
        view = (center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2)
        visible = (max(x0, view[0]), max(y0, view[1]), min(x1, view[2]), min(y1, view[3]))
        if visible[0] >= visible[2] or visible[1] >= visible[3]:
            return
        overlay = self._weather_overlay
        if not (overlay and overlay["key"] == (field["key"], z, x0) and
                overlay["rect"][0] <= visible[0] and overlay["rect"][1] <= visible[1] and
                overlay["rect"][2] >= visible[2] and overlay["rect"][3] >= visible[3]):
            # Render half a view beyond each edge so short pans reuse the same image.
            target = (max(x0, view[0] - width / 2), max(y0, view[1] - height / 2),
                      min(x1, view[2] + width / 2), min(y1, view[3] + height / 2))
            size = (max(1, round(target[2] - target[0])), max(1, round(target[3] - target[1])))
            columns, rows = field["images"][0].size
            box = ((target[0] - x0) / (x1 - x0) * columns, (target[1] - y0) / (y1 - y0) * rows,
                   (target[2] - x0) / (x1 - x0) * columns, (target[3] - y0) / (y1 - y0) * rows)
            layers = [image.resize(size, Image.BILINEAR, box=box) for image in field["images"]]
            overlay = {"key": (field["key"], z, x0), "image": ImageTk.PhotoImage(weather.colorize(*layers), master=self.map),
                       "rect": (target[0], target[1], target[0] + size[0], target[1] + size[1])}
            self._weather_overlay = overlay
        self.map.create_image(overlay["rect"][0] - view[0], overlay["rect"][1] - view[1],
                              image=overlay["image"], anchor="nw")

    def _draw_wind_arrows(self, width: int, height: int) -> None:
        if not self._weather_map_active() or not self.map_layers["Wind"].get() or not self._weather_grid:
            return
        field = self._weather_field_images()
        cell = self._weather_grid[0] * TILE_SIZE * 2 ** self.map_zoom / 360  # grid spacing in pixels
        for lat, lon, towards, kn in field["winds"]:
            x, y = self._project(lat, lon)
            if not (-20 <= x <= width + 20 and -20 <= y <= height + 20):
                continue
            length = max(18.0, min(0.8 * cell, 22 + kn * 1.4, 66.0))
            # Web Mercator is conformal, so compass bearings keep their screen angle.
            dx, dy = math.sin(math.radians(towards)) * length / 2, -math.cos(math.radians(towards)) * length / 2
            colour = weather.wind_colour(kn)
            self.map.create_line(x - dx, y - dy, x + dx, y + dy, fill="white", width=6,
                                 arrow="last", arrowshape=(12, 14, 6), capstyle="round")
            self.map.create_line(x - dx, y - dy, x + dx, y + dy, fill=colour, width=3,
                                 arrow="last", arrowshape=(11, 13, 5))
            if cell >= 55:
                self.map.create_text(x - dx * 1.3, y - dy * 1.3, text=f"{kn:.0f}", fill=colour,
                                     font=("Segoe UI Semibold", 8))

    def _draw_weather_legend(self) -> None:
        rain_on, wind_on = self.map_layers["Rain and cloud"].get(), self.map_layers["Wind"].get()
        if not self._weather_map_active():
            return
        layers = {(True, True): "RAIN, CLOUD & WIND", (True, False): "RAIN & CLOUD", (False, True): "WIND"}[(rain_on, wind_on)]
        if not self._weather_grid:
            text = f"{layers} · view outside Met Éireann coverage (50–60°N, 20°W–1°E)"
        else:
            field = self._weather_field_images()
            if not field["count"]:
                text = f"{layers} · loading Met Éireann forecast grid…"
            else:
                text = f"{layers} · MET ÉIREANN MODEL FORECAST {field['when']:%H:%M} UTC · NOT RADAR"
                if rain_on and field["estimated"]:
                    text += " · rain partly estimated from symbols"
        title = self.map.bbox("map_title")
        top = (title[3] if title else 26) + 6
        label = self.map.create_text(14, top + 4, text=text, anchor="nw", fill=INK, font=("Segoe UI Semibold", 8))
        _x1, y1, x2, y2 = self.map.bbox(label)
        line = y2 - y1
        background = self.map.create_rectangle(8, top, x2 + 8, y2 + 8, fill=CARD, outline=LINE)
        self.map.tag_raise(label)
        rows = []
        if rain_on:
            rows.append(("box", [("#a3adbb", "cloud")] + [
                ("#%02x%02x%02x" % weather.rain_colour(weather.rain_level(mm))[:3], f"{mm:g}")
                for mm in weather.RAIN_LEGEND_MM], " mm/h rain"))
        if wind_on:
            rows.append(("arrow", [(colour, band) for _limit, colour, band in weather.WIND_BANDS],
                         " kn wind · arrows point downwind"))
        right, bottom = x2, y2
        for kind, swatches, unit in rows:
            row = bottom + line // 2 + 3
            x = 14
            for index, (colour, caption) in enumerate(swatches):
                if kind == "box":
                    self.map.create_rectangle(x, row - line // 3, x + line, row + line // 3, fill=colour, outline="")
                else:
                    self.map.create_line(x, row, x + line, row, fill=colour, width=2.5, arrow="last", arrowshape=(7, 8, 3))
                item = self.map.create_text(x + line + 4, row, text=caption + (unit if index == len(swatches) - 1 else ""),
                                            anchor="w", fill=MUTED, font=("Segoe UI", 8))
                x = self.map.bbox(item)[2] + (line if kind == "box" and index == 0 else line // 2)
            right, bottom = max(right, x), row + line // 2
        self.map.coords(background, 8, top, right + 8, bottom + 6)

    def _refresh_weather_panel(self) -> None:
        widget = self._panel_widgets.get("weather")
        if widget is None:
            return
        for child in widget.winfo_children():
            child.destroy()
        self._populate_panel("weather", widget)

    def _build_port_directory(self, frame) -> None:
        ttk.Label(frame, text="Irish commercial, fishing and ferry ports / Marine Atlas and NGA reference records.",
                  style="Muted.TLabel", wraplength=340).pack(anchor="w")
        self.port_query = tk.StringVar()
        ttk.Label(frame, text="Search ports").pack(anchor="w", pady=(10, 0))
        entry = ttk.Entry(frame, textvariable=self.port_query)
        entry.pack(fill="x", pady=(10, 6))
        self.port_country = tk.StringVar(value="Irish coast" if getattr(self, "console_layout", False) else "All countries")
        ttk.Label(frame, text="Port region / country code").pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.port_country, state="readonly",
                     values=["Irish coast", "All countries"] + sorted({p[4] for p in self.world_ports})).pack(fill="x")
        self.port_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Only ports in the current map view", variable=self.port_visible,
                        command=self._refresh_port_directory).pack(anchor="w", pady=8)
        self.port_count = ttk.Label(frame, style="Muted.TLabel")
        self.port_count.pack(anchor="w", pady=(0, 6))
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True)
        self.port_table = ttk.Treeview(holder, columns=("name", "country", "wpi"), show="headings",
                                       selectmode="browse", height=8)
        for column, title, width in (("name", "Port", 170), ("country", "Country", 65), ("wpi", "Ref ID", 75)):
            self.port_table.heading(column, text=title)
            self.port_table.column(column, width=width, minwidth=50, stretch=column == "name")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.port_table.yview)
        self.port_table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.port_table.pack(fill="both", expand=True)
        self.port_detail = ttk.Label(frame, text="Select a port to inspect its reference location.",
                                     wraplength=340, justify="left")
        self.port_detail.pack(anchor="w", pady=10)
        ttk.Button(frame, text="Center selected port", command=self._center_selected_port).pack(anchor="w")
        ttk.Label(frame, text="Real reference data / Marine Irish Digital Atlas (CC BY 4.0) and NGA. Historical catalogue locations, not surveyed berths. Different categories may describe the same harbour.",
                  style="Muted.TLabel", wraplength=340).pack(anchor="w", pady=(10, 0))
        self.port_table.bind("<<TreeviewSelect>>", self._port_table_selected)
        self.port_table.bind("<Double-1>", lambda _event: self._center_selected_port())
        self.port_table.bind("<Return>", lambda _event: self._center_selected_port())
        self.port_query.trace_add("write", lambda *_: self._schedule_port_directory())
        self.port_country.trace_add("write", lambda *_: self._refresh_port_directory())
        self._refresh_port_directory()
        if self.selected_port is not None:
            self._select_port(self.selected_port)

    def _schedule_port_directory(self) -> None:
        if self._port_refresh_after:
            self.root.after_cancel(self._port_refresh_after)
        self._port_refresh_after = self.root.after(150, self._refresh_port_directory)

    def _visible_port_indices(self):
        width, height = self._map_size
        return {i for i, port in enumerate(self.world_ports)
                if 0 <= self._project(port[2], port[3])[0] <= width
                and 0 <= self._project(port[2], port[3])[1] <= height}

    def _refresh_port_directory(self) -> None:
        self._port_refresh_after = None
        if not hasattr(self, "port_table") or not self.port_table.winfo_exists():
            return
        visible = self._visible_port_indices() if self.port_visible.get() else None
        country = self.port_country.get()
        if country == "Irish coast":
            irish_indices = getattr(self, "irish_port_indices", {i for i, p in enumerate(self.world_ports) if p[4] == "IE"})
            visible = irish_indices if visible is None else visible & irish_indices
            country = "All countries"
        indices = find_ports(self.world_ports, self.port_query.get(), country, visible)
        self.port_table.delete(*self.port_table.get_children())
        for index in indices:
            number, name, _lat, _lon, country = self.world_ports[index]
            metadata = getattr(self, "port_metadata", {}).get(str(number), {})
            title = f"{name} ({metadata['category']})" if metadata else name
            self.port_table.insert("", "end", iid=str(index), values=(title, country, number))
        self.port_count.configure(text=f"{len(indices):,} of {len(self.world_ports):,} ports" +
                                  (" · Irish coast" if self.port_country.get() == "Irish coast" else " · current view" if visible is not None else " · worldwide"))
        if self.selected_port in indices:
            self.port_table.selection_set(str(self.selected_port))
            self.port_table.see(str(self.selected_port))

    def _port_table_selected(self, _event=None) -> None:
        selected = self.port_table.selection()
        if selected:
            self._select_port(int(selected[0]))

    def _select_port(self, index) -> None:
        changed = self.selected_port != index
        self.selected_port = index
        number, name, lat, lon, country = self.world_ports[index]
        if hasattr(self, "port_detail") and self.port_detail.winfo_exists():
            metadata = getattr(self, "port_metadata", {}).get(str(number))
            source = f"{metadata['source']} / {metadata['category']} / {metadata['licence']}" if metadata else "NGA World Port Index"
            self.port_detail.configure(text=f"{name} · {country} · ref {number}\n{coordinates(lat, lon)}\nReal / {source}\nReference location, not a navigation fix")
        if changed:
            self._draw_map(force_static=True)

    def _center_selected_port(self) -> None:
        if self.selected_port is None:
            return
        port = self.world_ports[self.selected_port]
        if hasattr(self, "irish_ports_only") and self.selected_port not in self.irish_port_indices:
            self.irish_ports_only.set(False)
        self.map_layers["World ports"].set(True)
        self.map_zoom = min(10, MAX_IMAGERY_ZOOM if self.map_mode.get() == ONLINE_MAP else MAX_MAP_ZOOM)
        self._change_map_center((port[2], port[3]))
        self._refresh_port_directory()

    def _build_cable_directory(self, frame) -> None:
        ttk.Label(frame, text="Historical, stylized routes · reconstructed\nCC BY-NC-SA 3.0 · display only, never used for alerts.",
                  style="Muted.TLabel", wraplength=340).pack(anchor="w")
        unnamed = sum(c.get('name') == 'Unnamed cable' or not c.get('name') for c in self.world_cables)
        ttk.Label(frame, text=f"{unnamed} records have no supplied system name. Route IDs distinguish them.",
                  style="Muted.TLabel", wraplength=340).pack(anchor="w", pady=(5, 0))
        query = tk.StringVar()
        ttk.Label(frame, text="Search cable systems").pack(anchor="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=query).pack(fill="x", pady=10)
        count = ttk.Label(frame, style="Muted.TLabel")
        count.pack(anchor="w")
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=8)
        table = ttk.Treeview(holder, columns=("name",), show="headings", selectmode="browse", height=8)
        table.heading("name", text="Cable system")
        table.column("name", width=240)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        detail = ttk.Label(frame, text="Select a system, then fit its route on the map.", wraplength=340)
        detail.pack(anchor="w", pady=8)
        def refresh(*_):
            tokens = search_text(query.get()).split()
            indices = sorted((i for i, c in enumerate(self.world_cables)
                              if all(t in search_text(f'{route_name(c, i)} {i + 1:03d}') for t in tokens)),
                             key=lambda i: search_text(route_name(self.world_cables[i], i)))
            table.delete(*table.get_children())
            for i in indices:
                table.insert("", "end", iid=str(i), values=(f'{route_name(self.world_cables[i], i)} · #{i + 1:03d}',))
            count.configure(text=f"{len(indices)} of {len(self.world_cables)} route records")
            if self.selected_cable in indices:
                table.selection_set(str(self.selected_cable))
                table.see(str(self.selected_cable))
        def select(_event=None):
            if table.selection():
                self.selected_cable = int(table.selection()[0])
                cable = self.world_cables[self.selected_cable]
                detail.configure(text=self._cable_description(self.selected_cable))
                self.map_layers["Historical cable routes"].set(True)
                self._draw_map(force_static=True)
        self.cable_table = table
        self.cable_detail = detail
        ttk.Button(frame, text="Fit selected route", command=self._fit_selected_cable).pack(anchor="w")
        table.bind("<<TreeviewSelect>>", select)
        table.bind("<Double-1>", lambda _event: self._fit_selected_cable())
        table.bind("<Return>", lambda _event: self._fit_selected_cable())
        query.trace_add("write", refresh)
        refresh()

    def _fit_selected_cable(self) -> None:
        if self.selected_cable is None:
            return
        points = [(lat, lon) for segment in self.world_cables[self.selected_cable]['segments'] for lon, lat in segment]
        self._fit_points(points)

    def _cable_description(self, index) -> str:
        cable = self.world_cables[index]
        points = [(lat, lon) for segment in cable['segments'] for lon, lat in segment]
        center, lat_span, lon_span = geographic_extent(points)
        return (f"{route_name(cable, index)} · record #{index + 1:03d}\n"
                f"{len(cable['segments'])} route sections · reconstructed\n"
                f"Extent center: {coordinates(*center)}\n"
                f"Span: {lat_span:.1f}° latitude / {lon_span:.1f}° longitude")

    def _fit_points(self, points) -> None:
        if not points:
            return
        center, lat_span, lon_span = geographic_extent(points)
        # The live canvas size: before the first draw _map_size is still (0, 0) and every fit would be the world.
        width, height = max(self._map_size[0], self.map.winfo_width()), max(self._map_size[1], self.map.winfo_height())
        maximum = MAX_IMAGERY_ZOOM if self.map_mode.get() == ONLINE_MAP else MAX_MAP_ZOOM
        for zoom in range(maximum, MIN_MAP_ZOOM - 1, -1):
            _, top = geo_to_world(center[0] + lat_span / 2, center[1], zoom)
            _, bottom = geo_to_world(center[0] - lat_span / 2, center[1], zoom)
            if TILE_SIZE * 2 ** zoom * lon_span / 360 <= max(100, width - 100) and bottom - top <= max(100, height - 100):
                break
        self.map_zoom = zoom
        _, top = geo_to_world(center[0] + lat_span / 2, center[1], zoom)
        x, bottom = geo_to_world(center[0] - lat_span / 2, center[1], zoom)
        self.map_center = world_to_geo(x, (top + bottom) / 2, zoom)
        self._draw_map(force_static=True)
        self._schedule_tile_refresh()
        self._refresh_port_directory()

    def _panel_key_for_widget(self, widget_path: str) -> str | None:
        return next((key for key, widget in self._panel_widgets.items() if str(widget) == widget_path), None)

    def _update_close_panel_button(self, _event=None) -> None:
        try:
            selected = self.right_notebook.select()
            bottom_selected = self.bottom_notebook.select()
            is_panel = bool((selected and self._panel_key_for_widget(selected)) or
                            (bottom_selected and self._panel_key_for_widget(bottom_selected)))
            self.close_panel_button.configure(state="normal" if is_panel else "disabled")
        except tk.TclError:
            pass

    def _dock_tab_changed(self, event=None) -> None:
        if event is not None:
            self._active_dock_location = "bottom" if str(event.widget) == str(self.bottom_notebook) else "right"
        self._update_close_panel_button()

    def _selected_panel_key(self, notebook: ttk.Notebook) -> str | None:
        selected = notebook.select()
        return self._panel_key_for_widget(selected) if selected else None

    def close_current_panel(self) -> None:
        first = self.bottom_notebook if self._active_dock_location == "bottom" else self.right_notebook
        second = self.right_notebook if first is self.bottom_notebook else self.bottom_notebook
        key = self._selected_panel_key(first) or self._selected_panel_key(second)
        if key:
            self._close_panel(key)

    def _close_panel(self, key: str) -> None:
        widget = self._panel_widgets.pop(key, None)
        location = self._panel_locations.pop(key, None)
        if widget is not None and location:
            notebook = self.bottom_notebook if location == "bottom" else self.right_notebook
            try:
                notebook.forget(widget)
                widget.destroy()
            except tk.TclError:
                pass
        self._hide_bottom_if_empty()
        self._update_close_panel_button()
        if getattr(self, "console_layout", False) and len(self.right_notebook.tabs()) == 1:
            self.hide_console_panel()

    def show_console_panel(self, title="Exercise") -> None:
        already_open = self.panel_visible
        self.panel_visible = True
        self.panel_caption.configure(text=title)
        self._position_console_panel()
        if not already_open:
            self.tools.animate('details', self.floating_panel, (-46, 16), (-70, 16), {'relx': 1, 'anchor': 'ne'})

    def _position_console_panel(self) -> None:
        # The alert board is docked beside the rail; the map host holds the floating panels.
        self.layout_columns()
        available = self.chart_host.winfo_width()
        right_width = self.tools.detail_width
        if available > 500:
            right_width = min(right_width, max(330, available - 294))
        if getattr(self, "panel_visible", False):
            # Stay clear of the mode bar, and of the replay bar while the exercise is shown.
            bottom = 200 if self.exercise_visible.get() else 120
            height = max(350, self.chart_host.winfo_height() - bottom)
            self.floating_panel.configure(width=right_width, height=height)
            self.floating_panel.place(relx=1, x=-70, y=16, anchor="ne")
        if hasattr(self, "alert_board") and self.alert_board.dialog.visible:
            self.alert_board.dialog.place()

    def hide_console_panel(self) -> None:
        self.tools.cancel_animation('details')
        self.tools.hide_tooltip()
        self.panel_visible = False
        self.floating_panel.place_forget()

    def enable_exercise(self) -> None:
        self.ais_tracker.follow.set(False)
        self.exercise_visible.set(True)
        self.replay_controls.configure(width=600)
        self.replay_controls.place(x=16, rely=1, y=-110, anchor="sw")
        self.render()

    def show_exercise(self) -> None:
        self.enable_exercise()
        self.right_notebook.select(0)
        self.show_console_panel("Fictional exercise")
        self.fit_map()

    def open_exercise_alert(self, alert) -> None:
        self.alert = alert
        self.vessel = next(v for v in self.scenario['vessels'] if v['mmsi'] == alert['mmsi'])
        self.cable = next(c for c in self.scenario['cables'] if c['id'] == alert['segment_id'])
        self.seek(alert['t'])
        self.show_exercise()

    def hide_exercise(self) -> None:
        self.exercise_visible.set(False)
        self.playing = False
        self.replay_controls.place_forget()
        self.hide_console_panel()
        self.fit_ireland()
        self.render()

    def fit_ireland(self) -> None:
        if hasattr(self, 'ais_tracker'):
            self.ais_tracker.follow.set(False)
        self._fit_points([(50.8, -12.0), (55.6, -4.8)])  # Ireland, the Irish Sea and the near Atlantic

    def toggle_fullscreen(self, _event=None) -> str:
        self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))
        return "break"

    def _move_panel(self, key: str, destination: str) -> None:
        widget = self._panel_widgets.get(key)
        source_location = self._panel_locations.get(key)
        if widget is None or source_location == destination:
            return
        source = self.bottom_notebook if source_location == "bottom" else self.right_notebook
        target = self._notebook_for(destination)
        source.forget(widget)
        widget.destroy()
        replacement = ttk.Frame(target, padding=12 if getattr(self, 'console_layout', False) else 18)
        self._panel_widgets[key] = replacement
        self._panel_locations[key] = destination
        self._populate_panel(key, replacement)
        target.add(replacement, text=self._panel_titles[key])
        target.select(replacement)
        if getattr(self, "console_layout", False) and destination == "right":
            self.show_console_panel(self._panel_titles[key])
        self._hide_bottom_if_empty()
        self._update_close_panel_button()

    def move_current_panel(self, destination: str) -> None:
        first = self.bottom_notebook if self._active_dock_location == "bottom" else self.right_notebook
        second = self.right_notebook if first is self.bottom_notebook else self.bottom_notebook
        key = self._selected_panel_key(first) or self._selected_panel_key(second)
        if key:
            self._move_panel(key, destination)

    def move_bottom_tabs_right(self) -> None:
        for widget_path in list(self.bottom_notebook.tabs()):
            key = self._panel_key_for_widget(widget_path)
            if key:
                self._move_panel(key, "right")
        self._hide_bottom_if_empty()

    def _dock_tab_press(self, event) -> None:
        notebook = event.widget
        try:
            index = notebook.index(f"@{event.x},{event.y}")
            widget_path = notebook.tabs()[index]
        except (tk.TclError, IndexError):
            self._dock_drag = None
            return
        key = self._panel_key_for_widget(widget_path)
        if key is None:
            self._dock_drag = None
            return
        location = "bottom" if str(notebook) == str(self.bottom_notebook) else "right"
        self._dock_drag = {"key": key, "location": location,
                           "x": event.x_root, "y": event.y_root, "moved": False}

    def _dock_tab_motion(self, event) -> None:
        if not self._dock_drag:
            return
        dx = abs(event.x_root - self._dock_drag["x"])
        dy = abs(event.y_root - self._dock_drag["y"])
        if dx + dy > 8:
            self._dock_drag["moved"] = True

    def _notebook_under_pointer(self, x_root: int, y_root: int) -> ttk.Notebook | None:
        notebooks = [self.right_notebook]
        if self._bottom_visible:
            notebooks.append(self.bottom_notebook)
        for notebook in notebooks:
            if not notebook.winfo_ismapped():
                continue
            left, top = notebook.winfo_rootx(), notebook.winfo_rooty()
            right, bottom = left + notebook.winfo_width(), top + notebook.winfo_height()
            if left <= x_root <= right and top <= y_root <= bottom:
                return notebook
        return None

    def _dock_tab_release(self, event) -> None:
        drag = self._dock_drag
        self._dock_drag = None
        if not drag or not drag["moved"]:
            return
        target = self._notebook_under_pointer(event.x_root, event.y_root)
        if target is None:
            return
        key = drag["key"]
        destination = "bottom" if str(target) == str(self.bottom_notebook) else "right"
        if destination != drag["location"]:
            self._move_panel(key, destination)
            target = self._notebook_for(destination)
        widget = self._panel_widgets.get(key)
        if widget is None:
            return
        try:
            index = target.index(f"@{event.x_root - target.winfo_rootx()},{event.y_root - target.winfo_rooty()}")
            target.insert(index, widget)
        except tk.TclError:
            pass
        target.select(widget)
        self._update_close_panel_button()

    def _dock_context_menu(self, event) -> str | None:
        notebook = event.widget
        try:
            index = notebook.index(f"@{event.x},{event.y}")
            key = self._panel_key_for_widget(notebook.tabs()[index])
        except (tk.TclError, IndexError):
            return None
        if key is None:
            return None
        notebook.select(index)
        location = "bottom" if str(notebook) == str(self.bottom_notebook) else "right"
        target = "right" if location == "bottom" else "bottom"
        menu = tk.Menu(self.root, tearoff=False, font=("Segoe UI", 10))
        menu.add_command(label=f"Move to {target} pane", command=lambda: self._move_panel(key, target))
        menu.add_command(label="Close panel", command=lambda: self._close_panel(key))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def center_vessel(self) -> None:
        fix = fix_at(self.vessel["track"], self.position_s)
        dark = None if fix else self._dark_state()
        if dark:
            # Frame the labelled prediction area, never an invented fix.
            self._fit_points(desktop_prediction.extent_points(dark["position"]["prediction"]))
            return
        if not fix:
            messagebox.showinfo("No AIS fix", "The vessel has no AIS position at this replay time.", parent=self.root)
            return
        self._change_map_center((fix["lat"], fix["lon"]))

    def _set_map_tool(self, tool: str) -> None:
        if not self.require_tool('ping' if tool == 'ping' else 'map.view'):
            return
        if tool == 'ping' and self.map_tool == 'ping':
            self._clear_map_ping()
            return
        self.map_tool = tool
        self.measure_points.clear()
        if tool == "measure":
            self.measurement_line.clear()
            self.map_status_label.configure(text="Measure · click two points on the map")
        elif tool == 'ping':
            self.map_status_label.configure(text='Ping · click the map to mark a point · Escape to clear')
            if hasattr(self, 'ais_tracker'):
                self.ais_tracker.follow.set(False)
            self.map.focus_set()
        else:
            self.map_status_label.configure(text="Map note · click the map to place a marker")
        self._update_ping_button()
        self.map.configure(cursor="tcross")
        self._draw_map()

    def _update_ping_button(self) -> None:
        button = getattr(self, 'toolbar_buttons', {}).get('ping')
        if button is not None:
            button.configure(fg_color=CONTROL if self.map_tool == 'ping' else 'transparent')

    def _clear_map_ping(self, _event=None) -> str:
        timer = getattr(self, '_ping_after', None)
        if timer is not None:
            self.root.after_cancel(timer)
        self._ping_after = None
        self._map_ping = None
        self.map.delete('map_ping')
        if self.map_tool == 'ping':
            self.map_tool = None
            self.map.configure(cursor='')
        self._update_ping_button()
        self.map_status_label.configure(text='Ping cleared')
        return 'break'

    def _place_map_ping(self, point: tuple[float, float], share: bool = True) -> None:
        self._clear_map_ping()
        self._map_ping = point
        self._ping_started = time.monotonic()
        self.map_status_label.configure(text=f'Ping · {coordinates(*point)} · visible for 15 seconds')
        self._animate_map_ping()
        if share and hasattr(self, 'soc'):
            self.soc.share_ping(point)

    def _animate_map_ping(self) -> None:
        self._ping_after = None
        if self._map_ping is None:
            return
        if time.monotonic() - self._ping_started >= 15:
            self._map_ping = None
            self.map.delete('map_ping')
            if self.map_status_label.cget('text').startswith('Ping'):
                self.map_status_label.configure(text='Ping expired · drag to pan / wheel to zoom')
            return
        self._draw_map_ping()
        reduced = hasattr(self, 'tools') and self.tools.reduced_motion.get()
        self._ping_after = self.root.after(250 if reduced else 80, self._animate_map_ping)

    def _draw_map_ping(self) -> None:
        self.map.delete('map_ping')
        if getattr(self, '_map_ping', None) is None:
            return
        x, y = self._project(*self._map_ping)
        width, height = self._map_size
        if not (-40 <= x <= width + 40 and -40 <= y <= height + 40):
            return
        reduced = hasattr(self, 'tools') and self.tools.reduced_motion.get()
        phase = 0 if reduced else ((time.monotonic() - self._ping_started) % 1.4) / 1.4
        for radius, color in ((12, TEAL), (20 + phase * 22, '#527c8b')):
            self.map.create_oval(x-radius, y-radius, x+radius, y+radius,
                                 outline=color, width=2, tags='map_ping')
        self.map.create_oval(x-3, y-3, x+3, y+3, fill=TEAL, outline=INK, tags='map_ping')
        self.map.create_line(x-8, y, x+8, y, fill=TEAL, tags='map_ping')
        self.map.create_line(x, y-8, x, y+8, fill=TEAL, tags='map_ping')
        self.map.create_text(max(90, min(x, width-90)), max(18, y-48),
            text=f'PING · {coordinates(*self._map_ping)}', fill=INK,
            font=('Segoe UI', 10, 'bold'), tags='map_ping')

    def clear_map_notes(self) -> None:
        self.map_note_points.clear()
        self.measure_points.clear()
        self.measurement_line.clear()
        self.map_tool = None
        self._update_ping_button()
        self.map.configure(cursor="")
        self.map_status_label.configure(text="Map notes and measurement cleared")
        self._draw_map()
        if "notes" in self._panel_widgets:
            self.open_window("notes", self._panel_locations.get("notes", "right"))

    def close(self) -> None:
        if hasattr(self, 'soc'):
            self.soc.close()
        if hasattr(self, 'alert_board'):
            self.alert_board.close()
        if hasattr(self, 'pinch'):
            self.pinch.close()
        if hasattr(self, 'tools'):
            self.tools.close()
        if hasattr(self, "ais_tracker"):
            self.ais_tracker.close()
        self._tile_executor.shutdown(wait=False, cancel_futures=True)
        self._weather_executor.shutdown(wait=False, cancel_futures=True)
        # Cancel callbacks before Tk deletes their registered commands. This
        # also prevents a closed window's timers leaking into another window.
        for callback in self.root.tk.call('after', 'info'):
            try:
                # A timer may belong to a child widget (e.g. CTkTextbox).
                # Cancel it in Tcl; let its owning widget delete the command.
                self.root.tk.call('after', 'cancel', callback)
            except tk.TclError:
                pass
        self.root.destroy()

    def _project(self, lat: float, lon: float) -> tuple[float, float]:
        width, height = self._map_size
        point_x, point_y = geo_to_world(lat, lon, self.map_zoom)
        center_x, center_y = geo_to_world(*self.map_center, self.map_zoom)
        world = TILE_SIZE * 2 ** self.map_zoom
        point_x += round((center_x - point_x) / world) * world
        return width / 2 + point_x - center_x, height / 2 + point_y - center_y

    def _points(self, points: list) -> list[float]:
        return [coordinate for lat, lon in points for coordinate in self._project(lat, lon)]

    def _draw_map_callout(self, text: str, x: float, y: float, kind: str,
                          occupied: list[tuple[int, int, int, int]]) -> None:
        offsets = {
            "vessel": ((16, -30, "nw"), (18, 17, "nw"), (-16, -30, "ne"),
                       (18, 37, "nw"), (-16, 18, "ne"), (24, -48, "nw"), (18, 56, "nw")),
            "radar": ((14, 14, "nw"), (16, -22, "nw"), (-14, 15, "ne"),
                      (20, 34, "nw"), (-14, -24, "ne"), (22, -42, "nw")),
            "asset": ((12, 8, "nw"), (12, -23, "nw"), (-12, 10, "ne"),
                       (12, 27, "nw"), (-12, -24, "ne"), (20, 44, "nw"), (20, -40, "nw")),
            "port": ((10, -18, "nw"), (10, 7, "nw"), (-10, -18, "ne"), (-10, 7, "ne")),
        }
        font = ("Segoe UI Semibold", 9) if kind == "vessel" else ("Segoe UI", 8)
        width, height = self._map_size
        for dx, dy, anchor in offsets[kind]:
            item = self.map.create_text(x + dx, y + dy, text=text, anchor=anchor,
                                        fill=INK, font=font, justify="left")
            bounds = self.map.bbox(item)
            self.map.delete(item)
            if not bounds:
                continue
            x1, y1, x2, y2 = bounds
            padded = (x1 - 4, y1 - 3, x2 + 4, y2 + 3)
            if padded[0] < 3 or padded[1] < 3 or padded[2] > width - 3 or padded[3] > height - 3:
                continue
            if any(padded[0] <= box[2] + 3 and padded[2] >= box[0] - 3 and
                   padded[1] <= box[3] + 3 and padded[3] >= box[1] - 3 for box in occupied):
                continue
            self.map.create_rectangle(*padded, fill=CARD, outline=LINE, width=1)
            self.map.create_text(x + dx, y + dy, text=text, anchor=anchor,
                                 fill=INK, font=font, justify="left")
            occupied.append(padded)
            return

    def _world_at(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        center_x, center_y = geo_to_world(*self.map_center, self.map_zoom)
        return center_x + screen_x - self._map_size[0] / 2, center_y + screen_y - self._map_size[1] / 2

    def _tile_path(self, key: tuple[int, int, int]) -> Path:
        z, x, y = key
        return self._tile_cache / str(z) / str(x) / f"{y}.jpeg"

    def _tile_meta_path(self, key: tuple[int, int, int]) -> Path:
        return self._tile_path(key).with_suffix(".json")

    def _tile_metadata(self, key: tuple[int, int, int]) -> dict:
        try:
            return json.loads(self._tile_meta_path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _expiry(headers) -> float:
        cache_control = headers.get("Cache-Control", "")
        for directive in cache_control.split(","):
            name, _, value = directive.strip().partition("=")
            if name.lower() in ("no-cache", "no-store"):
                return time.time()
            if name.lower() == "max-age":
                try:
                    return time.time() + max(0, int(value.strip('"')))
                except ValueError:
                    break
        expires = headers.get("Expires")
        if expires:
            try:
                return parsedate_to_datetime(expires).timestamp()
            except (TypeError, ValueError, OverflowError):
                pass
        return time.time() + 24 * 60 * 60

    def _visible_tiles(self) -> list[tuple[int, int, int, int, int]]:
        width, height = self._map_size
        z = self.map_zoom
        center_x, center_y = geo_to_world(*self.map_center, z)
        left, right = center_x - width / 2, center_x + width / 2
        top, bottom = center_y - height / 2, center_y + height / 2
        min_x, max_x = math.floor(left / TILE_SIZE), math.floor(right / TILE_SIZE)
        min_y = max(0, math.floor(top / TILE_SIZE))
        max_y = min((2 ** z) - 1, math.floor(bottom / TILE_SIZE))
        tiles = []
        for tile_y in range(min_y, max_y + 1):
            for tile_x in range(min_x, max_x + 1):
                tiles.append((z, tile_x % (2 ** z), tile_y, tile_x, tile_y))
        return tiles

    def _tile_fetch_worker(self, key: tuple[int, int, int]) -> None:
        path = self._tile_path(key)
        metadata = self._tile_metadata(key)
        z, x, y = key
        headers = {"User-Agent": TILE_USER_AGENT, "Accept": "image/jpeg"}
        if path.exists() and metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if path.exists() and metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]
        request = Request(TILE_URL.format(z=z, x=x, y=y), headers=headers)
        try:
            try:
                response = urlopen(request, timeout=8)
            except HTTPError as error:
                if error.code != 304:
                    raise
                metadata["expires_at"] = self._expiry(error.headers)
                self._tile_meta_path(key).write_text(json.dumps(metadata), encoding="utf-8")
                self._tile_queue.put((key, True, "Map tiles refreshed", None))
                return
            with response:
                data = response.read(TILE_SIZE * TILE_SIZE * 8)
                if response.headers.get("x-blocked"):
                    raise ValueError("Imagery provider blocked the request")
                if not data.startswith(b"\xff\xd8\xff") or not response.headers.get("Content-Type", "").lower().startswith("image/jpeg"):
                    raise ValueError("Tile service returned an unexpected image format")
                cache_control = response.headers.get("Cache-Control", "")
                no_store = any(item.strip().lower() == "no-store" for item in cache_control.split(","))
                if no_store:
                    path.unlink(missing_ok=True)
                    self._tile_meta_path(key).unlink(missing_ok=True)
                    self._tile_queue.put((key, True, "NASA imagery loaded", data))
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = path.with_suffix(".tmp")
                temp_path.write_bytes(data)
                temp_path.replace(path)
                metadata = {
                    "expires_at": self._expiry(response.headers),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                }
                self._tile_meta_path(key).write_text(json.dumps(metadata), encoding="utf-8")
            self._tile_queue.put((key, True, "NASA imagery loaded", None))
        except Exception as error:
            self._tile_queue.put((key, False, str(error), None))

    def _update_visible_tiles(self) -> None:
        if self.map_mode.get() != ONLINE_MAP or self._map_size[0] < 100:
            return
        missing = False
        for z, x, y, _x_absolute, _y_absolute in self._visible_tiles():
            key = (z, x, y)
            path = self._tile_path(key)
            metadata = self._tile_metadata(key)
            if path.exists() and key not in self._tile_images:
                try:
                    with Image.open(path) as image:
                        self._tile_images[key] = ImageTk.PhotoImage(image.copy(), master=self.map)
                except (OSError, ValueError, tk.TclError):
                    path.unlink(missing_ok=True)
            fresh = path.exists() and metadata.get("expires_at", 0) > time.time()
            if not fresh and key not in self._tile_pending and self._tile_retry_after.get(key, 0) < time.time():
                self._tile_pending.add(key)
                self._tile_executor.submit(self._tile_fetch_worker, key)
            if key not in self._tile_images:
                missing = True
        self._tile_status = "Loading NASA imagery…" if missing else "NASA imagery · local cache"
        self._draw_map()

    def _schedule_tile_refresh(self, delay_ms: int = 240) -> None:
        if self.map_mode.get() != ONLINE_MAP:
            return
        if self._tile_refresh_after is not None:
            try:
                self.root.after_cancel(self._tile_refresh_after)
            except tk.TclError:
                pass
        self._tile_refresh_after = self.root.after(delay_ms, self._update_visible_tiles)

    def _poll_tiles(self) -> None:
        changed = False
        while True:
            try:
                key, succeeded, result, image_data = self._tile_queue.get_nowait()
            except queue.Empty:
                break
            self._tile_pending.discard(key)
            if succeeded:
                path = self._tile_path(key)
                try:
                    if image_data:
                        with Image.open(BytesIO(image_data)) as image:
                            self._tile_images[key] = ImageTk.PhotoImage(image.copy(), master=self.map)
                    else:
                        with Image.open(path) as image:
                            self._tile_images[key] = ImageTk.PhotoImage(image.copy(), master=self.map)
                    self._tile_status = result
                    changed = True
                except (OSError, tk.TclError):
                    self._tile_status = "A map tile could not be displayed"
            else:
                self._tile_retry_after[key] = time.time() + 120
                self._tile_status = "Imagery unavailable · showing local map and cached tiles"
        if changed:
            self._draw_map()
        if self.map_mode.get() == ONLINE_MAP:
            self.map_status_label.configure(text=self._tile_status or "Loading NASA imagery…")
        self.root.after(150, self._poll_tiles)

    def _map_resized(self, _event=None) -> None:
        if not hasattr(self, "map_status_label"):
            return  # The console is still being built; its scheduled fit draws the first frame.
        if getattr(self, "console_layout", False):
            self._position_console_panel()
        self._draw_map(force_static=True)
        self._schedule_tile_refresh()
        if hasattr(self, "port_visible") and self.port_visible.get():
            self._schedule_port_directory()

    def _change_map_mode(self, _event=None) -> None:
        if isinstance(_event, str) and _event in ("Offline coastline", ONLINE_MAP):
            self.map_mode.set(_event)
        if self.map_mode.get() == ONLINE_MAP:
            self.map_zoom = min(self.map_zoom, MAX_IMAGERY_ZOOM)
            self._tile_status = "Loading NASA imagery…"
            self.map_attribution_label.configure(text="NASA Earthdata · Natural Earth · NGA · TeleGeography")
            self.map_status_label.configure(text="Online imagery · visible tiles requested as you view")
            self._update_visible_tiles()
        else:
            self.map_attribution_label.configure(text="Natural Earth · NGA · TeleGeography")
            self.map_status_label.configure(text="Offline coastline · no network requests")
            self._draw_map(force_static=True)

    def _pan_start(self, event) -> None:
        if hasattr(self, 'ais_tracker'):
            self.ais_tracker.follow.set(False)
        self._drag_state = {"x": event.x, "y": event.y, "last_x": event.x, "last_y": event.y, "moved": False}
        self.map.configure(cursor="tcross" if self.map_tool else "fleur")

    def _pan_move(self, event) -> None:
        if not self._drag_state:
            return
        drag = self._drag_state
        if abs(event.x - drag["x"]) + abs(event.y - drag["y"]) > 4:
            drag["moved"] = True
        if not drag["moved"]:
            return
        center_x, center_y = geo_to_world(*self.map_center, self.map_zoom)
        center_x -= event.x - drag["last_x"]
        center_y -= event.y - drag["last_y"]
        self.map_center = world_to_geo(center_x, center_y, self.map_zoom)
        drag["last_x"], drag["last_y"] = event.x, event.y
        self._draw_map(force_static=True)

    def _pan_end(self, event) -> None:
        was_drag = bool(self._drag_state and self._drag_state["moved"])
        self._drag_state = None
        self.map.configure(cursor="hand2" if self.map_tool else "")
        if was_drag:
            self._schedule_tile_refresh()
            if hasattr(self, "port_visible") and self.port_visible.get():
                self._schedule_port_directory()
        if not was_drag and not self.map_tool:
            self._inspect_map_item(event)
        if not was_drag and self.map_tool:
            point = world_to_geo(*self._world_at(event.x, event.y), self.map_zoom)
            if self.map_tool == 'ping':
                self._place_map_ping(point)
            elif self.map_tool == "pin":
                self.map_note_points.append(point)
                self.map_status_label.configure(text=f"Map note added · {coordinates(*point)}")
                self.map_tool = None
            elif self.map_tool == "measure":
                self.measure_points.append(point)
                if len(self.measure_points) == 2:
                    km = distance_km(*self.measure_points)
                    self.measurement_line = list(self.measure_points)
                    self.map_status_label.configure(text=f"Measured {km:.2f} km ({km / 1.852:.2f} nm) · choose Measure to start over")
                    self.measure_points.clear()
                    self.map_tool = None
                else:
                    self.map_status_label.configure(text="First point set · click a second point to measure")
            self.map.configure(cursor="tcross" if self.map_tool else "")
            self._update_ping_button()
            self._draw_map()
            self._schedule_tile_refresh()

    def _map_motion(self, event) -> None:
        if self.map_tool:
            lat, lon = world_to_geo(*self._world_at(event.x, event.y), self.map_zoom)
            self.map_status_label.configure(text=f"{self.map_tool.title()} · {coordinates(lat, lon)}")
            return
        for item in reversed(self.map.find_overlapping(event.x - 3, event.y - 3, event.x + 3, event.y + 3)):
            for tag in self.map.gettags(item):
                if tag.startswith("sim-alert:") and hasattr(self, "alert_board"):
                    self.map_status_label.configure(text=self.alert_board.describe(tag.split(":", 1)[1]))
                    return
                if tag.startswith("ais-ship:") and hasattr(self, "ais_tracker"):
                    vessel = self.ais_tracker.state.vessels.get(tag.split(":", 1)[1])
                    if vessel:
                        self.map_status_label.configure(text=f"{vessel['name']} / MMSI {vessel['mmsi']} / {vessel['label']} / received {vessel['received_utc']}")
                    return
                if tag.startswith("world-port-cluster:"):
                    cluster = self._port_clusters[tag]
                    self.map_status_label.configure(text=f"{len(cluster)} port records · click to zoom into cluster")
                    return
                if tag.startswith("world-port:"):
                    number, name, lat, lon, country = self.world_ports[int(tag.split(":")[1])]
                    source = "Marine Atlas" if str(number) in getattr(self, "port_metadata", {}) else "NGA WPI"
                    self.map_status_label.configure(text=f"{source} · {name} ({country}) · ref {number} · {lat:.3f}, {lon:.3f}")
                    return
                if tag.startswith("world-cable:"):
                    index = int(tag.split(":")[1])
                    name = route_name(self.world_cables[index], index)
                    self.map_status_label.configure(text=f"Historical stylized cable route · {name} · reconstructed, display only")
                    return
        lat, lon = world_to_geo(*self._world_at(event.x, event.y), self.map_zoom)
        self.map_status_label.configure(text=f"{coordinates(lat, lon)} · drag to pan / click a port to inspect")

    def _inspect_map_item(self, event) -> None:
        tags = [tag for item in reversed(self.map.find_overlapping(event.x - 5, event.y - 5, event.x + 5, event.y + 5))
                for tag in self.map.gettags(item)]
        for tag in tags:
            if tag.startswith("sim-alert:") and hasattr(self, "alert_board"):
                self.alert_board.open(tag.split(":", 1)[1])
                return
        for tag in tags:
            if tag.startswith("ais-ship:") and hasattr(self, "ais_tracker"):
                self.ais_tracker.select_on_map(tag.split(":", 1)[1])
                return
        for tag in tags:
            if tag.startswith("world-port-cluster:"):
                members = self._port_clusters[tag]
                x = sum(p[1] for p in members) / len(members)
                y = sum(p[2] for p in members) / len(members)
                point = world_to_geo(*self._world_at(x, y), self.map_zoom)
                self.map_zoom = min(self.map_zoom + 2, MAX_IMAGERY_ZOOM if self.map_mode.get() == ONLINE_MAP else MAX_MAP_ZOOM)
                self._change_map_center(point)
                self._refresh_port_directory()
                return
            if tag.startswith("world-port:"):
                self._select_port(int(tag.split(":")[1]))
                self.open_window("ports")
                self._refresh_port_directory()
                return
        for tag in tags:
            if tag.startswith("world-cable:"):
                self.selected_cable = int(tag.split(":")[1])
                self.open_window("cables")
                if self.cable_table.exists(str(self.selected_cable)):
                    self.cable_table.selection_set(str(self.selected_cable))
                    self.cable_table.see(str(self.selected_cable))
                self.cable_detail.configure(text=self._cable_description(self.selected_cable))
                self._draw_map(force_static=True)
                return

    def _mouse_wheel(self, event, amount: int | None = None) -> str:
        # On macOS, Shift also marks horizontal MouseWheel events.
        if event.state & 1:
            return "break"
        if amount is None and event.num in (4, 5):
            amount = 1 if event.num == 4 else -1
        if amount is not None:
            # Tk versions differ in the numeric button reported to callbacks.
            self._zoom_at(amount, event.x, event.y)
        else:
            # macOS Tk 8.6 sends small deltas, including +/-1, for both devices.
            self._zoom_from_scroll(event.delta, event.x, event.y,
                                   precise=abs(event.delta) < 120)
        return "break"

    def _touchpad_scroll(self, event) -> str:
        # Tk 9 packs signed X/Y distances into the high/low 16 bits of delta.
        vertical = event.delta & 0xffff
        if vertical >= 0x8000:
            vertical -= 0x10000
        self._zoom_from_scroll(vertical, event.x, event.y, precise=True)
        return "break"

    def _zoom_from_scroll(self, delta: int, x: float, y: float, *, precise: bool) -> None:
        if not delta:
            return
        direction = 1 if delta > 0 else -1
        now = time.monotonic()
        previous_time, previous_direction = self._last_scroll_zoom
        # A trackpad gesture produces many events. Respond immediately, then
        # limit repeated steps so one short gesture cannot exhaust the zoom range.
        if precise and direction == previous_direction and now - previous_time < 0.15:
            return
        self._last_scroll_zoom = (now, direction)
        self._zoom_at(direction, x, y)

    def _zoom_at(self, amount: int, screen_x: float, screen_y: float) -> None:
        maximum = MAX_IMAGERY_ZOOM if self.map_mode.get() == ONLINE_MAP else MAX_MAP_ZOOM
        new_zoom = max(MIN_MAP_ZOOM, min(maximum, self.map_zoom + amount))
        if new_zoom == self.map_zoom:
            return
        under_cursor = world_to_geo(*self._world_at(screen_x, screen_y), self.map_zoom)
        self.map_zoom = new_zoom
        point_x, point_y = geo_to_world(*under_cursor, new_zoom)
        center_x = point_x - (screen_x - self._map_size[0] / 2)
        center_y = point_y - (screen_y - self._map_size[1] / 2)
        self.map_center = world_to_geo(center_x, center_y, new_zoom)
        self._draw_map(force_static=True)
        self._schedule_tile_refresh()

        if hasattr(self, "port_visible") and self.port_visible.get():
            self._schedule_port_directory()

    def _zoom_by(self, amount: int) -> None:
        self._zoom_at(amount, self._map_size[0] / 2, self._map_size[1] / 2)

    def _change_map_center(self, point: tuple[float, float]) -> None:
        self.map_center = point
        self._draw_map(force_static=True)
        self._schedule_tile_refresh()
        self._refresh_port_directory()

    def fit_map(self) -> None:
        points = [(p['lat'], p['lon']) for p in self.vessel['track']]
        points += [tuple(p) for p in self.cable['path']]
        self._fit_points(points)

    def fit_world(self) -> None:
        self.map_center = (0.0, 0.0)
        self.map_zoom = 1
        self._draw_map(force_static=True)
        self._schedule_tile_refresh(0)
        self._refresh_port_directory()

    def _draw_global_land(self, width: int, height: int) -> None:
        z = self.map_zoom
        world = TILE_SIZE * 2 ** z
        center_x, center_y = geo_to_world(*self.map_center, z)
        level = "110m" if z <= 4 else "50m"
        for ring, (lon_min, lat_min, lon_max, lat_max) in self.land_rings[level]:
            north_y = geo_to_world(lat_max, 0, z)[1] - center_y + height / 2
            south_y = geo_to_world(lat_min, 0, z)[1] - center_y + height / 2
            if south_y < -4 or north_y > height + 4:
                continue
            left_x = geo_to_world(0, lon_min, z)[0] - center_x + width / 2
            right_x = geo_to_world(0, lon_max, z)[0] - center_x + width / 2
            for shift in (-world, 0, world):
                if right_x + shift < -4 or left_x + shift > width + 4:
                    continue
                coords = []
                for lon, lat in ring:
                    x, y = geo_to_world(lat, lon, z)
                    coords.extend((x - center_x + width / 2 + shift, y - center_y + height / 2))
                self.map.create_polygon(coords, fill="#090c0f", outline="#38424b", width=1)
        if z >= 8 and self.map_mode.get() != ONLINE_MAP:
            for ring, (lon_min, lat_min, lon_max, lat_max) in self.coastline_rings:
                north_y = geo_to_world(lat_max, 0, z)[1] - center_y + height / 2
                south_y = geo_to_world(lat_min, 0, z)[1] - center_y + height / 2
                left_x = geo_to_world(0, lon_min, z)[0] - center_x + width / 2
                right_x = geo_to_world(0, lon_max, z)[0] - center_x + width / 2
                if south_y < 0 or north_y > height or right_x < 0 or left_x > width:
                    continue
                coords = []
                for lon, lat in ring:
                    x, y = geo_to_world(lat, lon, z)
                    coords.extend((x - center_x + width / 2, y - center_y + height / 2))
                self.map.create_polygon(coords, fill="#090c0f", outline="#38424b", width=1)

    def _draw_graticule(self, width: int, height: int) -> None:
        z = self.map_zoom
        spacing = 45 if z <= 2 else 15 if z <= 4 else 5 if z <= 6 else 1 if z <= 8 else 0.25
        center_x, center_y = geo_to_world(*self.map_center, z)
        world = TILE_SIZE * 2 ** z
        lon_left = ((center_x - width / 2) / world) * 360 - 180
        lon_right = ((center_x + width / 2) / world) * 360 - 180
        first_lon = math.ceil(lon_left / spacing) * spacing
        for index in range(min(100, math.ceil((lon_right - first_lon) / spacing) + 1)):
            lon = first_lon + index * spacing
            x = (lon + 180) / 360 * world - center_x + width / 2
            if 0 <= x <= width:
                self.map.create_line(x, 0, x, height, fill="#163343")
        lat_top = world_to_geo(center_x, center_y - height / 2, z)[0]
        lat_bottom = world_to_geo(center_x, center_y + height / 2, z)[0]
        first_lat = math.ceil(lat_bottom / spacing) * spacing
        for index in range(min(100, math.ceil((lat_top - first_lat) / spacing) + 1)):
            lat = first_lat + index * spacing
            if abs(lat) >= 85:
                continue
            y = geo_to_world(lat, 0, z)[1] - center_y + height / 2
            if 0 <= y <= height:
                self.map.create_line(0, y, width, y, fill="#163343")

    def _draw_world_cables(self, width: int, height: int) -> None:
        z = self.map_zoom
        world = TILE_SIZE * 2 ** z
        center_x, center_y = geo_to_world(*self.map_center, z)
        for index, cable in enumerate(self.world_cables):
            for segment in cable["segments"]:
                if len(segment) < 2:
                    continue
                points = []
                previous_x = None
                for lon, lat in segment:
                    wx, wy = geo_to_world(lat, lon, z)
                    if previous_x is None:
                        wx += round((center_x - wx) / world) * world
                    else:
                        wx += round((previous_x - wx) / world) * world
                    previous_x = wx
                    points.append((wx - center_x + width / 2, wy - center_y + height / 2))
                for shift in (-world, 0, world):
                    xs = [point[0] + shift for point in points]
                    ys = [point[1] for point in points]
                    if max(xs) < 0 or min(xs) > width or max(ys) < 0 or min(ys) > height:
                        continue
                    coords = [coordinate for x, y in points for coordinate in (x + shift, y)]
                    selected = index == self.selected_cable
                    self.map.create_line(coords, fill=TEAL if selected else "#617387",
                                         width=2.5 if selected else .8 if z < 6 else 1.1,
                                         tags=(f"world-cable:{index}",))

    def _draw_world_ports(self, width: int, height: int) -> list:
        z = self.map_zoom
        world = TILE_SIZE * 2 ** z
        center_x, center_y = geo_to_world(*self.map_center, z)
        clusters: dict[tuple[int, int], list[tuple[int, float, float]]] = {}
        labels = []
        self._port_clusters = {}
        for index, port in enumerate(self.world_ports):
            if hasattr(self, "irish_ports_only") and self.irish_ports_only.get() and index not in self.irish_port_indices:
                continue
            _number, _name, lat, lon, _country = port
            wx, wy = geo_to_world(lat, lon, z)
            wx += round((center_x - wx) / world) * world
            x = wx - center_x + width / 2
            y = wy - center_y + height / 2
            if y < -5 or y > height + 5:
                continue
            for shift in (-world, 0, world):
                sx = x + shift
                if sx < -5 or sx > width + 5:
                    continue
                if z <= 5:
                    clusters.setdefault((int(sx // 25), int(y // 25)), []).append((index, sx, y))
                else:
                    selected = index == self.selected_port
                    radius = 6 if selected else 2.8
                    self.map.create_oval(sx - radius, y - radius, sx + radius, y + radius,
                                         fill=TEAL if selected else "#8ba2ad", outline=TEAL if selected else '', width=1.5 if selected else 0,
                                         tags=(f"world-port:{index}",))
                    if selected or (z >= 8 and len(labels) < 40):
                        labels.append((-1 if selected else 3, "port", _name, sx, y))
        if z <= 5:
            for members in clusters.values():
                count = len(members)
                index = members[0][0]
                x = sum(m[1] for m in members) / count
                y = sum(m[2] for m in members) / count
                tag = f"world-port-cluster:{len(self._port_clusters)}" if count > 1 else f"world-port:{index}"
                if count > 1:
                    self._port_clusters[tag] = members
                radius = 2.8 if count == 1 else 7
                self.map.create_oval(x - radius, y - radius, x + radius, y + radius,
                                     fill="#78909c", outline='', width=0,
                                     tags=(tag,))
                if count > 1:
                    self.map.create_text(x, y, text=str(count), fill=BG, font=("Segoe UI", 8, "bold"), tags=(tag,))
        return labels

    def _draw_map(self, force_static: bool = False) -> None:
        size = (self.map.winfo_width(), self.map.winfo_height())
        if size[0] < 100 or size[1] < 100:
            return
        self._map_size = size
        width, height = size
        exercise = not hasattr(self, "exercise_visible") or self.exercise_visible.get()
        self.map.delete("all")
        self.map.create_rectangle(0, 0, width, height, fill=SEA, outline="")
        map_labels: list[tuple[int, str, str, float, float]] = []
        grid_label_boxes: list[tuple[int, int, int, int]] = []
        if self.map_mode.get() != ONLINE_MAP and not getattr(self, "console_layout", False):
            self._draw_graticule(width, height)
        self._draw_global_land(width, height)
        if self.map_mode.get() == ONLINE_MAP:
            center_x, center_y = geo_to_world(*self.map_center, self.map_zoom)
            for z, x, y, x_absolute, y_absolute in self._visible_tiles():
                image = self._tile_images.get((z, x, y))
                sx = x_absolute * TILE_SIZE - center_x + width / 2
                sy = y_absolute * TILE_SIZE - center_y + height / 2
                if image:
                    self.map.create_image(sx, sy, image=image, anchor="nw")
            self.map.create_text(12, 12, text="NASA BLUE MARBLE · DISPLAY ONLY", anchor="nw",
                                 fill="#1e3550", font=("Segoe UI Semibold", 9), tags="map_title")
            self.map_status_label.configure(text=self._tile_status or "NASA imagery · cached on this device")
            self.map_attribution_label.configure(text="NASA Earthdata · Natural Earth · NGA · TeleGeography")
        else:
            self.map.create_text(12, 12, text="GLOBAL COASTLINE · DISPLAY ONLY", anchor="nw",
                                 fill=MUTED, font=("Segoe UI Semibold", 9), tags="map_title")
            self.map_status_label.configure(text="Drag to pan · wheel, two-finger scroll or +/- to zoom" if not self.map_tool else self.map_status_label.cget("text"))
            self.map_attribution_label.configure(text="Natural Earth · Marine Atlas CC BY 4.0 · NGA · TeleGeography")

        self._draw_weather_overlay(width, height)
        if self.map_layers["Historical cable routes"].get():
            self._draw_world_cables(width, height)
        if self.map_layers["World ports"].get():
            map_labels.extend(self._draw_world_ports(width, height))
        self._draw_wind_arrows(width, height)
        self._prediction_banner = None
        if hasattr(self, "ais_tracker"):
            self.ais_tracker.draw()
        if hasattr(self, "alert_board"):
            self.alert_board.draw()

        show_prediction = exercise and self.map_layers["Dark prediction"].get()
        dark = self._dark_state() if show_prediction else None
        if dark:
            desktop_prediction.draw_areas(self, dark["position"]["prediction"])
        if exercise and self.map_layers["Anchor reach"].get():
            for cable in self.scenario["cables"]:
                self.map.create_line(*self._points(cable["anchor_reachable"]), fill="#e4b45f", width=11, dash=(3, 4))
        if exercise and self.map_layers["Cable"].get():
            for cable in self.scenario["cables"]:
                self.map.create_line(*self._points(cable["path"]), fill="white", width=7)
                self.map.create_line(*self._points(cable["path"]), fill=TEAL, width=3)
        if dark and dark["countdown"]:
            desktop_prediction.draw_worst_case(self, dark["position"]["prediction"], dark["countdown"])
        if exercise and self.map_layers["Response assets"].get():
            for asset in self.scenario["assets"]:
                if asset.get("lat") is None or asset.get("lon") is None:
                    continue
                x, y = self._project(asset["lat"], asset["lon"])
                self.map.create_oval(x - 7, y - 7, x + 7, y + 7, fill=CONTROL, outline=TEAL, width=2)
                map_labels.append((2, "asset", asset["name"].split("(")[0].strip(), x, y))

        if exercise and self.map_layers["AIS track"].get():
            for section in trail_sections(self.vessel["track"], self.position_s):
                if len(section) > 1:
                    self.map.create_line(*self._points(section), fill="#45dbe6", width=3)
        if exercise and self.map_layers["Radar contacts"].get():
            for detection in self.scenario["detections"]:
                if detection["t"] > self.position_s:
                    continue
                x, y = self._project(detection["lat"], detection["lon"])
                self.map.create_polygon(x, y - 10, x + 10, y, x, y + 10, x - 10, y,
                                        fill="#f6d293", outline="#8f4d00", width=2)
                label = f"SAR {self._utc(detection['t'])} · {detection.get('length_m', '?')} m"
                map_labels.append((1, "radar", label, x, y))
        if exercise and self.position_s >= self.alert["t"]:
            at_alert = fix_at(self.vessel["track"], self.alert["t"])
            if at_alert:
                crossing = step(at_alert["lat"], at_alert["lon"], at_alert["cog_deg"], at_alert["sog_kn"] * self.alert["eta_expected_s"] / 3600)
                self.map.create_line(*self._points([(at_alert["lat"], at_alert["lon"]), crossing]), fill=AMBER, width=2, dash=(5, 5))
        fix = fix_at(self.vessel["track"], self.position_s) if exercise and self.map_layers["AIS track"].get() else None
        if show_prediction:
            self._draw_reappearance(map_labels)
        if fix:
            x, y = self._project(fix["lat"], fix["lon"])
            self.map.create_oval(x - 13, y - 13, x + 13, y + 13, fill=SEA, outline=PURPLE, width=2)
            self.map.create_oval(x - 9, y - 9, x + 9, y + 9, fill=PURPLE, outline=SEA, width=2)
            map_labels.append((0, "vessel", f"{self.vessel['name']}\n{fix['sog_kn']:.1f} kn · {fix['cog_deg']:.0f}°", x, y))
        elif dark:
            prediction = dark["position"]["prediction"]
            x, y = desktop_prediction.draw_marker(self, prediction)
            map_labels.append((0, "vessel", f"{self.vessel['name']} · best guess\n"
                                            f"±{dark['position']['uncertainty_nm']:.1f} nm", x, y))
            self._prediction_banner = prediction
        elif not fix_at(self.vessel["track"], self.position_s) and self.position_s < self.vessel["track"][-1]["t"]:
            self.map.create_text(width / 2, 42, text="AIS RECEPTION GAP · marker withdrawn", fill=AMBER, font=("Segoe UI Semibold", 10))
        for index, (lat, lon) in enumerate(self.map_note_points, 1):
            x, y = self._project(lat, lon)
            self.map.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#d7be70", outline="white", width=2)
            self.map.create_text(x, y, text=str(index), fill="white", font=("Segoe UI", 8, "bold"))
        if self.measure_points:
            for lat, lon in self.measure_points:
                x, y = self._project(lat, lon)
                self.map.create_oval(x - 5, y - 5, x + 5, y + 5, fill="white", outline="#ae5600", width=2)
        if self.measurement_line:
            self.map.create_line(*self._points(self.measurement_line), fill="#ae5600", width=2, dash=(5, 3))
            km = distance_km(*self.measurement_line)
            midpoint = ((self.measurement_line[0][0] + self.measurement_line[1][0]) / 2,
                        (self.measurement_line[0][1] + self.measurement_line[1][1]) / 2)
            mx, my = self._project(*midpoint)
            self.map.create_text(mx, my - 12, text=f"{km:.2f} km / {km / 1.852:.2f} nm", fill="#7d3e00", font=("Segoe UI Semibold", 9))
        reserved = list(grid_label_boxes)
        for _priority, kind, label, x, y in sorted(map_labels, key=lambda item: item[0]):
            self._draw_map_callout(label, x, y, kind, reserved)
        self._draw_weather_legend()
        self.map.create_rectangle(4, height - 24, width - 4, height - 3, fill=CARD, outline="")
        self.map.create_text(10, height - 13,
                             text="Irish AIS observations · received positions only" if not exercise else "Reference ports and cables · exercise overlays fictional",
                             anchor="w", fill="#93a8b5", font=("Segoe UI", 8))
        if width >= 350:
            lat = self.map_center[0]
            km_per_pixel = math.cos(math.radians(lat)) * 40075.017 / (TILE_SIZE * 2 ** self.map_zoom)
            target = km_per_pixel * 80
            power = 10 ** math.floor(math.log10(max(target, .00001)))
            km = next(v * power for v in (1, 2, 5, 10) if v * power >= target)
            pixels = km / km_per_pixel
            self.map.create_rectangle(width - pixels - 24, height - 56, width - 8, height - 27, fill=CARD, outline=LINE)
            self.map.create_line(width - pixels - 16, height - 35, width - 16, height - 35, width=2, fill=INK)
            self.map.create_text(width - 16, height - 48, text=f"{km:g} km · z{self.map_zoom}", anchor="e", fill=INK, font=("Segoe UI", 8))
        if self._prediction_banner:
            desktop_prediction.draw_banner(self, self._prediction_banner)
        self._draw_map_ping()

    def _dark_state(self) -> dict | None:
        """Predicted position and worst-case cable countdown while the exercise vessel is dark."""
        track = self.vessel["track"]
        if not track or fix_at(track, self.position_s):
            return None
        position = position_at(track, self.position_s)
        if position is None or position["status"] != "predicted":
            return None
        return {"position": position, "countdown": dark_countdown(track, self.cable, self.position_s)}

    def _reappearance(self) -> dict | None:
        """Consistency of the latest AIS return with the fix before its gap, once observed."""
        track = self.vessel["track"]
        gap = last_gap(track, self.position_s)
        if gap is None:
            return None
        before, after = gap
        return {"before": before, "after": after,
                **reappearance_check(before, after, v_max_kn(track, before["t"]))}

    def _draw_reappearance(self, map_labels: list) -> None:
        check = self._reappearance()
        if check is None or self.position_s - check["after"]["t"] > REAPPEARANCE_SHOW_S:
            return
        before, after = check["before"], check["after"]
        self.map.create_line(*self._points([(before["lat"], before["lon"]), (after["lat"], after["lon"])]),
                             fill=AMBER, width=2, dash=(2, 4))
        x, y = self._project(after["lat"], after["lon"])
        map_labels.append((1, "radar", f"AIS back: {check['verdict'].replace('_', ' ').upper()}\n"
                                       f"{check['distance_nm']:.1f} of {check['reachable_nm']:.1f} nm reachable", x, y))

    def _utc(self, position_s: float) -> str:
        start = datetime.fromisoformat(self.scenario["t0_utc"].replace("Z", "+00:00"))
        return (start + timedelta(seconds=position_s)).strftime("%H:%M:%S UTC")

    def _remaining(self) -> tuple[float, float] | None:
        if self.position_s < self.alert["t"]:
            return None
        elapsed = self.position_s - self.alert["t"]
        return max(0, self.alert["eta_expected_s"] - elapsed), max(0, self.alert["eta_earliest_s"] - elapsed)

    def render(self) -> None:
        if hasattr(self, 'tools'):
            self.tools.update_legend()
        for alert, label in getattr(self, "alert_cards", []):
            if self.exercise_visible.get() and self.alert['id'] == alert['id']:
                remaining = self._remaining()
                label.configure(text=clock(remaining[0]) if remaining else '--:--:--')
            else:
                label.configure(text='--:--:--')
        self.time_label.configure(text=f"{self._utc(self.position_s)} · T+{clock(self.position_s)}")
        self.play_button.configure(text="Pause" if self.playing else "Play")
        self._moving_scale = True
        self.timeline.set(self.position_s)
        self._moving_scale = False
        fix = fix_at(self.vessel["track"], self.position_s)
        remaining = self._remaining()
        state = "ALERT · review required" if remaining else "AIS reception gap" if not fix else "Vessel under watch"
        self.state_label.configure(text=state, text_color=AMBER if remaining or not fix else TEAL)
        self.countdown_label.configure(text=clock(remaining[0]) if remaining else "--:--:--")
        self.summary_state_label.configure(text="Review required" if remaining else "AIS gap" if not fix else "Under watch")
        self.summary_countdown_label.configure(text=clock(remaining[0]) if remaining else "--:--:--")
        self.summary_distance_label.configure(text=f"{self.alert['distance_km']:.1f} km")
        self.earliest_label.configure(text=f"Earliest planning estimate: {clock(remaining[1])}" if remaining else "Waiting for alert")
        self.distance_label.configure(text=f"{self.alert['distance_km']} km to illustrative cable at alert · {self.cable['label']}" if remaining else "Countdown begins at the observed alert fix")
        if not remaining:
            self._render_prediction_status()
        self.reasons_label.configure(text="\n\n".join(f"• {reason}" for reason in self.alert["reasons"]) if remaining else "Observations appear as the replay advances.")
        options = []
        for option in self.alert["options"]:
            eta = "—" if option["eta_s"] is None else f"{math.ceil(option['eta_s'] / 60)} min"
            status = response_status(option, remaining[1]) if remaining else "Pending"
            options.append(f"{option['asset']}\n  {eta}  ·  {status}")
        self.options_label.configure(text="\n\n".join(options))
        can_approve = remaining and any(response_status(option, remaining[1]) == "In time" for option in self.alert["options"])
        self.approve_button.configure(state="normal" if can_approve and not self.approved else "disabled")
        self.approval_label.configure(text=f"Simulated {self.approved['asset']} approved at {self._utc(self.approved['time'])}" if self.approved else "Operator approval required")
        current_beat = max((index for index, (_, beat_time) in enumerate(self._beats(), 1) if self.position_s >= beat_time), default=1)
        self.beat_label.configure(text=f"Beat {current_beat:02d} / 07")
        self.summary_beat_label.configure(text=f"{current_beat:02d} / 07")
        self._draw_map()

    def _render_prediction_status(self) -> None:
        """Before the alert, show the dark-vessel countdown or the latest AIS-return check."""
        dark = self._dark_state()
        check = self._reappearance()
        if dark and dark["countdown"]:
            countdown = dark["countdown"]
            self.state_label.configure(text="AIS reception gap · position predicted\n"
                                            f"Worst-case cable contact in {clock(countdown['remaining_s'])}")
            self.earliest_label.configure(text=f"Worst-case cable contact in {clock(countdown['remaining_s'])}")
            self.distance_label.configure(
                text=f"Predicted, not observed: {countdown['distance_nm']:.1f} nm from the last AIS fix to the "
                     f"anchor-reachable section at an assumed maximum of {countdown['v_max_kn']:.0f} kn.")
        elif check:
            self.distance_label.configure(
                text=f"AIS returned at T+{clock(check['after']['t'])}: {check['verdict'].replace('_', ' ')} · "
                     f"{check['distance_nm']:.1f} of {check['reachable_nm']:.1f} nm reachable. {check['note']}")

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = min(now - self.last_frame, .5)
        self.last_frame = now
        if self.playing:
            self.position_s = min(self.duration, self.position_s + elapsed * self.rate.get())
            if self.position_s >= self.duration:
                self.playing = False
            if int(self.position_s) != self._last_second:
                self._last_second = int(self.position_s)
                self.render()
        self.root.after(80, self._tick)

    def _scale_changed(self, value: str) -> None:
        if not self._moving_scale:
            self.seek(float(value))

    def _space(self, event: tk.Event) -> None:
        if isinstance(event.widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Scale, tk.Text, tk.Entry,
                                     ctk.CTkButton, ctk.CTkEntry, ctk.CTkOptionMenu, ctk.CTkSlider)):
            return
        if hasattr(self, "exercise_visible") and not self.exercise_visible.get():
            return
        self.toggle_play()

    def toggle_play(self) -> None:
        if self.position_s >= self.duration:
            self.seek(0)
        self.playing = not self.playing
        self.last_frame = time.monotonic()
        self.render()

    def seek(self, position_s: float) -> None:
        self.playing = False
        self.position_s = max(0, min(self.duration, position_s))
        self.approved = None
        self.render()

    def _evidence_text(self) -> str:
        remaining = self._remaining()
        detection = next((d for d in self.scenario["detections"] if d["t"] <= self.position_s), None)
        lines = [
            f"Scenario: {self.scenario['name']} ({self.scenario['label']})",
            f"Vessel: {self.vessel['name']} ({self.vessel['label']})",
            f"Cable: {self.cable['name']} ({self.cable['label']}); geometry is illustrative.",
            f"Replay time: {self._utc(self.position_s)}",
            "",
            "REVIEW CUES",
            *(self.alert["reasons"] if remaining else ["The alert has not fired yet."]),
            "",
            "RADAR REVIEW",
        ]
        if detection:
            lines.extend([
                f"Separate {detection['label']} contact at {self._utc(detection['t'])}: estimated {detection.get('length_m', 'unknown')} m.",
                f"AIS-declared length: {self.vessel.get('ais_length_m', 'unknown')} m.",
                "Association and identity are unconfirmed; measurement uncertainty needs review.",
            ])
        else:
            lines.append("No radar observation is available yet.")
        lines.extend([
            "",
            "COUNTDOWN AND LIMITS",
            self.alert.get("eta_method", "Constant speed and course from the alert fix."),
            "The 250 m anchor-reach cutoff and response capabilities are assumptions.",
            "An AIS gap or unmatched radar contact is a lead for review, not proof of malicious action.",
            self.alert.get("score_basis", ""),
            "",
            "OPERATOR DECISION",
            json.dumps(self.approved, indent=2) if self.approved else "Human approval has not been recorded.",
            "No operational action was sent.",
        ])
        return "\n".join(lines)

    def review_evidence(self) -> None:
        if not self.require_tool('evidence.share'):
            return
        self.playing = False
        self.render()
        self.open_window("evidence", self._panel_locations.get("evidence", "right"))

    def review_response(self) -> None:
        if not self.require_tool('response.review'):
            return
        remaining = self._remaining()
        if not remaining or self.approved:
            return
        available = [option for option in self.alert["options"] if response_status(option, remaining[1]) == "In time"]
        self.playing = False
        self.render()
        self._decision_choice.set("")
        self._decision_acknowledged.set(False)
        self.open_window("decision", self._panel_locations.get("decision", "right"))

    def save_record(self, parent: tk.Misc | None = None) -> None:
        if not self.require_tool('evidence.share'):
            return
        if not self._remaining():
            return
        parent = parent or self.root
        target = filedialog.asksaveasfilename(parent=parent, title="Save exercise decision record",
                                              defaultextension=".html", filetypes=[("HTML document", "*.html")],
                                              initialfile=f"argus-mara-{self.alert['id']}-exercise-evidence.html")
        if not target:
            return
        report = escape(self._evidence_text())
        alert_json = escape(json.dumps(self.alert, indent=2, ensure_ascii=False))
        html = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>Argus Mara exercise evidence</title>"
                "<style>body{max-width:850px;margin:40px auto;padding:20px;font:15px/1.6 system-ui;color:#172530}"
                "pre{white-space:pre-wrap;background:#f4f6f7;padding:18px;border:1px solid #d5dde1}</style>"
                f"<h1>Argus Mara · {escape(self.alert['id'])}</h1><p>Simulated exercise · {escape(self._utc(self.position_s))}</p>"
                f"<pre>{report}</pre><h2>Exact alert contract</h2><pre>{alert_json}</pre></html>")
        try:
            Path(target).write_text(html, encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=parent)
        else:
            messagebox.showinfo("Record saved", f"Saved to {target}", parent=parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the local demo files without opening a window")
    parser.add_argument('--soc', default=os.environ.get('ARGUS_SOC_URL', ''), help='prefill the SOC HTTPS origin on the sign-in screen')
    parser.add_argument('--soc-login', action='store_true', help='open the SOC sign-in screen even if no address is configured')
    parser.add_argument('--soc-dev-http', action='store_true', help='allow HTTP only to localhost for development tests')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--offline', action='store_true', help='open one offline window without login or Docker')
    modes.add_argument('--soc-client', action='store_true', help='sign-in only; do not offer local server startup')
    args = parser.parse_args()
    if args.offline and (args.soc_login or args.soc_client):
        parser.error('--offline cannot be combined with SOC sign-in flags')
    try:
        scenario, alerts, coastline = load_demo()
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Unable to load Argus Mara: {error}\n")
    if args.check:
        try:
            land, ports, cables = load_world_assets()
            irish = load_irish_ports()
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.exit(1, f"Unable to load global map layers: {error}\n")
        print(f"Desktop demo ready: {len(scenario['vessels'])} vessel(s), {len(alerts['alerts'])} alert(s), "
              f"{land['count']} global land rings, {ports['count']} world ports, {irish['count']} Irish port records, {cables['count']} historical cable routes.")
        return 0
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    if not args.offline:
        from desktop_soc import login_screen
        def logged_in(client):
            if 'map.view' not in client.user['permissions']:
                messagebox.showerror('Access denied', 'Ask an administrator to grant map.view access.', parent=root)
                client.logout()
                root.destroy()
                return
            ArgusApp(root, scenario, alerts, coastline, soc_client=client)
        login_screen(root, args.soc, logged_in, allow_loopback_http=args.soc_dev_http,
                     on_offline=None if args.soc_login or args.soc_client else
                     lambda: ArgusApp(root, scenario, alerts, coastline),
                     local_launcher=not args.soc_client)
    else:
        ArgusApp(root, scenario, alerts, coastline)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
