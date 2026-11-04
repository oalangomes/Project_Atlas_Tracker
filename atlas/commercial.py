from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .tracker_context import calibration_context, development_capabilities
from .finance_core import as_minor, input_date, utc_now
from .media_utils import season_start_from_date
from .server_utils import as_int, effective_career_date, parse_raw

MODEL_ID = "atlas-commercial-v5"
BIG_SLOTS = {"shirt_main", "shirt_sleeve", "stadium_naming", "supplier"}
SLOT_LABELS = {
    "shirt_main": "Trikot-Hauptsponsor",
    "shirt_sleeve": "Sleeve sponsor",
    "stadium_naming": "Stadionnamensrechte",
    "supplier": "Supplier",
    "training_ground_naming": "Training-ground naming rights",
    "training_partner": "Trainingspartner",
    "official_partner": "Offizieller Partner",
    "regional_partner": "Regionalpartner",
    "digital_partner": "Digitalpartner",
    "matchday_partner": "Spieltags-Partner",
    "financial_partner": "Finanzpartner",
    "automotive_partner": "Mobility partner",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_money(value: float, step: int = 5000) -> int:
    if step <= 0:
        return int(round(value))
    return int(round(value / step) * step)


def _seed_value(*parts: Any) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _season_label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


class CommercialReference:
    def __init__(self, root: Path):
        self.root = root
        self.sponsors = {int(row["sponsor_id"]): row for row in _read_csv(root / "sponsors" / "sponsors.csv")}
        self.sponsor_markets: dict[int, dict[int, dict[str, str]]] = {}
        for row in _read_csv(root / "sponsors" / "sponsor_markets.csv"):
            self.sponsor_markets.setdefault(int(row["sponsor_id"]), {})[int(row["nation_id"])] = row
        self.sponsor_regions: dict[int, dict[str, dict[str, str]]] = {}
        for row in _read_csv(root / "sponsors" / "sponsor_regions.csv"):
            self.sponsor_regions.setdefault(int(row["sponsor_id"]), {})[row["region_id"]] = row
        self.sponsor_overrides = {
            (int(row["sponsor_id"]), row["sponsorship_type_id"]): row
            for row in _read_csv(root / "sponsors" / "sponsor_type_overrides.csv")
        }
        self.types = {row["sponsorship_type_id"]: row for row in _read_csv(root / "reference" / "sponsorship_types.csv")}
        self.affinities = {
            (row["industry_id"], row["sponsorship_type_id"]): float(row["affinity"])
            for row in _read_csv(root / "reference" / "industry_type_affinities.csv")
        }
        self.regions_by_nation: dict[int, set[str]] = {}
        for row in _read_csv(root / "reference" / "country_regions.csv"):
            self.regions_by_nation.setdefault(int(row["nation_id"]), set()).add(row["region_id"])
        self.suppliers = {int(row["supplier_id"]): row for row in _read_csv(root / "suppliers" / "equipment_suppliers.csv")}
        self.supplier_markets: dict[int, dict[int, dict[str, str]]] = {}
        for row in _read_csv(root / "suppliers" / "supplier_markets.csv"):
            self.supplier_markets.setdefault(int(row["supplier_id"]), {})[int(row["nation_id"])] = row
        self.supplier_regions: dict[int, dict[str, dict[str, str]]] = {}
        for row in _read_csv(root / "suppliers" / "supplier_regions.csv"):
            self.supplier_regions.setdefault(int(row["supplier_id"]), {})[row["region_id"]] = row
        self.supplier_classes = {int(row["class_id"]): row for row in _read_csv(root / "suppliers" / "supplier_contract_classes.csv")}
        self.supplier_values = {int(row["class_id"]): row for row in _read_csv(root / "suppliers" / "supplier_deal_value_guidance.csv")}

    def sponsor_name(self, sponsor_id: int) -> str:
        return str((self.sponsors.get(sponsor_id) or {}).get("name") or f"Sponsor {sponsor_id}")

    def supplier_name(self, supplier_id: int) -> str:
        return str((self.suppliers.get(supplier_id) or {}).get("name") or f"Supplier {supplier_id}")


class CommercialService:
    """Sponsor and supplier contracts using stable season-based offers.

    Reference profiles are bundled CSV files. Career contracts are stored separately
    so later data deactivation never invalidates an existing agreement.
    """

    def __init__(self, database, reference_root: Path | None = None, media=None):
        self.database = database
        self.media = media
        root = reference_root or (Path(__file__).resolve().parents[1] / "reference" / "commercial")
        self.reference = CommercialReference(root)

    @staticmethod
    def _snapshot(conn: sqlite3.Connection, career_id: int, snapshot_id: int | None = None) -> sqlite3.Row:
        if snapshot_id is not None:
            row = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1", (career_id,)).fetchone()
        if not row:
            raise ValueError("Sponsorship requires a snapshot.")
        return row

    def _club_context(self, conn: sqlite3.Connection, career_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        snapshot = self._snapshot(conn, career_id, snapshot_id)
        team_id = as_int(snapshot["managed_team_ea_id"])
        if team_id is None:
            raise ValueError("The managed club is not known in the snapshot.")
        team = conn.execute("SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?", (snapshot["id"], team_id)).fetchone()
        if not team:
            raise ValueError("Club state is missing from the snapshot.")
        league = conn.execute("SELECT * FROM league_states WHERE snapshot_id=? AND ea_league_id=?", (snapshot["id"], team["league_ea_id"])).fetchone()
        table = conn.execute("SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?", (snapshot["id"], team_id)).fetchone()
        raw = parse_raw(team["raw_json"])
        popularity = as_int(raw.get("popularity")) or as_int(raw.get("team_popularity"))
        domestic = as_int(team["domestic_prestige"]) or 3
        international = as_int(team["international_prestige"]) or 1
        capacity = as_int(team["stadium_capacity"]) or 12000
        level = as_int(league["level"]) if league else None
        position = as_int(table["current_table_position"]) if table else None
        teams = 0
        if team["league_ea_id"] is not None:
            teams = int(conn.execute("SELECT COUNT(*) FROM team_states WHERE snapshot_id=? AND league_ea_id=?", (snapshot["id"], team["league_ea_id"])).fetchone()[0])
        performance = 0.5
        if position and teams > 1:
            performance = 1.0 - (position - 1) / (teams - 1)
        shared = calibration_context(conn, career_id, snapshot, team, level)
        pop_score = _clamp(((popularity if popularity is not None else domestic * 10) - 20) / 75, 0, 1) * 100.0
        stadium_score = _clamp(math.log(max(5000, capacity) / 5000, 12), 0, 1) * 100.0
        capabilities = development_capabilities(conn, career_id)
        commercial_capability = float(capabilities.get("commercial", 50.0))
        shared_status = float(shared["commercialStatusScore"])
        score = _clamp(shared_status * 0.86 + pop_score * 0.07 + commercial_capability * 0.05 + performance * 100.0 * 0.02, 20.0, 97.0)
        club_level = int(_clamp(round(1 + score / 100.0 * 19), 1, 20))
        hype_score = _clamp(float(shared["trajectoryScore"]) * 0.72 + performance * 100.0 * 0.28, 15.0, 100.0)
        established_score = _clamp(float(shared["prestigeScore"]) * 0.46 + float(shared["financialScaleScore"]) * 0.34 + pop_score * 0.20, 10.0, 100.0)
        promotion_count = int(shared.get("promotionCount") or 0)
        newly_promoted = promotion_count > 0 and int(shared.get("observedSeasons") or 0) <= 4
        relegation_risk = _clamp((45.0 - performance * 100.0) / 100.0 + (0.12 if newly_promoted else 0.0), 0.0, 0.38)
        career_date = effective_career_date(conn, snapshot)
        season_year = season_start_from_date(career_date)
        status_band = "globale Topmarke" if score >= 91 else "internationaler Spitzenclub" if score >= 82 else "etablierter Erstligist" if score >= 69 else "Wachstumsclub" if score >= 55 else "regionaler Club"
        return {
            "careerId": career_id,
            "snapshotId": int(snapshot["id"]),
            "careerDate": career_date,
            "seasonStartYear": season_year,
            "seasonLabel": _season_label(season_year) if season_year is not None else None,
            "teamEaId": team_id,
            "teamName": team["team_name"],
            "leagueEaId": team["league_ea_id"],
            "leagueName": team["league_name"],
            "nationId": as_int(league["country_id"]) if league else None,
            "leagueLevel": level,
            "tablePosition": position,
            "teamCount": teams,
            "clubLevel": club_level,
            "commercialScore": round(score, 1),
            "commercialStatusScore": round(shared_status, 1),
            "staffMarketScore": shared["staffMarketScore"],
            "organizationScore": shared["organizationScore"],
            "leagueMarketScore": shared["leagueMarketScore"],
            "trajectoryScore": shared["trajectoryScore"],
            "promotionCount": promotion_count,
            "observedSeasons": shared["observedSeasons"],
            "hypeScore": round(hype_score, 1),
            "establishedScore": round(established_score, 1),
            "newlyPromoted": newly_promoted,
            "relegationRisk": round(relegation_risk, 3),
            "statusBand": status_band,
            "components": {
                "popularity": round(pop_score, 1),
                "prestige": shared["prestigeScore"],
                "sporting": shared["sportingScore"],
                "financialScale": shared["financialScaleScore"],
                "stadium": round(stadium_score, 1),
                "league": shared["leagueMarketScore"],
                "momentum": round(hype_score, 1),
                "clubDevelopment": round(commercial_capability, 1),
            },
            "commercialCapability": round(commercial_capability, 1),
        }

    def _market_fit(self, partner_id: int, nation_id: int | None, *, supplier: bool = False) -> tuple[float, str]:
        markets = self.reference.supplier_markets if supplier else self.reference.sponsor_markets
        regions = self.reference.supplier_regions if supplier else self.reference.sponsor_regions
        if nation_id is not None and nation_id in markets.get(partner_id, {}):
            row = markets[partner_id][nation_id]
            presence = float(row.get("presence") or 0)
            expansion = float(row.get("expansion_interest") or 0)
            return _clamp(0.72 + presence / 330 + expansion / 600, 0.65, 1.28), "direct national market"
        best: tuple[float, str] | None = None
        for region_id in self.reference.regions_by_nation.get(nation_id or -1, set()):
            row = regions.get(partner_id, {}).get(region_id)
            if not row:
                continue
            presence = float(row.get("presence") or 0)
            expansion = float(row.get("expansion_interest") or 0)
            value = _clamp(0.68 + presence / 360 + expansion / 650, 0.6, 1.22)
            if best is None or value > best[0]:
                best = (value, f"Region {region_id}")
        global_row = regions.get(partner_id, {}).get("GLOBAL")
        if best is None and global_row:
            presence = float(global_row.get("presence") or 0)
            expansion = float(global_row.get("expansion_interest") or 0)
            best = (_clamp(0.68 + presence / 380 + expansion / 700, 0.62, 1.18), "globale Reichweite")
        return best or (0.55, "limited market presence")

    @staticmethod
    def _sponsor_base_value(level: int) -> float:
        return 25_000 * math.exp(math.log(60_000_000 / 25_000) * (level - 1) / 19)

    @staticmethod
    def _league_shirt_anchor(context: dict[str, Any]) -> float:
        league_score = float(context.get("leagueMarketScore") or 55.0)
        anchor = 60_000 * math.exp(math.log(6_000_000 / 60_000) * _clamp((league_score - 40.0) / 54.0, 0.0, 1.0))
        league_name = str(context.get("leagueName") or "").casefold()
        if "premier league" in league_name:
            anchor *= 1.18
        elif "championship" in league_name:
            anchor *= 1.08
        return anchor

    def _expected_sponsor_band(self, slot: str, context: dict[str, Any]) -> dict[str, Any]:
        type_row = self.reference.types.get(slot) or {}
        slot_multiplier = float(type_row.get("base_value_multiplier") or 1.0)
        club_anchor = self._sponsor_base_value(int(context["clubLevel"]))
        league_anchor = self._league_shirt_anchor(context)
        anchor = max(club_anchor, league_anchor)
        established = float(context.get("establishedScore") or 50.0)
        hype = float(context.get("hypeScore") or 50.0)
        capability = float(context.get("commercialCapability") or 50.0)
        risk = float(context.get("relegationRisk") or 0.0)
        status_factor = _clamp(0.78 + established / 260.0 + hype / 520.0 + (capability - 50.0) / 900.0 - risk * 0.18, 0.78, 1.38)
        middle = anchor * slot_multiplier * status_factor
        low = middle * (0.68 if context.get("newlyPromoted") else 0.74)
        high = middle * (1.42 if float(context.get("hypeScore") or 0) >= 70 else 1.30)
        return {
            "lowMinor": _round_money(low, 10_000) * 100,
            "midMinor": _round_money(middle, 10_000) * 100,
            "highMinor": _round_money(high, 10_000) * 100,
            "clubAnchorMinor": _round_money(club_anchor * slot_multiplier, 10_000) * 100,
            "leagueAnchorMinor": _round_money(league_anchor * slot_multiplier, 10_000) * 100,
            "statusFactor": round(status_factor, 3),
        }

    def _partner_logo(self, kind: str, partner_id: int) -> dict[str, Any] | None:
        if self.media is None:
            return None
        media_type = "supplier_logo" if kind == "supplier" else "sponsor_logo"
        return self.media.resolve(kind, partner_id, media_type)

    @staticmethod
    def _bonus_clauses(slot: str, bonus_max_minor: int, context: dict[str, Any], seed: int) -> list[dict[str, Any]]:
        if bonus_max_minor <= 0:
            return []
        rng = random.Random(seed)
        team_count = max(8, int(context.get("teamCount") or 18))
        club_level = int(context.get("clubLevel") or 10)
        target = int(round(team_count * _clamp(0.83 - club_level * 0.027, 0.20, 0.72)))
        target = max(1, min(team_count, target + rng.choice([-1, 0, 0, 1])))
        if slot in {"regional_partner", "digital_partner", "matchday_partner"}:
            definitions = [
                ("League target", f"Season finish in position {target} or better", 0.45),
                ("Pokalrunde", "Mindestens Viertelfinale im nationalen Hauptpokal", 0.30),
                ("Leistungsserie", "At least five competitive matches unbeaten", 0.25),
            ]
        else:
            definitions = [
                ("League target", f"Season finish in position {target} or better", 0.45),
                ("Europapokal", "Qualification for the Champions League, Europa League or Conference League", 0.32),
                ("Pokalerfolg", "Mindestens Halbfinale im nationalen Hauptpokal", 0.23),
            ]
        clauses: list[dict[str, Any]] = []
        allocated = 0
        for index, (label, requirement, share) in enumerate(definitions):
            amount = bonus_max_minor - allocated if index == len(definitions) - 1 else int(round(bonus_max_minor * share / 500_000) * 500_000)
            amount = max(0, amount)
            allocated += amount
            clauses.append({
                "key": f"{slot}:{index + 1}", "label": label, "requirement": requirement,
                "amountMinor": amount, "amount": amount / 100, "share": round(amount / bonus_max_minor, 3),
                "triggerStatus": "not evaluated automatically yet",
            })
        return clauses

    @staticmethod
    def _scale_bonus_clauses(explanation: dict[str, Any], bonus_max_minor: int) -> None:
        clauses = list(explanation.get("bonusClauses") or [])
        if not clauses or bonus_max_minor <= 0:
            explanation["bonusClauses"] = []
            return
        weights = [max(0.0, float(clause.get("share") or 0)) for clause in clauses]
        total = sum(weights) or float(len(clauses))
        allocated = 0
        for index, clause in enumerate(clauses):
            amount = bonus_max_minor - allocated if index == len(clauses) - 1 else int(round(bonus_max_minor * weights[index] / total / 500_000) * 500_000)
            amount = max(0, amount); allocated += amount
            clause["amountMinor"] = amount; clause["amount"] = amount / 100
            clause["share"] = round(amount / bonus_max_minor, 3)
        explanation["bonusClauses"] = clauses

    def _sponsor_terms(self, sponsor: dict[str, str], slot: str, context: dict[str, Any], seed: int) -> dict[str, Any]:
        sponsor_id = int(sponsor["sponsor_id"])
        type_row = self.reference.types.get(slot)
        if not type_row:
            raise ValueError("Unknowne Sponsoringart.")
        affinity = self.reference.affinities.get((sponsor["industry_id"], slot), 35.0)
        override = self.reference.sponsor_overrides.get((sponsor_id, slot))
        preferred = None
        tolerance = None
        if override:
            affinity = float(override.get("affinity") or affinity)
            preferred = float(override.get("preferred_club_level") or 10)
            tolerance = max(1.0, float(override.get("club_level_tolerance") or 5))
        market_fit, market_note = self._market_fit(sponsor_id, context.get("nationId"), supplier=False)
        profile_factor = _clamp(
            0.58
            + float(sponsor.get("company_size") or 5) / 55
            + float(sponsor.get("brand_prestige") or 5) / 50
            + float(sponsor.get("football_interest") or 8) / 65,
            0.65,
            1.35,
        )
        preferred_factor = 1.0
        if preferred is not None and tolerance is not None:
            preferred_factor = _clamp(1.12 - abs(context["clubLevel"] - preferred) / tolerance * 0.12, 0.72, 1.12)
        rng = random.Random(seed)
        noise = rng.triangular(0.91, 1.09, 1.0)
        development_factor = _clamp(0.96 + (float(context.get("commercialCapability") or 50.0) - 50.0) / 625.0, 0.92, 1.08)
        expected_band = self._expected_sponsor_band(slot, context)
        partner_factor = profile_factor * market_fit * preferred_factor * (0.78 + affinity / 220) * development_factor * noise
        value = expected_band["midMinor"] / 100 * partner_factor
        growth = float(sponsor.get("growth_aggression") or 8)
        strategic_overbid = 1.0
        overbid_probability = _clamp((growth - 9.0) / 32.0 + max(0.0, float(context.get("hypeScore") or 50.0) - 65.0) / 180.0, 0.0, 0.38)
        if rng.random() < overbid_probability:
            strategic_overbid = rng.uniform(1.08, 1.28)
            value *= strategic_overbid
        annual = max(5_000, _round_money(value, 5_000))
        min_years = int(type_row.get("min_contract_years") or 1)
        max_years = int(type_row.get("max_contract_years") or 5)
        duration = rng.randint(min_years, max_years)
        risk = float(sponsor.get("risk_tolerance") or 8)
        bonus_share = _clamp(0.08 + risk / 80 + growth / 110, 0.08, 0.42)
        bonus_max = _round_money(annual * bonus_share, 5_000)
        signing = _round_money(annual * max(0, growth - 11) / 150, 5_000)
        score = affinity * 0.34 + market_fit * 27 + profile_factor * 20 + preferred_factor * 12 + rng.random() * 8
        return {
            "annualValueMinor": annual * 100,
            "bonusMaxMinor": bonus_max * 100,
            "signingPaymentMinor": signing * 100,
            "durationSeasons": duration,
            "contractClass": None,
            "matchScore": round(score, 2),
            "marketFit": round(market_fit, 3),
            "explanation": {
                "modelId": MODEL_ID,
                "market": market_note,
                "industryAffinity": round(affinity, 1),
                "profileFactor": round(profile_factor, 3),
                "clubLevel": context["clubLevel"],
                "clubStatusBand": context.get("statusBand"),
                "commercialStatusScore": context.get("commercialStatusScore"),
                "staffMarketScore": context.get("staffMarketScore"),
                "leagueMarketScore": context.get("leagueMarketScore"),
                "trajectoryScore": context.get("trajectoryScore"),
                "hypeScore": context.get("hypeScore"),
                "establishedScore": context.get("establishedScore"),
                "newlyPromoted": context.get("newlyPromoted"),
                "relegationRisk": context.get("relegationRisk"),
                "commercialCapability": context.get("commercialCapability", 50.0),
                "developmentFactor": round(development_factor, 3),
                "strategicOverbidFactor": round(strategic_overbid, 3),
                "expectedBandLowMinor": expected_band["lowMinor"],
                "expectedBandMidMinor": expected_band["midMinor"],
                "expectedBandHighMinor": expected_band["highMinor"],
                "leagueAnchorMinor": expected_band["leagueAnchorMinor"],
                "clubAnchorMinor": expected_band["clubAnchorMinor"],
                "statusFactor": expected_band["statusFactor"],
                "amountSource": "Atlas estimate based on shared club-status calibration, league market, sponsor profile, momentum and commercial capability",
                "bonusClauses": self._bonus_clauses(slot, bonus_max * 100, context, _seed_value(seed, "bonuses")),
                "bonusNotice": "Bonuses are stored as a clearly defined cap; automatic trigger posting is not part of this release.",
            },
        }

    @staticmethod
    def _base_supplier_class(level: int) -> int:
        if level <= 5:
            return 1
        if level <= 9:
            return 2
        if level <= 13:
            return 3
        if level <= 17:
            return 4
        return 5

    def _supplier_allowed(self, supplier: dict[str, str], context: dict[str, Any]) -> bool:
        rule = str(supplier.get("special_rule") or "")
        nation_id = context.get("nationId")
        regions = self.reference.regions_by_nation.get(nation_id or -1, set())
        if "ITALY_TOP_ONLY" in rule and not (nation_id == 27 and context["clubLevel"] >= 16):
            return False
        if "DACH_ONLY" in rule and "DACH" not in regions:
            return False
        fit, _ = self._market_fit(int(supplier["supplier_id"]), nation_id, supplier=True)
        return fit >= 0.58

    def _supplier_terms(self, supplier: dict[str, str], context: dict[str, Any], seed: int, incumbent_id: int | None = None) -> dict[str, Any]:
        supplier_id = int(supplier["supplier_id"])
        rng = random.Random(seed)
        base_class = self._base_supplier_class(context["clubLevel"])
        market_fit, market_note = self._market_fit(supplier_id, context.get("nationId"), supplier=True)
        strategy = ((float(supplier.get("strategic_aggression") or 10.5) - 10.5) / 9.5) * 0.70
        region_adjustment = (market_fit - 0.9) * 1.25
        momentum = _clamp((context["components"]["momentum"] - 50) / 100, -0.40, 0.40)
        incumbent = 0.25 if incumbent_id == supplier_id else 0.0
        development = _clamp((float(context.get("commercialCapability") or 50.0) - 50.0) / 100.0 * 0.35, -0.18, 0.18)
        noise = rng.triangular(-0.75, 0.75, 0.0)
        offer_score = _clamp(context["clubLevel"] + strategy + region_adjustment + momentum + incumbent + development + noise, context["clubLevel"] - 1.5, context["clubLevel"] + 1.5)
        offer_class = self._base_supplier_class(int(round(offer_score)))
        offer_class = int(_clamp(offer_class, base_class - 1, base_class + 1))
        offer_class = int(_clamp(offer_class, int(supplier.get("min_contract_class") or 1), int(supplier.get("max_contract_class") or 5)))
        value_band = self.reference.supplier_values[offer_class]
        low = float(value_band["orientation_min_eur"])
        high = float(value_band["orientation_max_eur"])
        class_ranges = {1: (1, 5), 2: (6, 9), 3: (10, 13), 4: (14, 17), 5: (18, 20)}
        lower_level, upper_level = class_ranges[offer_class]
        position = _clamp((offer_score - lower_level) / max(1, upper_level - lower_level), 0, 1)
        power = _clamp(0.74 + float(supplier.get("supplier_power") or 10) / 48, 0.78, 1.18)
        strategic = _clamp(0.9 + float(supplier.get("strategic_aggression") or 10) / 100, 0.92, 1.12)
        value = (low + (high - low) * position) * power * market_fit * strategic * rng.triangular(0.93, 1.07, 1.0)
        step = 10_000 if offer_class <= 2 else 50_000 if offer_class <= 4 else 100_000
        annual = _round_money(value, step)
        duration_roll = rng.random()
        duration = 2 if duration_roll < 0.25 else 4 if duration_roll > 0.75 else 3
        bonus_max = _round_money(annual * _clamp(0.09 + float(supplier.get("strategic_aggression") or 10) / 130, 0.10, 0.24), step)
        return {
            "annualValueMinor": annual * 100,
            "bonusMaxMinor": bonus_max * 100,
            "signingPaymentMinor": 0,
            "durationSeasons": duration,
            "contractClass": offer_class,
            "matchScore": round(offer_score, 2),
            "marketFit": round(market_fit, 3),
            "explanation": {
                "modelId": MODEL_ID,
                "market": market_note,
                "baseClass": base_class,
                "offerClass": offer_class,
                "offerScore": round(offer_score, 2),
                "clubLevel": context["clubLevel"],
                "commercialCapability": context.get("commercialCapability", 50.0),
                "clubDevelopmentAdjustment": round(development, 3),
                "amountSource": "Atlas estimate innerhalb des Supplier-Klassenbands",
                "bonusClauses": self._bonus_clauses("supplier", bonus_max * 100, context, _seed_value(seed, "bonuses")),
                "bonusNotice": "Supplier bonuses are performance-based payments above the guaranteed annual value.",
            },
        }

    def _partner_options(self, kind: str, active_only: bool = True) -> list[dict[str, Any]]:
        if kind == "supplier":
            ordered = sorted(self.reference.suppliers.items(), key=lambda item: item[1]["name"].casefold())
            logos = self.media.resolve_many("supplier", [key for key, _ in ordered], "supplier_logo") if self.media is not None else {}
            return [
                {"id": key, "name": row["name"], "kind": "supplier", "active": True,
                 "logo": logos.get(key)}
                for key, row in ordered
            ]
        ordered = []
        for key, row in sorted(self.reference.sponsors.items(), key=lambda item: item[1]["name"].casefold()):
            active = str(row.get("active") or "0") == "1"
            if active_only and not active:
                continue
            ordered.append((key, row, active))
        logos = self.media.resolve_many("sponsor", [key for key, _, _ in ordered], "sponsor_logo") if self.media is not None else {}
        return [
            {"id": key, "name": row["name"], "kind": "sponsor", "active": active,
             "industryId": row.get("industry_id"), "logo": logos.get(key)}
            for key, row, active in ordered
        ]

    def _contract_status(self, row: dict[str, Any], reference_date: str) -> str:
        if row.get("status") == "cancelled":
            return "cancelled"
        if str(row["start_date"]) > reference_date:
            return "future"
        if str(row["end_date"]) < reference_date:
            return "expired"
        return "active"

    def _contract_dict(self, row: sqlite3.Row | dict[str, Any], reference_date: str) -> dict[str, Any]:
        item = dict(row)
        item["status"] = self._contract_status(item, reference_date)
        item["slotLabel"] = SLOT_LABELS.get(str(item["slot_type"]), str(item["slot_type"]))
        reference_season = season_start_from_date(reference_date) or int(item["start_season_start_year"])
        remaining_from = int(item["start_season_start_year"]) if item["status"] == "future" else reference_season
        item["remainingSeasons"] = max(0, int(item["end_season_start_year"]) - remaining_from + 1)
        item["annualValue"] = None if item.get("annual_value_minor") is None else int(item["annual_value_minor"]) / 100
        item["signingPayment"] = None if item.get("signing_payment_minor") is None else int(item["signing_payment_minor"]) / 100
        item["bonusMax"] = None if item.get("bonus_max_minor") is None else int(item["bonus_max_minor"]) / 100
        item["sourceLabel"] = "Manual" if item.get("terms_source") == "manual" else "Calculated by Atlas"
        item["partnerKind"] = item.pop("partner_kind")
        item["partnerId"] = item.pop("partner_id")
        item["partnerName"] = item.pop("partner_name")
        item["logo"] = self._partner_logo(item["partnerKind"], int(item["partnerId"]))
        item["slotType"] = item.pop("slot_type")
        item["startDate"] = item.pop("start_date")
        item["endDate"] = item.pop("end_date")
        item["startSeasonStartYear"] = item.pop("start_season_start_year")
        item["endSeasonStartYear"] = item.pop("end_season_start_year")
        item["annualValueMinor"] = item.pop("annual_value_minor")
        item["signingPaymentMinor"] = item.pop("signing_payment_minor")
        item["bonusMaxMinor"] = item.pop("bonus_max_minor")
        item["termsSource"] = item.pop("terms_source")
        item["contractClass"] = item.pop("contract_class")
        item["createdAt"] = item.pop("created_at")
        item["updatedAt"] = item.pop("updated_at")
        item["signedDate"] = item.pop("signed_date")
        item["existingAtSetup"] = bool(item.pop("existing_at_setup"))
        item["financeSynced"] = bool(item.pop("finance_synced"))
        if item.get("terms_json"):
            item["terms"] = json.loads(item.pop("terms_json"))
        else:
            item.pop("terms_json", None)
            item["terms"] = {}
        return item

    def _earliest_offer_start(self, conn: sqlite3.Connection, career_id: int, slot: str, context: dict[str, Any]) -> str:
        season_year = int(context["seasonStartYear"])
        base = date(season_year + 1, 7, 1) if slot in BIG_SLOTS else date.fromisoformat(str(context["careerDate"])[:10])
        rows = conn.execute(
            "SELECT end_date FROM commercial_contracts WHERE career_id=? AND slot_type=? AND status<>'cancelled' AND end_date>=? ORDER BY end_date",
            (career_id, slot, base.isoformat()),
        ).fetchall()
        for row in rows:
            end = date.fromisoformat(str(row["end_date"])[:10])
            if end >= base:
                base = end + timedelta(days=1)
        if slot in BIG_SLOTS and (base.month, base.day) != (7, 1):
            base = date(base.year + (1 if (base.month, base.day) > (7, 1) else 0), 7, 1)
        return base.isoformat()

    def _replace_legacy_open_offers(self, conn: sqlite3.Connection, career_id: int, context: dict[str, Any]) -> int:
        """Replace open pre-bonus offers with current, fully explained offers."""
        rows = conn.execute(
            "SELECT id,slot_type,explanation_json FROM commercial_offers WHERE career_id=? AND status='open'",
            (career_id,),
        ).fetchall()
        by_slot: dict[str, list[int]] = {}
        for row in rows:
            try:
                explanation = json.loads(row["explanation_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                explanation = {}
            if "bonusClauses" in explanation and explanation.get("modelId") == MODEL_ID:
                continue
            by_slot.setdefault(str(row["slot_type"]), []).append(int(row["id"]))
        replaced = 0
        for slot, offer_ids in by_slot.items():
            placeholders = ",".join("?" for _ in offer_ids)
            conn.execute(f"DELETE FROM commercial_offers WHERE id IN ({placeholders})", tuple(offer_ids))
            created = self._insert_offer_batch(
                conn, career_id, context, slot,
                requested_count=len(offer_ids), audit_action="commercial_legacy_offers_replace",
            )
            replaced += created
            self._audit(conn, career_id, "commercial_legacy_offers_remove", 0, {
                "slot": slot, "removed": len(offer_ids), "replacements": created, "model": MODEL_ID,
            })
        return replaced

    def _refresh_open_offers(self, conn: sqlite3.Connection, career_id: int, context: dict[str, Any]) -> None:
        rows = conn.execute(
            """SELECT o.*,s.career_date previous_career_date FROM commercial_offers o
               LEFT JOIN snapshots s ON s.id=o.snapshot_id
               WHERE o.career_id=? AND o.status='open'""",
            (career_id,),
        ).fetchall()
        current_date = date.fromisoformat(str(context["careerDate"])[:10])
        now = utc_now()
        for row in rows:
            slot = str(row["slot_type"])
            earliest = self._earliest_offer_start(conn, career_id, slot, context)
            start = str(row["start_date"])
            end = str(row["end_date"])
            explanation = json.loads(row["explanation_json"] or "{}")
            changed = False
            if start < earliest:
                start_year = season_start_from_date(earliest) or date.fromisoformat(earliest).year
                end = f"{start_year + int(row['duration_seasons'])}-06-30"
                start = earliest
                explanation["startAdjusted"] = f"Start moved to {earliest} because of the existing contract."
                changed = True
            previous_date_raw = str(row["previous_career_date"] or "")[:10]
            if int(row["snapshot_id"]) != int(context["snapshotId"]) and previous_date_raw:
                try:
                    elapsed = (current_date - date.fromisoformat(previous_date_raw)).days
                except ValueError:
                    elapsed = 0
                if elapsed >= 35:
                    rng = random.Random(_seed_value("offer-review", career_id, row["id"], context["snapshotId"]))
                    roll = rng.random()
                    if roll < 0.015 and start > current_date.isoformat():
                        explanation["withdrawn"] = True
                        explanation["withdrawalReason"] = rng.choice([
                            "The partner has reprioritised its budget.",
                            "The partner has chosen another market for now.",
                            "The partner's internal approval was withdrawn.",
                        ])
                        conn.execute(
                            "UPDATE commercial_offers SET status='expired',snapshot_id=?,explanation_json=?,updated_at=? WHERE id=?",
                            (context["snapshotId"], json.dumps(explanation, ensure_ascii=False, sort_keys=True), now, row["id"]),
                        )
                        continue
                    if roll < 0.115:
                        factor = rng.choice([0.93, 0.96, 1.04, 1.07])
                        annual = _round_money(int(row["annual_value_minor"]) / 100 * factor, 5_000) * 100
                        signing = _round_money(int(row["signing_payment_minor"] or 0) / 100 * factor, 5_000) * 100
                        bonus = _round_money(int(row["bonus_max_minor"] or 0) / 100 * factor, 5_000) * 100
                        explanation.setdefault("revisions", []).append({
                            "snapshotId": int(context["snapshotId"]), "careerDate": context["careerDate"],
                            "changePercent": round((factor - 1) * 100, 1),
                            "notice": "Terms adjusted to the new sporting and commercial situation.",
                        })
                        self._scale_bonus_clauses(explanation, bonus)
                        conn.execute(
                            """UPDATE commercial_offers SET snapshot_id=?,annual_value_minor=?,signing_payment_minor=?,
                               bonus_max_minor=?,start_date=?,end_date=?,explanation_json=?,updated_at=? WHERE id=?""",
                            (context["snapshotId"], annual, signing, bonus, start, end,
                             json.dumps(explanation, ensure_ascii=False, sort_keys=True), now, row["id"]),
                        )
                        continue
                    conn.execute("UPDATE commercial_offers SET snapshot_id=?,updated_at=? WHERE id=?", (context["snapshotId"], now, row["id"]))
            if changed:
                conn.execute(
                    "UPDATE commercial_offers SET start_date=?,end_date=?,explanation_json=?,updated_at=? WHERE id=?",
                    (start, end, json.dumps(explanation, ensure_ascii=False, sort_keys=True), now, row["id"]),
                )

    def _offer_groups(self, conn: sqlite3.Connection, career_id: int, context: dict[str, Any], contracts: list[dict[str, Any]], offers: list[dict[str, Any]]) -> dict[str, Any]:
        groups: dict[str, Any] = {}
        slots = list(self.reference.types) + ["supplier"]
        for slot in slots:
            slot_contracts = [item for item in contracts if item["slotType"] == slot and item["status"] in {"active", "future"}]
            slot_contracts.sort(key=lambda item: (item["startDate"], item["id"]))
            current = next((item for item in slot_contracts if item["status"] == "active"), None)
            next_contract = next((item for item in slot_contracts if item["status"] == "future"), None)
            groups[slot] = {
                "slotType": slot, "slotLabel": SLOT_LABELS.get(slot, slot),
                "currentContract": current, "nextContract": next_contract,
                "offers": [item for item in offers if item["slotType"] == slot],
                "expectedBand": self._expected_sponsor_band(slot, context) if slot != "supplier" else None,
                "earliestStartDate": self._earliest_offer_start(conn, career_id, slot, context),
            }
        return groups

    def _offers(self, conn: sqlite3.Connection, career_id: int, context: dict[str, Any]) -> list[dict[str, Any]]:
        rows = conn.execute("SELECT * FROM commercial_offers WHERE career_id=? ORDER BY created_at DESC,id DESC", (career_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["slotLabel"] = SLOT_LABELS.get(item["slot_type"], item["slot_type"])
            item["annualValue"] = int(item["annual_value_minor"]) / 100
            item["signingPayment"] = int(item["signing_payment_minor"] or 0) / 100
            item["bonusMax"] = int(item["bonus_max_minor"] or 0) / 100
            item["explanation"] = json.loads(item.pop("explanation_json") or "{}")
            for old, new in (("partner_kind","partnerKind"),("partner_id","partnerId"),("partner_name","partnerName"),("slot_type","slotType"),("annual_value_minor","annualValueMinor"),("signing_payment_minor","signingPaymentMinor"),("bonus_max_minor","bonusMaxMinor"),("duration_seasons","durationSeasons"),("contract_class","contractClass"),("start_date","startDate"),("end_date","endDate"),("created_at","createdAt"),("updated_at","updatedAt")):
                item[new] = item.pop(old)
            item["logo"] = self._partner_logo(item["partnerKind"], int(item["partnerId"]))
            item["statusLabel"] = "Withdrawn" if item["status"] == "expired" and item["explanation"].get("withdrawn") else "Abgelaufen" if item["status"] == "expired" else None
            items.append(item)
        return items

    def overview(self, career_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        with self.database.transaction() as conn:
            context = self._club_context(conn, career_id, snapshot_id)
            context["shirtMainExpectedBand"] = self._expected_sponsor_band("shirt_main", context)
            self._sync_finance(conn, career_id, context["careerDate"])
            legacy_replacements = self._replace_legacy_open_offers(conn, career_id, context)
            self._refresh_open_offers(conn, career_id, context)
            rows = conn.execute("SELECT * FROM commercial_contracts WHERE career_id=? ORDER BY start_date DESC,id DESC", (career_id,)).fetchall()
            contracts = [self._contract_dict(row, context["careerDate"]) for row in rows]
            offers = self._offers(conn, career_id, context)
            offer_groups = self._offer_groups(conn, career_id, context, contracts, offers)
        active = [item for item in contracts if item["status"] == "active"]
        future = [item for item in contracts if item["status"] == "future"]
        return {
            "modelId": MODEL_ID,
            "legacyOffersReplaced": legacy_replacements,
            "context": context,
            "contracts": contracts,
            "activeContracts": active,
            "futureContracts": future,
            "offers": offers,
            "offerGroups": offer_groups,
            "slotTypes": [
                {"id": key, "name": SLOT_LABELS.get(key, row.get("name") or key), "bigSlot": key in BIG_SLOTS, "partnerKind": "supplier" if key == "supplier" else "sponsor"}
                for key, row in self.reference.types.items()
            ] + [{"id": "supplier", "name": "Supplier", "bigSlot": True, "partnerKind": "supplier"}],
            "sponsors": self._partner_options("sponsor", active_only=True),
            "allSponsors": self._partner_options("sponsor", active_only=False),
            "suppliers": self._partner_options("supplier"),
            "rules": {
                "bigContractStart": "Major new contracts start no earlier than 1 July of the following season and never before an existing contract expires.",
                "offerLifecycle": "Open offers are retained. Individual terms may change or, rarely, be withdrawn after later snapshots.",
                "existingContracts": "Existing contracts may begin in the current season; past payments are not created retroactively.",
                "sharedClubStatus": "Shirt sponsors and the supplier market use the same observable club-status basis. League, reputation, financial scale, squad strength and promotion momentum are weighted by market.",
            },
        }

    def _calculated_existing_terms(self, kind: str, partner_id: int, slot: str, context: dict[str, Any], seed: int) -> dict[str, Any]:
        if kind == "supplier":
            supplier = self.reference.suppliers.get(partner_id)
            if not supplier:
                raise ValueError("Supplier not found.")
            return self._supplier_terms(supplier, context, seed)
        sponsor = self.reference.sponsors.get(partner_id)
        if not sponsor:
            raise ValueError("Sponsor not found.")
        return self._sponsor_terms(sponsor, slot, context, seed)

    def save_existing_contract(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            context = self._club_context(conn, career_id, as_int(payload.get("snapshotId")))
            slot = str(payload.get("slotType") or "").strip()
            partner_ref = str(payload.get("partnerRef") or "").strip()
            ref_kind, _, ref_id = partner_ref.partition(":")
            kind = str(payload.get("partnerKind") or ref_kind or ("supplier" if slot == "supplier" else "sponsor")).strip()
            if slot not in set(self.reference.types) | {"supplier"}:
                raise ValueError("Unknown contract type.")
            expected_kind = "supplier" if slot == "supplier" else "sponsor"
            if kind != expected_kind:
                raise ValueError("Contract type and selected partner do not match.")
            # The stable partnerRef is authoritative. Older frontends localized
            # numeric HTML attributes (100000 -> 100.000) and then reduced them to
            # an invalid Number; never let that lossy field override the reference.
            normalized_ref_id = ref_id
            if re.fullmatch(r"\d{1,3}(?:[. ]\d{3})+", normalized_ref_id):
                normalized_ref_id = normalized_ref_id.replace(".", "").replace(" ", "")
            partner_id = as_int(normalized_ref_id) if normalized_ref_id else as_int(payload.get("partnerId"))
            if partner_id is None:
                raise ValueError("Partner is missing.")
            if kind == "supplier" and partner_id not in self.reference.suppliers:
                raise ValueError("Supplier not found.")
            if kind == "sponsor" and partner_id not in self.reference.sponsors:
                raise ValueError("Sponsor not found.")
            partner_name = self.reference.supplier_name(partner_id) if kind == "supplier" else self.reference.sponsor_name(partner_id)
            start_year = as_int(payload.get("startSeasonStartYear"))
            if start_year is None:
                start_year = int(context["seasonStartYear"])
            remaining = as_int(payload.get("remainingSeasons")) or 1
            if not 1 <= remaining <= 10:
                raise ValueError("The remaining term must be between 1 and 10 seasons.")
            start_value = payload.get("startDate") or f"{start_year}-07-01"
            start = input_date(start_value, "Contract start", required=True)
            assert start is not None
            start_date = start.isoformat()
            start_year = season_start_from_date(start_date) or start.year
            end_year = start_year + remaining - 1
            end_value = payload.get("endDate") or f"{end_year + 1}-06-30"
            end = input_date(end_value, "Contract end", required=True)
            assert end is not None
            if end < start:
                raise ValueError("Contract end must not precede contract start.")
            end_date = end.isoformat()
            end_year = season_start_from_date(end_date) or end.year
            signed = input_date(payload.get("signedDate") or context["careerDate"], "Unterschriftsdatum", required=True)
            assert signed is not None
            career_day = input_date(context["careerDate"], "Career date", required=True)
            assert career_day is not None
            if signed > career_day:
                raise ValueError("Signature date must not be in the future.")
            manual_value = payload.get("annualValue") not in (None, "")
            terms = self._calculated_existing_terms(kind, partner_id, slot, context, _seed_value(career_id, start_year, slot, kind, partner_id, "existing"))
            annual_minor = as_minor(payload.get("annualValue")) if manual_value else int(terms["annualValueMinor"])
            signing_minor = as_minor(payload.get("signingPayment")) if payload.get("signingPayment") not in (None, "") else 0
            bonus_minor = as_minor(payload.get("bonusMax")) if payload.get("bonusMax") not in (None, "") else int(terms.get("bonusMaxMinor") or 0)
            if annual_minor is None or annual_minor < 0:
                raise ValueError("Annual value must not be negative.")
            if signing_minor is None or signing_minor < 0:
                raise ValueError("One-time payment must not be negative.")
            if bonus_minor is None or bonus_minor < 0:
                raise ValueError("Bonus cap must not be negative.")
            notes = str(payload.get("notes") or "").strip()
            if len(notes) > 2000:
                raise ValueError("Notes must not exceed 2,000 characters.")
            self._scale_bonus_clauses(terms.setdefault("explanation", {}), int(bonus_minor or 0))
            self._ensure_slot_available(conn, career_id, slot, start_date, end_date, None)
            now = utc_now()
            career_date = str(context["careerDate"])
            contract_status = "future" if start_date > career_date else "expired" if end_date < career_date else "active"
            cursor = conn.execute(
                "INSERT INTO commercial_contracts(career_id,slot_type,partner_kind,partner_id,partner_name,status,start_date,end_date,start_season_start_year,end_season_start_year,signed_date,annual_value_minor,amount_status,signing_payment_minor,bonus_max_minor,terms_source,contract_class,terms_json,offer_id,existing_at_setup,finance_synced,notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,1,0,?,?,?)",
                (career_id, slot, kind, partner_id, partner_name, contract_status, start_date, end_date, start_year, end_year,
                 signed.isoformat(), annual_minor, "known" if manual_value else "estimated",
                 signing_minor, bonus_minor, "manual" if manual_value else "calculated", terms.get("contractClass"),
                 json.dumps(terms, ensure_ascii=False, sort_keys=True), notes or None, now, now),
            )
            contract_id = int(cursor.lastrowid)
            self._audit(conn, career_id, "commercial_contract_existing_create", contract_id, {"slot": slot, "partner": partner_name})
            self._sync_finance(conn, career_id, context["careerDate"])
        result = self.overview(career_id, context["snapshotId"])
        result["savedContractId"] = contract_id
        return result

    def _ensure_slot_available(self, conn: sqlite3.Connection, career_id: int, slot: str, start_date: str, end_date: str, ignore_id: int | None) -> None:
        params: list[Any] = [career_id, slot, end_date, start_date]
        sql = "SELECT * FROM commercial_contracts WHERE career_id=? AND slot_type=? AND status<>'cancelled' AND start_date<=? AND end_date>=?"
        if ignore_id is not None:
            sql += " AND id<>?"
            params.append(ignore_id)
        row = conn.execute(sql, tuple(params)).fetchone()
        if row:
            raise ValueError(f"For {SLOT_LABELS.get(slot, slot)} already has a contract in this period with {row['partner_name']}.")

    def _insert_offer_batch(
        self, conn: sqlite3.Connection, career_id: int, context: dict[str, Any], slot: str,
        *, requested_count: int | None = None, audit_action: str = "commercial_offers_generate",
    ) -> int:
        if slot not in set(self.reference.types) | {"supplier"}:
            raise ValueError("Unknown contract type.")
        start_date = self._earliest_offer_start(conn, career_id, slot, context)
        start_year = season_start_from_date(start_date) or date.fromisoformat(start_date).year
        incumbent = conn.execute(
            "SELECT partner_id FROM commercial_contracts WHERE career_id=? AND slot_type=? AND status<>'cancelled' ORDER BY end_date DESC,id DESC LIMIT 1",
            (career_id, slot),
        ).fetchone()
        incumbent_id = int(incumbent["partner_id"]) if incumbent else None
        prior_rows = conn.execute(
            "SELECT partner_id,status FROM commercial_offers WHERE career_id=? AND slot_type=?",
            (career_id, slot),
        ).fetchall()
        excluded_ids = {int(row["partner_id"]) for row in prior_rows if row["status"] in {"open", "accepted"}}
        open_count = sum(1 for row in prior_rows if row["status"] == "open")
        round_index = len(prior_rows) + 1
        candidates: list[dict[str, Any]] = []
        if slot == "supplier":
            for supplier_id, supplier in self.reference.suppliers.items():
                if supplier_id in excluded_ids or not self._supplier_allowed(supplier, context):
                    continue
                terms = self._supplier_terms(
                    supplier, context,
                    _seed_value(career_id, start_year, slot, supplier_id, round_index), incumbent_id,
                )
                frequency = float(supplier.get("offer_frequency") or 10)
                selection = terms["matchScore"] + frequency / 5 + random.Random(
                    _seed_value("select", career_id, context["snapshotId"], supplier_id, round_index)
                ).random() * 3
                candidates.append({"kind": "supplier", "id": supplier_id, "name": supplier["name"], "terms": terms, "selection": selection})
        else:
            for sponsor_id, sponsor in self.reference.sponsors.items():
                if sponsor_id in excluded_ids or str(sponsor.get("active") or "0") != "1":
                    continue
                terms = self._sponsor_terms(
                    sponsor, slot, context,
                    _seed_value(career_id, start_year, slot, sponsor_id, round_index),
                )
                candidates.append({"kind": "sponsor", "id": sponsor_id, "name": sponsor["name"], "terms": terms, "selection": terms["matchScore"]})
        candidates.sort(key=lambda item: (-item["selection"], item["name"].casefold()))
        rng = random.Random(_seed_value("offer-count", career_id, context["snapshotId"], slot, round_index))
        if requested_count is None:
            requested = rng.randint(1, 3) if slot == "supplier" and open_count else rng.randint(3, 5) if slot == "supplier" else rng.randint(2, 4) if open_count else rng.randint(4, 7)
        else:
            requested = max(1, int(requested_count))
        limit = max(0, min(requested, 10 - open_count, len(candidates)))
        selected = candidates[:limit]
        if not selected:
            return 0
        now = utc_now()
        for item in selected:
            terms = item["terms"]
            duration = int(terms["durationSeasons"])
            end_year = start_year + duration - 1
            seed_key = f"{career_id}:{context['snapshotId']}:{slot}:{round_index}:{item['kind']}:{item['id']}"
            explanation = dict(terms["explanation"])
            explanation.update({
                "offerModel": MODEL_ID,
                "offerRound": round_index,
                "earliestStartReason": "after existing contracts expire" if start_date != f"{int(context['seasonStartYear']) + 1}-07-01" else "regular next-season start",
            })
            conn.execute(
                """INSERT INTO commercial_offers(
                       career_id,snapshot_id,season_start_year,slot_type,partner_kind,partner_id,partner_name,
                       annual_value_minor,signing_payment_minor,bonus_max_minor,duration_seasons,contract_class,
                       start_date,end_date,match_score,explanation_json,status,seed_key,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?)""",
                (career_id, context["snapshotId"], start_year, slot, item["kind"], item["id"], item["name"],
                 int(terms["annualValueMinor"]), int(terms.get("signingPaymentMinor") or 0), int(terms.get("bonusMaxMinor") or 0),
                 duration, terms.get("contractClass"), start_date, f"{end_year + 1}-06-30", float(terms["matchScore"]),
                 json.dumps(explanation, ensure_ascii=False, sort_keys=True), seed_key, now, now),
            )
        self._audit(conn, career_id, audit_action, 0, {
            "slot": slot, "count": len(selected), "round": round_index, "startDate": start_date, "model": MODEL_ID,
        })
        return len(selected)

    def generate_offers(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            context = self._club_context(conn, career_id, as_int(payload.get("snapshotId")))
            slot = str(payload.get("slotType") or "shirt_main")
            self._replace_legacy_open_offers(conn, career_id, context)
            self._refresh_open_offers(conn, career_id, context)
            created = self._insert_offer_batch(conn, career_id, context, slot)
            if not created:
                raise ValueError("No further suitable offers are currently available for this contract type.")
        return self.overview(career_id, context["snapshotId"])

    def accept_offer(self, career_id: int, offer_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            offer = conn.execute("SELECT * FROM commercial_offers WHERE id=? AND career_id=?", (offer_id, career_id)).fetchone()
            if not offer:
                raise ValueError("Offer not found.")
            if offer["status"] != "open":
                raise ValueError("This offer is no longer open.")
            context = self._club_context(conn, career_id, int(offer["snapshot_id"]))
            self._ensure_slot_available(conn, career_id, str(offer["slot_type"]), str(offer["start_date"]), str(offer["end_date"]), None)
            start_year = season_start_from_date(str(offer["start_date"])) or int(offer["season_start_year"])
            end_year = season_start_from_date(str(offer["end_date"])) or start_year
            contract_status = "future" if str(offer["start_date"]) > str(context["careerDate"]) else "active"
            now = utc_now()
            cursor = conn.execute(
                "INSERT INTO commercial_contracts(career_id,slot_type,partner_kind,partner_id,partner_name,status,start_date,end_date,start_season_start_year,end_season_start_year,signed_date,annual_value_minor,amount_status,signing_payment_minor,bonus_max_minor,terms_source,contract_class,terms_json,offer_id,existing_at_setup,finance_synced,notes,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'calculated',?,?,?,0,0,NULL,?,?)",
                (career_id, offer["slot_type"], offer["partner_kind"], offer["partner_id"], offer["partner_name"],
                 contract_status, offer["start_date"], offer["end_date"], start_year, end_year, context["careerDate"], offer["annual_value_minor"],
                 "estimated", offer["signing_payment_minor"], offer["bonus_max_minor"], offer["contract_class"],
                 offer["explanation_json"], offer_id, now, now),
            )
            contract_id = int(cursor.lastrowid)
            conn.execute("UPDATE commercial_offers SET status='accepted',updated_at=? WHERE id=?", (now, offer_id))
            other_rows = conn.execute(
                "SELECT id,explanation_json FROM commercial_offers WHERE career_id=? AND slot_type=? AND status='open' AND id<>?",
                (career_id, offer["slot_type"], offer_id),
            ).fetchall()
            for other in other_rows:
                explanation = json.loads(other["explanation_json"] or "{}")
                explanation["closedBecauseContractSigned"] = True
                conn.execute(
                    "UPDATE commercial_offers SET status='expired',explanation_json=?,updated_at=? WHERE id=?",
                    (json.dumps(explanation, ensure_ascii=False, sort_keys=True), now, other["id"]),
                )
            self._audit(conn, career_id, "commercial_offer_accept", contract_id, {"offerId": offer_id, "partner": offer["partner_name"]})
            self._sync_finance(conn, career_id, context["careerDate"])
        return self.overview(career_id, context["snapshotId"])

    def decline_offer(self, career_id: int, offer_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            offer = conn.execute("SELECT snapshot_id,status FROM commercial_offers WHERE id=? AND career_id=?", (offer_id, career_id)).fetchone()
            if not offer:
                raise ValueError("Offer not found.")
            if offer["status"] != "open":
                raise ValueError("Only open offers can be declined.")
            conn.execute("UPDATE commercial_offers SET status='declined',updated_at=? WHERE id=?", (utc_now(), offer_id))
            snapshot_id = int(offer["snapshot_id"])
        return self.overview(career_id, snapshot_id)

    def cancel_contract(self, career_id: int, contract_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM commercial_contracts WHERE id=? AND career_id=?", (contract_id, career_id)).fetchone()
            if not row:
                raise ValueError("Contract not found.")
            if row["status"] == "cancelled":
                raise ValueError("This contract has already been cancelled.")
            conn.execute("UPDATE commercial_contracts SET status='cancelled',updated_at=? WHERE id=?", (utc_now(), contract_id))
            conn.execute("UPDATE finance_recurring_rules SET active=0,updated_at=? WHERE career_id=? AND source_type='commercial_contract' AND source_id=?", (utc_now(), career_id, f"contract:{contract_id}:annual"))
            self._audit(conn, career_id, "commercial_contract_cancel", contract_id, {})
            snapshot = self._snapshot(conn, career_id)
        return self.overview(career_id, int(snapshot["id"]))

    def _sync_finance(self, conn: sqlite3.Connection, career_id: int, reference_date: str) -> None:
        profile = conn.execute("SELECT * FROM finance_profiles WHERE career_id=?", (career_id,)).fetchone()
        if not profile:
            return
        start_floor = max(str(profile["financial_start_date"]), reference_date)
        contracts = conn.execute("SELECT * FROM commercial_contracts WHERE career_id=? AND status<>'cancelled'", (career_id,)).fetchall()
        now = utc_now()
        for contract in contracts:
            amount = contract["annual_value_minor"]
            if amount is None or int(amount) == 0:
                continue
            source_id = f"contract:{contract['id']}:annual"
            existing = conn.execute("SELECT id FROM finance_recurring_rules WHERE career_id=? AND source_type='commercial_contract' AND source_id=?", (career_id, source_id)).fetchone()
            if existing:
                continue
            contract_start = date.fromisoformat(str(contract["start_date"]))
            floor = date.fromisoformat(start_floor)
            due = contract_start
            while due < floor:
                due = date(due.year + 1, due.month, due.day)
            if due > date.fromisoformat(str(contract["end_date"])):
                continue
            direction = "income" if int(amount) > 0 else "expense"
            label = SLOT_LABELS.get(str(contract["slot_type"]), str(contract["slot_type"]))
            source_label = "Atlas estimate" if contract["amount_status"] == "estimated" else "confirmed"
            conn.execute(
                "INSERT INTO finance_recurring_rules(career_id,source_type,source_id,category_key,direction,amount_minor,cadence,start_date,end_date,next_due_date,fixed_cost,description,active,created_at,updated_at) "
                "VALUES(?,?,?,?,? ,?,'annual',?,?,?,0,?,1,?,?)",
                (career_id, "commercial_contract", source_id, "commercial_income" if direction == "income" else "club_operations", direction,
                 abs(int(amount)), str(contract["start_date"]), str(contract["end_date"]), due.isoformat(),
                 f"{label}: {contract['partner_name']} ({source_label})", now, now),
            )
            conn.execute("UPDATE commercial_contracts SET finance_synced=1,updated_at=? WHERE id=?", (now, contract["id"]))

    @staticmethod
    def _audit(conn: sqlite3.Connection, career_id: int, action: str, entity_id: int, details: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO manual_change_log(career_id,occurred_at,action,entity_type,entity_id,details_json) VALUES(?,?,?,?,?,?)",
            (career_id, utc_now(), action, "commercial", entity_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
        )

    def status(self) -> dict[str, Any]:
        active_sponsors = sum(1 for row in self.reference.sponsors.values() if str(row.get("active") or "0") == "1")
        return {
            "model": MODEL_ID,
            "sponsors": len(self.reference.sponsors),
            "activeSponsors": active_sponsors,
            "suppliers": len(self.reference.suppliers),
            "sponsorshipTypes": len(self.reference.types),
        }
