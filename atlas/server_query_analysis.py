from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
from typing import Any, Iterable

from .media_utils import season_start_from_date
from .positions import broad_position_group
from .server_utils import age_on_date, as_int, parse_raw, rows_to_dicts
from .match_stats import detailed_analysis


class AnalysisQueryMixin:
    """Cross-snapshot season read models used by analysis and movement pages."""

    @staticmethod
    def _season_label(season_index: int, start_year: int | None = None) -> str:
        if start_year is not None:
            return f"{start_year}/{str(start_year + 1)[-2:]}"
        return f"Season {season_index + 1}"

    def _season_options(self, conn: Any, career_id: int) -> list[dict[str, Any]]:
        snapshot_rows = conn.execute(
            """WITH ranked AS (
                   SELECT s.*,ROW_NUMBER() OVER (
                       PARTITION BY s.season_index ORDER BY s.import_sequence DESC
                   ) rn
                   FROM snapshots s WHERE s.career_id=?
               )
               SELECT season_index,MIN(career_date) first_date,MAX(career_date) last_date,
                      MAX(import_sequence) latest_sequence,COUNT(*) snapshot_count,
                      MAX(CASE WHEN rn=1 THEN id END) latest_snapshot_id,
                      MAX(CASE WHEN rn=1 THEN managed_team_ea_id END) managed_team_ea_id,
                      MAX(CASE WHEN rn=1 THEN managed_team_name END) managed_team_name
               FROM ranked GROUP BY season_index ORDER BY season_index""",
            (career_id,),
        ).fetchall()
        manual_rows = conn.execute(
            """SELECT id,season_index,label,start_year,end_year,managed_team_ea_id,managed_team_name
               FROM manual_seasons WHERE career_id=? ORDER BY start_year,season_index""",
            (career_id,),
        ).fetchall()
        merged: dict[int, dict[str, Any]] = {}
        for row in snapshot_rows:
            item = dict(row)
            index = int(item["season_index"])
            start_year = season_start_from_date(item.get("first_date"))
            item.update({
                "label": self._season_label(index, start_year),
                "start_year": start_year,
                "end_year": start_year + 1 if start_year is not None else None,
                "manual_season_id": None,
                "manual_season_index": None,
                "ea_season_index": index,
                "has_snapshots": True,
                "has_manual_data": False,
            })
            merged[index] = item
        for row in manual_rows:
            item = dict(row)
            manual_index = int(item["season_index"])
            start_year = as_int(item.get("start_year"))
            existing_key = next(
                (key for key, value in merged.items() if start_year is not None and as_int(value.get("start_year")) == start_year),
                None,
            )
            key = existing_key if existing_key is not None else manual_index
            current = merged.get(key, {
                "season_index": key,
                "ea_season_index": None,
                "first_date": None,
                "last_date": None,
                "latest_sequence": None,
                "snapshot_count": 0,
                "latest_snapshot_id": None,
                "has_snapshots": False,
            })
            current.update({
                "label": item.get("label") or self._season_label(manual_index, start_year),
                "start_year": start_year,
                "end_year": item.get("end_year"),
                "manual_season_id": item.get("id"),
                "manual_season_index": manual_index,
                "has_manual_data": True,
            })
            if current.get("managed_team_ea_id") is None:
                current["managed_team_ea_id"] = item.get("managed_team_ea_id")
                current["managed_team_name"] = item.get("managed_team_name")
            merged[key] = current
        result = sorted(
            merged.values(),
            key=lambda item: (as_int(item.get("start_year")) is None, as_int(item.get("start_year")) or 9999, int(item["season_index"])),
        )
        season_numbers = self._career_season_numbers(conn, career_id)
        latest_snapshot = conn.execute(
            "SELECT season_index FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1",
            (career_id,),
        ).fetchone()
        current_index = int(latest_snapshot["season_index"]) if latest_snapshot else (int(result[-1]["season_index"]) if result else None)
        for ordinal, item in enumerate(result, 1):
            start_year = as_int(item.get("start_year"))
            item["career_season_number"] = season_numbers.get(start_year, ordinal) if start_year is not None else ordinal
            item["is_current"] = current_index is not None and int(item["season_index"]) == current_index
        return result

    def _season_context(self, conn: Any, snapshot: Any, requested: int | None) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
        options = self._season_options(conn, int(snapshot["career_id"]))
        selected = int(snapshot["season_index"]) if requested is None else int(requested)
        option = next((item for item in options if int(item["season_index"]) == selected), None)
        if option is None:
            raise ValueError("Season not found.")
        return selected, options, option

    def _season_completion(self, conn: Any, career_id: int, option: dict[str, Any] | None) -> dict[str, Any]:
        """Return whether season awards may be assigned.

        A season is closed when a later calendar season is already observed or,
        for the latest season, the newest snapshot contains managed-team fixtures
        and none of them is still open.  This allows awards directly after the
        final match without requiring a snapshot from the following season.
        """
        if not option:
            return {"complete": False, "reason": "season_missing", "label": "Season not found"}
        if not bool(option.get("is_current")):
            return {"complete": True, "reason": "later_season_observed", "label": "Season complete"}
        snapshot_id = as_int(option.get("latest_snapshot_id"))
        if snapshot_id is None:
            return {"complete": False, "reason": "no_snapshot", "label": "No final snapshot is available"}
        row = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed,
                      SUM(CASE WHEN fo.is_completed=0 THEN 1 ELSE 0 END) open
               FROM fixture_observations fo
               WHERE fo.snapshot_id=? AND fo.managed_team_involved=1""",
            (snapshot_id,),
        ).fetchone()
        total = (as_int(row["total"]) or 0) if row else 0
        completed = (as_int(row["completed"]) or 0) if row else 0
        open_count = (as_int(row["open"]) or 0) if row else 0
        if total > 0 and completed > 0 and open_count == 0:
            return {"complete": True, "reason": "all_fixtures_completed", "label": "Final season match completed"}
        return {
            "complete": False,
            "reason": "fixtures_remaining" if open_count else "completion_not_confirmed",
            "label": f"Still {open_count} open season matches" if open_count else "Season end not yet confirmed",
            "fixture_count": total,
            "completed_fixture_count": completed,
            "open_fixture_count": open_count,
        }

    def _snapshot_transfer_events(self, conn: Any, career_id: int, season_index: int) -> list[dict[str, Any]]:
        season_snapshots = conn.execute(
            """SELECT * FROM snapshots WHERE career_id=? AND season_index=?
               ORDER BY import_sequence""",
            (career_id, season_index),
        ).fetchall()
        if not season_snapshots:
            return []
        previous = conn.execute(
            """SELECT * FROM snapshots WHERE career_id=? AND import_sequence<?
               ORDER BY import_sequence DESC LIMIT 1""",
            (career_id, season_snapshots[0]["import_sequence"]),
        ).fetchone()
        ordered = ([previous] if previous else []) + list(season_snapshots)
        events: list[dict[str, Any]] = []
        for before, after in zip(ordered, ordered[1:]):
            before_rows = conn.execute(
                """SELECT ea_player_id,display_name,team_ea_id,team_name,overall,primary_position,raw_json
                   FROM player_states WHERE snapshot_id=?""",
                (before["id"],),
            ).fetchall()
            after_rows = conn.execute(
                """SELECT ea_player_id,display_name,team_ea_id,team_name,overall,primary_position,raw_json
                   FROM player_states WHERE snapshot_id=?""",
                (after["id"],),
            ).fetchall()
            before_map = {int(row["ea_player_id"]): dict(row) for row in before_rows}
            after_map = {int(row["ea_player_id"]): dict(row) for row in after_rows}
            loans_after = {
                (int(row["player_ea_id"]), int(row["parent_team_ea_id"]), int(row["loan_team_ea_id"]))
                for row in conn.execute("SELECT * FROM loan_states WHERE snapshot_id=?", (after["id"],)).fetchall()
            }
            loans_before = {
                (int(row["player_ea_id"]), int(row["parent_team_ea_id"]), int(row["loan_team_ea_id"]))
                for row in conn.execute("SELECT * FROM loan_states WHERE snapshot_id=?", (before["id"],)).fetchall()
            }
            for player_id in sorted(before_map.keys() & after_map.keys()):
                old = before_map[player_id]
                new = after_map[player_id]
                from_id = as_int(old.get("team_ea_id"))
                to_id = as_int(new.get("team_ea_id"))
                if from_id is None or to_id is None or from_id == to_id:
                    continue
                if (player_id, from_id, to_id) in loans_after or (player_id, from_id, to_id) in loans_before:
                    continue
                player_raw = parse_raw(new.get("raw_json"))
                events.append({
                    "eventKey": f"derived:{before['id']}:{after['id']}:{player_id}:{from_id}:{to_id}",
                    "date": after["career_date"],
                    "season_index": season_index,
                    "fromSnapshotId": before["id"],
                    "toSnapshotId": after["id"],
                    "player_ea_id": player_id,
                    "display_name": new.get("display_name") or old.get("display_name"),
                    "overall": new.get("overall"),
                    "primary_position": new.get("primary_position"),
                    "primary_position_id": as_int(player_raw.get("primary_position_id")),
                    "from_team_ea_id": from_id,
                    "from_team_name": old.get("team_name") or f"Team {from_id}",
                    "to_team_ea_id": to_id,
                    "to_team_name": new.get("team_name") or f"Team {to_id}",
                    "fee": None,
                    "currency": "EUR",
                    "source": "snapshot_difference",
                    "source_label": "Derived",
                    "event_status": "Completed",
                })
        return events

    def _presigned_transfer_events(self, conn: Any, career_id: int, season_index: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """SELECT g.raw_json,s.id snapshot_id,s.career_date,s.import_sequence
               FROM generic_snapshot_rows g JOIN snapshots s ON s.id=g.snapshot_id
               WHERE s.career_id=? AND s.season_index=? AND g.file_name='presigned_transfers.csv'
               ORDER BY s.import_sequence""",
            (career_id, season_index),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = parse_raw(row["raw_json"])
            player_id = as_int(raw.get("player_id"))
            from_id = as_int(raw.get("from_team_id"))
            to_id = as_int(raw.get("to_team_id"))
            if player_id is None or from_id is None or to_id is None:
                continue
            key = str(raw.get("transfer_key") or f"{player_id}:{from_id}:{to_id}:{raw.get('completion_date') or raw.get('signed_date') or ''}")
            latest[key] = {
                "eventKey": f"observed:{key}",
                "date": raw.get("completion_date") or raw.get("signed_date") or row["career_date"],
                "agreement_date": raw.get("signed_date"),
                "completion_date": raw.get("completion_date"),
                "season_index": season_index,
                "sourceSnapshotId": row["snapshot_id"],
                "player_ea_id": player_id,
                "display_name": raw.get("display_name") or f"Player {player_id}",
                "overall": None,
                "primary_position": None,
                "primary_position_id": None,
                "from_team_ea_id": from_id,
                "from_team_name": raw.get("from_team_name") or f"Team {from_id}",
                "to_team_ea_id": to_id,
                "to_team_name": raw.get("to_team_name") or f"Team {to_id}",
                "fee": as_int(raw.get("offered_fee")),
                "currency": "EUR",
                "source": "presigned_observation",
                "source_label": "Observed",
                "event_status": "Agreed",
            }
        return list(latest.values())

    def _manual_transaction_events(self, conn: Any, career_id: int, season_index: int, kind: str) -> list[dict[str, Any]]:
        option = next((item for item in self._season_options(conn, career_id) if int(item["season_index"]) == int(season_index)), None)
        manual_season_id = as_int(option.get("manual_season_id")) if option else None
        if manual_season_id is not None:
            rows = conn.execute(
                """SELECT t.*,s.season_index manual_season_index,s.label season_label,s.managed_team_ea_id
                   FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                   WHERE s.career_id=? AND s.id=? AND t.transaction_type=?
                   ORDER BY COALESCE(t.transaction_date,''),t.id""",
                (career_id, manual_season_id, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.*,s.season_index manual_season_index,s.label season_label,s.managed_team_ea_id
                   FROM manual_transactions t JOIN manual_seasons s ON s.id=t.manual_season_id
                   WHERE s.career_id=? AND s.season_index=? AND t.transaction_type=?
                   ORDER BY COALESCE(t.transaction_date,''),t.id""",
                (career_id, season_index, kind),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            result.append({
                "eventKey": f"manual:{kind}:{item['id']}",
                "manual_id": item["id"],
                "date": item.get("transaction_date"),
                "season_index": season_index,
                "player_ea_id": item.get("player_ea_id"),
                "display_name": item.get("display_name"),
                "overall": None,
                "primary_position": None,
                "primary_position_id": None,
                "from_team_ea_id": item.get("from_team_ea_id"),
                "from_team_name": item.get("from_team_name"),
                "to_team_ea_id": item.get("to_team_ea_id"),
                "to_team_name": item.get("to_team_name"),
                "fee": item.get("fee"),
                "currency": item.get("currency") or "EUR",
                "loan_end_date": item.get("loan_end_date"),
                "direction_raw": item.get("direction"),
                "source": "manual",
                "source_label": "Manual",
                "event_status": "Manually added",
                "updated_at": item.get("updated_at"),
                "notes": item.get("notes"),
            })
        return result

    def _season_transfer_events(self, conn: Any, career_id: int, season_index: int) -> list[dict[str, Any]]:
        derived = self._snapshot_transfer_events(conn, career_id, season_index)
        agreements = self._presigned_transfer_events(conn, career_id, season_index)
        by_pair: dict[tuple[int | None, int | None, int | None], dict[str, Any]] = {
            (as_int(item.get("player_ea_id")), as_int(item.get("from_team_ea_id")), as_int(item.get("to_team_ea_id"))): item
            for item in derived
        }
        unmatched: list[dict[str, Any]] = []
        for agreement in agreements:
            key = (as_int(agreement.get("player_ea_id")), as_int(agreement.get("from_team_ea_id")), as_int(agreement.get("to_team_ea_id")))
            match = by_pair.get(key)
            if match:
                if agreement.get("fee") is not None:
                    match["fee"] = agreement["fee"]
                match["agreement_date"] = agreement.get("agreement_date")
                match["completion_date"] = agreement.get("completion_date")
                match["source"] = "snapshot_difference+presigned"
                match["source_label"] = "Derived + observed"
            else:
                unmatched.append(agreement)
        events = derived + unmatched + self._manual_transaction_events(conn, career_id, season_index, "transfer")
        events.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("display_name") or "")), reverse=True)
        return events

    def _season_loan_events(self, conn: Any, career_id: int, season_index: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """SELECT l.*,s.id source_snapshot_id,s.career_date,s.import_sequence,
                      p.display_name,p.overall,p.primary_position,p.raw_json player_raw,
                      parent.team_name parent_team_name,loan.team_name loan_team_name
               FROM loan_states l JOIN snapshots s ON s.id=l.snapshot_id
               LEFT JOIN player_states p ON p.snapshot_id=l.snapshot_id AND p.ea_player_id=l.player_ea_id
               LEFT JOIN team_states parent ON parent.snapshot_id=l.snapshot_id AND parent.ea_team_id=l.parent_team_ea_id
               LEFT JOIN team_states loan ON loan.snapshot_id=l.snapshot_id AND loan.ea_team_id=l.loan_team_ea_id
               WHERE s.career_id=? AND s.season_index=?
               ORDER BY s.import_sequence""",
            (career_id, season_index),
        ).fetchall()
        observed: dict[tuple[int, int, int], dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            key = (int(item["player_ea_id"]), int(item["parent_team_ea_id"]), int(item["loan_team_ea_id"]))
            raw = parse_raw(item.pop("player_raw", None))
            event = observed.get(key)
            if event is None:
                event = {
                    "eventKey": f"loan:{season_index}:{key[0]}:{key[1]}:{key[2]}",
                    "date": item.get("career_date"),
                    "first_observed_date": item.get("career_date"),
                    "last_observed_date": item.get("career_date"),
                    "season_index": season_index,
                    "sourceSnapshotId": item.get("source_snapshot_id"),
                    "player_ea_id": key[0],
                    "display_name": item.get("display_name") or f"Player {key[0]}",
                    "overall": item.get("overall"),
                    "primary_position": item.get("primary_position"),
                    "primary_position_id": as_int(raw.get("primary_position_id")),
                    "parent_team_ea_id": key[1],
                    "parent_team_name": item.get("parent_team_name") or f"Team {key[1]}",
                    "loan_team_ea_id": key[2],
                    "loan_team_name": item.get("loan_team_name") or f"Team {key[2]}",
                    "loan_end_date": item.get("loan_end_date"),
                    "is_loan_to_buy": item.get("is_loan_to_buy"),
                    "fee": None,
                    "source": "snapshot",
                    "source_label": "Imported",
                    "event_status": "Observed",
                }
                observed[key] = event
            else:
                event["last_observed_date"] = item.get("career_date")
                if item.get("loan_end_date"):
                    event["loan_end_date"] = item.get("loan_end_date")
        events = list(observed.values())
        for item in self._manual_transaction_events(conn, career_id, season_index, "loan"):
            events.append({
                **item,
                "parent_team_ea_id": item.get("from_team_ea_id"),
                "parent_team_name": item.get("from_team_name"),
                "loan_team_ea_id": item.get("to_team_ea_id"),
                "loan_team_name": item.get("to_team_name"),
                "is_loan_to_buy": None,
            })
        events.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("display_name") or "")), reverse=True)
        return events

    @staticmethod
    def _league_name_key(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        text = text.casefold().replace("&", " and ")
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"\b(?:sky\s*bet|skybet|barclays|efl|cinch|ladbrokes)\b", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    def _resolve_league_reference(
        self, conn: Any, league_id: Any, league_name: Any, country_id: Any = None
    ) -> tuple[Any | None, str]:
        numeric_id = as_int(league_id)
        if numeric_id is not None:
            exact = conn.execute(
                "SELECT * FROM reference_leagues WHERE ea_league_id=?", (numeric_id,)
            ).fetchone()
            if exact is not None:
                return exact, "reference_id"

        name_key = self._league_name_key(league_name)
        if not name_key:
            return None, "unresolved"

        aliases = {
            "premier league": 13,
            "english premier league": 13,
            "england premier league": 13,
            "championship": 14,
            "english championship": 14,
            "england championship": 14,
            "league one": 60,
            "english league one": 60,
            "england league one": 60,
            "league two": 61,
            "english league two": 61,
            "england league two": 61,
        }
        alias_id = aliases.get(name_key)
        if alias_id is not None:
            alias = conn.execute(
                "SELECT * FROM reference_leagues WHERE ea_league_id=?", (alias_id,)
            ).fetchone()
            if alias is not None:
                return alias, "reference_alias"

        rows = conn.execute(
            "SELECT * FROM reference_leagues ORDER BY ea_league_id"
        ).fetchall()
        country = as_int(country_id)
        candidates: list[tuple[float, Any]] = []
        source_tokens = set(name_key.split())
        for row in rows:
            if country is not None and as_int(row["country_id"]) not in (None, country):
                continue
            candidate_key = self._league_name_key(row["league_name"])
            if not candidate_key:
                continue
            if candidate_key == name_key:
                score = 10.0
            elif candidate_key.endswith(" " + name_key) or name_key.endswith(" " + candidate_key):
                score = 8.0
            else:
                candidate_tokens = set(candidate_key.split())
                if not source_tokens or not source_tokens.issubset(candidate_tokens):
                    continue
                score = 5.0 + len(source_tokens) / max(1, len(candidate_tokens))
            candidates.append((score, row))
        if not candidates:
            return None, "unresolved"
        candidates.sort(key=lambda item: (item[0], -(as_int(item[1]["ea_league_id"]) or 0)), reverse=True)
        best_score = candidates[0][0]
        best = [row for score, row in candidates if abs(score - best_score) < 0.0001]
        if len(best) == 1:
            return best[0], "reference_name"
        return None, "ambiguous"

    @staticmethod
    def _position_group(position: Any) -> str:
        if not str(position or "").strip():
            return "Unknown"
        return {"GK": "Goalkeeper", "DEF": "Defence", "MID": "Midfield", "ATT": "Attack"}[
            broad_position_group(position)
        ]

    def _league_history(
        self, conn: Any, career_id: int, team_id: int, current_snapshot_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Build one clear league path plus separate season-result fields.

        League level answers where the club played. Final/current position answers
        how the season went; the two dimensions are deliberately never combined.
        """
        season_options = {int(item["season_index"]): item for item in self._season_options(conn, career_id)}
        max_snapshot_sequence = conn.execute(
            "SELECT MAX(import_sequence) FROM snapshots WHERE career_id=?", (career_id,)
        ).fetchone()[0]

        def league_context(league_id: Any, league_name: Any, level: Any = None, country_id: Any = None) -> dict[str, Any]:
            resolved_level = as_int(level)
            if resolved_level is not None and resolved_level <= 0:
                resolved_level = None
            resolved_country = as_int(country_id)
            numeric_id = as_int(league_id)
            reference, resolution = self._resolve_league_reference(
                conn, numeric_id, league_name, resolved_country
            )
            if reference is not None:
                reference_level = as_int(reference["level"])
                if resolved_level is None and reference_level is not None and reference_level > 0:
                    resolved_level = reference_level
                resolved_country = resolved_country or as_int(reference["country_id"])
                numeric_id = as_int(reference["ea_league_id"])
            reference_name = reference["league_name"] if reference is not None else league_name
            display_name = self._display_competition_name(
                conn,
                reference_name or league_name or "League",
                career_id=career_id,
                static_competition_id=numeric_id,
            )
            return {
                "league_ea_id": numeric_id,
                "league_name": display_name,
                "league_level": resolved_level,
                "country_id": resolved_country,
                "league_level_source": "snapshot" if as_int(level) not in (None, 0) else resolution,
                "league_level_resolved": resolved_level is not None and resolved_level > 0,
            }

        rows = conn.execute(
            """WITH ranked AS (
                   SELECT s.season_index,s.career_date,s.import_sequence,s.id snapshot_id,
                          tls.league_ea_id,tls.current_table_position,tls.points,tls.matches_played,tls.champion,
                          COALESCE(ls.league_name,ts.league_name) league_name,ls.level league_level,ls.country_id,
                          ROW_NUMBER() OVER (PARTITION BY s.season_index ORDER BY s.import_sequence DESC) rn
                   FROM team_league_states tls
                   JOIN snapshots s ON s.id=tls.snapshot_id
                   LEFT JOIN team_states ts ON ts.snapshot_id=s.id AND ts.ea_team_id=tls.team_ea_id
                   LEFT JOIN league_states ls ON ls.snapshot_id=s.id AND ls.ea_league_id=tls.league_ea_id
                   WHERE s.career_id=? AND tls.team_ea_id=?
               ) SELECT * FROM ranked WHERE rn=1 ORDER BY season_index""",
            (career_id, team_id),
        ).fetchall()
        merged: dict[int, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            index = int(item["season_index"])
            option = season_options.get(index, {})
            context = league_context(item.get("league_ea_id"), item.get("league_name"), item.get("league_level"), item.get("country_id"))
            is_current = max_snapshot_sequence is not None and int(item["import_sequence"]) == int(max_snapshot_sequence)
            raw_position = as_int(item.get("current_table_position"))
            reliable_final = (not is_current) or as_int(item.get("champion")) == 1
            final_position = raw_position if reliable_final and raw_position and raw_position > 0 else None
            current_position = None
            position_source = None
            position_source_label = None
            if is_current:
                current_position = raw_position if raw_position and raw_position > 0 else None
                if current_snapshot_id is not None:
                    calculated = self._current_league_position(conn, current_snapshot_id, team_id)
                    if calculated:
                        current_position = as_int(calculated.get("position"))
                        position_source = calculated.get("source")
                        position_source_label = calculated.get("source_label")
            merged[index] = {
                "season_index": index,
                "season_label": option.get("label") or self._season_label(index, season_start_from_date(item.get("career_date"))),
                "career_season_number": option.get("career_season_number"),
                "start_year": option.get("start_year"),
                "end_year": option.get("end_year"),
                **context,
                "final_position": final_position,
                "current_position": current_position,
                "result_status": "running" if is_current and final_position is None else "final" if final_position is not None else "incomplete",
                "is_current": is_current,
                "points": item.get("points"),
                "matches_played": item.get("matches_played"),
                "source": "snapshot_final" if final_position is not None else "snapshot_current",
                "source_label": "Imported",
                "source_snapshot_id": item.get("snapshot_id"),
                "position_source": position_source,
                "position_source_label": position_source_label,
                "confidence": "current_season" if is_current and final_position is None else "season_closed_by_later_snapshot" if final_position is not None else "league_observed",
            }

        legacy_manual_rows = conn.execute(
            """SELECT c.id,c.competition_object_id league_ea_id,c.competition_name league_name,
                      c.final_position,c.updated_at,s.season_index,s.label season_label,s.start_year,s.end_year
               FROM manual_competitions c JOIN manual_seasons s ON s.id=c.manual_season_id
               WHERE s.career_id=? AND s.managed_team_ea_id=?
                 AND c.competition_type='league' AND c.final_position IS NOT NULL
               ORDER BY s.start_year,c.sort_order,c.id""",
            (career_id, team_id),
        ).fetchall()
        for row in legacy_manual_rows:
            item = dict(row); index = int(item["season_index"]); context = league_context(item.get("league_ea_id"), item.get("league_name")); option = season_options.get(index, {})
            merged[index] = {
                "season_index": index, "season_label": item.get("season_label") or self._season_label(index, as_int(item.get("start_year"))),
                "career_season_number": option.get("career_season_number"), "start_year": item.get("start_year"), "end_year": item.get("end_year"),
                **context, "final_position": item.get("final_position"), "current_position": None, "result_status": "final", "is_current": False,
                "points": None, "matches_played": None, "source": "manual_competition", "source_label": "Manual",
                "manual_competition_id": item.get("id"), "updated_at": item.get("updated_at"), "confidence": "manual_entry",
            }
        manual_rows = conn.execute(
            """SELECT lf.*,s.season_index,s.label season_label,s.start_year,s.end_year
               FROM manual_league_finishes lf JOIN manual_seasons s ON s.id=lf.manual_season_id
               WHERE s.career_id=? AND lf.team_ea_id=? ORDER BY s.start_year""",
            (career_id, team_id),
        ).fetchall()
        for row in manual_rows:
            item = dict(row); index = int(item["season_index"]); context = league_context(item.get("league_ea_id"), item.get("league_name")); option = season_options.get(index, {})
            merged[index] = {
                "season_index": index, "season_label": item.get("season_label") or self._season_label(index, as_int(item.get("start_year"))),
                "career_season_number": option.get("career_season_number"), "start_year": item.get("start_year"), "end_year": item.get("end_year"),
                **context, "final_position": item.get("final_position"), "current_position": None, "result_status": "final", "is_current": False,
                "points": None, "matches_played": None, "source": "manual", "source_label": "Manual",
                "manual_id": item.get("id"), "updated_at": item.get("updated_at"), "confidence": "manual_entry",
            }
        result = sorted(merged.values(), key=lambda item: (as_int(item.get("start_year")) or 9999, int(item["season_index"])))
        previous = None
        for item in result:
            current_level = as_int(item.get("league_level")); previous_level = as_int(previous.get("league_level")) if previous else None
            if previous is None:
                movement, delta = "first", None
            elif current_level is None or previous_level is None:
                movement, delta = "unknown", None
            else:
                delta = previous_level - current_level
                movement = "promotion" if delta > 0 else "relegation" if delta < 0 else "same"
            item["movement"] = movement; item["level_change"] = delta
            item["position_display"] = (
                f"#{int(item['final_position'])}" if item.get("final_position") is not None
                else f"currently #{int(item['current_position'])}" if item.get("current_position") is not None
                else "in progress" if item.get("result_status") == "running" else "–"
            )
            previous = item
        return result

    @staticmethod
    def _indices_clause(indices: Iterable[int]) -> tuple[str, tuple[int, ...]]:
        values = tuple(int(value) for value in indices)
        if not values:
            return "NULL", ()
        return ",".join("?" for _ in values), values

    def _deep_squad_analysis(
        self, conn: Any, career_id: int, snapshots: list[Any], selected_options: list[dict[str, Any]]
    ) -> dict[str, Any]:
        selected_indices = [int(item["season_index"]) for item in selected_options]
        manual_season_map = {
            int(item["manual_season_id"]): int(item["season_index"])
            for item in selected_options if item.get("manual_season_id") is not None
        }
        latest = snapshots[-1] if snapshots else None
        current_players: list[dict[str, Any]] = []
        if latest is not None:
            rows = conn.execute(
                """SELECT p.ea_player_id,p.display_name,p.overall,p.potential,p.primary_position,p.raw_json
                   FROM roster_states r JOIN player_states p
                     ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                   WHERE r.snapshot_id=? AND r.team_ea_id=? ORDER BY p.overall DESC,p.display_name""",
                (latest["id"], latest["managed_team_ea_id"]),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["age"] = age_on_date(parse_raw(item.get("raw_json")).get("birthdate_raw"), latest["career_date"])
                item["position_group"] = self._position_group(item.get("primary_position"))
                current_players.append(item)

        group_order = ["Goalkeeper", "Defence", "Midfield", "Attack", "Unknown"]
        position_balance = []
        for group in group_order:
            items = [item for item in current_players if item["position_group"] == group]
            if not items:
                continue
            overalls = [as_int(item.get("overall")) for item in items if as_int(item.get("overall")) is not None]
            potentials = [as_int(item.get("potential")) for item in items if as_int(item.get("potential")) is not None]
            ages = [item.get("age") for item in items if item.get("age") is not None]
            position_balance.append({
                "group": group,
                "count": len(items),
                "average_overall": round(sum(overalls) / len(overalls), 1) if overalls else None,
                "average_potential": round(sum(potentials) / len(potentials), 1) if potentials else None,
                "average_age": round(sum(ages) / len(ages), 1) if ages else None,
            })

        age_band_specs = [
            ("U21", lambda age: age < 21),
            ("21–24", lambda age: 21 <= age <= 24),
            ("25–28", lambda age: 25 <= age <= 28),
            ("29–32", lambda age: 29 <= age <= 32),
            ("33+", lambda age: age >= 33),
        ]
        age_structure = []
        for label, predicate in age_band_specs:
            items = [item for item in current_players if item.get("age") is not None and predicate(int(item["age"]))]
            overalls = [as_int(item.get("overall")) for item in items if as_int(item.get("overall")) is not None]
            age_structure.append({
                "label": label, "count": len(items),
                "average_overall": round(sum(overalls) / len(overalls), 1) if overalls else None,
            })

        latest_by_season: dict[int, Any] = {}
        for snap in snapshots:
            latest_by_season[int(snap["season_index"])] = snap
        performance: dict[str, dict[str, Any]] = {}
        imported_keys: set[tuple[int, int, int]] = set()

        def add_performance(
            key: str, player_id: int | None, display_name: str, position: Any, overall: Any,
            appearances: Any, goals: Any, assists: Any, clean_sheets: Any, rating: Any, source: str
        ) -> None:
            entry = performance.setdefault(key, {
                "player_ea_id": player_id, "player_key": key, "display_name": display_name,
                "primary_position": position, "overall": as_int(overall), "appearances": 0,
                "goals": 0, "assists": 0, "clean_sheets": 0,
                "rating_weight": 0.0, "rating_appearances": 0, "sources": set(),
            })
            if not entry.get("primary_position") and position:
                entry["primary_position"] = position
            if entry.get("overall") is None and as_int(overall) is not None:
                entry["overall"] = as_int(overall)
            apps = max(0, as_int(appearances) or 0)
            entry["appearances"] += apps
            entry["goals"] += max(0, as_int(goals) or 0)
            entry["assists"] += max(0, as_int(assists) or 0)
            entry["clean_sheets"] += max(0, as_int(clean_sheets) or 0)
            rating_value = float(rating) if rating not in (None, "") else None
            if rating_value is not None and rating_value > 0 and apps > 0:
                entry["rating_weight"] += rating_value * apps
                entry["rating_appearances"] += apps
            entry["sources"].add(source)

        for season_index, snap in latest_by_season.items():
            rows = conn.execute(
                """SELECT ss.*,p.primary_position,p.overall
                   FROM season_stat_states ss
                   LEFT JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id
                   WHERE ss.snapshot_id=? AND ss.represented_team_ea_id=?""",
                (snap["id"], snap["managed_team_ea_id"]),
            ).fetchall()
            for row in rows:
                player_id = int(row["player_ea_id"])
                competition_id = int(row["competition_object_id"])
                imported_keys.add((season_index, player_id, competition_id))
                add_performance(
                    f"ea:{player_id}", player_id, row["display_name"] or f"Player {player_id}",
                    row["primary_position"], row["overall"], row["appearances"], row["goals"],
                    row["assists"], row["clean_sheets"], row["average_rating"], "imported",
                )

        if manual_season_map:
            manual_clause, manual_values = self._indices_clause(manual_season_map.keys())
            manual_rows = conn.execute(
                f"""SELECT ps.*,c.competition_object_id,ms.id manual_season_id,ms.season_index manual_season_index
                    FROM manual_player_stats ps
                    JOIN manual_competitions c ON c.id=ps.manual_competition_id
                    JOIN manual_seasons ms ON ms.id=c.manual_season_id
                    WHERE ms.career_id=? AND ms.id IN ({manual_clause})""",
                (career_id, *manual_values),
            ).fetchall()
            for row in manual_rows:
                player_id = as_int(row["player_ea_id"])
                competition_id = as_int(row["competition_object_id"])
                season_index = manual_season_map[int(row["manual_season_id"])]
                if player_id is not None and competition_id is not None and (season_index, player_id, competition_id) in imported_keys:
                    continue
                position = overall = None
                if player_id is not None:
                    context = conn.execute(
                        """SELECT primary_position,overall FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
                           WHERE s.career_id=? AND p.ea_player_id=? ORDER BY s.import_sequence DESC LIMIT 1""",
                        (career_id, player_id),
                    ).fetchone()
                    if context:
                        position, overall = context["primary_position"], context["overall"]
                key = f"ea:{player_id}" if player_id is not None else f"manual:{row['player_key']}"
                add_performance(
                    key, player_id, row["display_name"], position, overall, row["appearances"],
                    row["goals"], row["assists"], row["clean_sheets"], row["average_rating"], "manual",
                )

        if len(selected_indices) == 1:
            for item in current_players:
                key = f"ea:{int(item['ea_player_id'])}"
                performance.setdefault(key, {
                    "player_ea_id": int(item["ea_player_id"]), "player_key": key,
                    "display_name": item["display_name"], "primary_position": item.get("primary_position"),
                    "overall": as_int(item.get("overall")), "appearances": 0, "goals": 0,
                    "assists": 0, "clean_sheets": 0, "rating_weight": 0.0,
                    "rating_appearances": 0, "sources": set(),
                })

        player_context = {int(item["ea_player_id"]): item for item in current_players if item.get("ea_player_id") is not None}
        performance_rows = []
        for entry in performance.values():
            context = player_context.get(as_int(entry.get("player_ea_id")) or -1, {})
            entry["age"] = context.get("age")
            entry["potential"] = as_int(context.get("potential"))
            apps = int(entry["appearances"])
            rating_apps = int(entry.pop("rating_appearances"))
            rating_weight = float(entry.pop("rating_weight"))
            entry["average_rating"] = round(rating_weight / rating_apps, 2) if rating_apps else None
            entry["goal_contributions"] = int(entry["goals"]) + int(entry["assists"])
            entry["contributions_per_appearance"] = round(entry["goal_contributions"] / apps, 2) if apps else None
            entry["source"] = "mixed" if len(entry["sources"]) > 1 else next(iter(entry["sources"]), "none")
            entry.pop("sources", None)
            performance_rows.append(entry)
        performance_rows.sort(
            key=lambda item: (item["goal_contributions"], item["goals"], item["assists"], item["appearances"]),
            reverse=True,
        )
        max_appearances = max((int(item["appearances"]) for item in performance_rows), default=0)
        usage = {"Stammkern": 0, "Rotation": 0, "Squad option": 0, "No appearances": 0}
        for item in performance_rows:
            apps = int(item["appearances"])
            share = apps / max_appearances if max_appearances else 0
            category = "Stammkern" if share >= 0.75 else "Rotation" if share >= 0.4 else "Squad option" if apps > 0 else "No appearances"
            usage[category] += 1
            item["usage_category"] = category
            item["appearance_share"] = round(share * 100, 1) if max_appearances else 0
        appearance_distribution = [{"label": label, "count": usage[label]} for label in usage]

        ages = [int(item["age"]) for item in current_players if item.get("age") is not None]
        potentials = [as_int(item.get("potential")) for item in current_players if as_int(item.get("potential")) is not None]
        current_overalls = [as_int(item.get("overall")) for item in current_players if as_int(item.get("overall")) is not None]
        summary = {
            "squad_count": len(current_players),
            "average_overall": round(sum(current_overalls) / len(current_overalls), 1) if current_overalls else None,
            "average_potential": round(sum(potentials) / len(potentials), 1) if potentials else None,
            "average_age": round(sum(ages) / len(ages), 1) if ages else None,
            "youngest_age": min(ages) if ages else None,
            "oldest_age": max(ages) if ages else None,
            "under_21": sum(age < 21 for age in ages),
            "over_30": sum(age >= 30 for age in ages),
            "performance_player_count": len([item for item in performance_rows if item["appearances"] > 0]),
            "max_appearances": max_appearances,
        }
        return {
            "summary": summary,
            "positionBalance": position_balance,
            "ageStructure": age_structure,
            "appearanceDistribution": appearance_distribution,
            "performanceLeaders": performance_rows[:15],
            "_allPerformance": performance_rows,
            "usageDefinition": "Usage categories relative to the player with the most appearances in the selected period: core starter from 75%, rotation from 40%.",
            "snapshotId": latest["id"] if latest is not None else None,
        }

    def _season_comparison(
        self, conn: Any, career_id: int, options: list[dict[str, Any]], league_history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        history_by_index = {int(item["season_index"]): item for item in league_history}
        result: list[dict[str, Any]] = []
        for option in options:
            index = int(option["season_index"])
            season_snapshots = conn.execute(
                "SELECT * FROM snapshots WHERE career_id=? AND season_index=? ORDER BY import_sequence",
                (career_id, index),
            ).fetchall()
            latest = season_snapshots[-1] if season_snapshots else None
            match_rows = conn.execute(
                """WITH ranked AS (
                       SELECT fo.*,f.home_team_ea_id,f.away_team_ea_id,s.managed_team_ea_id,s.import_sequence,
                              ROW_NUMBER() OVER (PARTITION BY fo.fixture_id ORDER BY s.import_sequence DESC) rn
                       FROM fixture_observations fo
                       JOIN snapshots s ON s.id=fo.snapshot_id
                       JOIN fixtures f ON f.id=fo.fixture_id
                       WHERE s.career_id=? AND s.season_index=?
                   ) SELECT * FROM ranked WHERE rn=1 AND is_completed=1 AND managed_team_involved=1""",
                (career_id, index),
            ).fetchall()
            wins = draws = losses = goals_for = goals_against = 0
            for row in match_rows:
                code = str(row["managed_team_result"] or "")
                wins += code == "W"; draws += code == "D"; losses += code == "L"
                managed_id = as_int(row["managed_team_ea_id"]); home_id = as_int(row["home_team_ea_id"])
                home_score = as_int(row["home_score"]) or 0; away_score = as_int(row["away_score"]) or 0
                if managed_id is not None and managed_id == home_id:
                    goals_for += home_score; goals_against += away_score
                else:
                    goals_for += away_score; goals_against += home_score

            squad = self._deep_squad_analysis(conn, career_id, list(season_snapshots), [option])
            performance = squad.pop("_allPerformance", [])
            used = [item for item in performance if (as_int(item.get("appearances")) or 0) > 0]
            top_scorer = max(used, key=lambda item: (as_int(item.get("goals")) or 0, as_int(item.get("appearances")) or 0), default=None)

            team_id = as_int(option.get("managed_team_ea_id"))
            transfers = self._season_transfer_events(conn, career_id, index)
            loans = self._season_loan_events(conn, career_id, index)
            own_transfers = [event for event in transfers if team_id is not None and team_id in {as_int(event.get("from_team_ea_id")), as_int(event.get("to_team_ea_id"))}]
            own_loans = [event for event in loans if team_id is not None and team_id in {as_int(event.get("parent_team_ea_id")), as_int(event.get("loan_team_ea_id"))}]
            league = history_by_index.get(index, {})
            summary = squad.get("summary", {})
            result.append({
                "season_index": index,
                "season_label": option.get("label") or self._season_label(index),
                "career_season_number": option.get("career_season_number"),
                "is_current": bool(option.get("is_current")),
                "league_name": league.get("league_name"),
                "position_display": league.get("position_display"),
                "matches": len(match_rows), "wins": wins, "draws": draws, "losses": losses,
                "goals_for": goals_for, "goals_against": goals_against, "goal_difference": goals_for-goals_against,
                "players_used": len(used),
                "top_scorer_name": top_scorer.get("display_name") if top_scorer else None,
                "top_scorer_id": top_scorer.get("player_ea_id") if top_scorer else None,
                "top_scorer_goals": top_scorer.get("goals") if top_scorer else None,
                "average_overall": summary.get("average_overall"),
                "average_age": summary.get("average_age"),
                "squad_count": summary.get("squad_count"),
                "transfers": len(own_transfers), "loans": len(own_loans),
                "has_snapshots": bool(season_snapshots), "has_manual_data": bool(option.get("has_manual_data")),
            })
        return result

    def _season_report(
        self,
        performance_rows: list[dict[str, Any]],
        competitions: list[dict[str, Any]],
        transfers: list[dict[str, Any]],
        loans: list[dict[str, Any]],
        league_finish: dict[str, Any] | None,
        is_current: bool,
        completion: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a transparent, rule-based season report without generative text."""
        used = [row for row in performance_rows if (as_int(row.get("appearances")) or 0) > 0]
        max_apps = max((as_int(row.get("appearances")) or 0 for row in used), default=0)

        def award(label: str, row: dict[str, Any] | None, value: str, rule: str) -> dict[str, Any] | None:
            if row is None:
                return None
            return {
                "label": label,
                "player_ea_id": row.get("player_ea_id"),
                "display_name": row.get("display_name"),
                "primary_position": row.get("primary_position"),
                "value": value,
                "rule": rule,
                "media": self.state.media.player_media(as_int(row.get("player_ea_id"))) if as_int(row.get("player_ea_id")) is not None else None,
            }

        awards: list[dict[str, Any]] = []
        awards_available = bool(completion.get("complete"))
        if used and awards_available:
            eligible = [row for row in used if (as_int(row.get("appearances")) or 0) >= max(3, round(max_apps * .35))]
            player_of_season = max(eligible or used, key=lambda row: (
                float(row.get("average_rating") or 0) * 10
                + float(row.get("goal_contributions") or 0) * 1.5
                + float(row.get("appearance_share") or 0) * .08,
                as_int(row.get("appearances")) or 0,
            ))
            awards.extend(filter(None, [
                award("Player of the Season", player_of_season, f"{player_of_season.get('average_rating') or '–'} avg. rating · {as_int(player_of_season.get('goal_contributions')) or 0} goal contributions", "At least 35% of the maximum appearances; rating, goal contributions and usage share are combined."),
                award("Top scorer", max(used, key=lambda row: (as_int(row.get("goals")) or 0, as_int(row.get("appearances")) or 0)), f"{max(as_int(row.get('goals')) or 0 for row in used)} goals", "Most goals in the season period."),
                award("Assist leader", max(used, key=lambda row: (as_int(row.get("assists")) or 0, as_int(row.get("appearances")) or 0)), f"{max(as_int(row.get('assists')) or 0 for row in used)} assists", "Most assists in the season period."),
                award("Ever-present Player", max(used, key=lambda row: as_int(row.get("appearances")) or 0), f"{max_apps} appearances", "Most appearances across all competitions."),
            ]))
            talents = [row for row in used if as_int(row.get("age")) is not None and (as_int(row.get("age")) or 99) <= 21]
            if talents:
                talent = max(talents, key=lambda row: (as_int(row.get("appearances")) or 0, as_int(row.get("goal_contributions")) or 0, as_int(row.get("overall")) or 0))
                item = award("Young Player of the Season", talent, f"{as_int(talent.get('age'))} years · {as_int(talent.get('appearances')) or 0} appearances", "Best U21 player based on playing time, goal contributions and OVR.")
                if item:
                    awards.append(item)
            keepers = [row for row in used if str(row.get("primary_position") or "").upper() in {"GK", "TW"}]
            if keepers:
                keeper = max(keepers, key=lambda row: (as_int(row.get("clean_sheets")) or 0, float(row.get("average_rating") or 0), as_int(row.get("appearances")) or 0))
                item = award("Goalkeeper of the Season", keeper, f"{as_int(keeper.get('clean_sheets')) or 0} clean sheets", "Clean sheets, rating and appearances.")
                if item:
                    awards.append(item)

        return {
            "awards": awards,
            "awards_available": awards_available,
            "season_complete": awards_available,
            "completion": completion,
            "competition_count": len(competitions),
            "transfer_count": len([item for item in transfers if item.get("direction") != "Global"]),
            "loan_count": len([item for item in loans if item.get("direction") != "Global"]),
            "league_finish": league_finish,
            "is_current": is_current,
            "status_label": "Completed season report" if awards_available else "Ongoing season report",
            "method_note": (
                "Awards are assigned by rules only after the confirmed final match, using available season statistics. "
                "Missing competitions or legacy-season data may affect the result."
            ),
        }

    def _manual_season_report_data(
        self, conn: Any, career_id: int, season_option: dict[str, Any],
        performance_rows: list[dict[str, Any]], transfers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manual_id = as_int(season_option.get("manual_season_id"))
        awards: list[dict[str, Any]] = []
        note = None
        if manual_id is not None:
            rows = conn.execute(
                """SELECT a.*,t.from_team_name,t.to_team_name,t.fee,t.currency,t.transaction_date
                   FROM manual_season_awards a
                   LEFT JOIN manual_transactions t ON t.id=a.related_transaction_id
                   JOIN manual_seasons s ON s.id=a.manual_season_id
                   WHERE a.manual_season_id=? AND s.career_id=?
                   ORDER BY a.id""",
                (manual_id, career_id),
            ).fetchall()
            for row in rows:
                item = dict(row)
                pid = as_int(item.get("player_ea_id"))
                item["media"] = self.state.media.player_media(pid) if pid is not None else None
                item["source_label"] = "Manager award"
                awards.append(item)
            report_row = conn.execute(
                "SELECT summary_note FROM manual_season_reports WHERE manual_season_id=?",
                (manual_id,),
            ).fetchone()
            note = report_row["summary_note"] if report_row else None
        players = []
        seen: set[str] = set()
        for row in sorted(performance_rows, key=lambda item: (-(as_int(item.get("appearances")) or 0), str(item.get("display_name") or ""))):
            pid = as_int(row.get("player_ea_id"))
            key = f"ea:{pid}" if pid is not None else f"name:{str(row.get('display_name') or '').lower()}"
            if key in seen:
                continue
            seen.add(key)
            players.append({
                "player_ea_id": pid, "display_name": row.get("display_name"),
                "primary_position": row.get("primary_position"),
                "appearances": row.get("appearances"),
                "media": self.state.media.player_media(pid) if pid is not None else None,
            })
        transfer_options = []
        for item in transfers:
            if item.get("direction") == "Global":
                continue
            transfer_options.append({
                "id": item.get("manual_id") if item.get("source") == "manual" else None,
                "event_key": item.get("eventKey") or item.get("event_key"),
                "player_ea_id": item.get("player_ea_id"), "display_name": item.get("display_name"),
                "from_team_name": item.get("from_team_name"), "to_team_name": item.get("to_team_name"),
                "fee": item.get("fee"), "date": item.get("date") or item.get("transaction_date"),
                "source_label": item.get("source_label"),
            })
        return {
            "manualSeasonId": manual_id, "awards": awards, "summaryNote": note,
            "categories": [{"key": key, "label": label} for key, label in self.state.manual.AWARD_CATEGORIES.items()]
                + [{"key": "custom", "label": "Custom award"}],
            "players": players, "transfers": transfer_options,
        }

    @staticmethod
    def _record_catalog(
        match_rows: list[Any],
        performance_rows: list[dict[str, Any]],
        transfers: list[dict[str, Any]],
        period_label: str,
    ) -> dict[str, Any]:
        """Build data-strict player, match, streak and transfer records."""
        player_records: list[dict[str, Any]] = []
        match_records: list[dict[str, Any]] = []
        streak_records: list[dict[str, Any]] = []
        transfer_records: list[dict[str, Any]] = []
        position_records: list[dict[str, Any]] = []

        rows = [dict(item) for item in performance_rows]
        for item in rows:
            apps = as_int(item.get("appearances")) or 0
            goals = as_int(item.get("goals")) or 0
            assists = as_int(item.get("assists")) or 0
            item["goals_per_appearance"] = round(goals / apps, 3) if apps else None
            item["assists_per_appearance"] = round(assists / apps, 3) if apps else None
            if item.get("contributions_per_appearance") is None:
                item["contributions_per_appearance"] = round((goals + assists) / apps, 3) if apps else None

        def player_record(
            label: str, key: str, *, minimum_apps: int = 0, decimals: int = 0,
            value_type: str | None = None, pool: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any] | None:
            candidates = [
                item for item in (pool if pool is not None else rows)
                if (as_int(item.get("appearances")) or 0) >= minimum_apps and item.get(key) is not None
            ]
            if not candidates:
                return None
            best = max(candidates, key=lambda item: (float(item.get(key) or 0), as_int(item.get("appearances")) or 0))
            value = float(best.get(key) or 0)
            record = {
                "label": label,
                "value": round(value, decimals) if decimals else int(value),
                "value_type": value_type or ("rating" if key == "average_rating" else "number"),
                "player_ea_id": best.get("player_ea_id"),
                "display_name": best.get("display_name"),
                "primary_position": best.get("primary_position"),
                "appearances": best.get("appearances"),
                "source": best.get("source"),
            }
            if pool is None:
                player_records.append(record)
            return record

        max_apps = max((as_int(item.get("appearances")) or 0 for item in rows), default=0)
        rate_minimum = max(5, round(max_apps * .25)) if max_apps else 5
        player_record("Most appearances", "appearances")
        player_record("Most goals", "goals")
        player_record("Most assists", "assists")
        player_record("Most goal contributions", "goal_contributions")
        player_record("Most clean sheets", "clean_sheets")
        player_record("Best average rating", "average_rating", minimum_apps=max(3, round(max_apps * .25)), decimals=2)
        player_record("Best goals per appearance", "goals_per_appearance", minimum_apps=rate_minimum, decimals=2, value_type="rate")
        player_record("Best goal contributions per appearance", "contributions_per_appearance", minimum_apps=rate_minimum, decimals=2, value_type="rate")
        player_record("Highest OVR", "overall")
        player_record("Highest potential", "potential")

        for group in ("Goalkeeper", "Defence", "Midfield", "Attack"):
            group_rows = [item for item in rows if AnalysisQueryMixin._position_group(item.get("primary_position")) == group and (as_int(item.get("appearances")) or 0) > 0]
            if not group_rows:
                continue
            records = [
                player_record("Most appearances", "appearances", pool=group_rows),
                player_record("Most goal contributions", "goal_contributions", pool=group_rows),
                player_record("Best rating", "average_rating", minimum_apps=max(3, round(max((as_int(item.get("appearances")) or 0 for item in group_rows), default=0) * .25)), decimals=2, pool=group_rows),
            ]
            position_records.append({"group": group, "records": [item for item in records if item is not None]})

        matches = [dict(row) for row in match_rows]
        matches.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("time") or ""), str(row.get("fixture_key") or "")))
        enriched_matches = []
        for row in matches:
            managed_id = as_int(row.get("managed_team_ea_id"))
            home_id = as_int(row.get("home_team_ea_id"))
            is_home = managed_id is not None and home_id == managed_id
            scored = (as_int(row.get("home_score")) or 0) if is_home else (as_int(row.get("away_score")) or 0)
            conceded = (as_int(row.get("away_score")) or 0) if is_home else (as_int(row.get("home_score")) or 0)
            opponent = row.get("away_team_name") if is_home else row.get("home_team_name")
            enriched_matches.append({**row, "scored": scored, "conceded": conceded, "difference": scored-conceded, "opponent": opponent})
        if enriched_matches:
            def match_item(label: str, row: dict[str, Any], value: str) -> dict[str, Any]:
                return {
                    "label": label, "value": value, "value_type": "text", "fixture_id": row.get("fixture_id"),
                    "opponent": row.get("opponent"), "date": row.get("date"),
                    "competition_name": row.get("competition_name"),
                }
            wins = [row for row in enriched_matches if row["difference"] > 0]
            defeats = [row for row in enriched_matches if row["difference"] < 0]
            if wins:
                row = max(wins, key=lambda item: (item["difference"], item["scored"]))
                match_records.append(match_item("Biggest win", row, f"{row['scored']}:{row['conceded']}"))
            if defeats:
                row = min(defeats, key=lambda item: (item["difference"], -item["conceded"]))
                match_records.append(match_item("Biggest defeat", row, f"{row['scored']}:{row['conceded']}"))
            row = max(enriched_matches, key=lambda item: (item["scored"] + item["conceded"], item["scored"]))
            match_records.append(match_item("Highest-scoring match", row, f"{row['scored']}:{row['conceded']}"))

            def longest_streak(predicate: Any) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
                best = current = 0
                best_start = best_end = current_start = None
                for row in enriched_matches:
                    if predicate(row):
                        if current == 0:
                            current_start = row
                        current += 1
                        if current > best:
                            best, best_start, best_end = current, current_start, row
                    else:
                        current = 0
                        current_start = None
                return best, best_start, best_end
            for label, predicate in (
                ("Longest winning streak", lambda row: row["difference"] > 0),
                ("Longest unbeaten streak", lambda row: row["difference"] >= 0),
                ("Longest clean-sheet streak", lambda row: row["conceded"] == 0),
            ):
                count, streak_start, streak_end = longest_streak(predicate)
                if count:
                    streak_records.append({
                        "label": label, "value": count,
                        "start_date": streak_start.get("date") if streak_start else None,
                        "end_date": streak_end.get("date") if streak_end else None,
                    })

        own_transfers = [item for item in transfers if item.get("direction") in {"Incoming", "Outgoing"}]
        known_transfers = [item for item in own_transfers if item.get("fee") is not None]
        for direction, label in (("Incoming", "Highest fee paid"), ("Outgoing", "Highest fee received")):
            pool = [item for item in known_transfers if item.get("direction") == direction]
            if pool:
                best = max(pool, key=lambda item: as_int(item.get("fee")) or 0)
                transfer_records.append({
                    "label": label, "value": as_int(best.get("fee")), "value_type": "money",
                    "player_ea_id": best.get("player_ea_id"), "display_name": best.get("display_name"),
                    "date": best.get("date") or best.get("transaction_date"), "source": best.get("source_label") or best.get("source"),
                })
        spending = sum(as_int(item.get("fee")) or 0 for item in known_transfers if item.get("direction") == "Incoming")
        income = sum(as_int(item.get("fee")) or 0 for item in known_transfers if item.get("direction") == "Outgoing")
        if known_transfers:
            transfer_records.extend([
                {"label": "Known transfer spending", "value": spending, "value_type": "money"},
                {"label": "Known transfer income", "value": income, "value_type": "money"},
                {"label": "Known transfer balance", "value": income - spending, "value_type": "money"},
            ])

        unknown_fees = sum(item.get("fee") is None for item in own_transfers)
        notes = [
            "Records use only imported or manual data available in the selected period.",
            "Incomplete historical seasons may therefore produce provisional records.",
            f"Rate records require at least {rate_minimum} appearances in the selected period.",
        ]
        if unknown_fees:
            notes.append(f"{unknown_fees} transfer(s) with unknown fees are excluded from expenses, income and balance.")
        return {
            "periodLabel": period_label,
            "playerRecords": player_records,
            "positionRecords": position_records,
            "matchRecords": match_records,
            "streakRecords": streak_records,
            "transferRecords": transfer_records,
            "notes": notes,
        }

    def _analysis(self, career_id: int, snapshot_id: int, requested_season: int | None = None) -> dict[str, Any]:
        with self.state.database.connect() as conn:
            snapshot = self._snapshot(conn, snapshot_id)
            if int(snapshot["career_id"]) != int(career_id):
                raise ValueError("Snapshot does not belong to the selected career.")
            options = self._season_options(conn, career_id)
            if requested_season == -1:
                selected_indices = [int(item["season_index"]) for item in options]
                selected_label = "All seasons"
                selected_option = None
            else:
                selected_index, _, selected_option = self._season_context(conn, snapshot, requested_season)
                selected_indices = [selected_index]
                selected_label = str(selected_option.get("label") or self._season_label(selected_index))
            selected_options = [item for item in options if int(item["season_index"]) in selected_indices]
            manual_season_ids = [int(item["manual_season_id"]) for item in selected_options if item.get("manual_season_id") is not None]
            clause, values = self._indices_clause(selected_indices)
            snapshots = conn.execute(
                f"SELECT * FROM snapshots WHERE career_id=? AND season_index IN ({clause}) ORDER BY import_sequence",
                (career_id, *values),
            ).fetchall() if values else []
            latest = snapshots[-1] if snapshots else snapshot

            match_rows = conn.execute(
                f"""WITH ranked AS (
                       SELECT fo.*,f.id fixture_id,f.home_team_ea_id,f.away_team_ea_id,s.managed_team_ea_id,
                              s.season_index,s.import_sequence,
                              ROW_NUMBER() OVER (PARTITION BY fo.fixture_id ORDER BY s.import_sequence DESC) rn
                       FROM fixture_observations fo
                       JOIN snapshots s ON s.id=fo.snapshot_id
                       JOIN fixtures f ON f.id=fo.fixture_id
                       WHERE s.career_id=? AND s.season_index IN ({clause})
                   ) SELECT * FROM ranked WHERE rn=1 AND is_completed=1 AND managed_team_involved=1""",
                (career_id, *values),
            ).fetchall() if values else []
            wins = draws = losses = goals_for = goals_against = 0
            for row in match_rows:
                result = str(row["managed_team_result"] or "")
                wins += result == "W"
                draws += result == "D"
                losses += result == "L"
                managed_id = as_int(row["managed_team_ea_id"])
                home = as_int(row["home_team_ea_id"])
                hs = as_int(row["home_score"]) or 0
                aw = as_int(row["away_score"]) or 0
                if managed_id is not None and home == managed_id:
                    goals_for += hs; goals_against += aw
                else:
                    goals_for += aw; goals_against += hs

            managed_team_id = as_int(latest["managed_team_ea_id"])
            match_intelligence = detailed_analysis(conn, career_id, selected_indices, managed_team_id)
            league_history = self._league_history(conn, career_id, managed_team_id, int(latest["id"])) if managed_team_id is not None else []
            selected_history = [row for row in league_history if int(row["season_index"]) in selected_indices]
            levels = [as_int(row.get("league_level")) for row in selected_history]
            levels = [level for level in levels if level is not None and level > 0]
            highest_level = min(levels) if levels else None
            highest_rows = [row for row in selected_history if as_int(row.get("league_level")) == highest_level] if highest_level is not None else []
            best_highest = min(
                (int(row["final_position"]) for row in highest_rows if row.get("final_position") is not None),
                default=None,
            )
            best_row = next((row for row in highest_rows if as_int(row.get("final_position")) == best_highest), None)
            representative_row = best_row or (highest_rows[-1] if highest_rows else None)
            league_context = {
                "mode": "highest_reached",
                "league_level": highest_level,
                "league_name": representative_row.get("league_name") if representative_row else None,
                "position": best_highest,
                "season_label": best_row.get("season_label") if best_row else None,
                "source": representative_row.get("source") if representative_row else None,
            }
            if len(selected_indices) == 1 and selected_option and selected_option.get("is_current") and managed_team_id is not None:
                current_position = self._current_league_position(conn, int(latest["id"]), managed_team_id)
                if current_position:
                    league_row = conn.execute(
                        "SELECT league_ea_id,league_name FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
                        (latest["id"], managed_team_id),
                    ).fetchone()
                    league_context = {
                        "mode": "current",
                        "league_level": None,
                        "league_name": self._display_competition_name(
                            conn,
                            (league_row["league_name"] if league_row else None) or current_position.get("competition_name"),
                            career_id=career_id,
                            competition_object_id=as_int(current_position.get("competition_object_id")),
                            static_competition_id=as_int(league_row["league_ea_id"]) if league_row else None,
                        ),
                        "position": current_position.get("position"),
                        "season_label": selected_option.get("label"),
                        "source": current_position.get("source"),
                        "source_label": current_position.get("source_label"),
                    }

            all_transfers: list[dict[str, Any]] = []
            all_loans: list[dict[str, Any]] = []
            transfer_activity: list[dict[str, Any]] = []
            option_by_index = {int(item["season_index"]): item for item in options}
            for index in selected_indices:
                transfers = self._season_transfer_events(conn, career_id, index)
                loans = self._season_loan_events(conn, career_id, index)
                season_team_id = as_int(option_by_index.get(index, {}).get("managed_team_ea_id"))
                for event in transfers:
                    event["direction"] = (
                        "Incoming" if season_team_id is not None and as_int(event.get("to_team_ea_id")) == season_team_id
                        else "Outgoing" if season_team_id is not None and as_int(event.get("from_team_ea_id")) == season_team_id
                        else "Global"
                    )
                for event in loans:
                    event["direction"] = (
                        "Loan in" if season_team_id is not None and as_int(event.get("loan_team_ea_id")) == season_team_id
                        else "Loan out" if season_team_id is not None and as_int(event.get("parent_team_ea_id")) == season_team_id
                        else "Global"
                    )
                all_transfers.extend(transfers)
                all_loans.extend(loans)
                own_t = [event for event in transfers if event.get("direction") != "Global"]
                own_l = [event for event in loans if event.get("direction") != "Global"]
                transfer_activity.append({
                    "season_index": index,
                    "season_label": option_by_index.get(index, {}).get("label") or self._season_label(index),
                    "incoming": sum(event.get("direction") == "Incoming" for event in own_t),
                    "outgoing": sum(event.get("direction") == "Outgoing" for event in own_t),
                    "loans_in": sum(event.get("direction") == "Loan in" for event in own_l),
                    "loans_out": sum(event.get("direction") == "Loan out" for event in own_l),
                    "known_income": sum(as_int(event.get("fee")) or 0 for event in own_t if event.get("direction") == "Outgoing"),
                    "known_spending": sum(as_int(event.get("fee")) or 0 for event in own_t if event.get("direction") == "Incoming"),
                    "unknown_fees": sum(event.get("fee") is None for event in own_t),
                })

            imported_players = conn.execute(
                f"""SELECT COUNT(DISTINCT ss.player_ea_id)
                    FROM season_stat_states ss JOIN snapshots s ON s.id=ss.snapshot_id
                    WHERE s.career_id=? AND s.season_index IN ({clause})
                      AND ss.represented_team_ea_id=s.managed_team_ea_id AND COALESCE(ss.appearances,0)>0""",
                (career_id, *values),
            ).fetchone()[0] if values else 0
            manual_clause, manual_values = self._indices_clause(manual_season_ids)
            manual_players = conn.execute(
                f"""SELECT COUNT(DISTINCT ps.player_key)
                    FROM manual_player_stats ps JOIN manual_competitions c ON c.id=ps.manual_competition_id
                    JOIN manual_seasons ms ON ms.id=c.manual_season_id
                    WHERE ms.career_id=? AND ms.id IN ({manual_clause}) AND COALESCE(ps.appearances,0)>0""",
                (career_id, *manual_values),
            ).fetchone()[0] if manual_values else 0

            title_rows = conn.execute(
                f"""WITH ranked AS (
                       SELECT cps.*,s.season_index,s.import_sequence,
                              ROW_NUMBER() OVER (PARTITION BY s.season_index,cps.competition_object_id,cps.team_ea_id ORDER BY s.import_sequence DESC) rn
                       FROM competition_progress_states cps JOIN snapshots s ON s.id=cps.snapshot_id
                       WHERE s.career_id=? AND s.season_index IN ({clause}) AND cps.team_ea_id=s.managed_team_ea_id
                   ) SELECT COUNT(*) FROM ranked WHERE rn=1 AND has_team_won=1""",
                (career_id, *values),
            ).fetchone()[0] if values else 0

            squad_trend: list[dict[str, Any]] = []
            for snap in snapshots:
                player_rows = conn.execute(
                    """SELECT p.overall,p.raw_json FROM roster_states r JOIN player_states p
                       ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                       WHERE r.snapshot_id=? AND r.team_ea_id=?""",
                    (snap["id"], snap["managed_team_ea_id"]),
                ).fetchall()
                overalls = [as_int(row["overall"]) for row in player_rows if as_int(row["overall"]) is not None]
                ages = []
                for row in player_rows:
                    raw = parse_raw(row["raw_json"])
                    age = age_on_date(raw.get("birthdate_raw"), snap["career_date"])
                    if age is not None:
                        ages.append(age)
                squad_trend.append({
                    "snapshot_id": snap["id"],
                    "career_date": snap["career_date"],
                    "season_index": snap["season_index"],
                    "average_overall": round(sum(overalls) / len(overalls), 2) if overalls else None,
                    "average_age": round(sum(ages) / len(ages), 2) if ages else None,
                    "squad_count": len(player_rows),
                })

            current_squad = squad_trend[-1] if squad_trend else {"squad_count": 0, "average_overall": None, "average_age": None}
            competitions: list[dict[str, Any]] = []
            leaders: list[dict[str, Any]] = []
            if len(selected_indices) == 1:
                index = selected_indices[0]
                latest_season_snapshot = conn.execute(
                    """SELECT * FROM snapshots WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC LIMIT 1""",
                    (career_id, index),
                ).fetchone()
                if latest_season_snapshot:
                    competitions = rows_to_dicts(conn.execute(
                        """SELECT f.competition_object_id,MAX(fo.competition_name) competition_name,COUNT(*) matches,
                                  SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed
                           FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                           WHERE fo.snapshot_id=? AND fo.managed_team_involved=1
                           GROUP BY f.competition_object_id ORDER BY competition_name""",
                        (latest_season_snapshot["id"],),
                    ).fetchall())
                    leaders = rows_to_dicts(conn.execute(
                        """SELECT player_ea_id,MAX(display_name) display_name,SUM(COALESCE(appearances,0)) appearances,
                                  SUM(COALESCE(goals,0)) goals,SUM(COALESCE(assists,0)) assists,
                                  CASE WHEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)>0
                                       THEN SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN average_rating*appearances ELSE 0 END)
                                          / SUM(CASE WHEN average_rating>0 AND COALESCE(appearances,0)>0 THEN appearances ELSE 0 END)
                                  END average_rating
                           FROM season_stat_states WHERE snapshot_id=? AND represented_team_ea_id=?
                           GROUP BY player_ea_id ORDER BY goals DESC,assists DESC LIMIT 10""",
                        (latest_season_snapshot["id"], latest_season_snapshot["managed_team_ea_id"]),
                    ).fetchall())
                selected_manual_id = as_int(selected_options[0].get("manual_season_id")) if selected_options else None
                manual_competitions = conn.execute(
                    """SELECT c.competition_object_id,c.competition_name,0 matches,0 completed,c.final_position,c.result_text,'manual' source
                       FROM manual_competitions c JOIN manual_seasons ms ON ms.id=c.manual_season_id
                       WHERE ms.career_id=? AND ms.id=? ORDER BY c.sort_order,c.id""",
                    (career_id, selected_manual_id),
                ).fetchall() if selected_manual_id is not None else []
                known_names = {str(item.get("competition_name") or "").lower() for item in competitions}
                for row in manual_competitions:
                    item = dict(row)
                    if str(item.get("competition_name") or "").lower() not in known_names:
                        competitions.append(item)

            deep_squad = self._deep_squad_analysis(conn, career_id, list(snapshots), selected_options)
            all_performance = deep_squad.pop("_allPerformance", [])
            records = self._record_catalog(list(match_rows), all_performance, all_transfers, selected_label)
            season_comparison = self._season_comparison(conn, career_id, options, league_history)

            unknown_fees = sum(event.get("fee") is None for event in all_transfers if event.get("direction") != "Global")
            quality_items = [
                {"level": "good" if snapshots else "warn", "label": f"{len(snapshots)} snapshot states in the selected range"},
                {"level": "good" if selected_history else "warn", "label": f"{len(selected_history)} reliable league position record(s)"},
                {"level": "warn" if unknown_fees else "good", "label": f"{unknown_fees} managed-club transfers with unknown fees" if unknown_fees else "Known transfer fees are fully recorded"},
                {"level": "good" if match_rows else "warn", "label": f"{len(match_rows)} completed matches available for analysis"},
            ]
            if requested_season != -1 and selected_option and selected_option.get("is_current"):
                quality_items.append({"level": "info", "label": "Current season is not yet marked as complete"})
            season_report = None
            if len(selected_indices) == 1:
                report_league = selected_history[-1] if selected_history else None
                if selected_option and selected_option.get("is_current") and league_context.get("mode") == "current":
                    base = dict(report_league or {})
                    base.update({
                        "league_name": league_context.get("league_name"),
                        "current_position": league_context.get("position"),
                        "final_position": None,
                        "position_display": f"currently #{int(league_context['position'])}" if league_context.get("position") is not None else "in progress",
                        "position_source": league_context.get("source"),
                        "position_source_label": league_context.get("source_label"),
                        "result_status": "running",
                    })
                    report_league = base
                completion = self._season_completion(conn, career_id, selected_option)
                season_report = self._season_report(
                    all_performance, competitions, all_transfers, all_loans,
                    report_league, bool(selected_option and selected_option.get("is_current")), completion,
                )
                manual_report = self._manual_season_report_data(
                    conn, career_id, selected_option or {}, all_performance, all_transfers
                )
                if not bool(completion.get("complete")):
                    manual_report["lockedAwardCount"] = len(manual_report.get("awards") or [])
                    manual_report["awards"] = []
                season_report["manual"] = manual_report
                season_report["records"] = records
                season_report["squadAnalysis"] = deep_squad

        return {
            "careerId": career_id,
            "snapshotId": snapshot_id,
            "seasonOptions": options,
            "selectedSeasonIndex": -1 if requested_season == -1 else selected_indices[0],
            "selectedSeasonLabel": selected_label,
            "metrics": {
                "seasons": len(selected_indices),
                "matches": len(match_rows),
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "best_league_finish": best_highest,
                "league_context": league_context,
                "titles": int(title_rows or 0),
                "players_used": max(int(imported_players or 0), int(manual_players or 0)),
                "transfers": sum(event.get("direction") != "Global" for event in all_transfers),
                "loans": sum(event.get("direction") != "Global" for event in all_loans),
                "squad_count": current_squad.get("squad_count"),
                "average_overall": current_squad.get("average_overall"),
                "average_age": current_squad.get("average_age"),
            },
            "leagueHistory": league_history,
            "squadTrend": squad_trend,
            "transferActivity": transfer_activity,
            "squadAnalysis": deep_squad,
            "records": records,
            "seasonComparison": season_comparison,
            "matchIntelligence": match_intelligence,
            "seasonReport": season_report,
            "seasonOverview": {
                "competitions": competitions,
                "leaders": leaders,
                "transfers": all_transfers,
                "loans": all_loans,
                "leagueFinish": season_report.get("league_finish") if season_report else (selected_history[-1] if selected_history else None),
            },
            "quality": {"items": quality_items, "unknownTransferFees": unknown_fees},
        }
