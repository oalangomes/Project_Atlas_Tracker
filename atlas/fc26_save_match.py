"""Read the last completed fixture from FC 26 career-save bytes.

The field mapping was adapted from the Sheffield Hub decoders, released under
the Unlicense. The source revision is recorded in the Atlas evidence contract.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from struct import unpack_from


READER_REVISION = "atlas-fc26-match-v1"

# The versioned binary layout defines field offsets and record widths. The
# save itself provides record counts, fixture identity, and values.
_FACTS_HEADER = b"mxif\x01\x01"
_AFTER_FACTS = b"mrni"
_TEAM_START = 0x11
_TEAM_RECORD_SIZE = 0xC0
_PLAYER_COUNT_OFFSET = 0x192
_PLAYER_START = 0x198
_PLAYER_RECORD_SIZE = 0x92
_FACTS_TAIL_SIZE = 0x2A5
_FIXTURE_DATE_OFFSET = 409
_FIXTURE_TEAMS_OFFSET = 645
_FIXTURE_DATE_COPY_OFFSET = 668

_HISTORY_MARKER = b"mham"
_AFTER_HISTORY = b"mssm"
_HISTORY_COUNT_OFFSET = 20
_HISTORY_RECORDS_START = 24
_HISTORY_RECORD_SIZE = 29
_HISTORY_TAIL_SIZE = 5
_EMPTY_ID = 0xFFFFFFFF

_TEAM_FIELDS = {
    "possession_pct": 3,
    "passes_total": 4,
    "passes_completed": 9,
    "through_passes_attempted": 13,
    "through_passes_completed": 14,
    "lobbed_through_passes_attempted": 16,
    "lobbed_through_passes_completed": 17,
    "wing_passes": 19,
    "line_breaking_passes": 22,
    "one_two_attempted": 28,
    "one_two_completed": 29,
    "one_two_reported_success_pct": 30,
    "lobbed_passes_attempted": 31,
    "lobbed_passes_completed": 32,
    "set_piece_passes_attempted": 37,
    "set_piece_passes_completed": 38,
}
_PLAYER_FIELDS = {
    "passes_total": 0x14,
    "passes_completed": 0x3C,
    "through_passes_completed": 0x4C,
    "lobbed_through_passes_completed": 0x50,
    "lobbed_passes_completed": 0x58,
    "ground_passes_completed": 0x5C,
    "set_piece_passes_completed": 0x60,
}
_TEAM_PASSING_COMPARISON_FIELDS = {"crosses_attempted": 10, "crosses_delivered": 11, "key_passes": 25}
_PLAYER_PASSING_COMPARISON_FIELDS = {
    "offside_passes": 0x1C,
    "passes_intercepted": 0x38,
    "crosses_attempted": 0x40,
    "crosses_delivered": 0x44,
    "key_passes": 0x54,
}
_TEAM_SHOOTING_DEFENDING_FIELDS = {
    "shots": 2, "shots_on_target": 40, "blocks": 43, "clearances": 44,
    "aerial_duels_won": 45, "saves": 47,
}
_PLAYER_SHOOTING_DEFENDING_FIELDS = {
    "shots": 0x64, "shots_on_target": 0x68, "shots_off_target_derived": 0x70,
    "blocks": 0x78, "clearances": 0x7C, "aerial_duels_attempted": 0x80, "aerial_duels_won": 0x84,
}


@dataclass(frozen=True)
class SavedMatchSide:
    team_id: int
    goals: int
    fields: dict[str, int]
    players: list[dict[str, int]]


@dataclass(frozen=True)
class SavedMatch:
    day: date
    home: SavedMatchSide
    away: SavedMatchSide
    facts_sha256: str


def _u32(data: bytes, offset: int) -> int:
    return unpack_from("<I", data, offset)[0]


def read_saved_match(data: bytes, *, compare_passing: bool = False,
                     compare_shooting_defending: bool = False) -> SavedMatch | None:
    """Read compatible MXIF and MHAM blocks, or return None for invalid evidence."""
    if not data.startswith(b"FBCHUNKS"):
        return None
    start = data.find(_FACTS_HEADER)
    if start < 0 or len(data) < start + _PLAYER_START:
        return None

    player_count = _u32(data, start + _PLAYER_COUNT_OFFSET)
    if player_count == 0 or player_count % 2:
        return None
    trailer = start + _PLAYER_START + player_count * _PLAYER_RECORD_SIZE
    end = trailer + _FACTS_TAIL_SIZE
    if not data.startswith(_AFTER_FACTS, end):
        return None

    day_value = _u32(data, trailer + _FIXTURE_DATE_OFFSET)
    if day_value < 10000101 or day_value != _u32(data, trailer + _FIXTURE_DATE_COPY_OFFSET):
        return None
    try:
        year, month_day = divmod(day_value, 10000)
        month, day_of_month = divmod(month_day, 100)
        day = date(year, month, day_of_month)
    except ValueError:
        return None

    clubs = unpack_from("<II", data, trailer + _FIXTURE_TEAMS_OFFSET)
    if clubs[0] == clubs[1] or any(club in (0, _EMPTY_ID) for club in clubs):
        return None
    score = _read_history_score(data, end + len(_AFTER_FACTS), clubs)
    if score is None:
        return None

    per_side = player_count // 2
    team_fields = _TEAM_FIELDS | _TEAM_PASSING_COMPARISON_FIELDS if compare_passing else _TEAM_FIELDS
    player_fields = _PLAYER_FIELDS | _PLAYER_PASSING_COMPARISON_FIELDS if compare_passing else _PLAYER_FIELDS
    if compare_shooting_defending:
        team_fields = team_fields | _TEAM_SHOOTING_DEFENDING_FIELDS
        player_fields = player_fields | _PLAYER_SHOOTING_DEFENDING_FIELDS
    home = _read_side(data, start, clubs[0], score[0], 0, per_side, team_fields, player_fields)
    away = _read_side(data, start, clubs[1], score[1], 1, per_side, team_fields, player_fields)
    return SavedMatch(day, home, away, hashlib.sha256(memoryview(data)[start:end]).hexdigest())


def _read_history_score(data: bytes, after_facts: int, clubs: tuple[int, int]) -> tuple[int, int] | None:
    start = data.find(_HISTORY_MARKER, after_facts)
    if start < 0 or len(data) < start + _HISTORY_RECORDS_START:
        return None
    records = start + _HISTORY_RECORDS_START
    count = _u32(data, start + _HISTORY_COUNT_OFFSET)
    end = records + count * _HISTORY_RECORD_SIZE + _HISTORY_TAIL_SIZE
    if count == 0 or not data.startswith(_AFTER_HISTORY, end) or data[records] != 1:
        return None

    # The first history record is the newest match and gives its official score.
    home_id, away_id, home_goals, away_goals = unpack_from("<IIII", data, records + 1)
    if (home_id, away_id) != clubs or _EMPTY_ID in (home_goals, away_goals):
        return None
    return home_goals, away_goals


def _read_side(data: bytes, start: int, team_id: int, goals: int,
               side: int, per_side: int, team_fields: dict[str, int],
               player_fields: dict[str, int]) -> SavedMatchSide:
    team = start + _TEAM_START + side * _TEAM_RECORD_SIZE
    fields = {name: _u32(data, team + slot * 4) for name, slot in team_fields.items()}
    players = []
    player_start = start + _PLAYER_START + side * per_side * _PLAYER_RECORD_SIZE
    player_end = player_start + per_side * _PLAYER_RECORD_SIZE
    for offset in range(player_start, player_end, _PLAYER_RECORD_SIZE):
        player_id = _u32(data, offset)
        if player_id not in (0, _EMPTY_ID):
            fields_by_player = {name: _u32(data, offset + field) for name, field in player_fields.items()}
            fields_by_player["player_id"] = player_id
            players.append(fields_by_player)
    return SavedMatchSide(team_id, goals, fields, players)
