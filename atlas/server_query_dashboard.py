from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .team_strength import live_squad_strength
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, career_clock, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, parse_fc_date,
    parse_raw, player_age_data, rows_to_dicts, subtract_months, youth_potential_range,
)

class DashboardQueryMixin:
    def _dashboard(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = conn.execute(
                """SELECT s.*,c.display_name career_name,c.manager_name
                   FROM snapshots s JOIN careers c ON c.id=s.career_id WHERE s.id=?""",
                (snapshot_id,),
            ).fetchone()
            if not snap:
                raise ValueError("Snapshot not found.")
            team = conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchone()
            league_state = conn.execute(
                "SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchone()
            squad_count = conn.execute(
                "SELECT COUNT(*) FROM roster_states WHERE snapshot_id=? AND team_ea_id=?",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchone()[0]
            squad_strength = live_squad_strength(conn, snapshot_id, int(snap["managed_team_ea_id"]))
            matches = self._fixture_rows(conn, snapshot_id, managed_only=True)
            upcoming = [row for row in matches if not row.get("is_completed")][:8]
            recent = [row for row in matches if row.get("is_completed")][-8:][::-1]
            leaders = conn.execute(
                """SELECT player_ea_id,display_name,SUM(COALESCE(goals,0)) goals,
                          SUM(COALESCE(assists,0)) assists,SUM(COALESCE(appearances,0)) appearances,
                          CASE WHEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)>0
                               THEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN average_rating*appearances ELSE 0 END)
                                  / SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)
                          END average_rating
                   FROM season_stat_states
                   WHERE snapshot_id=? AND represented_team_ea_id=?
                   GROUP BY player_ea_id,display_name
                   ORDER BY goals DESC,assists DESC,appearances DESC LIMIT 8""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchall()
            top_players = conn.execute(
                """SELECT p.ea_player_id,p.display_name,p.overall,p.potential,p.primary_position,
                          r.jersey_number,r.form,r.injury
                   FROM roster_states r JOIN player_states p
                     ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                   WHERE r.snapshot_id=? AND r.team_ea_id=?
                   ORDER BY p.overall DESC,p.potential DESC,p.display_name LIMIT 8""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchall()
            timeline = conn.execute(
                """SELECT id,career_date,season_index,import_sequence,same_day_sequence,import_status
                   FROM snapshots WHERE career_id=? ORDER BY import_sequence""",
                (snap["career_id"],),
            ).fetchall()
            competitions = conn.execute(
                """SELECT f.competition_object_id,fo.competition_name,
                          SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) played,
                          SUM(CASE WHEN COALESCE(fo.is_completed,0)=0 THEN 1 ELSE 0 END) upcoming
                   FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                   WHERE fo.snapshot_id=? AND fo.managed_team_involved=1
                   GROUP BY f.competition_object_id,fo.competition_name
                   ORDER BY played DESC,fo.competition_name""",
                (snapshot_id,),
            ).fetchall()
            contract_summary = conn.execute(
                """SELECT COUNT(*) count,SUM(COALESCE(wage,0)) wage_total,
                          AVG(COALESCE(wage,0)) wage_average
                   FROM contract_states WHERE snapshot_id=? AND team_ea_id=?""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchone()
            computed_position = self._current_league_position(conn, snapshot_id, int(snap["managed_team_ea_id"]))
            season_numbers = self._career_season_numbers(conn, int(snap["career_id"]))
            live_clock = career_clock(conn, int(snap["career_id"]))
        season_start = self._season_start(snap)
        leader_items = self._enrich_players(rows_to_dicts(leaders))
        top_player_items = self._enrich_players(rows_to_dicts(top_players))
        competition_items = rows_to_dicts(competitions)
        for item in competition_items:
            competition_id = as_int(item.get("competition_object_id"))
            if competition_id is not None:
                item["identity"] = self.state.media.competition_identity(competition_id, snapshot_id=snapshot_id, competition_name=item.get("competition_name"))
        snapshot_item = dict(snap)
        snapshot_item["season_start_year"] = season_start
        snapshot_item["season_label"] = f"{season_start}/{str(season_start + 1)[-2:]}" if season_start is not None else f"EA season index {int(snap['season_index'])}"
        snapshot_item["career_season_number"] = season_numbers.get(season_start) if season_start is not None else None
        league_item = clean_raw(league_state) or {}
        if computed_position:
            league_item["current_table_position"] = computed_position.get("position")
            league_item["table_position_source"] = computed_position.get("source")
            league_item["table_position_source_label"] = computed_position.get("source_label")
            league_item["table_competition_object_id"] = computed_position.get("competition_object_id")
            league_item["table_competition_name"] = computed_position.get("competition_name")
        timeline_items = rows_to_dicts(timeline)
        for item in timeline_items:
            start = season_start_from_date(item.get("career_date"))
            item["season_start_year"] = start
            item["season_label"] = f"{start}/{str(start + 1)[-2:]}" if start is not None else f"EA season index {item.get('season_index')}"
            item["career_season_number"] = season_numbers.get(start) if start is not None else None
        return {
            "snapshot": snapshot_item,
            "team": clean_raw(team),
            "teamIdentity": self.state.media.team_identity(int(snap["managed_team_ea_id"]), season_start=season_start),
            "leagueState": league_item,
            "squadCount": squad_count,
            "squadStrength": {
                "overall": round(float(squad_strength["average"]), 2) if squad_strength["average"] is not None else None,
                "playerCount": int(squad_strength["count"]),
                "overallSum": int(squad_strength["sum"]),
                "minimum": squad_strength["minimum"],
                "maximum": squad_strength["maximum"],
                "formula": "Sum of the OVR values of all players assigned to the current senior squad and club in the snapshot, divided by their number",
                "eaBaseOverall": as_int(team["overall"]) if team else None,
                "eaBaseOverallUsed": False,
                "source": {"kind": "calculated_snapshot_roster", "membership": squad_strength["membershipSource"]},
            },
            "completedMatches": sum(1 for row in matches if row.get("is_completed")),
            "upcoming": self._enrich_fixtures(upcoming, season_start, snapshot_id),
            "recent": self._enrich_fixtures(recent, season_start, snapshot_id),
            "leaders": leader_items,
            "topPlayers": top_player_items,
            "timeline": timeline_items,
            "competitions": competition_items,
            "contractSummary": dict(contract_summary) if contract_summary else {},
            "liveCareerDate": str(live_clock["careerDate"]),
        }

    def _coverage(self, snapshot_id: int) -> dict[str, Any]:
        tables = [
            "player_states", "team_states", "league_states", "competition_states", "roster_states",
            "season_stat_states", "fixture_observations", "player_match_performances", "contract_states",
            "loan_states", "youth_player_states", "player_growth_states", "competition_progress_states",
            "generic_snapshot_rows",
        ]
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
                for table in tables
            }
            files = conn.execute(
                "SELECT * FROM import_files WHERE snapshot_id=? ORDER BY file_name", (snapshot_id,)
            ).fetchall()
            metadata = conn.execute(
                "SELECT key,value FROM snapshot_metadata WHERE snapshot_id=? ORDER BY key", (snapshot_id,)
            ).fetchall()
        return {
            "snapshot": dict(snap),
            "counts": counts,
            "files": rows_to_dicts(files),
            "metadata": {row["key"]: row["value"] for row in metadata},
            "capabilities": parse_raw(snap["capabilities_json"]),
            "warnings": json.loads(snap["warnings_json"] or "[]"),
        }

    def _squad(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            rows = conn.execute(
                """SELECT r.jersey_number,r.teamsheet_slot_label,r.form,r.injury,r.raw_json roster_raw_json,
                          p.ea_player_id,p.display_name,p.team_ea_id,p.team_name,p.overall,p.potential,p.primary_position,
                          p.nationality_id,p.contract_valid_until,p.height,p.weight,p.preferred_foot_id,p.raw_json player_raw_json,
                          COALESCE(stats.appearances,0) appearances,COALESCE(stats.goals,0) goals,
                          COALESCE(stats.assists,0) assists,stats.average_rating,
                          c.wage,c.duration_months,c.raw_json contract_raw_json,
                          CASE WHEN y.player_ea_id IS NULL THEN 0 ELSE 1 END is_youth,
                          CASE WHEN l.player_ea_id IS NULL THEN 0 ELSE 1 END is_on_loan
                   FROM roster_states r
                   JOIN player_states p ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                   LEFT JOIN (
                     SELECT snapshot_id,player_ea_id,represented_team_ea_id,SUM(COALESCE(appearances,0)) appearances,
                            SUM(COALESCE(goals,0)) goals,SUM(COALESCE(assists,0)) assists,
                            CASE WHEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)>0
                                 THEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN average_rating*appearances ELSE 0 END)
                                    / SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)
                            END average_rating
                     FROM season_stat_states GROUP BY snapshot_id,player_ea_id,represented_team_ea_id
                   ) stats ON stats.snapshot_id=p.snapshot_id AND stats.player_ea_id=p.ea_player_id AND stats.represented_team_ea_id=p.team_ea_id
                   LEFT JOIN contract_states c ON c.snapshot_id=p.snapshot_id AND c.player_ea_id=p.ea_player_id
                   LEFT JOIN youth_player_states y ON y.snapshot_id=p.snapshot_id AND y.player_ea_id=p.ea_player_id
                   LEFT JOIN loan_states l ON l.snapshot_id=p.snapshot_id AND l.player_ea_id=p.ea_player_id
                   WHERE r.snapshot_id=? AND r.team_ea_id=?
                   ORDER BY CASE WHEN r.jersey_number IS NULL OR r.jersey_number=0 THEN 999 ELSE r.jersey_number END,
                            p.display_name""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchall()
            team = conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchone()
            captain_player_id = None
            season_numbers = self._career_season_numbers(conn, int(snap["career_id"]))
            financial_items: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["is_captain"] = int(item["ea_player_id"]) == captain_player_id
                player_raw_json = item.pop("player_raw_json", None)
                player_raw = parse_raw(player_raw_json)
                item.update(player_age_data(player_raw.get("birthdate_raw"), snap["career_date"]))
                player_context = dict(item)
                player_context["raw_json"] = player_raw_json
                roster_context = {"form": item.get("form"), "raw_json": item.pop("roster_raw_json", None)}
                contract_context = {"wage": item.get("wage"), "raw_json": item.pop("contract_raw_json", None)}
                financial = self.state.financial.calculate_player(
                    conn, snap, player_context, roster=roster_context, contract=contract_context
                )
                atlas_finance = self.state.player_finance.analyze(snapshot_id, int(item["ea_player_id"]))
                financial["market_value"] = {
                    "value": atlas_finance["market"].get("value"),
                    "available": True,
                    "source": "atlas_player_finance",
                    "label": "Atlas market value · independent model based on performance, league, club, age, potential and contract",
                }
                item["financial"] = financial
                item["player_finance"] = atlas_finance
                item["dynamic_overall"] = (atlas_finance.get("dynamic") or {}).get("dynamicOverall")
                item["dynamic_delta"] = (atlas_finance.get("dynamic") or {}).get("delta")
                item["market_value"] = atlas_finance["market"].get("value")
                item["weekly_wage"] = financial["weekly_wage"].get("value")
                item["wage_label"] = financial["weekly_wage"].get("label")
                financial_items.append(item)
        season_start = self._season_start(snap)
        snapshot_item = dict(snap)
        snapshot_item["season_start_year"] = season_start
        snapshot_item["season_label"] = f"{season_start}/{str(season_start + 1)[-2:]}" if season_start is not None else "Unknown season"
        snapshot_item["career_season_number"] = season_numbers.get(season_start) if season_start is not None else None
        return {
            "snapshot": snapshot_item,
            "team": clean_raw(team),
            "teamIdentity": self.state.media.team_identity(int(snap["managed_team_ea_id"]), season_start=season_start),
            "players": self._enrich_players(financial_items),
        }
