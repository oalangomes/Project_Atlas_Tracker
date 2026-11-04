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

class QueryBaseMixin:
    def _snapshot(self, conn: sqlite3.Connection, snapshot_id: int) -> sqlite3.Row:
        snap = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if not snap:
            raise ValueError("Snapshot not found.")
        return snap

    def _season_start(self, snapshot: sqlite3.Row | dict[str, Any]) -> int | None:
        return season_start_from_date(str(snapshot["career_date"] or ""))

    def _career_season_numbers(self, conn: sqlite3.Connection, career_id: int) -> dict[int, int]:
        """Map calendar season start years to the visible career-season ordinal.

        EA's season_index is kept as a technical ordering input only.  Live-start
        careers can begin with an already advanced EA index, so visible numbering
        follows the actual calendar seasons present in snapshots/manual history.
        """
        years = {
            year for row in conn.execute(
                "SELECT career_date FROM snapshots WHERE career_id=?", (career_id,)
            ).fetchall()
            if (year := season_start_from_date(row["career_date"])) is not None
        }
        years.update(
            int(row["start_year"]) for row in conn.execute(
                "SELECT start_year FROM manual_seasons WHERE career_id=?", (career_id,)
            ).fetchall() if row["start_year"] is not None
        )
        return {year: index + 1 for index, year in enumerate(sorted(years))}

    @staticmethod
    def _clean_reference_competition_name(value: Any) -> str:
        """Remove reference-only country/level decorations from visible names."""
        text = str(value or "").strip()
        text = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", text).strip()
        countries = (
            "England", "Germany", "France", "Spain", "Italy", "Scotland", "Portugal",
            "Netherlands", "Holland", "Belgium", "Austria", "Switzerland", "Denmark",
            "Norway", "Sweden", "Poland", "Turkey", "USA", "Mexico", "Argentina",
            "Brazil", "Australia", "Ireland", "Romania", "Czech Republic",
        )
        for country in countries:
            prefix = country + " "
            if text.casefold().startswith(prefix.casefold()) and len(text) > len(prefix):
                text = text[len(prefix):].strip()
                break
        return text or str(value or "").strip()

    def _display_competition_name(
        self,
        conn: sqlite3.Connection,
        raw_name: Any,
        *,
        career_id: int | None = None,
        competition_object_id: int | None = None,
        static_competition_id: int | None = None,
    ) -> str:
        """Return the latest observed Atlas name, falling back to a cleaned reference name.

        This keeps league history, analysis and competition pages on the same visible
        naming source instead of exposing reference decorations such as country prefixes
        or ``(1)`` level suffixes.
        """
        clauses: list[str] = []
        args: list[Any] = []
        if competition_object_id is not None:
            clauses.append("cs.competition_object_id=?")
            args.append(int(competition_object_id))
        elif static_competition_id is not None:
            clauses.append("cs.static_competition_id=?")
            args.append(int(static_competition_id))
        if clauses:
            if career_id is not None:
                clauses.append("s.career_id=?")
                args.append(int(career_id))
            row = conn.execute(
                f"""SELECT cs.competition_name FROM competition_states cs
                    JOIN snapshots s ON s.id=cs.snapshot_id
                    WHERE {' AND '.join(clauses)} AND TRIM(COALESCE(cs.competition_name,''))<>''
                    ORDER BY s.import_sequence DESC,cs.snapshot_id DESC LIMIT 1""",
                tuple(args),
            ).fetchone()
            if row and row["competition_name"]:
                return str(row["competition_name"]).strip()
        return self._clean_reference_competition_name(raw_name) or "Competition"

    def _current_league_position(
        self, conn: sqlite3.Connection, snapshot_id: int, team_id: int
    ) -> dict[str, Any] | None:
        """Return the same computed league table position used by competition pages."""
        metadata = conn.execute(
            "SELECT value FROM snapshot_metadata WHERE snapshot_id=? AND key='primary_compobjid'",
            (snapshot_id,),
        ).fetchone()
        primary_id = as_int(metadata["value"]) if metadata else None
        competitions = conn.execute(
            """SELECT c.competition_object_id,c.static_competition_id,c.competition_name,
                      SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed,
                      COUNT(fo.fixture_id) fixture_count,
                      SUM(CASE WHEN fo.managed_team_involved=1 THEN 1 ELSE 0 END) managed_matches
               FROM competition_states c
               LEFT JOIN fixtures f ON f.competition_object_id=c.competition_object_id
               LEFT JOIN fixture_observations fo ON fo.snapshot_id=c.snapshot_id AND fo.fixture_id=f.id
               WHERE c.snapshot_id=?
               GROUP BY c.competition_object_id,c.static_competition_id,c.competition_name
               HAVING managed_matches>0
               ORDER BY CASE WHEN c.competition_object_id=? THEN 0 ELSE 1 END,
                        completed DESC,fixture_count DESC""",
            (snapshot_id, primary_id),
        ).fetchall()
        for competition in competitions:
            competition_id = as_int(competition["competition_object_id"])
            if competition_id is None:
                continue
            fixtures = self._fixture_rows(conn, snapshot_id, competition_id=competition_id)
            format_info = self._competition_format(
                snapshot_id,
                competition_id,
                str(competition["competition_name"] or ""),
                as_int(competition["static_competition_id"]),
                fixtures,
            )
            if not format_info.get("hasTable"):
                continue
            table_fixtures = fixtures
            if format_info.get("type") == "hybrid" and format_info.get("leaguePhaseGroups"):
                phase_groups = set(format_info["leaguePhaseGroups"])
                table_fixtures = [
                    fixture for fixture in fixtures
                    if as_int(fixture.get("match_group_id")) in phase_groups
                ]
            table = aggregate_standings(table_fixtures)
            row = next((item for item in table if as_int(item.get("team_id")) == int(team_id)), None)
            if row:
                return {
                    "position": as_int(row.get("position")),
                    "competition_object_id": competition_id,
                    "competition_name": competition["competition_name"],
                    "source": "computed_standings",
                    "source_label": "Berechnete Tabelle",
                    "table": table,
                }
        return None

    def _enrich_players(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            player_id = as_int(row.get("ea_player_id") or row.get("player_ea_id"))
            if player_id is not None:
                row["media"] = self.state.media.player_media(player_id)
        return rows

    def _enrich_fixtures(
        self,
        rows: list[dict[str, Any]],
        season_start: int | None,
        snapshot_id: int | None = None,
        team_cache: dict[int, dict[str, Any]] | None = None,
        competition_cache: dict[int, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        cache_team = team_cache if team_cache is not None else {}
        cache_comp = competition_cache if competition_cache is not None else {}
        for row in rows:
            home_id = as_int(row.get("home_team_ea_id")); away_id = as_int(row.get("away_team_ea_id"))
            competition_id = as_int(row.get("competition_object_id"))
            if home_id is not None:
                if home_id not in cache_team:
                    cache_team[home_id] = self.state.media.team_brief(home_id)
                row["homeIdentity"] = cache_team[home_id]
            if away_id is not None:
                if away_id not in cache_team:
                    cache_team[away_id] = self.state.media.team_brief(away_id)
                row["awayIdentity"] = cache_team[away_id]
            if competition_id is not None:
                if competition_id not in cache_comp:
                    cache_comp[competition_id] = self.state.media.competition_identity(
                        competition_id, snapshot_id=snapshot_id, competition_name=row.get("competition_name")
                    )
                row["competitionIdentity"] = cache_comp[competition_id]
        return rows

    def _fixture_rows(self, conn: sqlite3.Connection, snapshot_id: int, *, managed_only: bool = False,
                      competition_id: int | None = None, team_id: int | None = None) -> list[dict[str, Any]]:
        clauses = ["fo.snapshot_id=?"]
        args: list[Any] = [snapshot_id]
        if managed_only:
            clauses.append("fo.managed_team_involved=1")
        if competition_id is not None:
            clauses.append("f.competition_object_id=?")
            args.append(competition_id)
        if team_id is not None:
            clauses.append("(f.home_team_ea_id=? OR f.away_team_ea_id=?)")
            args.extend([team_id, team_id])
        rows = conn.execute(
            f"""SELECT fo.*,f.id fixture_id,f.home_team_ea_id,f.away_team_ea_id,
                       f.competition_object_id,f.static_competition_id,f.stadium_ea_id
                FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                WHERE {' AND '.join(clauses)}
                ORDER BY fo.date,fo.time,fo.fixture_key""",
            tuple(args),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = parse_raw(item.get("raw_json"))
            item["raw"] = raw
            item["match_group_id"] = as_int(raw.get("match_group_id"))
            result.append(item)
        return result
