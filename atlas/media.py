"""Media subsystem facade.

Scanning, image processing and identity resolution live in separate mixins while
the public ``MediaLibrary`` API remains unchanged.
"""
from __future__ import annotations

import os
import queue
import threading
from typing import Any

from .db import Database
from .media_identity import MediaIdentityMixin
from .media_processing import MediaProcessingMixin
from .media_sources import MediaSourceMixin
from .media_utils import (
    MEDIA_EXTENSIONS, SOURCE_TYPES, competition_crosswalk_name_key, competition_name_key,
    file_sha256, now_iso, season_start_from_date, unique_colors,
)
from .media_watcher import MediaWatcher
from .paths import media_cache_dir, media_originals_dir, media_thumbnails_dir


class MediaLibrary(MediaSourceMixin, MediaProcessingMixin, MediaIdentityMixin):
    """ID-based media index with lazy, parallel image preparation."""

    def __init__(self, database: Database, *, worker_count: int | None = None):
        self.database = database
        media_originals_dir()
        media_cache_dir()
        media_thumbnails_dir()

        cpu = os.cpu_count() or 4
        self.worker_count = worker_count or max(2, min(8, cpu - 1))
        self._queue: queue.PriorityQueue[tuple[int, int, int]] = queue.PriorityQueue()
        self._queued: set[int] = set()
        self._queue_lock = threading.Lock()
        self._sequence = 0
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._workers: list[threading.Thread] = []

        self._scan_lock = threading.Lock()
        self._scan_thread: threading.Thread | None = None
        self._cancel_scan = threading.Event()
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {
            "active": False,
            "phase": "idle",
            "startedAt": None,
            "finishedAt": None,
            "total": 0,
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
        self._start_workers()
        self._repair_processing_states()
        # Repair assets that were indexed before the first/current snapshot made
        # their EA identities known. This is metadata-only and safe on startup.
        self.reconcile_assignments(limit=100000)
        self.queue_pending_assets(limit=50000)


__all__ = [
    "MEDIA_EXTENSIONS", "SOURCE_TYPES", "MediaLibrary", "MediaWatcher",
    "competition_crosswalk_name_key", "competition_name_key", "file_sha256",
    "now_iso", "season_start_from_date", "unique_colors",
]
