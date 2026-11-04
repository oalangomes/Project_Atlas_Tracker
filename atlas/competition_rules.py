from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from .media_utils import season_start_from_date

RULESET_PATH = Path(__file__).resolve().parents[1] / "reference" / "competition_qualification_rules_v1.json"
RULESET_MODEL_ID = "atlas-competition-qualification-rules-v1"


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_ruleset() -> dict[str, Any]:
    try:
        payload = json.loads(RULESET_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"format": "project-atlas-competition-qualification-rules", "version": "missing", "rules": []}
    if not isinstance(payload, dict):
        return {"format": "project-atlas-competition-qualification-rules", "version": "invalid", "rules": []}
    if not isinstance(payload.get("rules"), list):
        payload["rules"] = []
    return payload


def ruleset_version() -> str:
    return str(load_ruleset().get("version") or "unknown")


def _snapshot_context(conn: sqlite3.Connection, snapshot_id: int, team_id: int | None = None) -> dict[str, Any]:
    snapshot = conn.execute(
        "SELECT id,career_date,managed_team_ea_id FROM snapshots WHERE id=?",
        (snapshot_id,),
    ).fetchone()
    if not snapshot:
        return {}
    resolved_team = _as_int(team_id if team_id is not None else snapshot["managed_team_ea_id"])
    if resolved_team is None:
        return {}
    league = conn.execute(
        "SELECT tls.league_ea_id,ls.league_name,ls.country_id,ls.level,tls.current_table_position,tls.points,tls.matches_played "
        "FROM team_league_states tls "
        "LEFT JOIN league_states ls ON ls.snapshot_id=tls.snapshot_id AND ls.ea_league_id=tls.league_ea_id "
        "WHERE tls.snapshot_id=? AND tls.team_ea_id=?",
        (snapshot_id, resolved_team),
    ).fetchone()
    if not league or _as_int(league["league_ea_id"]) is None:
        return {}
    team_count = conn.execute(
        "SELECT COUNT(*) FROM team_league_states WHERE snapshot_id=? AND league_ea_id=?",
        (snapshot_id, int(league["league_ea_id"])),
    ).fetchone()[0]
    return {
        "snapshotId": snapshot_id,
        "careerDate": str(snapshot["career_date"] or ""),
        "seasonStartYear": season_start_from_date(str(snapshot["career_date"] or "")),
        "teamEaId": resolved_team,
        "leagueEaId": int(league["league_ea_id"]),
        "leagueName": str(league["league_name"] or ""),
        "countryId": _as_int(league["country_id"]),
        "level": _as_int(league["level"]),
        "position": _as_int(league["current_table_position"]),
        "points": _as_int(league["points"]),
        "matchesPlayed": _as_int(league["matches_played"]) or 0,
        "teamCount": int(team_count or 0),
    }


def _rule_matches(rule: dict[str, Any], context: dict[str, Any]) -> bool:
    if _as_int(rule.get("leagueEaId")) != _as_int(context.get("leagueEaId")):
        return False
    season = _as_int(context.get("seasonStartYear"))
    start = _as_int(rule.get("seasonFrom"))
    end = _as_int(rule.get("seasonTo"))
    if season is not None and start is not None and season < start:
        return False
    if season is not None and end is not None and season > end:
        return False
    expected_teams = _as_int(rule.get("teamCount"))
    if expected_teams is not None and _as_int(context.get("teamCount")) not in {None, 0, expected_teams}:
        return False
    return True


def qualification_rule(conn: sqlite3.Connection, snapshot_id: int, team_id: int | None = None) -> dict[str, Any] | None:
    context = _snapshot_context(conn, snapshot_id, team_id)
    if not context:
        return None
    candidates = [rule for rule in load_ruleset().get("rules", []) if isinstance(rule, dict) and _rule_matches(rule, context)]
    if not candidates:
        return None
    # Narrow season windows beat broad fallbacks. Ties prefer later definitions.
    def rank(rule: dict[str, Any]) -> tuple[int, int]:
        start = _as_int(rule.get("seasonFrom")) or 0
        end = _as_int(rule.get("seasonTo")) or 9999
        return (-(end - start), start)
    selected = sorted(candidates, key=rank, reverse=True)[0]
    return {**selected, "context": context, "rulesetVersion": ruleset_version(), "modelId": RULESET_MODEL_ID}


def _positions(rule: dict[str, Any], key: str) -> set[int]:
    raw = rule.get("positions") if isinstance(rule.get("positions"), dict) else {}
    values = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if _as_int(value) is not None}


def _league_final(conn: sqlite3.Connection, snapshot_id: int, rule: dict[str, Any]) -> bool:
    expected = _as_int(rule.get("expectedFinalMatches"))
    if expected is None or expected <= 0:
        return False
    league_id = _as_int(rule.get("leagueEaId"))
    if league_id is None:
        return False
    rows = conn.execute(
        "SELECT matches_played FROM team_league_states WHERE snapshot_id=? AND league_ea_id=?",
        (snapshot_id, league_id),
    ).fetchall()
    expected_teams = _as_int(rule.get("teamCount"))
    if not rows or (expected_teams is not None and len(rows) != expected_teams):
        return False
    return min(int(row["matches_played"] or 0) for row in rows) >= expected


def qualification_state(conn: sqlite3.Connection, snapshot_id: int, team_id: int) -> dict[str, Any]:
    context = _snapshot_context(conn, snapshot_id, team_id)
    rule = qualification_rule(conn, snapshot_id, team_id)
    if not context:
        return {"available": False, "reason": "team_league_context_missing", "modelId": RULESET_MODEL_ID}
    if rule is None:
        return {
            "available": False,
            "reason": "no_rule",
            "context": context,
            "rulesetVersion": ruleset_version(),
            "modelId": RULESET_MODEL_ID,
        }
    final = _league_final(conn, snapshot_id, rule)
    position = _as_int(context.get("position"))
    outcomes: list[str] = []
    if final and position is not None:
        for key in (
            "league_title", "promotion", "promotion_playoff", "relegation", "relegation_playoff",
            "champions_league_qualification", "europa_league_qualification", "conference_league_qualification",
            "europe_qualification",
        ):
            if position in _positions(rule, key):
                outcomes.append(key)
        # European hierarchy implies generic Europe qualification.
        if any(item in outcomes for item in ("champions_league_qualification", "europa_league_qualification", "conference_league_qualification")):
            if "europe_qualification" not in outcomes:
                outcomes.append("europe_qualification")
    danger_positions = sorted(_positions(rule, "relegation") | _positions(rule, "relegation_playoff"))
    return {
        "available": True,
        "final": final,
        "position": position,
        "outcomes": outcomes,
        "relegationDangerPositions": danger_positions,
        "safeFromRelegation": bool(final and position is not None and position not in danger_positions),
        "rule": {
            "id": rule.get("id"),
            "leagueEaId": rule.get("leagueEaId"),
            "leagueName": rule.get("leagueName"),
            "seasonFrom": rule.get("seasonFrom"),
            "seasonTo": rule.get("seasonTo"),
            "teamCount": rule.get("teamCount"),
            "expectedFinalMatches": rule.get("expectedFinalMatches"),
            "positions": rule.get("positions") or {},
            "dynamicConditions": rule.get("dynamicConditions") or [],
            "provenance": rule.get("provenance") or {},
        },
        "context": context,
        "rulesetVersion": ruleset_version(),
        "modelId": RULESET_MODEL_ID,
    }


def league_rule_summary(conn: sqlite3.Connection, snapshot_id: int, league_id: int) -> dict[str, Any] | None:
    team = conn.execute(
        "SELECT team_ea_id FROM team_league_states WHERE snapshot_id=? AND league_ea_id=? ORDER BY team_ea_id LIMIT 1",
        (snapshot_id, league_id),
    ).fetchone()
    if not team:
        return None
    state = qualification_state(conn, snapshot_id, int(team["team_ea_id"]))
    if not state.get("available"):
        return {
            "available": False,
            "reason": state.get("reason"),
            "rulesetVersion": state.get("rulesetVersion"),
            "modelId": RULESET_MODEL_ID,
        }
    rule = state.get("rule") or {}
    return {
        "available": True,
        "final": bool(state.get("final")),
        "ruleId": rule.get("id"),
        "seasonFrom": rule.get("seasonFrom"),
        "seasonTo": rule.get("seasonTo"),
        "expectedFinalMatches": rule.get("expectedFinalMatches"),
        "positions": rule.get("positions") or {},
        "dynamicConditions": rule.get("dynamicConditions") or [],
        "provenance": rule.get("provenance") or {},
        "rulesetVersion": state.get("rulesetVersion"),
        "modelId": RULESET_MODEL_ID,
    }
