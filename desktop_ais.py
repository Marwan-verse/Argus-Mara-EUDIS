"""Opt-in AIS observations in the offline desktop shell; no detector or response."""
from datetime import datetime, timezone
import json
import math
import os
import queue
import tkinter as tk
from tkinter import ttk

from argus.live_client import LivePoller, LiveState, server_url

DEFAULT_SERVER = "https://shared-live-ais-production.up.railway.app"


def vessel_type(value):
    """Broad AIS type labels; USCG AIS Message 5 / AIS Encoding Guide."""
    text = str(value or '').strip()
    try:
        code = int(text)
    except ValueError:
        return text if text and text.casefold() not in ('unavailable', 'unknown', 'none') else 'Unknown'
    if 70 <= code <= 79:
        return 'Cargo'
    if 80 <= code <= 89:
        return 'Tanker'
    if 60 <= code <= 69:
        return 'Passenger'
    if 40 <= code <= 49:
        return 'High-speed craft'
    return {30: 'Fishing', 31: 'Tug / tow', 32: 'Tug / tow', 35: 'Military',
            36: 'Sailing', 37: 'Pleasure craft', 51: 'Search and rescue',
            52: 'Tug / tow', 57: 'Tug / tow', 0: 'Unknown'}.get(code, f'Other ({code})')


def speed_range(minimum='', maximum=''):
    values = []
    for text in (minimum, maximum):
        if not str(text).strip():
            values.append(None)
            continue
        try:
            value = float(text)
        except (TypeError, ValueError):
            raise ValueError('Speed limits must be numbers in knots') from None
        if not math.isfinite(value) or not 0 <= value <= 102.2:
            raise ValueError('Speed limits must be between 0 and 102.2 kn')
        values.append(value)
    low, high = values
    if low is not None and high is not None and low > high:
        raise ValueError('Minimum speed must not exceed maximum speed')
    return low, high


def filter_contacts(vessels, now, stale_seconds, fresh_only=False, kind='All types', low=None, high=None):
    result = []
    for vessel in vessels:
        if fresh_only and (vessel['received_s'] is None or now - vessel['received_s'] > stale_seconds):
            continue
        if kind != 'All types' and vessel_type(vessel.get('type')) != kind:
            continue
        speed = vessel['sog_kn']
        if (low is not None or high is not None) and (speed is None or low is not None and speed < low or high is not None and speed > high):
            continue
        result.append(vessel)
    return result


def age_text(received_s, now):
    if received_s is None:
        return "No position"
    seconds = max(0, now - received_s)
    if seconds < 60:
        return "<1 min"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 3600)} h"


class DesktopAIS:
    def __init__(self, app, poller_factory=LivePoller, cache_path=None):
        self.app = app
        self.poller_factory = poller_factory
        self.state = LiveState()
        self.poller = None
        self.closed = False
        self.status = "Connecting to shared Irish AIS"
        self.cache_path = cache_path
        self.address = tk.StringVar(app.root, value=os.environ.get("ARGUS_LIVE_SERVER", DEFAULT_SERVER))
        self.query = tk.StringVar(app.root, value="")
        self.visible = tk.BooleanVar(app.root, value=True)
        self.fresh_only = tk.BooleanVar(app.root, value=False)
        self.kind = tk.StringVar(app.root, value='All types')
        self.minimum_speed = tk.StringVar(app.root, value='')
        self.maximum_speed = tk.StringVar(app.root, value='')
        self.follow = tk.BooleanVar(app.root, value=False)
        self.filter_error = ''
        self.filter_label = self.type_selector = None
        self.tabs = self.detail_tab = None
        for variable in (self.fresh_only, self.kind, self.minimum_speed, self.maximum_speed):
            variable.trace_add('write', self.filters_changed)
        self.selected = None
        self.limit = 90
        self.table = self.status_label = self.detail = self.count = None
        self.query.trace_add("write", self.search)
        self.timer = app.root.after(500, self.poll)
        if cache_path is not None:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("server", DEFAULT_SERVER) == self.address.get():
                    self.state.apply(cached)
                    self.connected_address = self.address.get()
                    self.status = "Cached AIS observations · waiting for live refresh"
            except (OSError, ValueError, TypeError):
                pass

    def build(self, frame):
        ttk.Label(frame, text="Irish coastline / received AIS observations",
                  style="Muted.TLabel", wraplength=330).pack(anchor="w", pady=(0, 10))
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        ttk.Button(actions, text="Reconnect", command=self.connect).pack(side="left")
        ttk.Button(actions, text="Disconnect", command=self.disconnect).pack(side="left", padx=5)
        settings = ttk.Frame(frame)
        ttk.Label(settings, text="AIS server (HTTPS)").pack(anchor="w")
        ttk.Entry(settings, textvariable=self.address).pack(fill="x", pady=6)
        ttk.Button(settings, text="Connect to this server", command=self.connect).pack(anchor="w")
        def toggle_settings():
            if settings.winfo_manager():
                settings.pack_forget()
            else:
                settings.pack(fill="x", after=actions, pady=8)
        ttk.Button(actions, text="Server", command=toggle_settings).pack(side="right")
        self.status_label = ttk.Label(frame, text=self.status, wraplength=330, style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=10)
        ttk.Checkbutton(frame, text="Show all received AIS ships on the map", variable=self.visible,
                        command=self.app._draw_map).pack(anchor="w")
        self.tabs = ttk.Notebook(frame, style='Dock.TNotebook')
        self.tabs.pack(fill='both', expand=True, pady=8)
        directory = ttk.Frame(self.tabs, padding=6)
        self.detail_tab = ttk.Frame(self.tabs, padding=6)
        filters = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(directory, text='Ships')
        self.tabs.add(self.detail_tab, text='Selected ship')
        self.tabs.add(filters, text='Filters')
        self.detail = ttk.Label(self.detail_tab, wraplength=330, justify="left")
        self.detail.pack(anchor="w", pady=10)
        ttk.Checkbutton(self.detail_tab, text='Follow selected ship', variable=self.follow,
                        command=self.update_follow).pack(anchor='w')
        ttk.Button(self.detail_tab, text='Center selected ship', command=self.center).pack(anchor='w', pady=10)
        ttk.Checkbutton(filters, text='Fresh fixes only', variable=self.fresh_only).pack(anchor='w')
        self.type_selector = ttk.Combobox(filters, textvariable=self.kind, state='readonly',
            values=['All types'] + sorted({vessel_type(v.get('type')) for v in self.state.vessels.values()}))
        self.type_selector.pack(fill='x', pady=4)
        speeds = ttk.Frame(filters)
        speeds.pack(fill='x')
        ttk.Label(speeds, text='Speed kn').pack(side='left')
        ttk.Entry(speeds, textvariable=self.minimum_speed, width=6).pack(side='left', padx=4)
        ttk.Label(speeds, text='to').pack(side='left')
        ttk.Entry(speeds, textvariable=self.maximum_speed, width=6).pack(side='left', padx=4)
        ttk.Button(speeds, text='Reset', command=self.reset_filters).pack(side='right')
        self.filter_label = ttk.Label(filters, style='Muted.TLabel', wraplength=330)
        self.filter_label.pack(anchor='w')
        frame = directory
        ttk.Label(frame, text="Search vessel name or MMSI").pack(anchor="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.query).pack(fill="x", pady=6)
        self.count = ttk.Label(frame, style="Muted.TLabel")
        self.count.pack(anchor="w")
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=6)
        self.table = ttk.Treeview(holder, columns=("name", "speed", "age", "label"),
                                  show="headings", selectmode="browse", height=7)
        for key, title, width in (("name", "Vessel / MMSI", 160), ("speed", "kn", 55),
                                  ("age", "Fix age", 65), ("label", "Evidence", 75)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=45)
        scrollbar = ttk.Scrollbar(holder, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.table.bind("<Double-1>", lambda _: self.center())
        self.table.bind("<Return>", lambda _: self.center())
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Show more", command=self.more).pack(side="left")
        ttk.Button(buttons, text="Center selected", command=self.center).pack(side="left", padx=5)
        ttk.Button(buttons, text="Fit AIS", command=self.fit).pack(side="left")
        ttk.Label(frame, text="Green: fresh fix / muted: stale / cyan: selected. Received positions only; provider reception is incomplete.",
                  style="Muted.TLabel", wraplength=330).pack(anchor="w")
        self.refresh()

    def connect(self):
        try:
            address = server_url(self.address.get().strip())
        except ValueError as error:
            self.status = str(error)
            self.refresh()
            return
        if self.poller:
            self.poller.stop()
        # Preserve a validated cached snapshot while the new connection starts.
        # A server switch must not mix observations from different services.
        if getattr(self, "connected_address", address) != address:
            self.state = LiveState()
            self.selected = None
        self.connected_address = address
        self.poller = self.poller_factory(address)
        self.poller.start()
        self.status = "Connecting · waiting for received observations"
        self.refresh()

    def save_cache(self):
        if self.cache_path is None:
            return
        payload = {"schema_version": 1, "stream_id": self.state.stream_id,
            "server": self.connected_address,
            "sequence": self.state.sequence,
            "generated_utc": datetime.fromtimestamp(self.state.generated_s, timezone.utc).isoformat(),
            "feed": self.state.feed, "vessels": list(self.state.vessels.values())}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.cache_path)
        except OSError:
            pass  # Failure to cache cannot stop a read-only feed.

    def disconnect(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        self.state = LiveState()
        self.selected = None
        self.follow.set(False)
        self.status = "Disconnected · received positions cleared"
        self.refresh()
        self.update_header()
        self.app._draw_map()

    def update_header(self):
        if hasattr(self.app, "feed_header"):
            total = len(self.positions())
            now = datetime.now(timezone.utc)
            fresh = sum(now.timestamp() - v['received_s'] <= self.state.feed.get('stale_seconds', 900)
                        for v in self.positions())
            connection = self.state.feed['status'].upper() if self.status.startswith('Connected') else 'CONNECTING' if self.status.startswith('Connecting') else 'RECONNECTING' if self.poller else 'OFFLINE'
            if hasattr(self.app, 'feed_counts_label'):
                self.app.feed_header.configure(text=connection.title(), text_color='#a8b6c2' if connection in ('LIVE', 'OFFLINE') else '#e1b164')
                self.app.feed_counts_label.configure(text=f'{total:,} / {fresh:,}')
                self.app.utc_header.configure(text=f'{now:%H:%M:%S}Z')
            else:
                self.app.feed_header.configure(text=f"{total:,} SHIPS / {fresh:,} FRESH / {connection}")
                self.app.utc_header.configure(text=f"ZULU {now:%H:%M:%S}Z")

    def poll(self):
        if self.closed:
            return
        changed = False
        if self.poller:
            while True:
                try:
                    kind, value = self.poller.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "data":
                    try:
                        changed = self.state.apply(value) or changed
                        self.status = f"Connected · {self.state.feed['status']} · {self.state.feed['label']}"
                    except ValueError:
                        self.status = "Invalid AIS response · last valid observations retained"
                else:
                    self.status = f"Connection: {value} · last fixes retained"
        self.refresh()
        if changed:
            self.save_cache()
        self.update_header()
        if self.follow.get():
            self.center()
        if changed or self.state.vessels:
            self.app._draw_map()
        self.timer = self.app.root.after(2000, self.poll)

    def search(self, *_):
        self.limit = 90
        self.refresh()

    def filters_changed(self, *_):
        self.limit = 90
        self.refresh()
        self.app._draw_map()

    def reset_filters(self):
        self.fresh_only.set(False)
        self.kind.set('All types')
        self.minimum_speed.set('')
        self.maximum_speed.set('')

    def filtered(self):
        try:
            low, high = speed_range(self.minimum_speed.get(), self.maximum_speed.get())
            self.filter_error = ''
        except ValueError as error:
            self.filter_error = str(error)
            return []
        return filter_contacts(self.state.vessels.values(), datetime.now(timezone.utc).timestamp(),
            self.state.feed.get('stale_seconds', 900), self.fresh_only.get(), self.kind.get(), low, high)

    def more(self):
        self.limit += 90
        self.refresh()

    def refresh(self):
        if self.status_label is None or not self.status_label.winfo_exists():
            return
        self.status_label.configure(text=self.status)
        now = datetime.now(timezone.utc).timestamp()
        query = self.query.get().strip().casefold()
        rows = sorted((v for v in self.filtered()
                       if query in f"{v['name']} {v['mmsi']}".casefold()),
                      key=lambda v: (v['name'].casefold(), v['mmsi']))
        visible = rows[:self.limit]
        desired = {v['mmsi'] for v in visible}
        for identifier in self.table.get_children():
            if identifier not in desired:
                self.table.delete(identifier)
        for index, vessel in enumerate(visible):
            identifier = vessel['mmsi']
            values = (f"{vessel['name']} / {identifier}",
                      "—" if vessel['sog_kn'] is None else f"{vessel['sog_kn']:.1f}",
                      age_text(vessel['received_s'], now), vessel['label'])
            if self.table.exists(identifier):
                self.table.item(identifier, values=values)
                self.table.move(identifier, "", index)
            else:
                self.table.insert("", "end", iid=identifier, values=values)
        self.count.configure(text=f"{len(visible)} shown / {len(rows)} matches / {len(self.state.vessels)} contacts")
        if self.filter_label is not None and self.filter_label.winfo_exists():
            self.filter_label.configure(text=self.filter_error or 'Filters apply to the directory and map')
        if self.type_selector is not None and self.type_selector.winfo_exists():
            self.type_selector.configure(values=['All types'] + sorted({self.kind.get()} - {'All types'} |
                {vessel_type(v.get('type')) for v in self.state.vessels.values()}))
        self.update_detail()

    def select(self, _event=None):
        selection = self.table.selection()
        if selection:
            changed = self.selected != selection[0]
            self.selected = selection[0]
            self.update_detail()
            if changed:
                self.tabs.select(self.detail_tab)
            self.app._draw_map()

    def update_detail(self):
        vessel = self.state.vessels.get(self.selected)
        text = "Select a contact to inspect its received UTC and position."
        if vessel:
            position = "No position received" if vessel['received_s'] is None else f"{vessel['lat']:.5f}, {vessel['lon']:.5f}"
            now = datetime.now(timezone.utc).timestamp()
            freshness = 'No position' if vessel['received_s'] is None else 'Fresh' if now - vessel['received_s'] <= self.state.feed.get('stale_seconds', 900) else 'Stale'
            speed = 'Unavailable' if vessel['sog_kn'] is None else f"{vessel['sog_kn']:.1f} kn"
            course = 'Unavailable' if vessel['cog_deg'] is None else f"{vessel['cog_deg']:.1f}°"
            text = (f"{vessel['name']} · MMSI {vessel['mmsi']}\nType: {vessel_type(vessel.get('type'))}\n"
                    f"Speed: {speed} / Course: {course}\n{position}\n"
                    f"{freshness} / fix age {age_text(vessel['received_s'], now)}\n"
                    f"Received UTC: {vessel['received_utc'] or 'Unavailable'}\nEvidence: {vessel['label']}")
        if self.detail is not None and self.detail.winfo_exists():
            self.detail.configure(text=text)

    def positions(self):
        return [v for v in self.state.vessels.values() if v['received_s'] is not None]

    def center(self):
        vessel = self.state.vessels.get(self.selected)
        if vessel and vessel['received_s'] is not None:
            self.app._change_map_center((vessel['lat'], vessel['lon']))

    def update_follow(self):
        if self.follow.get():
            vessel = self.state.vessels.get(self.selected)
            if not vessel or vessel['received_s'] is None:
                self.follow.set(False)
            else:
                self.center()

    def fit(self):
        self.follow.set(False)
        self.app._fit_points([(v['lat'], v['lon']) for v in self.filtered() if v['received_s'] is not None])

    def draw(self):
        if not self.visible.get():
            return
        now = datetime.now(timezone.utc).timestamp()
        width, height = self.app._map_size
        for vessel in self.filtered():
            if vessel['received_s'] is None:
                continue
            x, y = self.app._project(vessel['lat'], vessel['lon'])
            if not (-10 <= x <= width + 10 and -10 <= y <= height + 10):
                continue
            stale = now - vessel['received_s'] > self.state.feed.get('stale_seconds', 900)
            color = "#71828c" if stale else "#6bba97"
            if vessel['mmsi'] == self.selected:
                color = "#47c7da"
            angle = math.radians(vessel['cog_deg'] or 0)
            shape = []
            for across, along in ((0, -6), (4, 4), (0, 2), (-4, 4)):
                shape.extend((x + across * math.cos(angle) - along * math.sin(angle),
                              y + across * math.sin(angle) + along * math.cos(angle)))
            tags = ("received_ais", "ais-ship:" + vessel['mmsi'])
            if stale and vessel['mmsi'] != self.selected:
                self.app.map.create_oval(x-2.3, y-2.3, x+2.3, y+2.3, fill=color, outline='', tags=tags)
            else:
                self.app.map.create_polygon(shape, fill=color, outline='', tags=tags)
            if vessel['mmsi'] == self.selected:
                self.app.map.create_oval(x - 14, y - 14, x + 14, y + 14, outline=color, width=1.5,
                                         tags=tags)
                self.app.map.create_text(x + 16, y, anchor="w", fill=color,
                    text=f"{vessel['name']} · {vessel['label']} · {age_text(vessel['received_s'], now)}",
                    tags=tags)
        if not self.positions():
            self.app.map.create_text(width / 2, height / 2, fill="#d9bb47", font=("Consolas", 15),
                text="CONNECTING TO IRISH AIS" if self.poller else "AIS DISCONNECTED",
                tags="received_ais")
        elif self.filter_error or not self.filtered():
            self.app.map.create_text(width / 2, height / 2, fill='#d9bb47',
                text=self.filter_error or 'No contacts match these filters', tags='received_ais')
        if not getattr(self.app, "console_layout", False):
            self.app.map.create_text(12, 34, anchor="nw", fill="#00dce8", tags="received_ais",
                text=f"Received AIS: {len(self.positions())} positions · {self.status}")

    def select_on_map(self, mmsi):
        if mmsi not in self.state.vessels:
            return
        self.selected = mmsi
        self.app.open_window("ais")
        self.query.set(mmsi)
        self.refresh()
        if self.table.exists(mmsi):
            self.table.selection_set(mmsi)
            self.table.see(mmsi)
        self.update_detail()
        self.tabs.select(self.detail_tab)
        self.app._draw_map()

    def close(self):
        self.closed = True
        if self.poller:
            self.poller.stop()
        self.app.root.after_cancel(self.timer)
