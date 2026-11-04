"""Evidence-bounded professional commission analysis for Atlas careers."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

MIN_USABLE_MINUTES = 300
MIN_USABLE_GAMES = 3
RELIABLE_MINUTES = 450
RELIABLE_GAMES = 5
METRIC_VERSION = 3
REPORT_VERSION = 4
_REPORT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-ollama-report")
_REPORT_JOB_LOCK = Lock()
_REPORT_JOBS: dict[str, dict[str, Any]] = {}
_REPORT_JOB_KEYS: dict[str, str] = {}
_RETRO_REPORT_JOBS: dict[str, dict[str, Any]] = {}

STAT_FIELDS = (
    "npk_goals", "own_goals", "assists", "shots", "shots_on_target", "passes",
    "passes_completed", "tackles", "interceptions", "blocks", "clearances", "dribbles",
    "dribbles_completed", "crosses_attempted", "crosses_delivered", "key_passes",
    "possession_won", "possession_lost", "saves", "shots_against", "goals_conceded",
    "npk_expected_goals", "expected_assists", "game_rating", "man_of_the_match",
)


def assess_sample(minutes: int, valid_games: int) -> dict[str, Any]:
    minutes, valid_games = max(0, int(minutes or 0)), max(0, int(valid_games or 0))
    usable = minutes >= MIN_USABLE_MINUTES and valid_games >= MIN_USABLE_GAMES
    reliable = minutes >= RELIABLE_MINUTES and valid_games >= RELIABLE_GAMES
    if reliable:
        code, label, scope = "confiavel", "Amostra confiável", "ranking_principal"
    elif usable:
        code, label, scope = "recorte_util", "Recorte utilizável", "ranking_principal"
    elif minutes <= 0:
        code, label, scope = "sem_minutagem", "Sem minutagem", "fora_de_ranking"
    elif minutes < 90:
        code, label, scope = "amostra_minima", "Amostra mínima (<90 min) — não conclusiva", "sinal_amostra_curta"
    elif minutes < 180:
        code, label, scope = "amostra_muito_curta", "Amostra muito curta (90–179 min) — não conclusiva", "sinal_amostra_curta"
    elif minutes < MIN_USABLE_MINUTES:
        code, label, scope = "amostra_curta", "Amostra curta (180–299 min) — ampliar teste", "sinal_amostra_curta"
    else:
        code, label, scope = "jogos_insuficientes", "Minutos suficientes, mas jogos válidos insuficientes", "sinal_amostra_curta"
    return {"usable": usable, "reliable": reliable, "code": code, "label": label, "scope": scope}


def _weighted_rating(rows: list[dict[str, Any]]) -> float | None:
    rated = [(float(r["rating"]), max(1, int(r["minutes_played"] or 0))) for r in rows if r.get("rating") is not None]
    total = sum(weight for _, weight in rated)
    return round(sum(rating * weight for rating, weight in rated) / total, 2) if total else None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _sum_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    valid_games = 0
    for row in rows:
        stats = row.get("stats") or {}
        if int(row.get("minutes") or 0) >= 15 or any(int(stats.get(field) or 0) > 0 for field in ("npk_goals", "own_goals", "pk_goals", "assists")):
            valid_games += 1
        for field in STAT_FIELDS:
            value = stats.get(field)
            if value is None:
                continue
            if field == "man_of_the_match":
                totals[field] += int(bool(value))
            else:
                parsed = _float(value)
                if parsed is not None:
                    totals[field] += parsed
                    counts[field] += 1
    # xG/xA are not made zero where the source omitted them.
    out = {key: round(value, 3) if key in {"npk_expected_goals", "expected_assists"} else int(value) if value.is_integer() else round(value, 2)
           for key, value in totals.items()}
    for key in ("npk_expected_goals", "expected_assists"):
        if counts[key] == 0:
            out[key] = None
    mins = sum(int(r.get("minutes") or 0) for r in rows)
    for source, dest in (("npk_goals", "goals_per90"), ("assists", "assists_per90"),
                         ("npk_expected_goals", "xg_per90"), ("expected_assists", "xa_per90")):
        out[dest] = round(out[source] * 90 / mins, 2) if mins and out.get(source) is not None else None
    out["minutes"] = mins
    out["appearances"] = len(rows)
    out["pass_accuracy_pct"] = round(out["passes_completed"] * 100 / out["passes"], 1) if out.get("passes") else None
    out["shot_accuracy_pct"] = round(out["shots_on_target"] * 100 / out["shots"], 1) if out.get("shots") else None
    out["average_rating"] = round(sum(float(r["rating"]) for r in rows if r.get("rating") is not None) / len([r for r in rows if r.get("rating") is not None]), 2) if any(r.get("rating") is not None for r in rows) else None
    out["valid_games"] = valid_games
    out["sample"] = assess_sample(mins, valid_games)
    return out


def _position_group(pos: str | None) -> str:
    p = str(pos or "").upper().strip()
    if p == "GK": return "Goleiro"
    if p in {"CB", "LCB", "RCB", "SW"}: return "Zagueiro"
    if p in {"LB", "LWB"}: return "Corredor esquerdo defensivo"
    if p in {"RB", "RWB"}: return "Corredor direito defensivo"
    if p in {"CDM", "CM"}: return "Meio-campo central"
    if p in {"CAM"}: return "Meia ofensivo"
    if p in {"LM", "LW"}: return "Corredor esquerdo ofensivo"
    if p in {"RM", "RW"}: return "Corredor direito ofensivo"
    if p in {"ST", "CF"}: return "Atacante"
    return "N/D"


def _cohort_comparisons(players: list[dict[str, Any]], cohort_key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        label = player.get(cohort_key) or "N/D"
        if label != "N/D" and player.get("detailed_stats"):
            groups[label].append(player)
    result = []
    for label, members in sorted(groups.items()):
        cohort = _sum_stats([row for p in members for row in p["detailed_stats"]])
        result.append({"position": label, "players": len(members), "matches": cohort["appearances"],
                       "minutes": cohort["minutes"], "goals_per90": cohort["goals_per90"],
                       "xg_per90": cohort["xg_per90"], "xa_per90": cohort["xa_per90"],
                       "average_rating": cohort["average_rating"], "sample": cohort["sample"]})
    return result


def _function_comparisons(detailed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in detailed:
        label = row.get("position")
        if label and label != "N/D" and row.get("match_position"):
            groups[label].append(row)
    result = []
    for label, rows in sorted(groups.items()):
        totals = _sum_stats(rows)
        result.append({"position": label, "players": len({int(r["player_ea_id"]) for r in rows}),
                       "matches": totals["appearances"], "minutes": totals["minutes"],
                       "goals_per90": totals["goals_per90"], "xg_per90": totals["xg_per90"],
                       "xa_per90": totals["xa_per90"], "average_rating": totals["average_rating"],
                       "sample": totals["sample"]})
    return result


def analyze_team_identity(conn: Any, career_id: int, snapshot_id: int) -> dict[str, Any]:
    """Describe the team's statistical profile without inventing possession or tactics."""
    snapshot = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)).fetchone()
    if not snapshot:
        raise ValueError("Snapshot does not belong to the selected career.")
    team_id = int(snapshot["managed_team_ea_id"] or -1)
    available_tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if not {"match_stat_exports", "match_team_detailed_stats"}.issubset(available_tables):
        completed = conn.execute(
            "SELECT COUNT(*) FROM fixture_observations WHERE snapshot_id=? AND managed_team_involved=1 AND is_completed=1",
            (snapshot_id,),
        ).fetchone()[0]
        return {"career_id": int(career_id), "snapshot_id": int(snapshot_id),
                "season_index": int(snapshot["season_index"]), "team_name": snapshot["managed_team_name"],
                "completed_matches": int(completed or 0), "detailed_matches": 0,
                "coverage_pct": 0.0 if completed else None,
                "metrics": {key: None for key in ("passes_per_match", "pass_accuracy_pct", "dribbles_completed_per_match",
                    "crosses_attempted_per_match", "through_passes_per_match", "shots_per_match", "npk_xg_per_match",
                    "tackles_per_match", "interceptions_per_match", "possession_share_pct")},
                "opponent_profiles": [], "style_sample_sufficient": False,
                "sample_note": "Amostra detalhada indisponível; estilo e perfis ficam inconclusivos.",
                "unavailable": ["estatísticas detalhadas da equipe", "posse de bola percentual", "pressão alta",
                                "altura da linha", "formação inicial, quando não exportada"]}
    rows = conn.execute(
        """SELECT fo.fixture_id,fo.date,fo.home_team_name,fo.away_team_name,fo.home_score,fo.away_score,
                  f.home_team_ea_id,f.away_team_ea_id,e.id export_id,e.team0_ea_id,e.team1_ea_id,
                  t.team_index,t.team_ea_id,t.stats_json
             FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
             LEFT JOIN match_stat_exports e ON e.fixture_id=f.id AND e.career_id=f.career_id
                  AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
                  AND e.superseded_by_export_id IS NULL
             LEFT JOIN match_team_detailed_stats t ON t.export_id=e.id
             WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
             ORDER BY fo.date,fo.fixture_id,t.team_index""", (snapshot_id,),
    ).fetchall()
    by_fixture: dict[int, dict[str, Any]] = {}
    for row in rows:
        fixture_id = int(row["fixture_id"])
        item = by_fixture.setdefault(fixture_id, {"fixture_id": fixture_id, "date": row["date"],
            "home": row["home_team_name"], "away": row["away_team_name"], "home_score": row["home_score"],
            "away_score": row["away_score"], "home_team_ea_id": row["home_team_ea_id"],
            "away_team_ea_id": row["away_team_ea_id"], "teams": {}})
        if row["team_ea_id"] is not None and row["stats_json"]:
            item["teams"][int(row["team_ea_id"])] = json.loads(row["stats_json"] or "{}")
    completed = list(by_fixture.values())
    detailed_rows: list[dict[str, Any]] = []
    for item in completed:
        own = item["teams"].get(team_id)
        opponent_id = item["away_team_ea_id"] if int(item["home_team_ea_id"] or -1) == team_id else item["home_team_ea_id"]
        opponent = item["teams"].get(int(opponent_id or -1))
        if not own:
            continue
        goals_for = item["home_score"] if int(item["home_team_ea_id"] or -1) == team_id else item["away_score"]
        goals_against = item["away_score"] if int(item["home_team_ea_id"] or -1) == team_id else item["home_score"]
        detailed_rows.append({"fixture_id": item["fixture_id"], "date": item["date"], "own": own, "opponent": opponent,
                              "goals_for": goals_for, "goals_against": goals_against})

    def average(field: str, source: str = "own") -> float | None:
        values = [_float((row.get(source) or {}).get(field)) for row in detailed_rows]
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 2) if values else None

    def ratio(numerator: str, denominator: str, source: str = "own") -> float | None:
        top = sum((_float((row.get(source) or {}).get(numerator)) or 0.0) for row in detailed_rows
                  if (row.get(source) or {}).get(numerator) is not None)
        bottom = sum((_float((row.get(source) or {}).get(denominator)) or 0.0) for row in detailed_rows
                     if (row.get(source) or {}).get(denominator) is not None)
        return round(top * 100 / bottom, 1) if bottom else None

    metrics = {
        "passes_per_match": average("passes"),
        "pass_accuracy_pct": ratio("passes_completed", "passes"),
        "dribbles_completed_per_match": average("dribbles_completed"),
        "crosses_attempted_per_match": average("crosses_attempted"),
        "through_passes_per_match": average("tracker_completed_through_passes_including_lobbed"),
        "shots_per_match": average("shots"),
        "npk_xg_per_match": average("npk_expected_goals"),
        "tackles_per_match": average("tackles"),
        "interceptions_per_match": average("interceptions"),
        "possession_share_pct": None,
    }

    # Compare lower and upper thirds of the observed opposition shot-volume ranks.
    ranked = sorted((row for row in detailed_rows if row.get("opponent") and row["opponent"].get("shots") is not None),
                    key=lambda row: (float(row["opponent"]["shots"]), str(row.get("date") or ""), row["fixture_id"]))
    cohort_size = len(ranked) // 3
    cohorts = []
    if cohort_size >= 5:
        groups = [("Adversários com menor volume de finalizações", ranked[:cohort_size]),
                  ("Adversários com maior volume de finalizações", ranked[-cohort_size:])]
        for label, group in groups:
            points, goal_difference, xg_differences = [], [], []
            for row in group:
                own, opp = row["own"], row["opponent"]
                own_goals = int(row.get("goals_for") or 0)
                opp_goals = int(row.get("goals_against") or 0)
                points.append(3 if own_goals > opp_goals else 1 if own_goals == opp_goals else 0)
                goal_difference.append(own_goals - opp_goals)
                own_xg, opp_xg = _float(own.get("npk_expected_goals")), _float(opp.get("npk_expected_goals"))
                if own_xg is not None and opp_xg is not None:
                    xg_differences.append(own_xg - opp_xg)
            cohorts.append({"opponent_profile": label, "matches": len(group),
                            "points_per_match": round(sum(points) / len(points), 2),
                            "goal_difference_per_match": round(sum(goal_difference) / len(goal_difference), 2),
                            "xg_difference_per_match": round(sum(xg_differences) / len(xg_differences), 2) if xg_differences else None,
                            "opponent_shots_avg": round(sum(float(row["opponent"]["shots"]) for row in group) / len(group), 2)})
        cohorts.sort(key=lambda row: (row["points_per_match"], row["goal_difference_per_match"]))
        cohorts[0]["reading"] = "maior_dificuldade_observada"
        cohorts[-1]["reading"] = "maior_facilidade_observada"

    return {"career_id": int(career_id), "snapshot_id": int(snapshot_id),
            "season_index": int(snapshot["season_index"]), "team_name": snapshot["managed_team_name"],
            "completed_matches": len(completed), "detailed_matches": len(detailed_rows),
            "coverage_pct": round(100 * len(detailed_rows) / len(completed), 1) if completed else None,
            "metrics": metrics, "opponent_profiles": cohorts,
            "style_sample_sufficient": len(detailed_rows) >= 5,
            "sample_note": "Amostra utilizável a partir de 5 partidas completas; sem isso, estilo e perfis ficam inconclusivos.",
            "unavailable": ["posse de bola percentual", "pressão alta", "altura da linha", "formação inicial, quando não exportada"]}


def analyze_players(players: list[dict[str, Any]], performances: list[dict[str, Any]], detailed: list[dict[str, Any]] | None = None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    detailed = detailed or []
    coverage = coverage or {}
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    detail_by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    detail_by_player_fixture: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in performances:
        if row.get("player_ea_id") is not None:
            by_player[int(row["player_ea_id"])].append(row)
    for row in detailed:
        if row.get("player_ea_id") is not None:
            player_id = int(row["player_ea_id"])
            detail_by_player[player_id].append(row)
            if row.get("fixture_key"):
                detail_by_player_fixture[(player_id, str(row["fixture_key"]))].append(row)

    result = []
    total_appearances = 0
    for player in players:
        player_id = int(player["ea_player_id"])
        rows = by_player.get(player_id, [])
        rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("fixture_key") or "")))
        valid = []
        for row in rows:
            minutes = int(row.get("minutes_played") or 0)
            detail_stats = [item.get("stats") or {} for item in detail_by_player_fixture.get(
                (player_id, str(row.get("fixture_key") or "")), [])]
            recorded_contribution = any(
                _float(stats.get(field)) is not None and float(stats.get(field) or 0) > 0
                for stats in detail_stats for field in ("npk_goals", "own_goals", "pk_goals", "assists")
            )
            # Hub counts a starter, 15+ minutes, or a recorded goal/assist as a valid appearance.
            # Starter status is not exported by Atlas; use only available minutes and MatchStats events.
            if minutes >= 15 or recorded_contribution:
                valid.append(row)
        minutes = sum(max(0, int(r.get("minutes_played") or 0)) for r in rows)
        latest_five = valid[-5:]
        season_rating, recent_rating = _weighted_rating(valid), _weighted_rating(latest_five)
        sample = assess_sample(minutes, len(valid))
        delta = round(recent_rating - season_rating, 2) if recent_rating is not None and season_rating is not None else None
        if not sample["usable"]:
            moment = "Sinal insuficiente" if recent_rating is not None else "Sem dados de forma"
            recommendation = "Ampliar amostra antes de decidir" if recent_rating is not None else "Sem recomendação: faltam dados"
        elif delta is not None and delta >= 0.3:
            moment, recommendation = "Em alta", "Manter em observação competitiva"
        elif delta is not None and delta <= -0.3:
            moment, recommendation = "Em queda", "Acompanhar a recuperação da forma"
        else:
            moment, recommendation = "Estável", "Manter acompanhamento"
        detailed_rows = detail_by_player.get(player_id, [])
        detail_totals = _sum_stats(detailed_rows)
        # Match-specific positional provenance only: latest-lineup snapshots are excluded.
        observed_positions = [_position_group(r.get("match_position")) for r in detailed_rows if r.get("match_position")]
        registered_position = player.get("primary_position") or "N/D"
        total_appearances += len(rows)
        result.append({
            "player_ea_id": player_id, "display_name": player.get("display_name") or "N/D",
            "position": registered_position, "hierarchy": None, "hierarchy_label": "N/D — não registrada no Atlas",
            "appearances": len(rows), "valid_form_games": len(valid), "minutes": minutes,
            "season_rating": season_rating, "recent_rating": recent_rating, "recent_appearances": len(latest_five),
            "recent_delta": delta, "sample": sample, "moment": moment, "recommendation": recommendation,
            "goals": detail_totals.get("npk_goals"), "assists": detail_totals.get("assists"),
            "detailed_stats": detailed_rows, "metrics": detail_totals,
            "match_position": observed_positions[-1] if observed_positions else None,
            "position_sample_source": "posição por atuação registrada no histórico de rating" if observed_positions else "posição principal cadastrada no elenco",
            "latest_date": rows[-1].get("date") if rows else None,
            "source": "player_match_performances" if rows else None,
        })

    result.sort(key=lambda p: (p["recent_rating"] is None, -(p["recent_rating"] or 0), p["display_name"].casefold()))
    position_comparisons = _cohort_comparisons(result, "position")
    function_comparisons = _function_comparisons(detailed)
    for player in result:
        player.pop("detailed_stats", None)
    return {
        "metric_version": METRIC_VERSION, "players": result,
        "coverage": {**coverage, "squad_players": len(players),
                     "players_with_performances": sum(bool(by_player.get(int(p["ea_player_id"]), [])) for p in players),
                     "appearance_rows": total_appearances,
                     "ratings_and_minutes": "extraídos do histórico profissional de atuações; temporadas cumulativas",
                     "hierarchy": "indisponível; N/D", "youth_5x5": "escopo separado; nenhuma métrica profissional aplicada"},
        "position_comparisons": position_comparisons,
        "function_comparisons": function_comparisons,
    }


def _ensure_cache(conn: Any) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS technical_commission_cache (
        career_id INTEGER NOT NULL REFERENCES careers(id), snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        metric_version INTEGER NOT NULL, source_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(career_id, snapshot_id, metric_version))""")


def _read_data(conn: Any, career_id: int, snapshot_id: int) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)).fetchone()
    if not snapshot:
        raise ValueError("Snapshot does not belong to the selected career.")
    team_id = snapshot["managed_team_ea_id"]
    players = [dict(row) for row in conn.execute(
        "SELECT ea_player_id,display_name,primary_position FROM player_states WHERE snapshot_id=? AND team_ea_id=? ORDER BY display_name",
        (snapshot_id, team_id))]
    performances = [dict(row) for row in conn.execute(
        """SELECT p.player_ea_id,p.fixture_key,p.date,p.rating,p.minutes_played,p.actual_position,p.actual_position_source
           FROM player_match_performances p WHERE p.snapshot_id=? AND CAST(json_extract(p.raw_json,'$.managed_team_id') AS INTEGER)=?
           ORDER BY p.date,p.fixture_key,p.player_ea_id""", (snapshot_id, team_id))] if team_id is not None else []
    fixture_rows = conn.execute(
        """SELECT e.id,e.fixture_id,e.team0_ea_id,e.team1_ea_id,f.fixture_key,
                  d.player_ea_id,d.minutes_played,d.game_rating,d.stats_json,
                  CASE WHEN p.actual_position_source='career_playermatchratinghistory_position' THEN p.actual_position ELSE NULL END match_position
           FROM match_stat_exports e JOIN snapshots es ON es.id=e.snapshot_id
           JOIN fixture_observations o ON o.snapshot_id=? AND o.fixture_id=e.fixture_id
           JOIN fixtures f ON f.id=e.fixture_id
           JOIN match_player_detailed_stats d ON d.export_id=e.id
           LEFT JOIN player_match_performances p ON p.snapshot_id=? AND p.fixture_key=f.fixture_key AND p.player_ea_id=d.player_ea_id
           WHERE e.career_id=? AND es.season_index=? AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
             AND e.superseded_by_export_id IS NULL AND o.is_completed=1 AND o.managed_team_involved=1
             AND (? IN (e.team0_ea_id,e.team1_ea_id))
             AND d.team_index=CASE WHEN e.team0_ea_id=? THEN 0 ELSE 1 END
           ORDER BY o.date,e.id,d.player_ea_id""",
        (snapshot_id, snapshot_id, career_id, int(snapshot["season_index"]), int(team_id or -1), int(team_id or -1))).fetchall() if team_id is not None else []
    detailed = []
    export_ids: set[int] = set()
    for row in fixture_rows:
        item = dict(row)
        item["stats"] = json.loads(item.pop("stats_json") or "{}")
        item["minutes"] = item.get("minutes_played")
        item["rating"] = item.get("game_rating")
        item["position"] = _position_group(item.get("match_position"))
        detailed.append(item)
        export_ids.add(int(item["id"]))
    fixture_count = int(conn.execute(
        "SELECT COUNT(*) FROM fixture_observations WHERE snapshot_id=? AND managed_team_involved=1 AND is_completed=1",
        (snapshot_id,)).fetchone()[0])
    stats_present = sum(bool(r.get("stats")) for r in detailed)
    coverage = {"detailed_matches": len(export_ids), "completed_team_matches": fixture_count,
                "detailed_match_coverage_pct": round(len(export_ids) * 100 / fixture_count, 1) if fixture_count else None,
                "detailed_player_rows": len(detailed), "players_with_detailed_stats": len({int(r["player_ea_id"]) for r in detailed if r.get("player_ea_id") is not None}),
                "metrics_from_matchstats": "gols, assistências, NPK-xG, xA, chutes, passes, desarmes, interceptações e ações registradas",
                "detailed_metric_scope": "somente partidas com exportação completa ligada; não representa temporada completa",
                "detailed_rows_with_stats": stats_present,
                "position_function": "função por atuação somente quando provenance é histórico de posição do rating; sem inferência"}
    return snapshot, players, performances, detailed, coverage


def get_commission(conn: Any, career_id: int, snapshot_id: int) -> dict[str, Any]:
    _ensure_cache(conn)
    snapshot, players, performances, detailed, coverage = _read_data(conn, career_id, snapshot_id)
    source_hash = hashlib.sha256(json.dumps({"players": players, "performances": performances, "detailed": detailed, "coverage": coverage}, sort_keys=True, default=str).encode()).hexdigest()
    cached = conn.execute("SELECT source_hash,payload_json FROM technical_commission_cache WHERE career_id=? AND snapshot_id=? AND metric_version=?",
                          (career_id, snapshot_id, METRIC_VERSION)).fetchone()
    if cached and cached["source_hash"] == source_hash:
        payload = json.loads(cached["payload_json"])
    else:
        payload = analyze_players(players, performances, detailed, coverage)
        conn.execute("""INSERT INTO technical_commission_cache(career_id,snapshot_id,metric_version,source_hash,payload_json)
            VALUES(?,?,?,?,?) ON CONFLICT(career_id,snapshot_id,metric_version) DO UPDATE SET source_hash=excluded.source_hash,
            payload_json=excluded.payload_json,generated_at=CURRENT_TIMESTAMP""",
            (career_id, snapshot_id, METRIC_VERSION, source_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    payload.update({"career_id": career_id, "snapshot_id": snapshot_id, "season_index": int(snapshot["season_index"]),
                    "career_date": snapshot["career_date"], "managed_team_name": snapshot["managed_team_name"],
                    "managed_completed_fixture_count": int(snapshot["managed_completed_fixture_count"] or 0)})
    from .media_utils import season_start_from_date
    season_rows = conn.execute(
        """SELECT season_index,MIN(career_date) first_date,MAX(id) latest_snapshot_id
             FROM snapshots WHERE career_id=? GROUP BY season_index ORDER BY season_index""",
        (career_id,),
    ).fetchall()
    season_options = []
    for row in season_rows:
        index = int(row["season_index"])
        start_year = season_start_from_date(row["first_date"])
        season_options.append({"season_index": index,
                               "label": f"{start_year}/{str(start_year + 1)[-2:]}" if start_year is not None else f"Season {index + 1}",
                               "is_current": index == int(snapshot["season_index"]),
                               "latest_snapshot_id": int(row["latest_snapshot_id"])})
    payload["seasonOptions"] = season_options
    payload["selectedSeasonIndex"] = int(snapshot["season_index"])
    payload["selectedSeasonLabel"] = next((option["label"] for option in season_options if option["season_index"] == int(snapshot["season_index"])), f"Season {int(snapshot['season_index']) + 1}")
    observation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(fixture_observations)").fetchall()}
    fixture_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(fixtures)").fetchall()}
    match_rows = []
    if {"snapshot_id", "fixture_id", "managed_team_involved", "is_completed"}.issubset(observation_columns) and {"id"}.issubset(fixture_columns):
        expressions = {name: f"fo.{name}" if name in observation_columns else "NULL" for name in
                       ("date", "competition_name", "home_team_name", "away_team_name", "home_score", "away_score", "is_completed")}
        match_rows = conn.execute(
            f"""SELECT f.id fixture_id,{expressions['date']} date,{expressions['competition_name']} competition_name,
                       {expressions['home_team_name']} home_team_name,{expressions['away_team_name']} away_team_name,
                       {expressions['home_score']} home_score,{expressions['away_score']} away_score,{expressions['is_completed']} is_completed,
                       EXISTS(SELECT 1 FROM match_stat_exports e WHERE e.fixture_id=f.id
                              AND e.superseded_by_export_id IS NULL AND e.linkage_status='linked'
                              AND e.export_status='complete_participant_export') detailed_stats_available
                FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                WHERE fo.snapshot_id=? AND fo.managed_team_involved=1
                ORDER BY CASE WHEN fo.is_completed=1 THEN 0 ELSE 1 END,
                         CASE WHEN fo.is_completed=1 THEN fo.date END DESC,
                         CASE WHEN COALESCE(fo.is_completed,0)<>1 THEN fo.date END ASC,f.id LIMIT 80""",
            (snapshot_id,)).fetchall()
    payload["briefingOptions"] = {
        "matches": [{"fixture_id": int(row["fixture_id"]), "date": row["date"],
                     "competition": row["competition_name"], "home": row["home_team_name"],
                     "away": row["away_team_name"], "home_score": row["home_score"],
                     "away_score": row["away_score"], "detailed_stats_available": bool(row["detailed_stats_available"])}
                    for row in match_rows if row["is_completed"] == 1],
        "upcoming": [{"fixture_id": int(row["fixture_id"]), "date": row["date"],
                      "competition": row["competition_name"], "home": row["home_team_name"],
                      "away": row["away_team_name"]}
                     for row in match_rows if row["is_completed"] != 1],
    }
    payload["team_identity"] = analyze_team_identity(conn, career_id, snapshot_id)
    return payload


def ollama_models(timeout: float = 2.0) -> dict[str, Any]:
    base = os.environ.get("ATLAS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    request = urllib.request.Request(base + "/api/tags", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            models = json.loads(response.read().decode("utf-8"))
        return {"available": True, "models": [m.get("name") for m in models.get("models", []) if m.get("name")]}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"available": False, "models": [], "message": f"Ollama offline ou indisponível: {exc.__class__.__name__}"}


def ollama_analysis(payload: dict[str, Any], model: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    """Optional local AI. Output is constrained and evidence-linked; never writes SQLite."""
    tags = ollama_models(timeout=2.0)
    selected = model or os.environ.get("ATLAS_OLLAMA_MODEL") or (tags["models"][0] if tags["models"] else None)
    if not tags["available"] or not selected:
        return {"available": False, "fallback": True, "message": "Análise local indisponível; leitura determinística do Atlas preservada.", "observations": []}
    metric_fields = ("npk_goals", "assists", "npk_expected_goals", "expected_assists", "shots",
                     "pass_accuracy_pct", "tackles", "interceptions", "saves", "goals_conceded")
    facts = [{"player_ea_id": p["player_ea_id"], "display_name": p["display_name"], "position": p["position"],
              "minutes": p["minutes"], "appearances": p["appearances"], "season_rating": p["season_rating"],
              "recent_rating": p["recent_rating"], "sample": p["sample"],
              "match_metrics": {key: (p.get("metrics") or {}).get(key) for key in metric_fields}}
             for p in payload.get("players", [])]
    body = {"model": selected, "stream": False, "format": "json", "think": False,
            "messages": [{"role": "system", "content": "Retorne um objeto JSON com observations, array de objetos {player_ea_id, signal}. signal deve ser um destes valores: form_up, form_down, goals, assists, goals_above_xg, xg_above_goals, reliable_sample, small_sample. Selecione no máximo oito sinais diretamente sustentados pelos valores JSON. Não inclua texto ou campos adicionais, não estime dados ausentes, não invente hierarquia nem recomende escalação. Se não houver sinal claro, retorne lista vazia."},
                         {"role": "user", "content": json.dumps({"coverage": payload.get("coverage"), "facts": facts}, ensure_ascii=False)}],
            "options": {"temperature": 0.1, "num_predict": 400}}
    base = os.environ.get("ATLAS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = json.loads(result.get("message", {}).get("content", "{}"))
        observations = content.get("observations")
        if not isinstance(observations, list):
            raise ValueError("invalid schema")
        clean = []
        facts_by_id = {str(p["player_ea_id"]): p for p in facts}
        signal_fields = {"form_up": ["recent_rating", "season_rating"], "form_down": ["recent_rating", "season_rating"],
                         "goals": ["match_metrics.npk_goals"], "assists": ["match_metrics.assists"],
                         "goals_above_xg": ["match_metrics.npk_goals", "match_metrics.npk_expected_goals"],
                         "xg_above_goals": ["match_metrics.npk_goals", "match_metrics.npk_expected_goals"],
                         "reliable_sample": ["sample.reliable"], "small_sample": ["sample.usable"]}
        for note in observations:
            if not isinstance(note, dict) or not {"player_ea_id", "signal"}.issubset(note) or not set(note).issubset({"player_ea_id", "signal", "evidence"}):
                raise ValueError("invalid signal object")
            player_id = str(note.get("player_ea_id", ""))
            signal = note.get("signal")
            fact = facts_by_id.get(player_id)
            if not fact or signal not in signal_fields:
                raise ValueError("invalid evidence reference")
            metrics = fact.get("match_metrics") or {}
            if signal == "form_up" and (fact.get("recent_rating") is None or fact.get("season_rating") is None or fact["recent_rating"] < fact["season_rating"] + 0.3): continue
            if signal == "form_down" and (fact.get("recent_rating") is None or fact.get("season_rating") is None or fact["recent_rating"] > fact["season_rating"] - 0.3): continue
            if signal == "goals" and metrics.get("npk_goals") in (None, 0): continue
            if signal == "assists" and metrics.get("assists") in (None, 0): continue
            if signal == "goals_above_xg" and (metrics.get("npk_goals") is None or metrics.get("npk_expected_goals") is None or metrics["npk_goals"] <= metrics["npk_expected_goals"]): continue
            if signal == "xg_above_goals" and (metrics.get("npk_goals") is None or metrics.get("npk_expected_goals") is None or metrics["npk_expected_goals"] <= metrics["npk_goals"]): continue
            if signal == "reliable_sample" and not fact.get("sample", {}).get("reliable"): continue
            if signal == "small_sample" and fact.get("sample", {}).get("usable"): continue
            text_by_signal = {"form_up": f"Nota recente {fact['recent_rating']:.2f}, acima da média do período ({fact['season_rating']:.2f}).",
                              "form_down": f"Nota recente {fact['recent_rating']:.2f}, abaixo da média do período ({fact['season_rating']:.2f}).",
                              "goals": f"{metrics['npk_goals']} gols sem pênalti nas partidas com MatchStats.",
                              "assists": f"{metrics['assists']} assistências nas partidas com MatchStats.",
                              "goals_above_xg": f"Gols ({metrics['npk_goals']}) acima do NPK-xG registrado ({metrics['npk_expected_goals']:.2f}) no recorte coberto.",
                              "xg_above_goals": f"NPK-xG ({metrics['npk_expected_goals']:.2f}) acima dos gols ({metrics['npk_goals']}) no recorte coberto.",
                              "reliable_sample": f"Amostra confiável: {fact['minutes']} minutos e {fact['appearances']} atuações registradas.",
                              "small_sample": f"Amostra abaixo do patamar utilizável: {fact['minutes']} minutos e {fact['appearances']} atuações registradas."}
            clean.append({"player_ea_id": player_id, "signal": signal, "text": text_by_signal[signal], "evidence": signal_fields[signal]})
        return {"available": True, "fallback": False, "model": selected, "observations": clean}
    except (OSError, ValueError, KeyError, urllib.error.URLError, TimeoutError) as exc:
        detail = str(exc).replace("\n", " ")[:120]
        suffix = f": {detail}" if detail else ""
        return {"available": False, "fallback": True, "message": f"Análise local não validada; painel determinístico mantido ({exc.__class__.__name__}{suffix}).", "observations": []}


def get_ollama_analysis(conn: Any, career_id: int, snapshot_id: int, model: str | None = None) -> dict[str, Any]:
    conn.execute("""CREATE TABLE IF NOT EXISTS technical_commission_ai_cache (
        career_id INTEGER NOT NULL REFERENCES careers(id), snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        model TEXT NOT NULL, source_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(career_id,snapshot_id,model))""")
    deterministic = get_commission(conn, career_id, snapshot_id)
    cache_model = model or os.environ.get("ATLAS_OLLAMA_MODEL") or "auto"
    chosen = cache_model
    source_hash = hashlib.sha256(json.dumps({"version": METRIC_VERSION, "coverage": deterministic.get("coverage"),
        "players": [{k: p.get(k) for k in ("player_ea_id", "position", "minutes", "appearances", "season_rating", "recent_rating", "sample", "goals", "assists", "metrics")} for p in deterministic.get("players", [])]},
        sort_keys=True, default=str).encode()).hexdigest()
    cached = conn.execute("SELECT source_hash,payload_json FROM technical_commission_ai_cache WHERE career_id=? AND snapshot_id=? AND model=?",
                          (career_id, snapshot_id, cache_model)).fetchone()
    if cached and cached["source_hash"] == source_hash:
        return json.loads(cached["payload_json"])
    try:
        timeout = min(180.0, max(5.0, float(os.environ.get("ATLAS_OLLAMA_TIMEOUT_SECONDS", "90"))))
    except ValueError:
        timeout = 90.0
    result = ollama_analysis(deterministic, None if chosen == "auto" else chosen, timeout=timeout)
    if result.get("available"):
        conn.execute("""INSERT INTO technical_commission_ai_cache(career_id,snapshot_id,model,source_hash,payload_json)
            VALUES(?,?,?,?,?) ON CONFLICT(career_id,snapshot_id,model) DO UPDATE SET source_hash=excluded.source_hash,
            payload_json=excluded.payload_json,generated_at=CURRENT_TIMESTAMP""",
            (career_id, snapshot_id, cache_model, source_hash, json.dumps(result, ensure_ascii=False, sort_keys=True)))
    return result


def _briefing_facts(conn: Any, career_id: int, snapshot_id: int, mode: str,
                    fixture_id: int | None, player_ea_id: int | None,
                    language_override: str | None = None) -> tuple[dict[str, Any], list[str], str]:
    """Assemble small, career-scoped fact packs for dynamic local reports."""
    snapshot = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)).fetchone()
    if not snapshot:
        raise ValueError("Snapshot does not belong to the selected career.")
    team_id = int(snapshot["managed_team_ea_id"] or -1)
    facts: list[dict[str, Any]] = []

    def fact(key: str, label: str, value: Any, source: str) -> None:
        if value is not None:
            facts.append({"id": key, "label": label, "value": value, "source": source})

    if mode in {"match", "match_player", "next_match"}:
        if fixture_id is None:
            raise ValueError("Select a match from the current career calendar.")
        row = conn.execute(
            """SELECT fo.*,f.fixture_key,f.home_team_ea_id,f.away_team_ea_id,f.competition_object_id
                 FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                 WHERE fo.snapshot_id=? AND fo.fixture_id=? AND fo.managed_team_involved=1""",
            (snapshot_id, fixture_id),
        ).fetchone()
        if not row:
            raise ValueError("Selected match is not part of this career snapshot.")
        completed = row["is_completed"] == 1
        if mode in {"match", "match_player"} and not completed:
            raise ValueError("Match reports are available only for completed matches.")
        if mode == "next_match" and completed:
            raise ValueError("Preparation reports require an upcoming match.")
        managed_is_home = int(row["home_team_ea_id"] or -1) == team_id
        opponent_id = int((row["away_team_ea_id"] if managed_is_home else row["home_team_ea_id"]) or -1)
        match = {"fixture_id": int(fixture_id), "date": row["date"], "competition": row["competition_name"],
                 "home": row["home_team_name"], "away": row["away_team_name"], "completed": completed,
                 "managed_team_side": "home" if managed_is_home else "away",
                 "opponent_ea_id": opponent_id}
        if completed:
            match["score"] = [row["home_score"], row["away_score"]]
            match["managed_score"] = row["home_score"] if managed_is_home else row["away_score"]
            match["opponent_score"] = row["away_score"] if managed_is_home else row["home_score"]
        fact("match", "Fixture", match, "Atlas fixture calendar")
        if mode in {"match", "match_player"} and completed and opponent_id > 0:
            prior_snapshot = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? AND import_sequence<=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
                (career_id, int(snapshot["import_sequence"])),
            ).fetchone()
            history_rows = []
            if prior_snapshot:
                history_rows = conn.execute(
                    """SELECT DISTINCT f.id,fo.managed_team_result
                         FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                        WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1 AND f.id<>?
                          AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)""",
                    (int(prior_snapshot["id"]), int(fixture_id), opponent_id, opponent_id),
                ).fetchall()
            fact("opponent_history", "Earlier recorded meetings with this opponent", {
                "opponent_ea_id": opponent_id, "previous_meetings": len(history_rows),
                "previous_wins": sum(1 for item in history_rows if str(item["managed_team_result"] or "").upper() == "W"),
            }, "completed Atlas fixtures in the latest snapshot available at the selected career date")
        if mode in {"match", "match_player"}:
            export = conn.execute(
                """SELECT e.id FROM match_stat_exports e WHERE e.fixture_id=? AND e.career_id=?
                     AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
                     AND e.superseded_by_export_id IS NULL ORDER BY e.id DESC LIMIT 1""",
                (fixture_id, career_id),
            ).fetchone()
            if export:
                teams = conn.execute(
                    "SELECT team_index,team_ea_id,stats_json FROM match_team_detailed_stats WHERE export_id=? ORDER BY team_index",
                    (export["id"],),
                ).fetchall()
                team_stats = []
                for team in teams:
                    stats = json.loads(team["stats_json"] or "{}")
                    keys = ("npk_expected_goals", "expected_assists", "shots", "shots_on_target", "passes",
                            "pass_accuracy_pct_derived", "possession_won", "possession_lost", "tackles",
                            "interceptions", "saves", "goals_conceded")
                    team_stats.append({key: stats.get(key) for key in keys if stats.get(key) is not None} | {"team_index": int(team["team_index"])})
                fact("matchstats", "Linked FC26 match statistics", team_stats, "complete linked MatchStats export")
                players = conn.execute(
                    """SELECT d.player_ea_id,d.team_index,d.minutes_played,d.game_rating,d.stats_json,p.display_name,p.primary_position
                         FROM match_player_detailed_stats d LEFT JOIN player_states p
                           ON p.snapshot_id=? AND p.ea_player_id=d.player_ea_id
                         WHERE d.export_id=? ORDER BY d.game_rating DESC,d.minutes_played DESC LIMIT 44""",
                    (snapshot_id, export["id"]),
                ).fetchall()
                player_facts = []
                for item in players:
                    stats = json.loads(item["stats_json"] or "{}")
                    keys = ("npk_goals", "assists", "npk_expected_goals", "expected_assists", "shots",
                            "shots_on_target", "key_passes", "tackles", "interceptions", "saves", "goals_conceded")
                    player_facts.append({"player_ea_id": int(item["player_ea_id"]), "name": item["display_name"],
                                         "position": item["primary_position"], "minutes": item["minutes_played"],
                                         "rating": item["game_rating"], "stats": {key: stats.get(key) for key in keys if stats.get(key) is not None}})
                fact("match_players", "Player match performances", player_facts, "complete linked MatchStats export")
                if mode == "match_player":
                    if player_ea_id is None:
                        raise ValueError("Select a player from the current match.")
                    participant = next((item for item in player_facts if int(item["player_ea_id"]) == int(player_ea_id)), None)
                    if not participant:
                        raise ValueError("Selected player has no linked performance in this match.")
                    player_team = next((team for team in teams if int(team["team_ea_id"] or -1) == team_id), None)
                    participant_row = next((item for item in players if int(item["player_ea_id"]) == int(player_ea_id)), None)
                    if not player_team or not participant_row or int(participant_row["team_index"]) != int(player_team["team_index"]):
                        raise ValueError("Selected player did not appear for the managed club in this match.")
                    fact("selected_match_player", "Selected player in this match", participant, "complete linked MatchStats participant row")
                    scope = f"fixture:{fixture_id}:player:{player_ea_id}"
            else:
                fact("matchstats_missing", "MatchStats coverage", "No complete linked export for this fixture", "Atlas linkage status")
                if mode == "match_player":
                    if player_ea_id is None:
                        raise ValueError("Select a player from the current match.")
                    appearance = conn.execute(
                        """SELECT p.player_ea_id,p.display_name,p.date,p.rating,p.minutes_played,p.actual_position,
                                  p.join_status,p.fixture_key
                             FROM player_match_performances p JOIN fixtures f ON f.fixture_key=p.fixture_key AND f.career_id=?
                             WHERE p.snapshot_id=? AND f.id=? AND p.player_ea_id=?
                               AND CAST(json_extract(p.raw_json,'$.managed_team_id') AS INTEGER)=?
                               AND COALESCE(p.minutes_played,0)>0 ORDER BY p.date DESC LIMIT 1""",
                        (career_id, snapshot_id, fixture_id, player_ea_id, team_id),
                    ).fetchone()
                    if not appearance:
                        raise ValueError("No recorded managed-team appearance is linked to this player and match.")
                    fact("selected_match_player", "Selected player in this match", {
                        "player_ea_id": int(appearance["player_ea_id"]), "name": appearance["display_name"],
                        "minutes": appearance["minutes_played"], "rating": appearance["rating"],
                        "position": appearance["actual_position"], "fixture_key": appearance["fixture_key"],
                    }, "Atlas player match rating history; detailed MatchStats unavailable")
                    fact("match_player_stats_missing", "Detailed player metrics", "N/D — no linked MatchStats export for this fixture", "Atlas linkage status")
                    scope = f"fixture:{fixture_id}:player:{player_ea_id}"
        else:
            squad = conn.execute(
                """SELECT p.ea_player_id,p.display_name,p.primary_position,p.overall
                     FROM player_states p WHERE p.snapshot_id=? AND p.team_ea_id=? ORDER BY p.display_name""",
                (snapshot_id, team_id),
            ).fetchall()
            loads = conn.execute(
                """SELECT player_ea_id,date,minutes_played,rating FROM player_match_performances
                     WHERE snapshot_id=? AND CAST(json_extract(raw_json,'$.managed_team_id') AS INTEGER)=?
                     ORDER BY date DESC,fixture_key DESC""", (snapshot_id, team_id),
            ).fetchall()
            by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for load in loads:
                player_key = int(load["player_ea_id"])
                if len(by_player[player_key]) < 3:
                    by_player[player_key].append({"minutes": load["minutes_played"], "rating": load["rating"], "date": load["date"]})
            people = []
            for player in squad:
                recent = by_player.get(int(player["ea_player_id"]), [])
                rated = [float(item["rating"]) for item in recent if item.get("rating") is not None]
                people.append({"player_ea_id": int(player["ea_player_id"]), "name": player["display_name"],
                               "position": player["primary_position"], "overall": player["overall"],
                               "last_3_recorded_appearances": len(recent),
                               "last_3_minutes": sum(int(item["minutes"] or 0) for item in recent),
                               "last_3_average_rating": round(sum(rated) / len(rated), 2) if rated else None})
            positions = [str(item.get("position") or "").upper() for item in people]
            gk = sum(pos == "GK" for pos in positions)
            defenders = sum(pos in {"CB", "LCB", "RCB", "SW", "LB", "LWB", "RB", "RWB"} for pos in positions)
            midfielders = sum(pos in {"CDM", "CM", "CAM", "LM", "RM", "RCM", "LCM", "RDM", "LDM"} for pos in positions)
            forwards = sum(pos in {"ST", "CF", "LW", "RW", "LF", "RF"} for pos in positions)
            formations = []
            if len(people) >= 11 and gk >= 1 and defenders >= 3 and midfielders >= 2 and forwards >= 1:
                formations = ["4-3-3", "4-2-3-1", "4-4-2"]
                if defenders >= 3 and midfielders >= 4 and forwards >= 2:
                    formations.append("3-5-2")
            fact("squad", "Current squad and recorded recent load", people, "selected Atlas snapshot and player match ratings")
            fact("formation_options", "Shapes supported by recorded squad positions", formations, "deterministic position-count check")
            fact("opponent", "Upcoming opponent", row["away_team_name"] if int(row["home_team_ea_id"] or -1) == team_id else row["home_team_name"], "fixture calendar only; no opponent style inferred")
            previous = conn.execute(
                """SELECT fixture_id,date,home_team_name,away_team_name FROM fixture_observations
                     WHERE snapshot_id=? AND managed_team_involved=1 AND is_completed=1
                     ORDER BY date DESC LIMIT 1""", (snapshot_id,),
            ).fetchone()
            if previous:
                previous_fact = dict(previous)
                try:
                    previous_fact["days_before_selected_fixture"] = (date.fromisoformat(str(row["date"])) - date.fromisoformat(str(previous["date"]))).days
                except (TypeError, ValueError):
                    previous_fact["days_before_selected_fixture"] = None
                fact("previous_fixture", "Most recent completed fixture and recovery interval", previous_fact, "Atlas fixture calendar")
            following = conn.execute(
                """SELECT fixture_id,date,home_team_name,away_team_name FROM fixture_observations
                     WHERE snapshot_id=? AND managed_team_involved=1 AND COALESCE(is_completed,0)<>1 AND date>?
                     ORDER BY date ASC LIMIT 1""", (snapshot_id, row["date"]),
            ).fetchone()
            if following:
                following_fact = dict(following)
                try:
                    following_fact["days_after_selected_fixture"] = (date.fromisoformat(str(following["date"])) - date.fromisoformat(str(row["date"]))).days
                except (TypeError, ValueError):
                    following_fact["days_after_selected_fixture"] = None
                fact("following_fixture", "Next fixture after this match", following_fact, "Atlas fixture calendar")
        if mode == "match":
            scope = f"fixture:{fixture_id}"
    elif mode == "player":
        if player_ea_id is None:
            raise ValueError("Select a player from the current professional squad.")
        deterministic = get_commission(conn, career_id, snapshot_id)
        player = next((item for item in deterministic.get("players", []) if int(item["player_ea_id"]) == int(player_ea_id)), None)
        if not player:
            raise ValueError("Selected player is not in the current professional squad.")
        player_fields = {key: player.get(key) for key in ("player_ea_id", "display_name", "position", "minutes", "appearances",
                          "season_rating", "recent_rating", "recent_appearances", "sample", "moment", "recommendation", "metrics")}
        fact("player_summary", "Current career performance", player_fields, "Atlas deterministic commission metrics")
        player_state = conn.execute(
            "SELECT * FROM player_states WHERE snapshot_id=? AND ea_player_id=?", (snapshot_id, player_ea_id)
        ).fetchone()
        growth = conn.execute(
            "SELECT * FROM player_growth_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_ea_id)
        ).fetchone()
        attribute_analysis = None
        if player_state:
            try:
                from .server_query_entities import EntityQueryMixin
                from .server_utils import parse_raw
                player_context = dict(player_state)
                player_context["raw"] = parse_raw(player_context.pop("raw_json", None))
                attribute_analysis = EntityQueryMixin._player_analysis(
                    object.__new__(EntityQueryMixin), conn, snapshot, player_context, growth,
                    {"appearances": player.get("appearances"), "goals": player.get("goals"),
                     "assists": player.get("assists"), "average_rating": player.get("season_rating"), "clean_sheets": 0},
                )
            except (KeyError, TypeError, ValueError, sqlite3.Error):
                attribute_analysis = None
        if attribute_analysis:
            fact("player_attributes", "Registered attributes and role profile", {
                "position_group": attribute_analysis.get("position_group_label"),
                "primary_position": attribute_analysis.get("primary_position"),
                "strengths": attribute_analysis.get("strengths"),
                "development_areas": attribute_analysis.get("developmentAreas"),
                "roles": attribute_analysis.get("roles"),
                "position_comparisons": (attribute_analysis.get("comparison") or {}).get("categoryComparisons"),
                "peer_count": (attribute_analysis.get("comparison") or {}).get("peer_count"),
                "attribute_coverage": attribute_analysis.get("dataQuality"),
            }, "Atlas position-aware attribute analysis; not match performance")
        rows = conn.execute(
            """SELECT p.date,p.fixture_key,p.rating,p.minutes_played,p.actual_position,
                      fo.competition_name,fo.home_team_name,fo.away_team_name,fo.home_score,fo.away_score
                 FROM player_match_performances p LEFT JOIN fixtures f ON f.fixture_key=p.fixture_key
                 LEFT JOIN fixture_observations fo ON fo.snapshot_id=p.snapshot_id AND fo.fixture_id=f.id
                 WHERE p.snapshot_id=? AND p.player_ea_id=?
                 ORDER BY p.date DESC,p.fixture_key DESC LIMIT 10""",
            (snapshot_id, player_ea_id),
        ).fetchall()
        fact("player_recent_matches", "Last recorded player appearances", [dict(item) for item in rows], "player match rating history")
        from .match_stats import detailed_player_matches
        detailed_rows = detailed_player_matches(conn, career_id, int(player_ea_id), season_indices=[int(snapshot["season_index"])])[:10]
        compact_matches = [{"date": item.get("date"), "competition": item.get("competitionName"),
                            "home": item.get("homeTeamName"), "away": item.get("awayTeamName"),
                            "score": [item.get("homeScore"), item.get("awayScore")],
                            "stats": {key: item["stats"].get(key) for key in ("npk_goals", "assists", "npk_expected_goals", "expected_assists",
                                       "shots", "key_passes", "tackles", "interceptions", "game_rating")
                                      if item["stats"].get(key) is not None}}
                           for item in detailed_rows]
        if compact_matches:
            fact("player_matchstats", "Player detail from linked MatchStats", compact_matches, "complete linked MatchStats exports; partial season coverage")
        else:
            fact("player_matchstats_missing", "Player MatchStats", "No linked player MatchStats rows in this season", "Atlas linkage status")
        scope = f"player:{player_ea_id}"
    elif mode == "team_identity":
        identity = analyze_team_identity(conn, career_id, snapshot_id)
        fact("team_statistical_profile", "Team style evidence from linked matches", {
            "detailed_matches": identity["detailed_matches"], "completed_matches": identity["completed_matches"],
            "coverage_pct": identity["coverage_pct"], "metrics": identity["metrics"],
            "sample_sufficient": identity["style_sample_sufficient"],
            "unavailable": identity["unavailable"],
        }, "calculated from complete linked MatchStats exports; unavailable metrics remain null")
        fact("opponent_profiles", "Results against measured opponent shot-volume profiles",
             identity["opponent_profiles"], "ranked opponent team-shot counts and recorded match outcomes; association only")
        scope = f"team_identity:season:{int(snapshot['season_index'])}"
    else:
        raise ValueError("Unsupported technical commission report type.")

    from .settings import application_language, normalize_language
    context = {"mode": mode, "career_id": int(career_id), "snapshot_id": int(snapshot_id),
               "career_date": snapshot["career_date"], "managed_team": snapshot["managed_team_name"],
               "season_index": int(snapshot["season_index"]), "report_version": REPORT_VERSION,
               "language": normalize_language(language_override) if language_override else application_language(), "facts": facts}
    if mode == "next_match":
        options = next((item.get("value") for item in facts if item["id"] == "formation_options"), [])
        context["allowed_formations"] = options
    return context, [str(item["id"]) for item in facts], scope


def _report_source_hash(context: dict[str, Any], career_id: int, mode: str, scope: str) -> str:
    stable = {"career_id": int(career_id), "mode": mode, "scope_key": scope,
              "season_index": context.get("season_index"), "report_version": REPORT_VERSION,
              "language": context.get("language"),
              "facts": context.get("facts", []), "allowed_formations": context.get("allowed_formations")}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _report_fact_map(context: dict[str, Any]) -> dict[str, Any]:
    return {str(item.get("id")): item.get("value") for item in context.get("facts", []) if isinstance(item, dict)}


def _commission_note(context: dict[str, Any]) -> dict[str, Any] | None:
    if context.get("mode") != "match":
        return None
    facts = _report_fact_map(context)
    match = facts.get("match") or {}
    if not match.get("completed") or match.get("managed_score") is None or match.get("opponent_score") is None:
        return None
    goals_for, goals_against = int(match["managed_score"]), int(match["opponent_score"])
    opponent = str(match.get("away") if match.get("managed_team_side") == "home" else match.get("home") or "adversário")
    language = context.get("language", "pt-BR")
    refs = ["match"]
    history = facts.get("opponent_history") or {}
    first_recorded_win = int(history.get("previous_wins") or 0) == 0
    if goals_for > goals_against and goals_for - goals_against >= 3:
        if first_recorded_win:
            refs.append("opponent_history")
            templates = {
                "pt-BR": f"Professor, essa entra para a história registrada da carreira: grande vitória por {goals_for}–{goals_against} contra {opponent}, primeiro triunfo registrado sobre o rival.",
                "en-GB": f"Professor, this goes into the career record: a great {goals_for}–{goals_against} win over {opponent}, the first recorded victory against this opponent.",
                "es-ES": f"Profesor, queda en la historia registrada de la carrera: gran victoria por {goals_for}–{goals_against} ante {opponent}, primer triunfo registrado frente al rival.",
            }
        else:
            templates = {
                "pt-BR": f"Grande vitória da equipe: {goals_for}–{goals_against} contra {opponent}.",
                "en-GB": f"A big team win: {goals_for}–{goals_against} against {opponent}.",
                "es-ES": f"Gran victoria del equipo: {goals_for}–{goals_against} ante {opponent}.",
            }
    elif goals_for > goals_against:
        templates = {"pt-BR": f"Vitória registrada: {goals_for}–{goals_against} contra {opponent}.",
                     "en-GB": f"Recorded win: {goals_for}–{goals_against} against {opponent}.",
                     "es-ES": f"Victoria registrada: {goals_for}–{goals_against} ante {opponent}."}
    elif goals_for == goals_against:
        templates = {"pt-BR": f"Empate registrado: {goals_for}–{goals_against} contra {opponent}.",
                     "en-GB": f"Recorded draw: {goals_for}–{goals_against} against {opponent}.",
                     "es-ES": f"Empate registrado: {goals_for}–{goals_against} ante {opponent}."}
    else:
        templates = {"pt-BR": f"Resultado da partida: derrota por {goals_for}–{goals_against} contra {opponent}.",
                     "en-GB": f"Match result: a {goals_for}–{goals_against} defeat against {opponent}.",
                     "es-ES": f"Resultado del partido: derrota por {goals_for}–{goals_against} ante {opponent}."}
    return {"text": templates.get(language, templates["pt-BR"]), "fact_refs": refs}


def _deterministic_match_summary(context: dict[str, Any]) -> dict[str, Any] | None:
    if context.get("mode") not in {"match", "match_player"}:
        return None
    match = _report_fact_map(context).get("match") or {}
    if match.get("managed_score") is None or match.get("opponent_score") is None:
        return None
    team = str(context.get("managed_team") or "Managed team")
    opponent = str(match.get("away") if match.get("managed_team_side") == "home" else match.get("home") or "opponent")
    gf, ga = int(match["managed_score"]), int(match["opponent_score"])
    language = context.get("language", "pt-BR")
    outcome = ("venceu" if gf > ga else "empatou com" if gf == ga else "perdeu para") if language == "pt-BR" else (
        "beat" if gf > ga else "drew with" if gf == ga else "lost to") if language == "en-GB" else (
        "venció a" if gf > ga else "empató con" if gf == ga else "perdió ante")
    if context.get("mode") == "match_player":
        player = _report_fact_map(context).get("selected_match_player") or {}
        name = str(player.get("name") or "Player")
        stats = player.get("stats") or {}
        rating = player.get("rating")
        minute = player.get("minutes")
        if language == "pt-BR":
            text = f"{name}: {minute if minute is not None else 'N/D'} min, nota {rating if rating is not None else 'N/D'}; {int(stats['npk_goals'])} gols e {int(stats['assists'])} assistências registrados." if stats.get("npk_goals") is not None and stats.get("assists") is not None else f"{name}: atuação individual baseada nos minutos, nota e estatísticas disponíveis nesta partida."
        elif language == "en-GB":
            text = f"{name}: {minute if minute is not None else 'N/D'} min, rating {rating if rating is not None else 'N/D'}; {int(stats['npk_goals'])} goals and {int(stats['assists'])} assists recorded." if stats.get("npk_goals") is not None and stats.get("assists") is not None else f"{name}: individual review based on the minutes, rating and statistics available for this match."
        else:
            text = f"{name}: {minute if minute is not None else 'N/D'} min, nota {rating if rating is not None else 'N/D'}; {int(stats['npk_goals'])} goles y {int(stats['assists'])} asistencias registrados." if stats.get("npk_goals") is not None and stats.get("assists") is not None else f"{name}: análisis individual basado en los minutos, la nota y las estadísticas disponibles en este partido."
        return {"text": text, "fact_refs": ["selected_match_player"]}
    score = f"{gf}–{ga}"
    comp = str(match.get("competition") or "")
    if language == "pt-BR":
        text = f"{team} {outcome} {opponent} por {score}{f' na {comp}' if comp else ''}."
    elif language == "en-GB":
        text = f"{team} {outcome} {opponent} {score}{f' in {comp}' if comp else ''}."
    else:
        text = f"{team} {outcome} {opponent} por {score}{f' en {comp}' if comp else ''}."
    return {"text": text, "fact_refs": ["match"]}


def _deterministic_report_summary(context: dict[str, Any]) -> dict[str, Any] | None:
    match_summary = _deterministic_match_summary(context)
    if match_summary:
        return match_summary
    facts = _report_fact_map(context)
    language = context.get("language", "pt-BR")
    if context.get("mode") == "team_identity":
        profile = facts.get("team_statistical_profile") or {}
        detailed, total, coverage = profile.get("detailed_matches"), profile.get("completed_matches"), profile.get("coverage_pct")
        if detailed is not None and total is not None:
            text = {"pt-BR": f"Leitura da equipe baseada em {detailed} de {total} partidas completas detalhadas ({coverage}% de cobertura).",
                    "en-GB": f"Team review based on {detailed} of {total} completed fixtures with detailed data ({coverage}% coverage).",
                    "es-ES": f"Análisis del equipo basado en {detailed} de {total} partidos completos con datos detallados ({coverage}% de cobertura)."}.get(language)
            return {"text": text, "fact_refs": ["team_statistical_profile"]}
    if context.get("mode") == "player":
        player = facts.get("player_summary") or {}
        name, position = player.get("display_name") or "Player", player.get("position") or "N/D"
        minutes, appearances, rating = player.get("minutes"), player.get("appearances"), player.get("season_rating")
        sample = (player.get("sample") or {}).get("label") or "N/D"
        text = {"pt-BR": f"{name} ({position}): {minutes if minutes is not None else 'N/D'} min, {appearances if appearances is not None else 'N/D'} atuações, nota média {rating if rating is not None else 'N/D'}. Amostra: {sample}.",
                "en-GB": f"{name} ({position}): {minutes if minutes is not None else 'N/D'} min, {appearances if appearances is not None else 'N/D'} appearances, average rating {rating if rating is not None else 'N/D'}. Sample: {sample}.",
                "es-ES": f"{name} ({position}): {minutes if minutes is not None else 'N/D'} min, {appearances if appearances is not None else 'N/D'} apariciones, nota media {rating if rating is not None else 'N/D'}. Muestra: {sample}."}.get(language)
        return {"text": text, "fact_refs": ["player_summary"]}
    return None


def _evidence_confidence(context: dict[str, Any], mode: str) -> float:
    facts = _report_fact_map(context)
    if mode == "team_identity":
        coverage = (facts.get("team_statistical_profile") or {}).get("coverage_pct")
        return max(0.0, min(100.0, float(coverage))) if coverage is not None else 0.0
    if mode == "player":
        sample = (facts.get("player_summary") or {}).get("sample") or {}
        return 95.0 if sample.get("reliable") else 90.0 if sample.get("usable") else 75.0
    if mode == "match_player" and "match_player_stats_missing" in facts:
        return 75.0
    if mode == "match" and "matchstats_missing" in facts:
        return 75.0
    return 100.0


def _claim_has_structural_conflict(context: dict[str, Any], mode: str, text: str) -> bool:
    folded = text.casefold()
    facts = _report_fact_map(context)
    match = facts.get("match") or {}
    absent_terms = ("posse de bola", "possession", "posesión", "pressão alta", "high press", "presión alta",
                    "titular", "starting xi", "starting eleven", "alineación titular", "lesão", "injury",
                    "injured", "suspensão", "suspended", "availability", "disponibilidade", "disponible")
    if any(term in folded for term in absent_terms) and mode in {"match", "match_player", "player", "next_match", "team_identity"}:
        return True
    # A scoreline alone establishes the result, not territorial or statistical
    # dominance. Atlas currently has no validated dominance metric to support it.
    dominance_terms = ("dominated", "dominó", "dominou", "dominó el partido", "dominó el encuentro",
                       "controlled the match", "controlled proceedings", "controló el partido",
                       "controló el encuentro", "controlou a partida", "controlou o jogo")
    if mode in {"match", "match_player"} and any(term in folded for term in dominance_terms):
        return True
    unsupported_judgements = ("solid defence", "solid defense", "defesa sólida", "defesa solida",
                              "defensa sólida", "defensa solida", "weak defence", "weak defense",
                              "defesa frágil", "defensa débil", "clinical finishing", "finalização clínica",
                              "definición clínica", "excellent defending", "excelente defesa", "gran defensa")
    if mode in {"match", "match_player"} and (
        any(term in folded for term in unsupported_judgements)
        or ("defensa" in folded and "sólid" in folded)
        or ("defesa" in folded and "sólid" in folded)
        or ("defence" in folded and "solid" in folded)
        or ("defense" in folded and "solid" in folded)
    ):
        return True
    if mode in {"match", "match_player"}:
        side = match.get("managed_team_side")
        home_words = ("home team", "at home", "mandante", "equipe da casa", "time da casa", "local")
        away_words = ("away team", "away side", "visiting team", "visitante", "equipe visitante", "fora de casa", "visitante")
        if side == "home" and any(term in folded for term in away_words):
            return True
        if side == "away" and any(term in folded for term in home_words):
            return True
        if any(term in folded for term in ("histórica", "histórico", "historic", "histórica", "first ever", "primeiro triunfo", "primer triunfo")):
            return True
    return False


def _ensure_report_cache(conn: Any) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS technical_commission_report_cache (
        career_id INTEGER NOT NULL REFERENCES careers(id), snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        mode TEXT NOT NULL, scope_key TEXT NOT NULL, model TEXT NOT NULL, source_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL, generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(career_id,snapshot_id,mode,scope_key,model))""")


def get_cached_commission_report(conn: Any, career_id: int, snapshot_id: int, mode: str,
                                 fixture_id: int | None = None, player_ea_id: int | None = None,
                                 model: str | None = None, language: str | None = None) -> dict[str, Any]:
    """Read a persisted report without contacting Ollama; exact facts can reuse prior snapshots."""
    context, _, scope = _briefing_facts(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id, language)
    selected = model or os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='technical_commission_report_cache'").fetchone()
    if not exists:
        return {"state": "missing", "cached": False, "model": selected, "scope_key": scope}
    current_hash = _report_source_hash(context, career_id, mode, scope)
    row = conn.execute(
        """SELECT snapshot_id,source_hash,payload_json,generated_at FROM technical_commission_report_cache
             WHERE career_id=? AND mode=? AND scope_key=? AND model=? AND source_hash=?
             ORDER BY generated_at DESC,snapshot_id DESC LIMIT 1""",
        (career_id, mode, scope, selected, current_hash),
    ).fetchone()
    if row:
        value = json.loads(row["payload_json"])
        return {"state": "ready", "cached": True, "model": selected, "scope_key": scope, "source_hash": current_hash,
                "snapshot_id": int(row["snapshot_id"]), "generated_at": row["generated_at"], "result": value}
    row = conn.execute(
        """SELECT snapshot_id,source_hash,payload_json,generated_at FROM technical_commission_report_cache
             WHERE career_id=? AND mode=? AND scope_key=? AND model=?
             ORDER BY generated_at DESC,snapshot_id DESC LIMIT 1""",
        (career_id, mode, scope, selected),
    ).fetchone()
    auto_key = f"auto:{career_id}:{mode}:{scope}:{selected}:{current_hash}"
    with _REPORT_JOB_LOCK:
        job_id = _REPORT_JOB_KEYS.get(auto_key)
        job = _REPORT_JOBS.get(job_id) if job_id else None
    if not row:
        if job and job.get("status") in {"queued", "running"}:
            return {"state": job["status"], "cached": False, "model": selected, "scope_key": scope,
                    "source_hash": current_hash, "job_id": job_id}
        return {"state": "missing", "cached": False, "model": selected, "scope_key": scope, "source_hash": current_hash}
    value = json.loads(row["payload_json"])
    if str(row["source_hash"]) == current_hash:
        return {"state": "ready", "cached": True, "model": selected, "scope_key": scope, "source_hash": current_hash,
                "snapshot_id": int(row["snapshot_id"]), "generated_at": row["generated_at"], "result": value}
    return {"state": "stale", "cached": True, "model": selected, "scope_key": scope,
            "source_hash": current_hash, "snapshot_id": int(row["snapshot_id"]), "generated_at": row["generated_at"], "result": value}


def get_commission_report(conn: Any, career_id: int, snapshot_id: int, mode: str,
                          fixture_id: int | None = None, player_ea_id: int | None = None,
                          model: str | None = None, force_refresh: bool = False,
                          language: str | None = None) -> dict[str, Any]:
    """Generate a cited, cached, local Ollama report from one selected Atlas context."""
    context, fact_ids, scope = _briefing_facts(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id, language)
    selected = model or os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
    _ensure_report_cache(conn)
    source_hash = _report_source_hash(context, career_id, mode, scope)
    cached = conn.execute(
        """SELECT source_hash,payload_json FROM technical_commission_report_cache
             WHERE career_id=? AND mode=? AND scope_key=? AND model=? AND source_hash=?
             ORDER BY generated_at DESC,snapshot_id DESC LIMIT 1""",
        (career_id, mode, scope, selected, source_hash),
    ).fetchone()
    if cached and not force_refresh:
        value = json.loads(cached["payload_json"])
        value["cached"] = True
        conn.execute("""INSERT INTO technical_commission_report_cache(career_id,snapshot_id,mode,scope_key,model,source_hash,payload_json)
             VALUES(?,?,?,?,?,?,?) ON CONFLICT(career_id,snapshot_id,mode,scope_key,model) DO UPDATE SET
             source_hash=excluded.source_hash,payload_json=excluded.payload_json""",
            (career_id, snapshot_id, mode, scope, selected, source_hash,
             json.dumps(value, ensure_ascii=False, sort_keys=True)))
        return value
    tags = ollama_models(timeout=2.0)
    if not tags.get("available") or selected not in tags.get("models", []):
        return {"available": False, "fallback": True, "cached": False,
                "message": "Ollama indisponível ou modelo não instalado. Os dados do Atlas continuam disponíveis.", "context": context}
    language = str(context.get("language") or "pt-BR")
    language_name = {"pt-BR": "Brazilian Portuguese", "en-GB": "British English", "es-ES": "Spanish"}.get(language, "Brazilian Portuguese")
    tasks = {
        "pt-BR": {
            "next_match": "Prepare a próxima partida com calendário, minutos e posições exportadas. Escolha apenas formação de allowed_formations; não infira lesões, disponibilidade, escalação ou estilo rival.",
            "player": "Analise aptidões comparáveis, amostra, minutos e MatchStats. Não declare hierarquia, titularidade, causa ou comparação ausente dos fatos.",
            "match_player": "Analise somente o jogador selecionado nesta partida, usando avaliação, posição, minutos e estatísticas individuais. Não recomende titularidade.",
            "team_identity": "Descreva padrões calculados nas métricas agregadas e compare perfis de adversário já calculados. Associação observada não prova causa; não crie estilo tático sem métricas.",
            "match": "Analise resultado e indicadores registrados. Confira mando pelos campos home e away e mantenha a mesma ordem no placar. Destaques devem corresponder aos dados do jogador.",
        },
        "en-GB": {
            "next_match": "Prepare for the next fixture using the calendar, recorded minutes and exported positions. Choose only a shape in allowed_formations; do not infer injuries, availability, a confirmed line-up or opponent style.",
            "player": "Review comparable registered attributes, sample, minutes and MatchStats. Do not claim hierarchy, starting status, causation or comparisons absent from the facts.",
            "match_player": "Review only the selected player's contribution in this fixture using the available rating, position, minutes and individual statistics. Do not recommend starting status.",
            "team_identity": "Describe patterns calculated from aggregate metrics and compare the opponent profiles already calculated. Association does not prove causation; do not invent tactical style without metrics.",
            "match": "Analyse the result and recorded indicators. Check home and away from those exact fields and keep the score in the same order. Player highlights must match that player's records.",
        },
        "es-ES": {
            "next_match": "Prepara el próximo partido usando calendario, minutos y posiciones exportadas. Elige solo una formación de allowed_formations; no infieras lesiones, disponibilidad, alineación ni estilo rival.",
            "player": "Analiza atributos comparables, muestra, minutos y MatchStats. No afirmes jerarquía, titularidad, causalidad ni comparaciones ausentes de los hechos.",
            "match_player": "Analiza solo al jugador seleccionado en este partido con nota, posición, minutos y estadísticas individuales. No recomiendes titularidad.",
            "team_identity": "Describe patrones calculados en métricas agregadas y compara perfiles rivales ya calculados. Asociación no demuestra causalidad; no inventes estilo táctico sin métricas.",
            "match": "Analiza el resultado y los indicadores registrados. Comprueba local y visitante en esos campos y conserva el orden del marcador. Los destacados deben coincidir con los datos del jugador.",
        },
    }
    language_tasks = tasks.get(language, tasks["pt-BR"])
    task = language_tasks.get(mode, language_tasks["match"])
    system = (f"You are Atlas's evidence-bound technical commission analyst. Write every text field only in {language_name}. "
              "Return ONLY valid JSON with exactly these keys: summary ({text, fact_refs}), observations, recommendations, strengths, development_areas, training_suggestions, formation. "
              "Every claim must cite supplied fact IDs. Reconcile team side, player identity, score order, units and sample before writing. "
              "Never convert missing values to zero. Do not infer possession, pressure, tactical instructions, causation, injury, availability, starting XI, hierarchy or historical significance. "
              "Use the Atlas sample label verbatim. Translate internal metric keys into plain football language (npk_goals means non-penalty goals; never print raw field keys). A scoreline alone proves the result, not dominance or control of play. Return no more than three short claims across all lists. Keep each item to one checkable claim. Omit a claim if evidence is incomplete or contradictory; do not fill every list. "
              "Use strengths/development/training lists only for player modes. For team identity, describe measured associations without causal language. " + task)
    allowed_shapes = context.get("allowed_formations") or []
    formation_schema = {"type": "null"}
    if mode == "next_match" and allowed_shapes:
        formation_schema = {"type": "object", "additionalProperties": False,
                            "properties": {"shape": {"type": "string", "enum": allowed_shapes},
                                           "reason": {"type": "string", "maxLength": 500},
                                           "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                            "required": ["shape", "reason", "fact_refs"]}
    response_schema = {"type": "object", "additionalProperties": False,
                       "properties": {"summary": {"type": "object", "additionalProperties": False,
                                                   "properties": {"text": {"type": "string", "maxLength": 700},
                                                                  "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                   "required": ["text", "fact_refs"]},
                                      "observations": {"type": "array", "maxItems": 3,
                                                       "items": {"type": "object", "additionalProperties": False,
                                                                 "properties": {"text": {"type": "string", "maxLength": 500},
                                                                                "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                                 "required": ["text", "fact_refs"]}},
                                      "recommendations": {"type": "array", "maxItems": 3,
                                                          "items": {"type": "object", "additionalProperties": False,
                                                                    "properties": {"text": {"type": "string", "maxLength": 500},
                                                                                   "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                                    "required": ["text", "fact_refs"]}},
                                      "strengths": {"type": "array", "maxItems": 6,
                                                    "items": {"type": "object", "additionalProperties": False,
                                                              "properties": {"text": {"type": "string", "maxLength": 500},
                                                                             "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                              "required": ["text", "fact_refs"]}},
                                      "development_areas": {"type": "array", "maxItems": 6,
                                                            "items": {"type": "object", "additionalProperties": False,
                                                                      "properties": {"text": {"type": "string", "maxLength": 500},
                                                                                     "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                                      "required": ["text", "fact_refs"]}},
                                      "training_suggestions": {"type": "array", "maxItems": 6,
                                                               "items": {"type": "object", "additionalProperties": False,
                                                                         "properties": {"text": {"type": "string", "maxLength": 500},
                                                                                        "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                                         "required": ["text", "fact_refs"]}},
                                      "formation": formation_schema},
                       "required": ["summary", "observations", "recommendations", "strengths", "development_areas", "training_suggestions", "formation"]}
    body = {"model": selected, "stream": False, "format": response_schema, "think": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(context, ensure_ascii=False, sort_keys=True)}],
            "keep_alive": "10m", "options": {"temperature": 0.0, "num_predict": 1000}}
    base = os.environ.get("ATLAS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        timeout = min(300.0, max(20.0, float(os.environ.get("ATLAS_OLLAMA_TIMEOUT_SECONDS", "240"))))
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        report = json.loads(raw.get("message", {}).get("content", "{}"))
        if not isinstance(report, dict):
            raise ValueError("schema inválido")
        valid_ids = set(fact_ids)
        default_refs = {"match": ["match", "matchstats", "match_players"],
                        "match_player": ["match", "matchstats", "match_players", "selected_match_player"],
                        "player": ["player_summary", "player_recent_matches", "player_matchstats"],
                        "team_identity": ["team_statistical_profile", "opponent_profiles"],
                        "next_match": ["match", "squad", "formation_options", "previous_fixture", "following_fixture"]}
        safe_default_refs = [item for item in default_refs.get(mode, []) if item in valid_ids]

        summary = report.get("summary")
        if isinstance(summary, str):
            summary = {"text": summary, "fact_refs": safe_default_refs}
        if not isinstance(summary, dict):
            summary = {"text": "Análise gerada a partir do contexto selecionado no Atlas.", "fact_refs": safe_default_refs}
        summary_text = summary.get("text") if isinstance(summary.get("text"), str) else "Análise gerada a partir dos dados registrados no Atlas."
        summary_refs = summary.get("fact_refs")
        if not isinstance(summary_refs, list) or not summary_refs or not set(summary_refs).issubset(valid_ids):
            summary_refs = safe_default_refs
        report["summary"] = {"text": summary_text[:700], "fact_refs": summary_refs}
        for key in ("observations", "recommendations", "strengths", "development_areas", "training_suggestions"):
            values = report.get(key) if isinstance(report.get(key), list) else []
            cleaned = []
            for item in values[:8]:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                refs = item.get("fact_refs")
                if not isinstance(refs, list) or not refs or not set(refs).issubset(valid_ids):
                    continue
                cleaned.append({"text": item["text"][:500], "fact_refs": refs})
            report[key] = cleaned
        if mode not in {"player", "match_player"}:
            for key in ("strengths", "development_areas", "training_suggestions"):
                report[key] = []
        if mode == "team_identity":
            # A citation to the broad team profile alone cannot make an absent
            # metric present. Drop text that claims unavailable tactical data.
            unavailable_terms = ("posse", "possessão", "pressão", "linha defensiva", "altura da linha", "formação")
            for key in ("observations", "recommendations"):
                report[key] = [item for item in report[key]
                               if not any(term in item["text"].casefold() for term in unavailable_terms)]
            if any(term in report["summary"]["text"].casefold() for term in unavailable_terms):
                report["summary"] = {
                    "text": "Leitura limitada às métricas de equipe registradas e aos resultados por perfil de finalizações dos adversários.",
                    "fact_refs": safe_default_refs,
                }
        formation = report.get("formation")
        report["formation"] = formation
        if mode != "next_match":
            report["formation"] = None
        elif formation is not None:
            allowed = set(context.get("allowed_formations") or [])
            if not isinstance(formation, dict) or formation.get("shape") not in allowed:
                report["formation"] = None
            else:
                reason = formation.get("reason") if isinstance(formation.get("reason"), str) else ""
                forbidden = ("disponibilidade", "disponível", "lesão", "suspensão", "fisicamente", "fadiga", "cansaço", "confiabilidade baixa")
                if any(term in reason.casefold() for term in forbidden):
                    reason = "Esquema compatível com as posições registradas; o Atlas não confirma condição física ou disponibilidade."
                report["formation"] = {"shape": formation["shape"], "reason": reason[:500],
                                       "fact_refs": [item for item in ("formation_options", "squad") if item in valid_ids]}
        if report["formation"] is None and mode == "next_match":
            report["recommendations"] = [item for item in report["recommendations"]
                                         if not any(term in item["text"].casefold() for term in ("disponibilidade", "disponível", "lesão", "suspensão", "fisicamente", "fadiga", "cansaço"))]
        if mode == "next_match":
            blocked = ("disponibilidade", "disponível", "lesão", "suspensão", "fisicamente", "fadiga", "cansaço", "carga equilibrada", "boa condição")
            if any(term in report["summary"]["text"].casefold() for term in blocked):
                report["summary"]["text"] = "Preparação baseada no calendário e na carga de minutos registrada para o elenco. O Atlas não registra condição física, lesões ou suspensões."
                report["summary"]["fact_refs"] = [item for item in ("match", "squad", "previous_fixture", "following_fixture") if item in valid_ids]
        elif mode == "player":
            blocked = ("disponibilidade", "disponível", "lesão", "suspensão", "fisicamente", "fadiga", "confiabilidade baixa", "baixa confiabilidade")
            if any(term in report["summary"]["text"].casefold() for term in blocked):
                report["summary"]["text"] = "Relatório baseado nas avaliações, minutos, amostra e MatchStats ligados a este jogador no recorte selecionado."
                report["summary"]["fact_refs"] = [item for item in ("player_summary", "player_recent_matches", "player_matchstats") if item in valid_ids]
        deterministic_summary = _deterministic_report_summary(context)
        if deterministic_summary:
            report["summary"] = deterministic_summary
        deterministic_note = _commission_note(context)
        if deterministic_note:
            report["commission_note"] = deterministic_note

        claim_rows: list[dict[str, Any]] = []
        structurally_rejected = 0
        for key in ("summary", "observations", "recommendations", "strengths", "development_areas", "training_suggestions"):
            if key == "summary" and deterministic_summary:
                continue
            values = report.get(key) if key == "summary" else report.get(key, [])
            values = [values] if key == "summary" else values
            for index, item in enumerate(values or []):
                if _claim_has_structural_conflict(context, mode, str(item.get("text") or "")):
                    structurally_rejected += 1
                    continue
                claim_rows.append({"claim_id": f"{key}:{index}", "text": item["text"], "fact_refs": item["fact_refs"]})
        if isinstance(report.get("formation"), dict):
            claim_rows.append({"claim_id": "formation:0", "text": str(report["formation"].get("reason") or ""),
                               "fact_refs": report["formation"].get("fact_refs") or []})
        verification_schema = {"type": "object", "additionalProperties": False,
                               "properties": {"supported_claim_ids": {"type": "array", "items": {"type": "string"}},
                                              "unsupported_claim_ids": {"type": "array", "items": {"type": "string"}}},
                               "required": ["supported_claim_ids", "unsupported_claim_ids"]}
        supported_ids: set[str] = set()
        if claim_rows:
            verify_body = {"model": selected, "stream": False, "format": verification_schema, "think": False,
                           "options": {"temperature": 0, "num_predict": 500},
                           "messages": [
                               {"role": "system", "content": f"You are a strict fact checker. The report is written in {language_name}; do not rewrite it. For each claim ID, mark it supported only when its full meaning, subject, direction, number, unit and scope follow directly from the supplied facts. A valid citation ID alone is insufficient. Reject inference, contradictory home/away, unsupported historical claims, tactics, lineup and availability. Return only the requested JSON."},
                               {"role": "user", "content": json.dumps({"facts": context["facts"], "claims": claim_rows}, ensure_ascii=False, sort_keys=True)}]}
            verify_req = urllib.request.Request(base + "/api/chat", data=json.dumps(verify_body, ensure_ascii=False).encode("utf-8"),
                                                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(verify_req, timeout=timeout) as response:
                checked = json.loads(response.read().decode("utf-8"))
            checked_json = json.loads(checked.get("message", {}).get("content", "{}"))
            if not isinstance(checked_json.get("supported_claim_ids"), list):
                raise ValueError("verificador de coerência inválido")
            supported_ids = set(str(item) for item in checked_json["supported_claim_ids"])
            supported_ids.intersection_update(item["claim_id"] for item in claim_rows)
        total_claims = len(claim_rows) + structurally_rejected
        coherent_pct = round(100 * len(supported_ids) / total_claims, 1) if total_claims else 100.0
        for key in ("observations", "recommendations", "strengths", "development_areas", "training_suggestions"):
            report[key] = [item for index, item in enumerate(report.get(key) or []) if f"{key}:{index}" in supported_ids]
        if report.get("formation") is not None and "formation:0" not in supported_ids:
            report["formation"] = None
        if not deterministic_summary and "summary:0" not in supported_ids:
            fallback_summary = {"pt-BR": "N/D — o resumo gerado não atingiu a confiança mínima de evidência.",
                                "en-GB": "N/A — the generated summary did not meet the evidence confidence threshold.",
                                "es-ES": "N/D — el resumen generado no alcanzó el umbral de confianza de evidencia."}.get(language, "N/D")
            report["summary"] = {"text": fallback_summary, "fact_refs": safe_default_refs}
        evidence_pct = _evidence_confidence(context, mode)
        # Only verifier-approved free text remains visible. Confidence therefore
        # reflects the evidence coverage of the published report; draft acceptance
        # is kept separately for tuning the prompt.
        final_coherence_pct = 100.0 if (deterministic_summary or "summary:0" in supported_ids or not claim_rows) else coherent_pct
        confidence_pct = round(min(final_coherence_pct, evidence_pct), 1)
        quality_score = round(confidence_pct / 10, 1)
        review_required = confidence_pct < 90.0
        if review_required:
            for key in ("observations", "recommendations", "strengths", "development_areas", "training_suggestions"):
                report[key] = []
            report["formation"] = None
        result = {"available": True, "fallback": False, "cached": False, "model": selected,
                  "mode": mode, "scope_key": scope, "report": report, "fact_catalog": context["facts"],
                  "quality_score": quality_score, "confidence_pct": confidence_pct,
                  "coherent_claims_pct": final_coherence_pct, "draft_claim_acceptance_pct": coherent_pct,
                  "evidence_coverage_pct": evidence_pct,
                  "verified_claims": len(supported_ids), "review_required": review_required,
                  "rejected_claims": total_claims - len(supported_ids),
                  "minimum_quality_score": 8.5, "minimum_confidence_pct": 90}
        conn.execute("""INSERT INTO technical_commission_report_cache(career_id,snapshot_id,mode,scope_key,model,source_hash,payload_json)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(career_id,snapshot_id,mode,scope_key,model) DO UPDATE SET
            source_hash=excluded.source_hash,payload_json=excluded.payload_json,generated_at=CURRENT_TIMESTAMP""",
            (career_id, snapshot_id, mode, scope, selected, source_hash,
             json.dumps(result, ensure_ascii=False, sort_keys=True)))
        return result
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, TimeoutError) as exc:
        detail = str(exc).replace("\n", " ")[:120]
        return {"available": False, "fallback": True, "cached": False, "model": selected,
                "message": f"Análise local não validada; métricas do Atlas preservadas ({exc.__class__.__name__}: {detail})."}


def start_commission_report_job(career_id: int, work: Any, dedupe_key: str | None = None) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    with _REPORT_JOB_LOCK:
        if dedupe_key and dedupe_key in _REPORT_JOB_KEYS:
            existing_id = _REPORT_JOB_KEYS[dedupe_key]
            existing = _REPORT_JOBS.get(existing_id)
            if existing and int(existing.get("career_id") or -1) == int(career_id):
                return {"job_id": existing_id, "status": str(existing.get("status") or "queued"), "deduplicated": True}
        _REPORT_JOBS[job_id] = {"career_id": int(career_id), "status": "queued", "result": None}
        if dedupe_key:
            _REPORT_JOB_KEYS[dedupe_key] = job_id

    def run() -> None:
        with _REPORT_JOB_LOCK:
            job = _REPORT_JOBS.get(job_id)
            if job is not None:
                job["status"] = "running"
        try:
            result = work()
            with _REPORT_JOB_LOCK:
                job = _REPORT_JOBS.get(job_id)
                if job is not None:
                    job["result"] = result
                    job["status"] = "complete"
        except Exception as exc:  # surfaced to the UI as a failed report, not a server crash
            with _REPORT_JOB_LOCK:
                job = _REPORT_JOBS.get(job_id)
                if job is not None:
                    job["error"] = f"{exc.__class__.__name__}: {str(exc)[:180]}"
                    job["status"] = "failed"

    _REPORT_EXECUTOR.submit(run)
    return {"job_id": job_id, "status": "queued"}


def queue_auto_commission_reports(database: Any, career_id: int, fixture_id: int,
                                  snapshot_id: int | None = None) -> list[dict[str, str]]:
    """Queue one persisted match report and refresh the season identity after a new result is linked."""
    from .db import Database
    if not isinstance(database, Database):
        raise TypeError("Automatic commission reports require the active Atlas Database.")
    with database.connect() as conn:
        _ensure_report_cache(conn)
        if snapshot_id is None:
            latest = conn.execute(
                """SELECT s.id FROM snapshots s JOIN fixture_observations fo ON fo.snapshot_id=s.id
                     WHERE s.career_id=? AND fo.fixture_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
                     ORDER BY s.import_sequence DESC LIMIT 1""", (career_id, fixture_id),
            ).fetchone()
            snapshot_id = int(latest["id"]) if latest else None
        if snapshot_id is None:
            return []
        selected_model = os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
        snapshot = conn.execute("SELECT managed_team_ea_id FROM snapshots WHERE id=? AND career_id=?",
                                (snapshot_id, career_id)).fetchone()
        team_id = int(snapshot["managed_team_ea_id"] or -1) if snapshot else -1
        pending: list[tuple[str, int | None, int | None]] = [("match", fixture_id, None),
                                                            ("team_identity", None, None)]
        if team_id > 0:
            pending.extend(("match_player", fixture_id, player_id) for player_id in
                           _managed_player_ids_for_fixture(conn, career_id, int(snapshot_id), fixture_id, team_id))
        scheduled = []
        for mode, report_fixture, player_id in pending:
            try:
                context, _, scope = _briefing_facts(conn, career_id, snapshot_id, mode, report_fixture, player_id)
                source_hash = _report_source_hash(context, career_id, mode, scope)
                cached = conn.execute(
                    """SELECT 1 FROM technical_commission_report_cache WHERE career_id=? AND mode=? AND scope_key=?
                         AND model=? AND source_hash=? LIMIT 1""",
                    (career_id, mode, scope, selected_model, source_hash),
                ).fetchone()
                if cached:
                    continue
                dedupe = f"auto:{career_id}:{mode}:{scope}:{selected_model}:{source_hash}"
                def work(mode=mode, report_fixture=report_fixture, player_id=player_id, selected_model=selected_model):
                    with database.connect() as report_conn:
                        return get_commission_report(report_conn, career_id, int(snapshot_id), mode,
                                                     fixture_id=report_fixture, player_ea_id=player_id, model=selected_model)
                scheduled.append(start_commission_report_job(career_id, work, dedupe))
            except (ValueError, sqlite3.Error):
                continue
        return scheduled


def queue_auto_reports_for_imported_snapshots(database: Any, results: list[Any]) -> list[dict[str, str]]:
    """Analyze only newly completed fixtures; old careers are not backfilled on startup."""
    scheduled: list[dict[str, str]] = []
    for result in results:
        if getattr(result, "status", None) != "imported" or not getattr(result, "snapshot_id", None):
            continue
        career_id, snapshot_id = int(result.career_id), int(result.snapshot_id)
        with database.connect() as conn:
            snapshot = conn.execute("SELECT import_sequence FROM snapshots WHERE id=? AND career_id=?",
                                    (snapshot_id, career_id)).fetchone()
            if not snapshot:
                continue
            previous = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? AND import_sequence<? ORDER BY import_sequence DESC LIMIT 1",
                (career_id, snapshot["import_sequence"]),
            ).fetchone()
            previous_id = int(previous["id"]) if previous else None
            current = conn.execute(
                """SELECT fixture_id FROM fixture_observations WHERE snapshot_id=? AND managed_team_involved=1
                     AND is_completed=1 ORDER BY date,fixture_id""", (snapshot_id,),
            ).fetchall()
            newly_completed = []
            for row in current:
                prior = conn.execute(
                    "SELECT is_completed FROM fixture_observations WHERE snapshot_id=? AND fixture_id=?",
                    (previous_id, row["fixture_id"]),
                ).fetchone() if previous_id is not None else None
                if not prior or prior["is_completed"] != 1:
                    newly_completed.append(int(row["fixture_id"]))
        for fixture_id in newly_completed:
            scheduled.extend(queue_auto_commission_reports(database, career_id, fixture_id, snapshot_id))
    return scheduled


def get_commission_report_job(career_id: int, job_id: str) -> dict[str, Any]:
    with _REPORT_JOB_LOCK:
        job = _REPORT_JOBS.get(job_id)
        if not job or int(job.get("career_id") or -1) != int(career_id):
            raise ValueError("Report task not found for this career.")
        return {"job_id": job_id, "status": job["status"], "result": job.get("result"),
                "error": job.get("error")}


def _managed_player_ids_for_fixture(conn: Any, career_id: int, snapshot_id: int,
                                    fixture_id: int, team_id: int) -> list[int]:
    export = conn.execute(
        """SELECT e.id FROM match_stat_exports e WHERE e.fixture_id=? AND e.career_id=?
             AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
             AND e.superseded_by_export_id IS NULL ORDER BY e.id DESC LIMIT 1""",
        (fixture_id, career_id),
    ).fetchone()
    if export:
        rows = conn.execute(
            """SELECT DISTINCT d.player_ea_id FROM match_player_detailed_stats d
                 JOIN match_team_detailed_stats t ON t.export_id=d.export_id AND t.team_index=d.team_index
                WHERE d.export_id=? AND t.team_ea_id=? AND COALESCE(d.minutes_played,0)>0
                ORDER BY d.player_ea_id""", (int(export["id"]), team_id)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT DISTINCT p.player_ea_id FROM player_match_performances p
                 JOIN fixtures f ON f.fixture_key=p.fixture_key AND f.career_id=?
                WHERE p.snapshot_id=? AND f.id=?
                  AND CAST(json_extract(p.raw_json,'$.managed_team_id') AS INTEGER)=?
                  AND COALESCE(p.minutes_played,0)>0 ORDER BY p.player_ea_id""",
            (career_id, snapshot_id, fixture_id, team_id),
        ).fetchall()
    return [int(row["player_ea_id"]) for row in rows]


def _historical_report_tasks(conn: Any, career_id: int) -> list[dict[str, Any]]:
    """Build career-scoped reports from the latest imported snapshot of each season."""
    snapshots = conn.execute(
        "SELECT id,season_index,import_sequence,managed_team_ea_id FROM snapshots WHERE career_id=? "
        "ORDER BY season_index,import_sequence,id", (career_id,)
    ).fetchall()
    latest_by_season: dict[int, Any] = {}
    for snapshot in snapshots:
        latest_by_season[int(snapshot["season_index"])] = snapshot

    tasks: list[dict[str, Any]] = []
    for season_index, snapshot in sorted(latest_by_season.items()):
        snapshot_id = int(snapshot["id"])
        team_id = int(snapshot["managed_team_ea_id"] or -1)
        if team_id <= 0:
            continue
        fixtures = conn.execute(
            """SELECT fo.fixture_id,fo.date FROM fixture_observations fo
                 WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
                 ORDER BY fo.date,fo.fixture_id""", (snapshot_id,)
        ).fetchall()
        for fixture in fixtures:
            fixture_id = int(fixture["fixture_id"])
            tasks.append({"snapshot_id": snapshot_id, "season_index": season_index,
                          "mode": "match", "fixture_id": fixture_id, "player_ea_id": None,
                          "label": f"{fixture['date'] or 'match'} · match report"})
            player_ids = _managed_player_ids_for_fixture(conn, career_id, snapshot_id, fixture_id, team_id)
            for player_id in player_ids:
                tasks.append({"snapshot_id": snapshot_id, "season_index": season_index,
                              "mode": "match_player", "fixture_id": fixture_id,
                              "player_ea_id": player_id,
                              "label": f"{fixture['date'] or 'match'} · player {player_id}"})
        tasks.append({"snapshot_id": snapshot_id, "season_index": season_index,
                      "mode": "team_identity", "fixture_id": None, "player_ea_id": None,
                      "label": f"Season {season_index + 1} · team profile"})
    return tasks


def start_retroactive_commission_reports(career_id: int, work: Any,
                                        metadata: dict[str, Any] | None = None) -> dict[str, str]:
    """Queue one resumable batch; individual report snapshots persist as they finish."""
    job_id = uuid.uuid4().hex
    with _REPORT_JOB_LOCK:
        for existing_id, job in _RETRO_REPORT_JOBS.items():
            if int(job.get("career_id") or -1) == int(career_id) and job.get("status") in {"queued", "running"}:
                return {"job_id": existing_id, "status": str(job["status"]), "deduplicated": "true"}
        _RETRO_REPORT_JOBS[job_id] = {"career_id": int(career_id), "status": "queued", "total": 0,
            "completed": 0, "generated": 0, "reused": 0, "review_required": 0, "failed": 0,
            "current": "", "backup_path": "", **(metadata or {})}

    def run() -> None:
        with _REPORT_JOB_LOCK:
            _RETRO_REPORT_JOBS[job_id]["status"] = "running"
        try:
            work(job_id)
            with _REPORT_JOB_LOCK:
                job = _RETRO_REPORT_JOBS.get(job_id)
                if job and job["status"] == "running":
                    job["status"] = "complete_with_warnings" if job["failed"] else "complete"
        except Exception as exc:
            with _REPORT_JOB_LOCK:
                job = _RETRO_REPORT_JOBS.get(job_id)
                if job:
                    job["status"] = "failed"
                    job["error"] = f"{exc.__class__.__name__}: {str(exc)[:180]}"

    _REPORT_EXECUTOR.submit(run)
    return {"job_id": job_id, "status": "queued"}


def run_retroactive_commission_reports(database: Any, career_id: int, job_id: str,
                                       language: str | None = None) -> None:
    """Generate every available historical match and managed-player report in sequence."""
    with database.connect() as conn:
        tasks = _historical_report_tasks(conn, career_id)
    with _REPORT_JOB_LOCK:
        job = _RETRO_REPORT_JOBS.get(job_id)
        if not job or int(job.get("career_id") or -1) != int(career_id):
            raise ValueError("Historical report task not found for this career.")
        job["total"] = len(tasks)
    if not tasks:
        return
    models = ollama_models(timeout=3.0)
    selected_model = os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
    if not models.get("available") or selected_model not in models.get("models", []):
        raise RuntimeError("Ollama is offline or the configured model is unavailable; no historical reports were generated.")

    for task in tasks:
        with _REPORT_JOB_LOCK:
            job = _RETRO_REPORT_JOBS.get(job_id)
            if job is None:
                return
            job["current"] = task["label"]
        try:
            with database.connect() as conn:
                cached = get_cached_commission_report(conn, career_id, task["snapshot_id"], task["mode"],
                    task["fixture_id"], task["player_ea_id"], selected_model, language)
                was_cached = cached.get("state") == "ready"
                result = get_commission_report(conn, career_id, task["snapshot_id"], task["mode"],
                    task["fixture_id"], task["player_ea_id"], selected_model,
                    language=language) if not was_cached else cached["result"]
            with _REPORT_JOB_LOCK:
                job = _RETRO_REPORT_JOBS.get(job_id)
                if job is None:
                    return
                job["completed"] += 1
                if was_cached or result.get("cached"):
                    job["reused"] += 1
                elif result.get("available"):
                    job["generated"] += 1
                else:
                    job["failed"] += 1
                    job.setdefault("errors", []).append({"item": task["label"], "message": result.get("message", "Report unavailable")})
                if result.get("review_required"):
                    job["review_required"] += 1
                if not result.get("available"):
                    job["current"] = ""
                    break
        except Exception as exc:
            with _REPORT_JOB_LOCK:
                job = _RETRO_REPORT_JOBS.get(job_id)
                if job is None:
                    return
                job["completed"] += 1
                job["failed"] += 1
                job.setdefault("errors", []).append({"item": task["label"], "message": f"{exc.__class__.__name__}: {str(exc)[:120]}"})
        with _REPORT_JOB_LOCK:
            job = _RETRO_REPORT_JOBS.get(job_id)
            if job:
                job["current"] = ""


def get_retroactive_commission_report_job(career_id: int, job_id: str) -> dict[str, Any]:
    with _REPORT_JOB_LOCK:
        job = _RETRO_REPORT_JOBS.get(job_id)
        if not job or int(job.get("career_id") or -1) != int(career_id):
            raise ValueError("Historical report task not found for this career.")
        return dict(job) | {"job_id": job_id}


def backfill_commission(conn: Any, career_id: int) -> int:
    snapshots = conn.execute("SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence", (career_id,)).fetchall()
    for row in snapshots:
        get_commission(conn, career_id, int(row["id"]))
    return len(snapshots)
