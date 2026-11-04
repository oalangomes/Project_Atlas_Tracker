from __future__ import annotations

import json
import re
from typing import Any

from .server_utils import as_int, input_bool, parse_raw
from .paths import global_settings_path

DEFAULTS = {
    "hideWomensFootball": False,
    "language": "pt-BR",
}

LANGUAGES = {"pt-BR", "en-GB", "es-ES"}


def normalize_language(value: Any) -> str:
    language = str(value or "").strip()
    return language if language in LANGUAGES else DEFAULTS["language"]


def application_language() -> str:
    """Read the installation-wide Atlas language without opening a career database."""
    path = global_settings_path()
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return normalize_language(value.get("language"))
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULTS["language"]

_WOMEN_MARKERS = (
    "women", "woman", "female", "frauen", "damen", "fémin", "feminin",
    "femmin", "femen", "femin", "wsl", "nwsl", "liga f", "division 1 feminine",
)


class SettingsService:
    """Small global application settings store and presentation filter.

    Snapshot rows remain immutable. Visibility settings only affect derived models and
    API responses; they never delete or rewrite imported data.
    """

    def __init__(self, database):
        self.database = database

    def _read_global_payload(self) -> dict[str, Any]:
        path = global_settings_path()
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except (OSError, json.JSONDecodeError):
                pass
        # One-time migration from a previously opened workspace database.
        try:
            with self.database.connect() as conn:
                row = conn.execute("SELECT value FROM app_meta WHERE key='application_settings'").fetchone()
            if row:
                raw = json.loads(row["value"])
                if isinstance(raw, dict):
                    self._write_global_payload(raw)
                    return raw
        except Exception:
            pass
        return {}

    @staticmethod
    def _write_global_payload(value: dict[str, Any]) -> None:
        path = global_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    def get(self) -> dict[str, Any]:
        value = self._read_global_payload()
        result = dict(DEFAULTS)
        if "hideWomensFootball" in value:
            try:
                result["hideWomensFootball"] = input_bool(value.get("hideWomensFootball"), "Hide women's football")
            except ValueError:
                result["hideWomensFootball"] = DEFAULTS["hideWomensFootball"]
        result["language"] = normalize_language(value.get("language", result["language"]))
        return result

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get()
        old_visibility = current["hideWomensFootball"]
        if "hideWomensFootball" in payload:
            current["hideWomensFootball"] = input_bool(payload.get("hideWomensFootball"), "Hide women's football")
        if "language" in payload:
            language = str(payload.get("language") or "").strip()
            if language not in LANGUAGES:
                raise ValueError("Language must be pt-BR, en-GB or es-ES.")
            current["language"] = language
        self._write_global_payload(current)
        # Visibility changes alter derived presentation/simulation state in the
        # currently open career only; the preference itself is installation-global.
        if old_visibility != current["hideWomensFootball"]:
            with self.database.transaction() as conn:
                conn.execute("DELETE FROM atlas_world_simulation_runs")
        return current

    @staticmethod
    def _bounded_int(value: Any, low: int, high: int, label: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} is invalid.") from exc
        if not low <= number <= high:
            raise ValueError(f"{label} must be between {low} and {high}.")
        return number

    @staticmethod
    def _bounded_float(value: Any, low: float, high: float, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} is invalid.") from exc
        if not low <= number <= high:
            raise ValueError(f"{label} must be between {low} and {high}.")
        return round(number, 2)

    def hide_womens_football(self) -> bool:
        return bool(self.get().get("hideWomensFootball"))

    @staticmethod
    def _name_looks_women(value: Any) -> bool:
        text = re.sub(r"\s+", " ", str(value or "").casefold()).strip()
        return bool(text and any(marker in text for marker in _WOMEN_MARKERS))

    def hidden_ids(self, *, career_id: int | None = None, snapshot_id: int | None = None) -> dict[str, set[int]]:
        result = {"teams": set(), "players": set(), "leagues": set(), "competitions": set()}
        if not self.hide_womens_football():
            return result
        with self.database.connect() as conn:
            if snapshot_id is None and career_id is not None:
                row = conn.execute(
                    "SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1",
                    (career_id,),
                ).fetchone()
                snapshot_id = int(row["id"]) if row else None
            if snapshot_id is None:
                return result
            team_rows = conn.execute(
                "SELECT ea_team_id,league_ea_id,team_name,league_name,gender,raw_json FROM team_states WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            league_members: dict[int, list[bool]] = {}
            for row in team_rows:
                raw = parse_raw(row["raw_json"])
                is_women = as_int(row["gender"]) == 1 or as_int(raw.get("gender")) == 1 or self._name_looks_women(row["team_name"])
                team_id = as_int(row["ea_team_id"])
                league_id = as_int(row["league_ea_id"])
                if team_id is not None and is_women:
                    result["teams"].add(team_id)
                if league_id is not None:
                    league_members.setdefault(league_id, []).append(is_women)
            for league_id, flags in league_members.items():
                if flags and all(flags):
                    result["leagues"].add(league_id)
            for row in conn.execute(
                "SELECT ea_player_id,team_ea_id,display_name,raw_json FROM player_states WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall():
                raw = parse_raw(row["raw_json"])
                player_id = as_int(row["ea_player_id"])
                team_id = as_int(row["team_ea_id"])
                if player_id is not None and (
                    as_int(raw.get("gender")) == 1
                    or team_id in result["teams"]
                    or self._name_looks_women(raw.get("league_name"))
                ):
                    result["players"].add(player_id)
            competition_rows = conn.execute(
                "SELECT competition_object_id,competition_name FROM competition_states WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            for row in competition_rows:
                competition_id = as_int(row["competition_object_id"])
                if competition_id is not None and self._name_looks_women(row["competition_name"]):
                    result["competitions"].add(competition_id)
            fixture_rows = conn.execute(
                "SELECT DISTINCT f.competition_object_id,f.home_team_ea_id,f.away_team_ea_id "
                "FROM fixtures f JOIN fixture_observations fo ON fo.fixture_id=f.id WHERE fo.snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            participants: dict[int, set[int]] = {}
            for row in fixture_rows:
                competition_id = as_int(row["competition_object_id"])
                if competition_id is None:
                    continue
                bucket = participants.setdefault(competition_id, set())
                for value in (row["home_team_ea_id"], row["away_team_ea_id"]):
                    team_id = as_int(value)
                    if team_id is not None:
                        bucket.add(team_id)
            for competition_id, team_ids in participants.items():
                if team_ids and all(team_id in result["teams"] for team_id in team_ids):
                    result["competitions"].add(competition_id)
        return result

    def apply_payload(self, payload: Any, *, career_id: int | None = None, snapshot_id: int | None = None) -> Any:
        ids = self.hidden_ids(career_id=career_id, snapshot_id=snapshot_id)
        if not any(ids.values()):
            return payload

        player_keys = ("ea_player_id", "player_ea_id", "playerId", "playerEaId")
        team_keys = (
            "ea_team_id", "team_ea_id", "team_id", "teamId", "teamEaId", "eaTeamId",
            "club_id", "clubId", "clubEaId", "represented_team_ea_id", "current_club_ea_id",
            "managed_team_ea_id", "initial_team_ea_id", "managedTeamEaId", "initialTeamEaId",
            "home_team_ea_id", "away_team_ea_id", "from_team_ea_id", "to_team_ea_id",
            "parent_team_ea_id", "loan_team_ea_id",
        )
        competition_keys = ("competition_object_id", "competitionId", "competitionObjectId")
        league_keys = ("league_ea_id", "leagueEaId")

        def hidden_dict(value: dict[str, Any]) -> bool:
            for key in player_keys:
                player_id = as_int(value.get(key))
                if player_id is not None and player_id in ids["players"]:
                    return True
            team_values = {as_int(value.get(key)) for key in team_keys if as_int(value.get(key)) is not None}
            if team_values and all(team_id in ids["teams"] for team_id in team_values):
                return True
            for key in competition_keys:
                competition_id = as_int(value.get(key))
                if competition_id is not None and competition_id in ids["competitions"]:
                    return True
            for key in league_keys:
                league_id = as_int(value.get(key))
                if league_id is not None and league_id in ids["leagues"]:
                    return True
            if as_int(value.get("gender")) == 1:
                return True
            kind = str(value.get("type") or "")
            entity_id = as_int(value.get("id"))
            if kind == "player" and entity_id in ids["players"]:
                return True
            if kind == "club" and entity_id in ids["teams"]:
                return True
            if kind == "competition" and entity_id in ids["competitions"]:
                return True
            return False

        def visit(value: Any) -> Any:
            if isinstance(value, list):
                filtered = []
                for item in value:
                    if isinstance(item, dict) and hidden_dict(item):
                        continue
                    filtered.append(visit(item))
                value[:] = filtered
                return value
            if isinstance(value, dict):
                for key, nested in list(value.items()):
                    value[key] = visit(nested)
                return value
            return value

        return visit(payload)
