from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, parse_fc_date,
    parse_raw, rows_to_dicts, subtract_months, youth_potential_range,
)

class CompetitionQueryMixin:
    def _competition_format(
        self,
        snapshot_id: int,
        competition_id: int,
        name: str,
        static_competition_id: int | None,
        fixtures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Runtime/static competition IDs can drift after title updates. Resolve the
        # competition through the guarded media crosswalk first; only use broader
        # league-name/participant evidence when that cannot establish a league.
        name_key = competition_name_key(name)
        identity = self.state.media.competition_identity(
            competition_id, snapshot_id=snapshot_id, competition_name=name
        )
        identity_id = as_int(identity.get("mediaCompetitionId"))
        resolved_static_id = identity_id
        static_is_league = False
        with self.state.database.connect() as conn:
            league_rows = conn.execute(
                "SELECT ea_league_id,league_name FROM reference_leagues ORDER BY ea_league_id"
            ).fetchall()
            if identity_id is not None:
                static_is_league = bool(conn.execute(
                    "SELECT 1 FROM reference_leagues WHERE ea_league_id=? LIMIT 1",
                    (identity_id,),
                ).fetchone())

        if not static_is_league:
            exact_leagues = [
                row for row in league_rows
                if name_key and competition_name_key(row["league_name"]) == name_key
            ]
            if len(exact_leagues) == 1:
                resolved_static_id = int(exact_leagues[0]["ea_league_id"])
                static_is_league = True

        # Keep a snapshot static ID only when no safer identity could be derived.
        # This preserves unknown competitions without letting a contradictory stale
        # ID override an established name/crosswalk mapping.
        if resolved_static_id is None and static_competition_id is not None:
            resolved_static_id = static_competition_id
            with self.state.database.connect() as conn:
                static_is_league = bool(conn.execute(
                    "SELECT 1 FROM reference_leagues WHERE ea_league_id=? LIMIT 1",
                    (static_competition_id,),
                ).fetchone())

        # Last-resort league evidence for renamed/localized leagues: if most
        # fixture participants belong to one league, treat the competition as
        # that league rather than defaulting to knockout.
        if not static_is_league:
            inferred = self.state.media._participant_league_id(snapshot_id, competition_id)
            if inferred:
                inferred_id, share = inferred
                inferred_row = next((row for row in league_rows if int(row["ea_league_id"]) == inferred_id), None)
                inferred_key = competition_name_key(inferred_row["league_name"]) if inferred_row else ""
                league_words = ("league", "liga", "bundesliga", "ligue", "serie", "eredivisie", "premiership", "division", "championship", "superliga")
                looks_like_league = any(word in name_key for word in league_words)
                names_overlap = bool(name_key and inferred_key and (name_key in inferred_key or inferred_key in name_key))
                if share >= 0.72 and (looks_like_league or names_overlap):
                    resolved_static_id = inferred_id
                    static_is_league = True
        if fixtures is None:
            with self.state.database.connect() as conn:
                fixture_rows = self._fixture_rows(conn, snapshot_id, competition_id=competition_id)
        else:
            fixture_rows = fixtures
        info = competition_format_info(
            fixture_rows,
            name=name,
            static_is_league=static_is_league,
        )
        info["staticCompetitionId"] = resolved_static_id
        return info

    def _competitions(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            rows = conn.execute(
                """SELECT c.competition_object_id,c.static_competition_id,c.competition_name,c.raw_json,
                          COUNT(fo.fixture_id) fixture_count,
                          SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed,
                          SUM(CASE WHEN fo.managed_team_involved=1 THEN 1 ELSE 0 END) managed_matches,
                          COUNT(DISTINCT f.home_team_ea_id)+COUNT(DISTINCT f.away_team_ea_id) participant_refs,
                          (SELECT COUNT(*) FROM season_stat_states ss
                           WHERE ss.snapshot_id=c.snapshot_id AND ss.competition_object_id=c.competition_object_id) stat_count
                   FROM competition_states c
                   LEFT JOIN fixtures f ON f.career_id=? AND f.competition_object_id=c.competition_object_id
                   LEFT JOIN fixture_observations fo ON fo.snapshot_id=c.snapshot_id AND fo.fixture_id=f.id
                   WHERE c.snapshot_id=?
                   GROUP BY c.competition_object_id,c.competition_name,c.raw_json
                   ORDER BY managed_matches DESC,fixture_count DESC,c.competition_name""",
                (snap["career_id"], snapshot_id),
            ).fetchall()
        result = []
        for row in rows:
            # A competition state alone is not deeper simulation. Historical or
            # placeholder states without current fixtures and season statistics are
            # omitted so the same domestic league can live only in Atlas World.
            if int(row["fixture_count"] or 0) <= 0 and int(row["stat_count"] or 0) <= 0:
                continue
            item = clean_raw(row) or {}
            sources = str(item.get("raw", {}).get("sources") or "")
            item["sources"] = [source for source in sources.split(";") if source]
            item["notStarted"] = (
                int(item.get("fixture_count") or 0) > 0
                and int(item.get("completed") or 0) == 0
                and int(item.get("stat_count") or 0) == 0
            )
            competition_id = as_int(item.get("competition_object_id"))
            if competition_id is not None:
                item["identity"] = self.state.media.competition_identity(
                    competition_id, snapshot_id=snapshot_id, competition_name=item.get("competition_name")
                )
                item["format"] = self._competition_format(
                    snapshot_id,
                    competition_id,
                    str(item.get("competition_name") or ""),
                    as_int(item.get("static_competition_id")),
                )
            result.append(item)
        world_competitions = self.state.player_dynamics.world.simulated_leagues(snapshot_id)
        return {
            "snapshot": dict(snap),
            "competitions": result,
            "worldCompetitions": world_competitions,
            "tabs": [
                {"id": "deeper", "name": "Deeper Simulation", "count": len(result)},
                {"id": "atlas", "name": "atlas-world-simulation", "count": len(world_competitions)},
            ],
        }

    def _competition(self, snapshot_id: int, competition_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            competition = conn.execute(
                "SELECT * FROM competition_states WHERE snapshot_id=? AND competition_object_id=?",
                (snapshot_id, competition_id),
            ).fetchone()
            if not competition:
                raise ValueError("Competition not found in the selected snapshot.")
            fixtures = self._fixture_rows(conn, snapshot_id, competition_id=competition_id)
            stats = rows_to_dicts(conn.execute(
                """SELECT player_ea_id,display_name,represented_team_ea_id,represented_team_name,
                          appearances,goals,assists,average_rating,clean_sheets
                   FROM season_stat_states
                   WHERE snapshot_id=? AND competition_object_id=?""",
                (snapshot_id, competition_id),
            ).fetchall())
            progress = conn.execute(
                """SELECT cps.*,ts.team_name FROM competition_progress_states cps
                   LEFT JOIN team_states ts ON ts.snapshot_id=cps.snapshot_id AND ts.ea_team_id=cps.team_ea_id
                   WHERE cps.snapshot_id=? AND cps.competition_object_id=? ORDER BY cps.team_ea_id""",
                (snapshot_id, competition_id),
            ).fetchall()
        participant_map: dict[int, str] = {}
        for fixture in fixtures:
            for id_key, name_key in (("home_team_ea_id", "home_team_name"), ("away_team_ea_id", "away_team_name")):
                team_id = as_int(fixture.get(id_key))
                if team_id is not None:
                    participant_map[team_id] = fixture.get(name_key) or f"Team {team_id}"
        format_info = self._competition_format(
            snapshot_id,
            competition_id,
            str(competition["competition_name"] or ""),
            as_int(competition["static_competition_id"]) if "static_competition_id" in competition.keys() else None,
            fixtures,
        )
        table_fixtures = fixtures
        if format_info["type"] == "hybrid" and format_info.get("leaguePhaseGroups"):
            phase_groups = set(format_info["leaguePhaseGroups"])
            table_fixtures = [
                fixture for fixture in fixtures
                if as_int(fixture.get("match_group_id")) in phase_groups
            ]
        table = aggregate_standings(table_fixtures) if format_info.get("hasTable") else []
        completed = [row for row in fixtures if row.get("is_completed")]
        upcoming = [row for row in fixtures if not row.get("is_completed")]

        groups: dict[str, dict[str, Any]] = {}
        for fixture in fixtures:
            key, label, order = fixture_group_value(fixture)
            group = groups.setdefault(key, {"key": key, "label": label, "order": order, "fixtures": [], "completed": 0, "upcoming": 0})
            group["fixtures"].append(fixture)
            if fixture.get("is_completed"):
                group["completed"] += 1
            else:
                group["upcoming"] += 1
        fixture_groups = sorted(groups.values(), key=lambda group: (group["order"], group["label"]))

        top_scorers = sorted(stats, key=lambda row: (-(as_int(row.get("goals")) or 0), -(as_int(row.get("assists")) or 0), str(row.get("display_name") or "")))[:5]
        top_assists = sorted(stats, key=lambda row: (-(as_int(row.get("assists")) or 0), -(as_int(row.get("goals")) or 0), str(row.get("display_name") or "")))[:5]
        max_appearances = max((as_int(row.get("appearances")) or 0 for row in stats), default=0)
        rating_minimum = max(3, round(max_appearances * 0.25)) if max_appearances else 3
        rating_pool = [row for row in stats if (as_int(row.get("appearances")) or 0) >= rating_minimum and float(row.get("average_rating") or 0) > 0]
        top_ratings = sorted(rating_pool, key=lambda row: (-float(row.get("average_rating") or 0), -(as_int(row.get("appearances")) or 0), str(row.get("display_name") or "")))[:5]

        season_start = self._season_start(snap)
        team_identity_cache: dict[int, dict[str, Any]] = {}
        competition_identity_cache: dict[int, dict[str, Any]] = {}
        fixtures = self._enrich_fixtures(
            fixtures, season_start, snapshot_id, team_identity_cache, competition_identity_cache
        )
        annotate_knockout_progress(
            fixture_groups, enabled=format_info.get("type") in {"knockout", "playoff", "hybrid"}
        )
        for row in table:
            team_id = int(row["team_id"])
            if team_id not in team_identity_cache:
                team_identity_cache[team_id] = self.state.media.team_brief(team_id)
            row["identity"] = team_identity_cache[team_id]
        participant_items = []
        for key, value in sorted(participant_map.items(), key=lambda item: item[1].lower()):
            if key not in team_identity_cache:
                team_identity_cache[key] = self.state.media.team_brief(key)
            participant_items.append({"team_id": key, "team_name": value, "identity": team_identity_cache[key]})
        top_scorers = self._enrich_players(top_scorers)
        top_assists = self._enrich_players(top_assists)
        top_ratings = self._enrich_players(top_ratings)
        return {
            "snapshot": dict(snap),
            "competition": clean_raw(competition),
            "identity": self.state.media.competition_identity(competition_id, snapshot_id=snapshot_id, competition_name=competition["competition_name"]),
            "format": format_info,
            "fixtures": fixtures,
            "fixtureGroups": fixture_groups,
            "completed": completed,
            "upcoming": upcoming,
            "participants": participant_items,
            "standings": table,
            "topPlayers": top_scorers,
            "topScorers": top_scorers,
            "topAssists": top_assists,
            "topRatings": top_ratings,
            "ratingMinimumAppearances": rating_minimum,
            "progress": [clean_raw(row) for row in progress],
            "summary": {
                "fixture_count": len(fixtures),
                "completed": len(completed),
                "upcoming": len(upcoming),
                "participant_count": len(participant_map),
                "managed_matches": sum(1 for row in fixtures if row.get("managed_team_involved")),
                "group_count": len(fixture_groups),
            },
        }
