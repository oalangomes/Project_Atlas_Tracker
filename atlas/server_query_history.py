from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, latest_snapshot, parse_fc_date,
    parse_raw, rows_to_dicts, subtract_months, youth_potential_range,
)

class HistoryQueryMixin:
    def _compare(self, career_id: int, from_id: int, to_id: int) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            old = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (from_id, career_id)).fetchone()
            new = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (to_id, career_id)).fetchone()
            if not old or not new:
                raise ValueError("Snapshots do not belong to the selected career.")

            def roster_map(snap: sqlite3.Row) -> dict[int, dict[str, Any]]:
                rows = conn.execute(
                    """SELECT p.ea_player_id,p.display_name,p.overall,p.potential,p.team_ea_id,p.team_name,
                              p.primary_position,p.contract_valid_until,r.jersey_number,c.wage,c.duration_months
                       FROM roster_states r JOIN player_states p
                         ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                       LEFT JOIN contract_states c ON c.snapshot_id=p.snapshot_id AND c.player_ea_id=p.ea_player_id
                       WHERE r.snapshot_id=? AND r.team_ea_id=?""",
                    (snap["id"], snap["managed_team_ea_id"]),
                ).fetchall()
                return {row["ea_player_id"]: dict(row) for row in rows}

            before = roster_map(old)
            after = roster_map(new)
            added_ids = sorted(set(after) - set(before), key=lambda pid: after[pid]["display_name"])
            removed_ids = sorted(set(before) - set(after), key=lambda pid: before[pid]["display_name"])
            changed = []
            for player_id in sorted(set(before) & set(after), key=lambda pid: after[pid]["display_name"]):
                a, b = before[player_id], after[player_id]
                delta = {
                    "player_id": player_id,
                    "display_name": b["display_name"],
                    "before": a,
                    "after": b,
                    "overall_delta": (b.get("overall") or 0) - (a.get("overall") or 0),
                    "potential_delta": (b.get("potential") or 0) - (a.get("potential") or 0),
                    "wage_delta": (b.get("wage") or 0) - (a.get("wage") or 0),
                    "changed_fields": [],
                }
                for field in ("overall", "potential", "team_ea_id", "primary_position", "jersey_number", "wage", "duration_months", "contract_valid_until"):
                    if a.get(field) != b.get(field):
                        delta["changed_fields"].append(field)
                if delta["changed_fields"]:
                    changed.append(delta)

            old_completed = {
                row["fixture_key"]: row
                for row in self._fixture_rows(conn, old["id"], managed_only=True)
                if row.get("is_completed")
            }
            new_completed = {
                row["fixture_key"]: row
                for row in self._fixture_rows(conn, new["id"], managed_only=True)
                if row.get("is_completed")
            }
            new_results = [new_completed[key] for key in new_completed.keys() - old_completed.keys()]
            new_results.sort(key=lambda row: (row.get("date") or "", row.get("time") or ""))

            def totals(snapshot_id: int, team_id: int) -> dict[int, dict[str, Any]]:
                rows = conn.execute(
                    """SELECT player_ea_id,MAX(display_name) display_name,
                              SUM(COALESCE(appearances,0)) appearances,SUM(COALESCE(goals,0)) goals,
                              SUM(COALESCE(assists,0)) assists,
                              CASE WHEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)>0
                                   THEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN average_rating*appearances ELSE 0 END)
                                      / SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)
                              END average_rating
                       FROM season_stat_states WHERE snapshot_id=? AND represented_team_ea_id=?
                       GROUP BY player_ea_id""",
                    (snapshot_id, team_id),
                ).fetchall()
                return {row["player_ea_id"]: dict(row) for row in rows}

            stat_before = totals(old["id"], old["managed_team_ea_id"])
            stat_after = totals(new["id"], new["managed_team_ea_id"])
            stat_deltas = []
            for player_id in set(stat_before) | set(stat_after):
                a = stat_before.get(player_id, {})
                b = stat_after.get(player_id, {})
                row = {
                    "player_id": player_id,
                    "display_name": b.get("display_name") or a.get("display_name") or str(player_id),
                    "appearances": (b.get("appearances") or 0) - (a.get("appearances") or 0),
                    "goals": (b.get("goals") or 0) - (a.get("goals") or 0),
                    "assists": (b.get("assists") or 0) - (a.get("assists") or 0),
                }
                if any(row[key] for key in ("appearances", "goals", "assists")):
                    stat_deltas.append(row)
            stat_deltas.sort(key=lambda row: (-row["goals"], -row["assists"], -row["appearances"], row["display_name"]))

            league_before = conn.execute(
                "SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?",
                (old["id"], old["managed_team_ea_id"]),
            ).fetchone()
            league_after = conn.execute(
                "SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?",
                (new["id"], new["managed_team_ea_id"]),
            ).fetchone()

            loan_before = {
                (row["player_ea_id"], row["parent_team_ea_id"], row["loan_team_ea_id"]): dict(row)
                for row in conn.execute("SELECT * FROM loan_states WHERE snapshot_id=?", (old["id"],)).fetchall()
            }
            loan_after = {
                (row["player_ea_id"], row["parent_team_ea_id"], row["loan_team_ea_id"]): dict(row)
                for row in conn.execute("SELECT * FROM loan_states WHERE snapshot_id=?", (new["id"],)).fetchall()
            }

        return {
            "from": dict(old),
            "to": dict(new),
            "managedTeamChanged": old["managed_team_ea_id"] != new["managed_team_ea_id"],
            "addedPlayers": [after[player_id] for player_id in added_ids],
            "removedPlayers": [before[player_id] for player_id in removed_ids],
            "changedPlayers": changed,
            "newResults": new_results,
            "statDeltas": stat_deltas,
            "leagueBefore": clean_raw(league_before),
            "leagueAfter": clean_raw(league_after),
            "newLoans": [loan_after[key] for key in loan_after.keys() - loan_before.keys()],
            "endedLoans": [loan_before[key] for key in loan_before.keys() - loan_after.keys()],
            "summary": {
                "added_players": len(added_ids),
                "removed_players": len(removed_ids),
                "changed_players": len(changed),
                "new_results": len(new_results),
                "new_loans": len(loan_after.keys() - loan_before.keys()),
                "ended_loans": len(loan_before.keys() - loan_after.keys()),
            },
        }

    def _chronology(self, career_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            career = conn.execute("SELECT * FROM careers WHERE id=?", (career_id,)).fetchone()
            if not career:
                raise ValueError("Career not found.")
            selected = conn.execute(
                "SELECT * FROM snapshots WHERE id=? AND career_id=?",
                (snapshot_id, career_id),
            ).fetchone() if snapshot_id is not None else latest_snapshot(conn, career_id)
            if not selected:
                raise ValueError("No snapshot is available for this career.")
            snapshots = conn.execute(
                "SELECT * FROM snapshots WHERE career_id=? AND import_sequence<=? ORDER BY import_sequence",
                (career_id, selected["import_sequence"]),
            ).fetchall()

            events: list[dict[str, Any]] = []

            def add(event_type: str, event_date: str | None, title: str, description: str = "", *,
                    precision: str = "exact", source: str = "snapshot", importance: int = 1,
                    player_id: int | None = None, club_id: int | None = None,
                    competition_id: int | None = None, fixture_id: int | None = None,
                    data: dict[str, Any] | None = None) -> None:
                events.append({
                    "id": f"{event_type}:{len(events)+1}",
                    "type": event_type,
                    "date": event_date or selected["career_date"],
                    "title": title,
                    "description": description,
                    "precision": precision,
                    "source": source,
                    "importance": importance,
                    "player_id": player_id,
                    "club_id": club_id,
                    "competition_id": competition_id,
                    "fixture_id": fixture_id,
                    "data": data or {},
                })

            # User-maintained historical seasons are stored separately from immutable snapshots.
            manual_seasons = conn.execute(
                "SELECT * FROM manual_seasons WHERE career_id=? ORDER BY season_index,id",
                (career_id,),
            ).fetchall()
            for manual_season in manual_seasons:
                start_date = f"{manual_season['start_year']}-07-01" if manual_season["start_year"] else None
                end_date = f"{manual_season['end_year']}-06-30" if manual_season["end_year"] else start_date
                add(
                    "season", start_date, f"Historical season: {manual_season['label']}",
                    manual_season["managed_team_name"] or "Club not specified",
                    precision="manual", source="manuelle Pflege", importance=2,
                    club_id=as_int(manual_season["managed_team_ea_id"]),
                    data={"manual_season_id": manual_season["id"], "season_index": manual_season["season_index"]},
                )
                competition_rows = conn.execute(
                    "SELECT * FROM manual_competitions WHERE manual_season_id=? ORDER BY sort_order,id",
                    (manual_season["id"],),
                ).fetchall()
                for competition in competition_rows:
                    result_parts = []
                    if competition["final_position"]:
                        result_parts.append(f"Platz {competition['final_position']}")
                    if competition["result_text"]:
                        result_parts.append(str(competition["result_text"]))
                    add(
                        "competition_result", end_date, f"{competition['competition_name']} abgeschlossen",
                        " · ".join(result_parts) or "Participation recorded manually",
                        precision="manual", source="manuelle Pflege", importance=2,
                        competition_id=as_int(competition["competition_object_id"]),
                        data={"manual_competition_id": competition["id"], "competition_type": competition["competition_type"]},
                    )
                transaction_rows = conn.execute(
                    "SELECT * FROM manual_transactions WHERE manual_season_id=? ORDER BY COALESCE(transaction_date,''),id",
                    (manual_season["id"],),
                ).fetchall()
                for transaction in transaction_rows:
                    incoming = transaction["direction"] == "incoming"
                    kind = "Loan" if transaction["transaction_type"] == "loan" else "Transfer"
                    direction = "Incoming" if incoming else "Outgoing"
                    other_name = transaction["from_team_name"] if incoming else transaction["to_team_name"]
                    fee_text = f" · Transfer fee {transaction['fee']} {transaction['currency']}" if transaction["fee"] is not None else ""
                    add(
                        "loan" if transaction["transaction_type"] == "loan" else "transfer",
                        transaction["transaction_date"] or start_date,
                        f"{kind}-{direction}: {transaction['display_name']}",
                        f"Partnerverein: {other_name or 'not specified'}{fee_text}",
                        precision="manual", source="manuelle Pflege", importance=2,
                        player_id=as_int(transaction["player_ea_id"]),
                        club_id=as_int(transaction["from_team_ea_id"] if incoming else transaction["to_team_ea_id"]),
                        data={"manual_transaction_id": transaction["id"], "direction": transaction["direction"]},
                    )

            # Snapshot checkpoints. They provide the reliable boundaries for inferred changes.
            for snap in snapshots:
                add(
                    "snapshot", snap["career_date"], "Datenstand erfasst",
                    f"Snapshot {snap['external_snapshot_id']} · Season {int(snap['season_index']) + 1}",
                    precision="snapshot", source="manifest", importance=0,
                    data={"snapshot_id": snap["id"], "import_sequence": snap["import_sequence"]},
                )

            # Exact, dated match history from the selected observation.
            matches = self._fixture_rows(conn, selected["id"], managed_only=True)
            completed = [match for match in matches if match.get("is_completed")]
            for match in completed:
                home_id = as_int(match.get("home_team_ea_id"))
                away_id = as_int(match.get("away_team_ea_id"))
                managed_id = as_int(selected["managed_team_ea_id"])
                is_home = home_id == managed_id
                opponent_id = away_id if is_home else home_id
                opponent_name = match.get("away_team_name") if is_home else match.get("home_team_name")
                own = as_int(match.get("home_score" if is_home else "away_score"))
                against = as_int(match.get("away_score" if is_home else "home_score"))
                outcome = "Match"
                if own is not None and against is not None:
                    outcome = "Sieg" if own > against else "Niederlage" if own < against else "Unentschieden"
                add(
                    "match", match.get("date"), f"{outcome} gegen {opponent_name or 'unknownen Gegner'}",
                    f"{match.get('competition_name') or 'Competition'} · {own if own is not None else '–'}:{against if against is not None else '–'}",
                    source="fixtures.csv", importance=2 if outcome == "Sieg" else 1,
                    club_id=opponent_id, competition_id=as_int(match.get("competition_object_id")),
                    fixture_id=as_int(match.get("fixture_id")),
                    data={"result": match.get("managed_team_result"), "home": is_home},
                )

            # Contract signings and changes expose an exact contract date in the exporter.
            contract_rows = conn.execute(
                """SELECT c.*,p.display_name FROM contract_states c
                   LEFT JOIN player_states p ON p.snapshot_id=c.snapshot_id AND p.ea_player_id=c.player_ea_id
                   WHERE c.snapshot_id=? AND c.team_ea_id=?""",
                (selected["id"], selected["managed_team_ea_id"]),
            ).fetchall()
            for row in contract_rows:
                item = clean_raw(row) or {}
                raw = item.get("raw", {})
                contract_date = parse_fc_date(raw.get("contract_date"))
                if not contract_date:
                    continue
                role = contract_role_label(raw.get("player_role"))
                add(
                    "contract", contract_date, f"Contract: {item.get('display_name') or item.get('player_ea_id')}",
                    f"{role} · {item.get('duration_months') or '–'} Monate · {item.get('wage') or '–'} € pro Woche",
                    source="contracts.csv", importance=1, player_id=as_int(item.get("player_ea_id")),
                    data={"role": role, "wage": item.get("wage"), "duration_months": item.get("duration_months")},
                )

            # Active loan end dates are exact future commitments.
            loan_rows = conn.execute(
                """SELECT l.*,p.display_name,parent.team_name parent_team_name,loan.team_name loan_team_name
                   FROM loan_states l
                   LEFT JOIN player_states p ON p.snapshot_id=l.snapshot_id AND p.ea_player_id=l.player_ea_id
                   LEFT JOIN team_states parent ON parent.snapshot_id=l.snapshot_id AND parent.ea_team_id=l.parent_team_ea_id
                   LEFT JOIN team_states loan ON loan.snapshot_id=l.snapshot_id AND loan.ea_team_id=l.loan_team_ea_id
                   WHERE l.snapshot_id=? AND (l.parent_team_ea_id=? OR l.loan_team_ea_id=?)""",
                (selected["id"], selected["managed_team_ea_id"], selected["managed_team_ea_id"]),
            ).fetchall()
            for row in loan_rows:
                item = dict(row)
                incoming = as_int(item.get("loan_team_ea_id")) == as_int(selected["managed_team_ea_id"])
                direction = "Loan in ends" if incoming else "Loan out ends"
                other = item.get("parent_team_name") if incoming else item.get("loan_team_name")
                add(
                    "loan", item.get("loan_end_date"), f"{direction}: {item.get('display_name') or item.get('player_ea_id')}",
                    f"Partnerverein: {other or 'unavailable'}", source="loans.csv", importance=1,
                    player_id=as_int(item.get("player_ea_id")), club_id=as_int(item.get("parent_team_ea_id" if incoming else "loan_team_ea_id")),
                    data={"incoming": incoming, "loan_to_buy": bool(item.get("is_loan_to_buy"))},
                )

            # Youth intake dates are estimated from months_in_squad and clearly labelled as such.
            youth_rows = conn.execute("SELECT * FROM youth_player_states WHERE snapshot_id=?", (selected["id"],)).fetchall()
            for row in youth_rows:
                item = clean_raw(row) or {}
                months = as_int(item.get("raw", {}).get("months_in_squad"))
                estimated = subtract_months(selected["career_date"], months or 0)
                add(
                    "youth", estimated, f"Jugendspieler erfasst: {item.get('display_name')}",
                    f"{item.get('primary_position') or 'Position unknown'} · OVR {item.get('overall') or '–'} · POT {item.get('potential') or '–'}",
                    precision="estimated", source="youth_players.csv", importance=1,
                    player_id=as_int(item.get("player_ea_id")), data={"months_in_squad": months},
                )

            # Awards may be absent; generic rows preserve them without changing the schema.
            award_rows = conn.execute(
                "SELECT raw_json FROM generic_snapshot_rows WHERE snapshot_id=? AND file_name='player_awards.csv'",
                (selected["id"],),
            ).fetchall()
            for row in award_rows:
                raw = parse_raw(row["raw_json"])
                count = as_int(raw.get("count")) or 0
                if count <= 0:
                    continue
                add(
                    "award", selected["career_date"], f"Auszeichnung: {raw.get('display_name') or raw.get('player_id')}",
                    f"Typ {raw.get('award_type_id', '–')} · Anzahl {count}", precision="snapshot",
                    source="player_awards.csv", importance=2, player_id=as_int(raw.get("player_id")),
                )

            # Snapshot-to-snapshot changes become derived career events when multiple snapshots exist.
            for previous, current in zip(snapshots, snapshots[1:]):
                comparison = self._compare(career_id, previous["id"], current["id"])
                for player in comparison["addedPlayers"]:
                    add("squad", current["career_date"], f"New to squad: {player.get('display_name')}",
                        f"OVR {player.get('overall') or '–'} · POT {player.get('potential') or '–'}",
                        precision="snapshot", source="snapshot comparison", importance=2,
                        player_id=as_int(player.get("ea_player_id")))
                for player in comparison["removedPlayers"]:
                    add("squad", current["career_date"], f"No longer in squad: {player.get('display_name')}",
                        f"Last known club: {player.get('team_name') or '–'}",
                        precision="snapshot", source="snapshot comparison", importance=1,
                        player_id=as_int(player.get("ea_player_id")))
                for change in comparison["changedPlayers"]:
                    if abs(as_int(change.get("overall_delta")) or 0) >= 2:
                        add("development", current["career_date"], f"Entwicklung: {change.get('display_name')}",
                            f"OVR {change['before'].get('overall')} → {change['after'].get('overall')}",
                            precision="snapshot", source="snapshot comparison", importance=1,
                            player_id=as_int(change.get("player_id")), data={"overall_delta": change.get("overall_delta")})

            # Data-driven milestones from exact match and rating observations.
            wins = []
            for match in completed:
                managed_id = as_int(selected["managed_team_ea_id"])
                home = as_int(match.get("home_team_ea_id")) == managed_id
                own = as_int(match.get("home_score" if home else "away_score"))
                against = as_int(match.get("away_score" if home else "home_score"))
                if own is not None and against is not None and own > against:
                    wins.append((own - against, own, match))
            if wins:
                _, _, best = max(wins, key=lambda item: (item[0], item[1]))
                home = as_int(best.get("home_team_ea_id")) == as_int(selected["managed_team_ea_id"])
                opponent = best.get("away_team_name" if home else "home_team_name")
                own = as_int(best.get("home_score" if home else "away_score"))
                against = as_int(best.get("away_score" if home else "home_score"))
                add("milestone", best.get("date"), "Biggest win in the current data set",
                    f"{own}:{against} gegen {opponent}", source="derived from fixtures", importance=3,
                    club_id=as_int(best.get("away_team_ea_id" if home else "home_team_ea_id")),
                    competition_id=as_int(best.get("competition_object_id")), fixture_id=as_int(best.get("fixture_id")))

            best_rating = conn.execute(
                """SELECT * FROM player_match_performances WHERE snapshot_id=? AND rating IS NOT NULL
                   ORDER BY rating DESC,minutes_played DESC LIMIT 1""", (selected["id"],)
            ).fetchone()
            if best_rating:
                add("milestone", best_rating["date"], "Best single-match rating in the current data",
                    f"{best_rating['display_name'] or best_rating['player_ea_id']} · Bewertung {best_rating['rating']}",
                    source="match_ratings.csv", importance=3, player_id=as_int(best_rating["player_ea_id"]))

        type_order = {"milestone": 0, "match": 1, "award": 2, "competition_result": 3, "transfer": 4, "contract": 5, "squad": 6, "development": 7, "loan": 8, "season": 9, "youth": 10, "snapshot": 11}
        events.sort(key=lambda event: (event.get("date") or "", -event.get("importance", 0), -type_order.get(event.get("type"), 99)), reverse=True)
        counts: dict[str, int] = defaultdict(int)
        for event in events:
            counts[event["type"]] += 1
        return {
            "career": dict(career),
            "snapshot": dict(selected),
            "events": events,
            "summary": {
                "event_count": len(events),
                "exact": sum(1 for event in events if event["precision"] == "exact"),
                "estimated": sum(1 for event in events if event["precision"] == "estimated"),
                "snapshot_based": sum(1 for event in events if event["precision"] == "snapshot"),
                "manual": sum(1 for event in events if event["precision"] == "manual"),
                "by_type": dict(counts),
            },
        }

    def _search(self, snapshot_id: int, text: str) -> list[dict[str, Any]]:
        term = f"%{text.lower()}%"
        numeric = text.isdigit()
        number = int(text) if numeric else -1
        with self.state.database.connect() as conn:
            players = conn.execute(
                """SELECT p.ea_player_id id,p.display_name label,
                          COALESCE(tno.display_name,p.team_name) subtitle,p.overall meta,p.primary_position extra
                   FROM player_states p
                   JOIN snapshots s ON s.id=p.snapshot_id
                   LEFT JOIN team_name_overrides tno
                     ON tno.career_id=s.career_id AND tno.ea_team_id=p.team_ea_id
                   WHERE p.snapshot_id=? AND
                     (LOWER(p.display_name) LIKE ? OR (?=1 AND p.ea_player_id=?))
                   ORDER BY CASE WHEN LOWER(p.display_name)=LOWER(?) THEN 0 ELSE 1 END,
                            p.overall DESC,p.display_name LIMIT 12""",
                (snapshot_id, term, 1 if numeric else 0, number, text),
            ).fetchall()
            teams = conn.execute(
                """SELECT t.ea_team_id id,COALESCE(tno.display_name,t.team_name) label,
                          t.league_name subtitle,t.overall meta,'' extra
                   FROM team_states t
                   JOIN snapshots s ON s.id=t.snapshot_id
                   LEFT JOIN team_name_overrides tno
                     ON tno.career_id=s.career_id AND tno.ea_team_id=t.ea_team_id
                   WHERE t.snapshot_id=? AND
                     (LOWER(t.team_name) LIKE ? OR LOWER(COALESCE(tno.display_name,'')) LIKE ?
                      OR (?=1 AND t.ea_team_id=?))
                   ORDER BY CASE WHEN LOWER(COALESCE(tno.display_name,t.team_name))=LOWER(?) THEN 0 ELSE 1 END,
                            COALESCE(tno.display_name,t.team_name) LIMIT 8""",
                (snapshot_id, term, term, 1 if numeric else 0, number, text),
            ).fetchall()
            competitions = conn.execute(
                """SELECT competition_object_id id,competition_name label,'Competition' subtitle,'' meta,'' extra
                   FROM competition_states WHERE snapshot_id=? AND
                     (LOWER(competition_name) LIKE ? OR (?=1 AND competition_object_id=?))
                   ORDER BY competition_name LIMIT 6""",
                (snapshot_id, term, 1 if numeric else 0, number),
            ).fetchall()
        result: list[dict[str, Any]] = []
        result.extend({"type": "player", **dict(row)} for row in players)
        result.extend({"type": "club", **dict(row)} for row in teams)
        result.extend({"type": "competition", **dict(row)} for row in competitions)
        return result[:24]
