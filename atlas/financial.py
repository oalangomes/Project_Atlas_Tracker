from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .positions import POSITION_ALIASES, POSITION_BY_ID, canonical_position
from .server_utils import age_on_date, as_int, parse_raw


PROFILE_FILE = "fc26_ea_value_wage_active_mod_profile_v1.0.json"
PROFILE_ID = "fc26-active-mod-profile-2026-08-01"
MODEL_ID = "ea-legacy-transition-v0.1"
CONFIDENCE = "approximate"


class FinancialCalculationProvider(Protocol):
    profile_id: str
    model_id: str

    def market_value(self, values: dict[str, Any]) -> dict[str, Any]: ...
    def weekly_wage(self, values: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProfitabilityObservation:
    value: int | None
    value_source: str
    source_snapshot_id: int | None
    source_snapshot_external_id: str | None
    warning: str | None = None


class EaLegacyTransitionProvider:
    """Versioned approximation of FC 26's legacy value/wage configuration."""

    def __init__(self, profile_path: Path):
        self.profile_path = profile_path
        self.profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        self.profile_id = str(self.profile.get("profileId") or PROFILE_ID)
        self.model_id = str(self.profile.get("calculationModel") or MODEL_ID)
        self.config = self.profile["activeConfig"]

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _round_step(value: float, step: int) -> int:
        return int(math.floor(max(0.0, value) / step + 0.5) * step)

    @staticmethod
    def normalize_position(value: Any, position_id: Any = None) -> str | None:
        return canonical_position(value, position_id)

    @staticmethod
    def _threshold_pairs(section: dict[str, Any], prefix: str, count_key: str) -> list[tuple[float, float]]:
        count = as_int(section.get(count_key)) or 0
        pairs: list[tuple[float, float]] = []
        for index in range(1, count + 1):
            boundary = section.get(f"{prefix}_{index}")
            value = section.get(f"{prefix}_{index}_VAL")
            if boundary not in (None, "") and value not in (None, ""):
                pairs.append((float(boundary), float(value)))
        return pairs

    @classmethod
    def _ascending_lookup(cls, section: dict[str, Any], prefix: str, count_key: str, needle: float) -> float:
        pairs = sorted(cls._threshold_pairs(section, prefix, count_key), key=lambda item: item[0])
        for boundary, value in pairs:
            if needle <= boundary:
                return value
        return pairs[-1][1] if pairs else 0.0

    @classmethod
    def _descending_lookup(cls, section: dict[str, Any], prefix: str, count_key: str, needle: float) -> float:
        pairs = sorted(cls._threshold_pairs(section, prefix, count_key), key=lambda item: item[0], reverse=True)
        for boundary, value in pairs:
            if needle >= boundary:
                return value
        return pairs[-1][1] if pairs else 0.0

    @staticmethod
    def _position_value(section: dict[str, Any], position: str) -> float:
        return float(section.get(f"PLAYER_POSITION_{position}") or 0)

    def market_value(self, values: dict[str, Any]) -> dict[str, Any]:
        overall = as_int(values.get("overall"))
        age = as_int(values.get("age"))
        position = self.normalize_position(values.get("position"), values.get("position_id"))
        if overall is None or age is None or position is None:
            return {
                "value": None,
                "available": False,
                "warning": "OVR, age or position is missing for EA market-value calculation.",
            }

        sex = "women" if bool(values.get("is_women")) or str(values.get("sex") or "").lower() == "women" else "men"
        suffix = "WOMEN" if sex == "women" else "MEN"
        config = self.config[f"player_{sex}_values"]
        potential = as_int(values.get("potential"))
        potential = overall if potential is None else potential
        form = as_int(values.get("form"))
        form = 5 if form is None else form
        prestige = as_int(values.get("domestic_prestige"))
        prestige = 1 if prestige is None else prestige
        reputation = as_int(values.get("international_reputation"))
        reputation = 0 if reputation is None else reputation
        contract_years = as_int(values.get("contract_years"))
        contract_years = 0 if contract_years is None else max(0, contract_years)

        base = self._ascending_lookup(config[f"RATINGRANGE_{suffix}"], "RATING", "RATING_COUNT", overall)
        age_pct = self._ascending_lookup(config[f"AGE_{suffix}"], "AGE", "AGE_COUNT", age)
        remaining_potential = max(potential - overall, 0)
        potential_pct = self._ascending_lookup(
            config[f"POTENTIAL_{suffix}"], "POTENTIAL", "POTENTIAL_COUNT", remaining_potential
        ) if remaining_potential else 0.0
        contract_pct = self._ascending_lookup(
            config[f"CONTRACT_{suffix}"], "CONTRACT", "CONTRACT_COUNT", contract_years
        )
        form_pct = self._ascending_lookup(config[f"FORM_{suffix}"], "FORM", "FORM_COUNT", form)
        position_pct = self._position_value(config[f"POSITION_{suffix}"], position)
        prestige_pct = self._ascending_lookup(
            config[f"CLUB_PRESTIGE_{suffix}"], "PRESTIGE", "PRESTIGE_COUNT", prestige
        )
        reputation_pct = self._ascending_lookup(
            config[f"INT_REPUTATION_{suffix}"], "REPUTATION", "REPUTATION_COUNT", reputation
        ) if reputation > 0 else 0.0
        overall_damping = self._descending_lookup(
            config[f"OVERALL_{suffix}"], "OVERALL", "OVERALL_COUNT", overall
        )
        valuation = config[f"VALUATION_{suffix}"]
        combined_pct = (
            overall_damping * (age_pct + form_pct + position_pct + reputation_pct)
            + potential_pct * self._number(valuation.get("POTENTIAL_RELEVANCE"))
            + contract_pct * self._number(valuation.get("CONTRACT_RELEVANCE"))
            + prestige_pct * self._number(valuation.get("PRESTIGE_RELEVANCE"))
        )
        minimum_section = config[f"MINIMUM_VALUE_{suffix}"]
        minimum_pairs = []
        for index in range(1, (as_int(minimum_section.get("MINIMUM_COUNT")) or 0) + 1):
            boundary = minimum_section.get(f"MINIMUM_OVR_{index}")
            value = minimum_section.get(f"MINIMUM_VAL_{index}")
            if boundary not in (None, "") and value not in (None, ""):
                minimum_pairs.append((float(boundary), float(value)))
        minimum_pairs.sort(key=lambda item: item[0], reverse=True)
        minimum = next((value for boundary, value in minimum_pairs if overall >= boundary), 0.0)
        raw = max(base * (1 + combined_pct / 100), minimum)
        rounded = self._round_step(raw, 1000)
        return {
            "value": rounded,
            "available": True,
            "label": "EA market value (calculated)",
            "profile_id": self.profile_id,
            "model": self.model_id,
            "confidence": CONFIDENCE,
            "details": {
                "base_value": int(base), "age_pct": age_pct, "remaining_potential": remaining_potential,
                "potential_pct": potential_pct, "contract_pct": contract_pct, "form_pct": form_pct,
                "position_pct": position_pct, "prestige_pct": prestige_pct,
                "reputation_pct": reputation_pct, "overall_damping": overall_damping,
                "combined_pct": combined_pct, "minimum_value": int(minimum), "raw_value": raw,
                "rounded_value": rounded, "sex": sex, "position": position,
            },
        }

    def weekly_wage(self, values: dict[str, Any]) -> dict[str, Any]:
        overall = as_int(values.get("overall"))
        age = as_int(values.get("age"))
        position = self.normalize_position(values.get("position"), values.get("position_id"))
        profitability = as_int(values.get("profitability"))
        if overall is None or age is None or position is None:
            return {"value": None, "available": False, "warning": "OVR, age or position is missing for EA wage calculation."}
        if profitability is None:
            return {"value": None, "available": False, "warning": "Profitability is missing; no wage is estimated for an external club."}
        if not 1 <= profitability <= 10:
            return {"value": None, "available": False, "warning": f"Profitability {profitability} is outside the supported profile range of 1–10."}

        wage = self.config["playerwages"]
        is_women = bool(values.get("is_women"))
        league_id = as_int(values.get("league_id"))
        mapped_league_id = league_id
        if is_women and league_id is not None:
            mapped_league_id = as_int(wage["WOMEN_LEAGUE_ASPIRATIONAL_OVERRIDES"].get(str(league_id))) or league_id
        domestic_prestige = as_int(values.get("domestic_prestige"))
        domestic_prestige = 1 if domestic_prestige is None else domestic_prestige
        if not 1 <= domestic_prestige <= 10:
            domestic_prestige = 1

        def loose_lookup(section: dict[str, Any], prefix: str, needle: float) -> float:
            pairs = []
            for key, boundary in section.items():
                if key.startswith(prefix + "_") and not key.endswith("_VAL"):
                    suffix = key[len(prefix) + 1:]
                    if suffix.isdigit() and f"{prefix}_{suffix}_VAL" in section:
                        pairs.append((float(boundary), float(section[f"{prefix}_{suffix}_VAL"])))
            pairs.sort(key=lambda item: item[0])
            for boundary, result in pairs:
                if needle <= boundary:
                    return result
            return pairs[-1][1] if pairs else 0.0

        base_wage = loose_lookup(wage["WAGE_RATINGRANGE"], "RATING", overall) * 100
        age_pct = loose_lookup(wage["WAGE_AGE"], "AGE", age)
        position_pct = self._position_value(wage["WAGE_POSITION"], position)
        league_key = f"LEAGUE_MODIFIER_{mapped_league_id}" if mapped_league_id is not None else ""
        default_key = "DEFAULT_LEAGUE_MODIFIER_WOMEN" if is_women else "DEFAULT_LEAGUE_MODIFIER_MEN"
        league_pct = self._number(wage["WAGE_LEAGUE"].get(league_key), self._number(wage["WAGE_LEAGUE"].get(default_key)))

        domestic_table = self.config["wageDomesticPrestigeMultipliers"]
        profit_table = self.config["wageProfitabilityMultipliers"]
        actual_key = str(league_id) if league_id is not None else ""
        mapped_key = str(mapped_league_id) if mapped_league_id is not None else ""
        domestic_row = domestic_table.get(actual_key) or domestic_table.get(mapped_key) or domestic_table["0"]
        profit_row = profit_table.get(actual_key) or profit_table.get(mapped_key) or profit_table["0"]
        prestige_multiplier = float(domestic_row[domestic_prestige - 1])
        profitability_multiplier = float(profit_row[profitability - 1])
        percentage_factor = 1 + (age_pct + position_pct + league_pct) / 100
        raw = max(500.0, base_wage * percentage_factor * prestige_multiplier * profitability_multiplier)
        rounded = max(500, self._round_step(raw, 500))
        return {
            "value": rounded,
            "available": True,
            "label": "EA wage (calculated)",
            "profile_id": self.profile_id,
            "model": self.model_id,
            "confidence": CONFIDENCE,
            "details": {
                "base_wage": int(base_wage), "age_pct": age_pct, "position_pct": position_pct,
                "league_pct": league_pct, "prestige_multiplier": prestige_multiplier,
                "profitability_multiplier": profitability_multiplier, "raw_wage": raw,
                "rounded_wage": rounded, "league_id": league_id,
                "mapped_league_id": mapped_league_id, "position": position,
            },
        }


class FinancialService:
    def __init__(self, database, profile_path: Path):
        self.database = database
        self.provider = EaLegacyTransitionProvider(profile_path)

    def status(self) -> dict[str, Any]:
        return {
            "profileId": self.provider.profile_id,
            "model": self.provider.model_id,
            "confidence": CONFIDENCE,
            "profilePath": str(self.provider.profile_path),
        }

    @staticmethod
    def _is_women(player_raw: dict[str, Any], team_raw: dict[str, Any]) -> bool:
        gender = as_int(player_raw.get("gender"))
        if gender is None:
            gender = as_int(team_raw.get("gender"))
        return gender == 1

    @staticmethod
    def _contract_years(contract_valid_until: Any, career_date: str | None) -> int:
        if contract_valid_until in (None, "") or not career_date:
            return 0
        target = str(contract_valid_until).strip()
        current_year = as_int(str(career_date)[:4])
        if current_year is None:
            return 0
        numeric = as_int(target)
        if numeric is not None and 1900 <= numeric <= 2500:
            return max(0, numeric - current_year)
        try:
            if len(target) == 8 and target.isdigit():
                end = date(int(target[:4]), int(target[4:6]), int(target[6:8]))
            else:
                end = date.fromisoformat(target[:10])
            current = date.fromisoformat(str(career_date)[:10])
            return max(0, math.ceil((end - current).days / 365.25))
        except (ValueError, TypeError):
            return 0

    def profitability_for_snapshot(
        self, conn: sqlite3.Connection, career_id: int, snapshot_id: int, team_id: int
    ) -> ProfitabilityObservation:
        target = conn.execute(
            "SELECT import_sequence FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)
        ).fetchone()
        if not target:
            return ProfitabilityObservation(None, "missing", None, None, "Snapshot not found.")
        earlier = conn.execute(
            """SELECT ts.profitability,s.id,s.external_snapshot_id
               FROM team_states ts JOIN snapshots s ON s.id=ts.snapshot_id
               WHERE s.career_id=? AND ts.ea_team_id=? AND ts.profitability IS NOT NULL
                 AND s.import_sequence<=?
               ORDER BY s.import_sequence DESC LIMIT 1""",
            (career_id, team_id, target["import_sequence"]),
        ).fetchone()
        if earlier:
            return ProfitabilityObservation(
                int(earlier["profitability"]), "observed", int(earlier["id"]), str(earlier["external_snapshot_id"])
            )
        later = conn.execute(
            """SELECT ts.profitability,s.id,s.external_snapshot_id
               FROM team_states ts JOIN snapshots s ON s.id=ts.snapshot_id
               WHERE s.career_id=? AND ts.ea_team_id=? AND ts.profitability IS NOT NULL
                 AND s.import_sequence>?
               ORDER BY s.import_sequence ASC LIMIT 1""",
            (career_id, team_id, target["import_sequence"]),
        ).fetchone()
        if later:
            return ProfitabilityObservation(
                int(later["profitability"]), "inferred_from_later_snapshot",
                int(later["id"]), str(later["external_snapshot_id"]),
            )
        return ProfitabilityObservation(
            None, "missing", None, None,
            "No observed or later inferable profitability value exists for this club.",
        )

    def historical_market_value(
        self,
        conn: sqlite3.Connection,
        career_id: int,
        player_id: int,
        effective_date: str,
        overall: int,
        potential: int,
        *,
        preferred_team_id: int | None = None,
    ) -> dict[str, Any]:
        """Calculate a marked historical value from a manual OVR/POT point.

        The nearest observed player state supplies stable context such as birthdate,
        position and sex.  No context means no invented value.
        """
        player_row = conn.execute(
            """SELECT p.*,s.id context_snapshot_id,s.career_date context_career_date,s.import_sequence
               FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
               WHERE s.career_id=? AND p.ea_player_id=?
               ORDER BY CASE WHEN s.career_date<=? THEN 0 ELSE 1 END,
                        ABS(julianday(s.career_date)-julianday(?)),s.import_sequence DESC
               LIMIT 1""",
            (career_id, player_id, effective_date, effective_date),
        ).fetchone()
        if not player_row:
            return {
                "value": None, "available": False, "label": "EA market value (calculated)",
                "source": "manual_development", "confidence": CONFIDENCE,
                "warning": "No observed player state is available for age and position.",
            }
        player = dict(player_row)
        player_raw = parse_raw(player.get("raw_json"))
        age = age_on_date(player_raw.get("birthdate_raw"), effective_date)
        position_id = player_raw.get("primary_position_id")
        team_id = preferred_team_id if preferred_team_id is not None else as_int(player.get("team_ea_id"))
        team_row = None
        if team_id is not None:
            team_row = conn.execute(
                """SELECT ts.*,s.id context_snapshot_id,s.career_date context_career_date
                   FROM team_states ts JOIN snapshots s ON s.id=ts.snapshot_id
                   WHERE s.career_id=? AND ts.ea_team_id=?
                   ORDER BY CASE WHEN s.career_date<=? THEN 0 ELSE 1 END,
                            ABS(julianday(s.career_date)-julianday(?)),s.import_sequence DESC
                   LIMIT 1""",
                (career_id, team_id, effective_date, effective_date),
            ).fetchone()
        team = dict(team_row) if team_row else {}
        team_raw = parse_raw(team.get("raw_json"))
        domestic_prestige = as_int(team.get("domestic_prestige"))
        if domestic_prestige is None:
            domestic_prestige = as_int(team_raw.get("domestic_prestige"))
        result = self.provider.market_value({
            "overall": overall,
            "potential": potential,
            "age": age,
            "position": player.get("primary_position"),
            "position_id": position_id,
            "contract_years": 0,
            "form": 5,
            "domestic_prestige": domestic_prestige,
            "international_reputation": player_raw.get("international_reputation"),
            "is_women": self._is_women(player_raw, team_raw),
        })
        result["source"] = "manual_development"
        result["label"] = "EA market value (calculated)"
        result["profile_id"] = self.provider.profile_id
        result["model"] = self.provider.model_id
        result["confidence"] = CONFIDENCE
        result["context"] = {
            "effective_date": effective_date,
            "player_context_snapshot_id": as_int(player.get("context_snapshot_id")),
            "player_context_date": player.get("context_career_date"),
            "team_context_snapshot_id": as_int(team.get("context_snapshot_id")),
            "team_context_date": team.get("context_career_date"),
            "team_id": team_id,
            "age": age,
            "position": self.provider.normalize_position(player.get("primary_position"), position_id),
            "assumptions": ["Form=5", "Remaining contract term=0"],
        }
        return result

    def calculate_player(
        self,
        conn: sqlite3.Connection,
        snapshot: sqlite3.Row | dict[str, Any],
        player: sqlite3.Row | dict[str, Any],
        *,
        roster: sqlite3.Row | dict[str, Any] | None = None,
        contract: sqlite3.Row | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snap = dict(snapshot)
        item = dict(player)
        player_raw = parse_raw(item.get("raw_json") or item.get("raw"))
        roster_item = dict(roster) if roster else {}
        roster_raw = parse_raw(roster_item.get("raw_json") or roster_item.get("raw"))
        contract_item = dict(contract) if contract else {}
        team_id = as_int(item.get("team_ea_id"))
        team = None
        if team_id is not None:
            team = conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?", (snap["id"], team_id)
            ).fetchone()
        team_item = dict(team) if team else {}
        team_raw = parse_raw(team_item.get("raw_json"))
        age = age_on_date(player_raw.get("birthdate_raw"), snap.get("career_date"))
        position_id = player_raw.get("primary_position_id")
        if position_id in (None, ""):
            position_id = roster_raw.get("primary_position_id")
        form = as_int(roster_item.get("form"))
        if form is None:
            form = as_int(roster_raw.get("form"))
        domestic_prestige = as_int(team_item.get("domestic_prestige"))
        if domestic_prestige is None:
            domestic_prestige = as_int(team_raw.get("domestic_prestige"))
        market = self.provider.market_value({
            "overall": item.get("overall"), "potential": item.get("potential"), "age": age,
            "position": item.get("primary_position"), "position_id": position_id,
            "contract_years": self._contract_years(item.get("contract_valid_until"), snap.get("career_date")),
            "form": form, "domestic_prestige": domestic_prestige,
            "international_reputation": player_raw.get("international_reputation"),
            "is_women": self._is_women(player_raw, team_raw),
        })

        managed_team_id = as_int(snap.get("managed_team_ea_id"))
        contract_team_id = as_int(contract_item.get("team_ea_id"))
        own_outgoing_loan = False
        if managed_team_id is not None and as_int(item.get("ea_player_id")) is not None:
            own_outgoing_loan = conn.execute(
                """SELECT 1 FROM loan_states
                   WHERE snapshot_id=? AND player_ea_id=? AND parent_team_ea_id=?
                   LIMIT 1""",
                (snap["id"], item.get("ea_player_id"), managed_team_id),
            ).fetchone() is not None
        own_club = managed_team_id is not None and (
            team_id == managed_team_id or contract_team_id == managed_team_id or own_outgoing_loan
        )
        if own_club:
            exact_wage = as_int(contract_item.get("wage"))
            wage = {
                "value": exact_wage,
                "available": exact_wage is not None,
                "label": "Snapshot-Gehalt" if exact_wage is not None else "Wage unavailable",
                "source": "snapshot_contract" if exact_wage is not None else "missing_own_contract",
                "confidence": "observed" if exact_wage is not None else None,
                "warning": None if exact_wage is not None else "No wage is estimated for a managed-club player without a contracts.csv entry.",
            }
            profitability = ProfitabilityObservation(None, "not_used_for_managed_club", None, None)
        elif team_id is None or not team:
            profitability = ProfitabilityObservation(None, "missing", None, None, "Club state is missing.")
            wage = {"value": None, "available": False, "label": "EA wage (calculated)", "source": "missing_team", "warning": profitability.warning}
        else:
            profitability = self.profitability_for_snapshot(conn, int(snap["career_id"]), int(snap["id"]), team_id)
            wage = self.provider.weekly_wage({
                "overall": item.get("overall"), "age": age, "position": item.get("primary_position"),
                "position_id": position_id, "league_id": team_item.get("league_ea_id"),
                "domestic_prestige": domestic_prestige, "profitability": profitability.value,
                "is_women": self._is_women(player_raw, team_raw),
            })
            wage["source"] = "calculated" if wage.get("available") else "unavailable"
            wage["profitability_value"] = profitability.value
            wage["profitability_value_source"] = profitability.value_source
            wage["profitability_source_snapshot_id"] = profitability.source_snapshot_id
            wage["profitability_source_snapshot_external_id"] = profitability.source_snapshot_external_id
            if not wage.get("warning") and profitability.warning:
                wage["warning"] = profitability.warning

        return {
            "market_value": market,
            "weekly_wage": wage,
            "own_club": own_club,
            "profile_id": self.provider.profile_id,
            "model": self.provider.model_id,
            "confidence": CONFIDENCE,
            "inputs": {"age": age, "team_id": team_id, "managed_team_id": managed_team_id},
        }
