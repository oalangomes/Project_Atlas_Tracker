"""Calendar-semester projection of Atlas's source-bound sporting report."""
from __future__ import annotations

from typing import Any


def _calendar_half(month: str) -> int:
    try:
        value = int(str(month)[5:7])
    except (TypeError, ValueError):
        raise ValueError("Report month must use YYYY-MM.") from None
    if value not in range(1, 13):
        raise ValueError("Report month must use YYYY-MM.")
    return 1 if value <= 6 else 2


def _sum_if_complete(values: list[Any]) -> int | None:
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def build_semester_report(report: dict[str, Any], semester: int) -> dict[str, Any]:
    """Aggregate a season report into Jan-Jun or Jul-Dec without new inference.

    The result deliberately retains the selected and excluded months and only
    aggregates values whose source months are complete.  It is a read-side
    projection: source fixtures, player states and report inputs remain intact.
    """
    if semester not in {1, 2}:
        raise ValueError("Semester must be 1 (Jan-Jun) or 2 (Jul-Dec).")
    source_months = list(report.get("months") or [])
    included = [month for month in source_months if _calendar_half(month.get("month")) == semester]
    excluded = [month.get("month") for month in source_months if month not in included]
    matches = [match for month in included for match in month.get("matches") or []]
    known_results = [match for match in matches if match.get("result") in {"V", "E", "D"}]
    wins = sum(match.get("result") == "V" for match in known_results)
    draws = sum(match.get("result") == "E" for match in known_results)
    losses = sum(match.get("result") == "D" for match in known_results)
    player_rows: dict[int, dict[str, Any]] = {}
    for month in included:
        for player in month.get("players") or []:
            player_id = player.get("playerEaId")
            if not isinstance(player_id, int):
                continue
            row = player_rows.setdefault(player_id, {
                "playerEaId": player_id, "name": player.get("name"), "position": player.get("position"),
                "minutes": 0, "minutesAvailable": True, "matchesWithRating": 0,
                "ratingTotal": 0.0, "ratingAvailable": False, "detailedMatches": 0,
                "months": [],
            })
            row["months"].append(month.get("month"))
            minutes = player.get("minutes")
            if minutes is None:
                row["minutesAvailable"] = False
            else:
                row["minutes"] += int(minutes)
            rated = int(player.get("matchesWithRating") or 0)
            rating = player.get("averageRating")
            row["matchesWithRating"] += rated
            if rating is not None and rated:
                row["ratingTotal"] += float(rating) * rated
                row["ratingAvailable"] = True
            row["detailedMatches"] += int(player.get("detailedMatches") or 0)
    players = []
    for row in player_rows.values():
        players.append({
            "playerEaId": row["playerEaId"], "name": row["name"], "position": row["position"],
            "minutes": row["minutes"] if row["minutesAvailable"] else None,
            "matchesWithRating": row["matchesWithRating"],
            "averageRating": round(row["ratingTotal"] / row["matchesWithRating"], 2)
            if row["ratingAvailable"] and row["matchesWithRating"] else None,
            "detailedMatches": row["detailedMatches"], "months": row["months"],
        })
    players.sort(key=lambda row: (row["averageRating"] is not None, row["averageRating"] or 0,
                                  row["minutes"] or 0), reverse=True)
    period = "Jan-Jun" if semester == 1 else "Jul-Dec"
    goals_for = _sum_if_complete([month.get("goalsFor") for month in included])
    goals_against = _sum_if_complete([month.get("goalsAgainst") for month in included])
    return {
        "careerId": report.get("careerId"), "seasonIndex": report.get("seasonIndex"),
        "snapshotId": report.get("snapshotId"), "snapshotCareerDate": report.get("snapshotCareerDate"),
        "teamEaId": report.get("teamEaId"), "teamName": report.get("teamName"),
        "semester": semester, "periodLabel": period,
        "includedMonths": [month.get("month") for month in included], "excludedMonths": excluded,
        "metrics": {
            "fixtures": len(matches), "resultCoverage": len(known_results), "wins": wins, "draws": draws,
            "losses": losses, "goalsFor": goals_for, "goalsAgainst": goals_against,
            "pointsLeague": _sum_if_complete([month.get("pointsLeague") for month in included]),
            "detailedExports": sum(int(month.get("exports") or 0) for month in included),
        },
        "coverage": {
            "months": len(included), "partialMonths": [month.get("month") for month in included if month.get("partial")],
            "fixturesWithResult": len(known_results), "fixturesWithDetailedExport": sum(match.get("exportId") is not None for match in matches),
            "selectedSnapshotOnly": True,
        },
        "players": players,
        "limitations": [
            "Calendar-semester aggregation only; no player development or tactical cause is inferred.",
            "Goals and league points are unavailable when any included source month is incomplete.",
            "Player ratings are weighted by rated appearances; missing ratings are not treated as zero.",
        ],
    }
