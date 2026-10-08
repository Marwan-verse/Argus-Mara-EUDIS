"""Small, dependency-free helpers for reproducible Space evidence files."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from argus.space import timestamp


LABELS = {"real", "reconstructed", "simulated", "fictional", "assumption"}


def utc(value):
    return datetime.fromtimestamp(timestamp(value), timezone.utc).isoformat().replace("+00:00", "Z")


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def time_range(points, key="ts"):
    times = sorted({utc(point[key]) for point in points}, key=timestamp)
    return {"first_utc": times[0] if times else None, "last_utc": times[-1] if times else None,
            "observation_count": len(points), "continuous_coverage": False}


def source_record(path, role, label):
    if label not in LABELS:
        raise ValueError("source label must be one of " + ", ".join(sorted(LABELS)))
    path = Path(path)
    return {"file": path.name, "role": role, "label": label, "sha256": sha256(path),
            "bytes": path.stat().st_size}
