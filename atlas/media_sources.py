from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .media_utils import (
    MEDIA_EXTENSIONS, SOURCE_TYPES, competition_crosswalk_name_key, competition_name_key,
    file_sha256, now_iso, season_start_from_date, unique_colors,
)
from .paths import media_cache_dir, media_originals_dir, media_thumbnails_dir

class MediaSourceMixin:
    def add_source(self, source_type: str, path: str, *, recursive: bool = True) -> dict[str, Any]:
        if source_type not in SOURCE_TYPES:
            raise ValueError("Unknowner Medienquellentyp.")
        source_path = Path(path).expanduser().resolve()
        if not source_path.is_dir():
            raise ValueError("The selected media folder was not found.")
        with self.database.transaction() as conn:
            conn.execute(
                """INSERT INTO media_sources(source_type,path,recursive,enabled)
                   VALUES(?,?,?,1)
                   ON CONFLICT(source_type,path) DO UPDATE SET recursive=excluded.recursive,enabled=1""",
                (source_type, str(source_path), int(recursive)),
            )
            row = conn.execute(
                "SELECT * FROM media_sources WHERE source_type=? AND path=?", (source_type, str(source_path))
            ).fetchone()
        return dict(row)

    def remove_source(self, source_id: int) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE media_sources SET enabled=0 WHERE id=?", (source_id,))

    def sources(self) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM media_sources ORDER BY enabled DESC,source_type,path").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["label"] = SOURCE_TYPES.get(item["source_type"], item["source_type"])
            result.append(item)
        return result

    def progress(self) -> dict[str, Any]:
        with self._progress_lock:
            scan = dict(self._progress)
        with self.database.connect() as conn:
            processing = {
                row["processing_state"]: row["count"]
                for row in conn.execute(
                    "SELECT processing_state,COUNT(*) count FROM media_assets GROUP BY processing_state"
                ).fetchall()
            }
        with self._queue_lock:
            queued = len(self._queued)
        return {
            **scan,
            "paused": self._pause.is_set(),
            "workers": self.worker_count,
            "queue": queued,
            "processing": processing,
        }

    def status(self) -> dict[str, Any]:
        with self.database.connect() as conn:
            counts = {
                row["status"]: row["count"]
                for row in conn.execute("SELECT status,COUNT(*) count FROM media_assets GROUP BY status").fetchall()
            }
            types = {
                row["media_type"]: row["count"]
                for row in conn.execute(
                    "SELECT media_type,COUNT(*) count FROM media_assets WHERE is_active=1 AND status='assigned' GROUP BY media_type"
                ).fetchall()
            }
            processing = {
                row["processing_state"]: row["count"]
                for row in conn.execute(
                    "SELECT processing_state,COUNT(*) count FROM media_assets GROUP BY processing_state"
                ).fetchall()
            }
            latest = conn.execute("SELECT MAX(updated_at) FROM media_assets").fetchone()[0]
        return {
            "sources": self.sources(),
            "counts": counts,
            "types": types,
            "processing": processing,
            "lastScanAt": latest,
            "progress": self.progress(),
        }

    def assets(self, *, status: str | None = None, media_type: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        args: list[Any] = []
        if status:
            clauses.append("a.status=?")
            args.append(status)
        if media_type:
            clauses.append("a.media_type=?")
            args.append(media_type)
        args.append(max(1, min(limit, 2000)))
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""SELECT a.*,s.source_type,s.path source_root
                    FROM media_assets a LEFT JOIN media_sources s ON s.id=a.source_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY a.updated_at DESC,a.id DESC LIMIT ?""",
                tuple(args),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            # Assigned assets expose lazy URLs even before a cache exists. The first HTTP
            # request prepares the image and then serves it.
            if item.get("status") == "assigned":
                version = self._asset_version(item)
                item["url"] = self.asset_url(item["id"], "cache", version)
                item["thumbUrl"] = self.asset_url(item["id"], "thumb", version)
            else:
                item["url"] = None
                item["thumbUrl"] = None
            result.append(item)
        return result

    def start_scan(self) -> dict[str, Any]:
        with self._scan_lock:
            if self._scan_thread and self._scan_thread.is_alive():
                return {"started": False, "alreadyRunning": True, "progress": self.progress()}
            self._cancel_scan.clear()
            # Mark the scan active before starting the thread. Without this synchronous
            # transition a fast caller can observe ``active=false``, stop waiting and
            # then see the worker switch to active a moment later.
            with self._progress_lock:
                self._progress.update({
                    "active": True,
                    "phase": "starting",
                    "startedAt": now_iso(),
                    "finishedAt": None,
                    "cancelRequested": False,
                })
            self._scan_thread = threading.Thread(target=self._scan_all_background, name="atlas-media-indexer", daemon=True)
            self._scan_thread.start()
        return {"started": True, "alreadyRunning": False, "progress": self.progress()}

    def scan_all(self) -> dict[str, Any]:
        """Synchronous compatibility entry point used by tests and CLI."""
        return self._scan_all_impl()

    def _scan_all_background(self) -> None:
        try:
            self._scan_all_impl()
        except Exception as exc:
            with self._progress_lock:
                self._progress.update({
                    "active": False,
                    "phase": "failed",
                    "finishedAt": now_iso(),
                    "errors": int(self._progress.get("errors") or 0) + 1,
                    "currentFile": f"{type(exc).__name__}: {exc}",
                })

    def _scan_all_impl(self) -> dict[str, Any]:
        started_monotonic = time.perf_counter()
        sources = [source for source in self.sources() if source.get("enabled")]
        file_lists: list[tuple[dict[str, Any], list[Path]]] = []
        total = 0
        for source in sources:
            root = Path(source["path"])
            if not root.is_dir():
                continue
            iterator = root.rglob("*") if source["recursive"] else root.glob("*")
            files = [path for path in iterator if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS]
            file_lists.append((source, files))
            total += len(files)

        with self._progress_lock:
            self._progress = {
                "active": True,
                "phase": "indexing",
                "startedAt": now_iso(),
                "finishedAt": None,
                "total": total,
                "visited": 0,
                "indexed": 0,
                "unchanged": 0,
                "assigned": 0,
                "warnings": 0,
                "errors": 0,
                "currentFile": None,
                "filesPerSecond": 0.0,
                "cancelRequested": False,
            }

        results: list[dict[str, Any]] = []
        aggregate = {"indexed": 0, "unchanged": 0, "assigned": 0, "warnings": 0, "errors": 0}
        for source, files in file_lists:
            if self._cancel_scan.is_set():
                break
            result = self._index_source(source, files, started_monotonic)
            results.append(result)
            for key in aggregate:
                aggregate[key] += int(result.get(key) or 0)

        reconcile = self.reconcile_assignments(limit=100000)
        aggregate["assigned"] += int(reconcile.get("assigned") or 0)
        self.queue_pending_assets(limit=50000)
        elapsed = max(0.001, time.perf_counter() - started_monotonic)
        with self._progress_lock:
            self._progress.update({
                "active": False,
                "phase": "cancelled" if self._cancel_scan.is_set() else "complete",
                "finishedAt": now_iso(),
                "filesPerSecond": round(int(self._progress.get("visited") or 0) / elapsed, 1),
                "currentFile": None,
            })
        # Compatibility aliases retain the old API contract.
        return {
            "sources": results,
            "imported": aggregate["assigned"],
            "indexed": aggregate["indexed"],
            "assigned": aggregate["assigned"],
            "unchanged": aggregate["unchanged"],
            "warnings": aggregate["warnings"],
            "errors": aggregate["errors"],
            "cancelled": self._cancel_scan.is_set(),
        }

    def scan_source(self, source_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            source_row = conn.execute("SELECT * FROM media_sources WHERE id=?", (source_id,)).fetchone()
        if not source_row:
            raise ValueError("Media source not found.")
        source = dict(source_row)
        root = Path(source["path"])
        if not root.is_dir():
            raise ValueError(f"Media folder not found: {root}")
        iterator = root.rglob("*") if source["recursive"] else root.glob("*")
        files = [path for path in iterator if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS]
        started = time.perf_counter()
        with self._progress_lock:
            self._progress.update({"active": True, "phase": "indexing", "total": len(files), "visited": 0, "startedAt": now_iso()})
        result = self._index_source(source, files, started)
        reconcile = self.reconcile_assignments(limit=100000)
        result["reconciledAssigned"] = int(reconcile.get("assigned") or 0)
        self.queue_pending_assets(limit=50000)
        with self._progress_lock:
            self._progress.update({"active": False, "phase": "complete", "finishedAt": now_iso(), "currentFile": None})
        return {**result, "imported": result["assigned"]}

    def _index_source(self, source: dict[str, Any], files: list[Path], scan_started: float) -> dict[str, Any]:
        source_id = int(source["id"])
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT source_path,source_mtime_ns,source_size FROM media_assets
                   WHERE source_id=? ORDER BY id DESC""",
                (source_id,),
            ).fetchall()
        latest: dict[str, tuple[int | None, int | None]] = {}
        for row in rows:
            latest.setdefault(row["source_path"], (row["source_mtime_ns"], row["source_size"]))

        player_ids, club_ids, competition_ids, stadium_ids, sponsor_ids, supplier_ids = self._entity_id_sets()
        candidates: list[dict[str, Any]] = []
        unchanged = errors = 0
        visited = 0
        for path in files:
            if self._cancel_scan.is_set():
                break
            visited += 1
            try:
                stat = path.stat()
                previous = latest.get(str(path))
                if previous == (stat.st_mtime_ns, stat.st_size):
                    unchanged += 1
                else:
                    info = self._recognize(source["source_type"], path.name)
                    status, warning, entity_type, media_type = self._classify(
                        info, player_ids, club_ids, competition_ids, stadium_ids, sponsor_ids, supplier_ids
                    )
                    processing_state = "pending" if status == "assigned" else "not_required"
                    candidates.append({
                        "source": source,
                        "path": path,
                        "stat": stat,
                        "info": {**info, "entity_type": entity_type, "media_type": media_type},
                        "status": status,
                        "warning": warning,
                        "processing_state": processing_state,
                    })
            except Exception as exc:
                errors += 1
                self._record_error(source_id, path, str(exc))
            if visited % 200 == 0 or visited == len(files):
                elapsed = max(0.001, time.perf_counter() - scan_started)
                with self._progress_lock:
                    self._progress["visited"] = int(self._progress.get("visited") or 0) + (200 if visited % 200 == 0 else visited % 200)
                    self._progress["currentFile"] = path.name
                    self._progress["filesPerSecond"] = round(int(self._progress["visited"]) / elapsed, 1)

        inserted_ids = self._batch_insert(candidates)
        assigned = sum(1 for item in candidates if item["status"] == "assigned")
        warnings = sum(1 for item in candidates if item["status"] != "assigned")
        with self.database.transaction() as conn:
            conn.execute(
                """UPDATE media_sources SET last_scan_at=?,last_file_count=?,last_imported_count=?,
                           last_warning_count=? WHERE id=?""",
                (now_iso(), len(files), len(candidates), warnings + errors, source_id),
            )
        with self._progress_lock:
            self._progress["indexed"] = int(self._progress.get("indexed") or 0) + len(candidates)
            self._progress["unchanged"] = int(self._progress.get("unchanged") or 0) + unchanged
            self._progress["assigned"] = int(self._progress.get("assigned") or 0) + assigned
            self._progress["warnings"] = int(self._progress.get("warnings") or 0) + warnings
            self._progress["errors"] = int(self._progress.get("errors") or 0) + errors
        return {
            "sourceId": source_id,
            "sourceType": source["source_type"],
            "path": str(source["path"]),
            "files": len(files),
            "indexed": len(candidates),
            "assigned": assigned,
            "unchanged": unchanged,
            "warnings": warnings,
            "errors": errors,
        }

    def reconcile_assignments(self, *, limit: int = 100000) -> dict[str, int]:
        """Re-evaluate unresolved media against the current snapshot/reference IDs.

        Media files are intentionally skipped by the fast index when their mtime and
        size have not changed. That used to leave assets permanently ``unknown`` if
        they were indexed before the relevant career snapshot existed. Reconciliation
        only revisits database metadata; it does not hash, decode or copy source files.
        """
        player_ids, club_ids, competition_ids, stadium_ids, sponsor_ids, supplier_ids = self._entity_id_sets()
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT a.*,s.source_type FROM media_assets a
                   LEFT JOIN media_sources s ON s.id=a.source_id
                   WHERE a.is_active=1 AND a.status IN ('unknown','conflict')
                   ORDER BY a.id LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()

        changed = assigned = still_unresolved = 0
        enqueue_ids: list[int] = []
        stamp = now_iso()
        with self.database.transaction() as conn:
            for row in rows:
                source_type = str(row["source_type"] or "auto")
                info = self._recognize(source_type, str(row["original_name"] or Path(str(row["source_path"])).name))
                status, warning, entity_type, media_type = self._classify(
                    info, player_ids, club_ids, competition_ids, stadium_ids, sponsor_ids, supplier_ids
                )
                processing_state = (
                    "ready" if status == "assigned" and row["cache_path"]
                    else "pending" if status == "assigned"
                    else "not_required"
                )
                new_values = (
                    media_type, entity_type, info.get("ea_id"), info.get("season_start"),
                    info.get("variant"), info.get("kit_type"), status, warning,
                    info.get("ignored_reason"), processing_state,
                )
                old_values = (
                    row["media_type"], row["entity_type"], row["ea_id"], row["season_start"],
                    row["variant"], row["kit_type"], row["status"], row["warning"],
                    row["ignored_reason"], row["processing_state"],
                )
                if new_values != old_values:
                    conn.execute(
                        """UPDATE media_assets SET media_type=?,entity_type=?,ea_id=?,season_start=?,variant=?,kit_type=?,
                                  status=?,warning=?,ignored_reason=?,processing_state=?,processing_error=NULL,updated_at=?
                           WHERE id=?""",
                        (*new_values, stamp, int(row["id"])),
                    )
                    changed += 1
                if status == "assigned":
                    assigned += 1
                    if processing_state == "pending":
                        enqueue_ids.append(int(row["id"]))
                elif status in {"unknown", "conflict"}:
                    still_unresolved += 1

        for asset_id in enqueue_ids:
            self.enqueue(asset_id, priority=0)
        return {
            "checked": len(rows),
            "changed": changed,
            "assigned": assigned,
            "stillUnresolved": still_unresolved,
        }

    def _entity_id_sets(self) -> tuple[set[int], set[int], set[int], set[int], set[int], set[int]]:
        with self.database.connect() as conn:
            player_ids = {int(row[0]) for row in conn.execute("SELECT DISTINCT ea_player_id FROM player_states")}
            club_ids = {int(row[0]) for row in conn.execute("SELECT ea_team_id FROM reference_teams")}
            club_ids.update(int(row[0]) for row in conn.execute("SELECT DISTINCT ea_team_id FROM team_states"))
            competition_ids = {int(row[0]) for row in conn.execute("SELECT ea_competition_id FROM reference_competitions")}
            competition_ids.update(int(row[0]) for row in conn.execute("SELECT DISTINCT competition_object_id FROM competition_states"))
            stadium_ids = {int(row[0]) for row in conn.execute("SELECT ea_stadium_id FROM reference_stadiums")}
        commercial_root = Path(__file__).resolve().parents[1] / "reference" / "commercial"
        with (commercial_root / "sponsors" / "sponsors.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            sponsor_ids = {int(row["sponsor_id"]) for row in csv.DictReader(handle)}
        with (commercial_root / "suppliers" / "equipment_suppliers.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            supplier_ids = {int(row["supplier_id"]) for row in csv.DictReader(handle)}
        return player_ids, club_ids, competition_ids, stadium_ids, sponsor_ids, supplier_ids

    def _classify(
        self,
        info: dict[str, Any],
        player_ids: set[int],
        club_ids: set[int],
        competition_ids: set[int],
        stadium_ids: set[int],
        sponsor_ids: set[int],
        supplier_ids: set[int],
    ) -> tuple[str, str | None, str | None, str]:
        if info.get("ignored_reason"):
            return "ignored", None, info.get("entity_type"), info.get("media_type") or "unknown"
        entity_type = info.get("entity_type")
        ea_id = info.get("ea_id")
        media_type = info.get("media_type") or "unknown"
        if entity_type == "ambiguous_logo":
            club = int(ea_id) in club_ids
            competition = int(ea_id) in competition_ids
            if club and not competition:
                return "assigned", None, "club", "club_logo"
            if competition and not club:
                return "assigned", None, "competition", "competition_logo"
            if club and competition:
                return "conflict", "ID matches both a club and a competition.", None, media_type
            return "unknown", "ID was not found.", None, media_type
        exists = {
            "player": int(ea_id) in player_ids if ea_id is not None else False,
            "club": int(ea_id) in club_ids if ea_id is not None else False,
            "competition": int(ea_id) in competition_ids if ea_id is not None else False,
            "stadium": int(ea_id) in stadium_ids if ea_id is not None else False,
            "sponsor": int(ea_id) in sponsor_ids if ea_id is not None else False,
            "supplier": int(ea_id) in supplier_ids if ea_id is not None else False,
        }.get(entity_type, False)
        if entity_type and ea_id is not None and not exists:
            return "unknown", "The detected EA ID exists in neither snapshot nor reference data.", entity_type, media_type
        return "assigned", None, entity_type, media_type

    def _batch_insert(self, candidates: list[dict[str, Any]]) -> list[int]:
        if not candidates:
            return []
        stamp = now_iso()
        inserted: list[int] = []
        with self.database.transaction() as conn:
            for item in candidates:
                path: Path = item["path"]
                stat = item["stat"]
                info = item["info"]
                fast_fingerprint = f"stat:{stat.st_mtime_ns}:{stat.st_size}"
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO media_assets(
                           source_id,media_type,entity_type,ea_id,season_start,variant,kit_type,
                           source_path,original_name,source_hash,source_mtime_ns,source_size,original_ext,
                           status,warning,ignored_reason,is_active,processing_state,imported_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
                    (
                        item["source"]["id"], info.get("media_type") or "unknown", info.get("entity_type"), info.get("ea_id"),
                        info.get("season_start"), info.get("variant"), info.get("kit_type"), str(path), path.name,
                        fast_fingerprint, stat.st_mtime_ns, stat.st_size, path.suffix.lower(), item["status"], item["warning"],
                        info.get("ignored_reason"), item["processing_state"], stamp, stamp,
                    ),
                )
                if cursor.rowcount == 0:
                    row = conn.execute(
                        "SELECT id FROM media_assets WHERE source_path=? AND source_hash=?",
                        (str(path), fast_fingerprint),
                    ).fetchone()
                    asset_id = int(row["id"])
                else:
                    asset_id = int(cursor.lastrowid)
                inserted.append(asset_id)
                if item["status"] == "assigned":
                    conn.execute(
                        """UPDATE media_assets SET is_active=0 WHERE id<>? AND entity_type=? AND ea_id=?
                           AND media_type=? AND COALESCE(season_start,0)=COALESCE(?,0)
                           AND COALESCE(variant,'')=COALESCE(?, '') AND is_active=1""",
                        (asset_id, info.get("entity_type"), info.get("ea_id"), info.get("media_type"), info.get("season_start"), info.get("variant")),
                    )
        return inserted

    def _recognize(self, source_type: str, name: str) -> dict[str, Any]:
        stem = Path(name).stem
        if source_type == "sponsor_logos":
            match = re.fullmatch(r"(?:sponsor[_-]?)?(\d+)", stem, re.I)
            if match:
                return {"media_type": "sponsor_logo", "entity_type": "sponsor", "ea_id": int(match.group(1))}
        if source_type == "supplier_logos":
            match = re.fullmatch(r"(?:supplier[_-]?)?(\d+)", stem, re.I)
            if match:
                return {"media_type": "supplier_logo", "entity_type": "supplier", "ea_id": int(match.group(1))}
        if source_type in {"players", "auto"}:
            match = re.fullmatch(r"p(\d+)", stem, re.I)
            if match:
                return {"media_type": "player_portrait", "entity_type": "player", "ea_id": int(match.group(1))}
        if source_type in {"trophies", "auto"}:
            match = re.fullmatch(r"t(\d+)(s?)", stem, re.I)
            if match:
                if match.group(2):
                    return {"media_type": "trophy", "entity_type": "competition", "ea_id": int(match.group(1)), "ignored_reason": "dunkle s-Variante"}
                return {"media_type": "trophy", "entity_type": "competition", "ea_id": int(match.group(1))}
        if source_type in {"stadiums", "auto"}:
            match = re.fullmatch(r"stadium_(\d+)_(\d+)", stem, re.I)
            if match:
                return {"media_type": "stadium", "entity_type": "stadium", "ea_id": int(match.group(1)), "variant": match.group(2)}
        if source_type in {"kits", "auto"}:
            match = re.fullmatch(r"j(\d+)_(\d+)_(\d+)", stem, re.I)
            if match:
                return {
                    "media_type": "kit", "entity_type": "club", "ea_id": int(match.group(2)),
                    "kit_type": int(match.group(1)), "season_start": int(match.group(3)),
                    "variant": f"j{match.group(1)}",
                }
        if source_type in {"club_logos", "competition_logos", "auto"}:
            match = re.fullmatch(r"l(\d+)", stem, re.I)
            if match:
                if source_type == "club_logos":
                    return {"media_type": "club_logo", "entity_type": "club", "ea_id": int(match.group(1))}
                if source_type == "competition_logos":
                    return {"media_type": "competition_logo", "entity_type": "competition", "ea_id": int(match.group(1))}
                return {"media_type": "logo", "entity_type": "ambiguous_logo", "ea_id": int(match.group(1))}
        return {"media_type": "unrecognized", "entity_type": None, "ea_id": None, "ignored_reason": "Filename does not match a supported EA FC pattern"}

    def _record_error(self, source_id: int, path: Path, message: str) -> None:
        fingerprint = "error-" + hashlib.sha256(str(path).encode("utf-8", "ignore")).hexdigest()
        with self.database.connect() as conn:
            existing = conn.execute("SELECT id FROM media_assets WHERE source_path=? AND source_hash=?", (str(path), fingerprint)).fetchone()
        if existing:
            return
        stamp = now_iso()
        with self.database.transaction() as conn:
            conn.execute(
                """INSERT INTO media_assets(source_id,media_type,source_path,original_name,source_hash,original_ext,
                           status,warning,processing_state,imported_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (source_id, "error", str(path), path.name, fingerprint, path.suffix.lower(), "error", message, "not_required", stamp, stamp),
            )
