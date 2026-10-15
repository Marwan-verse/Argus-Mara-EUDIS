"""Native group collaboration and administrator controls."""
from concurrent.futures import ThreadPoolExecutor
import queue
import os
import re
import time
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from argus import soc_session
from argus.collab_client import ClientError, SOCClient
from argus.collab_crypto import KINDS

SHARED_CODE = re.compile(r"code from\s+([^\s:]+)\s+to\s+([^\s:]+)\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


def shareable_code(sender, recipient, code):
    """Clipboard text that names both people, so a pasted code can be checked for its direction."""
    return f"Argus Mara code from {sender} to {recipient}: {code}"


def received_code(text, own, peer):
    """The code to compare from typed or pasted text; refuse a code sent by oneself or another pair."""
    match = SHARED_CODE.search(text)
    if not match:
        return text
    sender, recipient, code = match.groups()
    if sender.lower() == own.lower():
        raise ValueError(f"That is your own code. Paste the code {peer} sends you.")
    if sender.lower() != peer.lower() or recipient.lower() != own.lower():
        raise ValueError(f"This code is from {sender} to {recipient}, not from {peer} to you.")
    return code


def login_screen(root, initial_url, on_login, *, allow_loopback_http=False,
                 on_offline=None, local_launcher=False, remember=False):
    """No protected app is constructed until HTTPS authentication succeeds.

    With remember, a sign-in saved on this computer is tried first and the
    "Stay signed in" box is offered; a second local demo window passes False.
    """
    root.title("Argus Mara · SOC sign in")
    height = (620 if local_launcher else 430) + (40 if remember else 0)
    root.geometry(f"{620 if local_launcher else 580}x{height}")
    frame = ctk.CTkFrame(root)
    frame.pack(fill="both", expand=True, padx=24, pady=24)
    ctk.CTkLabel(frame, text="SOC sign in", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(12, 8))
    fields = {}
    for key, title in (("url", "SOC HTTPS address"), ("username", "Username"), ("password", "Password")):
        ctk.CTkLabel(frame, text=title).pack(anchor="w", padx=16)
        entry = ctk.CTkEntry(frame, show="•" if key == "password" else "")
        entry.pack(fill="x", padx=16, pady=(0, 8))
        fields[key] = entry
    fields["url"].insert(0, initial_url or "")
    remember_box = None
    if remember:
        remember_box = ctk.CTkCheckBox(frame, text="Stay signed in on this computer (up to 8 hours)")
        remember_box.select()
        remember_box.pack(anchor="w", padx=16, pady=(0, 6))
    welcome = "No account yet? Create one; an administrator approves new accounts."
    status = ctk.CTkLabel(frame, text=welcome, wraplength=480)
    status.pack(padx=16, pady=4)
    executor = ThreadPoolExecutor(max_workers=1)
    events = queue.Queue()
    busy = False
    closed = False
    cancelled = threading.Event()
    ca_file = os.environ.get('ARGUS_SOC_CA_FILE') or None
    controls = []

    def set_busy(value):
        nonlocal busy
        busy = value
        for control in controls:
            control.configure(state="disabled" if value else "normal")

    def submit():
        nonlocal busy
        if busy:
            return
        try:
            client = SOCClient(fields["url"].get().strip(), allow_loopback_http=allow_loopback_http,
                               ca_file=ca_file)
        except (ValueError, OSError) as error:
            status.configure(text=str(error))
            return
        username, secret = fields["username"].get().strip(), fields["password"].get()
        fields["password"].delete(0, "end")
        keep = bool(remember_box.get()) if remember_box else None
        set_busy(True)
        status.configure(text="Signing in securely…")

        def job():
            try:
                client.login(username, secret)
                if keep:
                    client.remember = soc_session.save(client)
                elif keep is False:
                    soc_session.forget()
                events.put(("login", client, None))
            except Exception as error:
                events.put(("login", None, str(error)))
        executor.submit(job)

    def resume():
        set_busy(True)
        status.configure(text="Looking for a sign-in saved on this computer…")

        def job():
            saved = soc_session.load()
            if not saved or (initial_url and initial_url.rstrip("/") != saved["url"]):
                events.put(("resume", None, welcome))
                return
            try:
                client = SOCClient(saved["url"], allow_loopback_http=allow_loopback_http, ca_file=saved.get("ca_file"))
                client.resume(saved["token"])
                client.remember = True
                events.put(("login", client, None))
            except ClientError as error:
                if error.status == 401:
                    soc_session.forget()
                    events.put(("resume", saved, "Your saved sign-in has expired. Sign in again."))
                else:
                    events.put(("resume", saved, f"{error} Sign in again or retry later."))
            except (ValueError, OSError) as error:
                events.put(("resume", saved, f"The saved sign-in could not be used: {error}"))
        executor.submit(job)

    signup = {}

    def create_account():
        dialog = signup.get("dialog")
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return
        if busy:
            return
        dialog = ctk.CTkToplevel(root)
        dialog.title("Create an Argus Mara account")
        dialog.geometry("440x390")
        dialog.resizable(False, False)
        dialog.transient(root)
        entries = {}
        for key, title in (("username", "Username"), ("password", "Password (at least 14 characters)"),
                           ("repeat", "Repeat password")):
            ctk.CTkLabel(dialog, text=title).pack(anchor="w", padx=20, pady=(12 if key == "username" else 0, 0))
            entry = ctk.CTkEntry(dialog, show="" if key == "username" else "•")
            entry.pack(fill="x", padx=20, pady=(0, 6))
            entries[key] = entry
        entries["username"].insert(0, fields["username"].get().strip())
        note = ctk.CTkLabel(dialog, text="An administrator approves new accounts before they can sign in. "
                                         "The account is created on the server in the sign-in screen's address field.",
                            wraplength=390, justify="left")
        note.pack(anchor="w", padx=20, pady=6)
        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(row, text="Cancel", width=110, fg_color="transparent", border_width=1,
                      command=dialog.destroy).pack(side="left")
        send = ctk.CTkButton(row, text="Request account", width=170, command=request_account)
        send.pack(side="right")
        entries["repeat"].bind("<Return>", lambda _: request_account())
        signup.update(dialog=dialog, entries=entries, note=note, send=send)
        entries["username"].focus_set()

    def request_account():
        entries, note = signup["entries"], signup["note"]
        username, secret = entries["username"].get().strip(), entries["password"].get()
        if secret != entries["repeat"].get():
            note.configure(text="The two passwords differ. Type them again.")
            for key in ("password", "repeat"):
                entries[key].delete(0, "end")
            return
        try:
            client = SOCClient(fields["url"].get().strip(), allow_loopback_http=allow_loopback_http, ca_file=ca_file)
        except (ValueError, OSError) as error:
            note.configure(text=f"{error} (first field of the sign-in screen).")
            return
        for key in ("password", "repeat"):
            entries[key].delete(0, "end")
        signup["send"].configure(state="disabled")
        note.configure(text="Sending your request…")

        def job():
            try:
                client.signup(username, secret)
                events.put(("signup", username, None))
            except Exception as error:
                events.put(("signup", None, str(error)))
        executor.submit(job)

    def launch_local():
        if busy:
            return
        set_busy(True)
        status.configure(text="Preparing local two-window demo…")

        def job():
            from argus.soc_launcher import start_local
            try:
                result = start_local(lambda text: events.put(("progress", text, None)), cancelled)
                events.put(("local", result, None))
            except Exception as error:
                events.put(("local", None, str(error)))
        executor.submit(job)

    def offline():
        nonlocal closed
        if busy:
            return
        closed = True
        cancelled.set()
        executor.shutdown(wait=False, cancel_futures=True)
        frame.destroy()
        on_offline()

    def check():
        nonlocal busy, closed, ca_file
        if closed:
            return
        try:
            kind, result, error = events.get_nowait()
        except queue.Empty:
            root.after(100, check)
            return
        if kind == "progress":
            status.configure(text=result)
            root.after(100, check)
        elif kind == "resume":
            # No usable saved sign-in: fill in what it remembered and ask for the password.
            set_busy(False)
            for key in ("url", "username"):
                if result and result.get(key) and not fields[key].get():
                    fields[key].insert(0, result[key])
            status.configure(text=error)
            root.after(100, check)
        elif kind == "signup":
            dialog = signup.get("dialog")
            dialog_open = dialog is not None and dialog.winfo_exists()
            if error and dialog_open:
                signup["note"].configure(text=error)
                signup["send"].configure(state="normal")
            elif error:
                status.configure(text=error)
            else:
                if dialog_open:
                    dialog.destroy()
                fields["username"].delete(0, "end")
                fields["username"].insert(0, result)
                status.configure(text=f"Account {result} requested. When an administrator approves it, sign in here.")
            root.after(100, check)
        elif error:
            set_busy(False)
            status.configure(text=error)
            root.after(100, check)
        elif kind == "local":
            from argus.soc_launcher import open_second_client
            url, ca_file = result
            fields["url"].configure(state="normal")
            fields["url"].delete(0, "end")
            fields["url"].insert(0, url)
            try:
                open_second_client(url, ca_file)
                status.configure(text="Local server ready. Sign in separately in each window as Mykhailo / Igor. "
                                      "Passwords: data/soc-local/demo.env")
                # Exactly two windows per launch screen, including this one.
                local_button.pack_forget()
            except OSError:
                status.configure(text="Server ready, but the second window could not open. Retry or open another client manually.")
            set_busy(False)
            root.after(100, check)
        else:
            closed = True
            executor.shutdown(wait=False)
            frame.destroy()
            on_login(result)

    def close():
        nonlocal closed
        closed = True
        cancelled.set()
        executor.shutdown(wait=False, cancel_futures=True)
        # Cancel Tcl timers before a root window deletes their commands.
        # Attached sign-in dialogs share the app interpreter and its timers.
        if isinstance(root, ctk.CTk):
            for callback in root.tk.call('after', 'info'):
                root.tk.call('after', 'cancel', callback)
        root.destroy()

    actions = ctk.CTkFrame(frame, fg_color="transparent")
    actions.pack(pady=8)
    button = ctk.CTkButton(actions, text="Sign in", command=submit)
    button.pack(side="left", padx=4)
    signup_button = ctk.CTkButton(actions, text="Create account", fg_color="transparent", border_width=1,
                                  command=create_account)
    signup_button.pack(side="left", padx=4)
    controls.extend([button, signup_button, *fields.values()] + ([remember_box] if remember_box else []))
    if local_launcher:
        local_button = ctk.CTkButton(frame, text="Start local server + two sign-in windows", command=launch_local)
        local_button.pack(fill="x", padx=16, pady=(16, 4))
        controls.append(local_button)
        ctk.CTkLabel(frame, text="Two windows on this PC. For separate devices, sign in to your shared HTTPS server.",
                     wraplength=480).pack(padx=16, pady=4)
    if on_offline:
        offline_button = ctk.CTkButton(frame, text="Continue offline · one window · no Docker", command=offline)
        offline_button.pack(fill="x", padx=16, pady=8)
        controls.append(offline_button)
    fields["password"].bind("<Return>", lambda _: submit())
    root.protocol("WM_DELETE_WINDOW", close)
    if remember:
        resume()
    root.after(100, check)


class DesktopSOC:
    def __init__(self, app):
        self.app = app
        self.client = app.soc_client
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.pending = 0
        self.busy = 0
        self.window = None
        self.login_window = None
        self.stopping = False
        self.history = []
        self.verified_peers = set()
        self.last_poll = 0
        self._tick_after = None
        self.last_status = "Sign in to communicate" if not self.client else "Signed in · create or join a session"
        self._tick_after = self.app.root.after(250, self.tick)

    def task(self, function, callback=None, background=False):
        if self.stopping or self.pending >= 8:
            self.status("Please wait for the current request")
            return
        self.pending += 1
        if not background:
            self.busy += 1
        self.render()
        def job():
            try:
                self.events.put((callback, function(), None, background))
            except Exception as error:
                self.events.put((callback, None, error, background))
        self.executor.submit(job)

    def tick(self):
        if self.stopping:
            return
        if self._tick_after:
            try:
                self.app.root.after_cancel(self._tick_after)
            except tk.TclError:
                pass
        self._tick_after = None
        while True:
            try:
                callback, result, error, background = self.events.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            if not background:
                self.busy -= 1
            if error:
                self.status(str(error))
                if isinstance(error, ClientError) and error.status == 401:
                    soc_session.forget()
                    messagebox.showinfo("Sign in required", "Your access expired or was revoked. Sign in again.", parent=self.app.root)
                    self.app.close()
                    return
                if self.client and self.client.room is None:
                    self.history.clear()
                    self.verified_peers.clear()
                if isinstance(error, ClientError) and error.status is None:
                    self.app.soc_online = False
            else:
                self.app.soc_online = True
                if callback:
                    callback(result)
        if self.client and self.pending == 0 and time.monotonic() - self.last_poll >= 1.5:
            self.last_poll = time.monotonic()
            self.task(self.client.poll, self.receive, background=True)
        self.render()
        self._tick_after = self.app.root.after(100, self.tick)

    def status(self, text):
        self.last_status = text
        if self.window and self.window.winfo_exists():
            self.status_label.configure(text=text)

    def receive(self, messages):
        for message in messages:
            payload, kind = message["payload"], message["kind"]
            sender = message.get('sender', 'Peer')
            if kind == "ping":
                self.app._place_map_ping((payload["lat"], payload["lon"]), share=False)
                self.app.map_status_label.configure(text="Peer ping · analyst annotation · not a sensor alert")
                text = f"{sender} ping: {payload['lat']:.5f}, {payload['lon']:.5f}"
            else:
                text = f"{sender} · {'Message' if kind == 'chat' else kind.title()}\n{payload['text']}"
            self.history.append(text)
        self.history = self.history[-100:]
        self.render()

    def open(self):
        if not self.client:
            if self.login_window and self.login_window.winfo_exists():
                self.login_window.lift()
                return
            window = ctk.CTkToplevel(self.app.root)
            self.login_window = window
            window.transient(self.app.root)
            def attached(client):
                self.client = self.app.soc_client = client
                self.app.soc_online = True
                self.app.soc_mode_label.configure(text=f"SOC · {client.user['username']}")
                window.destroy()
                self.open()
            login_screen(window, "", attached)
            return
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        from desktop_soc_view import build
        build(self)
        self.render()

    def reset(self, result=None):
        self.history.clear()
        self.verified_peers.clear()
        self.status('Session ready. Verify your teammates.' if self.client.room and self.client.room.get('locked') else 'Connected. Invite your teammates.')
        self.render()

    def create(self):
        scope = self.group.get()
        group = None if scope == 'Team session (all groups)' else scope.removeprefix('Private: ')
        self.task(lambda: self.client.create(group), self.reset)

    def join(self, code):
        if len(code.replace('-', '').replace(' ', '')) != 8:
            self.status('Enter the 8-character invitation, for example ABCD-EFGH.')
            return
        self.task(lambda: self.client.join(code), self.reset)

    def copy_invite(self):
        if not self.client.code:
            return
        code = self.client.code
        self.window.clipboard_clear()
        self.window.clipboard_append(code[:4] + '-' + code[4:])
        self.status('Invitation copied. Send it to your teammate; it expires after 10 minutes.')

    def leave(self):
        if messagebox.askyesno('Leave session', 'Leaving ends this session for everyone. Continue?', parent=self.window):
            self.task(self.client.leave, lambda _: self.reset())

    def sign_out(self):
        if not messagebox.askyesno('Sign out', 'Sign out and remove the saved sign-in from this computer?', parent=self.window):
            return
        soc_session.forget()
        self.client.remember = False  # Closing now revokes the sign-in on the server.
        self.app.close()

    def confirmed(self, _=None):
        self.status('Your teammates are verified. Waiting for their confirmation.')
        self.render()

    def compare_peer(self, user_id):
        cipher, room = self.client.cipher, self.client.room
        if not cipher or not cipher.room_id or user_id not in cipher.safety_codes:
            self.status('Wait for the host to start the secure chat.')
            return
        member = next(m for m in room['members'] if m['user_id'] == user_id)
        room_id = room['room_id']
        from desktop_soc_view import label, button, BG, CARD, MUTED
        dialog = ctk.CTkToplevel(self.window)
        dialog.title('Verify ' + member['username'])
        dialog.geometry('610x500')
        dialog.resizable(False, False)
        dialog.configure(fg_color=CARD)
        dialog.transient(self.window)
        dialog.grab_set()
        label(dialog, 'Compare with ' + member['username'], 21, True).pack(padx=24, pady=(22, 8))
        own, peer = self.client.user['username'], member['username']
        code = cipher.safety_codes[user_id]
        # Copied with both names, so pasting one's own code back is caught below.
        shared = shareable_code(own, peer, code)
        def copy_code():
            dialog.clipboard_clear()
            dialog.clipboard_append(shared)
        copy_code()
        label(dialog, f"Your code is copied. Send it to {peer} in another app, such as Signal or WhatsApp, "
                      f"or read it aloud. Then paste or type the code {peer} sends you. Not through this chat.",
              wraplength=545, justify='left', text_color=MUTED).pack(padx=24, pady=8)
        label(dialog, 'Your code', text_color=MUTED).pack(padx=24, pady=(8, 0))
        mine = ctk.CTkFrame(dialog, fg_color='transparent')
        mine.pack(pady=(2, 10))
        label(mine, code, font=ctk.CTkFont('Consolas', 19, 'bold')).pack(side='left', padx=(0, 10))
        button(mine, 'Copy again', copy_code, width=100).pack(side='left')
        label(dialog, f"Code from {peer}", text_color=MUTED).pack(padx=24)
        theirs = ctk.CTkFrame(dialog, fg_color='transparent')
        theirs.pack(pady=(2, 4))
        entry = ctk.CTkEntry(theirs, width=420, height=38, font=ctk.CTkFont('Consolas', 15),
                             placeholder_text=f"Paste or type the code {peer} sends you")
        entry.pack(side='left', padx=(0, 8))
        def paste():
            try:
                pasted = dialog.clipboard_get()
            except tk.TclError:
                return
            entry.delete(0, 'end')
            entry.insert(0, pasted.strip())
        button(theirs, 'Paste', paste, width=80).pack(side='left')
        problem = label(dialog, '', text_color='#ff7b72', wraplength=545, justify='left')
        problem.pack(padx=24, pady=4)
        row = ctk.CTkFrame(dialog, fg_color='transparent')
        row.pack(fill='x', padx=24, pady=12)
        def check(_=None):
            current = self.client.cipher
            if current is not cipher or not self.client.room or self.client.room['room_id'] != room_id:
                dialog.destroy()
                self.status('Session changed. Verify the new session instead.')
                return
            try:
                received = received_code(entry.get(), own, peer)
            except ValueError as error:
                problem.configure(text=str(error))
                return
            if not cipher.verify_peer(user_id, received):
                problem.configure(text='The codes differ. Check the code again together. If it still differs, '
                                       'do not chat: someone may be intercepting. Leave the session.')
                return
            self.verified_peers.add(user_id)
            dialog.destroy()
            self.render()
            if set(cipher.safety_codes) <= self.verified_peers:
                self.task(self.client.confirm, self.confirmed)
        entry.bind('<Return>', check)
        button(row, 'Cancel', dialog.destroy, width=130).pack(side='left')
        button(row, 'Check code', check, True, width=220).pack(side='right')
        self.verify_window, self.verify_entry, self.verify_problem, self.verify_check = dialog, entry, problem, check
        self.verify_paste = paste
        entry.focus_set()

    def render(self):
        from desktop_soc_view import render
        render(self)

    def send_message(self, kind, payload, on_success=None):
        permissions = (self.client.room or {}).get('permissions', self.client.user['permissions'])
        if KINDS.get(kind) not in permissions:
            self.status('This tool is not available to everyone in the session.')
            return
        def done(_):
            self.history.append(f"You · {kind.title()}\n{payload.get('text', payload)}")
            self.history = self.history[-100:]
            if on_success:
                on_success()
            self.status('Message sent.' if kind == 'chat' else 'Shared with your team.')
            self.render()
        self.task(lambda: self.client.send(kind, payload), done)

    def send_text(self):
        if self.busy:
            self.status('A request is finishing. Your draft is saved; try again in a moment.')
            return
        draft = self.message.get('1.0', 'end').strip()
        if not draft:
            self.status('Write a message first.')
            return
        def sent():
            if self.window and self.window.winfo_exists() and self.message.get('1.0', 'end').strip() == draft:
                self.message.delete('1.0', 'end')
        self.send_message('chat', {'text': draft}, sent)

    def enter_message(self, event):
        if event.state & 1:
            return None
        self.send_text()
        return 'break'

    def share_ping(self, point):
        if self.client and self.client.cipher and self.client.cipher.verified and self.client.room and self.client.room.get('locked') and len(self.client.room['confirmed']) == len(self.client.room['members']):
            self.send_message("ping", {"lat": point[0], "lon": point[1]})

    def share_contact(self):
        tracker = self.app.ais_tracker
        vessel = tracker.state.vessels.get(tracker.selected)
        if not vessel:
            self.status("Select an AIS contact first")
            return
        import json
        self.send_message("contact", {"text": json.dumps({k: vessel.get(k) for k in ("mmsi", "name", "lat", "lon", "sog_kn", "cog_deg", "received_utc", "label")}, ensure_ascii=False)})

    def share_evidence(self):
        self.send_message('evidence', {'text': self.app._evidence_text()[:4000]})

    def build_admin(self, frame):
        self.admin_frame = frame
        self.admin_data = None
        ttk.Button(frame, text="Refresh users / groups", command=self.refresh_admin).pack(anchor="w")
        self.user_selector = ttk.Combobox(frame, state="readonly")
        self.user_selector.pack(fill="x", pady=5)
        self.user_selector.bind("<<ComboboxSelected>>", lambda _: self.select_user())
        self.pending_label = ttk.Label(frame, text="", wraplength=620, justify="left")
        self.pending_label.pack(anchor="w")
        self.admin_username = ttk.Entry(frame)
        self.admin_username.pack(fill="x", pady=4)
        ttk.Label(frame, text="Username (new accounts only)").pack(anchor="w")
        self.admin_password = ttk.Entry(frame, show="•")
        self.admin_password.pack(fill="x", pady=4)
        ttk.Label(frame, text="Password: 14+ characters; leave blank to keep it when updating").pack(anchor="w")
        self.memberships = ttk.Frame(frame)
        self.memberships.pack(fill="x", pady=5)
        self.disabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Disable account and revoke access", variable=self.disabled).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="Create account", command=lambda: self.save_user(True)).pack(side="left")
        ttk.Button(row, text="Update selected / revoke sessions", command=lambda: self.save_user(False)).pack(side="left", padx=4)
        ttk.Separator(frame).pack(fill="x", pady=12)
        self.group_selector = ttk.Combobox(frame)
        self.group_selector.pack(fill="x", pady=4)
        self.group_selector.bind("<<ComboboxSelected>>", lambda _: self.select_group())
        ttk.Label(frame, text="Select a group or enter a new name. Check its permitted tools.").pack(anchor="w")
        self.permissions_frame = ttk.Frame(frame)
        self.permissions_frame.pack(fill="x")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Save group", command=self.save_group).pack(side="left")
        ttk.Button(row, text="Delete custom group", command=self.delete_group).pack(side="left", padx=4)
        self.refresh_admin()

    def refresh_admin(self):
        self.task(lambda: self.client.request("GET", "/v1/admin"), self.show_admin)

    def show_admin(self, data):
        if not self.window or not self.window.winfo_exists():
            return
        self.admin_data = data
        self.user_selector.configure(values=[u["username"] for u in data["users"]])
        waiting = [u["username"] for u in data["users"] if not u["groups"] and not u["disabled"] and not u.get("admin")]
        self.pending_label.configure(text=f"Waiting for approval: {', '.join(waiting)}. Select an account, tick a group "
                                          "and press Update selected; or tick Disable to refuse it." if waiting else "")
        self.group_selector.configure(values=[g["name"] for g in data["groups"]])
        for frame in (self.memberships, self.permissions_frame):
            for child in frame.winfo_children():
                child.destroy()
        self.group_vars = {g["name"]: tk.BooleanVar(value=False) for g in data["groups"]}
        for group, variable in self.group_vars.items():
            ttk.Checkbutton(self.memberships, text=group, variable=variable).pack(side="left")
        self.perm_vars = {p: tk.BooleanVar(value=False) for p in data["available_permissions"]}
        for permission, variable in self.perm_vars.items():
            ttk.Checkbutton(self.permissions_frame, text=permission, variable=variable).pack(anchor="w")
        self.select_user()
        self.select_group()
        self.status("Administration refreshed")

    def select_user(self):
        if not self.admin_data:
            return
        user = next((u for u in self.admin_data["users"] if u["username"] == self.user_selector.get()), None)
        if user:
            self.admin_username.delete(0, "end")
            self.admin_username.insert(0, user["username"])
            self.disabled.set(bool(user["disabled"]))
            for group, variable in self.group_vars.items():
                variable.set(group in user["groups"])

    def select_group(self):
        if not self.admin_data:
            return
        group = next((g for g in self.admin_data["groups"] if g["name"] == self.group_selector.get()), None)
        for permission, variable in self.perm_vars.items():
            variable.set(bool(group and permission in group["permissions"]))

    def save_user(self, create):
        if not self.admin_data:
            return
        data = {"username": self.admin_username.get(), "password": self.admin_password.get(),
                "groups": [g for g, v in self.group_vars.items() if v.get()], "disabled": self.disabled.get()}
        self.admin_password.delete(0, "end")
        path = "/v1/admin/users"
        if not create:
            user = next((u for u in self.admin_data["users"] if u["username"] == self.user_selector.get()), None)
            if not user:
                self.status("Select an account")
                return
            path += "/" + user["id"]
        self.task(lambda: self.client.request("POST" if create else "PUT", path, data), lambda _: self.refresh_admin())

    def save_group(self):
        import re
        group = self.group_selector.get().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", group):
            self.status("Use 3–40 letters, digits, dots, hyphens or underscores")
            return
        data = {"permissions": [p for p, v in self.perm_vars.items() if v.get()]}
        self.task(lambda: self.client.request("PUT", "/v1/admin/groups/" + group, data), lambda _: self.refresh_admin())

    def delete_group(self):
        group = self.group_selector.get()
        if not self.admin_data or group not in [g["name"] for g in self.admin_data["groups"]]:
            self.status("Select an existing custom group")
            return
        if messagebox.askyesno("Delete group", f"Remove {group} and close its active sessions?", parent=self.window):
            self.task(lambda: self.client.request("DELETE", "/v1/admin/groups/" + group), lambda _: self.refresh_admin())

    def close(self):
        self.stopping = True
        client = self.client
        if client:
            # A remembered sign-in stays valid; leaving still ends the open session for everyone.
            self.executor.submit(client.leave if getattr(client, 'remember', False) else client.logout)
        self.executor.shutdown(wait=False, cancel_futures=False)
