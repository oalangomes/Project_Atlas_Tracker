"""Descriptive rotation and match continuity using linked, as-of FC26 evidence."""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from .match_competitive_context import pre_match_competitive_context
from .match_lineups import match_lineup_phases
from .match_stats import _team_single_match_metrics
from .server_utils import as_int


MODEL_ID = "atlas-rotation-continuity-v1"
COMPLETE_STATUSES = ("complete_participant_export", "participant_export_complete_with_unresolved_nonparticipant")
METRICS = ("goalsFor", "goalsAgainst", "npkXgFor", "npkXgAgainst", "shotsFor", "shotsAgainst",
           "npkXgBalance", "shotsBalance")


def _number(value: Any) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
        return number if number is not None and math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _difference(left: Any, right: Any, digits: int = 2) -> float | None:
    a, b = _number(left), _number(right)
    return round(a - b, digits) if a is not None and b is not None else None


def _opponent_tier(gap: float | None) -> str:
    if gap is None:
        return "unknown"
    return "stronger" if gap > 2 else "weaker" if gap < -2 else "similar"


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in METRICS:
        values = [_number(row["metrics"].get(key)) for row in rows]
        known = [value for value in values if value is not None]
        metrics[key] = {"average": round(sum(known) / len(known), 2) if known else None,
                        "coveredMatches": len(known), "groupMatches": len(rows)}
    gaps = [_number(row["opponentContext"].get("overallGap")) for row in rows]
    known_gaps = [gap for gap in gaps if gap is not None]
    return {"matches": len(rows), "fixtureIds": [row["fixtureId"] for row in rows],
            "homeMatches": sum(row["venue"] == "home" for row in rows),
            "awayMatches": sum(row["venue"] == "away" for row in rows),
            "opponentOverallGapAverage": round(sum(known_gaps) / len(known_gaps), 2) if known_gaps else None,
            "opponentGapCoveredMatches": len(known_gaps), "metrics": metrics}


def _completed_fixtures(conn: sqlite3.Connection, career_id: int, season_indices: list[int],
                        as_of_sequence: int) -> list[sqlite3.Row]:
    if not season_indices:
        return []
    marks = ",".join("?" for _ in season_indices)
    return conn.execute(
        f"""WITH observed AS (
               SELECT fo.*,f.home_team_ea_id,f.away_team_ea_id,s.managed_team_ea_id,
                      s.season_index,s.import_sequence,s.id observation_snapshot_id,
                      ROW_NUMBER() OVER (PARTITION BY f.id ORDER BY s.import_sequence DESC,s.id DESC) rn
               FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
               JOIN snapshots s ON s.id=fo.snapshot_id
               WHERE s.career_id=? AND s.season_index IN ({marks}) AND s.import_sequence<=?
           ) SELECT * FROM observed WHERE rn=1 AND is_completed=1 AND managed_team_involved=1
           ORDER BY season_index,date,import_sequence,fixture_id""",
        (career_id, *season_indices, as_of_sequence),
    ).fetchall()


def _linked_exports(conn: sqlite3.Connection, career_id: int, season_indices: list[int],
                    as_of_sequence: int) -> dict[int, sqlite3.Row]:
    if not season_indices:
        return {}
    marks = ",".join("?" for _ in season_indices)
    rows = conn.execute(
        f"""WITH eligible AS (
               SELECT e.*,s.season_index,s.import_sequence,
                      ROW_NUMBER() OVER (PARTITION BY e.fixture_id
                          ORDER BY s.import_sequence DESC,e.id DESC) rn
               FROM match_stat_exports e JOIN snapshots s ON s.id=e.snapshot_id
               WHERE e.career_id=? AND s.season_index IN ({marks}) AND s.import_sequence<=?
                 AND e.linkage_status='linked' AND e.export_status IN (?,?)
           ) SELECT * FROM eligible WHERE rn=1""",
        (career_id, *season_indices, as_of_sequence, *COMPLETE_STATUSES),
    ).fetchall()
    return {int(row["fixture_id"]): row for row in rows if row["fixture_id"] is not None}


def rotation_continuity(conn: sqlite3.Connection, career_id: int, snapshot: sqlite3.Row,
                        season_indices: list[int], filters: dict[str, str] | None = None) -> dict[str, Any]:
    """Compare consecutive recorded XIs; all performance metrics are whole-match values."""
    selected = {key: str((filters or {}).get(key) or "") for key in
                ("competition", "venue", "opponentTier", "opponentFormation")}
    if selected["venue"] not in ("", "home", "away"):
        raise ValueError("Invalid venue filter.")
    if selected["opponentTier"] not in ("", "stronger", "similar", "weaker", "unknown"):
        raise ValueError("Invalid opponent tier filter.")
    fixtures = _completed_fixtures(conn, career_id, season_indices, int(snapshot["import_sequence"]))
    exports = _linked_exports(conn, career_id, season_indices, int(snapshot["import_sequence"]))
    rows: list[dict[str, Any]] = []
    prior: dict[str, Any] | None = None
    for fixture in fixtures:
        fixture_id = int(fixture["fixture_id"])
        team_id = as_int(fixture["managed_team_ea_id"])
        home_id, away_id = as_int(fixture["home_team_ea_id"]), as_int(fixture["away_team_ea_id"])
        if team_id not in (home_id, away_id):
            continue
        is_home = team_id == home_id
        opponent_id = away_id if is_home else home_id
        export = exports.get(fixture_id)
        starters: set[int] | None = None
        own_stats: dict[str, Any] = {}
        opponent_stats: dict[str, Any] = {}
        source_snapshot = None
        opponent_formation = None
        if export:
            source_snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (export["snapshot_id"],)).fetchone()
            team_index = 0 if as_int(export["team0_ea_id"]) == team_id else 1 if as_int(export["team1_ea_id"]) == team_id else None
            if team_index is not None:
                player_rows = conn.execute(
                    "SELECT player_ea_id,stats_json FROM match_player_detailed_stats WHERE export_id=? AND team_index=?",
                    (export["id"], team_index),
                ).fetchall()
                indexed = [(as_int(json.loads(row["stats_json"]).get("array_index")), int(row["player_ea_id"]))
                           for row in player_rows]
                slots = [index for index, _ in indexed if index is not None and 0 <= index < 11]
                players = {player for index, player in indexed if index is not None and 0 <= index < 11}
                if sorted(slots) == list(range(11)) and len(players) == 11:
                    starters = players
                team_rows = conn.execute(
                    "SELECT team_index,stats_json FROM match_team_detailed_stats WHERE export_id=?", (export["id"],)
                ).fetchall()
                for item in team_rows:
                    try:
                        parsed = _team_single_match_metrics(json.loads(item["stats_json"] or "{}"))
                    except (TypeError, ValueError):
                        parsed = {}
                    if int(item["team_index"]) == team_index:
                        own_stats = parsed
                    else:
                        opponent_stats = parsed
                lineup = match_lineup_phases(conn, {"exportId": int(export["id"]),
                                                    "snapshotId": int(export["snapshot_id"])}, fixture_id)
                opponent_formation = next((team["initialFormation"] for team in (lineup or {}).get("teams", [])
                                           if team["teamEaId"] == opponent_id), None)
        opponent_context: dict[str, Any] = {"available": False, "overallGap": None, "tier": "unknown",
                                            "asOfSnapshotId": None, "leagueLevel": None,
                                            "tablePosition": None, "reason": "no_prior_context"}
        context_snapshot = source_snapshot or conn.execute(
            "SELECT * FROM snapshots WHERE id=?", (fixture["observation_snapshot_id"],)
        ).fetchone()
        if context_snapshot and fixture["date"] and opponent_id is not None:
            context = pre_match_competitive_context(
                conn, career_id, context_snapshot, str(fixture["date"]), team_id, opponent_id,
                fixture["raw_json"] if "raw_json" in fixture.keys() else None,
            )
            gap = _number(context.get("opponent_overall_gap"))
            opponent_context = {"available": bool(context.get("available")), "overallGap": gap,
                                "tier": _opponent_tier(gap), "asOfSnapshotId": context.get("as_of_snapshot_id"),
                                "leagueLevel": (context.get("opponent") or {}).get("league_level"),
                                "tablePosition": context.get("opponent_table_position"),
                                "reason": context.get("reason")}
        goals_for = fixture["home_score"] if is_home else fixture["away_score"]
        goals_against = fixture["away_score"] if is_home else fixture["home_score"]
        npk_for, npk_against = _number(own_stats.get("npk_expected_goals")), _number(opponent_stats.get("npk_expected_goals"))
        shots_for, shots_against = _number(own_stats.get("shots")), _number(opponent_stats.get("shots"))
        retention = len(starters & prior["starters"]) if starters is not None and prior and prior["starters"] is not None and prior["season"] == int(fixture["season_index"]) else None
        group = "continued" if retention is not None and retention >= 8 else "changed" if retention is not None else None
        reason = ("no_complete_matchstats" if not export else "incomplete_initial_xi" if starters is None
                  else "previous_xi_unavailable" if retention is None else None)
        row = {"fixtureId": fixture_id, "date": fixture["date"], "seasonIndex": int(fixture["season_index"]),
               "competition": fixture["competition_name"], "venue": "home" if is_home else "away",
               "home": fixture["home_team_name"], "away": fixture["away_team_name"],
               "opponentEaId": opponent_id, "opponentName": fixture["away_team_name"] if is_home else fixture["home_team_name"],
               "sourceExportId": int(export["id"]) if export else None,
               "sourceSnapshotId": int(export["snapshot_id"]) if export else None,
               "initialXiKnown": starters is not None, "starterCount": len(starters) if starters is not None else None,
               "previousFixtureId": prior["fixtureId"] if prior and prior["season"] == int(fixture["season_index"]) else None,
               "retainedStarters": retention, "rotationGroup": group, "exclusionReason": reason,
               "opponentContext": opponent_context, "opponentInitialFormation": opponent_formation,
               "metrics": {"goalsFor": as_int(goals_for), "goalsAgainst": as_int(goals_against),
                           "npkXgFor": npk_for, "npkXgAgainst": npk_against,
                           "shotsFor": shots_for, "shotsAgainst": shots_against,
                           "npkXgBalance": _difference(npk_for, npk_against),
                           "shotsBalance": _difference(shots_for, shots_against, 0)}}
        rows.append(row)
        prior = {"fixtureId": fixture_id, "season": int(fixture["season_index"]), "starters": starters}
    options = {"competitions": sorted({str(row["competition"]) for row in rows if row["competition"]}),
               "opponentFormations": sorted({str(row["opponentInitialFormation"]) for row in rows
                                               if row["opponentInitialFormation"]})}
    filtered = [row for row in rows if
                (not selected["competition"] or row["competition"] == selected["competition"])
                and (not selected["venue"] or row["venue"] == selected["venue"])
                and (not selected["opponentTier"] or row["opponentContext"]["tier"] == selected["opponentTier"])
                and (not selected["opponentFormation"] or
                     (row["opponentInitialFormation"] or "unknown") == selected["opponentFormation"])]
    continued = [row for row in filtered if row["rotationGroup"] == "continued"]
    changed = [row for row in filtered if row["rotationGroup"] == "changed"]
    known = continued + changed
    summaries = {"continued": _group_summary(continued), "changed": _group_summary(changed)}
    comparable = min(len(continued), len(changed)) >= 3
    return {"modelId": MODEL_ID, "snapshotId": int(snapshot["id"]), "seasonIndices": season_indices,
            "definition": {"continued": "8–11 starters retained from the immediately previous completed match in this season",
                           "changed": "0–7 starters retained from the immediately previous completed match in this season",
                           "minimumGroupMatches": 3, "opponentTier": "pre-match squad OVR gap: stronger >2, similar -2 to 2, weaker <-2",
                           "resultScope": "descriptive whole-match comparison; no substitution on/off or causal inference"},
            "filters": selected, "filterOptions": options,
            "coverage": {"completedMatches": len(rows), "linkedDetailedMatches": sum(row["sourceExportId"] is not None for row in filtered),
                         "knownInitialXi": sum(row["initialXiKnown"] for row in filtered),
                         "groupedMatches": len(known), "selectedMatches": len(filtered),
                         "excludedFromComparison": len(filtered) - len(known),
                         "preMatchGapCovered": sum(row["opponentContext"]["overallGap"] is not None for row in filtered)},
            "groups": summaries, "comparisonEligible": comparable,
            "comparisonStatus": "descriptive" if comparable else "insufficient_group_sample",
            "possessionShare": {"status": "unavailable", "coveredMatches": 0,
                                "note": "No confirmed team possession percentage in the linked export; no without-possession style label."},
            "matches": filtered, "excluded": [row for row in filtered if row["rotationGroup"] is None]}
