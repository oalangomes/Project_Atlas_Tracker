from __future__ import annotations

import json
import os
from pathlib import Path
from typing import IO, Any

from .paths import app_data_dir


class AtlasAlreadyRunning(RuntimeError):
    pass


class SingleInstanceLock:
    """OS-backed installation lock kept for the lifetime of the Atlas process."""

    def __init__(self) -> None:
        self.path = app_data_dir() / "atlas_instance.lock"
        self.handle: IO[str] | None = None

    def acquire(self, *, workspace_id: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise AtlasAlreadyRunning("Project Atlas is already running. Use the existing window or stop the running process first.") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise AtlasAlreadyRunning("Project Atlas is already running. Use the existing window or stop the running process first.") from exc
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps({"pid": os.getpid(), "workspaceId": workspace_id}, ensure_ascii=False))
            handle.flush()
            self.handle = handle
        except Exception:
            handle.close()
            raise

    def release(self) -> None:
        handle = self.handle
        self.handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            handle.close()

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()
