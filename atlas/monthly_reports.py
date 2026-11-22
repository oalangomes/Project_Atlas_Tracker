"""Read-only, snapshot-scoped monthly sporting reports.

The structured result is independent of Markdown. MatchStats aggregation and
evidence eligibility remain owned by match_stats and metric_evidence.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from .commission import assess_sample
from .competition_scope import competition_category
from .match_stats import aggregate_detailed_stats, detailed_match, reconstruct_match_stats
from .metric_evidence import snapshot_fixture_evidence
from .positions import trusted_actual_position
from .server_utils import age_on_date


ROLE_FIELDS = {
    "GK": ("saves", "goals_conceded", "shots_against"),
    "DEF": ("tackles", "interceptions", "possession_won", "defense_duels_won"),
    "MID": ("key_passes", "passes", "interceptions", "expected_assists"),
    "ATT": ("npk_goals", "npk_expected_goals", "expected_assists", "shots", "key_passes"),
}


def _role(position: str | None) -> str:
    pos = str(position or "").upper()
    if pos == "GK":
        return "GK"
    if pos in {"CB", "LCB", "RCB", "LB", "RB", "LWB", "RWB", "SW"}:
        return "DEF"
    if pos in {"CDM", "CM"}:
        return "MID"
    return "ATT"


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _monthly_player(player: dict[str, Any], matches: list[dict[str, Any]],
                    previous: dict[str, Any] | None) -> dict[str, Any]:
    detailed = [row["detail"] for row in matches if row.get("detail")]
    summary = aggregate_detailed_stats(detailed)
    rated = [row for row in matches if _num(row.get("rating")) is not None]
    minutes_rows = [row for row in matches if _num(row.get("minutes")) is not None]
    minutes = sum(int(row["minutes"]) for row in minutes_rows)
    ratings = [float(row["rating"]) for row in rated]
    role = _role(player.get("position"))
    sample = assess_sample(minutes, len(rated))
    ordered_ratings = sorted(rated, key=lambda row: (float(row["rating"]), row["fixtureId"]))
    best = ordered_ratings[-1] if ordered_ratings else None
    worst = ordered_ratings[0] if ordered_ratings else None
    fields = tuple(dict.fromkeys((*ROLE_FIELDS[role], "npk_goals", "assists", "npk_expected_goals",
                                  "expected_assists", "shots", "key_passes", "tackles", "interceptions",
                                  "possession_won", "passes")))
    role_stats = {field: summary.get(field) for field in fields}
    detailed_minutes = summary.get("minutes_played")
    per90 = {field: round(float(value) * 90 / detailed_minutes, 2)
             for field, value in role_stats.items()
             if value is not None and detailed_minutes and
             summary["metricCoverage"].get(field) == len(detailed) and
             summary["metricCoverage"].get("minutes_played") == len(detailed)}
    result = {**player, "role": role, "matchesWithRating": len(rated),
              "matchesWithMinutes": len(minutes_rows), "minutes": minutes if minutes_rows else None,
              "averageRating": round(sum(ratings) / len(ratings), 2) if ratings else None,
              "detailedMatches": len(detailed), "detailedStats": role_stats,
              "detailedCoverage": summary["metricCoverage"], "per90": per90,
              "sample": sample["label"], "sampleCode": sample["code"],
              "best": {k: best.get(k) for k in ("fixtureId", "date", "opponent", "competition",
                                                 "goalsFor", "goalsAgainst", "rating", "minutes")} if best else None,
              "worst": {k: worst.get(k) for k in ("fixtureId", "date", "opponent", "competition",
                                                   "goalsFor", "goalsAgainst", "rating", "minutes")} if worst else None,
              "observedPositions": sorted({row["position"] for row in matches if row.get("position")}),
              "superiorOpponents": [row for row in matches if row.get("superior")],
              "reconstructed": {field: sum(row["reconstructed"].get(field, 0) for row in matches
                                            if row.get("reconstructed"))
                                for field in ("goals", "assists", "appearances")} if any(row.get("reconstructed") for row in matches) else None,
              "reconstructedMatches": sum(bool(row.get("reconstructed")) for row in matches)}
    if previous:
        result["comparison"] = {
            "overallDelta": (player["overall"] - previous["overall"]
                             if player.get("overall") is not None and previous.get("overall") is not None else None),
            "minutesDelta": (minutes - previous["minutes"]
                             if minutes_rows and previous.get("minutes") is not None else None),
            "ratingDelta": (round(result["averageRating"] - previous["averageRating"], 2)
                            if result["averageRating"] is not None and previous.get("averageRating") is not None else None),
        }
    else:
        result["comparison"] = None
    return result


def build_season_report(conn: sqlite3.Connection, career_id: int, season_index: int,
                        snapshot_id: int) -> dict[str, Any]:
    """Build one coherent season view as of an explicit snapshot; never writes."""
    conn.row_factory = sqlite3.Row
    snapshot = conn.execute(
        "SELECT * FROM snapshots WHERE id=? AND career_id=? AND season_index=?",
        (snapshot_id, career_id, season_index)).fetchone()
    if not snapshot:
        raise ValueError("Snapshot does not belong to the selected career and season")
    team = snapshot["managed_team_ea_id"]
    if team is None:
        raise ValueError("Selected snapshot has no managed team")
    career = conn.execute("SELECT fingerprint_candidate FROM careers WHERE id=?", (career_id,)).fetchone()
    fixtures = [dict(row) for row in conn.execute(
        """SELECT f.id fixtureId,f.fixture_key fixtureKey,f.home_team_ea_id homeTeamId,
                  f.away_team_ea_id awayTeamId,fo.date,fo.competition_name competition,
                  fo.home_team_name homeTeam,fo.away_team_name awayTeam,
                  fo.home_score homeScore,fo.away_score awayScore
           FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
           WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
           ORDER BY fo.date,f.id""", (snapshot_id,))]
    fixtures = [row for row in fixtures if row["date"] and row["date"][:10] <= snapshot["career_date"][:10]]
    evidence = {row["fixtureId"]: row["evidence"]
                for row in snapshot_fixture_evidence(conn, dict(snapshot))}
    reconstructed = reconstruct_match_stats(conn, snapshot_id)
    # All player IDs ever linked to the managed team or its academy before this snapshot.
    ids = {int(row[0]) for row in conn.execute(
        """SELECT DISTINCT player_ea_id FROM roster_states r JOIN snapshots s ON s.id=r.snapshot_id
           WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=? AND r.team_ea_id=?
           UNION SELECT DISTINCT player_ea_id FROM youth_player_states y JOIN snapshots s ON s.id=y.snapshot_id
           WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
           UNION SELECT DISTINCT player_ea_id FROM season_stat_states st JOIN snapshots s ON s.id=st.snapshot_id
           WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=? AND st.represented_team_ea_id=?
           UNION SELECT DISTINCT player_ea_id FROM loan_states ls JOIN snapshots s ON s.id=ls.snapshot_id
           WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=? AND ls.parent_team_ea_id=?""",
        (career_id, season_index, snapshot["import_sequence"], team,
         career_id, season_index, snapshot["import_sequence"],
         career_id, season_index, snapshot["import_sequence"], team,
         career_id, season_index, snapshot["import_sequence"], team))}
    first_seen = {int(row[0]): row[1] for row in conn.execute(
        """SELECT player_ea_id,MIN(career_date) FROM (
             SELECT r.player_ea_id,s.career_date FROM roster_states r JOIN snapshots s ON s.id=r.snapshot_id
              WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=? AND r.team_ea_id=?
             UNION ALL SELECT y.player_ea_id,s.career_date FROM youth_player_states y
              JOIN snapshots s ON s.id=y.snapshot_id WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
             UNION ALL SELECT st.player_ea_id,s.career_date FROM season_stat_states st
              JOIN snapshots s ON s.id=st.snapshot_id WHERE s.career_id=? AND s.season_index=?
               AND s.import_sequence<=? AND st.represented_team_ea_id=?
             UNION ALL SELECT ls.player_ea_id,s.career_date FROM loan_states ls
              JOIN snapshots s ON s.id=ls.snapshot_id WHERE s.career_id=? AND s.season_index=?
               AND s.import_sequence<=? AND ls.parent_team_ea_id=?) GROUP BY player_ea_id""",
        (career_id, season_index, snapshot["import_sequence"], team,
         career_id, season_index, snapshot["import_sequence"],
         career_id, season_index, snapshot["import_sequence"], team,
         career_id, season_index, snapshot["import_sequence"], team))}
    levels = {int(row["ea_team_id"]): {"league": row["league_name"], "level": row["level"]}
              for row in conn.execute(
                  """SELECT t.ea_team_id,l.league_name,l.level FROM team_states t
                     LEFT JOIN league_states l ON l.snapshot_id=t.snapshot_id AND l.ea_league_id=t.league_ea_id
                     WHERE t.snapshot_id=?""", (snapshot_id,))}
    managed_level = levels.get(team, {}).get("level")
    # The selected snapshot is the authoritative fixture set. One row per fixture.
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    player_matches: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for match in fixtures:
        month = match["date"][:7]
        home = match["homeTeamId"] == team
        match["opponent"] = match["awayTeam"] if home else match["homeTeam"]
        match["competitionCategory"] = competition_category(conn, snapshot_id, team, match["competition"])
        opponent_id = match["awayTeamId"] if home else match["homeTeamId"]
        opponent_level = levels.get(opponent_id, {})
        match["opponentLeague"] = opponent_level.get("league")
        match["opponentLevel"] = opponent_level.get("level")
        match["venue"] = "Casa" if home else "Fora"
        match["goalsFor"] = match["homeScore"] if home else match["awayScore"]
        match["goalsAgainst"] = match["awayScore"] if home else match["homeScore"]
        if match["goalsFor"] is None or match["goalsAgainst"] is None:
            match["result"] = "n/d"
        else:
            match["result"] = "V" if match["goalsFor"] > match["goalsAgainst"] else ("E" if match["goalsFor"] == match["goalsAgainst"] else "D")
        match["evidence"] = evidence.get(match["fixtureId"], {"state": "absent", "reason": "no_eligible_matchstats_export"})
        detail = detailed_match(conn, match["fixtureId"], career_id=career_id,
                               season_index=season_index,
                               as_of_import_sequence=snapshot["import_sequence"])
        match["exportId"] = detail["exportId"] if detail else None
        match["teamStats"] = next((row["stats"] for row in detail["teams"] if row["teamEaId"] == team), None) if detail else None
        match["opponentStats"] = next((row["stats"] for row in detail["teams"] if row["teamEaId"] != team), None) if detail else None
        match["superior"] = (managed_level is not None and match["opponentLevel"] is not None
                             and match["opponentLevel"] < managed_level)
        performance_rows = conn.execute(
            """SELECT p.* FROM player_match_performances p JOIN snapshots s ON s.id=p.snapshot_id
               WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
                 AND p.fixture_key=? ORDER BY s.import_sequence DESC,s.id DESC""",
            (career_id, season_index, snapshot["import_sequence"], match["fixtureKey"])).fetchall()
        performance = {}
        for row in performance_rows:
            performance.setdefault(int(row["player_ea_id"]), dict(row))
        detail_players = {}
        if detail:
            side = next((row["teamIndex"] for row in detail["teams"] if row["teamEaId"] == team), None)
            detail_players = {row["playerEaId"]: row["stats"] for row in detail["players"] if row["teamIndex"] == side}
        ids.update(detail_players)
        ids.update(performance)
        for pid in set(detail_players) | set(performance):
            first_seen[pid] = min(first_seen.get(pid, match["date"]), match["date"])
        standouts = []
        for pid in ids & (set(detail_players) | set(performance)):
            perf = performance.get(pid, {})
            stats = detail_players.get(pid)
            rec = reconstructed.get(match["fixtureKey"], {}).get(pid)
            minutes = perf.get("minutes_played")
            rating = perf.get("rating")
            if stats:
                minutes = stats.get("minutes_played", minutes)
                rating = stats.get("game_rating", rating)
            if _num(rating) is not None:
                detail_name = next((row["displayName"] for row in detail["players"]
                                    if row["playerEaId"] == pid and row.get("displayName")), None) if detail else None
                standouts.append({"playerEaId": pid, "name": perf.get("display_name") or detail_name or f"ID {pid}",
                                  "rating": rating, "minutes": minutes})
            player_matches[month][pid].append({
                "fixtureId": match["fixtureId"], "date": match["date"],
                "opponent": match["opponent"], "competition": match["competition"],
                "goalsFor": match["goalsFor"], "goalsAgainst": match["goalsAgainst"],
                "minutes": minutes, "rating": rating, "detail": stats,
                "position": trusted_actual_position(perf.get("actual_position"),
                                                     perf.get("actual_position_source")),
                "reconstructed": rec, "superior": match["superior"],
            })
        match["standouts"] = sorted(standouts, key=lambda row: (_num(row["rating"]) or 0,
                                                               _num(row["minutes"]) or 0), reverse=True)[:3]
        by_month[month].append(match)
    months = []
    previous_players: dict[int, dict[str, Any]] = {}
    previous_roster: set[int] | None = None
    for month, games in sorted(by_month.items()):
        month_end = f"{month}-31"
        month_snapshot = conn.execute(
            """SELECT id,career_date,import_sequence FROM snapshots WHERE career_id=? AND season_index=?
               AND import_sequence<=? AND career_date<=? ORDER BY import_sequence DESC,id DESC LIMIT 1""",
            (career_id, season_index, snapshot["import_sequence"], month_end)).fetchone()
        sid = int(month_snapshot["id"]) if month_snapshot else None
        rows = {int(row["ea_player_id"]): dict(row) for row in conn.execute(
            f"SELECT * FROM player_states WHERE snapshot_id=? AND ea_player_id IN ({','.join('?' for _ in ids)})",
            (sid, *sorted(ids)))} if ids and sid is not None else {}
        youth = {int(row["player_ea_id"]): dict(row) for row in conn.execute(
            "SELECT * FROM youth_player_states WHERE snapshot_id=?", (sid,))} if sid is not None else {}
        roster = {int(row[0]) for row in conn.execute(
            "SELECT player_ea_id FROM roster_states WHERE snapshot_id=? AND team_ea_id=?", (sid, team))} if sid is not None else set()
        loans = {int(row[0]) for row in conn.execute(
            "SELECT player_ea_id FROM loan_states WHERE snapshot_id=? AND parent_team_ea_id=?", (sid, team))} if sid is not None else set()
        players = []
        for pid in sorted(pid for pid in ids if first_seen.get(pid, month)[:7] <= month):
            state = rows.get(pid, {})
            academy = youth.get(pid, {})
            if not state and not academy and month_snapshot is not None:
                old_youth = conn.execute(
                    """SELECT y.* FROM youth_player_states y JOIN snapshots s ON s.id=y.snapshot_id
                       WHERE y.player_ea_id=? AND s.career_id=? AND s.season_index=?
                         AND s.import_sequence<=? ORDER BY s.import_sequence DESC,s.id DESC LIMIT 1""",
                    (pid, career_id, season_index, month_snapshot["import_sequence"])).fetchone()
                old_state = conn.execute(
                    """SELECT p.* FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
                       WHERE p.ea_player_id=? AND s.career_id=? AND s.season_index=?
                         AND s.import_sequence<=? ORDER BY s.import_sequence DESC,s.id DESC LIMIT 1""",
                    (pid, career_id, season_index, month_snapshot["import_sequence"])).fetchone()
                academy = dict(old_youth) if old_youth else {}
                state = dict(old_state) if old_state else {}
            raw = json.loads(state.get("raw_json") or "{}") if state else {}
            basic = {"playerEaId": pid, "name": state.get("display_name") or academy.get("display_name") or f"ID {pid}",
                     "position": state.get("primary_position") or academy.get("primary_position"),
                     "overall": state.get("overall") if state else academy.get("overall"),
                     "potential": state.get("potential") if state else academy.get("potential"),
                     "age": age_on_date(raw.get("birthdate_raw"), month_snapshot["career_date"]) if month_snapshot and raw else None,
                     "category": "profissional" if pid in roster else ("academia" if pid in youth else
                                 ("emprestado" if pid in loans else ("academia histórica" if academy and not state else "histórico/saída")))}
            players.append(_monthly_player(basic, player_matches[month].get(pid, []), previous_players.get(pid)))
        previous_players = {row["playerEaId"]: row for row in players}
        roster_changes = None if previous_roster is None else {
            "added": sorted(roster - previous_roster), "removed": sorted(previous_roster - roster)}
        previous_roster = roster
        competitions = {}
        for competition in sorted({row["competition"] or "n/d" for row in games}):
            subset = [row for row in games if (row["competition"] or "n/d") == competition]
            competitions[competition] = {"matches": len(subset), "wins": sum(row["result"] == "V" for row in subset),
                                         "draws": sum(row["result"] == "E" for row in subset),
                                         "losses": sum(row["result"] == "D" for row in subset)}
        known = [row for row in games if row["result"] != "n/d"]
        wins = sum(row["result"] == "V" for row in known)
        draws = sum(row["result"] == "E" for row in known)
        league = [row for row in games if row["competitionCategory"] == "league"]
        metric_coverage = {
            field: sum(game["teamStats"] is not None and game["opponentStats"] is not None and
                       game["teamStats"].get(field) is not None and
                       game["opponentStats"].get(field) is not None for game in games)
            for field in ("expected_goals_derived", "npk_expected_goals", "shots", "passes")}
        months.append({"month": month, "partial": month == snapshot["career_date"][:7],
                       "snapshotIdForPlayerState": sid, "matches": games, "players": players,
                       "rosterChanges": roster_changes, "metricCoverage": metric_coverage,
                       "competitions": competitions,
                       "pointsLeague": (3 * sum(row["result"] == "V" for row in league) +
                                        sum(row["result"] == "E" for row in league))
                       if all(row["result"] != "n/d" for row in league) else None,
                       "goalsFor": sum(row["goalsFor"] for row in games) if len(known) == len(games) else None,
                       "goalsAgainst": sum(row["goalsAgainst"] for row in games) if len(known) == len(games) else None,
                       "resultCoverage": len(known),
                       "pointsPct": round((3 * wins + draws) / (3 * len(known)) * 100, 1) if known else None,
                       "exports": sum(row["exportId"] is not None for row in games)})
    return {"careerId": career_id, "careerFingerprint": career[0], "seasonIndex": season_index,
            "snapshotId": snapshot_id, "snapshotCareerDate": snapshot["career_date"],
            "teamEaId": team, "teamName": snapshot["managed_team_name"],
            "months": months, "fixtureCount": len(fixtures), "playerCount": len(ids)}


def build_month_report(conn: sqlite3.Connection, career_id: int, season_index: int,
                       snapshot_id: int, month: str) -> dict[str, Any]:
    report = build_season_report(conn, career_id, season_index, snapshot_id)
    found = next((item for item in report["months"] if item["month"] == month), None)
    if found is None:
        raise ValueError(f"No completed managed matches in {month}")
    return found
