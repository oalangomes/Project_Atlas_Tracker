from __future__ import annotations

import re
import shutil
import sqlite3
import uuid
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database
from .career_identity import CareerIdentityGuard
from .paths import (
    app_data_dir,
    current_workspace_id,
    load_workspace_registry,
    save_workspace_registry,
    workspace_data_dir,
    default_snapshot_root,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    name = " ".join(str(value or "").strip().split())
    if not name:
        raise ValueError("Workspace name is missing.")
    if len(name) > 80:
        raise ValueError("Workspace name must not exceed 80 characters.")
    return name


def _workspace_id() -> str:
    return "ws_" + uuid.uuid4().hex[:12]


class WorkspaceManager:
    """Manages isolated Atlas career/save workspaces.

    Main keeps the legacy database location. Career profiles and branches use isolated
    SQLite databases but share the fixed community exporter hot-folder. Switching is a
    restart boundary so only the active career profile can consume new exports.
    """

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self._migrate_current_profile_metadata()

    def _migrate_current_profile_metadata(self) -> None:
        """Adopt legacy Main metadata without moving or rewriting career state."""
        if not self.database_path.is_file() or not self.database_path.stat().st_size:
            return
        try:
            conn = sqlite3.connect(self.database_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            try:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='careers'").fetchone():
                    return
                rows = conn.execute("SELECT fingerprint_candidate, display_name, initial_team_name, initial_team_ea_id, manager_name FROM careers ORDER BY id LIMIT 2").fetchall()
                if len(rows) != 1:
                    return
                latest = conn.execute("SELECT managed_team_name FROM snapshots ORDER BY imported_at DESC, id DESC LIMIT 1").fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return
        registry = load_workspace_registry()
        workspace_id = current_workspace_id()
        changed = False
        for item in registry.get("workspaces", []):
            if str(item.get("id")) != workspace_id:
                continue
            fingerprint = str(rows[0]["fingerprint_candidate"] or "").strip()
            if fingerprint and not str(item.get("careerFingerprint") or "").strip():
                item["careerFingerprint"] = fingerprint
                changed = True
            if fingerprint and not isinstance(item.get("careerIdentity"), dict):
                item["careerIdentity"] = {
                    "version": 2, "localProfileId": workspace_id, "state": "bound",
                    "primaryFingerprint": fingerprint, "fingerprintAliases": [fingerprint],
                    "origin": {
                        "managerDisplayName": str(rows[0]["display_name"] or "").strip() or None,
                        "managerNationalityId": None,
                        "initialTeamId": None,
                        "initialTeamName": str(rows[0]["initial_team_name"] or "").strip() or None,
                    },
                    "pending": None, "migratedAt": _now(),
                }
                item["careerIdentity"]["origin"]["initialTeamId"] = rows[0]["initial_team_ea_id"]
                item["careerIdentity"]["origin"]["managerDisplayName"] = str(rows[0]["manager_name"] or rows[0]["display_name"] or "").strip() or None
                changed = True
            if workspace_id == "main" and str(item.get("name") or "").strip().casefold() == "main":
                candidate = str((latest["managed_team_name"] if latest else None) or rows[0]["initial_team_name"] or rows[0]["display_name"] or "").strip()
                if candidate:
                    item["name"] = candidate
                    changed = True
            if changed:
                item["updatedAt"] = _now()
            break
        if changed:
            save_workspace_registry(registry)

    def _workspace_stats(self, item: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(item.get("id"))
        data_dir = workspace_data_dir(workspace_id)
        db_path = data_dir / "atlas_tracker.sqlite3"
        careers = snapshots = 0
        career_row = latest_row = None
        if db_path.is_file() and db_path.stat().st_size:
            try:
                conn = sqlite3.connect(db_path, timeout=2.0)
                try:
                    has_careers = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='careers'").fetchone()
                    if has_careers:
                        careers = int(conn.execute("SELECT COUNT(*) FROM careers").fetchone()[0])
                        snapshots = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
                        career_row = conn.execute("SELECT fingerprint_candidate, display_name, manager_name, initial_team_name FROM careers ORDER BY id LIMIT 1").fetchone()
                        latest_row = conn.execute("SELECT career_date, managed_team_name FROM snapshots ORDER BY imported_at DESC, id DESC LIMIT 1").fetchone()
                finally:
                    conn.close()
            except sqlite3.Error:
                pass
        result = dict(item)
        if 'career_row' in locals() and career_row:
            result["careerFingerprint"] = str(result.get("careerFingerprint") or career_row[0] or "") or None
            result["careerDisplayName"] = career_row[1]
            result["managerName"] = career_row[2]
            result["initialTeamName"] = career_row[3]
        if 'latest_row' in locals() and latest_row:
            result["careerDate"] = latest_row[0]
            result["managedTeamName"] = latest_row[1]
        identity = result.get("careerIdentity") if isinstance(result.get("careerIdentity"), dict) else {}
        result["careerIdentityState"] = str(identity.get("state") or ("bound" if result.get("careerFingerprint") else "unbound"))
        result["pendingCareerBinding"] = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        result["careerFingerprintAliases"] = list(identity.get("fingerprintAliases") or [])
        result.update({
            "databasePath": str(db_path),
            "databaseSizeBytes": db_path.stat().st_size if db_path.is_file() else 0,
            "careerCount": careers,
            "snapshotCount": snapshots,
            "isCurrent": workspace_id == current_workspace_id(),
        })
        return result

    def overview(self) -> dict[str, Any]:
        registry = load_workspace_registry()
        items = [self._workspace_stats(dict(item)) for item in registry.get("workspaces", []) if isinstance(item, dict)]
        items.sort(key=lambda item: (0 if item.get("kind") == "main" else 1, str(item.get("createdAt") or ""), str(item.get("name") or "").casefold()))
        return {
            "model": "atlas-career-saves-v3",
            "currentWorkspaceId": current_workspace_id(),
            "nextWorkspaceId": str(registry.get("activeWorkspaceId") or "main"),
            "workspaces": items,
        }


    def create_empty(self, name: str) -> dict[str, Any]:
        """Create a blank career profile with its own DB.

        The profile remains unbound until its first valid full snapshot import. All
        community profiles watch the same fixed LUA export hot-folder; identity checks
        keep exports from being mixed into the wrong active career.
        """
        name = _safe_name(name)
        registry = load_workspace_registry()
        if any(str(item.get("name") or "").casefold() == name.casefold() for item in registry.get("workspaces", []) if isinstance(item, dict)):
            raise ValueError("A career save with this name already exists.")
        workspace_id = _workspace_id()
        relative_dir = Path("workspaces") / workspace_id
        target_dir = app_data_dir() / relative_dir
        target_dir.mkdir(parents=True, exist_ok=False)
        target_db = target_dir / "atlas_tracker.sqlite3"
        try:
            Database(target_db).initialize()
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        now = _now()
        item = {
            "id": workspace_id, "name": name, "kind": "career",
            "dataDir": str(relative_dir).replace("\\", "/"),
            "snapshotRoot": str(default_snapshot_root()),
            "sourceWorkspaceId": None, "careerFingerprint": None,
            "careerIdentity": {"version": 2, "localProfileId": workspace_id, "state": "unbound", "primaryFingerprint": None, "fingerprintAliases": [], "origin": None, "pending": None},
            "archived": False, "createdAt": now, "updatedAt": now,
        }
        registry.setdefault("workspaces", []).append(item)
        save_workspace_registry(registry)
        return self._workspace_stats(item)


    def approve_pending_binding(self, workspace_id: str) -> dict[str, Any]:
        CareerIdentityGuard.approve_pending(workspace_id)
        registry = load_workspace_registry()
        target = next(item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id)
        return self._workspace_stats(dict(target))

    def cancel_pending_binding(self, workspace_id: str) -> dict[str, Any]:
        CareerIdentityGuard.cancel_pending(workspace_id)
        registry = load_workspace_registry()
        target = next(item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id)
        return self._workspace_stats(dict(target))

    def set_archived(self, workspace_id: str, archived: bool) -> dict[str, Any]:
        if workspace_id == current_workspace_id() and archived:
            raise ValueError("The currently open career save cannot be archived.")
        registry = load_workspace_registry()
        target = None
        for item in registry.get("workspaces", []):
            if str(item.get("id")) == workspace_id:
                item["archived"] = bool(archived)
                item["updatedAt"] = _now()
                target = item
                break
        if target is None:
            raise ValueError("Career save not found.")
        save_workspace_registry(registry)
        return self._workspace_stats(dict(target))
    def clone_current(self, name: str) -> dict[str, Any]:
        name = _safe_name(name)
        registry = load_workspace_registry()
        if any(str(item.get("name") or "").casefold() == name.casefold() for item in registry.get("workspaces", []) if isinstance(item, dict)):
            raise ValueError("A workspace with this name already exists.")
        source_id = current_workspace_id()
        workspace_id = _workspace_id()
        relative_dir = Path("workspaces") / workspace_id
        target_dir = app_data_dir() / relative_dir
        target_dir.mkdir(parents=True, exist_ok=False)
        target_db = target_dir / "atlas_tracker.sqlite3"

        source = sqlite3.connect(self.database_path, timeout=30.0)
        destination = sqlite3.connect(target_db, timeout=30.0)
        try:
            source.backup(destination)
        except Exception:
            destination.close()
            source.close()
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        else:
            destination.close()
            source.close()

        source_record = next((x for x in registry.get("workspaces", []) if isinstance(x, dict) and str(x.get("id")) == source_id), {})
        source_identity = copy.deepcopy(source_record.get("careerIdentity")) if isinstance(source_record.get("careerIdentity"), dict) else None
        if source_identity is not None:
            source_identity["localProfileId"] = workspace_id
            source_identity["branchedFromProfileId"] = source_id
            source_identity["pending"] = None
        now = _now()
        item = {
            "id": workspace_id,
            "name": name,
            "kind": "branch",
            "dataDir": str(relative_dir).replace("\\", "/"),
            "snapshotRoot": str(default_snapshot_root()),
            "sourceWorkspaceId": source_id,
            "careerFingerprint": source_record.get("careerFingerprint"),
            "careerIdentity": source_identity,
            "archived": False,
            "createdAt": now,
            "updatedAt": now,
        }
        registry.setdefault("workspaces", []).append(item)
        save_workspace_registry(registry)
        return self._workspace_stats(item)

    def rename(self, workspace_id: str, name: str) -> dict[str, Any]:
        name = _safe_name(name)
        registry = load_workspace_registry()
        if any(str(item.get("id")) != workspace_id and str(item.get("name") or "").casefold() == name.casefold() for item in registry.get("workspaces", []) if isinstance(item, dict)):
            raise ValueError("A workspace with this name already exists.")
        target = None
        for item in registry.get("workspaces", []):
            if str(item.get("id")) == workspace_id:
                item["name"] = name
                item["updatedAt"] = _now()
                target = item
                break
        if target is None:
            raise ValueError("Workspace not found.")
        save_workspace_registry(registry)
        return self._workspace_stats(dict(target))

    def select_for_next_start(self, workspace_id: str) -> dict[str, Any]:
        registry = load_workspace_registry()
        target = next((item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id), None)
        if target is None:
            raise ValueError("Workspace not found.")
        if bool(target.get("archived")):
            raise ValueError("An archived career save must be restored before it can be opened.")
        registry["activeWorkspaceId"] = workspace_id
        save_workspace_registry(registry)
        return {
            "ok": True,
            "currentWorkspaceId": current_workspace_id(),
            "nextWorkspaceId": workspace_id,
            "restartRequired": workspace_id != current_workspace_id(),
        }

    def delete(self, workspace_id: str) -> dict[str, Any]:
        if workspace_id == "main":
            raise ValueError("The main workspace cannot be deleted.")
        if workspace_id == current_workspace_id():
            raise ValueError("The currently open workspace cannot be deleted. Switch to another career save first.")
        registry = load_workspace_registry()
        target = next((item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id), None)
        if target is None:
            raise ValueError("Workspace not found.")
        stats = self._workspace_stats(dict(target))
        if str(target.get("kind")) not in {"branch", "sandbox"} and int(stats.get("careerCount") or 0) > 0:
            raise ValueError("A career save with imported data cannot be deleted for safety. Archive it instead.")
        data_dir_raw = str(target.get("dataDir") or "")
        safe_id = re.fullmatch(r"ws_[0-9a-f]{12}", workspace_id)
        expected = (app_data_dir() / "workspaces" / workspace_id).resolve()
        actual = (app_data_dir() / data_dir_raw).resolve()
        if not safe_id or actual != expected:
            raise ValueError("Workspace path cannot be deleted safely.")
        registry["workspaces"] = [item for item in registry.get("workspaces", []) if str(item.get("id")) != workspace_id]
        if str(registry.get("activeWorkspaceId")) == workspace_id:
            registry["activeWorkspaceId"] = "main"
        save_workspace_registry(registry)
        shutil.rmtree(actual, ignore_errors=False)
        return {"ok": True, "deletedWorkspaceId": workspace_id}
