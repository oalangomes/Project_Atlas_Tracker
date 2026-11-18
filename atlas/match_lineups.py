"""Conservative initial XI estimate from one linked match export."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .match_stats import _new_completed_fixture
from .positions import broad_position_group, canonical_position
from .server_utils import as_int

FORMATION_MODEL_ID = "atlas-match-formation-estimate-v3"


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


def _formation_shape(players: set[int], history: dict[int, dict[str, Any]]) -> tuple[str, str] | None:
    """Separate tactical lines only when the recorded role bands support it."""
    line_shape = _line_shape(players, history)
    if not line_shape:
        return None
    positions = [canonical_position(history[player_id].get("actual_position"),
                                    history[player_id].get("actual_position_id")) for player_id in players]
    groups = Counter(positions)
    defense, midfield, attack = (int(part) for part in line_shape.split("-"))
    defensive_midfield = sum(groups[pos] for pos in ("RDM", "CDM", "LDM"))
    central_midfield = sum(groups[pos] for pos in ("RCM", "CM", "LCM"))
    advanced_midfield = sum(groups[pos] for pos in ("RAM", "CAM", "LAM", "RM", "LM"))
    if (central_midfield == 0 and defensive_midfield > 0 and advanced_midfield > 0
            and defensive_midfield + advanced_midfield == midfield and attack > 0):
        return f"{defense}-{defensive_midfield}-{advanced_midfield}-{attack}", "role_bands"
    return line_shape, "broad_lines"


def match_lineup_phases(conn: sqlite3.Connection, detailed: dict[str, Any] | None,
                        fixture_id: int) -> dict[str, Any] | None:
    """Return the initial estimate only when its source and XI are attributable."""
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
        initial_shape = _formation_shape(starters, history)
        if not initial_shape:
            continue
        initial_lines = _line_shape(starters, history)
        result.append({"teamEaId": team_id, "initialLines": initial_lines,
                       "initialFormation": initial_shape[0], "initialPrecision": initial_shape[1]})
    return {"modelId": FORMATION_MODEL_ID, "sourceExportId": int(detailed["exportId"]),
            "sourceSnapshotId": int(export["snapshot_id"]), "teams": result} if result else None


def save_match_formation_estimates(conn: sqlite3.Connection, phases: dict[str, Any]) -> None:
    """Persist derived estimates with export and model provenance, apart from coach notes."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for team in phases["teams"]:
        evidence = {"sourceSnapshotId": phases["sourceSnapshotId"],
                    "lineShape": team["initialLines"], "precision": team["initialPrecision"]}
        conn.execute(
            "INSERT OR IGNORE INTO match_formation_estimates "
            "(source_export_id,team_ea_id,phase,model_id,formation,evidence_json,saved_at) "
            "VALUES(?,?,'initial',?,?,?,?)",
            (phases["sourceExportId"], team["teamEaId"], phases["modelId"],
             team["initialFormation"], json.dumps(evidence, sort_keys=True), now),
        )
