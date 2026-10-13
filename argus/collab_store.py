"""Durable account/RBAC store. No plaintext passwords, tokens or messages."""
import hashlib
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

PERMISSIONS = frozenset({"map.view", "chat", "ping", "contact.share", "evidence.share",
                         "alert.review", "response.review"})
DEFAULT_GROUPS = {"user": ["map.view", "chat", "ping", "contact.share"],
                  "intelligence": sorted(PERMISSIONS)}


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}", value):
        raise ValueError("Use 3–40 letters, digits, dots, hyphens or underscores")
    return value.lower()


def password(value):
    if not isinstance(value, str) or not 14 <= len(value) <= 128:
        raise ValueError("Use a password of 14–128 characters")
    return value


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS groups(name TEXT PRIMARY KEY, permissions TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                group_name TEXT REFERENCES groups(name) ON DELETE CASCADE, PRIMARY KEY(user_id,group_name));
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT,
                action TEXT NOT NULL, target TEXT NOT NULL);
        """)
        for group, perms in DEFAULT_GROUPS.items():
            self.db.execute("INSERT OR IGNORE INTO groups VALUES (?,?)", (group, json.dumps(perms)))
        self.db.commit()
        self.hasher = PasswordHasher()  # Argon2id RFC 9106 low-memory profile.
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def close(self):
        self.db.close()

    def audit(self, actor, action, target):
        self.db.execute("INSERT INTO audit(at,actor,action,target) VALUES (?,?,?,?)", (time.time(), actor, action, target))

    def user(self, user_id):
        row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None or row["disabled"]:
            return None
        groups = [r[0] for r in self.db.execute("SELECT group_name FROM memberships WHERE user_id=? ORDER BY group_name", (user_id,))]
        perms = set()
        for group in groups:
            perms.update(json.loads(self.db.execute("SELECT permissions FROM groups WHERE name=?", (group,)).fetchone()[0]))
        return {"id": row["id"], "username": row["username"], "admin": bool(row["admin"]),
                "groups": groups, "permissions": sorted(perms)}

    def create_user(self, username, hashed, groups, admin=False, actor=None):
        username = name(username)
        self.validate_groups(groups)
        user_id = secrets.token_hex(16)
        try:
            with self.db:
                self.db.execute("INSERT INTO users(id,username,password_hash,admin) VALUES (?,?,?,?)", (user_id, username, hashed, int(admin)))
                for group in groups:
                    self.db.execute("INSERT INTO memberships VALUES (?,?)", (user_id, group))
                self.audit(actor, "user.create", username)
        except sqlite3.IntegrityError:
            raise ValueError("Username already exists") from None
        return self.user(user_id)

    def validate_groups(self, groups):
        if not isinstance(groups, list) or len(groups) > 32 or any(not isinstance(g, str) for g in groups) or len(set(groups)) != len(groups):
            raise ValueError("Invalid groups")
        existing = {r[0] for r in self.db.execute("SELECT name FROM groups")}
        if not set(groups) <= existing:
            raise ValueError("Unknown group")

    def credential(self, username):
        return self.db.execute("SELECT id,password_hash,disabled FROM users WHERE username=?", (username,)).fetchone()

    def verify(self, hashed, candidate):
        try:
            return self.hasher.verify(hashed, candidate)
        except (VerificationError, InvalidHashError):
            return False

    def issue_token(self, user_id, ttl):
        token = secrets.token_urlsafe(32)
        expires = time.time() + ttl
        with self.db:
            self.db.execute("DELETE FROM tokens WHERE expires<=?", (time.time(),))
            # Limit simultaneous logins per account.
            self.db.execute("DELETE FROM tokens WHERE user_id=? AND hash NOT IN (SELECT hash FROM tokens WHERE user_id=? ORDER BY expires DESC LIMIT 7)", (user_id, user_id))
            self.db.execute("INSERT INTO tokens VALUES (?,?,?)", (self.token_hash(token), user_id, expires))
        return token, expires

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token):
        row = self.db.execute("SELECT user_id FROM tokens WHERE hash=? AND expires>?", (self.token_hash(token), time.time())).fetchone()
        return self.user(row[0]) if row else None

    def logout(self, token):
        with self.db:
            self.db.execute("DELETE FROM tokens WHERE hash=?", (self.token_hash(token),))

    def change_user(self, user_id, groups, disabled, hashed, actor):
        row = self.db.execute("SELECT username,admin FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown user")
        if row["admin"]:
            raise ValueError("Administrator accounts are protected from UI changes")
        self.validate_groups(groups)
        if type(disabled) is not bool:
            raise ValueError("Invalid disabled flag")
        with self.db:
            self.db.execute("DELETE FROM memberships WHERE user_id=?", (user_id,))
            for group in groups:
                self.db.execute("INSERT INTO memberships VALUES (?,?)", (user_id, group))
            self.db.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))
            if hashed:
                self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, user_id))
            self.db.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
            self.audit(actor, "user.update_and_revoke", row["username"])

    def set_group(self, group, permissions, actor):
        group = name(group)
        if not isinstance(permissions, list) or any(not isinstance(p, str) for p in permissions) or not set(permissions) <= PERMISSIONS:
            raise ValueError("Unknown permission")
        with self.db:
            self.db.execute("INSERT INTO groups VALUES (?,?) ON CONFLICT(name) DO UPDATE SET permissions=excluded.permissions", (group, json.dumps(sorted(set(permissions)))))
            self.audit(actor, "group.update", group)

    def delete_group(self, group, actor):
        if group in DEFAULT_GROUPS:
            raise ValueError("Default groups cannot be deleted; edit their permissions")
        with self.db:
            self.db.execute("DELETE FROM groups WHERE name=?", (group,))
            self.audit(actor, "group.delete", group)

    def admin_snapshot(self):
        users = []
        for r in self.db.execute("SELECT id,username,admin,disabled FROM users ORDER BY username"):
            user = dict(r)
            user["groups"] = [m[0] for m in self.db.execute("SELECT group_name FROM memberships WHERE user_id=? ORDER BY group_name", (r["id"],))]
            users.append(user)
        return {"users": users, "groups": [{"name": r[0], "permissions": json.loads(r[1])} for r in self.db.execute("SELECT name,permissions FROM groups ORDER BY name")],
                "available_permissions": sorted(PERMISSIONS)}
