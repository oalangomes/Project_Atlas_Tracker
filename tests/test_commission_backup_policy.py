"""Derived report operations do not make full database backups."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atlas.db import ClosingConnection, Database
from atlas.server_http import ApiHandler


class TinyDatabase:
    def __init__(self, path):
        self.path = path
        with self.connect() as conn:
            conn.executescript("CREATE TABLE careers(id INTEGER PRIMARY KEY);"
                               "CREATE TABLE snapshots(career_id INTEGER, season_index INTEGER, import_sequence INTEGER, id INTEGER);"
                               "INSERT INTO careers VALUES(1); INSERT INTO snapshots VALUES(1,1,1,7);")
        self.create_backup = Mock(side_effect=AssertionError("unexpected backup"))

    def connect(self):
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn


class BackupPolicyTests(unittest.TestCase):
    def test_replay_start_and_resume_never_copy_database(self):
        with tempfile.TemporaryDirectory() as temp:
            database = TinyDatabase(Path(temp) / "tiny.sqlite3")
            handler = SimpleNamespace(state=SimpleNamespace(database=database), _json=Mock())
            for resumable, expected_path in ((None, ""), ({"backup_path": "legacy_backup.sqlite3"},
                                                       "legacy_backup.sqlite3")):
                with self.subTest(resumable=resumable), \
                     patch("atlas.commission.ollama_models", return_value={"available": True,
                                                                            "models": ["qwen3.5:9b"]}), \
                     patch("atlas.commission._find_resumable_replay", return_value=resumable), \
                     patch("atlas.commission.start_retroactive_commission_reports",
                           return_value={"job_id": "test-job", "status": "running"}) as start:
                    ApiHandler._api_post(handler, "/api/careers/1/commission/retroactive-report-jobs",
                                         {"season_index": 1})
                    self.assertEqual(start.call_args.args[-1], expected_path)
                    self.assertFalse(handler._json.call_args.args[0]["backup_created"])
                    database.create_backup.assert_not_called()

    def test_explicit_backup_and_destructive_reset_protection_remain(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "tiny.sqlite3")
            with db.connect() as conn:
                conn.execute("CREATE TABLE test_marker(value TEXT)")
                conn.execute("INSERT INTO test_marker VALUES('kept')")
            backup = db.create_backup("explicit_test")
            try:
                self.assertTrue(backup.exists())
                with sqlite3.connect(backup, factory=ClosingConnection) as conn:
                    self.assertEqual(conn.execute("SELECT value FROM test_marker").fetchone()[0], "kept")
            finally:
                backup.unlink(missing_ok=True)
            from atlas.career_reset import CareerResetService
            with db.connect() as conn:
                conn.execute("""INSERT INTO careers(public_id,fingerprint_candidate,display_name,created_at,updated_at)
                              VALUES('test-career','test-fingerprint','Test','2025-01-01','2025-01-01')""")
                conn.execute("""INSERT INTO snapshots(career_id,external_snapshot_id,schema_version,
                              season_index,career_date,career_date_sort,exported_at_utc,content_hash,
                              import_status,source_path,imported_at,import_sequence)
                              VALUES(1,'snapshot-1','1',1,'2025-01-01',20250101,'2025-01-01',
                              'content-1','imported','fixture','2025-01-01',1)""")
            with patch.object(db, "create_backup", side_effect=RuntimeError("protected")) as guard:
                with self.assertRaisesRegex(RuntimeError, "protected"):
                    CareerResetService(db).reset_to_snapshot(1, 1)
                guard.assert_called_once()


if __name__ == "__main__":
    unittest.main()
