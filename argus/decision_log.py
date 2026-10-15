"""Tamper-evident log of analyst decisions on this computer.

Each line is one JSON record signed with this computer's Ed25519 key and
holding the SHA-256 of the line before it. Changing a letter breaks that
line's signature; removing, inserting or reordering lines breaks the chain.
The first line names the public key, so `python -m argus.decision_log verify`
needs nothing but the file. Removing the last lines leaves a valid shorter
log, so the app shows a short seal of the last line to note down.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data/desktop/decision-log.jsonl"


def default_path():
    return Path(os.environ.get("ARGUS_DECISION_LOG") or DEFAULT_PATH)


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def line_hash(line):
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def grouped(hexdigest, groups):
    text = hexdigest[:4 * groups].upper()
    return "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def fingerprint(public_key):
    """Short name of a public key, to compare between screens."""
    return grouped(hashlib.sha256(base64.b64decode(public_key)).hexdigest(), 4)


@dataclass
class Verification:
    ok: bool
    count: int = 0  # Decisions, not counting the opening record.
    key: str = ""  # Fingerprint of the key that signed the log.
    seal: str = ""  # Short hash of the last line.
    problems: list = field(default_factory=list)
    bad: dict = field(default_factory=dict)  # Record number: "changed" (its signature) or "link" (its place in the chain).

    def summary(self):
        if not self.ok:
            return self.problems[0]
        if not self.count:
            return "No decisions recorded yet."
        decisions = f"All {self.count} decisions" if self.count > 1 else "1 decision"
        return (f"{decisions} verified: every signature matches and no record is missing before the last one. "
                f"Key {self.key} · seal {self.seal}")


class DecisionLog:
    """Append-only signed records in a JSON Lines file; the private key sits next to it."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        self.key_path = self.path.with_suffix(".key")
        self._key = None

    def key(self):
        """This computer's signing key, created on first use in a file only the user can read."""
        if self._key is None:
            if self.key_path.exists():
                self._key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(self.key_path.read_text().strip()))
            else:
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                key = Ed25519PrivateKey.generate()
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(base64.b64encode(key.private_bytes_raw()).decode() + "\n")
                self._key = key
        return self._key

    def public_key(self):
        return base64.b64encode(self.key().public_key().public_bytes_raw()).decode()

    def lines(self):
        if not self.path.exists():
            return []
        return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def records(self):
        return [json.loads(line) for line in self.lines()]

    def append(self, **fields):
        """Sign and add one decision; start the log, or a new one after a key change, when needed."""
        lines = self.lines()
        if lines and json.loads(lines[0]).get("key") != self.public_key():
            # A different key signed the existing file: keep it, start a new log that names it.
            archived = self.path.with_name(f"{self.path.stem}-{time.strftime('%Y%m%d-%H%M%S')}{self.path.suffix}")
            self.path.rename(archived)
            previous = {"file": archived.name, "seal": grouped(line_hash(lines[-1]), 2)}
            lines = []
        else:
            previous = None
        if not lines:
            opening = {"seq": 0, "kind": "start", "time": now(), "key": self.public_key(),
                       "note": "Argus Mara decision log. Each record is signed and names the record before it."}
            if previous:
                opening["previous"] = previous
            lines = [self._write(opening, None)]
        record = {"seq": len(lines), "kind": "decision", "time": now(), **fields}
        self._write(record, lines[-1])
        return record

    def _write(self, record, before):
        if before is not None:
            record["prev"] = line_hash(before)
        record["sig"] = base64.b64encode(self.key().sign(canonical(record))).decode()
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return line

    def seal(self):
        """Short hash of the last line; it changes if records are removed from the end."""
        lines = self.lines()
        return grouped(line_hash(lines[-1]), 2) if lines else ""

    def verify(self):
        return verify_lines(self.lines(), expected_key=self.public_key() if self.key_path.exists() else None)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def verify_lines(lines, expected_key=None):
    """Check every signature and link. Report the first problem in plain words."""
    if not lines:
        return Verification(True)
    try:
        records = [json.loads(line) for line in lines]
    except ValueError:
        bad = next(i for i, line in enumerate(lines) if not _parses(line))
        return Verification(False, problems=[f"Record {bad} is not readable: the file was edited by hand."])
    opening = records[0]
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(opening["key"]))
    except (KeyError, TypeError, ValueError):
        return Verification(False, problems=["The first record does not name a signing key."])
    result = Verification(True, count=len(records) - 1, key=fingerprint(opening["key"]), seal=grouped(line_hash(lines[-1]), 2))
    if expected_key and opening["key"] != expected_key:
        result.problems.append(f"The log was signed with key {result.key}, not this computer's key "
                               f"{fingerprint(expected_key)}: it was replaced or comes from another computer.")
    for index, record in enumerate(records):
        unsigned = {k: v for k, v in record.items() if k != "sig"}
        try:
            public.verify(base64.b64decode(record["sig"]), canonical(unsigned))
        except (KeyError, TypeError, ValueError, InvalidSignature):
            result.problems.append(f"Record {index}: the signature does not match. The record was changed after signing.")
            result.bad[index] = "changed"
            continue
        if record.get("seq") != index:
            result.problems.append(f"Record {index}: its number is {record.get('seq')}. Records were removed or reordered.")
            result.bad[index] = "link"
        elif index and record.get("prev") != line_hash(lines[index - 1]):
            result.problems.append(f"Record {index}: the record before it was changed, removed or moved.")
            result.bad[index] = "link"
    result.ok = not result.problems
    return result


def _parses(line):
    try:
        json.loads(line)
        return True
    except ValueError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify the signed decision log.")
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("path", nargs="?", type=Path, default=None, help="log file (default: the app's log)")
    args = parser.parse_args(argv)
    path = args.path or default_path()
    if not path.exists():
        print(f"No decision log at {path}")
        return 1
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = verify_lines(lines)
    print(("OK: " if result.ok else "FAILED: ") + result.summary())
    for problem in result.problems[1:]:
        print("        " + problem)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
