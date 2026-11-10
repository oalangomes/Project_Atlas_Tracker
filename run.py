from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from atlas import __version__
from atlas.db import Database
from atlas.instance_lock import SingleInstanceLock, AtlasAlreadyRunning
from atlas.importer import SnapshotImporter
from atlas.manifest import SnapshotContract, SnapshotValidator
from atlas.paths import app_data_dir, database_path, log_dir, read_snapshot_root, initialize_workspace_context, current_workspace_id
from atlas.server import AppState, AtlasHttpServer
from atlas.media import MediaLibrary, MediaWatcher
from atlas.reference import ReferenceImporter
from atlas.watcher import HotFolderWatcher
from atlas.match_stats_importer import MatchStatsImporter

PROJECT_ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = PROJECT_ROOT / "schemas" / "FC26_CareerTracker_Snapshot_Contract_v1.2.0.json"
STATIC_DIR = PROJECT_ROOT / "atlas" / "static"


def available_port(preferred: int) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available local port was found.")


def build_core() -> tuple[Database, SnapshotImporter]:
    db = Database(database_path())
    contract = SnapshotContract(CONTRACT_PATH)
    validator = SnapshotValidator(contract)
    return db, SnapshotImporter(db, validator)


def find_edge() -> Path | None:
    candidates: list[Path] = []
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        raw = os.environ.get(variable)
        if raw:
            candidates.append(Path(raw) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    found = shutil.which("msedge") or shutil.which("microsoft-edge")
    if found:
        candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def request_shutdown(url: str) -> None:
    try:
        request = urllib.request.Request(
            f"{url}api/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=3).read()
    except Exception:
        pass


def launch_desktop(url: str, log) -> subprocess.Popen | None:
    edge = find_edge()
    if not edge:
        log("Microsoft Edge was not found; opening the default browser.")
        webbrowser.open(url)
        return None
    profile = app_data_dir() / "desktop_profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(edge),
        f"--app={url}",
        "--start-maximized",
        "--no-first-run",
        "--disable-session-crashed-bubble",
        "--disable-background-mode",
        "--disable-extensions",
        f"--user-data-dir={profile}",
    ]
    log(f"Opening desktop window: {edge}")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_runtime_state(url: str, pid: int) -> None:
    path = app_data_dir() / "runtime_state.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"url": url, "pid": pid, "startedAt": datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp, path)


def build_frontend():
    """Try to compile TypeScript frontend to JavaScript."""
    try:
        # Use powershell to bypass execution policy and run tsc in the frontend folder
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", "cd frontend; ./tsc"],
            capture_output=True, text=True, check=True
        )
        return True
    except subprocess.CalledProcessError as exc:
        # We log it but don't stop the server, as tsc might fail if node_modules are missing
        # but the previous build might still be usable.
        return False
    except Exception:
        return False

def main() -> int:
    parser = argparse.ArgumentParser(description="Project Atlas Tracker")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--desktop", action="store_true", help="Open the interface in a dedicated Edge app window")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--scan", action="store_true", help="Scan the hot folder once and exit")
    parser.add_argument("--import-snapshot", type=Path, help="Validate and import one snapshot without moving it")
    parser.add_argument("--workspace", help="Workspace ID for this run only")
    args = parser.parse_args()

    instance_lock = SingleInstanceLock()
    try:
        instance_lock.acquire(workspace_id=args.workspace)
    except AtlasAlreadyRunning as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2
    atexit.register(instance_lock.release)

    workspace_id = initialize_workspace_context(args.workspace)
    session = datetime.now().strftime("%Y%m%d%H%M%S")
    log_path = log_dir() / f"atlas_start_{session}.log"

    def log(message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}"
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
        if sys.stdout:
            print(line, flush=True)

    try:
        log(f"Project Atlas Tracker v{__version__}")
        log(f"Workspace: {workspace_id}")
        log(f"Python: {sys.version.split()[0]} · {sys.executable}")
        
        # Auto-compile frontend before starting the server
        if build_frontend():
            log("Frontend compiled successfully.")
        else:
            log("Frontend compilation skipped or failed (Check if Node.js/npm is installed).")

        db, importer = build_core()
        if args.import_snapshot:
            result = importer.import_folder(args.import_snapshot, move_after=False)
            log(str(result))
            return 0 if result.status in {"imported", "duplicate"} else 1
        watcher = HotFolderWatcher(importer)
        if args.scan:
            watcher.match_stats_importer = MatchStatsImporter(db)
            results = watcher.scan_once()
            for result in results:
                log(str(result))
            return 0 if all(r.status != "failed" for r in results) else 1

        shutdown_event = threading.Event()
        reference_importer = ReferenceImporter(db)
        seeded = reference_importer.ensure_builtin()
        log("Bundled EA FC reference data loaded." if seeded else "EA FC reference data already available.")
        media_library = MediaLibrary(db)
        media_watcher = MediaWatcher(media_library)
        state = AppState(db, watcher, STATIC_DIR, shutdown_event, media_library, reference_importer)

        def reconcile_media_after_snapshot(results) -> None:
            if any(result.status == "imported" for result in results):
                media_library.reconcile_assignments(limit=100000)
            from atlas.commission import queue_auto_reports_for_imported_snapshots
            queue_auto_reports_for_imported_snapshots(db, results)

        def queue_reports_after_matchstats(linked_matches) -> None:
            from atlas.commission import queue_auto_commission_reports
            for item in linked_matches:
                queue_auto_commission_reports(db, item["career_id"], item["fixture_id"], item.get("snapshot_id"))

        watcher.on_results = reconcile_media_after_snapshot
        watcher.on_match_stats = queue_reports_after_matchstats
        port = available_port(args.port)
        server = AtlasHttpServer(("127.0.0.1", port), state)
        watcher.start()
        media_watcher.start()
        url = f"http://127.0.0.1:{port}/"
        write_runtime_state(url, os.getpid())
        log(f"Local server: {url}")
        root = read_snapshot_root()
        log(f"Snapshot root: {root if root else 'not configured yet'}")

        desktop_process: subprocess.Popen | None = None
        if args.desktop:
            def open_desktop() -> None:
                nonlocal desktop_process
                desktop_process = launch_desktop(url, log)
                if desktop_process:
                    # Edge can hand an app URL to an already running browser
                    # instance and exit immediately. That is not a closed UI;
                    # only tie Atlas lifetime to a process that stayed attached.
                    try:
                        rc = desktop_process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        rc = desktop_process.wait()
                        log(f"Desktop window closed (code {rc}).")
                        request_shutdown(url)
                    else:
                        log(f"Desktop URL handed to an existing browser instance (code {rc}); Atlas remains available.")
            threading.Thread(target=open_desktop, daemon=True).start()
        elif not args.no_browser:
            threading.Timer(0.7, lambda: webbrowser.open(url)).start()

        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            log("Stopped by user.")
        finally:
            watcher.stop()
            media_watcher.stop()
            media_library.stop()
            server.server_close()
            log("Project Atlas Tracker stopped.")
        return 0
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(traceback.format_exc())
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
