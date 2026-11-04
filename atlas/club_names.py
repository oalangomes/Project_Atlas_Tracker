from __future__ import annotations

from typing import Any

from .finance_core import utc_now
from .server_utils import as_int


NAME_PAIRS = (
    ("ea_team_id", "team_name"),
    ("team_id", "team_name"),
    ("team_ea_id", "team_name"),
    ("club_id", "club_name"),
    ("managed_team_ea_id", "managed_team_name"),
    ("initial_team_ea_id", "initial_team_name"),
    ("home_team_ea_id", "home_team_name"),
    ("away_team_ea_id", "away_team_name"),
    ("from_team_ea_id", "from_team_name"),
    ("to_team_ea_id", "to_team_name"),
    ("parent_team_ea_id", "parent_team_name"),
    ("loan_team_ea_id", "loan_team_name"),
    ("represented_team_ea_id", "represented_team_name"),
    ("current_club_ea_id", "current_club_name"),
    ("eaTeamId", "teamName"),
    ("teamId", "teamName"),
    ("teamEaId", "teamName"),
    ("clubId", "clubName"),
    ("managedTeamEaId", "managedTeamName"),
    ("initialTeamEaId", "initialTeamName"),
    ("homeTeamEaId", "homeTeamName"),
    ("awayTeamEaId", "awayTeamName"),
    ("fromTeamEaId", "fromTeamName"),
    ("toTeamEaId", "toTeamName"),
    ("currentClubEaId", "currentClubName"),
    ("clubEaId", "clubName"),
)


class ClubNameService:
    def __init__(self, database):
        self.database = database

    def mapping(self, career_id: int) -> dict[int, str]:
        with self.database.connect() as conn:
            return {
                int(row["ea_team_id"]): str(row["display_name"])
                for row in conn.execute(
                    "SELECT ea_team_id,display_name FROM team_name_overrides WHERE career_id=?",
                    (career_id,),
                ).fetchall()
            }

    def list(self, career_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            latest = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1",
                (career_id,),
            ).fetchone()
            teams = conn.execute(
                "SELECT ea_team_id,team_name,league_name FROM team_states WHERE snapshot_id=? ORDER BY team_name",
                (latest["id"],),
            ).fetchall() if latest else []
            overrides = {
                int(row["ea_team_id"]): dict(row)
                for row in conn.execute("SELECT * FROM team_name_overrides WHERE career_id=?", (career_id,)).fetchall()
            }
        items = []
        for row in teams:
            override = overrides.get(int(row["ea_team_id"]))
            items.append({
                "eaTeamId": row["ea_team_id"], "originalName": row["team_name"],
                "displayName": override["display_name"] if override else row["team_name"],
                "leagueName": row["league_name"], "overridden": bool(override),
                "note": override.get("note") if override else None,
            })
        return {"items": items, "overrideCount": len(overrides)}

    def save(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        team_id = as_int(payload.get("eaTeamId"))
        display_name = str(payload.get("displayName") or "").strip()
        note = str(payload.get("note") or "").strip() or None
        if team_id is None or team_id <= 0:
            raise ValueError("Club ID is missing.")
        if not display_name:
            raise ValueError("The displayed club name must not be empty.")
        now = utc_now()
        with self.database.transaction() as conn:
            if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
                raise ValueError("Career not found.")
            if not conn.execute(
                "SELECT 1 FROM team_states ts JOIN snapshots s ON s.id=ts.snapshot_id "
                "WHERE s.career_id=? AND ts.ea_team_id=? LIMIT 1",
                (career_id, team_id),
            ).fetchone():
                raise ValueError("Club not found.")
            conn.execute(
                "INSERT INTO team_name_overrides(career_id,ea_team_id,display_name,note,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(career_id,ea_team_id) DO UPDATE SET "
                "display_name=excluded.display_name,note=excluded.note,updated_at=excluded.updated_at",
                (career_id, team_id, display_name, note, now, now),
            )
        return {"ok": True, "eaTeamId": team_id, "displayName": display_name, "applied": True}

    def delete(self, career_id: int, team_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM team_name_overrides WHERE career_id=? AND ea_team_id=?", (career_id, team_id))
        return {"ok": True, "eaTeamId": team_id}

    def apply_payload(self, payload: Any, career_id: int | None) -> Any:
        if career_id is None:
            return payload
        aliases = self.mapping(career_id)
        if not aliases:
            return payload

        def visit(value: Any) -> Any:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return value
            if not isinstance(value, dict):
                return value
            for id_key, name_key in NAME_PAIRS:
                team_id = as_int(value.get(id_key))
                if team_id is not None and team_id in aliases:
                    if name_key in value and f"{name_key}_original" not in value:
                        value[f"{name_key}_original"] = value.get(name_key)
                    value[name_key] = aliases[team_id]
            if value.get("type") == "club":
                team_id = as_int(value.get("id"))
                if team_id is not None and team_id in aliases:
                    value.setdefault("originalLabel", value.get("label"))
                    value["label"] = aliases[team_id]
            for nested in list(value.values()):
                visit(nested)
            return value

        return visit(payload)
