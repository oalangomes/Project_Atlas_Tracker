from __future__ import annotations

import threading
from typing import Any

class MediaWatcher:
    """Polling watcher that starts a non-blocking index pass.

    start_scan() is idempotent, so automatic polling and the manual UI button can never
    launch overlapping full directory scans.
    """

    def __init__(self, library: Any, interval: float = 60.0):
        self.library = library
        self.interval = max(10.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="atlas-media-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def trigger(self) -> None:
        try:
            self.last_result = self.library.start_scan()
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"

    def _loop(self) -> None:
        self.trigger()
        while not self._stop.wait(self.interval):
            self.trigger()
