"""Compact, source-preserving API view of the deterministic sporting report."""
from __future__ import annotations

from typing import Any

from .monthly_report_markdown import render_month, render_season


_TEAM_METRICS = ("expected_goals_derived", "npk_expected_goals", "shots", "passes")
_MATCH_FIELDS = ("fixtureId", "date", "opponent", "opponentLeague", "competition",
                 "venue", "result", "goalsFor", "goalsAgainst", "superior", "exportId",
                 "standouts")
_PLAYER_FIELDS = ("playerEaId", "name", "category", "position", "age", "overall",
                  "potential", "role", "minutes", "matchesWithRating", "averageRating",
                  "detailedMatches", "detailedStats", "detailedCoverage", "per90", "sample",
                  "sampleCode",
                  "best", "worst", "observedPositions", "comparison", "reconstructed",
                  "reconstructedMatches", "superiorOpponents")
_MONTH_FIELDS = ("month", "partial", "snapshotIdForPlayerState", "competitions",
                 "pointsLeague", "goalsFor", "goalsAgainst", "resultCoverage",
                 "pointsPct", "exports", "metricCoverage", "rosterChanges")


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the same calculations while omitting large raw MatchStats/evidence maps."""
    months = []
    for month in report["months"]:
        matches = []
        for match in month["matches"]:
            item = {key: match.get(key) for key in _MATCH_FIELDS}
            item["teamStats"] = {key: (match.get("teamStats") or {}).get(key) for key in _TEAM_METRICS}
            item["opponentStats"] = {key: (match.get("opponentStats") or {}).get(key) for key in _TEAM_METRICS}
            item["evidenceState"] = (match.get("evidence") or {}).get("state")
            item["evidenceReason"] = (match.get("evidence") or {}).get("reason")
            matches.append(item)
        months.append({**{key: month.get(key) for key in _MONTH_FIELDS},
                       "matches": matches,
                       "players": [{key: player.get(key) for key in _PLAYER_FIELDS}
                                   for player in month["players"]]})
    return {key: report.get(key) for key in ("careerId", "careerFingerprint", "seasonIndex",
                                             "snapshotId", "snapshotCareerDate", "teamEaId",
                                             "teamName", "fixtureCount", "playerCount")} | {"months": months}


def markdown_download(report: dict[str, Any], month: str | None = None) -> dict[str, str]:
    """Render an independently downloadable month or the season synthesis."""
    if month is None:
        return {"fileName": f"atlas-temporada-{report['seasonIndex']}-snapshot-{report['snapshotId']}.md",
                "content": render_season(report, navigation=False)}
    for index, item in enumerate(report["months"]):
        if item["month"] == month:
            previous = report["months"][index - 1] if index else None
            return {"fileName": f"atlas-{month}-snapshot-{report['snapshotId']}.md",
                    "content": render_month(report, item, previous, navigation=False)}
    raise ValueError(f"No completed managed matches in {month}")
