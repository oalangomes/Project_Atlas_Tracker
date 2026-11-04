from __future__ import annotations

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

class MediaProcessingMixin:
    def _start_workers(self) -> None:
        for index in range(self.worker_count):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"atlas-media-worker-{index + 1}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def stop(self) -> None:
        self._cancel_scan.set()
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout=5.0)
        self._stop.set()
        self._pause.clear()
        for _ in self._workers:
            self._queue.put((9999, 0, -1))
        for thread in self._workers:
            thread.join(timeout=2.0)

    def pause_processing(self) -> None:
        self._pause.set()

    def resume_processing(self) -> None:
        self._pause.clear()

    def cancel_scan(self) -> None:
        self._cancel_scan.set()
        with self._progress_lock:
            self._progress["cancelRequested"] = True

    @staticmethod
    def _priority_for(media_type: str | None) -> int:
        return {
            "club_logo": 5,
            "competition_logo": 6,
            "trophy": 7,
            "kit": 8,
            "stadium": 12,
            "player_portrait": 40,
        }.get(media_type or "", 50)

    def enqueue(self, asset_id: int, *, priority: int = 50) -> None:
        with self._queue_lock:
            if asset_id in self._queued:
                return
            self._queued.add(asset_id)
            self._sequence += 1
            sequence = self._sequence
        self._queue.put((priority, sequence, asset_id))

    def queue_pending_assets(self, *, limit: int = 50000) -> int:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT id,media_type FROM media_assets
                   WHERE status='assigned' AND is_active=1 AND processing_state IN ('pending','failed')
                   ORDER BY CASE media_type
                     WHEN 'club_logo' THEN 1 WHEN 'competition_logo' THEN 2 WHEN 'trophy' THEN 3
                     WHEN 'kit' THEN 4 WHEN 'stadium' THEN 5 ELSE 10 END, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        for row in rows:
            self.enqueue(int(row["id"]), priority=self._priority_for(row["media_type"]))
        return len(rows)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                priority, sequence, asset_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if asset_id < 0:
                self._queue.task_done()
                continue
            while self._pause.is_set() and not self._stop.wait(0.2):
                pass
            try:
                self._process_asset(asset_id)
            except Exception:
                pass
            finally:
                with self._queue_lock:
                    self._queued.discard(asset_id)
                self._queue.task_done()

    def _repair_processing_states(self) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                """UPDATE media_assets SET processing_state='ready',processed_at=COALESCE(processed_at,updated_at)
                   WHERE status='assigned' AND cache_path IS NOT NULL AND (processing_state IS NULL OR processing_state<>'ready')"""
            )
            conn.execute(
                """UPDATE media_assets SET processing_state='pending'
                   WHERE status='assigned' AND cache_path IS NULL AND (processing_state IS NULL OR processing_state IN ('processing','ready'))"""
            )
            conn.execute(
                """UPDATE media_assets SET processing_state='not_required'
                   WHERE status<>'assigned' AND (processing_state IS NULL OR processing_state='pending')"""
            )

    def ensure_processed(self, asset_id: int, *, timeout: float = 60.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            with self.database.connect() as conn:
                row = conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                raise ValueError("Media item was not found.")
            state = row["processing_state"] or "pending"
            if state == "ready" and row["cache_path"]:
                return dict(row)
            if state in {"not_required"}:
                raise ValueError("This media item does not require image processing.")
            if state == "processing":
                if time.monotonic() >= deadline:
                    raise RuntimeError("Media processing is taking longer than expected.")
                time.sleep(0.05)
                continue
            self._process_asset(asset_id, raise_errors=True)

    def _process_asset(self, asset_id: int, *, raise_errors: bool = False) -> None:
        started = time.perf_counter()
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                if raise_errors:
                    raise ValueError("Media item was not found.")
                return
            if row["processing_state"] == "ready" and row["cache_path"]:
                return
            if row["status"] != "assigned":
                conn.execute("UPDATE media_assets SET processing_state='not_required' WHERE id=?", (asset_id,))
                return
            if row["processing_state"] == "processing":
                return
            conn.execute(
                "UPDATE media_assets SET processing_state='processing',processing_started_at=?,processing_error=NULL WHERE id=?",
                (now_iso(), asset_id),
            )
            item = dict(row)
        try:
            try:
                from PIL import Image  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Pillow is missing. Run install_optional_dependencies.bat.") from exc
            source = Path(item["source_path"])
            if not source.is_file():
                raise FileNotFoundError(f"Source file is missing: {source}")
            media_type = item["media_type"]
            digest = file_sha256(source)
            hash_short = digest[:12]
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem)[:80]
            original_dir = media_originals_dir() / media_type
            cache_dir = media_cache_dir() / media_type
            thumb_dir = media_thumbnails_dir() / media_type
            original_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            thumb_dir.mkdir(parents=True, exist_ok=True)
            original_target = original_dir / f"{safe_name}_{hash_short}{source.suffix.lower()}"
            if not original_target.exists():
                shutil.copy2(source, original_target)
            cache_target = cache_dir / f"{safe_name}_{hash_short}.webp"
            thumb_target = cache_target
            with Image.open(source) as image:
                image.load()
                width, height = image.size
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                if media_type == "stadium":
                    image.save(cache_target, "WEBP", lossless=False, quality=86, method=1)
                    thumb_target = thumb_dir / f"{safe_name}_{hash_short}.webp"
                    thumb = image.copy()
                    thumb.thumbnail((300, 118))
                    thumb.save(thumb_target, "WEBP", lossless=False, quality=82, method=0)
                elif media_type == "player_portrait":
                    # A single 180px WebP is small enough for both profiles and list cards.
                    # Fast lossy RGB compression retains alpha and is dramatically faster
                    # than the former method=6 lossless pass plus a second thumbnail pass.
                    image.save(cache_target, "WEBP", lossless=False, quality=91, method=0, exact=True)
                else:
                    image.save(cache_target, "WEBP", lossless=True, method=0, exact=True)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            with self.database.transaction() as conn:
                conn.execute(
                    """UPDATE media_assets SET width=?,height=?,original_copy_path=?,cache_path=?,thumb_path=?,
                               content_hash=?,processing_state='ready',processing_error=NULL,processed_at=?,
                               conversion_ms=?,warning=NULL,updated_at=? WHERE id=?""",
                    (width, height, str(original_target), str(cache_target), str(thumb_target), digest, now_iso(), elapsed_ms, now_iso(), asset_id),
                )
        except Exception as exc:
            with self.database.transaction() as conn:
                conn.execute(
                    """UPDATE media_assets SET processing_state='failed',processing_error=?,warning=?,updated_at=? WHERE id=?""",
                    (f"{type(exc).__name__}: {exc}", str(exc), now_iso(), asset_id),
                )
            if raise_errors:
                raise
