"""Workspace overview and delete guard must inspect the runtime SQLite path."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas.db import ClosingConnection
from atlas.workspaces import WorkspaceManager


class WorkspaceDatabasePathTests(unittest.TestCase):
    def test_overview_and_delete_guard_use_atlas_tracker_database(self):
        workspace_id = "ws_f5151a33099c"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_dir = root / "workspaces" / workspace_id
            data_dir.mkdir(parents=True)
            runtime_db = data_dir / "atlas_tracker.sqlite3"
            with sqlite3.connect(runtime_db, factory=ClosingConnection) as conn:
                conn.executescript("""CREATE TABLE careers(id INTEGER PRIMARY KEY,
                    fingerprint_candidate TEXT,display_name TEXT,manager_name TEXT,initial_team_name TEXT);
                    CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_date TEXT,managed_team_name TEXT,imported_at TEXT);
                    INSERT INTO careers VALUES(1,'fc26v2-e7050151','Alan Gomes','Alan Gomes','Plymouth Argyle');
                    INSERT INTO snapshots VALUES(1,'2025-10-25','Plymouth Argyle','2026-11-03');""")
            with sqlite3.connect(data_dir / "atlas_core.sqlite3", factory=ClosingConnection) as conn:
                conn.executescript("CREATE TABLE careers(id INTEGER); CREATE TABLE snapshots(id INTEGER);")
            item = {"id": workspace_id, "name": "ARGILA", "kind": "career",
                    "dataDir": f"workspaces/{workspace_id}"}
            manager = WorkspaceManager(root / "nonexistent.sqlite3")
            with patch("atlas.workspaces.workspace_data_dir", return_value=data_dir), \
                 patch("atlas.workspaces.app_data_dir", return_value=root), \
                 patch("atlas.workspaces.current_workspace_id", return_value="main"), \
                 patch("atlas.workspaces.load_workspace_registry",
                       return_value={"activeWorkspaceId": "main", "workspaces": [item]}), \
                 patch("atlas.workspaces.shutil.rmtree") as remove:
                stats = manager._workspace_stats(item)
                self.assertEqual(stats["databasePath"], str(runtime_db))
                self.assertEqual(stats["databaseSizeBytes"], runtime_db.stat().st_size)
                self.assertEqual(stats["careerCount"], 1)
                self.assertEqual(stats["snapshotCount"], 1)
                with self.assertRaisesRegex(ValueError, "cannot be deleted"):
                    manager.delete(workspace_id)
                remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
