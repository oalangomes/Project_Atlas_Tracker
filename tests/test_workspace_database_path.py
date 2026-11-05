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

    def test_new_and_cloned_profiles_use_runtime_database_filename(self):
        new_id = "ws_111111111111"
        clone_id = "ws_222222222222"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.sqlite3"
            with sqlite3.connect(source, factory=ClosingConnection) as conn:
                conn.executescript("""CREATE TABLE careers(id INTEGER PRIMARY KEY,
                    fingerprint_candidate TEXT,display_name TEXT,manager_name TEXT,initial_team_name TEXT);
                    CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_date TEXT,managed_team_name TEXT,imported_at TEXT);
                    INSERT INTO careers VALUES(1,'fixture','Manager','Manager','Plymouth Argyle');""")
            manager = object.__new__(WorkspaceManager)
            manager.database_path = source
            registry = {"activeWorkspaceId": "main", "workspaces": [
                {"id": "main", "name": "Main", "kind": "main", "careerFingerprint": "fixture"}]}
            with patch("atlas.workspaces.app_data_dir", return_value=root), \
                 patch("atlas.workspaces.workspace_data_dir",
                       side_effect=lambda workspace_id: root / "workspaces" / workspace_id), \
                 patch("atlas.workspaces.current_workspace_id", return_value="main"), \
                 patch("atlas.workspaces.load_workspace_registry", return_value=registry), \
                 patch("atlas.workspaces.save_workspace_registry"), \
                 patch("atlas.workspaces._workspace_id", side_effect=[new_id, clone_id]):
                created = manager.create_empty("New career")
                self.assertEqual(created["databasePath"], str(root / "workspaces" / new_id / "atlas_tracker.sqlite3"))
                cloned = manager.clone_current("Small pilot")
                self.assertEqual(cloned["databasePath"], str(root / "workspaces" / clone_id / "atlas_tracker.sqlite3"))
                self.assertEqual(cloned["careerCount"], 1)
                self.assertFalse((root / "workspaces" / new_id / "atlas_core.sqlite3").exists())
                self.assertFalse((root / "workspaces" / clone_id / "atlas_core.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
