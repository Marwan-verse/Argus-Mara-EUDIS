"""Same-origin browser administration for the private SOC service only."""
import hashlib
import secrets
import time
from pathlib import Path

from aiohttp import web

ASSETS = {"/admin/": ("index.html", "text/html"),
          "/admin/app.mjs": ("app.mjs", "text/javascript"),
          "/admin/admin.css": ("admin.css", "text/css"),
          "/admin/styles.css": ("../styles.css", "text/css")}
SESSION_SECONDS = 3600
IDLE_SECONDS = 900


def cookie_name(config):
    return "argus_admin_dev" if config.allow_loopback_http else "__Host-argus_admin"


def csrf_token(token):
    return hashlib.sha256(("argus-admin-csrf:" + token).encode()).hexdigest()


def authenticate(request, relay):
    """Cookie credentials are accepted only by the isolated admin browser API."""
    token = request.cookies.get(cookie_name(relay.config), "")
    if not 20 <= len(token) <= 128:
        raise web.HTTPUnauthorized(text="Sign in required")
    store = relay.store
    row = store.db.execute("SELECT last_seen FROM browser_sessions WHERE hash=?", (store.token_hash(token),)).fetchone()
    user = store.authenticate(token)
    if not row or not user or time.time() - row[0] >= IDLE_SECONDS:
        if row:
            store.logout(token)
        raise web.HTTPUnauthorized(text="Session expired; sign in again")
    if not user["admin"]:
        raise web.HTTPForbidden(text="Administrator access required")
    if request.method not in {"GET", "HEAD"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied.isascii() or not secrets.compare_digest(supplied, csrf_token(token)):
            raise web.HTTPForbidden(text="CSRF check failed; reload this page")
    with store.db:
        store.db.execute("UPDATE browser_sessions SET last_seen=? WHERE hash=?", (time.time(), store.token_hash(token)))
    return user, token


def install(app, service, verify_login, handlers):
    async def asset(request):
        filename, mime = ASSETS[request.path]
        path = Path(__file__).resolve().parents[1] / "ui" / "admin" / filename
        if not path.is_file():
            raise web.HTTPServiceUnavailable(text="Admin assets missing; rebuild the frontend")
        return web.Response(body=path.read_bytes(), content_type=mime)

    async def sign_in(request):
        relay = request.app[service]
        user = await verify_login(request)
        if not user["admin"]:
            raise web.HTTPForbidden(text="Administrator access required")
        # A fresh token prevents fixation; revoke this browser's previous session.
        previous = request.cookies.get(cookie_name(relay.config), "")
        if previous:
            relay.store.logout(previous)
        token, expires = relay.store.issue_token(user["id"], SESSION_SECONDS)
        with relay.store.db:
            relay.store.db.execute("INSERT INTO browser_sessions VALUES (?,?)", (relay.store.token_hash(token), time.time()))
            relay.store.audit(user["id"], "admin.browser_login", user["username"])
        response = web.json_response({"user": user, "csrf": csrf_token(token), "expires": expires})
        response.set_cookie(cookie_name(relay.config), token, max_age=SESSION_SECONDS,
                            secure=not relay.config.allow_loopback_http, httponly=True, samesite="Strict", path="/")
        return response

    async def session(request):
        return web.json_response({"user": request["user"], "csrf": csrf_token(request["token"]),
                                  "idle_seconds": IDLE_SECONDS, "absolute_seconds": SESSION_SECONDS})

    async def sign_out(request):
        relay = request.app[service]
        with relay.store.db:
            relay.store.audit(request["user"]["id"], "admin.browser_logout", request["user"]["username"])
        response = await handlers["logout"](request)
        response.del_cookie(cookie_name(relay.config), path="/")
        return response

    for route in ASSETS:
        app.router.add_get(route, asset)
    app.router.add_post("/admin/api/login", sign_in)
    app.router.add_get("/admin/api/session", session)
    app.router.add_post("/admin/api/logout", sign_out)
    app.router.add_get("/admin/api/state", handlers["state"])
    app.router.add_post("/admin/api/users", handlers["user"])
    app.router.add_put("/admin/api/users/{user_id}", handlers["user"])
    app.router.add_post("/admin/api/users/{user_id}/revoke", handlers["revoke"])
    app.router.add_put("/admin/api/groups/{group}", handlers["group"])
    app.router.add_delete("/admin/api/groups/{group}", handlers["group"])
