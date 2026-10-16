"""Browser auth boundary and account lifecycle against the real SOC service."""
import tempfile
import json
import time
import unittest
from pathlib import Path

from aiohttp import ClientSession, CookieJar
from aiohttp.test_utils import TestServer

from argus.admin_web import cookie_name
from argus.collab_server import Config, SERVICE, create_app

SECRET = "synthetic-admin-web-test-42"


class AdminWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Config(Path(self.temp.name) / "accounts.sqlite3", allow_loopback_http=True))
        self.relay = self.app[SERVICE]
        hashed = self.relay.store.hasher.hash(SECRET)
        self.admin = self.relay.store.create_user("admin", hashed, ["intelligence"], admin=True)
        self.operator = self.relay.store.create_user("operator", hashed, ["user"])
        self.applicant = self.relay.store.create_user("applicant", hashed, [])
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.origin = str(self.server.make_url("")).rstrip("/")
        self.relay.config.origin = self.origin
        self.http = ClientSession(cookie_jar=CookieJar(unsafe=True))
        self.csrf = ""

    async def asyncTearDown(self):
        await self.http.close()
        await self.server.close()
        self.temp.cleanup()

    async def request(self, method, path, data=None, headers=None):
        defaults = {"Origin": self.origin, "X-CSRF-Token": self.csrf}
        defaults.update(headers or {})
        response = await self.http.request(method, self.server.make_url(path), json=data, headers=defaults)
        raw = await response.text()
        try:
            result = json.loads(raw)
        except ValueError:
            result = raw
        return response, result

    async def login(self):
        response, data = await self.request("POST", "/admin/api/login", {"username": "admin", "password": SECRET})
        self.assertEqual(response.status, 200, data)
        self.csrf = data["csrf"]
        return response, data

    async def test_assets_are_allowlisted_and_errors_keep_security_headers(self):
        response, html = await self.request("GET", "/admin/")
        self.assertEqual(response.status, 200)
        self.assertIn('lang="en"', html)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        for path in ("/admin/admin.css", "/admin/styles.css", "/admin/app.mjs"):
            self.assertEqual((await self.request("GET", path))[0].status, 200)
        for path in ("/admin/api/state", "/admin/../.git/config", "/admin/accounts.sqlite3"):
            response, _ = await self.request("GET", path)
            self.assertIn(response.status, (401, 404))
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        response, _ = await self.request("GET", "/admin/", headers={"Host": "attacker.example"})
        self.assertEqual(response.status, 403)

    async def test_cookie_scope_csrf_origin_and_logout(self):
        response, data = await self.login()
        self.assertNotIn("token", data)
        cookie = response.cookies[cookie_name(self.relay.config)]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/")
        self.assertEqual((await self.request("GET", "/admin/api/state"))[0].status, 200)
        # Browser cookies never authenticate the desktop API.
        self.assertEqual((await self.request("GET", "/v1/admin"))[0].status, 401)
        # Even an extracted browser token is not a native API bearer credential.
        token = self.http.cookie_jar.filter_cookies(self.server.make_url("/"))[cookie_name(self.relay.config)].value
        self.assertEqual((await self.request("GET", "/v1/admin", headers={"Authorization": "Bearer " + token}))[0].status, 401)
        for headers in ({"Origin": "https://evil.example"}, {"Origin": ""}, {"X-CSRF-Token": ""}, {"X-CSRF-Token": "wrong"}):
            self.assertEqual((await self.request("PUT", "/admin/api/groups/custom", {"permissions": ["chat"]}, headers))[0].status, 403)
        self.assertEqual((await self.request("POST", "/admin/api/logout", {}))[0].status, 200)
        self.assertEqual((await self.request("GET", "/admin/api/state"))[0].status, 401)

    async def test_nonadmin_cannot_obtain_browser_session_or_promote_self(self):
        response, _ = await self.request("POST", "/admin/api/login", {"username": "operator", "password": SECRET})
        self.assertEqual(response.status, 403)
        self.assertFalse(response.cookies)
        self.assertEqual(self.relay.store.db.execute("SELECT COUNT(*) FROM browser_sessions").fetchone()[0], 0)
        token = self.relay.store.issue_token(self.operator["id"], 3600)[0]
        self.assertEqual((await self.request("PUT", f'/v1/admin/users/{self.operator["id"]}', {"admin": True}, {"Authorization": "Bearer " + token}))[0].status, 403)
        self.assertEqual((await self.request("GET", "/admin/api/state", headers={"Authorization": "Bearer " + token}))[0].status, 401)

    async def test_production_cookie_is_secure_and_http_is_rejected(self):
        self.relay.config.allow_loopback_http = False
        self.assertEqual((await self.request("GET", "/admin/"))[0].status, 426)
        self.relay.config.proxy_network = "127.0.0.1/32"
        self.relay.config.origin = self.origin.replace("http:", "https:")
        response, data = await self.request("POST", "/admin/api/login", {"username": "admin", "password": SECRET},
                                            {"Origin": self.relay.config.origin, "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status, 200, data)
        cookie = response.cookies["__Host-argus_admin"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertNotIn("domain", str(cookie).lower())
        self.assertIn("Strict-Transport-Security", response.headers)

    async def test_idle_absolute_expiry_and_login_rotation(self):
        await self.login()
        old = self.http.cookie_jar.filter_cookies(self.server.make_url("/"))[cookie_name(self.relay.config)].value
        await self.login()
        self.assertIsNone(self.relay.store.authenticate(old))
        with self.relay.store.db:
            self.relay.store.db.execute("UPDATE browser_sessions SET last_seen=?", (time.time() - 901,))
        self.assertEqual((await self.request("GET", "/admin/api/state"))[0].status, 401)
        await self.login()
        with self.relay.store.db:
            self.relay.store.db.execute("UPDATE tokens SET expires=?", (time.time() - 1,))
        self.assertEqual((await self.request("GET", "/admin/api/state"))[0].status, 401)

    async def test_approval_ban_reset_revoke_and_audit(self):
        await self.login()
        path = f'/admin/api/users/{self.applicant["id"]}'
        response, state = await self.request("GET", "/admin/api/state")
        self.assertEqual(next(u for u in state["users"] if u["username"] == "applicant")["status"], "pending")
        response, _ = await self.request("PUT", path, {"groups": ["analyst"], "disabled": False, "admin": True})
        self.assertEqual(response.status, 200)
        account = self.relay.store.user(self.applicant["id"])
        self.assertFalse(account["admin"])
        self.assertIn("evidence.share", account["permissions"])
        self.assertNotIn("response.review", account["permissions"])
        response, signin = await self.request("POST", "/v1/login", {"username": "applicant", "password": SECRET})
        self.assertEqual(response.status, 200)
        # A ban revokes native tokens too.
        self.assertEqual((await self.request("PUT", path, {"groups": ["analyst"], "disabled": True}))[0].status, 200)
        self.assertIsNone(self.relay.store.authenticate(signin["token"]))
        self.assertEqual((await self.request("POST", "/v1/login", {"username": "applicant", "password": SECRET}))[0].status, 401)
        replacement = "replacement-test-password-42"
        self.assertEqual((await self.request("PUT", path, {"groups": ["observer"], "disabled": False, "password": replacement}))[0].status, 200)
        self.assertEqual((await self.request("POST", "/v1/login", {"username": "applicant", "password": SECRET}))[0].status, 401)
        response, signin = await self.request("POST", "/v1/login", {"username": "applicant", "password": replacement})
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.request("POST", path + "/revoke", {}))[0].status, 200)
        self.assertIsNone(self.relay.store.authenticate(signin["token"]))
        _, state = await self.request("GET", "/admin/api/state")
        self.assertIn("user.revoke_sessions", [entry["action"] for entry in state["audit"]])
        self.assertNotIn(SECRET, str(state))
        self.assertNotIn(replacement, str(state))
        self.assertNotIn(signin["token"], str(state))

    async def test_group_membership_union_delete_and_protected_admin(self):
        await self.login()
        self.assertEqual((await self.request("PUT", "/admin/api/groups/research", {"permissions": ["evidence.share"]}))[0].status, 200)
        path = f'/admin/api/users/{self.operator["id"]}'
        self.assertEqual((await self.request("PUT", path, {"groups": ["user", "research"], "disabled": False}))[0].status, 200)
        self.assertIn("evidence.share", self.relay.store.user(self.operator["id"])["permissions"])
        self.assertEqual((await self.request("DELETE", "/admin/api/groups/research"))[0].status, 200)
        self.assertNotIn("evidence.share", self.relay.store.user(self.operator["id"])["permissions"])
        self.assertEqual((await self.request("PUT", "/admin/api/groups/custom", {"permissions": ["root.shell"]}))[0].status, 400)
        self.assertEqual((await self.request("DELETE", "/admin/api/groups/user"))[0].status, 400)
        for suffix, method in (("", "PUT"), ("/revoke", "POST")):
            self.assertEqual((await self.request(method, f'/admin/api/users/{self.admin["id"]}' + suffix, {"groups": [], "disabled": True}))[0].status, 400)

    async def test_revocation_during_password_hashing_stops_admin_write(self):
        await self.login()
        original = self.relay.hash_work

        async def revoke_while_hashing(function, *args):
            result = await original(function, *args)
            with self.relay.store.db:
                self.relay.store.db.execute("DELETE FROM tokens WHERE user_id=?", (self.admin["id"],))
            return result

        self.relay.hash_work = revoke_while_hashing
        response, _ = await self.request("POST", "/admin/api/users", {"username": "should-not-exist", "password": SECRET, "groups": ["user"]})
        self.assertEqual(response.status, 401)
        self.assertIsNone(self.relay.store.credential("should-not-exist"))


if __name__ == "__main__":
    unittest.main()
