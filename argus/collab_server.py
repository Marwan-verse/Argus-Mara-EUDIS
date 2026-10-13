"""Private SOC account service and ciphertext relay, separate from public AIS.

One process/replica with a private SQLite volume. HTTPS at Caddy; bind the
application to a private Docker network. Plain HTTP is explicit loopback dev only.
"""
import argparse
import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import time

from aiohttp import web

from argus.collab_store import Store, name, password

SERVICE = web.AppKey("soc", object)
KINDS = {"chat": "chat", "ping": "ping", "contact": "contact.share", "evidence": "evidence.share"}


@dataclass
class Config:
    database: Path
    origin: str = "https://soc.example.invalid"
    allow_loopback_http: bool = False
    token_ttl: int = 8 * 3600
    invitation_ttl: int = 600
    room_ttl: int = 8 * 3600
    max_rooms: int = 128
    history_size: int = 256
    proxy_network: str | None = None
    max_members: int = 16
    history_bytes: int = 256 * 1024
    local_demo: bool = False

    @classmethod
    def from_env(cls):
        origin = os.environ.get("ARGUS_SOC_ORIGIN", "").rstrip("/")
        dev = os.environ.get("ARGUS_SOC_DEV_HTTP", "0") == "1"
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" and not (dev and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"})) or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Set ARGUS_SOC_ORIGIN to the external HTTPS origin; HTTP is loopback development only")
        network = os.environ.get('ARGUS_SOC_PROXY_NETWORK') or None
        if network:
            ipaddress.ip_network(network)
        local_demo = os.environ.get('ARGUS_SOC_LOCAL_DEMO', '0') == '1'
        if local_demo and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Demo accounts are restricted to a localhost origin')
        return cls(Path(os.environ.get("ARGUS_SOC_DB", "data/soc/accounts.sqlite3")), origin, dev, proxy_network=network, local_demo=local_demo)


@dataclass
class Room:
    id: str
    group: str | None
    created: float
    code_hash: str
    invitation_expires: float
    members: dict = field(default_factory=dict)
    confirmed: set = field(default_factory=set)
    counters: dict = field(default_factory=dict)
    sequence: int = 0
    messages: deque = field(default_factory=deque)
    locked: bool = False
    history_bytes: int = 0


class Relay:
    def __init__(self, config):
        self.config = config
        self.store = Store(config.database)
        self.rooms = {}
        self.rates = {}
        self.hash_slots = asyncio.Semaphore(2)
        self.pending_hashes = 0

    def limit(self, key, maximum, seconds=60):
        now = time.monotonic()
        # Bound storage and retain active rate windows rather than resetting them.
        if len(self.rates) >= 4096:
            self.rates = {k: v for k, v in self.rates.items() if v[1] > now}
            if key not in self.rates and len(self.rates) >= 4096:
                raise web.HTTPTooManyRequests(text="Try again later", headers={"Retry-After": "60"})
        count, expires = self.rates.get(key, (0, now + seconds))
        if expires <= now:
            count, expires = 0, now + seconds
        if count >= maximum:
            raise web.HTTPTooManyRequests(text="Try again later", headers={"Retry-After": str(max(1, int(expires-now)))})
        self.rates[key] = count + 1, expires

    async def hash_work(self, function, *args):
        if self.pending_hashes >= 8:
            raise web.HTTPServiceUnavailable(text="Authentication busy; retry shortly")
        self.pending_hashes += 1
        try:
            async with self.hash_slots:
                task = asyncio.create_task(asyncio.to_thread(function, *args))
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task  # Do not release slot while its Argon2 worker still runs.
                    raise
        finally:
            self.pending_hashes -= 1

    def purge(self):
        now = time.time()
        for room_id, room in list(self.rooms.items()):
            if now - room.created >= self.config.room_ttl or (len(room.members) == 1 and now >= room.invitation_expires):
                del self.rooms[room_id]

    def close_user_rooms(self, user_id=None, group=None):
        for room_id, room in list(self.rooms.items()):
            if (user_id is not None and user_id in room.members) or (group is not None and room.group == group):
                del self.rooms[room_id]

    def authorized_room(self, request):
        self.purge()
        room = self.rooms.get(request.match_info["room_id"])
        user = request["user"]
        if not room or user["id"] not in room.members or room.members[user["id"]]["token_hash"] != Store.token_hash(request["token"]) or not self.eligible(room, user):
            raise web.HTTPNotFound(text="Session unavailable")
        return room

    @staticmethod
    def eligible(room, user):
        return bool(user and 'chat' in user['permissions'] and
                    (room.group is None or room.group in user['groups']))

    def permissions(self, room):
        grants = []
        for user_id in room.members:
            user = self.store.user(user_id)
            grants.append(set(user['permissions']) if self.eligible(room, user) else set())
        if room.group is not None:
            row = self.store.db.execute('SELECT permissions FROM groups WHERE name=?', (room.group,)).fetchone()
            grants.append(set(json.loads(row[0])) if row else set())
        return sorted(set.intersection(*grants)) if grants else []

    def snapshot(self, room, after=0):
        return {"room_id": room.id, "group": room.group, "sequence": room.sequence,
                'locked': room.locked, 'host_id': next(iter(room.members)), 'max_members': self.config.max_members,
                'permissions': self.permissions(room), 'invitation_expires': room.invitation_expires,
                "members": [{**{k: v for k, v in m.items() if k != "token_hash"},
                             'groups': (self.store.user(m['user_id']) or {}).get('groups', [])} for m in room.members.values()],
                "confirmed": sorted(room.confirmed),
                "messages": [{"sequence": seq, "packet": packet} for seq, packet, _ in room.messages if seq > after]}


def json_response(value):
    return web.json_response(value)


async def body(request):
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="JSON required")
    try:
        value = await request.json()
    except (ValueError, UnicodeError):
        raise web.HTTPBadRequest(text="Invalid JSON") from None
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(text="JSON object required")
    return value


@web.middleware
async def security(request, handler):
    relay = request.app[SERVICE]
    config = relay.config
    # Trust forwarded scheme only from the explicitly configured private proxy
    # network. Remote HTTP is rejected even if someone exposes the wrong port.
    if not request.secure:
        try:
            peer = ipaddress.ip_address(request.remote)
        except (ValueError, TypeError):
            peer = None
        local_dev = config.allow_loopback_http and peer is not None and peer.is_loopback
        trusted_tls = (config.proxy_network is not None and peer is not None and
                       peer in ipaddress.ip_network(config.proxy_network) and
                       request.headers.get('X-Forwarded-Proto') == 'https')
        if not (local_dev or trusted_tls):
            raise web.HTTPUpgradeRequired(text='HTTPS required')
    origin = request.headers.get("Origin")
    if origin and origin != config.origin:
        raise web.HTTPForbidden(text="Origin denied")
    if request.path != "/healthz":
        relay.limit(("global",), 6000)
        relay.limit(("peer", request.remote), 6000)
        if request.path != "/v1/login":
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer ") or not 20 <= len(token[7:]) <= 128:
                raise web.HTTPUnauthorized(text="Sign in required")
            token = token[7:]
            user = relay.store.authenticate(token)
            if not user:
                raise web.HTTPUnauthorized(text="Sign in required")
            relay.limit(("user", user["id"]), 240)
            request["user"], request["token"] = user, token
    try:
        response = await handler(request)
    except ValueError as error:
        response = web.json_response({"error": str(error)}, status=400)
    except web.HTTPException as error:
        response = web.json_response({"error": error.text}, status=error.status,
                                     headers={k: v for k, v in error.headers.items() if k.lower() == "retry-after"})
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})
    if not config.allow_loopback_http:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


async def login(request):
    relay = request.app[SERVICE]
    data = await body(request)
    username = name(data.get("username"))
    candidate = data.get("password")
    if not isinstance(candidate, str) or not 1 <= len(candidate) <= 128:
        raise web.HTTPUnauthorized(text="Invalid username or password")
    relay.limit(("login-global",), 60)
    relay.limit(("login-peer", request.remote), 20)
    relay.limit(("login-name", username), 8, 300)
    row = relay.store.credential(username)
    valid = await relay.hash_work(relay.store.verify, row["password_hash"] if row else relay.store.dummy_hash, candidate)
    # Re-read after hash work: an administrator may revoke an account meanwhile.
    current = relay.store.credential(username)
    if not valid or not current or current["disabled"] or current["password_hash"] != row["password_hash"]:
        raise web.HTTPUnauthorized(text="Invalid username or password")
    token, expires = relay.store.issue_token(current["id"], relay.config.token_ttl)
    return json_response({"token": token, "expires": expires, "user": relay.store.user(current["id"])})


async def me(request):
    return json_response(request["user"])


async def logout(request):
    relay = request.app[SERVICE]
    relay.store.logout(request["token"])
    relay.close_user_rooms(user_id=request["user"]["id"])
    return json_response({"ok": True})


def require(request, permission=None, admin=False):
    user = request["user"]
    if (admin and not user["admin"]) or (permission and permission not in user["permissions"]):
        raise web.HTTPForbidden(text="Permission denied")


def public_key(value):
    try:
        raw = base64.b64decode(value, validate=True) if isinstance(value, str) and len(value) == 44 else b""
    except ValueError:
        raw = b""
    if len(raw) != 32 or raw == bytes(32):
        raise ValueError("Invalid X25519 public key")
    return value


def member(request, key):
    user = request["user"]
    return {"user_id": user["id"], "username": user["username"], "public_key": key,
            "token_hash": Store.token_hash(request["token"])}


async def create_room(request):
    require(request, "chat")
    relay = request.app[SERVICE]
    data = await body(request)
    group = data.get("group")
    if group is not None and (not isinstance(group, str) or group not in request["user"]["groups"]):
        raise web.HTTPForbidden(text="Group membership required")
    key = public_key(data.get("public_key"))
    relay.purge()
    relay.limit(("room-create", request["user"]["id"]), 10, 600)
    if len(relay.rooms) >= relay.config.max_rooms:
        raise web.HTTPServiceUnavailable(text="Session limit reached")
    relay.close_user_rooms(user_id=request["user"]["id"])
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    # 40 random bits, authenticated joins, ten-minute expiry and global limits.
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(8))
        code_hash = Store.token_hash(code)
        if not any(r.code_hash == code_hash for r in relay.rooms.values()):
            break
    now = time.time()
    room = Room(secrets.token_hex(16), group, now, Store.token_hash(code), now + relay.config.invitation_ttl,
                messages=deque(maxlen=relay.config.history_size))
    room.members[request["user"]["id"]] = member(request, key)
    relay.rooms[room.id] = room
    return json_response({**relay.snapshot(room), "code": code, "invitation_expires": room.invitation_expires})


async def join_room(request):
    require(request, "chat")
    relay = request.app[SERVICE]
    relay.limit(("join", request["user"]["id"]), 10, 600)
    relay.limit(('join-global',), 120, 600)
    data = await body(request)
    key = public_key(data.get("public_key"))
    code = data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}", code):
        raise web.HTTPNotFound(text="Invitation unavailable")
    relay.purge()
    room = next((r for r in relay.rooms.values() if secrets.compare_digest(r.code_hash, Store.token_hash(code))), None)
    user = request["user"]
    if not room or room.locked or len(room.members) >= relay.config.max_members or room.invitation_expires <= time.time() or not relay.eligible(room, user) or user["id"] in room.members:
        raise web.HTTPNotFound(text="Invitation unavailable")
    # Host must still have a valid token and membership, not merely an old room.
    host = next(iter(room.members.values()))
    host_user = relay.store.user(host["user_id"])
    token_active = relay.store.db.execute("SELECT 1 FROM tokens WHERE hash=? AND expires>?", (host["token_hash"], time.time())).fetchone()
    if not relay.eligible(room, host_user) or not token_active:
        del relay.rooms[room.id]
        raise web.HTTPNotFound(text="Invitation unavailable")
    relay.close_user_rooms(user_id=user["id"])
    room.members[user["id"]] = member(request, key)
    return json_response(relay.snapshot(room))


async def lock_room(request):
    relay = request.app[SERVICE]
    room = relay.authorized_room(request)
    if request['user']['id'] != next(iter(room.members)):
        raise web.HTTPForbidden(text='Only the host can start the session')
    if len(room.members) < 2:
        raise web.HTTPConflict(text='At least two participants are required')
    room.locked = True
    room.code_hash = ''
    return json_response(relay.snapshot(room))


async def room_state(request):
    relay = request.app[SERVICE]
    room = relay.authorized_room(request)
    try:
        after = int(request.query.get("after", "0"))
    except ValueError:
        raise ValueError("Invalid cursor") from None
    if after < 0 or after > room.sequence:
        raise ValueError("Invalid cursor")
    if room.messages and after < room.messages[0][0] - 1:
        raise web.HTTPConflict(text="Messages expired; create a new session")
    return json_response(relay.snapshot(room, after))


async def confirm(request):
    room = request.app[SERVICE].authorized_room(request)
    if not room.locked or len(room.members) < 2:
        raise web.HTTPConflict(text='The host must first start the encrypted session')
    room.confirmed.add(request["user"]["id"])
    return json_response({"ok": True})


async def leave(request):
    relay = request.app[SERVICE]
    room = relay.authorized_room(request)
    del relay.rooms[room.id]  # No replacement peer under old keys.
    return json_response({"ok": True})


async def send(request):
    relay = request.app[SERVICE]
    room = relay.authorized_room(request)
    data = await body(request)
    if set(data) != {"v", "room_id", "sender", "counter", "kind", "ciphertexts"}:
        raise ValueError("Invalid envelope")
    user = request["user"]
    kind = data["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Unknown message type")
    require(request, KINDS[kind])
    if KINDS[kind] not in relay.permissions(room):
        raise web.HTTPForbidden(text='This tool is not available to every session participant')
    if not room.locked or len(room.confirmed) != len(room.members):
        raise web.HTTPConflict(text='Every participant must confirm the safety codes')
    # Revalidate both parties before sending, including the receiver's expiry.
    for m in room.members.values():
        peer = relay.store.user(m["user_id"])
        active = relay.store.db.execute("SELECT 1 FROM tokens WHERE hash=? AND expires>?", (m["token_hash"], time.time())).fetchone()
        if not active or not relay.eligible(room, peer):
            del relay.rooms[room.id]
            raise web.HTTPNotFound(text="Session unavailable")
    counter = data["counter"]
    if (data["v"] != 2 or data["room_id"] != room.id or data["sender"] != user["id"] or
            type(counter) is not int or not room.counters.get(user["id"], 0) < counter < 2**64):
        raise ValueError("Invalid sender or replayed message")
    ciphertexts = data['ciphertexts']
    if not isinstance(ciphertexts, dict) or set(ciphertexts) != set(room.members) - {user['id']}:
        raise ValueError('Invalid recipient roster')
    for ciphertext in ciphertexts.values():
        try:
            raw = base64.b64decode(ciphertext, validate=True) if isinstance(ciphertext, str) and len(ciphertext) <= 8200 else b''
        except ValueError:
            raw = b''
        if not 16 <= len(raw) <= 6016:
            raise ValueError('Invalid ciphertext')
    relay.limit(("send", user["id"]), 60)
    room.counters[user["id"]] = counter
    room.sequence += 1
    size = len(json.dumps(data))
    if len(room.messages) == room.messages.maxlen:
        room.history_bytes -= room.messages.popleft()[2]
    room.messages.append((room.sequence, data, size))
    room.history_bytes += size
    while room.messages and room.history_bytes > relay.config.history_bytes:
        room.history_bytes -= room.messages.popleft()[2]
    return json_response({"sequence": room.sequence})


async def admin_state(request):
    require(request, admin=True)
    return json_response(request.app[SERVICE].store.admin_snapshot())


async def admin_user(request):
    require(request, admin=True)
    relay = request.app[SERVICE]
    data = await body(request)
    candidate = data.get("password")
    hashed = await relay.hash_work(relay.store.hasher.hash, password(candidate)) if candidate else None
    groups = data.get("groups", [])
    actor = request["user"]["id"]
    if request.method == "POST":
        if not hashed:
            raise ValueError("A password is required")
        result = relay.store.create_user(data.get("username"), hashed, groups, actor=actor)
    else:
        user_id = request.match_info["user_id"]
        relay.store.change_user(user_id, groups, data.get("disabled", False), hashed, actor)
        relay.close_user_rooms(user_id=user_id)
        result = {"ok": True}
    return json_response(result)


async def admin_group(request):
    require(request, admin=True)
    relay = request.app[SERVICE]
    group = request.match_info["group"]
    affected = [r[0] for r in relay.store.db.execute('SELECT user_id FROM memberships WHERE group_name=?', (group,))]
    if request.method == "DELETE":
        relay.store.delete_group(group, request["user"]["id"])
    else:
        data = await body(request)
        relay.store.set_group(group, data.get("permissions"), request["user"]["id"])
    relay.close_user_rooms(group=group)
    for user_id in affected:
        relay.close_user_rooms(user_id=user_id)
    return json_response({"ok": True})


def create_app(config):
    app = web.Application(client_max_size=128 * 1024, middlewares=[security])
    app[SERVICE] = Relay(config)
    async def health(request):
        return json_response({"ready": True})
    app.router.add_get("/healthz", health)
    app.router.add_post("/v1/login", login)
    app.router.add_get("/v1/me", me)
    app.router.add_post("/v1/logout", logout)
    app.router.add_post("/v1/rooms", create_room)
    app.router.add_post("/v1/join", join_room)
    app.router.add_get("/v1/rooms/{room_id}", room_state)
    app.router.add_post("/v1/rooms/{room_id}/confirm", confirm)
    app.router.add_post('/v1/rooms/{room_id}/lock', lock_room)
    app.router.add_post("/v1/rooms/{room_id}/messages", send)
    app.router.add_delete("/v1/rooms/{room_id}", leave)
    app.router.add_get("/v1/admin", admin_state)
    app.router.add_post("/v1/admin/users", admin_user)
    app.router.add_put("/v1/admin/users/{user_id}", admin_user)
    app.router.add_put("/v1/admin/groups/{group}", admin_group)
    app.router.add_delete("/v1/admin/groups/{group}", admin_group)

    async def lifecycle(application):
        async def expiry():
            while True:
                await asyncio.sleep(30)
                application[SERVICE].purge()
        task = asyncio.create_task(expiry())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            application[SERVICE].store.close()
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-admin", metavar="USERNAME", help="create first administrator locally; prompt for password")
    parser.add_argument('--seed-demo', action='store_true', help='create local-only sample users from private environment variables')
    args = parser.parse_args()
    config = Config.from_env()
    if args.seed_demo:
        if not config.local_demo:
            parser.error('Demo seeding requires ARGUS_SOC_LOCAL_DEMO=1 and a localhost origin')
        store = Store(config.database)
        try:
            for username, env_key, groups in (('Marwan', 'ARGUS_DEMO_MARWAN_PASSWORD', ['intelligence', 'user']),
                                               ('Igor', 'ARGUS_DEMO_IGOR_PASSWORD', ['user'])):
                secret = os.environ.get(env_key, '')
                if not 4 <= len(secret) <= 128:
                    parser.error('Set both demo passwords in the private local environment')
                if not store.credential(username.lower()):
                    store.create_user(username, store.hasher.hash(secret), groups)
            admin_secret = os.environ.get('ARGUS_DEMO_ADMIN_PASSWORD', '')
            if admin_secret and not store.credential('admin'):
                store.create_user('admin', store.hasher.hash(password(admin_secret)), ['intelligence', 'user'], admin=True)
            print('Local sample accounts ready; production password policy is unchanged.')
        finally:
            store.close()
        return
    if args.bootstrap_admin:
        store = Store(config.database)
        try:
            if store.db.execute("SELECT 1 FROM users WHERE admin=1").fetchone():
                parser.error("An administrator already exists")
            secret = password(getpass.getpass("New admin password (14+ characters): "))
            if secret != getpass.getpass("Repeat password: "):
                parser.error("Passwords differ")
            store.create_user(args.bootstrap_admin, store.hasher.hash(secret), ["intelligence", "user"], admin=True)
            print("Administrator created. No public registration is enabled.")
        finally:
            store.close()
        return
    host = '0.0.0.0' if config.proxy_network and not config.allow_loopback_http else '127.0.0.1'
    web.run_app(create_app(config), host=host, port=int(os.environ.get("PORT", "8080")), access_log=None, print=None)


if __name__ == "__main__":
    main()
