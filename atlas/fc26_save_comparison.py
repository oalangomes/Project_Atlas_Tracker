"""Optional parity audit for metrics already supplied by MatchStats."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from typing import Any

from .fc26_save_match import SavedMatchSide


def save_passing_comparison_enabled() -> bool:
    return os.environ.get("ATLAS_SAVE_PASSING_COMPARISON") == "1"


def save_shooting_defending_comparison_enabled() -> bool:
    return os.environ.get("ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON") == "1"


def save_shooting_defending_fallback_enabled() -> bool:
    return os.environ.get("ATLAS_SAVE_SHOOTING_DEFENDING_FALLBACK") == "1"


SHOOTING_DEFENDING_FALLBACK_METRICS = (
    ("shots", "Shots", "shots"),
    ("shots_on_target", "Shots on target", "shots"),
    ("blocks", "Defensive blocks", "actions"),
    ("clearances", "Clearances", "actions"),
    ("aerial_duels_won", "Aerial duels won", "duels"),
)


def _base_passing(fields: Mapping[str, int], through: Mapping[str, int]) -> dict[str, int | float]:
    total, completed = fields["passes_total"], fields["passes_completed"]
    if not 0 <= completed <= total < 0xFFFFFFFF:
        return {}
    stats: dict[str, int | float] = {"passes": total, "passes_completed": completed}
    if total:
        stats["pass_accuracy_pct_derived"] = round(completed / total * 100, 1)
    for key in ("passes_intercepted", "offside_passes"):
        if key in fields and 0 <= fields[key] <= total - completed:
            stats[key] = fields[key]
    if 0 <= fields["key_passes"] <= completed:
        stats["key_passes"] = fields["key_passes"]
    attempts, delivered = fields["crosses_attempted"], fields["crosses_delivered"]
    if 0 <= attempts <= total:
        stats["crosses_attempted"] = attempts
        if 0 <= delivered <= min(attempts, completed):
            stats["crosses_delivered"] = delivered
            if attempts:
                stats["cross_success_pct_derived"] = round(delivered / attempts * 100, 1)
    if "through_passes_completed" in through and "lobbed_through_passes_completed" in through:
        combined = through["through_passes_completed"] + through["lobbed_through_passes_completed"]
        if combined <= completed:
            stats["tracker_completed_through_passes_including_lobbed"] = combined
    return stats


def collect_comparable_passing(side: SavedMatchSide, players_are_unique: bool,
                               team_through: Mapping[str, int], player_through: Mapping[int, Mapping[str, int]],
                               ) -> tuple[dict[str, int | float], dict[int, dict[str, int | float]]]:
    team = _base_passing(side.fields, team_through)
    players = {player["player_id"]: _base_passing(player, player_through.get(player["player_id"], {}))
               for player in side.players} if players_are_unique else {}

    def total_for(key: str) -> int | float | None:
        if players and all(key in stats for stats in players.values()):
            return sum(stats[key] for stats in players.values())
        return None

    # Individual cross offsets need corroboration by the independent team tallies.
    totals_match = bool(team) and total_for("passes") == team["passes"] and total_for("passes_completed") == team["passes_completed"]
    attempts_match = (totals_match and "crosses_attempted" in team
                      and team["crosses_attempted"] == total_for("crosses_attempted"))
    delivered_match = (attempts_match and "crosses_delivered" in team
                       and team["crosses_delivered"] == total_for("crosses_delivered"))
    if not delivered_match:
        team.pop("crosses_delivered", None)
        team.pop("cross_success_pct_derived", None)
        for stats in players.values():
            stats.pop("crosses_delivered", None)
            stats.pop("cross_success_pct_derived", None)
    if not attempts_match:
        for stats in players.values():
            stats.pop("crosses_attempted", None)
    if totals_match:
        for key in ("passes_intercepted", "offside_passes"):
            count = total_for(key)
            if count is not None:
                team[key] = count
    return team, {player_id: stats for player_id, stats in players.items() if stats}


def collect_comparable_shooting_defending(side: SavedMatchSide,
                                         players_are_unique: bool) -> dict[str, Any]:
    def read(fields: Mapping[str, int], *, player: bool) -> dict[str, int]:
        raw_counters = ("blocks", "clearances", "aerial_duels_attempted") if player else (
            "blocks", "clearances", "aerial_duels_won", "saves",
        )
        stats = {key: fields[key] for key in raw_counters if fields[key] < 0xFFFFFFFF}
        if player and "aerial_duels_attempted" in stats and fields["aerial_duels_won"] <= stats["aerial_duels_attempted"]:
            stats["aerial_duels_won"] = fields["aerial_duels_won"]

        shots, on_target = fields["shots"], fields["shots_on_target"]
        if shots < 0xFFFFFFFF:
            stats["shots"] = shots
            if on_target <= shots:
                stats["shots_on_target"] = on_target
                if player and fields["shots_off_target_derived"] <= shots - on_target:
                    off_target = fields["shots_off_target_derived"]
                    stats["shots_off_target_derived"] = off_target
                    stats["shots_blocked"] = shots - on_target - off_target
        return stats

    players = {}
    if players_are_unique:
        for player in side.players:
            values = read(player, player=True)
            if values:
                players[player["player_id"]] = values
    return {"team": read(side.fields, player=False), "players": players}


def fixture_save_stat_sources(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                              fixture_id: int, detailed: Mapping[str, Any] | None) -> dict[str, Any]:
    passing = save_passing_comparison_enabled()
    shooting_defending = save_shooting_defending_comparison_enabled()
    fallback = save_shooting_defending_fallback_enabled() and not (detailed and detailed.get("available"))
    if not (passing or shooting_defending or fallback):
        return {}
    row = conn.execute(
        """SELECT p.snapshot_id,p.mxif_sha256,c.reader_revision,c.stats_json,
                  f.home_team_ea_id,f.away_team_ea_id
           FROM fc26_save_passing_comparison c JOIN fc26_save_possession p ON p.fixture_id=c.fixture_id
           JOIN snapshots s ON s.id=p.snapshot_id JOIN fixtures f ON f.id=p.fixture_id
           WHERE p.fixture_id=? AND s.career_id=? AND s.season_index=? AND s.import_sequence<=?""",
        (fixture_id, snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"]),
    ).fetchone()
    if row is None:
        return {}
    saved = json.loads(row["stats_json"])
    sources = {}
    if passing and "home" in saved and "away" in saved:
        sources["savePassingComparison"] = _compare_sources(saved, row, detailed)
    shooting_stats = saved.get("shootingAndDefending")
    if shooting_stats and shooting_defending:
        sources["saveShootingDefendingComparison"] = _compare_sources(shooting_stats, row, detailed)
    if shooting_stats and fallback:
        backup = _fallback_stats(shooting_stats, row)
        if backup["home"] or backup["away"]:
            sources["saveShootingDefendingFallback"] = backup
    return sources


def _save_source(row: sqlite3.Row) -> dict[str, Any]:
    return {"kind": "fc26_save_mxif", "readerRevision": row["reader_revision"],
            "sourceSnapshotId": row["snapshot_id"], "mxifSha256": row["mxif_sha256"]}


def _fallback_stats(saved: Mapping[str, Any], row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {"source": _save_source(row), "players": {}}
    for side in ("home", "away"):
        team = saved[side]["team"]
        players = saved[side]["players"]
        validated = {}
        # Require an independent match between the team count and the complete
        # set of recorded player values. Keep an unrelated field if one fails.
        for metric, _, _ in SHOOTING_DEFENDING_FALLBACK_METRICS:
            if metric not in team or not players or (metric == "shots_on_target" and "shots" not in validated):
                continue
            values = [stats.get(metric) for stats in players.values()]
            if all(value is not None for value in values) and sum(values) == team[metric]:
                validated[metric] = team[metric]
        result[side] = validated
        if validated:
            for player_id, stats in players.items():
                result["players"][player_id] = {"teamEaId": row[f"{side}_team_ea_id"],
                                                "stats": {metric: stats[metric] for metric in validated}}
    return result


def _compare_sources(saved: Mapping[str, Any], row: sqlite3.Row,
                     detailed: Mapping[str, Any] | None) -> dict[str, Any]:
    matchstats = detailed or {}
    live_teams = {team["teamEaId"]: team.get("stats", {}) for team in matchstats.get("teams", [])}
    teams_by_index = {team["teamIndex"]: team["teamEaId"] for team in matchstats.get("teams", [])}

    def compare(values: Mapping[str, Any], live_values: Mapping[str, Any]) -> dict[str, Any]:
        return {key: {"careerFile": value, "liveEditor": live_values.get(key)} for key, value in values.items()}

    home_id, away_id = row["home_team_ea_id"], row["away_team_ea_id"]
    sides_by_id = {home_id: "home", away_id: "away"}
    players = {}
    for player in matchstats.get("players", []):
        player_id = str(player["playerEaId"])
        team_id = teams_by_index.get(player["teamIndex"])
        side = sides_by_id.get(team_id)
        if side and player_id in saved[side]["players"]:
            players[player_id] = {"teamEaId": team_id,
                                  "stats": compare(saved[side]["players"][player_id], player.get("stats", {}))}
    return {
        "source": _save_source(row),
        "liveEditorExportId": matchstats.get("exportId"),
        "home": compare(saved["home"]["team"], live_teams.get(home_id, {})),
        "away": compare(saved["away"]["team"], live_teams.get(away_id, {})),
        "players": players,
    }
