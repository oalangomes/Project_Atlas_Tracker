from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .finance_core import utc_now
from .competition_rules import league_rule_summary
from .media_utils import competition_name_key, season_start_from_date
from .positions import broad_position_group, is_wide_position
from .server_utils import age_on_date, as_int, parse_raw

MODEL_ID = "atlas-world-simulation-v6"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seed_value(*parts: Any) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _noise(seed: str, entity_id: int, channel: str) -> float:
    rng = random.Random(_seed_value(MODEL_ID, seed, entity_id, channel))
    return rng.uniform(-1.0, 1.0)


def _position_group(position: Any) -> str:
    return {"GK": "goalkeeper", "DEF": "defence", "MID": "midfield", "ATT": "attack"}[
        broad_position_group(position)
    ]


def _is_wide(position: Any) -> bool:
    return is_wide_position(position)


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


def _names_match(first: str | None, second: str | None) -> bool:
    a = competition_name_key(first)
    b = competition_name_key(second)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def _second_last_saturday_of_august(year: int) -> date:
    return _last_weekday(year, 8, 5) - timedelta(days=7)


def _league_calendar(season_year: int, team_count: int, career_date: str) -> dict[str, Any]:
    start = _second_last_saturday_of_august(season_year)
    end = _last_weekday(season_year + 1, 5, 5)
    current = date.fromisoformat(str(career_date)[:10])
    total_rounds = max(1, (team_count - 1) * 2)
    total_update_weeks = max(1, (end - start).days // 7)
    if current < start:
        update_index = 0
    elif current >= end:
        update_index = total_update_weeks
    else:
        most_recent_saturday = current - timedelta(days=(current.weekday() - 5) % 7)
        update_index = max(0, min(total_update_weeks, (most_recent_saturday - start).days // 7 + 1))
    completed_rounds = 0 if update_index <= 0 else min(total_rounds, int(math.ceil(update_index * total_rounds / total_update_weeks)))
    if current >= end:
        completed_rounds = total_rounds
    return {
        "seasonStart": start.isoformat(),
        "seasonEnd": end.isoformat(),
        "currentDate": current.isoformat(),
        "lastUpdateDate": None if update_index <= 0 else min(end, start + timedelta(days=(update_index - 1) * 7)).isoformat(),
        "completedRounds": completed_rounds,
        "totalRounds": total_rounds,
        "progress": round(completed_rounds / total_rounds, 4),
    }


def _round_robin(team_ids: list[int]) -> list[list[tuple[int, int]]]:
    teams: list[int | None] = list(team_ids)
    if len(teams) % 2:
        teams.append(None)
    size = len(teams)
    first_half: list[list[tuple[int, int]]] = []
    rotation = teams[:]
    for round_index in range(size - 1):
        pairs: list[tuple[int, int]] = []
        for index in range(size // 2):
            left, right = rotation[index], rotation[size - 1 - index]
            if left is None or right is None:
                continue
            # Alternate the fixed team's home advantage across rounds.
            if index == 0 and round_index % 2:
                left, right = right, left
            pairs.append((int(left), int(right)))
        first_half.append(pairs)
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return first_half + [[(away, home) for home, away in pairs] for pairs in first_half]


def _poisson(rng: random.Random, mean: float) -> int:
    threshold = math.exp(-max(0.01, mean))
    product = 1.0
    result = 0
    while product > threshold and result < 10:
        result += 1
        product *= rng.random()
    return max(0, result - 1)


class WorldSimulationService:
    """Procedural shallow domestic-league simulation for unsupported competitions.

    Deeper EA competitions remain authoritative and are never duplicated. Atlas
    advances only on Saturday update points from late August through late May and
    stores aggregate tables/player statistics without claiming individual fixtures.
    """

    def __init__(self, database, settings=None, media=None):
        self.database = database
        self.settings = settings
        self.media = media

    @staticmethod
    def _competition_catalog(conn: sqlite3.Connection, snapshot_id: int) -> list[dict[str, Any]]:
        rows = [dict(row) for row in conn.execute(
            """SELECT cs.competition_object_id,cs.static_competition_id,cs.competition_name,
                      (SELECT COUNT(*) FROM fixtures f JOIN fixture_observations fo ON fo.fixture_id=f.id
                       WHERE fo.snapshot_id=cs.snapshot_id AND f.competition_object_id=cs.competition_object_id) fixture_count,
                      (SELECT COUNT(*) FROM season_stat_states ss
                       WHERE ss.snapshot_id=cs.snapshot_id AND ss.competition_object_id=cs.competition_object_id) stat_count
               FROM competition_states cs WHERE cs.snapshot_id=?""",
            (snapshot_id,),
        ).fetchall()]
        by_id = {int(row["competition_object_id"]): row for row in rows}
        participant_sets: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
        fixture_team_sets: dict[int, set[int]] = defaultdict(set)
        stat_team_sets: dict[int, set[int]] = defaultdict(set)
        fixture_participants = conn.execute(
            """SELECT f.competition_object_id,ts.league_ea_id,ts.ea_team_id
               FROM fixtures f JOIN fixture_observations fo ON fo.fixture_id=f.id
               JOIN team_states ts ON ts.snapshot_id=fo.snapshot_id
                 AND ts.ea_team_id IN (f.home_team_ea_id,f.away_team_ea_id)
               WHERE fo.snapshot_id=? AND ts.league_ea_id IS NOT NULL""",
            (snapshot_id,),
        ).fetchall()
        stat_participants = conn.execute(
            """SELECT ss.competition_object_id,ts.league_ea_id,ts.ea_team_id
               FROM season_stat_states ss JOIN team_states ts
                 ON ts.snapshot_id=ss.snapshot_id AND ts.ea_team_id=ss.represented_team_ea_id
               WHERE ss.snapshot_id=? AND ts.league_ea_id IS NOT NULL""",
            (snapshot_id,),
        ).fetchall()
        for item in fixture_participants:
            competition_id = as_int(item["competition_object_id"])
            league_id = as_int(item["league_ea_id"])
            team_id = as_int(item["ea_team_id"])
            if competition_id is not None and league_id is not None and team_id is not None:
                participant_sets[competition_id][league_id].add(team_id)
                fixture_team_sets[competition_id].add(team_id)
        for item in stat_participants:
            competition_id = as_int(item["competition_object_id"])
            league_id = as_int(item["league_ea_id"])
            team_id = as_int(item["ea_team_id"])
            if competition_id is not None and league_id is not None and team_id is not None:
                participant_sets[competition_id][league_id].add(team_id)
                stat_team_sets[competition_id].add(team_id)
        for competition_id, leagues in participant_sets.items():
            if competition_id in by_id:
                by_id[competition_id]["participant_leagues"] = {
                    league_id: len(team_ids) for league_id, team_ids in leagues.items()
                }
                by_id[competition_id]["fixture_team_ids"] = set(fixture_team_sets.get(competition_id, set()))
                by_id[competition_id]["stat_team_ids"] = set(stat_team_sets.get(competition_id, set()))
        return rows

    @staticmethod
    def _matching_deeper_competition(
        league_id: int,
        league_name: str,
        competitions: list[dict[str, Any]],
        expected_team_ids: list[int] | set[int] | tuple[int, ...] = (),
    ) -> dict[str, Any] | None:
        """Return an actually covered domestic league competition.

        A cup containing clubs from a league is *not* proof that the league itself
        is covered by Deeper Simulation.  Older versions used participant makeup as
        a fallback and could therefore let DFB-Pokal/other cups suppress an entire
        domestic league.  v5 accepts only direct league identity matches and then
        verifies that the current snapshot covers most member clubs.
        """
        expected = {int(team_id) for team_id in expected_team_ids}
        if not expected:
            return None
        candidates: list[tuple[int, float, dict[str, Any]]] = []
        for row in competitions:
            if int(row.get("fixture_count") or 0) <= 0 and int(row.get("stat_count") or 0) <= 0:
                continue
            score = 0
            if as_int(row.get("static_competition_id")) == league_id:
                score = 100
            elif competition_name_key(row.get("competition_name")) == competition_name_key(league_name):
                score = 90
            elif _names_match(row.get("competition_name"), league_name):
                score = 70
            if not score:
                continue
            covered = (
                set(row.get("fixture_team_ids") or set())
                | set(row.get("stat_team_ids") or set())
            ) & expected
            coverage = len(covered) / max(1, len(expected))
            # A domestic competition must cover a clear majority of the actual
            # league membership before it is allowed to switch Atlas World off.
            # This also protects partially exported competitions.
            if coverage < 0.72:
                continue
            candidates.append((score, coverage, row))
        if not candidates:
            return None
        _, coverage, chosen = max(candidates, key=lambda item: (item[0], item[1]))
        chosen["deeper_team_coverage"] = round(coverage, 4)
        return chosen

    @staticmethod
    def _domestic_competition_id(league_id: int, league_name: str, competitions: list[dict[str, Any]]) -> int | None:
        matches: list[tuple[int, dict[str, Any]]] = []
        for row in competitions:
            score = 0
            if as_int(row.get("static_competition_id")) == league_id:
                score = 100
            elif competition_name_key(row.get("competition_name")) == competition_name_key(league_name):
                score = 90
            elif _names_match(row.get("competition_name"), league_name):
                score = 70
            if score:
                matches.append((score, row))
        if not matches:
            return None
        return as_int(max(matches, key=lambda item: item[0])[1].get("competition_object_id"))

    @staticmethod
    def _weighted_sample(rng: random.Random, items: list[dict[str, Any]], count: int, weight_fn) -> list[dict[str, Any]]:
        pool = list(items)
        selected: list[dict[str, Any]] = []
        for _ in range(min(max(0, count), len(pool))):
            weights = [max(0.0001, float(weight_fn(item))) for item in pool]
            total = sum(weights)
            pick = rng.random() * total
            cursor = 0.0
            chosen_index = len(pool) - 1
            for index, weight in enumerate(weights):
                cursor += weight
                if pick <= cursor:
                    chosen_index = index
                    break
            selected.append(pool.pop(chosen_index))
        return selected

    @staticmethod
    def _allocate_events(
        *, seed: str, channel: str, total: int, candidates: list[dict[str, Any]], weight_fn,
        caps: dict[int, int] | None = None,
    ) -> dict[int, int]:
        result = {int(player["ea_player_id"]): 0 for player in candidates}
        if total <= 0 or not candidates:
            return result
        rng = random.Random(_seed_value(MODEL_ID, seed, channel))
        for _ in range(int(total)):
            eligible = []
            weights = []
            for player in candidates:
                player_id = int(player["ea_player_id"])
                if caps is not None and result[player_id] >= max(0, int(caps.get(player_id, 0))):
                    continue
                eligible.append(player)
                weights.append(max(0.0001, float(weight_fn(player))))
            if not eligible:
                break
            pick = rng.random() * sum(weights)
            cursor = 0.0
            chosen = eligible[-1]
            for player, weight in zip(eligible, weights):
                cursor += weight
                if pick <= cursor:
                    chosen = player
                    break
            result[int(chosen["ea_player_id"])] += 1
        return result

    @staticmethod
    def _team_first_player_stats(
        *, seed: str, squad: list[dict[str, Any]], team_matches: int, team_goals_for: int | None,
        team_goals_against: int | None, team_strength: float, team_overall: float | None,
        ages: dict[int, int | None], injuries: dict[int, int], ranks: dict[int, tuple[int, int]],
        observed_rows: dict[int, dict[str, Any]] | None = None,
    ) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
        """Build one coherent team season line before exposing player statistics.

        For a fully Atlas-simulated player layer, every synthetic league match uses
        exactly eleven starters and no more than five substitutes.  This makes the
        aggregate appearance counts a consequence of legal matchday usage rather
        than independent per-player guesses.  Where FC already supplied player
        lines, those facts remain authoritative and Atlas fills only the remaining
        aggregate capacity.
        """
        observed_rows = observed_rows or {}
        matches = max(0, int(team_matches or 0))
        ordered = sorted(squad, key=lambda item: (-(as_int(item.get("overall")) or 0), int(item["ea_player_id"])))
        by_id = {int(player["ea_player_id"]): player for player in ordered}
        full_simulation = not observed_rows
        starts: dict[int, int] = defaultdict(int)
        sub_apps: dict[int, int] = defaultdict(int)
        appearances: dict[int, int] = defaultdict(int)
        max_players_used_in_match = 0
        max_subs_used_in_match = 0

        def usage(player: dict[str, Any]) -> float:
            player_id = int(player["ea_player_id"])
            rank, squad_size = ranks.get(player_id, (1, max(1, len(ordered))))
            overall = as_int(player.get("overall")) or 60
            potential = as_int(player.get("potential")) or overall
            return _expected_usage(
                rank, squad_size, ages.get(player_id), max(0, potential - overall), injuries.get(player_id, 0)
            )

        if full_simulation and matches > 0 and len(ordered) >= 11:
            goalkeepers = [player for player in ordered if _position_group(player.get("primary_position")) == "goalkeeper"]
            outfield = [player for player in ordered if _position_group(player.get("primary_position")) != "goalkeeper"]
            for match_index in range(matches):
                rng = random.Random(_seed_value(MODEL_ID, seed, "lineup", match_index))
                starters: list[dict[str, Any]] = []
                if goalkeepers:
                    starters.extend(WorldSimulationService._weighted_sample(
                        rng, goalkeepers, 1,
                        lambda player: (usage(player) ** 3.0) * (0.8 + (as_int(player.get("overall")) or 60) / 100),
                    ))
                # Keep every synthetic XI football-plausible without hard-coding a
                # formation: one goalkeeper plus minimum representation in defence,
                # midfield and attack, then fill the remaining places by selection
                # strength. This supports three-, four- and five-defender systems.
                required_groups = (("defence", 3), ("midfield", 2), ("attack", 1))
                for group_name, minimum in required_groups:
                    group_pool = [player for player in outfield if player not in starters and _position_group(player.get("primary_position")) == group_name]
                    starters.extend(WorldSimulationService._weighted_sample(
                        rng, group_pool, min(minimum, max(0, 11 - len(starters))),
                        lambda player: (usage(player) ** 3.0) * (0.78 + (as_int(player.get("overall")) or 60) / 95),
                    ))
                starter_pool = [player for player in outfield if player not in starters]
                starters.extend(WorldSimulationService._weighted_sample(
                    rng, starter_pool, 11 - len(starters),
                    lambda player: (usage(player) ** 3.0) * (0.78 + (as_int(player.get("overall")) or 60) / 95),
                ))
                if len(starters) < 11:
                    remaining = [player for player in ordered if player not in starters]
                    starters.extend(WorldSimulationService._weighted_sample(rng, remaining, 11 - len(starters), usage))
                remaining = [player for player in ordered if player not in starters]
                max_subs = min(5, len(remaining))
                if max_subs <= 3:
                    subs_to_use = max_subs
                else:
                    # FC allows five changes; most simulated matches use four or five,
                    # but never more than five distinct substitutes.
                    subs_to_use = min(max_subs, rng.choice((3, 4, 4, 5, 5)))
                substitutes = WorldSimulationService._weighted_sample(
                    rng, remaining, subs_to_use,
                    lambda player: (usage(player) ** 1.65) * (1.05 if 9 <= ranks.get(int(player["ea_player_id"]), (99, 99))[0] <= 18 else 0.8),
                )
                used_ids = set()
                for player in starters:
                    player_id = int(player["ea_player_id"])
                    starts[player_id] += 1
                    appearances[player_id] += 1
                    used_ids.add(player_id)
                for player in substitutes:
                    player_id = int(player["ea_player_id"])
                    if player_id in used_ids:
                        continue
                    sub_apps[player_id] += 1
                    appearances[player_id] += 1
                    used_ids.add(player_id)
                max_players_used_in_match = max(max_players_used_in_match, len(used_ids))
                max_subs_used_in_match = max(max_subs_used_in_match, max(0, len(used_ids) - len(starters)))
        else:
            # Partial observed coverage: FC rows cannot be decomposed back into starts
            # and substitute appearances.  Preserve them, then allocate only the
            # remaining legal aggregate appearance capacity to missing players.
            observed_total = sum(max(0, as_int(row.get("appearances")) or 0) for row in observed_rows.values())
            missing = [player for player in ordered if int(player["ea_player_id"]) not in observed_rows]
            max_capacity = max(0, matches * 16 - observed_total)
            minimum_capacity = max(0, matches * 11 - observed_total)
            desired_capacity = min(max_capacity, max(minimum_capacity, int(round(matches * 15.0 - observed_total))))
            caps = {int(player["ea_player_id"]): matches for player in missing}
            allocated = WorldSimulationService._allocate_events(
                seed=seed, channel="partial_apps", total=desired_capacity, candidates=missing,
                weight_fn=lambda player: usage(player) ** 1.9, caps=caps,
            )
            for player_id, count in allocated.items():
                appearances[player_id] = count
            max_players_used_in_match = 16 if desired_capacity else 0
            max_subs_used_in_match = 5 if desired_capacity else 0

        observed_goals = sum(max(0, as_int(row.get("goals")) or 0) for row in observed_rows.values())
        observed_assists = sum(max(0, as_int(row.get("assists")) or 0) for row in observed_rows.values())
        observed_conceded = sum(max(0, as_int(row.get("goals_conceded")) or 0) for row in observed_rows.values())
        synthetic = [player for player in ordered if int(player["ea_player_id"]) not in observed_rows]
        gf_budget = None if team_goals_for is None else max(0, int(team_goals_for) - observed_goals)
        ga_budget = None if team_goals_against is None else max(0, int(team_goals_against) - observed_conceded)

        def scoring_weight(player: dict[str, Any]) -> float:
            player_id = int(player["ea_player_id"])
            apps = max(0, appearances.get(player_id, 0))
            overall = as_int(player.get("overall")) or 60
            strength = _clamp((overall - 50) / 40, 0.15, 1.35)
            group = _position_group(player.get("primary_position"))
            rate = {"goalkeeper": 0.001, "defence": 0.045, "midfield": 0.19, "attack": 0.58}[group]
            if group == "defence" and _is_wide(player.get("primary_position")):
                rate *= 1.12
            return max(0.0001, apps * rate * strength)

        def assist_weight(player: dict[str, Any]) -> float:
            player_id = int(player["ea_player_id"])
            apps = max(0, appearances.get(player_id, 0))
            overall = as_int(player.get("overall")) or 60
            strength = _clamp((overall - 50) / 40, 0.15, 1.35)
            group = _position_group(player.get("primary_position"))
            rate = {"goalkeeper": 0.006, "defence": 0.09 if _is_wide(player.get("primary_position")) else 0.045,
                    "midfield": 0.30, "attack": 0.23}[group]
            return max(0.0001, apps * rate * strength)

        if gf_budget is None:
            expected_gf = max(0, int(round(matches * _clamp(0.85 + team_strength * 1.05, 0.55, 2.2))))
            gf_budget = max(0, expected_gf - observed_goals)
        scoring_candidates = [player for player in synthetic if appearances.get(int(player["ea_player_id"]), 0) > 0]
        goals = WorldSimulationService._allocate_events(
            seed=seed, channel="goals", total=gf_budget, candidates=scoring_candidates, weight_fn=scoring_weight,
        )
        total_team_goals = observed_goals + sum(goals.values())
        if team_goals_for is None:
            team_goals_for = total_team_goals
        assist_target = min(
            int(team_goals_for or 0),
            max(observed_assists, int(round(int(team_goals_for or 0) * _clamp(0.76 + _noise(seed, 0, "assist_rate") * 0.07, 0.62, 0.88)))),
        )
        assists = WorldSimulationService._allocate_events(
            seed=seed, channel="assists", total=max(0, assist_target - observed_assists),
            candidates=scoring_candidates, weight_fn=assist_weight,
        )

        goalkeepers = [player for player in scoring_candidates if _position_group(player.get("primary_position")) == "goalkeeper"]
        if ga_budget is None:
            expected_ga = max(0, int(round(matches * _clamp(1.72 - team_strength * 0.92, 0.55, 1.95))))
            ga_budget = max(0, expected_ga - observed_conceded)
            team_goals_against = observed_conceded + ga_budget
        conceded = WorldSimulationService._allocate_events(
            seed=seed, channel="goals_against", total=ga_budget, candidates=goalkeepers,
            weight_fn=lambda player: max(0.05, starts.get(int(player["ea_player_id"]), 0) * 1.5 + appearances.get(int(player["ea_player_id"]), 0)),
        )
        unattributed_ga = max(0, int(ga_budget) - sum(conceded.values()))

        team_clean_sheets = 0
        if matches > 0 and team_goals_against is not None:
            team_clean_sheets = int(round(matches * math.exp(-max(0.0, float(team_goals_against)) / matches)))
            team_clean_sheets = max(0, min(matches, team_clean_sheets))
        gk_cs_caps = {int(player["ea_player_id"]): max(0, appearances.get(int(player["ea_player_id"]), 0)) for player in goalkeepers}
        clean_sheet_by_gk = WorldSimulationService._allocate_events(
            seed=seed, channel="gk_clean_sheets", total=team_clean_sheets, candidates=goalkeepers,
            weight_fn=lambda player: max(0.05, starts.get(int(player["ea_player_id"]), 0) + appearances.get(int(player["ea_player_id"]), 0) * 0.2),
            caps=gk_cs_caps,
        )

        results: dict[int, dict[str, Any]] = {}
        for player in synthetic:
            player_id = int(player["ea_player_id"])
            apps = max(0, appearances.get(player_id, 0))
            overall = as_int(player.get("overall")) or 60
            relative = _clamp((overall - (team_overall if team_overall is not None else overall)) / 12, -1.0, 1.0)
            rating = _clamp(6.28 + team_strength * 0.48 + relative * 0.24 + _noise(seed, player_id, "rating") * 0.24, 5.9, 7.75)
            group = _position_group(player.get("primary_position"))
            if group == "goalkeeper":
                player_conceded = conceded.get(player_id, 0)
                saves = max(0, int(round(apps * _clamp(3.55 - team_strength * 1.05, 1.7, 4.5) + player_conceded * 0.22)))
                clean_sheets = clean_sheet_by_gk.get(player_id, 0)
            elif group == "defence":
                saves = player_conceded = 0
                clean_sheets = max(0, min(apps, int(round(apps * (team_clean_sheets / max(1, matches))))))
            else:
                saves = player_conceded = clean_sheets = 0
            results[player_id] = {
                "appearances": apps,
                "starts": max(0, starts.get(player_id, 0)),
                "sub_appearances": max(0, sub_apps.get(player_id, 0)),
                "average_rating": round(rating, 2),
                "goals": goals.get(player_id, 0),
                "assists": assists.get(player_id, 0),
                "yellow_cards": None,
                "red_cards": None,
                "saves": saves,
                "goals_conceded": player_conceded,
                "clean_sheets": clean_sheets,
            }

        integrity = {
            "mode": "per_match_lineups" if full_simulation else "observed_plus_aggregate_cap",
            "teamMatches": matches,
            "startersPerMatch": 11,
            "maxSubstitutesPerMatch": 5,
            "maxPlayersUsedPerMatch": 16,
            "observedPlayerRows": len(observed_rows),
            "simulatedPlayerRows": len(results),
            "appearanceTotalObserved": sum(max(0, as_int(row.get("appearances")) or 0) for row in observed_rows.values()),
            "appearanceTotalSimulated": sum(row["appearances"] for row in results.values()),
            "maxPlayersActuallyUsedInSyntheticMatch": max_players_used_in_match,
            "maxSubsActuallyUsedInSyntheticMatch": max_subs_used_in_match,
            "teamGoalsFor": team_goals_for,
            "observedGoals": observed_goals,
            "simulatedGoals": sum(row["goals"] for row in results.values()),
            "goalBudgetSatisfied": team_goals_for is None or observed_goals + sum(row["goals"] for row in results.values()) == int(team_goals_for),
            "teamGoalsAgainst": team_goals_against,
            "observedGoalsConceded": observed_conceded,
            "simulatedGoalsConceded": sum(row["goals_conceded"] for row in results.values()),
            "unattributedGoalsAgainst": unattributed_ga,
            "assistTarget": assist_target,
            "totalAssists": observed_assists + sum(row["assists"] for row in results.values()),
        }
        return results, integrity

    def ensure_snapshot(self, snapshot_id: int) -> None:
        with self.database.connect() as probe:
            run = probe.execute("SELECT model_version FROM atlas_world_simulation_runs WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if run and run["model_version"] == MODEL_ID:
                return

        with self.database.transaction() as conn:
            snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError("Snapshot not found.")
            run = conn.execute("SELECT model_version FROM atlas_world_simulation_runs WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if run and run["model_version"] == MODEL_ID:
                return

            conn.execute("DELETE FROM atlas_simulated_player_stats WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM atlas_league_simulations WHERE snapshot_id=?", (snapshot_id,))

            hidden = self.settings.hidden_ids(snapshot_id=snapshot_id) if self.settings and self.settings.hide_womens_football() else {"teams": set(), "players": set(), "leagues": set()}
            aliases = {int(row["ea_team_id"]): str(row["display_name"]) for row in conn.execute(
                "SELECT ea_team_id,display_name FROM team_name_overrides WHERE career_id=?", (snapshot["career_id"],)
            ).fetchall()}
            teams = {int(row["ea_team_id"]): dict(row) for row in conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=?", (snapshot_id,)
            ).fetchall() if int(row["ea_team_id"]) not in hidden.get("teams", set())}
            leagues = {int(row["ea_league_id"]): dict(row) for row in conn.execute(
                "SELECT * FROM league_states WHERE snapshot_id=?", (snapshot_id,)
            ).fetchall() if int(row["ea_league_id"]) not in hidden.get("leagues", set())}
            players = [dict(row) for row in conn.execute("SELECT * FROM player_states WHERE snapshot_id=?", (snapshot_id,)).fetchall()
                       if int(row["ea_player_id"]) not in hidden.get("players", set()) and as_int(row["team_ea_id"]) in teams]
            rosters = {int(row["player_ea_id"]): dict(row) for row in conn.execute(
                "SELECT * FROM roster_states WHERE snapshot_id=?", (snapshot_id,)
            ).fetchall()}
            competitions = self._competition_catalog(conn, snapshot_id)
            observed_stats = [dict(row) for row in conn.execute(
                "SELECT * FROM season_stat_states WHERE snapshot_id=?", (snapshot_id,)
            ).fetchall()]
            league_state_rows = [dict(row) for row in conn.execute(
                "SELECT * FROM team_league_states WHERE snapshot_id=?", (snapshot_id,)
            ).fetchall()]
            league_states_by_team = {
                int(row["team_ea_id"]): row for row in league_state_rows
                if as_int(row.get("team_ea_id")) is not None
            }

            league_teams: dict[int, list[int]] = defaultdict(list)
            squads: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for team_id, team in teams.items():
                league_id = as_int(team.get("league_ea_id"))
                if league_id is not None and league_id not in hidden.get("leagues", set()):
                    league_teams[league_id].append(team_id)
                    if league_id not in leagues:
                        leagues[league_id] = {
                            "ea_league_id": league_id,
                            "league_name": team.get("league_name") or f"Liga {league_id}",
                            "raw_json": "{}",
                        }
            for player in players:
                team_id = as_int(player.get("team_ea_id"))
                if team_id is not None:
                    squads[team_id].append(player)
            ranks: dict[int, tuple[int, int]] = {}
            for squad in squads.values():
                ordered = sorted(squad, key=lambda item: (-(as_int(item.get("overall")) or 0), str(item.get("display_name") or "")))
                for index, player in enumerate(ordered, 1):
                    ranks[int(player["ea_player_id"])] = (index, len(ordered))

            season_year = season_start_from_date(str(snapshot["career_date"] or "")) or date.fromisoformat(str(snapshot["career_date"])[:10]).year
            now = utc_now()
            table_rows: dict[tuple[int, int], dict[str, Any]] = {}
            simulated_league_ids: set[int] = set()
            live_team_overalls: dict[int, float] = {}

            for league_id, team_ids in sorted(league_teams.items()):
                if len(team_ids) < 2:
                    continue
                league = leagues.get(league_id) or {}
                league_name = str(league.get("league_name") or teams[team_ids[0]].get("league_name") or f"Liga {league_id}")
                deeper = self._matching_deeper_competition(league_id, league_name, competitions, team_ids)
                if deeper:
                    continue
                simulated_league_ids.add(league_id)
                team_ids = sorted(team_ids)
                calendar = _league_calendar(season_year, len(team_ids), str(snapshot["career_date"]))

                strengths: dict[int, float] = {}
                available_strengths = []
                for candidate_id in team_ids:
                    candidate_values = sorted(
                        (as_int(player.get("overall")) or 0 for player in squads.get(candidate_id, [])), reverse=True,
                    )
                    if candidate_values:
                        available_strengths.append(sum(candidate_values[:18]) / len(candidate_values[:18]))
                league_live_fallback = sum(available_strengths) / len(available_strengths) if available_strengths else 65.0
                for team_id in team_ids:
                    team = teams[team_id]
                    squad_ovr = sorted((as_int(player.get("overall")) or 0 for player in squads.get(team_id, [])), reverse=True)
                    squad_top = sum(squad_ovr[:18]) / len(squad_ovr[:18]) if squad_ovr else league_live_fallback
                    overall = squad_top
                    live_team_overalls[team_id] = squad_top
                    domestic = as_int(team.get("domestic_prestige")) or 3
                    international = as_int(team.get("international_prestige")) or 1
                    season_quality = _noise(f"{snapshot['career_id']}:{season_year}:{league_id}", team_id, "season_quality")
                    strengths[team_id] = _clamp(
                        ((overall - 55) / 35) * 0.63 + ((squad_top - 55) / 35) * 0.22
                        + ((domestic - 1) / 9) * 0.09 + ((international - 1) / 9) * 0.04
                        + season_quality * 0.06,
                        0.05, 1.20,
                    )

                # FC exports league-wide aggregate standings even for leagues that do
                # not have Deeper Simulation fixtures/player stats.  v0.23.10 consumes
                # the full leagueteamlinks table whenever AutoCapture v1.6.1+ supplied
                # it: W/D/L and GF/GA are FC facts, not Atlas estimates.
                aggregate_rows = {team_id: league_states_by_team.get(team_id) for team_id in team_ids}
                aggregate_complete = all(
                    row is not None
                    and as_int(row.get("current_table_position")) is not None
                    and as_int(row.get("matches_played")) is not None
                    for row in aggregate_rows.values()
                )
                positions = [as_int(row.get("current_table_position")) for row in aggregate_rows.values() if row is not None]
                aggregate_complete = aggregate_complete and len(set(positions)) == len(team_ids)

                if aggregate_complete:
                    aggregate_match_counts = [as_int((aggregate_rows[team_id] or {}).get("matches_played")) or 0 for team_id in team_ids]
                    aggregate_rounds = max(aggregate_match_counts) if aggregate_match_counts else 0
                    aggregate_calendar = {
                        **calendar,
                        "lastUpdateDate": str(snapshot["career_date"] or "")[:10],
                        "completedRounds": aggregate_rounds,
                        "progress": round(aggregate_rounds / max(1, int(calendar.get("totalRounds") or 1)), 4),
                    }
                    for team_id in sorted(team_ids, key=lambda candidate: as_int(aggregate_rows[candidate].get("current_table_position")) or 999):
                        row = aggregate_rows[team_id] or {}
                        position = as_int(row.get("current_table_position")) or 0
                        matches = as_int(row.get("matches_played")) or 0
                        points = as_int(row.get("points")) or 0
                        split_fields = {
                            "homeWins": as_int(row.get("home_wins")), "homeDraws": as_int(row.get("home_draws")),
                            "homeLosses": as_int(row.get("home_losses")), "awayWins": as_int(row.get("away_wins")),
                            "awayDraws": as_int(row.get("away_draws")), "awayLosses": as_int(row.get("away_losses")),
                            "homeGoalsFor": as_int(row.get("home_goals_for")), "homeGoalsAgainst": as_int(row.get("home_goals_against")),
                            "awayGoalsFor": as_int(row.get("away_goals_for")), "awayGoalsAgainst": as_int(row.get("away_goals_against")),
                        }
                        full_fc_table = all(value is not None for value in split_fields.values())
                        if full_fc_table:
                            wins = int(split_fields["homeWins"] or 0) + int(split_fields["awayWins"] or 0)
                            draws = int(split_fields["homeDraws"] or 0) + int(split_fields["awayDraws"] or 0)
                            losses = int(split_fields["homeLosses"] or 0) + int(split_fields["awayLosses"] or 0)
                            goals_for = int(split_fields["homeGoalsFor"] or 0) + int(split_fields["awayGoalsFor"] or 0)
                            goals_against = int(split_fields["homeGoalsAgainst"] or 0) + int(split_fields["awayGoalsAgainst"] or 0)
                            home_matches = int(split_fields["homeWins"] or 0) + int(split_fields["homeDraws"] or 0) + int(split_fields["homeLosses"] or 0)
                            away_matches = int(split_fields["awayWins"] or 0) + int(split_fields["awayDraws"] or 0) + int(split_fields["awayLosses"] or 0)
                            home_points = int(split_fields["homeWins"] or 0) * 3 + int(split_fields["homeDraws"] or 0)
                            away_points = int(split_fields["awayWins"] or 0) * 3 + int(split_fields["awayDraws"] or 0)
                        else:
                            wins = draws = losses = goals_for = goals_against = 0
                            home_matches = away_matches = home_points = away_points = 0
                        team_name = aliases.get(team_id) or str(teams[team_id].get("team_name") or f"Team {team_id}")
                        details = {
                            **aggregate_calendar,
                            "strength": round(strengths[team_id], 4),
                            "deeperCompetition": None,
                            "aggregateOnly": not full_fc_table,
                            "tableSource": "fc_team_league_aggregate",
                            "home": {
                                "matches": home_matches, "wins": split_fields["homeWins"], "draws": split_fields["homeDraws"],
                                "losses": split_fields["homeLosses"], "goalsFor": split_fields["homeGoalsFor"],
                                "goalsAgainst": split_fields["homeGoalsAgainst"], "points": home_points if full_fc_table else None,
                            },
                            "away": {
                                "matches": away_matches, "wins": split_fields["awayWins"], "draws": split_fields["awayDraws"],
                                "losses": split_fields["awayLosses"], "goalsFor": split_fields["awayGoalsFor"],
                                "goalsAgainst": split_fields["awayGoalsAgainst"], "points": away_points if full_fc_table else None,
                            },
                            "integrity": {
                                "reportedMatches": matches,
                                "wdlMatches": wins + draws + losses if full_fc_table else None,
                                "reportedPoints": points,
                                "pointsFromWdl": wins * 3 + draws if full_fc_table else None,
                                "matchesConsistent": (wins + draws + losses == matches) if full_fc_table else None,
                                "pointsConsistent": (wins * 3 + draws == points) if full_fc_table else None,
                            },
                            "modelNotice": (
                                "Complete FC26 league table from leagueteamlinks; Atlas simulates only player statistics that were not exported."
                                if full_fc_table else
                                "The FC26 league table contains position, points and matches; older snapshots do not contain exported W/D/L/GF/GA values."
                            ),
                        }
                        conn.execute(
                            """INSERT INTO atlas_league_simulations(
                                   snapshot_id,league_ea_id,league_name,team_ea_id,team_name,position,matches_played,
                                   wins,draws,losses,goals_for,goals_against,points,source,confidence,model_version,
                                   details_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'observed',?,?,?, ?,?)""",
                            (snapshot_id, league_id, league_name, team_id, team_name, position, matches,
                             wins, draws, losses, goals_for, goals_against, points, 0.995 if full_fc_table else 0.96, MODEL_ID,
                             json.dumps(details, ensure_ascii=False, sort_keys=True), now, now),
                        )
                        table_rows[(league_id, team_id)] = {
                            "league_name": league_name, "position": position, "matches_played": matches,
                            "wins": wins if full_fc_table else None, "draws": draws if full_fc_table else None,
                            "losses": losses if full_fc_table else None, "goals_for": goals_for if full_fc_table else None,
                            "goals_against": goals_against if full_fc_table else None,
                            "source": "fc_aggregate", "full_fc_table": full_fc_table, "strength": strengths[team_id],
                        }
                    continue

                # No complete FC aggregate is available: create one coherent shallow
                # league model.  This is the only place where Atlas invents the table.
                schedule = _round_robin(team_ids)
                completed_rounds = min(len(schedule), int(calendar["completedRounds"]))
                aggregates = {team_id: {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "points": 0,
                                        "home": {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "points": 0},
                                        "away": {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "points": 0}} for team_id in team_ids}
                for round_index, fixtures in enumerate(schedule[:completed_rounds]):
                    for home_id, away_id in fixtures:
                        home_strength, away_strength = strengths[home_id], strengths[away_id]
                        rng = random.Random(_seed_value(MODEL_ID, snapshot["career_id"], season_year, league_id, round_index, home_id, away_id))
                        home_goals = _poisson(rng, _clamp(1.28 + (home_strength - away_strength) * 1.45, 0.25, 3.45))
                        away_goals = _poisson(rng, _clamp(1.02 + (away_strength - home_strength) * 1.25, 0.18, 3.10))
                        home, away = aggregates[home_id], aggregates[away_id]
                        home["matches"] += 1; away["matches"] += 1
                        home["gf"] += home_goals; home["ga"] += away_goals
                        away["gf"] += away_goals; away["ga"] += home_goals
                        home["home"]["matches"] += 1; away["away"]["matches"] += 1
                        home["home"]["gf"] += home_goals; home["home"]["ga"] += away_goals
                        away["away"]["gf"] += away_goals; away["away"]["ga"] += home_goals
                        if home_goals > away_goals:
                            home["wins"] += 1; home["points"] += 3; away["losses"] += 1
                            home["home"]["wins"] += 1; home["home"]["points"] += 3; away["away"]["losses"] += 1
                        elif away_goals > home_goals:
                            away["wins"] += 1; away["points"] += 3; home["losses"] += 1
                            away["away"]["wins"] += 1; away["away"]["points"] += 3; home["home"]["losses"] += 1
                        else:
                            home["draws"] += 1; away["draws"] += 1; home["points"] += 1; away["points"] += 1
                            home["home"]["draws"] += 1; away["away"]["draws"] += 1
                            home["home"]["points"] += 1; away["away"]["points"] += 1

                ordered = sorted(team_ids, key=lambda team_id: (
                    -aggregates[team_id]["points"],
                    -(aggregates[team_id]["gf"] - aggregates[team_id]["ga"]),
                    -aggregates[team_id]["gf"],
                    aliases.get(team_id, str(teams[team_id].get("team_name") or "")).casefold(),
                ))
                for position, team_id in enumerate(ordered, 1):
                    agg = aggregates[team_id]
                    team_name = aliases.get(team_id) or str(teams[team_id].get("team_name") or f"Team {team_id}")
                    details = {
                        **calendar,
                        "strength": round(strengths[team_id], 4),
                        "deeperCompetition": None,
                        "aggregateOnly": False,
                        "tableSource": "atlas_procedural",
                        "home": {
                            "matches": agg["home"]["matches"], "wins": agg["home"]["wins"], "draws": agg["home"]["draws"],
                            "losses": agg["home"]["losses"], "goalsFor": agg["home"]["gf"],
                            "goalsAgainst": agg["home"]["ga"], "points": agg["home"]["points"],
                        },
                        "away": {
                            "matches": agg["away"]["matches"], "wins": agg["away"]["wins"], "draws": agg["away"]["draws"],
                            "losses": agg["away"]["losses"], "goalsFor": agg["away"]["gf"],
                            "goalsAgainst": agg["away"]["ga"], "points": agg["away"]["points"],
                        },
                        "modelNotice": "Procedural Atlas league table; not claimed as EA match-by-match history.",
                    }
                    conn.execute(
                        """INSERT INTO atlas_league_simulations(
                               snapshot_id,league_ea_id,league_name,team_ea_id,team_name,position,matches_played,
                               wins,draws,losses,goals_for,goals_against,points,source,confidence,model_version,
                               details_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'simulated',?,?,?, ?,?)""",
                        (snapshot_id, league_id, league_name, team_id, team_name, position, agg["matches"], agg["wins"], agg["draws"],
                         agg["losses"], agg["gf"], agg["ga"], agg["points"], 0.64, MODEL_ID,
                         json.dumps(details, ensure_ascii=False, sort_keys=True), now, now),
                    )
                    table_rows[(league_id, team_id)] = {
                        "league_name": league_name, "position": position, "matches_played": agg["matches"],
                        "wins": agg["wins"], "draws": agg["draws"], "losses": agg["losses"],
                        "goals_for": agg["gf"], "goals_against": agg["ga"],
                        "source": "simulated", "full_fc_table": False, "strength": strengths[team_id],
                    }

            observed_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in observed_stats:
                observed_by_player[int(row["player_ea_id"])].append(row)
            simulated_player_rows = 0
            for league_id in sorted(simulated_league_ids):
                for team_id in sorted(league_teams.get(league_id, [])):
                    team = teams.get(team_id)
                    league_row = table_rows.get((league_id, team_id))
                    if team is None or not league_row:
                        continue
                    league_name = str(league_row["league_name"])
                    competition_id = self._domestic_competition_id(league_id, league_name, competitions)
                    team_squad = list(squads.get(team_id, []))
                    observed_team_rows: dict[int, dict[str, Any]] = {}
                    for player in team_squad:
                        player_id = int(player["ea_player_id"])
                        for row in observed_by_player.get(player_id, []):
                            if (
                                (competition_id is not None and as_int(row.get("competition_object_id")) == competition_id)
                                or _names_match(row.get("competition_name"), league_name)
                            ):
                                observed_team_rows[player_id] = row
                                break
                    ages = {
                        int(player["ea_player_id"]): age_on_date(
                            parse_raw(player.get("raw_json")).get("birthdate_raw"), snapshot["career_date"]
                        )
                        for player in team_squad
                    }
                    injuries = {
                        int(player["ea_player_id"]): as_int((rosters.get(int(player["ea_player_id"])) or {}).get("injury")) or 0
                        for player in team_squad
                    }
                    stats_by_player, team_integrity = self._team_first_player_stats(
                        seed=f"{snapshot['career_id']}:{season_year}:{league_id}:{team_id}",
                        squad=team_squad,
                        team_matches=int(league_row["matches_played"]),
                        team_goals_for=as_int(league_row.get("goals_for")),
                        team_goals_against=as_int(league_row.get("goals_against")),
                        team_strength=float(league_row["strength"]),
                        team_overall=live_team_overalls.get(team_id),
                        ages=ages, injuries=injuries, ranks=ranks,
                        observed_rows=observed_team_rows,
                    )
                    for player in team_squad:
                        player_id = int(player["ea_player_id"])
                        stats = stats_by_player.get(player_id)
                        if stats is None:
                            continue
                        rank, squad_size = ranks.get(player_id, (1, 1))
                        details = {
                            "source": "atlas_simulation",
                            "leaguePosition": league_row["position"],
                            "squadRank": rank,
                            "squadSize": squad_size,
                            "simulatedStarts": stats.get("starts", 0),
                            "simulatedSubAppearances": stats.get("sub_appearances", 0),
                            "teamIntegrity": team_integrity,
                            "modelNotice": (
                                "Player statistics come from a team-level Atlas simulation. FC26 table values are fixed budgets; "
                                "synthetic appearances use 11 starters and at most five substitutes per modelled league match."
                            ),
                        }
                        conn.execute(
                            """INSERT INTO atlas_simulated_player_stats(
                                   snapshot_id,player_ea_id,team_ea_id,league_ea_id,competition_object_id,competition_name,
                                   appearances,average_rating,goals,assists,yellow_cards,red_cards,saves,goals_conceded,
                                   clean_sheets,confidence,model_version,details_json,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (snapshot_id, player_id, team_id, league_id, competition_id, league_name, stats["appearances"],
                             stats["average_rating"], stats["goals"], stats["assists"], stats["yellow_cards"], stats["red_cards"],
                             stats["saves"], stats["goals_conceded"], stats["clean_sheets"],
                             0.76 if league_row.get("goals_for") is not None else 0.64, MODEL_ID,
                             json.dumps(details, ensure_ascii=False, sort_keys=True), now, now),
                        )
                        simulated_player_rows += 1

            league_row_count = int(conn.execute("SELECT COUNT(*) FROM atlas_league_simulations WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0])
            conn.execute(
                """INSERT INTO atlas_world_simulation_runs(snapshot_id,model_version,league_row_count,player_row_count,created_at,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO UPDATE SET model_version=excluded.model_version,
                   league_row_count=excluded.league_row_count,player_row_count=excluded.player_row_count,updated_at=excluded.updated_at""",
                (snapshot_id, MODEL_ID, league_row_count, simulated_player_rows, now, now),
            )

    def simulated_leagues(self, snapshot_id: int) -> list[dict[str, Any]]:
        self.ensure_snapshot(snapshot_id)
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT league_ea_id,league_name,COUNT(*) team_count,MAX(matches_played) matches_played,
                          MIN(source) table_source,MIN(details_json) details_json
                   FROM atlas_league_simulations WHERE snapshot_id=?
                   GROUP BY league_ea_id,league_name ORDER BY league_name""",
                (snapshot_id,),
            ).fetchall()
            qualification_rules = {int(row["league_ea_id"]): league_rule_summary(conn, snapshot_id, int(row["league_ea_id"])) for row in rows}
        result = []
        for row in rows:
            details = json.loads(row["details_json"] or "{}")
            league_id = int(row["league_ea_id"])
            league_name = str(row["league_name"] or f"Liga {league_id}")
            is_fc_table = str(row["table_source"] or "") == "observed"
            result.append({
                "leagueEaId": league_id, "leagueName": league_name,
                "teamCount": int(row["team_count"]), "matchesPlayed": int(row["matches_played"]),
                "completedRounds": int(details.get("completedRounds") or 0), "totalRounds": int(details.get("totalRounds") or 0),
                "seasonStart": details.get("seasonStart"), "seasonEnd": details.get("seasonEnd"),
                "lastUpdateDate": details.get("lastUpdateDate"), "progress": details.get("progress"), "modelId": MODEL_ID,
                "tableSource": "fc_aggregate" if is_fc_table else "atlas_simulation",
                "tableSourceLabel": "Atlas simulation · FC26-Tabelle" if is_fc_table else "Atlas simulation",
                "identity": self.media.league_identity(league_id, league_name=league_name) if self.media is not None else None,
                "qualificationRules": qualification_rules.get(league_id),
            })
        return result

    def league_table(self, snapshot_id: int, league_id: int) -> dict[str, Any]:
        self.ensure_snapshot(snapshot_id)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM atlas_league_simulations WHERE snapshot_id=? AND league_ea_id=? ORDER BY position",
                (snapshot_id, league_id),
            ).fetchall()
            snapshot = conn.execute("SELECT career_id FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            aliases = {
                int(row["ea_team_id"]): str(row["display_name"])
                for row in conn.execute(
                    "SELECT ea_team_id,display_name FROM team_name_overrides WHERE career_id=?",
                    (int(snapshot["career_id"]),),
                ).fetchall()
            } if snapshot else {}
            qualification_rules = league_rule_summary(conn, snapshot_id, league_id)

            # Atlas-World leagues use exactly the same canonical season-stat layer as
            # player/club profiles. FC-provided rows remain authoritative; Atlas only
            # contributes the synthetic rows that fill otherwise invisible league
            # player statistics. This keeps league leaderboards consistent with every
            # other page instead of inventing a second set of scorers here.
            synthetic_rows = [dict(row) for row in conn.execute(
                """SELECT aps.player_ea_id,aps.team_ea_id represented_team_ea_id,
                          COALESCE(ts.team_name,p.team_name) represented_team_name,
                          p.display_name,aps.appearances,aps.goals,aps.assists,aps.average_rating,
                          aps.competition_object_id,aps.competition_name
                   FROM atlas_simulated_player_stats aps
                   JOIN player_states p ON p.snapshot_id=aps.snapshot_id AND p.ea_player_id=aps.player_ea_id
                   LEFT JOIN team_states ts ON ts.snapshot_id=aps.snapshot_id AND ts.ea_team_id=aps.team_ea_id
                   WHERE aps.snapshot_id=? AND aps.league_ea_id=?""",
                (snapshot_id, league_id),
            ).fetchall()]
            competition_ids = {
                int(row["competition_object_id"]) for row in synthetic_rows
                if as_int(row.get("competition_object_id")) is not None
            }
            observed_candidates = [dict(row) for row in conn.execute(
                """SELECT ss.player_ea_id,COALESCE(ss.represented_team_ea_id,p.team_ea_id) represented_team_ea_id,
                          COALESCE(ss.represented_team_name,ts.team_name,p.team_name) represented_team_name,
                          COALESCE(ss.display_name,p.display_name) display_name,ss.appearances,ss.goals,ss.assists,
                          ss.average_rating,ss.competition_object_id,ss.competition_name
                   FROM season_stat_states ss
                   JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id
                   LEFT JOIN team_states ts ON ts.snapshot_id=ss.snapshot_id
                        AND ts.ea_team_id=COALESCE(ss.represented_team_ea_id,p.team_ea_id)
                   WHERE ss.snapshot_id=?""",
                (snapshot_id,),
            ).fetchall()]
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            alias = aliases.get(int(item["team_ea_id"]))
            if alias:
                item["team_name_original"] = item.get("team_name")
                item["team_name"] = alias
            item["details"] = json.loads(item.pop("details_json") or "{}")
            aggregate_only = bool(item["details"].get("aggregateOnly"))
            item["goal_difference"] = None if aggregate_only else int(item["goals_for"]) - int(item["goals_against"])
            item["source_label"] = "FC26-Tabelle" if str(item.get("source")) == "observed" else "Atlas simulation"
            item["aggregate_only"] = aggregate_only
            item["identity"] = self.media.team_brief(int(item["team_ea_id"])) if self.media is not None else None
            position = as_int(item.get("position"))
            rule_positions = ((qualification_rules or {}).get("positions") or {}) if qualification_rules and qualification_rules.get("available") else {}
            zone_outcomes = [key for key, values in rule_positions.items() if isinstance(values, list) and position is not None and position in {as_int(value) for value in values}]
            item["qualification"] = {
                "zoneOutcomes": zone_outcomes,
                "confirmedOutcomes": zone_outcomes if bool((qualification_rules or {}).get("final")) else [],
                "final": bool((qualification_rules or {}).get("final")),
                "ruleId": (qualification_rules or {}).get("ruleId"),
                "rulesetVersion": (qualification_rules or {}).get("rulesetVersion"),
            }
            items.append(item)

        def split_table(key: str) -> list[dict[str, Any]]:
            split_rows: list[dict[str, Any]] = []
            for item in items:
                split = (item.get("details") or {}).get(key) or {}
                if any(split.get(field) is None for field in ("matches", "wins", "draws", "losses", "goalsFor", "goalsAgainst", "points")):
                    continue
                split_rows.append({
                    "team_ea_id": item["team_ea_id"], "team_name": item["team_name"], "identity": item.get("identity"),
                    "matches_played": int(split.get("matches") or 0), "wins": int(split.get("wins") or 0),
                    "draws": int(split.get("draws") or 0), "losses": int(split.get("losses") or 0),
                    "goals_for": int(split.get("goalsFor") or 0), "goals_against": int(split.get("goalsAgainst") or 0),
                    "points": int(split.get("points") or 0),
                })
            split_rows.sort(key=lambda row: (
                -row["points"], -(row["goals_for"] - row["goals_against"]), -row["goals_for"], str(row["team_name"]).casefold()
            ))
            for position, row in enumerate(split_rows, 1):
                row["position"] = position
                row["goal_difference"] = row["goals_for"] - row["goals_against"]
            return split_rows

        details = items[0].get("details", {}) if items else {}
        league_name = str(items[0]["league_name"] if items else f"Liga {league_id}")

        observed_rows = [
            row for row in observed_candidates
            if (as_int(row.get("competition_object_id")) in competition_ids if competition_ids else False)
            or _names_match(row.get("competition_name"), league_name)
        ]
        stats_by_player: dict[int, dict[str, Any]] = {}
        # Imported/Deeper rows win if partial FC coverage exists inside an otherwise
        # Atlas-World league. Synthetic rows fill only players without that FC row.
        for row in observed_rows + synthetic_rows:
            player_id = int(row["player_ea_id"])
            if player_id in stats_by_player:
                continue
            team_id = as_int(row.get("represented_team_ea_id"))
            if team_id is not None and team_id in aliases:
                row["represented_team_name"] = aliases[team_id]
            row["media"] = self.media.player_media(player_id) if self.media is not None else None
            stats_by_player[player_id] = row
        player_stats = list(stats_by_player.values())
        top_scorers = sorted(
            player_stats,
            key=lambda row: (-(as_int(row.get("goals")) or 0), -(as_int(row.get("assists")) or 0), str(row.get("display_name") or "")),
        )[:5]
        top_assists = sorted(
            player_stats,
            key=lambda row: (-(as_int(row.get("assists")) or 0), -(as_int(row.get("goals")) or 0), str(row.get("display_name") or "")),
        )[:5]
        max_appearances = max((as_int(row.get("appearances")) or 0 for row in player_stats), default=0)
        rating_minimum = max(3, round(max_appearances * 0.25)) if max_appearances else 3
        rating_pool = [
            row for row in player_stats
            if (as_int(row.get("appearances")) or 0) >= rating_minimum
            and float(row.get("average_rating") or 0) > 0
        ]
        top_ratings = sorted(
            rating_pool,
            key=lambda row: (-float(row.get("average_rating") or 0), -(as_int(row.get("appearances")) or 0), str(row.get("display_name") or "")),
        )[:5]

        fc_table = bool(items) and all(str(item.get("source")) == "observed" for item in items)
        full_fc_table = fc_table and not any(bool(item.get("aggregate_only")) for item in items)
        if fc_table and full_fc_table:
            notice = (
                "Overall, home and away tables come from FC26 leagueteamlinks. Atlas simulates only unexported "
                "player season statistics for this league and anchors goals and appearances to those team values."
            )
        elif fc_table:
            notice = (
                "This older snapshot contains only position, points and matches from FC26. AutoCapture v1.6.1 or newer "
                "is required for complete W/D/L/GF/GA and home/away data."
            )
        else:
            notice = "Atlas updates this table on Saturdays between late August and late May. No individual matches are claimed."
        return {
            "snapshotId": snapshot_id, "leagueEaId": league_id,
            "leagueName": league_name, "items": items, "modelId": MODEL_ID,
            "homeItems": split_table("home"), "awayItems": split_table("away"),
            "tableSource": "fc_aggregate" if fc_table else "atlas_simulation",
            "identity": self.media.league_identity(league_id, league_name=league_name) if self.media is not None else None,
            "calendar": {key: details.get(key) for key in ("seasonStart", "seasonEnd", "lastUpdateDate", "completedRounds", "totalRounds", "progress")},
            "topScorers": top_scorers,
            "topAssists": top_assists,
            "topRatings": top_ratings,
            "ratingMinimumAppearances": rating_minimum,
            "qualificationRules": qualification_rules,
            "notice": notice,
        }

    def simulated_player_stats(self, snapshot_id: int, *, player_id: int | None = None, team_id: int | None = None) -> list[dict[str, Any]]:
        self.ensure_snapshot(snapshot_id)
        where = ["snapshot_id=?"]
        params: list[Any] = [snapshot_id]
        if player_id is not None:
            where.append("player_ea_id=?"); params.append(player_id)
        if team_id is not None:
            where.append("team_ea_id=?"); params.append(team_id)
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM atlas_simulated_player_stats WHERE " + " AND ".join(where) + " ORDER BY competition_name,player_ea_id",
                params,
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item.update({
                "represented_team_ea_id": item["team_ea_id"], "current_club_ea_id": item["team_ea_id"],
                "source": "atlas_simulation", "source_label": "Atlas simulation", "amount_status": "estimated",
            })
            item["details"] = json.loads(item.pop("details_json") or "{}")
            result.append(item)
        return result
