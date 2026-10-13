"""Floating vessel summary, using received data and optional local photographs."""
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageOps

from desktop_style import Icons

WHITE = '#ffffff'
INK = '#26333c'
MUTED = '#75808a'
LINE = '#e0e5e9'
BLUE = '#0879df'
GOLD = '#ffd15a'
NAVIGATION = {0: 'Underway using engine', 1: 'At anchor', 2: 'Not under command',
              3: 'Restricted manoeuvrability', 4: 'Constrained by draught', 5: 'Moored',
              6: 'Aground', 7: 'Engaged in fishing', 8: 'Underway sailing',
              11: 'Towing astern', 12: 'Pushing / towing alongside', 14: 'AIS safety beacon'}


def navigation_status(value):
    # USCG AIS Class A reports: 15 is the undefined/default value.
    return NAVIGATION.get(value, f'Reserved ({value})' if value in (9, 10, 13) else 'Not reported')


def age_description(stamp, now):
    if stamp is None:
        return 'No position received'
    minutes = max(0, int((now - stamp) // 60))
    if minutes < 1:
        return 'less than a minute ago'
    hours, minutes = divmod(minutes, 60)
    return f'{hours} h {minutes} min ago' if hours else f'{minutes} min ago'


def local_photo(directory, mmsi):
    """Only explicitly named local files; no photo lookup or screenshot reuse."""
    if not isinstance(mmsi, str) or len(mmsi) != 9 or not mmsi.isascii() or not mmsi.isdigit():
        return None
    for suffix in ('.jpg', '.jpeg', '.png'):
        path = Path(directory) / (mmsi + suffix)
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                continue
            with Image.open(path) as photo:
                if photo.width * photo.height > 20_000_000:
                    continue
                return ImageOps.fit(ImageOps.exif_transpose(photo).convert('RGB'), (720, 340))
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    return None


class VesselCard:
    def __init__(self, tracker):
        self.tracker = tracker
        self.app = tracker.app
        self.parent = getattr(self.app, 'chart_host', self.app.map)
        self.icons = Icons()
        self.visible = False
        self.position = None
        self.drag = None
        self.photo_mmsi = None
        self.photo_image = None
        self.labels = {}
        self.frame = ctk.CTkFrame(self.parent, fg_color=WHITE, border_color='#d2d9df',
                                 border_width=1, corner_radius=8, width=376, height=700)
        self.frame.pack_propagate(False)
        header = ctk.CTkFrame(self.frame, fg_color=WHITE, corner_radius=8, height=60)
        header.pack(fill='x', padx=7, pady=(6, 0))
        self.type_icon = ctk.CTkLabel(header, text='', image=self.icons.get('ship', WHITE, 21),
            fg_color='#e77959', corner_radius=5, width=30, height=30)
        self.type_icon.pack(side='left', padx=(2, 7))
        self.flag = tk.Canvas(header, width=27, height=24, highlightthickness=0, bg=WHITE)
        self.flag.pack(side='left', padx=(0, 7))
        close = self.button(header, '', self.tracker.clear_selection, width=26,
                            image=self.icons.get('close', '#93a0b4'))
        close.pack(side='right', padx=2)
        handle = self.label(header, '⠿', size=23, color='#93a0b4')
        handle.pack(side='right', padx=5)
        title = ctk.CTkFrame(header, fg_color=WHITE)
        title.pack(side='left', fill='x', expand=True)
        self.name = self.label(title, '', size=20, bold=True, wrap=210)
        self.name.pack(anchor='w')
        self.kind = self.label(title, '', size=12, color=MUTED)
        self.kind.pack(anchor='w')
        for widget in (header, handle, self.name, self.kind):
            widget.configure(cursor='fleur')
            widget.bind('<ButtonPress-1>', self.start_drag, add='+')
            widget.bind('<B1-Motion>', self.move_drag, add='+')
            widget.bind('<ButtonRelease-1>', lambda _: setattr(self, 'drag', None), add='+')

        self.body = ctk.CTkScrollableFrame(self.frame, fg_color=WHITE, corner_radius=0,
            scrollbar_button_color='#c4ced6', scrollbar_button_hover_color='#9daab6')
        self.body.pack(fill='both', expand=True, padx=3, pady=(2, 5))
        self.hero = ctk.CTkLabel(self.body, text='', fg_color='#e8eef2', height=170)
        self.hero.pack(fill='x')
        self.photo_note = self.label(self.body, '', size=11, color=MUTED)
        self.photo_note.pack(anchor='w', padx=8, pady=(3, 0))
        actions = ctk.CTkFrame(self.body, fg_color=WHITE)
        actions.pack(fill='x', padx=8, pady=10)
        self.fleet_button = self.button(actions, 'Add to fleet', self.toggle_fleet, width=140)
        self.fleet_button.pack(side='left')
        self.details_button = self.button(actions, 'Vessel details', self.open_details, width=146, primary=True)
        self.details_button.pack(side='right')

        voyage = ctk.CTkFrame(self.body, fg_color=WHITE)
        voyage.pack(fill='x', padx=10, pady=(5, 0))
        voyage.grid_columnconfigure((0, 1), weight=1, uniform='voyage')
        self.label(voyage, 'First recorded fix', color=MUTED, size=11).grid(row=0, column=0, sticky='w')
        self.label(voyage, 'Declared destination', color=MUTED, size=11).grid(row=0, column=1, sticky='e')
        self.origin = self.label(voyage, '', size=17, wrap=145)
        self.origin.grid(row=1, column=0, sticky='nw', pady=5)
        self.destination = self.label(voyage, '', size=17, wrap=155)
        self.destination.grid(row=1, column=1, sticky='ne', pady=5)
        self.start_time = self.label(voyage, '', size=11, wrap=160)
        self.start_time.grid(row=2, column=0, sticky='nw')
        self.eta = self.label(voyage, 'Reported ETA: —', size=11, wrap=155)
        self.eta.grid(row=2, column=1, sticky='ne')
        self.voyage_arrow = tk.Canvas(self.body, bg=WHITE, highlightthickness=0, height=43)
        self.voyage_arrow.pack(fill='x', padx=10, pady=4)
        self.voyage_arrow.bind('<Configure>', self.draw_voyage_arrow)
        controls = ctk.CTkFrame(self.body, fg_color=WHITE)
        controls.pack(pady=(0, 12), padx=8, fill='x')
        self.past_button = self.button(controls, 'Past track', self.toggle_path, width=128)
        self.past_button.pack(side='left')
        self.route_button = self.button(controls, 'Measure route', self.measure_route, width=146)
        self.route_button.pack(side='right')
        self.path_note = self.label(self.body, '', size=11, color=MUTED, wrap=330)
        self.path_note.pack(anchor='w', padx=10, pady=(0, 12))

        metrics = ctk.CTkFrame(self.body, fg_color=LINE, corner_radius=0)
        metrics.pack(fill='x')
        for column, (key, heading) in enumerate((('navigation', 'Navigation status'),
                                                 ('speed', 'Speed / Course'), ('draught', 'Draught'))):
            metrics.grid_columnconfigure(column, weight=1, uniform='metrics')
            cell = ctk.CTkFrame(metrics, fg_color=WHITE, corner_radius=0)
            cell.grid(row=0, column=column, sticky='nsew', padx=(0 if column == 0 else 1, 0), pady=1)
            self.label(cell, heading, size=11, color=MUTED, wrap=101).pack(anchor='w', padx=7, pady=(7, 0))
            self.labels[key] = self.label(cell, '', size=12, bold=True, wrap=101)
            self.labels[key].pack(anchor='w', padx=7, pady=(2, 9))
        self.received = self.label(self.body, '', color=MUTED, size=12, wrap=330)
        self.received.pack(anchor='w', padx=10, pady=(10, 3))
        self.source = self.label(self.body, '', color=MUTED, size=11, wrap=330)
        self.source.pack(anchor='w', padx=10, pady=(0, 10))
        self.resize_binding = self.app.map.bind('<Configure>', self.resize, add='+')

    @staticmethod
    def label(parent, text, size=13, color=INK, bold=False, wrap=0):
        return ctk.CTkLabel(parent, text=text, text_color=color, justify='left', anchor='w',
            height=0, width=0, wraplength=wrap, font=ctk.CTkFont('Segoe UI', size, 'bold' if bold else 'normal'))

    @staticmethod
    def button(parent, text, command, width=120, primary=False, image=None):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=36,
            image=image, fg_color=BLUE if primary else WHITE, hover_color='#0569c4' if primary else '#edf2f6',
            text_color=WHITE if primary else INK, border_width=0 if primary else 1,
            border_color='#afb9c3', corner_radius=4, font=ctk.CTkFont('Segoe UI', 12, 'bold'))

    def show(self):
        self.visible = True
        self.refresh()
        self.resize()
        self.frame.lift()

    def hide(self):
        self.visible = False
        self.frame.place_forget()

    def resize(self, _event=None):
        if not self.visible:
            return
        scaling = self.frame._get_widget_scaling()
        width, height = self.parent.winfo_width() / scaling, self.parent.winfo_height() / scaling
        card_width = min(376, max(240, width - 100))
        card_height = min(710, max(150, height - 108))
        self.frame.configure(width=card_width, height=card_height)
        x, y = self.position or (width - card_width - 72, 20)
        x, y = max(8, min(x, width - card_width - 8)), max(8, min(y, height - card_height - 42))
        self.frame.place(x=x, y=y)
        if self.position is not None:
            self.position = (x, y)

    def start_drag(self, event):
        scaling = self.frame._get_widget_scaling()
        self.drag = (event.x_root, event.y_root, self.frame.winfo_x() / scaling, self.frame.winfo_y() / scaling)

    def move_drag(self, event):
        if self.drag:
            x, y, initial_x, initial_y = self.drag
            scaling = self.frame._get_widget_scaling()
            self.position = (initial_x + (event.x_root - x) / scaling, initial_y + (event.y_root - y) / scaling)
            self.resize()
        return 'break'

    def draw_voyage_arrow(self, _event=None):
        canvas = self.voyage_arrow
        width = canvas.winfo_width()
        canvas.delete('all')
        canvas.create_line(15, 17, width-15, 17, fill='#ced5db', width=2)
        for x in (15, width-15):
            canvas.create_oval(x-4, 13, x+4, 21, fill='#96a5af', outline='')
        middle = width / 2
        canvas.create_polygon(middle-10, 7, middle+13, 17, middle-10, 27, middle-5, 17, fill='#07acdf', outline='')
        canvas.create_text(middle, 37, text='Voyage summary · no route prediction', fill=MUTED, font=('Segoe UI', 9))

    def refresh(self):
        from desktop_ais import vessel_type
        vessel = self.tracker.state.vessels.get(self.tracker.selected)
        if not vessel:
            self.hide()
            return
        mmsi = vessel['mmsi']
        name = vessel['name']
        self.name.configure(text=name if len(name) <= 36 else name[:35] + '…')
        self.kind.configure(text=vessel_type(vessel.get('type')))
        self.flag.delete('all')
        # ITU MID 250 is Ireland. Other/auxiliary identities retain their MMSI.
        if mmsi.startswith('250'):
            for index, color in enumerate(('#009a60', WHITE, '#ff8200')):
                self.flag.create_rectangle(index*9, 0, index*9+9, 24, fill=color, outline='')
        else:
            self.flag.create_text(13, 12, text='AIS', fill=MUTED, font=('Segoe UI', 8, 'bold'))
        if self.photo_mmsi != mmsi:
            photo = local_photo(Path(__file__).resolve().parent / 'data/desktop/vessel_photos', mmsi)
            self.photo_mmsi = mmsi
            self.photo_image = ctk.CTkImage(light_image=photo, dark_image=photo, size=(330, 156)) if photo else self.icons.get('ship', '#8c9eab', 70)
            self.hero.configure(image=self.photo_image, text='' if photo else 'Vessel photograph unavailable',
                compound='top', text_color=MUTED, font=ctk.CTkFont('Segoe UI', 12))
            self.photo_note.configure(text='Local vessel photograph' if photo else f'MMSI {mmsi} · received AIS contact')
        points = self.tracker.history.tracks.get(mmsi, [])
        first = points[0] if points else None
        self.origin.configure(text=f"{first['lat']:.3f}, {first['lon']:.3f}" if first else 'Not recorded')
        self.start_time.configure(text=f"Recorded UTC:\n{first['received_utc'][:16].replace('T', ' ')}" if first else 'Departure: unknown')
        self.destination.configure(text=vessel.get('destination') or 'Not reported')
        self.labels['navigation'].configure(text=navigation_status(vessel.get('nav_status')))
        speed, course = vessel.get('sog_kn'), vessel.get('cog_deg')
        self.labels['speed'].configure(text=f"{'—' if speed is None else f'{speed:.1f} kn'} /\n{'—' if course is None else f'{course:.0f}°'}")
        self.labels['draught'].configure(text='Not reported')
        now = datetime.now(timezone.utc).timestamp()
        stale = vessel['received_s'] is None or now - vessel['received_s'] > self.tracker.state.feed.get('stale_seconds', 900)
        prediction = self.tracker.selected_prediction(now)
        predicted = (f"\nPosition now predicted, not observed: ±{prediction['reachable']['radius_nm']:.1f} nm"
                     if prediction else '')
        self.received.configure(text=f"Received: {age_description(vessel['received_s'], now)} · {'Stale' if stale else 'Fresh'}\nUTC: {vessel['received_utc'] or 'Unavailable'}{predicted}")
        self.source.configure(text=f"AIS source: shared feed · {vessel['label']}\nDestination is declared text; departure port is unknown.")
        self.path_note.configure(text=f"{len(points)} recorded fixes · reception gaps stay open" if points else 'Past track appears as new positions are received.')
        self.fleet_button.configure(text='Remove from fleet' if mmsi in self.tracker.fleet else 'Add to fleet')
        active = self.tracker.show_path.get()
        self.past_button.configure(fg_color='#34424f' if active else WHITE, text_color=WHITE if active else INK)

    def toggle_path(self):
        self.tracker.show_path.set(not self.tracker.show_path.get())
        self.refresh()
        self.app._draw_map()

    def toggle_fleet(self):
        mmsi = self.tracker.selected
        if mmsi in self.tracker.fleet:
            self.tracker.fleet.remove(mmsi)
        else:
            self.tracker.fleet.add(mmsi)
        if hasattr(self.tracker, 'connected_address'):
            self.tracker.save_cache()
        self.refresh()

    def open_details(self):
        self.hide()
        self.app.open_window('ais')
        self.tracker.tabs.select(self.tracker.detail_tab)

    def measure_route(self):
        self.hide()
        self.tracker.follow.set(False)
        self.app._set_map_tool('measure')

    def close(self):
        self.app.map.unbind('<Configure>', self.resize_binding)
        self.frame.destroy()
