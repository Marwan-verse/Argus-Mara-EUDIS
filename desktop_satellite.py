"""Native satellite review dock and acquisition-time map overlays."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import queue
import time
import tkinter as tk
from urllib.parse import urlencode
from tkinter import filedialog, ttk
import webbrowser
import customtkinter as ctk

from PIL import Image, ImageTk

from argus import gfw_sar
from argus.satellite import atomic_json, bounds
from argus.satellite_ai import choose_model, get_key, read_ledger, save_key
from argus.satellite_workspace import DEFAULT_QUESTION, SatelliteWorkspace
from argus.satellite_scan import CoastalScan, read_state, grid
from argus.space import timestamp

BG, INK, MUTED, TEAL = '#141e28', '#e4ebf0', '#a8b6c2', '#47c7da'
RADAR, RADAR_MUTED = '#c88cff', '#9d8bb5'  # Global Fishing Watch radar contacts (D84)
RADAR_LABELS = {'no_team_ais': 'no team AIS', 'team_ais_match': 'AIS match', 'nearby_ais_review': 'AIS nearby · review',
                'no_contemporaneous_ais': 'no team AIS history', 'time_unresolved': 'time unresolved',
                'ais_unavailable': 'AIS lookup failed'}


class DesktopSatellite:
    def __init__(self, app, root):
        self.app = app
        self.workspace = SatelliteWorkspace(root)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='argus-satellite-ui')
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.frame = None
        self.current = None
        self.image = None
        self.map_photo = None
        self.map_image_key = None
        self.catalogue = []
        self.scenes = []
        self.map_contacts = []
        self.selected_contact = None
        self.selected_candidate = None
        self._engine = None
        self.watch_future = None
        self.watch_at = 0
        self.contact_signature = None
        self.contact_page = 0
        self.watch_review_at = 0
        self.pending_contact = None
        self.pending_fleet = None
        self.fleet_after = ''
        self.fleet_stack = []
        self.fleet_next = None
        self.fleet_rows = {}
        self.fleet_signature = None
        self.fleet_filter = False
        self.fleet_only_leads = tk.BooleanVar(app.root, value=False)
        self.resume_timer = app.root.after(1500, self.resume_local)
        self.show_image = tk.BooleanVar(value=True)
        self.show_ais = tk.BooleanVar(value=True)
        self.show_ai = tk.BooleanVar(value=True)
        self.show_radar = tk.BooleanVar(value=True)
        self.radar_points = []
        self.radar_summary = {}
        self.radar_signature = None
        self.selected_radar = None
        self.poll_timer = app.root.after(150, self.poll)

    @property
    def remote(self):
        return self.app.soc_client is not None

    def request(self, path, method='GET', data=None):
        if not self.app.soc_online:
            raise ValueError('Restore the SOC connection to use shared satellite tools')
        return self.app.soc_client.request(method, '/v1/satellite/'+path, data)

    def task(self, function, callback):
        if self.closed or self.busy:
            return
        self.busy = True
        self.message('Working… catalogue and archive operations do not use AI credits')
        def run():
            try:
                result = function()
                self.results.put((callback, result, None))
            except (ValueError, OSError) as error:
                self.results.put((callback, None, str(error)[:300]))
            except Exception:
                self.results.put((callback, None, 'Satellite task failed; check data access and host configuration'))
        self.executor.submit(run)

    def poll(self):
        if self.closed:
            return
        try:
            callback, result, error = self.results.get_nowait()
            self.busy = False
            if error:
                self.message(error)
            else:
                callback(result)
        except queue.Empty:
            pass
        if self.pending_fleet is not None and not self.busy:
            target = self.pending_fleet
            self.pending_fleet = None
            self.load_fleet('' if int(target) == 0 else str(int(target)-1).zfill(9), selected=target)
        if self.pending_contact is not None and not self.busy:
            identifier, point_id = self.pending_contact
            self.pending_contact = None
            self.open_review(identifier, point_id)
        if self.watch_future is not None and self.watch_future.done():
            try:
                self.apply_watch(self.watch_future.result())
            except (ValueError, OSError):
                pass
            except Exception:
                self.message('Coastal status unavailable; previous observations retain their timestamps')
            self.watch_future = None
        if time.monotonic() >= self.watch_at and not self.busy and self.watch_future is None and self.app.allowed('evidence.share'):
            self.watch_at = time.monotonic()+15
            self.watch_future = self.executor.submit(self.read_watch)
        self.poll_timer = self.app.root.after(150, self.poll)

    def engine(self):
        if self._engine is None or self._engine.workspace.root != self.workspace.root:
            self._engine = CoastalScan(self.workspace)
        return self._engine

    def resume_local(self):
        if not self.closed and not self.remote and self.app.allowed('evidence.share') and os.environ.get('ARGUS_SATELLITE_AUTOSTART', '1') != '0':
            self.workspace.fleet.start()
            if read_state(self.workspace.root).get('enabled'):
                try:
                    self.engine().resume()
                except (ValueError, ImportError, OSError) as error:
                    self.message(str(error))

    def read_watch(self):
        identifier = self.current['scene']['id'] if self.current and self.selected_contact and time.monotonic() >= self.watch_review_at else None
        review = None
        if identifier:
            review = self.request('scenes/'+identifier+'/review') if self.remote else self.workspace.review(identifier)
            self.watch_review_at = time.monotonic()+60
        if self.remote:
            status = self.request('status')
            status['comparisons'] = self.request('comparisons')
            status['fleet'] = self.read_fleet(self.fleet_after, self.fleet_filter)
            status['fleet_leads'] = self.read_fleet('', True)
            return status, self.request('contacts')['contacts'], review
        if os.environ.get('ARGUS_SATELLITE_AUTOSTART', '1') != '0':
            self.workspace.fleet.start()
            self.workspace.reconcile_reviews(limit=1)
        status = self.workspace.status()
        status['comparisons'] = self.workspace.comparison_index()
        status['fleet'] = self.read_fleet(self.fleet_after, self.fleet_filter)
        status['fleet_leads'] = self.read_fleet('', True)
        try:
            status['radar'] = {**gfw_sar.map_index(self.workspace.root), 'configured': gfw_sar.configured()}
        except (OSError, ValueError):
            status['radar'] = {'points': [], 'summary': {}, 'configured': False}
        return status, self.workspace.contacts(), review

    def apply_watch(self, value):
        status, self.map_contacts, review = value
        if 'radar' in status:
            self.apply_radar(status['radar'])
        if 'comparisons' in status and hasattr(self.app, 'alert_board'):
            self.app.alert_board.refresh_evidence(status['comparisons'])
        if 'fleet_leads' in status and hasattr(self.app, 'alert_board'):
            self.app.alert_board.refresh_history(status['fleet_leads'])
        if 'fleet' in status and self.frame is not None and self.frame.winfo_exists():
            self.apply_fleet(status['fleet'])
        scan = status.get('scan', {})
        if self.frame is not None and self.frame.winfo_exists():
            mode = 'AI PAUSED · AIS RECORDING' if scan.get('running') and scan.get('analysis_paused') else 'SCANNING' if scan.get('running') else 'WAITING TO RESUME' if scan.get('enabled') else 'STOPPED'
            counts = scan.get('statuses', {})
            ais = scan.get('ais') or {}
            coasts = scan.get('coasts') or {}
            coast_lines = '\n'.join(
                f"{side}: {row.get('covered_tiles', 0):,}/{row.get('total_tiles', 0):,} processed · {row.get('queued', 0):,} queued · {row.get('obscured', 0):,} obscured"
                for side in ('North', 'East', 'South', 'West') if (row := coasts.get(side)) is not None)
            self.coast_status.set(f"{mode} · {scan.get('covered_tiles', 0):,}/{scan.get('total_tiles', 0):,} areas processed · {scan.get('queued', 0):,} queued\n"
                 f"{counts.get('unobservable_water', 0):,} obscured/land · {scan.get('tiles_without_image') or 0:,} without images · {counts.get('failed_review_required', 0):,} failed · {counts.get('partial_review_required', 0):,} partial\n"
                 f"{len(self.map_contacts):,} visual leads · {ais.get('latest_vessels', 0):,} latest AIS\n"
                 + (coast_lines+'\n' if coast_lines else '')
                 + f"Rotation: North → East → South → West\n"
                 f"{scan.get('message', '')}\n{scan.get('ais_error') or 'New images checked every 30 min · AIS captured every minute'}")
            budget = status.get('budget', {})
            self.coast_budget.set(f"Pilot reserved ${budget.get('reserved_usd', 0):.2f}/$20 · reported ${budget.get('reported_usd', 0):.4f} · {budget.get('calls', 0)} calls")
            signature = tuple((r['scene_id'], r['id'], r.get('matched_mmsi')) for r in self.map_contacts)
            if signature != self.contact_signature:
                self.contact_signature = signature
                self.render_contacts()
            if review and self.current and review['scene']['id'] == self.current['scene']['id'] and self.selected_contact:
                point = next((p for p in review['contacts'] if p['id'] == self.selected_contact['id']), None)
                if point:
                    preferred = (self.selected_candidate or {}).get('mmsi')
                    self.current = review
                    self.show_contact(point)
                    for i, candidate in enumerate(point.get('candidates', [])):
                        if candidate['mmsi'] == preferred:
                            self.candidate_table.selection_set(str(i))
                            self.select_candidate()
                            break
        self.redraw()

    def scan_control(self, action):
        def work():
            if self.remote:
                return self.request('scan', 'POST', {'action': action})
            engine = self.engine()
            return engine.start() if action == 'start' else engine.stop()
        def done(_value):
            self.watch_at = 0
            self.message('Coastal scan started · $20 shared pilot ceiling' if action == 'start' else 'Stopping after the current request')
        self.task(work, done)

    def start_watch(self):
        """SATELLITE-WATCH launchers: start Coast Watch once TensorX is connected.

        A scan left enabled is resumed by resume_local, so it is not started twice.
        """
        if self.closed or self.remote:
            return
        try:
            connected = bool(get_key())
        except ValueError:
            connected = False
        if not connected:
            self.message('Connect TensorX to start Coast Watch. "AIS at image time · free" works without it.')
        elif self.busy:
            self.app.root.after(1000, self.start_watch)
        elif not read_state(self.workspace.root).get('enabled'):
            self.scan_control('start')

    def coast_view(self):
        boxes = [t['bbox'] for t in grid()['tiles']]
        self.fit_visible([(min(b[1] for b in boxes), min(b[0] for b in boxes)),
                          (max(b[3] for b in boxes), max(b[2] for b in boxes))])

    def render_contacts(self, delta=0):
        """Every saved contact is reachable; only the visible page creates rows."""
        self.contact_page = max(0, min((max(0, len(self.map_contacts)-1))//200, self.contact_page+delta))
        start = self.contact_page*200
        self.contacts_table.delete(*self.contacts_table.get_children())
        for index, row in enumerate(self.map_contacts[start:start+200], start=start):
            self.contacts_table.insert('', 'end', iid=str(index), values=(row['ts'][5:16].replace('T', ' '), row.get('matched_mmsi') or 'Unmatched lead'))
        self.contact_page_label.configure(text=f"{start+1 if self.map_contacts else 0}–{min(start+200, len(self.map_contacts))} of {len(self.map_contacts)} contacts")
        self.contact_previous.configure(state='normal' if start else 'disabled')
        self.contact_next.configure(state='normal' if start+200 < len(self.map_contacts) else 'disabled')
        self.redraw()

    def fit_visible(self, points):
        """Keep the evidence beside its dock instead of underneath it."""
        self.app._fit_points(points)
        panel = getattr(self.app, 'floating_panel', None)
        if panel is not None and panel.winfo_ismapped():
            width = self.app._map_size[0]
            available = max(100, width-panel.winfo_width()-100)
            xs = [self.app._project(lat, lon)[0] for lat, lon in points]
            while max(xs)-min(xs) > available and self.app.map_zoom > 1:
                self.app.map_zoom -= 1
                xs = [self.app._project(lat, lon)[0] for lat, lon in points]
            lat, lon = self.app.map_center
            lon += (panel.winfo_width()+70)/2 * 360/(256*2**self.app.map_zoom)
            self.app.map_center = (lat, (lon+180) % 360-180)
        tracker = getattr(self.app, 'ais_tracker', None)
        if tracker is not None:
            tracker.follow.set(False)

    def message(self, text):
        if self.frame is not None and self.frame.winfo_exists():
            self.status.set(text)

    def build(self, frame):
        content = ctk.CTkScrollableFrame(frame, fg_color=BG, corner_radius=0)
        content.pack(fill='both', expand=True)
        frame = content
        self.frame = frame
        self.status = tk.StringVar(value='Coastal scan available · $20 conservative pilot limit')
        ttk.Label(frame, text='SATELLITE ANALYSIS', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Shared SOC host' if self.remote else 'Local private workspace',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=360, justify='left',
                  style='Muted.TLabel').pack(anchor='w', fill='x', pady=(0, 8))
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill='both', expand=True)
        watch_tab, search_tab, self.contact_tab = ttk.Frame(self.tabs), ttk.Frame(self.tabs), ttk.Frame(self.tabs)
        self.tabs.add(watch_tab, text='Coast Watch')
        self.tabs.add(self.contact_tab, text='Selected contact')
        self.fleet_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.fleet_tab, text='Fleet history')
        self.tabs.add(search_tab, text='Search & import')
        self.build_fleet()
        coast = ctk.CTkFrame(watch_tab, fg_color='#1b2b39', border_color='#294957', border_width=1)
        coast.pack(fill='x', pady=(0, 10))
        ctk.CTkLabel(coast, text='IRELAND · COAST WATCH', text_color=TEAL, anchor='w',
                     font=('Segoe UI', 13, 'bold')).pack(fill='x', padx=10, pady=(8, 2))
        self.coast_status = tk.StringVar(value='Rolling coverage of the island’s ~40 km coastal belt.\nOptical leads need review; cloud and AIS gaps remain visible.')
        ctk.CTkLabel(coast, textvariable=self.coast_status, text_color=INK, anchor='w', justify='left',
                     wraplength=340, font=('Segoe UI', 11)).pack(fill='x', padx=10, pady=4)
        self.coast_budget = tk.StringVar(value='$20 conservative shared pilot ceiling')
        ctk.CTkLabel(coast, textvariable=self.coast_budget, text_color=TEAL, anchor='w', justify='left',
                     wraplength=340, font=('Segoe UI', 11)).pack(fill='x', padx=10, pady=4)
        controls = ttk.Frame(coast)
        controls.pack(fill='x', padx=8, pady=(2, 8))
        ttk.Button(controls, text='Start scan', command=lambda: self.scan_control('start')).pack(side='left')
        ttk.Button(controls, text='Stop', command=lambda: self.scan_control('stop')).pack(side='left', padx=4)
        ttk.Button(controls, text='All Ireland', command=self.coast_view).pack(side='left')
        radar = ctk.CTkFrame(watch_tab, fg_color='#1b2b39', border_color='#294957', border_width=1)
        radar.pack(fill='x', pady=(0, 10))
        ctk.CTkLabel(radar, text='RADAR · SENTINEL-1 (GFW)', text_color=RADAR, anchor='w',
                     font=('Segoe UI', 13, 'bold')).pack(fill='x', padx=10, pady=(8, 2))
        self.radar_status = tk.StringVar(value=self.radar_text())
        ctk.CTkLabel(radar, textvariable=self.radar_status, text_color=INK, anchor='w', justify='left',
                     wraplength=340, font=('Segoe UI', 11)).pack(fill='x', padx=10, pady=4)
        if not self.remote:
            radar_controls = ttk.Frame(radar)
            radar_controls.pack(fill='x', padx=8, pady=(2, 4))
            ttk.Button(radar_controls, text='Connect GFW', command=self.connect_gfw).pack(side='left')
            ttk.Button(radar_controls, text='Fetch radar · 14 days', command=self.fetch_radar).pack(side='left', padx=4)
        ttk.Checkbutton(radar, text='Radar on map · filled = no AIS', variable=self.show_radar,
                        command=self.redraw).pack(anchor='w', padx=8)
        credit = ttk.Label(radar, text=gfw_sar.ATTRIBUTION, style='Muted.TLabel', cursor='hand2')
        credit.pack(anchor='w', padx=10, pady=(0, 8))
        credit.bind('<Button-1>', lambda _event: webbrowser.open(gfw_sar.ATTRIBUTION_URL))
        self.contacts_table = ttk.Treeview(watch_tab, columns=('time', 'match'), show='headings', height=8, selectmode='browse')
        self.contacts_table.heading('time', text='Image UTC · click a lead')
        self.contacts_table.heading('match', text='Possible AIS identity')
        self.contacts_table.column('time', width=135)
        self.contacts_table.column('match', width=180)
        self.contacts_table.pack(fill='x', pady=(0, 5))
        self.contacts_table.bind('<<TreeviewSelect>>', self.select_contact_row)
        paging = ttk.Frame(watch_tab)
        paging.pack(fill='x')
        self.contact_previous = ttk.Button(paging, text='Previous', command=lambda: self.render_contacts(-1))
        self.contact_previous.pack(side='left')
        self.contact_next = ttk.Button(paging, text='Next', command=lambda: self.render_contacts(1))
        self.contact_next.pack(side='right')
        self.contact_page_label = ttk.Label(paging, text='0 contacts')
        self.contact_page_label.pack(side='left', padx=4)
        self.render_contacts()
        ttk.Label(watch_tab, text='~40 km coastal belt · optical screening · not every vessel is visible.\nAmber leads require review. Click a map lead for image-time AIS and its latest received position.',
                  style='Muted.TLabel', wraplength=340, justify='left').pack(fill='x', pady=8)
        self.contact_card = ctk.CTkFrame(self.contact_tab, fg_color='#1b2b39', corner_radius=8)
        self.contact_card.pack(fill='x', pady=(0, 10))
        self.contact_title = ctk.CTkLabel(self.contact_card, text='Select an amber contact on the map', text_color=INK,
                                         wraplength=340, justify='left', anchor='w')
        self.contact_title.pack(fill='x', padx=8, pady=4)
        self.candidate_info = tk.StringVar(value='No contact selected')
        ctk.CTkLabel(self.contact_card, textvariable=self.candidate_info, text_color=TEAL, anchor='w', justify='left',
                     wraplength=330, font=('Segoe UI', 11)).pack(fill='x', padx=8, pady=4)
        self.thumbnail = ctk.CTkLabel(self.contact_card, text='Satellite image · acquisition-time evidence', text_color=MUTED)
        self.thumbnail.pack(fill='x', padx=8)
        self.candidate_table = ttk.Treeview(self.contact_card, columns=('ship', 'error', 'time'), show='headings', height=3, selectmode='browse')
        for key, label, width in [('ship', 'Possible ship', 160), ('error', 'Error m', 65), ('time', 'Fix Δ s', 65)]:
            self.candidate_table.heading(key, text=label)
            self.candidate_table.column(key, width=width)
        self.candidate_table.pack(fill='x', padx=8, pady=4)
        self.candidate_table.bind('<<TreeviewSelect>>', self.select_candidate)
        self.latest_button = ttk.Button(self.contact_card, text='Show latest received AIS position', command=self.show_latest, state='disabled')
        self.latest_button.pack(anchor='w', padx=8, pady=(0, 8))
        frame = search_tab
        bar = ttk.Frame(frame)
        bar.pack(fill='x', pady=(0, 8))
        if not self.remote:
            ttk.Button(bar, text='Connect TensorX', command=self.connect).pack(side='left')
        ttk.Button(bar, text='Refresh', command=self.refresh).pack(side='left', padx=4)
        ttk.Button(bar, text='Map centre', command=self.use_map).pack(side='left')
        self.sensor = tk.StringVar(value='Sentinel-2')
        ttk.Combobox(frame, textvariable=self.sensor, values=['Sentinel-2', 'Sentinel-1'],
                     state='readonly', width=18).pack(anchor='w', pady=(0, 4))
        self.area = tk.StringVar(value='-6.17, 53.30, -6.07, 53.36')
        ttk.Label(frame, text='Crop: west, south, east, north (about 11 km maximum)',
                  style='Muted.TLabel', wraplength=360).pack(anchor='w')
        ttk.Entry(frame, textvariable=self.area).pack(fill='x', pady=(2, 4))
        dates = ttk.Frame(frame)
        dates.pack(fill='x')
        now = datetime.now(timezone.utc)
        self.start = tk.StringVar(value=(now-timedelta(days=7)).date().isoformat())
        self.end = tk.StringVar(value=now.date().isoformat())
        ttk.Entry(dates, textvariable=self.start, width=13).pack(side='left')
        ttk.Label(dates, text=' to ').pack(side='left')
        ttk.Entry(dates, textvariable=self.end, width=13).pack(side='left')
        ttk.Button(dates, text='Search', command=self.search).pack(side='left', padx=4)
        self.catalogue_table = ttk.Treeview(frame, columns=('date', 'cloud'), show='headings', height=3, selectmode='browse')
        self.catalogue_table.heading('date', text='Acquisition UTC')
        self.catalogue_table.heading('cloud', text='Cloud %')
        self.catalogue_table.column('date', width=200)
        self.catalogue_table.column('cloud', width=65)
        self.catalogue_table.pack(fill='x', pady=(6, 4))
        ttk.Button(frame, text='Load selected image crop', command=self.prepare).pack(anchor='w')
        ttk.Label(frame, text='SAVED CROPS · SELECT TO OPEN', style='Muted.TLabel').pack(anchor='w', pady=(10, 3))
        self.scene_table = ttk.Treeview(frame, columns=('sensor', 'date'), show='headings', height=3, selectmode='browse')
        for key, title, width in [('sensor', 'Sensor', 90), ('date', 'Acquisition UTC', 210)]:
            self.scene_table.heading(key, text=title)
            self.scene_table.column(key, width=width)
        self.scene_table.pack(fill='x')
        self.scene_table.bind('<<TreeviewSelect>>', self.select_scene)
        if not self.remote:
            imports = ttk.Frame(frame)
            imports.pack(fill='x', pady=(6, 4))
            ttk.Button(imports, text='Import GeoTIFF', command=self.import_raster).pack(side='left')
            ttk.Button(imports, text='Import AIS archive', command=self.import_ais).pack(side='left', padx=4)
        self.question = tk.StringVar(value=DEFAULT_QUESTION)
        ttk.Entry(frame, textvariable=self.question).pack(fill='x', pady=(6, 4))
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions, text='Analyse image', command=self.analyse).pack(side='left')
        ttk.Button(actions, text='AIS at image time · free', command=self.history).pack(side='left', padx=4)
        layers = ttk.Frame(watch_tab)
        layers.pack(fill='x', pady=6)
        for label, variable in [('Image', self.show_image), ('Historical AIS', self.show_ais), ('AI leads', self.show_ai)]:
            ttk.Checkbutton(layers, text=label, variable=variable, command=self.redraw).pack(side='left')
        self.details = tk.Text(self.contact_tab, height=10, wrap='word', bg=BG, fg=INK,
                               insertbackground=INK, relief='flat', font=('Segoe UI', 10), padx=8, pady=8)
        self.details.pack(fill='x')
        self.set_details('Start Coast Watch for new image cycles, or search a small area manually.\n\nAmber contacts are unreviewed visual leads. Select one to see its source image, image-time AIS candidates and latest received positions. Automatic optical screening cannot see every ship. No operational action is sent.')
        self.refresh()

    def redraw(self):
        self.app._draw_map(force_static=True)

    def set_details(self, text):
        if self.frame is not None and self.frame.winfo_exists():
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('1.0', text)
            self.details.configure(state='disabled')

    def use_map(self):
        lat, lon = self.app.map_center
        self.area.set(f'{lon-.05:.5f}, {lat-.03:.5f}, {lon+.05:.5f}, {lat+.03:.5f}')

    def bbox(self):
        return bounds([float(part.strip()) for part in self.area.get().split(',')], small=True)

    def refresh(self):
        def work():
            return (self.request('status'), self.request('scenes')['scenes']) if self.remote else (self.workspace.status(), self.workspace.list_scenes())
        def done(value):
            status, self.scenes = value
            self.scene_table.delete(*self.scene_table.get_children())
            for row in self.scenes:
                self.scene_table.insert('', 'end', iid=row['id'], values=(row['sensor'], row['acquired_utc'][:19]))
            budget = status.get('budget', {})
            self.message(f"{'TensorX connected' if status.get('configured') else 'TensorX key not connected'} · {'automatic enabled' if status.get('automatic') else 'automatic stopped'}\n"
                         f"Pilot reserved ${budget.get('reserved_usd', 0):.2f}/$20 · reported ${budget.get('reported_usd', 0):.4f} · {budget.get('calls', 0)} calls")
        self.task(work, done)

    def job(self, action, data, callback):
        def work():
            if self.remote:
                identifier = self.request('jobs', 'POST', {'action': action, **data})['job_id']
                deadline = time.monotonic()+240
                while time.monotonic() < deadline:
                    result = self.request('jobs/'+identifier)
                    if result['status'] == 'failed':
                        raise ValueError(result['error'])
                    if result['status'] == 'complete':
                        return result['result']
                    time.sleep(.8)
                raise ValueError('Host job is still running; refresh saved crops or the review later. No automatic resubmission.')
            if action == 'search':
                return self.workspace.search(data['sensor'], data['bbox'], data['start'], data['end'])
            if action == 'prepare':
                return self.workspace.prepare(data['product_id'], data['bbox'])
            if action == 'analyse':
                return self.workspace.analyse(data['identifier'], data['question'])
            return self.workspace.history(data['identifier'])
        self.task(work, callback)

    def search(self):
        try:
            data = {'sensor': self.sensor.get(), 'bbox': self.bbox(),
                    'start': self.start.get()+'T00:00:00Z', 'end': self.end.get()+'T23:59:59Z'}
        except ValueError as error:
            self.message(str(error))
            return
        def done(rows):
            self.catalogue = rows
            self.catalogue_table.delete(*self.catalogue_table.get_children())
            for index, row in enumerate(rows):
                cloud = row.get('cloud_percent')
                self.catalogue_table.insert('', 'end', iid=str(index), values=(row['acquired_utc'][:19], '-' if cloud is None else f'{cloud:.0f}'))
            self.message(f'{len(rows)} catalogue scenes · select a scene to load a crop. SAR requires a calibrated GeoTIFF import.')
        self.job('search', data, done)

    def prepare(self):
        selected = self.catalogue_table.selection()
        if not selected:
            self.message('Select a catalogue scene first')
            return
        try:
            data = {'product_id': self.catalogue[int(selected[0])]['id'], 'bbox': self.bbox()}
        except (ValueError, IndexError) as error:
            self.message(str(error))
            return
        self.job('prepare', data, self.prepared)

    def prepared(self, scene):
        self.message('Crop ready · no AI credits used')
        self.scene_table.insert('', 0, iid=scene['id'], values=(scene['sensor'], scene['acquired_utc'][:19])) if not self.scene_table.exists(scene['id']) else None
        self.scene_table.selection_set(scene['id'])

    def select_scene(self, _event=None):
        selected = self.scene_table.selection()
        if not selected or self.busy:
            return
        identifier = selected[0]
        self.open_review(identifier)

    def open_review(self, identifier, point_id=None):
        def work():
            if self.remote:
                payload = self.request('scenes/'+identifier+'/image')
                image = base64.b64decode(payload['image_base64'], validate=True)
                review = self.request('scenes/'+identifier+'/review')
            else:
                image, review = self.workspace.image(identifier), self.workspace.review(identifier)
            if hashlib.sha256(image).hexdigest() != review['scene']['image_sha256']:
                raise ValueError('Satellite image integrity check failed')
            return image, review
        def done(value):
            image, review = value
            self.image = Image.open(BytesIO(image)).convert('RGB')
            self.map_image_key = None
            self.current = review
            self.selected_contact = None
            self.selected_candidate = None
            w, s, e, n = review['scene']['bbox']
            self.fit_visible([(s, w), (n, e)])
            self.show_result(review)
            if point_id is not None:
                point = next((p for p in review['contacts'] if p['id'] == point_id), None)
                if point:
                    self.show_contact(point)
        self.task(work, done)

    def select_contact_row(self, _event=None):
        selected = self.contacts_table.selection()
        if selected and int(selected[0]) < len(self.map_contacts):
            row = self.map_contacts[int(selected[0])]
            self.open_map_contact(row)

    def open_map_contact(self, point):
        self.app.open_window('satellite')
        self.pending_contact = (point['scene_id'], point['id'])
        return 'break'

    def show_contact(self, point):
        self.app.open_window('satellite')
        self.tabs.select(self.contact_tab)
        self.selected_contact, self.selected_candidate = point, None
        self.latest_button.configure(state='disabled')
        scene = self.current['scene']
        quality = point.get('localization') or {}
        origin = 'OPTICAL FEATURE · UNCLASSIFIED' if quality.get('status') == 'feature_only' else 'AI ASSUMPTION'
        location_note = (f"\nPixel support: {quality['status'].replace('_', ' ')} · "
                         f"{'verified water mask' if quality.get('water_mask_verified') else 'water quality unavailable'}"
                         if quality else '')
        self.contact_title.configure(text=f"{point['id']} · {point['confidence'].upper()} confidence · {origin}\n"
             f"{scene['sensor']} · {scene['acquired_utc']}\n{point['description']}"+location_note)
        if self.image is not None:
            x, y = point['x']*self.image.width, point['y']*self.image.height
            left, top = max(0, min(self.image.width-120, x-60)), max(0, min(self.image.height-72, y-36))
            crop = self.image.crop((left, top, min(self.image.width, left+120), min(self.image.height, top+72)))
            self.contact_photo = ctk.CTkImage(light_image=crop, dark_image=crop, size=(330, 198))
            self.thumbnail.configure(image=self.contact_photo, text='')
        self.candidate_table.delete(*self.candidate_table.get_children())
        self.candidate_info.set('Select a possible AIS identity below.' if point.get('candidates') else
                                'No contemporaneous AIS in the archive. Keep recording or import acquisition-day history; current positions cannot identify this past image.')
        for index, candidate in enumerate(point.get('candidates', [])):
            offset = candidate.get('nearest_fix_offset_s')
            self.candidate_table.insert('', 'end', iid=str(index), values=(candidate['name'], f"{candidate['distance_m']:.0f}", '-' if offset is None else f'{offset:.0f}'))
        self.set_details(f"IMAGE-TIME CONTACT · {scene['acquired_utc']}\n{point['lat']:.6f}, {point['lon']:.6f}\n"
             f"{point['association'].replace('_', ' ')}\n"
             f"{'Multiple ships satisfy the 300 m gate. Identity is ambiguous.' if point.get('ambiguous') else 'Candidates are ranked by image-time spatial error, not identity probability.'}\n\n"
             + ('Select a candidate for its historical broadcasts and latest received position.' if point.get('candidates') else
                'No suitable historical AIS fixes are available here. Current ships are not backdated into this image. Import acquisition-day AIS, or keep recording for future scenes.')
             + '\n\nImage detail is enlarged from native pixels. It is not a vessel photograph. Operator review required.')
        if point.get('candidates'):
            preferred = next((i for i, c in enumerate(point['candidates']) if c['mmsi'] == point.get('matched_mmsi')), 0)
            self.candidate_table.selection_set(str(preferred))
            self.select_candidate()
        self.redraw()
        return 'break'

    def select_candidate(self, _event=None):
        selected = self.candidate_table.selection()
        if not selected or self.selected_contact is None:
            return
        index = int(selected[0])
        candidates = self.selected_contact.get('candidates', [])
        if index >= len(candidates):
            return
        candidate = candidates[index]
        self.selected_candidate = candidate
        evidence, latest = candidate['position_evidence'], candidate.get('latest')
        self.latest_button.configure(state='normal' if latest else 'disabled')
        self.candidate_info.set(f"{candidate['name']} · {candidate['mmsi']}\n"
              f"Separation from estimated AIS {candidate['distance_m']:.0f} m · fix offset {candidate.get('nearest_fix_offset_s')} s\n"
              f"{'Motion inconsistent · review required' if not candidate.get('motion_consistent', True) else 'Outside 300 m gate · alternative only' if not candidate['within_gate'] else 'AMBIGUOUS · several candidates' if self.selected_contact.get('ambiguous') else 'Provisional · identity unconfirmed'}\n"
              + (f"Latest {'STALE' if latest['stale'] else 'received'}: {latest['received_utc']}\n"
                 f"{latest['lat']:.5f}, {latest['lon']:.5f}\nDestination: {latest.get('destination') or 'Unavailable'}"
                 if latest else 'No latest received position is available.'))
        lines = [f"POSSIBLE IDENTITY · {candidate['name']} · {candidate['mmsi']}",
             f"Image UTC {self.current['scene']['acquired_utc']}",
             f"Separation from estimated AIS: {candidate['distance_m']:.0f} m · 300 m gate {'passed' if candidate['within_gate'] else 'failed'}",
             f"Nearest AIS fix: {candidate.get('nearest_fix_offset_s')} seconds from acquisition",
             f"Position method: {evidence['position_method'].replace('_', ' ')}",
             f"Interpolation bracket: {evidence.get('bracket_s', 'N/A')} s · projected fix age: {evidence.get('age_s', 'N/A')} s",
             f"Motion check: {evidence.get('kinematic_consistency', 'unavailable').replace('_', ' ')} · implied {evidence.get('implied_segment_speed_kn')} kn · 80 kn assumption",
             f"{'RECEPTION-TIME ASSUMPTION: observation time is not verified.' if evidence.get('observation_time_assumed') else 'Provider-reported AIS timestamp.'}",
             f"{'AMBIGUOUS: several spatial or temporally reachable candidates.' if self.selected_contact.get('ambiguous') else 'Provisional association; identity is not confirmed.'}", '']
        support = evidence.get('temporal_support')
        if support:
            lines += [f"Temporal movement support: up to {support['center_radius_m']:.0f} m around the estimate",
                      support['caveat'],
                      'Inside endpoint reachability; no identity match inferred.' if candidate.get('within_temporal_support') and not candidate['within_gate']
                      else 'Endpoint reachability does not confirm identity.', '']
        if latest:
            lines += [f"LATEST RECEIVED AIS · {'STALE' if latest['stale'] else 'recent reception'}", latest['received_utc'],
                      f"{latest['lat']:.6f}, {latest['lon']:.6f} · {latest['age_s']} seconds old",
                      f"Speed/course: {latest.get('sog_kn')} kn / {latest.get('cog_deg')}°",
                      f"Declared destination now: {latest.get('destination') or 'Unavailable'}",
                      f"Displacement: {latest['displacement_km']} km · minimum average {latest['minimum_average_speed_kn']} kn" if latest['after_image'] else 'This fix predates the image; no later received position is available.',
                      f"Travel check: {latest['travel_consistency'].replace('_', ' ')}",
                      'The dashed link is displacement, not a recorded route.', '']
        else:
            lines += ['No latest AIS fix for this MMSI in the captured feed. Start/keep Coast Watch running to update reception.', '']
        lines += ['DECLARATIONS AT IMAGE TIME · values are not independently verified']
        for key, field in sorted(candidate['broadcast_fields'].items()):
            lines.append(f"{key.replace('_', ' ')}: {field['value']}\n  received {field['received_utc']}")
        self.set_details('\n'.join(lines))
        self.redraw()

    def show_latest(self):
        latest = (self.selected_candidate or {}).get('latest')
        if latest is None:
            self.message('Select a candidate with a latest received AIS position first')
            return
        self.fit_visible([(self.selected_contact['lat'], self.selected_contact['lon']), (latest['lat'], latest['lon'])])
        self.message(f"Latest received {latest['received_utc']} · {'stale' if latest['stale'] else 'recent'} · dashed displacement link is not a voyage track")
        self.redraw()

    def analyse(self):
        if self.current is None:
            self.message('Load a scene first')
            return
        self.job('analyse', {'identifier': self.current['scene']['id'], 'question': self.question.get()}, self.show_result)
        if self.busy:
            self.message('Analysing image · crowded areas use four detail windows · shared $20 ceiling · cached components reused')

    def history(self):
        if self.current is not None:
            self.job('history', {'identifier': self.current['scene']['id']}, self.show_result)

    def show_result(self, result):
        self.current = result
        self.selected_contact = self.selected_candidate = None
        self.latest_button.configure(state='disabled')
        self.candidate_table.delete(*self.candidate_table.get_children())
        self.candidate_info.set('Choose an amber map lead for possible AIS identities and the latest received position.')
        self.contact_title.configure(text=f"{result['scene']['sensor']} · {result['scene']['acquired_utc']}\nImage overview · select a contact")
        if self.image is not None:
            self.contact_photo = ctk.CTkImage(light_image=self.image, dark_image=self.image, size=(330, 198))
            self.thumbnail.configure(image=self.contact_photo, text='')
        self.tabs.select(self.contact_tab)
        scene, ais = result['scene'], result['ais']
        visual = result.get('visual')
        lines = [f"{scene['sensor']} · {scene['label'].upper()} pixels", f"Acquired {scene['acquired_utc']}",
                 f"Historical AIS: {ais['coverage']['status']} · {len(ais['vessels'])} eligible ships", '']
        if visual:
            lines += [f"AI ASSUMPTION · UNREVIEWED · {visual['model']}", visual['summary'],
                      f"{len(result['contacts'])} possible contacts · {'cached' if visual.get('cached') else 'new request'}", '']
            lines.extend(f"{p['id']} · {p['confidence']} confidence: {p['association'].replace('_', ' ')} · {p['description']}" for p in result['contacts'])
            cost_label = 'Reported cost of completed image requests' if visual.get('adaptive_version') else 'Reported cost of this answer'
            lines += ['', f"{cost_label}: ${visual['reported_cost_usd']:.6f}"]
            lines += [''] + visual['limitations']
            if visual.get('analysis_windows'):
                lines += ['', 'DETAIL WINDOW COVERAGE']
                lines.extend(f"Window {i+1}: {w['status']}" + (f" · {w['error']}" if w.get('error') else '')
                             for i, w in enumerate(visual['analysis_windows']))
        comparison = result.get('comparison')
        if comparison:
            lines += ['', 'ALL ELIGIBLE AIS VESSELS AT IMAGE TIME']
            lines.extend(f"{v['name']} · {v['mmsi']} · {v['status'].replace('_', ' ')}"
                         for v in comparison.get('vessel_checks', []))
            lines += [comparison.get('not_checked') or comparison['caveat']]
        lines += ['', 'Select a blue historical AIS marker for all retained broadcast fields and their timestamps.', result['caveat']]
        self.set_details('\n'.join(lines))
        if visual:
            budget = result.get('budget', {})
            verification = 'partial image review' if visual.get('analysis_incomplete') else 'cached' if visual.get('cached') else 'image input verified' if visual.get('image_input_verified') else 'image input unverified'
            self.message(f"{visual['model']} · {verification}\n"
                         f"Pilot reserved ${budget.get('reserved_usd', 0):.2f}/$20 · reported ${budget.get('reported_usd', 0):.6f} · operator review required")
        else:
            self.message('Review ready · image acquisition time shown on map · operator review required')
        self.redraw()

    def import_ais(self):
        path = filedialog.askopenfilename(parent=self.app.root, title='Import historical AIS recording',
                                          filetypes=[('AIS archives', '*.csv *.parquet *.json')])
        if path:
            self.task(lambda: self.workspace.import_ais(path),
                      lambda result: self.message(f"AIS archive imported · {result['bytes']:,} bytes · press AIS at image time to rematch"))

    def import_raster(self):
        path = filedialog.askopenfilename(parent=self.app.root, title='Import calibrated, terrain-corrected GeoTIFF',
                                          filetypes=[('GeoTIFF', '*.tif *.tiff')])
        if not path:
            return
        from tkinter import simpledialog
        acquired = simpledialog.askstring('Acquisition UTC', 'Exact image acquisition time, e.g. 2026-10-13T06:30:34Z', parent=self.app.root)
        if not acquired:
            return
        label = simpledialog.askstring('Evidence provenance', 'Evidence label: real, reconstructed, simulated, fictional or assumption', initialvalue='real', parent=self.app.root)
        if not label:
            return
        try:
            area = self.bbox()
        except ValueError as error:
            self.message(str(error))
            return
        sensor = self.sensor.get()
        self.task(lambda: self.workspace.import_raster(path, area, acquired, sensor, label), self.prepared)

    def build_fleet(self):
        frame = self.fleet_tab
        self.fleet_status = tk.StringVar(self.app.root, value='Fleet history inventory is loading. Checks use the linked team database.')
        ttk.Label(frame, textvariable=self.fleet_status, wraplength=340, justify='left',
                  style='Muted.TLabel').pack(fill='x', pady=6)
        ttk.Checkbutton(frame, text='Only histories requiring review', variable=self.fleet_only_leads,
                        command=self.set_fleet_filter).pack(anchor='w')
        self.fleet_table = ttk.Treeview(frame, columns=('ship', 'state', 'fixes'), show='headings', height=9, selectmode='browse')
        for key, title, width in [('ship', 'Vessel / MMSI', 145), ('state', 'History check', 140), ('fixes', 'Fixes', 55)]:
            self.fleet_table.heading(key, text=title)
            self.fleet_table.column(key, width=width)
        self.fleet_table.pack(fill='x')
        self.fleet_table.bind('<<TreeviewSelect>>', self.show_history)
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=4)
        self.fleet_previous_button = ttk.Button(controls, text='Previous', command=self.fleet_previous)
        self.fleet_previous_button.pack(side='left')
        self.fleet_next_button = ttk.Button(controls, text='Next', command=self.fleet_forward)
        self.fleet_next_button.pack(side='left', padx=4)
        ttk.Button(controls, text='Refresh', command=lambda: self.load_fleet(self.fleet_after)).pack(side='left')
        if not self.remote:
            ttk.Button(frame, text='Connect team database', command=self.connect_database).pack(anchor='w', pady=4)
        self.fleet_details = tk.Text(frame, height=17, wrap='word', bg=BG, fg=INK, relief='flat', state='disabled')
        self.fleet_details.pack(fill='both', expand=True, pady=6)

    def read_fleet(self, after='', only_leads=False):
        if self.remote:
            return self.request('fleet?'+urlencode({'after': after, 'limit': 50, 'leads': str(only_leads).lower()}))
        return self.workspace.fleet.page(after, 50, only_leads)

    def apply_fleet(self, packet, selected=None):
        from argus.fleet_history import source_health
        if packet.get('after', '') != self.fleet_after or packet.get('only_leads', False) != self.fleet_only_leads.get():
            return
        summary, worker = packet.get('summary', {}), packet.get('worker', {})
        self.fleet_status.set(
            f"{summary.get('checked_vessels', 0):,}/{summary.get('total_vessels', 0):,} recorded vessels checked · "
            f"{summary.get('never_checked', 0):,} never checked\n"
            f"{summary.get('new_evidence_pending', 0):,} awaiting new-evidence checks · {summary.get('review_required', 0):,} for review\n"
            f"Inventory {'complete' if packet.get('inventory_complete') else 'loading'} · {packet.get('inventory_vessels_cached', 0):,} cached\n"
            f"{source_health(summary)}\n"
            f"{worker.get('message', '')}\nUpdated {packet.get('updated_utc') or 'not yet'}. Partial received history, not a safety clearance.")
        self.fleet_next = packet.get('next_after')
        self.fleet_previous_button.configure(state='normal' if self.fleet_stack else 'disabled')
        self.fleet_next_button.configure(state='normal' if self.fleet_next else 'disabled')
        rows = packet.get('vessels', [])
        signature = json.dumps(rows, sort_keys=True)
        if signature != self.fleet_signature:
            old = self.fleet_table.selection()
            self.fleet_signature = signature
            self.fleet_rows = {r['mmsi']: r for r in rows}
            self.fleet_table.delete(*self.fleet_table.get_children())
            for row in rows:
                result = row.get('result') or {}
                state = ('checking' if row.get('checking') else 'unchecked' if not row.get('checked_utc') else
                         'new evidence pending' if row.get('new_evidence_pending') else result.get('status', 'checked').replace('_', ' '))
                self.fleet_table.insert('', 'end', iid=row['mmsi'], values=(result.get('name') or row['mmsi'], state,
                                                                          result.get('rows_checked', '—')))
            selected = selected or (old[0] if old and old[0] in self.fleet_rows else None)
        if selected and selected in self.fleet_rows:
            self.fleet_table.selection_set(selected)
            self.show_history()

    def load_fleet(self, after='', selected=None):
        if self.busy:
            self.message('Wait for the current satellite request before changing history pages.')
            return
        self.fleet_after = after
        only_leads = self.fleet_filter
        self.task(lambda: self.read_fleet(after, only_leads),
                  lambda packet: self.apply_fleet(packet, selected))

    def set_fleet_filter(self):
        self.fleet_filter = self.fleet_only_leads.get()
        self.fleet_stack = []
        self.fleet_after = ''
        self.watch_at = 0
        self.load_fleet('')

    def fleet_forward(self):
        if self.fleet_next and not self.busy:
            self.fleet_stack.append(self.fleet_after)
            self.load_fleet(self.fleet_next)

    def fleet_previous(self):
        if self.fleet_stack and not self.busy:
            self.load_fleet(self.fleet_stack.pop())

    def open_fleet(self, mmsi=None):
        self.app.open_window('satellite')
        self.tabs.select(self.fleet_tab)
        self.fleet_only_leads.set(False)
        self.fleet_filter = False
        self.fleet_stack = []
        if mmsi:
            self.pending_fleet = mmsi
        elif not self.busy:
            self.load_fleet('')

    def show_history(self, _event=None):
        selected = self.fleet_table.selection()
        if not selected or selected[0] not in self.fleet_rows:
            return
        row = self.fleet_rows[selected[0]]
        result = row.get('result') or {}
        lines = [f"{result.get('name') or row['mmsi']} · {row['mmsi']}",
                 f"Checked: {row.get('checked_utc') or 'not checked yet'}", result.get('caveat', ''),
                 f"Evidence: {', '.join(result.get('source_labels', [])) or 'not loaded'} · findings are assumptions",
                 f"Retained history: {result.get('first_fix_utc')} to {result.get('last_fix_utc')}",
                 f"{result.get('rows_checked', 0)} fixes · {result.get('epoch_count', 0)} stream epochs",
                 f"Reception gaps: {result.get('received_gap_count', 0)} · not proof of transponder shutdown",
                 f"New evidence pending: {bool(row.get('new_evidence_pending'))}",
                 f"{result.get('finding_count', 0)} findings · {result.get('findings_retained', 0)} retained in summary", '']
        if row.get('last_error'):
            lines += ['Check incomplete: '+row['last_error'], '']
        for finding in result.get('findings', []):
            lines += [f"{finding['received_utc']} · {finding['kind'].replace('_', ' ')}", finding['reason'], '']
        self.fleet_details.configure(state='normal')
        self.fleet_details.delete('1.0', 'end')
        self.fleet_details.insert('1.0', '\n'.join(lines))
        self.fleet_details.configure(state='disabled')

    def connect_database(self):
        if self.busy or self.remote:
            return
        from tkinter import simpledialog
        from argus import supabase_ais
        key = simpledialog.askstring('Connect team database',
            'Enter the Argus Mara Supabase secret key. It is verified and saved in this computer’s credential store; never put it in chat.',
            show='•', parent=self.app.root)
        if not key:
            return
        key = key.strip()
        def work():
            if not supabase_ais.valid_key(key):
                raise ValueError('Expected a Supabase secret or service-role key')
            state = supabase_ais.http_rpc(supabase_ais.base_url(follow_link=False)+'/rest/v1/rpc/argus_ais_status', {}, key)
            supabase_ais.save_key(key)
            supabase_ais.link(self.workspace.root)
            return state
        def done(_state):
            self.watch_at = 0
            if os.environ.get('ARGUS_SATELLITE_AUTOSTART', '1') != '0':
                self.workspace.fleet.start()
            self.message('Team database connected. History checks require the fleet-history migration on that database.')
        self.task(work, done)

    def connect(self):
        if self.busy:
            return
        from tkinter import simpledialog
        key = simpledialog.askstring('Connect TensorX', 'Paste your TensorX API key. It is saved only in this computer’s credential store. Catalogue checks are free.',
                                     show='•', parent=self.app.root)
        if not key:
            return
        def work():
            model = choose_model(key)
            save_key(key)
            atomic_json(self.workspace.root/'ai/model.json', model)
            return model
        self.task(work, lambda model: self.message(f"Connected · {model['id']} · $20 pilot ceiling"))

    def show_vessel(self, vessel):
        self.app.open_window('satellite')
        lines = [f"HISTORICAL AIS · {vessel['name']} · {vessel['mmsi']}",
                 f"At {self.current['scene']['acquired_utc']}",
                 f"{vessel['position']['lat']:.6f}, {vessel['position']['lon']:.6f}",
                 'Position: '+vessel['position_evidence']['position_method'].replace('_', ' '),
                 'Broadcast values are unverified declarations; missing fields were not supplied.', '']
        for key, field in sorted(vessel['broadcast_fields'].items()):
            lines.append(f"{key.replace('_', ' ')}: {field['value']}\n  received {field['received_utc']}")
        self.set_details('\n'.join(lines))
        return 'break'

    def radar_text(self):
        summary = self.radar_summary or {}
        if not summary.get('detections'):
            return ('Radar sees through cloud. Each Global Fishing\nWatch detection is compared with team AIS\n'
                    'at the radar time. GFW publishes ~5 days late.\n'
                    + ('Shared hosts show only their saved leads.' if self.remote else
                       'GFW connected · press Fetch radar.' if summary.get('configured') else
                       'Connect a free non-commercial GFW token.'))
        statuses = summary.get('statuses', {})
        newest = (summary.get('newest_detection_utc') or 'none')[:16].replace('T', ' ')
        return (f"{summary['detections']:,} radar cells · {summary.get('leads', 0):,} without AIS (leads)\n"
                f"{statuses.get('team_ais_match', 0):,} match team AIS · {statuses.get('nearby_ais_review', 0):,} AIS nearby\n"
                f"{statuses.get('no_contemporaneous_ais', 0) + statuses.get('time_unresolved', 0):,} not compared (no AIS history or time)\n"
                f"Newest radar {newest} UTC · GFW ~5 days late")

    def apply_radar(self, packet):
        self.radar_summary = {**packet.get('summary', {}), 'configured': packet.get('configured', False)}
        points = packet.get('points', [])
        signature = tuple((p['id'], p.get('status'), p.get('lead')) for p in points)
        if signature != self.radar_signature:
            self.radar_signature, self.radar_points = signature, points
        if self.frame is not None and self.frame.winfo_exists():
            self.radar_status.set(self.radar_text())

    def connect_gfw(self):
        if self.busy or self.remote:
            return
        from tkinter import simpledialog
        token = simpledialog.askstring('Connect Global Fishing Watch',
            'Paste your free, non-commercial Global Fishing Watch API token. One small radar request checks it, '
            'then it is saved only in this computer’s credential store; never put it in chat.',
            show='•', parent=self.app.root)
        if not token:
            return
        token = token.strip()
        def work():
            if not gfw_sar.valid_token(token):
                raise ValueError('That does not look like a Global Fishing Watch API token')
            check = gfw_sar.check_token(token)
            gfw_sar.save_token(token)
            return check
        def done(check):
            self.watch_at = 0
            self.message(f"Global Fishing Watch connected · {', '.join(check['datasets']) or gfw_sar.DATASET} · "
                         'press Fetch radar')
        self.task(work, done)

    def fetch_radar(self):
        if self.remote:
            return
        if self.busy:
            self.message('Wait for the current satellite task, then fetch radar again')
            return
        def work():
            start, end = gfw_sar.window(days=14)
            return gfw_sar.fetch(self.workspace.root, start, end)[0]
        def done(result):
            counts = result['counts']
            self.watch_at = 0
            self.message(f"Radar {result['window']['start']} to {result['window']['end_exclusive']} (end excluded) · "
                         f"{counts['detection_rows']} cells · {counts['leads']} without AIS · newest "
                         f"{result['newest_detection_utc'] or 'none'}\n{gfw_sar.ATTRIBUTION}")
        self.task(work, done)
        self.message('Fetching Global Fishing Watch radar detections, then comparing them with AIS at each radar time…')

    def open_radar_lead(self, lead):
        self.app.open_window('satellite')
        if self.remote:
            # Shared hosts send the lead itself; its detection file stays on the host.
            self.show_radar_details({'id': lead['detection_id'], 'lat': lead['lat'], 'lon': lead['lon'],
                                     'time_utc': lead['acquired_utc'], 'detections': 1, 'gfw_matched': False,
                                     'status': 'no_team_ais', 'reason': lead['reason']})
            return
        self.show_radar_point({'id': lead['detection_id']})

    def show_radar_point(self, point):
        try:
            self.show_radar_details(gfw_sar.detection(self.workspace.root, point['id']))
        except ValueError as error:
            self.message(str(error))
        return 'break'

    def show_radar_details(self, d):
        self.app.open_window('satellite')
        self.tabs.select(self.contact_tab)
        self.selected_contact = self.selected_candidate = None
        self.selected_radar = d['id']
        self.latest_button.configure(state='disabled')
        self.candidate_table.delete(*self.candidate_table.get_children())
        blank = Image.new('RGB', (330, 80), BG)
        self.contact_photo = ctk.CTkImage(light_image=blank, dark_image=blank, size=(330, 80))
        self.thumbnail.configure(image=self.contact_photo, text='Radar detection · GFW publishes positions, not pixels')
        when = d.get('time_utc') or d.get('hour_utc') or 'unknown time'
        lead = gfw_sar.is_lead(d)
        self.contact_title.configure(text=f"RADAR CONTACT · {'NO AIS · ' if lead else ''}REAL · UNREVIEWED\n"
                                          f"Sentinel-1 via Global Fishing Watch · {when}")
        vessel = d.get('gfw_vessel') or {}
        team = d.get('team_ais') or {}
        self.candidate_info.set(
            ('Lead: no AIS in GFW’s match or the team history within 1 km.' if lead else
             f"Team AIS: {RADAR_LABELS.get(d.get('status'), str(d.get('status')).replace('_', ' '))}.")
            + (f"\nGFW AIS match: {vessel.get('name') or '?'} · {vessel.get('mmsi') or 'no MMSI'}" if d.get('gfw_matched') else
               '\nGFW found no AIS match for this radar contact.'))
        sources = {'gfw_detection_timestamp': 'GFW detection time', 'sentinel1_scene_midpoint': 'Sentinel-1 scene midpoint'}
        lines = [('RADAR CONTACT WITHOUT AIS · lead for review' if lead else 'RADAR DETECTION')
                 + ' · real, published by Global Fishing Watch · unreviewed',
                 f"Team AIS at radar time ({team.get('source', 'not checked')}): "
                 + RADAR_LABELS.get(d.get('status'), str(d.get('status')).replace('_', ' '))
                 + (f" · {team['nearby_fixes']} fixes within 10 min around" if team.get('nearby_fixes') is not None else '')]
        if d.get('gfw_matched'):
            lines.append(f"GFW AIS match: {vessel.get('name') or '?'} · MMSI {vessel.get('mmsi') or '?'} · flag {vessel.get('flag') or '?'}"
                         + ('' if d.get('same_identity_as_gfw') is None else
                            ' · team AIS agrees' if d['same_identity_as_gfw'] else ' · team AIS names a different ship'))
        else:
            lines.append('GFW AIS match: none')
        if d.get('time_utc'):
            lines.append(f"Radar time {d['time_utc']} · {sources.get(d.get('time_source'), 'time from the report')}"
                         + (f" ± {d['time_uncertainty_s']:.0f} s" if d.get('time_uncertainty_s') else ''))
        else:
            lines.append(f"Hourly bin {d.get('hour_utc')} · no Sentinel-1 scene time, so AIS was not compared")
        lines.append(f"Cell {d['lat']:.3f}, {d['lon']:.3f} ± {d.get('cell_deg', gfw_sar.CELL_DEG)/2:.3f}° (about 1.1 × 0.7 km) · "
                     f"{d.get('detections', 1)} radar target(s)")
        if team.get('note') or team.get('error'):
            lines.append(team.get('note') or team.get('error'))
        if d.get('candidates'):
            lines += ['', 'AIS WITHIN 1 KM OF THE CELL · provisional, identity unconfirmed']
        for candidate in d.get('candidates', []):
            evidence = candidate.get('position_evidence') or {}
            lines.append(f"{candidate['name']} · {candidate['mmsi']} · {candidate['distance_m']:.0f} m from the cell"
                         f"{' · matched' if candidate.get('assigned') else ''} · fix Δ {candidate.get('nearest_fix_offset_s')} s · "
                         f"{str(evidence.get('position_method', 'position')).replace('_', ' ')}")
        if d.get('reason'):
            lines += ['', d['reason']]
        if d.get('scene_ids'):
            lines += ['', 'Sentinel-1 scene: ' + ', '.join(d['scene_ids'])]
        lines += ['', gfw_sar.CAVEAT, '', f"{gfw_sar.ATTRIBUTION} · {gfw_sar.ATTRIBUTION_URL}"]
        self.set_details('\n'.join(lines))
        self.fit_visible([(d['lat']-.03, d['lon']-.05), (d['lat']+.03, d['lon']+.05)])
        self.redraw()
        return 'break'

    @staticmethod
    def radar_label(point):
        when = (point.get('time_utc') or point.get('hour_utc') or '')[5:16].replace('T', ' ')
        if point.get('lead'):
            return 'Radar · no AIS · ' + when
        if point.get('gfw_matched') and point.get('status') == 'no_team_ais':
            return f"Radar · GFW AIS {point.get('gfw_name') or ''} · not in team AIS · {when}"
        return f"Radar · {RADAR_LABELS.get(point.get('status'), 'unchecked')} · {when}"

    def draw_radar(self):
        if not self.show_radar.get() or not self.radar_points:
            return
        canvas, (width, height) = self.app.map, self.app._map_size
        shown = 0
        for point in self.radar_points:
            x, y = self.app._project(point['lat'], point['lon'])
            if not -10 <= x <= width+10 or not -10 <= y <= height+10:
                continue
            shown += 1
            tag, lead = 'radar-contact-'+point['id'], point.get('lead')
            if self.app.map_zoom >= 11:
                half = point.get('cell_deg', gfw_sar.CELL_DEG)/2
                x0, y0 = self.app._project(point['lat']+half, point['lon']-half)
                x1, y1 = self.app._project(point['lat']-half, point['lon']+half)
                canvas.create_rectangle(x0, y0, x1, y1, outline=RADAR if lead else RADAR_MUTED, dash=(2, 3), tags=tag)
            if point['id'] == self.selected_radar:
                canvas.create_oval(x-13, y-13, x+13, y+13, outline=INK, width=2, tags=tag)
            if lead:
                canvas.create_oval(x-8, y-8, x+8, y+8, fill='#3d1f4f', outline=RADAR, width=2, tags=tag)
                canvas.create_oval(x-2, y-2, x+2, y+2, fill=RADAR, outline=RADAR, tags=tag)
            else:
                canvas.create_oval(x-5, y-5, x+5, y+5, outline=RADAR_MUTED, width=2, dash=(2, 2), tags=tag)
            if self.app.map_zoom >= 9 or (lead and self.app.map_zoom >= 7):
                canvas.create_text(x+11, y-8, anchor='nw', fill=RADAR if lead else RADAR_MUTED,
                                   text=self.radar_label(point), font=('Segoe UI', 9), tags=tag)
            canvas.tag_bind(tag, '<Button-1>', lambda event, p=point: self.show_radar_point(p))
        label = getattr(self.app, 'map_attribution_label', None)
        if shown and label is not None and gfw_sar.ATTRIBUTION not in str(label.cget('text')):
            label.configure(text=f"{label.cget('text')} · Radar: {gfw_sar.ATTRIBUTION}")

    def draw(self):
        if not self.app.allowed('evidence.share'):
            return
        self.draw_radar()
        if self.current is None:
            self.draw_coastal_contacts()
            return
        canvas, scene = self.app.map, self.current['scene']
        w, s, e, n = scene['bbox']
        x0, y0 = self.app._project(n, w)
        x1, y1 = self.app._project(s, e)
        width, height = self.app._map_size
        if x1 < 0 or x0 > width or y1 < 0 or y0 > height or x1 <= x0 or y1 <= y0:
            self.draw_coastal_contacts()
            return
        if self.show_image.get() and self.image is not None:
            left, top, right, bottom = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
            target = (max(1, round(right-left)), max(1, round(bottom-top)))
            key = (scene['id'], self.app.map_zoom, self.app.map_center, width, height)
            if key != self.map_image_key:
                source = ((left-x0)/(x1-x0)*self.image.width, (top-y0)/(y1-y0)*self.image.height,
                          (right-x0)/(x1-x0)*self.image.width, (bottom-y0)/(y1-y0)*self.image.height)
                cropped = self.image.transform(target, Image.Transform.EXTENT, source, Image.Resampling.BILINEAR)
                self.map_photo = ImageTk.PhotoImage(cropped)
                self.map_image_key = key
            canvas.create_image(left, top, image=self.map_photo, anchor='nw')
        canvas.create_rectangle(x0, y0, x1, y1, outline=TEAL, width=2, dash=(6, 3))
        canvas.create_text(max(12, x0+6), max(34, y0+6), anchor='nw', fill=TEAL,
                           text=f"{scene['sensor']} · {scene['acquired_utc']}\nHISTORICAL · {scene['label'].upper()} PIXELS · AI UNREVIEWED",
                           font=('Segoe UI Semibold', 9))
        if self.show_ais.get():
            when = timestamp(scene['acquired_utc'])
            for index, vessel in enumerate(self.current['ais']['vessels']):
                position = vessel['position']
                x, y = self.app._project(position['lat'], position['lon'])
                previous = None
                for point in vessel['track']:
                    if timestamp(point['ts']) > when:
                        break
                    if previous and timestamp(point['ts'])-timestamp(previous['ts']) <= 600:
                        canvas.create_line(*self.app._points([(previous['lat'], previous['lon']), (point['lat'], point['lon'])]), fill='#80bcf1', width=2)
                    previous = point
                tag = f'satellite-ais-{index}'
                canvas.create_oval(x-5, y-5, x+5, y+5, fill='#14354e', outline='#80bcf1', width=2, tags=tag)
                canvas.tag_bind(tag, '<Button-1>', lambda event, v=vessel: self.show_vessel(v))
        if self.show_ai.get():
            for point in self.current['contacts']:
                x, y = self.app._project(point['lat'], point['lon'])
                tag = 'satellite-contact-'+point['id']
                canvas.create_rectangle(x-8, y-8, x+8, y+8, outline='#e1b164', width=2, dash=(3, 2), tags=tag)
                canvas.create_text(x+11, y-8, anchor='nw', fill='#e1b164',
                                   text=point['id']+' · '+point['confidence']+' confidence · '+
                                   ('unclassified optical feature' if point['id'].startswith('OPT-') else 'AI assumption'), font=('Segoe UI', 9), tags=tag)
                canvas.tag_bind(tag, '<Button-1>', lambda event, p=point: self.show_contact(p))
        self.draw_coastal_contacts()

    def draw_coastal_contacts(self):
        if not self.show_ai.get():
            return
        canvas = self.app.map
        width, height = self.app._map_size
        current_id = self.current['scene']['id'] if self.current else None
        for index, point in enumerate(self.map_contacts):
            if point['scene_id'] == current_id:
                continue
            x, y = self.app._project(point['lat'], point['lon'])
            if not -10 <= x <= width+10 or not -10 <= y <= height+10:
                continue
            tag = f'coastal-contact-{index}'
            canvas.create_polygon(x, y-7, x+7, y, x, y+7, x-7, y, fill='#73532b', outline='#e1b164', width=2, tags=tag)
            if self.app.map_zoom >= 9:
                origin = 'Unclassified feature' if point['id'].startswith('OPT-') else 'AI observation'
                canvas.create_text(x+10, y-8, anchor='nw', text=origin+' · '+point['ts'][5:16].replace('T', ' '), fill='#e1b164', font=('Segoe UI', 9), tags=tag)
            canvas.tag_bind(tag, '<Button-1>', lambda event, p=point: self.open_map_contact(p))
        candidate = self.selected_candidate
        latest = (candidate or {}).get('latest')
        if latest and self.selected_contact:
            point = self.selected_contact
            x, y = self.app._project(latest['lat'], latest['lon'])
            x0, y0 = self.app._project(point['lat'], point['lon'])
            canvas.create_line(x0, y0, x, y, fill='#7cc6ee', width=2, dash=(5, 5))
            tag = 'satellite-latest'
            canvas.create_oval(x-7, y-7, x+7, y+7, outline='#7cc6ee', fill='#173e56', width=2, tags=tag)
            canvas.create_text(x+11, y+4, anchor='nw', text=f"{candidate['name']} · latest received\n{latest['received_utc']} {'· STALE' if latest['stale'] else ''}",
                               fill='#7cc6ee', font=('Segoe UI', 9), tags=tag)
            canvas.tag_bind(tag, '<Button-1>', lambda event: self.select_candidate())

    def close(self):
        self.closed = True
        self.app.root.after_cancel(self.poll_timer)
        self.app.root.after_cancel(self.resume_timer)
        self.workspace.fleet.stop()
        if self._engine:
            self._engine.stop(suspend=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
