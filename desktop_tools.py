"""Local desktop navigation, review workflow and layout preferences."""
import json
import math
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from desktop_console import RAIL_WIDTH
from desktop_style import Icons

from argus.map_view import search_text
from desktop_ais import speed_range, vessel_type

PRESETS = {
    'Irish coast': {'points': [(49, -18), (57.5, -4.5)]},
    'Irish Sea': {'points': [(51.2, -7), (55.7, -3.7)]},
    'Western approaches': {'points': [(49.8, -17), (56.5, -9)]},
    'Dublin Bay': {'points': [(53.2, -6.5), (53.45, -5.95)]},
    'Cork Harbour': {'points': [(51.7, -8.5), (51.95, -8.1)]},
}


def parse_coordinates(query):
    match = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*([NSns]?)\s*[,; ]\s*([+-]?\d+(?:\.\d+)?)\s*([EWew]?)\s*', query)
    if not match:
        return None
    lat, ns, lon, ew = match.groups()
    lat, lon = float(lat), float(lon)
    if ns:
        lat = abs(lat) * (-1 if ns.upper() == 'S' else 1)
    if ew:
        lon = abs(lon) * (-1 if ew.upper() == 'W' else 1)
    if not (-85.05112878 <= lat <= 85.05112878 and -180 <= lon <= 180):
        raise ValueError('Coordinates must be within ±85.0511° latitude and ±180° longitude')
    return lat, lon


def search_results(app, query, custom_views=None):
    coordinate = parse_coordinates(query)
    if coordinate:
        return [('coordinate', coordinate, f'{coordinate[0]:.5f}, {coordinate[1]:.5f}', 'Latitude, longitude')]
    tokens = search_text(query).split()
    matches = []
    views = {**PRESETS, **(custom_views or {})}
    for name in views:
        if all(token in search_text(name) for token in tokens):
            matches.append(('view', name, name, 'Saved map view'))
    if not tokens:
        return matches
    for vessel in app.ais_tracker.state.vessels.values():
        name = f"{vessel['name']} / {vessel['mmsi']}"
        if all(token in search_text(name + ' ' + vessel_type(vessel.get('type'))) for token in tokens):
            matches.append(('vessel', vessel['mmsi'], name, vessel_type(vessel.get('type'))))
    for index, (identifier, name, _lat, _lon, country) in enumerate(app.world_ports):
        if all(token in search_text(f'{name} {identifier} {country}') for token in tokens):
            matches.append(('port', index, name, f'Port / {country} / ref {identifier}'))
    return matches


class ConsoleTools:
    def __init__(self, app):
        self.app = app
        self.alert_width, self.detail_width = 320, 405
        self.alerts_visible = True
        self.custom_views = {}
        self.alert_statuses = {a['id']: tk.StringVar(app.root, value='New') for a in app.alerts}
        self.review_values = {a['id']: 'New' for a in app.alerts}
        self.alert_messages = {}
        self.search_query = tk.StringVar(app.root, value='')
        self.search_matches = []
        self.palette = None
        self.save_timer = None
        self.drag = None
        self.legend_sar = None
        self.icons = Icons()
        self.alert_details = {}
        self.tooltip = None
        self.tooltip_timer = None
        self.animations = {}
        self.reduced_motion = tk.BooleanVar(app.root, value=os.environ.get('ARGUS_REDUCED_MOTION') == '1')
        location = os.environ.get('ARGUS_UI_PREFERENCES', str(Path(__file__).resolve().parent / 'data/desktop/ui_preferences.json'))
        self.settings_path = Path(location) if location else None
        self.settings = {}
        if self.settings_path:
            try:
                data = json.loads(self.settings_path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    self.settings = data
            except (OSError, ValueError):
                pass

    def setup(self):
        import run_gui as ui
        for attribute, default, minimum, maximum in (('alert_width', 320, 260, 480), ('detail_width', 405, 330, 620)):
            value = self.settings.get(attribute, default)
            setattr(self, attribute, max(minimum, min(maximum, value)) if type(value) is int else default)
        self.alerts_visible = self.settings.get('alerts_visible', True) is not False
        self.reduced_motion.set(self.settings.get('reduced_motion', self.reduced_motion.get()) is True)
        for name, view in self.settings.get('views', {}).items() if isinstance(self.settings.get('views'), dict) else []:
            if self.valid_view(name, view):
                self.custom_views[name] = view
        self.resize_handle(self.app.alerts_panel, 'alerts', 'right')
        self.resize_handle(self.app.floating_panel, 'details', 'left')
        self.app.root.bind('<Control-k>', self.open_search)
        self.app.root.bind('<Control-K>', self.open_search)
        self.app._position_console_panel()
        self.legend = ctk.CTkFrame(self.app.chart_host, fg_color=ui.BG, corner_radius=8)
        self.legend_controls = {}
        self.place_legend()
        self.app.root.after_idle(self.place_legend)
        tracker = self.app.ais_tracker
        for title, variable, color, inverse in (
            ('Ships', tracker.visible, '#6bba97', False),
            ('Stale', tracker.fresh_only, '#778896', True),
            ('Ports', self.app.map_layers['World ports'], '#9badb8', False),
            ('Cables', self.app.map_layers['Historical cable routes'], '#73899e', False),
            ('SAR demo', self.app.map_layers['Radar contacts'], ui.AMBER, False),
            ('Sim alerts', self.app.map_layers['Simulated alerts'], '#a48bd8', False),
        ):
            control = ctk.CTkCheckBox(self.legend, text=title, variable=variable, onvalue=not inverse,
                offvalue=inverse, command=lambda: self.app._draw_map(force_static=True), width=65,
                checkbox_width=14, checkbox_height=14, text_color=color, fg_color=color,
                hover_color=ui.HOVER, font=ctk.CTkFont('Segoe UI', 11))
            control.pack(side='left', padx=5, pady=10)
            self.legend_controls[title] = control
            if title == 'SAR demo':
                self.legend_sar = control
            self.attach_tooltip(control, {'Stale': 'Show or hide fixes older than the feed freshness interval',
                                          'Sim alerts': 'Simulated alert markers: fictional vessels, not live data'}.get(title, f'{title}: toggle this map layer'))
        for variable in (tracker.visible, tracker.fresh_only, tracker.kind, tracker.minimum_speed, tracker.maximum_speed):
            variable.trace_add('write', lambda *_: self.schedule_save())
        filters = self.settings.get('filters', {})
        if isinstance(filters, dict):
            try:
                speed_range(filters.get('minimum', ''), filters.get('maximum', ''))
                tracker.fresh_only.set(filters.get('fresh_only') is True)
                tracker.kind.set(str(filters.get('type', 'All types'))[:64])
                tracker.minimum_speed.set(str(filters.get('minimum', '')))
                tracker.maximum_speed.set(str(filters.get('maximum', '')))
                tracker.visible.set(filters.get('visible', True) is not False)
            except ValueError:
                pass
        self.update_alert_counts()
        self.update_legend()

    def place_legend(self):
        """Keep the legend just right of the map mode buttons, whatever their font width."""
        modes = getattr(self.app, 'modes_bar', None)
        x = 455
        if modes is not None:
            scaling = ctk.ScalingTracker.get_widget_scaling(modes)
            x = 16 + modes.winfo_reqwidth() / scaling + 10
        self.legend.place(x=x, rely=1, y=-54, anchor='sw')

    @staticmethod
    def valid_view(name, view):
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or name in PRESETS or not isinstance(view, dict):
            return False
        center, zoom = view.get('center'), view.get('zoom')
        return (isinstance(center, list) and len(center) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in center)
                and -85.05112878 <= center[0] <= 85.05112878 and -180 <= center[1] <= 180 and type(zoom) is int and 1 <= zoom <= 13)

    def schedule_save(self):
        if self.settings_path is None:
            return
        if self.save_timer:
            self.app.root.after_cancel(self.save_timer)
        self.save_timer = self.app.root.after(400, self.save)

    def save(self):
        self.save_timer = None
        if not self.settings_path:
            return
        tracker = self.app.ais_tracker
        data = {'alert_width': self.alert_width, 'detail_width': self.detail_width,
            'reduced_motion': self.reduced_motion.get(),
            'alerts_visible': self.alerts_visible, 'views': self.custom_views,
            'filters': {'fresh_only': tracker.fresh_only.get(), 'type': tracker.kind.get(),
                'minimum': tracker.minimum_speed.get(), 'maximum': tracker.maximum_speed.get(), 'visible': tracker.visible.get()}}
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data), encoding='utf-8')
            temporary.replace(self.settings_path)
        except OSError:
            pass

    def resize_handle(self, parent, kind, edge):
        import run_gui as ui
        docked = kind == 'alerts'
        handle = ctk.CTkFrame(parent, width=4 if docked else 5, fg_color=ui.LINE, corner_radius=0, cursor='sb_h_double_arrow')
        if docked:
            # The docked board's right border doubles as its resize handle.
            handle.place(relx=1, x=-4, y=0, relheight=1)
            handle.bind('<Enter>', lambda _: handle.configure(fg_color=ui.TEAL), add=True)
            handle.bind('<Leave>', lambda _: handle.configure(fg_color=ui.LINE), add=True)
        else:
            handle.place(relx=1 if edge == 'right' else 0, x=-5 if edge == 'right' else 0, y=6, relheight=.97)
        handle.bind('<ButtonPress-1>', lambda e: self.start_resize(kind, e.x_root))
        handle.bind('<B1-Motion>', lambda e: self.resize(kind, e.x_root))
        handle.bind('<ButtonRelease-1>', lambda _: self.schedule_save())
        handle.bind('<Enter>', lambda _: self.app.map_status_label.configure(text=f'Drag this edge to resize {kind}'), add=True)

    def start_resize(self, kind, x):
        self.drag = (x, self.alert_width if kind == 'alerts' else self.detail_width)

    def resize(self, kind, x):
        if not self.drag:
            return
        start, width = self.drag
        # The docked alerts narrow the map; the detail panel floats over the map.
        scaling = ctk.ScalingTracker.get_widget_scaling(self.app.chart_frame)
        if kind == 'alerts':
            total = self.app.chart_frame.winfo_width() / scaling
            self.alert_width = max(260, min(480, total - RAIL_WIDTH - 420, width + x - start))
        else:
            available = self.app.chart_host.winfo_width() / scaling
            self.detail_width = max(330, min(620, available - 294, width + start - x))
        self.app._position_console_panel()

    def toggle_alerts(self):
        self.alerts_visible = not self.alerts_visible
        self.app.layout_columns()
        self.schedule_save()

    def review_alert(self, alert):
        self.app.open_exercise_alert(alert)
        if self.alert_statuses[alert['id']].get() == 'New':
            self.set_alert_status(alert['id'], 'Reviewed')

    def set_alert_status(self, identifier, value):
        current = self.review_values[identifier]
        if value not in ('New', 'Reviewed', 'Acknowledged'):
            return
        if value == 'Acknowledged' and current == 'New':
            message = 'Review the exercise alert first'
            self.alert_statuses[identifier].set(current)
        else:
            self.review_values[identifier] = value
            self.alert_statuses[identifier].set(value)
            message = 'Acknowledgement records review only' if value == 'Acknowledged' else ''
        if identifier in self.alert_messages:
            self.alert_messages[identifier].configure(text=message)
        if message and identifier in self.alert_details and not self.alert_details[identifier][0].winfo_manager():
            self.toggle_alert_details(identifier)
        self.update_alert_counts()

    def update_alert_counts(self):
        board = getattr(self.app, 'alert_board', None)
        if board is not None:
            board.refresh_statuses()
        elif hasattr(self.app, 'alert_counts_label'):
            states = [v.get() for v in self.alert_statuses.values()]
            self.app.alert_counts_label.configure(text=f"{states.count('New')} new / {states.count('Reviewed')} reviewed / {states.count('Acknowledged')} acknowledged")

    def update_legend(self):
        if self.legend_sar:
            self.legend_sar.configure(state='normal' if self.app.exercise_visible.get() else 'disabled')

    def toggle_alert_details(self, identifier):
        frame, actions, button = self.alert_details[identifier]
        if frame.winfo_manager():
            frame.pack_forget()
            button.configure(text='Details')
        else:
            frame.pack(fill='x', padx=12, pady=(0, 8), before=actions)
            button.configure(text='Hide details')

    def attach_tooltip(self, widget, title):
        widget.bind('<Enter>', lambda _: self.request_tooltip(widget, title), add=True)
        widget.bind('<Leave>', lambda _: self.hide_tooltip(), add=True)
        widget.bind('<ButtonPress-1>', lambda _: self.hide_tooltip(), add=True)

    def style_button(self, widget, title=None):
        import run_gui as ui
        original = widget.cget('border_width')
        widget.bind('<FocusIn>', lambda _: widget.configure(border_width=1, border_color=ui.TEAL), add=True)
        widget.bind('<FocusOut>', lambda _: widget.configure(border_width=original, border_color=ui.LINE), add=True)
        def activate(_event):
            widget.invoke()
            return 'break'
        widget.bind('<Return>', activate, add=True)
        widget.bind('<space>', activate, add=True)
        if title:
            self.attach_tooltip(widget, title)

    def request_tooltip(self, widget, title):
        self.hide_tooltip()
        self.tooltip_timer = self.app.root.after(300, lambda: self.show_tooltip(widget, title))

    def show_tooltip(self, widget, title):
        import run_gui as ui
        self.tooltip_timer = None
        if not widget.winfo_exists():
            return
        # The outer chart frame spans the rail, the docked alerts and the map.
        host = getattr(self.app, 'chart_frame', self.app.chart_host)
        if self.tooltip is None:
            self.tooltip = ctk.CTkLabel(host, text='', fg_color=ui.CONTROL,
                text_color=ui.INK, corner_radius=6, font=ctk.CTkFont('Segoe UI', 12), wraplength=260)
        self.tooltip.configure(text=title)
        self.tooltip.update_idletasks()
        scaling = ctk.ScalingTracker.get_widget_scaling(self.tooltip)
        x = widget.winfo_rootx() - host.winfo_rootx()
        y = max(8, widget.winfo_rooty() - host.winfo_rooty())
        if x > host.winfo_width() - 300:
            self.tooltip.place(x=(x-8) / scaling, y=y / scaling, anchor='ne')
        else:
            self.tooltip.place(x=(x+widget.winfo_width()+8) / scaling, y=y / scaling, anchor='nw')
        self.tooltip.lift()

    def hide_tooltip(self):
        if self.tooltip_timer:
            self.app.root.after_cancel(self.tooltip_timer)
            self.tooltip_timer = None
        if self.tooltip:
            self.tooltip.place_forget()

    def cancel_animation(self, key):
        timer = self.animations.pop(key, None)
        if timer:
            self.app.root.after_cancel(timer)

    def animate(self, key, widget, start, end, placement):
        self.cancel_animation(key)
        def step(index=0):
            progress = 1 if self.reduced_motion.get() else min(1, index / 8)
            eased = 1 - (1 - progress) ** 3
            x = round(start[0] + (end[0] - start[0]) * eased)
            y = round(start[1] + (end[1] - start[1]) * eased)
            widget.place(x=x, y=y, **placement)
            if progress < 1:
                self.animations[key] = self.app.root.after(16, lambda: step(index+1))
            else:
                self.animations.pop(key, None)
        step()

    def build_views(self, frame):
        ttk.Label(frame, text='Display presets and locally saved map views', style='Muted.TLabel').pack(anchor='w')
        table = ttk.Treeview(frame, columns=('name',), show='headings', height=8)
        table.heading('name', text='Map view')
        table.column('name', width=280)
        table.pack(fill='both', expand=True, pady=10)
        def refresh():
            table.delete(*table.get_children())
            for name in {**PRESETS, **self.custom_views}:
                table.insert('', 'end', iid=name, values=(name,))
        def open_selected(_=None):
            if table.selection():
                self.apply_view(table.selection()[0])
        ttk.Button(frame, text='Open selected view', command=open_selected).pack(anchor='w')
        table.bind('<Double-1>', open_selected)
        table.bind('<Return>', open_selected)
        name = tk.StringVar(self.app.root)
        ttk.Label(frame, text='Name this map view').pack(anchor='w', pady=(10, 0))
        ttk.Entry(frame, textvariable=name).pack(fill='x', pady=5)
        message = ttk.Label(frame, style='Muted.TLabel', wraplength=330)
        message.pack(anchor='w')
        def save_current():
            title = name.get().strip()
            view = {'center': list(self.app.map_center), 'zoom': self.app.map_zoom}
            if not self.valid_view(title, view):
                message.configure(text='Choose a name of 1–64 characters that differs from the presets')
                return
            self.custom_views[title] = view
            self.schedule_save()
            refresh()
            message.configure(text='Saved locally')
        def remove():
            if table.selection() and table.selection()[0] in self.custom_views:
                self.custom_views.pop(table.selection()[0])
                self.schedule_save()
                refresh()
        ttk.Button(frame, text='Save current view', command=save_current).pack(anchor='w', pady=4)
        ttk.Button(frame, text='Delete selected saved view', command=remove).pack(anchor='w')
        refresh()

    def apply_view(self, name):
        view = {**PRESETS, **self.custom_views}.get(name)
        if not view:
            return
        self.app.ais_tracker.follow.set(False)
        if self.app.exercise_visible.get():
            self.app.hide_exercise()
        if 'points' in view:
            self.app._fit_points(view['points'])
        else:
            import run_gui as ui
            self.app.map_zoom = min(view['zoom'], ui.MAX_IMAGERY_ZOOM if self.app.map_mode.get() == ui.ONLINE_MAP else ui.MAX_MAP_ZOOM)
            self.app._change_map_center(tuple(view['center']))

    def open_search(self, _event=None):
        import run_gui as ui
        if self.palette is None:
            self.palette = ctk.CTkFrame(self.app.chart_host, width=650, height=380,
                fg_color=ui.CARD, border_width=1, border_color=ui.LINE, corner_radius=10)
            title = ctk.CTkFrame(self.palette, fg_color='transparent')
            title.pack(fill='x', padx=14, pady=8)
            ctk.CTkLabel(title, text='Search ships, ports, views or coordinates', text_color=ui.INK).pack(side='left')
            close = ctk.CTkButton(title, text='', image=self.icons.get('close'), command=self.close_search,
                                  width=32, height=32, fg_color='transparent', hover_color=ui.HOVER)
            close.pack(side='right')
            self.style_button(close, 'Close search · Escape')
            self.search_entry = ctk.CTkEntry(self.palette, textvariable=self.search_query, height=36,
                fg_color=ui.CONTROL, border_color=ui.LINE, text_color=ui.INK,
                border_width=1, corner_radius=8, font=ctk.CTkFont('Segoe UI', 13))
            self.search_entry.pack(fill='x', padx=14, pady=6)
            self.search_entry.bind('<FocusIn>', lambda _: self.search_entry.configure(border_color=ui.TEAL), add=True)
            self.search_entry.bind('<FocusOut>', lambda _: self.search_entry.configure(border_color=ui.LINE), add=True)
            self.search_table = ttk.Treeview(self.palette, columns=('kind', 'name', 'info'), show='headings', height=8)
            for key, width in (('kind', 80), ('name', 260), ('info', 230)):
                self.search_table.heading(key, text=key.title())
                self.search_table.column(key, width=width)
            self.search_table.pack(fill='both', expand=True, padx=14, pady=8)
            self.search_note = ctk.CTkLabel(self.palette, text='', text_color=ui.MUTED)
            self.search_note.pack(anchor='w', padx=14, pady=(0, 8))
            self.search_query.trace_add('write', lambda *_: self.update_search())
            self.search_entry.bind('<Return>', self.choose_search)
            self.search_entry.bind('<Escape>', lambda _: self.close_search())
            self.search_entry.bind('<Down>', self.next_search)
            self.search_entry.bind('<Up>', lambda _: self.next_search(direction=-1))
            self.search_table.bind('<Return>', self.choose_search)
            self.search_table.bind('<Double-1>', self.choose_search)
            self.search_table.bind('<Escape>', lambda _: self.close_search())
        self.animate('search', self.palette, (0, 13), (0, 25), {'relx': .5, 'anchor': 'n'})
        self.palette.lift()
        self.update_search()
        self.search_entry.focus_set()
        return 'break'

    def update_search(self):
        if self.palette is None:
            return
        self.search_table.delete(*self.search_table.get_children())
        try:
            results = search_results(self.app, self.search_query.get(), self.custom_views)
            self.search_matches = results[:100]
            note = f'{len(results)} matches / first {len(self.search_matches)} shown' if results else 'No matches. Coordinates use latitude, longitude.'
        except ValueError as error:
            self.search_matches, note = [], str(error)
        for index, (kind, _target, name, info) in enumerate(self.search_matches):
            self.search_table.insert('', 'end', iid=str(index), values=(kind.title(), name, info))
        if self.search_matches:
            self.search_table.selection_set('0')
        self.search_note.configure(text=note)

    def next_search(self, _event=None, direction=1):
        if self.search_matches:
            selected = self.search_table.selection()
            index = int(selected[0]) if selected else 0
            index = max(0, min(len(self.search_matches) - 1, index + direction))
            self.search_table.selection_set(str(index))
            self.search_table.see(str(index))
        return 'break'

    def choose_search(self, _event=None):
        selected = self.search_table.selection()
        if not selected:
            return 'break'
        kind, target, _name, _info = self.search_matches[int(selected[0])]
        self.close_search()
        tracker = self.app.ais_tracker
        tracker.follow.set(False)
        if kind == 'vessel':
            tracker.reset_filters()
            tracker.visible.set(True)
            tracker.select_on_map(target)
            tracker.center()
        elif kind == 'port':
            self.app.open_window('ports')
            self.app.port_country.set('Irish coast' if target in self.app.irish_port_indices else 'All countries')
            self.app.port_query.set(self.app.world_ports[target][1])
            self.app._select_port(target)
            self.app._center_selected_port()
        elif kind == 'view':
            self.apply_view(target)
        else:
            import run_gui as ui
            self.app.map_zoom = 8 if self.app.map_mode.get() == ui.ONLINE_MAP else 10
            self.app._change_map_center(target)
        return 'break'

    def close_search(self):
        self.cancel_animation('search')
        self.hide_tooltip()
        if self.palette is not None:
            self.palette.place_forget()

    def close(self):
        self.hide_tooltip()
        for key in list(self.animations):
            self.cancel_animation(key)
        if self.save_timer:
            self.app.root.after_cancel(self.save_timer)
        self.save()
