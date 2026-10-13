"""Native two-analyst collaboration and administrator controls."""
from concurrent.futures import ThreadPoolExecutor
import queue
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from argus.collab_client import ClientError, SOCClient
from argus.collab_crypto import KINDS


def login_screen(root, initial_url, on_login, *, allow_loopback_http=False):
    """No protected app is constructed until HTTPS authentication succeeds."""
    root.title("Argus Mara · SOC sign in")
    root.geometry("580x430")
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
    status = ctk.CTkLabel(frame, text="Administrator accounts are created on the server.", wraplength=480)
    status.pack(padx=16, pady=4)
    executor = ThreadPoolExecutor(max_workers=1)
    events = queue.Queue()
    busy = False
    closed = False

    def submit():
        nonlocal busy
        if busy:
            return
        try:
            client = SOCClient(fields["url"].get().strip(), allow_loopback_http=allow_loopback_http)
        except ValueError as error:
            status.configure(text=str(error))
            return
        username, secret = fields["username"].get().strip(), fields["password"].get()
        fields["password"].delete(0, "end")
        busy = True
        button.configure(state="disabled")
        status.configure(text="Signing in securely…")

        def job():
            try:
                client.login(username, secret)
                events.put((client, None))
            except Exception as error:
                events.put((None, str(error)))
        executor.submit(job)

    def check():
        nonlocal busy, closed
        if closed:
            return
        try:
            client, error = events.get_nowait()
        except queue.Empty:
            root.after(100, check)
            return
        if error:
            busy = False
            button.configure(state="normal")
            status.configure(text=error)
            root.after(100, check)
        else:
            closed = True
            executor.shutdown(wait=False)
            frame.destroy()
            on_login(client)

    def close():
        nonlocal closed
        closed = True
        executor.shutdown(wait=False, cancel_futures=True)
        root.destroy()

    button = ctk.CTkButton(frame, text="Sign in", command=submit)
    button.pack(pady=8)
    fields["password"].bind("<Return>", lambda _: submit())
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, check)


class DesktopSOC:
    def __init__(self, app):
        self.app = app
        self.client = app.soc_client
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.pending = 0
        self.window = None
        self.login_window = None
        self.stopping = False
        self.history = []
        self.last_status = "Sign in to communicate" if not self.client else "Signed in · create or join a session"
        self.app.root.after(250, self.tick)

    def task(self, function, callback=None):
        if self.stopping or self.pending >= 8:
            self.status("Please wait for the current request")
            return
        self.pending += 1
        def job():
            try:
                self.events.put((callback, function(), None))
            except Exception as error:
                self.events.put((callback, None, error))
        self.executor.submit(job)

    def tick(self):
        if self.stopping:
            return
        while True:
            try:
                callback, result, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            if error:
                self.status(str(error))
                if isinstance(error, ClientError) and error.status == 401:
                    messagebox.showinfo("Sign in required", "Your access expired or was revoked. Sign in again.", parent=self.app.root)
                    self.app.close()
                    return
                if isinstance(error, ClientError) and error.status in (404, 409) and self.client:
                    self.client.room = self.client.cipher = self.client.code = None
                    self.history.clear()
                    self.render()
                self.app.soc_online = False
            else:
                self.app.soc_online = True
                if callback:
                    callback(result)
        if self.client and self.pending == 0:
            self.task(self.client.poll, self.receive)
        self.app.root.after(1500, self.tick)

    def status(self, text):
        self.last_status = text
        if self.window and self.window.winfo_exists():
            self.status_label.configure(text=text)

    def receive(self, messages):
        for message in messages:
            payload, kind = message["payload"], message["kind"]
            if kind == "ping":
                self.app._place_map_ping((payload["lat"], payload["lon"]), share=False)
                self.app.map_status_label.configure(text="Peer ping · analyst annotation · not a sensor alert")
                text = f"Peer ping: {payload['lat']:.5f}, {payload['lon']:.5f}"
            else:
                text = f"Peer [{kind}]: {payload['text']}"
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
        self.window = ctk.CTkToplevel(self.app.root)
        self.window.title("SOC communication")
        self.window.geometry("740x750")
        self.window.minsize(620, 650)
        self.window.transient(self.app.root)
        tabs = ttk.Notebook(self.window)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        frame = ttk.Frame(tabs, padding=12)
        tabs.add(frame, text="Session")
        ttk.Label(frame, text=f"{self.client.user['username']} · {self.client.url}", wraplength=660).pack(anchor="w")
        self.status_label = ttk.Label(frame, text=self.last_status, wraplength=650)
        self.status_label.pack(anchor="w", pady=8)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=6)
        self.group = tk.StringVar(value=(self.client.user["groups"] or [""])[0])
        ttk.Combobox(row, textvariable=self.group, values=self.client.user["groups"], state="readonly", width=17).pack(side="left")
        ttk.Button(row, text="Create session", command=self.create).pack(side="left", padx=4)
        self.join_code = ttk.Entry(row, width=17)
        self.join_code.pack(side="left", padx=4)
        ttk.Button(row, text="Join", command=lambda: self.join(self.join_code.get())).pack(side="left")
        self.invite_label = ttk.Label(frame, text="", font=("Consolas", 13), wraplength=660)
        self.invite_label.pack(anchor="w", pady=5)
        self.safety_label = ttk.Label(frame, text="", font=("Consolas", 12), wraplength=660)
        self.safety_label.pack(anchor="w", pady=5)
        ttk.Label(frame, text="Compare the entire safety code with your colleague by voice or in person before confirming.", wraplength=660).pack(anchor="w")
        self.confirm_button = ttk.Button(frame, text="Codes match · confirm", command=lambda: self.task(self.client.confirm, lambda _: self.status("Confirmed · waiting for your colleague")))
        self.confirm_button.pack(anchor="w", pady=6)
        self.chat = tk.Text(frame, wrap="word", height=12, state="disabled")
        self.chat.pack(fill="both", expand=True, pady=8)
        self.message = tk.Text(frame, wrap="word", height=3)
        self.message.pack(fill="x")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        self.kind = tk.StringVar(value="chat")
        self.kind_selector = ttk.Combobox(row, textvariable=self.kind, values=list(KINDS), state="readonly", width=12)
        self.kind_selector.pack(side="left")
        self.send_button = ttk.Button(row, text="Send", command=self.send_text)
        self.send_button.pack(side="left", padx=6)
        ttk.Button(row, text="Share selected contact", command=self.share_contact).pack(side="left")
        ttk.Button(row, text="Leave", command=lambda: self.task(self.client.leave, lambda _: self.reset())).pack(side="right")
        ttk.Label(frame, text="Map Ping shares a point only while this session is verified. Messages stay in memory.", wraplength=660).pack(anchor="w")
        if 'evidence.share' in self.client.user['permissions']:
            ttk.Button(frame, text='Share exercise evidence summary', command=self.share_evidence).pack(anchor='w', pady=4)
        if self.client.user["admin"]:
            admin = ttk.Frame(tabs, padding=12)
            tabs.add(admin, text="Administration")
            self.build_admin(admin)
        self.render()

    def reset(self, result=None):
        self.history.clear()
        self.status("Session changed · compare the new safety code")
        self.render()

    def create(self):
        group = self.group.get()
        self.task(lambda: self.client.create(group), self.reset)

    def join(self, code):
        self.task(lambda: self.client.join(code), self.reset)

    def render(self):
        if not self.window or not self.window.winfo_exists():
            return
        room, cipher = self.client.room, self.client.cipher
        ready = bool(room and cipher and cipher.verified and len(room["confirmed"]) == 2)
        self.invite_label.configure(text=f"Invite (10 min, single use): {self.client.code}" if self.client.code and room and len(room["members"]) == 1 else "")
        peer = next((m["username"] for m in (room or {}).get("members", []) if m["user_id"] != self.client.user["id"]), "waiting")
        self.safety_label.configure(text=f"Peer: {peer}\nSafety: {cipher.safety_code}\n{'E2EE verified on both devices' if ready else 'Verification required'}" if cipher and cipher.room_id else "Waiting for a second analyst")
        self.confirm_button.configure(state="normal" if cipher and cipher.room_id and not cipher.verified else "disabled")
        self.send_button.configure(state="normal" if ready else "disabled")
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.insert("1.0", "\n\n".join(self.history))
        self.chat.see("end")
        self.chat.configure(state="disabled")
        kinds = [k for k, permission in KINDS.items() if k != "ping" and permission in self.client.user["permissions"]]
        self.kind_selector.configure(values=kinds)
        if self.kind.get() not in kinds:
            self.kind.set(kinds[0] if kinds else "")

    def send_message(self, kind, payload):
        if KINDS[kind] not in self.client.user["permissions"]:
            self.status("Your group cannot use this tool")
            return
        def done(_):
            self.history.append(f"You [{kind}]: {payload.get('text', payload)}")
            self.history = self.history[-100:]
            self.render()
        self.task(lambda: self.client.send(kind, payload), done)

    def send_text(self):
        self.send_message(self.kind.get(), {"text": self.message.get("1.0", "end").strip()})

    def share_ping(self, point):
        if self.client and self.client.cipher and self.client.cipher.verified and self.client.room and len(self.client.room["confirmed"]) == 2:
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
            self.executor.submit(client.logout)
        self.executor.shutdown(wait=False, cancel_futures=False)
