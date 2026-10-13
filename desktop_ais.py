"""Opt-in AIS observations in the offline desktop shell; no detector or response."""
from datetime import datetime, timezone
import json
import math
import os
import queue
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from argus.live_client import LivePoller, LiveState, server_url
from desktop_prediction import AMBER, draw_areas, draw_marker, live_prediction, outlined_text
from desktop_tracks import ReceivedTracks

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
        self.history = ReceivedTracks()
        self.fleet = set()
        self.card = None
        self.last_cache_s = 0
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
        self.show_path = tk.BooleanVar(app.root, value=True)
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
                if cache_path.stat().st_size > 40 * 1024 * 1024:
                    raise ValueError('Oversized AIS cache')
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("server", DEFAULT_SERVER) == self.address.get():
                    self.state.apply(cached)
                    fleet = cached.get('desktop_fleet', [])
                    if isinstance(fleet, list) and len(fleet) <= 5000:
                        self.fleet = {m for m in fleet if isinstance(m, str) and len(m) == 9 and m.isascii() and m.isdigit() and int(m) > 0}
                    now = datetime.now(timezone.utc).timestamp()
                    self.history.restore(cached.get('desktop_tracks', {}), self.state.vessels, now)
                    self.history.capture(self.state.vessels, self.state.stream_id, now)
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
        detail_body = ctk.CTkScrollableFrame(self.detail_tab, fg_color='#141e28')
        detail_body.pack(fill='both', expand=True)
        self.detail = ttk.Label(detail_body, wraplength=310, justify="left")
        self.detail.pack(anchor="w", pady=10)
        ttk.Checkbutton(detail_body, text='Show selected ship path', variable=self.show_path,
                        command=self.app._draw_map).pack(anchor='w')
        ttk.Checkbutton(detail_body, text='Follow selected ship', variable=self.follow,
                        command=self.update_follow).pack(anchor='w')
        ttk.Button(detail_body, text='Center selected ship', command=self.center).pack(anchor='w', pady=10)
        ttk.Button(detail_body, text='Fit recorded path', command=self.fit_path).pack(anchor='w')
        ttk.Button(detail_body, text='Clear ship selection', command=self.clear_selection).pack(anchor='w', pady=8)
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
            self.history = ReceivedTracks()
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
        payload['desktop_tracks'] = dict(self.history.tracks)
        payload['desktop_fleet'] = sorted(self.fleet)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.cache_path)
            self.last_cache_s = datetime.now(timezone.utc).timestamp()
        except OSError:
            pass  # Failure to cache cannot stop a read-only feed.

    def disconnect(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        self.state = LiveState()
        self.history = ReceivedTracks()
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
                        applied = self.state.apply(value)
                        changed = applied or changed
                        if applied:
                            self.history.capture(self.state.vessels, self.state.stream_id,
                                                 datetime.now(timezone.utc).timestamp())
                        self.status = f"Connected · {self.state.feed['status']} · {self.state.feed['label']}"
                    except ValueError:
                        self.status = "Invalid AIS response · last valid observations retained"
                else:
                    self.status = f"Connection: {value} · last fixes retained"
        now = datetime.now(timezone.utc).timestamp()
        self.history.prune(now, set(self.state.vessels))
        self.refresh()
        if changed and now - self.last_cache_s >= 15:
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
            self.update_detail()
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
            points = self.history.tracks.get(self.selected, [])
            origin = (f"First recorded fix: {points[0]['lat']:.5f}, {points[0]['lon']:.5f}\n"
                      f"Path starts UTC: {points[0]['received_utc']}\n"
                      f"Recorded path: {len(points)} fixes / {points[0]['label']}\n") if points else 'Recorded path: awaiting fresh received fixes\n'
            destination = vessel.get('destination') or 'Not reported'
            destination_time = vessel.get('destination_received_utc') or 'Unavailable'
            text = (f"{vessel['name']} · MMSI {vessel['mmsi']}\nType: {vessel_type(vessel.get('type'))}\n"
                    f"Speed: {speed} / Course: {course}\n{position}\n"
                    f"{freshness} / fix age {age_text(vessel['received_s'], now)}\n"
                    f"Received UTC: {vessel['received_utc'] or 'Unavailable'}\nEvidence: {vessel['label']}\n\n"
                    f"Declared destination: {destination}\nDestination received UTC: {destination_time}\n\n"
                    f"{origin}Local history: up to 24 h / 720 fixes per ship.\n"
                    'Reception gaps stay open. Departure port is unknown; declared destination is unverified.')
        if self.detail is not None and self.detail.winfo_exists():
            self.detail.configure(text=text)
        if self.card is not None:
            self.card.refresh()

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

    def fit_path(self):
        self.follow.set(False)
        points = self.history.tracks.get(self.selected, [])
        if points:
            self.app._fit_points([(p['lat'], p['lon']) for p in points])

    def clear_selection(self):
        self.selected = None
        if self.card is not None:
            self.card.hide()
        self.follow.set(False)
        if self.table is not None and self.table.winfo_exists():
            self.table.selection_remove(self.table.selection())
        self.update_detail()
        self.app._draw_map()

    def draw_path(self, visible_contacts):
        if not self.show_path.get() or self.selected not in visible_contacts:
            return
        tags = ('received_ais', 'selected_ais_path')
        sections = self.history.sections(self.selected)
        for section in sections:
            points = [self.app._project(p['lat'], p['lon']) for p in section]
            # Also split at the projection seam of the current wrapped map view.
            previous = None
            for x, y in points:
                if previous and abs(x - previous[0]) < 256 * 2 ** self.app.map_zoom / 2:
                    self.app.map.create_line(*previous, x, y, fill='#a89b72', width=5, tags=tags)
                    self.app.map.create_line(*previous, x, y, fill='#ffd15a', width=3, tags=tags)
                previous = (x, y)
        history = self.history.tracks.get(self.selected, [])
        if history:
            first = history[0]
            x, y = self.app._project(first['lat'], first['lon'])
            self.app.map.create_oval(x-3, y-3, x+3, y+3, outline='#ffd15a', width=1.5, tags=tags)

    def selected_prediction(self, now):
        """Labelled prediction for the selected contact once its last received fix is stale."""
        vessel = self.state.vessels.get(self.selected)
        layer = getattr(self.app, 'map_layers', {}).get('Dark prediction')
        if vessel is None or (layer is not None and not layer.get()):
            return None
        return live_prediction(vessel, now, self.state.feed.get('stale_seconds', 900))

    def draw(self):
        if not self.visible.get():
            return
        now = datetime.now(timezone.utc).timestamp()
        width, height = self.app._map_size
        contacts = self.filtered()
        visible = {v['mmsi'] for v in contacts}
        prediction = self.selected_prediction(now) if self.selected in visible else None
        if prediction:
            draw_areas(self.app, prediction, tags=('received_ais',))
        self.draw_path(visible)
        for vessel in contacts:
            if vessel['received_s'] is None:
                continue
            x, y = self.app._project(vessel['lat'], vessel['lon'])
            if not (-10 <= x <= width + 10 and -10 <= y <= height + 10):
                continue
            stale = now - vessel['received_s'] > self.state.feed.get('stale_seconds', 900)
            color = "#71828c" if stale else "#6bba97"
            if vessel['mmsi'] == self.selected:
                color = "#ffd15a"
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
                self.app.map.create_oval(x - 10, y - 10, x + 10, y + 10, outline=color, width=1.5,
                                         tags=tags)
                # A bold, outlined name remains readable over any map layer.
                name_tags = (*tags, 'selected_ais_name')
                label_x, anchor = (x - 15, 'e') if x > width - 320 else (x + 15, 'w')
                name = vessel['name'] if len(vessel['name']) <= 36 else vessel['name'][:35] + '…'
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1)):
                    self.app.map.create_text(label_x + dx, y + dy, anchor=anchor, fill='#ffffff',
                        text=name, font=('Segoe UI', 15, 'bold'), tags=name_tags)
                self.app.map.create_text(label_x, y, anchor=anchor, fill='#26333c',
                    text=name, font=('Segoe UI', 15, 'bold'), tags=name_tags)
        if prediction:
            # The contact itself already marks the last received fix and carries its name.
            x, y = draw_marker(self.app, prediction, last_point=False, tags=('received_ais',))
            outlined_text(self.app.map, x, y - 26, f"best guess now · ±{prediction['reachable']['radius_nm']:.1f} nm",
                          fill=AMBER, size=10, tags=('received_ais',))
            if hasattr(self.app, '_prediction_banner'):
                self.app._prediction_banner = prediction
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
        if getattr(self.app, 'console_layout', False):
            self.app.hide_console_panel()
            if self.card is None:
                from desktop_vessel_card import VesselCard
                self.card = VesselCard(self)
            self.card.show()
        self.app._draw_map()

    def close(self):
        self.closed = True
        if self.poller:
            self.poller.stop()
        if self.card is not None:
            self.card.close()
        if self.state.stream_id is not None and hasattr(self, 'connected_address'):
            self.save_cache()
        self.app.root.after_cancel(self.timer)
