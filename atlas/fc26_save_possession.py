"""Read season-independent possession from the last match saved by FC 26."""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from struct import unpack_from
from typing import Any, Mapping

from .db import Database


LOGGER = logging.getLogger(__name__)
SOURCE = "fc26_save_mxif"
MAX_SAVE_BYTES = 64 * 1024 * 1024
SAVE_SETTLE_NS = 1_000_000_000

# Sheffield Hub's mxif and mham specs. The team records precede the player
# array, whose size varies with the number of slots (36 or 40 observed).
PLAYER_OFFSET = 0x198
PLAYER_RECORD_SIZE = 0x92
TRAILER_SIZE = 0x2A5
SUPPORTED_PLAYER_SLOT_COUNTS = {36, 40}


@dataclass(frozen=True)
class SavedMatchPossession:
    match_date: str
    home_id: int
    away_id: int
    home_score: int
    away_score: int
    home_pct: int
    away_pct: int
    home_players: frozenset[int]
    away_players: frozenset[int]
    mxif_sha256: str


def decode_save_possession(data: bytes) -> SavedMatchPossession | None:
    if not data.startswith(b"FBCHUNKS"):
        return None
    start = data.find(b"mxif")
    end = data.find(b"mrni", start + 4)
    if start < 0 or end < 0 or not data.startswith(b"mxif\x01\x01", start):
        return None
    mxif = data[start:end]
    if len(mxif) < PLAYER_OFFSET + TRAILER_SIZE:
        return None
    slots = unpack_from("<I", mxif, 0x192)[0]
    trailer = PLAYER_OFFSET + slots * PLAYER_RECORD_SIZE
    if slots not in SUPPORTED_PLAYER_SLOT_COUNTS or len(mxif) != trailer + TRAILER_SIZE:
        return None

    home_pct = unpack_from("<I", mxif, 0x1D)[0]
    away_pct = unpack_from("<I", mxif, 0xDD)[0]
    match_day = unpack_from("<I", mxif, trailer + 409)[0]
    home_id, away_id = unpack_from("<II", mxif, trailer + 645)
    date_check = unpack_from("<I", mxif, trailer + 668)[0]
    if match_day != date_check or home_pct + away_pct != 100 or home_id == away_id:
        return None
    try:
        match_date = date(match_day // 10000, match_day // 100 % 100, match_day % 100).isoformat()
    except ValueError:
        return None

    # The latest mham record independently identifies the fixture's teams and
    # score, including games whose mxif player goals omit a rival own goal.
    history = data.find(b"mham", end + 4)
    if history < 0 or not data.startswith(b"mssm", history + 116):
        return None
    if unpack_from("<I", data, history + 20)[0] != 3 or data[history + 24] != 1:
        return None
    h_home, h_away, home_score, away_score = unpack_from("<IIII", data, history + 25)
    if (h_home, h_away) != (home_id, away_id) or not (0 < home_id < 0xFFFFFFFF and 0 < away_id < 0xFFFFFFFF):
        return None

    def players(first: int) -> frozenset[int]:
        ids = (unpack_from("<I", mxif, PLAYER_OFFSET + i * PLAYER_RECORD_SIZE)[0]
               for i in range(first, first + slots // 2))
        return frozenset(player for player in ids if 0 < player < 0xFFFFFFFF)

    return SavedMatchPossession(match_date, home_id, away_id, home_score, away_score,
                                home_pct, away_pct, players(0), players(slots // 2),
                                hashlib.sha256(mxif).hexdigest())


class SavePossessionImporter:
    def __init__(self, database: Database, root: Path | None = None) -> None:
        self.database = database
        local_app_data = os.environ.get("LOCALAPPDATA")
        self.root = root if root is not None else (
            Path(local_app_data) / "EA SPORTS FC 26" / "settings" if local_app_data else None
        )
        self._files: dict[Path, tuple[tuple[int, int, int], SavedMatchPossession | None]] = {}
        self._last_scan: tuple[tuple[int, int], frozenset[SavedMatchPossession]] | None = None

    def scan_once(self) -> int:
        files = {}
        if self.root and self.root.is_dir():
            for path in self.root.glob("CmMgr*"):
                try:
                    before = path.stat()
                    if (not path.is_file() or not 0 < before.st_size <= MAX_SAVE_BYTES
                            or time.time_ns() - before.st_mtime_ns < SAVE_SETTLE_NS):
                        continue
                    signature = (before.st_size, before.st_mtime_ns, before.st_ino)
                    cached = self._files.get(path)
                    if cached and signature == cached[0]:
                        files[path] = cached
                        continue
                    with path.open("rb") as save:
                        data = save.read(MAX_SAVE_BYTES + 1)
                    after = path.stat()
                    if signature == (len(data), after.st_mtime_ns, after.st_ino) and after.st_size == len(data):
                        files[path] = (signature, decode_save_possession(data))
                except OSError:
                    # EA may replace or lock the file while saving. The next scan retries.
                    continue
        self._files = files
        matches = frozenset(match for _, match in files.values() if match is not None)
        if not matches:
            return 0
        with self.database.connect() as conn:
            snapshot_revision = tuple(conn.execute("SELECT COUNT(*),COALESCE(MAX(id),0) FROM snapshots").fetchone())
        scan = (snapshot_revision, matches)
        if scan == self._last_scan:
            return 0

        saved = 0
        with self.database.transaction() as conn:
            candidates: dict[int, list[tuple[int, SavedMatchPossession]]] = {}
            for match in sorted(matches, key=lambda match: match.mxif_sha256):
                candidate = self._linked_observation(conn, match)
                if candidate:
                    fixture_id, snapshot_id = candidate
                    candidates.setdefault(fixture_id, []).append((snapshot_id, match))
            for fixture_id, sources in candidates.items():
                if len({(item.home_pct, item.away_pct) for _, item in sources}) != 1:
                    LOGGER.info("FC26 saves disagree on possession for Atlas fixture %s", fixture_id)
                    continue
                snapshot_id, match = sources[0]
                saved += conn.execute(
                    """INSERT INTO fc26_save_possession (fixture_id,snapshot_id,mxif_sha256,home_pct,away_pct)
                       VALUES (?,?,?,?,?) ON CONFLICT(fixture_id) DO NOTHING""",
                    (fixture_id, snapshot_id, match.mxif_sha256, match.home_pct, match.away_pct),
                ).rowcount
        self._last_scan = scan
        return saved

    @staticmethod
    def _linked_observation(conn: sqlite3.Connection, match: SavedMatchPossession) -> tuple[int, int] | None:
        rows = conn.execute(
            """SELECT s.id snapshot_id,s.managed_team_ea_id,fo.fixture_id,fo.fixture_key
               FROM snapshots s JOIN fixture_observations fo ON fo.snapshot_id=s.id
               JOIN fixtures f ON f.id=fo.fixture_id AND f.career_id=s.career_id
               WHERE fo.date=? AND f.home_team_ea_id=? AND f.away_team_ea_id=?
                 AND fo.home_score=? AND fo.away_score=? AND fo.is_completed=1
                 AND fo.managed_team_involved=1 AND s.managed_team_ea_id IN (?,?)
               ORDER BY s.import_sequence,s.id""",
            (match.match_date, match.home_id, match.away_id, match.home_score, match.away_score,
             match.home_id, match.away_id),
        ).fetchall()
        if len({row["fixture_id"] for row in rows}) != 1:
            return None
        for row in rows:
            observed = match.home_players if row["managed_team_ea_id"] == match.home_id else match.away_players
            participants = frozenset(result[0] for result in conn.execute(
                """SELECT player_ea_id FROM player_match_performances
                   WHERE snapshot_id=? AND fixture_key=? AND minutes_played>0 AND join_status='joined_by_date'""",
                (row["snapshot_id"], row["fixture_key"]),
            ))
            # mxif includes unused substitutes, while ratings list appearances.
            if len(participants) >= 11 and participants <= observed:
                return row["fixture_id"], row["snapshot_id"]
        return None


def snapshot_save_possession(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                             fixture_id: int | None = None) -> dict[int, dict[str, Any]]:
    try:
        rows = conn.execute(
            """SELECT p.*,f.home_team_ea_id,f.away_team_ea_id
               FROM fc26_save_possession p JOIN snapshots s ON s.id=p.snapshot_id
               JOIN fixtures f ON f.id=p.fixture_id
               WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
                 AND (? IS NULL OR p.fixture_id=?)""",
            (snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"], fixture_id, fixture_id),
        )
    except sqlite3.OperationalError as exc:
        if str(exc) == "no such table: fc26_save_possession":
            return {}
        raise
    return {row["fixture_id"]: {"kind": SOURCE, "sourceSnapshotId": row["snapshot_id"],
                               "mxifSha256": row["mxif_sha256"], "homePct": row["home_pct"],
                               "awayPct": row["away_pct"], "homeTeamEaId": row["home_team_ea_id"],
                               "awayTeamEaId": row["away_team_ea_id"]} for row in rows}
