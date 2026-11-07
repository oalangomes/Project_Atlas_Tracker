"""Pre-match opponent context from the career save, without future snapshots."""
from __future__ import annotations

import json
from typing import Any

from .team_strength import live_squad_strength


def _prior_league_table(conn: Any, career_id: int, snapshot_id: int, snapshot_date: str,
                        league_id: int, league_name: str) -> dict[int, dict[str, Any]]:
    """Rebuild a table only when all league clubs have comparable fixture coverage."""
    present = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('fixtures','fixture_observations')")}
    if present != {"fixtures", "fixture_observations"}:
        return {}
    team_ids = {int(row[0]) for row in conn.execute(
        "SELECT ea_team_id FROM team_states WHERE snapshot_id=? AND league_ea_id=?",
        (snapshot_id, league_id))}
    if len(team_ids) < 4:
        return {}
    rows = [dict(row) for row in conn.execute(
        """SELECT f.home_team_ea_id,f.away_team_ea_id,fo.home_team_name,fo.away_team_name,
                  fo.home_score,fo.away_score,fo.is_completed
           FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
           WHERE fo.snapshot_id=? AND f.career_id=? AND fo.competition_name=?
             AND fo.date<=? AND fo.is_completed=1""",
        (snapshot_id, career_id, league_name, snapshot_date))]
    rows = [row for row in rows if row["home_team_ea_id"] in team_ids
            and row["away_team_ea_id"] in team_ids
            and row["home_score"] is not None and row["away_score"] is not None]
    from .server_utils import aggregate_standings
    table = aggregate_standings(rows)
    if len(table) != len(team_ids) or not table:
        return {}
    played = [int(row["played"]) for row in table]
    if min(played) < 1 or max(played) - min(played) > 2:
        return {}
    # Alphabetical order is only a display fallback in aggregate_standings,
    # not a verified league tie-breaker. Do not publish a tied club's rank.
    keys = [(row["points"], row["goal_difference"], row["goals_for"]) for row in table]
    return {int(row["team_id"]): {
        "position": int(row["position"]) if keys.count(keys[index]) == 1 else None,
        "points": int(row["points"]), "matches_played": int(row["played"]),
        "team_count": len(table), "tie_break_unresolved": keys.count(keys[index]) > 1,
    } for index, row in enumerate(table)}


def pre_match_competitive_context(conn: Any, career_id: int, snapshot: Any,
                                  match_date: str, managed_team_id: int,
                                  opponent_team_id: int, fixture_raw: str | None = None) -> dict[str, Any]:
    """Use the last same-season snapshot strictly before the fixture date."""
    result: dict[str, Any] = {
        "available": False, "match_date": match_date, "as_of_snapshot_id": None,
        "as_of_career_date": None, "managed_team": None, "opponent": None,
        "opponent_overall_gap": None, "competition_phase": None,
        "opponent_table_position": None,
        "table_position_status": "unverified_in_imported_league_table",
    }
    required = {"snapshots", "team_states", "league_states", "roster_states", "player_states"}
    present = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?,?)", tuple(sorted(required)))}
    if present != required:
        result["reason"] = "career_context_tables_missing"
        return result
    prior = conn.execute(
        """SELECT id,career_date FROM snapshots
           WHERE career_id=? AND season_index=? AND import_sequence<=? AND career_date<?
           ORDER BY career_date DESC,import_sequence DESC,id DESC LIMIT 1""",
        (career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"]), match_date),
    ).fetchone()
    if not prior:
        result["reason"] = "no_prior_same_season_snapshot"
        return result
    prior_id = int(prior["id"])
    result["as_of_snapshot_id"] = prior_id
    result["as_of_career_date"] = str(prior["career_date"])

    def club(team_id: int) -> dict[str, Any]:
        row = conn.execute(
            """SELECT ts.team_name,ts.league_ea_id,ts.league_name,ls.country_id,ls.level
               FROM team_states ts LEFT JOIN league_states ls
                 ON ls.snapshot_id=ts.snapshot_id AND ls.ea_league_id=ts.league_ea_id
               WHERE ts.snapshot_id=? AND ts.ea_team_id=?""",
            (prior_id, team_id),
        ).fetchone()
        strength = live_squad_strength(conn, prior_id, team_id)
        count = int(strength["count"])
        # A handful of imported players is not a representative squad mean.
        average = round(float(strength["average"]), 1) if count >= 16 and strength["average"] is not None else None
        return {"team_ea_id": team_id, "team_name": row["team_name"] if row else None,
                "league_ea_id": int(row["league_ea_id"]) if row and row["league_ea_id"] is not None else None,
                "league_name": row["league_name"] if row else None,
                "league_level": int(row["level"]) if row and row["level"] is not None else None,
                "league_country_id": int(row["country_id"]) if row and row["country_id"] is not None else None,
                "squad_average_overall": average, "squad_player_count": count,
                "squad_membership_source": strength["membershipSource"],
                "squad_average_status": "available" if average is not None else "insufficient_current_save_roster"}

    managed, opponent = club(managed_team_id), club(opponent_team_id)
    result["managed_team"], result["opponent"] = managed, opponent
    tables: dict[int, dict[int, dict[str, Any]]] = {}
    for team in (managed, opponent):
        league_id, league_name = team.get("league_ea_id"), team.get("league_name")
        if league_id is None or not league_name:
            continue
        if league_id not in tables:
            tables[league_id] = _prior_league_table(conn, career_id, prior_id, str(prior["career_date"]),
                                                    league_id, league_name)
        position = tables[league_id].get(team["team_ea_id"])
        if position and position["position"] is not None:
            team["league_table"] = position
    opponent_table = opponent.get("league_table") or {}
    result["opponent_table_position"] = opponent_table.get("position")
    if result["opponent_table_position"] is not None:
        result["table_position_status"] = "derived_from_prior_completed_league_fixtures"
    if managed["squad_average_overall"] is not None and opponent["squad_average_overall"] is not None:
        result["opponent_overall_gap"] = round(
            opponent["squad_average_overall"] - managed["squad_average_overall"], 1)
    result["league_levels_comparable"] = bool(
        managed["league_country_id"] is not None
        and managed["league_country_id"] == opponent["league_country_id"])
    try:
        raw = json.loads(fixture_raw or "{}")
    except (TypeError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for key in ("round_name", "stage_name", "phase_name"):
            phase = raw.get(key)
            if isinstance(phase, str) and 2 <= len(phase.strip()) <= 80 and not phase.strip().isdigit():
                result["competition_phase"] = phase.strip()
                break
    result["available"] = bool(opponent["league_name"] or opponent["squad_average_overall"] is not None
                               or result["competition_phase"])
    result["source_note"] = ("Live career-save club and available roster state from the last same-season snapshot "
                             "strictly before this fixture; table rank uses prior completed league fixtures only "
                             "when coverage and tie-breaks are unambiguous. "
                             "Squad overall is an available-roster mean, not the match starting XI or a performance metric.")
    return result
