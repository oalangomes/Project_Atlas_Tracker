from __future__ import annotations

import sqlite3
from typing import Any

from .positions import broad_position_group


def live_squad_players(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return current save players for one club, never the static EA club rating.

    ``roster_states`` is authoritative where it is available. Some non-managed
    clubs are only represented in ``player_states``; that live save membership
    is the explicit fallback. The EA/Sofifa team overall is deliberately not a
    fallback because it describes the database baseline, not the current save.
    """

    rows = conn.execute(
        "SELECT p.ea_player_id,p.overall,p.primary_position FROM roster_states r "
        "JOIN player_states p ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id "
        "WHERE r.snapshot_id=? AND r.team_ea_id=? AND p.team_ea_id=? AND p.overall IS NOT NULL "
        "ORDER BY p.overall DESC,p.ea_player_id",
        (snapshot_id, team_id, team_id),
    ).fetchall()
    source = "roster_states"
    if not rows:
        rows = conn.execute(
            "SELECT ea_player_id,overall,primary_position FROM player_states "
            "WHERE snapshot_id=? AND team_ea_id=? AND overall IS NOT NULL "
            "ORDER BY overall DESC,ea_player_id",
            (snapshot_id, team_id),
        ).fetchall()
        source = "player_states_membership"
    items = [dict(row) | {"membership_source": source} for row in rows]
    return items[:top_n] if top_n is not None else items


def live_squad_strength(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    players = live_squad_players(conn, snapshot_id, team_id, top_n=top_n)
    values = [int(player["overall"]) for player in players]
    groups: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for player in players:
        groups[broad_position_group(player.get("primary_position"))].append(int(player["overall"]))
    return {
        "average": sum(values) / len(values) if values else None,
        "sum": sum(values),
        "count": len(values),
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "groups": {
            key: (sum(group_values) / len(group_values) if group_values else None)
            for key, group_values in groups.items()
        },
        "membershipSource": players[0]["membership_source"] if players else "unavailable",
        "formula": "sum(current save player overall) / player count",
        "eaBaseOverallUsed": False,
    }


def live_league_strengths(
    conn: sqlite3.Connection,
    snapshot_id: int,
    league_id: int | None,
) -> dict[int, float]:
    if league_id is None:
        return {}
    team_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT ea_team_id FROM team_states WHERE snapshot_id=? AND league_ea_id=?",
            (snapshot_id, league_id),
        ).fetchall()
    ]
    result: dict[int, float] = {}
    for team_id in team_ids:
        strength = live_squad_strength(conn, snapshot_id, team_id)
        if strength["average"] is not None:
            result[team_id] = float(strength["average"])
    return result


def contextual_team_strength(
    conn: sqlite3.Connection,
    snapshot_id: int,
    team_id: int,
) -> dict[str, Any]:
    """Live squad strength with a non-EA proxy for genuinely missing rosters."""

    strength = live_squad_strength(conn, snapshot_id, team_id)
    if strength["average"] is not None:
        return strength
    team = conn.execute(
        "SELECT domestic_prestige,international_prestige FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
        (snapshot_id, team_id),
    ).fetchone()
    if not team:
        return strength | {"average": 65.0, "membershipSource": "neutral_missing_team_context"}
    domestic = int(team["domestic_prestige"] or 0)
    international = int(team["international_prestige"] or 0)
    proxy = max(58.0, min(85.0, 58.0 + domestic * .75 + international * .55))
    return strength | {
        "average": proxy,
        "membershipSource": "prestige_context_proxy",
        "formula": "58 + domestic prestige × 0.75 + international prestige × 0.55",
        "eaBaseOverallUsed": False,
    }
