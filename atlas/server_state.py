from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .db import Database
from .manual_data import ManualDataService
from .financial import FinancialService, PROFILE_FILE
from .finance_core import FinanceCoreService
from .player_finance import PlayerFinanceService
from .player_dynamics import PlayerDynamicsService
from .club_names import ClubNameService
from .commercial import CommercialService
from .settings import SettingsService
from .media import MediaLibrary
from .paths import app_data_dir, read_snapshot_root, current_workspace_id, workspace_record
from .reference import ReferenceImporter
from .watcher import HotFolderWatcher
from .match_stats_importer import MatchStatsImporter
from .workspaces import WorkspaceManager
from .career_reset import CareerResetService

@dataclass
class AppState:
    database: Database
    watcher: HotFolderWatcher
    static_dir: Path
    shutdown_event: threading.Event
    media: MediaLibrary | None = None
    reference: ReferenceImporter | None = None
    manual: ManualDataService | None = None
    financial: FinancialService | None = None
    finance_core: FinanceCoreService | None = None
    player_finance: PlayerFinanceService | None = None
    player_dynamics: PlayerDynamicsService | None = None
    club_names: ClubNameService | None = None
    commercial: CommercialService | None = None
    settings: SettingsService | None = None
    match_stats: MatchStatsImporter | None = None
    workspaces: WorkspaceManager | None = None
    career_reset: CareerResetService | None = None

    def __post_init__(self) -> None:
        if self.reference is None:
            self.reference = ReferenceImporter(self.database)
            self.reference.ensure_builtin()
        if self.media is None:
            self.media = MediaLibrary(self.database)
        if self.manual is None:
            self.manual = ManualDataService(self.database)
        if self.financial is None:
            profile_path = Path(__file__).resolve().parents[1] / "reference" / "financial" / PROFILE_FILE
            self.financial = FinancialService(self.database, profile_path)
        if self.finance_core is None:
            self.finance_core = FinanceCoreService(self.database)
        if self.player_dynamics is None:
            self.player_dynamics = PlayerDynamicsService(self.database)
        if self.club_names is None:
            self.club_names = ClubNameService(self.database)
        if self.player_finance is None:
            self.player_finance = PlayerFinanceService(self.database, self.financial, self.finance_core, self.player_dynamics)
        if self.settings is None:
            self.settings = SettingsService(self.database)
        if self.commercial is None:
            self.commercial = CommercialService(self.database, media=self.media)
        if self.match_stats is None:
            self.match_stats = MatchStatsImporter(self.database)
        if self.workspaces is None:
            self.workspaces = WorkspaceManager(self.database.path)
        if self.career_reset is None:
            self.career_reset = CareerResetService(self.database)
        self.watcher.match_stats_importer = self.match_stats
        if getattr(self.player_dynamics, "world", None) is not None:
            self.player_dynamics.world.settings = self.settings
            self.player_dynamics.world.media = self.media

    def status(self) -> dict[str, Any]:
        root = read_snapshot_root()
        with self.database.connect() as conn:
            career_count = conn.execute("SELECT COUNT(*) FROM careers").fetchone()[0]
            snapshot_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            failed_count = conn.execute(
                "SELECT COUNT(*) FROM import_events WHERE level='error'"
            ).fetchone()[0]
            newest = conn.execute("SELECT MAX(imported_at) FROM snapshots").fetchone()[0]
        ready_count = 0
        if root and (root / "ready").is_dir():
            ready_count = sum(
                1
                for p in (root / "ready").iterdir()
                if p.is_dir() and (p / "READY").is_file()
            )
        workspace = workspace_record()
        return {
            "version": __version__,
            "workspace": {**workspace, "isSandbox": str(workspace.get("kind")) in {"sandbox", "branch"}, "currentWorkspaceId": current_workspace_id()},
            "snapshotRoot": str(root) if root else None,
            "databasePath": str(self.database.path),
            "appDataPath": str(app_data_dir()),
            "careerCount": career_count,
            "snapshotCount": snapshot_count,
            "failedImportCount": failed_count,
            "readyCount": ready_count,
            "watcherActive": True,
            "lastScanAt": self.watcher.last_scan_at,
            "lastImportAt": newest,
            "media": self.media.status(),
            "reference": self.reference.status(),
            "financial": self.financial.status(),
            "playerFinance": {"model": "atlas-player-finance-v4", "mode": "atlas_primary"},
            "playerDynamics": {"model": "atlas-dynamic-performance-v12"},
            "commercial": self.commercial.status(),
            "matchStats": self.match_stats.status(),
            "settings": self.settings.get(),
        }
