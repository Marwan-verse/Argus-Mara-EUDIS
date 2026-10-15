"""HTTPS SOC client. Passwords and ephemeral keys stay in memory; only a token the
user chose to remember goes to the OS keychain (see soc_session)."""
import json
import ipaddress
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

from argus.collab_crypto import RoomCipher


class ClientError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def forwarded_origin(value):
    """Recognize the documented VS Code/Codespaces HTTPS tunnel domains."""
    parsed = urlsplit(value)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and any(host.endswith(suffix) for suffix in ('.devtunnels.ms', '.app.github.dev'))


TUNNEL_ACCESS_HELP = ('The forwarded port requires GitHub/Microsoft web access. In VS Code set '
                      'Port Visibility to Public, then use the HTTPS link. Argus account login is still required.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if forwarded_origin(req.full_url):
            raise ClientError(TUNNEL_ACCESS_HELP)
        raise ClientError("Server redirects are disabled")


def server_url(value, allow_loopback_http=False):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(char) <= 32 for char in value):
        raise ValueError("Enter the SOC HTTPS address")
    value = value.rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('Enter a valid SOC HTTPS address') from None
    if (parsed.scheme != "https" and not (allow_loopback_http and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})) or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTPS origin without a path or credentials")
    if '\\' in value or port is not None and not 1 <= port <= 65535:
        raise ValueError('Enter a valid SOC HTTPS address')
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        host = parsed.hostname
        if len(host) > 253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in host.split('.')):
            raise ValueError('Enter a valid SOC HTTPS hostname') from None
    return value


class SOCClient:
    def __init__(self, url, *, allow_loopback_http=False, ca_file=None):
        self.url = server_url(url, allow_loopback_http)
        self.ca_file = ca_file
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
        self.token = None
        self.user = None
        self.room = None
        self.cipher = None
        self.cursor = 0
        self.code = None
        self.remember = False  # A remembered sign-in survives closing the app; see soc_session.

    def request(self, method, path, data=None):
        headers = {"Accept": "application/json"}
        if forwarded_origin(self.url):
            # Microsoft documents this for API clients. It bypasses the HTML
            # warning page, never tunnel authorization or Argus authentication.
            headers['X-Tunnel-Skip-AntiPhishing-Page'] = 'true'
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
                try:
                    return json.loads(raw)
                except (ValueError, UnicodeError):
                    if forwarded_origin(self.url):
                        raise ClientError('The tunnel returned a web page instead of the SOC API. ' + TUNNEL_ACCESS_HELP) from None
                    raise ClientError('The server did not return the SOC API response') from None
        except HTTPError as error:
            try:
                message = json.loads(error.read(8192)).get("error", "Request refused")
            except (ValueError, AttributeError):
                message = TUNNEL_ACCESS_HELP if forwarded_origin(self.url) and error.code in (401, 403) else "Request refused"
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

    def resume(self, token):
        """Sign in with a remembered token; the server decides whether it is still valid."""
        self.token = token
        try:
            return self.refresh_user()
        except ClientError:
            self.token = None
            raise

    def signup(self, username, password):
        """Request an account; it can sign in once an administrator adds it to a group."""
        return self.request("POST", "/v1/signup", {"username": username, "password": password})

    def create(self, group=None):
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
        if room.get('locked') and len(room['members']) >= 2:
            self.cipher.establish(room["room_id"], self.user["id"], room["members"])

    def lock(self):
        self.room = self.request('POST', f"/v1/rooms/{self.room['room_id']}/lock", {})
        self._establish(self.room)
        return self.room

    def confirm(self):
        if not self.cipher or not self.cipher.room_id:
            raise ClientError('Wait for the host to start the encrypted session')
        if self.cipher.unverified_peers():
            raise ClientError('Type the code each teammate reads to you first')
        self.request("POST", f"/v1/rooms/{self.room['room_id']}/confirm", {})
        self.cipher.confirm()

    def poll(self):
        self.refresh_user()  # Rights are not trusted from a stale login response.
        if not self.room:
            return []
        try:
            room = self.request("GET", f"/v1/rooms/{self.room['room_id']}?after={self.cursor}")
        except ClientError as error:
            if error.status in (404, 409):
                self.room = self.cipher = self.code = None
            raise
        try:
            self._establish(room)
            self.room = room
            if not self.cipher.verified:
                return []
            result = []
            for item in room["messages"]:
                packet = item["packet"]
                if packet["sender"] != self.user["id"]:
                    sender = next(m['username'] for m in room['members'] if m['user_id'] == packet['sender'])
                    result.append({"kind": packet["kind"], "payload": self.cipher.decrypt(packet), 'sender': sender})
                self.cursor = item["sequence"]
            return result
        except Exception:
            self.room = self.cipher = self.code = None
            raise ClientError('Session failed encryption or identity checks; create a new session', 409) from None

    def send(self, kind, payload):
        if not self.room or not self.room.get('locked') or len(self.room['confirmed']) != len(self.room['members']):
            raise ClientError('Every participant must confirm the safety codes')
        from argus.collab_crypto import KINDS
        if KINDS.get(kind) not in self.room.get('permissions', self.user['permissions']):
            raise ClientError('This tool is not available to everyone in this session', 403)
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
