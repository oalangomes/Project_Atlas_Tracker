from __future__ import annotations

import json
import math
import sqlite3
from datetime import date
from typing import Any

from .finance_core import as_minor, input_date, utc_now
from .server_utils import age_on_date, as_int, effective_career_date, input_bool, parse_raw
from .media_utils import season_start_from_date
from .player_dynamics import PlayerDynamicsService, position_group
from .team_strength import live_squad_strength


MODEL_ID = "atlas-player-finance-v4"
QUALITY = "atlas_primary"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_major(value: float) -> int:
    value = max(0.0, value)
    if value < 100_000:
        step = 5_000
    elif value < 1_000_000:
        step = 25_000
    elif value < 10_000_000:
        step = 100_000
    elif value < 50_000_000:
        step = 250_000
    else:
        step = 500_000
    return int(math.floor(value / step + 0.5) * step)


def _round_wage(value: float) -> int:
    step = 100 if value < 5_000 else 500 if value < 25_000 else 1_000
    return max(step, int(math.floor(max(0.0, value) / step + 0.5) * step))


MARKET_VALUE_ANCHORS = (
    (45.0, 25_000.0), (50.0, 70_000.0), (55.0, 180_000.0), (60.0, 450_000.0),
    (65.0, 1_200_000.0), (70.0, 3_200_000.0), (75.0, 8_000_000.0),
    (78.0, 14_000_000.0), (80.0, 20_000_000.0), (82.0, 28_000_000.0),
    (85.0, 48_000_000.0), (88.0, 80_000_000.0), (90.0, 112_000_000.0),
    (92.0, 150_000_000.0), (94.0, 210_000_000.0), (96.0, 305_000_000.0),
    (99.0, 370_000_000.0),
)

WEEKLY_WAGE_ANCHORS = (
    (50.0, 400.0), (55.0, 650.0), (60.0, 1_000.0), (65.0, 2_800.0),
    (70.0, 8_000.0), (75.0, 20_000.0), (78.0, 32_000.0), (80.0, 45_000.0),
    (82.0, 60_000.0), (85.0, 95_000.0), (88.0, 140_000.0), (90.0, 185_000.0),
    (92.0, 235_000.0), (94.0, 290_000.0), (96.0, 350_000.0), (99.0, 650_000.0),
)


def _interpolate_anchor(value: float, anchors: tuple[tuple[float, float], ...]) -> float:
    value = float(value)
    if value <= anchors[0][0]:
        return anchors[0][1] * math.exp((value - anchors[0][0]) * .16)
    for (low_x, low_y), (high_x, high_y) in zip(anchors, anchors[1:]):
        if value <= high_x:
            share = (value - low_x) / (high_x - low_x)
            # Log interpolation keeps the football market's nonlinear price curve.
            return math.exp(math.log(low_y) + (math.log(high_y) - math.log(low_y)) * share)
    return anchors[-1][1] * (1.0 + min(1.0, value - anchors[-1][0]) * .10)



def _raw_number(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        try:
            value = float(raw.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None

def _position_group(position: Any) -> str:
    value = str(position or "").strip().upper()
    if value in {"GK", "TW"}:
        return "goalkeeper"
    if value in {"SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB", "RAV", "RV", "RIV", "IV", "LIV", "LV", "LAV"}:
        return "defence"
    if value in {"RDM", "CDM", "LDM", "RM", "RCM", "CM", "LCM", "LM", "RAM", "CAM", "LAM", "ZDM", "ZM", "ZOM"}:
        return "midfield"
    return "attack"


class PlayerFinanceService:
    """Independent Atlas valuation plus transparent deal planning.

    Imported OVR/POT remain immutable and the legacy EA approximation stays visible
    only as a control value. The primary Atlas market value is built independently
    from the seasonal performance state, league and club context, age, potential and
    contract status. Observed wages and snapshot data are never silently overwritten.
    """

    def __init__(self, database, financial_service, finance_core, player_dynamics=None):
        self.database = database
        self.financial = financial_service
        self.finance_core = finance_core
        self.player_dynamics = player_dynamics or PlayerDynamicsService(database)

    @staticmethod
    def _stats(conn: sqlite3.Connection, snapshot_id: int, player_id: int) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT ss.appearances,ss.goals,ss.assists,ss.clean_sheets,ss.average_rating FROM season_stat_states ss "
            "JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id "
            "WHERE ss.snapshot_id=? AND ss.player_ea_id=? AND ss.represented_team_ea_id=p.team_ea_id",
            (snapshot_id, player_id),
        ).fetchall()
        appearances = sum(as_int(row["appearances"]) or 0 for row in rows)
        goals = sum(as_int(row["goals"]) or 0 for row in rows)
        assists = sum(as_int(row["assists"]) or 0 for row in rows)
        clean_sheets = sum(as_int(row["clean_sheets"]) or 0 for row in rows)
        weighted_rating_total = 0.0
        weighted_rating_apps = 0
        for row in rows:
            rating = row["average_rating"]
            apps = as_int(row["appearances"]) or 0
            if rating not in (None, 0) and apps > 0:
                weighted_rating_total += float(rating) * apps
                weighted_rating_apps += apps
        return {
            "appearances": appearances,
            "goals": goals,
            "assists": assists,
            "clean_sheets": clean_sheets,
            "average_rating": round(weighted_rating_total / weighted_rating_apps, 2) if weighted_rating_apps else None,
        }

    @staticmethod
    def _contract_years(contract_until: Any, career_date: str) -> float:
        if not contract_until:
            return 0.0
        text = str(contract_until).strip()
        try:
            if text.isdigit() and len(text) == 4:
                target = date(int(text), 6, 30)
            elif text.isdigit() and len(text) == 8:
                target = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
            else:
                target = date.fromisoformat(text[:10])
            current = date.fromisoformat(str(career_date)[:10])
            return max(0.0, (target - current).days / 365.25)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _factor(label: str, value: float, explanation: str) -> dict[str, Any]:
        return {"label": label, "value": round(value, 4), "impactPct": round((value - 1) * 100, 1), "explanation": explanation}

    def _override(self, conn: sqlite3.Connection, career_id: int, snapshot_id: int, player_id: int) -> dict[str, Any] | None:
        return None

    @staticmethod
    def _age_market_factor(age: int | None, dynamic_overall: float) -> float:
        if age is None:
            return 1.0
        if age <= 19:
            return 1.20
        if age <= 21:
            return 1.16
        if age <= 23:
            return 1.12
        if age <= 26:
            return 1.07
        if age == 27:
            return 0.99
        if age == 28:
            return 0.93
        if age == 29:
            return 0.85
        if age == 30:
            return 0.76
        if age == 31:
            return 0.67
        if age == 32:
            return 0.58
        if age == 33:
            return 0.50
        # Elite veterans retain value longer than ordinary squad players.
        return _clamp(0.38 + max(0.0, dynamic_overall - 82) * 0.015, 0.36, 0.66)

    @staticmethod
    def _position_market_factor(position: Any) -> float:
        value = str(position or "").strip().upper()
        if value in {"GK", "TW"}:
            return 0.80
        if value in {"CB", "RCB", "LCB", "IV", "RIV", "LIV", "SW"}:
            return 0.98
        if value in {"RB", "LB", "RWB", "LWB", "RV", "LV", "RAV", "LAV"}:
            return 0.95
        if value in {"CDM", "RDM", "LDM", "ZDM"}:
            return 0.97
        if value in {"CM", "RCM", "LCM", "ZM"}:
            return 1.02
        if value in {"CAM", "RAM", "LAM", "ZOM", "RM", "LM"}:
            return 1.05
        if value in {"RW", "LW", "RF", "LF"}:
            return 1.07
        return 1.08

    def _league_market_context(self, team: sqlite3.Row | None, snapshot: sqlite3.Row, career_date: str | None = None) -> dict[str, Any]:
        league_id = as_int(team["league_ea_id"]) if team is not None else None
        league_name = str(team["league_name"] or "") if team is not None else ""
        observed_date = str(career_date or snapshot["career_date"] or "")
        season_start = season_start_from_date(observed_date) or date.fromisoformat(observed_date[:10]).year
        profile = self.finance_core.dynamic_revenue.profile_for(league_id, league_name, season_start)
        fx = self.finance_core.dynamic_revenue.catalog.get("fxToEur") or {"EUR": 1.0}
        currency = str(profile.get("nativeCurrency") or "EUR")
        to_eur = float(fx.get(currency, 1.0))
        team_count = max(1, int(profile.get("teamCount") or 18))
        if profile.get("annualPoolMajor") is not None:
            per_team_eur = float(profile.get("annualPoolMajor") or 0) * to_eur / team_count
        else:
            per_team_eur = (float(profile.get("individualBaseMajor") or 0) + float(profile.get("individualSpreadMajor") or 0) * 0.5) * to_eur
        factor = _clamp(0.82 + 0.15 * math.log1p(max(0.0, per_team_eur) / 10_000_000), 0.70, 1.18)
        return {
            "factor": factor,
            "profileKey": profile.get("key"),
            "quality": profile.get("quality"),
            "projected": bool(profile.get("projected")),
            "leagueName": league_name,
            "perTeamMediaEur": round(per_team_eur),
        }

    @staticmethod
    def _club_market_factor(team: sqlite3.Row | None, live_overall: float | None) -> float:
        if team is None:
            return 0.78
        domestic = as_int(team["domestic_prestige"]) or 4
        international = as_int(team["international_prestige"]) or 2
        overall = live_overall if live_overall is not None else 65.0
        return _clamp(0.78 + domestic * 0.020 + international * 0.025 + max(0, overall - 65) * 0.003, 0.80, 1.18)

    def analyze(self, snapshot_id: int, player_id: int) -> dict[str, Any]:
        dynamic = self.player_dynamics.analyze(snapshot_id, player_id)
        with self.database.connect() as conn:
            snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError("Snapshot not found.")
            player = conn.execute(
                "SELECT * FROM player_states WHERE snapshot_id=? AND ea_player_id=?", (snapshot_id, player_id)
            ).fetchone()
            if not player:
                raise ValueError("Player not found in the selected snapshot.")
            roster = conn.execute(
                "SELECT * FROM roster_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            contract = conn.execute(
                "SELECT * FROM contract_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            team = conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?", (snapshot_id, player["team_ea_id"])
            ).fetchone() if player["team_ea_id"] is not None else None
            legacy = self.financial.calculate_player(conn, snapshot, player, roster=roster, contract=contract)
            raw = parse_raw(player["raw_json"])
            evaluation_date = effective_career_date(conn, snapshot)
            age = age_on_date(raw.get("birthdate_raw"), evaluation_date)
            overall = as_int(player["overall"]) or 0
            potential = as_int(player["potential"]) or overall
            dynamic_overall = float(dynamic.get("dynamicOverallExact") or overall)
            contract_years = self._contract_years(player["contract_valid_until"], evaluation_date)
            stats = dynamic.get("stats") or {}

            league_context = self._league_market_context(team, snapshot, evaluation_date)
            league_factor = float(league_context["factor"])
            team_strength = live_squad_strength(conn, snapshot_id, int(player["team_ea_id"])) if player["team_ea_id"] is not None else {"average": None}
            club_factor = self._club_market_factor(team, team_strength["average"])
            age_factor = self._age_market_factor(age, dynamic_overall)
            position_factor = self._position_market_factor(player["primary_position"])
            gap = max(0.0, potential - overall)
            development_weight = 0.045 if age is not None and age <= 20 else 0.035 if age is not None and age <= 23 else 0.018 if age is not None and age <= 26 else 0.006
            potential_factor = _clamp(1 + gap * development_weight, 1.0, 1.78)
            reputation = _raw_number(raw, ("international_reputation", "internationalreputation", "reputation"))
            reputation_factor = _clamp(0.96 + (float(reputation or 1) - 1) * 0.040, 0.96, 1.12)
            if contract_years < 0.5:
                contract_factor = 0.58
            elif contract_years < 1.25:
                contract_factor = 0.78
            elif contract_years < 2.25:
                contract_factor = 0.96
            elif contract_years < 3.5:
                contract_factor = 1.04
            else:
                contract_factor = 1.08
            team_gender = as_int(team["gender"]) if team is not None else None
            is_women = self.financial._is_women(raw, parse_raw(team["raw_json"]) if team is not None else {})
            market_scale = 0.045 if is_women else 1.0

            # Temporary form must matter without turning three hot months into a
            # permanent world-record premium. Its share therefore falls toward the
            # elite end; this is the one and only performance input to market value.
            dynamic_delta = float(dynamic.get("delta") or 0)
            dynamic_market_weight = _clamp(.72 - max(0.0, overall - 78.0) * .022, .32, .72)
            market_rating = _clamp(overall + dynamic_delta * dynamic_market_weight, 35.0, 99.0)
            quality_core = _interpolate_anchor(market_rating, MARKET_VALUE_ANCHORS)
            elite_context_damping = _clamp(1.0 - max(0.0, market_rating - 82.0) * .045, .35, 1.0)
            applied_factors = {
                "age": 1.0 + (age_factor - 1.0) * elite_context_damping,
                "potential": 1.0 + (potential_factor - 1.0) * elite_context_damping,
                "position": 1.0 + (position_factor - 1.0) * elite_context_damping,
                "league": 1.0 + (league_factor - 1.0) * elite_context_damping,
                "club": 1.0 + (club_factor - 1.0) * elite_context_damping,
                "reputation": 1.0 + (reputation_factor - 1.0) * elite_context_damping,
                "contract": 1.0 + (contract_factor - 1.0) * elite_context_damping,
            }
            atlas_value = _round_major(
                quality_core * math.prod(applied_factors.values()) * market_scale
            )
            coverage_missing = sum(1 for value in (age, player["team_ea_id"], team, stats.get("average_rating")) if value is None)
            performance_source = dynamic.get("performanceSource")
            source_uncertainty = 0.06 if performance_source == "simulated" else 0.03 if performance_source == "hybrid" else 0.0
            uncertainty = _clamp(0.10 + coverage_missing * 0.035 + source_uncertainty, 0.10, 0.30)
            low = _round_major(atlas_value * (1 - uncertainty))
            high = _round_major(atlas_value * (1 + uncertainty))

            avg_squad = float(team_strength["average"] if team_strength["average"] is not None else overall)
            usage = int(stats.get("appearances") or 0) / max(1, int((dynamic.get("breakdown") or {}).get("teamMatches") or 1))
            importance = _clamp(1 + (dynamic_overall - avg_squad) * 0.027 + min(0.10, usage * 0.10), 0.93, 1.28)
            seller_ask = _round_major(high * importance)
            seller_floor = _round_major(low * _clamp(0.96 + (contract_years - 1) * 0.025, 0.78, 1.06))

            managed_team_id = as_int(snapshot["managed_team_ea_id"])
            # A snapshot contract wage is the strongest salary evidence regardless
            # of club ownership. Historically PlayerFinance only exposed observed
            # wages for the managed club, which made foreign-player negotiations
            # lose a perfectly usable snapshot salary. When no contract wage is
            # present, the existing atlas-player-finance-v4 market-wage model below
            # remains the single fallback; no second salary model is introduced.
            observed_current_wage = as_int(contract["wage"]) if contract is not None else None
            current_wage = observed_current_wage
            # Wages have their own curve. Temporary form affects salary expectations
            # much more slowly than transfer value, so only 35% of the Dynamic-OVR
            # change is used for a hypothetical new contract.
            wage_overall = _clamp(overall + float(dynamic.get("delta") or 0) * .35, 35.0, 99.0)
            wage_base = _interpolate_anchor(wage_overall, WEEKLY_WAGE_ANCHORS)
            wage_age = 0.80 if age is not None and age <= 20 else 0.90 if age is not None and age <= 23 else 1.0 if age is None or age <= 30 else 0.95
            wage_reputation = _clamp(0.94 + (float(reputation or 1) - 1) * .065, .94, 1.20)
            wage_position = 1.05 if str(player["primary_position"] or "").upper() in {"ST", "CF", "LW", "RW", "CAM", "ZOM"} else 1.0
            market_wage = _round_wage(
                wage_base * wage_age * _clamp(league_factor, .78, 1.14)
                * _clamp(club_factor, .84, 1.14) * wage_reputation * wage_position
            )
            current_anchor = int(current_wage) if current_wage is not None else market_wage
            demand_center = max(market_wage, int(current_anchor * (1.07 if contract_years <= 1.25 else 1.0)))
            demand_low = _round_wage(demand_center * 0.95)
            demand_high = _round_wage(demand_center * (1.15 if dynamic_overall >= avg_squad + 3 else 1.09))

            override = self._override(conn, int(snapshot["career_id"]), snapshot_id, player_id)
            if override:
                if override.get("market_value_minor") is not None:
                    atlas_value = int(override["market_value_minor"]) // 100
                    low = _round_major(atlas_value * (1 - uncertainty))
                    high = _round_major(atlas_value * (1 + uncertainty))
                    seller_ask = _round_major(high * importance)
                    seller_floor = _round_major(low * _clamp(0.96 + (contract_years - 1) * 0.025, 0.78, 1.06))
                if override.get("market_wage_weekly_minor") is not None:
                    market_wage = int(override["market_wage_weekly_minor"]) // 100
                    demand_low = _round_wage(market_wage * 0.95)
                    demand_high = _round_wage(market_wage * 1.15)

            factors = [
                self._factor("Leistungsniveau", 1.0, f"Basis-OVR {overall}; Dynamic OVR {dynamic_overall:.1f} ({dynamic_delta:+.1f}) has a one-time, dampened effect as market rating {market_rating:.1f}."),
                self._factor("Liga-Markt", applied_factors["league"], f"{league_context['leagueName'] or 'Liga unknown'} · Profil {league_context['profileKey']} · quality {league_context['quality']}."),
                self._factor("Club context", applied_factors["club"], "Prestige, international standing and squad strength affect demand and visibility."),
                self._factor("Potenzial", applied_factors["potential"], f"POT gap to unchanged base OVR: {gap:.1f}."),
                self._factor("Alter & Wiederverkauf", applied_factors["age"], f"Alter {age if age is not None else 'unknown'}."),
                self._factor("Positioneller Markt", applied_factors["position"], "Position-specific scarcity and real-world price levels."),
                self._factor("Contract term", applied_factors["contract"], f"Approximately {contract_years:.1f} contract years."),
                self._factor("Reputation", applied_factors["reputation"], "Internationale Reputation, soweit im Snapshot vorhanden."),
            ]

            return {
                "modelId": MODEL_ID,
                "mode": QUALITY,
                "player": {"eaPlayerId": player_id, "displayName": player["display_name"], "position": player["primary_position"], "overall": overall, "potential": potential, "age": age},
                "dynamic": dynamic,
                "legacy": {
                    "marketValue": legacy.get("market_value", {}).get("value"),
                    "weeklyWage": legacy.get("weekly_wage", {}).get("value"),
                    "marketLabel": "EA-Kontrollwert",
                    "wageLabel": legacy.get("weekly_wage", {}).get("label"),
                },
                "market": {
                    "value": atlas_value, "rangeLow": low, "rangeHigh": high,
                    "sellerFloor": seller_floor, "sellerAsk": seller_ask,
                    "uncertaintyPct": round(uncertainty * 100, 1),
                    "overridden": bool(override and override.get("market_value_minor") is not None),
                    "primary": True,
                },
                "wage": {
                    "current": current_wage, "currentObserved": current_wage,
                    "display": current_wage if current_wage is not None else market_wage,
                    "displayLabel": "Snapshot-Wochengehalt" if current_wage is not None else "Atlas-Wochengehalt",
                    "operativeSource": "snapshot_contract" if current_wage is not None else "atlas_player_finance_v4",
                    "annualDisplay": (current_wage if current_wage is not None else market_wage) * 52,
                    "market": market_wage, "annualMarket": market_wage * 52,
                    "demandLow": demand_low, "demandHigh": demand_high,
                    "overridden": bool(override and override.get("market_wage_weekly_minor") is not None),
                },
                "factors": factors,
                "stats": stats,
                "context": {
                    "contractYears": round(contract_years, 2), "squadAverageOverall": round(avg_squad, 2),
                    "importanceFactor": round(importance, 3), "positionGroup": position_group(player["primary_position"]),
                    "teamMatches": (dynamic.get("breakdown") or {}).get("teamMatches"),
                    "leagueMarket": league_context, "clubMarketFactor": round(club_factor, 3),
                    "eliteContextDamping": round(elite_context_damping, 3),
                    "dynamicMarketWeight": round(dynamic_market_weight, 3),
                    "marketRating": round(market_rating, 2),
                    "gender": team_gender, "marketScale": market_scale,
                },
                "override": override,
                "notes": [
                    "Atlas market value is the primary independent valuation and does not imitate the EA formula.",
                    "In-game OVR and POT remain unchanged; the seasonal Atlas performance value is separate.",
                    "Simulated performance data is clearly labelled and is not claimed as match history.",
                    "A club asking price is not a neutral market value.",
                ],
            }
