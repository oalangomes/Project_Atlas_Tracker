from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database
from .paths import read_snapshot_root


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CareerResetService:
    """Transactional hard reset of one career to an imported full snapshot.

    Snapshot facts are normally immutable.  Reset therefore works on a temporary
    database copy, validates it, and only then copies the finished database back
    over the live file using SQLite's backup API.  The original live database is
    backed up before any work starts.
    """

    def __init__(self, database: Database):
        self.database = database

    def reset_to_snapshot(self, career_id: int, snapshot_id: int, *, delete_raw_files: bool = False) -> dict[str, Any]:
        # A reset replaces the live database near the end of a long operation.
        # Freeze all Atlas-internal writers for the full reset so media workers,
        # MatchStats and the snapshot watcher cannot write into the old live DB
        # and then race the restore. Reads remain available through WAL.
        with self.database.write_guard():
            return self._reset_to_snapshot_locked(
                career_id, snapshot_id, delete_raw_files=delete_raw_files
            )

    def _reset_to_snapshot_locked(self, career_id: int, snapshot_id: int, *, delete_raw_files: bool = False) -> dict[str, Any]:
        with self.database.connect() as conn:
            target = conn.execute(
                "SELECT * FROM snapshots WHERE id=? AND career_id=?",
                (snapshot_id, career_id),
            ).fetchone()
            career = conn.execute("SELECT * FROM careers WHERE id=?", (career_id,)).fetchone()
            if not target or not career:
                raise ValueError("The selected snapshot does not belong to this career.")
            later = conn.execute(
                "SELECT * FROM snapshots WHERE career_id=? AND import_sequence>? ORDER BY import_sequence",
                (career_id, int(target["import_sequence"])),
            ).fetchall()
            later_snapshot_ids = [int(row["id"]) for row in later]
            target_imported_at = str(target["imported_at"] or "")
            target_date = str(target["career_date"] or "")[:10]
            removed_match_exports = conn.execute(
                """SELECT * FROM match_stat_exports
                   WHERE career_id=? AND (
                       (snapshot_id IS NOT NULL AND snapshot_id IN (
                           SELECT id FROM snapshots WHERE career_id=? AND import_sequence>?
                       )) OR imported_at>?
                   ) ORDER BY id""",
                (career_id, career_id, int(target["import_sequence"]), target_imported_at),
            ).fetchall()
            removed_pulses = conn.execute(
                """SELECT * FROM transfer_pulses
                   WHERE career_id=? AND (career_date_sort>? OR imported_at>?) ORDER BY id""",
                (career_id, int(target["career_date_sort"] or 0), target_imported_at),
            ).fetchall()

        backup = self.database.create_backup(f"reset_before_snapshot_{int(target['import_sequence'])}")

        fd, tmp_name = tempfile.mkstemp(prefix="atlas_reset_", suffix=".sqlite3", dir=str(self.database.path.parent))
        # tempfile.mkstemp() returns an OPEN OS-level file handle.  On Windows,
        # trying to unlink that path before closing the handle raises WinError 32.
        # Keep the empty file in place; sqlite3 can open it and backup() will
        # populate it with the live database contents.
        os.close(fd)
        temp_path = Path(tmp_name)
        try:
            self._copy_database(self.database.path, temp_path)
            result = self._mutate_copy(
                temp_path,
                career_id=career_id,
                snapshot_id=snapshot_id,
                target_imported_at=target_imported_at,
                target_date=target_date,
                target_date_sort=int(target["career_date_sort"] or 0),
                later_snapshot_ids=later_snapshot_ids,
                removed_match_export_ids=[int(row["id"]) for row in removed_match_exports],
                removed_pulse_ids=[int(row["id"]) for row in removed_pulses],
            )
            # Re-run schema initialization to restore immutable triggers and then
            # verify that the reset copy has no broken foreign-key references.
            checked = Database(temp_path)
            with checked.connect() as conn:
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    first = violations[0]
                    raise RuntimeError(f"Reset validation failed: foreign-key violation in {first[0]}.")
                kept = conn.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE career_id=?", (career_id,)
                ).fetchone()[0]
                current = conn.execute(
                    "SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1", (career_id,)
                ).fetchone()
                if not current or int(current[0]) != snapshot_id:
                    raise RuntimeError("Reset validation failed: the selected snapshot is not the latest retained state.")
            self._copy_database(temp_path, self.database.path)
        finally:
            # Temp cleanup must never mask a reset that already completed.
            # Windows Defender/indexers can briefly retain handles even after
            # sqlite3 has closed them, so deletion is deliberately best-effort.
            for cleanup_path in (
                temp_path,
                Path(str(temp_path) + "-wal"),
                Path(str(temp_path) + "-shm"),
            ):
                try:
                    cleanup_path.unlink(missing_ok=True)
                except OSError:
                    pass

        file_result = self._handle_raw_files(
            career_id=career_id,
            later_snapshots=[dict(row) for row in later],
            removed_match_exports=[dict(row) for row in removed_match_exports],
            removed_pulses=[dict(row) for row in removed_pulses],
            delete_raw_files=delete_raw_files,
        )
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO import_events(occurred_at,level,code,message,snapshot_external_id,details_json) VALUES(?,?,?,?,?,?)",
                (
                    utc_now(), "info", "career_reset",
                    f"Career reset to snapshot #{int(target['import_sequence'])}: {target_date}",
                    str(target["external_snapshot_id"]),
                    json.dumps({
                        "careerId": career_id,
                        "snapshotId": snapshot_id,
                        "removedSnapshots": len(later_snapshot_ids),
                        "removedMatchStats": len(removed_match_exports),
                        "removedTransferPulses": len(removed_pulses),
                        "backup": str(backup),
                        **file_result,
                    }, separators=(",", ":")),
                ),
            )
            conn.commit()

        return {
            "ok": True,
            "careerId": career_id,
            "targetSnapshotId": snapshot_id,
            "targetImportSequence": int(target["import_sequence"]),
            "targetDate": target_date,
            "retainedSnapshots": int(result["retainedSnapshots"]),
            "removedSnapshots": len(later_snapshot_ids),
            "removedMatchStats": len(removed_match_exports),
            "removedTransferPulses": len(removed_pulses),
            "backup": str(backup),
            **file_result,
        }

    @staticmethod
    def _copy_database(source_path: Path, destination_path: Path) -> None:
        source = sqlite3.connect(source_path, timeout=30.0)
        destination = sqlite3.connect(destination_path, timeout=30.0)
        try:
            source.execute("PRAGMA busy_timeout=30000")
            destination.execute("PRAGMA busy_timeout=30000")
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    def _mutate_copy(
        self,
        path: Path,
        *,
        career_id: int,
        snapshot_id: int,
        target_imported_at: str,
        target_date: str,
        target_date_sort: int,
        later_snapshot_ids: list[int],
        removed_match_export_ids: list[int],
        removed_pulse_ids: list[int],
    ) -> dict[str, Any]:
        conn = sqlite3.connect(path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Snapshot-state tables are protected from ordinary deletion.  The
            # reset copy is the one controlled exception; Database.initialize()
            # recreates all protection triggers before the copy goes live.
            triggers = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'immutable_%'"
            ).fetchall()
            for row in triggers:
                safe_name = str(row["name"]).replace('"', '""')
                conn.execute(f'DROP TRIGGER IF EXISTS "{safe_name}"')

            if removed_match_export_ids:
                marks = ",".join("?" for _ in removed_match_export_ids)
                conn.execute(
                    f"UPDATE match_stat_exports SET superseded_by_export_id=NULL WHERE superseded_by_export_id IN ({marks})",
                    removed_match_export_ids,
                )
                conn.execute(
                    f"DELETE FROM match_player_detailed_stats WHERE export_id IN ({marks})",
                    removed_match_export_ids,
                )
                conn.execute(
                    f"DELETE FROM match_team_detailed_stats WHERE export_id IN ({marks})",
                    removed_match_export_ids,
                )
                conn.execute(
                    f"DELETE FROM match_stat_exports WHERE id IN ({marks})",
                    removed_match_export_ids,
                )

            if later_snapshot_ids:
                marks = ",".join("?" for _ in later_snapshot_ids)
                # Delete all snapshot-scoped state generically.  This includes
                # newer derived models introduced by future schema versions.
                tables = [row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()]
                for table in tables:
                    if table in {"snapshots", "match_stat_exports"}:
                        continue
                    columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
                    if "snapshot_id" in columns:
                        safe_table = table.replace('"', '""')
                        conn.execute(f'DELETE FROM "{safe_table}" WHERE snapshot_id IN ({marks})', later_snapshot_ids)

                # Entities span snapshots and therefore need their lifetime fixed
                # before the parent snapshots disappear.
                self._repair_entities(conn, career_id, set(later_snapshot_ids))
                conn.execute(f"DELETE FROM snapshots WHERE id IN ({marks})", later_snapshot_ids)

            if removed_pulse_ids:
                marks = ",".join("?" for _ in removed_pulse_ids)
                conn.execute(f"DELETE FROM transfer_world_players WHERE last_pulse_id IN ({marks})", removed_pulse_ids)
                conn.execute(f"DELETE FROM transfer_world_loans WHERE last_pulse_id IN ({marks})", removed_pulse_ids)
                conn.execute(f"DELETE FROM transfer_pulses WHERE id IN ({marks})", removed_pulse_ids)

            # Transfer events are derived career state rather than immutable
            # snapshot facts.  Anything detected after the retained import is
            # discarded so a reset cannot leak later knowledge backwards.
            conn.execute(
                "DELETE FROM transfer_market_events WHERE career_id=? AND (detected_date>? OR created_at>?)",
                (career_id, target_date, target_imported_at),
            )

            # Remove fixture identities that no longer exist in any retained
            # observation or retained MatchStats export.
            orphan_fixture_ids = [int(row[0]) for row in conn.execute(
                """SELECT f.id FROM fixtures f
                   WHERE f.career_id=?
                     AND NOT EXISTS (SELECT 1 FROM fixture_observations o WHERE o.fixture_id=f.id)
                     AND NOT EXISTS (SELECT 1 FROM match_stat_exports m WHERE m.fixture_id=f.id)""",
                (career_id,),
            ).fetchall()]
            if orphan_fixture_ids:
                marks = ",".join("?" for _ in orphan_fixture_ids)
                # Legacy finance data may reference a fixture; it is not part of
                # the tracker UI anymore, but keep the database structurally valid.
                conn.execute(f"UPDATE finance_generated_events SET fixture_id=NULL WHERE fixture_id IN ({marks})", orphan_fixture_ids)
                conn.execute(f"DELETE FROM fixtures WHERE id IN ({marks})", orphan_fixture_ids)

            # Resequence defensively, even though retaining a prefix normally
            # already leaves a contiguous sequence.
            rows = conn.execute(
                """SELECT id,season_index,career_date_sort,managed_completed_fixture_count,
                          global_completed_fixture_count,exported_at_utc,external_snapshot_id
                   FROM snapshots WHERE career_id=?
                   ORDER BY season_index,career_date_sort,managed_completed_fixture_count,
                            global_completed_fixture_count,exported_at_utc,external_snapshot_id""",
                (career_id,),
            ).fetchall()
            same_day: dict[tuple[int, int], int] = {}
            for sequence, row in enumerate(rows, start=1):
                key = (int(row["season_index"]), int(row["career_date_sort"]))
                same_day[key] = same_day.get(key, 0) + 1
                conn.execute(
                    "UPDATE snapshots SET import_sequence=?,same_day_sequence=? WHERE id=?",
                    (sequence, same_day[key], int(row["id"])),
                )
            conn.execute("UPDATE careers SET updated_at=? WHERE id=?", (utc_now(), career_id))
            conn.commit()
            return {"retainedSnapshots": len(rows)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _repair_entities(conn: sqlite3.Connection, career_id: int, removed_snapshot_ids: set[int]) -> None:
        """Rebuild entity lifetimes from retained state rows in bulk.

        Older reset builds queried a state table once *per entity*.  A normal
        full-career database contains tens of thousands of player entities and
        hundreds of thousands of player-state rows, so that N+1 pattern became
        effectively quadratic on real careers.  Stream each state table once in
        chronological order instead and update entity lifetimes in batches.
        """
        state_tables = {
            "player": "player_states",
            "team": "team_states",
            "league": "league_states",
            "competition": "competition_states",
        }
        for entity_type, table in state_tables.items():
            entity_rows = conn.execute(
                "SELECT id FROM entities WHERE career_id=? AND entity_type=? ORDER BY id",
                (career_id, entity_type),
            ).fetchall()
            if not entity_rows:
                continue
            entity_ids = {int(row[0]) for row in entity_rows}

            first_last: dict[int, list[int]] = {}
            # One ordered scan per entity type.  This is O(state rows), rather
            # than rescanning the full table separately for every player.
            cursor = conn.execute(
                f"""SELECT st.entity_id, st.snapshot_id
                       FROM {table} st
                       JOIN snapshots s ON s.id=st.snapshot_id
                       JOIN entities e ON e.id=st.entity_id
                       WHERE e.career_id=? AND e.entity_type=?
                       ORDER BY st.entity_id, s.import_sequence, s.id""",
                (career_id, entity_type),
            )
            for entity_id_raw, snapshot_id_raw in cursor:
                entity_id = int(entity_id_raw)
                snapshot_id = int(snapshot_id_raw)
                pair = first_last.get(entity_id)
                if pair is None:
                    first_last[entity_id] = [snapshot_id, snapshot_id]
                else:
                    pair[1] = snapshot_id

            updates = [
                (pair[0], pair[1], entity_id)
                for entity_id, pair in first_last.items()
            ]
            if updates:
                conn.executemany(
                    "UPDATE entities SET first_seen_snapshot_id=?,last_seen_snapshot_id=? WHERE id=?",
                    updates,
                )

            missing = [(entity_id,) for entity_id in entity_ids.difference(first_last)]
            if missing:
                conn.executemany("DELETE FROM entities WHERE id=?", missing)

    def _handle_raw_files(
        self,
        *,
        career_id: int,
        later_snapshots: list[dict[str, Any]],
        removed_match_exports: list[dict[str, Any]],
        removed_pulses: list[dict[str, Any]],
        delete_raw_files: bool,
    ) -> dict[str, Any]:
        snapshot_root = read_snapshot_root()
        if snapshot_root is None:
            return {"rawFilesMoved": 0, "rawFilesDeleted": 0, "rawFileWarnings": []}
        snapshot_root = Path(snapshot_root)
        shared_root = snapshot_root.parent if snapshot_root.name.casefold() == "snapshots" else snapshot_root
        match_root = shared_root / "MatchStats"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_root = shared_root / "ResetArchive" / stamp
        moved = 0
        deleted = 0
        warnings: list[str] = []

        items: list[tuple[str, dict[str, Any], Path]] = []
        for row in later_snapshots:
            items.append(("Snapshots", row, snapshot_root))
        for row in removed_match_exports:
            items.append(("MatchStats", row, match_root))
        for row in removed_pulses:
            items.append(("TransferPulses", row, shared_root))

        seen: set[Path] = set()
        for kind, row, root in items:
            raw = str(row.get("source_path") or "").strip()
            if not raw:
                continue
            name = Path(raw).name
            candidates = [Path(raw), root / "ready" / name, root / "imported" / name]
            if kind == "Snapshots":
                candidates.append(root / "imported" / str(career_id) / name)
            source = next((candidate for candidate in candidates if candidate.exists()), None)
            if source is None:
                continue
            try:
                source = source.resolve()
            except OSError:
                pass
            if source in seen:
                continue
            seen.add(source)
            try:
                if delete_raw_files:
                    if source.is_dir():
                        shutil.rmtree(source)
                    else:
                        source.unlink(missing_ok=True)
                    deleted += 1
                else:
                    destination_dir = archive_root / kind
                    destination_dir.mkdir(parents=True, exist_ok=True)
                    destination = destination_dir / source.name
                    counter = 1
                    while destination.exists():
                        destination = destination_dir / f"{source.stem}_{counter}{source.suffix}"
                        counter += 1
                    shutil.move(str(source), str(destination))
                    moved += 1
            except OSError as exc:
                warnings.append(f"{source}: {exc}")
        result: dict[str, Any] = {
            "rawFilesMoved": moved,
            "rawFilesDeleted": deleted,
            "rawFileWarnings": warnings,
        }
        if moved:
            result["resetArchive"] = str(archive_root)
        return result
