"""Shared, snapshot-scoped evidence contract for match indicators.

Values remain in their source tables. This module describes eligibility,
coverage and provenance at query time, so later imports cannot rewrite an
earlier snapshot's view of a fixture.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .fc26_save_possession import snapshot_save_possession
from .positions import trusted_actual_position


EVIDENCE_VERSION = "atlas-match-evidence-v1"
COMPLETE_EXPORT_STATUSES = frozenset({
    "complete_participant_export",
    "participant_export_complete_with_unresolved_nonparticipant",
})
METRICS = (
    ("npk_expected_goals", "NPK-xG", "goals", "direct", None, ()),
    ("expected_goals_derived", "Team xG", "goals", "derived",
     "NPK-xG + 0.7 × opponent penalties committed", ("npk_expected_goals", "opponent.penalties_committed")),
    ("expected_assists", "xA", "assists", "direct", None, ()),
    ("shots", "Shots", "shots", "direct", None, ()),
    ("shots_on_target", "Shots on target", "shots", "direct", None, ()),
    ("key_passes", "Key passes", "passes", "direct", None, ()),
    ("tracker_completed_through_passes_including_lobbed", "Completed through passes", "passes", "direct", None, ()),
    ("passes", "Passes", "passes", "direct", None, ()),
    ("passes_completed", "Completed passes", "passes", "direct", None, ()),
)


def export_is_usable(export: Mapping[str, Any] | None) -> bool:
    return bool(export and export.get("linkage_status") == "linked"
                and export.get("export_status") in COMPLETE_EXPORT_STATUSES
                and (export.get("superseded_by_export_id") is None or export.get("asOfEligible")))


def fixture_evidence(snapshot: Mapping[str, Any], fixture_id: int,
                     detailed: Mapping[str, Any] | None = None,
                     performances: list[dict[str, Any]] | None = None,
                     candidate: Mapping[str, Any] | None = None,
                     event_date: str | None = None,
                     save_possession: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Describe the selected fixture; candidate may be partial or unlinked."""
    available = bool(detailed and detailed.get("available"))
    export_status = (detailed or {}).get("status") or (candidate or {}).get("export_status")
    linkage_status = (detailed or {}).get("linkageStatus") or (candidate or {}).get("linkage_status")
    if available:
        state, reason = "complete", None
    elif candidate:
        if export_status not in COMPLETE_EXPORT_STATUSES:
            state, reason = "partial", "export_incomplete"
        elif linkage_status != "linked":
            state, reason = "unlinked", "export_not_linked"
        else:
            state, reason = "partial", "missing_team_rows"
    else:
        state, reason = "absent", "no_eligible_matchstats_export"
    source_snapshot_id = (detailed or {}).get("snapshotId") or (candidate or {}).get("snapshot_id")
    export_id = (detailed or {}).get("exportId") or (candidate or {}).get("id")
    source = {"kind": "fc26_matchstats", "exportId": export_id,
              "sourceSnapshotId": source_snapshot_id, "exportStatus": export_status,
              "linkageStatus": linkage_status,
              "importedAt": (detailed or {}).get("importedAt") or (candidate or {}).get("imported_at"),
              "captureId": (detailed or {}).get("captureId") or (candidate or {}).get("pipeline_capture_id")}
    teams = []
    for team in (detailed or {}).get("teams", []) if available else []:
        stats = team.get("stats") or {}
        indicators = []
        for key, label, unit, origin, formula, inputs in METRICS:
            value = stats.get(key)
            indicators.append({
                "key": key, "label": label, "unit": unit, "value": value,
                "state": "available" if value is not None else "absent",
                "origin": origin if value is not None else "unavailable",
                "reason": None if value is not None else (
                    "missing_penalty_context" if key == "expected_goals_derived"
                    and stats.get("npk_expected_goals") is not None else "not_exported"),
                "formula": formula, "inputs": list(inputs), "source": source,
            })
        teams.append({"teamIndex": team.get("teamIndex"), "teamEaId": team.get("teamEaId"),
                      "indicators": indicators})
    if save_possession:
        save_source = {key: save_possession[key] for key in ("kind", "sourceSnapshotId", "mxifSha256")}
        teams_by_id = {team["teamEaId"]: team for team in teams}
        for side in ("home", "away"):
            team_id = save_possession[f"{side}TeamEaId"]
            team = teams_by_id.get(team_id)
            if team is None:
                team = {"teamIndex": None, "teamEaId": team_id, "indicators": []}
                teams.append(team)
            team["indicators"].append({
                "key": "possession_pct", "label": "Ball possession", "unit": "%",
                "value": save_possession[f"{side}Pct"], "state": "available", "origin": "direct",
                "reason": None, "formula": None, "inputs": [], "source": save_source,
            })
    positions = []
    for player in performances or []:
        raw_observed = player.get("observedPosition") or player.get("actual_position")
        origin = player.get("observedPositionSource") or player.get("actual_position_source")
        observed = trusted_actual_position(raw_observed, origin)
        backfill = player.get("observedPositionBackfill")
        positions.append({
            "playerEaId": player.get("player_ea_id"),
            "observed": observed or None, "natural": player.get("primary_position"),
            "state": "observed" if observed else "absent",
            "origin": origin if observed else "no_trusted_match_position",
            "sourceSnapshotId": ((backfill or {}).get("snapshotId") if backfill else snapshot.get("id"))
                                if observed else None,
            "backfilledFromEarlierSnapshot": bool(backfill),
        })
    return {
        "version": EVIDENCE_VERSION,
        "careerId": snapshot.get("career_id"), "snapshotId": snapshot.get("id"),
        "seasonIndex": snapshot.get("season_index"), "fixtureId": fixture_id,
        "period": "fixture", "eventDate": event_date,
        "selectedSnapshotCareerDate": snapshot.get("career_date"),
        "state": state, "reason": reason,
        "source": source, "teams": teams, "positions": positions,
    }


def snapshot_fixture_evidence(conn: Any, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One bounded query for every completed managed fixture in a snapshot."""
    rows = conn.execute(
        """SELECT fo.fixture_id,fo.date,fo.home_team_name,fo.away_team_name,
                  e.id export_id,e.snapshot_id source_snapshot_id,e.export_status,
                  e.linkage_status,e.superseded_by_export_id,e.imported_at,e.pipeline_capture_id,
                  t.team_index,t.team_ea_id,t.stats_json
           FROM fixture_observations fo
           LEFT JOIN match_stat_exports e ON e.id=(
               SELECT candidate.id FROM match_stat_exports candidate
               JOIN snapshots source ON source.id=candidate.snapshot_id
               WHERE candidate.fixture_id=fo.fixture_id AND candidate.career_id=?
                 AND source.career_id=? AND source.season_index=?
                 AND source.import_sequence<=?
                 AND (candidate.superseded_by_export_id IS NULL OR EXISTS (
                     SELECT 1 FROM match_stat_exports successor
                     JOIN snapshots successor_snapshot ON successor_snapshot.id=successor.snapshot_id
                     WHERE successor.id=candidate.superseded_by_export_id
                       AND successor_snapshot.import_sequence>?))
               ORDER BY CASE WHEN candidate.linkage_status='linked' AND candidate.export_status IN
                    ('complete_participant_export','participant_export_complete_with_unresolved_nonparticipant')
                    THEN 0 ELSE 1 END,
                    source.import_sequence DESC,candidate.id DESC LIMIT 1)
           LEFT JOIN match_team_detailed_stats t ON t.export_id=e.id
           WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
           ORDER BY fo.date,fo.fixture_id,t.team_index""",
        (snapshot["career_id"], snapshot["career_id"], snapshot["season_index"],
         snapshot["import_sequence"], snapshot["import_sequence"], snapshot["id"]),
    ).fetchall()
    by_fixture: dict[int, dict[str, Any]] = {}
    for row in rows:
        fixture_id = int(row["fixture_id"])
        item = by_fixture.setdefault(fixture_id, {
            "fixtureId": fixture_id, "date": row["date"],
            "homeTeamName": row["home_team_name"], "awayTeamName": row["away_team_name"],
            "candidate": None, "teams": [],
        })
        if row["export_id"] is not None:
            item["candidate"] = {"id": row["export_id"], "snapshot_id": row["source_snapshot_id"],
                                 "export_status": row["export_status"], "linkage_status": row["linkage_status"],
                                 "superseded_by_export_id": row["superseded_by_export_id"],
                                 "asOfEligible": True,
                                 "imported_at": row["imported_at"], "pipeline_capture_id": row["pipeline_capture_id"]}
        if row["team_index"] is not None:
            try:
                stats = json.loads(row["stats_json"] or "{}")
            except (TypeError, ValueError):
                stats = {}
            item["teams"].append({"teamIndex": row["team_index"], "teamEaId": row["team_ea_id"],
                                  "stats": stats if isinstance(stats, dict) else {}})
    result = []
    save_possession = snapshot_save_possession(conn, snapshot)
    for item in by_fixture.values():
        candidate = item.pop("candidate")
        teams = item.pop("teams")
        if export_is_usable(candidate) and len(teams) == 2:
            from .match_stats import _add_team_expected_goals_from_opponent_penalty
            _add_team_expected_goals_from_opponent_penalty(teams[0]["stats"], teams[1]["stats"])
            _add_team_expected_goals_from_opponent_penalty(teams[1]["stats"], teams[0]["stats"])
            detailed = {"available": True, "exportId": candidate["id"],
                        "snapshotId": candidate["snapshot_id"], "status": candidate["export_status"],
                        "linkageStatus": candidate["linkage_status"],
                        "importedAt": candidate["imported_at"], "captureId": candidate["pipeline_capture_id"],
                        "teams": teams}
        else:
            detailed = None
        item["evidence"] = fixture_evidence(snapshot, item["fixtureId"], detailed, candidate=candidate,
                                            event_date=item["date"],
                                            save_possession=save_possession.get(item["fixtureId"]))
        result.append(item)
    return result
