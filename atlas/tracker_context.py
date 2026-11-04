from __future__ import annotations

import math
import sqlite3
from typing import Any


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def development_capabilities(conn: sqlite3.Connection, career_id: int) -> dict[str, float]:
    """Neutral read-only capabilities used by optional simulation models.

    Community Tracker has no club-development, staff, scouting or academy-management
    systems. Keeping a neutral baseline prevents those removed systems from changing
    imported statistics or simulation confidence.
    """
    return {key: 50.0 for key in (
        "sporting", "scouting", "youth", "medical", "performance", "analysis",
        "commercial", "operations",
    )}


def stadium_capacity_overlay(conn: sqlite3.Connection, career_id: int, base_capacity: int) -> dict[str, int]:
    capacity = max(0, int(base_capacity or 0))
    return {
        "snapshotCapacity": capacity,
        "atlasAddedCapacity": 0,
        "effectiveCapacity": capacity,
    }


def calibration_context(
    conn: sqlite3.Connection,
    career_id: int,
    snapshot: Any,
    team: Any,
    league_level: int | None,
) -> dict[str, float | int]:
    """Build sponsorship context exclusively from imported FC26 facts."""
    domestic = int(team["domestic_prestige"] or 3) if "domestic_prestige" in team.keys() else 3
    international = int(team["international_prestige"] or 1) if "international_prestige" in team.keys() else 1
    overall = float(team["overall"] or 65) if "overall" in team.keys() else 65.0
    capacity = int(team["stadium_capacity"] or 12000) if "stadium_capacity" in team.keys() else 12000
    prestige = _clamp(domestic * 12.0 + international * 8.0, 10.0, 100.0)
    sporting = _clamp((overall - 45.0) * 1.8, 10.0, 100.0)
    financial = _clamp(24.0 + math.log(max(5000, capacity) / 5000, 10) * 32.0 + domestic * 5.0, 10.0, 100.0)
    league_market = _clamp(88.0 - max(0, int(league_level or 1) - 1) * 14.0, 25.0, 95.0)
    status = _clamp(prestige * .36 + sporting * .30 + financial * .20 + league_market * .14, 10.0, 100.0)
    return {
        "commercialStatusScore": round(status, 2),
        "trajectoryScore": round(sporting, 2),
        "prestigeScore": round(prestige, 2),
        "financialScaleScore": round(financial, 2),
        "sportingScore": round(sporting, 2),
        "leagueMarketScore": round(league_market, 2),
        "staffMarketScore": 50.0,
        "organizationScore": 50.0,
        "promotionCount": 0,
        "observedSeasons": 1,
    }
