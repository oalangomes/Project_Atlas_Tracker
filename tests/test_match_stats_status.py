import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas.db import Database
from atlas.match_stats_importer import MatchStatsImporter


class MatchStatsStatusTests(unittest.TestCase):
    def test_revision_tracks_imports_and_relinks_without_polling_noise(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "atlas.sqlite3")
            importer = MatchStatsImporter(db)
            with patch.object(importer, "roots", return_value=[]):
                empty = importer.status()
                with db.transaction() as conn:
                    conn.execute("""
                        INSERT INTO careers (
                            id, public_id, fingerprint_candidate, display_name, created_at, updated_at
                        ) VALUES (1, 'career', 'fingerprint', 'Career', '', '')
                    """)
                    conn.executemany(
                        "INSERT INTO fixtures (id, career_id, fixture_key) VALUES (?, 1, ?)",
                        [(1, "first"), (2, "second")],
                    )
                    conn.execute("""
                        INSERT INTO match_stat_exports (
                            id, external_export_id, content_hash, export_status, imported_at
                        ) VALUES (1, 'export', 'hash', 'complete_participant_export', '2026-11-26T12:00:00Z')
                    """)
                imported = importer.status()
                self.assertNotEqual(empty["revision"], imported["revision"])
                self.assertEqual((imported["exports"], imported["linked"], imported["pending"]), (1, 0, 1))

                with db.transaction() as conn:
                    conn.execute("""
                        UPDATE match_stat_exports
                        SET career_id=1, fixture_id=1, linkage_status='linked' WHERE id=1
                    """)
                linked = importer.status()
                self.assertNotEqual(imported["revision"], linked["revision"])

                with db.transaction() as conn:
                    conn.execute("UPDATE match_stat_exports SET fixture_id=2 WHERE id=1")
                relinked = importer.status()
                self.assertNotEqual(linked["revision"], relinked["revision"])
                for key in ("exports", "linked", "pending", "lastImportAt"):
                    self.assertEqual(linked[key], relinked[key])

                importer.last_scan_at = "2026-11-26T12:00:03Z"
                self.assertEqual(relinked["revision"], importer.status()["revision"])
