"""Fixture-scoped goalkeeper metrics with explicit attribution guards.

Opponent xG is conventional chance quality, not post-shot xG or expected saves.
Player saves and team shots on target are kept as distinct source facts.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any

from .positions import trusted_position_source


MODEL_ID = "atlas-goalkeeper-context-v1"


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _stats(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _role(player: dict[str, Any], observed: dict[int, dict[str, Any]]) -> tuple[bool, str]:
    player_id = player.get("playerEaId")
    observed_row = observed.get(int(player_id), {}) if player_id is not None else {}
    if trusted_position_source(observed_row.get("source")) and observed_row.get("position"):
        return str(observed_row["position"]).upper().strip() == "GK", "observed"
    return str(player.get("primaryPosition") or "").upper().strip() == "GK", "registered"


def fixture_goalkeepers(teams: list[dict[str, Any]], players: list[dict[str, Any]], *,
                        observed_positions: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Attribute team context only when exactly one keeper has positive minutes."""
    observed = observed_positions or {}
    team_by_index = {int(team["teamIndex"]): team for team in teams if team.get("teamIndex") is not None}
    keepers_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        if player.get("teamIndex") is None or player.get("playerEaId") is None:
            continue
        is_keeper, basis = _role(player, observed)
        if not is_keeper:
            continue
        stats = player.get("stats") or {}
        keepers_by_index[int(player["teamIndex"])].append({
            "playerEaId": int(player["playerEaId"]),
            "minutes": _number(stats.get("minutes_played")),
            "saves": _number(stats.get("saves")),
            "goalsConceded": _number(stats.get("goals_conceded")),
            "shotsAgainst": _number(stats.get("shots_against")),
            "positionBasis": basis,
        })
    sides: list[dict[str, Any]] = []
    for index, team in sorted(team_by_index.items()):
        team_stats = team.get("stats") or {}
        opponent = next((item for other_index, item in team_by_index.items() if other_index != index), None)
        opponent_stats = (opponent or {}).get("stats") or {}
        keepers = keepers_by_index.get(index, [])
        positive = [keeper for keeper in keepers if keeper["minutes"] is not None and keeper["minutes"] > 0]
        unknown = [keeper for keeper in keepers if keeper["minutes"] is None]
        state = ("uncertain_minutes" if unknown else "multiple_goalkeepers" if len(positive) > 1
                 else "single_goalkeeper" if len(positive) == 1 else "no_goalkeeper")
        opponent_facts = {
            "opponentShotsOnTarget": _number(opponent_stats.get("shots_on_target")),
            "opponentNpkXg": _number(opponent_stats.get("npk_expected_goals")),
            "opponentXg": _number(opponent_stats.get("expected_goals_derived")),
        }
        metrics = {
            "opponentShotsOnTarget": None, "opponentNpkXg": None, "opponentXg": None,
            "saveRatePct": None, "savesPer90": None,
            "goalsConcededPer90": None, "goalsPrevented": None,
            "goalsPreventedPer90": None,
        }
        rate_reason = prevented_reason = None
        if state == "single_goalkeeper":
            metrics.update(opponent_facts)
            keeper = positive[0]
            minutes, saves, conceded = keeper["minutes"], keeper["saves"], keeper["goalsConceded"]
            team_saves = _number(team_stats.get("saves"))
            team_conceded = _number(team_stats.get("goals_conceded"))
            faced = metrics["opponentShotsOnTarget"]
            xga = metrics["opponentXg"]
            if saves is not None:
                metrics["savesPer90"] = round(saves * 90 / minutes, 2)
            if conceded is None or team_conceded is None:
                prevented_reason = "missing_goal_concession_pair"
            elif conceded != team_conceded:
                prevented_reason = "goal_concession_mismatch"
            else:
                metrics["goalsConcededPer90"] = round(conceded * 90 / minutes, 2)
                if xga is None:
                    prevented_reason = "missing_total_opponent_xg"
                else:
                    metrics["goalsPrevented"] = round(xga - conceded, 3)
                    metrics["goalsPreventedPer90"] = round((xga - conceded) * 90 / minutes, 3)
            if saves is None or conceded is None or faced is None:
                rate_reason = "missing_save_rate_input"
            elif team_saves is not None and saves != team_saves:
                rate_reason = "team_saves_mismatch"
            elif team_conceded is not None and conceded != team_conceded:
                rate_reason = "goal_concession_mismatch"
            elif saves + conceded != faced:
                rate_reason = "shots_on_target_mismatch"
            elif faced == 0:
                rate_reason = "no_shots_on_target"
            else:
                metrics["saveRatePct"] = round(saves / faced * 100, 1)
        else:
            rate_reason = prevented_reason = state
        sides.append({
            "teamIndex": index, "teamEaId": team.get("teamEaId"),
            "opponentTeamEaId": (opponent or {}).get("teamEaId"),
            "state": state, "keepers": keepers,
            "opponentTeamFacts": opponent_facts,
            "eligibleKeeperId": positive[0]["playerEaId"] if state == "single_goalkeeper" else None,
            "metrics": metrics, "saveRateReason": rate_reason,
            "goalsPreventedReason": prevented_reason,
            "source": {"saves": "FC26 goalkeeper row", "goalsConceded": "FC26 goalkeeper and team rows",
                       "shotsOnTarget": "FC26 opponent team row",
                       "opponentXg": "Atlas total xG from opponent NPK-xG and penalty context"},
        })
    return {"modelId": MODEL_ID, "sides": sides,
            "interpretationLimit": "Conventional opponent xG measures chance quality, not post-shot xG or individual goalkeeper responsibility."}


def contexts_for_exports(conn: Any, export_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Load all teammate and opponent facts in bounded batches, without N+1 queries."""
    result: dict[int, dict[str, Any]] = {}
    for start in range(0, len(export_ids), 400):
        ids = list(dict.fromkeys(int(value) for value in export_ids[start:start + 400]))
        if not ids:
            continue
        marks = ",".join("?" for _ in ids)
        teams: dict[int, list[dict[str, Any]]] = defaultdict(list)
        players: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in conn.execute(
            f"SELECT export_id,team_index,team_ea_id,stats_json FROM match_team_detailed_stats WHERE export_id IN ({marks})",
            ids,
        ):
            teams[int(row["export_id"])].append({"teamIndex": int(row["team_index"]),
                                                  "teamEaId": row["team_ea_id"],
                                                  "stats": _stats(row["stats_json"])})
        for row in conn.execute(
            f"""SELECT d.export_id,d.player_ea_id,d.team_index,d.minutes_played,d.stats_json,p.primary_position
                FROM match_player_detailed_stats d
                JOIN match_stat_exports e ON e.id=d.export_id
                LEFT JOIN player_states p ON p.snapshot_id=e.snapshot_id AND p.ea_player_id=d.player_ea_id
                WHERE d.export_id IN ({marks})""",
            ids,
        ):
            stats = _stats(row["stats_json"])
            if stats.get("minutes_played") is None:
                stats["minutes_played"] = row["minutes_played"]
            players[int(row["export_id"])].append({
                "playerEaId": int(row["player_ea_id"]), "teamIndex": int(row["team_index"]),
                "primaryPosition": row["primary_position"], "stats": stats,
            })
        for export_id in ids:
            team_rows = sorted(teams.get(export_id, []), key=lambda item: item["teamIndex"])
            if len(team_rows) == 2:
                from .match_stats import _add_team_expected_goals_from_opponent_penalty
                _add_team_expected_goals_from_opponent_penalty(team_rows[0]["stats"], team_rows[1]["stats"])
                _add_team_expected_goals_from_opponent_penalty(team_rows[1]["stats"], team_rows[0]["stats"])
            result[export_id] = fixture_goalkeepers(team_rows, players.get(export_id, []))
    return result


def summarize_keeper_matches(sides: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only the fixtures where each contextual metric is comparable."""
    sample = Counter()
    saves = faced = direct_saves = save_minutes = 0.0
    conceded = conceded_minutes = prevented = prevented_minutes = 0.0
    for side in sides:
        sample["appearances"] += 1
        if side.get("state") != "single_goalkeeper":
            sample["excluded"] += 1
            continue
        sample["singleKeeper"] += 1
        keeper = next((item for item in side.get("keepers", [])
                       if item.get("playerEaId") == side.get("eligibleKeeperId")), None)
        if not keeper:
            continue
        minutes = _number(keeper.get("minutes"))
        metrics = side.get("metrics") or {}
        if minutes is None or minutes <= 0:
            continue
        if keeper.get("saves") is not None:
            sample["savesPer90"] += 1
            direct_saves += float(keeper["saves"])
            save_minutes += minutes
        if metrics.get("saveRatePct") is not None:
            sample["saveRate"] += 1
            saves += float(keeper["saves"])
            faced += float(metrics["opponentShotsOnTarget"])
        if metrics.get("goalsConcededPer90") is not None:
            sample["goalsConceded"] += 1
            conceded += float(keeper["goalsConceded"])
            conceded_minutes += minutes
        if metrics.get("goalsPrevented") is not None:
            sample["goalsPrevented"] += 1
            prevented += float(metrics["goalsPrevented"])
            prevented_minutes += minutes
    return {
        "modelId": MODEL_ID, "sample": dict(sample),
        "saveRatePct": round(saves / faced * 100, 1) if faced > 0 else None,
        "savesPer90": round(direct_saves * 90 / save_minutes, 2) if save_minutes > 0 else None,
        "goalsConcededPer90": round(conceded * 90 / conceded_minutes, 2) if conceded_minutes > 0 else None,
        "goalsPrevented": round(prevented, 3) if sample["goalsPrevented"] else None,
        "goalsPreventedPer90": round(prevented * 90 / prevented_minutes, 3) if prevented_minutes > 0 else None,
    }
