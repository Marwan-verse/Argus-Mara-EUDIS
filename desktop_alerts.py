"""Docked incident queue: one card per vessel, a review window and map markers.

The queue scores the fictional exercise alert and the simulated contacts through
Brain (``argus.brain_board``: the assembler's detectors, the small-vessel rule
and the AIS spoofing detector) and folds the scores into ``argus.incidents``
(``argus.incident_board``). A contact at Medium or above is one updatable
incident card; Low and None contacts are watched, not incidents. Each is marked
EXERCISE or SIM in its card, in its review window and on the map. Acknowledge,
escalate and reject go through ``argus.incidents.set_status`` and stay in this
session; nothing is transmitted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from argus.alert_board import line_path, sort_key
from argus.brain_board import build_board, update
from argus.incident_board import OPEN_RANK, Tracker
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
# List groups after the open incidents by level: quiet incidents, watched contacts, closed incidents.
GROUP_TITLES = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "quiet": "QUIET · BELOW MEDIUM",
                "watching": "WATCHING · LOW, NO INCIDENT", "closed": "CLOSED"}
EVENT_TEXT = {"opened": "Incident {id} opened at {level}", "raised": "Level raised to {level}",
              "review_again": "Level rose after review: review again",
              "quiet": f"Quiet {QUIET_CLOSE_S // 60} min below Medium: close?"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def age_text(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def countdown(item: dict) -> str | None:
    """mm:ss to the asset for a contact with a simulated ETA, else None."""
    eta = item["observations"].get("eta_min")
    if eta is None or item.get("eta_start_min") is None:
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
    if "ais_spoofing" in item.get("detectors", ()):
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
        self.started = time.monotonic()
        self.tracker = Tracker()
        self.tracker.step(self.items, 0)
        self.recipients: dict[str, str] = {}
        self.history: dict[str, list[tuple[str, str]]] = {}
        self.exercise_seen = "New"
        self.selected: str | None = None
        self.hovered: str | None = None
        self.level_filter: str | None = None
        self.show_closed = False
        self.show_watching = False
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
        app.root.bind("<Escape>", self.dialog.escape, add="+")

    # ----- building -------------------------------------------------------------------
    def _build(self):
        ui, app, panel = self.ui, self.app, self.panel
        head = tk.Frame(panel, bg=ui.CARD)
        head.pack(fill="x", padx=(16, 12), pady=(14, 0))
        tk.Label(head, text="Incidents", bg=ui.CARD, fg=ui.INK, font=(SANS, 15, "bold")).pack(side="left")
        tk.Label(head, text="SIMULATED", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 7, "bold"), padx=5,
                 highlightthickness=1, highlightbackground=ui.LINE).pack(side="left", padx=(10, 0), pady=(3, 0))
        close = ctk.CTkButton(head, text="", image=app.tools.icons.get("close"), command=app.tools.toggle_alerts,
                              width=30, height=30, fg_color="transparent", hover_color=ui.HOVER)
        close.pack(side="right")
        app.tools.style_button(close, "Hide incidents")
        restart = ctk.CTkButton(head, text="", image=app.tools.icons.get("refresh"), command=self.restart,
                                width=30, height=30, fg_color="transparent", hover_color=ui.HOVER)
        restart.pack(side="right", padx=2)
        app.tools.style_button(restart, "Restart the simulation: countdowns, incidents and decisions reset")

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
        tag = tk.Label(top, text="EXERCISE" if item.get("exercise") else "SIM", bg=ui.CARD, fg=ui.MUTED,
                       font=(SANS, 7, "bold"))
        tag.pack(side="right")
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
        flags = tk.Frame(body, bg=ui.CARD)
        flag_labels = []
        for _ in range(3):
            label = tk.Label(flags, bg=ui.CARD, font=(SANS, 8, "bold"), padx=5, pady=1)
            label.keep_colour = True
            flag_labels.append(label)
        card = {"item": item, "frame": frame, "stripe": stripe, "name": name, "age": age, "eta": eta,
                "reason": reason, "status": status, "flags": flags, "flag_labels": flag_labels,
                "texts": {}, "background": ui.CARD}
        for widget in (frame, stripe, body, top, name, tag, age, reason, bottom, eta, status, flags, *flag_labels):
            widget.bind("<Button-1>", lambda _event, key=item["id"]: self.open(key))
            widget.bind("<Enter>", lambda _event, key=item["id"]: self.hover(key, True), add="+")
            widget.bind("<Leave>", lambda _event, key=item["id"]: self.hover(key, False), add="+")
        self.cards[item["id"]] = card
        self.paint(item["id"])

    # ----- state ----------------------------------------------------------------------
    def incident(self, identifier: str) -> dict | None:
        return self.tracker.incident(self.by_id[identifier])

    def status(self, identifier: str) -> str:
        """Incident status, "Rejected" once closed, or "Watching" for a Low contact without an incident."""
        return self.tracker.status(self.by_id[identifier]) or "Watching"

    def group(self, identifier: str) -> str:
        """critical/high/medium for an open incident, else quiet, watching or closed."""
        item = self.by_id[identifier]
        incident = self.tracker.open_incident(item)
        if incident is not None:
            return incident["level"] if RANK[incident["level"]] >= OPEN_RANK else "quiet"
        return "closed" if self.tracker.incident(item) is not None else "watching"

    def elapsed_min(self) -> float:
        return (time.monotonic() - self.started) / 60

    def counts(self) -> dict[str, int]:
        states = [self.status(item["id"]) for item in self.items]
        return {state: states.count(state) for state in (*STATUSES, "Watching")}

    def log(self, identifier: str, text: str) -> None:
        self.history.setdefault(identifier, []).append((utc_now(), text))

    def decide(self, identifier: str, status: str, text: str, reason: str | None = None,
               to: str | None = None) -> None:
        """Record an analyst decision on the vessel's open incident through ``argus.incidents``."""
        if hasattr(self.app, 'require_tool') and not self.app.require_tool('alert.review'):
            return
        item = self.by_id[identifier]
        if self.tracker.open_incident(item) is None:
            return
        self.tracker.decide(item, status, reason)
        if to:
            self.recipients[identifier] = to
        self.sync_exercise(item, status)
        self.log(identifier, text)
        self.changed(identifier)

    def mark_reviewed(self, identifier: str) -> None:
        if self.status(identifier) != "New":
            return
        item = self.by_id[identifier]
        self.tracker.decide(item, "Reviewed")
        self.sync_exercise(item, "Reviewed")
        self.log(identifier, "Opened for review")
        self.changed(identifier, redraw=False)

    def withdraw(self, identifier: str) -> None:
        """Take back an escalation; the incident stays open as Reviewed."""
        self.recipients.pop(identifier, None)
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
                    self.tracker.decide(item, value)
                    self.log(item["id"], f"{value} in the exercise replay")
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
        if incident and not closed and RANK[incident["peak_level"]] > RANK[incident["level"]]:
            parts.append(f"peak {LEVEL_NAMES[incident['peak_level']]}")
        parts.append(item["line_name"])
        card["status"].configure(text=clip(" · ".join(parts), self.meta_font, width - 50),
                                 fg=ui.INK if status in ("New", "Escalated") else ui.MUTED)
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
        elapsed = self.elapsed_min()
        for key in [identifier] if identifier else self.cards:
            card = self.cards[key]
            item = card["item"]
            texts = card["texts"]
            age = "replay" if item.get("exercise") else age_text(item.get("raised_min_ago", 0) + elapsed)
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
                        - self.tag_font.measure("EXERCISE" if item.get("exercise") else "SIM"))
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
        """Contacts drawn on the map: everything not closed that passes the level filter."""
        return [item for item in self.items if self.group(item["id"]) != "closed" and self.matches_filter(item["id"])]

    def _order(self, identifier: str) -> tuple:
        incident = self.incident(identifier)
        return (not (incident and incident.get("needs_review_again")), sort_key(self.by_id[identifier]))

    def relayout(self, top: bool = False) -> None:
        ui = self.ui
        for widget in self.list.winfo_children():
            widget.pack_forget()
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
        if not shown and self.level_filter != "low":
            self.empty.configure(text="No open incidents at this level." if self.level_filter else "No open incidents.",
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
                 f"{counts['Escalated']} escalated · {counts['Rejected']} rejected")

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
    def open(self, identifier: str, reveal: bool = True) -> None:
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
            self.reveal(item)
        else:
            self.app._draw_map()
        self.app.map_status_label.configure(text=self.describe(identifier))

    def deselect(self) -> None:
        previous, self.selected = self.selected, None
        if previous in self.cards:
            self.paint(previous)
        self.app._draw_map()

    def reveal(self, item: dict, fit: bool = False) -> None:
        """Bring the contact into the map area left of the review window; fit its track when asked."""
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
            for zoom in range(min(maximum, 10), 4, -1):
                xs, ys = zip(*(ui.geo_to_world(lat, lon, zoom) for lat, lon in points))
                if max(xs) - min(xs) <= free - 140 * scaling and max(ys) - min(ys) <= height - 240 * scaling:
                    break
            app.map_zoom = zoom
            centre_x, centre_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        else:
            x, y = app._project(item["lat"], item["lon"])
            inside = left + 40 <= x <= width - right - 40 and 60 <= y <= height - 140
            if inside and app.map_zoom >= 6:
                app._draw_map()
                return
            app.map_zoom = max(app.map_zoom, min(7, maximum))
            centre_x, centre_y = ui.geo_to_world(item["lat"], item["lon"], app.map_zoom)
        centre = (centre_x - (target_x - width / 2), centre_y - (target_y - height / 2))
        app._change_map_center(ui.world_to_geo(*centre, app.map_zoom))

    def restart(self) -> None:
        self.items = build_board(self.app.scenario, self.app.alerts)
        self.by_id = {item["id"]: item for item in self.items}
        for item in self.items:
            self.cards[item["id"]]["item"] = item
            self.cards[item["id"]]["texts"].clear()
        self.started = time.monotonic()
        self.tracker = Tracker()
        self.tracker.step(self.items, 0)
        self.recipients.clear()
        self.history.clear()
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
        self.app.map_status_label.configure(text="Simulation restarted · countdowns, incidents and decisions reset")

    def advance(self, elapsed_s: float) -> dict[str, list[str]]:
        """Score the board at ``elapsed_s`` and fold it into the incidents; log, repaint and flash what changed."""
        changed = update(self.items, elapsed_s)
        events = self.tracker.step(self.items, int(elapsed_s))
        for identifier, found in events.items():
            incident = self.incident(identifier)
            for event in found:
                self.log(identifier, EVENT_TEXT[event].format(id=incident["id"], level=LEVEL_NAMES[incident["level"]]))
        touched = set(changed) | set(events)
        if not touched:
            return events
        for identifier in touched:
            self.paint(identifier)
        self.relayout()
        for identifier, found in events.items():
            if {"opened", "raised", "review_again"} & set(found):
                self.flash(identifier)
        news = [f"{self.by_id[i]['name']} " + ("incident opened" if "opened" in found else
                "review again" if "review_again" in found else "quiet: close?" if "quiet" in found
                else f"now {LEVEL_NAMES[self.incident(i)['level']]}") for i, found in events.items()]
        self.app._draw_map()
        if news:
            self.app.map_status_label.configure(text=" · ".join(news))
        if self.dialog.item and self.dialog.item["id"] in touched:
            self.dialog.refresh()
        return events

    def tick(self) -> None:
        self.timer = None
        try:
            self.advance(time.monotonic() - self.started)
            self.update_live()
            self.dialog.update_live()
            self.pulse_halos()
        finally:
            self.timer = self.app.root.after(1000, self.tick)

    def close(self) -> None:
        for timer in [self.timer, *self.flashing.values()]:
            if timer:
                try:
                    self.app.root.after_cancel(timer)
                except tk.TclError:
                    pass
        self.timer = None
        self.flashing.clear()

    # ----- map ------------------------------------------------------------------------
    def draw(self) -> None:
        app, ui = self.app, self.ui
        self.halos = []
        layer = app.map_layers.get("Simulated alerts")
        if layer is None or not layer.get():
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
                tag = "EXERCISE" if item.get("exercise") else "SIM"
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
        if items:
            text = f"SIMULATED · {len(items)} fictional contact{'s' if len(items) != 1 else ''}"
            label = app.map.create_text(20, 40, text=text, anchor="w", fill=ui.INK, font=(SANS, 9, "bold"),
                                        tags=("sim-badge",))
            left, top, right, bottom = app.map.bbox(label)
            box = app.map.create_rectangle(left - 7, top - 3, right + 7, bottom + 3, fill=ui.BG, outline=ui.LINE,
                                           tags=("sim-badge",))
            app.map.tag_lower(box, label)

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
        self.frame = ctk.CTkFrame(app.chart_host, width=self.WIDTH, height=620, fg_color=ui.CARD,
                                  corner_radius=8, border_width=1, border_color=ui.LINE)
        self.frame.pack_propagate(False)
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
        self.name = tk.Label(self.frame, text="", bg=ui.CARD, fg=ui.INK, font=(SANS, 18, "bold"), anchor="w")
        self.name.pack(fill="x", padx=20, pady=(4, 0))
        self.meta = tk.Label(self.frame, text="", bg=ui.CARD, fg=ui.MUTED, font=(SANS, 10), anchor="w",
                             justify="left")
        self.meta.pack(fill="x", padx=20)
        self.title = tk.Label(self.frame, text="", bg=ui.CARD, fg=ui.INK, font=(SANS, 12), anchor="w",
                              justify="left", wraplength=self.WIDTH - 50)
        self.title.pack(fill="x", padx=20, pady=(8, 0))
        self.flags = tk.Label(self.frame, text="", bg=ui.CARD, fg=STYLE["medium"][0], font=(SANS, 10, "bold"),
                              anchor="w", justify="left", wraplength=self.WIDTH - 50)
        self.flags.pack(fill="x", padx=20, pady=(4, 0))
        self.scale = tk.Canvas(self.frame, height=44, bg=ui.CARD, highlightthickness=0)
        self.scale.pack(fill="x", padx=20, pady=(12, 0))
        self.scale.bind("<Configure>", lambda _event: self.draw_scale())
        facts = tk.Frame(self.frame, bg=ui.CARD)
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

    # ----- layout ---------------------------------------------------------------------
    def place(self) -> None:
        app = self.board.app
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        width = app.chart_host.winfo_width() / scaling
        height = app.chart_host.winfo_height() / scaling
        bottom = 200 if app.exercise_visible.get() else 120
        self.frame.configure(width=max(360, min(self.WIDTH, width - 110)), height=max(380, min(760, height - bottom)))
        self.frame.place(relx=1, x=-70, y=16, anchor="ne")
        self.frame.lift()

    def covered_width(self) -> float:
        scaling = ctk.ScalingTracker.get_widget_scaling(self.frame)
        return (float(self.frame.cget("width")) + 90) * scaling

    # ----- content --------------------------------------------------------------------
    def show(self, item: dict) -> None:
        if self.item is None or self.item["id"] != item["id"]:
            self.mode = None
        self.item = item
        self.visible = True
        self.place()
        self.refresh()

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
        self.tag.configure(text="EXERCISE" if item.get("exercise") else "SIMULATED")
        self.name.configure(text=item["name"])
        meta = [item["vessel_type"]]
        if item.get("length_m"):
            meta.append(f"{item['length_m']:.0f} m")
        meta += [f"SOG {item['sog_kn']:.1f} kn", f"COG {item['cog_deg']:03.0f}°"]
        if not item.get("exercise"):
            minutes = int(item.get("raised_min_ago", 0) + board.elapsed_min())
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
        assessment = item["assessment"]
        wrap = int(float(self.frame.cget("width"))) - 110
        self.heading("INDICATORS", top=4)
        for factor in assessment["factors"]:
            points = factor["points"]
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", pady=2)
            text = f"+{points}" if points > 0 else ("−" + str(-points) if points < 0 else "0")
            tk.Label(row, text=text, width=3, anchor="e", bg=ui.CARD, fg=ui.INK if points else ui.MUTED,
                     font=(MONO, 10, "bold")).pack(side="left", anchor="n")
            tk.Label(row, text=factor["text"], bg=ui.CARD, fg=ui.INK if points else ui.MUTED, font=(SANS, 10),
                     anchor="w", justify="left", wraplength=wrap).pack(side="left", fill="x", expand=True, padx=(10, 0))
        for note in assessment["notes"]:
            row = tk.Frame(self.body, bg=ui.CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="", width=3, bg=ui.CARD, font=(MONO, 10)).pack(side="left")
            tk.Label(row, text=note, bg=ui.CARD, fg=SECONDARY, font=(SANS, 10, "italic"), anchor="w", justify="left",
                     wraplength=wrap).pack(side="left", fill="x", expand=True, padx=(10, 0))
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
            tk.Label(row, text=stamp, bg=ui.CARD, fg=ui.MUTED, font=(MONO, 9)).pack(side="left", anchor="n")
            tk.Label(row, text=text, bg=ui.CARD, fg=SECONDARY, font=(SANS, 10), anchor="w", justify="left",
                     wraplength=wrap - 40).pack(side="left", fill="x", expand=True, padx=(10, 0))
        source = ("Fictional exercise alert from the demo files." if item.get("exercise") else
                  "Simulated contact. Vessel, track and observations are fictional; the route is illustrative.")
        source += (" Brain opens and updates the incident; only a human sets its status." if
                   board.incident(item["id"]) else " Low: watched, not an incident; it opens one if it reaches Medium.")
        tk.Label(self.body, text=source + " Decisions are logged locally and not transmitted.", bg=ui.CARD,
                 fg=ui.MUTED, font=(SANS, 9), anchor="w", justify="left", wraplength=wrap + 40).pack(
            fill="x", padx=(6, 0), pady=(18, 6))

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

    def fill_form(self) -> None:
        ui = self.ui
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
