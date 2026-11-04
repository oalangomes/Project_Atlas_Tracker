from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .importer import ImportResult, SnapshotImporter
from .paths import read_snapshot_root


class HotFolderWatcher:
    """Polling watcher. Filesystem events are only triggers in the contract; validation remains authoritative."""

    def __init__(self, importer: SnapshotImporter, interval: float = 3.0, on_results: Callable[[list[ImportResult]], None] | None = None, match_stats_importer=None, on_match_stats: Callable[[list[dict[str, int]]], None] | None = None):
        self.importer = importer
        self.interval = max(1.0, interval)
        self.on_results = on_results
        self.match_stats_importer = match_stats_importer
        self.on_match_stats = on_match_stats
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_scan_at: float | None = None
        self.last_results: list[ImportResult] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="snapshot-hot-folder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def trigger(self) -> None:
        self._wake.set()

    def scan_once(self) -> list[ImportResult]:
        root = read_snapshot_root()
        if root is None:
            self.last_results = []
            if self.match_stats_importer is not None:
                try:
                    self.match_stats_importer.scan_once()
                    linked = list(getattr(self.match_stats_importer, "last_linked_matches", []) or [])
                    if linked and self.on_match_stats:
                        self.on_match_stats(linked)
                except Exception:
                    pass
            self.last_scan_at = time.time()
            return []
        for name in ("incoming", "ready", "imported", "failed"):
            (root / name).mkdir(parents=True, exist_ok=True)
        self.last_results = self.importer.import_ready_root(root)
        if self.match_stats_importer is not None:
            try:
                self.match_stats_importer.scan_once()
                linked = list(getattr(self.match_stats_importer, "last_linked_matches", []) or [])
                if linked and self.on_match_stats:
                    self.on_match_stats(linked)
            except Exception:
                pass
        self.last_scan_at = time.time()
        if self.last_results and self.on_results:
            self.on_results(self.last_results)
        return self.last_results

    def _run(self) -> None:
        # Complete scan on startup, then poll. A wake event supports immediate manual scans.
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                # Importer records individual failures. A watcher-level exception must not terminate monitoring.
                pass
            self._wake.wait(self.interval)
            self._wake.clear()
