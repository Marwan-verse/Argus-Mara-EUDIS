"""SOC E2EE v1. Only endpoints import this module; relay never has keys.

Fresh X25519 keys per two-person room; HKDF separates directions; AES-256-GCM
binds routing metadata. Compare the full safety code over a trusted channel.
"""
import base64
import hashlib
import json
import math

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KINDS = {"chat": "chat", "ping": "ping", "contact": "contact.share", "evidence": "evidence.share"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def encode(value):
    return base64.b64encode(value).decode("ascii")


def decode(value, maximum=8192):
    if not isinstance(value, str) or len(value) > maximum * 2:
        raise ValueError("Invalid encoded data")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid encoded data") from None
    if len(result) > maximum:
        raise ValueError("Encoded data too large")
    return result


def validate_payload(kind, payload):
    if kind not in KINDS or not isinstance(payload, dict):
        raise ValueError("Invalid message")
    if kind == "ping":
        if set(payload) != {"lat", "lon"}:
            raise ValueError("A ping requires coordinates")
        for name, limit in (("lat", 90), ("lon", 180)):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
                raise ValueError("Invalid coordinates")
    else:
        if set(payload) != {"text"} or not isinstance(payload["text"], str) or not 1 <= len(payload["text"].strip()) <= 4000:
            raise ValueError("Enter 1–4000 characters")
        if any(ord(c) < 32 and c not in "\n\t" for c in payload["text"]):
            raise ValueError("Control characters are not allowed")
    if len(canonical(payload)) > 6000:
        raise ValueError("Message is too large")
    return payload


class RoomCipher:
    def __init__(self):
        self._private = X25519PrivateKey.generate()
        self.public_key = encode(self._private.public_key().public_bytes_raw())
        self.room_id = None
        self.verified = False
        self.sent = self.received = 0

    def establish(self, room_id, own_id, members):
        if len(members) != 2 or len({m["user_id"] for m in members}) != 2:
            raise ValueError("A room must have two different analysts")
        ordered = sorted(members, key=lambda m: m["user_id"])
        own = next((m for m in ordered if m["user_id"] == own_id), None)
        if own is None or own["public_key"] != self.public_key:
            raise ValueError("Our room key was changed")
        peer = next(m for m in ordered if m["user_id"] != own_id)
        transcript = canonical({"v": 1, "room_id": room_id,
                                "members": [{k: m[k] for k in ("user_id", "username", "public_key")} for m in ordered]})
        digest = hashlib.sha256(transcript).digest()
        if self.room_id is not None:
            if self.room_id != room_id or self._digest != digest:
                self.verified = False
                raise ValueError("Room identity changed; create a new session")
            return
        shared = self._private.exchange(X25519PublicKey.from_public_bytes(decode(peer["public_key"], 32)))
        keys = HKDF(algorithm=hashes.SHA256(), length=104, salt=digest,
                    info=b"Argus Mara SOC E2EE v1").derive(shared)
        first = own_id == ordered[0]["user_id"]
        self._send_key, self._receive_key = (keys[:32], keys[32:64]) if first else (keys[32:64], keys[:32])
        self._send_prefix, self._receive_prefix = (keys[64:68], keys[68:72]) if first else (keys[68:72], keys[64:68])
        safety = hashlib.sha256(keys[72:] + digest).hexdigest()[:32].upper()
        self.safety_code = " ".join(safety[i:i+4] for i in range(0, 32, 4))
        self.room_id, self.own_id, self.peer_id, self._digest = room_id, own_id, peer["user_id"], digest

    def confirm(self):
        if not self.room_id:
            raise ValueError("Wait for the other analyst")
        self.verified = True

    def encrypt(self, kind, payload):
        if not self.verified:
            raise ValueError("Compare and confirm the safety code first")
        validate_payload(kind, payload)
        self.sent += 1
        if self.sent >= 2**64:
            raise ValueError("Create a new session")
        header = {"v": 1, "room_id": self.room_id, "sender": self.own_id, "counter": self.sent, "kind": kind}
        nonce = self._send_prefix + self.sent.to_bytes(8, "big")
        return {**header, "ciphertext": encode(AESGCM(self._send_key).encrypt(nonce, canonical(payload), canonical(header)))}

    def decrypt(self, packet):
        if not self.verified:
            raise ValueError("Compare and confirm the safety code first")
        if set(packet) != {"v", "room_id", "sender", "counter", "kind", "ciphertext"}:
            raise ValueError("Invalid encrypted envelope")
        counter = packet["counter"]
        if (packet["v"] != 1 or packet["room_id"] != self.room_id or packet["sender"] != self.peer_id or
                type(counter) is not int or not self.received < counter < 2**64 or packet["kind"] not in KINDS):
            raise ValueError("Wrong sender, session or replayed message")
        header = {k: v for k, v in packet.items() if k != "ciphertext"}
        nonce = self._receive_prefix + counter.to_bytes(8, "big")
        clear = AESGCM(self._receive_key).decrypt(nonce, decode(packet["ciphertext"]), canonical(header))
        payload = validate_payload(packet["kind"], json.loads(clear))
        self.received = counter
        return payload
