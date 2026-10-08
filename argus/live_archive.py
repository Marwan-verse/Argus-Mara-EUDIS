"""Private, bounded-memory AIS archive for the optional shared live service.

``append`` fsyncs a schema-whitelisted JSONL journal before returning. ``flush``
commits recorder-schema Parquet atomically, then retires its matching journal.
Chunk IDs and a journal digest make crash recovery idempotent. Nothing is deleted
to meet the capacity limit: a full disk/archive stops ingestion. This protects
accepted local records, not packets never delivered by the upstream AIS provider.

Use one serial writer (for example serial ``await asyncio.to_thread(...)`` calls).
Raw messages stay private on the archive volume and must never be returned by an
HTTP endpoint. Exceptions deliberately omit message content and secret values.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from recorder.recorder import SCHEMA


class ArchiveError(RuntimeError):
    """Storage/integrity failure: stop collecting rather than drop history."""


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LiveArchive:
    def __init__(self, root, flush_seconds=300, max_rows=4096,
                 max_archive_bytes=450 * 1024 * 1024):
        if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 4096:
            raise ValueError("max_rows must be between 1 and 4096")
        if not math.isfinite(flush_seconds) or flush_seconds <= 0:
            raise ValueError("flush_seconds must be finite and positive")
        if not isinstance(max_archive_bytes, int) or max_archive_bytes <= 0:
            raise ValueError("max_archive_bytes must be a positive integer")
        self.root = Path(root)
        self.flush_seconds = flush_seconds
        self.max_rows = max_rows
        self.max_archive_bytes = max_archive_bytes
        self._rows = []
        self._buffer_bytes = 0
        self._journal = None
        self._started = time.monotonic()
        self._recovered = False
        self._failed = False
        self._next_id = 1
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.chunks = self.root / "chunks"
            self.pending = self.root / "pending"
            self.chunks.mkdir(exist_ok=True)
            self.pending.mkdir(exist_ok=True)
            self._bytes = self._stored_bytes()
        except OSError:
            raise ArchiveError("Cannot initialize private archive storage") from None

    def _stored_bytes(self):
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    @property
    def used_bytes(self):
        """Last accounted private storage size; contains no paths or raw data."""
        return self._bytes

    def stats(self):
        """Safe scalar health data; a stopped archive must stop the collector."""
        return {"bytes": self._bytes, "max_bytes": self.max_archive_bytes,
                "pending_rows": len(self._rows), "stopped": self._failed}

    def _ready(self):
        if self._failed:
            raise ArchiveError("Archive is stopped after a storage or integrity failure")
        if not self._recovered:
            self.recover()

    def _capacity(self, additional):
        if self._bytes + additional > self.max_archive_bytes:
            raise ArchiveError("Private archive capacity reached; history was retained")

    @staticmethod
    def _normalize(row):
        clean = {field.name: row.get(field.name) for field in SCHEMA}
        received = clean["recv_utc"]
        if isinstance(received, str):
            received = datetime.fromisoformat(received.replace("Z", "+00:00"))
        if not isinstance(received, datetime) or received.tzinfo is None:
            raise ValueError("Invalid receive timestamp")
        clean["recv_utc"] = received.astimezone(timezone.utc)
        if clean["raw"] is not None and (not isinstance(clean["raw"], str) or len(clean["raw"].encode("utf-8")) > 65_536):
            raise ValueError("Invalid raw message size")
        for name in ("lat", "lon", "sog", "cog", "heading"):
            value = clean[name]
            if value is not None and not math.isfinite(float(value)):
                clean[name] = None
        # Reuse the recorder's types, including millisecond UTC timestamps.
        return pa.Table.from_pylist([clean], schema=SCHEMA).to_pylist()[0]

    @staticmethod
    def _encoded(row):
        serializable = {**row, "recv_utc": row["recv_utc"].isoformat()}
        return (json.dumps(serializable, ensure_ascii=False, separators=(",", ":"),
                           allow_nan=False) + "\n").encode("utf-8")

    def append(self, row):
        """Persist a private recorder row before the caller publishes its state."""
        try:
            self._ready()
            clean = self._normalize(row)
            encoded = self._encoded(clean)
            if len(encoded) > 131_072:
                raise ValueError("Journal row exceeds safety limit")
            self._capacity(len(encoded))
            if self._journal is None:
                self._journal = self.pending / f"{self._next_id:020d}.jsonl"
                self._next_id += 1
                self._started = time.monotonic()
            new_file = not self._journal.exists()
            with self._journal.open("ab", buffering=0) as stream:
                if stream.write(encoded) != len(encoded):
                    raise OSError("Short journal write")
                os.fsync(stream.fileno())
            if new_file:
                _sync_directory(self.pending)
            self._bytes += len(encoded)
            self._rows.append(clean)
            self._buffer_bytes += len(encoded)
            if (len(self._rows) >= self.max_rows or self._buffer_bytes >= 8 * 1024 * 1024
                    or time.monotonic() - self._started >= self.flush_seconds):
                self.flush()
        except ArchiveError:
            self._failed = True
            raise
        except Exception:
            self._failed = True
            raise ArchiveError("Cannot durably append an AIS record; collection must stop") from None

    def _read_journal(self, path):
        rows, digest, valid_bytes = [], hashlib.sha256(), 0
        with path.open("rb") as stream:
            while True:
                line = stream.readline(131_073)
                if not line:
                    break
                if len(line) > 131_072:
                    raise ArchiveError("Oversized private journal record")
                try:
                    row = self._normalize(json.loads(line))
                except Exception:
                    if line.endswith(b"\n") or stream.read(1):
                        raise ArchiveError("Private journal contains a damaged record") from None
                    # Preserve the damaged tail for inspection before truncating
                    # the active journal to its intact, acknowledged prefix.
                    backup = path.with_suffix(".torn")
                    if backup.exists():
                        backup = path.with_suffix(".torn." + uuid.uuid4().hex)
                    self._capacity(path.stat().st_size)
                    shutil.copyfile(path, backup)
                    with backup.open("rb") as saved:
                        os.fsync(saved.fileno())
                    _sync_directory(self.pending)
                    with path.open("r+b") as repaired:
                        repaired.truncate(valid_bytes)
                        os.fsync(repaired.fileno())
                    self._bytes = self._stored_bytes()
                    break
                if len(rows) >= self.max_rows:
                    raise ArchiveError("Private journal exceeds configured recovery row bound")
                if valid_bytes + len(line) > 8 * 1024 * 1024 + 131_072:
                    raise ArchiveError("Private journal exceeds configured recovery memory bound")
                rows.append(row)
                digest.update(line)
                valid_bytes += len(line)
        return rows, digest.hexdigest()

    def _commit(self, journal, rows, digest):
        destination = self.chunks / (journal.stem + ".parquet")
        if destination.exists():
            metadata = pq.read_metadata(destination)
            stored = metadata.metadata or {}
            if (metadata.num_rows != len(rows) or stored.get(b"argus_journal_sha256") != digest.encode()
                    or not metadata.schema.to_arrow_schema().equals(SCHEMA, check_metadata=False)):
                raise ArchiveError("Committed chunk does not match its pending journal")
        elif rows:
            temporary = destination.with_suffix(".tmp")
            schema = SCHEMA.with_metadata({b"argus_journal_sha256": digest.encode(),
                                           b"argus_chunk_id": journal.stem.encode()})
            table = pa.Table.from_pylist(rows, schema=schema)
            # Reserve room for an uncompressed row-sized working copy. The
            # configured cap includes journals and temporary commit files.
            self._capacity(journal.stat().st_size + 16 * 1024)
            pq.write_table(table, temporary, compression="zstd")
            temporary_bytes = temporary.stat().st_size
            self._capacity(temporary_bytes)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            _sync_directory(self.chunks)
            self._bytes += temporary_bytes
        journal_bytes = journal.stat().st_size
        journal.unlink()
        _sync_directory(self.pending)
        self._bytes -= journal_bytes

    def flush(self):
        """Commit the active journal; safe after a normal stop or feed drop."""
        try:
            self._ready()
            if self._journal is None:
                return
            rows, digest = self._read_journal(self._journal)
            self._commit(self._journal, rows, digest)
            self._journal = None
            self._rows.clear()
            self._buffer_bytes = 0
            self._started = time.monotonic()
        except ArchiveError:
            self._failed = True
            raise
        except Exception:
            self._failed = True
            raise ArchiveError("Cannot commit private archive; journal was retained") from None

    def recover(self):
        """Commit intact pending records once, including after rename/unlink crashes."""
        if self._failed:
            raise ArchiveError("Archive is stopped after a storage or integrity failure")
        if self._journal is not None:
            raise ArchiveError("Cannot recover while a writer journal is active")
        try:
            # An interrupted temporary output is reproducible from its durable
            # journal; remove only that output, never source history.
            for temporary in self.chunks.glob("*.tmp"):
                if re.fullmatch(r"\d{20}", temporary.stem) and (self.pending / (temporary.stem + ".jsonl")).exists():
                    temporary.unlink()
            self._bytes = self._stored_bytes()
            self._capacity(0)
            ids = [int(path.stem) for folder, extension in ((self.pending, ".jsonl"), (self.chunks, ".parquet"))
                   for path in folder.glob("*" + extension) if re.fullmatch(r"\d{20}", path.stem)]
            self._next_id = max(ids, default=0) + 1
            for journal in sorted(self.pending.glob("*.jsonl")):
                if not re.fullmatch(r"\d{20}", journal.stem):
                    raise ArchiveError("Unexpected private journal filename")
                rows, digest = self._read_journal(journal)
                self._commit(journal, rows, digest)
            # .tmp files have no published chunk identity. A matching durable
            # journal has just been recovered above, so these outputs are stale.
            for temporary in self.chunks.glob("*.tmp"):
                if (re.fullmatch(r"\d{20}", temporary.stem)
                        and (self.chunks / (temporary.stem + ".parquet")).exists()):
                    temporary.unlink()
            _sync_directory(self.chunks)
            self._bytes = self._stored_bytes()
            self._recovered = True
        except ArchiveError:
            self._failed = True
            raise
        except Exception:
            self._failed = True
            raise ArchiveError("Cannot recover private archive; source records were retained") from None

    def recent_rows(self, max_age_hours=48):
        """Stream private rows from the recent archive, using small Arrow batches.

        The window is relative to the latest archived receive time, including
        simulated fixtures; it is not relative to the process wall clock.
        Passing ``None`` streams the entire archive without accumulating rows.
        """
        self._ready()
        if self._journal is not None:
            self.flush()
        if max_age_hours is not None and (not math.isfinite(max_age_hours) or max_age_hours <= 0):
            raise ValueError("max_age_hours must be positive or None")
        files = sorted(self.chunks.glob("*.parquet"))
        latest = None
        if files:
            for batch in pq.ParquetFile(files[-1]).iter_batches(batch_size=512, columns=["recv_utc"]):
                for received in batch.column(0).to_pylist():
                    if received is not None:
                        latest = max(latest, received) if latest else received
        cutoff = latest - timedelta(hours=max_age_hours) if latest and max_age_hours is not None else None
        for path in files:
            parquet = pq.ParquetFile(path)
            if cutoff is not None:
                stats = [parquet.metadata.row_group(index).column(0).statistics
                         for index in range(parquet.metadata.num_row_groups)]
                if stats and all(stat is not None and stat.has_min_max and stat.max < cutoff for stat in stats):
                    continue
            for batch in parquet.iter_batches(batch_size=512):
                for row in batch.to_pylist():
                    if cutoff is None or row["recv_utc"] >= cutoff:
                        yield row
