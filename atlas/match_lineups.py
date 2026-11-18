"""Conservative initial/final XI reconstruction from one linked match export."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from .match_stats import _new_completed_fixture
from .positions import broad_position_group, canonical_position
from .server_utils import as_int


def _line_shape(players: set[int], history: dict[int, dict[str, Any]]) -> str | None:
    if len(players) != 11:
        return None
    groups = Counter()
    for player_id in players:
        row = history.get(player_id)
        position = canonical_position(row.get("actual_position"), row.get("actual_position_id")) if row else None
        if not position:
            return None
        groups[broad_position_group(position)] += 1
    if groups["GK"] != 1 or sum(groups.values()) != 11:
        return None
    return f'{groups["DEF"]}-{groups["MID"]}-{groups["ATT"]}'


def _departures(starters: set[int], incoming: set[int],
                history: dict[int, dict[str, Any]], duration: int) -> set[int] | None:
    """Find an unambiguous set of replaced starters; never infer event minutes."""
    if not incoming:
        return set() if all((as_int(history[p].get("minutes_played")) or 0) >= duration - 3 for p in starters) else None
    if len(incoming) > 5:
        return None
    candidates = {p: as_int(history[p].get("minutes_played")) for p in starters}
    entering = {p: as_int(history[p].get("minutes_played")) for p in incoming}
    if any(v is None or v <= 0 for v in entering.values()) or any(v is None for v in candidates.values()):
        return None
    solutions: set[frozenset[int]] = set()
    used: set[int] = set()

    def search(index: int) -> None:
        if len(solutions) > 1:
            return
        if index == len(entering):
            if all(minutes >= duration - 3 or player_id in used for player_id, minutes in candidates.items()):
                solutions.add(frozenset(used))
            return
        entrant_minutes = list(entering.values())[index]
        for player_id, starter_minutes in candidates.items():
            if player_id in used or starter_minutes >= duration:
                continue
            if duration <= starter_minutes + entrant_minutes <= duration + 3:
                used.add(player_id)
                search(index + 1)
                used.remove(player_id)

    search(0)
    return set(next(iter(solutions))) if len(solutions) == 1 else None


def match_lineup_phases(conn: sqlite3.Connection, detailed: dict[str, Any] | None,
                        fixture_id: int) -> dict[str, Any] | None:
    """Return recorded-position line counts only when source and XI are attributable."""
    if not detailed or not detailed.get("exportId") or detailed.get("snapshotId") is None:
        return None
    export = conn.execute(
        "SELECT e.snapshot_id,e.fixture_id,e.team0_ea_id,e.team1_ea_id,s.career_id,s.import_sequence "
        "FROM match_stat_exports e JOIN snapshots s ON s.id=e.snapshot_id WHERE e.id=?",
        (detailed["exportId"],),
    ).fetchone()
    if not export or as_int(export["fixture_id"]) != fixture_id:
        return None
    previous = conn.execute(
        "SELECT id FROM snapshots WHERE career_id=? AND import_sequence IS NOT NULL "
        "AND (import_sequence<? OR (import_sequence=? AND id<?)) "
        "ORDER BY import_sequence DESC,id DESC LIMIT 1",
        (export["career_id"], export["import_sequence"], export["import_sequence"], export["snapshot_id"]),
    ).fetchone()
    if not previous:
        return None
    newly_completed = _new_completed_fixture(conn, int(previous["id"]), int(export["snapshot_id"]))
    if not newly_completed or int(newly_completed["fixture_id"]) != fixture_id:
        return None
    def history_at(snapshot_id: int) -> dict[int, dict[int, dict[str, Any]]]:
        rows = conn.execute(
            "SELECT raw_json FROM generic_snapshot_rows WHERE snapshot_id=? AND file_name='last_match_players.csv'",
            (snapshot_id,),
        ).fetchall()
        by_team: dict[int, dict[int, dict[str, Any]]] = {}
        for raw in rows:
            row = json.loads(raw["raw_json"])
            team_id, player_id = as_int(row.get("team_id")), as_int(row.get("player_id"))
            if team_id is not None and player_id is not None:
                by_team.setdefault(team_id, {})[player_id] = row
        return by_team

    by_team = history_at(int(export["snapshot_id"]))
    previous_by_team = history_at(int(previous["id"]))
    participant_rows = conn.execute(
        "SELECT player_ea_id,team_index,stats_json FROM match_player_detailed_stats WHERE export_id=?",
        (detailed["exportId"],),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for team_index, team_id in enumerate((export["team0_ea_id"], export["team1_ea_id"])):
        if team_id is None:
            continue
        team_id = int(team_id)
        rows = [r for r in participant_rows if int(r["team_index"]) == team_index]
        starter_indices = [(as_int(json.loads(r["stats_json"]).get("array_index")), int(r["player_ea_id"])) for r in rows]
        if len({index for index, _ in starter_indices if index is not None and 0 <= index < 11}) != 11:
            continue
        starters = {player_id for index, player_id in starter_indices if index is not None and 0 <= index < 11}
        if len(starters) != 11:
            continue
        history = by_team.get(team_id, {})
        if not starters.issubset(history):
            continue
        earlier = previous_by_team.get(team_id, {})
        evidence_fields = ("minutes_played", "actual_position", "actual_position_id")
        def changed(player_id: int) -> bool:
            before = earlier.get(player_id)
            after = history[player_id]
            return before is None or any(before.get(field) != after.get(field) for field in evidence_fields)
        # A prior rival match can remain in last_match_players unchanged. A
        # fresh starter record is needed before attributing this team's rows.
        if not any(changed(player_id) for player_id in starters):
            continue
        initial = _line_shape(starters, history)
        if not initial:
            continue
        minutes = [as_int(row.get("minutes_played")) for row in history.values()]
        duration = max((minute for minute in minutes if minute is not None), default=0)
        final = None
        substitution_count = None
        if duration == 90:
            detailed_ids = {int(r["player_ea_id"]) for r in rows}
            incoming = {p for p, row in history.items() if p not in starters
                        and (as_int(row.get("minutes_played")) or 0) > 0
                        and (p in detailed_ids or changed(p))}
            outgoing = _departures(starters, incoming, history, duration)
            if outgoing is not None:
                final = _line_shape((starters - outgoing) | incoming, history)
                if final:
                    substitution_count = len(incoming)
        result.append({"teamEaId": team_id, "initialLines": initial,
                       "finalLines": final, "substitutionCount": substitution_count})
    return {"sourceSnapshotId": int(export["snapshot_id"]), "teams": result} if result else None
