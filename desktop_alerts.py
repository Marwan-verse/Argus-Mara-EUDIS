"""Docked incident queue: one card per vessel, a review window and map markers.

The queue scores the fictional exercise alert and the simulated contacts through
Brain (``argus.brain_board``: the assembler's detectors, the small-vessel rule
and the AIS spoofing detector) and folds the scores into ``argus.incidents``
(``argus.incident_board``). A contact at Medium or above is one updatable
incident card; Low and None contacts are watched, not incidents. Each is marked
by its source in its card, in its review window and on the map: EXERCISE, BRAIN
(a fictional story track that the detectors score at the replay time, "from
track") or SIM (hand-written simulated observations). Acknowledge,
escalate and reject go through ``argus.incidents.set_status`` and stay in this
session; nothing is transmitted.

Each incident also shows who can reach it (``argus.responders``): one line on
the card, every asset with minutes and reasons in the review window while
escalating, and on the map the bases and a dashed line from the best asset to
where it meets the vessel. The storm switch grounds the drones; the wind is an exercise value.
Send and Recall (permission ``response.review``) record a simulated human
decision: a sent asset is busy for every other incident, so one that relied
on it can rise, and the review window warns before that happens.
"""
from __future__ import annotations

import math
import sys
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from argus import responders
from argus.alert_board import inside, line_path, sort_key
from argus.brain_board import build_board, update
from argus.explain import explain, source
from argus.incident_board import OPEN_RANK, Replay
from argus.incidents import QUIET_CLOSE_S, REASONS, STATUSES
from argus.levels import LEVEL_NAMES, RANK

LEVELS = ("critical", "high", "medium", "low")
CODES = {"critical": "CRIT", "high": "HIGH", "medium": "MED", "low": "LOW", "none": "—"}
# Level colour and a dark tint of it; colour is used for severity only.
STYLE = {
    "critical": ("#e5534b", "#3a2023"), "high": ("#ec8a3c", "#3a2a1d"),
    "medium": ("#d8b25c", "#34301f"), "low": ("#5d9cec", "#1b2a3d"), "none": ("#7d8b97", "#1f2b36"),
}
SANS = "Segoe UI"
MONO = "Menlo" if sys.platform == "darwin" else "Consolas"
SECONDARY = "#c3ced6"
ROW_HOVER, ROW_SELECTED = "#18242f", "#203243"
RECIPIENTS = ("Duty officer", "Line operator", "Irish Coast Guard (MRCC)", "Naval Service operations")
SORTS = ("Severity", "Time to asset", "Newest")
STATUS_DETAIL = {"New": "Awaiting review", "Reviewed": "No decision", "Acknowledged": "Monitoring"}
MARKER_SIZE = {"critical": 1.7, "high": 1.5, "medium": 1.25, "low": 1.0}
# Data-label tags in the review window as (text colour, background).
CHIP = {"SIMULATED": ("#c3ced6", "#2a3542"), "EXERCISE": ("#e1b164", "#34301f"), "REAL": ("#47c7da", "#173339"),
        "ASSUMPTION": ("#d8b25c", "#34301f"), "ILLUSTRATIVE": ("#a8b6c2", "#1c2a36"),
        "RULE OUTCOME": ("#a8b6c2", "#1c2a36"), "SOURCE": ("#47c7da", "#173339")}
DETECTOR_REASONS = 4
# Responder colours: arrives before the earliest line ETA, arrives after it, cannot go.
IN_TIME, LATE, UNAVAILABLE = "#47c7da", "#ec8a3c", "#7d8b97"
RESPONSE_SHAPE = {"aircraft": "square", "helicopter": "square", "ship": "circle", "drone": "diamond",
                  "hail": "ring"}
# List groups after the open incidents by level: quiet incidents, watched contacts, closed incidents.
GROUP_TITLES = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "quiet": "QUIET · BELOW MEDIUM",
                "watching": "WATCHING · LOW, NO INCIDENT", "closed": "CLOSED"}
# How often the panel checks the exercise replay clock.
FOLLOW_MS = 250


def age_text(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def countdown(item: dict) -> str | None:
    """mm:ss to the asset for a contact with a simulated ETA or a story ETA from its track, else None."""
    eta = item["observations"].get("eta_min")
    if eta is None or (item.get("eta_start_min") is None and not item.get("story")):
        return None
    seconds = max(0, int(eta * 60))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def proximity_text(item: dict) -> str:
    """Where the contact is relative to the asset, as one short phrase."""
    observations = item["observations"]
    if observations.get("in_corridor"):
        return "In corridor"
    clock = countdown(item)
    if clock is not None:
        return "At the asset" if clock == "00:00" else f"ETA {clock}"
    if observations.get("distance_nm") is not None:
        return f"{observations['distance_nm']:.1f} nm off"
    return ""


def badges(item: dict, incident: dict | None) -> list[tuple[str, str]]:
    """Short flags for a card as (text, kind); kind "warn" is drawn in amber, "note" muted."""
    found = []
    if incident and incident.get("needs_review_again"):
        found.append(("⚠ Review again", "warn"))
    if incident and incident.get("suggest_close"):
        found.append((f"Quiet {QUIET_CLOSE_S // 60} min · close?", "note"))
    if item["observations"].get("spoof_signs"):  # a lone GPS glitch is a finding but not a spoofing sign
        found.append(("AIS spoofing?", "warn"))
    relevance = item.get("relevance") or {}
    if relevance.get("small"):
        found.append(("Small craft · cap lifted" if relevance.get("exception") else "Small craft · capped Low", "note"))
    return found


def clip(text: str, font: tkfont.Font, width: int) -> str:
    """The text cut with an ellipsis to fit ``width`` pixels on one line."""
    if font.measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle].rstrip() + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


def nearest_point(lat: float, lon: float, path) -> tuple[float, float] | None:
    """Closest point on a short polyline, in a local flat approximation."""
    best, best_distance = None, float("inf")
    scale = math.cos(math.radians(lat))
    for (a_lat, a_lon), (b_lat, b_lon) in zip(path, path[1:]):
        ax, ay = (a_lon - lon) * scale, a_lat - lat
        dx, dy = (b_lon - a_lon) * scale, b_lat - a_lat
        length = dx * dx + dy * dy
        fraction = 0.0 if not length else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        x, y = ax + fraction * dx, ay + fraction * dy
        if x * x + y * y < best_distance:
            best_distance, best = x * x + y * y, (lat + y, lon + x / scale)
    return best


def recolour(widget, background: str) -> None:
    """Set the background of a row's plain Tk widgets and the corners of its CustomTkinter ones."""
    for child in widget.winfo_children():
        if isinstance(child, ctk.CTkBaseClass):
            child.configure(bg_color=background)
            if isinstance(child, ctk.CTkFrame):
                recolour(child, background)
        elif isinstance(child, (tk.Frame, tk.Label)) and not getattr(child, "keep_colour", False):
            child.configure(bg=background)
            recolour(child, background)


class AlertBoard:
    """The docked incident queue, its live countdowns, the review window and the map layer."""

    def __init__(self, app, panel):
        import run_gui as ui
        self.app, self.panel, self.ui = app, panel, ui
        self.items = build_board(app.scenario, app.alerts)
        self.by_id = {item["id"]: item for item in self.items}
        # The board follows the exercise replay clock; its countdowns start at the exercise alert.
        self.replay = Replay(self.items, app.scenario, app.alert["t"])
        self.replay.seek(app.position_s)
        self.exercise_seen = "New"
        self.selected: str | None = None
        self.hovered: str | None = None
        self.level_filter: str | None = None
        self.show_closed = False
        self.show_watching = False
        self.evidence_leads = []
        self.show_reviewed_evidence = tk.BooleanVar(app.root, value=False)
        self.evidence_page = 0
        self.evidence_status = "Waiting for satellite comparisons"
        self.evidence_signature = None
        self.history_signature = None
        self.history_lead_count = 0
        self.show_demo_alerts = tk.BooleanVar(
            app.root, value=app.tools.settings.get("show_demo_alerts", True) is True)
        self.sort_mode = tk.StringVar(app.root, value="Severity")
        self.cards: dict[str, dict] = {}
        self.wrap = 230
        self.reason_font = tkfont.Font(root=app.root, family=SANS, size=10)
        self.meta_font = tkfont.Font(root=app.root, family=SANS, size=9)
        self.name_font = tkfont.Font(root=app.root, family=SANS, size=11, weight="bold")
        self.timer_font = tkfont.Font(root=app.root, family=MONO, size=9, weight="bold")
        self.tag_font = tkfont.Font(root=app.root, family=SANS, size=7, weight="bold")
        self.halos: list[tuple[int, float, float]] = []
        self.pulse = False
        self.flashing: dict[str, str] = {}
        app.alert_board = self
        self.dialog = ReviewDialog(self)
        self._build()
        self.relayout()
        self.timer = app.root.after(1000, self.tick)
        self.follower = app.root.after(FOLLOW_MS, self.follow)
        app.root.bind("<Escape>", self.dialog.escape, add="+")

    # ----- building -------------------------------------------------------------------
    def _build(self):
        ui, app, panel = self.ui, self.app, self.panel
        head = tk.Frame(panel, bg=ui.CARD)
        head.pack(fill="x", padx=(16, 12), pady=(14, 0))
        # Buttons first, so a narrow panel squeezes the labels, not the buttons.
        close = ctk.CTkButton(head, text="", image=app.tools.icons.get("close"), command=app.tools.toggle_alerts,
                              width=30, height=30, fg_color="transparent", hover_color=ui.HOVER)
        close.pack(side="right")
        app.tools.style_button(close, "Hide incidents")
        restart = ctk.CTkButton(head, text="", image=app.tools.icons.get("refresh"), command=self.restart,
                                width=30, height=30, fg_color="transparent", hover_color=ui.HOVER)
        restart.pack(side="right", padx=2)
        app.tools.style_button(restart, "Reset incidents and decisions at this replay time")
        tk.Label(head, text="Incidents", bg=ui.CARD, fg=ui.INK, font=(SANS, 15, "bold")).pack(side="left")
        tk.Label(head, text="REPLAY", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 7, "bold"), padx=5,
                 highlightthickness=1, highlightbackground=ui.LINE).pack(side="left", padx=(8, 0), pady=(3, 0))
        self.clock = tk.Label(head, text=self.stamp(self.replay.now), bg=ui.CARD, fg=ui.AMBER, font=(MONO, 9, "bold"))
        self.clock.pack(side="left", padx=(6, 0), pady=(3, 0))
        app.tools.attach_tooltip(self.clock, "Replay time: incidents follow the exercise replay (Play or the slider)")

        self.demo_switch = ctk.CTkCheckBox(
            panel, text="Show fictional / simulated alerts", variable=self.show_demo_alerts,
            command=self.toggle_demo_alerts, font=ctk.CTkFont(SANS, 12),
            checkbox_width=16, checkbox_height=16, height=26)
        self.demo_switch.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(panel, text="Satellite / AIS review leads appear below.\n"
                 "Live AIS alone does not establish a threat.",
                 bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9), justify="left",
                 wraplength=250).pack(fill="x", padx=16, pady=(4, 6))

        row = tk.Frame(panel, bg=ui.CARD)
        row.pack(fill="x", padx=(16, 12), pady=(2, 0))
        self.summary = tk.Label(row, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 10), anchor="w")
        self.summary.pack(side="left")
        self.clear_filter = tk.Label(row, text="show all", bg=ui.CARD, fg=ui.INK, font=(SANS, 10, "underline"),
                                     cursor="hand2")
        self.clear_filter.bind("<Button-1>", lambda _event: self.set_filter(None))
        sort = ctk.CTkOptionMenu(row, values=list(SORTS), variable=self.sort_mode, width=124, height=24,
            command=lambda _value: self.relayout(top=True), fg_color=ui.CARD, button_color=ui.CARD,
            button_hover_color=ui.HOVER, text_color=ui.MUTED, font=ctk.CTkFont(SANS, 11),
            dropdown_font=ctk.CTkFont(SANS, 12), anchor="e")
        sort.pack(side="right")
        app.tools.attach_tooltip(sort, "Sort the incidents")

        strip = tk.Frame(panel, bg=ui.CARD)
        strip.pack(fill="x", padx=12, pady=(10, 0))
        self.tiles = {}
        for index, level in enumerate(LEVELS):
            strip.columnconfigure(index * 2, weight=1, uniform="strip")
            if index:
                tk.Frame(strip, bg=ui.LINE, width=1).grid(row=0, column=index * 2 - 1, sticky="ns", pady=6)
            cell = tk.Frame(strip, bg=ui.CARD, cursor="hand2")
            cell.grid(row=0, column=index * 2, sticky="nsew")
            line = tk.Frame(cell, bg=ui.CARD)
            line.pack(pady=(4, 0))
            code = tk.Label(line, text="WATCH" if level == "low" else CODES[level], bg=ui.CARD, fg=ui.MUTED,
                            font=(MONO, 9), cursor="hand2")
            code.pack(side="left")
            count = tk.Label(line, text="0", bg=ui.CARD, fg=STYLE[level][0], font=(MONO, 12, "bold"), cursor="hand2")
            count.pack(side="left", padx=(5, 0))
            underline = tk.Frame(cell, bg=ui.CARD, height=2)
            underline.pack(fill="x", padx=12, pady=(5, 0))
            for widget in (cell, line, code, count, underline):
                widget.bind("<Button-1>", lambda _event, value=level: self.set_filter(value))
            app.tools.attach_tooltip(cell, "Show watched contacts: Low, not incidents" if level == "low"
                                     else f"Show {LEVEL_NAMES[level].lower()} incidents only")
            self.tiles[level] = (code, underline)
            self.tiles[level + "-count"] = count
        tk.Frame(panel, bg=ui.LINE, height=1).pack(fill="x", padx=12)

        footer = tk.Frame(panel, bg=ui.CARD)
        footer.pack(side="bottom", fill="x", padx=(16, 12), pady=(0, 10))
        tk.Frame(footer, bg=ui.LINE, height=1).pack(fill="x", pady=(0, 7))
        app.alert_counts_label = tk.Label(footer, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9),
                                          anchor="w", justify="left", wraplength=self.wrap + 50)
        app.alert_counts_label.pack(fill="x")

        self.list = ctk.CTkScrollableFrame(panel, fg_color=ui.CARD, corner_radius=0,
            scrollbar_button_color=ui.LINE, scrollbar_button_hover_color=ui.HOVER)
        self.list.pack(fill="both", expand=True, padx=(4, 4))
        self.history_frame = tk.Frame(self.list, bg=ui.CARD)
        self.refresh_history({'vessels': [], 'summary': {}, 'worker': {}}, relayout=False)
        self.evidence_frame = tk.Frame(self.list, bg=ui.CARD)
        self.refresh_evidence({'leads': [], 'reviews_checked': 0, 'reviews_pending': 0}, relayout=False)
        self.reports_frame = tk.Frame(self.list, bg=ui.CARD)
        self.refresh_reports(relayout=False)
        self.headers = {}
        for group, text in GROUP_TITLES.items():
            header = tk.Frame(self.list, bg=ui.CARD)
            title = tk.Label(header, text=text, bg=ui.CARD, fg=ui.MUTED, font=(SANS, 8, "bold"))
            title.pack(side="left", padx=(10, 0))
            count = tk.Label(header, text="", bg=ui.CARD, fg=ui.MUTED, font=(MONO, 8))
            count.pack(side="left", padx=(6, 0))
            tk.Frame(header, bg=ui.LINE, height=1).pack(side="bottom", fill="x", before=title)
            if group in ("closed", "watching"):
                toggle = self.toggle_closed if group == "closed" else self.toggle_watching
                for widget in (header, title, count):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _event, command=toggle: command())
            self.headers[group] = (header, count)
        self.empty = tk.Label(self.list, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 10),
                              justify="left", wraplength=self.wrap)
        for item in self.items:
            self._card(item)

    def refresh_history(self, packet, relayout=True):
        import json
        from argus.fleet_history import source_health
        # Cached data can stay unchanged while its source becomes stale.
        signature = json.dumps(packet, sort_keys=True)+source_health(packet.get('summary', {}))
        if signature == self.history_signature:
            return
        self.history_signature = signature
        self.history_lead_count = packet.get('summary', {}).get('review_required', 0)
        ui = self.ui
        for child in self.history_frame.winfo_children():
            child.destroy()
        summary = packet.get('summary', {})
        tk.Label(self.history_frame, text=f"FLEET HISTORY REVIEW · {self.history_lead_count}",
                 bg=ui.CARD, fg=ui.INK, font=(SANS, 10, 'bold')).pack(anchor='w', padx=10, pady=(12, 4))
        text = (f"{summary.get('checked_vessels', 0)} / {summary.get('total_vessels', 0)} recorded vessels checked\n"
                f"{summary.get('never_checked', 0)} never checked · {summary.get('new_evidence_pending', 0)} awaiting new evidence checks\n"
                + source_health(summary)+'\n'
                + packet.get('worker', {}).get('message', 'History inventory is loading.'))
        if not packet.get('inventory_complete'):
            text += '\nInventory is still loading; missing entries are not clean results.'
        tk.Label(self.history_frame, text=text, bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9),
                 wraplength=self.wrap, justify='left').pack(anchor='w', padx=10)
        for row in packet.get('vessels', []):
            result = row.get('result') or {}
            findings = [f for f in result.get('findings', []) if f.get('review_required')]
            text = (f"{result.get('name') or row['mmsi']} · {row['mmsi']}\nMotion history requires review\n"
                    f"Checked {row.get('checked_utc')} · derived assumption\n"
                    + '\n'.join(f['reason'] for f in findings[-2:]) + '\nOpen history evidence')
            tk.Button(self.history_frame, text=text, anchor='w', justify='left', wraplength=self.wrap,
                      bg=ui.CARD, fg=ui.INK, activebackground=ui.HOVER, activeforeground=ui.INK,
                      relief='flat', padx=10, pady=8, cursor='hand2',
                      command=lambda mmsi=row['mmsi']: self.app.satellite.open_fleet(mmsi)).pack(fill='x', padx=8, pady=4)
        tk.Button(self.history_frame, text='Open all vessel histories', bg=ui.CARD, fg=ui.INK,
                  relief='flat', cursor='hand2', command=lambda: self.app.satellite.open_fleet()).pack(anchor='w', padx=10, pady=6)
        if relayout:
            self.relayout()

    def refresh_evidence(self, result, relayout=True):
        """Real-image comparisons stay visible when the fictional queue is hidden."""
        import json
        signature = json.dumps(result, sort_keys=True)
        if signature == self.evidence_signature:
            return
        self.evidence_signature = signature
        self.evidence_leads = result.get('leads', [])
        self.evidence_status = (f"{result.get('reviews_checked', 0)} images checked · "
                                f"{result.get('reviews_pending', 0)} awaiting history check\n"
                                f"{result.get('image_contacts', 0)} image contacts · "
                                f"{result.get('images_without_ais', 0)} images without contemporaneous AIS\n"
                                f"{result.get('partial_analysis_images', 0)} images with incomplete detail review")
        self.evidence_page = min(self.evidence_page, max(0, (len(self.evidence_leads)-1)//50))
        self.paint_evidence()
        if relayout:
            self.relayout()

    def paint_evidence(self):
        from argus.satellite_disposition import OUTCOMES, CLOSED_OUTCOMES
        ui = self.ui
        for child in self.evidence_frame.winfo_children():
            child.destroy()
        tk.Label(self.evidence_frame, text=f"SATELLITE / AIS REVIEW · {len(self.evidence_leads)} leads",
                 bg=ui.CARD, fg=ui.INK, font=(SANS, 10, 'bold')).pack(anchor='w', padx=10, pady=(12, 4))
        tk.Label(self.evidence_frame, text=self.evidence_status, bg=ui.CARD, fg=ui.MUTED,
                 font=(SANS, 9), wraplength=self.wrap, justify='left').pack(anchor='w', padx=10)
        def refilter():
            self.evidence_page = 0
            self.paint_evidence()
            self.relayout(top=True)
        tk.Checkbutton(self.evidence_frame, text='Show reviewed outcomes', variable=self.show_reviewed_evidence,
                       command=refilter, bg=ui.CARD, fg=ui.INK, selectcolor=ui.CARD).pack(anchor='w', padx=10)
        visible = [r for r in self.evidence_leads if self.show_reviewed_evidence.get() or r.get('review_status') not in CLOSED_OUTCOMES]
        self.evidence_page = min(self.evidence_page, max(0, (len(visible)-1)//50))
        tk.Label(self.evidence_frame, text=f'{len(visible)} shown · analyst outcomes retain the original evidence',
                 bg=ui.CARD, fg=ui.MUTED, wraplength=self.wrap).pack(anchor='w', padx=10)
        start = self.evidence_page*50
        for lead in visible[start:start+50]:
            state = OUTCOMES.get(lead.get('review_status'), 'Unreviewed')
            if lead.get('review_status') == 'unreviewed':
                state = 'Unreviewed'
            if lead.get('evidence_changed'):
                state = 'Evidence changed · review again'
            text = (f"{lead['name']}" + (f" · {lead['mmsi']}" if lead.get('mmsi') else '') +
                    f"\n{lead['title']}\nImage {lead['acquired_utc']}\n"
                    f"{lead['source_label']} pixels · assumption · {state}\n{lead['reason']}\nOpen image evidence")
            tk.Button(self.evidence_frame, text=text, anchor='w', justify='left', wraplength=self.wrap,
                      bg=ui.CARD, fg=ui.INK, activebackground=ui.HOVER, activeforeground=ui.INK,
                      relief='flat', padx=10, pady=8, cursor='hand2',
                      command=lambda row=lead: self.open_evidence(row)).pack(fill='x', padx=8, pady=4)
            if lead.get('evidence_key'):
                def review(row=lead):
                    from desktop_evidence_review import EvidenceReview
                    EvidenceReview(self, row)
                tk.Button(self.evidence_frame, text='Record analyst outcome', command=review,
                          bg=ui.CARD, fg=ui.INK, relief='flat', cursor='hand2').pack(anchor='w', padx=18)
        if len(visible) > 50:
            controls = tk.Frame(self.evidence_frame, bg=ui.CARD)
            controls.pack(fill='x')
            def turn(delta):
                self.evidence_page += delta
                self.paint_evidence()
                self.relayout(top=True)
            for text, delta, enabled in [('Previous', -1, start > 0),
                                         ('Next', 1, start+50 < len(visible))]:
                tk.Button(controls, text=text, state='normal' if enabled else 'disabled',
                          command=lambda d=delta: turn(d)).pack(side='left', padx=8)

    def open_evidence(self, lead):
        satellite = self.app.satellite
        self.app.open_window('satellite')
        satellite.pending_contact = (lead['scene_id'], lead.get('contact_id'))

    def refresh_reports(self, relayout=True):
        """Analyst reports stay separate from the simulated Brain severity groups."""
        from desktop_reports import review_reports
        ui = self.ui
        self.report_cards = []
        for child in self.reports_frame.winfo_children():
            child.destroy()
        groups = self.app.vessel_reports.grouped()
        if groups:
            tk.Label(self.reports_frame, text=f"REPORTED VESSELS · {len(groups)}", bg=ui.CARD,
                     fg=ui.INK, font=(SANS, 10, "bold")).pack(anchor="w", padx=10, pady=(12, 6))
            for entries in groups:
                report = entries[-1]["report"]
                vessel = report["vessel"]
                text = (f"{vessel['name']} · {vessel['id']}\n{report['category']}\n"
                        f"{entries[-1]['sender']} · {vessel['label']} · {len(entries)} report(s)\nReview concern")
                card = tk.Button(self.reports_frame, text=text, anchor="w", justify="left",
                    wraplength=max(150, self.wrap), padx=10, pady=8, cursor="hand2",
                    bg=ui.CARD, fg=ui.INK, activebackground=ui.HOVER, activeforeground=ui.INK,
                    relief="flat", font=(SANS, 10), highlightthickness=1, highlightbackground=ui.LINE,
                    command=lambda found=entries: review_reports(self.app, found))
                card.pack(fill="x", padx=8, pady=(0, 6))
                self.report_cards.append(card)
        if relayout:
            self.relayout(top=True)

    def _card(self, item):
        """One card: a level stripe, then name and timer, one line of why, asset and status, flags."""
        ui = self.ui
        frame = tk.Frame(self.list, bg=ui.CARD, cursor="hand2")
        rule = tk.Frame(frame, bg=ui.LINE, height=1)
        rule.keep_colour = True
        rule.pack(side="bottom", fill="x")
        stripe = tk.Frame(frame, bg=ui.CARD, width=4)
        stripe.keep_colour = True
        stripe.pack(side="left", fill="y", padx=(6, 0), pady=8)
        body = tk.Frame(frame, bg=ui.CARD)
        body.pack(side="left", fill="both", expand=True, padx=(10, 10), pady=(8, 9))
        top = tk.Frame(body, bg=ui.CARD)
        top.pack(fill="x")
        name = tk.Label(top, text=item["name"], bg=ui.CARD, fg=ui.INK, font=self.name_font, anchor="w")
        name.pack(side="left")
        tag = tk.Label(top, text=source(item)["tag"], bg=ui.CARD, fg=ui.MUTED, font=(SANS, 7, "bold"))
        tag.pack(side="right")
        self.app.tools.attach_tooltip(tag, source(item)["text"])
        eta = tk.Label(top, bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9))
        eta.pack(side="right", padx=(0, 8))
        reason = tk.Label(body, text="", bg=ui.CARD, fg=SECONDARY, font=self.reason_font, anchor="w")
        reason.pack(fill="x", pady=(2, 0))
        bottom = tk.Frame(body, bg=ui.CARD)
        bottom.pack(fill="x", pady=(3, 0))
        status = tk.Label(bottom, bg=ui.CARD, fg=ui.MUTED, font=self.meta_font, anchor="w")
        status.pack(side="left")
        age = tk.Label(bottom, bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9))
        age.pack(side="right")
        respond = tk.Label(body, text="", bg=ui.CARD, fg=ui.MUTED, font=self.meta_font, anchor="w")
        flags = tk.Frame(body, bg=ui.CARD)
        flag_labels = []
        for _ in range(3):
            label = tk.Label(flags, bg=ui.CARD, font=(SANS, 8, "bold"), padx=5, pady=1)
            label.keep_colour = True
            flag_labels.append(label)
        card = {"item": item, "frame": frame, "stripe": stripe, "name": name, "age": age, "eta": eta,
                "reason": reason, "status": status, "flags": flags, "flag_labels": flag_labels,
                "respond": respond, "bottom": bottom, "texts": {}, "background": ui.CARD}
        for widget in (frame, stripe, body, top, name, tag, age, reason, bottom, eta, status, respond, flags,
                       *flag_labels):
            widget.bind("<Button-1>", lambda _event, key=item["id"]: self.open(key, centre=True))
            widget.bind("<Enter>", lambda _event, key=item["id"]: self.hover(key, True), add="+")
            widget.bind("<Leave>", lambda _event, key=item["id"]: self.hover(key, False), add="+")
        self.cards[item["id"]] = card
        self.paint(item["id"])

    # ----- state ----------------------------------------------------------------------
    @property
    def tracker(self):
        return self.replay.tracker

    @property
    def recipients(self) -> dict[str, str]:
        return self.replay.recipients

    @property
    def history(self) -> dict[str, list[tuple[int, str]]]:
        """Per contact: (replay time, text) for Brain's incident events and the analyst's decisions."""
        return self.replay.log

    def incident(self, identifier: str) -> dict | None:
        return self.tracker.incident(self.by_id[identifier])

    def status(self, identifier: str) -> str:
        """Incident status, "Rejected" once closed, or "Watching" for a Low contact without an incident."""
        return self.tracker.status(self.by_id[identifier]) or "Watching"

    def response(self, identifier: str) -> dict | None:
        """Who can reach an open incident at this replay time (``argus.responders``), else None."""
        if self.status(identifier) in ("Rejected", "Watching") or self.group(identifier) == "hidden":
            return None
        return self.replay.responses.get(identifier)

    def response_line(self, identifier: str) -> tuple[str, bool] | None:
        result = self.response(identifier)
        return responders.summary_line(result) if result else None

    def toggle_storm(self) -> None:
        """Switch the exercise wind between normal and storm and score the current replay time again."""
        def action():
            self.replay.storm = not self.replay.storm
            return self.replay.refresh()
        wind = self.replay.fleet["wind"]["normal_kn" if self.replay.storm else "storm_kn"]
        self.rescore(action, f"Exercise wind {wind:g} kn"
                     + (" · drones available" if self.replay.storm else " · storm: drones grounded"))

    def send(self, identifier: str, asset_id: str) -> None:
        """Send an asset to the incident: a simulated human decision, logged, never transmitted."""
        if hasattr(self.app, 'require_tool') and not self.app.require_tool('response.review'):
            return
        item = self.by_id[identifier]
        self.rescore(lambda: self.replay.send(item, asset_id), f"Sent {asset_id} to {item['name']} (simulated)")

    def recall(self, identifier: str, asset_id: str) -> None:
        if hasattr(self.app, 'require_tool') and not self.app.require_tool('response.review'):
            return
        item = self.by_id[identifier]
        self.rescore(lambda: self.replay.recall(item, asset_id), f"Recalled {asset_id} from {item['name']}")

    def rescore(self, action, text: str) -> None:
        """Run a change that scores the board again at this replay time; repaint and announce what rose."""
        before = self.snapshot()
        try:
            events = action()
        except (KeyError, ValueError) as error:
            self.app.map_status_label.configure(text=f"{self.stamp(self.replay.now)} · {error.args[0]}")
            return
        after = self.snapshot()
        for identifier in {key for key in after if after[key] != before[key]} | set(events):
            self.paint(identifier)
        news = []
        for identifier, found in events.items():
            if {"raised", "opened"} & set(found):
                self.flash(identifier)
                news.append(f"{self.by_id[identifier]['name']} now {LEVEL_NAMES[self.incident(identifier)['level']]}"
                            + (": no responder in time" if (self.response(identifier) or {}).get("no_response_in_time")
                               else ""))
        self.relayout()
        self.app._draw_map()
        if self.dialog.item:
            self.dialog.refresh()
        self.app.map_status_label.configure(text=" · ".join([self.stamp(self.replay.now), text, *news[:3]]))

    def group(self, identifier: str) -> str:
        """critical/high/medium for an open incident, else quiet, watching, closed or hidden (not raised yet)."""
        item = self.by_id[identifier]
        if not self.show_demo_alerts.get():
            return "hidden"
        if not self.replay.present(item):
            return "hidden"
        incident = self.tracker.open_incident(item)
        if incident is not None:
            return incident["level"] if RANK[incident["level"]] >= OPEN_RANK else "quiet"
        return "closed" if self.tracker.incident(item) is not None else "watching"

    def age_min(self, item: dict) -> float:
        """Minutes since the contact was raised, on the replay clock."""
        return (self.replay.now - self.replay.appear_s(item)) / 60

    def stamp(self, t: int) -> str:
        return "T+" + self.ui.clock(t)[:5] if t >= 0 else "T−" + self.ui.clock(-t)[:5]

    def counts(self) -> dict[str, int]:
        states = [self.status(item["id"]) for item in self.items if self.group(item["id"]) != "hidden"]
        return {state: states.count(state) for state in (*STATUSES, "Watching")}

    def decide(self, identifier: str, status: str, text: str, reason: str | None = None,
               to: str | None = None) -> None:
        """Record an analyst decision on the vessel's open incident through ``argus.incidents``."""
        if hasattr(self.app, 'require_tool') and not self.app.require_tool('alert.review'):
            return
        item = self.by_id[identifier]
        if self.tracker.open_incident(item) is None:
            return
        before = self.snapshot()
        self.replay.decide(item, status, text, reason, to)
        self.sync_exercise(item, status)
        after = self.snapshot()
        for other in {key for key in after if after[key] != before[key]} - {identifier}:
            self.paint(other)  # a closed incident frees its assets for the others
        self.changed(identifier)

    def mark_reviewed(self, identifier: str) -> None:
        if self.status(identifier) != "New":
            return
        item = self.by_id[identifier]
        self.replay.decide(item, "Reviewed", "Opened for review")
        self.sync_exercise(item, "Reviewed")
        self.changed(identifier, redraw=False)

    def withdraw(self, identifier: str) -> None:
        """Take back an escalation; the incident stays open as Reviewed."""
        self.decide(identifier, "Reviewed", "Escalation withdrawn; reviewing again")

    def sync_exercise(self, item: dict, status: str) -> None:
        """Mirror the exercise incident's review status to the exercise replay's status menu."""
        if not item.get("exercise") or status not in ("New", "Reviewed", "Acknowledged"):
            return
        tools, alert_id = self.app.tools, item["alert"]["id"]
        if status == "Acknowledged" and tools.review_values.get(alert_id) == "New":
            self.exercise_seen = "Reviewed"
            tools.set_alert_status(alert_id, "Reviewed")
        self.exercise_seen = status
        tools.set_alert_status(alert_id, status)

    def changed(self, identifier: str, redraw: bool = True) -> None:
        self.paint(identifier)
        self.relayout()
        if redraw:
            self.app._draw_map()
        if self.dialog.item and self.dialog.item["id"] == identifier:
            self.dialog.refresh()

    def refresh_statuses(self) -> None:
        """Called when the exercise replay's status menu changes outside the queue."""
        for item in self.items:
            if not item.get("exercise"):
                continue
            value = self.app.tools.review_values.get(item["alert"]["id"])
            if value != self.exercise_seen and value in ("New", "Reviewed", "Acknowledged"):
                self.exercise_seen = value
                if self.tracker.open_incident(item) is not None and self.status(item["id"]) != value:
                    self.replay.decide(item, value, f"{value} in the exercise replay")
            self.paint(item["id"])
            if self.dialog.item and self.dialog.item["id"] == item["id"]:
                self.dialog.refresh()
        self.update_counts()

    # ----- list -----------------------------------------------------------------------
    def paint(self, identifier: str) -> None:
        card = self.cards[identifier]
        item, ui = card["item"], self.ui
        incident = self.incident(identifier)
        level = item["assessment"]["level"]
        status = self.status(identifier)
        closed = status == "Rejected"
        background = ROW_SELECTED if identifier == self.selected else ROW_HOVER if identifier == self.hovered else ui.CARD
        if identifier in self.flashing:
            background = card["background"]
        if card["background"] != background:
            card["frame"].configure(bg=background)
            recolour(card["frame"], background)
            card["background"] = background
        card["stripe"].configure(bg=ui.LINE if closed else STYLE[level][0])
        card["name"].configure(fg=ui.MUTED if closed else ui.INK)
        width = self.wrap + 24
        card["reason"].configure(text=clip(item["title"], self.reason_font, width))
        # Status first, then the peak, then the asset: clipping only ever shortens the asset name.
        if status == "Escalated" and identifier in self.recipients:
            parts = [f"Escalated · {self.recipients[identifier]}"]
        elif closed and incident and incident.get("status_reason"):
            parts = [f"Rejected · {incident['status_reason']}"]
        else:
            parts = [status]
        parts.append(source(item)["short"])  # with the BRAIN/SIM tag: "Brain · from track" or "SIM · hand-written"
        if incident and not closed and RANK[incident["peak_level"]] > RANK[incident["level"]]:
            parts.append(f"peak {LEVEL_NAMES[incident['peak_level']]}")
        parts.append(item["line_name"])
        card["status"].configure(text=clip(" · ".join(parts), self.meta_font, width - 50),
                                 fg=ui.INK if status in ("New", "Escalated") else ui.MUTED)
        line = self.response_line(identifier)
        if line:
            text, warn = line
            card["respond"].configure(text=clip(text, self.meta_font, width),
                                      fg=STYLE["critical"][0] if warn else IN_TIME)
            card["respond"].pack(fill="x", pady=(3, 0), after=card["bottom"])
        else:
            card["respond"].pack_forget()
        flags = badges(item, incident if not closed else None)
        for index, label in enumerate(card["flag_labels"]):
            if index < len(flags):
                text, kind = flags[index]
                colour = STYLE["medium"] if kind == "warn" else (ui.MUTED, ui.CONTROL)
                label.configure(text=text, fg=colour[0], bg=colour[1])
                label.pack(side="left", padx=(0, 4))
            else:
                label.pack_forget()
        if flags and not closed:
            card["flags"].pack(fill="x", pady=(5, 0))
        else:
            card["flags"].pack_forget()
        card["texts"].pop("eta", None)
        self.update_live(identifier)

    def timer_text(self, item: dict) -> tuple[str, bool]:
        """The card's timer and whether it is a live countdown."""
        if item.get("exercise"):
            remaining = self.app._remaining()
            if remaining:
                return f"ETA {self.ui.clock(remaining[0])}", True
            return "before alert", False
        return proximity_text(item), countdown(item) is not None

    def update_live(self, identifier: str | None = None) -> None:
        for key in [identifier] if identifier else self.cards:
            card = self.cards[key]
            item = card["item"]
            texts = card["texts"]
            age = "replay" if item.get("exercise") else age_text(self.age_min(item))
            eta, ticking = self.timer_text(item)
            ticking = ticking and self.status(key) != "Rejected"
            if texts.get("age") != age:
                card["age"].configure(text=age)
                texts["age"] = age
            if texts.get("eta") != (eta, ticking):
                colour = STYLE[item["assessment"]["level"]][0] if ticking else self.ui.MUTED
                card["eta"].configure(text=eta, fg=colour, font=(MONO, 9, "bold") if ticking else (SANS, 9))
                texts["eta"] = (eta, ticking)
                # The name gives way to the timer and the SIM/EXERCISE tag on a narrow panel.
                room = (self.wrap + 30 - (self.timer_font if ticking else self.meta_font).measure(eta) - 16
                        - self.tag_font.measure(source(item)["tag"]))
                card["name"].configure(text=clip(item["name"], self.name_font, max(60, room)))

    def hover(self, identifier: str, inside: bool) -> None:
        frame = self.cards[identifier]["frame"]
        if not inside:
            x, y = frame.winfo_pointerxy()
            if (frame.winfo_rootx() <= x < frame.winfo_rootx() + frame.winfo_width()
                    and frame.winfo_rooty() <= y < frame.winfo_rooty() + frame.winfo_height()):
                return
        previous = self.hovered
        self.hovered = identifier if inside else (None if previous == identifier else previous)
        for key in {previous, self.hovered} - {None}:
            if key in self.cards:
                self.paint(key)

    def matches_filter(self, identifier: str) -> bool:
        group = self.group(identifier)
        if self.level_filter is None:
            return True
        if self.level_filter == "low":
            return group == "watching"
        return group == self.level_filter

    def visible_items(self) -> list[dict]:
        """Contacts drawn on the map: everything raised by now and not closed that passes the level filter."""
        return [item for item in self.items if self.group(item["id"]) not in ("closed", "hidden")
                and self.matches_filter(item["id"])]

    def _order(self, identifier: str) -> tuple:
        incident = self.incident(identifier)
        return (not (incident and incident.get("needs_review_again")), sort_key(self.by_id[identifier]))

    def relayout(self, top: bool = False) -> None:
        ui = self.ui
        for widget in self.list.winfo_children():
            widget.pack_forget()
        self.history_frame.pack(fill="x", pady=(0, 12))
        self.evidence_frame.pack(fill="x", pady=(0, 12))
        if self.app.vessel_reports.entries:
            self.reports_frame.pack(fill="x", pady=(0, 12))
        groups = {item["id"]: self.group(item["id"]) for item in self.items}
        first = True

        def header(key, count):
            nonlocal first
            frame, label = self.headers[key]
            label.configure(text=str(count))
            frame.pack(fill="x", pady=(4 if first else 14, 0))
            first = False

        def card(item):
            nonlocal first
            self.cards[item["id"]]["frame"].pack(fill="x")
            first = False

        def members(group):
            return sorted((item for item in self.items if groups[item["id"]] == group
                           and self.matches_filter(item["id"])), key=lambda item: self._order(item["id"]))

        mode = self.sort_mode.get()
        shown = 0
        if mode == "Severity":
            for group in ("critical", "high", "medium", "quiet"):
                found = members(group)
                if found:
                    header(group, len(found))
                    for item in found:
                        card(item)
                    shown += len(found)
        else:
            def time_key(item):
                observations = item["observations"]
                eta = 0.0 if observations.get("in_corridor") else observations.get("eta_min")
                return (eta if eta is not None else 1e9, sort_key(item))
            key = time_key if mode == "Time to asset" else (lambda item: (item.get("raised_min_ago", 0), sort_key(item)))
            found = sorted((item for group in ("critical", "high", "medium", "quiet") for item in members(group)), key=key)
            for item in found:
                card(item)
            shown = len(found)
        if not shown and self.level_filter != "low" and not self.app.vessel_reports.entries and not self.evidence_leads and not self.history_lead_count:
            self.empty.configure(text=("Fictional / simulated alerts hidden.\n"
                                      "No satellite / AIS review leads loaded yet.")
                                 if not self.show_demo_alerts.get() else
                                 ("No open incidents at this level." if self.level_filter else "No open incidents."),
                                 wraplength=self.wrap)
            self.empty.pack(fill="x", padx=10, pady=16)
        watching = members("watching")
        if watching:
            expanded = self.show_watching or self.level_filter == "low"
            header("watching", f"{len(watching)} · {'hide' if expanded else 'show'}")
            if expanded:
                for item in watching:
                    card(item)
        closed = members("closed")
        if closed:
            header("closed", f"{len(closed)} · {'hide' if self.show_closed else 'show'}")
            if self.show_closed:
                for item in closed:
                    card(item)
        counts = {level: 0 for level in LEVELS}
        for group in groups.values():
            if group in counts:
                counts[group] += 1
            elif group == "watching":
                counts["low"] += 1
        for level in LEVELS:
            code, underline = self.tiles[level]
            active = self.level_filter == level
            self.tiles[level + "-count"].configure(text=str(counts[level]))
            code.configure(fg=ui.INK if active else ui.MUTED)
            underline.configure(bg=STYLE[level][0] if active else ui.CARD)
        if self.level_filter:
            self.clear_filter.pack(side="left", padx=(4, 0))
        else:
            self.clear_filter.pack_forget()
        self.update_counts()
        canvas = getattr(self.list, "_parent_canvas", None)
        if canvas is not None and top:
            canvas.yview_moveto(0)
        elif canvas is not None:
            self.app.root.after_idle(self.clamp_scroll)

    def clamp_scroll(self) -> None:
        """Keep the view inside the queue after it shrinks, so it never shows empty space."""
        canvas = getattr(self.list, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        content, view = self.list.winfo_reqheight(), canvas.winfo_height()
        limit = max(0, content - view)
        if canvas.canvasy(0) > limit:
            canvas.yview_moveto(limit / max(content, 1))

    def update_counts(self) -> None:
        counts = self.counts()
        open_count = sum(counts[state] for state in STATUSES if state != "Rejected")
        if self.level_filter == "low":
            self.summary.configure(text=f"{counts['Watching']} watching ·")
        elif self.level_filter:
            shown = sum(1 for item in self.items if self.group(item["id"]) == self.level_filter)
            self.summary.configure(text=f"{shown} {LEVEL_NAMES[self.level_filter].lower()} ·")
        else:
            self.summary.configure(text=f"{open_count} open · {counts['Escalated']} escalated")
        self.app.alert_counts_label.configure(
            text=f"{counts['New']} new · {counts['Reviewed']} reviewed · {counts['Acknowledged']} acknowledged · "
                 f"{counts['Escalated']} escalated · {counts['Rejected']} rejected\n"
                 "Brain: {} contacts scored in {:.0f} ms at this replay step".format(*self.replay.scored))
        if not self.show_demo_alerts.get():
            self.app.alert_counts_label.configure(text="Fictional / simulated alerts hidden")
        from argus.satellite_disposition import CLOSED_OUTCOMES
        unresolved = sum(r.get('review_status') not in CLOSED_OUTCOMES for r in self.evidence_leads)
        self.app.alert_counts_label.configure(text=self.app.alert_counts_label.cget('text') +
            f"\n{len(self.evidence_leads)} satellite / AIS leads · {unresolved} awaiting review")
        if self.history_lead_count:
            self.app.alert_counts_label.configure(text=self.app.alert_counts_label.cget('text') +
                f"\n{self.history_lead_count} vessel histories require review")
        if self.app.vessel_reports.entries:
            self.app.alert_counts_label.configure(text=self.app.alert_counts_label.cget("text") +
                f"\n{len(self.app.vessel_reports.grouped())} reported vessels · analyst review")

    def toggle_demo_alerts(self) -> None:
        """Hide the replay queue and markers, retaining decisions and analyst reports."""
        self.app.tools.settings["show_demo_alerts"] = self.show_demo_alerts.get()
        self.app.tools.schedule_save()
        if not self.show_demo_alerts.get():
            self.dialog.close()
            self.selected = self.hovered = None
            self.level_filter = None
        self.relayout(top=True)
        self.app._draw_map()

    def set_filter(self, level: str | None) -> None:
        self.level_filter = None if level == self.level_filter else level
        self.relayout(top=True)
        self.app._draw_map()

    def toggle_closed(self) -> None:
        self.show_closed = not self.show_closed
        self.relayout()

    def toggle_watching(self) -> None:
        if self.level_filter == "low":
            self.set_filter(None)
            return
        self.show_watching = not self.show_watching
        self.relayout()

    def set_width(self, pixels: int) -> None:
        wrap = max(150, pixels - 92)
        if pixels <= 0 or wrap == self.wrap:
            return
        self.wrap = wrap
        for frame in (self.history_frame, self.evidence_frame):
            for widget in frame.winfo_children():
                if isinstance(widget, (tk.Label, tk.Button)):
                    widget.configure(wraplength=wrap)
        for card in self.report_cards:
            card.configure(wraplength=wrap)
        for identifier in self.cards:
            self.paint(identifier)
        self.empty.configure(wraplength=wrap)
        self.app.alert_counts_label.configure(wraplength=wrap + 50)

    def scroll_to(self, identifier: str) -> None:
        card = self.cards.get(identifier)
        canvas = getattr(self.list, "_parent_canvas", None)
        if not card or canvas is None or not card["frame"].winfo_manager():
            return
        self.list.update_idletasks()
        total = max(1, self.list.winfo_height())
        top, height = card["frame"].winfo_y(), card["frame"].winfo_height()
        first, last = canvas.yview()
        if top < first * total or top + height > last * total:
            canvas.yview_moveto(max(0.0, (top - 40) / total))

    def flash(self, identifier: str, count: int = 6) -> None:
        """Briefly tint a card whose incident has just opened or risen."""
        card = self.cards[identifier]
        previous = self.flashing.pop(identifier, None)
        if previous and count == 6:
            self.app.root.after_cancel(previous)
        if count <= 0:
            card["background"] = None
            self.paint(identifier)
            return
        background = STYLE[card["item"]["assessment"]["level"]][1] if count % 2 else self.ui.CARD
        card["frame"].configure(bg=background)
        recolour(card["frame"], background)
        card["background"] = background
        self.flashing[identifier] = self.app.root.after(300, lambda: self.flash(identifier, count - 1))

    # ----- actions --------------------------------------------------------------------
    def open(self, identifier: str, reveal: bool = True, centre: bool = False) -> None:
        """Select a contact and show its review window; ``centre`` (a card click) centres the map on it."""
        if hasattr(self.app, 'require_tool') and not self.app.require_tool('alert.review'):
            return
        item = self.by_id.get(identifier)
        if not item:
            return
        previous, self.selected = self.selected, identifier
        if previous in self.cards and previous != identifier:
            self.paint(previous)
        self.paint(identifier)
        self.mark_reviewed(identifier)
        self.dialog.show(item)
        self.scroll_to(identifier)
        if reveal:
            self.reveal(item, centre=centre)
        else:
            self.app._draw_map()
        self.app.map_status_label.configure(text=self.describe(identifier))

    def deselect(self) -> None:
        previous, self.selected = self.selected, None
        if previous in self.cards:
            self.paint(previous)
        self.app._draw_map()

    def reveal(self, item: dict, fit: bool = False, centre: bool = False) -> None:
        """Bring the contact into the map area left of the review window; centre it or fit its track when asked."""
        app, ui = self.app, self.ui
        if hasattr(app, "ais_tracker"):
            app.ais_tracker.follow.set(False)
        width, height = app._map_size
        if width < 100 or height < 100:
            return
        scaling = ctk.ScalingTracker.get_widget_scaling(app.map)
        right = self.dialog.covered_width() if self.dialog.visible else 70 * scaling
        left = 16 * scaling
        free = max(120, width - right - left)
        target_x, target_y = left + free / 2, height / 2 - 20 * scaling
        maximum = ui.MAX_IMAGERY_ZOOM if app.map_mode.get() == ui.ONLINE_MAP else ui.MAX_MAP_ZOOM
        if fit:
            points = list(item["track"]) + [(item["lat"], item["lon"])]
            nearest = nearest_point(item["lat"], item["lon"], line_path(item["line_id"], app.scenario))
            if nearest:
                points.append(nearest)
            result = self.response(item["id"])
            shown = result and (result["assigned"] or result["best"])
            if shown and shown["meet"]:
                points += [(shown["lat"], shown["lon"]), tuple(shown["meet"])]  # the responder's route too
            for zoom in range(min(maximum, 10), 4, -1):
                xs, ys = zip(*(ui.geo_to_world(lat, lon, zoom) for lat, lon in points))
                if max(xs) - min(xs) <= free - 140 * scaling and max(ys) - min(ys) <= height - 240 * scaling:
                    break
            app.map_zoom = zoom
            centre_x, centre_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        else:
            x, y = app._project(item["lat"], item["lon"])
            inside = left + 40 <= x <= width - right - 40 and 60 <= y <= height - 140
            if inside and app.map_zoom >= 6 and not centre:
                app._draw_map()
                return
            app.map_zoom = max(app.map_zoom, min(7, maximum))
            centre_x, centre_y = ui.geo_to_world(item["lat"], item["lon"], app.map_zoom)
        centre = (centre_x - (target_x - width / 2), centre_y - (target_y - height / 2))
        app._change_map_center(ui.world_to_geo(*centre, app.map_zoom))

    def restart(self) -> None:
        """Clear decisions and incidents and rebuild the board at the current replay time."""
        self.items = build_board(self.app.scenario, self.app.alerts)
        self.by_id = {item["id"]: item for item in self.items}
        for item in self.items:
            self.cards[item["id"]]["item"] = item
            self.cards[item["id"]]["texts"].clear()
        storm = self.replay.storm
        self.replay = Replay(self.items, self.app.scenario, self.app.alert["t"])
        self.replay.storm = storm  # the wind is an exercise setting, not a decision
        self.replay.seek(self.app.position_s)
        self.follow_exercise()
        tools = self.app.tools
        for identifier in tools.review_values:
            tools.review_values[identifier] = "New"
            tools.alert_statuses[identifier].set("New")
        self.exercise_seen = "New"
        self.selected = None
        self.dialog.close()
        for identifier in self.cards:
            self.paint(identifier)
        self.relayout(top=True)
        self.app._draw_map()
        self.app.map_status_label.configure(text="Incidents restarted at this replay time · decisions reset")

    def snapshot(self) -> dict[str, tuple]:
        return {item["id"]: (self.group(item["id"]), item["assessment"]["level"], item["title"],
                             self.response_line(item["id"])) for item in self.items}

    def follow_exercise(self) -> None:
        """Put the exercise contact at its AIS fix for the replay time (it keeps its last fix in a gap)."""
        for item in self.items:
            if not item.get("exercise"):
                continue
            track = self.app.vessel["track"]
            fix = self.ui.fix_at(track, self.replay.now)
            if fix:
                item.update(lat=fix["lat"], lon=fix["lon"], cog_deg=fix["cog_deg"], sog_kn=fix["sog_kn"])
            item["track"] = [(point["lat"], point["lon"]) for point in track if point["t"] <= self.replay.now][-40:]

    def advance(self, t: float) -> dict[str, list[str]]:
        """Move the board to replay time ``t``: re-score, fold into incidents, repaint and flash what changed."""
        before = self.snapshot()
        events, rewound = self.replay.seek(t)
        self.follow_exercise()
        after = self.snapshot()
        touched = {key for key in after if after[key] != before[key]} | set(events)
        self.clock.configure(text=self.stamp(self.replay.now))
        for identifier in (self.cards if rewound else touched):
            self.paint(identifier)
        if rewound or touched:
            self.relayout()
        if self.selected and self.group(self.selected) == "hidden":
            self.dialog.close()
        for identifier, found in events.items():
            if {"opened", "raised", "review_again"} & set(found):
                self.flash(identifier)
        news = [f"{self.by_id[i]['name']} " + ("incident opened" if "opened" in found else
                "review again" if "review_again" in found else "quiet: close?" if "quiet" in found
                else f"now {LEVEL_NAMES[self.incident(i)['level']]}") for i, found in events.items()]
        moving = any(item.get("story") and self.replay.present(item) for item in self.items)
        if rewound or touched or self.replay.assignments or moving:
            self.app._draw_map()  # sent assets and story vessels move with the replay clock
        if news:
            self.app.map_status_label.configure(text=f"{self.stamp(self.replay.now)} · " + " · ".join(news[:4]))
        if self.dialog.item and (rewound or self.dialog.item["id"] in touched):
            self.dialog.refresh()
        self.update_live()
        self.dialog.update_live()
        return events

    def follow(self) -> None:
        """Follow the exercise replay clock: Play, the timeline slider and jumps all move the board."""
        self.follower = None
        try:
            if int(self.app.position_s) != self.replay.now:
                self.advance(self.app.position_s)
        finally:
            self.follower = self.app.root.after(FOLLOW_MS, self.follow)

    def tick(self) -> None:
        self.timer = None
        try:
            self.pulse_halos()
        finally:
            self.timer = self.app.root.after(1000, self.tick)

    def close(self) -> None:
        for timer in [self.timer, self.follower, *self.flashing.values()]:
            if timer:
                try:
                    self.app.root.after_cancel(timer)
                except tk.TclError:
                    pass
        self.timer = self.follower = None
        self.flashing.clear()

    # ----- map ------------------------------------------------------------------------
    def draw(self) -> None:
        app, ui = self.app, self.ui
        self.halos = []
        layer = app.map_layers.get("Simulated alerts")
        if layer is None or not layer.get() or not self.show_demo_alerts.get():
            return
        width, height = app._map_size
        occupied: list[tuple[float, float, float, float]] = []
        exercise_shown = app.exercise_visible.get()
        items = [item for item in self.visible_items() if not (item.get("exercise") and exercise_shown)]
        selected = self.by_id.get(self.selected)
        if selected and (self.status(selected["id"]) == "Rejected" or (selected.get("exercise") and exercise_shown)):
            selected = None
        if selected:
            colour = STYLE[selected["assessment"]["level"]][0]
            path = line_path(selected["line_id"], app.scenario)
            if len(path) > 1:
                app.map.create_line(*app._points(path), fill=ui.BG, width=7, tags=("sim-selected",))
                app.map.create_line(*app._points(path), fill=colour, width=3, dash=(9, 5), tags=("sim-selected",))
            if len(selected["track"]) > 1:
                app.map.create_line(*app._points(selected["track"]), fill=colour, width=2, tags=("sim-selected",))
        labels = []
        for item in sorted(items, key=lambda row: (row["id"] == self.selected, row["assessment"]["rank"])):
            x, y = app._project(item["lat"], item["lon"])
            if not (-20 <= x <= width + 20 and -20 <= y <= height + 20):
                continue
            level = item["assessment"]["level"]
            colour = STYLE[level][0]
            size = MARKER_SIZE.get(level, 1.0)
            tags = ("sim-alert", f"sim-alert:{item['id']}")
            if level == "critical":
                radius = 17 if self.pulse else 13
                halo = app.map.create_oval(x - radius, y - radius, x + radius, y + radius, outline=colour,
                                           width=2, tags=tags)
                self.halos.append((halo, x, y))
            if item["sog_kn"] >= 0.5:
                angle = math.radians(item["cog_deg"] or 0)
                shape = []
                for across, along in ((0, -7), (5, 5), (0, 2.5), (-5, 5)):
                    across, along = across * size, along * size
                    shape.extend((x + across * math.cos(angle) - along * math.sin(angle),
                                  y + across * math.sin(angle) + along * math.cos(angle)))
                app.map.create_polygon(shape, fill=colour, outline=ui.BG, width=1, tags=tags)
            else:
                radius = 4.5 * size
                app.map.create_oval(x - radius, y - radius, x + radius, y + radius, fill=colour, outline=ui.BG,
                                    width=1, tags=tags)
            if item["id"] == self.selected:
                app.map.create_oval(x - 18, y - 18, x + 18, y + 18, outline=ui.INK, width=2, tags=tags)
            if level in ("critical", "high") or item["id"] == self.selected:
                tag = source(item)["tag"]
                labels.append((item["id"] != self.selected, -item["assessment"]["rank"], -item["assessment"]["score"],
                               f"{item['name']} · {tag}", x, y, colour, tags))
        # The selected contact labels first, then critical and high; a label that would overlap is left out.
        for optional, _rank, _score, text, x, y, colour, tags in sorted(labels, key=lambda row: row[:3]):
            for dx, dy, anchor in ((14, -12, "w"), (14, 12, "w"), (-14, -12, "e"), (-14, 12, "e")):
                if self._label(x + dx, y + dy, text, colour, tags, anchor, occupied, force=False):
                    break
            else:
                if not optional:
                    self._label(x + 14, y - 12, text, colour, tags, "w", occupied, force=True)
        if selected:
            visible = [app._project(*point) for point in line_path(selected["line_id"], app.scenario)]
            visible = [(x, y) for x, y in visible if 40 <= x <= width - 160 and 70 <= y <= height - 100]
            vessel = app._project(selected["lat"], selected["lon"])
            for x, y in sorted(visible, key=lambda point: -math.dist(point, vessel)):
                if self._label(x, y + 12, f"{selected['line_name']} · illustrative route",
                               STYLE[selected["assessment"]["level"]][0], ("sim-selected",), "n", occupied, force=False):
                    break
        self.draw_response(occupied)
        self.draw_assigned(occupied)
        if items:
            text = f"SIMULATED · {len(items)} fictional contact{'s' if len(items) != 1 else ''}"
            label = app.map.create_text(20, 40, text=text, anchor="w", fill=ui.INK, font=(SANS, 9, "bold"),
                                        tags=("sim-badge",))
            left, top, right, bottom = app.map.bbox(label)
            box = app.map.create_rectangle(left - 7, top - 3, right + 7, bottom + 3, fill=ui.BG, outline=ui.LINE,
                                           tags=("sim-badge",))
            app.map.tag_lower(box, label)

    def draw_response(self, occupied) -> None:
        """For the selected incident: asset bases, the vessel's expected path and the best asset's dashed route."""
        app, ui = self.app, self.ui
        result = self.response(self.selected) if self.selected else None
        if not result:
            return
        item = self.by_id[self.selected]
        width, height = app._map_size
        px = ctk.ScalingTracker.get_widget_scaling(app.map)
        tags = ("sim-response",)
        shown = result["assigned"] or result["best"]
        if shown and shown["meet"]:
            meet_x, meet_y = app._project(*shown["meet"])
            now_x, now_y = app._project(*self.replay.position(item)(self.replay.now))
            colour = LATE if shown["in_time"] is False else IN_TIME
            app.map.create_line(now_x, now_y, meet_x, meet_y, fill=STYLE[item["assessment"]["level"]][0],
                                width=max(1, round(px)), dash=(2, 4), tags=tags)
            base_x, base_y = app._project(shown["lat"], shown["lon"])
            app.map.create_line(base_x, base_y, meet_x, meet_y, fill=ui.BG, width=round(5 * px), tags=tags)
            app.map.create_line(base_x, base_y, meet_x, meet_y, fill=colour, width=round(2.5 * px),
                                dash=(8, 5), tags=tags)
            r = 6 * px
            app.map.create_oval(meet_x - r, meet_y - r, meet_x + r, meet_y + r, outline=colour,
                                width=round(2 * px), tags=tags)
            sent = "sent · " if shown["status"] == "assigned" else ""
            self._label(meet_x + 10 * px, meet_y + 10 * px,
                        f"{shown['id']} {sent}meets it in {responders.minutes(shown['eta_s'])} min",
                        colour, tags, "w", occupied, force=True)
        for row in result["rows"]:
            if row["lat"] is None:
                continue
            x, y = app._project(row["lat"], row["lon"])
            if not (0 <= x <= width and 0 <= y <= height):
                continue
            colour = (UNAVAILABLE if row["status"] == "unavailable" else
                      LATE if row["in_time"] is False else IN_TIME)
            r = (6 if row is shown else 4.5) * px
            shape = RESPONSE_SHAPE.get(row["kind"], "circle")
            outline = ui.INK if row is shown else ui.BG
            if shape == "diamond":
                app.map.create_polygon(x, y - r * 1.3, x + r * 1.3, y, x, y + r * 1.3, x - r * 1.3, y,
                                       fill=colour, outline=outline, width=1, tags=tags)
            elif shape == "square":
                app.map.create_rectangle(x - r, y - r, x + r, y + r, fill=colour, outline=outline, width=1,
                                         tags=tags)
            elif shape == "ring":
                app.map.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=round(2 * px), tags=tags)
            else:
                app.map.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline=outline, width=1, tags=tags)
            self._label(x + r + 4 * px, y, row["id"], colour, tags, "w", occupied, force=row is shown)

    def draw_assigned(self, occupied) -> None:
        """Every sent asset at the replay time: preparing at its base, en route to the meeting point, on scene."""
        app, ui = self.app, self.ui
        px = ctk.ScalingTracker.get_widget_scaling(app.map)
        for asset_id in self.replay.assignments:
            where = self.replay.asset_track(asset_id, self.replay.now)
            if where is None:
                continue
            tags = ("sim-asset", f"sim-asset:{asset_id}")
            x, y = app._project(where["lat"], where["lon"])
            if where["phase"] == "en route":
                meet_x, meet_y = app._project(*where["meet"])
                app.map.create_line(x, y, meet_x, meet_y, fill=IN_TIME, width=round(2 * px), dash=(6, 4), tags=tags)
            r = 8 * px
            shape = RESPONSE_SHAPE.get(where["asset"]["kind"], "circle")
            if shape == "diamond":
                app.map.create_polygon(x, y - r * 1.3, x + r * 1.3, y, x, y + r * 1.3, x - r * 1.3, y,
                                       fill=IN_TIME, outline=ui.INK, width=2, tags=tags)
            elif shape == "square":
                app.map.create_rectangle(x - r, y - r, x + r, y + r, fill=IN_TIME, outline=ui.INK, width=2, tags=tags)
            else:
                app.map.create_oval(x - r, y - r, x + r, y + r, fill=IN_TIME, outline=ui.INK, width=2, tags=tags)
            phase = {"preparing": f"preparing · {where['minutes_left']} min",
                     "en route": f"en route · {where['minutes_left']} min",
                     "on scene": f"on scene · {where['item']['name']}"}[where["phase"]]
            self._label(x + r + 6 * px, y - r, f"{asset_id} {phase}", IN_TIME, tags, "w", occupied, force=True)

    def _label(self, x, y, text, colour, tags, anchor, occupied, force=True) -> bool:
        """Draw a boxed map label unless it would overlap one already drawn."""
        app = self.app
        label = app.map.create_text(x, y, text=text, anchor=anchor, fill=colour, font=(SANS, 9, "bold"), tags=tags)
        left, top, right, bottom = app.map.bbox(label)
        box = (left - 4, top - 2, right + 4, bottom + 2)
        if not force and any(box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]
                             for other in occupied):
            app.map.delete(label)
            return False
        occupied.append(box)
        background = app.map.create_rectangle(*box, fill=self.ui.BG, outline="", tags=tags)
        app.map.tag_lower(background, label)
        return True

    def pulse_halos(self) -> None:
        self.pulse = not self.pulse
        if self.app.tools.reduced_motion.get():
            return
        radius = 17 if self.pulse else 13
        for halo, x, y in self.halos:
            self.app.map.coords(halo, x - radius, y - radius, x + radius, y + radius)

    def describe(self, identifier: str) -> str:
        item = self.by_id[identifier]
        kind = "Fictional exercise" if item.get("exercise") else "Simulated contact"
        incident = self.tracker.open_incident(item)
        where = f"{incident['id']} {self.status(identifier)}" if incident else self.status(identifier)
        return (f"{kind} · {item['name']} · {item['assessment']['level_name']} {item['assessment']['score']} · "
                f"{where} · {item['title']}")


class ReviewDialog:
    """Review window: indicators behind the level, time to the asset and the operator's decision."""
    WIDTH = 520

    def __init__(self, board: AlertBoard):
        self.board = board
        app, ui = board.app, board.ui
        self.ui = ui
        self.item: dict | None = None
        self.mode: str | None = None
        self.visible = False
        self.choice = tk.StringVar(app.root, value="")
        self.position: tuple[float, float] | None = None  # (right edge, top) once the operator drags it
        self.drag: tuple | None = None
        self.drag_target: tuple[int, int] | None = None
        self.frame = ctk.CTkFrame(app.chart_host, width=self.WIDTH, height=620, fg_color=ui.CARD,
                                  corner_radius=8, border_width=1, border_color=ui.LINE)
        self.frame.pack_propagate(False)
        # Wrap lengths are screen pixels; the frame width is in CustomTkinter units (x2 on a 200% display).
        self.px = ctk.ScalingTracker.get_widget_scaling(self.frame)
        self.id_font = tkfont.Font(root=app.root, family=MONO, size=10, weight="bold")
        self.row_font = tkfont.Font(root=app.root, family=SANS, size=10)
        self.name_font = tkfont.Font(root=app.root, family=SANS, size=9)
        head = tk.Frame(self.frame, bg=ui.CARD)
        head.pack(fill="x", padx=(20, 12), pady=(14, 0))
        self.level = tk.Label(head, text="", bg=ui.CARD, font=(SANS, 10, "bold"))
        self.level.pack(side="left")
        self.score = tk.Label(head, text="", bg=ui.CARD, fg=ui.MUTED, font=(MONO, 10))
        self.score.pack(side="left", padx=(10, 0))
        close = ctk.CTkButton(head, text="", image=app.tools.icons.get("close"), command=self.close, width=30,
                              height=30, fg_color="transparent", hover_color=ui.HOVER)
        close.pack(side="right")
        app.tools.style_button(close, "Close · Escape")
        self.tag = tk.Label(head, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 7, "bold"), padx=5,
                            highlightthickness=1, highlightbackground=ui.LINE)
        self.tag.pack(side="right", padx=(0, 10))
        name_row = tk.Frame(self.frame, bg=ui.CARD)
        name_row.pack(fill="x", padx=20, pady=(4, 0))
        self.report_button = ctk.CTkButton(name_row, text="Report vessel", width=140, height=36,
            fg_color="#47c7da", hover_color="#6ed5e3", text_color=ui.BG,
            font=ctk.CTkFont(SANS, 12, "bold"),
            image=app.tools.icons.get("alerts", ui.BG, 18),
            command=self.report_vessel)
        self.report_button.pack(side="right", padx=(5, 0))
        self.name = tk.Label(name_row, text="", bg=ui.CARD, fg=ui.INK, font=(SANS, 18, "bold"), anchor="w")
        self.name.pack(side="left", fill="x", expand=True)
        self.meta = tk.Label(self.frame, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 10), anchor="w",
                             justify="left")
        self.meta.pack(fill="x", padx=20)
        self.title = tk.Label(self.frame, text="", bg=ui.CARD, fg=ui.INK, font=(SANS, 12), anchor="w",
                              justify="left", wraplength=round((self.WIDTH - 50) * self.px))
        self.title.pack(fill="x", padx=20, pady=(8, 0))
        self.flags = tk.Label(self.frame, text="", bg=ui.CARD, fg=STYLE["medium"][0], font=(SANS, 10, "bold"),
                              anchor="w", justify="left", wraplength=round((self.WIDTH - 50) * self.px))
        self.flags.pack(fill="x", padx=20, pady=(4, 0))
        for widget in (head, self.level, self.score, self.tag, self.name, self.meta, self.title, self.flags):
            widget.configure(cursor="fleur")
            widget.bind("<ButtonPress-1>", self.start_drag, add="+")
            widget.bind("<B1-Motion>", self.move_drag, add="+")
            widget.bind("<ButtonRelease-1>", self.end_drag, add="+")
            widget.bind("<Double-Button-1>", lambda _event: self.dock(), add="+")
            widget.bind("<Enter>", lambda _event: app.map_status_label.configure(
                text="Drag to move this window · double-click to dock it"), add="+")
        self.scale = tk.Canvas(self.frame, height=44, bg=ui.CARD, highlightthickness=0)
        self.scale.pack(fill="x", padx=20, pady=(12, 0))
        self.scale.bind("<Configure>", lambda _event: self.draw_scale())
        facts = self.facts_frame = tk.Frame(self.frame, bg=ui.CARD)
        facts.pack(fill="x", padx=20, pady=(8, 0))
        self.facts = {}
        for index, (key, caption) in enumerate((("asset", "ASSET"), ("time", "TIME TO ASSET"), ("status", "STATUS"))):
            facts.columnconfigure(index, weight=4 if index == 0 else 3, uniform="facts")
            cell = tk.Frame(facts, bg=ui.CARD)
            cell.grid(row=0, column=index, sticky="nsew", padx=(0, 12))
            tk.Label(cell, text=caption, bg=ui.CARD, fg=ui.MUTED, font=(SANS, 8, "bold"), anchor="w").pack(fill="x")
            value = tk.Label(cell, text="", bg=ui.CARD, fg=ui.INK, font=(SANS, 11, "bold"), anchor="w",
                             justify="left", wraplength=140)
            value.pack(fill="x", pady=(2, 0))
            detail = tk.Label(cell, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9), anchor="w",
                              justify="left", wraplength=140)
            detail.pack(fill="x")
            cell.bind("<Configure>", lambda event, labels=(value, detail): [
                label.configure(wraplength=max(60, event.width - 4)) for label in labels
                if label.cget("wraplength") != max(60, event.width - 4)])
            self.facts[key] = (value, detail)
        tk.Frame(self.frame, bg=ui.LINE, height=1).pack(fill="x", padx=20, pady=(12, 0))
        self.actions = tk.Frame(self.frame, bg=ui.CARD)
        self.actions.pack(side="bottom", fill="x", padx=20, pady=(10, 16))
        tk.Frame(self.frame, bg=ui.LINE, height=1).pack(side="bottom", fill="x", padx=20)
        self.form = tk.Frame(self.frame, bg=ui.CARD)
        self.middle = tk.Frame(self.frame, bg=ui.CARD)
        self.middle.pack(fill="both", expand=True, padx=(14, 8), pady=(4, 0))
        self.body = ctk.CTkScrollableFrame(self.middle, fg_color=ui.CARD, corner_radius=0,
            scrollbar_button_color=ui.LINE, scrollbar_button_hover_color=ui.HOVER)
        self.body.pack(fill="both", expand=True)

    def report_vessel(self):
        from desktop_reports import board_snapshot, open_report
        if self.item:
            open_report(self.board.app, board_snapshot(self.item))

    # ----- layout ---------------------------------------------------------------------
    def place(self) -> None:
        app = self.board.app
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        width = app.chart_host.winfo_width() / scaling
        height = app.chart_host.winfo_height() / scaling
        bottom = 200 if app.exercise_visible.get() else 120
        dialog_width = max(360, min(self.WIDTH, width - 110))
        dialog_height = max(380, min(760, height - bottom))
        if self.position is None:
            self.frame.configure(width=dialog_width, height=dialog_height)
            self.frame.place(relx=1, x=-70, y=16, anchor="ne")
        else:
            right, top = self.clamp(dialog_width, width, height)
            self.frame.configure(width=dialog_width, height=min(dialog_height, max(300, height - top - 16)))
            self.frame.place(relx=0, x=right, y=top, anchor="ne")
        self.frame.lift()

    def clamp(self, dialog_width: float, width: float, height: float) -> tuple[float, float]:
        """Keep part of a moved window, and its whole header, inside the map."""
        right, top = self.position
        self.position = (max(min(dialog_width, 120), min(width + dialog_width - 120, right)),
                         max(0, min(height - 48, top)))
        return self.position

    def start_drag(self, event) -> None:
        host = self.board.app.chart_host
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        right = (self.frame.winfo_rootx() + self.frame.winfo_width() - host.winfo_rootx()) / scaling
        top = (self.frame.winfo_rooty() - host.winfo_rooty()) / scaling
        self.drag = (event.x_root, event.y_root, right, top)
        self.drag_target = None

    def move_drag(self, event) -> None:
        if not self.drag:
            return
        # Coalesce motion events into one move per idle so the map behind can repaint in time.
        if self.drag_target is None:
            self.board.app.root.after_idle(self.apply_drag)
        self.drag_target = (event.x_root, event.y_root)

    def apply_drag(self) -> None:
        if not self.drag or self.drag_target is None:
            return
        x, y, right, top = self.drag
        x_root, y_root = self.drag_target
        self.drag_target = None
        host = self.board.app.chart_host
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        self.position = (right + (x_root - x) / scaling, top + (y_root - y) / scaling)
        # Only move while dragging; resizing re-lays out the whole window and leaves trails.
        right, top = self.clamp(self.frame.winfo_width() / scaling, host.winfo_width() / scaling,
                                host.winfo_height() / scaling)
        self.frame.place(relx=0, x=right, y=top, anchor="ne")

    def end_drag(self, _event=None) -> None:
        if self.drag:
            self.apply_drag()
            self.drag = None
            self.place()

    def dock(self) -> None:
        self.drag = None
        self.position = None
        if self.visible:
            self.place()

    def covered_width(self) -> float:
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        if self.position is not None:
            return 70 * scaling  # moved by the operator: no longer a fixed strip on the right
        return (float(self.frame.cget("width")) + 90) * scaling

    # ----- content --------------------------------------------------------------------
    def show(self, item: dict) -> None:
        changed = self.item is None or self.item["id"] != item["id"]
        if changed:
            self.mode = None
        self.item = item
        self.visible = True
        self.place()
        self.refresh()
        canvas = getattr(self.body, "_parent_canvas", None)
        if changed and canvas is not None:
            # A new contact starts at the top, not at the previous contact's scroll position.
            canvas.yview_moveto(0)

    def refresh(self) -> None:
        item, board, ui = self.item, self.board, self.ui
        if item is None:
            return
        item = board.by_id.get(item["id"], item)
        self.item = item
        assessment = item["assessment"]
        incident = board.incident(item["id"])
        status = board.status(item["id"])
        level = assessment["level_name"].upper()
        if incident and RANK[incident["peak_level"]] > RANK[assessment["level"]]:
            level += f"  ·  PEAK {LEVEL_NAMES[incident['peak_level']].upper()}"
        self.level.configure(text=level, fg=STYLE[assessment["level"]][0])
        self.score.configure(text=f"Score {assessment['score']}" + (f"  ·  {incident['id']}" if incident else ""))
        self.tag.configure(text=source(item)["long_tag"])
        self.name.configure(text=item["name"])
        meta = [item["vessel_type"]]
        if item.get("length_m"):
            meta.append(f"{item['length_m']:.0f} m")
        meta += [f"SOG {item['sog_kn']:.1f} kn", f"COG {item['cog_deg']:03.0f}°"]
        if not item.get("exercise"):
            minutes = int(board.age_min(item))
            meta.append("raised now" if minutes < 1 else f"raised {minutes} min ago" if minutes < 60
                        else f"raised {minutes // 60} h {minutes % 60:02d} min ago")
        self.meta.configure(text="  ·  ".join(meta))
        self.title.configure(text=item["title"])
        flags = badges(item, incident if status != "Rejected" else None)
        self.flags.configure(text="   ".join(text for text, _kind in flags))
        if flags:
            self.flags.pack(fill="x", padx=20, pady=(4, 0), after=self.title)
        else:
            self.flags.pack_forget()
        self.draw_scale()
        self.facts["asset"][0].configure(text=item["line_name"])
        self.facts["asset"][1].configure(text="Fictional cable" if item.get("exercise") else "Illustrative route")
        self.update_live(force=True)
        detail = {"Escalated": f"To {board.recipients.get(item['id'], '')}",
                  "Rejected": (incident or {}).get("status_reason") or "",
                  "Watching": "Low: an observation, not an incident"}.get(status, STATUS_DETAIL.get(status, ""))
        self.facts["status"][0].configure(text="Closed · rejected" if status == "Rejected" else status, fg=ui.INK)
        self.facts["status"][1].configure(text=detail)
        self.fill_body()
        self.fill_actions()
        self.fill_form()

    def update_live(self, force: bool = False) -> None:
        if not self.visible or self.item is None:
            return
        item = self.item
        observations = item["observations"]
        colour, font = self.ui.INK, (SANS, 11, "bold")
        if item.get("exercise"):
            remaining = self.board.app._remaining()
            value, detail = (self.board.ui.clock(remaining[0]), "Exercise replay countdown") if remaining else (
                "Before alert", "Exercise replay")
            if remaining:
                colour, font = STYLE[item["assessment"]["level"]][0], (MONO, 12, "bold")
        elif countdown(item) is not None:
            value, detail = countdown(item), "Constant speed and course"
            colour, font = STYLE[item["assessment"]["level"]][0], (MONO, 12, "bold")
        elif observations.get("in_corridor"):
            value, detail = "In corridor", "Within 1 nm of the asset"
        elif observations.get("distance_nm") is not None:
            value, detail = f"{observations['distance_nm']:.1f} nm off", "Not on a closing course"
        else:
            value, detail = "—", ""
        widgets = self.facts["time"]
        if force or widgets[0].cget("text") != value:
            widgets[0].configure(text=value, fg=colour, font=font)
            widgets[1].configure(text=detail)

    def draw_scale(self) -> None:
        canvas, ui = self.scale, self.ui
        canvas.delete("all")
        if self.item is None:
            return
        width = max(200, canvas.winfo_width())
        assessment = self.item["assessment"]
        maximum = 16

        def position(score):
            return (width - 2) * min(score, maximum) / maximum + 1

        for level, start, end in (("none", 0, 3), ("low", 3, 6), ("medium", 6, 9), ("high", 9, 12),
                                  ("critical", 12, maximum)):
            active = level == assessment["level"]
            colour, tint = STYLE[level]
            canvas.create_rectangle(position(start) + 1, 16, position(end) - 1, 21,
                                    fill=colour if active else tint, outline="")
            if level != "none":
                canvas.create_text(position(start) + 2, 34, text=f"{LEVEL_NAMES[level]} {start}+", anchor="w",
                                   fill=ui.INK if active else ui.MUTED, font=(SANS, 8))
        x = position(assessment["score"])
        canvas.create_polygon(x - 5, 5, x + 5, 5, x, 12, fill=ui.INK, outline="")

    def heading(self, text: str, top: int = 16) -> None:
        tk.Label(self.body, text=text, bg=self.ui.CARD, fg=self.ui.MUTED, font=(SANS, 8, "bold"),
                 anchor="w").pack(fill="x", padx=(6, 0), pady=(top, 6))

    def fill_body(self) -> None:
        ui, item, board = self.ui, self.item, self.board
        for child in self.body.winfo_children():
            child.destroy()
        wrap = round((float(self.frame.cget("width")) - 110) * self.px)
        self.compact(self.mode == "escalate")
        if self.mode == "escalate":
            # Escalating is when an asset is chosen: the window shows who can reach the vessel instead.
            self.fill_responders(wrap)
            return
        self.fill_why(explain(item), wrap)
        self.heading("RECOMMENDED ACTION")
        tk.Label(self.body, text=item["recommendation"], bg=ui.CARD, fg=ui.INK, font=(SANS, 10), anchor="w",
                 justify="left", wraplength=wrap + 40).pack(fill="x", padx=(6, 0))
        self.heading("LOG")
        entries = board.history.get(item["id"], [])
        if not entries:
            tk.Label(self.body, text="No entries.", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 10),
                     anchor="w").pack(fill="x", padx=(6, 0))
        for stamp, text in entries[-8:]:
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", padx=(6, 0), pady=1)
            tk.Label(row, text=board.stamp(stamp), bg=ui.CARD, fg=ui.MUTED, font=(MONO, 9)).pack(side="left", anchor="n")
            tk.Label(row, text=text, bg=ui.CARD, fg=SECONDARY, font=(SANS, 10), anchor="w", justify="left",
                     wraplength=wrap - 40).pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.heading("DATA LABELS")
        for tag, text in explain(item)["labels"]:
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", padx=(6, 0), pady=2)
            self.chip(row, tag, width=13).pack(side="left", anchor="n")
            tk.Label(row, text=text, bg=ui.CARD, fg=SECONDARY, font=(SANS, 9), anchor="w", justify="left",
                     wraplength=wrap - 70).pack(side="left", fill="x", expand=True, padx=(8, 0))
        source = ("Brain opens and updates the incident; only a human sets its status." if board.incident(item["id"])
                  else "Low: watched, not an incident; it opens one if it reaches Medium.")
        tk.Label(self.body, text=source + " Decisions are logged locally and not transmitted.", bg=ui.CARD,
                 fg=ui.MUTED, font=(SANS, 9), anchor="w", justify="left", wraplength=wrap + 40).pack(
            fill="x", padx=(6, 0), pady=(12, 6))

    def fill_responders(self, wrap: int) -> None:
        """Who can reach it: the storm switch, the card line, then every asset with minutes or a reason."""
        ui, item, board = self.ui, self.item, self.board
        head = tk.Frame(self.body, bg=ui.CARD)
        head.pack(fill="x", padx=(6, 0), pady=(4, 6))
        tk.Label(head, text="WHO CAN REACH IT", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 8, "bold")).pack(side="left")
        storm = board.replay.storm
        switch = ctk.CTkButton(
            head, text=f"Storm {board.replay.fleet['wind']['storm_kn']} kn: {'ON' if storm else 'off'}",
            command=board.toggle_storm, height=24, width=120, corner_radius=6,
            font=ctk.CTkFont(SANS, 11, "bold" if storm else "normal"),
            fg_color=STYLE["high"][1] if storm else ui.CARD, hover_color=ui.HOVER, border_width=1,
            border_color=STYLE["high"][0] if storm else ui.LINE, text_color=STYLE["high"][0] if storm else ui.MUTED)
        switch.pack(side="right", padx=(0, 6))
        board.app.tools.style_button(switch, "Exercise wind: a storm grounds every drone (wind limit 25 kn)")
        result = board.response(item["id"])
        if result is None:
            tk.Label(self.body, text="Worked out for open incidents at Medium or above.", bg=ui.CARD, fg=ui.MUTED,
                     font=(SANS, 10), anchor="w").pack(fill="x", padx=(6, 0))
            return
        status_open = board.status(item["id"]) not in ("Rejected", "Watching")
        text, warn = responders.summary_line(result)
        tk.Label(self.body, text=text, bg=ui.CARD, fg=STYLE["critical"][0] if warn else IN_TIME,
                 font=(SANS, 11, "bold"), anchor="w", justify="left", wraplength=wrap + 40).pack(fill="x", padx=(6, 0))
        if result["deadline_s"] is None:
            when = "Not approaching a line: eyes-on times only"
        elif result["at_line"]:
            when = result["at_line_text"].capitalize()
        else:
            when = (f"Earliest line ETA {board.stamp(result['deadline_s'])} "
                    f"(in {responders.minutes(result['deadline_s'] - result['now'])} min)")
        tk.Label(self.body, text=f"{when} · wind {result['wind_kn']:g} kn, exercise value", bg=ui.CARD,
                 fg=ui.MUTED, font=(SANS, 9), anchor="w", justify="left", wraplength=wrap + 40).pack(
            fill="x", padx=(6, 0), pady=(1, 4))
        for row in result["rows"]:
            unavailable = row["status"] == "unavailable"
            colour = UNAVAILABLE if unavailable else LATE if row["in_time"] is False else IN_TIME
            if unavailable:
                verdict = row["reason"]
            else:
                verdict = f"{responders.minutes(row['eta_s'])} min"
                if row["margin_s"] is not None:
                    verdict += (f" · in time (+{responders.minutes(row['margin_s'])})" if row["in_time"]
                                else f" · {responders.minutes(-row['margin_s'])} min late")
                if not row["counts"]:
                    verdict += " · look only"
            line = tk.Frame(self.body, bg=ui.CARD)
            line.pack(fill="x", padx=(6, 0), pady=1)
            tk.Label(line, text=row["id"], width=5, anchor="w", bg=ui.CARD, fg=colour,
                     font=(MONO, 10, "bold")).pack(side="left", anchor="n")
            action = None
            if row["status"] == "assigned":
                action = ("Recall", lambda asset=row["id"]: board.recall(item["id"], asset),
                          "Take the asset back; it is free for the other incidents again")
                verdict = "SENT · " + verdict
            elif row["counts"] and not unavailable and status_open:
                action = ("Send", lambda asset=row["id"]: board.send(item["id"], asset),
                          "Send this asset (simulated decision, logged, not transmitted). "
                          "It is then busy for every other incident")
            button_width = 0
            if action:
                text_, command, tip = action
                button = ctk.CTkButton(line, text=text_, command=command, width=58, height=22, corner_radius=5,
                                       font=ctk.CTkFont(SANS, 11, "bold"), fg_color=ui.CARD, hover_color=ui.HOVER,
                                       border_width=1, border_color=colour, text_color=colour)
                button.pack(side="right", padx=(6, 0))
                board.app.tools.style_button(button, tip)
                button_width = round(64 * self.px)
            tk.Label(line, text=verdict, bg=ui.CARD, fg=ui.MUTED if unavailable else colour, font=self.row_font,
                     anchor="e", justify="right").pack(side="right", anchor="n")
            name = row["name"] if row["kind"] == "satellite" else f"{row['name']} · {row['base']}"
            # The asset name gives way to its minutes, verdict and button.
            room = (wrap + 40 - self.id_font.measure("MPA1 ") - self.row_font.measure(verdict) - button_width
                    - round(20 * self.px))
            tk.Label(line, text=clip(name, self.name_font, max(40, room)), bg=ui.CARD,
                     fg=ui.MUTED if unavailable else SECONDARY, font=self.name_font, anchor="w",
                     justify="left").pack(side="left", fill="x", expand=True, padx=(4, 8))
            if action and action[0] == "Send":
                others = board.replay.conflicts(item, row["id"])
                if others:
                    names = ", ".join(other["name"] for other in others)
                    tk.Label(self.body, text=f"⚠ Only {row['id']} reaches {names} in time: sending it here "
                                             f"leaves {'them' if len(others) > 1 else 'it'} with no responder",
                             bg=ui.CARD, fg=STYLE["medium"][0], font=(SANS, 9), anchor="w", justify="left",
                             wraplength=wrap).pack(fill="x", padx=(round(52 * self.px), 0), pady=(0, 3))
        note = tk.Frame(self.body, bg=ui.CARD)
        note.pack(fill="x", padx=(6, 0), pady=(6, 0))
        self.chip(note, "ASSUMPTION").pack(side="left", anchor="n")
        tk.Label(note, text="Bases are public places, coordinates approximate. Speeds, readiness, ranges, drone "
                            "sites and the patrol ship position are team assumptions. VHF and satellite only look.",
                 bg=ui.CARD, fg=ui.MUTED, font=(SANS, 9), anchor="w", justify="left", wraplength=wrap - 70).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    def compact(self, on: bool) -> None:
        """While escalating, fold the level scale and facts so the asset list has room."""
        if on:
            self.scale.pack_forget()
            self.facts_frame.pack_forget()
        elif not self.scale.winfo_manager():
            above = self.flags if self.flags.winfo_manager() else self.title
            self.scale.pack(fill="x", padx=20, pady=(12, 0), after=above)
            self.facts_frame.pack(fill="x", padx=20, pady=(8, 0), after=self.scale)

    def chip(self, parent, tag: str, width: int = 0) -> tk.Label:
        """A small data-label tag such as SIMULATED, REAL or ASSUMPTION."""
        fg, bg = CHIP.get(tag, (self.ui.MUTED, self.ui.CONTROL))
        return tk.Label(parent, text=tag, bg=bg, fg=fg, font=(SANS, 7, "bold"), padx=5, pady=1, width=width)

    def line(self, prefix: str, text: str, wrap: int, colour: str, prefix_colour: str | None = None,
             font=(SANS, 10)) -> None:
        """One indented row: a short mono prefix (points or a bullet) and wrapped text."""
        row = tk.Frame(self.body, bg=self.ui.CARD)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=prefix, width=3, anchor="e", bg=self.ui.CARD, fg=prefix_colour or colour,
                 font=(MONO, 10, "bold")).pack(side="left", anchor="n")
        tk.Label(row, text=text, bg=self.ui.CARD, fg=colour, font=font, anchor="w", justify="left",
                 wraplength=wrap).pack(side="left", fill="x", expand=True, padx=(10, 0))

    def fill_why(self, why: dict, wrap: int) -> None:
        """Why this level: the five groups with points and factors, rules applied, the line, detectors."""
        ui = self.ui
        head = tk.Frame(self.body, bg=ui.CARD)
        head.pack(fill="x", padx=(6, 0), pady=(4, 6))
        tk.Label(head, text="WHY THIS LEVEL", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 8, "bold")).pack(side="left")
        tk.Label(head, text=why["basis"], bg=ui.CARD, fg=ui.MUTED, font=(MONO, 9)).pack(side="right")
        for group in why["groups"]:
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", padx=(6, 0), pady=(6, 1))
            active = group["points"] > 0
            tk.Label(row, text=f"{group['key']}  {group['title']}", bg=ui.CARD, fg=ui.INK if active else ui.MUTED,
                     font=(SANS, 10, "bold")).pack(side="left")
            score = f"{group['points']} of {group['cap']} max" if group["cap"] else f"{group['points']} pts"
            tk.Label(row, text=score if group["factors"] else "nothing observed", bg=ui.CARD, fg=ui.MUTED,
                     font=(MONO, 9) if group["factors"] else (SANS, 9)).pack(side="right")
            for factor in group["factors"]:
                points = factor["points"]
                text = f"+{points}" if points > 0 else ("−" + str(-points) if points < 0 else "0")
                self.line(text, factor["text"], wrap, ui.INK if points else ui.MUTED)
        if why["rules"]:
            self.heading("RULES APPLIED")
            for note in why["rules"]:
                self.line("›", note, wrap, SECONDARY, ui.MUTED, (SANS, 10, "italic"))
        line = why["line"]
        self.heading("THREATENED LINE")
        self.line("›", f"{line['name']}: {line['where']}", wrap, ui.INK, ui.MUTED)
        for other in line["others"]:
            self.line("", f"Also named: {other['name']}, {other['where']}. Scored for the most urgent line only.",
                      wrap, ui.MUTED)
        small = why["small_vessel"]
        if small:
            self.heading("SMALL VESSEL")
            self.line("›", f"Small: {small['reason']}.", wrap, ui.INK, ui.MUTED)
            self.line("", small["outcome"], wrap, STYLE["low"][0] if small["capped"] else STYLE["medium"][0])
        self.heading("FINDINGS BY DETECTOR")
        for finding in why["findings"]:
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", padx=(6, 0), pady=(4, 1))
            tk.Label(row, text=finding["title"], bg=ui.CARD, fg=ui.INK, font=(SANS, 10, "bold")).pack(side="left")
            self.chip(row, finding["label"]).pack(side="left", padx=(8, 0))
            for reason in finding["reasons"][:DETECTOR_REASONS]:
                self.line("•", reason, wrap, SECONDARY, ui.MUTED)
            hidden = len(finding["reasons"]) - DETECTOR_REASONS
            if hidden > 0:
                self.line("", f"+{hidden} more", wrap, ui.MUTED)

    def fill_actions(self) -> None:
        ui, item, board = self.ui, self.item, self.board
        for child in self.actions.winfo_children():
            child.destroy()
        status = board.status(item["id"])

        def button(text, command, side="left", primary=False, tip=None):
            widget = ctk.CTkButton(self.actions, text=text, command=command, height=32, corner_radius=6,
                width=max(84, len(text) * 7 + 28), font=ctk.CTkFont(SANS, 12, "bold" if primary else "normal"),
                fg_color=ui.PURPLE if primary else ui.CARD, hover_color="#af9450" if primary else ui.HOVER,
                border_width=0 if primary else 1, border_color=ui.LINE, text_color=ui.BG if primary else ui.INK)
            widget.pack(side=side, padx=(0, 8) if side == "left" else (8, 0))
            self.board.app.tools.style_button(widget, tip)
            return widget

        if item.get("exercise"):
            button("Open replay", self.open_replay, tip="Open the exercise replay with its countdown")
        else:
            button("Show on map", lambda: board.reveal(self.item, fit=True), tip="Fit the map to the track and the asset")
        if self.mode or status in ("Watching", "Rejected"):
            # Low contacts are observations and a rejected incident is closed: nothing to decide.
            return
        if status == "Escalated":
            button("Withdraw", lambda: board.withdraw(self.item["id"]), tip="Take back the escalation; keep reviewing")
        if status != "Rejected":
            button("Escalate", lambda: self.open_form("escalate"), side="right", primary=True,
                   tip="Escalate to a duty officer, the asset operator, MRCC or the Naval Service")
            button("Reject", lambda: self.open_form("reject"), side="right", tip="Close with a reason")
            if status in ("New", "Reviewed"):
                button("Acknowledge", lambda: board.decide(self.item["id"], "Acknowledged", "Acknowledged; monitoring"),
                       tip="Seen and monitoring; no escalation")

    def open_form(self, mode: str) -> None:
        self.mode = mode
        self.choice.set(RECIPIENTS[0] if mode == "escalate" else REASONS[0])
        self.fill_actions()
        self.fill_form()
        self.fill_body()
        canvas = getattr(self.body, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(0)

    def fill_form(self) -> None:
        ui = self.ui
        note = getattr(self, "note", None)
        # A Send while escalating rebuilds the form; keep the note the analyst already typed.
        typed = note.get() if self.mode and note is not None and note.winfo_exists() else ""
        for child in self.form.winfo_children():
            child.destroy()
        if not self.mode:
            self.form.pack_forget()
            return
        escalate = self.mode == "escalate"
        tk.Frame(self.form, bg=ui.LINE, height=1).pack(fill="x")
        tk.Label(self.form, text="ESCALATE TO" if escalate else "REJECT AS", bg=ui.CARD, fg=ui.MUTED,
                 font=(SANS, 8, "bold"), anchor="w").pack(fill="x", pady=(12, 4))
        options = tk.Frame(self.form, bg=ui.CARD)
        options.pack(fill="x")
        for index, option in enumerate(RECIPIENTS if escalate else REASONS):
            options.columnconfigure(index % 2, weight=1, uniform="options")
            ctk.CTkRadioButton(options, text=option, variable=self.choice, value=option, fg_color=ui.PURPLE,
                hover_color=ui.HOVER, border_color=ui.MUTED, text_color=ui.INK, font=ctk.CTkFont(SANS, 12),
                radiobutton_width=16, radiobutton_height=16, border_width_unchecked=2,
                border_width_checked=5).grid(row=index // 2, column=index % 2, sticky="w", pady=4)
        self.note = ctk.CTkEntry(self.form, placeholder_text="Note for the log (optional)", height=32, corner_radius=6,
                                 fg_color=ui.CONTROL, border_color=ui.LINE, text_color=ui.INK,
                                 font=ctk.CTkFont(SANS, 12))
        self.note.pack(fill="x", pady=(8, 0))
        if typed:
            self.note.insert(0, typed)
        self.note.bind("<Return>", lambda _event: self.confirm())
        buttons = tk.Frame(self.form, bg=ui.CARD)
        buttons.pack(fill="x", pady=(10, 4))
        ctk.CTkButton(buttons, text="Cancel", command=self.cancel_form, width=84, height=30, corner_radius=6,
                      fg_color=ui.CARD, hover_color=ui.HOVER, border_width=1, border_color=ui.LINE,
                      text_color=ui.INK, font=ctk.CTkFont(SANS, 12)).pack(side="left")
        ctk.CTkButton(buttons, text="Confirm escalation" if escalate else "Confirm rejection", command=self.confirm,
                      width=150, height=30, corner_radius=6, fg_color=ui.PURPLE, hover_color="#af9450",
                      text_color=ui.BG, font=ctk.CTkFont(SANS, 12, "bold")).pack(side="right")
        tk.Label(buttons, text="Simulation: not transmitted", bg=ui.CARD, fg=ui.MUTED,
                 font=(SANS, 9)).pack(side="right", padx=10)
        self.form.pack(side="bottom", fill="x", padx=20, pady=(4, 4), before=self.middle)

    def cancel_form(self) -> None:
        self.mode = None
        self.fill_form()
        self.fill_actions()
        self.fill_body()

    def confirm(self) -> None:
        if not self.mode or self.item is None:
            return
        choice = self.choice.get()
        note = self.note.get().strip()[:200]
        suffix = f". Note: {note}" if note else ""
        identifier = self.item["id"]
        self.mode, escalate = None, self.mode == "escalate"
        if escalate:
            self.board.decide(identifier, "Escalated", f"Escalated to {choice}{suffix}", to=choice)
        else:
            self.board.decide(identifier, "Rejected", f"Rejected: {choice.lower()}{suffix}", reason=choice)
        self.board.app.map_status_label.configure(
            text=f"{self.item['name']} {'escalated to ' + choice if escalate else 'rejected: ' + choice.lower()} · "
                 "logged locally, not transmitted")

    def open_replay(self) -> None:
        alert = self.item.get("alert")
        self.close()
        if alert:
            self.board.app.tools.review_alert(alert)

    def close(self) -> None:
        if self.visible:
            self.frame.place_forget()
        self.visible = False
        self.mode = None
        if self.board.selected:
            self.board.deselect()

    def escape(self, event=None):
        palette = getattr(self.board.app.tools, "palette", None)
        if palette is not None and event is not None and str(event.widget).startswith(str(palette)):
            return None
        if self.visible:
            self.close()
            return "break"
        return None
