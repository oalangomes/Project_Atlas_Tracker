from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .match_stats import reconstruct_match_stats, detailed_match
from .positions import trusted_actual_position
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, parse_fc_date,
    parse_raw, rows_to_dicts, subtract_months, youth_potential_range,
)


def historical_observed_positions(conn: sqlite3.Connection, snapshot: sqlite3.Row,
                                  fixture_key: str) -> dict[int, dict[str, Any]]:
    """Recover trusted in-match positions from earlier snapshots of this fixture.

    The exporter stamps the position actually used in a match (including
    substitutes) via career_playerlastmatchhistory only in the snapshot taken
    right after that match. Later snapshots re-export the rating history alone,
    so the line-up slot disappears for substitutes. The most recent snapshot
    still holding a trusted position for this fixture is therefore the most
    faithful record, and later snapshots never override it.
    """

    result: dict[int, dict[str, Any]] = {}
    rows = conn.execute(
        """SELECT pmp.player_ea_id,pmp.actual_position,pmp.actual_position_source,pmp.snapshot_id
             FROM player_match_performances pmp JOIN snapshots s ON s.id=pmp.snapshot_id
            WHERE s.career_id=? AND pmp.fixture_key=? AND pmp.snapshot_id<>?
              AND COALESCE(pmp.actual_position,'')<>''
            ORDER BY s.import_sequence DESC""",
        (snapshot["career_id"], fixture_key, snapshot["id"]),
    ).fetchall()
    for row in rows:
        position = trusted_actual_position(row["actual_position"], row["actual_position_source"])
        if not position:
            continue
        player_id = as_int(row["player_ea_id"])
        if player_id is None or player_id in result:
            continue
        result[player_id] = {
            "position": position,
            "source": str(row["actual_position_source"]),
            "snapshot_id": int(row["snapshot_id"]),
        }
    return result


def apply_historical_observed_positions(rows: list[dict[str, Any]],
                                        trusted: dict[int, dict[str, Any]]) -> int:
    """Fill missing observed positions without overwriting a present one."""

    filled = 0
    for item in rows:
        player_id = as_int(item.get("player_ea_id"))
        if player_id is None or str(item.get("actual_position") or "").strip():
            continue
        trusted_row = trusted.get(player_id)
        if not trusted_row:
            continue
        item["actual_position"] = trusted_row["position"]
        item["actual_position_source"] = trusted_row["source"]
        item["observedPositionBackfill"] = {"snapshotId": trusted_row["snapshot_id"]}
        filled += 1
    return filled

class MatchQueryMixin:
    def _matches(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            rows = self._fixture_rows(conn, snapshot_id, managed_only=True)
            per_comp = conn.execute(
                """SELECT f.competition_object_id,fo.competition_name,
                          COUNT(*) total,SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed
                   FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                   WHERE fo.snapshot_id=? AND fo.managed_team_involved=1
                   GROUP BY f.competition_object_id,fo.competition_name ORDER BY fo.competition_name""",
                (snapshot_id,),
            ).fetchall()
            detailed_fixture_ids = {
                int(r[0]) for r in conn.execute(
                    "SELECT fixture_id FROM match_stat_exports WHERE fixture_id IS NOT NULL AND superseded_by_export_id IS NULL"
                ).fetchall()
            }
        season_start = self._season_start(snap)
        rows = self._enrich_fixtures(rows, season_start, snapshot_id)
        for item in rows:
            item["detailedStatsAvailable"] = int(item.get("fixture_id") or 0) in detailed_fixture_ids
        completed = [row for row in rows if row.get("is_completed")]
        upcoming = [row for row in rows if not row.get("is_completed")]
        competition_items = rows_to_dicts(per_comp)
        for item in competition_items:
            competition_id = as_int(item.get("competition_object_id"))
            if competition_id is not None:
                item["identity"] = self.state.media.competition_identity(competition_id, snapshot_id=snapshot_id, competition_name=item.get("competition_name"))
        return {
            "snapshot": dict(snap),
            "matches": rows,
            "completed": completed,
            "upcoming": upcoming,
            "competitions": competition_items,
        }

    def _match_detail(self, snapshot_id: int, fixture_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            row = conn.execute(
                """SELECT fo.*,f.id fixture_id,f.home_team_ea_id,f.away_team_ea_id,
                          f.competition_object_id,f.static_competition_id,f.stadium_ea_id
                   FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                   WHERE fo.snapshot_id=? AND f.id=?""",
                (snapshot_id, fixture_id),
            ).fetchone()
            if not row:
                raise ValueError("Match not found in the selected snapshot.")
            performances = conn.execute(
                """SELECT pmp.*,ps.overall,ps.potential,ps.primary_position,rs.jersey_number,
                          ps.team_ea_id,ps.team_name
                   FROM player_match_performances pmp
                   LEFT JOIN player_states ps ON ps.snapshot_id=pmp.snapshot_id AND ps.ea_player_id=pmp.player_ea_id
                   LEFT JOIN roster_states rs ON rs.snapshot_id=pmp.snapshot_id AND rs.player_ea_id=pmp.player_ea_id
                   WHERE pmp.snapshot_id=? AND pmp.fixture_key=?
                   ORDER BY pmp.rating DESC,pmp.minutes_played DESC,pmp.display_name""",
                (snapshot_id, row["fixture_key"]),
            ).fetchall()
            competition = conn.execute(
                "SELECT * FROM competition_states WHERE snapshot_id=? AND competition_object_id=?",
                (snapshot_id, row["competition_object_id"]),
            ).fetchone()
            history = conn.execute(
                """SELECT s.id snapshot_id,s.career_date,s.import_sequence,fo.is_completed,
                          fo.home_score,fo.away_score,fo.home_penalties,fo.away_penalties
                   FROM fixture_observations fo JOIN snapshots s ON s.id=fo.snapshot_id
                   WHERE s.career_id=? AND fo.fixture_key=? ORDER BY s.import_sequence""",
                (snap["career_id"], row["fixture_key"]),
            ).fetchall()
            reconstructed = reconstruct_match_stats(conn, snapshot_id).get(str(row["fixture_key"] or ""), {})
            detailed = detailed_match(conn, fixture_id, career_id=int(snap["career_id"]),
                                      as_of_import_sequence=int(snap["import_sequence"]),
                                      season_index=int(snap["season_index"]))
            if row["fixture_key"]:
                historical_observed = historical_observed_positions(conn, snap, row["fixture_key"])
            else:
                historical_observed = {}
        season_start = self._season_start(snap)
        match_item = dict(row)
        self._enrich_fixtures([match_item], season_start, snapshot_id)
        home_identity = self.state.media.team_identity(int(row["home_team_ea_id"]), season_start=season_start) if row["home_team_ea_id"] is not None else None
        away_identity = self.state.media.team_identity(int(row["away_team_ea_id"]), season_start=season_start) if row["away_team_ea_id"] is not None else None
        stadium_id = as_int(row["stadium_ea_id"]) if "stadium_ea_id" in row.keys() else None
        stadium_source = "fixture"
        stadium = self.state.media.stadium_by_id(stadium_id) if stadium_id is not None else None
        if stadium is None and home_identity and home_identity.get("stadiums"):
            stadium = home_identity["stadiums"][0]
            stadium_source = "home_team_fallback"
        raw_base_performances = rows_to_dicts(performances)

        # FC26's career_playermatchratinghistory can retain duplicate rows for the
        # same footballer/date. The snapshot exporter preserves that raw table for
        # auditability, but a match view must never render one footballer twice.
        # Keep the strongest row per player and merge any missing fields from the
        # duplicate so legacy snapshots are repaired at query time as well.
        def performance_quality(item: dict[str, Any]) -> tuple[int, int, int, float]:
            actual = 1 if str(item.get("actual_position") or "").strip() else 0
            joined = 1 if str(item.get("join_status") or "") in {"joined_by_date", "resolved", "detailed_export"} else 0
            minutes = as_int(item.get("minutes_played")) or 0
            try:
                rating = float(item.get("rating")) if item.get("rating") not in (None, "") else -1.0
            except (TypeError, ValueError):
                rating = -1.0
            return actual, joined, minutes, rating

        base_by_player: dict[int, dict[str, Any]] = {}
        for candidate in raw_base_performances:
            player_id = as_int(candidate.get("player_ea_id"))
            if player_id is None:
                continue
            current = base_by_player.get(player_id)
            if current is None:
                base_by_player[player_id] = candidate
                continue
            preferred, alternate = (candidate, current) if performance_quality(candidate) > performance_quality(current) else (current, candidate)
            merged = dict(preferred)
            for key, value in alternate.items():
                if merged.get(key) in (None, "") and value not in (None, ""):
                    merged[key] = value
            base_by_player[player_id] = merged
        base_performances = list(base_by_player.values())
        suppressed_snapshot_duplicates = max(0, len(raw_base_performances) - len(base_performances))
        historical_backfill_count = apply_historical_observed_positions(base_performances, historical_observed)

        detailed_by_player = {int(item.get("playerEaId")): item for item in (detailed or {}).get("players", []) if item.get("playerEaId") is not None}
        detailed_team_ids = {int(item.get("teamIndex")): as_int(item.get("teamEaId")) for item in (detailed or {}).get("teams", []) if item.get("teamIndex") is not None}
        existing_ids = {as_int(item.get("player_ea_id")) for item in base_performances}
        for player_id, detail in detailed_by_player.items():
            if player_id in existing_ids:
                continue
            stats = detail.get("stats") or {}
            team_index = as_int(detail.get("teamIndex"))
            base_performances.append({
                "player_ea_id": player_id,
                "display_name": detail.get("displayName") or f"Player {player_id}",
                "primary_position": detail.get("primaryPosition"),
                "actual_position": detail.get("primaryPosition"),
                "team_ea_id": detail.get("teamEaId"),
                "match_team_ea_id": detailed_team_ids.get(team_index) if team_index is not None else None,
                "match_team_index": team_index,
                "minutes_played": stats.get("minutes_played"),
                "rating": stats.get("game_rating"),
                "join_status": "detailed_export",
            })
        performance_items = self._enrich_players(base_performances)
        home_team_id = as_int(row["home_team_ea_id"]); away_team_id = as_int(row["away_team_ea_id"])
        for item in performance_items:
            player_id = as_int(item.get("player_ea_id")) or -1
            event = reconstructed.get(player_id)
            if event:
                item["reconstructedStats"] = event
            detail = detailed_by_player.get(player_id)
            if detail:
                item["detailedStats"] = detail.get("stats") or {}
                team_index = as_int(detail.get("teamIndex"))
                item["match_team_index"] = team_index
                item["match_team_ea_id"] = detailed_team_ids.get(team_index) if team_index is not None else None
            elif as_int(item.get("team_ea_id")) in {home_team_id, away_team_id}:
                item["match_team_ea_id"] = as_int(item.get("team_ea_id"))
                item["match_team_index"] = 0 if as_int(item.get("team_ea_id")) == home_team_id else 1
        capabilities = parse_raw(snap["capabilities_json"])
        capabilities["reconstructedMatchStats"] = bool(reconstructed)
        capabilities["detailedPlayerMatchStats"] = bool(detailed)
        return {
            "snapshot": dict(snap),
            "match": match_item,
            "performances": performance_items,
            "performanceDiagnostics": {
                "suppressedSnapshotDuplicates": suppressed_snapshot_duplicates,
                "historicalObservedPositionsBackfilled": historical_backfill_count,
            },
            "competition": clean_raw(competition),
            "competitionIdentity": self.state.media.competition_identity(int(row["competition_object_id"]), snapshot_id=snapshot_id, competition_name=match_item.get("competition_name")) if row["competition_object_id"] is not None else None,
            "homeIdentity": home_identity,
            "awayIdentity": away_identity,
            "stadium": stadium,
            "stadiumSource": stadium_source if stadium else None,
            "history": rows_to_dicts(history),
            "capabilities": capabilities,
            "reconstruction": {
                "available": bool(reconstructed),
                "sourceLabel": "Aus aufeinanderfolgenden Snapshots rekonstruiert" if reconstructed else "Cannot be reconstructed reliably",
            },
            "detailedStats": detailed or {"available": False, "modelId": "atlas-fc26-match-stats-v1"},
        }
