"""Compact, source-preserving API view of the deterministic sporting report."""
from __future__ import annotations

import re
from typing import Any

from .monthly_report_markdown import render_month, render_season


_TEAM_METRICS = ("expected_goals_derived", "npk_expected_goals", "shots", "passes")
_MATCH_FIELDS = ("fixtureId", "date", "opponent", "opponentLeague", "competition",
                 "venue", "result", "goalsFor", "goalsAgainst", "superior", "exportId",
                 "standouts")
_PLAYER_FIELDS = ("playerEaId", "name", "category", "position", "age", "overall",
                  "potential", "role", "minutes", "matchesWithRating", "averageRating",
                  "matchesWithMinutes",
                  "detailedMatches", "detailedStats", "detailedCoverage", "per90", "sample",
                  "sampleCode",
                  "best", "worst", "observedPositions", "comparison", "reconstructed",
                  "reconstructedMatches", "superiorOpponents")
_MONTH_FIELDS = ("month", "partial", "snapshotIdForPlayerState", "competitions",
                 "pointsLeague", "goalsFor", "goalsAgainst", "resultCoverage",
                 "pointsPct", "exports", "metricCoverage", "rosterChanges")


def validate_report_period(start_month: str, end_month: str) -> None:
    if not all(re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month)
               for month in (start_month, end_month)):
        raise ValueError("Report period requires two months in YYYY-MM format.")
    if start_month > end_month:
        raise ValueError("Start month must be before or equal to end month.")


def report_period(report: dict[str, Any], start_month: str, end_month: str, *,
                  compare_previous_month: bool = False) -> dict[str, Any]:
    """Select inclusive calendar months from the same snapshot-bound report."""
    months = [item for item in report["months"] if start_month <= item["month"] <= end_month]
    if months and not compare_previous_month:
        # The first roster delta compares to a month outside this period.
        months[0] = {**months[0], "rosterChanges": None,
                     "players": [{**player, "comparison": None} for player in months[0]["players"]]}
    return {
        **report,
        "months": months,
        "fixtureCount": sum(len(item["matches"]) for item in months),
        "playerCount": len({player["playerEaId"] for item in months for player in item["players"]}),
        "availableMonths": [item["month"] for item in report["months"]],
        "period": {
            "startMonth": start_month,
            "endMonth": end_month,
            "partial": end_month >= report["snapshotCareerDate"][:7],
        },
    }


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
    return {key: report[key] for key in ("careerId", "careerFingerprint", "seasonIndex",
                                        "snapshotId", "snapshotCareerDate", "teamEaId",
                                        "teamName", "fixtureCount", "playerCount",
                                        "availableMonths", "period") if key in report} | {"months": months}


def markdown_download(report: dict[str, Any], month: str | None = None) -> dict[str, str]:
    """Render a standalone month or the synthesis of the selected months."""
    if month is None:
        period = report.get("period")
        label = (f"{period['startMonth']}_a_{period['endMonth']}" if period
                 else f"temporada-{report['seasonIndex']}")
        return {"fileName": f"atlas-{label}-snapshot-{report['snapshotId']}.md",
                "content": render_season(report, navigation=False)}
    for index, item in enumerate(report["months"]):
        if item["month"] == month:
            previous = report["months"][index - 1] if index else None
            return {"fileName": f"atlas-{month}-snapshot-{report['snapshotId']}.md",
                    "content": render_month(report, item, previous, navigation=False)}
    raise ValueError(f"No completed managed matches in {month}")
