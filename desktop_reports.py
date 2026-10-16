"""Vessel report form and analyst incident review for the native console."""
import threading

import customtkinter as ctk

from argus import responders
from argus.collab_crypto import validate_payload
from argus import report_ai
from argus.report_ai import build_pack, check_all, draft_report
from argus.vessel_reports import CATEGORIES, make_report
from desktop_soc_view import BG, CARD, MUTED, button, label

WARN = "#ffb176"


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


def board_context(board, item):
    """Incident, status and who can reach it, as the Incidents panel shows them (replay clock)."""
    identifier = item["id"]
    now = board.replay.now
    context = {"replay_time": None if now is None else board.stamp(int(now)), "status": board.status(identifier)}
    if not item.get("exercise") and now is not None:
        context["raised_min"] = max(0, int(board.age_min(item)))
    incident = board.incident(identifier)
    if incident:
        context["incident"] = {"id": incident["id"], "status": incident["status"],
                               "peak_level": incident["peak_level"], "opened": board.stamp(int(incident["opened_t"])),
                               "status_reason": incident.get("status_reason")}
    result = board.response(identifier)
    if result:
        text, warn = responders.summary_line(result)
        deadline = result.get("deadline_s")
        context["responders"] = {"text": text, "warn": warn,
                                 "deadline": None if deadline is None or result.get("at_line") else board.stamp(int(deadline))}
    return context


def evidence_pack(app, vessel, item=None):
    """What the system holds on the reported vessel: the Brain item and panel, else its live AIS record."""
    try:
        board = getattr(app, "alert_board", None)
        if item is not None:
            current = board.by_id.get(item["id"], item) if board is not None else item
            return build_pack(vessel, current, board_context(board, current) if board is not None else {})
        tracker = getattr(app, "ais_tracker", None)
        live = tracker.state.vessels.get(vessel["id"]) if tracker is not None else None
        return build_pack(vessel, live=live)
    except (KeyError, TypeError, ValueError, AttributeError):
        # A report never depends on the evidence: fall back to the vessel snapshot alone.
        return build_pack(vessel)


class ReportDialog:
    def __init__(self, app, vessel, item=None):
        self.app, self.vessel = app, dict(vessel)
        self.pending = False
        self.busy = False
        self.report = None
        self.generation = None
        self.scope = (app.soc_client, (app.soc_client.room or {}).get("room_id")) if app.soc_client else (None, None)
        self.pack = evidence_pack(app, self.vessel, item)
        self.window = ctk.CTkToplevel(app.root)
        self.window.title("Report vessel")
        self.window.geometry("640x800")
        self.window.minsize(580, 700)
        self.window.configure(fg_color=CARD)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        label(self.window, "Report vessel", 22, True).pack(anchor="w", padx=22, pady=(20, 8))
        label(self.window, f"{vessel['name']} · {vessel['id']}\n{vessel['label']} · Analyst report for review",
              wraplength=580, justify="left").pack(anchor="w", padx=22)
        label(self.window, f"Evidence: {self.pack['summary']}", text_color=MUTED, wraplength=580,
              justify="left").pack(anchor="w", padx=22, pady=(4, 0))
        label(self.window, "Category", text_color=MUTED).pack(anchor="w", padx=22, pady=(12, 4))
        self.category = ctk.CTkOptionMenu(self.window, values=list(CATEGORIES), width=360)
        self.category.pack(fill="x", padx=22)
        label(self.window, "Why are you reporting this vessel? (required, up to 2000 characters)",
              wraplength=580, text_color=MUTED).pack(anchor="w", padx=22, pady=(12, 4))
        # Undo lets the analyst take back a draft that replaced their own text (Ctrl+Z).
        self.reason = ctk.CTkTextbox(self.window, height=200, wrap="word", undo=True)
        self.reason.pack(fill="both", expand=True, padx=22)
        tools = ctk.CTkFrame(self.window, fg_color="transparent")
        tools.pack(fill="x", padx=22, pady=(10, 0))
        self.draft_button = button(tools, "Draft with AI", self.draft, width=150)
        self.draft_button.pack(side="left")
        self.check_button = button(tools, "Check report", self.check, width=140)
        self.check_button.pack(side="left", padx=(8, 0))
        self.pdf_button = button(tools, "Save PDF", self.save_pdf, width=120)
        self.pdf_button.pack(side="left", padx=(8, 0))
        self.notes = ctk.CTkTextbox(self.window, height=150, wrap="word", fg_color=BG, text_color=MUTED)
        self.notes.pack(fill="x", padx=22, pady=(8, 0))
        self.show_notes("Draft with AI writes a draft from the evidence for you to edit. Check report compares "
                        "your text with the system data. Nothing is sent until you create or share the report.")
        self.problem = label(self.window, "", text_color=WARN, wraplength=580, justify="left")
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

    def show_notes(self, text):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def run(self, message, work, done):
        """Run ``work`` off the Tk thread so the window stays responsive; ``done`` gets its result on it."""
        if self.busy or self.pending:
            return
        self.busy = True
        for widget in (self.draft_button, self.check_button, self.pdf_button, self.submit_button):
            widget.configure(state="disabled")
        self.problem.configure(text=message, text_color=MUTED)
        box = {}

        def worker():
            try:
                box["result"] = work()
            except Exception as error:  # reported in the window; the form itself keeps working
                box["error"] = error

        thread = threading.Thread(target=worker, name="argus-report-ai", daemon=True)
        thread.start()
        self.app.root.after(50, lambda: self.finish(thread, box, done))

    def finish(self, thread, box, done):
        if not self.window.winfo_exists():
            return
        if thread.is_alive():
            self.app.root.after(50, lambda: self.finish(thread, box, done))
            return
        self.busy = False
        for widget in (self.draft_button, self.check_button, self.pdf_button, self.submit_button):
            widget.configure(state="normal")
        self.problem.configure(text="", text_color=WARN)
        if "error" in box:
            self.problem.configure(text=f"Could not finish: {box['error']}")
            return
        done(box["result"])

    def draft(self):
        self.run("Drafting from the evidence… (AI when a key and budget allow)", lambda: draft_report(self.pack),
                 self.drafted)

    def drafted(self, result):
        # One undo step: Ctrl+Z brings back exactly the text the draft replaced.
        self.reason.configure(autoseparators=False)
        self.reason.edit_separator()
        self.reason.delete("1.0", "end")
        self.reason.insert("1.0", result["text"])
        self.reason.edit_separator()
        self.reason.configure(autoseparators=True)
        self.category.set(result["category"])
        meta = result.get("ai") or {}
        self.generation = {"method": result["method"], "model": result.get("model"),
                           "generated_utc": result["generated_utc"], "evidence": result["evidence"],
                           "cost_usd": meta.get("cost_usd"), "cached": meta.get("cached"),
                           "fallback": result.get("fallback")}
        if result["method"] == "ai":
            head = (f"AI-assisted draft by {result['model']}. Code checked it against the evidence: times, "
                    "positions, numbers, names, IDs, level, intent words and data label.")
        else:
            head = f"Template draft from system data, no AI used: {result['fallback']}."
        lines = [head, *result.get("notes", ()),
                 f"Category set to the suggestion: {result['category']}. Change it if you disagree.",
                 f"Evidence used: {', '.join(result['evidence'])}."]
        if meta:
            lines.append(self.cost_line(meta))
        lines.append("Edit the text before you send it; Ctrl+Z restores your previous text.")
        self.show_notes("\n".join(lines))

    def cost_line(self, meta):
        spent = report_ai.budget()
        total = "" if spent["reserved_usd"] is None else (
            f" · report AI budget ${spent['reserved_usd']:.4f} of ${spent['limit_usd']:g} used")
        cost = "from cache, no cost" if meta.get("cached") else f"cost ${meta['cost_usd']:.4f} (provider usage)"
        return f"{meta['model']} · {cost}{total}"

    def check(self):
        text, category = self.reason.get("1.0", "end"), self.category.get()
        self.run("Checking the report against the system data…", lambda: check_all(self.pack, text, category),
                 self.checked)

    @staticmethod
    def finding_lines(findings):
        lines = []
        for number, finding in enumerate(findings, 1):
            quote = f" “{finding['quote']}”" if finding["quote"] else ""
            evidence = f"  Evidence: {', '.join(finding['evidence'])}" if finding["evidence"] else ""
            lines.append(f"{number}. {finding['kind'].capitalize()}{quote}: {finding['problem']}\n"
                         f"   Fix: {finding['fix']}{evidence}")
        return lines

    def checked(self, result):
        code, ai = result["code"], result["ai"]
        lines = ["CODE CHECK (exact, no AI)"]
        if code["consistent"]:
            lines.append("Report is consistent with system data.")
        lines += self.finding_lines(code["findings"]) + code["notes"]
        if "unavailable" in ai:
            lines += ["", f"AI CHECK (meaning) not run: {ai['unavailable']}."]
        else:
            lines += ["", f"AI CHECK (meaning, {ai['meta']['model']}) · findings are suggestions for the analyst"]
            if ai["consistent"]:
                lines.append("No meaning problems found.")
            lines += self.finding_lines(ai["findings"])
            if ai["rejected"]:
                lines.append(f"{len(ai['rejected'])} AI finding(s) dropped by validation: "
                             f"{', '.join(sorted(set(ai['rejected'])))}.")
            lines.append(self.cost_line(ai["meta"]))
        self.show_notes("\n".join(lines))

    def save_pdf(self):
        self.show_notes("Save PDF is coming in the next step: the export with the evidence appendix is not built yet.")

    def submit(self):
        if self.pending or self.busy:
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
        self.pending = True
        self.submit_button.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self.category.configure(state="disabled")
        self.reason.configure(state="disabled")
        self.problem.configure(text="Report queued; waiting for the current SOC request…" if soc.pending else
                               "Sharing report with your SOC session…", text_color=MUTED)
        sender = app.soc_client.user["username"]
        accepted = soc.send_message("report", self.report, lambda: self.saved(sender, True),
                                    expected_room=self.scope[1])
        if not accepted:
            self.delivery_failed(soc.last_status)
            return
        self.window.after(100, self.check_delivery)

    def check_delivery(self):
        if not self.window.winfo_exists():
            return
        if self.app.soc.busy:
            self.window.after(100, self.check_delivery)
            return
        self.delivery_failed(self.app.soc.last_status + " Delivery may be uncertain; check with your team before retrying.")

    def delivery_failed(self, text):
        self.pending = False
        self.submit_button.configure(state="normal")
        self.cancel.configure(state="normal")
        self.category.configure(state="normal")
        self.reason.configure(state="normal")
        self.problem.configure(text=text, text_color="#ffb176")

    def saved(self, sender, shared):
        self.app.vessel_reports.add(self.report, sender, shared=shared)
        self.app.alert_board.refresh_reports()
        if not self.app.tools.alerts_visible:
            self.app.tools.toggle_alerts()
        self.app.map_status_label.configure(text="Vessel report added to Incidents" + (" · shared with SOC session" if shared else " · local"))
        self.window.destroy()


def open_report(app, vessel, item=None):
    """``item`` is the Brain board item when the report starts from the review window."""
    current = getattr(app, "report_dialog", None)
    if current and current.window.winfo_exists():
        current.window.lift()
        return current
    app.report_dialog = ReportDialog(app, vessel, item)
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
