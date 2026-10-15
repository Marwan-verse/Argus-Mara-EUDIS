"""Vessel report form and analyst incident review for the native console."""
import customtkinter as ctk

from argus.collab_crypto import validate_payload
from argus.vessel_reports import CATEGORIES, make_report
from desktop_soc_view import BG, CARD, MUTED, button, label


def live_snapshot(vessel):
    return {"id": str(vessel["mmsi"]), "name": vessel["name"], "label": vessel["label"],
            "lat": vessel["lat"], "lon": vessel["lon"]}


def board_snapshot(item):
    identifier = str(item["alert"]["mmsi"]) if item.get("exercise") else str(item["id"])
    return {"id": identifier, "name": item["name"], "label": item["label"],
            "lat": item["lat"], "lon": item["lon"]}


def sharing_problem(app):
    """A report is local offline; SOC reports require a fully verified live room."""
    client = app.soc_client
    if client is None:
        return None
    room, cipher = client.room, client.cipher
    if not app.allowed("contact.share"):
        return "Reporting requires contact sharing permission and a SOC connection."
    if (not room or not room.get("locked") or not cipher or not cipher.verified
            or len(room["confirmed"]) != len(room["members"])):
        return "Create or join a Team session and verify every teammate before reporting."
    if "contact.share" not in room.get("permissions", client.user["permissions"]):
        return "Contact sharing must be available to every teammate in this session."
    return None


class ReportDialog:
    def __init__(self, app, vessel):
        self.app, self.vessel = app, dict(vessel)
        self.pending = False
        self.report = None
        self.scope = (app.soc_client, (app.soc_client.room or {}).get("room_id")) if app.soc_client else (None, None)
        self.window = ctk.CTkToplevel(app.root)
        self.window.title("Report vessel")
        self.window.geometry("570x580")
        self.window.minsize(520, 540)
        self.window.configure(fg_color=CARD)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        label(self.window, "Report vessel", 22, True).pack(anchor="w", padx=22, pady=(20, 8))
        label(self.window, f"{vessel['name']} · {vessel['id']}\n{vessel['label']} · Analyst report for review",
              wraplength=510, justify="left").pack(anchor="w", padx=22)
        label(self.window, "Category", text_color=MUTED).pack(anchor="w", padx=22, pady=(16, 4))
        self.category = ctk.CTkOptionMenu(self.window, values=list(CATEGORIES), width=360)
        self.category.pack(fill="x", padx=22)
        label(self.window, "Why are you reporting this vessel? (required, up to 2000 characters)",
              wraplength=510, text_color=MUTED).pack(anchor="w", padx=22, pady=(14, 4))
        self.reason = ctk.CTkTextbox(self.window, height=160)
        self.reason.pack(fill="both", expand=True, padx=22)
        self.problem = label(self.window, "", text_color="#ffb176", wraplength=510, justify="left")
        self.problem.pack(fill="x", padx=22, pady=6)
        scope = "Shared with your verified SOC session." if app.soc_client else "Local report · kept until this app closes."
        label(self.window, scope + " No operational action is triggered.", text_color=MUTED,
              wraplength=510, justify="left").pack(anchor="w", padx=22)
        row = ctk.CTkFrame(self.window, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=18)
        self.cancel = button(row, "Cancel", self.close, width=110)
        self.cancel.pack(side="left")
        self.submit_button = button(row, "Report and share" if app.soc_client else "Create report",
                                    self.submit, True, width=200)
        self.submit_button.pack(side="right")
        self.window.bind("<Escape>", lambda _: self.close())
        self.reason.focus_set()

    def close(self):
        if not self.pending:
            self.window.destroy()

    def submit(self):
        if self.pending:
            return
        app = self.app
        problem = sharing_problem(app)
        if problem:
            self.problem.configure(text=problem)
            return
        scope = (app.soc_client, (app.soc_client.room or {}).get("room_id")) if app.soc_client else (None, None)
        if scope != self.scope:
            self.problem.configure(text="SOC session changed. Reopen this form for the new session.")
            return
        try:
            draft = make_report(self.vessel, self.category.get(), self.reason.get("1.0", "end"))
            # Keep the ID across a manual retry if delivery was uncertain.
            if self.report and all(draft[key] == self.report[key] for key in ("vessel", "category", "reason")):
                draft = self.report
            validate_payload("report", draft)
            self.report = draft
        except ValueError as error:
            self.problem.configure(text=str(error))
            return
        if app.soc_client is None:
            self.saved("Local analyst", False)
            return
        soc = app.soc
        if soc.busy or soc.pending or soc.stopping:
            self.problem.configure(text="A SOC request is finishing. Your draft is saved; try again in a moment.")
            return
        self.pending = True
        self.submit_button.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self.category.configure(state="disabled")
        self.reason.configure(state="disabled")
        self.problem.configure(text="Sharing report with your SOC session…")
        soc.send_message("report", self.report, lambda: self.saved(app.soc_client.user["username"], True))
        self.window.after(100, self.check_delivery)

    def check_delivery(self):
        if not self.window.winfo_exists():
            return
        if self.app.soc.busy:
            self.window.after(100, self.check_delivery)
            return
        self.pending = False
        self.submit_button.configure(state="normal")
        self.cancel.configure(state="normal")
        self.category.configure(state="normal")
        self.reason.configure(state="normal")
        self.problem.configure(text=self.app.soc.last_status + " Delivery may be uncertain; check with your team before retrying.")

    def saved(self, sender, shared):
        self.app.vessel_reports.add(self.report, sender, shared=shared)
        self.app.alert_board.refresh_reports()
        if not self.app.tools.alerts_visible:
            self.app.tools.toggle_alerts()
        self.app.map_status_label.configure(text="Vessel report added to Incidents" + (" · shared with SOC session" if shared else " · local"))
        self.window.destroy()


def open_report(app, vessel):
    current = getattr(app, "report_dialog", None)
    if current and current.window.winfo_exists():
        current.window.lift()
        return current
    app.report_dialog = ReportDialog(app, vessel)
    return app.report_dialog


def review_reports(app, entries):
    window = ctk.CTkToplevel(app.root)
    window.title("Reported vessel incident")
    window.geometry("620x600")
    window.configure(fg_color=CARD)
    window.transient(app.root)
    vessel = entries[-1]["report"]["vessel"]
    label(window, vessel["name"], 22, True).pack(anchor="w", padx=20, pady=(18, 8))
    label(window, f"{vessel['id']} · {vessel['label']}\nAnalyst reports · unverified concerns · human review required",
          wraplength=560, justify="left", text_color=MUTED).pack(anchor="w", padx=20)
    body = ctk.CTkScrollableFrame(window, fg_color=BG)
    body.pack(fill="both", expand=True, padx=16, pady=12)
    for entry in reversed(entries):
        report = entry["report"]
        source = "SOC session" if entry["shared"] else "Local"
        text = (f"{report['category']}\n{entry['sender']} · {report['created_utc']} · {source}\n"
                f"Reported position: {report['vessel']['lat']:.5f}, {report['vessel']['lon']:.5f}\n\n{report['reason']}")
        label(body, text, wraplength=530, justify="left").pack(anchor="w", fill="x", padx=10, pady=12)
    button(window, "Close", window.destroy).pack(pady=(0, 16))
