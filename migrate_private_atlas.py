from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from atlas.db import Database


APP_NAME = "ProjectAtlasTracker"
DB_NAMES = ("atlas_tracker.sqlite3", "atlas_core.sqlite3", "atlas_tracker.sqlite", "atlas_core.sqlite")
SKIP_TABLES = {"app_meta", "sqlite_sequence"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def local_appdata() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "share"


def default_target() -> Path:
    return local_appdata() / APP_NAME / "atlas_tracker.sqlite3"


def _candidate_summary(path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "path": path,
        "modified": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "size": int(path.stat().st_size),
        "careers": [],
        "careerCount": 0,
        "snapshotCount": 0,
    }
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "careers" in tables:
                columns_available = {
                    str(row[1]) for row in conn.execute("PRAGMA table_info(careers)").fetchall()
                }
                wanted = [
                    name for name in (
                        "id", "display_name", "manager_name", "initial_team_name",
                        "updated_at", "fingerprint_candidate"
                    ) if name in columns_available
                ]
                if wanted:
                    rows = conn.execute(
                        "SELECT " + ",".join(quote(name) for name in wanted) +
                        " FROM careers ORDER BY " +
                        ("updated_at DESC" if "updated_at" in columns_available else "id DESC") +
                        " LIMIT 8"
                    ).fetchall()
                    summary["careers"] = [dict(row) for row in rows]
                    summary["careerCount"] = int(conn.execute("SELECT COUNT(*) FROM careers").fetchone()[0])
            if "snapshots" in tables:
                summary["snapshotCount"] = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    except sqlite3.Error as exc:
        summary["error"] = str(exc)
    return summary


def _candidate_label(summary: dict[str, object]) -> str:
    careers = summary.get("careers") or []
    career_count = int(summary.get("careerCount") or 0)
    snapshot_count = int(summary.get("snapshotCount") or 0)
    if careers:
        first = careers[0]
        team = str(first.get("initial_team_name") or first.get("display_name") or "Unknown career")
        manager = str(first.get("manager_name") or "").strip()
        updated = str(first.get("updated_at") or summary.get("modified") or "")
        extra = f" +{career_count - 1} more" if career_count > 1 else ""
        manager_part = f" · {manager}" if manager else ""
        return f"{team}{manager_part}{extra} · {snapshot_count} snapshots · updated {updated}"
    return f"No readable career metadata · modified {summary.get('modified')}"


def discover_sources(target: Path) -> list[Path]:
    root = local_appdata()
    candidates: list[Path] = []

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if not resolved.is_file() or resolved == target.resolve() or resolved in candidates:
            return
        candidates.append(resolved)

    # Private Atlas used several app-data root names over its lifetime. The
    # original/private build most commonly lives under FC26CareerTracker and
    # stores each career below workspaces\ws_*\atlas_core.sqlite3. Search the
    # complete known roots recursively so every workspace is offered separately.
    known_legacy_roots = (
        root / "FC26CareerTracker",
        root / "ProjectAtlas",
        root / "Project Atlas",
    )
    for legacy_root in known_legacy_roots:
        if not legacy_root.is_dir():
            continue
        for name in DB_NAMES:
            add(legacy_root / name)
            for path in legacy_root.rglob(name):
                add(path)

    # Last-resort compatibility with custom/renamed Atlas app-data directories.
    # A direct root DB is enough to identify a likely Atlas folder; once found,
    # also inspect its workspaces directory recursively rather than stopping at
    # the root database. This avoids a broad recursive scan of all LOCALAPPDATA.
    if root.is_dir():
        for app_dir in root.iterdir():
            if not app_dir.is_dir() or app_dir in known_legacy_roots:
                continue
            has_root_db = False
            for name in DB_NAMES:
                candidate = app_dir / name
                if candidate.is_file():
                    has_root_db = True
                    add(candidate)
            workspace_root = app_dir / "workspaces"
            if has_root_db and workspace_root.is_dir():
                for name in DB_NAMES:
                    for path in workspace_root.rglob(name):
                        add(path)

    # Newest files first makes the current workspace easy to spot, but selection
    # remains explicit whenever discovery is used.
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates


def choose_source(candidates: list[Path]) -> Path:
    if not candidates:
        raise RuntimeError(
            "No private Atlas database was found automatically. Run this script with "
            "--source followed by the full path to atlas_core.sqlite / atlas_tracker.sqlite3."
        )
    summaries = [_candidate_summary(path) for path in candidates]
    if not sys.stdin.isatty():
        joined = "\n".join(
            f"  {index}. {_candidate_label(summary)}\n     {summary['path']}"
            for index, summary in enumerate(summaries, start=1)
        )
        raise RuntimeError(
            "Automatic migration requires an explicit source selection when no interactive console is available.\n"
            + joined + "\nUse --source to select one."
        )

    print("Atlas career databases found:\n")
    for index, summary in enumerate(summaries, start=1):
        print(f"  {index}. {_candidate_label(summary)}")
        print(f"     {summary['path']}")
    print("\nNothing has been copied yet.")
    while True:
        raw = input("Select the career database to migrate (or Q to cancel): ").strip()
        if raw.casefold() in {"q", "quit", "cancel"}:
            raise RuntimeError("Migration cancelled.")
        try:
            selected = int(raw) - 1
            if 0 <= selected < len(candidates):
                return candidates[selected]
        except ValueError:
            pass
        print("Please enter one of the listed numbers.")


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_names(conn: sqlite3.Connection, schema: str) -> set[str]:
    rows = conn.execute(
        f"SELECT name FROM {quote(schema)}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def columns(conn: sqlite3.Connection, schema: str, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA {quote(schema)}.table_info({quote(table)})").fetchall()


def target_is_empty(conn: sqlite3.Connection) -> bool:
    for table in ("careers", "snapshots"):
        if conn.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]:
            return False
    return True


def copy_tables(conn: sqlite3.Connection) -> tuple[list[tuple[str, int]], list[tuple[str, str]]]:
    source_tables = table_names(conn, "legacy")
    target_tables = table_names(conn, "main")
    copied: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []
    for table in sorted((source_tables & target_tables) - SKIP_TABLES):
        target_info = columns(conn, "main", table)
        source_columns = {str(row[1]) for row in columns(conn, "legacy", table)}
        common = [str(row[1]) for row in target_info if str(row[1]) in source_columns]
        required_missing = [
            str(row[1])
            for row in target_info
            if str(row[1]) not in source_columns
            and int(row[3] or 0) == 1
            and row[4] is None
            and int(row[5] or 0) == 0
        ]
        if required_missing:
            skipped.append((table, "missing required columns: " + ", ".join(required_missing)))
            continue
        if not common:
            skipped.append((table, "no compatible columns"))
            continue
        names = ",".join(quote(name) for name in common)
        conn.execute(f"INSERT INTO main.{quote(table)} ({names}) SELECT {names} FROM legacy.{quote(table)}")
        count = int(conn.execute("SELECT changes()").fetchone()[0])
        copied.append((table, count))
    return copied, skipped


def integrity_errors(conn: sqlite3.Connection) -> list[str]:
    errors = [" | ".join(str(value) for value in row) for row in conn.execute("PRAGMA foreign_key_check")]
    result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if result.casefold() != "ok":
        errors.append(result)
    return errors


def update_main_identity(target: Path) -> None:
    registry_path = target.parent / "workspaces.json"
    if not registry_path.is_file():
        return
    with sqlite3.connect(target) as conn:
        conn.row_factory = sqlite3.Row
        careers = conn.execute("SELECT * FROM careers ORDER BY id LIMIT 2").fetchall()
    if len(careers) != 1:
        return
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    career = careers[0]
    fingerprint = str(career["fingerprint_candidate"] or "").strip()
    if not fingerprint:
        return
    for workspace in registry.get("workspaces", []):
        if str(workspace.get("id")) != "main":
            continue
        workspace["name"] = str(career["initial_team_name"] or career["display_name"] or "Main")
        workspace["careerFingerprint"] = fingerprint
        workspace["careerIdentity"] = {
            "version": 2,
            "localProfileId": "main",
            "state": "bound",
            "primaryFingerprint": fingerprint,
            "fingerprintAliases": [fingerprint],
            "origin": {
                "managerDisplayName": career["manager_name"],
                "managerNationalityId": None,
                "initialTeamId": career["initial_team_ea_id"],
                "initialTeamName": career["initial_team_name"],
            },
            "pending": None,
            "migratedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        break
    temporary = registry_path.with_suffix(".json.migration.tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, registry_path)


def _unique_sibling(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _sqlite_backup(source: Path, destination: Path) -> None:
    """Copy a SQLite database through SQLite itself, without renaming/deleting source."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source, timeout=60)
    dst = sqlite3.connect(destination, timeout=60)
    try:
        src.execute("PRAGMA busy_timeout = 60000")
        dst.execute("PRAGMA busy_timeout = 60000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _sqlite_readonly_snapshot(source: Path, destination: Path) -> None:
    """Create a transactionally consistent local copy of a legacy DB via a read-only URI.

    The source is opened with sqlite3.connect(..., uri=True), where Windows file URIs
    are supported reliably.  We deliberately do not pass the URI through ATTACH
    DATABASE: ATTACH on a non-URI main connection can treat ``file:///C:/...`` as a
    literal filename on Windows and fail with "unable to open database".
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.as_uri() + "?mode=ro"
    src = sqlite3.connect(source_uri, uri=True, timeout=60)
    dst = sqlite3.connect(destination, timeout=60)
    try:
        src.execute("PRAGMA busy_timeout = 60000")
        dst.execute("PRAGMA busy_timeout = 60000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _publish_staging(staging: Path, target: Path) -> None:
    """Replace target contents via SQLite backup, never via filesystem replace/unlink."""
    src = sqlite3.connect(staging, timeout=60)
    dst = sqlite3.connect(target, timeout=60)
    try:
        src.execute("PRAGMA busy_timeout = 60000")
        dst.execute("PRAGMA busy_timeout = 60000")
        # backup() replaces the destination database image while keeping the
        # destination path itself intact. This avoids Windows sharing violations
        # from antivirus/indexers or short-lived SQLite file handles.
        src.backup(dst)
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        dst.close()
        src.close()


def _cleanup_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def migrate(source: Path, target: Path, *, replace_existing: bool = False) -> dict[str, object]:
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Source database does not exist: {source}")
    if source == target:
        raise RuntimeError("Source and target database must be different.")
    target.parent.mkdir(parents=True, exist_ok=True)

    target_had_data = False
    if target.is_file() and target.stat().st_size:
        try:
            with sqlite3.connect(target, timeout=60) as existing:
                existing.execute("PRAGMA busy_timeout = 60000")
                has_careers = existing.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='careers'"
                ).fetchone()
                target_had_data = bool(has_careers and not target_is_empty(existing))
        except sqlite3.Error as exc:
            raise RuntimeError(f"Could not inspect the existing Tracker database: {exc}") from exc
        if target_had_data and not replace_existing:
            raise RuntimeError(
                "The Tracker target already contains a career. Re-run with --replace-existing "
                "or use the interactive replacement prompt. Existing Tracker data will be backed up first."
            )

    stamp = utc_stamp()
    staging = _unique_sibling(target.with_name(f".{target.stem}_migration_staging_{stamp}{target.suffix}"))
    legacy_snapshot = _unique_sibling(
        target.with_name(f".{target.stem}_migration_source_{stamp}{target.suffix}")
    )
    backup: Path | None = None
    copied: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []
    career_count = 0
    snapshot_count = 0

    try:
        # Read the selected private-Atlas DB through an actual read-only SQLite
        # connection and materialise a local snapshot first. This keeps the source
        # untouched and avoids Windows URI handling differences in ATTACH DATABASE.
        _sqlite_readonly_snapshot(source, legacy_snapshot)

        # Build and validate a complete replacement away from the live target.
        Database(staging)
        conn = sqlite3.connect(staging, timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 60000")
            conn.execute("PRAGMA foreign_keys=OFF")
            # Attach the local snapshot as an ordinary path. URI parameters are not
            # needed here because this temporary database is ours and disposable.
            conn.execute("ATTACH DATABASE ? AS legacy", (str(legacy_snapshot),))
            conn.execute("BEGIN IMMEDIATE")
            copied, skipped = copy_tables(conn)
            conn.execute(
                "INSERT INTO app_meta(key,value) VALUES('private_atlas_migrated_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),),
            )
            conn.commit()
            conn.execute("DETACH DATABASE legacy")
            conn.execute("PRAGMA foreign_keys=ON")
            errors = integrity_errors(conn)
            if errors:
                raise RuntimeError("Migrated database failed integrity checks: " + "; ".join(errors[:10]))
            career_count = int(conn.execute("SELECT COUNT(*) FROM careers").fetchone()[0])
            snapshot_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            if career_count < 1 or snapshot_count < 1:
                raise RuntimeError("The source did not contain an imported career with snapshots.")
        finally:
            conn.close()

        # Preserve the current Tracker database using SQLite's backup API. This
        # does not require deleting, renaming or byte-copying an open SQLite file.
        if target.is_file() and target.stat().st_size:
            backup = _unique_sibling(
                target.with_name(f"{target.stem}_before_private_migration_{stamp}{target.suffix}")
            )
            _sqlite_backup(target, backup)

        try:
            _publish_staging(staging, target)
        except Exception as exc:
            # If publication touched an existing target, restore the pre-migration
            # image through SQLite as well. Never rename/delete the target path.
            if backup and backup.exists():
                try:
                    _publish_staging(backup, target)
                except Exception as restore_exc:
                    raise RuntimeError(
                        f"Could not publish migrated Tracker database ({exc}); "
                        f"automatic restore also failed ({restore_exc}). Backup: {backup}"
                    ) from exc
            raise

        # Re-open once after publication so a truncated/incomplete copy cannot be
        # reported as successful.
        with sqlite3.connect(target, timeout=60) as verify:
            verify.execute("PRAGMA busy_timeout = 60000")
            errors = integrity_errors(verify)
            if errors:
                raise RuntimeError("Published Tracker database failed integrity checks: " + "; ".join(errors[:10]))
            published_careers = int(verify.execute("SELECT COUNT(*) FROM careers").fetchone()[0])
            published_snapshots = int(verify.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
            if published_careers != career_count or published_snapshots != snapshot_count:
                raise RuntimeError(
                    "Published Tracker database does not match the validated staging database."
                )
    finally:
        _cleanup_sqlite_files(staging)
        _cleanup_sqlite_files(legacy_snapshot)

    update_main_identity(target)
    return {
        "source": str(source),
        "target": str(target),
        "backup": str(backup) if backup else None,
        "careers": career_count,
        "snapshots": snapshot_count,
        "tablesCopied": copied,
        "tablesSkipped": skipped,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate a private Project Atlas career into Project Atlas Tracker.")
    parser.add_argument("--source", type=Path, help="Private Atlas SQLite database")
    parser.add_argument("--target", type=Path, default=default_target(), help="Tracker SQLite database")
    parser.add_argument(
        "--replace-existing", action="store_true",
        help="Replace a previously migrated/non-empty Tracker database after creating a backup"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        source = args.source.resolve() if args.source else choose_source(discover_sources(args.target))
        print(f"\nSelected source: {source}")
        print(f"Target: {args.target.resolve()}")
        print("\nClose both Atlas applications before continuing.")
        replace_existing = bool(args.replace_existing)
        if args.target.is_file():
            try:
                with sqlite3.connect(args.target) as existing:
                    has_careers = existing.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='careers'"
                    ).fetchone()
                    nonempty = bool(has_careers and not target_is_empty(existing))
            except sqlite3.Error:
                nonempty = False
            if nonempty and not replace_existing:
                if not sys.stdin.isatty():
                    raise RuntimeError(
                        "The Tracker target already contains a career. Use --replace-existing to replace it safely."
                    )
                print("\nThe Tracker already contains migrated/imported career data.")
                print("A timestamped backup will be created before replacing it.")
                answer = input("Type REPLACE to discard the current Tracker copy and migrate the selected source: ").strip()
                if answer != "REPLACE":
                    print("Migration cancelled.")
                    return 1
                replace_existing = True
        if sys.stdin.isatty():
            answer = input("Type MIGRATE to create the Tracker copy: ").strip()
            if answer != "MIGRATE":
                print("Migration cancelled.")
                return 1
        result = migrate(source, args.target, replace_existing=replace_existing)
    except Exception as exc:
        print(f"\nMigration failed: {exc}", file=sys.stderr)
        return 1
    print("\nMigration completed successfully.")
    print(f"Careers: {result['careers']} · Snapshots: {result['snapshots']}")
    print("The private Atlas database was not modified.")
    if result["backup"]:
        print(f"Previous empty Tracker database backup: {result['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
