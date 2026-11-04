from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from typing import Any

from .competition_rules import qualification_state


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _team_league_name(conn: sqlite3.Connection, snapshot_id: int, team_id: int) -> str:
    row = conn.execute(
        "SELECT league_name FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
        (snapshot_id, team_id),
    ).fetchone()
    return str(row[0] or "") if row else ""


def competition_category(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
    competition_name: str | None,
) -> str:
    name = _key(competition_name)
    league = _key(_team_league_name(conn, snapshot_id, team_id))
    if name and league and (name == league or name in league or league in name):
        return "league"
    continental_tokens = (
        "champions league", "europa league", "conference league", "uefa",
        "champions cup", "libertadores", "sudamericana", "continental",
    )
    if any(token in name for token in continental_tokens):
        return "continental"
    cup_tokens = (" cup", "cup ", "pokal", "coppa", "copa", "coupe", "trophy", "fa cup", "dfb")
    if any(token in f" {name} " for token in cup_tokens):
        return "domestic_cup"
    return "other"


def scope_matches(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
    competition_name: str | None,
    scope: str | None,
) -> bool:
    normalized = str(scope or "").strip().casefold()
    if normalized in {"", "all", "all_competitions", "alle", "pflichtspiele"}:
        return True
    if normalized not in {"league", "domestic_cup", "continental"}:
        return False
    return competition_category(conn, snapshot_id, team_id, competition_name) == normalized


def scoped_player_stats(
    conn: sqlite3.Connection,
    snapshot_id: int,
    player_id: int,
    team_id: int,
    competition_scope: str | None = None,
) -> dict[str, int]:
    rows = conn.execute(
        "SELECT appearances,goals,assists,clean_sheets,saves,competition_name "
        "FROM season_stat_states WHERE snapshot_id=? AND player_ea_id=? AND represented_team_ea_id=?",
        (snapshot_id, player_id, team_id),
    ).fetchall()
    result = {"appearances": 0, "goals": 0, "assists": 0, "goal_contributions": 0, "clean_sheets": 0, "saves": 0, "starts": 0, "minutes": 0}
    for row in rows:
        if not scope_matches(conn, snapshot_id, team_id, row["competition_name"], competition_scope):
            continue
        result["appearances"] += int(row["appearances"] or 0)
        result["goals"] += int(row["goals"] or 0)
        result["assists"] += int(row["assists"] or 0)
        result["clean_sheets"] += int(row["clean_sheets"] or 0)
        result["saves"] += int(row["saves"] or 0)
    result["goal_contributions"] = result["goals"] + result["assists"]

    perf_rows = conn.execute(
        "SELECT p.minutes_played,COALESCE(fo.competition_name,cs.competition_name,'') competition_name "
        "FROM player_match_performances p "
        "LEFT JOIN fixtures f ON f.career_id=(SELECT career_id FROM snapshots WHERE id=p.snapshot_id) AND f.fixture_key=p.fixture_key "
        "LEFT JOIN fixture_observations fo ON fo.snapshot_id=p.snapshot_id AND fo.fixture_id=f.id "
        "LEFT JOIN competition_states cs ON cs.snapshot_id=p.snapshot_id AND cs.competition_object_id=f.competition_object_id "
        "WHERE p.snapshot_id=? AND p.player_ea_id=? AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)",
        (snapshot_id, player_id, team_id, team_id),
    ).fetchall()
    for row in perf_rows:
        if not scope_matches(conn, snapshot_id, team_id, row["competition_name"], competition_scope):
            continue
        minutes = int(row["minutes_played"] or 0)
        result["minutes"] += minutes
        if minutes >= 60:
            result["starts"] += 1
    return result


def appearances_with_minimum_minutes(
    conn: sqlite3.Connection,
    snapshot_id: int,
    player_id: int,
    team_id: int,
    minimum_minutes: int,
    competition_scope: str | None = None,
) -> int:
    rows = conn.execute(
        "SELECT p.fixture_key,p.minutes_played,COALESCE(fo.competition_name,cs.competition_name,'') competition_name "
        "FROM player_match_performances p "
        "LEFT JOIN fixtures f ON f.career_id=(SELECT career_id FROM snapshots WHERE id=p.snapshot_id) AND f.fixture_key=p.fixture_key "
        "LEFT JOIN fixture_observations fo ON fo.snapshot_id=p.snapshot_id AND fo.fixture_id=f.id "
        "LEFT JOIN competition_states cs ON cs.snapshot_id=p.snapshot_id AND cs.competition_object_id=f.competition_object_id "
        "WHERE p.snapshot_id=? AND p.player_ea_id=? AND p.minutes_played>=? AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)",
        (snapshot_id, player_id, minimum_minutes, team_id, team_id),
    ).fetchall()
    return len({str(row["fixture_key"]) for row in rows if scope_matches(conn, snapshot_id, team_id, row["competition_name"], competition_scope)})


def team_achievements(conn: sqlite3.Connection, snapshot_id: int, team_id: int) -> dict[str, bool]:
    league_row = conn.execute(
        "SELECT tls.*,cur.level current_level,prev.level previous_level FROM team_league_states tls "
        "LEFT JOIN league_states cur ON cur.snapshot_id=tls.snapshot_id AND cur.ea_league_id=tls.league_ea_id "
        "LEFT JOIN league_states prev ON prev.snapshot_id=tls.snapshot_id AND prev.ea_league_id=tls.previous_league_ea_id "
        "WHERE tls.snapshot_id=? AND tls.team_ea_id=?",
        (snapshot_id, team_id),
    ).fetchone()
    current_level = int(league_row["current_level"] or 0) if league_row else 0
    previous_level = int(league_row["previous_level"] or 0) if league_row else 0
    observed_promotion = bool(current_level and previous_level and current_level < previous_level)
    observed_relegation = bool(current_level and previous_level and current_level > previous_level)
    champion = bool(int(league_row["champion"] or 0)) if league_row else False
    comps = conn.execute(
        "SELECT cps.stage_id,cps.has_team_won,cps.raw_json,cs.competition_name FROM competition_progress_states cps "
        "LEFT JOIN competition_states cs ON cs.snapshot_id=cps.snapshot_id AND cs.competition_object_id=cps.competition_object_id "
        "WHERE cps.snapshot_id=? AND cps.team_ea_id=?",
        (snapshot_id, team_id),
    ).fetchall()
    names = [str(row["competition_name"] or "") for row in comps]
    won_names = [str(row["competition_name"] or "") for row in comps if int(row["has_team_won"] or 0) == 1]
    observed_champions_league = any("champions league" in _key(name) for name in names)
    observed_europe = observed_champions_league or any(competition_category(conn, snapshot_id, team_id, name) == "continental" for name in names)
    cup_win = any(competition_category(conn, snapshot_id, team_id, name) == "domestic_cup" for name in won_names)

    placement = qualification_state(conn, snapshot_id, team_id)
    inferred = set(placement.get("outcomes") or []) if placement.get("available") and placement.get("final") else set()
    promotion = observed_promotion or "promotion" in inferred
    relegation = observed_relegation or "relegation" in inferred
    champions_league = observed_champions_league or "champions_league_qualification" in inferred
    europe = observed_europe or "europe_qualification" in inferred or champions_league
    # A playoff position is not survival: the result remains unresolved until FC26 later
    # confirms the next league or the relevant playoff outcome.
    survival = bool(placement.get("safeFromRelegation")) if placement.get("available") and placement.get("final") else False
    return {
        "league_title": champion or "league_title" in inferred,
        "cup_win": cup_win,
        "promotion": promotion,
        "promotion_playoff": "promotion_playoff" in inferred,
        "relegation": relegation,
        "relegation_playoff": "relegation_playoff" in inferred,
        "survival": survival,
        "europe_qualification": europe,
        "champions_league_qualification": champions_league,
    }


def competition_achievement(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
    trigger: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    trigger_type = str(trigger.get("type") or "")
    competition = _key(trigger.get("competition"))
    rows = conn.execute(
        "SELECT cps.stage_id,cps.has_team_won,cps.raw_json,cs.competition_name FROM competition_progress_states cps "
        "LEFT JOIN competition_states cs ON cs.snapshot_id=cps.snapshot_id AND cs.competition_object_id=cps.competition_object_id "
        "WHERE cps.snapshot_id=? AND cps.team_ea_id=?",
        (snapshot_id, team_id),
    ).fetchall()
    matching = [row for row in rows if not competition or competition in _key(row["competition_name"]) or _key(row["competition_name"]) in competition]
    if trigger_type == "competition_won":
        met = any(int(row["has_team_won"] or 0) == 1 for row in matching)
        return met, {"competition": trigger.get("competition"), "matchedRows": len(matching)}
    if trigger_type == "competition_stage_reached":
        wanted = str(trigger.get("stage") or "").strip()
        wanted_number = int(wanted) if wanted.isdigit() else None
        for row in matching:
            if wanted_number is not None and int(row["stage_id"] or -1) >= wanted_number:
                return True, {"competition": trigger.get("competition"), "stage": wanted, "observedStageId": int(row["stage_id"] or 0)}
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except Exception:
                raw = {}
            observed_text = " ".join(str(raw.get(k) or "") for k in ("stage_name", "stage", "round_name", "round"))
            if wanted and _key(wanted) and _key(wanted) in _key(observed_text):
                return True, {"competition": trigger.get("competition"), "stage": wanted, "observedStage": observed_text.strip()}
        return False, {"competition": trigger.get("competition"), "stage": wanted, "matchedRows": len(matching)}
    return False, {}
