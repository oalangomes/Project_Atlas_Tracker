from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, parse_fc_date,
    parse_raw, player_age_data, rows_to_dicts, subtract_months,
)

class ManagementQueryMixin:
    def _contracts(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            rows = conn.execute(
                """SELECT c.*,p.display_name,p.overall,p.potential,p.primary_position,
                          p.contract_valid_until,p.team_ea_id,p.team_name,p.raw_json player_raw,
                          r.jersey_number,r.form,r.raw_json roster_raw
                   FROM contract_states c
                   LEFT JOIN player_states p ON p.snapshot_id=c.snapshot_id AND p.ea_player_id=c.player_ea_id
                   LEFT JOIN roster_states r ON r.snapshot_id=c.snapshot_id AND r.player_ea_id=c.player_ea_id
                   WHERE c.snapshot_id=? AND c.team_ea_id=?
                   ORDER BY p.contract_valid_until,c.duration_months,p.display_name""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchall()
            stat_rows = conn.execute(
                """SELECT player_ea_id,SUM(COALESCE(appearances,0)) appearances,
                          SUM(COALESCE(goals,0)) goals,SUM(COALESCE(assists,0)) assists,
                          CASE WHEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)>0
                               THEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN average_rating*appearances ELSE 0 END)
                                  / SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)
                          END average_rating
                   FROM season_stat_states WHERE snapshot_id=? AND represented_team_ea_id=? GROUP BY player_ea_id""",
                (snapshot_id, snap["managed_team_ea_id"]),
            ).fetchall()
            stats_by_player = {int(row["player_ea_id"]): dict(row) for row in stat_rows}
            items = []
            for row in rows:
                source = dict(row)
                player_raw_json = source.pop("player_raw", None)
                roster_raw_json = source.pop("roster_raw", None)
                item = clean_raw(source) or {}
                player_raw = parse_raw(player_raw_json)
                roster_raw = parse_raw(roster_raw_json)
                raw_role = item.get("raw", {}).get("player_role")
                item["playerRaw"] = player_raw
                item["primary_position_id"] = as_int(player_raw.get("primary_position_id"))
                item["player_role_raw"] = as_int(raw_role)
                item["player_role_label"] = contract_role_label(raw_role)
                item.update(player_age_data(player_raw.get("birthdate_raw"), snap["career_date"]))
                financial = self.state.financial.calculate_player(
                    conn, snap,
                    {
                        "overall": item.get("overall"), "potential": item.get("potential"),
                        "team_ea_id": item.get("team_ea_id"), "team_name": item.get("team_name"),
                        "primary_position": item.get("primary_position"),
                        "contract_valid_until": item.get("contract_valid_until"), "raw_json": player_raw_json,
                    },
                    roster={"form": item.get("form"), "raw_json": roster_raw_json},
                    contract={"wage": item.get("wage"), "raw_json": item.get("raw")},
                )
                item["market_value"] = financial["market_value"].get("value")
                item["financial"] = financial
                item.update(stats_by_player.get(int(item.get("player_ea_id") or 0), {}))
                items.append(item)
        items = self._enrich_players(items)
        for item in items:
            item["effective_weekly_wage"] = item.get("wage")

        def position_group(position: Any) -> str:
            value = str(position or "").upper()
            if value in {"GK", "TW"}: return "Goalkeepers"
            if value in {"LB", "RB", "CB", "LWB", "RWB", "LV", "RV", "IV", "LAV", "RAV"}: return "Defenders"
            if value in {"CDM", "CM", "CAM", "LM", "RM", "ZDM", "ZM", "ZOM"}: return "Midfielders"
            return "Attackers"

        wages = [as_int(item.get("wage")) for item in items]
        known = [value for value in wages if value is not None and value >= 0]
        total = sum(known)
        positive = [value for value in known if value > 0]
        sorted_items = sorted(items, key=lambda item: as_int(item.get("wage")) or -1, reverse=True)
        top_five_total = sum((as_int(item.get("wage")) or 0) for item in sorted_items[:5])

        max_wage = max(positive) if positive else 0
        if max_wage:
            raw_step = max_wage / 5
            magnitude = 10 ** max(0, len(str(int(raw_step))) - 1)
            normalized = raw_step / magnitude
            multiplier = 1 if normalized <= 1 else 2 if normalized <= 2 else 5 if normalized <= 5 else 10
            step = max(500, int(multiplier * magnitude))
        else:
            step = 5000
        distribution = []
        for index in range(5):
            lower = index * step
            upper = (index + 1) * step if index < 4 else None
            count = sum(1 for value in known if value >= lower and (upper is None or value < upper))
            label = f"{lower:,}–{upper - 1:,} €" if upper is not None else f"{lower:,} €+"
            distribution.append({"label": label.replace(",", "."), "lower": lower, "upper": upper, "count": count})

        group_order = ["Goalkeepers", "Defenders", "Midfielders", "Attackers"]
        group_rows = []
        for group in group_order:
            group_items = [item for item in items if position_group(item.get("primary_position")) == group]
            group_wages = [as_int(item.get("wage")) for item in group_items if as_int(item.get("wage")) is not None]
            group_total = sum(group_wages)
            group_rows.append({
                "group": group, "count": len(group_items), "known_count": len(group_wages),
                "weekly_wage": group_total,
                "average_wage": round(group_total / len(group_wages)) if group_wages else None,
                "share": round(group_total / total * 100, 1) if total else 0,
            })

        risk_threshold = sorted(positive)[max(0, int(len(positive) * .75) - 1)] if positive else 0
        risks = []
        for item in sorted_items:
            duration = as_int(item.get("duration_months"))
            wage = as_int(item.get("wage"))
            reasons = []
            if duration is not None and duration <= 12: reasons.append("12 months or less remaining")
            if wage is not None and wage >= risk_threshold and risk_threshold > 0: reasons.append("high wage")
            if reasons:
                risks.append({
                    "player_ea_id": item.get("player_ea_id"), "display_name": item.get("display_name"),
                    "wage": wage, "duration_months": duration, "reasons": reasons,
                })

        return {
            "snapshot": dict(snap),
            "contracts": items,
            "summary": {
                "count": len(items), "known_count": len(known), "missing_count": len(items) - len(known),
                "weekly_wage": total, "annual_wage": total * 52,
                "average_wage": round(total / len(known)) if known else 0,
                "median_wage": round(median(known)) if known else 0,
                "highest_wage": max(known) if known else 0,
                "lowest_wage": min(known) if known else 0,
                "top_five_share": round(top_five_total / total * 100, 1) if total else 0,
            },
            "wageStructure": {
                "distribution": distribution,
                "byPosition": group_rows,
                "topEarners": sorted_items[:10],
                "risks": risks[:12],
                "sourceLabel": "Imported wages from contracts.csv only",
            },
        }

    def _loans(self, snapshot_id: int, season_index: int | None = None) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            selected_index, options, option = self._season_context(conn, snap, season_index)
            items = self._season_loan_events(conn, int(snap["career_id"]), selected_index)
        managed_team_id = as_int(option.get("managed_team_ea_id"))
        for item in items:
            parent_id = as_int(item.get("parent_team_ea_id"))
            loan_id = as_int(item.get("loan_team_ea_id"))
            item["parentIdentity"] = self.state.media.team_brief(parent_id) if parent_id is not None else None
            item["loanIdentity"] = self.state.media.team_brief(loan_id) if loan_id is not None else None
            item["direction"] = (
                "Loan in" if managed_team_id is not None and loan_id == managed_team_id
                else "Loan out" if managed_team_id is not None and parent_id == managed_team_id
                else "Global"
            )
        items = self._enrich_players(items)
        incoming = [item for item in items if item.get("direction") == "Loan in"]
        outgoing = [item for item in items if item.get("direction") == "Loan out"]
        return {
            "snapshot": dict(snap),
            "seasonIndex": selected_index,
            "seasonLabel": option.get("label"),
            "seasonOptions": options,
            "incoming": incoming,
            "outgoing": outgoing,
            "all": items,
            "summary": {
                "incoming": len(incoming),
                "outgoing": len(outgoing),
                "global": len(items),
                "manual": sum(item.get("source") == "manual" for item in items),
                "imported": sum(item.get("source") == "snapshot" for item in items),
            },
        }

    def _transfers(self, snapshot_id: int, season_index: int | None = None) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            selected = self._snapshot(conn, snapshot_id)
            selected_index, options, option = self._season_context(conn, selected, season_index)
            events = self._season_transfer_events(conn, int(selected["career_id"]), selected_index)
            snapshot_count = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE career_id=? AND season_index=?",
                (selected["career_id"], selected_index),
            ).fetchone()[0]
        managed_team_id = as_int(option.get("managed_team_ea_id"))
        for item in events:
            from_id = as_int(item.get("from_team_ea_id"))
            to_id = as_int(item.get("to_team_ea_id"))
            item["media"] = self.state.media.player_media(int(item["player_ea_id"])) if as_int(item.get("player_ea_id")) is not None else None
            item["fromIdentity"] = self.state.media.team_brief(from_id) if from_id is not None else None
            item["toIdentity"] = self.state.media.team_brief(to_id) if to_id is not None else None
            item["direction"] = (
                "Incoming" if managed_team_id is not None and to_id == managed_team_id
                else "Outgoing" if managed_team_id is not None and from_id == managed_team_id
                else "Global"
            )
        own = [item for item in events if item["direction"] != "Global"]
        return {
            "snapshot": dict(selected),
            "seasonIndex": selected_index,
            "seasonLabel": option.get("label"),
            "seasonOptions": options,
            "own": own,
            "all": events,
            "summary": {
                "own": len(own),
                "incoming": sum(1 for item in own if item["direction"] == "Incoming"),
                "outgoing": sum(1 for item in own if item["direction"] == "Outgoing"),
                "global": len(events),
                "manual": sum(item.get("source") == "manual" for item in events),
                "observed": sum("presigned" in str(item.get("source")) for item in events),
                "hasComparisonBasis": int(snapshot_count or 0) >= 1,
                "knownFees": sum(item.get("fee") is not None for item in own),
                "unknownFees": sum(item.get("fee") is None for item in own),
            },
            "note": "Transfer history combines snapshot differences, observed agreements and manual records. Unknown fees remain blank.",
        }

    def _youth(self, snapshot_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            rows = conn.execute(
                """SELECT y.*,p.team_ea_id,p.team_name,p.height,p.weight,p.nationality_id,
                          p.contract_valid_until,p.raw_json player_raw_json,
                          r.form,r.raw_json roster_raw_json,
                          c.wage,c.duration_months,c.raw_json contract_raw_json,
                          pg.raw_json growth_raw
                   FROM youth_player_states y
                   LEFT JOIN player_states p ON p.snapshot_id=y.snapshot_id AND p.ea_player_id=y.player_ea_id
                   LEFT JOIN roster_states r ON r.snapshot_id=y.snapshot_id AND r.player_ea_id=y.player_ea_id
                   LEFT JOIN contract_states c ON c.snapshot_id=y.snapshot_id AND c.player_ea_id=y.player_ea_id
                   LEFT JOIN player_growth_states pg ON pg.snapshot_id=y.snapshot_id AND pg.player_ea_id=y.player_ea_id
                   WHERE y.snapshot_id=? ORDER BY y.potential DESC,y.overall DESC,y.display_name""",
                (snapshot_id,),
            ).fetchall()
            items = []
            for row in rows:
                source = dict(row)
                player_raw_json = source.pop("player_raw_json", None)
                roster_raw_json = source.pop("roster_raw_json", None)
                contract_raw_json = source.pop("contract_raw_json", None)
                growth_raw = source.pop("growth_raw", None)
                player_context = {
                    "overall": source.get("overall"),
                    "potential": source.get("potential"),
                    "team_ea_id": source.get("team_ea_id"),
                    "team_name": source.get("team_name"),
                    "primary_position": source.get("primary_position"),
                    "contract_valid_until": source.get("contract_valid_until"),
                    "raw_json": player_raw_json,
                }
                roster_context = {"form": source.get("form"), "raw_json": roster_raw_json}
                contract_context = {"wage": source.get("wage"), "raw_json": contract_raw_json}
                financial = self.state.financial.calculate_player(
                    conn, snap, player_context, roster=roster_context, contract=contract_context
                )
                item = clean_raw(source) or {}
                item["growth"] = parse_raw(growth_raw)
                player_raw = parse_raw(player_raw_json)
                item["playerRaw"] = player_raw
                item["primary_position_id"] = as_int(
                    item.get("raw", {}).get("primary_position_id")
                    or player_raw.get("primary_position_id")
                )
                item["age"] = age_on_date(player_raw.get("birthdate_raw"), snap["career_date"])
                item["financial"] = financial
                item["market_value"] = financial["market_value"].get("value")
                item["weekly_wage"] = financial["weekly_wage"].get("value")
                item["wage_label"] = financial["weekly_wage"].get("label")
                items.append(item)
        return {
            "snapshot": dict(snap),
            "players": self._enrich_players(items),
            "summary": {
                "count": len(items),
                "average_overall": round(sum((item.get("overall") or 0) for item in items) / len(items), 1) if items else None,
                "average_potential": round(sum((item.get("potential") or 0) for item in items) / len(items), 1) if items else None,
                "elite": sum(1 for item in items if (item.get("potential") or 0) >= 85),
            },
        }
