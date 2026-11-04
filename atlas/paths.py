from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR_NAME = "ProjectAtlasTracker"
WORKSPACE_REGISTRY_VERSION = 3
_ACTIVE_WORKSPACE_ID: str | None = None
_ACTIVE_BASE: Path | None = None


def local_appdata() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "share"


def app_data_dir() -> Path:
    """Global Project Atlas Tracker application directory.

    Shared assets, logs and the workspace registry live here. Career/save state is
    stored below :func:`workspace_data_dir`.
    """
    path = local_appdata() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_registry_path() -> Path:
    return app_data_dir() / "workspaces.json"


def global_settings_path() -> Path:
    return app_data_dir() / "global_settings.json"


def workspace_registry_backup_paths() -> list[Path]:
    path = workspace_registry_path()
    return [path.with_suffix(".json.bak"), path.with_suffix(".json.bak2")]


def canonical_export_config_path() -> Path:
    """Path read by the FC26 Lua exporters.

    The file always mirrors the *currently running* workspace. Selecting another
    workspace does not rewrite it until Atlas is restarted, preventing an exporter
    from switching roots while the old database is still open.
    """
    return app_data_dir() / "export_path.txt"


def community_export_root() -> Path:
    """Default root used by the public FC26 community exporters."""
    profile = os.environ.get("USERPROFILE")
    documents = Path(profile) / "Documents" if profile else Path.home() / "Documents"
    return documents / "FC26 Export"


def default_snapshot_root() -> Path:
    return community_export_root() / "Snapshots"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_legacy_export_root() -> str | None:
    path = canonical_export_config_path()
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8-sig").strip()
    return value or None


def _default_registry() -> dict[str, Any]:
    now = _utc_now()
    return {
        "schemaVersion": WORKSPACE_REGISTRY_VERSION,
        "activeWorkspaceId": "main",
        "workspaces": [
            {
                "id": "main",
                "name": "Main",
                "kind": "main",
                "dataDir": ".",
                "snapshotRoot": _read_legacy_export_root() or str(default_snapshot_root()),
                "sourceWorkspaceId": None,
                "createdAt": now,
                "updatedAt": now,
                "careerFingerprint": None,
                "archived": False,
            }
        ],
    }


def _registry_valid(raw: Any) -> bool:
    return bool(isinstance(raw, dict) and isinstance(raw.get("workspaces"), list) and raw.get("workspaces"))


def _safe_workspace_data_dir(record: dict[str, Any]) -> Path:
    workspace_id = str(record.get("id") or "")
    raw = str(record.get("dataDir") or ".")
    base = app_data_dir().resolve()
    if workspace_id == "main" and raw == ".":
        return base
    if not workspace_id.startswith("ws_"):
        raise ValueError(f"Unsafe workspace ID: {workspace_id or 'empty'}")
    expected = (base / "workspaces" / workspace_id).resolve()
    actual = (base / raw).resolve()
    if actual != expected:
        raise ValueError(f"Unsafe data directory for workspace {workspace_id}: {raw}")
    return actual


def _discover_workspace_records() -> list[dict[str, Any]]:
    now = _utc_now()
    records = [_default_registry()["workspaces"][0]]
    root = app_data_dir() / "workspaces"
    if not root.is_dir():
        return records
    for folder in sorted(root.glob("ws_*")):
        if not folder.is_dir():
            continue
        workspace_id = folder.name
        if not __import__("re").fullmatch(r"ws_[0-9a-f]{12}", workspace_id):
            continue
        records.append({
            "id": workspace_id, "name": f"Recovered {workspace_id[-6:]}", "kind": "career",
            "dataDir": f"workspaces/{workspace_id}", "snapshotRoot": str(default_snapshot_root()),
            "sourceWorkspaceId": None, "createdAt": now, "updatedAt": now,
            "careerFingerprint": None, "careerIdentity": None, "archived": True, "recovered": True,
        })
    return records


def _normalize_registry(raw: dict[str, Any]) -> dict[str, Any]:
    if not any(str(item.get("id")) == "main" for item in raw.get("workspaces", []) if isinstance(item, dict)):
        raw.setdefault("workspaces", []).insert(0, _default_registry()["workspaces"][0])
    valid: list[dict[str, Any]] = []
    for item in raw.get("workspaces", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        try:
            safe_dir = _safe_workspace_data_dir(item)
        except ValueError:
            # Never trust a registry path outside the canonical workspace tree.
            continue
        # v1.0-v1.1 career workspaces used a private per-workspace export folder,
        # while the public v1.1.0 LUA exporters write to Documents\FC26 Export.
        # Upgrade only that exact Tracker-generated legacy path; intentional custom
        # roots remain untouched.
        if str(item.get("id")) != "main":
            configured = str(item.get("snapshotRoot") or "").strip()
            legacy_root = safe_dir / "exports"
            if not configured or configured.casefold() == str(legacy_root.resolve()).casefold():
                item["snapshotRoot"] = str(default_snapshot_root())
        valid.append(item)
    if not valid:
        valid = _default_registry()["workspaces"]
    raw["workspaces"] = valid
    valid_ids = {str(item.get("id")) for item in valid}
    if str(raw.get("activeWorkspaceId") or "") not in valid_ids:
        raw["activeWorkspaceId"] = "main"
    raw["schemaVersion"] = WORKSPACE_REGISTRY_VERSION
    return raw


def load_workspace_registry() -> dict[str, Any]:
    path = workspace_registry_path()
    candidates = [path, *workspace_registry_backup_paths()]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _registry_valid(raw):
            normalized = _normalize_registry(raw)
            if candidate != path:
                save_workspace_registry(normalized)
            return normalized
    # Last-resort recovery never discards workspace directories.
    registry = {
        "schemaVersion": WORKSPACE_REGISTRY_VERSION,
        "activeWorkspaceId": "main",
        "workspaces": _discover_workspace_records(),
        "recoveredAt": _utc_now(),
    }
    save_workspace_registry(registry)
    return registry


def save_workspace_registry(registry: dict[str, Any]) -> None:
    registry = _normalize_registry(dict(registry))
    path = workspace_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    backups = workspace_registry_backup_paths()
    if backups[0].exists():
        try:
            os.replace(backups[0], backups[1])
        except OSError:
            pass
    if path.exists():
        try:
            import shutil
            shutil.copy2(path, backups[0])
        except OSError:
            pass
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)

def workspace_record(workspace_id: str | None = None) -> dict[str, Any]:
    registry = load_workspace_registry()
    target = str(workspace_id or current_workspace_id())
    for item in registry["workspaces"]:
        if isinstance(item, dict) and str(item.get("id")) == target:
            return dict(item)
    raise KeyError(f"Unknown Project Atlas Tracker workspace: {target}")


def workspace_data_dir(workspace_id: str | None = None) -> Path:
    record = workspace_record(workspace_id)
    path = _safe_workspace_data_dir(record)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sync_export_config_for(workspace_id: str) -> None:
    record = workspace_record(workspace_id)
    target = canonical_export_config_path()
    root = str(record.get("snapshotRoot") or "").strip()
    if not root:
        # Never leave another workspace's root active in the canonical Lua config.
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    temp = target.with_suffix(".tmp")
    temp.write_text(root + "\n", encoding="utf-8")
    os.replace(temp, target)


def initialize_workspace_context(explicit_workspace_id: str | None = None, *, sync_export_config: bool = True) -> str:
    global _ACTIVE_WORKSPACE_ID, _ACTIVE_BASE
    base = app_data_dir().resolve()
    registry = load_workspace_registry()
    target = str(explicit_workspace_id or registry.get("activeWorkspaceId") or "main")
    valid_ids = {str(item.get("id")) for item in registry["workspaces"] if isinstance(item, dict)}
    if target not in valid_ids:
        raise ValueError(f"Project Atlas Tracker workspace does not exist: {target}")
    _ACTIVE_WORKSPACE_ID = target
    _ACTIVE_BASE = base
    if sync_export_config:
        _sync_export_config_for(target)
    return target


def current_workspace_id() -> str:
    global _ACTIVE_WORKSPACE_ID, _ACTIVE_BASE
    base = app_data_dir().resolve()
    if _ACTIVE_WORKSPACE_ID is None or _ACTIVE_BASE != base:
        initialize_workspace_context(sync_export_config=False)
    return str(_ACTIVE_WORKSPACE_ID or "main")


def reset_workspace_context_for_tests() -> None:
    global _ACTIVE_WORKSPACE_ID, _ACTIVE_BASE
    _ACTIVE_WORKSPACE_ID = None
    _ACTIVE_BASE = None


def database_path() -> Path:
    return workspace_data_dir() / "atlas_tracker.sqlite3"


def config_path() -> Path:
    """Compatibility alias for the canonical Lua exporter config."""
    return canonical_export_config_path()


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_snapshot_root() -> Path | None:
    record = workspace_record()
    value = str(record.get("snapshotRoot") or "").strip()
    # Legacy Main installations created before workspaces.json keep working even if
    # their registry entry did not yet capture export_path.txt.
    if not value and current_workspace_id() == "main":
        value = str(_read_legacy_export_root() or "").strip()
    return Path(value) if value else default_snapshot_root()


def write_snapshot_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("incoming", "ready", "imported", "failed"):
        (root / name).mkdir(parents=True, exist_ok=True)
    # Community exporters keep detailed match data next to the snapshot pipeline.
    match_stats_root = root.parent / "MatchStats" if root.name.casefold() == "snapshots" else root / "MatchStats"
    for name in ("incoming", "ready", "imported", "failed"):
        (match_stats_root / name).mkdir(parents=True, exist_ok=True)
    registry = load_workspace_registry()
    workspace_id = current_workspace_id()
    now = _utc_now()
    updated = False
    for item in registry["workspaces"]:
        if str(item.get("id")) == workspace_id:
            item["snapshotRoot"] = str(root)
            item["updatedAt"] = now
            updated = True
            break
    if not updated:
        raise ValueError(f"Active Project Atlas Tracker workspace does not exist: {workspace_id}")
    save_workspace_registry(registry)
    _sync_export_config_for(workspace_id)
    return root


def media_dir() -> Path:
    # The binary media library is intentionally shared between workspaces. Assignment
    # and career state remain isolated in each workspace database; the source/cache
    # files themselves are installation assets and do not need to be duplicated.
    path = app_data_dir() / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_originals_dir() -> Path:
    path = media_dir() / "originals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_cache_dir() -> Path:
    path = media_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_thumbnails_dir() -> Path:
    path = media_dir() / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_generated_dir() -> Path:
    path = media_dir() / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path
