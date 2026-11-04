from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any, *, required: bool = False, label: str = "Wert", max_length: int = 240) -> str | None:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is missing.")
    if len(text) > max_length:
        raise ValueError(f"{label} is too long (maximum {max_length} Zeichen).")
    return text or None


def optional_int(value: Any, *, minimum: int | None = None, maximum: int | None = None, label: str = "Wert") -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must not be less than {minimum} sein.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must not be greater than {maximum} sein.")
    return number


def optional_float(value: Any, *, minimum: float | None = None, maximum: float | None = None, label: str = "Wert") -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must not be less than {minimum:g} sein.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must not be greater than {maximum:g} sein.")
    return round(number, 2)


def normalized_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def optional_iso_date(value: Any, *, label: str = "Datum") -> str | None:
    text = clean_text(value, label=label, max_length=10)
    if not text:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD format.") from exc
    return text


class ManualDataService:
    """CRUD and read model for user-maintained historical career data.

    Imported snapshot tables remain immutable.  All writes in this service are
    confined to the manual_* tables introduced with database schema 7 and extended through schema 12.
    """

    def __init__(self, database: Database):
        self.database = database

    def overview(self, career_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            career = conn.execute("SELECT * FROM careers WHERE id=?", (career_id,)).fetchone()
            if not career:
                raise ValueError("Career not found.")
            seasons = [dict(row) for row in conn.execute(
                """SELECT s.*,
                          COUNT(DISTINCT c.id) competition_count,
                          COUNT(DISTINCT ps.id) stat_count,
                          COUNT(DISTINCT t.id) transaction_count,
                          COUNT(DISTINCT lf.id) league_finish_count,
                          COUNT(DISTINCT pd.id) development_count,
                          COUNT(DISTINCT sa.id) award_count
                   FROM manual_seasons s
                   LEFT JOIN manual_competitions c ON c.manual_season_id=s.id
                   LEFT JOIN manual_player_stats ps ON ps.manual_competition_id=c.id
                   LEFT JOIN manual_transactions t ON t.manual_season_id=s.id
                   LEFT JOIN manual_league_finishes lf ON lf.manual_season_id=s.id
                   LEFT JOIN manual_player_development pd ON pd.manual_season_id=s.id
                   LEFT JOIN manual_season_awards sa ON sa.manual_season_id=s.id
                   WHERE s.career_id=?
                   GROUP BY s.id
                   ORDER BY s.season_index,s.id""",
                (career_id,),
            ).fetchall()]
            competitions = [dict(row) for row in conn.execute(
                """SELECT c.* FROM manual_competitions c
                   JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE s.career_id=? ORDER BY s.season_index,c.sort_order,c.id""",
                (career_id,),
            ).fetchall()]
            stats = [dict(row) for row in conn.execute(
                """SELECT ps.*,c.competition_name,c.manual_season_id,s.season_index,s.label season_label
                   FROM manual_player_stats ps
                   JOIN manual_competitions c ON c.id=ps.manual_competition_id
                   JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE s.career_id=?
                   ORDER BY s.season_index,c.sort_order,ps.display_name""",
                (career_id,),
            ).fetchall()]
            transactions = [dict(row) for row in conn.execute(
                """SELECT t.*,s.season_index,s.label season_label
                   FROM manual_transactions t
                   JOIN manual_seasons s ON s.id=t.manual_season_id
                   WHERE s.career_id=?
                   ORDER BY s.season_index,COALESCE(t.transaction_date,''),t.id""",
                (career_id,),
            ).fetchall()]
            league_finishes = [dict(row) for row in conn.execute(
                """SELECT lf.*,s.season_index,s.label season_label,s.start_year,s.end_year
                   FROM manual_league_finishes lf
                   JOIN manual_seasons s ON s.id=lf.manual_season_id
                   WHERE s.career_id=?
                   ORDER BY s.season_index,lf.final_position,lf.team_name""",
                (career_id,),
            ).fetchall()]
            developments = [dict(row) for row in conn.execute(
                """SELECT pd.*,s.season_index,s.label season_label,s.start_year,s.end_year
                   FROM manual_player_development pd
                   JOIN manual_seasons s ON s.id=pd.manual_season_id
                   WHERE s.career_id=?
                   ORDER BY s.start_year,CASE pd.stage WHEN 'season_start' THEN 0 ELSE 1 END,pd.display_name""",
                (career_id,),
            ).fetchall()]
            changes = [dict(row) for row in conn.execute(
                """SELECT * FROM manual_change_log WHERE career_id=?
                   ORDER BY id DESC LIMIT 100""",
                (career_id,),
            ).fetchall()]
        for row in changes:
            try:
                row["details"] = json.loads(row.pop("details_json", "{}") or "{}")
            except json.JSONDecodeError:
                row["details"] = {}
        return {
            "career": dict(career),
            "seasons": seasons,
            "competitions": competitions,
            "stats": stats,
            "transactions": transactions,
            "leagueFinishes": league_finishes,
            "developments": developments,
            "changes": changes,
            "backups": self.database.list_backups(),
            "references": self.references(career_id),
        }

    def references(self, career_id: int) -> dict[str, list[dict[str, Any]]]:
        """Small reference lists used by forms.

        Players are intentionally resolved through ``search_players`` so the
        manual-data page does not have to download the full career database.
        """
        with self.database.connect() as conn:
            career = conn.execute("SELECT * FROM careers WHERE id=?", (career_id,)).fetchone()
            if not career:
                raise ValueError("Career not found.")
            recent_players = [dict(row) for row in conn.execute(
                """WITH ranked AS (
                       SELECT p.ea_player_id,p.display_name,p.primary_position,p.team_name,p.overall,
                              ROW_NUMBER() OVER (PARTITION BY p.ea_player_id ORDER BY s.import_sequence DESC) rn
                       FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
                       WHERE s.career_id=?
                   )
                   SELECT ea_player_id,display_name,primary_position,team_name,overall
                   FROM ranked WHERE rn=1
                   ORDER BY display_name LIMIT 250""",
                (career_id,),
            ).fetchall()]
            teams = [dict(row) for row in conn.execute(
                """SELECT t.ea_team_id,MAX(t.team_name) team_name
                   FROM team_states t JOIN snapshots s ON s.id=t.snapshot_id
                   WHERE s.career_id=? GROUP BY t.ea_team_id ORDER BY team_name""",
                (career_id,),
            ).fetchall()]
            competitions = [dict(row) for row in conn.execute(
                """SELECT cs.competition_object_id,MAX(cs.static_competition_id) static_competition_id,
                          MAX(cs.competition_name) competition_name
                   FROM competition_states cs JOIN snapshots s ON s.id=cs.snapshot_id
                   WHERE s.career_id=? GROUP BY cs.competition_object_id ORDER BY competition_name""",
                (career_id,),
            ).fetchall()]
            leagues = [dict(row) for row in conn.execute(
                """SELECT ls.ea_league_id,MAX(ls.league_name) league_name
                   FROM league_states ls JOIN snapshots s ON s.id=ls.snapshot_id
                   WHERE s.career_id=? GROUP BY ls.ea_league_id ORDER BY league_name""",
                (career_id,),
            ).fetchall()]
        return {"players": recent_players, "teams": teams, "competitions": competitions, "leagues": leagues}

    def search_players(self, career_id: int, query: str, limit: int = 40) -> list[dict[str, Any]]:
        """Search every player observed in the career plus manual-only names."""
        text = clean_text(query, label="Suchbegriff", max_length=120) or ""
        if len(text) < 2:
            return []
        limit = max(1, min(int(limit or 40), 80))
        like = f"%{text}%"
        prefix = f"{text}%"
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                raise ValueError("Career not found.")
            rows = conn.execute(
                """WITH ranked AS (
                       SELECT p.ea_player_id,p.display_name,p.primary_position,p.team_name,p.overall,
                              s.import_sequence,
                              ROW_NUMBER() OVER (PARTITION BY p.ea_player_id ORDER BY s.import_sequence DESC) rn
                       FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
                       WHERE s.career_id=?
                   )
                   SELECT ea_player_id,display_name,primary_position,team_name,overall,'snapshot' source
                   FROM ranked
                   WHERE rn=1 AND (display_name LIKE ? COLLATE NOCASE OR CAST(ea_player_id AS TEXT)=?)
                   ORDER BY CASE WHEN display_name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END,
                            display_name COLLATE NOCASE
                   LIMIT ?""",
                (career_id, like, text, prefix, limit),
            ).fetchall()
            result = [dict(row) for row in rows]
            remaining = limit - len(result)
            if remaining > 0:
                manual_rows = conn.execute(
                    """SELECT display_name,MAX(player_ea_id) player_ea_id,'manual' source
                       FROM (
                         SELECT ps.display_name,ps.player_ea_id
                         FROM manual_player_stats ps
                         JOIN manual_competitions c ON c.id=ps.manual_competition_id
                         JOIN manual_seasons s ON s.id=c.manual_season_id
                         WHERE s.career_id=? AND ps.display_name LIKE ? COLLATE NOCASE
                         UNION ALL
                         SELECT t.display_name,t.player_ea_id
                         FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                         WHERE s.career_id=? AND t.display_name LIKE ? COLLATE NOCASE
                       )
                       GROUP BY lower(display_name) ORDER BY display_name COLLATE NOCASE LIMIT ?""",
                    (career_id, like, career_id, like, remaining),
                ).fetchall()
                seen_ids = {row.get("ea_player_id") for row in result if row.get("ea_player_id") is not None}
                seen_names = {normalized_key(str(row.get("display_name") or "")) for row in result}
                for row in manual_rows:
                    item = dict(row)
                    if item.get("player_ea_id") in seen_ids or normalized_key(item["display_name"]) in seen_names:
                        continue
                    item.update({"primary_position": None, "team_name": None, "overall": None})
                    result.append(item)
        return result[:limit]

    def player_editor(self, career_id: int, player_id: int) -> dict[str, Any]:
        """Return merged imported/manual season choices and existing player rows."""
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                raise ValueError("Career not found.")
            manual_rows = [dict(row) for row in conn.execute(
                """SELECT * FROM manual_seasons WHERE career_id=? ORDER BY start_year,season_index,id""",
                (career_id,),
            ).fetchall()]
            snapshot_rows = [dict(row) for row in conn.execute(
                """SELECT season_index,MIN(career_date) first_date,MAX(career_date) last_date,
                          MAX(managed_team_ea_id) managed_team_ea_id,MAX(managed_team_name) managed_team_name
                   FROM snapshots WHERE career_id=? GROUP BY season_index ORDER BY first_date,season_index""",
                (career_id,),
            ).fetchall()]
            by_start: dict[int, dict[str, Any]] = {}
            seasons: list[dict[str, Any]] = []
            for row in snapshot_rows:
                first_date = str(row.get("first_date") or "")
                try:
                    year, month = int(first_date[:4]), int(first_date[5:7])
                    start_year = year if month >= 7 else year - 1
                except (ValueError, TypeError):
                    start_year = 2000 + int(row.get("season_index") or 0)
                item = {
                    "id": None,
                    "selection_value": f"snapshot:{int(row['season_index'])}:{start_year}",
                    "season_index": int(row["season_index"]),
                    "label": f"{start_year}/{str(start_year + 1)[-2:]}",
                    "start_year": start_year,
                    "end_year": start_year + 1,
                    "managed_team_ea_id": row.get("managed_team_ea_id"),
                    "managed_team_name": row.get("managed_team_name"),
                    "has_snapshots": True,
                    "has_manual_data": False,
                    "source_label": "Imported season",
                }
                by_start[start_year] = item
                seasons.append(item)
            for row in manual_rows:
                start_year = int(row["start_year"])
                current = by_start.get(start_year)
                item = current if current is not None else {
                    "season_index": int(row["season_index"]),
                    "has_snapshots": False,
                }
                item.update({
                    **row,
                    "selection_value": f"manual:{int(row['id'])}",
                    "has_manual_data": True,
                    "source_label": "Imported + manual" if item.get("has_snapshots") else "Manual season",
                })
                if current is None:
                    seasons.append(item)
                by_start[start_year] = item
            seasons.sort(key=lambda item: (int(item.get("start_year") or 9999), int(item.get("season_index") or 0)))
            competitions = [dict(row) for row in conn.execute(
                """SELECT c.* FROM manual_competitions c JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE s.career_id=? ORDER BY s.season_index,c.sort_order,c.id""",
                (career_id,),
            ).fetchall()]
            stats = [dict(row) for row in conn.execute(
                """SELECT ps.*,c.competition_name,c.manual_season_id,s.label season_label,
                          s.season_index,s.start_year,s.end_year
                   FROM manual_player_stats ps
                   JOIN manual_competitions c ON c.id=ps.manual_competition_id
                   JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE s.career_id=? AND ps.player_ea_id=?
                   ORDER BY s.season_index,c.sort_order,c.id""",
                (career_id, player_id),
            ).fetchall()]
            development = [dict(row) for row in conn.execute(
                """SELECT pd.*,s.label season_label,s.season_index,s.start_year,s.end_year,
                          s.managed_team_ea_id,s.managed_team_name
                   FROM manual_player_development pd
                   JOIN manual_seasons s ON s.id=pd.manual_season_id
                   WHERE s.career_id=? AND pd.player_ea_id=?
                   ORDER BY pd.effective_date,pd.id""",
                (career_id, player_id),
            ).fetchall()]
        return {"seasons": seasons, "competitions": competitions, "stats": stats, "development": development}

    def save_season(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        season_id = optional_int(payload.get("id"), minimum=1, label="Season ID")
        season_index = optional_int(payload.get("seasonIndex"), minimum=0, maximum=99, label="Season number")
        if season_index is None:
            raise ValueError("Season number is missing.")
        label = clean_text(payload.get("label"), label="Season label") or f"Season {season_index + 1}"
        start_year = optional_int(payload.get("startYear"), minimum=1900, maximum=2200, label="Start year")
        end_year = optional_int(payload.get("endYear"), minimum=1900, maximum=2201, label="Endjahr")
        if start_year is None:
            raise ValueError("Start year is missing.")
        if end_year is None:
            raise ValueError("End year is missing.")
        if end_year < start_year:
            raise ValueError("End year must not precede start year.")
        team_id = optional_int(payload.get("managedTeamEaId"), minimum=1, label="Team-ID")
        team_name = clean_text(payload.get("managedTeamName"), label="Club name")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=2000)
        now = utc_now()
        with self.database.transaction() as conn:
            if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                raise ValueError("Career not found.")
            if season_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_seasons(
                           career_id,season_index,label,start_year,end_year,managed_team_ea_id,
                           managed_team_name,notes,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (career_id, season_index, label, start_year, end_year, team_id, team_name, notes, now, now),
                )
                season_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute("SELECT * FROM manual_seasons WHERE id=? AND career_id=?", (season_id, career_id)).fetchone()
                if not existing:
                    raise ValueError("Historical season not found.")
                conn.execute(
                    """UPDATE manual_seasons SET season_index=?,label=?,start_year=?,end_year=?,
                           managed_team_ea_id=?,managed_team_name=?,notes=?,updated_at=? WHERE id=?""",
                    (season_index, label, start_year, end_year, team_id, team_name, notes, now, season_id),
                )
                action = "update"
            self._log(conn, career_id, action, "season", season_id, payload)
            row = conn.execute("SELECT * FROM manual_seasons WHERE id=?", (season_id,)).fetchone()
        return dict(row)

    def delete_season(self, career_id: int, season_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM manual_seasons WHERE id=? AND career_id=?", (season_id, career_id)).fetchone()
            if not row:
                raise ValueError("Historical season not found.")
            self._log(conn, career_id, "delete", "season", season_id, dict(row))
            conn.execute("DELETE FROM manual_seasons WHERE id=?", (season_id,))
        return {"ok": True, "id": season_id}

    def save_competition(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        competition_id = optional_int(payload.get("id"), minimum=1, label="Competitions-ID")
        season_id = optional_int(payload.get("seasonId"), minimum=1, label="Season ID")
        if season_id is None:
            raise ValueError("Historical season is missing.")
        kind = str(payload.get("competitionType") or "other").strip().lower()
        if kind not in {"league", "cup", "supercup", "playoff", "other"}:
            raise ValueError("Unknown competitionstyp.")
        name = clean_text(payload.get("competitionName"), required=True, label="Competitionsname")
        object_id = optional_int(payload.get("competitionObjectId"), minimum=1, label="Competition Object-ID")
        static_id = optional_int(payload.get("staticCompetitionId"), minimum=1, label="statische Competition-ID")
        final_position = optional_int(payload.get("finalPosition"), minimum=1, maximum=999, label="Platzierung")
        result_text = clean_text(payload.get("resultText"), label="Final result")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=2000)
        sort_order = optional_int(payload.get("sortOrder"), minimum=0, maximum=999, label="Sortierung") or 0
        now = utc_now()
        with self.database.transaction() as conn:
            self._season_belongs(conn, career_id, season_id)
            values = (season_id, kind, object_id, static_id, name, final_position, result_text, notes, sort_order, now)
            if competition_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_competitions(
                           manual_season_id,competition_type,competition_object_id,static_competition_id,
                           competition_name,final_position,result_text,notes,sort_order,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    values[:-1] + (now, now),
                )
                competition_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT c.* FROM manual_competitions c JOIN manual_seasons s ON s.id=c.manual_season_id
                       WHERE c.id=? AND s.career_id=?""",
                    (competition_id, career_id),
                ).fetchone()
                if not existing:
                    raise ValueError("Historical competition not found.")
                conn.execute(
                    """UPDATE manual_competitions SET manual_season_id=?,competition_type=?,competition_object_id=?,
                           static_competition_id=?,competition_name=?,final_position=?,result_text=?,notes=?,
                           sort_order=?,updated_at=? WHERE id=?""",
                    values + (competition_id,),
                )
                action = "update"
            self._log(conn, career_id, action, "competition", competition_id, payload)
            row = conn.execute("SELECT * FROM manual_competitions WHERE id=?", (competition_id,)).fetchone()
        return dict(row)

    def delete_competition(self, career_id: int, competition_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT c.* FROM manual_competitions c JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE c.id=? AND s.career_id=?""",
                (competition_id, career_id),
            ).fetchone()
            if not row:
                raise ValueError("Historical competition not found.")
            self._log(conn, career_id, "delete", "competition", competition_id, dict(row))
            conn.execute("DELETE FROM manual_competitions WHERE id=?", (competition_id,))
        return {"ok": True, "id": competition_id}

    def save_stat(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        stat_id = optional_int(payload.get("id"), minimum=1, label="Statistik-ID")
        competition_id = optional_int(payload.get("competitionId"), minimum=1, label="Competitions-ID")
        if competition_id is None:
            raise ValueError("Competition is missing.")
        player_id = optional_int(payload.get("playerEaId"), minimum=1, label="Player ID")
        display_name = clean_text(payload.get("displayName"), required=True, label="Player name")
        player_key = f"ea:{player_id}" if player_id is not None else f"name:{normalized_key(display_name or '')}"
        appearances = optional_int(payload.get("appearances"), minimum=0, maximum=999, label="Appearances") or 0
        goals = optional_int(payload.get("goals"), minimum=0, maximum=999, label="goals") or 0
        assists = optional_int(payload.get("assists"), minimum=0, maximum=999, label="Vorlagen") or 0
        clean_sheets = optional_int(payload.get("cleanSheets"), minimum=0, maximum=999, label="Clean sheets") or 0
        average_rating = optional_float(payload.get("averageRating"), minimum=1, maximum=10, label="Durchschnittsbewertung")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=1000)
        now = utc_now()
        with self.database.transaction() as conn:
            self._competition_belongs(conn, career_id, competition_id)
            upserted_existing = False
            if stat_id is None:
                existing = conn.execute(
                    "SELECT id FROM manual_player_stats WHERE manual_competition_id=? AND player_key=?",
                    (competition_id, player_key),
                ).fetchone()
                stat_id = int(existing["id"]) if existing else None
                upserted_existing = existing is not None
            if stat_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_player_stats(
                           manual_competition_id,player_ea_id,player_key,display_name,appearances,goals,
                           assists,clean_sheets,average_rating,notes,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (competition_id, player_id, player_key, display_name, appearances, goals, assists,
                     clean_sheets, average_rating, notes, now, now),
                )
                stat_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT ps.* FROM manual_player_stats ps
                       JOIN manual_competitions c ON c.id=ps.manual_competition_id
                       JOIN manual_seasons s ON s.id=c.manual_season_id
                       WHERE ps.id=? AND s.career_id=?""",
                    (stat_id, career_id),
                ).fetchone()
                if not existing:
                    raise ValueError("Historical player statistic not found.")
                conn.execute(
                    """UPDATE manual_player_stats SET manual_competition_id=?,player_ea_id=?,player_key=?,
                           display_name=?,appearances=?,goals=?,assists=?,clean_sheets=?,average_rating=?,
                           notes=?,updated_at=? WHERE id=?""",
                    (competition_id, player_id, player_key, display_name, appearances, goals, assists,
                     clean_sheets, average_rating, notes, now, stat_id),
                )
                action = "update"
            self._log(conn, career_id, action, "player_stat", stat_id, payload)
            row = conn.execute("SELECT * FROM manual_player_stats WHERE id=?", (stat_id,)).fetchone()
        result = dict(row)
        result["upsertedExisting"] = upserted_existing
        return result

    def delete_stat(self, career_id: int, stat_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT ps.* FROM manual_player_stats ps
                   JOIN manual_competitions c ON c.id=ps.manual_competition_id
                   JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE ps.id=? AND s.career_id=?""",
                (stat_id, career_id),
            ).fetchone()
            if not row:
                raise ValueError("Historical player statistic not found.")
            self._log(conn, career_id, "delete", "player_stat", stat_id, dict(row))
            conn.execute("DELETE FROM manual_player_stats WHERE id=?", (stat_id,))
        return {"ok": True, "id": stat_id}

    def _resolve_transaction_season(self, conn: Any, career_id: int, payload: dict[str, Any]):
        season_id = optional_int(payload.get("seasonId"), minimum=1, label="Season ID")
        if season_id is not None:
            return self._season_belongs(conn, career_id, season_id)
        season_index = optional_int(payload.get("seasonIndex"), minimum=0, maximum=99, label="Season number")
        if season_index is None:
            raise ValueError("Historical season is missing.")
        existing = conn.execute(
            """SELECT * FROM manual_seasons WHERE career_id=? AND season_index=?
               ORDER BY is_system_overlay,id LIMIT 1""",
            (career_id, season_index),
        ).fetchone()
        if existing:
            return existing
        snap = conn.execute(
            """SELECT career_date,managed_team_ea_id,managed_team_name FROM snapshots
               WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC LIMIT 1""",
            (career_id, season_index),
        ).fetchone()
        if not snap:
            raise ValueError("The selected season was not found.")
        career_date = str(snap["career_date"] or "")
        try:
            year, month = int(career_date[:4]), int(career_date[5:7])
            start_year = year if month >= 7 else year - 1
        except (TypeError, ValueError):
            start_year = 2000 + season_index
        now = utc_now()
        label = f"{start_year}/{str(start_year + 1)[-2:]}"
        cursor = conn.execute(
            """INSERT INTO manual_seasons(career_id,season_index,label,start_year,end_year,
                   managed_team_ea_id,managed_team_name,notes,is_system_overlay,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,1,?,?)""",
            (career_id, season_index, label, start_year, start_year + 1,
             snap["managed_team_ea_id"], snap["managed_team_name"],
             "Created automatically for manual transfers and loans in an imported season.", now, now),
        )
        return conn.execute("SELECT * FROM manual_seasons WHERE id=?", (int(cursor.lastrowid),)).fetchone()

    def save_transaction(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        transaction_id = optional_int(payload.get("id"), minimum=1, label="Vorgangs-ID")
        transaction_type = str(payload.get("transactionType") or "transfer").strip().lower()
        if transaction_type not in {"transfer", "loan"}:
            raise ValueError("Record type must be transfer or loan.")
        direction = str(payload.get("direction") or "incoming").strip().lower()
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("Direction must be incoming or outgoing.")
        player_id = optional_int(payload.get("playerEaId"), minimum=1, label="Player ID")
        display_name = clean_text(payload.get("displayName"), required=True, label="Player name")
        player_key = f"ea:{player_id}" if player_id is not None else f"name:{normalized_key(display_name or '')}"
        counterparty_id = optional_int(payload.get("counterpartyTeamEaId"), minimum=1, label="Club ID")
        counterparty_name = clean_text(payload.get("counterpartyTeamName"), required=True, label="Partnerverein")
        fee_unknown = str(payload.get("feeUnknown") or "").strip().lower() in {"1", "true", "on", "yes"}
        fee = None if fee_unknown else optional_int(payload.get("fee"), minimum=0, label="Transfer fee")
        currency = clean_text(payload.get("currency"), label="Currency", max_length=8) or "EUR"
        transaction_date = optional_iso_date(payload.get("transactionDate"), label="Datum")
        loan_end_date = optional_iso_date(payload.get("loanEndDate"), label="Loan end date")
        if transaction_type == "loan" and transaction_date and loan_end_date and loan_end_date < transaction_date:
            raise ValueError("Loan end must not precede its start.")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=2000)
        now = utc_now()
        with self.database.transaction() as conn:
            season = self._resolve_transaction_season(conn, career_id, payload)
            season_id = int(season["id"])
            own_id = season["managed_team_ea_id"]
            own_name = season["managed_team_name"] or "Managed club"
            if own_id is not None and counterparty_id is not None and int(own_id) == int(counterparty_id):
                raise ValueError("The partner club must not be the managed club.")
            if normalized_key(str(own_name)) and normalized_key(str(own_name)) == normalized_key(str(counterparty_name)):
                raise ValueError("The partner club must not be the managed club.")
            if direction == "incoming":
                from_id, from_name, to_id, to_name = counterparty_id, counterparty_name, own_id, own_name
            else:
                from_id, from_name, to_id, to_name = own_id, own_name, counterparty_id, counterparty_name
            values = (season_id, transaction_type, direction, player_id, player_key, display_name,
                      from_id, from_name, to_id, to_name, fee, currency, transaction_date,
                      loan_end_date if transaction_type == "loan" else None, notes, now)
            if transaction_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_transactions(
                           manual_season_id,transaction_type,direction,player_ea_id,player_key,display_name,
                           from_team_ea_id,from_team_name,to_team_ea_id,to_team_name,fee,currency,
                           transaction_date,loan_end_date,notes,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values[:-1] + (now, now),
                )
                transaction_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT t.* FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                       WHERE t.id=? AND s.career_id=?""",
                    (transaction_id, career_id),
                ).fetchone()
                if not existing:
                    raise ValueError("Historical transfer or loan record not found.")
                conn.execute(
                    """UPDATE manual_transactions SET manual_season_id=?,transaction_type=?,direction=?,
                           player_ea_id=?,player_key=?,display_name=?,from_team_ea_id=?,from_team_name=?,
                           to_team_ea_id=?,to_team_name=?,fee=?,currency=?,transaction_date=?,loan_end_date=?,
                           notes=?,updated_at=? WHERE id=?""",
                    values + (transaction_id,),
                )
                action = "update"
            self._log(conn, career_id, action, "transaction", transaction_id, payload)
            row = conn.execute("SELECT * FROM manual_transactions WHERE id=?", (transaction_id,)).fetchone()
        return dict(row)

    def delete_transaction(self, career_id: int, transaction_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT t.* FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                   WHERE t.id=? AND s.career_id=?""",
                (transaction_id, career_id),
            ).fetchone()
            if not row:
                raise ValueError("Historical transfer or loan record not found.")
            self._log(conn, career_id, "delete", "transaction", transaction_id, dict(row))
            conn.execute("DELETE FROM manual_transactions WHERE id=?", (transaction_id,))
        return {"ok": True, "id": transaction_id}

    def save_league_finish(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        finish_id = optional_int(payload.get("id"), minimum=1, label="Platzierungs-ID")
        season_id = optional_int(payload.get("seasonId"), minimum=1, label="Season ID")
        if season_id is None:
            raise ValueError("Historical season is missing.")
        team_id = optional_int(payload.get("teamEaId"), minimum=1, label="Team-ID")
        team_name = clean_text(payload.get("teamName"), required=True, label="Club name")
        team_key = f"ea:{team_id}" if team_id is not None else f"name:{normalized_key(team_name or '')}"
        league_id = optional_int(payload.get("leagueEaId"), minimum=1, label="Liga-ID")
        league_name = clean_text(payload.get("leagueName"), required=True, label="Liga")
        final_position = optional_int(payload.get("finalPosition"), minimum=1, maximum=999, label="Final position")
        if final_position is None:
            raise ValueError("Final position is missing.")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=2000)
        now = utc_now()
        with self.database.transaction() as conn:
            self._season_belongs(conn, career_id, season_id)
            values = (season_id, team_id, team_key, team_name, league_id, league_name, final_position, notes, now)
            upserted_existing = False
            if finish_id is None:
                existing = conn.execute(
                    "SELECT id FROM manual_league_finishes WHERE manual_season_id=? AND team_key=?",
                    (season_id, team_key),
                ).fetchone()
                if existing:
                    finish_id = int(existing["id"])
                    upserted_existing = True
            if finish_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_league_finishes(
                           manual_season_id,team_ea_id,team_key,team_name,league_ea_id,league_name,
                           final_position,notes,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    values[:-1] + (now, now),
                )
                finish_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT lf.* FROM manual_league_finishes lf
                       JOIN manual_seasons s ON s.id=lf.manual_season_id
                       WHERE lf.id=? AND s.career_id=?""",
                    (finish_id, career_id),
                ).fetchone()
                if not existing:
                    raise ValueError("Historical league finish not found.")
                conn.execute(
                    """UPDATE manual_league_finishes SET manual_season_id=?,team_ea_id=?,team_key=?,
                           team_name=?,league_ea_id=?,league_name=?,final_position=?,notes=?,updated_at=?
                       WHERE id=?""",
                    values + (finish_id,),
                )
                action = "update"
            self._log(conn, career_id, action, "league_finish", finish_id, payload)
            row = conn.execute("SELECT * FROM manual_league_finishes WHERE id=?", (finish_id,)).fetchone()
        result = dict(row)
        result["upsertedExisting"] = upserted_existing
        return result

    def delete_league_finish(self, career_id: int, finish_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT lf.* FROM manual_league_finishes lf
                   JOIN manual_seasons s ON s.id=lf.manual_season_id
                   WHERE lf.id=? AND s.career_id=?""",
                (finish_id, career_id),
            ).fetchone()
            if not row:
                raise ValueError("Historical league finish not found.")
            self._log(conn, career_id, "delete", "league_finish", finish_id, dict(row))
            conn.execute("DELETE FROM manual_league_finishes WHERE id=?", (finish_id,))
        return {"ok": True, "id": finish_id}

    def player_history(self, career_id: int, player_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT ps.*,c.competition_name,c.competition_type,c.final_position,c.result_text,
                          s.season_index,s.label season_label,s.start_year,s.end_year
                   FROM manual_player_stats ps
                   JOIN manual_competitions c ON c.id=ps.manual_competition_id
                   JOIN manual_seasons s ON s.id=c.manual_season_id
                   WHERE s.career_id=? AND ps.player_ea_id=?
                   ORDER BY s.season_index,c.sort_order,c.id""",
                (career_id, player_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _resolve_development_season(self, conn: Any, career_id: int, payload: dict[str, Any]):
        season_id = optional_int(payload.get("seasonId"), minimum=1, label="Season ID")
        selection = str(payload.get("seasonSelection") or "").strip()
        if season_id is not None:
            return self._season_belongs(conn, career_id, season_id)
        if selection.startswith("manual:"):
            return self._season_belongs(conn, career_id, int(selection.split(":", 1)[1]))
        if not selection.startswith("snapshot:"):
            raise ValueError("Season is missing.")
        parts = selection.split(":")
        if len(parts) != 3:
            raise ValueError("Season selection is invalid.")
        season_index = int(parts[1])
        start_year = int(parts[2])
        existing = conn.execute(
            "SELECT * FROM manual_seasons WHERE career_id=? AND start_year=? ORDER BY is_system_overlay,id LIMIT 1",
            (career_id, start_year),
        ).fetchone()
        if existing:
            return existing
        snap = conn.execute(
            """SELECT managed_team_ea_id,managed_team_name FROM snapshots
               WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC LIMIT 1""",
            (career_id, season_index),
        ).fetchone()
        now = utc_now()
        label = f"{start_year}/{str(start_year + 1)[-2:]}"
        cursor = conn.execute(
            """INSERT INTO manual_seasons(career_id,season_index,label,start_year,end_year,
                   managed_team_ea_id,managed_team_name,notes,is_system_overlay,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,1,?,?)""",
            (career_id, season_index, label, start_year, start_year + 1,
             snap["managed_team_ea_id"] if snap else None, snap["managed_team_name"] if snap else None,
             "Created automatically for manual additions to an imported season.", now, now),
        )
        return conn.execute("SELECT * FROM manual_seasons WHERE id=?", (int(cursor.lastrowid),)).fetchone()

    def save_development(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        development_id = optional_int(payload.get("id"), minimum=1, label="Entwicklungs-ID")
        player_id = optional_int(payload.get("playerEaId"), minimum=1, label="Player ID")
        if player_id is None:
            raise ValueError("Player ID is missing.")
        display_name = clean_text(payload.get("displayName"), required=True, label="Player name")
        player_key = f"ea:{player_id}"
        stage = str(payload.get("stage") or "season_start").strip().lower()
        if stage not in {"season_start", "season_mid", "season_end", "custom"}:
            raise ValueError("Date is invalid.")
        labels = {"season_start": "Season start", "season_mid": "Mid-season", "season_end": "Season end"}
        stage_label = clean_text(payload.get("stageLabel"), label="Bezeichnung", max_length=80) or labels.get(stage) or "Custom date"
        effective_date = optional_iso_date(payload.get("effectiveDate"), label="Stichtag")
        overall = optional_int(payload.get("overall"), minimum=1, maximum=99, label="OVR")
        potential = optional_int(payload.get("potential"), minimum=1, maximum=99, label="POT")
        if overall is None or potential is None:
            raise ValueError("OVR and POT must both be entered.")
        if potential < overall:
            raise ValueError("POT must not be lower than OVR.")
        notes = clean_text(payload.get("notes"), label="Notizen", max_length=1000)
        now = utc_now()
        with self.database.transaction() as conn:
            if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                raise ValueError("Career not found.")
            season = self._resolve_development_season(conn, career_id, payload)
            season_id = int(season["id"])
            if effective_date is None:
                if stage == "season_start":
                    effective_date = f"{int(season['start_year']):04d}-07-01"
                elif stage == "season_mid":
                    effective_date = f"{int(season['end_year']):04d}-01-01"
                elif stage == "season_end":
                    effective_date = f"{int(season['end_year']):04d}-06-30"
                else:
                    raise ValueError("A custom point in time requires a date.")
            upserted_existing = False
            if development_id is None:
                existing = conn.execute(
                    "SELECT id FROM manual_player_development WHERE manual_season_id=? AND player_key=? AND effective_date=?",
                    (season_id, player_key, effective_date),
                ).fetchone()
                if existing:
                    development_id = int(existing["id"])
                    upserted_existing = True
            values = (season_id, player_id, player_key, display_name, stage, stage_label, effective_date, overall, potential, notes, now)
            if development_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_player_development(
                           manual_season_id,player_ea_id,player_key,display_name,stage,stage_label,effective_date,
                           overall,potential,notes,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values[:-1] + (now, now),
                )
                development_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT pd.* FROM manual_player_development pd
                       JOIN manual_seasons s ON s.id=pd.manual_season_id
                       WHERE pd.id=? AND s.career_id=?""",
                    (development_id, career_id),
                ).fetchone()
                if not existing:
                    raise ValueError("Historical development point not found.")
                conn.execute(
                    """UPDATE manual_player_development SET manual_season_id=?,player_ea_id=?,player_key=?,
                           display_name=?,stage=?,stage_label=?,effective_date=?,overall=?,potential=?,notes=?,updated_at=?
                       WHERE id=?""",
                    values + (development_id,),
                )
                action = "update"
            self._log(conn, career_id, action, "player_development", development_id, payload)
            row = conn.execute("SELECT * FROM manual_player_development WHERE id=?", (development_id,)).fetchone()
        result = dict(row)
        result["upsertedExisting"] = upserted_existing
        return result

    def delete_development(self, career_id: int, development_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT pd.* FROM manual_player_development pd
                   JOIN manual_seasons s ON s.id=pd.manual_season_id
                   WHERE pd.id=? AND s.career_id=?""",
                (development_id, career_id),
            ).fetchone()
            if not row:
                raise ValueError("Historical development point not found.")
            self._log(conn, career_id, "delete", "player_development", development_id, dict(row))
            conn.execute("DELETE FROM manual_player_development WHERE id=?", (development_id,))
        return {"ok": True, "id": development_id}

    AWARD_CATEGORIES = {
        "player_of_season": "Player of the Season",
        "newcomer": "Newcomer of the Season",
        "transfer_of_season": "Transfer of the Season",
        "goalkeeper_of_season": "Goalkeeper of the Season",
        "talent_of_season": "Young Player of the Season",
        "surprise_of_season": "Surprise of the Season",
        "ever_present": "Ever-present Player of the Season",
        "fan_favourite": "Fan Favourite",
        "comeback": "Comeback of the Season",
        "unsung_hero": "Unsung Hero",
    }

    def _season_awards_allowed(self, conn: Any, career_id: int, season: Any) -> tuple[bool, str]:
        """Use the same conservative season-close rule as the analysis read model."""
        start_year = optional_int(season["start_year"], minimum=1900, label="Start year")
        season_index = int(season["season_index"])
        snapshots = conn.execute(
            "SELECT id,season_index,career_date,managed_team_ea_id FROM snapshots WHERE career_id=? ORDER BY import_sequence",
            (career_id,),
        ).fetchall()
        if not snapshots:
            return False, "Season end cannot be confirmed without a snapshot."

        def snapshot_start_year(row: Any) -> int | None:
            text = str(row["career_date"] or "")
            try:
                year, month = int(text[:4]), int(text[5:7])
            except (TypeError, ValueError):
                return None
            return year if month >= 7 else year - 1

        if start_year is not None and any((snapshot_start_year(row) or -1) > start_year for row in snapshots):
            return True, "A later season has already been observed."
        if start_year is None and any(int(row["season_index"]) > season_index for row in snapshots):
            return True, "A later season has already been observed."

        matching = [
            row for row in snapshots
            if (start_year is not None and snapshot_start_year(row) == start_year)
            or (start_year is None and int(row["season_index"]) == season_index)
        ]
        latest = matching[-1] if matching else None
        if latest is not None:
            fixture = conn.execute(
                """SELECT COUNT(*) total,
                          SUM(CASE WHEN is_completed=1 THEN 1 ELSE 0 END) completed,
                          SUM(CASE WHEN is_completed=0 THEN 1 ELSE 0 END) open
                   FROM fixture_observations
                   WHERE snapshot_id=? AND managed_team_involved=1""",
                (latest["id"],),
            ).fetchone()
            total = int(fixture["total"] or 0)
            completed = int(fixture["completed"] or 0)
            open_count = int(fixture["open"] or 0)
            if total > 0 and completed > 0 and open_count == 0:
                return True, "All observed season matches are complete."

        return False, "Season awards can be assigned only after the final match of the season."

    def save_season_award(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        award_id = optional_int(payload.get("id"), minimum=1, label="Award-ID")
        award_key = clean_text(payload.get("awardKey"), required=True, label="Award-Kategorie", max_length=80)
        custom_label = clean_text(payload.get("awardLabel"), label="Award-Name", max_length=120)
        if award_key == "custom":
            if not custom_label:
                raise ValueError("A custom award requires a name.")
            normalized = normalized_key(custom_label).replace(" ", "-") or "award"
            award_key = f"custom:{normalized}"
            award_label = custom_label
        else:
            award_label = self.AWARD_CATEGORIES.get(award_key or "")
            if not award_label:
                raise ValueError("Award category is invalid.")
        player_id = optional_int(payload.get("playerEaId"), minimum=1, label="Player ID")
        display_name = clean_text(payload.get("displayName"), required=True, label="Player name")
        player_key = f"ea:{player_id}" if player_id is not None else f"name:{normalized_key(display_name or '')}"
        related_transaction_id = optional_int(payload.get("relatedTransactionId"), minimum=1, label="Transfer-ID")
        reason = clean_text(payload.get("reason"), label="Reason", max_length=2000)
        now = utc_now()
        with self.database.transaction() as conn:
            season = self._resolve_transaction_season(conn, career_id, payload)
            season_id = int(season["id"])
            allowed, reason_text = self._season_awards_allowed(conn, career_id, season)
            if not allowed:
                raise ValueError(reason_text)
            if related_transaction_id is not None:
                tx = conn.execute(
                    """SELECT t.id FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                       WHERE t.id=? AND s.career_id=?""",
                    (related_transaction_id, career_id),
                ).fetchone()
                if not tx:
                    raise ValueError("Related transfer was not found.")
            if award_id is None:
                existing = conn.execute(
                    "SELECT id FROM manual_season_awards WHERE manual_season_id=? AND award_key=?",
                    (season_id, award_key),
                ).fetchone()
                award_id = int(existing["id"]) if existing else None
            values = (season_id, award_key, award_label, player_id, player_key, display_name, related_transaction_id, reason, now)
            if award_id is None:
                cursor = conn.execute(
                    """INSERT INTO manual_season_awards(
                           manual_season_id,award_key,award_label,player_ea_id,player_key,display_name,
                           related_transaction_id,reason,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    values[:-1] + (now, now),
                )
                award_id = int(cursor.lastrowid)
                action = "create"
            else:
                existing = conn.execute(
                    """SELECT a.* FROM manual_season_awards a JOIN manual_seasons s ON s.id=a.manual_season_id
                       WHERE a.id=? AND s.career_id=?""", (award_id, career_id)
                ).fetchone()
                if not existing:
                    raise ValueError("Season award not found.")
                conn.execute(
                    """UPDATE manual_season_awards SET manual_season_id=?,award_key=?,award_label=?,
                           player_ea_id=?,player_key=?,display_name=?,related_transaction_id=?,reason=?,updated_at=?
                       WHERE id=?""", values + (award_id,)
                )
                action = "update"
            self._log(conn, career_id, action, "season_award", award_id, payload)
            row = conn.execute("SELECT * FROM manual_season_awards WHERE id=?", (award_id,)).fetchone()
        return dict(row)

    def delete_season_award(self, career_id: int, award_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                """SELECT a.* FROM manual_season_awards a JOIN manual_seasons s ON s.id=a.manual_season_id
                   WHERE a.id=? AND s.career_id=?""", (award_id, career_id)
            ).fetchone()
            if not row:
                raise ValueError("Season award not found.")
            self._log(conn, career_id, "delete", "season_award", award_id, dict(row))
            conn.execute("DELETE FROM manual_season_awards WHERE id=?", (award_id,))
        return {"ok": True, "id": award_id}

    def save_season_report_note(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        summary_note = clean_text(payload.get("summaryNote"), label="Season note", max_length=6000)
        now = utc_now()
        with self.database.transaction() as conn:
            season = self._resolve_transaction_season(conn, career_id, payload)
            season_id = int(season["id"])
            conn.execute(
                """INSERT INTO manual_season_reports(manual_season_id,summary_note,created_at,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(manual_season_id) DO UPDATE SET summary_note=excluded.summary_note,updated_at=excluded.updated_at""",
                (season_id, summary_note, now, now),
            )
            self._log(conn, career_id, "update", "season_report", season_id, payload)
            row = conn.execute("SELECT * FROM manual_season_reports WHERE manual_season_id=?", (season_id,)).fetchone()
        return dict(row)

    def create_backup(self, label: str = "manual") -> dict[str, Any]:
        path = self.database.create_backup(label=label)
        return {"ok": True, "path": str(path), "name": path.name, "size": path.stat().st_size}

    def _season_belongs(self, conn: Any, career_id: int, season_id: int):
        row = conn.execute("SELECT * FROM manual_seasons WHERE id=? AND career_id=?", (season_id, career_id)).fetchone()
        if not row:
            raise ValueError("Historical season not found.")
        return row

    def _competition_belongs(self, conn: Any, career_id: int, competition_id: int):
        row = conn.execute(
            """SELECT c.* FROM manual_competitions c JOIN manual_seasons s ON s.id=c.manual_season_id
               WHERE c.id=? AND s.career_id=?""",
            (competition_id, career_id),
        ).fetchone()
        if not row:
            raise ValueError("Historical competition not found.")
        return row

    @staticmethod
    def _log(conn: Any, career_id: int, action: str, entity_type: str, entity_id: int, details: dict[str, Any]) -> None:
        conn.execute(
            """INSERT INTO manual_change_log(
                   career_id,occurred_at,action,entity_type,entity_id,details_json)
               VALUES(?,?,?,?,?,?)""",
            (career_id, utc_now(), action, entity_type, entity_id, json.dumps(details, ensure_ascii=False, default=str)),
        )
