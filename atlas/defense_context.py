"""Observed defensive actions and explicitly estimated team context.

No substitution timeline is available: same-fixture pairs do not imply overlap.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import json
import math
from typing import Any

from .match_stats import _add_team_expected_goals_from_opponent_penalty
from .positions import TRUSTED_POSITION_SOURCES, detailed_position_group, trusted_actual_position


MODEL_ID = "atlas-defense-context-v1"
DEFENSIVE_SECTORS = ("centre_back", "fullback", "defensive_midfield")
DIRECT_FIELDS = ("tackles", "interceptions", "blocks", "clearances")
CONTEXT_FIELDS = {"xga": "expected_goals_derived", "shots": "shots", "shotsOnTarget": "shots_on_target"}


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _json(value: Any) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _empty_metric() -> dict[str, Any]:
    return {"weightedTotal": 0.0, "minutes": 0.0, "fixtureIds": set()}


def _empty_context() -> dict[str, Any]:
    return {"minutes": 0.0, "fixtureIds": set(),
            "metrics": {key: _empty_metric() for key in CONTEXT_FIELDS},
            "cleanSheetMinutes": 0.0, "knownGoalsMinutes": 0.0, "knownGoalsFixtures": set()}


def _add_context(target: dict[str, Any], fixture_id: int, minutes: float,
                 opponent: dict[str, Any], own: dict[str, Any]) -> None:
    target["minutes"] += minutes
    target["fixtureIds"].add(fixture_id)
    for key, field in CONTEXT_FIELDS.items():
        value = _number(opponent.get(field))
        if value is None:
            continue
        metric = target["metrics"][key]
        metric["weightedTotal"] += value * minutes / 90
        metric["minutes"] += minutes
        metric["fixtureIds"].add(fixture_id)
    conceded = _number(own.get("goals_conceded"))
    if conceded is not None:
        target["knownGoalsMinutes"] += minutes
        target["knownGoalsFixtures"].add(fixture_id)
        if conceded == 0:
            target["cleanSheetMinutes"] += minutes


def _context_output(source: dict[str, Any]) -> dict[str, Any]:
    metrics = {}
    samples = {}
    for key, data in source["metrics"].items():
        metrics[f"{key}Per90Estimated"] = (
            round(data["weightedTotal"] / (data["minutes"] / 90), 3)
            if data["minutes"] > 0 else None)
        samples[key] = {"fixtures": len(data["fixtureIds"]), "minutes": round(data["minutes"], 1)}
    metrics["cleanSheetExposurePctEstimated"] = (
        round(source["cleanSheetMinutes"] / source["knownGoalsMinutes"] * 100, 1)
        if source["knownGoalsMinutes"] > 0 else None)
    samples["cleanSheet"] = {"fixtures": len(source["knownGoalsFixtures"]),
                              "minutes": round(source["knownGoalsMinutes"], 1)}
    return {"metrics": metrics, "sample": samples,
            "observedDefensiveMinutes": round(source["minutes"], 1),
            "observedDefensiveFixtures": len(source["fixtureIds"])}


def build_defense_context(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate each field only from rows carrying its own minutes and source."""
    players: dict[int, dict[str, Any]] = {}
    sectors = {sector: _empty_context() for sector in DEFENSIVE_SECTORS}
    sector_players: dict[str, set[int]] = defaultdict(set)
    pairs: dict[tuple[int, int], dict[str, Any]] = {}
    coverage = {"linkedFixtures": len(fixtures), "xgaFixtures": 0,
                "positiveMinuteRows": 0, "trustedDefensiveRows": 0,
                "withoutTrustedPosition": 0, "withoutMinutes": 0}
    for fixture in fixtures:
        fixture_id = int(fixture["fixtureId"])
        own = fixture.get("ownStats") or {}
        opponent = fixture.get("opponentStats") or {}
        if _number(opponent.get("expected_goals_derived")) is not None:
            coverage["xgaFixtures"] += 1
        observed_in_fixture: list[tuple[int, float]] = []
        for participant in fixture.get("players") or []:
            player_id = int(participant["playerEaId"])
            stats = participant.get("stats") or {}
            minutes = _number(stats.get("minutes_played"))
            if minutes is None:
                coverage["withoutMinutes"] += 1
            elif minutes > 0:
                coverage["positiveMinuteRows"] += 1
            position = trusted_actual_position(participant.get("observedPosition"),
                                               participant.get("observedPositionSource"))
            sector = detailed_position_group(position, default="") if position else ""
            if sector not in DEFENSIVE_SECTORS:
                sector = ""
            if not position:
                coverage["withoutTrustedPosition"] += 1
            player = players.setdefault(player_id, {
                "playerEaId": player_id, "displayName": participant.get("displayName"),
                "registeredPosition": participant.get("primaryPosition"),
                "direct": {field: {"total": 0.0, "fixtures": set(), "minutes": 0.0,
                                   "pairedTotal": 0.0, "missingMinutesRows": 0} for field in DIRECT_FIELDS},
                "context": _empty_context(), "sectors": set(), "observedPositions": set(),
            })
            if participant.get("displayName") and not player["displayName"]:
                player["displayName"] = participant["displayName"]
            if position:
                player["observedPositions"].add(position)
            for field in DIRECT_FIELDS:
                value = _number(stats.get(field))
                if value is None:
                    continue
                item = player["direct"][field]
                item["total"] += value
                item["fixtures"].add(fixture_id)
                if minutes is not None and minutes > 0:
                    item["pairedTotal"] += value
                    item["minutes"] += minutes
                else:
                    item["missingMinutesRows"] += 1
            if not sector or minutes is None or minutes <= 0:
                continue
            coverage["trustedDefensiveRows"] += 1
            player["sectors"].add(sector)
            sector_players[sector].add(player_id)
            _add_context(player["context"], fixture_id, minutes, opponent, own)
            _add_context(sectors[sector], fixture_id, minutes, opponent, own)
            observed_in_fixture.append((player_id, minutes))
        for (first_id, first_minutes), (second_id, second_minutes) in combinations(sorted(observed_in_fixture), 2):
            pair = pairs.setdefault((first_id, second_id), {"fixtureIds": set(), "overlapUpperBoundMinutes": 0.0})
            pair["fixtureIds"].add(fixture_id)
            pair["overlapUpperBoundMinutes"] += min(first_minutes, second_minutes)
    player_items = []
    for player in players.values():
        direct = {}
        for field, item in player["direct"].items():
            count = item["total"]
            direct[field] = {
                "total": int(count) if count.is_integer() else round(count, 2),
                "fixtures": len(item["fixtures"]), "minutes": round(item["minutes"], 1),
                "per90": round(item["pairedTotal"] * 90 / item["minutes"], 2)
                         if item["minutes"] > 0 and not item["missingMinutesRows"] else None,
            }
        player_items.append({"playerEaId": player["playerEaId"], "displayName": player["displayName"],
                             "registeredPosition": player["registeredPosition"],
                             "observedPositions": sorted(player["observedPositions"]),
                             "observedSectors": sorted(player["sectors"]), "direct": direct,
                             "estimatedContext": _context_output(player["context"])})
    player_items.sort(key=lambda item: (-item["estimatedContext"]["observedDefensiveMinutes"],
                                        str(item["displayName"] or ""), item["playerEaId"]))
    sector_items = []
    for sector, data in sectors.items():
        context = _context_output(data)
        xga_minutes = context["sample"]["xga"]["minutes"]
        qualified = xga_minutes >= 270 and context["sample"]["xga"]["fixtures"] >= 3
        sector_metrics = dict(context["metrics"])
        for sample_key, metric_key in (("xga", "xgaPer90Estimated"),
                                       ("shots", "shotsPer90Estimated"),
                                       ("shotsOnTarget", "shotsOnTargetPer90Estimated"),
                                       ("cleanSheet", "cleanSheetExposurePctEstimated")):
            sample = context["sample"][sample_key]
            if not qualified or sample["minutes"] < 270 or sample["fixtures"] < 3:
                sector_metrics[metric_key] = None
        sector_items.append({"sector": sector, "playerCount": len(sector_players[sector]),
                             "qualified": qualified, "qualificationMinutes": 270,
                             "qualificationFixtures": 3,
                             "estimatedContext": {**context, "metrics": sector_metrics}})
    pair_items = [{"firstPlayerEaId": first, "secondPlayerEaId": second,
                   "sameFixtureCount": len(item["fixtureIds"]),
                   "overlapUpperBoundMinutes": round(item["overlapUpperBoundMinutes"], 1),
                   "referenceUpperBoundReached": item["overlapUpperBoundMinutes"] >= 180,
                   "simultaneousPresenceConfirmed": False}
                  for (first, second), item in pairs.items()]
    pair_items.sort(key=lambda item: (-item["sameFixtureCount"], -item["overlapUpperBoundMinutes"],
                                      item["firstPlayerEaId"], item["secondPlayerEaId"]))
    return {"modelId": MODEL_ID, "available": bool(fixtures), "coverage": coverage,
            "players": player_items, "sectors": sector_items, "pairs": pair_items,
            "sectorPanelAvailable": any(item["qualified"] for item in sector_items),
            "interpretationLimit": (
                "Opponent xG and shots are team totals weighted by each observed defender's minutes, "
                "not events conceded while that player was on the pitch. Same-fixture pairs do not prove "
                "simultaneous presence; their min(minutes A, minutes B) is only an upper bound.")}


def defense_context(conn: Any, career_id: int, season_indices: list[int],
                    managed_team_id: int | None, *, as_of_import_sequence: int) -> dict[str, Any]:
    """Read linked exports and trusted positions no later than the selected snapshot."""
    if not season_indices:
        return build_defense_context([])
    marks = ",".join("?" for _ in season_indices)
    export_rows = conn.execute(
        f"""SELECT e.id export_id,e.fixture_id,s.id snapshot_id,s.season_index,s.import_sequence,
                   s.managed_team_ea_id,f.fixture_key
              FROM match_stat_exports e JOIN snapshots s ON s.id=e.snapshot_id
              JOIN fixtures f ON f.id=e.fixture_id
             WHERE e.career_id=? AND s.career_id=? AND s.season_index IN ({marks})
               AND s.import_sequence<=? AND e.linkage_status='linked'
               AND e.export_status IN ('complete_participant_export',
                   'participant_export_complete_with_unresolved_nonparticipant')
               AND (e.superseded_by_export_id IS NULL OR EXISTS (
                   SELECT 1 FROM match_stat_exports successor
                   JOIN snapshots later ON later.id=successor.snapshot_id
                   WHERE successor.id=e.superseded_by_export_id AND later.import_sequence>?))
             ORDER BY s.import_sequence DESC,e.id DESC""",
        (career_id, career_id, *season_indices, as_of_import_sequence, as_of_import_sequence),
    ).fetchall()
    seen_fixtures: set[int] = set()
    exports = []
    for row in export_rows:
        fixture_id = int(row["fixture_id"])
        if fixture_id not in seen_fixtures:
            exports.append(dict(row))
            seen_fixtures.add(fixture_id)
    if not exports:
        return build_defense_context([])
    teams_by_export: dict[int, list[dict[str, Any]]] = defaultdict(list)
    players_by_export: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for start in range(0, len(exports), 400):
        ids = [int(row["export_id"]) for row in exports[start:start + 400]]
        marks = ",".join("?" for _ in ids)
        for row in conn.execute(
            f"SELECT export_id,team_index,team_ea_id,stats_json FROM match_team_detailed_stats WHERE export_id IN ({marks})", ids):
            teams_by_export[int(row["export_id"])].append({"teamIndex": int(row["team_index"]),
                "teamEaId": row["team_ea_id"], "stats": _json(row["stats_json"])})
        for row in conn.execute(
            f"""SELECT d.export_id,d.player_ea_id,d.team_index,d.minutes_played,d.stats_json,
                       p.display_name,p.primary_position
                  FROM match_player_detailed_stats d
                  JOIN match_stat_exports e ON e.id=d.export_id
                  LEFT JOIN player_states p ON p.snapshot_id=e.snapshot_id AND p.ea_player_id=d.player_ea_id
                 WHERE d.export_id IN ({marks})""", ids):
            stats = _json(row["stats_json"])
            if stats.get("minutes_played") is None:
                stats["minutes_played"] = row["minutes_played"]
            players_by_export[int(row["export_id"])].append({
                "playerEaId": int(row["player_ea_id"]), "teamIndex": int(row["team_index"]),
                "displayName": row["display_name"], "primaryPosition": row["primary_position"],
                "stats": stats})
    observed: dict[tuple[int, str, int], dict[str, Any]] = {}
    keys_by_season: dict[int, set[str]] = defaultdict(set)
    for row in exports:
        if row["fixture_key"]:
            keys_by_season[int(row["season_index"])].add(str(row["fixture_key"]))
    sources = tuple(sorted(TRUSTED_POSITION_SOURCES))
    for season, keys in keys_by_season.items():
        key_list = sorted(keys)
        for start in range(0, len(key_list), 400):
            batch = key_list[start:start + 400]
            marks = ",".join("?" for _ in batch)
            for row in conn.execute(
                f"""SELECT p.fixture_key,p.player_ea_id,p.actual_position,p.actual_position_source
                      FROM player_match_performances p JOIN snapshots s ON s.id=p.snapshot_id
                     WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
                       AND p.fixture_key IN ({marks}) AND p.actual_position_source IN (?,?)
                     ORDER BY s.import_sequence DESC,s.id DESC""",
                (career_id, season, as_of_import_sequence, *batch, *sources)):
                key = (season, str(row["fixture_key"]), int(row["player_ea_id"]))
                if key not in observed and trusted_actual_position(row["actual_position"], row["actual_position_source"]):
                    observed[key] = {"position": row["actual_position"], "source": row["actual_position_source"]}
    fixtures = []
    for export in exports:
        export_id = int(export["export_id"])
        teams = teams_by_export.get(export_id, [])
        local_managed = export["managed_team_ea_id"] or managed_team_id
        own = next((team for team in teams if str(team["teamEaId"]) == str(local_managed)), None)
        opponent = next((team for team in teams if own and team["teamIndex"] != own["teamIndex"]), None)
        if not own or not opponent:
            continue
        own_stats = dict(own["stats"])
        opponent_stats = dict(opponent["stats"])
        _add_team_expected_goals_from_opponent_penalty(opponent_stats, own_stats)
        participants = []
        for player in players_by_export.get(export_id, []):
            if player["teamIndex"] != own["teamIndex"]:
                continue
            position = observed.get((int(export["season_index"]), str(export["fixture_key"] or ""),
                                     player["playerEaId"])) or {}
            participants.append({**player, "observedPosition": position.get("position"),
                                 "observedPositionSource": position.get("source")})
        fixtures.append({"fixtureId": int(export["fixture_id"]), "ownStats": own_stats,
                         "opponentStats": opponent_stats, "players": participants})
    result = build_defense_context(fixtures)
    result["coverage"].update({"linkedExports": len(exports),
                               "excludedMissingTeamRows": len(exports) - len(fixtures)})
    return result
