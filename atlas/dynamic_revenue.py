from __future__ import annotations

import json
import math
import re
import sqlite3
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

from .media_utils import season_start_from_date
from .tracker_context import stadium_capacity_overlay

PROFILE_FILE = "dynamic_revenue_profiles_v1.json"
MODEL_VERSION = "dynamic-revenue-1"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalise_name(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("uefa", " ").replace("ea sports", " ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return " ".join(text.split())


def _month_date(year: int, month_day: str) -> date:
    month, day = [int(part) for part in month_day.split("-", 1)]
    calendar_year = year if month >= 7 else year + 1
    return date(calendar_year, month, day)


class DynamicRevenueEngine:
    """Deterministic, explainable season revenue and club-cost generator.

    The engine never posts directly. It produces idempotent suggestions for the
    Financial Core. The service layer decides when a due suggestion becomes a
    journal entry.
    """

    def __init__(self, profile_path: Path):
        self.profile_path = profile_path
        self.catalog = self._load()

    def _load(self) -> dict[str, Any]:
        with self.profile_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("modelVersion") != MODEL_VERSION:
            raise ValueError("Unknowne Dynamic-Revenue-Profilversion.")
        allowed_quality = {"official", "reconstructed", "calibrated", "estimated"}
        source_keys = {str(item.get("key")) for item in data.get("sources") or []}
        profile_keys: set[str] = set()
        for profile in data.get("profiles") or []:
            key = str(profile.get("key") or "")
            if not key or key in profile_keys:
                raise ValueError("League profiles require unique keys.")
            profile_keys.add(key)
            if profile.get("quality") not in allowed_quality:
                raise ValueError(f"Invalid data quality in league profile {key}.")
            if int(profile.get("validFromSeason", 0)) > int(profile.get("validToSeason", 0)):
                raise ValueError(f"Invalid rights cycle in league profile {key}.")
            unknown_sources = set(profile.get("sourceKeys") or []) - source_keys
            if unknown_sources:
                raise ValueError(f"Unknowne Quellen im Liga-Profil {key}: {sorted(unknown_sources)}")
            if profile.get("distributionModel") == "central":
                weight_sum = sum(float(value) for value in (profile.get("weights") or {}).values())
                if not 0.98 <= weight_sum <= 1.02:
                    raise ValueError(f"Verteilungsgewichte im Liga-Profil {key} do not add up to 100 percent.")
        if not data.get("fallback"):
            raise ValueError("Fallback profile for unknown leagues is missing.")
        return data

    def sources(self) -> list[dict[str, Any]]:
        return list(self.catalog.get("sources") or [])

    def quality_label(self, key: str) -> str:
        return str((self.catalog.get("qualityLabels") or {}).get(key) or key)

    def _profile_candidates(self, league_id: int | None, league_name: str, season_start_year: int) -> list[dict[str, Any]]:
        name = _normalise_name(league_name)
        result: list[dict[str, Any]] = []
        for profile in self.catalog.get("profiles") or []:
            if season_start_year < int(profile.get("validFromSeason", 0)):
                continue
            if season_start_year > int(profile.get("validToSeason", 9999)):
                continue
            ids = {int(value) for value in profile.get("leagueIds") or []}
            aliases = [_normalise_name(value) for value in profile.get("aliases") or []]
            id_match = league_id is not None and int(league_id) in ids
            name_match = any(alias and (alias == name or alias in name or name in alias) for alias in aliases)
            if id_match or name_match:
                score = (10 if id_match else 0) + max((len(alias) for alias in aliases if alias and alias in name), default=0)
                result.append({**profile, "_score": score})
        return sorted(result, key=lambda item: int(item.get("_score", 0)), reverse=True)

    def profile_for(self, league_id: int | None, league_name: str, season_start_year: int) -> dict[str, Any]:
        candidates = self._profile_candidates(league_id, league_name, season_start_year)
        projected = False
        if candidates:
            profile = dict(candidates[0])
            profile.pop("_score", None)
        else:
            # A rights-cycle profile may expire while a career continues. Carry the latest
            # matching structure forward only as an explicitly estimated projection.
            name = _normalise_name(league_name)
            past: list[dict[str, Any]] = []
            for item in self.catalog.get("profiles") or []:
                ids = {int(value) for value in item.get("leagueIds") or []}
                aliases = [_normalise_name(value) for value in item.get("aliases") or []]
                matches = (league_id is not None and int(league_id) in ids) or any(
                    alias and (alias == name or alias in name or name in alias) for alias in aliases
                )
                if matches and int(item.get("validToSeason", -1)) < season_start_year:
                    past.append(item)
            if past:
                profile = dict(max(past, key=lambda item: int(item.get("validToSeason", 0))))
                projected = True
                profile["key"] = f"{profile.get('key')}_projected_{season_start_year}"
                profile["quality"] = "estimated"
                profile["notes"] = "Continuation of an expired rights cycle. Distribution remains structurally unchanged; volume is an Atlas estimate."
                profile["validFromSeason"] = season_start_year
                profile["validToSeason"] = season_start_year
            else:
                profile = dict(self.catalog.get("fallback") or {})
                profile["aliases"] = [league_name or "Unknowne Liga"]
                profile["leagueIds"] = [league_id] if league_id is not None else []
                profile["validFromSeason"] = season_start_year
                profile["validToSeason"] = season_start_year
                projected = True
        base_season = int(profile.get("poolBaseSeason", profile.get("validFromSeason", season_start_year)))
        growth = float(profile.get("annualGrowthRate", 0.02 if projected else 0.0))
        if projected and growth == 0:
            growth = 0.02
        years = max(0, season_start_year - base_season)
        factor = (1.0 + growth) ** years
        if profile.get("annualPoolMajor") is not None:
            profile["baseAnnualPoolMajor"] = float(profile["annualPoolMajor"])
            profile["annualPoolMajor"] = float(profile["annualPoolMajor"]) * factor
        for key in ("individualBaseMajor", "individualSpreadMajor"):
            if profile.get(key) is not None:
                profile[f"base{key[0].upper()}{key[1:]}"] = float(profile[key])
                profile[key] = float(profile[key]) * factor
        profile["projectionFactor"] = round(factor, 6)
        profile["projected"] = projected
        return profile

    def _convert_major(self, amount: float, native_currency: str, base_currency: str) -> int:
        rates = self.catalog.get("fxToEur") or {"EUR": 1.0}
        native_to_eur = float(rates.get(native_currency, 1.0))
        base_to_eur = float(rates.get(base_currency, 1.0))
        base_major = float(amount) * native_to_eur / base_to_eur
        return int(round(base_major * 100))

    def _latest_snapshot(self, conn: sqlite3.Connection, career_id: int, start_year: int) -> sqlite3.Row | None:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC",
            (career_id,),
        ).fetchall()
        return next((row for row in rows if season_start_from_date(row["career_date"]) == start_year), None)

    def _managed_context(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> dict[str, Any]:
        start_year = int(period["season_start_year"])
        snapshot = self._latest_snapshot(conn, career_id, start_year)
        if not snapshot:
            return {
                "snapshot": None, "teamId": None, "teamName": None, "leagueId": None,
                "leagueName": "Unknowne Liga", "leagueLevel": None, "position": None,
                "teamCount": None, "stadiumCapacity": 10000, "domesticPrestige": 4,
                "internationalPrestige": 2, "weeklyWagesMinor": 0, "teamRows": [],
            }
        team_id = snapshot["managed_team_ea_id"]
        team = conn.execute(
            "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
            (snapshot["id"], team_id),
        ).fetchone()
        league_id = int(team["league_ea_id"]) if team and team["league_ea_id"] is not None else None
        league = conn.execute(
            "SELECT * FROM league_states WHERE snapshot_id=? AND ea_league_id=?",
            (snapshot["id"], league_id),
        ).fetchone() if league_id is not None else None
        table = conn.execute(
            "SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?",
            (snapshot["id"], team_id),
        ).fetchone()
        team_rows = conn.execute(
            "SELECT ts.*,tls.current_table_position,tls.points,tls.matches_played "
            "FROM team_states ts LEFT JOIN team_league_states tls "
            "ON tls.snapshot_id=ts.snapshot_id AND tls.team_ea_id=ts.ea_team_id "
            "WHERE ts.snapshot_id=? AND ts.league_ea_id=?",
            (snapshot["id"], league_id),
        ).fetchall() if league_id is not None else []
        wages = conn.execute(
            "SELECT COALESCE(SUM(wage),0) total FROM contract_states WHERE snapshot_id=? AND team_ea_id=?",
            (snapshot["id"], team_id),
        ).fetchone()
        base_capacity = max(1000, int(team["stadium_capacity"] or 10000)) if team else 10000
        capacity = stadium_capacity_overlay(conn, career_id, base_capacity)
        return {
            "snapshot": snapshot,
            "teamId": int(team_id) if team_id is not None else None,
            "teamName": snapshot["managed_team_name"] or (team["team_name"] if team else None),
            "leagueId": league_id,
            "leagueName": (team["league_name"] if team else None) or (league["league_name"] if league else None) or "Unknowne Liga",
            "leagueLevel": int(league["level"]) if league and league["level"] is not None else None,
            "position": int(table["current_table_position"]) if table and table["current_table_position"] is not None else None,
            "matchesPlayed": int(table["matches_played"]) if table and table["matches_played"] is not None else None,
            "teamCount": len(team_rows) or None,
            "snapshotStadiumCapacity": capacity["snapshotCapacity"],
            "atlasAddedStadiumCapacity": capacity["atlasAddedCapacity"],
            "stadiumCapacity": capacity["effectiveCapacity"],
            "domesticPrestige": int(team["domestic_prestige"] or 4) if team else 4,
            "internationalPrestige": int(team["international_prestige"] or 2) if team else 2,
            "profitability": int(team["profitability"]) if team and team["profitability"] is not None else None,
            "weeklyWagesMinor": int(wages["total"] or 0) * 100,
            "teamRows": team_rows,
        }

    def _latest_fixtures(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT f.id fixture_id,f.competition_object_id,f.static_competition_id,f.home_team_ea_id,"
            "f.away_team_ea_id,fo.*,s.import_sequence FROM fixtures f "
            "JOIN fixture_observations fo ON fo.fixture_id=f.id "
            "JOIN snapshots s ON s.id=fo.snapshot_id "
            "WHERE f.career_id=? AND fo.managed_team_involved=1 AND fo.date>=? AND fo.date<=? "
            "ORDER BY f.id,s.import_sequence DESC",
            (career_id, period["start_date"], period["end_date"]),
        ).fetchall()
        seen: set[int] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            fixture_id = int(row["fixture_id"])
            if fixture_id in seen:
                continue
            seen.add(fixture_id)
            result.append(dict(row))
        return sorted(result, key=lambda item: (str(item.get("date") or ""), str(item.get("time") or ""), int(item["fixture_id"])))

    def _audience_scores(self, context: dict[str, Any]) -> tuple[float, float]:
        rows = context.get("teamRows") or []
        if not rows:
            own = 1.0 + context["domesticPrestige"] ** 1.7 + context["internationalPrestige"] * 1.5 + context["stadiumCapacity"] / 20000
            return own, own * max(1, int(context.get("teamCount") or 18))
        total = 0.0
        own = 0.0
        for row in rows:
            score = (
                1.0
                + float(row["domestic_prestige"] or 3) ** 1.7
                + float(row["international_prestige"] or 1) * 1.5
                + float(row["stadium_capacity"] or 10000) / 20000
            )
            total += score
            if int(row["ea_team_id"]) == int(context["teamId"]):
                own = score
        return own or 1.0, total or 1.0

    def _media_share_major(self, profile: dict[str, Any], context: dict[str, Any]) -> dict[str, float]:
        n = int(context.get("teamCount") or profile.get("teamCount") or 18)
        position = int(context.get("position") or max(1, math.ceil(n / 2)))
        position = max(1, min(n, position))
        prestige = _clamp((float(context.get("domesticPrestige") or 4) + float(context.get("internationalPrestige") or 2)) / 18.0, 0.05, 1.0)
        model = str(profile.get("distributionModel") or "central")
        if model == "individual":
            base = float(profile.get("individualBaseMajor") or 0)
            spread = float(profile.get("individualSpreadMajor") or 0)
            annual = base + spread * prestige ** 1.35
            performance = annual * float((profile.get("weights") or {}).get("merit", 0.2))
            return {"equal": annual - performance, "merit": performance, "audience": 0.0, "youth": 0.0, "total": annual}
        pool = float(profile.get("annualPoolMajor") or 0)
        weights = profile.get("weights") or {}
        equal = pool * float(weights.get("equal", 0)) / n
        rank_points = n - position + 1
        merit = pool * float(weights.get("merit", 0)) * rank_points / (n * (n + 1) / 2)
        own_audience, total_audience = self._audience_scores(context)
        audience = pool * float(weights.get("audience", 0)) * own_audience / total_audience
        youth_weight = float(weights.get("youth", 0))
        youth = pool * youth_weight / n
        return {"equal": equal, "merit": merit, "audience": audience, "youth": youth, "total": equal + merit + audience + youth}

    def _event(self, source_key: str, event_type: str, direction: str, category: str,
               event_date: date, amount_minor: int, profile: dict[str, Any],
               description: str, explanation: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "sourceKey": source_key,
            "eventType": event_type,
            "direction": direction,
            "categoryKey": category,
            "eventDate": event_date.isoformat(),
            "amountMinor": max(0, int(amount_minor)),
            "amountStatus": "estimated" if profile.get("quality") != "official" else "known",
            "modelProfileKey": profile.get("key"),
            "qualityGrade": profile.get("quality") or "estimated",
            "description": description,
            "explanation": explanation,
            **extra,
        }

    def _result_for_managed(self, fixture: dict[str, Any], team_id: int) -> str | None:
        if not fixture.get("is_completed"):
            return None
        home = int(fixture.get("home_team_ea_id") or 0) == team_id
        own = int(fixture.get("home_score") or 0) if home else int(fixture.get("away_score") or 0)
        opp = int(fixture.get("away_score") or 0) if home else int(fixture.get("home_score") or 0)
        if own > opp:
            return "W"
        if own < opp:
            return "L"
        hp = fixture.get("home_penalties")
        ap = fixture.get("away_penalties")
        if hp is not None and ap is not None and int(hp) != int(ap):
            won = int(hp) > int(ap) if home else int(ap) > int(hp)
            return "W" if won else "L"
        return "D"

    def _competition_kind(self, name: str, league_name: str) -> str:
        comp = _normalise_name(name)
        league = _normalise_name(league_name)
        if "champions league" in comp:
            return "ucl"
        if "europa league" in comp:
            return "uel"
        if "conference league" in comp:
            return "uecl"
        if league and (league in comp or comp in league):
            return "league"
        if any(token in comp for token in ("cup", "pokal", "copa", "coppa", "coupe", "taça", "taca")):
            return "cup"
        return "other"

    def _matchday_events(self, profile: dict[str, Any], context: dict[str, Any], fixtures: list[dict[str, Any]],
                         base_currency: str, financial_start: date) -> list[dict[str, Any]]:
        cfg = profile.get("matchday") or {}
        capacity = int(context["stadiumCapacity"])
        snapshot_capacity = int(context.get("snapshotStadiumCapacity") or capacity)
        atlas_added_capacity = int(context.get("atlasAddedStadiumCapacity") or 0)
        ticket = self._convert_major(float(cfg.get("ticketPriceMajor", 25)), profile["nativeCurrency"], base_currency)
        hospitality = self._convert_major(float(cfg.get("hospitalityPerHeadMajor", 4)), profile["nativeCurrency"], base_currency)
        concessions = self._convert_major(float(cfg.get("concessionsPerHeadMajor", 5)), profile["nativeCurrency"], base_currency)
        variable_cost = self._convert_major(float(cfg.get("variableCostPerHeadMajor", 3)), profile["nativeCurrency"], base_currency)
        fixed_cost = self._convert_major(float(cfg.get("fixedCostMajor", 50000)), profile["nativeCurrency"], base_currency)
        season_share = float(cfg.get("seasonTicketShare", 0.5))
        base_fill = float(cfg.get("baseFill", 0.7))
        history: list[str] = []
        events: list[dict[str, Any]] = []
        team_id = int(context["teamId"])
        rows_by_team = {int(row["ea_team_id"]): row for row in context.get("teamRows") or []}
        for fixture in fixtures:
            result = self._result_for_managed(fixture, team_id)
            fixture_date = date.fromisoformat(str(fixture["date"]))
            if result:
                history.append(result)
            if not fixture.get("is_completed") or fixture_date < financial_start:
                continue
            if int(fixture.get("home_team_ea_id") or 0) != team_id:
                continue
            opponent_id = int(fixture.get("away_team_ea_id") or 0)
            opponent = rows_by_team.get(opponent_id)
            opponent_prestige = float(opponent["domestic_prestige"] or 3) if opponent else 3.0
            own_prestige = float(context.get("domesticPrestige") or 4)
            form_slice = history[-6:-1] if len(history) > 1 else []
            form_adjustment = sum(0.018 if item == "W" else 0.002 if item == "D" else -0.012 for item in form_slice)
            kind = self._competition_kind(str(fixture.get("competition_name") or ""), str(context["leagueName"]))
            competition_adjustment = 0.04 if kind in {"ucl", "uel", "uecl"} else 0.025 if kind == "cup" else 0.0
            opponent_adjustment = _clamp((opponent_prestige - own_prestige) * 0.012, -0.05, 0.08)
            late_adjustment = 0.025 if fixture_date.month in {4, 5, 6} else 0.0
            demand_rate = _clamp(base_fill + form_adjustment + competition_adjustment + opponent_adjustment + late_adjustment, 0.35, 1.30)
            modeled_demand = max(0, int(round(snapshot_capacity * demand_rate)))
            attendance = max(0, min(capacity, modeled_demand))
            fill = attendance / capacity if capacity else 0.0
            capacity_attendance_gain = max(0, attendance - min(snapshot_capacity, modeled_demand))
            effective_ticket = int(round(ticket * (1 - season_share * 0.22)))
            ticket_income = attendance * effective_ticket
            hospitality_income = attendance * hospitality
            concessions_income = attendance * concessions
            gross = ticket_income + hospitality_income + concessions_income
            costs = fixed_cost + attendance * variable_cost
            explanation = {
                "attendance": attendance, "capacity": capacity, "fillRate": round(fill, 4),
                "snapshotCapacity": snapshot_capacity, "atlasAddedCapacity": atlas_added_capacity,
                "modeledDemand": modeled_demand, "demandRate": round(demand_rate, 4),
                "attendanceGainedFromAtlasCapacity": capacity_attendance_gain,
                "ticketIncomeMinor": ticket_income, "hospitalityMinor": hospitality_income,
                "concessionsMinor": concessions_income, "competitionKind": kind,
                "formAdjustment": round(form_adjustment, 4),
                "opponentAdjustment": round(opponent_adjustment, 4),
                "competitionAdjustment": round(competition_adjustment, 4),
                "opponent": fixture.get("away_team_name"),
            }
            events.append(self._event(
                f"matchday:{fixture['fixture_id']}:income", "matchday_income", "income", "match_income",
                fixture_date, gross, profile,
                f"Spieltagseinnahmen gegen {fixture.get('away_team_name') or 'Gegner'}",
                explanation, fixtureId=int(fixture["fixture_id"]),
                competitionEaId=fixture.get("competition_object_id"),
                competitionName=fixture.get("competition_name"),
            ))
            events.append(self._event(
                f"matchday:{fixture['fixture_id']}:cost", "matchday_cost", "expense", "club_operations",
                fixture_date, costs, profile,
                f"Spieltagsbetrieb gegen {fixture.get('away_team_name') or 'Gegner'}",
                {**explanation, "fixedCostMinor": fixed_cost, "variableCostMinor": attendance * variable_cost},
                fixtureId=int(fixture["fixture_id"]),
                competitionEaId=fixture.get("competition_object_id"),
                competitionName=fixture.get("competition_name"),
            ))
        return events

    def _uefa_events(self, profile: dict[str, Any], context: dict[str, Any], fixtures: list[dict[str, Any]],
                     base_currency: str, financial_start: date, season_start_year: int) -> list[dict[str, Any]]:
        definitions = {
            "ucl": {"start": 18_620_000, "win": 2_100_000, "draw": 700_000, "pay": "09-20", "label": "Champions League"},
            "uel": {"start": 4_310_000, "win": 450_000, "draw": 150_000, "pay": "09-27", "label": "Europa League"},
            "uecl": {"start": 3_170_000, "win": 400_000, "draw": 133_000, "pay": "09-27", "label": "Conference League"},
        }
        by_kind: dict[str, list[dict[str, Any]]] = {key: [] for key in definitions}
        for fixture in fixtures:
            kind = self._competition_kind(str(fixture.get("competition_name") or ""), str(context["leagueName"]))
            if kind in by_kind:
                by_kind[kind].append(fixture)
        events: list[dict[str, Any]] = []
        for kind, rows in by_kind.items():
            if not rows:
                continue
            spec = definitions[kind]
            start_date = _month_date(season_start_year, str(spec["pay"]))
            if start_date >= financial_start:
                amount = self._convert_major(spec["start"], "EUR", base_currency)
                events.append(self._event(
                    f"uefa:{kind}:{season_start_year}:starting", "prize_money", "income", "match_income",
                    start_date, amount, {**profile, "key": f"uefa_{kind}_2024_27", "quality": "official" if season_start_year <= 2026 else "estimated"},
                    f"{spec['label']} – starting bonus" + ("" if season_start_year <= 2026 else " (fortgeschrieben)"),
                    {"officialNativeAmountMajor": spec["start"], "nativeCurrency": "EUR", "component": "starting_fee",
                     "sourceKey": "uefa_2024_27", "projectedBeyondCycle": season_start_year > 2026},
                    competitionEaId=rows[0].get("competition_object_id"),
                    competitionName=rows[0].get("competition_name"),
                ))
            team_id = int(context["teamId"])
            for fixture in rows:
                if not fixture.get("is_completed"):
                    continue
                event_date = date.fromisoformat(str(fixture["date"]))
                if event_date < financial_start:
                    continue
                result = self._result_for_managed(fixture, team_id)
                native = spec["win"] if result == "W" else spec["draw"] if result == "D" else 0
                if not native:
                    continue
                amount = self._convert_major(native, "EUR", base_currency)
                events.append(self._event(
                    f"uefa:{kind}:fixture:{fixture['fixture_id']}", "prize_money", "income", "match_income",
                    event_date, amount, {**profile, "key": f"uefa_{kind}_2024_27", "quality": "official" if season_start_year <= 2026 else "estimated"},
                    f"{spec['label']} – {'win bonus' if result == 'W' else 'draw bonus'}" + ("" if season_start_year <= 2026 else " (fortgeschrieben)"),
                    {"officialNativeAmountMajor": native, "nativeCurrency": "EUR", "result": result,
                     "sourceKey": "uefa_2024_27", "projectedBeyondCycle": season_start_year > 2026},
                    fixtureId=int(fixture["fixture_id"]),
                    competitionEaId=fixture.get("competition_object_id"),
                    competitionName=fixture.get("competition_name"),
                ))
        return events

    def _domestic_cup_events(self, profile: dict[str, Any], context: dict[str, Any], fixtures: list[dict[str, Any]],
                             base_currency: str, financial_start: date) -> list[dict[str, Any]]:
        team_id = int(context["teamId"])
        events: list[dict[str, Any]] = []
        league_pool = float(profile.get("annualPoolMajor") or profile.get("individualSpreadMajor") or 20_000_000)
        n = max(1, int(context.get("teamCount") or profile.get("teamCount") or 18))
        base_bonus = max(15_000.0, league_pool / n * 0.012)
        cup_rows = [
            row for row in fixtures
            if self._competition_kind(str(row.get("competition_name") or ""), str(context["leagueName"])) == "cup"
        ]
        for index, fixture in enumerate(cup_rows):
            if not fixture.get("is_completed"):
                continue
            event_date = date.fromisoformat(str(fixture["date"]))
            if event_date < financial_start or self._result_for_managed(fixture, team_id) != "W":
                continue
            progress = 1.0 + index * 0.45
            native = base_bonus * progress
            amount = self._convert_major(native, str(profile["nativeCurrency"]), base_currency)
            events.append(self._event(
                f"cup:{fixture['fixture_id']}:progress", "prize_money", "income", "match_income",
                event_date, amount, profile,
                f"{fixture.get('competition_name') or 'Pokal'} – progress bonus",
                {"model": "calibrated_domestic_cup_progress", "progressIndex": index + 1,
                 "nativeAmountMajor": round(native, 2), "nativeCurrency": profile["nativeCurrency"]},
                fixtureId=int(fixture["fixture_id"]),
                competitionEaId=fixture.get("competition_object_id"),
                competitionName=fixture.get("competition_name"),
            ))
        return events

    def _monthly_events(self, profile: dict[str, Any], context: dict[str, Any], fixtures: list[dict[str, Any]],
                        base_currency: str, financial_start: date, period: sqlite3.Row,
                        config: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        start_year = int(period["season_start_year"])
        wins = draws = losses = 0
        team_id = int(context["teamId"])
        for fixture in fixtures:
            result = self._result_for_managed(fixture, team_id)
            if result == "W":
                wins += 1
            elif result == "D":
                draws += 1
            elif result == "L":
                losses += 1
        played = wins + draws + losses
        win_rate = wins / played if played else 0.4
        prestige = float(context.get("domesticPrestige") or 4)
        international = float(context.get("internationalPrestige") or 2)
        snapshot = context.get("snapshot")
        top_overall = 75.0
        if snapshot:
            player_rows = config.get("_playerRows") or []
            overalls = sorted([float(row["overall"]) for row in player_rows if row["overall"] is not None], reverse=True)
            if overalls:
                top_overall = sum(overalls[:3]) / min(3, len(overalls))
        commercial = profile.get("commercial") or {}
        annual_native = (
            float(commercial.get("annualBaseMajor", 1_500_000))
            + float(commercial.get("prestigeScaleMajor", 650_000)) * (prestige / 10.0) ** 1.25
            + float(commercial.get("prestigeScaleMajor", 650_000)) * 0.55 * (international / 10.0) ** 1.3
        )
        star_factor = 1.0 + max(0.0, top_overall - 76.0) * 0.025
        performance_factor = 0.84 + win_rate * 0.35
        annual_native *= star_factor * performance_factor * float(config.get("merchandising_multiplier", 1.0))
        monthly_merch = self._convert_major(annual_native / 12, str(profile["nativeCurrency"]), base_currency)
        weekly_wages = int(context.get("weeklyWagesMinor") or 0)
        monthly_wages = int(round(weekly_wages * 52 / 12))
        operations = profile.get("operations") or {}
        monthly_ops_native = (
            float(operations.get("monthlyBaseMajor", 180_000))
            + float(context["stadiumCapacity"]) * float(operations.get("stadiumCostPerSeatAnnualMajor", 75)) / 12
        )
        monthly_ops = self._convert_major(monthly_ops_native, str(profile["nativeCurrency"]), base_currency)
        monthly_ops += int(round(monthly_wages * float(operations.get("wageOverheadRate", 0.16))))
        monthly_ops = int(round(monthly_ops * float(config.get("operations_multiplier", 1.0))))
        development_rules = config.get("_developmentRules") or []
        for month_day in ("07-31","08-31","09-30","10-31","11-30","12-31","01-31","02-28","03-31","04-30","05-31","06-30"):
            event_date = _month_date(start_year, month_day)
            if event_date < financial_start:
                continue
            fraction = 1.0
            if event_date.year == financial_start.year and event_date.month == financial_start.month and financial_start.day > 1:
                days = monthrange(event_date.year, event_date.month)[1]
                fraction = (days - financial_start.day + 1) / days
            merch_amount = int(round(monthly_merch * fraction))
            wage_amount = int(round(monthly_wages * fraction))
            explicit_development_monthly = sum(
                int(rule.get("amount_minor") or 0) for rule in development_rules
                if str(rule.get("start_date") or "9999-12-31") <= event_date.isoformat()
                and (not rule.get("end_date") or str(rule.get("end_date")) >= event_date.isoformat())
                and int(rule.get("active") or 0) == 1
            )
            generic_ops_after_offset = max(0, monthly_ops - explicit_development_monthly)
            ops_amount = int(round(generic_ops_after_offset * fraction))
            proration = {"periodFraction": round(fraction, 6), "proratedFrom": financial_start.isoformat() if fraction < 1 else None}
            if config.get("merchandising_enabled", 1):
                events.append(self._event(
                    f"merch:{start_year}:{event_date.isoformat()}", "merchandising", "income", "commercial_income",
                    event_date, merch_amount, profile, f"Merchandising {event_date.strftime('%m/%Y')}",
                    {"annualNativeMajor": round(annual_native, 2), "starFactor": round(star_factor, 4),
                     "performanceFactor": round(performance_factor, 4), "winRate": round(win_rate, 4),
                     "topThreeOverall": round(top_overall, 2), "nativeCurrency": profile["nativeCurrency"], **proration},
                ))
            if config.get("wages_enabled", 1) and wage_amount > 0:
                events.append(self._event(
                    f"wages:{start_year}:{event_date.isoformat()}", "player_wages", "expense", "player_wages",
                    event_date, wage_amount, {**profile, "quality": "official"},
                    f"Player wages {event_date.strftime('%m/%Y')}",
                    {"weeklyWagesMinor": weekly_wages, "conversion": "weekly_x_52_div_12",
                     "source": "contracts.csv / final snapshot of the season", **proration},
                ))
            if config.get("operations_enabled", 1):
                events.append(self._event(
                    f"operations:{start_year}:{event_date.isoformat()}", "club_operations", "expense", "club_operations",
                    event_date, ops_amount, profile, f"Club operations {event_date.strftime('%m/%Y')}",
                    {"monthlyNativeBaseMajor": round(monthly_ops_native, 2),
                     "stadiumCapacity": context["stadiumCapacity"],
                     "wageOverheadRate": float(operations.get("wageOverheadRate", 0.16)),
                     "explicitDevelopmentMonthlyMinor": explicit_development_monthly,
                     "genericOperationsAfterOffsetMinor": generic_ops_after_offset,
                     "nativeCurrency": profile["nativeCurrency"], **proration},
                ))
        return events

    def build(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row,
              base_currency: str, financial_start_date: str, config: dict[str, Any]) -> dict[str, Any]:
        context = self._managed_context(conn, career_id, period)
        profile = self.profile_for(context.get("leagueId"), str(context.get("leagueName") or ""), int(period["season_start_year"]))
        if config.get("league_profile_key"):
            override = next((item for item in self.catalog.get("profiles") or [] if item.get("key") == config["league_profile_key"]), None)
            if override:
                profile = dict(override)
        fixture_rows = self._latest_fixtures(conn, career_id, period)
        player_rows = []
        if context.get("snapshot") and context.get("teamId") is not None:
            player_rows = conn.execute(
                "SELECT p.overall FROM roster_states r JOIN player_states p "
                "ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id "
                "WHERE r.snapshot_id=? AND r.team_ea_id=?",
                (context["snapshot"]["id"], context["teamId"]),
            ).fetchall()
        development_rules: list[dict[str, Any]] = []
        config = {**config, "_playerRows": player_rows, "_developmentRules": development_rules}
        financial_start = max(date.fromisoformat(str(period["start_date"])), date.fromisoformat(financial_start_date))
        events: list[dict[str, Any]] = []
        if context.get("teamId") is not None:
            if config.get("media_enabled", 1):
                share = self._media_share_major(profile, context)
                guaranteed_native = share["equal"]
                variable_native = share["merit"] + share["audience"] + share["youth"]
                for month_day, fraction, label in (("09-01",0.40,"1. Rate"),("01-15",0.30,"2. Rate"),("04-15",0.30,"3. Rate")):
                    event_date = _month_date(int(period["season_start_year"]), month_day)
                    if event_date < financial_start:
                        continue
                    amount = self._convert_major(guaranteed_native * fraction, str(profile["nativeCurrency"]), base_currency)
                    events.append(self._event(
                        f"media:{period['season_start_year']}:{profile['key']}:{month_day}", "media_rights", "income", "commercial_income",
                        event_date, amount, profile, f"Mediengelder {label}",
                        {"component":"guaranteed","nativeAmountMajor":round(guaranteed_native*fraction,2),
                         "nativeCurrency":profile["nativeCurrency"],"distributionModel":profile.get("distributionModel"),
                         "weights":profile.get("weights"),"leaguePositionUsed":context.get("position"),
                         "teamCount":context.get("teamCount") or profile.get("teamCount"),
                         "sourceKeys":profile.get("sourceKeys") or []},
                    ))
                variable_date = date(int(period["season_start_year"]) + 1, 6, 30)
                if variable_date >= financial_start and variable_native > 0:
                    amount = self._convert_major(variable_native, str(profile["nativeCurrency"]), base_currency)
                    events.append(self._event(
                        f"media:{period['season_start_year']}:{profile['key']}:variable", "media_rights", "income", "commercial_income",
                        variable_date, amount, profile, "Media revenue – performance- and reach-based settlement",
                        {"component":"variable","nativeAmountMajor":round(variable_native,2),
                         "nativeCurrency":profile["nativeCurrency"],"distributionModel":profile.get("distributionModel"),
                         "weights":profile.get("weights"),"leaguePositionUsed":context.get("position"),
                         "teamCount":context.get("teamCount") or profile.get("teamCount"),
                         "sourceKeys":profile.get("sourceKeys") or []},
                    ))
            if config.get("matchday_enabled", 1):
                events.extend(self._matchday_events(profile, context, fixture_rows, base_currency, financial_start))
            if config.get("prize_enabled", 1):
                events.extend(self._uefa_events(profile, context, fixture_rows, base_currency, financial_start, int(period["season_start_year"])))
                events.extend(self._domestic_cup_events(profile, context, fixture_rows, base_currency, financial_start))
            events.extend(self._monthly_events(profile, context, fixture_rows, base_currency, financial_start, period, config))
        events = [event for event in events if int(event.get("amountMinor") or 0) > 0]
        total_income = sum(int(event["amountMinor"]) for event in events if event["direction"] == "income")
        total_expense = sum(int(event["amountMinor"]) for event in events if event["direction"] == "expense")
        used_source_keys = set(profile.get("sourceKeys") or [])
        if any(str(event.get("modelProfileKey") or "").startswith("uefa_") for event in events):
            used_source_keys.add("uefa_2024_27")
        return {
            "profile": profile,
            "context": {key: value for key, value in context.items() if key not in {"snapshot", "teamRows"}},
            "events": events,
            "summary": {
                "incomeMinor": total_income,
                "expenseMinor": total_expense,
                "netMinor": total_income - total_expense,
                "eventCount": len(events),
            },
            "sources": [source for source in self.sources() if source.get("key") in used_source_keys],
        }
