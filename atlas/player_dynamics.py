from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date
from typing import Any

from .tracker_context import development_capabilities
from .match_stats import reconstruct_match_stats
from .media_utils import season_start_from_date
from .server_utils import age_on_date, as_int, parse_raw
from .team_strength import live_squad_strength
from .world_simulation import WorldSimulationService

MODEL_ID = "atlas-dynamic-performance-v12"
NOISE_SEED_ID = "atlas-dynamic-performance-v3"  # preserve established career trajectories


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def position_group(position: Any) -> str:
    value = str(position or "").strip().upper()
    if value in {"GK", "TW"}:
        return "goalkeeper"
    if value in {"SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB", "RAV", "RV", "RIV", "IV", "LIV", "LV", "LAV"}:
        return "defence"
    if value in {"RDM", "CDM", "LDM", "RM", "RCM", "CM", "LCM", "LM", "RAM", "CAM", "LAM", "ZDM", "ZM", "ZOM"}:
        return "midfield"
    return "attack"


def performance_profile(position: Any, role_assignment: dict[str, Any] | None = None) -> str:
    value = str(position or "").strip().upper()
    if value in {"GK", "TW"}:
        profile = "goalkeeper"
    elif value in {"SW", "RCB", "CB", "LCB", "RIV", "IV", "LIV"}:
        profile = "centre_back"
    elif value in {"RWB", "LWB", "RAV", "LAV"}:
        profile = "wingback"
    elif value in {"RB", "LB", "RV", "LV"}:
        profile = "fullback"
    elif value in {"RDM", "CDM", "LDM", "ZDM"}:
        profile = "defensive_midfield"
    elif value in {"RCM", "CM", "LCM", "ZM"}:
        profile = "central_midfield"
    elif value in {"RAM", "CAM", "LAM", "ZOM"}:
        profile = "attacking_midfield"
    elif value in {"RM", "LM", "RW", "LW", "RF", "LF"}:
        profile = "winger"
    else:
        profile = "striker"
    assignment = role_assignment or {}
    role_group = str(assignment.get("roleGroup") or "")
    role_key = str(assignment.get("roleKey") or "")
    focus_key = str(assignment.get("focusKey") or "")
    if role_group == "defensive_midfield":
        profile = "defensive_midfield"
    elif role_group == "central_midfield":
        profile = "central_midfield"
    elif role_group == "attacking_midfield":
        profile = "attacking_midfield"
    elif role_group == "wide_attack":
        profile = "winger"
    elif role_group == "striker":
        profile = "striker"
    elif role_group == "fullback":
        profile = "wingback" if role_key in {"wingback", "attacking_wingback", "inverted_wingback"} or focus_key == "attack" else "fullback"
    return profile


PROFILE_LABELS = {
    "goalkeeper": "Torwart",
    "centre_back": "Innenverteidigung",
    "fullback": "defensive Full-back",
    "wingback": "attacking wide role/wing-back",
    "defensive_midfield": "defensives Midfield",
    "central_midfield": "zentrales Midfield",
    "attacking_midfield": "offensives Midfield",
    "winger": "Wing",
    "striker": "Centre-forward",
}


RATING_BASELINES = {
    "goalkeeper": 6.60,
    "centre_back": 6.65,
    "fullback": 6.55,
    "wingback": 6.55,
    "defensive_midfield": 6.60,
    "central_midfield": 6.65,
    "attacking_midfield": 6.70,
    "winger": 6.65,
    "striker": 6.65,
}


def _is_wide(position: Any) -> bool:
    return str(position or "").strip().upper() in {
        "RWB", "RB", "LB", "LWB", "RAV", "RV", "LV", "LAV", "RM", "LM", "RW", "LW", "RF", "LF",
    }


def _noise(snapshot_key: str, player_id: int, channel: str) -> float:
    digest = hashlib.sha256(f"{NOISE_SEED_ID}:{snapshot_key}:{player_id}:{channel}".encode("utf-8")).digest()
    number = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return number * 2.0 - 1.0


def _raw_number(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = raw.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _season_progress(career_date: str) -> float:
    try:
        current = date.fromisoformat(str(career_date)[:10])
    except ValueError:
        return 0.5
    start_year = season_start_from_date(current.isoformat())
    if start_year is None:
        return 0.5
    start = date(start_year, 7, 1)
    end = date(start_year + 1, 6, 30)
    return _clamp((current - start).days / max(1, (end - start).days), 0.0, 1.0)


class PlayerDynamicsService:
    """Seasonal performance state without altering imported OVR/POT.

    Observed statistics are preferred. Players without deeper-simulation statistics
    receive a deterministic, explicitly labelled shallow simulation based on table,
    squad role, ability and season progress. It is a scouting signal, not claimed
    match history.
    """

    def __init__(self, database):
        self.database = database
        self.world = WorldSimulationService(database)

    @staticmethod
    def _aggregate_stats(conn: sqlite3.Connection, snapshot_id: int) -> dict[int, dict[str, Any]]:
        observed = conn.execute(
            "SELECT ss.player_ea_id,ss.appearances,ss.goals,ss.assists,ss.clean_sheets,ss.saves,ss.goals_conceded,ss.average_rating,"
            "ss.man_of_the_match,ss.yellow_cards,ss.second_yellow_cards,ss.red_cards "
            "FROM season_stat_states ss JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id "
            "WHERE ss.snapshot_id=? AND ss.represented_team_ea_id=p.team_ea_id",
            (snapshot_id,),
        ).fetchall()
        simulated = conn.execute(
            "SELECT ss.player_ea_id,ss.appearances,ss.goals,ss.assists,ss.clean_sheets,ss.saves,ss.goals_conceded,ss.average_rating,"
            "0 man_of_the_match,0 yellow_cards,0 second_yellow_cards,0 red_cards "
            "FROM atlas_simulated_player_stats ss JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id "
            "WHERE ss.snapshot_id=? AND ss.team_ea_id=p.team_ea_id",
            (snapshot_id,),
        ).fetchall()
        result: dict[int, dict[str, Any]] = {}
        ratings: dict[int, list[tuple[float, int]]] = defaultdict(list)
        sources: dict[int, set[str]] = defaultdict(set)
        for source, rows in (("observed", observed), ("simulated", simulated)):
            for row in rows:
                player_id = int(row["player_ea_id"])
                sources[player_id].add(source)
                item = result.setdefault(player_id, {
                    "appearances": 0, "goals": 0, "assists": 0, "clean_sheets": 0,
                    "saves": 0, "goals_conceded": 0, "average_rating": None,
                    "man_of_the_match": 0, "yellow_cards": 0,
                    "second_yellow_cards": 0, "red_cards": 0,
                })
                apps = as_int(row["appearances"]) or 0
                item["appearances"] += apps
                item["goals"] += as_int(row["goals"]) or 0
                item["assists"] += as_int(row["assists"]) or 0
                item["clean_sheets"] += as_int(row["clean_sheets"]) or 0
                item["saves"] += as_int(row["saves"]) or 0
                item["goals_conceded"] += as_int(row["goals_conceded"]) or 0
                item["man_of_the_match"] += as_int(row["man_of_the_match"]) or 0
                item["yellow_cards"] += as_int(row["yellow_cards"]) or 0
                item["second_yellow_cards"] += as_int(row["second_yellow_cards"]) or 0
                item["red_cards"] += as_int(row["red_cards"]) or 0
                if row["average_rating"] not in (None, 0) and apps > 0:
                    ratings[player_id].append((float(row["average_rating"]), apps))
        for player_id, item in result.items():
            values = ratings.get(player_id, [])
            if values:
                total_apps = sum(apps for _, apps in values)
                item["average_rating"] = round(sum(rating * apps for rating, apps in values) / total_apps, 2)
            item["coverage"] = "hybrid" if len(sources[player_id]) > 1 else next(iter(sources[player_id]))
        return result

    @staticmethod
    def _team_matches(table: dict[int, dict[str, Any]], team_id: int | None, career_date: str, team_count: int) -> int:
        if team_id is not None:
            observed = as_int((table.get(team_id) or {}).get("matches_played"))
            if observed is not None and observed > 0:
                return observed
        total = int(_clamp((team_count - 1) * 2 if 8 <= team_count <= 24 else 34, 22, 38))
        return max(1, int(round(total * _season_progress(career_date))))

    @staticmethod
    def _expected_usage(rank: int, squad_size: int, age: int | None, potential_gap: int, injury: int) -> float:
        if rank <= 11:
            usage = 0.82
        elif rank <= 16:
            usage = 0.54
        elif rank <= 22:
            usage = 0.27
        else:
            usage = 0.08
        if age is not None and age <= 20 and potential_gap >= 5 and rank > 11:
            usage += 0.08
        if injury:
            usage *= 0.55
        return _clamp(usage, 0.02, 0.92)

    @staticmethod
    def _managed_minute_usage(conn: sqlite3.Connection, snapshot_id: int, player_id: int) -> dict[str, Any] | None:
        """Return observed all-competition minute share for the managed team.

        Match-rating history has one row per player appearance. Counting all
        represented match dates provides the denominator, including matches in
        which this player did not appear. Minutes are capped at the regulation
        90 used by FC's role promises, so extra time cannot create >100% usage.
        """

        covered = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(NULLIF(fixture_key,''),NULLIF(date,''))) "
            "FROM player_match_performances WHERE snapshot_id=? "
            "AND COALESCE(NULLIF(fixture_key,''),NULLIF(date,'')) IS NOT NULL",
            (snapshot_id,),
        ).fetchone()[0]
        match_count = int(covered or 0)
        if match_count <= 0:
            return None
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(fixture_key,''),NULLIF(date,'')) match_key,MAX(COALESCE(minutes_played,0)) minutes "
            "FROM player_match_performances WHERE snapshot_id=? AND player_ea_id=? "
            "AND COALESCE(NULLIF(fixture_key,''),NULLIF(date,'')) IS NOT NULL GROUP BY match_key",
            (snapshot_id, player_id),
        ).fetchall()
        minutes = sum(max(0, min(90, as_int(row["minutes"]) or 0)) for row in rows)
        appearances = sum(1 for row in rows if (as_int(row["minutes"]) or 0) > 0)
        possible = match_count * 90
        return {
            "share": _clamp(minutes / max(1, possible), 0.0, 1.0),
            "minutesPlayed": minutes,
            "possibleMinutes": possible,
            "coveredMatches": match_count,
            "appearanceMatches": appearances,
            "basis": "observed_minutes",
        }

    @staticmethod
    def _team_strength(team_id: int | None, live_overall: float | None, table: dict[int, dict[str, Any]], league_team_ids: list[int]) -> float:
        if team_id is not None:
            row = table.get(team_id) or {}
            position = as_int(row.get("current_table_position"))
            if position and league_team_ids:
                return _clamp(1.0 - (position - 1) / max(1, len(league_team_ids) - 1), 0.0, 1.0)
        if live_overall is not None and league_team_ids:
            return _clamp((live_overall - 58) / 30, 0.0, 1.0)
        return 0.5

    @staticmethod
    def _simulate_stats(*, snapshot_key: str, player: dict[str, Any], team: dict[str, Any] | None,
                        team_matches: int, squad_rank: int, squad_size: int,
                        team_strength: float, team_overall: float | None,
                        age: int | None, injury: int) -> dict[str, Any]:
        player_id = int(player["ea_player_id"])
        overall = as_int(player.get("overall")) or 60
        potential = as_int(player.get("potential")) or overall
        group = position_group(player.get("primary_position"))
        usage = PlayerDynamicsService._expected_usage(squad_rank, squad_size, age, max(0, potential - overall), injury)
        appearances = max(0, min(team_matches, int(round(team_matches * usage + _noise(snapshot_key, player_id, "apps") * 1.2))))
        relative = _clamp((overall - (team_overall if team_overall is not None else overall)) / 12, -1.0, 1.0)
        rating = _clamp(6.28 + team_strength * 0.48 + relative * 0.24 + _noise(snapshot_key, player_id, "rating") * 0.24, 5.9, 7.75)
        strength = _clamp((overall - 55) / 35, 0.1, 1.2)
        n = max(0, appearances)
        if group == "goalkeeper":
            goals = assists = 0
            clean_rate = _clamp(0.12 + team_strength * 0.28 + strength * 0.05, 0.08, 0.48)
            clean_sheets = int(round(n * clean_rate + max(-1.0, _noise(snapshot_key, player_id, "cs"))))
            conceded = max(0, int(round(n * _clamp(1.65 - team_strength * 0.75 - strength * 0.22, 0.55, 1.9))))
            saves = max(0, int(round(n * _clamp(3.7 - team_strength * 1.15 + strength * 0.35, 1.8, 4.5))))
        elif group == "defence":
            goals = max(0, int(round(n * (0.012 + strength * 0.025) + _noise(snapshot_key, player_id, "goals"))))
            assists = max(0, int(round(n * (0.018 + strength * (0.055 if _is_wide(player.get("primary_position")) else 0.025)) + _noise(snapshot_key, player_id, "assists"))))
            clean_sheets = int(round(n * _clamp(0.14 + team_strength * 0.28, 0.08, 0.48)))
            saves = conceded = 0
        elif group == "midfield":
            goals = max(0, int(round(n * (0.025 + strength * 0.11) + _noise(snapshot_key, player_id, "goals") * 1.2)))
            assists = max(0, int(round(n * (0.035 + strength * 0.13) + _noise(snapshot_key, player_id, "assists") * 1.3)))
            clean_sheets = saves = conceded = 0
        else:
            goals = max(0, int(round(n * (0.07 + strength * 0.34) + _noise(snapshot_key, player_id, "goals") * 1.8)))
            assists = max(0, int(round(n * (0.025 + strength * 0.10) + _noise(snapshot_key, player_id, "assists"))))
            clean_sheets = saves = conceded = 0
        return {
            "appearances": n, "goals": goals, "assists": assists,
            "clean_sheets": max(0, clean_sheets), "saves": saves,
            "goals_conceded": conceded, "average_rating": round(rating, 2),
        }

    @staticmethod
    def _performance_score(stats: dict[str, Any], profile: str, team_strength: float) -> tuple[float, dict[str, Any]]:
        apps = max(0, int(stats.get("appearances") or 0))
        rating = stats.get("average_rating")
        baseline = RATING_BASELINES[profile]
        rating_sample = min(1.0, apps / 5.0) if apps else 0.0
        raw_rating_delta = 0.0 if rating is None else (float(rating) - baseline) * 24 * rating_sample
        output = 0.0
        sample_weight = min(1.0, apps / 6.0) if apps else 0.0
        if apps > 0:
            goals = int(stats.get("goals") or 0)
            assists = int(stats.get("assists") or 0)
            goal_rate = goals / apps
            assist_rate = assists / apps
            if profile == "goalkeeper":
                shots = int(stats.get("saves") or 0) + int(stats.get("goals_conceded") or 0)
                save_pct = int(stats.get("saves") or 0) / shots if shots else None
                output += math.tanh((save_pct - .68) / .10) * 14 if save_pct is not None else 0.0
                output += max(0.0, math.tanh((int(stats.get("clean_sheets") or 0) / apps - .20) / .18) * 6)
            elif profile == "centre_back":
                output += min(11.0, goals * 4.5 + assists * 2.0)
                output += max(0.0, math.tanh((int(stats.get("clean_sheets") or 0) / apps - .20) / .18) * 5)
            elif profile == "fullback":
                output += min(10.0, goals * 3.8 + assists * 2.2)
                output += max(0.0, math.tanh((int(stats.get("clean_sheets") or 0) / apps - .20) / .18) * 4)
            elif profile == "wingback":
                output += min(6.0, goals * 2.8)
                output += math.tanh((assist_rate - .10) / .16) * 8
                output += max(0.0, math.tanh((int(stats.get("clean_sheets") or 0) / apps - .20) / .20) * 2)
            elif profile == "defensive_midfield":
                # Scorers are a bonus for a six, never a prerequisite.
                output += min(10.0, goals * 3.8 + assists * 2.0)
            elif profile == "central_midfield":
                output += math.tanh((goal_rate - .05) / .14) * 5
                output += math.tanh((assist_rate - .08) / .18) * 7
            elif profile == "attacking_midfield":
                output += math.tanh((goal_rate - .12) / .20) * 10
                output += math.tanh((assist_rate - .13) / .20) * 13
            elif profile == "winger":
                output += math.tanh((goal_rate - .12) / .18) * 11
                output += math.tanh((assist_rate - .12) / .18) * 11
            else:
                output += math.tanh((goal_rate - .20) / .22) * 18
                output += math.tanh((assist_rate - .08) / .18) * 7
            output *= sample_weight
        motm = max(0, int(stats.get("man_of_the_match") or 0))
        discipline = (
            max(0, int(stats.get("yellow_cards") or 0)) * .65
            + max(0, int(stats.get("second_yellow_cards") or 0)) * 2.5
            + max(0, int(stats.get("red_cards") or 0)) * 4.0
        )
        motm_contribution = min(9.0, motm / max(1, apps) * 25.0) * sample_weight
        discipline_contribution = -min(9.0, discipline)
        # Great output for a weaker side is marginally harder; team strength is
        # context, not a free positive bonus to every player at a strong club.
        team_contribution = (0.5 - team_strength) * 4
        score = _clamp(50 + raw_rating_delta + output + motm_contribution + discipline_contribution + team_contribution, 5, 98)
        return score, {
            "profile": profile,
            "profileLabel": PROFILE_LABELS[profile],
            "ratingBaseline": baseline,
            "ratingContribution": round(raw_rating_delta, 2),
            "outputContribution": round(output, 2),
            "motmContribution": round(motm_contribution, 2),
            "disciplineContribution": round(discipline_contribution, 2),
            "teamContribution": round(team_contribution, 2),
            "sampleWeight": round(sample_weight, 3),
            "positionProtection": profile in {"goalkeeper", "centre_back", "fullback", "defensive_midfield"},
        }

    @staticmethod
    def _tactical_role_assignments(conn: sqlite3.Connection, career_id: int) -> dict[int, dict[str, Any]]:
        return {}

    @staticmethod
    def _managed_match_rows(
        conn: sqlite3.Connection, snapshot_id: int, reconstructed: dict[str, dict[int, dict[str, Any]]],
    ) -> dict[int, list[dict[str, Any]]]:
        rows = conn.execute(
            "SELECT player_ea_id,fixture_key,date,rating,minutes_played,actual_position FROM player_match_performances "
            "WHERE snapshot_id=? AND rating IS NOT NULL ORDER BY date DESC,artificial_key DESC",
            (snapshot_id,),
        ).fetchall()
        result: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            player_id = int(row["player_ea_id"])
            fixture_key = str(row["fixture_key"] or "")
            event = (reconstructed.get(fixture_key) or {}).get(player_id) or {}
            item = dict(row)
            item["reconstructed"] = event
            result[player_id].append(item)
        return result

    @staticmethod
    def _detailed_match_evidence(conn: sqlite3.Connection, career_id: int, season_index: int) -> dict[int, dict[str, Any]]:
        rows = conn.execute(
            """SELECT mpds.player_ea_id,mse.fixture_id,mpds.minutes_played,mpds.game_rating,mpds.stats_json
               FROM match_player_detailed_stats mpds
               JOIN match_stat_exports mse ON mse.id=mpds.export_id
               JOIN snapshots s ON s.id=mse.snapshot_id
               WHERE mse.career_id=? AND s.season_index=? AND mse.superseded_by_export_id IS NULL""",
            (career_id, season_index),
        ).fetchall()
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            pid = int(row["player_ea_id"])
            item = grouped.setdefault(pid, {"fixtures": set(), "minutes": 0, "ratings": [], "npkXg": 0.0, "xA": 0.0})
            item["fixtures"].add(int(row["fixture_id"]))
            minutes = max(0, min(130, as_int(row["minutes_played"]) or 0))
            item["minutes"] += minutes
            if row["game_rating"] is not None and float(row["game_rating"]) > 0:
                item["ratings"].append((float(row["game_rating"]), max(1, minutes)))
            try:
                stats = json.loads(str(row["stats_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                stats = {}
            item["npkXg"] += max(0.0, float(stats.get("npk_expected_goals") or 0))
            item["xA"] += max(0.0, float(stats.get("expected_assists") or 0))
        result: dict[int, dict[str, Any]] = {}
        for pid, item in grouped.items():
            ratings = item["ratings"]
            weight = sum(value[1] for value in ratings)
            result[pid] = {
                "matches": len(item["fixtures"]), "minutes": item["minutes"],
                "averageRating": round(sum(rating * minutes for rating, minutes in ratings) / weight, 3) if weight else None,
                "npkXg": round(item["npkXg"], 3), "xA": round(item["xA"], 3),
            }
        return result

    @staticmethod
    def _match_window_score(matches: list[dict[str, Any]], profile: str) -> tuple[float | None, dict[str, Any]]:
        if not matches:
            return None, {"matches": 0, "effectiveWeight": 0.0, "events": 0}
        baseline = RATING_BASELINES[profile]
        weighted_total = 0.0
        total_weight = 0.0
        event_contribution = 0.0
        event_count = 0
        for index, match in enumerate(matches):
            minutes = max(0, min(90, as_int(match.get("minutes_played")) or 0))
            recency = max(.72, 1.0 - index * .07)
            weight = max(.22, min(1.0, minutes / 75.0)) * recency
            rating = float(match.get("rating") or baseline)
            weighted_total += (rating - baseline) * 24 * weight
            total_weight += weight
            event = match.get("reconstructed") or {}
            goals = int(event.get("goals") or 0)
            assists = int(event.get("assists") or 0)
            if goals or assists or event.get("man_of_the_match") or event.get("red_cards") or event.get("second_yellow_cards"):
                event_count += 1
            goal_weight = {
                "centre_back": 5.0, "fullback": 4.2, "wingback": 3.6,
                "defensive_midfield": 4.2, "central_midfield": 3.6,
                "attacking_midfield": 3.2, "winger": 3.0, "striker": 2.8,
            }.get(profile, 4.0)
            assist_weight = {
                "centre_back": 2.3, "fullback": 2.5, "wingback": 2.8,
                "defensive_midfield": 2.2, "central_midfield": 2.6,
                "attacking_midfield": 3.0, "winger": 2.8, "striker": 2.0,
            }.get(profile, 2.0)
            event_contribution += (goals * goal_weight + assists * assist_weight) * weight
            event_contribution += int(event.get("man_of_the_match") or 0) * 4.0 * weight
            event_contribution -= int(event.get("yellow_cards") or 0) * .6 * weight
            event_contribution -= int(event.get("second_yellow_cards") or 0) * 2.5 * weight
            event_contribution -= int(event.get("red_cards") or 0) * 4.0 * weight
            if profile in {"goalkeeper", "centre_back", "fullback", "wingback"}:
                event_contribution += int(event.get("clean_sheets") or 0) * .9 * weight
            if profile == "goalkeeper" and event.get("save_percentage") is not None:
                event_contribution += math.tanh((float(event["save_percentage"]) - .68) / .10) * 3.5 * weight
        rating_contribution = weighted_total / max(.001, total_weight)
        score = _clamp(50 + rating_contribution + event_contribution, 5, 98)
        return score, {
            "matches": len(matches),
            "effectiveWeight": round(total_weight, 3),
            "ratingContribution": round(rating_contribution, 2),
            "eventContribution": round(event_contribution, 2),
            "events": event_count,
        }

    @staticmethod
    def _morale_score(*, raw: dict[str, Any], roster: dict[str, Any] | None, usage: float,
                      expected_usage: float, team_strength: float) -> tuple[float, str]:
        direct = _raw_number(raw, ("morale", "player_morale", "morale_value"))
        if direct is not None:
            if direct <= 10:
                direct *= 10
            return _clamp(direct, 0, 100), "beobachtet"
        form = as_int((roster or {}).get("form"))
        form_component = 0.0
        if form is not None:
            if 1 <= form <= 10:
                form_component = (form - 5) * 2.0
            elif -10 <= form <= 0:
                form_component = form * 1.8
            elif 0 <= form <= 100:
                form_component = (form - 50) * 0.22
        score = 50 + form_component + (usage - expected_usage) * 32 + (team_strength - 0.5) * 12
        return _clamp(score, 15, 88), "Proxy based on playing time, form and team situation"

    @staticmethod
    def _fitness_score(*, raw: dict[str, Any], roster: dict[str, Any] | None,
                       previous_roster: dict[str, Any] | None, previous_breakdown: dict[str, Any] | None,
                       days_since_previous: int | None, snapshot_key: str, player_id: int,
                       allow_simulated_setback: bool) -> tuple[float, str, dict[str, Any]]:
        """Return match fitness and a transparent availability state.

        Imported injuries remain authoritative. A player who was injured in the
        previous snapshot does not jump straight back to 100: a deterministic
        recovery window models match sharpness. Shallow-simulation players may
        occasionally receive a clearly labelled temporary workload setback.
        """
        injury = as_int((roster or {}).get("injury")) or 0
        previous_injury = as_int((previous_roster or {}).get("injury")) or 0
        direct = _raw_number(raw, ("match_fitness", "fitness", "energy", "energy_level", "physical_condition"))
        if direct is not None:
            if direct <= 1:
                direct *= 100
            direct = _clamp(direct, 0, 100)
            if injury:
                direct = min(direct, 52)
            state = "injured" if injury else "observed"
            return direct, "beobachteter Fitness-/Energiewert", {
                "state": state, "label": "Injured" if injury else "Observed fitness",
                "simulated": False, "recoveryDaysRemaining": None,
            }
        if injury:
            severity = (_noise(snapshot_key, player_id, "injury_severity") + 1.0) / 2.0
            remaining = int(round(24 + severity * 32))
            fitness = round(30 + (1.0 - severity) * 16, 1)
            return fitness, "beobachteter Verletzungsstatus; Match Fitness reduziert", {
                "state": "injured", "label": "Injured", "simulated": False,
                "recoveryDaysRemaining": remaining,
            }

        previous_availability = ((previous_breakdown or {}).get("availability") or {})
        previous_remaining = as_int(previous_availability.get("recoveryDaysRemaining")) or 0
        elapsed = max(0, days_since_previous or 0)
        if previous_injury or previous_availability.get("state") in {"injured", "recovery", "simulated_setback"}:
            if previous_remaining <= 0:
                seed = (_noise(snapshot_key, player_id, "recovery_window") + 1.0) / 2.0
                previous_remaining = int(round(18 + seed * 28))
            # We do not know the exact clearance date between snapshots. Assume roughly
            # half the interval was available for football-specific recovery.
            remaining = max(0, previous_remaining - max(4, int(round(elapsed * 0.55))))
            if remaining > 0:
                total = max(previous_remaining, 14)
                progress = _clamp(1.0 - remaining / total, 0.0, 1.0)
                fitness = round(62 + progress * 31, 1)
                simulated = bool(previous_availability.get("simulated")) and not previous_injury
                return fitness, "Aufbauphase nach Verletzung/Belastungsunterbrechung", {
                    "state": "recovery", "label": "Im Belastungsaufbau", "simulated": simulated,
                    "recoveryDaysRemaining": remaining,
                }

        if allow_simulated_setback:
            event = _noise(snapshot_key, player_id, "availability_setback")
            # About nine percent of shallow-simulation players receive a temporary,
            # reproducible workload/recovery setback in a snapshot.
            if event < -0.82:
                intensity = _clamp((-event - 0.82) / 0.18, 0.0, 1.0)
                remaining = int(round(8 + intensity * 20))
                fitness = round(82 - intensity * 18, 1)
                return fitness, "Atlas simulation: temporary workload/recovery phase", {
                    "state": "simulated_setback", "label": "Simulierte Recovery-Phase", "simulated": True,
                    "recoveryDaysRemaining": remaining,
                }
        return 100.0, "no penalty without an observed limitation", {
            "state": "fit", "label": "Fit", "simulated": False, "recoveryDaysRemaining": None,
        }

    @staticmethod
    def _affected_areas(group: str, position: Any) -> list[str]:
        if group == "goalkeeper":
            return ["Reflexe", "Stellungsspiel", "Fangsicherheit"]
        if group == "defence":
            return ["Defending", "Physical", "Passing"] if not _is_wide(position) else ["Pace", "Crossing", "Stamina"]
        if group == "midfield":
            return ["Passing", "Ball control", "Reactions"] if not _is_wide(position) else ["Pace", "Dribbling", "Crossing"]
        return ["Finishing", "Positioning", "Pace"]

    def ensure_snapshot(self, snapshot_id: int) -> None:
        self.world.ensure_snapshot(snapshot_id)
        # Generate the previous snapshot first so smoothing is deterministic and does
        # not depend on which profile the user opened first.
        previous_id = None
        with self.database.connect() as probe:
            current = probe.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not current:
                raise ValueError("Snapshot not found.")
            current_count = probe.execute(
                "SELECT COUNT(*) FROM player_dynamic_states WHERE snapshot_id=? AND model_version=?",
                (snapshot_id, MODEL_ID),
            ).fetchone()[0]
            player_count = probe.execute("SELECT COUNT(*) FROM player_states WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
            if current_count == player_count and player_count > 0:
                return
            current_season = season_start_from_date(str(current["career_date"] or ""))
            candidates = probe.execute(
                "SELECT id,career_date FROM snapshots WHERE career_id=? AND import_sequence<? ORDER BY import_sequence DESC",
                (current["career_id"], current["import_sequence"]),
            ).fetchall()
            previous = next((row for row in candidates if season_start_from_date(str(row["career_date"] or "")) == current_season), None)
            previous_id = int(previous["id"]) if previous else None
        if previous_id is not None:
            self.ensure_snapshot(previous_id)

        with self.database.transaction() as conn:
            snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError("Snapshot not found.")
            existing = conn.execute(
                "SELECT COUNT(*) FROM player_dynamic_states WHERE snapshot_id=? AND model_version=?",
                (snapshot_id, MODEL_ID),
            ).fetchone()[0]
            player_count = conn.execute("SELECT COUNT(*) FROM player_states WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
            if existing == player_count and player_count > 0:
                return

            players = [dict(row) for row in conn.execute("SELECT * FROM player_states WHERE snapshot_id=?", (snapshot_id,)).fetchall()]
            rosters = {int(row["player_ea_id"]): dict(row) for row in conn.execute("SELECT * FROM roster_states WHERE snapshot_id=?", (snapshot_id,)).fetchall()}
            teams = {int(row["ea_team_id"]): dict(row) for row in conn.execute("SELECT * FROM team_states WHERE snapshot_id=?", (snapshot_id,)).fetchall()}
            table = {int(row["team_ea_id"]): dict(row) for row in conn.execute("SELECT * FROM team_league_states WHERE snapshot_id=?", (snapshot_id,)).fetchall()}
            world_table = {int(row["team_ea_id"]): dict(row) for row in conn.execute("SELECT * FROM atlas_league_simulations WHERE snapshot_id=?", (snapshot_id,)).fetchall()}
            observed_stats = self._aggregate_stats(conn, snapshot_id)
            squads: dict[int, list[dict[str, Any]]] = defaultdict(list)
            league_teams: dict[int, list[int]] = defaultdict(list)
            for team_id, team in teams.items():
                if team.get("league_ea_id") is not None:
                    league_teams[int(team["league_ea_id"])].append(team_id)
            for player in players:
                if player.get("team_ea_id") is not None:
                    squads[int(player["team_ea_id"])].append(player)
            ranks: dict[int, tuple[int, int]] = {}
            for squad in squads.values():
                ordered = sorted(squad, key=lambda item: (-(as_int(item.get("overall")) or 0), str(item.get("display_name") or "")))
                for index, item in enumerate(ordered, 1):
                    ranks[int(item["ea_player_id"])] = (index, len(ordered))

            previous_states: dict[int, dict[str, Any]] = {}
            previous_morale_scores: dict[int, float] = {}
            previous_rosters: dict[int, dict[str, Any]] = {}
            days_since_previous: int | None = None
            if previous_id is not None:
                previous_snapshot = conn.execute("SELECT career_date FROM snapshots WHERE id=?", (previous_id,)).fetchone()
                if previous_snapshot:
                    try:
                        days_since_previous = max(0, (date.fromisoformat(str(snapshot["career_date"])[:10]) - date.fromisoformat(str(previous_snapshot["career_date"])[:10])).days)
                    except ValueError:
                        days_since_previous = None
                previous_rosters = {
                    int(row["player_ea_id"]): dict(row)
                    for row in conn.execute("SELECT * FROM roster_states WHERE snapshot_id=?", (previous_id,)).fetchall()
                }
                for row in conn.execute(
                    "SELECT player_ea_id,dynamic_delta,breakdown_json FROM player_dynamic_states WHERE snapshot_id=? AND model_version=?",
                    (previous_id, MODEL_ID),
                ).fetchall():
                    try:
                        previous_breakdown = json.loads(row["breakdown_json"] or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        previous_breakdown = {}
                    previous_states[int(row["player_ea_id"])] = {
                        "delta": float(row["dynamic_delta"]),
                        "breakdown": previous_breakdown,
                    }
                previous_morale_scores = {}

            now = str(snapshot["imported_at"] or "")
            snapshot_key = str(snapshot["external_snapshot_id"] or snapshot_id)
            capabilities = development_capabilities(conn, int(snapshot["career_id"]))
            managed_team_id = as_int(snapshot["managed_team_ea_id"])
            scouting_confidence_boost = _clamp(
                ((float(capabilities.get("scouting", 50.0)) + float(capabilities.get("analysis", 50.0))) / 2.0 - 50.0) * 0.002,
                -0.04, 0.10,
            )
            tactical_roles = self._tactical_role_assignments(conn, int(snapshot["career_id"]))
            reconstructed = reconstruct_match_stats(conn, snapshot_id)
            managed_match_rows = self._managed_match_rows(conn, snapshot_id, reconstructed)
            detailed_evidence = self._detailed_match_evidence(
                conn, int(snapshot["career_id"]), int(snapshot["season_index"]),
            )
            live_team_overalls = {
                team_id: live_squad_strength(conn, snapshot_id, team_id)["average"]
                for team_id in teams
            }
            for player in players:
                player_id = int(player["ea_player_id"])
                team_id = as_int(player.get("team_ea_id"))
                team = teams.get(team_id) if team_id is not None else None
                league_id = as_int((team or {}).get("league_ea_id"))
                team_ids = league_teams.get(league_id, []) if league_id is not None else []
                live_team_overall = live_team_overalls.get(team_id) if team_id is not None else None
                team_strength = self._team_strength(team_id, live_team_overall, table, team_ids)
                rank, squad_size = ranks.get(player_id, (1, 1))
                player_raw = parse_raw(player.get("raw_json"))
                roster = rosters.get(player_id)
                roster_raw = parse_raw((roster or {}).get("raw_json"))
                raw = {**player_raw, **roster_raw}
                age = age_on_date(player_raw.get("birthdate_raw"), snapshot["career_date"])
                overall = as_int(player.get("overall")) or 0
                potential = as_int(player.get("potential")) or overall
                injury = as_int((roster or {}).get("injury")) or 0
                team_matches = self._team_matches(table, team_id, str(snapshot["career_date"]), len(team_ids))
                if team_id is not None and not (as_int((table.get(team_id) or {}).get("matches_played")) or 0):
                    team_matches = as_int((world_table.get(team_id) or {}).get("matches_played")) or team_matches
                stats = observed_stats.get(player_id)
                stats_are_private_proxy = False
                if stats and (stats.get("appearances") or stats.get("average_rating") is not None):
                    coverage = str(stats.get("coverage") or "observed")
                    performance_source = "observed" if coverage in {"observed", "hybrid"} else "simulated"
                    confidence = (0.82 if coverage == "hybrid" else 0.9) if stats.get("average_rating") is not None else (0.70 if coverage == "hybrid" else 0.76)
                else:
                    stats = self._simulate_stats(
                        snapshot_key=snapshot_key, player=player, team=team, team_matches=team_matches,
                        squad_rank=rank, squad_size=squad_size, team_strength=team_strength,
                        team_overall=live_team_overall,
                        age=age, injury=injury,
                    )
                    performance_source = "simulated"
                    stats["coverage"] = "simulated"
                    stats_are_private_proxy = True
                    confidence = 0.52 if team_id is not None and league_id is not None else 0.34
                confidence = _clamp(confidence + scouting_confidence_boost, 0.25, 0.98)
                minute_usage = (
                    self._managed_minute_usage(conn, snapshot_id, player_id)
                    if managed_team_id is not None and team_id == managed_team_id else None
                )
                usage = (
                    float(minute_usage["share"]) if minute_usage is not None else
                    _clamp(int(stats.get("appearances") or 0) / max(1, team_matches), 0.0, 1.0)
                )
                usage_basis = minute_usage or {
                    "basis": "appearance_share",
                    "appearanceMatches": int(stats.get("appearances") or 0),
                    "coveredMatches": team_matches,
                    "minutesPlayed": None,
                    "possibleMinutes": None,
                }
                expected_usage = self._expected_usage(rank, squad_size, age, max(0, potential - overall), injury)
                group = position_group(player.get("primary_position"))
                role_assignment = tactical_roles.get(player_id) or {}
                profile = performance_profile(player.get("primary_position"), role_assignment)
                season_score, season_detail = self._performance_score(stats, profile, team_strength)
                detailed = detailed_evidence.get(player_id)
                detailed_blend = 0.0
                detailed_score = None
                if detailed and detailed.get("averageRating") is not None:
                    sample = min(1.0, float(detailed["minutes"]) / 540.0, float(detailed["matches"]) / 8.0)
                    rating_component = (float(detailed["averageRating"]) - RATING_BASELINES[profile]) * 22.0
                    minutes = max(1.0, float(detailed["minutes"]))
                    creation_per90 = (float(detailed["npkXg"]) + float(detailed["xA"])) * 90.0 / minutes
                    creation_baseline = 0.08 if profile in {"goalkeeper", "centre_back"} else 0.16 if profile in {"fullback", "defensive_midfield"} else 0.34
                    creation_component = math.tanh((creation_per90 - creation_baseline) / .30) * (3.0 if profile in {"goalkeeper", "centre_back"} else 8.0)
                    detailed_score = _clamp(50 + rating_component + creation_component, 8, 96)
                    detailed_blend = min(.35, sample * .35)
                    season_score = season_score * (1.0 - detailed_blend) + detailed_score * detailed_blend
                    season_detail["detailedMatchEvidence"] = {
                        **detailed, "score": round(detailed_score, 1), "blendWeight": round(detailed_blend, 3),
                        "confidence": round(.35 + sample * .60, 3),
                        "class": "established" if sample >= .75 else "developing" if sample >= .33 else "small_sample",
                    }
                    confidence = _clamp(confidence + sample * .05, 0.25, 0.99)
                recent_matches = managed_match_rows.get(player_id, []) if managed_team_id is not None and team_id == managed_team_id else []
                recent_score, recent_detail = self._match_window_score(recent_matches[:5], profile)
                previous_window_score, previous_window_detail = self._match_window_score(recent_matches[5:10], profile)
                if recent_score is None:
                    current_form_score = season_score
                    current_form_source = "season_fallback"
                else:
                    # Fewer than four meaningful appearances are damped toward the
                    # season state. A single cameo cannot create an artificial spike.
                    recent_reliability = min(1.0, float(recent_detail["effectiveWeight"]) / 3.2)
                    current_form_score = recent_score * recent_reliability + season_score * (1.0 - recent_reliability)
                    current_form_source = "last_five_matches"
                if recent_score is not None and previous_window_score is not None and int(previous_window_detail["matches"]) >= 2:
                    momentum_score = _clamp((recent_score - previous_window_score) / 8.0, -5.0, 5.0)
                    momentum_source = "last_five_vs_previous_five"
                else:
                    momentum_score = 0.0
                    momentum_source = "insufficient_match_windows"
                form_score = _clamp(current_form_score, 5, 98)
                form_detail = {
                    **season_detail,
                    "seasonScore": round(season_score, 1),
                    "currentFormScore": round(form_score, 1),
                    "currentFormSource": current_form_source,
                    "recentWindow": recent_detail,
                    "previousWindow": previous_window_detail,
                    "previousWindowScore": round(previous_window_score, 1) if previous_window_score is not None else None,
                    "momentumScore": round(momentum_score, 2),
                    "momentumSource": momentum_source,
                    "roleAssignment": role_assignment,
                }
                morale_score, morale_source = self._morale_score(
                    raw=raw, roster=roster, usage=usage, expected_usage=expected_usage, team_strength=team_strength,
                )
                if morale_source != "beobachtet" and player_id in previous_morale_scores:
                    morale_score = _clamp(previous_morale_scores[player_id] * 0.72 + morale_score * 0.28, 8, 94)
                    morale_source = "latest Tracker morale state + current playing-time/form proxy"
                previous_state = previous_states.get(player_id) or {}
                fitness_score, fitness_source, availability = self._fitness_score(
                    raw=raw, roster=roster, previous_roster=previous_rosters.get(player_id),
                    previous_breakdown=previous_state.get("breakdown"), days_since_previous=days_since_previous,
                    snapshot_key=snapshot_key, player_id=player_id,
                    allow_simulated_setback=performance_source == "simulated",
                )

                gap = max(0, potential - overall)
                # Performance quality is age-neutral. Age and potential only translate
                # the same observed form into a more or less volatile temporary OVR.
                if age is not None and age <= 20:
                    volatility = 1.18 + min(gap, 12) * 0.012
                    positive_cap = min(7.5, 5.5 + gap * 0.18)
                    negative_cap = 6.5
                elif age is not None and age <= 23:
                    volatility = 1.10 + min(gap, 10) * 0.010
                    positive_cap = min(6.8, 5.2 + gap * 0.14)
                    negative_cap = 6.0
                elif age is not None and age <= 26:
                    volatility = 1.03 + min(gap, 8) * 0.008
                    positive_cap = min(6.2, 5.2 + gap * 0.10)
                    negative_cap = 5.8
                elif age is not None and age <= 30:
                    volatility = 0.96
                    positive_cap = 5.4
                    negative_cap = 5.4
                else:
                    volatility = 0.86
                    positive_cap = 4.6
                    negative_cap = 5.2
                composite_form_score = _clamp(form_score * .55 + season_score * .45, 5, 98)
                form_delta = (composite_form_score - 50.0) / 10.0 * volatility
                breakout_bonus = 0.0
                if season_score >= 78 and usage >= .35:
                    breakout_bonus = min(2.10, (season_score - 78) * .095) * (0.9 + min(gap, 10) * .015)
                slump_penalty = 0.0
                if season_score <= 35 and usage >= .18:
                    slump_penalty = min(1.8, (35 - season_score) * .07)
                simulated_momentum = 0.0
                if performance_source == "simulated":
                    momentum_noise = _noise(snapshot_key, player_id, "momentum_swing")
                    if momentum_noise < -0.42:
                        simulated_momentum = -((abs(momentum_noise) - 0.42) / 0.58) * (0.75 + volatility * 0.9)
                    elif momentum_noise > 0.74:
                        simulated_momentum = ((momentum_noise - 0.74) / 0.26) * (0.35 + volatility * 0.35)
                morale_delta = _clamp((morale_score - 50) / 30.0, -1.5, 1.5)
                fitness_delta_raw = -max(0.0, 100 - fitness_score) / 15.0
                managed_player = managed_team_id is not None and team_id == managed_team_id
                medical_reduction = 0.0
                performance_modifier = 1.0
                if managed_player:
                    medical_reduction = _clamp(max(0.0, float(capabilities.get("medical", 50.0)) - 50.0) * 0.006, 0.0, 0.30)
                    fitness_delta = fitness_delta_raw * (1.0 - medical_reduction)
                else:
                    fitness_delta = fitness_delta_raw
                trend_delta = momentum_score * .16
                target = form_delta + breakout_bonus - slump_penalty + trend_delta + morale_delta + fitness_delta + simulated_momentum
                if managed_player:
                    performance_delta = float(capabilities.get("performance", 50.0)) - 50.0
                    if target >= 0:
                        performance_modifier = _clamp(1.0 + performance_delta * 0.0025, 0.92, 1.13)
                    else:
                        performance_modifier = _clamp(1.0 - performance_delta * 0.0040, 0.78, 1.10)
                    target *= performance_modifier
                if performance_source == "simulated":
                    # Shallow simulation may create visible winners and losers, but its
                    # extremes remain below genuinely observed performance runs.
                    target *= 0.78
                    breakout_bonus *= 0.78
                protected_position = profile in {"goalkeeper", "centre_back", "fullback", "defensive_midfield"}
                if protected_position and availability.get("state") == "fit":
                    negative_cap = min(negative_cap, 4.2)
                target = _clamp(target, -negative_cap, positive_cap)
                previous = previous_state.get("delta")
                previous_weight = .42
                if performance_source == "observed" and int(stats.get("appearances") or 0) >= 8 and form_score >= 75:
                    previous_weight = .28
                initial_weight = .96 if performance_source == "observed" and int(stats.get("appearances") or 0) >= 8 else .84
                delta = target * initial_weight if previous is None else float(previous) * previous_weight + target * (1.0 - previous_weight)
                delta = round(_clamp(delta, -negative_cap, positive_cap), 1)
                dynamic_exact = round(overall + delta, 1)
                dynamic_display = int(round(dynamic_exact))
                breakdown = {
                    "form": {"score": round(form_score, 1), **form_detail},
                    "seasonPerformance": {"score": round(season_score, 1), **season_detail},
                    "momentum": {
                        "score": round(momentum_score, 2),
                        "source": momentum_source,
                        "impact": round(trend_delta, 2),
                        "label": "steigend" if momentum_score >= .5 else "fallend" if momentum_score <= -.5 else "stable/not yet reliable",
                    },
                    "morale": {"score": round(morale_score, 1), "source": morale_source},
                    "fitness": {"score": round(fitness_score, 1), "source": fitness_source, "penaltyOnly": True},
                    "availability": availability,
                    "targetDelta": round(target, 2),
                    "pillars": {
                        "form": round(form_delta + breakout_bonus - slump_penalty + trend_delta, 2),
                        "morale": round(morale_delta, 2),
                        "matchFitness": round(fitness_delta, 2),
                    },
                    "previousDelta": previous,
                    "volatilityFactor": round(volatility, 3),
                    "breakoutBonus": round(breakout_bonus, 3),
                    "slumpPenalty": round(slump_penalty, 3),
                    "simulatedMomentum": round(simulated_momentum, 3),
                    "clubDevelopment": {
                        "managedTeamPlayer": managed_player,
                        "performanceCapability": capabilities.get("performance", 50.0),
                        "medicalCapability": capabilities.get("medical", 50.0),
                        "performanceModifier": round(performance_modifier, 3),
                        "medicalPenaltyReduction": round(medical_reduction, 3),
                        "scoutingConfidenceBoost": round(scouting_confidence_boost, 3),
                    },
                    "positiveCap": round(positive_cap, 2),
                    "negativeCap": round(negative_cap, 2),
                    "teamStrength": round(team_strength, 3),
                    "teamMatches": team_matches,
                    "usage": round(usage, 3),
                    "usageBasis": usage_basis["basis"],
                    "minutesPlayed": usage_basis.get("minutesPlayed"),
                    "possibleMinutes": usage_basis.get("possibleMinutes"),
                    "coveredMatches": usage_basis.get("coveredMatches"),
                    "appearanceMatches": usage_basis.get("appearanceMatches"),
                    "expectedUsage": round(expected_usage, 3),
                    "squadRank": rank,
                    "squadSize": squad_size,
                    "affectedAreas": self._affected_areas(group, player.get("primary_position")),
                    "sourceNotice": (
                        "Observed competition data plus clearly labelled simulated league statistics."
                        if stats.get("coverage") == "hybrid" else
                        "Simulated values are an Atlas scouting signal and not observed match history."
                        if performance_source == "simulated" else "Season statistics from the snapshot."
                    ),
                }
                stored_stats = stats
                if stats_are_private_proxy:
                    # The dynamic model may need a deterministic performance proxy
                    # when no canonical season data exists (e.g. free agents or an
                    # incompletely exported edge case).  Those proxy numbers are not
                    # season history and must never appear as appearances/goals in UI.
                    stored_stats = {
                        "coverage": "simulated",
                        "estimatedOnly": True,
                        "appearances": None,
                        "goals": None,
                        "assists": None,
                        "clean_sheets": None,
                        "saves": None,
                        "goals_conceded": None,
                        "average_rating": None,
                    }
                conn.execute(
                    "INSERT INTO player_dynamic_states(career_id,snapshot_id,player_ea_id,base_overall,potential,dynamic_overall,dynamic_delta,form_score,morale_score,fitness_score,performance_source,confidence,stats_json,breakdown_json,model_version,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(snapshot_id,player_ea_id) DO UPDATE SET "
                    "base_overall=excluded.base_overall,potential=excluded.potential,dynamic_overall=excluded.dynamic_overall,dynamic_delta=excluded.dynamic_delta,form_score=excluded.form_score,morale_score=excluded.morale_score,fitness_score=excluded.fitness_score,performance_source=excluded.performance_source,confidence=excluded.confidence,stats_json=excluded.stats_json,breakdown_json=excluded.breakdown_json,model_version=excluded.model_version,updated_at=excluded.updated_at",
                    (snapshot["career_id"], snapshot_id, player_id, overall, potential, dynamic_exact, delta,
                     round(form_score, 2), round(morale_score, 2), round(fitness_score, 2), performance_source,
                     round(confidence, 3), json.dumps(stored_stats, ensure_ascii=False), json.dumps(breakdown, ensure_ascii=False),
                     MODEL_ID, now, now),
                )

    def analyze(self, snapshot_id: int, player_id: int) -> dict[str, Any]:
        self.ensure_snapshot(snapshot_id)
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT ds.*,p.display_name,p.primary_position,p.team_ea_id,p.team_name,t.league_ea_id,t.league_name "
                "FROM player_dynamic_states ds JOIN player_states p ON p.snapshot_id=ds.snapshot_id AND p.ea_player_id=ds.player_ea_id "
                "LEFT JOIN team_states t ON t.snapshot_id=p.snapshot_id AND t.ea_team_id=p.team_ea_id "
                "WHERE ds.snapshot_id=? AND ds.player_ea_id=?",
                (snapshot_id, player_id),
            ).fetchone()
            if not row:
                raise ValueError("Dynamic performance value could not be calculated.")
            item = dict(row)
        stats = json.loads(item.pop("stats_json") or "{}")
        breakdown = json.loads(item.pop("breakdown_json") or "{}")
        model_version = item.pop("model_version")
        base_overall = item.pop("base_overall")
        potential = item.pop("potential")
        dynamic_exact = item.pop("dynamic_overall")
        performance_source = item.pop("performance_source")
        coverage = str(stats.get("coverage") or performance_source)
        return {
            "modelId": model_version,
            "baseOverall": base_overall,
            "potential": potential,
            "dynamicOverallExact": dynamic_exact,
            "dynamicOverall": int(round(float(dynamic_exact))) if dynamic_exact is not None else None,
            "delta": item.pop("dynamic_delta"),
            "formScore": item.pop("form_score"),
            "seasonPerformanceScore": (breakdown.get("seasonPerformance") or {}).get("score"),
            "momentumScore": (breakdown.get("momentum") or {}).get("score"),
            "moraleScore": item.pop("morale_score"),
            "fitnessScore": item.pop("fitness_score"),
            "performanceSource": coverage,
            "performanceSourceLabel": (
                "Atlas profile model · not a season statistic" if stats.get("estimatedOnly") else
                "Snapshot + Atlas-Liga" if coverage == "hybrid" else
                "Snapshot-Statistiken" if coverage == "observed" else "Atlas simulation"
            ),
            "confidence": item.pop("confidence"),
            "stats": stats,
            "breakdown": breakdown,
            **{key: value for key, value in item.items() if key not in {"id", "career_id", "snapshot_id", "created_at", "updated_at"}},
        }

    def scouting_board(self, snapshot_id: int, *, source: str = "all", position: str = "all", sort: str = "delta_desc", query: str = "", limit: int = 300) -> dict[str, Any]:
        self.ensure_snapshot(snapshot_id)
        source = source if source in {"all", "observed", "hybrid", "simulated"} else "all"
        position = position if position in {"all", "goalkeeper", "defence", "midfield", "attack"} else "all"
        sort = sort if sort in {"delta_desc", "delta_asc", "dynamic_desc"} else "delta_desc"
        order_sql = {
            "delta_desc": "ds.dynamic_delta DESC,ds.dynamic_overall DESC,p.display_name",
            "delta_asc": "ds.dynamic_delta ASC,ds.dynamic_overall ASC,p.display_name",
            "dynamic_desc": "ds.dynamic_overall DESC,ds.dynamic_delta DESC,p.display_name",
        }[sort]
        query_key = str(query or "").strip().casefold()
        with self.database.connect() as conn:
            snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            rows = conn.execute(
                "SELECT ds.*,p.display_name,p.primary_position,p.team_ea_id,p.team_name,p.overall,p.potential,p.raw_json player_raw_json,t.league_ea_id,t.league_name "
                "FROM player_dynamic_states ds JOIN player_states p ON p.snapshot_id=ds.snapshot_id AND p.ea_player_id=ds.player_ea_id "
                "LEFT JOIN team_states t ON t.snapshot_id=p.snapshot_id AND t.ea_team_id=p.team_ea_id "
                f"WHERE ds.snapshot_id=? ORDER BY {order_sql}",
                (snapshot_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        counts = {"observed": 0, "hybrid": 0, "simulated": 0}
        for row in rows:
            item = dict(row)
            player_raw = parse_raw(item.pop("player_raw_json", None))
            stats = json.loads(item.pop("stats_json") or "{}")
            coverage = str(stats.get("coverage") or item["performance_source"])
            counts[coverage] = counts.get(coverage, 0) + 1
            group = position_group(item.get("primary_position"))
            if source != "all" and coverage != source:
                continue
            if position != "all" and group != position:
                continue
            if query_key and query_key not in f"{item.get('display_name','')} {item.get('team_name','')} {item.get('league_name','')}".casefold():
                continue
            breakdown = json.loads(item.pop("breakdown_json") or "{}")
            items.append({
                "playerEaId": item["player_ea_id"], "displayName": item["display_name"],
                "position": item["primary_position"], "positionGroup": group,
                "teamEaId": item["team_ea_id"], "teamName": item["team_name"],
                "leagueEaId": item["league_ea_id"], "leagueName": item["league_name"],
                "overall": item["overall"], "potential": item["potential"],
                "age": age_on_date(player_raw.get("birthdate_raw"), snapshot["career_date"] if snapshot else None),
                "dynamicOverall": int(round(float(item["dynamic_overall"]))),
                "dynamicOverallExact": item["dynamic_overall"], "delta": item["dynamic_delta"],
                "formScore": item["form_score"], "moraleScore": item["morale_score"], "fitnessScore": item["fitness_score"],
                "seasonPerformanceScore": (breakdown.get("seasonPerformance") or {}).get("score"),
                "momentumScore": (breakdown.get("momentum") or {}).get("score"),
                "momentumLabel": (breakdown.get("momentum") or {}).get("label"),
                "source": coverage,
                "sourceLabel": (
                    "Atlas-Profilmodell" if stats.get("estimatedOnly") else
                    "Snapshot + Atlas-Liga" if coverage == "hybrid" else
                    "Snapshot" if coverage == "observed" else "Atlas simulation"
                ),
                "confidence": item["confidence"], "stats": stats,
                "affectedAreas": breakdown.get("affectedAreas") or [],
                "availability": breakdown.get("availability") or {"state": "fit", "label": "Fit", "simulated": False},
                "slumpPenalty": breakdown.get("slumpPenalty") or 0,
                "simulatedMomentum": breakdown.get("simulatedMomentum") or 0,
            })
            if len(items) >= max(1, min(limit, 1000)):
                break
        return {
            "snapshot": dict(snapshot) if snapshot else None,
            "modelId": MODEL_ID,
            "items": items,
            "counts": counts,
            "filters": {"source": source, "position": position, "sort": sort, "query": query},
            "notice": "Season performance, current form and momentum trend are evaluated separately. Simulated values are used only for worldwide scouting and are not claimed as real match statistics.",
        }
