"""SOC E2EE v2. Only endpoints import this module; relay never has keys.

Pairwise X25519 channels in a frozen group roster; HKDF separates directions; AES-256-GCM
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


def safety_display(material):
    """A shorter readable encoding of all 128 verification bits, not truncation."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    value = int.from_bytes(material[:16], 'big')
    characters = []
    for _ in range(26):
        characters.append(alphabet[value & 31])
        value >>= 5
    result = ''.join(reversed(characters))
    return ' '.join(result[i:i+5] for i in range(0, 26, 5))


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
        self.sent = 0
        self.received = {}

    def establish(self, room_id, own_id, members):
        if not 2 <= len(members) <= 16 or len({m["user_id"] for m in members}) != len(members):
            raise ValueError("A room must have 2–16 different analysts")
        ordered = sorted(members, key=lambda m: m["user_id"])
        own = next((m for m in ordered if m["user_id"] == own_id), None)
        if own is None or own["public_key"] != self.public_key:
            raise ValueError("Our room key was changed")
        transcript = canonical({"v": 2, "room_id": room_id,
                                "members": [{k: m[k] for k in ("user_id", "username", "public_key")} for m in ordered]})
        digest = hashlib.sha256(transcript).digest()
        if self.room_id is not None:
            if self.room_id != room_id or self._digest != digest:
                self.verified = False
                raise ValueError("Room identity changed; create a new session")
            return
        channels, safety_codes = {}, {}
        for peer in ordered:
            if peer['user_id'] == own_id:
                continue
            shared = self._private.exchange(X25519PublicKey.from_public_bytes(decode(peer['public_key'], 32)))
            pair = sorted([own_id, peer['user_id']])
            keys = HKDF(algorithm=hashes.SHA256(), length=104, salt=digest,
                        info=b'Argus Mara SOC E2EE v2' + canonical(pair)).derive(shared)
            first = own_id == pair[0]
            channels[peer['user_id']] = (keys[:32], keys[32:64], keys[64:68], keys[68:72]) if first else (keys[32:64], keys[:32], keys[68:72], keys[64:68])
            safety_codes[peer['user_id']] = safety_display(hashlib.sha256(keys[72:] + digest).digest())
        self.channels, self.safety_codes = channels, safety_codes
        self.safety_code = next(iter(safety_codes.values()))  # Two-person UI compatibility.
        self.room_id, self.own_id, self._digest = room_id, own_id, digest

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
        header = {"v": 2, "room_id": self.room_id, "sender": self.own_id, "counter": self.sent, "kind": kind}
        ciphertexts = {}
        for recipient, (send_key, _, prefix, _) in self.channels.items():
            nonce = prefix + self.sent.to_bytes(8, 'big')
            ciphertexts[recipient] = encode(AESGCM(send_key).encrypt(nonce, canonical(payload), canonical({**header, 'recipient': recipient})))
        return {**header, 'ciphertexts': ciphertexts}

    def decrypt(self, packet):
        if not self.verified:
            raise ValueError("Compare and confirm the safety code first")
        if set(packet) != {"v", "room_id", "sender", "counter", "kind", "ciphertexts"}:
            raise ValueError("Invalid encrypted envelope")
        counter = packet["counter"]
        sender = packet['sender']
        if (packet["v"] != 2 or packet["room_id"] != self.room_id or sender not in self.channels or
                type(counter) is not int or not self.received.get(sender, 0) < counter < 2**64 or packet["kind"] not in KINDS):
            raise ValueError("Wrong sender, session or replayed message")
        if not isinstance(packet['ciphertexts'], dict) or set(packet['ciphertexts']) != ({self.own_id} | set(self.channels)) - {sender}:
            raise ValueError('Recipient roster changed')
        header = {k: v for k, v in packet.items() if k != 'ciphertexts'}
        _, receive_key, _, prefix = self.channels[sender]
        nonce = prefix + counter.to_bytes(8, 'big')
        clear = AESGCM(receive_key).decrypt(nonce, decode(packet['ciphertexts'][self.own_id]), canonical({**header, 'recipient': self.own_id}))
        payload = validate_payload(packet["kind"], json.loads(clear))
        self.received[sender] = counter
        return payload
