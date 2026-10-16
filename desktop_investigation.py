"""Native investigation lab: source timeline, encounters, sandbox and evaluation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from argus.investigation import epoch, pair_review, timeline, utc
from argus.scenario_lab import ScenarioLab, encounter_exercise
from argus.evaluation import evaluate_cases, exercise_cases

BG, INK, MUTED = "#141e28", "#e4ebf0", "#a8b6c2"
COLOURS = ("#47c7da", "#f0bd70", "#c88cff", "#91cb82", "#fc8b8b")


def snapshot_sources(app):
    """Snapshot already available evidence only; no network, AI calls or disk scans."""
    origin = epoch(app.scenario["t0_utc"])
    replay = []
    for vessel in app.scenario["vessels"]:
        copied = deepcopy(vessel)
        copied["track"] = [{**f, "t": origin + f["t"]} for f in copied["track"] if f["t"] <= app.position_s]
        copied["source"] = "Exercise AIS; fictional"
        replay.append(copied)
    received = []
    tracker = app.ais_tracker
    for mmsi, vessel in tracker.state.vessels.items():
        fixes = tracker.history.tracks.get(mmsi, [])
        if not fixes:
            continue
        label = vessel.get("label", "real")
        segment, track, previous = 0, [], None
        for point in fixes:
            if previous and (point.get("label") != previous.get("label") or point.get("stream_id") != previous.get("stream_id")):
                segment += 1
            if point.get("label") == label:
                track.append({**point, "t": point["received_s"], "source_segment": segment})
            previous = point
        received.append({"mmsi": str(mmsi), "name": vessel.get("name") or str(mmsi), "label": label,
                         "source": "Locally received AIS; incomplete reception",
                         "track": track})
    observations = []
    for detection in app.scenario.get("detections", []):
        if detection["t"] <= app.position_s:
            observations.append({**deepcopy(detection), "acquired_utc": utc_iso(origin + detection["t"]),
                                 "source": "Exercise radar; association unconfirmed"})
    satellite = getattr(app, "satellite", None)
    for point in getattr(satellite, "map_contacts", []):
        stamp = point.get("ts")
        if stamp is not None:
            observations.append({**deepcopy(point), "acquired_utc": utc_iso(epoch(stamp)),
                                 "source": f"{point.get('sensor', 'Satellite')} cached observation"})
    for point in getattr(satellite, "radar_points", []):
        if point.get("time_utc"):
            observations.append({**deepcopy(point), "acquired_utc": point["time_utc"], "label": "real",
                                 "scene_label": "real", "source": "Global Fishing Watch radar; cached index",
                                 "source_kind": "gfw"})
    return replay, received, observations


def utc_iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def table(parent, columns, height=6):
    holder = ttk.Frame(parent)
    holder.pack(fill="both", expand=True, pady=4)
    widget = ttk.Treeview(holder, columns=[c[0] for c in columns], show="headings", height=height)
    for key, name, width in columns:
        widget.heading(key, text=name)
        widget.column(key, width=width, minwidth=width, stretch=False)
    vertical = ttk.Scrollbar(holder, orient="vertical", command=widget.yview)
    horizontal = ttk.Scrollbar(holder, orient="horizontal", command=widget.xview)
    widget.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    holder.columnconfigure(0, weight=1)
    holder.rowconfigure(0, weight=1)
    widget.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    return widget


def wrap_label(parent, **kwargs):
    label = ttk.Label(parent, **kwargs)
    label.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width - 8)))
    return label


def text_box(parent, height=7):
    box = tk.Text(parent, height=height, wrap="word", bg=BG, fg=INK, insertbackground=INK,
                  relief="flat", font=("Segoe UI", 10), padx=8, pady=6)
    scroll = ttk.Scrollbar(parent, command=box.yview)
    box.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    box.pack(fill="both", expand=True)
    box.configure(state="disabled")
    return box


def set_text(box, content):
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", content)
    box.configure(state="disabled")


class TrackChart:
    """Small schematic replay. Gaps and stream changes are never joined."""
    def __init__(self, parent):
        self.canvas = tk.Canvas(parent, height=145, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="x", pady=5)
        self.args = ([], [], None)
        self.canvas.bind("<Configure>", lambda _e: self.draw(*self.args))

    def draw(self, vessels, cables=(), until=None):
        self.args = (vessels, cables, until)
        self.canvas.delete("all")
        points = [f for v in vessels for f in v.get("track", [])]
        points += [{"lat": lat, "lon": lon} for c in cables for lat, lon in c.get("path", [])]
        if not points:
            self.canvas.create_text(12, 20, anchor="w", fill=MUTED, text="No positions available")
            return
        low_lat, high_lat = min(p["lat"] for p in points), max(p["lat"] for p in points)
        low_lon, high_lon = min(p["lon"] for p in points), max(p["lon"] for p in points)
        width, height = max(150, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        def xy(p):
            return (14 + (p["lon"] - low_lon) / max(.01, high_lon-low_lon) * (width-28),
                    height-14 - (p["lat"] - low_lat) / max(.01, high_lat-low_lat) * (height-48))
        for cable in cables:
            coordinates = [n for lat, lon in cable.get("path", []) for n in xy({"lat": lat, "lon": lon})]
            if len(coordinates) >= 4:
                self.canvas.create_line(*coordinates, fill="#a4a8ad", dash=(4, 4))
        for index, vessel in enumerate(vessels):
            visible = [f for f in vessel["track"] if until is None or f["t"] <= until]
            colour = COLOURS[index % len(COLOURS)]
            for a, b in zip(visible, visible[1:]):
                if b["t"] - a["t"] <= 180 and a.get("stream_id") == b.get("stream_id") and abs(b["lon"]-a["lon"]) <= 180:
                    self.canvas.create_line(*xy(a), *xy(b), fill=colour, width=2)
            if visible:
                x, y = xy(visible[-1])
                self.canvas.create_oval(x-4, y-4, x+4, y+4, fill=colour, outline="")
        self.canvas.create_text(8, 8, anchor="nw", fill=MUTED, text="SCHEMATIC · observed tracks · north up")


class InvestigationLab:
    def __init__(self, app, frame):
        self.app, self.frame = app, frame
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="argus-investigation")
        self.future = None
        self.poll_job = self.play_job = None
        self.events, self.pairs = [], []
        self.result = None
        self.lab = getattr(app, "_investigation_branch", None)
        self.replay, self.received, self.observations = snapshot_sources(app)
        self.status = tk.StringVar(frame, value="Local evidence and fictional exercises · human review required")
        wrap_label(frame, textvariable=self.status, wraplength=380).pack(fill="x", pady=(0, 5))
        style = ttk.Style(frame)
        style.configure("Lab.TNotebook", background=BG, borderwidth=0)
        style.configure("Lab.TNotebook.Tab", background="#1c2c39", foreground=MUTED, padding=(8, 6))
        style.map("Lab.TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", COLOURS[0])])
        style.configure("Lab.TCombobox", fieldbackground=BG, foreground=INK)
        style.map("Lab.TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", INK)],
                  selectbackground=[("readonly", BG)], selectforeground=[("readonly", INK)])
        self.tabs = ttk.Notebook(frame, style="Lab.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        self.pages = {}
        for key, title in (("timeline", "Timeline"), ("pairs", "Encounters"), ("challenge", "Challenge"), ("evaluation", "Evaluation")):
            page = ttk.Frame(self.tabs, padding=5)
            self.tabs.add(page, text=title)
            self.pages[key] = page
        self.build_timeline()
        self.build_pairs()
        self.build_challenge()
        self.build_evaluation()
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self.pause())
        frame.bind("<Destroy>", self.close, add="+")

    def close(self, event=None):
        if event is not None and event.widget is not self.frame:
            return
        self.closed = True
        self.app._investigation_branch = self.lab
        self.pause()
        if self.poll_job:
            self.frame.after_cancel(self.poll_job)
            self.poll_job = None
        if self.future:
            self.future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def job(self, work, done):
        if self.future is not None:
            self.status.set("A local calculation is already running")
            return
        self.status.set("Calculating from a fixed local snapshot…")
        self.future = self.executor.submit(work)
        def poll():
            self.poll_job = None
            if self.closed:
                return
            if not self.future.done():
                self.poll_job = self.frame.after(80, poll)
                return
            pending, self.future = self.future, None
            try:
                result = pending.result()
                if not self.app.require_tool("evidence.share"):
                    self.status.set("Evidence access is no longer available")
                    return
                done(result)
                self.status.set("Complete · review evidence and assumptions below")
            except Exception as error:
                self.status.set(f"Calculation failed: {error}")
        self.poll_job = self.frame.after(80, poll)

    def refresh(self):
        if not self.app.require_tool("evidence.share"):
            return
        self.replay, self.received, self.observations = snapshot_sources(self.app)
        self.refresh_choices()
        self.refresh_pair_choices()
        self.show_timeline()
        self.status.set("Evidence refreshed from currently loaded sources")

    def build_timeline(self):
        page = self.pages["timeline"]
        bar = ttk.Frame(page)
        bar.pack(fill="x")
        self.subject = ttk.Combobox(bar, state="readonly", style="Lab.TCombobox")
        self.subject.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")
        self.subject.bind("<<ComboboxSelected>>", lambda _e: self.show_timeline())
        self.key_events_only = tk.BooleanVar(page, True)
        ttk.Checkbutton(page, text="Key events only (include first and latest fixes)", variable=self.key_events_only,
                        command=self.show_timeline).pack(anchor="w")
        self.event_table = table(page, [("time", "UTC", 150), ("kind", "Event", 90), ("label", "Provenance", 85), ("title", "Summary", 270)])
        self.event_table.bind("<<TreeviewSelect>>", self.select_event)
        actions = ttk.Frame(page)
        actions.pack(fill="x")
        ttk.Button(actions, text="Show location", command=self.center_event).pack(side="left")
        ttk.Button(actions, text="Open source", command=self.open_source).pack(side="left", padx=3)
        ttk.Button(actions, text="Export timeline", command=lambda: self.export(self.events, "investigation-timeline.json")).pack(side="left")
        detail = ttk.Frame(page)
        detail.pack(fill="both", expand=True, pady=4)
        self.event_detail = text_box(detail)
        self.refresh_choices()
        self.show_timeline()

    def refresh_choices(self):
        current = self.subject.get()
        self.subjects = {f"{v.get('name', v['mmsi'])} · {v['mmsi']} · {v['label']}": v for v in self.replay + self.received}
        self.subject.configure(values=[*self.subjects, "Unassociated observations"])
        self.subject.set(current if current in self.subjects or current == "Unassociated observations" else next(iter(self.subjects), "Unassociated observations"))

    def show_timeline(self):
        vessel = self.subjects.get(self.subject.get())
        if vessel:
            self.events = timeline(vessel, observations=self.observations,
                                  reports=self.app.vessel_reports.entries,
                                  identity_history=getattr(self.app.ais_tracker.history, "identity_events", []))
        else:
            self.events = [{"t": epoch(p["acquired_utc"]), "kind": "satellite", "label": p.get("label", "assumption"),
                            "title": "Separate observation; identity unconfirmed", "source": p["source"],
                            "position": [p["lat"], p["lon"]], "record": p}
                           for p in self.observations if not p.get("matched_mmsi")]
            self.events.sort(key=lambda p: p["t"])
        self.event_table.delete(*self.event_table.get_children())
        fix_indices = [i for i, e in enumerate(self.events) if e["kind"] == "fix"]
        end_fixes = set(fix_indices[:1] + fix_indices[-1:])
        for index, event in enumerate(self.events):
            if self.key_events_only.get() and event["kind"] == "fix" and index not in end_fixes:
                continue
            self.event_table.insert("", "end", iid=str(index), values=(utc(event["t"]), event["kind"], event["label"], event["title"]))
        set_text(self.event_detail, "Select an event to inspect its source record.\n\nTimeline uses available local history only. Satellite associations remain provisional. Identity changes are recorded from local snapshots after this version starts; earlier changes are unknown. Reports retain their actual submission time.")

    def selected_event(self):
        selected = self.event_table.selection()
        return self.events[int(selected[0])] if selected else None

    def select_event(self, _event=None):
        event = self.selected_event()
        if event:
            set_text(self.event_detail, f"{event['title']}\n{utc(event['t'])}\n{event['label']} · {event['source']}\n\n" + json.dumps(event["record"], indent=2, ensure_ascii=False))

    def center_event(self):
        event = self.selected_event()
        if event and event.get("position") and self.app.require_tool("map.view"):
            self.app.map_center = tuple(event["position"])
            self.app.map_zoom = max(9, self.app.map_zoom)
            self.app.render()
            self.status.set(f"Map centred on {utc(event['t'])}; source position, not a current fix")

    def open_source(self):
        event = self.selected_event()
        if not event:
            return
        self.select_event()
        record = event["record"]
        if record.get("source_kind") == "gfw":
            self.app.satellite.show_radar_point(record)
        elif event["kind"] == "satellite" and record.get("scene_id") and record.get("id"):
            self.app.satellite.open_map_contact(record)
        else:
            self.status.set("Original available source record is shown below")

    def build_pairs(self):
        page = self.pages["pairs"]
        self.pair_source = ttk.Combobox(page, state="readonly", style="Lab.TCombobox", values=("Fictional encounter exercise", "Current replay", "Received AIS history"))
        self.pair_source.set("Fictional encounter exercise")
        self.pair_source.pack(fill="x")
        self.pair_source.bind("<<ComboboxSelected>>", lambda _e: self.refresh_pair_choices())
        wrap_label(page, text="Select 2–40 vessels · six-hour history window", wraplength=380).pack(fill="x")
        self.pair_choices = tk.Listbox(page, height=3, selectmode="extended", exportselection=False, bg=BG, fg=INK,
                                      selectbackground="#294254", selectforeground=INK)
        self.pair_choices.pack(fill="x")
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=3)
        ttk.Button(actions, text="Review selected", command=self.review_pairs).pack(side="left")
        ttk.Button(actions, text="Export review", command=lambda: self.export(self.pairs, "encounter-review.json")).pack(side="left", padx=3)
        footer = ttk.Frame(page)
        footer.pack(side="bottom", fill="x")
        self.pair_caption = tk.StringVar(page, value="Select an encounter to replay its supporting observations")
        wrap_label(footer, textvariable=self.pair_caption, wraplength=380).pack(fill="x")
        self.pair_time = tk.DoubleVar(page, 0)
        self.pair_slider = ttk.Scale(footer, variable=self.pair_time, command=self.draw_pair)
        self.pair_slider.pack(fill="x")
        self.pair_table = table(page, [("pair", "Vessels", 170), ("kind", "Pattern", 130), ("status", "Disposition", 120)], height=3)
        self.pair_table.bind("<<TreeviewSelect>>", self.select_pair)
        self.pair_chart = TrackChart(page)
        self.pair_chart.canvas.configure(height=85)
        self.refresh_pair_choices()

    def refresh_pair_choices(self):
        source = self.pair_source.get()
        self.pair_vessels = encounter_exercise() if source == "Fictional encounter exercise" else self.replay if source == "Current replay" else self.received
        self.pair_choices.delete(0, "end")
        for vessel in self.pair_vessels:
            self.pair_choices.insert("end", f"{vessel.get('name', vessel['mmsi'])} · {vessel['mmsi']} · {vessel['label']}")
        if self.pair_vessels:
            self.pair_choices.selection_set(0, min(4 if source == "Fictional encounter exercise" else 1, len(self.pair_vessels)-1))

    def review_pairs(self):
        selection = self.pair_choices.curselection()
        if not 2 <= len(selection) <= 40:
            self.status.set("Select between 2 and 40 vessels")
            return
        vessels = deepcopy([self.pair_vessels[i] for i in selection])
        now = max((f["t"] for v in vessels for f in v["track"]), default=0)
        def done(result):
            self.pairs = result
            self.pair_table.delete(*self.pair_table.get_children())
            for i, row in enumerate(result):
                self.pair_table.insert("", "end", iid=str(i), values=(" / ".join(row["names"]), row["kind"], row["status"]))
            self.pair_caption.set(f"{len(result)} patterns. Thresholds are assumptions; no finding establishes coordination or intent.")
            if result:
                self.pair_table.selection_set("0")
                self.select_pair()
        self.job(lambda: pair_review(vessels, now), done)

    def select_pair(self, _event=None):
        selected = self.pair_table.selection()
        if selected:
            row = self.pairs[int(selected[0])]
            self.pair_slider.configure(from_=row["start"], to=max(row["start"]+1, row["end"]))
            self.pair_time.set(row["end"])
            self.draw_pair()

    def draw_pair(self, _value=None):
        selected = self.pair_table.selection()
        if not selected:
            return
        row = self.pairs[int(selected[0])]
        tracks = [{"track": [s[key] for s in row["samples"]]} for key in ("a", "b")]
        self.pair_chart.draw(tracks, until=self.pair_time.get())
        offset = (self.pair_time.get() - row["start"]) / 60
        self.pair_caption.set(f"{row['label'].upper()} · +{offset:.1f} min · closest {row['min_distance_nm']:.2f} nm\n"
                              + ("Context: " + "; ".join(row["context"]) if row["context"] else "For review · identity and intent unconfirmed"))

    def build_challenge(self):
        page = self.pages["challenge"]
        wrap_label(page, text="FICTIONAL · edit inputs, then advance", wraplength=380).pack(fill="x")
        controls = ttk.Frame(page)
        controls.pack(fill="x", pady=5)
        self.speed, self.course, self.wind = tk.StringVar(page), tk.StringVar(page), tk.StringVar(page, "0")
        for i, (title, var) in enumerate((("Speed kn", self.speed), ("Course °", self.course), ("Wind kn", self.wind))):
            ttk.Label(controls, text=title).grid(row=0, column=i, sticky="w")
            ttk.Entry(controls, textvariable=var, width=9).grid(row=1, column=i, sticky="ew", padx=(0, 5))
            controls.columnconfigure(i, weight=1)
        self.ais = tk.BooleanVar(page, True)
        ttk.Checkbutton(page, text="AIS observations available", variable=self.ais).pack(anchor="w")
        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=3)
        for title, action in (("+1 min", lambda: self.advance(60)), ("+5 min", lambda: self.advance(300)),
                              ("Play", self.play), ("Pause", self.pause), ("Reset", self.reset_challenge)):
            ttk.Button(buttons, text=title, command=action, width=7).pack(side="left", padx=1)
        self.challenge_chart = TrackChart(page)
        self.challenge_chart.canvas.configure(height=90)
        self.challenge_status = tk.StringVar(page)
        wrap_label(page, textvariable=self.challenge_status, wraplength=380).pack(fill="x")
        ttk.Button(page, text="Export branch and assumptions", command=self.export_branch).pack(side="bottom", anchor="w")
        detail = ttk.Frame(page)
        detail.pack(fill="both", expand=True, pady=4)
        self.challenge_detail = text_box(detail, 9)
        if self.lab is None:
            self.reset_challenge()
        else:
            self.speed.set(f"{self.lab.speed:g}")
            self.course.set(f"{self.lab.course:g}")
            self.wind.set(f"{self.lab.wind:g}")
            self.ais.set(self.lab.ais)
            self.show_challenge(self.lab.evaluate())

    def reset_challenge(self):
        self.pause()
        self.lab = ScenarioLab(self.app.scenario, self.app.vessel["mmsi"], self.app.position_s)
        self.speed.set(f"{self.lab.speed:g}")
        self.course.set(f"{self.lab.course:g}")
        self.wind.set("0")
        self.ais.set(True)
        self.show_challenge(self.lab.evaluate())

    def advance(self, seconds):
        try:
            self.lab.configure(float(self.speed.get()), float(self.course.get()), self.ais.get(), float(self.wind.get()))
            self.show_challenge(self.lab.advance(seconds))
            return True
        except (ValueError, TypeError) as error:
            self.pause()
            self.status.set(str(error))
            return False

    def play(self):
        self.pause()
        def tick():
            self.play_job = None
            if not self.closed and self.advance(60):
                self.play_job = self.frame.after(750, tick)
        tick()

    def pause(self):
        if self.play_job:
            self.frame.after_cancel(self.play_job)
            self.play_job = None

    def show_challenge(self, result):
        level = result["assessment"]["assessment"]["level"].upper()
        eta = "No projected reachable-line crossing" if result["earliest_min"] is None else f"Earliest approach {result['earliest_min']:.1f} min"
        self.challenge_status.set(f"Branch +{(self.lab.now-self.lab.start)/60:.0f} min · {level}\n{eta} · last fix {result['observation_age_s']/60:.1f} min old")
        observed = [{"track": [f for f in self.lab.vessel["track"] if f["t"] >= self.lab.start]}]
        self.challenge_chart.draw(observed, self.lab.scenario["cables"])
        lines = [result["note"], result.get("eta_method") or "No approach estimate available."]
        if result["dark"]:
            lines.append(f"AIS unavailable: assumed reachable radius {result['reachable_radius_nm']:.1f} nm. Fleet ETAs remain conditional on last observed course/speed.")
        for finding in result["assessment"]["findings"]:
            lines.extend(finding["reasons"])
        lines.append("\nASSUMED OBSERVATION OPTIONS")
        for row in result["fleet"]["rows"]:
            eta = "unavailable" if row["eta_s"] is None else f"{row['eta_s']/60:.0f} min"
            lines.append(f"{row['name']}: {eta} · {row['status']}" + (f" · {row['reason']}" if row.get("reason") else ""))
        set_text(self.challenge_detail, "\n\n".join(lines))

    def export_branch(self):
        self.pause()
        self.export({"label": "fictional", "t0_utc": self.lab.scenario.get("t0_utc"), "start_s": self.lab.start,
                     "now_s": self.lab.now, "inputs": self.lab.actions, "observed_vessel": self.lab.vessel,
                     "simulated_truth": self.lab.truth, "cables": self.lab.scenario["cables"],
                     "fleet_assumptions": self.lab.fleet, "result": self.lab.evaluate()}, "fictional-branch.json")

    def build_evaluation(self):
        page = self.pages["evaluation"]
        wrap_label(page, text="Five fictional stories · development results only.\nBrain vs 1 nm proximity on the same tracks.", wraplength=380).pack(fill="x")
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=4)
        ttk.Button(actions, text="Run comparison", command=self.run_evaluation).pack(side="left")
        ttk.Button(actions, text="Export results", command=lambda: self.export(self.result, "exercise-evaluation.json")).pack(side="left", padx=4)
        self.eval_table = table(page, [("case", "Story", 170), ("label", "Review?", 95),
                                      ("brain", "Brain", 70), ("baseline", "Baseline", 95),
                                      ("lead", "Lead (min)", 110)], height=5)
        self.eval_table.bind("<<TreeviewSelect>>", self.select_case)
        detail = ttk.Frame(page)
        detail.pack(fill="both", expand=True, pady=4)
        self.eval_detail = text_box(detail, 10)
        set_text(self.eval_detail, "Run the comparison to calculate results.\n\nWarning lead is measured to first observed entry into a 1 nm corridor. Negative means the alert was later. No entry or no alert means no lead measurement. Alert episodes count transitions, not every refresh.")

    def run_evaluation(self):
        def done(result):
            self.result = result
            self.eval_table.delete(*self.eval_table.get_children())
            for i, row in enumerate(result["rows"]):
                lead = row["brain_lead_s"]
                self.eval_table.insert("", "end", iid=str(i), values=(row["name"], "Yes" if row["expected_review"] else "No", row["brain_episodes"],
                    row["baseline_episodes"], "N/A" if lead is None else f"{lead/60:+.1f}"))
            lines = [result["scope"], result["method"]]
            for key, title in (("brain", "BRAIN"), ("baseline", "PROXIMITY BASELINE")):
                row = result[key]
                lines.append(f"{title}: {row['alert_episodes']} alert episodes / {row['vessel_hours']:.1f} vessel-hours.\n"
                             f"Story labels: TP {row['true_positive']} · FP {row['false_positive']} · FN {row['false_negative']} · TN {row['true_negative']}.")
            lines.append(f"Dataset SHA-256: {result['dataset_sha256']}\n{result['version']}\nSelect a story for its label basis and exact timings.")
            set_text(self.eval_detail, "\n\n".join(lines))
        self.job(lambda: evaluate_cases(exercise_cases()), done)

    def select_case(self, _event=None):
        selected = self.eval_table.selection()
        if selected and self.result:
            row = self.result["rows"][int(selected[0])]
            set_text(self.eval_detail, self.result["scope"] + "\n\n" + self.result["method"] + "\n\n" + json.dumps(row, indent=2))

    def export(self, payload, name):
        if payload is None:
            self.status.set("Run the calculation before exporting")
            return
        if not self.app.require_tool("evidence.share"):
            return
        selected = filedialog.asksaveasfilename(parent=self.frame, defaultextension=".json", initialfile=name,
                                              filetypes=[("JSON evidence", "*.json")])
        if not selected:
            return
        path = Path(selected).resolve()
        root = Path(__file__).resolve().parent
        if path in {(root / "demo/scenario.json").resolve(), (root / "demo/alerts.json").resolve()}:
            self.status.set("Choose a new export file; shared demo contracts are protected")
            return
        try:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            self.status.set(f"Exported {path.name}")
        except (OSError, ValueError) as error:
            self.status.set(f"Export failed: {error}")
