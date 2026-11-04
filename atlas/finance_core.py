from __future__ import annotations

import json
import math
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .db import Database
from .media_utils import season_start_from_date
from .dynamic_revenue import DynamicRevenueEngine
from .finance_exposure import build_contract_exposure
from .competition_rules import league_rule_summary
from .server_utils import career_clock, input_bool

MODEL_VERSION = "financial-core-1"

POLICIES: dict[str, dict[str, float]] = {
    "cautious": {
        "reserve_months": 4.0,
        "transfer_allocation_rate": 0.40,
        "sales_retention_rate": 0.60,
        "wage_headroom_rate": 0.05,
    },
    "balanced": {
        "reserve_months": 3.0,
        "transfer_allocation_rate": 0.60,
        "sales_retention_rate": 0.75,
        "wage_headroom_rate": 0.10,
    },
    "ambitious": {
        "reserve_months": 2.0,
        "transfer_allocation_rate": 0.80,
        "sales_retention_rate": 0.90,
        "wage_headroom_rate": 0.15,
    },
}

ACCOUNT_DEFINITIONS = (
    ("1000", "Bank", "asset", "bank"),
    ("1100", "Forderungen", "asset", "receivables"),
    ("2000", "Verbindlichkeiten", "liability", "payables"),
    ("3000", "Opening balance", "equity", "opening_equity"),
    ("3100", "Owner funding", "equity", "owner_funding"),
    ("4000", "Transfer income", "income", "transfer_income"),
    ("4100", "Sponsorship and commercial income", "income", "commercial_income"),
    ("4200", "Matchday and competition", "income", "match_income"),
    ("4900", "Sonstige Einnahmen", "income", "other_income"),
    ("5000", "Transferausgaben", "expense", "transfer_expense"),
    ("5100", "Player wages", "expense", "player_wages"),
    ("5200", "Agent fees, bonuses and signing fees", "expense", "fees_bonuses"),
    ("5300", "Club operations", "expense", "club_operations"),
    ("5900", "Sonstige Ausgaben", "expense", "other_expense"),
)

CATEGORY_ACCOUNTS = {
    "transfer_income": "transfer_income",
    "commercial_income": "commercial_income",
    "match_income": "match_income",
    "other_income": "other_income",
    "transfer_expense": "transfer_expense",
    "player_wages": "player_wages",
    "fees_bonuses": "fees_bonuses",
    "club_operations": "club_operations",
    "other_expense": "other_expense",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def as_minor(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid monetary amount.") from exc
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def next_due(value: date, cadence: str) -> date:
    if cadence == "weekly":
        return value + timedelta(days=7)
    if cadence == "monthly":
        return add_months(value, 1)
    if cadence == "quarterly":
        return add_months(value, 3)
    if cadence in {"seasonal", "annual"}:
        return add_months(value, 12)
    raise ValueError("Unknowner Zahlungsrhythmus.")


def input_date(value: Any, label: str, *, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{label} is missing.")
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a valid date.") from exc


class FinanceCoreService:
    """Season-based finance journal, budgets and forecasts for one Atlas career."""

    def __init__(self, database: Database):
        self.database = database
        self.dynamic_revenue = DynamicRevenueEngine(
            Path(__file__).resolve().parent.parent / "reference" / "financial" / "dynamic_revenue_profiles_v1.json"
        )

    def season_options(self, career_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            return self._season_options(conn, career_id)

    def _season_options(self, conn: sqlite3.Connection, career_id: int) -> list[dict[str, Any]]:
        if not conn.execute("SELECT 1 FROM careers WHERE id=?", (career_id,)).fetchone():
            raise ValueError("Career not found.")
        options: dict[int, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT id,career_date,season_index,managed_team_ea_id,managed_team_name,import_sequence "
            "FROM snapshots WHERE career_id=? ORDER BY import_sequence", (career_id,),
        ).fetchall():
            year = season_start_from_date(row["career_date"])
            if year is None:
                continue
            current = options.setdefault(year, {
                "seasonStartYear": year,
                "seasonLabel": f"{year}/{str(year + 1)[-2:]}",
                "startDate": f"{year}-07-01",
                "endDate": f"{year + 1}-06-30",
                "snapshotId": None,
                "seasonIndex": row["season_index"],
                "managedTeamEaId": row["managed_team_ea_id"],
                "managedTeamName": row["managed_team_name"],
                "source": "snapshot",
            })
            current.update({
                "snapshotId": int(row["id"]),
                "seasonIndex": row["season_index"],
                "managedTeamEaId": row["managed_team_ea_id"],
                "managedTeamName": row["managed_team_name"],
                "careerDate": row["career_date"],
            })
        for row in conn.execute(
            "SELECT id,season_index,label,start_year,end_year,managed_team_ea_id,managed_team_name "
            "FROM manual_seasons WHERE career_id=? ORDER BY start_year", (career_id,),
        ).fetchall():
            year = int(row["start_year"])
            current = options.setdefault(year, {
                "seasonStartYear": year,
                "seasonLabel": row["label"] or f"{year}/{str(year + 1)[-2:]}",
                "startDate": f"{year}-07-01",
                "endDate": f"{int(row['end_year'])}-06-30",
                "snapshotId": None,
                "seasonIndex": row["season_index"],
                "managedTeamEaId": row["managed_team_ea_id"],
                "managedTeamName": row["managed_team_name"],
                "source": "manual",
            })
            if not current.get("managedTeamEaId"):
                current["managedTeamEaId"] = row["managed_team_ea_id"]
                current["managedTeamName"] = row["managed_team_name"]
            current["manualSeasonId"] = int(row["id"])
        return [options[key] for key in sorted(options)]

    def _profile(self, conn: sqlite3.Connection, career_id: int) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM finance_profiles WHERE career_id=?", (career_id,)).fetchone()

    def _period(self, conn: sqlite3.Connection, career_id: int, period_id: int | None = None) -> sqlite3.Row:
        if period_id is not None:
            row = conn.execute("SELECT * FROM finance_periods WHERE id=? AND career_id=?", (period_id, career_id)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM finance_periods WHERE career_id=? ORDER BY "
                "CASE status WHEN 'open' THEN 0 WHEN 'closing' THEN 1 ELSE 2 END, season_start_year DESC LIMIT 1",
                (career_id,),
            ).fetchone()
        if not row:
            raise ValueError("Financial period not found.")
        return row

    def _account_id(self, conn: sqlite3.Connection, career_id: int, system_key: str) -> int:
        row = conn.execute(
            "SELECT id FROM finance_accounts WHERE career_id=? AND system_key=?", (career_id, system_key)
        ).fetchone()
        if not row:
            raise ValueError(f"Finanzkonto {system_key} is missing.")
        return int(row["id"])

    def _seed_accounts(self, conn: sqlite3.Connection, career_id: int, now: str) -> None:
        for code, name, account_class, system_key in ACCOUNT_DEFINITIONS:
            conn.execute(
                "INSERT OR IGNORE INTO finance_accounts(career_id,code,name,account_class,system_key,created_at) "
                "VALUES(?,?,?,?,?,?)", (career_id, code, name, account_class, system_key, now),
            )

    def _latest_snapshot_for_season(self, conn: sqlite3.Connection, career_id: int, season_start_year: int) -> sqlite3.Row | None:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC", (career_id,)
        ).fetchall()
        return next((row for row in rows if season_start_from_date(row["career_date"]) == season_start_year), None)

    def _snapshot_weekly_wages(self, conn: sqlite3.Connection, career_id: int, season_start_year: int) -> int:
        snapshot = self._latest_snapshot_for_season(conn, career_id, season_start_year)
        if not snapshot:
            return 0
        managed_id = snapshot["managed_team_ea_id"]
        if managed_id is None:
            return 0
        row = conn.execute(
            "SELECT COALESCE(SUM(wage),0) total FROM contract_states WHERE snapshot_id=? AND team_ea_id=?",
            (snapshot["id"], managed_id),
        ).fetchone()
        return int(row["total"] or 0) * 100

    def setup(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            if self._profile(conn, career_id):
                raise ValueError("Finance is already set up for this career.")
            options = self._season_options(conn, career_id)
            if not options:
                raise ValueError("Setup requires at least one Atlas season.")
            year = int(payload.get("seasonStartYear") or options[-1]["seasonStartYear"])
            season = next((item for item in options if int(item["seasonStartYear"]) == year), None)
            if not season:
                raise ValueError("The selected season does not exist.")
            currency = str(payload.get("baseCurrency") or "EUR").upper()
            if currency not in {"EUR", "GBP", "USD"}:
                raise ValueError("Unsupported base currency.")
            policy_key = str(payload.get("policyKey") or "balanced")
            defaults = POLICIES.get(policy_key, POLICIES["balanced"])
            if policy_key == "custom":
                defaults = POLICIES["balanced"]
            reserve_months = float(payload.get("reserveMonths") if payload.get("reserveMonths") is not None else defaults["reserve_months"])
            transfer_rate = float(payload.get("transferAllocationRate") if payload.get("transferAllocationRate") is not None else defaults["transfer_allocation_rate"])
            sales_rate = float(payload.get("salesRetentionRate") if payload.get("salesRetentionRate") is not None else defaults["sales_retention_rate"])
            wage_rate = float(payload.get("wageHeadroomRate") if payload.get("wageHeadroomRate") is not None else defaults["wage_headroom_rate"])
            if reserve_months < 0 or not all(0 <= value <= 1.5 for value in (transfer_rate, sales_rate, wage_rate)):
                raise ValueError("Finance policy contains invalid values.")
            opening_minor = as_minor(payload.get("openingBalance"))
            if opening_minor < 0 and not input_bool(payload.get("allowNegativeOpening"), "Negativen Startbestand erlauben", default=False):
                raise ValueError("A negative opening balance must be confirmed explicitly.")
            latest_snapshot = self._latest_snapshot_for_season(conn, career_id, year)
            default_financial_start = str(latest_snapshot["career_date"]) if latest_snapshot and latest_snapshot["career_date"] else season["startDate"]
            start_day = input_date(payload.get("financialStartDate") or default_financial_start, "Finanzstart", required=True)
            assert start_day is not None
            start_date = start_day.isoformat()
            if not season["startDate"] <= start_date <= season["endDate"]:
                raise ValueError("The financial start date must be within the selected season.")
            now = utc_now()
            conn.execute(
                "INSERT INTO finance_profiles(career_id,base_currency,financial_start_date,policy_key,reserve_months," 
                "transfer_allocation_rate,sales_retention_rate,wage_headroom_rate,manual_reserve_floor_minor," 
                "setup_mode,setup_completed_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (career_id, currency, start_date, policy_key, reserve_months, transfer_rate, sales_rate, wage_rate,
                 as_minor(payload.get("manualReserveFloor")), str(payload.get("setupMode") or "guided"), now, now),
            )
            cursor = conn.execute(
                "INSERT INTO finance_periods(career_id,season_start_year,season_label,start_date,end_date,status,opened_at) "
                "VALUES(?,?,?,?,?,'open',?)",
                (career_id, year, season["seasonLabel"], season["startDate"], season["endDate"], now),
            )
            period_id = int(cursor.lastrowid)
            self._seed_accounts(conn, career_id, now)
            if opening_minor != 0:
                self._post_entry(
                    conn, career_id, period_id, start_date, "opening_balance", "opening",
                    "Confirmed opening balance", [
                        ("bank", max(opening_minor, 0), max(-opening_minor, 0)),
                        ("opening_equity", max(-opening_minor, 0), max(opening_minor, 0)),
                    ], currency, created_by="setup",
                )
            weekly_wages = self._snapshot_weekly_wages(conn, career_id, year)
            if payload.get("confirmedWeeklyWages") not in (None, ""):
                weekly_wages = as_minor(payload.get("confirmedWeeklyWages"))
            monthly_fixed = int(round(weekly_wages * 52 / 12))
            reserve = max(as_minor(payload.get("manualReserveFloor")), int(round(monthly_fixed * reserve_months)))
            setup_reference = date.fromisoformat(start_date)
            due_90 = self._payables_due_minor(conn, career_id, setup_reference, 90)
            setup_exposure = build_contract_exposure(
                conn, career_id, reference_date=setup_reference, horizon_end=date.fromisoformat(season["endDate"]),
                policy_key=policy_key, due90_minor=due_90,
            )
            contract_risk_reserve = int((setup_exposure.get("summary") or {}).get("liquidityReserveMinor") or 0)
            liquid_base = max(0, opening_minor - reserve - due_90 - contract_risk_reserve)
            suggested_transfer = int(math.floor(liquid_base * transfer_rate / 10_000_000) * 10_000_000)
            transfer_limit = as_minor(payload.get("transferBudget")) if payload.get("transferBudget") not in (None, "") else suggested_transfer
            suggested_wage = int(math.ceil((weekly_wages * (1 + wage_rate)) / 50_000) * 50_000) if weekly_wages else 0
            wage_limit = as_minor(payload.get("weeklyWageBudget")) if payload.get("weeklyWageBudget") not in (None, "") else suggested_wage
            for budget_type, approved, occupied, source in (
                ("transfer", transfer_limit, 0, "setup_confirmed"),
                ("player_wages", wage_limit, weekly_wages, "snapshot_confirmed" if weekly_wages else "setup_confirmed"),
            ):
                conn.execute(
                    "INSERT INTO finance_budget_plans(period_id,budget_type,approved_limit_minor,occupied_minor,source,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'active',?,?)",
                    (period_id, budget_type, approved, occupied, source, now, now),
                )
            for item in payload.get("openingCommitments") or []:
                self._save_commitment(conn, career_id, period_id, item, now)
            self._audit(conn, career_id, "finance_setup", "finance_period", period_id, {
                "seasonLabel": season["seasonLabel"], "currency": currency, "openingMinor": opening_minor,
            })
        return self.overview(career_id, period_id)

    def _audit(self, conn: sqlite3.Connection, career_id: int, action: str, entity_type: str,
               entity_id: int, details: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO manual_change_log(career_id,occurred_at,action,entity_type,entity_id,details_json) "
            "VALUES(?,?,?,?,?,?)", (career_id, utc_now(), action, entity_type, entity_id, json.dumps(details, ensure_ascii=False)),
        )

    def _post_entry(self, conn: sqlite3.Connection, career_id: int, period_id: int, booking_date: str,
                    source_type: str, source_id: str | None, description: str,
                    lines: list[tuple[str, int, int]], currency: str, *, created_by: str = "user",
                    reversal_of_id: int | None = None) -> int:
        period = self._period(conn, career_id, period_id)
        if period["status"] == "closed" and source_type != "closing_adjustment":
            raise ValueError("The financial period is closed.")
        debit = sum(int(item[1]) for item in lines)
        credit = sum(int(item[2]) for item in lines)
        if debit <= 0 or debit != credit:
            raise ValueError("Journal entry is not balanced.")
        now = utc_now()
        cursor = conn.execute(
            "INSERT INTO finance_journal_entries(career_id,period_id,booking_date,source_type,source_id,description,status," 
            "model_version,reversal_of_id,created_by,created_at,posted_at) VALUES(?,?,?,?,?,?,'posted',?,?,?,?,?)",
            (career_id, period_id, booking_date, source_type, source_id, description, MODEL_VERSION,
             reversal_of_id, created_by, now, now),
        )
        entry_id = int(cursor.lastrowid)
        for system_key, debit_minor, credit_minor in lines:
            if debit_minor == 0 and credit_minor == 0:
                continue
            conn.execute(
                "INSERT INTO finance_journal_lines(journal_entry_id,account_id,debit_minor,credit_minor,currency) "
                "VALUES(?,?,?,?,?)",
                (entry_id, self._account_id(conn, career_id, system_key), int(debit_minor), int(credit_minor), currency),
            )
        return entry_id

    def post_manual(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            profile = self._profile(conn, career_id)
            if not profile:
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            amount = as_minor(payload.get("amount"))
            if amount <= 0:
                raise ValueError("The amount must be greater than zero.")
            direction = str(payload.get("direction") or "expense")
            category = str(payload.get("categoryKey") or ("other_income" if direction == "income" else "other_expense"))
            category_account = CATEGORY_ACCOUNTS.get(category)
            if not category_account:
                raise ValueError("Unknown financial category.")
            if direction == "income":
                lines = [("bank", amount, 0), (category_account, 0, amount)]
            elif direction == "expense":
                lines = [(category_account, amount, 0), ("bank", 0, amount)]
            else:
                raise ValueError("Direction must be income or expense.")
            booking_day = input_date(payload.get("bookingDate"), "Buchungsdatum") or self._period_reference_date(conn, career_id, period)
            entry_id = self._post_entry(
                conn, career_id, int(period["id"]), booking_day.isoformat(),
                "manual", None, str(payload.get("description") or "Manualer Finanzvorgang"), lines,
                str(profile["base_currency"]),
            )
            self._audit(conn, career_id, "finance_journal_post", "finance_journal_entry", entry_id, {
                "direction": direction, "amountMinor": amount, "category": category,
            })
        return self.overview(career_id, int(period["id"]))

    def reverse_entry(self, career_id: int, entry_id: int, reason: str) -> dict[str, Any]:
        with self.database.transaction() as conn:
            entry = conn.execute(
                "SELECT * FROM finance_journal_entries WHERE id=? AND career_id=?", (entry_id, career_id)
            ).fetchone()
            if not entry:
                raise ValueError("Journal entry not found.")
            if entry["status"] == "reversed":
                raise ValueError("The journal entry has already been reversed.")
            if entry["reversal_of_id"] is not None:
                raise ValueError("A reversal entry cannot be reversed again.")
            lines = conn.execute(
                "SELECT l.*,a.system_key FROM finance_journal_lines l JOIN finance_accounts a ON a.id=l.account_id "
                "WHERE l.journal_entry_id=? ORDER BY l.id", (entry_id,),
            ).fetchall()
            profile = self._profile(conn, career_id)
            period = self._period(conn, career_id, int(entry["period_id"]))
            reverse_id = self._post_entry(
                conn, career_id, int(entry["period_id"]), self._period_reference_date(conn, career_id, period).isoformat(), "reversal", f"entry:{entry_id}",
                f"Storno: {entry['description']} – {reason.strip() or 'Korrektur'}",
                [(str(row["system_key"]), int(row["credit_minor"]), int(row["debit_minor"])) for row in lines],
                str(profile["base_currency"]), created_by="user", reversal_of_id=entry_id,
            )
            conn.execute("UPDATE finance_journal_entries SET status='reversed' WHERE id=?", (entry_id,))
            self._audit(conn, career_id, "finance_journal_reverse", "finance_journal_entry", reverse_id, {"originalId": entry_id})
            period_id = int(entry["period_id"])
        return self.overview(career_id, period_id)

    def _save_commitment(self, conn: sqlite3.Connection, career_id: int, period_id: int,
                         payload: dict[str, Any], now: str | None = None) -> int:
        now = now or utc_now()
        direction = str(payload.get("direction") or "payable")
        if direction not in {"payable", "receivable"}:
            raise ValueError("Payment direction must be payable or receivable.")
        amount_status = str(payload.get("amountStatus") or ("unknown" if payload.get("amount") in (None, "") else "known"))
        if amount_status not in {"known", "estimated", "unknown"}:
            raise ValueError("Unknowner Betragsstatus.")
        amount_minor = None if amount_status == "unknown" else as_minor(payload.get("amount"))
        if amount_minor is not None and amount_minor <= 0:
            raise ValueError("Known commitment amounts must be greater than zero.")
        due_date = input_date(payload.get("dueDate"), "Due date")
        category_key = str(payload.get("categoryKey") or ("other_income" if direction == "receivable" else "other_expense"))
        if category_key not in CATEGORY_ACCOUNTS:
            raise ValueError("Unknown financial category for the open payment.")
        cursor = conn.execute(
            "INSERT INTO finance_commitments(career_id,period_id,source_type,source_id,direction,amount_minor,amount_status," 
            "commitment_kind,due_date,category_key,condition_json,status,settled_minor,description,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,'open',0,?,?,?)",
            (career_id, period_id, str(payload.get("sourceType") or "manual"), payload.get("sourceId"), direction,
             amount_minor, amount_status, str(payload.get("commitmentKind") or "other"), due_date.isoformat() if due_date else None,
             category_key,
             json.dumps(payload.get("condition") or {}, ensure_ascii=False),
             str(payload.get("description") or "Offene Zahlung"), now, now),
        )
        return int(cursor.lastrowid)

    def save_commitment(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            if not self._profile(conn, career_id):
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            commitment_id = self._save_commitment(conn, career_id, int(period["id"]), payload)
            self._audit(conn, career_id, "finance_commitment_create", "finance_commitment", commitment_id, {})
        return self.overview(career_id, int(period["id"]))

    def settle_commitment(self, career_id: int, commitment_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM finance_commitments WHERE id=? AND career_id=?", (commitment_id, career_id)
            ).fetchone()
            if not row:
                raise ValueError("Open payment not found.")
            if row["amount_status"] == "unknown" or row["amount_minor"] is None:
                amount = as_minor(payload.get("amount"))
                if amount <= 0:
                    raise ValueError("An amount must be provided when settling an unknown payment.")
                total = amount
            else:
                total = int(row["amount_minor"])
                remaining = max(0, total - int(row["settled_minor"] or 0))
                amount = as_minor(payload.get("amount")) if payload.get("amount") not in (None, "") else remaining
                if amount <= 0 or amount > remaining:
                    raise ValueError("The partial amount exceeds the outstanding amount.")
            profile = self._profile(conn, career_id)
            category = CATEGORY_ACCOUNTS.get(str(row["category_key"])) or (
                "other_income" if row["direction"] == "receivable" else "other_expense"
            )
            if row["direction"] == "receivable":
                lines = [("bank", amount, 0), (category, 0, amount)]
            else:
                lines = [(category, amount, 0), ("bank", 0, amount)]
            entry_id = self._post_entry(
                conn, career_id, int(row["period_id"]), (
                    input_date(payload.get("bookingDate") or row["due_date"], "Buchungsdatum")
                    or self._period_reference_date(conn, career_id, self._period(conn, career_id, int(row["period_id"])))
                ).isoformat(),
                "commitment_settlement", f"commitment:{commitment_id}:{int(row['settled_minor'] or 0)}", str(row["description"]),
                lines, str(profile["base_currency"]),
            )
            settled = int(row["settled_minor"] or 0) + amount
            status = "settled" if row["amount_status"] == "unknown" or settled >= total else "partial"
            conn.execute(
                "UPDATE finance_commitments SET settled_minor=?,status=?,updated_at=? WHERE id=?",
                (settled, status, utc_now(), commitment_id),
            )
            self._audit(conn, career_id, "finance_commitment_settle", "finance_commitment", commitment_id, {"entryId": entry_id, "amountMinor": amount})
            period_id = int(row["period_id"])
        return self.overview(career_id, period_id)

    def save_recurring(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            if not self._profile(conn, career_id):
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            default_day = self._period_reference_date(conn, career_id, period)
            direction = str(payload.get("direction") or "expense")
            if direction not in {"income", "expense"}:
                raise ValueError("Direction must be income or expense.")
            cadence = str(payload.get("cadence") or "monthly")
            if cadence not in {"weekly", "monthly", "quarterly", "seasonal", "annual"}:
                raise ValueError("Unknowner Zahlungsrhythmus.")
            amount_minor = as_minor(payload.get("amount"))
            if amount_minor <= 0:
                raise ValueError("The recurring amount must be greater than zero.")
            category_key = str(payload.get("categoryKey") or ("other_income" if direction == "income" else "club_operations"))
            if category_key not in CATEGORY_ACCOUNTS:
                raise ValueError("Unknown financial category for the recurring transaction.")
            start = input_date(payload.get("startDate"), "Startdatum") or default_day
            next_day = input_date(payload.get("nextDueDate"), "Next due date") or start
            end = input_date(payload.get("endDate"), "Enddatum")
            if end and end < start:
                raise ValueError("End date must not precede start date.")
            if next_day < start or (end and next_day > end):
                raise ValueError("The next due date must be within the term.")
            now = utc_now()
            cursor = conn.execute(
                "INSERT INTO finance_recurring_rules(career_id,source_type,source_id,category_key,direction,amount_minor,cadence," 
                "start_date,end_date,next_due_date,fixed_cost,description,active,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (career_id, str(payload.get("sourceType") or "manual"), payload.get("sourceId"), category_key,
                 direction, amount_minor, cadence, start.isoformat(),
                 end.isoformat() if end else None, next_day.isoformat(),
                 1 if input_bool(payload.get("fixedCost"), "Fixkosten", default=False) else 0,
                 str(payload.get("description") or "Wiederkehrender Vorgang"), now, now),
            )
            rule_id = int(cursor.lastrowid)
            self._audit(conn, career_id, "finance_recurring_create", "finance_recurring_rule", rule_id, {})
        return self.overview(career_id)

    def run_due(self, career_id: int, through_date: str | None = None) -> dict[str, Any]:
        posted = 0
        with self.database.transaction() as conn:
            profile = self._profile(conn, career_id)
            if not profile:
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id)
            through = input_date(through_date, "Stichtag") or self._period_reference_date(conn, career_id, period)
            through = min(through, date.fromisoformat(str(period["end_date"])))
            rules = conn.execute(
                "SELECT * FROM finance_recurring_rules WHERE career_id=? AND active=1 AND next_due_date<=? ORDER BY next_due_date,id",
                (career_id, through.isoformat()),
            ).fetchall()
            for rule in rules:
                due = date.fromisoformat(rule["next_due_date"])
                while due <= through and (not rule["end_date"] or due <= date.fromisoformat(rule["end_date"])):
                    amount = int(rule["amount_minor"])
                    category = CATEGORY_ACCOUNTS.get(str(rule["category_key"])) or ("other_income" if rule["direction"] == "income" else "other_expense")
                    lines = [("bank", amount, 0), (category, 0, amount)] if rule["direction"] == "income" else [(category, amount, 0), ("bank", 0, amount)]
                    source_id = f"rule:{rule['id']}:{due.isoformat()}"
                    try:
                        self._post_entry(conn, career_id, int(period["id"]), due.isoformat(), "recurring", source_id,
                                         str(rule["description"]), lines, str(profile["base_currency"]), created_by="system")
                        posted += 1
                    except sqlite3.IntegrityError:
                        pass
                    due = next_due(due, str(rule["cadence"]))
                active = 0 if rule["end_date"] and due > date.fromisoformat(rule["end_date"]) else 1
                conn.execute(
                    "UPDATE finance_recurring_rules SET next_due_date=?,active=?,updated_at=? WHERE id=?",
                    (due.isoformat(), active, utc_now(), rule["id"]),
                )
        result = self.overview(career_id)
        result["postedRecurringCount"] = posted
        return result

    def adjust_budget(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            budget_type = str(payload.get("budgetType") or "transfer")
            plan = conn.execute(
                "SELECT * FROM finance_budget_plans WHERE period_id=? AND budget_type=?", (period["id"], budget_type)
            ).fetchone()
            if not plan:
                raise ValueError("Budget plan not found.")
            amount = as_minor(payload.get("amount"))
            if input_bool(payload.get("negative"), "Negative budget adjustment", default=False):
                amount = -abs(amount)
            if amount == 0:
                raise ValueError("Budget adjustment must not be zero.")
            event_type = str(payload.get("eventType") or "manual_adjustment")
            event_day = input_date(payload.get("eventDate"), "Budget adjustment date") or self._period_reference_date(conn, career_id, period)
            cursor = conn.execute(
                "INSERT INTO finance_budget_events(budget_plan_id,event_date,event_type,amount_minor,source_type,source_id,reason,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (plan["id"], event_day.isoformat(), event_type, amount,
                 str(payload.get("sourceType") or "manual"), payload.get("sourceId"),
                 str(payload.get("reason") or "Manuale Budgetanpassung"), utc_now()),
            )
            event_id = int(cursor.lastrowid)
            self._audit(conn, career_id, "finance_budget_adjust", "finance_budget_event", event_id, {"budgetType": budget_type, "amountMinor": amount})
        return self.overview(career_id, int(period["id"]))

    def save_forecast(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            amount_status = str(payload.get("amountStatus") or ("unknown" if payload.get("amount") in (None, "") else "estimated"))
            if amount_status not in {"known", "estimated", "unknown"}:
                raise ValueError("Unknowner Betragsstatus.")
            amount = None if amount_status == "unknown" else as_minor(payload.get("amount"))
            if amount is not None and amount < 0:
                raise ValueError("Forecast amounts must not be negative; use the appropriate direction.")
            scenario = str(payload.get("scenario") or "expected")
            if scenario not in {"conservative", "expected", "ambitious"}:
                raise ValueError("Unknownes Prognoseszenario.")
            direction = str(payload.get("direction") or "income")
            if direction not in {"income", "expense"}:
                raise ValueError("Forecast direction must be income or expense.")
            probability = float(payload.get("probability") if payload.get("probability") is not None else 1.0)
            if not 0.0 <= probability <= 1.0:
                raise ValueError("Probability must be between 0 and 1.")
            due_date = input_date(payload.get("dueDate"), "Due date")
            now = utc_now()
            cursor = conn.execute(
                "INSERT INTO finance_forecast_items(career_id,period_id,scenario,source_type,source_id,direction,amount_minor," 
                "amount_status,probability,due_date,status,explanation,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,'active',?,?,?)",
                (career_id, period["id"], scenario,
                 str(payload.get("sourceType") or "manual"), payload.get("sourceId"),
                 direction, amount, amount_status, probability,
                 due_date.isoformat() if due_date else None, str(payload.get("explanation") or "Manualer Prognoseposten"), now, now),
            )
            forecast_id = int(cursor.lastrowid)
            self._audit(conn, career_id, "finance_forecast_create", "finance_forecast_item", forecast_id, {})
        return self.overview(career_id, int(period["id"]))

    def accept_transfer_proposal(self, career_id: int, transaction_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            transaction = conn.execute(
                "SELECT t.*,s.start_year,s.label FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id "
                "WHERE t.id=? AND s.career_id=? AND t.transaction_type='transfer'", (transaction_id, career_id),
            ).fetchone()
            if not transaction:
                raise ValueError("Historical transfer not found.")
            period = conn.execute(
                "SELECT * FROM finance_periods WHERE career_id=? AND season_start_year=?", (career_id, transaction["start_year"])
            ).fetchone() or self._period(conn, career_id)
            if transaction["fee"] is None:
                issue_id = self._upsert_unresolved(conn, career_id, int(period["id"]), "manual_transaction", str(transaction_id),
                    transaction["transaction_date"], "unknown_transfer_fee", {"player": transaction["display_name"], "season": transaction["label"]})
                self._audit(conn, career_id, "finance_unresolved_create", "finance_unresolved_event", issue_id, {})
                return self._overview_conn(conn, career_id, int(period["id"]))
            amount = int(transaction["fee"]) * 100
            profile = self._profile(conn, career_id)
            direction = "expense" if transaction["direction"] == "incoming" else "income"
            account = "transfer_expense" if direction == "expense" else "transfer_income"
            lines = [(account, amount, 0), ("bank", 0, amount)] if direction == "expense" else [("bank", amount, 0), (account, 0, amount)]
            entry_id = self._post_entry(
                conn, career_id, int(period["id"]), (
                    input_date(payload.get("bookingDate") or transaction["transaction_date"], "Buchungsdatum")
                    or self._period_reference_date(conn, career_id, period)
                ).isoformat(),
                "manual_transaction", str(transaction_id), f"Transfer: {transaction['display_name']}", lines,
                str(profile["base_currency"]), created_by="reconciliation",
            )
            plan = conn.execute(
                "SELECT * FROM finance_budget_plans WHERE period_id=? AND budget_type='transfer'", (period["id"],)
            ).fetchone()
            if plan:
                if direction == "expense":
                    event_amount = -amount
                    event_type = "acquisition_reservation"
                else:
                    event_amount = int(round(amount * float(profile["sales_retention_rate"])))
                    event_type = "sale_retention"
                conn.execute(
                    "INSERT INTO finance_budget_events(budget_plan_id,event_date,event_type,amount_minor,source_type,source_id,reason,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (plan["id"], (
                        input_date(payload.get("bookingDate") or transaction["transaction_date"], "Buchungsdatum")
                        or self._period_reference_date(conn, career_id, period)
                     ).isoformat(), event_type, event_amount,
                     "manual_transaction", str(transaction_id), f"Transfer {transaction['display_name']}", utc_now()),
                )
            self._audit(conn, career_id, "finance_transfer_accept", "finance_journal_entry", entry_id, {"transactionId": transaction_id})
            period_id = int(period["id"])
        return self.overview(career_id, period_id)

    def _upsert_unresolved(self, conn: sqlite3.Connection, career_id: int, period_id: int | None,
                           source_type: str, source_id: str | None, event_date: str | None,
                           issue_key: str, details: dict[str, Any]) -> int:
        now = utc_now()
        conn.execute(
            "INSERT INTO finance_unresolved_events(career_id,period_id,source_type,source_id,event_date,issue_key,details_json," 
            "resolution_status,created_at) VALUES(?,?,?,?,?,?,?,'open',?) "
            "ON CONFLICT(career_id,source_type,source_id,issue_key) DO UPDATE SET period_id=excluded.period_id," 
            "event_date=excluded.event_date,details_json=excluded.details_json",
            (career_id, period_id, source_type, source_id, event_date, issue_key, json.dumps(details, ensure_ascii=False), now),
        )
        row = conn.execute(
            "SELECT id FROM finance_unresolved_events WHERE career_id=? AND source_type=? AND source_id IS ? AND issue_key=?",
            (career_id, source_type, source_id, issue_key),
        ).fetchone()
        return int(row["id"])

    def resolve_unresolved(self, career_id: int, event_id: int, status: str = "resolved") -> dict[str, Any]:
        if status not in {"resolved", "ignored"}:
            raise ValueError("Invalid conflict status.")
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM finance_unresolved_events WHERE id=? AND career_id=?", (event_id, career_id)).fetchone()
            if not row:
                raise ValueError("Unresolved transaction not found.")
            conn.execute(
                "UPDATE finance_unresolved_events SET resolution_status=?,resolved_at=? WHERE id=?",
                (status, utc_now(), event_id),
            )
            self._audit(conn, career_id, "finance_unresolved_resolve", "finance_unresolved_event", event_id, {"status": status})
        return self.overview(career_id)

    def _transfer_proposals(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT t.*,s.label season_label,s.start_year FROM manual_transactions t "
            "JOIN manual_seasons s ON s.id=t.manual_season_id WHERE s.career_id=? AND s.start_year=? "
            "AND t.transaction_type='transfer' ORDER BY COALESCE(t.transaction_date,''),t.id",
            (career_id, period["season_start_year"]),
        ).fetchall()
        proposals: list[dict[str, Any]] = []
        for row in rows:
            existing = conn.execute(
                "SELECT 1 FROM finance_journal_entries WHERE career_id=? AND source_type='manual_transaction' AND source_id=? "
                "AND reversal_of_id IS NULL", (career_id, str(row["id"])),
            ).fetchone()
            unresolved = conn.execute(
                "SELECT id,resolution_status FROM finance_unresolved_events WHERE career_id=? AND source_type='manual_transaction' "
                "AND source_id=? AND issue_key='unknown_transfer_fee'", (career_id, str(row["id"])),
            ).fetchone()
            proposals.append({
                "transactionId": int(row["id"]), "playerEaId": row["player_ea_id"], "displayName": row["display_name"],
                "direction": row["direction"], "feeMinor": int(row["fee"] * 100) if row["fee"] is not None else None,
                "amountStatus": "known" if row["fee"] is not None else "unknown", "transactionDate": row["transaction_date"],
                "fromTeamName": row["from_team_name"], "toTeamName": row["to_team_name"],
                "status": (
                    "posted" if existing else
                    "unresolved" if unresolved and unresolved["resolution_status"] == "open" else
                    str(unresolved["resolution_status"]) if unresolved else
                    "proposal"
                ),
            })
        return proposals

    def _cash_balance(self, conn: sqlite3.Connection, career_id: int, period_id: int | None = None) -> int:
        """Return cumulative bank balance, optionally as of the selected Atlas season.

        A season view must never include entries from later finance periods. Entries from
        previous periods remain part of the carried bank balance.
        """
        account_id = self._account_id(conn, career_id, "bank")
        if period_id is None:
            row = conn.execute(
                "SELECT COALESCE(SUM(l.debit_minor-l.credit_minor),0) balance FROM finance_journal_lines l "
                "JOIN finance_journal_entries e ON e.id=l.journal_entry_id "
                "WHERE e.career_id=? AND l.account_id=?",
                (career_id, account_id),
            ).fetchone()
        else:
            selected = self._period(conn, career_id, period_id)
            row = conn.execute(
                "SELECT COALESCE(SUM(l.debit_minor-l.credit_minor),0) balance FROM finance_journal_lines l "
                "JOIN finance_journal_entries e ON e.id=l.journal_entry_id "
                "JOIN finance_periods p ON p.id=e.period_id "
                "WHERE e.career_id=? AND l.account_id=? AND p.season_start_year<=?",
                (career_id, account_id, int(selected["season_start_year"])),
            ).fetchone()
        return int(row["balance"] or 0)

    def _revenue_config(self, conn: sqlite3.Connection, period_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM finance_revenue_configs WHERE period_id=?", (period_id,)).fetchone()
        if row:
            return row
        now = utc_now()
        conn.execute(
            "INSERT INTO finance_revenue_configs(period_id,created_at,updated_at) VALUES(?,?,?)",
            (period_id, now, now),
        )
        return conn.execute("SELECT * FROM finance_revenue_configs WHERE period_id=?", (period_id,)).fetchone()

    def _sync_generated_events(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row,
                               profile: sqlite3.Row) -> dict[str, Any]:
        config = self._revenue_config(conn, int(period["id"]))
        built = self.dynamic_revenue.build(
            conn, career_id, period, str(profile["base_currency"]), str(profile["financial_start_date"]), dict(config)
        )
        if period["status"] == "closed":
            return built
        now = utc_now()
        active_keys: list[str] = []
        for event in built["events"]:
            source_key = str(event["sourceKey"])
            active_keys.append(source_key)
            conn.execute(
                "INSERT INTO finance_generated_events(career_id,period_id,source_key,event_type,direction,category_key,event_date,"
                "amount_minor,amount_status,competition_ea_id,competition_name,fixture_id,model_profile_key,quality_grade,"
                "description,explanation_json,status,journal_entry_id,manually_overridden,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'suggested',NULL,0,?,?) "
                "ON CONFLICT(career_id,source_key) DO UPDATE SET "
                "period_id=excluded.period_id,event_type=excluded.event_type,direction=excluded.direction,"
                "category_key=excluded.category_key,event_date=excluded.event_date,amount_minor=excluded.amount_minor,"
                "amount_status=excluded.amount_status,competition_ea_id=excluded.competition_ea_id,"
                "competition_name=excluded.competition_name,fixture_id=excluded.fixture_id,"
                "model_profile_key=excluded.model_profile_key,quality_grade=excluded.quality_grade,"
                "description=excluded.description,explanation_json=excluded.explanation_json,updated_at=excluded.updated_at "
                "WHERE finance_generated_events.status='suggested' AND finance_generated_events.manually_overridden=0",
                (
                    career_id, int(period["id"]), source_key, event["eventType"], event["direction"], event["categoryKey"],
                    event["eventDate"], int(event["amountMinor"]), event["amountStatus"], event.get("competitionEaId"),
                    event.get("competitionName"), event.get("fixtureId"), event["modelProfileKey"], event["qualityGrade"],
                    event["description"], json.dumps(event.get("explanation") or {}, ensure_ascii=False, sort_keys=True), now, now,
                ),
            )
        if active_keys:
            placeholders = ",".join("?" for _ in active_keys)
            conn.execute(
                f"DELETE FROM finance_generated_events WHERE career_id=? AND period_id=? AND status='suggested' "
                f"AND manually_overridden=0 AND source_key NOT IN ({placeholders})",
                (career_id, int(period["id"]), *active_keys),
            )
        else:
            conn.execute(
                "DELETE FROM finance_generated_events WHERE career_id=? AND period_id=? AND status='suggested' "
                "AND manually_overridden=0", (career_id, int(period["id"])),
            )
        return built

    def _generated_revenue_summary(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row,
                                   profile: sqlite3.Row, reference_date: date) -> dict[str, Any]:
        built = self._sync_generated_events(conn, career_id, period, profile)
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_generated_events WHERE career_id=? AND period_id=? ORDER BY event_date,id",
            (career_id, int(period["id"])),
        ).fetchall()]
        for row in rows:
            try:
                row["explanation"] = json.loads(row.pop("explanation_json") or "{}")
            except json.JSONDecodeError:
                row["explanation"] = {}
            row["isDue"] = row["status"] == "suggested" and str(row["event_date"]) <= reference_date.isoformat()
        suggested = [row for row in rows if row["status"] == "suggested"]
        posted = [row for row in rows if row["status"] == "posted"]
        due = [row for row in suggested if row["isDue"]]
        def totals(items: list[dict[str, Any]]) -> dict[str, int]:
            income = sum(int(row["amount_minor"]) for row in items if row["direction"] == "income")
            expense = sum(int(row["amount_minor"]) for row in items if row["direction"] == "expense")
            return {"incomeMinor": income, "expenseMinor": expense, "netMinor": income - expense, "count": len(items)}
        catalog_profiles = [{
            "key": item.get("key"), "label": item.get("label"), "quality": item.get("quality"),
            "validFromSeason": item.get("validFromSeason"), "validToSeason": item.get("validToSeason"),
        } for item in self.dynamic_revenue.catalog.get("profiles") or []]
        return {
            "config": dict(self._revenue_config(conn, int(period["id"]))),
            "profile": built["profile"], "context": built["context"], "sources": built["sources"],
            "qualityLabel": self.dynamic_revenue.quality_label(str(built["profile"].get("quality") or "estimated")),
            "events": rows, "suggested": totals(suggested), "posted": totals(posted), "due": totals(due),
            "ignoredCount": sum(1 for row in rows if row["status"] == "ignored"),
            "profileOptions": catalog_profiles,
        }

    def save_revenue_config(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            profile = self._profile(conn, career_id)
            if not profile:
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            if period["status"] == "closed":
                raise ValueError("A closed financial period cannot be changed.")
            current = self._revenue_config(conn, int(period["id"]))
            profile_key = payload.get("leagueProfileKey")
            if profile_key:
                valid = any(item.get("key") == profile_key for item in self.dynamic_revenue.catalog.get("profiles") or [])
                if not valid:
                    raise ValueError("Unknownes Liga-Medienprofil.")
            fields = {
                "league_profile_key": str(profile_key) if profile_key else None,
                "profile_source": "manual" if profile_key else "automatic",
                "media_enabled": 1 if input_bool(payload.get("mediaEnabled", current["media_enabled"]), "Mediengelder aktiv") else 0,
                "matchday_enabled": 1 if input_bool(payload.get("matchdayEnabled", current["matchday_enabled"]), "Spieltag aktiv") else 0,
                "prize_enabled": 1 if input_bool(payload.get("prizeEnabled", current["prize_enabled"]), "Preisgelder aktiv") else 0,
                "merchandising_enabled": 1 if input_bool(payload.get("merchandisingEnabled", current["merchandising_enabled"]), "Merchandising aktiv") else 0,
                "wages_enabled": 1 if input_bool(payload.get("wagesEnabled", current["wages_enabled"]), "Player wages aktiv") else 0,
                "operations_enabled": 1 if input_bool(payload.get("operationsEnabled", current["operations_enabled"]), "Club operations enabled") else 0,
                "merchandising_multiplier": float(payload.get("merchandisingMultiplier", current["merchandising_multiplier"])),
                "operations_multiplier": float(payload.get("operationsMultiplier", current["operations_multiplier"])),
            }
            if not 0 <= fields["merchandising_multiplier"] <= 5 or not 0 <= fields["operations_multiplier"] <= 5:
                raise ValueError("Multipliers must be between 0 and 5.")
            conn.execute(
                "UPDATE finance_revenue_configs SET league_profile_key=?,profile_source=?,media_enabled=?,matchday_enabled=?,"
                "prize_enabled=?,merchandising_enabled=?,wages_enabled=?,operations_enabled=?,merchandising_multiplier=?,"
                "operations_multiplier=?,updated_at=? WHERE period_id=?",
                (*fields.values(), utc_now(), int(period["id"])),
            )
            self._sync_generated_events(conn, career_id, period, profile)
            self._audit(conn, career_id, "finance_revenue_config", "finance_period", int(period["id"]), fields)
        return self.overview(career_id, int(period["id"]))

    def _post_generated_conn(self, conn: sqlite3.Connection, career_id: int, event: sqlite3.Row) -> int:
        if event["status"] != "suggested":
            raise ValueError("The automatic transaction has already been processed.")
        category = str(event["category_key"])
        account = CATEGORY_ACCOUNTS.get(category)
        if not account:
            raise ValueError("The automatic transaction category is invalid.")
        amount = int(event["amount_minor"])
        if event["direction"] == "income":
            lines = [("bank", amount, 0), (account, 0, amount)]
        else:
            lines = [(account, amount, 0), ("bank", 0, amount)]
        profile = self._profile(conn, career_id)
        entry_id = self._post_entry(
            conn, career_id, int(event["period_id"]), str(event["event_date"]), "generated_revenue",
            str(event["source_key"]), str(event["description"]), lines, str(profile["base_currency"]),
            created_by="atlas_dynamic_revenue",
        )
        conn.execute(
            "UPDATE finance_generated_events SET status='posted',journal_entry_id=?,updated_at=? WHERE id=?",
            (entry_id, utc_now(), int(event["id"])),
        )
        return entry_id

    def post_generated_event(self, career_id: int, event_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            event = conn.execute(
                "SELECT * FROM finance_generated_events WHERE id=? AND career_id=?", (event_id, career_id)
            ).fetchone()
            if not event:
                raise ValueError("Automatic financial transaction not found.")
            period = self._period(conn, career_id, int(event["period_id"]))
            if str(event["event_date"]) > self._period_reference_date(conn, career_id, period).isoformat():
                raise ValueError("Future automatic transactions cannot be posted yet.")
            self._post_generated_conn(conn, career_id, event)
        return self.overview(career_id, int(event["period_id"]))

    def post_due_generated(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            profile = self._profile(conn, career_id)
            if not profile:
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            if period["status"] == "closed":
                raise ValueError("The financial period is closed.")
            self._sync_generated_events(conn, career_id, period, profile)
            through = self._period_reference_date(conn, career_id, period)
            count = 0
            for event in conn.execute(
                "SELECT * FROM finance_generated_events WHERE career_id=? AND period_id=? AND status='suggested' "
                "AND event_date<=? ORDER BY event_date,id", (career_id, int(period["id"]), through.isoformat()),
            ).fetchall():
                self._post_generated_conn(conn, career_id, event)
                count += 1
            self._audit(conn, career_id, "finance_generated_post_due", "finance_period", int(period["id"]), {"count": count, "through": through.isoformat()})
        result = self.overview(career_id, int(period["id"]))
        result["postedGeneratedCount"] = count
        return result

    def ignore_generated_event(self, career_id: int, event_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            event = conn.execute(
                "SELECT * FROM finance_generated_events WHERE id=? AND career_id=?", (event_id, career_id)
            ).fetchone()
            if not event or event["status"] != "suggested":
                raise ValueError("The automatic transaction cannot be ignored.")
            period = self._period(conn, career_id, int(event["period_id"]))
            if period["status"] == "closed":
                raise ValueError("The financial period is closed.")
            conn.execute("UPDATE finance_generated_events SET status='ignored',updated_at=? WHERE id=?", (utc_now(), event_id))
            self._audit(conn, career_id, "finance_generated_ignore", "finance_generated_event", event_id, {"sourceKey": event["source_key"]})
            period_id = int(event["period_id"])
        return self.overview(career_id, period_id)

    def override_generated_event(self, career_id: int, event_id: int, amount: Any) -> dict[str, Any]:
        amount_minor = as_minor(amount)
        if amount_minor < 0:
            raise ValueError("The amount must not be negative.")
        with self.database.transaction() as conn:
            event = conn.execute(
                "SELECT * FROM finance_generated_events WHERE id=? AND career_id=?", (event_id, career_id)
            ).fetchone()
            if not event or event["status"] != "suggested":
                raise ValueError("The automatic transaction cannot be overridden.")
            period = self._period(conn, career_id, int(event["period_id"]))
            if period["status"] == "closed":
                raise ValueError("The financial period is closed.")
            conn.execute(
                "UPDATE finance_generated_events SET amount_minor=?,amount_status='known',manually_overridden=1,updated_at=? WHERE id=?",
                (amount_minor, utc_now(), event_id),
            )
            self._audit(conn, career_id, "finance_generated_override", "finance_generated_event", event_id,
                        {"oldMinor": int(event["amount_minor"]), "newMinor": amount_minor})
            period_id = int(event["period_id"])
        return self.overview(career_id, period_id)

    def _close_checklist(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> dict[str, Any]:
        season_year = int(period["season_start_year"])
        later_season = any(int(item["seasonStartYear"]) > season_year for item in self._season_options(conn, career_id))
        snapshot_dates = [
            str(row["career_date"]) for row in conn.execute(
                "SELECT career_date FROM snapshots WHERE career_id=? AND career_date IS NOT NULL ORDER BY import_sequence",
                (career_id,),
            ).fetchall() if row["career_date"]
        ]
        observed_date = max(snapshot_dates) if snapshot_dates else None
        period_ended = later_season or bool(observed_date and observed_date > str(period["end_date"]))
        due_recurring = int(conn.execute(
            "SELECT COUNT(*) count FROM finance_recurring_rules WHERE career_id=? AND active=1 "
            "AND next_due_date<=? AND (end_date IS NULL OR next_due_date<=end_date)",
            (career_id, period["end_date"]),
        ).fetchone()["count"])
        overdue = int(conn.execute(
            "SELECT COUNT(*) count FROM finance_commitments WHERE career_id=? AND period_id=? "
            "AND status IN ('open','partial','carried') AND due_date IS NOT NULL AND due_date<=?",
            (career_id, period["id"], period["end_date"]),
        ).fetchone()["count"])
        unresolved = int(conn.execute(
            "SELECT COUNT(*) count FROM finance_unresolved_events WHERE career_id=? AND period_id=? "
            "AND resolution_status='open'",
            (career_id, period["id"]),
        ).fetchone()["count"])
        generated_due = int(conn.execute(
            "SELECT COUNT(*) count FROM finance_generated_events WHERE career_id=? AND period_id=? "
            "AND status='suggested' AND event_date<=?",
            (career_id, period["id"], period["end_date"]),
        ).fetchone()["count"])
        return {
            "periodEnded": period_ended,
            "observedCareerDate": observed_date,
            "laterSeasonObserved": later_season,
            "dueRecurringCount": due_recurring,
            "overdueCommitmentCount": overdue,
            "unresolvedCount": unresolved,
            "generatedDueCount": generated_due,
            "canClose": period_ended and due_recurring == 0 and overdue == 0 and unresolved == 0 and generated_due == 0,
        }

    def _period_reference_date(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> date:
        """Best observed in-career date for a season, never the host computer calendar."""
        checklist = self._close_checklist(conn, career_id, period)
        if checklist["periodEnded"]:
            return date.fromisoformat(str(period["end_date"]))
        try:
            live = date.fromisoformat(str(career_clock(conn, career_id)["careerDate"]))
            if date.fromisoformat(str(period["start_date"])) <= live <= date.fromisoformat(str(period["end_date"])):
                return live
        except (ValueError, TypeError):
            pass
        rows = conn.execute(
            "SELECT career_date FROM snapshots WHERE career_id=? AND career_date>=? AND career_date<=? "
            "ORDER BY career_date DESC,import_sequence DESC LIMIT 1",
            (career_id, period["start_date"], period["end_date"]),
        ).fetchone()
        if rows and rows["career_date"]:
            return date.fromisoformat(str(rows["career_date"]))
        return date.fromisoformat(str(period["start_date"]))

    def _payables_due_minor(self, conn: sqlite3.Connection, career_id: int, from_date: date, days: int,
                            period_id: int | None = None) -> int:
        until = from_date + timedelta(days=days)
        params: list[Any] = [career_id, from_date.isoformat(), until.isoformat()]
        period_clause = ""
        if period_id is not None:
            period_clause = " AND period_id=?"
            params.append(period_id)
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN amount_minor IS NULL THEN 0 ELSE amount_minor-settled_minor END),0) total "
            "FROM finance_commitments WHERE career_id=? AND direction='payable' AND status IN ('open','partial','carried') "
            "AND due_date IS NOT NULL AND due_date>=? AND due_date<=?" + period_clause,
            tuple(params),
        ).fetchone()
        return int(row["total"] or 0)

    def _fixed_monthly_minor(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> int:
        plan = conn.execute(
            "SELECT occupied_minor FROM finance_budget_plans WHERE period_id=? AND budget_type='player_wages'", (period["id"],)
        ).fetchone()
        wages_monthly = int(round(int(plan["occupied_minor"] or 0) * 52 / 12)) if plan else 0
        recurring = 0.0
        for row in conn.execute(
            "SELECT amount_minor,cadence FROM finance_recurring_rules WHERE career_id=? AND fixed_cost=1 AND direction='expense' "
            "AND start_date<=? AND (end_date IS NULL OR end_date>=?)",
            (career_id, period["end_date"], period["start_date"]),
        ).fetchall():
            amount = int(row["amount_minor"])
            cadence = str(row["cadence"])
            recurring += amount * {"weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3, "seasonal": 1 / 12, "annual": 1 / 12}[cadence]
        return wages_monthly + int(round(recurring))

    def _journal_rows(self, conn: sqlite3.Connection, career_id: int, period_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT e.*,COALESCE(SUM(CASE WHEN a.system_key='bank' THEN l.debit_minor-l.credit_minor ELSE 0 END),0) cash_effect_minor "
            "FROM finance_journal_entries e JOIN finance_journal_lines l ON l.journal_entry_id=e.id "
            "JOIN finance_accounts a ON a.id=l.account_id WHERE e.career_id=? AND e.period_id=? "
            "GROUP BY e.id ORDER BY e.booking_date DESC,e.id DESC", (career_id, period_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _contract_exposure(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row,
                           reference_date: date, due90_minor: int | None = None) -> dict[str, Any]:
        profile = self._profile(conn, career_id)
        policy_key = str(profile["policy_key"] or "balanced") if profile else "balanced"
        due90 = self._payables_due_minor(conn, career_id, reference_date, 90, int(period["id"])) if due90_minor is None else int(due90_minor)
        return build_contract_exposure(
            conn, career_id, reference_date=reference_date,
            horizon_end=date.fromisoformat(str(period["end_date"])), policy_key=policy_key, due90_minor=due90,
        )

    def _budget_summary(self, conn: sqlite3.Connection, period: sqlite3.Row, cash: int, reserve: int,
                        reference_date: date) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in conn.execute(
            "SELECT p.*,COALESCE(SUM(e.amount_minor),0) events_minor FROM finance_budget_plans p "
            "LEFT JOIN finance_budget_events e ON e.budget_plan_id=p.id WHERE p.period_id=? GROUP BY p.id",
            (period["id"],),
        ).fetchall():
            current = int(row["approved_limit_minor"] or 0) + int(row["events_minor"] or 0)
            occupied = int(row["occupied_minor"] or 0)
            if row["budget_type"] == "transfer":
                board = max(0, current)
                career_id = int(period["career_id"])
                due_90 = self._payables_due_minor(conn, career_id, reference_date, 90, int(period["id"]))
                exposure = self._contract_exposure(conn, career_id, period, reference_date, due_90)
                contract_risk_reserve = int((exposure.get("summary") or {}).get("liquidityReserveMinor") or 0)
                liquid = max(0, cash - reserve - due_90 - contract_risk_reserve)
                result["transfer"] = {
                    "planId": int(row["id"]), "approvedMinor": int(row["approved_limit_minor"]),
                    "eventsMinor": int(row["events_minor"]), "boardFrameworkMinor": board,
                    "liquidCapacityMinor": liquid, "usableNowMinor": min(board, liquid), "due90Minor": due_90,
                    "contractRiskReserveMinor": contract_risk_reserve,
                    "contractRiskModel": exposure.get("model"),
                }
            else:
                result["playerWages"] = {
                    "planId": int(row["id"]), "approvedWeeklyMinor": current, "occupiedWeeklyMinor": occupied,
                    "freeWeeklyMinor": current - occupied, "approvedAnnualMinor": current * 52,
                    "occupiedAnnualMinor": occupied * 52,
                }
        return result

    def _forecast(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row, cash: int, reserve: int) -> dict[str, Any]:
        commitments = conn.execute(
            "SELECT direction,amount_minor,amount_status,settled_minor,due_date FROM finance_commitments "
            "WHERE career_id=? AND period_id=? AND status IN ('open','partial','carried')", (career_id, period["id"]),
        ).fetchall()
        guaranteed_income = sum(max(0, int(row["amount_minor"] or 0) - int(row["settled_minor"] or 0)) for row in commitments if row["direction"] == "receivable" and row["amount_status"] != "unknown")
        guaranteed_expense = sum(max(0, int(row["amount_minor"] or 0) - int(row["settled_minor"] or 0)) for row in commitments if row["direction"] == "payable" and row["amount_status"] != "unknown")
        unknown_count = sum(1 for row in commitments if row["amount_status"] == "unknown")
        generated = {"income": 0, "expense": 0}
        for row in conn.execute(
            "SELECT direction,amount_minor FROM finance_generated_events WHERE career_id=? AND period_id=? AND status='suggested'",
            (career_id, period["id"]),
        ).fetchall():
            generated[str(row["direction"])] += int(row["amount_minor"])
        manual: dict[str, dict[str, int]] = {key: {"income": 0, "expense": 0} for key in ("conservative", "expected", "ambitious")}
        for row in conn.execute(
            "SELECT * FROM finance_forecast_items WHERE period_id=? AND status='active'", (period["id"],)
        ).fetchall():
            if row["amount_minor"] is not None:
                manual[str(row["scenario"])][str(row["direction"])] += int(round(int(row["amount_minor"]) * float(row["probability"])))
            else:
                unknown_count += 1
        scenarios: list[dict[str, Any]] = []
        for key, income_factor, expense_factor in (
            ("conservative", 0.80, 1.10), ("expected", 1.0, 1.0), ("ambitious", 1.15, 1.0),
        ):
            income = guaranteed_income + int((manual[key]["income"] + generated["income"]) * income_factor)
            expense = guaranteed_expense + int((manual[key]["expense"] + generated["expense"]) * expense_factor)
            projected = cash + income - expense
            scenarios.append({
                "scenario": key, "incomeMinor": income, "expenseMinor": expense, "closingCashMinor": projected,
                "reserveGapMinor": projected - reserve, "risk": "red" if projected < 0 else "amber" if projected < reserve else "green",
            })
        return {"scenarios": scenarios, "guaranteedIncomeMinor": guaranteed_income, "guaranteedExpenseMinor": guaranteed_expense,
                "generatedIncomeMinor": generated["income"], "generatedExpenseMinor": generated["expense"], "unknownCount": unknown_count}

    def _worst_possible_league_result(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row) -> dict[str, Any]:
        snapshot = conn.execute(
            "SELECT * FROM snapshots WHERE career_id=? AND career_date>=? AND career_date<=? "
            "ORDER BY import_sequence DESC LIMIT 1",
            (career_id, period["start_date"], period["end_date"]),
        ).fetchone()
        if not snapshot or snapshot["managed_team_ea_id"] is None:
            return {"available": False, "reason": "No usable league snapshot exists in this financial period."}
        team = conn.execute(
            "SELECT ea_team_id,league_ea_id,league_name FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
            (snapshot["id"], snapshot["managed_team_ea_id"]),
        ).fetchone()
        if not team or team["league_ea_id"] is None:
            return {"available": False, "reason": "The managed club is not assigned to a league."}
        rows = conn.execute(
            "SELECT tls.team_ea_id,tls.current_table_position,tls.points,tls.matches_played "
            "FROM team_league_states tls WHERE tls.snapshot_id=? AND tls.league_ea_id=?",
            (snapshot["id"], team["league_ea_id"]),
        ).fetchall()
        own = next((row for row in rows if int(row["team_ea_id"]) == int(team["ea_team_id"])), None)
        if not own or not rows:
            return {"available": False, "reason": "Current table points are missing for the league."}
        team_count = len(rows)
        observed_max = max(int(row["matches_played"] or 0) for row in rows)
        rule_summary = league_rule_summary(conn, int(snapshot["id"]), int(team["league_ea_id"]))
        expected_rule_matches = int((rule_summary or {}).get("expectedFinalMatches") or 0)
        standard_total = max(0, (team_count - 1) * 2)
        total_matches = max(expected_rule_matches or standard_total, observed_max)
        own_points = int(own["points"] or 0)
        own_played = int(own["matches_played"] or 0)
        can_finish_ahead = 0
        for row in rows:
            if int(row["team_ea_id"]) == int(team["ea_team_id"]):
                continue
            played = int(row["matches_played"] or 0)
            maximum_points = int(row["points"] or 0) + max(0, total_matches - played) * 3
            # In a strict minimum case Atlas treats an attainable points tie as losing the tiebreaker.
            if maximum_points >= own_points:
                can_finish_ahead += 1
        worst_position = min(team_count, can_finish_ahead + 1)
        rule_positions = ((rule_summary or {}).get("positions") or {}) if rule_summary and rule_summary.get("available") else {}
        direct_relegation_positions = sorted(int(value) for value in (rule_positions.get("relegation") or []) if str(value).isdigit())
        playoff_relegation_positions = sorted(int(value) for value in (rule_positions.get("relegation_playoff") or []) if str(value).isdigit())
        relegation_danger_positions = sorted(set(direct_relegation_positions + playoff_relegation_positions))
        if relegation_danger_positions:
            relegation_slots = len(direct_relegation_positions)
            danger_boundary = min(relegation_danger_positions)
            relegation_possible = worst_position >= danger_boundary
            rule_mode = "competition_rule"
        else:
            relegation_slots = 3 if team_count >= 18 else 2 if team_count >= 12 else 1
            danger_boundary = team_count - relegation_slots + 1
            relegation_possible = worst_position >= danger_boundary
            rule_mode = "team_count_fallback"
        return {
            "available": True,
            "snapshotId": int(snapshot["id"]),
            "snapshotDate": str(snapshot["career_date"]),
            "leagueEaId": int(team["league_ea_id"]),
            "leagueName": str(team["league_name"] or "Liga"),
            "teamCount": team_count,
            "currentPosition": int(own["current_table_position"] or 0) or None,
            "worstPossiblePosition": worst_position,
            "currentPoints": own_points,
            "matchesPlayed": own_played,
            "totalMatchesAssumed": total_matches,
            "remainingMatches": max(0, total_matches - own_played),
            "relegationSlotsAssumed": relegation_slots,
            "relegationDangerPositions": relegation_danger_positions or list(range(danger_boundary, team_count + 1)),
            "relegationBoundaryPosition": danger_boundary,
            "relegationPossible": relegation_possible,
            "qualificationRule": rule_summary,
            "ruleMode": rule_mode,
            "method": "Remaining league matches for the managed club are treated as defeats; every team that can still catch or overtake it is placed ahead pessimistically. The relegation/play-off boundary comes from competition rules when available; otherwise the legacy squad-size heuristic applies.",
        }

    def _fixed_monthly_at_date(self, conn: sqlite3.Connection, career_id: int, period: sqlite3.Row,
                               reference_date: date, occupied_weekly_minor: int | None = None) -> int:
        if occupied_weekly_minor is None:
            plan = conn.execute(
                "SELECT occupied_minor FROM finance_budget_plans WHERE period_id=? AND budget_type='player_wages'",
                (period["id"],),
            ).fetchone()
            occupied_weekly_minor = int(plan["occupied_minor"] or 0) if plan else 0
        wages_monthly = int(round(int(occupied_weekly_minor or 0) * 52 / 12))
        recurring = 0.0
        for row in conn.execute(
            "SELECT amount_minor,cadence FROM finance_recurring_rules WHERE career_id=? AND fixed_cost=1 AND direction='expense' "
            "AND active=1 AND start_date<=? AND (end_date IS NULL OR end_date>=?)",
            (career_id, reference_date.isoformat(), reference_date.isoformat()),
        ).fetchall():
            recurring += int(row["amount_minor"]) * {"weekly": 52 / 12, "monthly": 1, "quarterly": 1 / 3, "seasonal": 1 / 12, "annual": 1 / 12}[str(row["cadence"])]
        return wages_monthly + int(round(recurring))

    def _next_season_minimum_transfer_budget(self, conn: sqlite3.Connection, career_id: int,
                                             period: sqlite3.Row, profile: sqlite3.Row, cash: int) -> dict[str, Any]:
        reference_date = self._period_reference_date(conn, career_id, period)
        period_end = date.fromisoformat(str(period["end_date"]))
        next_start = period_end + timedelta(days=1)
        worst = self._worst_possible_league_result(conn, career_id, period)
        income = 0
        expense = 0
        unknown_count = 0

        for row in conn.execute(
            "SELECT direction,amount_minor,amount_status,settled_minor,due_date FROM finance_commitments "
            "WHERE career_id=? AND status IN ('open','partial','carried') AND (due_date IS NULL OR due_date<=?)",
            (career_id, period["end_date"]),
        ).fetchall():
            if row["amount_status"] == "unknown" or row["amount_minor"] is None:
                unknown_count += 1
                continue
            remaining = max(0, int(row["amount_minor"] or 0) - int(row["settled_minor"] or 0))
            if row["direction"] == "receivable": income += remaining
            else: expense += remaining

        generated_rows = conn.execute(
            "SELECT * FROM finance_generated_events WHERE career_id=? AND period_id=? AND status='suggested' AND event_date<=?",
            (career_id, period["id"], period["end_date"]),
        ).fetchall()
        worst_media_variable: int | None = None
        if worst.get("available"):
            try:
                context = self.dynamic_revenue._managed_context(conn, career_id, period)
                context["position"] = int(worst["worstPossiblePosition"])
                revenue_profile = self.dynamic_revenue.profile_for(context.get("leagueId"), str(context.get("leagueName") or ""), int(period["season_start_year"]))
                config = self._revenue_config(conn, int(period["id"]))
                if config["league_profile_key"]:
                    override = next((item for item in self.dynamic_revenue.catalog.get("profiles") or [] if item.get("key") == config["league_profile_key"]), None)
                    if override: revenue_profile = dict(override)
                share = self.dynamic_revenue._media_share_major(revenue_profile, context)
                variable_native = share["merit"] + share["audience"] + share["youth"]
                worst_media_variable = self.dynamic_revenue._convert_major(variable_native, str(revenue_profile["nativeCurrency"]), str(profile["base_currency"]))
            except (ValueError, KeyError, TypeError):
                worst_media_variable = None

        for row in generated_rows:
            amount = int(row["amount_minor"] or 0)
            if str(row["source_key"]).endswith(":variable") and int(row["manually_overridden"] or 0) == 0 and worst_media_variable is not None:
                amount = worst_media_variable
            known = str(row["amount_status"]) == "known" or str(row["quality_grade"]) == "official"
            if row["direction"] == "income":
                income += amount if known else int(round(amount * 0.80))
            else:
                expense += amount if known else int(round(amount * 1.10))

        for row in conn.execute(
            "SELECT direction,amount_minor,probability,due_date FROM finance_forecast_items "
            "WHERE period_id=? AND scenario='conservative' AND status='active' AND (due_date IS NULL OR due_date<=?)",
            (period["id"], period["end_date"]),
        ).fetchall():
            if row["amount_minor"] is None:
                unknown_count += 1
                continue
            amount = int(round(int(row["amount_minor"]) * float(row["probability"])))
            if row["direction"] == "income": income += amount
            else: expense += amount

        projected_closing_cash = cash + income - expense
        next_fixed_monthly = self._fixed_monthly_at_date(conn, career_id, period, next_start)
        next_reserve = max(
            int(profile["manual_reserve_floor_minor"] or 0),
            int(round(next_fixed_monthly * float(profile["reserve_months"]))),
        )
        due_90 = self._payables_due_minor(conn, career_id, next_start, 90)
        next_horizon_end = date(next_start.year + 1, 6, 30)
        next_exposure = build_contract_exposure(
            conn, career_id, reference_date=next_start, horizon_end=next_horizon_end,
            policy_key=str(profile["policy_key"] or "balanced"), due90_minor=due_90,
        )
        contract_risk_reserve = int((next_exposure.get("summary") or {}).get("liquidityReserveMinor") or 0)
        liquid_base = max(0, projected_closing_cash - next_reserve - due_90 - contract_risk_reserve)
        allocation_rate = float(profile["transfer_allocation_rate"])
        minimum_budget = int(math.floor(liquid_base * allocation_rate / 10_000_000) * 10_000_000)
        return {
            "available": True,
            "nextSeasonStartDate": next_start.isoformat(),
            "nextSeasonLabel": f"{next_start.year}/{str(next_start.year + 1)[-2:]}",
            "minimumTransferBudgetMinor": minimum_budget,
            "projectedClosingCashMinor": projected_closing_cash,
            "conservativeRemainingIncomeMinor": income,
            "conservativeRemainingExpenseMinor": expense,
            "nextSeasonReserveMinor": next_reserve,
            "nextSeasonFixedMonthlyMinor": next_fixed_monthly,
            "dueFirst90DaysMinor": due_90,
            "contractRiskReserveMinor": contract_risk_reserve,
            "liquidBaseMinor": liquid_base,
            "allocationRate": allocation_rate,
            "unknownAmountCount": unknown_count,
            "leagueWorstCase": worst,
            "explanation": "This is the smallest currently forecast release under the same rollover formula Atlas uses at season close: conservative ending balance minus next reserve, confirmed 90-day payments and policy-weighted contract provision, followed by the transfer allocation in the finance policy.",
            "notIncluded": "Unknown or uncapped contract amounts, future transfer sales and additional revenue not yet earned are not budgeted as cash.",
        }

    def overview(self, career_id: int, period_id: int | None = None) -> dict[str, Any]:
        with self.database.transaction() as conn:
            return self._overview_conn(conn, career_id, period_id)

    def _overview_conn(self, conn: sqlite3.Connection, career_id: int, period_id: int | None = None) -> dict[str, Any]:
        profile = self._profile(conn, career_id)
        seasons = self._season_options(conn, career_id)
        if not profile:
            suggestions = []
            if seasons:
                latest = seasons[-1]
                weekly = self._snapshot_weekly_wages(conn, career_id, int(latest["seasonStartYear"]))
                monthly = int(round(weekly * 52 / 12))
                suggestions = [
                    {"key": "tight", "label": "Eng", "openingMinor": monthly * 3},
                    {"key": "stable", "label": "Stabil", "openingMinor": monthly * 6},
                    {"key": "strong", "label": "Stark", "openingMinor": monthly * 9},
                ]
            return {"configured": False, "seasonOptions": seasons, "policyOptions": POLICIES, "liquiditySuggestions": suggestions}
        period = self._period(conn, career_id, period_id)
        cash = self._cash_balance(conn, career_id, int(period["id"]))
        reference_date = self._period_reference_date(conn, career_id, period)
        fixed_monthly = self._fixed_monthly_minor(conn, career_id, period)
        reserve = max(int(profile["manual_reserve_floor_minor"] or 0), int(round(fixed_monthly * float(profile["reserve_months"]))))
        commitments = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_commitments WHERE career_id=? AND period_id=? "
            "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,due_date,id", (career_id, period["id"]),
        ).fetchall()]
        recurring = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_recurring_rules WHERE career_id=? AND start_date<=? "
            "AND (end_date IS NULL OR end_date>=?) ORDER BY active DESC,next_due_date,id",
            (career_id, period["end_date"], period["start_date"]),
        ).fetchall()]
        forecasts = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_forecast_items WHERE period_id=? ORDER BY scenario,due_date,id", (period["id"],),
        ).fetchall()]
        unresolved = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_unresolved_events WHERE career_id=? AND period_id=? AND resolution_status='open' ORDER BY id DESC",
            (career_id, period["id"]),
        ).fetchall()]
        for row in unresolved:
            try:
                row["details"] = json.loads(row.pop("details_json") or "{}")
            except json.JSONDecodeError:
                row["details"] = {}
        periods = [dict(row) for row in conn.execute(
            "SELECT * FROM finance_periods WHERE career_id=? ORDER BY season_start_year DESC", (career_id,),
        ).fetchall()]
        journal = self._journal_rows(conn, career_id, int(period["id"]))
        revenue = self._generated_revenue_summary(conn, career_id, period, profile, reference_date)
        budget = self._budget_summary(conn, period, cash, reserve, reference_date)
        due_90 = int((budget.get("transfer") or {}).get("due90Minor") or 0)
        contract_exposure = self._contract_exposure(conn, career_id, period, reference_date, due_90)
        forecast = self._forecast(conn, career_id, period, cash, reserve)
        next_season_transfer = self._next_season_minimum_transfer_budget(conn, career_id, period, profile, cash)
        proposals = self._transfer_proposals(conn, career_id, period)
        close_checklist = self._close_checklist(conn, career_id, period)
        return {
            "configured": True, "profile": dict(profile), "period": dict(period), "periods": periods,
            "seasonOptions": seasons, "referenceDate": reference_date.isoformat(), "cashMinor": cash, "fixedMonthlyMinor": fixed_monthly,
            "reserveMinor": reserve, "freeCashAfterReserveMinor": cash - reserve,
            "journal": journal, "commitments": commitments, "recurringRules": recurring,
            "budgets": budget, "forecast": forecast, "forecastItems": forecasts,
            "nextSeasonMinimumTransferBudget": next_season_transfer,
            "unresolved": unresolved, "transferProposals": proposals, "closeChecklist": close_checklist,
            "dynamicRevenue": revenue, "contractExposure": contract_exposure,
            "accounts": [dict(row) for row in conn.execute(
                "SELECT id,code,name,account_class,system_key,active FROM finance_accounts WHERE career_id=? ORDER BY code", (career_id,),
            ).fetchall()],
        }

    def close_period(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            profile = self._profile(conn, career_id)
            if not profile:
                raise ValueError("Finance has not been set up yet.")
            period = self._period(conn, career_id, int(payload["periodId"]) if payload.get("periodId") else None)
            if period["status"] == "closed":
                raise ValueError("The season has already been closed financially.")
            checklist = self._close_checklist(conn, career_id, period)
            if not checklist["canClose"] and not input_bool(payload.get("force"), "Forced season close", default=False):
                reasons: list[str] = []
                if not checklist["periodEnded"]:
                    reasons.append("Season end has not yet been confirmed by a later career state")
                if checklist["dueRecurringCount"]:
                    reasons.append(f"{checklist['dueRecurringCount']} due recurring payments not yet posted")
                if checklist["overdueCommitmentCount"]:
                    reasons.append(f"{checklist['overdueCommitmentCount']} open due payments")
                if checklist["unresolvedCount"]:
                    reasons.append(f"{checklist['unresolvedCount']} unresolved transactions")
                if checklist["generatedDueCount"]:
                    reasons.append(f"{checklist['generatedDueCount']} automatic club transactions not yet confirmed")
                raise ValueError("Season close blocked: " + "; ".join(reasons) + ".")
            now = utc_now()
            conn.execute(
                "UPDATE finance_periods SET status='closed',closed_at=?,closing_note=? WHERE id=?",
                (now, str(payload.get("closingNote") or ""), period["id"]),
            )
            conn.execute("UPDATE finance_budget_plans SET status='closed',updated_at=? WHERE period_id=?", (now, period["id"]))
            next_year = int(period["season_start_year"]) + 1
            next_period = conn.execute(
                "SELECT * FROM finance_periods WHERE career_id=? AND season_start_year=?", (career_id, next_year)
            ).fetchone()
            if not next_period:
                cursor = conn.execute(
                    "INSERT INTO finance_periods(career_id,season_start_year,season_label,start_date,end_date,status,opened_at) "
                    "VALUES(?,?,?,?,?,'open',?)",
                    (career_id, next_year, f"{next_year}/{str(next_year + 1)[-2:]}", f"{next_year}-07-01", f"{next_year + 1}-06-30", now),
                )
                next_period_id = int(cursor.lastrowid)
            else:
                next_period_id = int(next_period["id"])
                conn.execute("UPDATE finance_periods SET status='open',opened_at=COALESCE(opened_at,?) WHERE id=?", (now, next_period_id))
            old_revenue = self._revenue_config(conn, int(period["id"]))
            conn.execute(
                "INSERT INTO finance_revenue_configs(period_id,league_profile_key,profile_source,media_enabled,matchday_enabled,"
                "prize_enabled,merchandising_enabled,wages_enabled,operations_enabled,merchandising_multiplier,operations_multiplier,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(period_id) DO NOTHING",
                (next_period_id, None, "automatic", old_revenue["media_enabled"], old_revenue["matchday_enabled"],
                 old_revenue["prize_enabled"], old_revenue["merchandising_enabled"], old_revenue["wages_enabled"],
                 old_revenue["operations_enabled"], old_revenue["merchandising_multiplier"], old_revenue["operations_multiplier"], now, now),
            )
            conn.execute(
                "UPDATE finance_commitments SET period_id=?,status=CASE WHEN status IN ('open','partial') THEN 'carried' ELSE status END," 
                "updated_at=? WHERE career_id=? AND period_id=? AND status IN ('open','partial')",
                (next_period_id, now, career_id, period["id"]),
            )
            weekly = self._snapshot_weekly_wages(conn, career_id, next_year)
            old_wage = conn.execute(
                "SELECT occupied_minor FROM finance_budget_plans WHERE period_id=? AND budget_type='player_wages'", (period["id"],)
            ).fetchone()
            occupied = weekly or int(old_wage["occupied_minor"] if old_wage else 0)
            cash = self._cash_balance(conn, career_id)
            monthly = self._fixed_monthly_at_date(conn, career_id, period, date(next_year, 7, 1), occupied)
            reserve = max(int(profile["manual_reserve_floor_minor"] or 0), int(round(monthly * float(profile["reserve_months"]))))
            rollover_reference = date(next_year, 7, 1)
            due_90 = self._payables_due_minor(conn, career_id, rollover_reference, 90, next_period_id)
            rollover_exposure = build_contract_exposure(
                conn, career_id, reference_date=rollover_reference, horizon_end=date(next_year + 1, 6, 30),
                policy_key=str(profile["policy_key"] or "balanced"), due90_minor=due_90,
            )
            contract_risk_reserve = int((rollover_exposure.get("summary") or {}).get("liquidityReserveMinor") or 0)
            transfer = int(math.floor(max(0, cash - reserve - due_90 - contract_risk_reserve) * float(profile["transfer_allocation_rate"]) / 10_000_000) * 10_000_000)
            wage = int(math.ceil((occupied * (1 + float(profile["wage_headroom_rate"]))) / 50_000) * 50_000) if occupied else 0
            for kind, approved, used in (("transfer", transfer, 0), ("player_wages", wage, occupied)):
                conn.execute(
                    "INSERT INTO finance_budget_plans(period_id,budget_type,approved_limit_minor,occupied_minor,source,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'active',?,?) ON CONFLICT(period_id,budget_type) DO UPDATE SET "
                    "approved_limit_minor=excluded.approved_limit_minor,occupied_minor=excluded.occupied_minor,status='active',updated_at=excluded.updated_at",
                    (next_period_id, kind, approved, used, "season_rollover", now, now),
                )
            self._audit(conn, career_id, "finance_period_close", "finance_period", int(period["id"]), {"nextPeriodId": next_period_id})
        return self.overview(career_id, next_period_id)
