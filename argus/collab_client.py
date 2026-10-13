"""HTTPS SOC client. Tokens, passwords and ephemeral keys stay in memory."""
import json
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

from argus.collab_crypto import RoomCipher


class ClientError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError("Server redirects are disabled")


def server_url(value, allow_loopback_http=False):
    if not isinstance(value, str):
        raise ValueError("Enter the SOC HTTPS address")
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" and not (allow_loopback_http and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})) or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTPS origin without a path or credentials")
    return value


class SOCClient:
    def __init__(self, url, *, allow_loopback_http=False, ca_file=None):
        self.url = server_url(url, allow_loopback_http)
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
        self.token = None
        self.user = None
        self.room = None
        self.cipher = None
        self.cursor = 0
        self.code = None

    def request(self, method, path, data=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        raw = None
        if data is not None:
            raw = json.dumps(data, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        request = Request(self.url + path, data=raw, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ClientError("Server response exceeds limit")
                return json.loads(raw)
        except HTTPError as error:
            try:
                message = json.loads(error.read(8192)).get("error", "Request refused")
            except (ValueError, AttributeError):
                message = "Request refused"
            raise ClientError(str(message)[:200], error.code) from None
        except (OSError, ValueError):
            raise ClientError("Cannot reach the SOC service securely; check address, certificate and connection") from None

    def login(self, username, password):
        result = self.request("POST", "/v1/login", {"username": username, "password": password})
        self.token, self.user = result["token"], result["user"]
        return self.user

    def refresh_user(self):
        self.user = self.request("GET", "/v1/me")
        return self.user

    def create(self, group):
        self.leave()
        cipher = RoomCipher()
        result = self.request("POST", "/v1/rooms", {"group": group, "public_key": cipher.public_key})
        self.cipher, self.room, self.code, self.cursor = cipher, result, result["code"], 0
        return result

    def join(self, code):
        self.leave()
        cipher = RoomCipher()
        result = self.request("POST", "/v1/join", {"code": code.replace("-", "").replace(" ", "").upper(), "public_key": cipher.public_key})
        self.cipher, self.room, self.code, self.cursor = cipher, result, None, 0
        self._establish(result)
        return result

    def _establish(self, room):
        if len(room["members"]) == 2:
            self.cipher.establish(room["room_id"], self.user["id"], room["members"])

    def confirm(self):
        if not self.cipher or not self.cipher.room_id:
            raise ClientError("Wait for the other analyst")
        self.request("POST", f"/v1/rooms/{self.room['room_id']}/confirm", {})
        self.cipher.confirm()

    def poll(self):
        self.refresh_user()  # Rights are not trusted from a stale login response.
        if not self.room:
            return []
        room = self.request("GET", f"/v1/rooms/{self.room['room_id']}?after={self.cursor}")
        try:
            self._establish(room)
            self.room = room
            if not self.cipher.verified:
                return []
            result = []
            for item in room["messages"]:
                packet = item["packet"]
                if packet["sender"] != self.user["id"]:
                    result.append({"kind": packet["kind"], "payload": self.cipher.decrypt(packet)})
                self.cursor = item["sequence"]
            return result
        except Exception:
            self.room = self.cipher = self.code = None
            raise ClientError('Session failed encryption or identity checks; create a new session', 409) from None

    def send(self, kind, payload):
        if not self.room or len(self.room["confirmed"]) != 2:
            raise ClientError("Both analysts must confirm their safety code")
        packet = self.cipher.encrypt(kind, payload)
        return self.request("POST", f"/v1/rooms/{self.room['room_id']}/messages", packet)

    def leave(self):
        if self.room:
            try:
                self.request("DELETE", f"/v1/rooms/{self.room['room_id']}")
            except ClientError:
                pass
        self.room = self.cipher = self.code = None
        self.cursor = 0

    def logout(self):
        try:
            if self.token:
                self.request("POST", "/v1/logout", {})
        finally:
            self.token = self.user = self.room = self.cipher = self.code = None
