"""Simulated fixtures only: durability, restart and archive-capacity boundaries."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow.parquet as pq

from argus.live_archive import ArchiveError, LiveArchive
from recorder.recorder import SCHEMA


START = datetime(2026, 10, 9, tzinfo=timezone.utc)


def row(**overrides):
    return {"recv_utc": START, "msg_type": "PositionReport", "mmsi": 123456789,
            "ship_name": "SIMULATED TEST", "lat": 53.0, "lon": -6.0, "sog": 0,
            "cog": 0, "heading": 0, "nav_status": 0, "time_utc": None,
            "raw": '{"MessageType":"PositionReport","fixture":"simulated"}', **overrides}


class LiveArchiveTests(unittest.TestCase):
    def test_append_is_fsynced_and_unflushed_record_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            with patch("argus.live_archive.os.fsync", wraps=__import__("os").fsync) as synced:
                archive.append(row())
            self.assertGreaterEqual(synced.call_count, 2)
            self.assertEqual(len(list(Path(directory).glob("pending/*.jsonl"))), 1)
            restored = LiveArchive(directory)
            restored.recover()
            self.assertEqual(list(restored.recent_rows())[0]["mmsi"], 123456789)
            self.assertEqual(list(Path(directory).glob("pending/*.jsonl")), [])

    def test_completed_chunks_match_recorder_schema_and_whitelist(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory, max_rows=2)
            archive.append(row(label="simulated", private_secret="SIMULATED PRIVATE FIELD"))
            archive.append(row(mmsi=222222222))
            path = next(Path(directory).glob("chunks/*.parquet"))
            self.assertTrue(pq.read_schema(path).equals(SCHEMA, check_metadata=False))
            records = list(archive.recent_rows())
            self.assertEqual(len(records), 2)
            self.assertEqual(set(records[0]), set(SCHEMA.names))
            self.assertIn("raw", records[0])  # Private restore only, never an API response.

    def test_crash_after_atomic_commit_does_not_duplicate_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            archive.append(row())
            original_unlink = Path.unlink

            def crash_before_journal_unlink(path, *args, **kwargs):
                if path.suffix == ".jsonl":
                    raise OSError("SIMULATED CRASH")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", crash_before_journal_unlink):
                with self.assertRaises(ArchiveError):
                    archive.flush()
            self.assertEqual(len(list(Path(directory).glob("chunks/*.parquet"))), 1)
            restored = LiveArchive(directory)
            restored.recover()
            restored.recover()
            self.assertEqual(len(list(restored.recent_rows())), 1)
            self.assertEqual(len(list(Path(directory).glob("chunks/*.parquet"))), 1)

    def test_interrupted_temporary_output_recovers_from_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            archive.append(row())
            journal = next(Path(directory).glob("pending/*.jsonl"))
            temporary = Path(directory) / "chunks" / (journal.stem + ".tmp")
            temporary.write_bytes(b"SIMULATED INCOMPLETE PARQUET")
            restored = LiveArchive(directory)
            restored.recover()
            self.assertEqual(len(list(restored.recent_rows())), 1)
            self.assertFalse(temporary.exists())

    def test_mismatched_completed_chunk_and_journal_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            archive.append(row())
            journal = next(Path(directory).glob("pending/*.jsonl"))
            destination = Path(directory) / "chunks" / (journal.stem + ".parquet")
            import pyarrow as pa
            pq.write_table(pa.Table.from_pylist([row()], schema=SCHEMA), destination)
            original_journal = journal.read_bytes()
            restored = LiveArchive(directory)
            with self.assertRaises(ArchiveError):
                restored.recover()
            self.assertTrue(destination.exists())
            self.assertEqual(journal.read_bytes(), original_journal)

    def test_torn_last_journal_record_preserves_intact_prefix_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            archive.append(row())
            journal = next(Path(directory).glob("pending/*.jsonl"))
            with journal.open("ab") as stream:
                stream.write(b'{"recv_utc": "SIMULATED TORN')
            restored = LiveArchive(directory)
            restored.recover()
            self.assertEqual(len(list(restored.recent_rows())), 1)
            backup = next(Path(directory).glob("pending/*.torn"))
            self.assertIn(b"SIMULATED TORN", backup.read_bytes())

    def test_damaged_complete_journal_record_fails_closed_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory)
            archive.append(row())
            journal = next(Path(directory).glob("pending/*.jsonl"))
            with journal.open("ab") as stream:
                stream.write(b"SIMULATED PRIVATE DAMAGED ROW\n")
            restored = LiveArchive(directory)
            with self.assertRaises(ArchiveError) as error:
                restored.recover()
            self.assertTrue(journal.exists())
            self.assertNotIn("SIMULATED PRIVATE", str(error.exception))
            with self.assertRaises(ArchiveError):
                restored.append(row())

    def test_capacity_stops_ingestion_and_retains_existing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory, max_archive_bytes=700)
            archive.append(row())
            journal = next(Path(directory).glob("pending/*.jsonl"))
            contents = journal.read_bytes()
            with self.assertRaises(ArchiveError):
                archive.append(row(raw="SIMULATED " + "x" * 600))
            self.assertEqual(journal.read_bytes(), contents)
            with self.assertRaises(ArchiveError):
                archive.append(row())

    def test_old_chunks_remain_on_disk_but_restore_window_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory, max_rows=1)
            archive.append(row())
            archive.append(row(recv_utc=START + timedelta(hours=72), mmsi=222222222))
            self.assertEqual([record["mmsi"] for record in archive.recent_rows()], [222222222])
            self.assertEqual(len(list(archive.recent_rows(max_age_hours=None))), 2)
            self.assertEqual(len(list(Path(directory).glob("chunks/*.parquet"))), 2)

    def test_invalid_or_oversized_input_does_not_leak_or_create_a_journal(self):
        for bad in (row(recv_utc=START.replace(tzinfo=None)), row(raw="SIMULATED " + "x" * 65_536)):
            with self.subTest(case=type(bad["recv_utc"]).__name__), tempfile.TemporaryDirectory() as directory:
                archive = LiveArchive(directory)
                with self.assertRaises(ArchiveError) as error:
                    archive.append(bad)
                self.assertNotIn("SIMULATED", str(error.exception))
                self.assertEqual(list(Path(directory).glob("pending/*.jsonl")), [])

    def test_nonfinite_parsed_numbers_become_null_while_private_raw_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LiveArchive(directory, max_rows=1)
            archive.append(row(lat=float("nan"), cog=float("inf")))
            restored = list(archive.recent_rows())[0]
            self.assertIsNone(restored["lat"])
            self.assertIsNone(restored["cog"])
            self.assertEqual(restored["raw"], row()["raw"])


if __name__ == "__main__":
    unittest.main()
