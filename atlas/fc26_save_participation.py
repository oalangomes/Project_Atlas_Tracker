"""Read and link the current match's persisted player states from FC 26."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from struct import unpack_from
from typing import Any

from .fc26_save_match import SavedMatch
from .positions import POSITION_BY_ID, trusted_actual_position


SOURCE = "fc26_save_mflp"
_HEADER_SIZE = 26
_RECORD_SIZE = 90
_TRAILER_SIZE = 4
_ROLES = {0: "starter_finished", 8: "starter_substituted", 16: "substitute_entered"}


@dataclass(frozen=True)
class PlayerParticipation:
    player_id: int
    status: int
    entry_minute: int
    minutes: int
    position_code: int


@dataclass(frozen=True)
class SavedParticipation:
    team_id: int
    players: tuple[PlayerParticipation, ...]
    block_hash: str


def read_saved_participation(data: bytes, match: SavedMatch) -> SavedParticipation | None:
    # Header and record layout adapted from the Hub's mflp reverse specification.
    start = data.find(b"mflp\x01\x01")
    if start < 0 or len(data) < start + _HEADER_SIZE:
        return None
    team_id = unpack_from("<I", data, start + 11)[0]
    if team_id != unpack_from("<I", data, start + 16)[0]:
        return None
    count = unpack_from("<I", data, start + 21)[0]
    first = start + _HEADER_SIZE
    records_end = first + count * _RECORD_SIZE
    end = records_end + _TRAILER_SIZE
    if not data.startswith(b"mglp", end):
        return None
    if team_id == match.home.team_id:
        side = match.home
    elif team_id == match.away.team_id:
        side = match.away
    else:
        return None
    match_ids = {player["player_id"] for player in side.players}
    players: dict[int, PlayerParticipation] = {}
    for offset in range(first, records_end, _RECORD_SIZE):
        player_id = unpack_from("<I", data, offset)[0]
        status = data[offset + 0x58]
        if player_id in (0, 0xFFFFFFFF) or status == 255:
            continue
        entry, minutes = unpack_from("<BB", data, offset + 0x4F)
        valid_entry = 0 < entry < 255 if status == 16 else entry == 0
        if (status not in _ROLES or data[offset + 0x59] != 1 or not 0 < minutes < 255
                or not valid_entry
                or player_id in players or player_id not in match_ids):
            return None
        position = unpack_from("<I", data, offset + 0x54)[0]
        players[player_id] = PlayerParticipation(player_id, status, entry, minutes, position)
    if sum(player.status != 16 for player in players.values()) != 11:
        return None
    return SavedParticipation(team_id, tuple(players[key] for key in sorted(players)),
                              hashlib.sha256(memoryview(data)[start:end]).hexdigest())


def persist_save_participation(conn: sqlite3.Connection, fixture_id: int, snapshot_id: int,
                               state: SavedParticipation) -> int:
    rows = conn.execute(
        """SELECT p.player_ea_id,p.minutes_played,p.actual_position,p.actual_position_source
           FROM fixture_observations f JOIN snapshots s ON s.id=f.snapshot_id
           JOIN player_match_performances p ON p.snapshot_id=s.id AND p.fixture_key=f.fixture_key
           WHERE f.fixture_id=? AND s.id=? AND s.managed_team_ea_id=?
             AND p.join_status='joined_by_date' AND p.minutes_played>0""",
        (fixture_id, snapshot_id, state.team_id),
    ).fetchall()
    by_id = {row["player_ea_id"]: row for row in rows}
    # A record in the roster is insufficient. Match the entire participant set
    # and their internal minutes against the linked fixture observation.
    if len(rows) != len(by_id) or set(by_id) != {p.player_id for p in state.players}:
        return 0
    for player in state.players:
        observed = by_id[player.player_id]
        if player.minutes != observed["minutes_played"]:
            return 0
        if observed["actual_position_source"] == "career_playerlastmatchhistory_latest_match":
            position = POSITION_BY_ID.get(player.position_code)
            observed_position = trusted_actual_position(observed["actual_position"], observed["actual_position_source"])
            if position and observed_position and position != observed_position:
                return 0

    payload: dict[int, dict[str, Any]] = {}
    outgoing: dict[tuple[int, int], list[int]] = defaultdict(list)
    incoming: dict[tuple[int, int], list[int]] = defaultdict(list)
    for player in state.players:
        payload[player.player_id] = {
            "role": _ROLES[player.status], "position": POSITION_BY_ID.get(player.position_code),
            "minutesPlayedInternal": player.minutes,
            "entryMinuteInternal": player.entry_minute if player.status == 16 else None,
        }
        if player.position_code in POSITION_BY_ID:
            if player.status == 8:
                outgoing[(player.position_code, player.minutes)].append(player.player_id)
            elif player.status == 16:
                incoming[(player.position_code, player.entry_minute)].append(player.player_id)
    for key, players in incoming.items():
        candidates = outgoing.get(key, [])
        if len(players) == len(candidates) == 1:
            payload[players[0]]["replacedPlayerEaId"] = candidates[0]
            payload[players[0]]["pairingMethod"] = "same_recorded_position_and_internal_minute"
    return conn.execute(
        """INSERT INTO fc26_save_participation (fixture_id,team_ea_id,mflp_sha256,players_json)
           VALUES (?,?,?,?) ON CONFLICT(fixture_id) DO NOTHING""",
        (fixture_id, state.team_id, state.block_hash, json.dumps(payload)),
    ).rowcount


def fixture_save_participation(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                               fixture_id: int) -> dict[str, Any] | None:
    try:
        row = conn.execute(
            """SELECT p.snapshot_id,p.mxif_sha256,m.team_ea_id,m.mflp_sha256,m.players_json
               FROM fc26_save_participation m JOIN fc26_save_possession p ON p.fixture_id=m.fixture_id
               JOIN snapshots s ON s.id=p.snapshot_id
               WHERE p.fixture_id=? AND s.career_id=? AND s.season_index=? AND s.import_sequence<=?""",
            (fixture_id, snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"]),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if str(exc) == "no such table: fc26_save_participation":
            return None
        raise
    if row is None:
        return None
    return {"teamEaId": row["team_ea_id"], "players": json.loads(row["players_json"]),
            "source": {"kind": SOURCE, "sourceSnapshotId": row["snapshot_id"],
                       "mxifSha256": row["mxif_sha256"], "mflpSha256": row["mflp_sha256"]}}
