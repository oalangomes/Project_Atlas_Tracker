from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .media_utils import competition_name_key, season_start_from_date
from .positions import broad_position_group
from .team_strength import live_squad_strength
from .server_utils import (
    age_on_date, aggregate_standings, annotate_knockout_progress, as_int, clean_raw,
    competition_format_info, contract_role_label, fixture_group_value, parse_fc_date,
    parse_raw, player_age_data, rows_to_dicts, subtract_months, youth_potential_range,
)
from .match_stats import (
    reconstructed_player_matches, detailed_player_matches, detailed_player_season_history,
    detailed_player_season_summary,
)

def _static_asset_version(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return "missing"


class EntityQueryMixin:
    @staticmethod
    def _player_position_group(position: Any) -> str:
        return {"GK": "goalkeeper", "DEF": "defence", "MID": "midfield", "ATT": "attack"}[
            broad_position_group(position)
        ]

    @staticmethod
    def _attribute_average(raw: dict[str, Any], fields: list[str]) -> float | None:
        values: list[float] = []
        for field in fields:
            value = raw.get(field)
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 99:
                values.append(number)
        return round(sum(values) / len(values), 1) if values else None

    def _player_analysis(
        self,
        conn: sqlite3.Connection,
        snapshot: Any,
        player: dict[str, Any],
        growth: Any,
        totals: dict[str, Any],
    ) -> dict[str, Any]:
        player_raw = player.get("raw", {}) if isinstance(player.get("raw"), dict) else {}
        growth_raw = parse_raw(growth["raw_json"]) if growth is not None and growth["raw_json"] else {}
        raw = {**growth_raw, **player_raw}
        group = self._player_position_group(player.get("primary_position"))

        if group == "goalkeeper":
            category_fields = {
                "Reflexe": ["gk_diving", "gk_reflexes", "reactions"],
                "Fangsicherheit": ["gk_handling", "gk_positioning"],
                "Distribution": ["gk_kicking", "short_passing", "long_passing", "vision"],
                "Athletik": ["jumping", "strength", "agility", "acceleration"],
                "Ruhe": ["composure", "balance", "reactions"],
                "Pace": ["acceleration", "sprint_speed"],
            }
            role_fields = {
                "Linienkeeper": ["gk_reflexes", "gk_diving", "reactions", "gk_positioning"],
                "Mitspielender Torwart": ["gk_kicking", "short_passing", "long_passing", "vision", "composure"],
                "Cross claiming": ["gk_handling", "gk_positioning", "jumping", "strength"],
            }
        elif group == "defence":
            category_fields = {
                "Pace": ["acceleration", "sprint_speed"],
                "Technik": ["ball_control", "dribbling", "agility", "balance"],
                "Passspiel": ["short_passing", "long_passing", "vision", "crossing"],
                "Defensive": ["interceptions", "defensive_awareness", "standing_tackle", "sliding_tackle"],
                "Kopfball": ["heading_accuracy", "jumping", "strength"],
                "Physis": ["strength", "stamina", "aggression", "balance"],
            }
            role_fields = {
                "Ball winner": ["defensive_awareness", "standing_tackle", "sliding_tackle", "aggression", "strength"],
                "Spielaufbauer": ["short_passing", "long_passing", "vision", "composure", "ball_control"],
                "Tackler": ["standing_tackle", "interceptions", "strength", "aggression", "reactions"],
                "Wide player": ["acceleration", "sprint_speed", "stamina", "crossing", "dribbling"],
            }
        elif group == "midfield":
            category_fields = {
                "Pace": ["acceleration", "sprint_speed"],
                "Technik": ["ball_control", "dribbling", "agility", "balance"],
                "Passspiel": ["short_passing", "long_passing", "vision", "curve"],
                "Finishing": ["finishing", "shot_power", "long_shots", "positioning"],
                "Defensive": ["interceptions", "defensive_awareness", "standing_tackle", "aggression"],
                "Physis": ["strength", "stamina", "jumping", "balance"],
            }
            role_fields = {
                "Spielmacher": ["vision", "short_passing", "long_passing", "ball_control", "composure"],
                "Box-to-Box": ["stamina", "reactions", "short_passing", "positioning", "standing_tackle", "finishing"],
                "Ballgewinner": ["interceptions", "standing_tackle", "aggression", "stamina", "defensive_awareness"],
                "Offensivmotor": ["dribbling", "vision", "positioning", "finishing", "acceleration"],
            }
        else:
            category_fields = {
                "Pace": ["acceleration", "sprint_speed"],
                "Technik": ["ball_control", "dribbling", "agility", "balance"],
                "Passspiel": ["short_passing", "vision", "crossing", "curve"],
                "Finishing": ["finishing", "shot_power", "long_shots", "volleys", "positioning"],
                "Kopfball": ["heading_accuracy", "jumping", "strength"],
                "Physis": ["strength", "stamina", "aggression", "balance"],
            }
            role_fields = {
                "Finisher": ["finishing", "positioning", "reactions", "shot_power", "volleys"],
                "Runs in behind": ["acceleration", "sprint_speed", "positioning", "finishing", "agility"],
                "Zielspieler": ["strength", "heading_accuracy", "jumping", "ball_control", "shot_power"],
                "Mitspielender Angreifer": ["short_passing", "vision", "ball_control", "dribbling", "composure"],
            }

        categories = [
            {"label": label, "value": self._attribute_average(raw, fields)}
            for label, fields in category_fields.items()
        ]
        categories = [item for item in categories if item["value"] is not None]
        roles = [
            {"label": label, "score": self._attribute_average(raw, fields)}
            for label, fields in role_fields.items()
        ]
        roles = sorted((item for item in roles if item["score"] is not None), key=lambda item: item["score"], reverse=True)
        ranked_categories = sorted(categories, key=lambda item: item["value"], reverse=True)

        player_id = as_int(player.get("ea_player_id"))
        player_team_id = as_int(player.get("team_ea_id"))
        player_position = str(player.get("primary_position") or "").strip().upper()
        team_row = conn.execute(
            "SELECT league_ea_id,league_name FROM team_states WHERE snapshot_id=? AND ea_team_id=?",
            (snapshot["id"], player_team_id),
        ).fetchone() if player_team_id is not None else None
        league_id = as_int(team_row["league_ea_id"]) if team_row is not None else None

        club_rows = conn.execute(
            """SELECT ea_player_id,team_ea_id,overall,potential,primary_position,height,weight,raw_json
               FROM player_states WHERE snapshot_id=? AND team_ea_id=?""",
            (snapshot["id"], player_team_id),
        ).fetchall() if player_team_id is not None else []
        league_rows = conn.execute(
            """SELECT p.ea_player_id,p.team_ea_id,p.overall,p.potential,p.primary_position,p.height,p.weight,p.raw_json
               FROM player_states p
               JOIN team_states t ON t.snapshot_id=p.snapshot_id AND t.ea_team_id=p.team_ea_id
               WHERE p.snapshot_id=? AND t.league_ea_id=?""",
            (snapshot["id"], league_id),
        ).fetchall() if league_id is not None else []

        def filter_peers(rows: Any, mode: str) -> list[dict[str, Any]]:
            result = [dict(row) for row in rows]
            if mode == "position":
                return [row for row in result if str(row.get("primary_position") or "").strip().upper() == player_position]
            return [row for row in result if self._player_position_group(row.get("primary_position")) == group]

        overall = as_int(player.get("overall"))
        potential = as_int(player.get("potential"))

        def comparison_for(rows: Any, scope: str, mode: str) -> dict[str, Any]:
            peers = filter_peers(rows, mode)

            def rank_for(field: str, value: int | None) -> int | None:
                if value is None:
                    return None
                better = sum(1 for row in peers if (as_int(row.get(field)) or -1) > value)
                return better + 1

            def peer_average(field: str) -> float | None:
                values = [value for row in peers if (value := as_int(row.get(field))) is not None]
                return round(sum(values) / len(values), 1) if values else None

            category_comparisons = []
            for category in categories:
                fields = category_fields.get(str(category.get("label")), [])
                peer_values = []
                for peer in peers:
                    peer_raw = parse_raw(peer.get("raw_json"))
                    value = self._attribute_average(peer_raw, fields)
                    if value is not None:
                        peer_values.append(float(value))
                own_value = float(category.get("value") or 0)
                percentile = round(100 * sum(value <= own_value for value in peer_values) / len(peer_values)) if peer_values else None
                category_comparisons.append({
                    "label": category.get("label"), "value": category.get("value"),
                    "peer_average": round(sum(peer_values) / len(peer_values), 1) if peer_values else None,
                    "peer_best": round(max(peer_values), 1) if peer_values else None,
                    "percentile": percentile, "peer_count": len(peer_values),
                })
            mode_label = f"Position {player_position or 'unknown'}" if mode == "position" else {"goalkeeper": "Goalkeeper", "defence": "Defence", "midfield": "Midfield", "attack": "Attack"}[group]
            scope_label = "At club" if scope == "club" else (team_row["league_name"] if team_row is not None and team_row["league_name"] else "Ligaweit")
            return {
                "scope": scope,
                "scope_label": scope_label,
                "mode": mode,
                "mode_label": mode_label,
                "peer_count": len(peers),
                "overall_rank": rank_for("overall", overall),
                "potential_rank": rank_for("potential", potential),
                "average_peer_overall": peer_average("overall"),
                "average_peer_potential": peer_average("potential"),
                "average_peer_height": peer_average("height"),
                "average_peer_weight": peer_average("weight"),
                "categoryComparisons": category_comparisons,
            }

        comparisons = {
            "club": {
                "group": comparison_for(club_rows, "club", "group"),
                "position": comparison_for(club_rows, "club", "position"),
            },
            "league": {
                "group": comparison_for(league_rows, "league", "group"),
                "position": comparison_for(league_rows, "league", "position"),
            },
        }
        default_comparison = comparisons["club"]["group"]

        appearances = as_int(totals.get("appearances")) or 0
        goals = as_int(totals.get("goals")) or 0
        assists = as_int(totals.get("assists")) or 0
        clean_sheets = as_int(totals.get("clean_sheets")) or 0
        performance = {
            "appearances": appearances,
            "goals": goals,
            "assists": assists,
            "clean_sheets": clean_sheets,
            "average_rating": totals.get("average_rating"),
            "goals_per_game": round(goals / appearances, 2) if appearances else None,
            "assists_per_game": round(assists / appearances, 2) if appearances else None,
            "contributions_per_game": round((goals + assists) / appearances, 2) if appearances else None,
        }
        expected_fields = sorted({field for fields in category_fields.values() for field in fields})
        available_count = sum(1 for field in expected_fields if self._attribute_average(raw, [field]) is not None)
        return {
            "position_group": group,
            "position_group_label": {"goalkeeper": "Goalkeeper", "defence": "Defence", "midfield": "Midfield", "attack": "Attack"}[group],
            "primary_position": player_position,
            "league_ea_id": league_id,
            "league_name": team_row["league_name"] if team_row is not None else None,
            "categories": categories,
            "categoryComparisons": default_comparison["categoryComparisons"],
            "comparisons": comparisons,
            "roles": roles,
            "strengths": ranked_categories[:3],
            "developmentAreas": list(reversed(ranked_categories[-2:])) if len(ranked_categories) >= 2 else [],
            "comparison": default_comparison,
            "physical": {"height": as_int(player.get("height")), "weight": as_int(player.get("weight"))},
            "performance": performance,
            "dataQuality": {
                "available_attributes": available_count,
                "expected_attributes": len(expected_fields),
                "coverage": round(available_count / len(expected_fields) * 100, 1) if expected_fields else 0,
                "is_rule_based": True,
            },
            "player_ea_id": player_id,
        }

    def _player_career_path(
        self, conn: Any, career_id: int, player_id: int, development_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build a conservative club/season chronology from immutable snapshots and movement overlays."""
        stations: dict[tuple[int | None, int | None, str], dict[str, Any]] = {}
        for point in development_history:
            team_id = as_int(point.get("team_ea_id"))
            team_name = str(point.get("team_name") or (f"Team {team_id}" if team_id is not None else "Unknown club"))
            start_year = as_int(point.get("season_start_year"))
            key = (start_year, team_id, team_name.casefold())
            current = stations.get(key)
            stamp = str(point.get("effective_date") or point.get("career_date") or "")
            candidate = {
                "season_start_year": start_year,
                "season_label": point.get("season_label") or (f"{start_year}/{str(start_year + 1)[-2:]}" if start_year is not None else "Unknown season"),
                "career_season_number": point.get("career_season_number"),
                "team_ea_id": team_id,
                "team_name": team_name,
                "first_date": stamp or None,
                "last_date": stamp or None,
                "overall": as_int(point.get("overall")),
                "potential": as_int(point.get("potential")),
                "market_value": point.get("market_value"),
                "market_value_hint": (point.get("financial") or {}).get("market_value", {}).get("label"),
                "source": point.get("source"),
            }
            if current is None:
                stations[key] = candidate
            else:
                if stamp and (not current.get("first_date") or stamp < str(current.get("first_date"))):
                    current["first_date"] = stamp
                if stamp and (not current.get("last_date") or stamp >= str(current.get("last_date"))):
                    current.update({
                        "last_date": stamp,
                        "overall": candidate["overall"],
                        "potential": candidate["potential"],
                        "market_value": candidate["market_value"],
                        "market_value_hint": candidate["market_value_hint"],
                        "source": candidate["source"],
                    })

        market_points = [
            point for point in development_history
            if point.get("market_value") is not None and (point.get("effective_date") or point.get("career_date"))
        ]

        def market_at(event_date: Any) -> tuple[Any, str | None]:
            target_text = parse_fc_date(event_date)
            if target_text is None or not market_points:
                return None, None
            target = date.fromisoformat(target_text)
            ranked: list[tuple[int, dict[str, Any]]] = []
            for point in market_points:
                observed_text = parse_fc_date(point.get("effective_date") or point.get("career_date"))
                if observed_text is None:
                    continue
                observed = date.fromisoformat(observed_text)
                ranked.append((abs((observed - target).days), point))
            if not ranked:
                return None, None
            closest = min(ranked, key=lambda item: item[0])[1]
            return closest.get("market_value"), str(closest.get("effective_date") or closest.get("career_date") or "") or None

        movements: list[dict[str, Any]] = []
        seen: set[str] = set()
        for option in self._season_options(conn, career_id):
            season_index = int(option["season_index"])
            for event_type, events in (
                ("transfer", self._season_transfer_events(conn, career_id, season_index)),
                ("loan", self._season_loan_events(conn, career_id, season_index)),
            ):
                for event in events:
                    if as_int(event.get("player_ea_id")) != player_id:
                        continue
                    if event_type == "loan":
                        from_id, from_name = as_int(event.get("parent_team_ea_id")), event.get("parent_team_name")
                        to_id, to_name = as_int(event.get("loan_team_ea_id")), event.get("loan_team_name")
                    else:
                        from_id, from_name = as_int(event.get("from_team_ea_id")), event.get("from_team_name")
                        to_id, to_name = as_int(event.get("to_team_ea_id")), event.get("to_team_name")
                    key = str(event.get("eventKey") or f"{event_type}:{season_index}:{from_id}:{to_id}:{event.get('date') or ''}")
                    if key in seen:
                        continue
                    seen.add(key)
                    event_date = event.get("date") or event.get("first_observed_date") or event.get("last_observed_date")
                    value, value_date = market_at(event_date)
                    movements.append({
                        "event_key": key,
                        "event_type": event_type,
                        "event_label": "Loan" if event_type == "loan" else "Transfer",
                        "season_index": season_index,
                        "season_label": option.get("label"),
                        "career_season_number": option.get("career_season_number"),
                        "date": event_date,
                        "from_team_ea_id": from_id,
                        "from_team_name": from_name or (f"Team {from_id}" if from_id is not None else "Unknown"),
                        "to_team_ea_id": to_id,
                        "to_team_name": to_name or (f"Team {to_id}" if to_id is not None else "Unknown"),
                        "fee": event.get("fee"),
                        "currency": event.get("currency") or "EUR",
                        "loan_end_date": event.get("loan_end_date"),
                        "source": event.get("source"),
                        "source_label": event.get("source_label") or "Derived",
                        "status": event.get("event_status"),
                        "market_value": value,
                        "market_value_date": value_date,
                    })
        movements.sort(key=lambda item: (str(item.get("date") or f"{as_int(item.get('season_index')) or 0:04d}"), item.get("event_type") or ""))
        station_rows = sorted(
            stations.values(),
            key=lambda item: (item.get("season_start_year") is None, as_int(item.get("season_start_year")) or 9999, str(item.get("first_date") or ""), item.get("team_name") or ""),
        )
        for item in station_rows:
            team_id = as_int(item.get("team_ea_id"))
            item["identity"] = self.state.media.team_identity(team_id, season_start=as_int(item.get("season_start_year"))) if team_id is not None else None
        return {
            "stations": station_rows,
            "movements": movements,
            "notes": [
                "Club history comes from observed snapshot states.",
                "Transfers and loans combine imported, derived and manually added records.",
                "Market values are calculated from the closest available development point in time.",
            ],
        }

    def _player(self, snapshot_id: int, player_id: int) -> dict[str, Any]:
        self.state.player_dynamics.ensure_snapshot(snapshot_id)
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            state = conn.execute(
                "SELECT * FROM player_states WHERE snapshot_id=? AND ea_player_id=?", (snapshot_id, player_id)
            ).fetchone()
            if not state:
                raise ValueError("Player not found in the selected snapshot.")
            stats = conn.execute(
                """SELECT * FROM season_stat_states WHERE snapshot_id=? AND player_ea_id=?
                   ORDER BY competition_name""",
                (snapshot_id, player_id),
            ).fetchall()
            simulated_stats = conn.execute(
                """SELECT * FROM atlas_simulated_player_stats WHERE snapshot_id=? AND player_ea_id=?
                   ORDER BY competition_name""",
                (snapshot_id, player_id),
            ).fetchall()
            performances = conn.execute(
                """SELECT pmp.*,f.id fixture_id,fo.competition_name,fo.home_team_name,fo.away_team_name,
                          fo.home_score,fo.away_score
                   FROM player_match_performances pmp
                   LEFT JOIN fixtures f ON f.fixture_key=pmp.fixture_key AND f.career_id=?
                   LEFT JOIN fixture_observations fo ON fo.snapshot_id=pmp.snapshot_id AND fo.fixture_id=f.id
                   WHERE pmp.snapshot_id=? AND pmp.player_ea_id=? ORDER BY pmp.date DESC""",
                (snap["career_id"], snapshot_id, player_id),
            ).fetchall()
            reconstructed_matches = reconstructed_player_matches(conn, snapshot_id, player_id)
            detailed_matches = detailed_player_matches(conn, int(snap["career_id"]), player_id)
            detailed_season_stats = detailed_player_season_summary(conn, int(snap["career_id"]), player_id, season_indices=[int(snap["season_index"])])
            detailed_season_history = detailed_player_season_history(conn, int(snap["career_id"]), player_id)
            history = conn.execute(
                """SELECT s.id snapshot_id,s.career_id,s.career_date,s.season_index,s.import_sequence,
                          s.managed_team_ea_id,s.external_snapshot_id,
                          p.overall,p.potential,p.team_ea_id,p.team_name,p.primary_position,
                          p.contract_valid_until,p.raw_json player_raw_json,
                          r.jersey_number,r.form,r.injury,r.raw_json roster_raw_json,
                          c.wage,c.duration_months,c.raw_json contract_raw_json,
                          l.parent_team_ea_id,l.loan_team_ea_id,l.loan_end_date
                   FROM player_states p JOIN snapshots s ON s.id=p.snapshot_id
                   LEFT JOIN roster_states r ON r.snapshot_id=p.snapshot_id AND r.player_ea_id=p.ea_player_id
                   LEFT JOIN contract_states c ON c.snapshot_id=p.snapshot_id AND c.player_ea_id=p.ea_player_id
                   LEFT JOIN loan_states l ON l.snapshot_id=p.snapshot_id AND l.player_ea_id=p.ea_player_id
                   WHERE s.career_id=? AND p.ea_player_id=? ORDER BY s.import_sequence""",
                (snap["career_id"], player_id),
            ).fetchall()
            stat_history = conn.execute(
                """SELECT s.id snapshot_id,s.career_date,s.season_index,s.import_sequence,ss.competition_object_id,
                          ss.competition_name,ss.represented_team_ea_id,ss.represented_team_name,
                          ss.appearances,ss.goals,ss.assists,ss.average_rating,ss.man_of_the_match,
                          ss.yellow_cards,ss.second_yellow_cards,ss.red_cards,ss.saves,ss.goals_conceded,
                          ss.clean_sheets
                   FROM season_stat_states ss JOIN snapshots s ON s.id=ss.snapshot_id
                   WHERE s.career_id=? AND ss.player_ea_id=? ORDER BY s.import_sequence,ss.competition_name""",
                (snap["career_id"], player_id),
            ).fetchall()
            roster = conn.execute(
                "SELECT * FROM roster_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            contract = conn.execute(
                "SELECT * FROM contract_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            loan = conn.execute(
                "SELECT * FROM loan_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            youth = conn.execute(
                "SELECT * FROM youth_player_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            growth = conn.execute(
                "SELECT * FROM player_growth_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_id)
            ).fetchone()
            award_rows = conn.execute(
                "SELECT raw_json FROM generic_snapshot_rows WHERE snapshot_id=? AND file_name='player_awards.csv'",
                (snapshot_id,),
            ).fetchall()
            is_captain = False
            financial = self.state.financial.calculate_player(conn, snap, state, roster=roster, contract=contract)
            history_items: list[dict[str, Any]] = []
            for history_row in history:
                item = dict(history_row)
                player_context = {
                    "overall": item.get("overall"), "potential": item.get("potential"),
                    "team_ea_id": item.get("team_ea_id"), "team_name": item.get("team_name"),
                    "primary_position": item.get("primary_position"),
                    "contract_valid_until": item.get("contract_valid_until"),
                    "raw_json": item.pop("player_raw_json", None),
                }
                roster_context = {
                    "form": item.get("form"), "raw_json": item.pop("roster_raw_json", None),
                }
                contract_context = {
                    "wage": item.get("wage"), "raw_json": item.pop("contract_raw_json", None),
                }
                snapshot_context = dict(item)
                snapshot_context["id"] = item["snapshot_id"]
                history_financial = self.state.financial.calculate_player(
                    conn, snapshot_context, player_context, roster=roster_context, contract=contract_context
                )
                item["financial"] = history_financial
                item["market_value"] = history_financial["market_value"].get("value")
                item["wage"] = history_financial["weekly_wage"].get("value")
                item["wage_label"] = history_financial["weekly_wage"].get("label")
                history_items.append(item)
        awards = [parse_raw(row["raw_json"]) for row in award_rows if as_int(parse_raw(row["raw_json"]).get("player_id")) == player_id]
        current_team_id = as_int(state["team_ea_id"])
        combined_stats = [
            row for row in stats
            if current_team_id is None or as_int(row["represented_team_ea_id"]) == current_team_id
        ] + [
            row for row in simulated_stats
            if current_team_id is None or as_int(row["team_ea_id"]) == current_team_id
        ]
        totals = {
            "appearances": sum(as_int(row["appearances"]) or 0 for row in combined_stats),
            "goals": sum(as_int(row["goals"]) or 0 for row in combined_stats),
            "assists": sum(as_int(row["assists"]) or 0 for row in combined_stats),
            "clean_sheets": sum(as_int(row["clean_sheets"]) or 0 for row in combined_stats),
            "man_of_the_match": sum(as_int(row["man_of_the_match"]) or 0 for row in combined_stats if "man_of_the_match" in row.keys()),
            "yellow_cards": sum(as_int(row["yellow_cards"]) or 0 for row in combined_stats if "yellow_cards" in row.keys()),
            "second_yellow_cards": sum(as_int(row["second_yellow_cards"]) or 0 for row in combined_stats if "second_yellow_cards" in row.keys()),
            "red_cards": sum(as_int(row["red_cards"]) or 0 for row in combined_stats if "red_cards" in row.keys()),
            "saves": sum(as_int(row["saves"]) or 0 for row in combined_stats if "saves" in row.keys()),
            "goals_conceded": sum(as_int(row["goals_conceded"]) or 0 for row in combined_stats if "goals_conceded" in row.keys()),
        }
        shots_faced = totals["saves"] + totals["goals_conceded"]
        totals["save_percentage"] = round(totals["saves"] / shots_faced, 4) if shots_faced > 0 else None
        ratings = [float(row["rating"]) for row in performances if row["rating"] not in (None, 0)]
        stat_ratings = [(float(row["average_rating"]), as_int(row["appearances"]) or 0) for row in combined_stats if row["average_rating"] not in (None, 0) and (as_int(row["appearances"]) or 0) > 0]
        totals["average_rating"] = (
            round(sum(rating * apps for rating, apps in stat_ratings) / sum(apps for _, apps in stat_ratings), 2)
            if stat_ratings else round(sum(ratings) / len(ratings), 2) if ratings else None
        )
        contract_item = clean_raw(contract)
        if contract_item:
            raw_role = contract_item.get("raw", {}).get("player_role")
            contract_item["player_role_raw"] = as_int(raw_role)
            contract_item["player_role_label"] = contract_role_label(raw_role)
        season_start = self._season_start(snap)
        player_item = clean_raw(state)
        player_raw = player_item.get("raw", {}) if player_item else {}
        if player_item is not None:
            player_item.update(player_age_data(player_raw.get("birthdate_raw"), snap["career_date"]))
            player_item["is_captain"] = is_captain
            player_item["market_value"] = financial["market_value"].get("value")
            player_item["weekly_wage"] = financial["weekly_wage"].get("value")
        team_id = as_int(player_item.get("team_ea_id") if player_item else None)
        nationality_id = as_int(player_item.get("nationality_id") if player_item else None)
        nationality = None
        if nationality_id is not None:
            with self.state.database.connect() as conn:
                nation = conn.execute(
                    "SELECT nation_id,nation_name,iso_code,flag_code FROM reference_nations WHERE nation_id=?",
                    (nationality_id,),
                ).fetchone()
            if nation:
                flag_code = str(nation["flag_code"] or nation["iso_code"] or "").lower()
                flag_file = self.state.static_dir / "flags" / f"{flag_code}.png"
                nationality = {
                    "id": int(nation["nation_id"]),
                    "name": nation["nation_name"],
                    "isoCode": nation["iso_code"],
                    "flagCode": nation["flag_code"],
                    "flagUrl": f"/flags/{flag_code}.png?v={_static_asset_version(flag_file)}" if flag_code and flag_file.is_file() else None,
                }
            else:
                nationality = {"id": nationality_id, "name": f"Nation {nationality_id}", "isoCode": None, "flagCode": None, "flagUrl": None}
        stat_items = rows_to_dicts(stats)
        for row in simulated_stats:
            item = dict(row)
            item.update({
                "represented_team_ea_id": item.get("team_ea_id"),
                "represented_team_name": player_item.get("team_name") if player_item else None,
                "source": "atlas_simulation",
                "source_label": "Atlas simulation",
            })
            stat_items.append(item)
        for item in stat_items:
            competition_id = as_int(item.get("competition_object_id"))
            if competition_id is not None:
                item["competitionIdentity"] = self.state.media.competition_identity(competition_id, snapshot_id=snapshot_id, competition_name=item.get("competition_name"))
        career_id = int(snap["career_id"])
        manual_history = self.state.manual.player_history(career_id, player_id)
        manual_editor = self.state.manual.player_editor(career_id, player_id)
        with self.state.database.connect() as conn:
            season_numbers = self._career_season_numbers(conn, career_id)
            for item in history_items:
                start_year = season_start_from_date(item.get("career_date"))
                item["season_start_year"] = start_year
                item["season_label"] = f"{start_year}/{str(start_year + 1)[-2:]}" if start_year is not None else "Unknown season"
                item["career_season_number"] = season_numbers.get(start_year) if start_year is not None else None
                item["ea_season_index"] = item.get("season_index")
                item["source"] = "snapshot"
                item["source_label"] = "Imported"
                item["stage"] = None
                item["stage_label"] = "Snapshot"
                item["effective_date"] = item.get("career_date")
            development_history = list(history_items)
            for point in manual_editor.get("development", []):
                item = dict(point)
                effective_date = str(item.get("effective_date") or f"{int(item['start_year']):04d}-07-01")
                market = self.state.financial.historical_market_value(
                    conn, career_id, player_id, effective_date,
                    int(item["overall"]), int(item["potential"]),
                    preferred_team_id=as_int(item.get("managed_team_ea_id")),
                )
                item.update({
                    "career_date": effective_date,
                    "effective_date": effective_date,
                    "season_start_year": as_int(item.get("start_year")),
                    "career_season_number": season_numbers.get(as_int(item.get("start_year"))),
                    "ea_season_index": item.get("season_index"),
                    "source": "manual",
                    "source_label": "Manual",
                    "stage_label": item.get("stage_label") or {"season_start": "Season start", "season_mid": "Mid-season", "season_end": "Season end"}.get(item.get("stage"), "Custom date"),
                    "market_value": market.get("value"),
                    "financial": {"market_value": market, "weekly_wage": {"value": None, "available": False, "label": "Not calculated"}},
                    "wage": None,
                    "wage_label": None,
                    "team_ea_id": item.get("managed_team_ea_id"),
                    "team_name": item.get("managed_team_name"),
                })
                development_history.append(item)
            development_history.sort(key=lambda item: (str(item.get("effective_date") or item.get("career_date") or ""), 0 if item.get("source") == "snapshot" else 1))

        latest_imported: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows_to_dicts(stat_history):
            competition_key = as_int(row.get("competition_object_id")) or competition_name_key(row.get("competition_name"))
            key = (as_int(row.get("season_index")) or 0, competition_key, as_int(row.get("represented_team_ea_id")) or 0)
            previous = latest_imported.get(key)
            if previous is None or (as_int(row.get("import_sequence")) or 0) >= (as_int(previous.get("import_sequence")) or 0):
                latest_imported[key] = row
        season_stats: list[dict[str, Any]] = []
        for row in latest_imported.values():
            start_year = season_start_from_date(row.get("career_date"))
            season_index = as_int(row.get("season_index")) or 0
            item = dict(row)
            item.update({
                "source": "snapshot",
                "source_label": "Imported",
                "season_label": f"{start_year}/{str(start_year + 1)[-2:]}" if start_year is not None else "Unknown season",
                "start_year": start_year,
                "end_year": start_year + 1 if start_year is not None else None,
                "career_season_number": season_numbers.get(start_year) if start_year is not None else None,
                "ea_season_index": season_index,
            })
            season_stats.append(item)
        current_start_year = season_start_from_date(snap["career_date"])
        for row in simulated_stats:
            item = dict(row)
            item.update({
                "source": "atlas_simulation",
                "source_label": "Atlas simulation",
                "represented_team_ea_id": item.get("team_ea_id"),
                "represented_team_name": player_item.get("team_name") if player_item else None,
                "season_label": f"{current_start_year}/{str(current_start_year + 1)[-2:]}" if current_start_year is not None else "Unknown season",
                "start_year": current_start_year,
                "end_year": current_start_year + 1 if current_start_year is not None else None,
                "career_season_number": season_numbers.get(current_start_year) if current_start_year is not None else None,
                "ea_season_index": snap["season_index"],
            })
            season_stats.append(item)
        for row in manual_history:
            item = dict(row)
            item.update({
                "source": "manual",
                "source_label": "Manual",
                "represented_team_ea_id": None,
                "represented_team_name": None,
                "yellow_cards": None,
                "second_yellow_cards": None,
                "red_cards": None,
                "man_of_the_match": None,
                "saves": None,
                "goals_conceded": None,
                "career_season_number": season_numbers.get(as_int(item.get("start_year"))),
                "ea_season_index": item.get("season_index"),
            })
            season_stats.append(item)
        season_stats.sort(key=lambda item: (as_int(item.get("season_index")) or 0, str(item.get("competition_name") or ""), 0 if item.get("source") == "snapshot" else 1))
        with self.state.database.connect() as conn:
            player_analysis = self._player_analysis(conn, snap, player_item or {}, growth, totals)
            player_career = self._player_career_path(conn, career_id, player_id, development_history)
        player_finance = self.state.player_finance.analyze(snapshot_id, player_id)
        financial["market_value"] = {
            "value": player_finance["market"].get("value"),
            "available": True,
            "source": "atlas_player_finance",
            "label": "Atlas market value · independent model based on performance, league, club, age, potential and contract",
        }
        if player_item is not None:
            player_item["market_value"] = player_finance["market"].get("value")
            player_item["dynamic_overall"] = (player_finance.get("dynamic") or {}).get("dynamicOverall")
            player_item["dynamic_delta"] = (player_finance.get("dynamic") or {}).get("delta")
        reconstructed_by_fixture = {str(item.get("fixtureKey") or ""): item for item in reconstructed_matches}
        performance_items = rows_to_dicts(performances)
        for item in performance_items:
            if not str(item.get("actual_position") or "").strip():
                try:
                    raw_performance = json.loads(str(item.get("raw_json") or "{}"))
                except (TypeError, json.JSONDecodeError):
                    raw_performance = {}
                rating_position_hint = str(raw_performance.get("rating_position_hint") or "").strip()
                if rating_position_hint:
                    item["actual_position"] = rating_position_hint
                    item["actual_position_source"] = "career_playermatchratinghistory_position"
            reconstructed = reconstructed_by_fixture.get(str(item.get("fixture_key") or ""))
            if reconstructed:
                item["reconstructedStats"] = reconstructed
        return {
            "snapshot": dict(snap),
            "player": player_item,
            "media": self.state.media.player_media(player_id),
            "teamIdentity": self.state.media.team_identity(team_id, season_start=season_start) if team_id is not None else None,
            "nationality": nationality,
            "stats": stat_items,
            "statHistory": rows_to_dicts(stat_history),
            "manualHistory": manual_history,
            "manualEditor": manual_editor,
            "seasonStats": season_stats,
            "performances": performance_items,
            "reconstructedMatches": reconstructed_matches,
            "detailedMatches": detailed_matches,
            "detailedSeasonStats": detailed_season_stats,
            "detailedSeasonHistory": detailed_season_history,
            "history": history_items,
            "developmentHistory": development_history,
            "financial": financial,
            "roster": clean_raw(roster),
            "contract": contract_item,
            "loan": clean_raw(loan),
            "youth": clean_raw(youth),
            "growth": clean_raw(growth),
            "awards": awards,
            "totals": totals,
            "analysis": player_analysis,
            "careerPath": player_career,
            "playerFinance": player_finance,
        }

    def _club(self, snapshot_id: int, team_id: int) -> dict[str, Any]:
        self.state.player_dynamics.ensure_snapshot(snapshot_id)
        with self.state.database.connect() as conn:
            snap = self._snapshot(conn, snapshot_id)
            team = conn.execute(
                "SELECT * FROM team_states WHERE snapshot_id=? AND ea_team_id=?", (snapshot_id, team_id)
            ).fetchone()
            if not team:
                raise ValueError("Club not found in the selected snapshot.")
            league = conn.execute(
                "SELECT * FROM team_league_states WHERE snapshot_id=? AND team_ea_id=?", (snapshot_id, team_id)
            ).fetchone()
            squad = conn.execute(
                """SELECT p.ea_player_id,p.display_name,p.team_ea_id,p.team_name,p.overall,p.potential,
                          p.primary_position,p.contract_valid_until,p.raw_json player_raw_json,
                          r.jersey_number,r.form,r.injury,r.raw_json roster_raw_json,
                          c.wage,c.duration_months,c.raw_json contract_raw_json
                   FROM roster_states r JOIN player_states p
                     ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                   LEFT JOIN contract_states c ON c.snapshot_id=p.snapshot_id AND c.player_ea_id=p.ea_player_id
                   WHERE r.snapshot_id=? AND r.team_ea_id=?
                   ORDER BY p.overall DESC,p.display_name""",
                (snapshot_id, team_id),
            ).fetchall()
            matches = self._fixture_rows(conn, snapshot_id, team_id=team_id)
            leaders = conn.execute(
                """WITH canonical_stats AS (
                       SELECT ss.player_ea_id,COALESCE(ss.goals,0) goals,COALESCE(ss.assists,0) assists,
                              COALESCE(ss.appearances,0) appearances,ss.average_rating rating,'observed' source
                       FROM season_stat_states ss
                       JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id
                       WHERE ss.snapshot_id=? AND ss.represented_team_ea_id=? AND p.team_ea_id=?
                       UNION ALL
                       SELECT ss.player_ea_id,COALESCE(ss.goals,0),COALESCE(ss.assists,0),
                              COALESCE(ss.appearances,0),ss.average_rating,'simulated'
                       FROM atlas_simulated_player_stats ss
                       JOIN player_states p ON p.snapshot_id=ss.snapshot_id AND p.ea_player_id=ss.player_ea_id
                       WHERE ss.snapshot_id=? AND ss.team_ea_id=? AND p.team_ea_id=?
                   ), aggregated AS (
                       SELECT player_ea_id,SUM(goals) goals,SUM(assists) assists,SUM(appearances) appearances,
                              CASE WHEN SUM(CASE WHEN rating IS NOT NULL AND appearances>0 THEN appearances ELSE 0 END)>0
                                   THEN SUM(CASE WHEN rating IS NOT NULL AND appearances>0 THEN rating*appearances ELSE 0 END)
                                      / SUM(CASE WHEN rating IS NOT NULL AND appearances>0 THEN appearances ELSE 0 END)
                              END average_rating,
                              COUNT(DISTINCT source) source_count,MIN(source) only_source
                       FROM canonical_stats GROUP BY player_ea_id
                   )
                   SELECT a.player_ea_id,p.display_name,p.team_ea_id,p.team_name,a.goals,a.assists,a.appearances,a.average_rating,
                          CASE WHEN a.source_count>1 THEN 'hybrid' ELSE a.only_source END source
                   FROM aggregated a JOIN player_states p ON p.snapshot_id=? AND p.ea_player_id=a.player_ea_id
                   ORDER BY a.goals DESC,a.assists DESC,a.appearances DESC LIMIT 12""",
                (snapshot_id, team_id, team_id, snapshot_id, team_id, team_id, snapshot_id),
            ).fetchall()
            loans_in = conn.execute(
                "SELECT * FROM loan_states WHERE snapshot_id=? AND loan_team_ea_id=?", (snapshot_id, team_id)
            ).fetchall()
            loans_out = conn.execute(
                "SELECT * FROM loan_states WHERE snapshot_id=? AND parent_team_ea_id=?", (snapshot_id, team_id)
            ).fetchall()
            history = conn.execute(
                """SELECT s.id snapshot_id,s.career_date,s.import_sequence,
                          (SELECT AVG(p.overall) FROM roster_states r JOIN player_states p ON p.snapshot_id=r.snapshot_id AND p.ea_player_id=r.player_ea_id
                           WHERE r.snapshot_id=ts.snapshot_id AND r.team_ea_id=ts.ea_team_id AND p.team_ea_id=ts.ea_team_id AND p.overall IS NOT NULL) overall,
                          ts.overall ea_base_overall,ts.attack,ts.midfield,
                          ts.defence,ts.club_worth,ts.league_ea_id,ts.league_name,tls.current_table_position,
                          tls.points,tls.matches_played
                   FROM team_states ts JOIN snapshots s ON s.id=ts.snapshot_id
                   LEFT JOIN team_league_states tls ON tls.snapshot_id=ts.snapshot_id AND tls.team_ea_id=ts.ea_team_id
                   WHERE s.career_id=? AND ts.ea_team_id=? ORDER BY s.import_sequence""",
                (snap["career_id"], team_id),
            ).fetchall()
            competitions = conn.execute(
                """SELECT f.competition_object_id,fo.competition_name,COUNT(*) matches,
                          SUM(CASE WHEN fo.is_completed=1 THEN 1 ELSE 0 END) completed
                   FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                   WHERE fo.snapshot_id=? AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)
                   GROUP BY f.competition_object_id,fo.competition_name ORDER BY matches DESC""",
                (snapshot_id, team_id, team_id),
            ).fetchall()
            league_history = self._league_history(conn, int(snap["career_id"]), team_id, snapshot_id)
            computed_position = self._current_league_position(conn, snapshot_id, team_id)
            league_item = clean_raw(league) or {}
            if computed_position:
                league_item["current_table_position_raw"] = league_item.get("current_table_position")
                league_item["current_table_position"] = computed_position.get("position")
                league_item["position_source"] = computed_position.get("source")
                league_item["position_source_label"] = computed_position.get("source_label")
                league_item["position_competition_object_id"] = computed_position.get("competition_object_id")
                league_item["position_competition_name"] = computed_position.get("competition_name")
            world_league_row = conn.execute(
                "SELECT * FROM atlas_league_simulations WHERE snapshot_id=? AND team_ea_id=?",
                (snapshot_id, team_id),
            ).fetchone()
            if world_league_row and not league_item.get("current_table_position"):
                league_item.update({
                    "current_table_position": world_league_row["position"],
                    "matches_played": world_league_row["matches_played"],
                    "points": world_league_row["points"],
                    "position_source": "atlas_simulation",
                    "position_source_label": "Atlas simulation",
                })
            squad_financial_items: list[dict[str, Any]] = []
            for squad_row in squad:
                item = dict(squad_row)
                player_raw_json = item.pop("player_raw_json", None)
                player_raw = parse_raw(player_raw_json)
                item.update(player_age_data(player_raw.get("birthdate_raw"), snap["career_date"]))
                player_context = dict(item)
                player_context["raw_json"] = player_raw_json
                roster_context = {"form": item.get("form"), "raw_json": item.pop("roster_raw_json", None)}
                contract_context = {"wage": item.get("wage"), "raw_json": item.pop("contract_raw_json", None)}
                player_financial = self.state.financial.calculate_player(
                    conn, snap, player_context, roster=roster_context, contract=contract_context
                )
                atlas_finance = self.state.player_finance.analyze(snapshot_id, int(item["ea_player_id"]))
                player_financial["market_value"] = {
                    "value": atlas_finance["market"].get("value"),
                    "available": True,
                    "source": "atlas_player_finance",
                    "label": "Atlas market value · independent model based on performance, league, club, age, potential and contract",
                }
                item["financial"] = player_financial
                item["player_finance"] = atlas_finance
                item["dynamic_overall"] = (atlas_finance.get("dynamic") or {}).get("dynamicOverall")
                item["dynamic_delta"] = (atlas_finance.get("dynamic") or {}).get("delta")
                item["market_value"] = atlas_finance["market"].get("value")
                item["weekly_wage"] = player_financial["weekly_wage"].get("value")
                item["wage_label"] = player_financial["weekly_wage"].get("label")
                squad_financial_items.append(item)
            live_strength = live_squad_strength(conn, snapshot_id, team_id)
        league_id = as_int(team["league_ea_id"])
        league_table = self.state.player_dynamics.world.league_table(snapshot_id, league_id) if league_id is not None else {"items": []}
        season_start = self._season_start(snap)
        squad_dicts = self._enrich_players(squad_financial_items)
        leader_items = self._enrich_players(rows_to_dicts(leaders))
        competition_items = rows_to_dicts(competitions)
        simulated_team_stats = self.state.player_dynamics.world.simulated_player_stats(snapshot_id, team_id=team_id)
        if simulated_team_stats:
            simulated_name = simulated_team_stats[0].get("competition_name")
            if simulated_name and not any(competition_name_key(item.get("competition_name")) == competition_name_key(simulated_name) for item in competition_items):
                competition_items.append({
                    "competition_object_id": simulated_team_stats[0].get("competition_object_id"),
                    "competition_name": simulated_name,
                    "league_ea_id": league_id,
                    "matches": league_item.get("matches_played") or 0,
                    "completed": league_item.get("matches_played") or 0,
                    "source": "atlas_simulation",
                    "source_label": "Atlas World · FC26 aggregate + simulated player values" if world_league_row and world_league_row["source"] == "observed" else "Atlas simulation",
                })
        for item in competition_items:
            competition_id = as_int(item.get("competition_object_id"))
            if competition_id is not None:
                item["identity"] = self.state.media.competition_identity(competition_id, snapshot_id=snapshot_id, competition_name=item.get("competition_name"))
            elif as_int(item.get("league_ea_id")) is not None:
                item["identity"] = self.state.media.league_identity(as_int(item.get("league_ea_id")), league_name=item.get("competition_name"))
        team_item = clean_raw(team) or {}
        alias = self.state.club_names.mapping(int(snap["career_id"])).get(team_id)
        if alias:
            team_item["team_name_original"] = team_item.get("team_name")
            team_item["team_name"] = alias
            if isinstance(team_item.get("raw"), dict):
                team_item["raw"]["team_name_original"] = team_item["raw"].get("team_name")
                team_item["raw"]["team_name"] = alias
        team_item["ea_base_overall"] = team_item.get("overall")
        team_item["ea_base_attack"] = team_item.get("attack")
        team_item["ea_base_midfield"] = team_item.get("midfield")
        team_item["ea_base_defence"] = team_item.get("defence")
        team_item["overall"] = round(float(live_strength["average"]), 2) if live_strength["average"] is not None else None
        team_item["attack"] = round(float(live_strength["groups"]["ATT"]), 1) if live_strength["groups"]["ATT"] is not None else None
        team_item["midfield"] = round(float(live_strength["groups"]["MID"]), 1) if live_strength["groups"]["MID"] is not None else None
        team_item["defence"] = round(float(live_strength["groups"]["DEF"]), 1) if live_strength["groups"]["DEF"] is not None else None
        team_item["overall_source"] = "live_roster_average"
        team_item["overall_sum"] = live_strength["sum"]
        team_item["overall_player_count"] = live_strength["count"]
        team_item["overall_membership_source"] = live_strength["membershipSource"]
        team_item["ea_base_overall_used"] = False
        return {
            "snapshot": dict(snap),
            "team": team_item,
            "identity": self.state.media.team_identity(team_id, season_start=season_start),
            "leagueState": league_item,
            "leagueTable": league_table,
            "squad": squad_dicts,
            "matches": self._enrich_fixtures(matches, season_start, snapshot_id),
            "leaders": leader_items,
            "loansIn": [clean_raw(row) for row in loans_in],
            "loansOut": [clean_raw(row) for row in loans_out],
            "history": rows_to_dicts(history),
            "leagueHistory": league_history,
            "competitions": competition_items,
            "summary": {
                "squad_count": len(squad_dicts),
                "average_overall": round(float(live_strength["average"]), 2) if live_strength["average"] is not None else None,
                "average_potential": round(sum((row["potential"] or 0) for row in squad_dicts) / len(squad_dicts), 1) if squad_dicts else None,
                "wage_total": sum((row.get("weekly_wage") or 0) for row in squad_dicts),
                "wage_label": "Snapshot wages" if int(team_id) == int(snap["managed_team_ea_id"] or -1) else "EA wages (calculated)",
            },
        }
