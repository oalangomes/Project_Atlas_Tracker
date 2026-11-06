"""Evidence-bounded professional commission analysis for Atlas careers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import date
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from .commission_prompt_policy import (build_system_prompt, claim_signature, compatible_formations,
                                       is_generic_claim, report_focus, report_subject)
from .claim_binding import score_claim_bindings
from .commission_role_policy import player_role, prompt_evidence, role_relevance_conflict

MIN_USABLE_MINUTES = 300
MIN_USABLE_GAMES = 3
RELIABLE_MINUTES = 450
RELIABLE_GAMES = 5
METRIC_VERSION = 3
REPORT_VERSION = 34
_REPORT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-ollama-report")
_REPORT_JOB_LOCK = Lock()
_REPORT_JOBS: dict[str, dict[str, Any]] = {}
_REPORT_JOB_KEYS: dict[str, str] = {}

STAT_FIELDS = (
    "npk_goals", "own_goals", "assists", "shots", "shots_on_target", "passes",
    "passes_completed", "tackles", "interceptions", "blocks", "clearances", "dribbles",
    "dribbles_completed", "crosses_attempted", "crosses_delivered", "key_passes",
    "possession_won", "possession_lost", "saves", "shots_against", "goals_conceded",
    "npk_expected_goals", "expected_assists", "game_rating", "man_of_the_match",
)

REPORT_TEAM_FIELDS = (
    "expected_goals_derived", "npk_expected_goals", "penalty_attempts_derived", "expected_assists",
    "shots", "shots_on_target", "xg_per_shot", "passes", "passes_completed", "pass_accuracy_pct_derived",
    "passes_under_pressure", "passes_completed_under_pressure", "pressure_pass_accuracy_pct", "key_passes",
    "tracker_completed_through_passes_including_lobbed", "dribbles", "dribbles_completed",
    "dribble_success_pct_derived", "crosses_attempted", "crosses_delivered", "cross_success_pct_derived",
    "possession_won", "possession_lost", "tackles", "interceptions", "blocks", "clearances",
    "defense_duels_attempted", "defense_duels_won", "defense_duel_success_pct_derived",
    "aerial_duels_attempted", "aerial_duels_won", "aerial_duel_success_pct_derived",
    "fouls_committed", "saves", "shots_against", "saving_shots_on_target", "goals_conceded",
)
REPORT_PLAYER_FIELDS = (
    "minutes_played", "game_rating", "goals_derived", "npk_goals", "assists", "npk_expected_goals",
    "expected_assists", "xg_plus_xa_per90", "xg_per_shot", "npk_finishing_delta", "shots",
    "shots_on_target", "key_passes", "passes", "passes_completed", "pass_accuracy_pct_derived",
    "passes_under_pressure", "passes_completed_under_pressure", "pressure_pass_accuracy_pct", "tracker_completed_through_passes_including_lobbed",
    "dribbles_completed", "possession_won", "possession_lost", "possession_balance", "tackles",
    "interceptions", "blocks", "clearances", "defense_duels_attempted", "defense_duels_won",
    "defense_duel_success_pct_derived", "aerial_duels_attempted", "aerial_duels_won",
    "aerial_duel_success_pct_derived", "fouls_committed", "saves", "shots_against", "goals_conceded",
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


def _compact_metrics(stats: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: stats[key] for key in fields if key in stats and stats[key] is not None}


def _mean_metric_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    means: dict[str, Any] = {}
    for field in fields:
        values = [_float((row.get("stats") or {}).get(field)) for row in rows]
        values = [value for value in values if value is not None]
        if values:
            means[field] = round(sum(values) / len(values), 3)
    return {"matches": len(rows), "metric_match_counts": {
        field: sum(_float((row.get("stats") or {}).get(field)) is not None for row in rows)
        for field in means
    }, "metrics_per_match": means}


def _normalize_report_clarifications(value: Any) -> list[dict[str, str]]:
    """Bound coach-supplied context before including it in a local LLM request."""
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError("Coach clarifications must be a list of question/answer pairs.")
    cleaned = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()[:280]
        answer = str(item.get("answer") or "").strip()[:1000]
        if question and answer:
            cleaned.append({"question": question, "answer": answer})
    if sum(len(item["answer"]) for item in cleaned) > 3600:
        raise ValueError("Coach clarifications exceed the 3,600 character limit.")
    return cleaned


def _coach_can_answer_information_request(question: str, reason: str) -> bool:
    """Only expose requests for qualitative context a coach can supply, not Atlas metrics."""
    text = f"{question} {reason}".casefold()
    question_text = str(question or "").casefold()
    atlas_data_terms = (
        "statistic", "statistics", "metric", "average", "last five", "last 5", "season average",
        "recent history", "recent record", "matches against", "performance in the last", "appearances",
        "minutes played", "goals", "xg", "expected goals", "shots", "passes", "tackles", "interceptions",
        "percentile", "rating", "média", "estatística", "métric", "últimas cinco", "últimos cinco",
        "últimas 5", "últimos 5", "média da temporada", "histórico recente", "desempenho nas últimas",
        "desempenho nos últimos", "partidas contra", "jogos contra", "minutos jogados", "gols", "remates",
        "finalizações", "passes", "desarmes", "interceptações", "nota média", "promedio", "estadística",
        "últimos cinco partidos", "últimas cinco partidas", "historial reciente", "rendimiento en los últimos",
        "minutos jugados", "goles", "tiros", "pases", "entradas", "intercepciones",
    )
    asks_about_recorded_coach_context = any(term in question_text for term in (
        "what was the intended", "what instruction did you", "what instructions did you",
        "instruction did you give", "what did you ask", "was the team instructed", "did you instruct", "did you ask the team",
        "qual era o plano", "qual instrução você", "qual instrucao voce", "que instrução você",
        "que instrucao voce", "o que você orientou", "o que voce orientou", "houve ajuste tático",
        "houve ajuste tatico", "qual foi o plano", "qué instrucción diste", "qué instrucciones diste",
        "cuál era el plan", "qué pediste al equipo", "se indicó al equipo"))
    return asks_about_recorded_coach_context and not any(term in text for term in atlas_data_terms)


def _prior_match_context(conn: Any, career_id: int, snapshot: Any, fixture_id: int,
                         managed_team_id: int, match_date: str) -> dict[str, Any]:
    """Build pre-match references from complete exports visible in this career snapshot only."""
    from .match_stats import detailed_match

    rows = conn.execute(
        """SELECT DISTINCT fo.fixture_id,fo.date,fo.home_team_name,fo.away_team_name,
                  fo.home_score,fo.away_score,f.home_team_ea_id,f.away_team_ea_id,
                  e.id export_id,e.snapshot_id export_snapshot_id
             FROM fixture_observations fo
             JOIN fixtures f ON f.id=fo.fixture_id
             JOIN match_stat_exports e ON e.fixture_id=f.id AND e.career_id=?
                  AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
                  AND e.superseded_by_export_id IS NULL
             JOIN snapshots source_snapshot ON source_snapshot.id=e.snapshot_id
             WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
               AND fo.fixture_id<>? AND fo.date<?
               AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)
               AND source_snapshot.career_id=? AND source_snapshot.season_index=?
               AND source_snapshot.import_sequence<=?
             ORDER BY fo.date DESC,fo.fixture_id DESC""",
        (career_id, int(snapshot["id"]), fixture_id, match_date, managed_team_id, managed_team_id,
         career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"])),
    ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        detailed = detailed_match(conn, int(row["fixture_id"]), career_id=career_id,
                                  as_of_import_sequence=int(snapshot["import_sequence"]),
                                  season_index=int(snapshot["season_index"]))
        if not detailed or int(detailed.get("exportId") or -1) != int(row["export_id"]):
            continue
        own = next((team for team in detailed.get("teams", []) if int(team.get("teamEaId") or -1) == managed_team_id), None)
        opponent = next((team for team in detailed.get("teams", []) if team is not own), None)
        if not own or not opponent:
            continue
        home = int(row["home_team_ea_id"] or -1) == managed_team_id
        history.append({
            "fixture_id": int(row["fixture_id"]), "date": row["date"],
            "opponent": row["away_team_name"] if home else row["home_team_name"],
            "venue": "home" if home else "away",
            "score": [row["home_score"], row["away_score"]],
            "goals_for": row["home_score"] if home else row["away_score"],
            "goals_against": row["away_score"] if home else row["home_score"],
            "team_stats": _compact_metrics(own.get("stats") or {}, REPORT_TEAM_FIELDS),
            "opponent_stats": _compact_metrics(opponent.get("stats") or {}, REPORT_TEAM_FIELDS),
        })
    recent = history[:5]
    metric_fields = ("expected_goals_derived", "npk_expected_goals", "shots", "shots_on_target",
                     "expected_assists", "passes", "pass_accuracy_pct_derived", "key_passes",
                     "tracker_completed_through_passes_including_lobbed", "dribbles_completed",
                     "possession_won", "possession_lost", "tackles", "interceptions", "blocks", "clearances")
    own_rows = [{"stats": row["team_stats"]} for row in history]
    against_rows = [{"stats": row["opponent_stats"]} for row in history]
    splits: dict[str, Any] = {}
    for venue in ("home", "away"):
        split = [row for row in history if row["venue"] == venue]
        if split:
            splits[venue] = {"for": _mean_metric_rows([{"stats": row["team_stats"]} for row in split], metric_fields),
                             "against": _mean_metric_rows([{"stats": row["opponent_stats"]} for row in split], metric_fields)}
    def goals_mean(rows: list[dict[str, Any]], field: str) -> float | None:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        return round(sum(values) / len(values), 3) if values else None
    return {
        "lookback_matches": len(history),
        "recent_five": [{"fixture_id": row["fixture_id"], "date": row["date"], "opponent": row["opponent"],
                          "venue": row["venue"], "score": row["score"]} for row in recent],
        "season_to_date_reference": {"for": _mean_metric_rows(own_rows, metric_fields),
                                     "against": _mean_metric_rows(against_rows, metric_fields),
                                     "goals_for_per_match": goals_mean(history, "goals_for"),
                                     "goals_against_per_match": goals_mean(history, "goals_against")},
        "last_five_reference": {"for": _mean_metric_rows([{"stats": row["team_stats"]} for row in recent], metric_fields),
                                "against": _mean_metric_rows([{"stats": row["opponent_stats"]} for row in recent], metric_fields),
                                "goals_for_per_match": goals_mean(recent, "goals_for"),
                                "goals_against_per_match": goals_mean(recent, "goals_against")},
        "venue_splits": splits,
        "source_note": "Only completed linked exports dated before this fixture, from this career and available by the selected snapshot; missing metrics remain absent.",
    }


def _prior_player_context(conn: Any, career_id: int, snapshot: Any, fixture_id: int,
                          managed_team_id: int, match_date: str,
                          player_ids: list[int]) -> list[dict[str, Any]]:
    """Summarize each selected player's last five valid pre-match MatchStats rows."""
    if not player_ids:
        return []
    from .match_stats import aggregate_detailed_stats

    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        f"""SELECT d.player_ea_id,d.minutes_played,d.stats_json,fo.date,fo.fixture_id,
                   p.actual_position,p.actual_position_source,ps.display_name,ps.primary_position
              FROM match_stat_exports e
              JOIN snapshots source_snapshot ON source_snapshot.id=e.snapshot_id
              JOIN fixtures f ON f.id=e.fixture_id
              JOIN fixture_observations fo ON fo.snapshot_id=? AND fo.fixture_id=e.fixture_id
                   AND fo.is_completed=1 AND fo.date<?
              JOIN match_player_detailed_stats d ON d.export_id=e.id
              LEFT JOIN player_match_performances p ON p.snapshot_id=? AND p.fixture_key=f.fixture_key
                   AND p.player_ea_id=d.player_ea_id
              LEFT JOIN player_states ps ON ps.snapshot_id=e.snapshot_id AND ps.ea_player_id=d.player_ea_id
             WHERE e.career_id=? AND e.fixture_id<>? AND e.linkage_status='linked'
               AND e.export_status='complete_participant_export' AND e.superseded_by_export_id IS NULL
               AND source_snapshot.career_id=? AND source_snapshot.import_sequence<=?
               AND source_snapshot.season_index=?
               AND (e.team0_ea_id=? OR e.team1_ea_id=?)
               AND d.team_index=CASE WHEN e.team0_ea_id=? THEN 0 ELSE 1 END
               AND d.player_ea_id IN ({placeholders})
             ORDER BY fo.date DESC,e.fixture_id DESC""",
        (int(snapshot["id"]), match_date, int(snapshot["id"]), career_id, fixture_id,
         career_id, int(snapshot["import_sequence"]), int(snapshot["season_index"]), managed_team_id, managed_team_id,
         managed_team_id, *player_ids),
    ).fetchall()
    grouped: dict[int, list[Any]] = defaultdict(list)
    for row in rows:
        player_id = int(row["player_ea_id"])
        if len(grouped[player_id]) >= 5:
            continue
        stats = json.loads(row["stats_json"] or "{}")
        minutes = int(row["minutes_played"] or stats.get("minutes_played") or 0)
        if minutes < 15 and not any(_float(stats.get(key)) and float(stats.get(key) or 0) > 0
                                    for key in ("goals_derived", "npk_goals", "own_goals", "pk_goals", "assists")):
            continue
        grouped[player_id].append({"date": row["date"], "fixture_id": int(row["fixture_id"]),
                                   "minutes": minutes, "stats": stats,
                                   "position": row["actual_position"] if row["actual_position_source"] == "career_playermatchratinghistory_position" else None,
                                   "registered_position": row["primary_position"], "name": row["display_name"]})
    result = []
    for player_id, appearances in grouped.items():
        stats = aggregate_detailed_stats([item["stats"] for item in appearances])
        position_minutes: dict[str, int] = defaultdict(int)
        for appearance in appearances:
            if appearance["position"]:
                position_minutes[str(appearance["position"]).upper()] += appearance["minutes"]
        result.append({"player_ea_id": player_id, "name": appearances[0]["name"],
                       "registered_position": appearances[0]["registered_position"],
                       "observed_position_minutes": dict(sorted(position_minutes.items())),
                       "valid_appearances": len(appearances), "minutes": stats.get("minutes_played"),
                       "rating": stats.get("average_rating"),
                       "stats": _compact_metrics(stats, REPORT_PLAYER_FIELDS),
                       "match_dates": [item["date"] for item in appearances]})
    return sorted(result, key=lambda item: str(item.get("name") or "").casefold())


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


def _season_date_bounds(conn: Any, career_id: int, season_index: int) -> tuple[str | None, str | None]:
    rows = conn.execute(
        "SELECT season_index,MIN(career_date) first_date FROM snapshots WHERE career_id=? GROUP BY season_index ORDER BY season_index",
        (career_id,),
    ).fetchall()
    starts = [(int(row["season_index"]), str(row["first_date"] or "")) for row in rows]
    start = next((value for index, value in starts if index == int(season_index)), None)
    following = next((value for index, value in starts if index > int(season_index)), None)
    return start, following


def analyze_team_identity(conn: Any, career_id: int, snapshot_id: int,
                          through_fixture_id: int | None = None) -> dict[str, Any]:
    """Describe the team's statistical profile without inventing possession or tactics."""
    snapshot = conn.execute("SELECT * FROM snapshots WHERE id=? AND career_id=?", (snapshot_id, career_id)).fetchone()
    if not snapshot:
        raise ValueError("Snapshot does not belong to the selected career.")
    team_id = int(snapshot["managed_team_ea_id"] or -1)
    season_start, next_season_start = _season_date_bounds(conn, career_id, int(snapshot["season_index"]))
    checkpoint_date = None
    if through_fixture_id is not None:
        checkpoint = conn.execute(
            "SELECT date FROM fixture_observations WHERE snapshot_id=? AND fixture_id=? AND managed_team_involved=1 AND is_completed=1",
            (snapshot_id, int(through_fixture_id)),
        ).fetchone()
        if not checkpoint or not checkpoint["date"]:
            raise ValueError("The selected team checkpoint has no reliable fixture date.")
        checkpoint_date = str(checkpoint["date"])
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
                  AND e.snapshot_id IN (SELECT source_snapshot.id FROM snapshots source_snapshot
                                         WHERE source_snapshot.career_id=? AND source_snapshot.season_index=?
                                           AND source_snapshot.import_sequence<=?)
             LEFT JOIN match_team_detailed_stats t ON t.export_id=e.id
             WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
               AND (? IS NULL OR fo.date>=?) AND (? IS NULL OR fo.date<?)
               AND (? IS NULL OR fo.date<? OR fo.fixture_id=?)
             ORDER BY fo.date,fo.fixture_id,t.team_index""",
        (career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"]), snapshot_id,
         season_start, season_start, next_season_start, next_season_start,
         checkpoint_date, checkpoint_date, int(through_fixture_id or -1)),
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
            "unavailable": ["posse de bola percentual", "pressão alta", "altura da linha", "formação inicial, quando não exportada"],
            "as_of_fixture_id": int(through_fixture_id) if through_fixture_id is not None else None,
            "as_of_date": checkpoint_date or str(snapshot["career_date"] or ""),
            "same_day_order": "only the selected fixture is included on its date; other same-day fixtures have no inferred order" if checkpoint_date else None}


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
    season_start, next_season_start = _season_date_bounds(conn, career_id, int(snapshot["season_index"]))
    snapshot_columns = set(snapshot.keys())
    snapshot_sequence = int(snapshot["import_sequence"]) if "import_sequence" in snapshot_columns else 2**31 - 1
    players = [dict(row) for row in conn.execute(
        "SELECT ea_player_id,display_name,primary_position FROM player_states WHERE snapshot_id=? AND team_ea_id=? ORDER BY display_name",
        (snapshot_id, team_id))]
    performances = [dict(row) for row in conn.execute(
        """SELECT p.player_ea_id,p.fixture_key,p.date,p.rating,p.minutes_played,p.actual_position,p.actual_position_source
           FROM player_match_performances p WHERE p.snapshot_id=? AND CAST(json_extract(p.raw_json,'$.managed_team_id') AS INTEGER)=?
             AND (? IS NULL OR p.date>=?) AND (? IS NULL OR p.date<?)
             AND (? IS NULL OR p.date<=?)
           ORDER BY p.date,p.fixture_key,p.player_ea_id""",
        (snapshot_id, team_id, season_start, season_start, next_season_start, next_season_start,
         snapshot["career_date"], snapshot["career_date"]))] if team_id is not None else []
    available_tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    fixture_rows = []
    if team_id is not None and {"match_stat_exports", "match_team_detailed_stats"}.issubset(available_tables):
        fixture_rows = conn.execute(
        """SELECT e.id,e.fixture_id,e.team0_ea_id,e.team1_ea_id,f.fixture_key,o.date,
                  d.player_ea_id,d.minutes_played,d.game_rating,d.stats_json,
                  CASE WHEN p.actual_position_source='career_playermatchratinghistory_position' THEN p.actual_position ELSE NULL END match_position
           FROM match_stat_exports e JOIN snapshots es ON es.id=e.snapshot_id
           JOIN fixture_observations o ON o.snapshot_id=? AND o.fixture_id=e.fixture_id
           JOIN fixtures f ON f.id=e.fixture_id
           JOIN match_player_detailed_stats d ON d.export_id=e.id
           LEFT JOIN player_match_performances p ON p.snapshot_id=? AND p.fixture_key=f.fixture_key AND p.player_ea_id=d.player_ea_id
           WHERE e.career_id=? AND es.season_index=? AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
             AND e.superseded_by_export_id IS NULL AND o.is_completed=1 AND o.managed_team_involved=1
             AND es.import_sequence<=? AND (? IS NULL OR o.date>=?) AND (? IS NULL OR o.date<?)
             AND (? IS NULL OR o.date<=?)
             AND (? IN (e.team0_ea_id,e.team1_ea_id))
             AND d.team_index=CASE WHEN e.team0_ea_id=? THEN 0 ELSE 1 END
           ORDER BY o.date,e.id,d.player_ea_id""",
            (snapshot_id, snapshot_id, career_id, int(snapshot["season_index"]), snapshot_sequence,
             season_start, season_start, next_season_start, next_season_start,
             snapshot["career_date"], snapshot["career_date"], int(team_id or -1), int(team_id or -1))).fetchall()
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
        """SELECT COUNT(*) FROM fixture_observations WHERE snapshot_id=? AND managed_team_involved=1 AND is_completed=1
             AND (? IS NULL OR date>=?) AND (? IS NULL OR date<?) AND (? IS NULL OR date<=?)""",
        (snapshot_id, season_start, season_start, next_season_start, next_season_start,
         snapshot["career_date"], snapshot["career_date"])).fetchone()[0])
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
                    language_override: str | None = None,
                    clarifications: list[dict[str, str]] | None = None) -> tuple[dict[str, Any], list[str], str]:
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
        home_team_id = int(row["home_team_ea_id"] or -1)
        away_team_id = int(row["away_team_ea_id"] or -1)
        managed_is_home = home_team_id == team_id
        opponent_id = away_team_id if managed_is_home else home_team_id
        match = {"fixture_id": int(fixture_id), "date": row["date"], "competition": row["competition_name"],
                 "home": row["home_team_name"], "away": row["away_team_name"], "completed": completed,
                 "managed_team_side": "home" if managed_is_home else "away",
                 "managed_team_ea_id": team_id, "opponent_ea_id": opponent_id,
                 "opponent_specific_history_available": False,
                 "event_timing_available": False}
        if completed:
            match["score"] = [row["home_score"], row["away_score"]]
            match["managed_score"] = row["home_score"] if managed_is_home else row["away_score"]
            match["opponent_score"] = row["away_score"] if managed_is_home else row["home_score"]
        fact("match", "Fixture", match, "Atlas fixture calendar")
        if mode in {"match", "match_player"} and completed and opponent_id > 0:
            prior_snapshot = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? AND season_index=? AND import_sequence<=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
                (career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"])),
            ).fetchone()
            history_rows = []
            if prior_snapshot:
                history_rows = conn.execute(
                    """SELECT DISTINCT f.id,fo.managed_team_result
                         FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                        WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1 AND f.id<>?
                          AND fo.date<?
                          AND (f.home_team_ea_id=? OR f.away_team_ea_id=?)""",
                    (int(prior_snapshot["id"]), int(fixture_id), str(row["date"]), opponent_id, opponent_id),
                ).fetchall()
            fact("opponent_history", "Earlier recorded meetings with this opponent", {
                "opponent_ea_id": opponent_id, "previous_meetings": len(history_rows),
                "previous_wins": sum(1 for item in history_rows if str(item["managed_team_result"] or "").upper() == "W"),
            }, "completed Atlas fixtures in the latest snapshot available at the selected career date")
            if row["date"]:
                prior_team_context = _prior_match_context(conn, career_id, snapshot, fixture_id, team_id, str(row["date"]))
                prior_team_context["opponent_reference_scope"] = "pooled across the managed team's earlier opponents; not a history of the current named opponent"
                prior_team_context["current_opponent_specific_history_available"] = False
                fact("pre_match_team_context", "Team performance before this fixture",
                     prior_team_context,
                     "career-scoped linked MatchStats dated strictly before the selected fixture")
        if mode in {"match", "match_player"}:
            export = conn.execute(
                """SELECT e.id FROM match_stat_exports e JOIN snapshots source_snapshot ON source_snapshot.id=e.snapshot_id
                     WHERE e.fixture_id=? AND e.career_id=? AND source_snapshot.season_index=?
                     AND source_snapshot.import_sequence<=?
                     AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
                     AND e.superseded_by_export_id IS NULL ORDER BY e.id DESC LIMIT 1""",
                (fixture_id, career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"])),
            ).fetchone()
            if export:
                from .match_stats import detailed_match
                detailed = detailed_match(conn, int(fixture_id), career_id=career_id,
                                          as_of_import_sequence=int(snapshot["import_sequence"]),
                                          season_index=int(snapshot["season_index"]))
                if not detailed or int(detailed.get("exportId") or -1) != int(export["id"]):
                    raise ValueError("The selected MatchStats export changed while the report context was being assembled.")
                teams = detailed.get("teams") or []
                teams_by_id = {int(team.get("teamEaId") or -1): team for team in teams}
                team_names = {home_team_id: row["home_team_name"], away_team_id: row["away_team_name"]}
                team_sides = {home_team_id: "home", away_team_id: "away"}
                team_stats = [{"team_index": int(team["teamIndex"]), "team_ea_id": team.get("teamEaId"),
                               "team_name": team_names.get(int(team.get("teamEaId") or -1)),
                               "team_side": team_sides.get(int(team.get("teamEaId") or -1)),
                               "stats": _compact_metrics(team.get("stats") or {}, REPORT_TEAM_FIELDS)} for team in teams]
                fact("matchstats", "Linked FC26 match statistics", team_stats, "complete linked MatchStats export")
                observed_rows = conn.execute(
                    """SELECT player_ea_id,actual_position,actual_position_source FROM player_match_performances
                         WHERE snapshot_id=? AND fixture_key=? AND actual_position_source='career_playermatchratinghistory_position'""",
                    (snapshot_id, row["fixture_key"]),
                ).fetchall()
                observed_positions = {int(item["player_ea_id"]): item["actual_position"] for item in observed_rows
                                      if item["actual_position"]}
                player_facts = []
                for item in detailed.get("players") or []:
                    player_id = int(item["playerEaId"])
                    stats = item.get("stats") or {}
                    player_team_id = int(item.get("teamEaId") or -1)
                    player_facts.append({"player_ea_id": player_id, "name": item.get("displayName"),
                                         "team_ea_id": item.get("teamEaId"),
                                         "team_name": team_names.get(player_team_id),
                                         "team_side": team_sides.get(player_team_id),
                                         "registered_position": item.get("primaryPosition"),
                                         "observed_position": observed_positions.get(player_id),
                                         "observed_position_source": "career_playermatchratinghistory_position" if player_id in observed_positions else None,
                                         "team_ea_id": item.get("teamEaId"), "team_index": item.get("teamIndex"),
                                         "minutes": stats.get("minutes_played"), "rating": stats.get("game_rating"),
                                         "stats": _compact_metrics(stats, REPORT_PLAYER_FIELDS)})
                fact("match_players", "Player match performances and position evidence", player_facts,
                     "complete linked MatchStats export; observed positions only from career_playermatchratinghistory_position")
                managed_players = [item for item in player_facts if int(item.get("team_ea_id") or -1) == team_id]
                context_players = ([item for item in managed_players if int(item["player_ea_id"]) == int(player_ea_id)]
                                   if mode == "match_player" and player_ea_id is not None else managed_players)
                if row["date"] and context_players:
                    prior_players = _prior_player_context(
                        conn, career_id, snapshot, fixture_id, team_id, str(row["date"]),
                        [int(item["player_ea_id"]) for item in context_players],
                    )
                    fact("pre_match_player_context", "Player performance before this fixture", prior_players,
                         "last five valid linked MatchStats appearances before the selected match; position minutes require trusted observed-position provenance")
                if mode == "match_player":
                    if player_ea_id is None:
                        raise ValueError("Select a player from the current match.")
                    participant = next((item for item in player_facts if int(item["player_ea_id"]) == int(player_ea_id)), None)
                    if not participant:
                        raise ValueError("Selected player has no linked performance in this match.")
                    player_team = next((team for team in teams if int(team.get("teamEaId") or -1) == team_id), None)
                    participant_row = next((item for item in detailed.get("players") or [] if int(item["playerEaId"]) == int(player_ea_id)), None)
                    if not player_team or not participant_row or int(participant_row["teamIndex"]) != int(player_team["teamIndex"]):
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
            # The former coarse defenders/midfielders/forwards counts could approve a
            # shape without a goalkeeper, wide players or enough distinct CBs.
            # Slot checks are conservative and do not infer selection or fitness.
            formations = compatible_formations(people)
            fact("squad", "Current squad and recorded recent load", people, "selected Atlas snapshot and player match ratings")
            fact("formation_options", "Potential shapes compatible with registered squad positions", formations, "conservative position-slot matching with distinct EA player IDs; NOT a confirmed XI, condition or tactical role")
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
        checkpoint_date = None
        checkpoint_key = None
        if fixture_id is not None:
            checkpoint = conn.execute(
                """SELECT fo.date,f.fixture_key FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                     WHERE fo.snapshot_id=? AND fo.fixture_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1""",
                (snapshot_id, int(fixture_id)),
            ).fetchone()
            if not checkpoint or not checkpoint["date"]:
                raise ValueError("The selected player checkpoint has no reliable fixture date.")
            checkpoint_date, checkpoint_key = str(checkpoint["date"]), str(checkpoint["fixture_key"])
            fixture_context = conn.execute(
                """SELECT fo.date,fo.competition_name,fo.home_team_name,fo.away_team_name,fo.home_score,fo.away_score,
                          fo.fixture_id,f.fixture_key,p.actual_position,p.actual_position_source
                     FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                     LEFT JOIN player_match_performances p ON p.snapshot_id=fo.snapshot_id
                          AND p.fixture_key=f.fixture_key AND p.player_ea_id=?
                    WHERE fo.snapshot_id=? AND fo.fixture_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1""",
                (int(player_ea_id), snapshot_id, int(fixture_id)),
            ).fetchone()
            if fixture_context:
                observed_position = (fixture_context["actual_position"]
                                     if fixture_context["actual_position_source"] == "career_playermatchratinghistory_position"
                                     else None)
                fact("player_checkpoint", "Player evaluation checkpoint", {
                    "fixture_id": int(fixture_id), "date": fixture_context["date"],
                    "competition": fixture_context["competition_name"],
                    "home": fixture_context["home_team_name"], "away": fixture_context["away_team_name"],
                    "home_score": fixture_context["home_score"], "away_score": fixture_context["away_score"],
                    "observed_position": observed_position,
                    "observed_position_source": "career_playermatchratinghistory_position" if observed_position else None,
                    "same_day_order": "unknown; other fixtures on this date are excluded from prior context",
                }, "selected completed fixture and player position only when provenance is trusted")
            snapshot, players, performances, detailed, coverage = _read_data(conn, career_id, snapshot_id)
            performances = [item for item in performances
                            if str(item.get("date") or "") < checkpoint_date or str(item.get("fixture_key") or "") == checkpoint_key]
            detailed = [item for item in detailed
                        if str(item.get("date") or "") < checkpoint_date or int(item.get("fixture_id") or -1) == int(fixture_id)]
            deterministic = analyze_players(players, performances, detailed, coverage)
        else:
            deterministic = get_commission(conn, career_id, snapshot_id)
        player = next((item for item in deterministic.get("players", []) if int(item["player_ea_id"]) == int(player_ea_id)), None)
        if not player:
            raise ValueError("Selected player is not in the current professional squad.")
        position_available_at_checkpoint = (checkpoint_date is None
                                             or str(snapshot["career_date"] or "") < checkpoint_date)
        player_fields = {key: player.get(key) for key in ("player_ea_id", "display_name", "minutes", "appearances",
                          "season_rating", "recent_rating", "recent_appearances", "sample", "moment", "recommendation", "metrics")}
        player_fields["position"] = player.get("position") if position_available_at_checkpoint else None
        fact("player_summary", "Current career performance", player_fields,
             "Atlas deterministic commission metrics; checkpoint position omitted when snapshot date is not strictly earlier")
        registered_group = _position_group(player.get("position")) if position_available_at_checkpoint else "N/D"
        peers = [item for item in deterministic.get("players", []) if position_available_at_checkpoint
                 if int(item.get("player_ea_id") or -1) != int(player_ea_id)
                 and item.get("position") and _position_group(item.get("position")) == registered_group]
        peer_rows = [{"player_ea_id": int(item["player_ea_id"]), "name": item.get("display_name"),
                      "registered_position": item.get("position"), "sample": item.get("sample"),
                      "appearances": item.get("appearances"), "minutes": item.get("minutes"),
                      "season_rating": item.get("season_rating"), "recent_rating": item.get("recent_rating"),
                      "metrics": {key: (item.get("metrics") or {}).get(key) for key in (
                          "goals_per90", "assists_per90", "xg_per90", "xa_per90", "npk_goals",
                          "assists", "shots", "key_passes", "tackles", "interceptions", "possession_won",
                          "possession_lost", "passes", "pass_accuracy_pct")
                                  if (item.get("metrics") or {}).get(key) is not None}}
                     for item in peers[:8]]
        fact("player_position_peers", "Same registered position-group peers in this squad", {
            "group": registered_group, "peer_count": len(peers), "players": peer_rows,
            "comparison_note": "Season MatchStats rows are partial and must be compared with minutes, appearance count and sample labels; registered position does not prove tactical function.",
        }, "existing Atlas Technical Commission career metrics and registered player positions")
        player_state = conn.execute(
            "SELECT * FROM player_states WHERE snapshot_id=? AND ea_player_id=?", (snapshot_id, player_ea_id)
        ).fetchone()
        growth = conn.execute(
            "SELECT * FROM player_growth_states WHERE snapshot_id=? AND player_ea_id=?", (snapshot_id, player_ea_id)
        ).fetchone()
        attribute_analysis = None
        if player_state and (checkpoint_date is None or str(snapshot["career_date"] or "") < checkpoint_date):
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
            }, "Atlas position-aware attribute analysis from the checkpoint snapshot; not proof of attributes at match kickoff")
        if checkpoint_date is not None:
            rows = [item for item in performances if int(item.get("player_ea_id") or -1) == int(player_ea_id)]
            rows.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("fixture_key") or "")), reverse=True)
        else:
            rows = conn.execute(
            """SELECT p.date,p.fixture_key,p.rating,p.minutes_played,p.actual_position,p.actual_position_source,
                      fo.competition_name,fo.home_team_name,fo.away_team_name,fo.home_score,fo.away_score
                 FROM player_match_performances p LEFT JOIN fixtures f ON f.fixture_key=p.fixture_key
                 LEFT JOIN fixture_observations fo ON fo.snapshot_id=p.snapshot_id AND fo.fixture_id=f.id
                 WHERE p.snapshot_id=? AND p.player_ea_id=? AND p.date<=?
                 ORDER BY p.date DESC,p.fixture_key DESC LIMIT 10""",
            (snapshot_id, player_ea_id, snapshot["career_date"]),
            ).fetchall()
        recent_facts = [dict(item) for item in rows[:10]]
        for recent in recent_facts:
            if recent.get("actual_position_source") != "career_playermatchratinghistory_position":
                recent["actual_position"] = None
            recent["observed_position_source"] = (recent.get("actual_position_source")
                                                   if recent.get("actual_position") else None)
            recent.pop("actual_position_source", None)
        # Re-emit only positions whose provenance is trusted; nominal/unverified values stay N/D.
        fact("player_recent_matches", "Last recorded player appearances", recent_facts,
             "player match rating history; positions retained only with trusted position-history provenance")
        from .match_stats import detailed_player_matches
        detailed_rows = detailed_player_matches(conn, career_id, int(player_ea_id),
                                                 season_indices=[int(snapshot["season_index"])],
                                                 as_of_import_sequence=int(snapshot["import_sequence"]))
        if checkpoint_date is not None:
            detailed_rows = [item for item in detailed_rows
                             if str(item.get("date") or "") < checkpoint_date or int(item.get("fixtureId") or -1) == int(fixture_id)]
        # Keep role-relevant historical GK evidence. The previous all-player
        # metric list contained only outfield attacking indicators and ratings.
        player_match_keys = (("saves", "shots_against", "saving_shots_on_target",
                              "goals_conceded", "passes", "passes_completed",
                              "pass_accuracy_pct_derived", "clearances", "game_rating")
                             if registered_group == "Goleiro" else
                             ("npk_goals", "assists", "npk_expected_goals", "expected_assists",
                              "shots", "key_passes", "tackles", "interceptions", "game_rating"))
        compact_matches = [{"date": item.get("date"), "competition": item.get("competitionName"),
                            "home": item.get("homeTeamName"), "away": item.get("awayTeamName"),
                            "score": [item.get("homeScore"), item.get("awayScore")],
                            "stats": {key: (item.get("stats") or {}).get(key) for key in player_match_keys
                                      if (item.get("stats") or {}).get(key) is not None}}
                           for item in [row for row in detailed_rows if str(row.get("date") or "") <= str(snapshot["career_date"] or "")][:10]]
        if compact_matches:
            fact("player_matchstats", "Player detail from linked MatchStats", compact_matches, "complete linked MatchStats exports; partial season coverage")
        else:
            fact("player_matchstats_missing", "Player MatchStats", "No linked player MatchStats rows in this season", "Atlas linkage status")
        scope = f"player:{player_ea_id}"
    elif mode == "team_identity":
        identity = analyze_team_identity(conn, career_id, snapshot_id, through_fixture_id=fixture_id)
        fact("team_statistical_profile", "Team statistical profile from linked matches", {
            "detailed_matches": identity["detailed_matches"], "completed_matches": identity["completed_matches"],
            "coverage_pct": identity["coverage_pct"], "metrics": identity["metrics"],
            "sample_sufficient": identity["style_sample_sufficient"],
            "unavailable": identity["unavailable"],
        }, "calculated from complete linked MatchStats exports available by this snapshot; checkpoint excludes other same-day fixtures" if fixture_id is not None else "calculated from complete linked MatchStats exports available by this snapshot; unavailable metrics remain null")
        fact("opponent_profiles", "Results against measured opponent shot-volume profiles",
             identity["opponent_profiles"], "ranked opponent team-shot counts and recorded match outcomes; association only")
        scope = f"team_identity:season:{int(snapshot['season_index'])}"
    else:
        raise ValueError("Unsupported technical commission report type.")

    if mode == "match":
        fact_map = {str(item["id"]): item.get("value") for item in facts}
        match_fact = fact_map.get("match") or {}
        match_stats = fact_map.get("matchstats") or []
        history_context = fact_map.get("pre_match_team_context") or {}
        managed_stats = next((item.get("stats") or {} for item in match_stats
                              if int(item.get("team_ea_id") or -1) == team_id), {})
        season_ref = (history_context.get("season_to_date_reference") or {})
        recent_ref = (history_context.get("last_five_reference") or {})
        season_for = (season_ref.get("for") or {})
        recent_for = (recent_ref.get("for") or {})
        metric_specs = [
            ("Gols marcados", "goals_for", "gols por partida", match_fact.get("managed_score"),
             season_ref.get("goals_for_per_match"), recent_ref.get("goals_for_per_match"),
             (season_ref.get("for") or {}).get("matches", 0), (recent_ref.get("for") or {}).get("matches", 0)),
            ("Gols sofridos", "goals_against", "gols por partida", match_fact.get("opponent_score"),
             season_ref.get("goals_against_per_match"), recent_ref.get("goals_against_per_match"),
             (season_ref.get("for") or {}).get("matches", 0), (recent_ref.get("for") or {}).get("matches", 0)),
        ]
        for label, key, unit, field in (
            ("xG a favor", "expected_goals_derived", "xG na partida", "expected_goals_derived"),
            ("Finalizações", "shots", "tentativas na partida", "shots"),
            ("Finalizações no alvo", "shots_on_target", "tentativas na partida", "shots_on_target"),
            ("Passes", "passes", "tentativas na partida", "passes"),
            ("Precisão de passe", "pass_accuracy_pct_derived", "% na partida", "pass_accuracy_pct_derived"),
            ("Desarmes", "tackles", "eventos na partida", "tackles"),
            ("Interceptações", "interceptions", "eventos na partida", "interceptions"),
        ):
            current = _float(managed_stats.get(field))
            if current is None and key == "expected_goals_derived":
                current = _float(managed_stats.get("npk_expected_goals"))
                key = "npk_expected_goals" if current is not None else key
            if field == "expected_goals_derived":
                season_values = season_for.get("metrics_per_match") or {}
                recent_values = recent_for.get("metrics_per_match") or {}
                season_counts = season_for.get("metric_match_counts") or {}
                recent_counts = recent_for.get("metric_match_counts") or {}
                season_value = season_values.get(key)
                recent_value = recent_values.get(key)
                if current is None and key == "expected_goals_derived":
                    current = _float(managed_stats.get("npk_expected_goals"))
                    key = "npk_expected_goals" if current is not None else key
                season_value = season_values.get(key, season_value)
                recent_value = recent_values.get(key, recent_value)
            else:
                season_values = season_for.get("metrics_per_match") or {}
                recent_values = recent_for.get("metrics_per_match") or {}
                season_counts = season_for.get("metric_match_counts") or {}
                recent_counts = recent_for.get("metric_match_counts") or {}
                season_value, recent_value = season_values.get(key), recent_values.get(key)
            metric_specs.append((label, key, unit, current, season_value, recent_value,
                                 season_counts.get(key, season_for.get("matches", 0)),
                                 recent_counts.get(key, recent_for.get("matches", 0))))
        comparisons = []
        interpretation_directions = {"goals_for": "higher_is_favorable", "goals_against": "lower_is_favorable",
                                     "pass_accuracy_pct_derived": "higher_is_more_accurate",
                                     "expected_goals_derived": "chance_volume_not_conversion", "npk_expected_goals": "chance_volume_not_conversion",
                                     "shots": "attempt_volume_only", "shots_on_target": "attempt_volume_only",
                                     "passes": "pass_volume_only", "tackles": "event_count_only", "interceptions": "event_count_only"}
        for label, key, unit, current, season_value, recent_value, season_n, recent_n in metric_specs:
            if current is None:
                continue
            season_value, recent_value = _float(season_value), _float(recent_value)
            comparisons.append({"metric": label, "metric_key": key, "entity": snapshot["managed_team_name"],
                                "unit": unit, "current_match": round(float(current), 3),
                                "interpretation_direction": interpretation_directions.get(key, "numeric_difference_only"),
                                "season_average": season_value, "last_five_average": recent_value,
                                "difference_vs_season": round(float(current) - season_value, 3) if season_value is not None else None,
                                "difference_vs_last_five": round(float(current) - recent_value, 3) if recent_value is not None else None,
                                "reference_samples": {"season": int(season_n or 0), "last_five": int(recent_n or 0)}})
        current_goals = _float(match_fact.get("managed_score"))
        current_xg = _float(managed_stats.get("expected_goals_derived"))
        historical_xg_key = "expected_goals_derived"
        if current_xg is None:
            current_xg = _float(managed_stats.get("npk_expected_goals"))
            historical_xg_key = "npk_expected_goals"
        historical_xg_season = _float(season_for.get("metrics_per_match", {}).get(historical_xg_key))
        historical_xg_recent = _float(recent_for.get("metrics_per_match", {}).get(historical_xg_key))
        historical_goals_season = _float(season_ref.get("goals_for_per_match"))
        historical_goals_recent = _float(recent_ref.get("goals_for_per_match"))
        if current_goals is not None and current_xg is not None:
            current_delta = round(current_goals - current_xg, 3)
            season_delta = round(historical_goals_season - historical_xg_season, 3) if historical_goals_season is not None and historical_xg_season is not None else None
            recent_delta = round(historical_goals_recent - historical_xg_recent, 3) if historical_goals_recent is not None and historical_xg_recent is not None else None
            comparisons.append({"metric": "Gols menos xG (conversão observada)", "metric_key": "finishing_delta",
                                "entity": snapshot["managed_team_name"], "unit": "gols por partida",
                                "interpretation_direction": "scoring_minus_xg_only_not_player_skill",
                                "current_match": current_delta, "season_average": season_delta,
                                "last_five_average": recent_delta,
                                "difference_vs_season": round(current_delta - season_delta, 3) if season_delta is not None else None,
                                "difference_vs_last_five": round(current_delta - recent_delta, 3) if recent_delta is not None else None,
                                "reference_samples": {"season": int(season_for.get("matches", 0)),
                                                      "last_five": int(recent_for.get("matches", 0))}})
        if comparisons:
            facts.append({"id": "match_comparisons", "label": "Precalculated like-for-like comparisons",
                          "value": comparisons,
                          "source": "Atlas deterministic calculations; same team and metric, current match versus pre-match per-match averages"})
    clarifications = _normalize_report_clarifications(clarifications)
    if clarifications:
        fact("coach_context", "Contexto enviado pelo treinador; não verificado pelo Atlas", clarifications,
             "user-supplied narrative; not imported or independently verified")

    from .settings import application_language, normalize_language
    context = {"mode": mode, "career_id": int(career_id), "snapshot_id": int(snapshot_id),
               "career_date": snapshot["career_date"], "managed_team": snapshot["managed_team_name"],
               "managed_team_ea_id": team_id, "season_index": int(snapshot["season_index"]), "report_version": REPORT_VERSION,
               "language": normalize_language(language_override) if language_override else application_language(), "facts": facts}
    if mode == "next_match":
        options = next((item.get("value") for item in facts if item["id"] == "formation_options"), [])
        context["allowed_formations"] = options
    context["report_subject"] = report_subject(context)
    role = player_role(context)
    if role is not None:
        context["role_analysis"] = role
    context["analysis_focus"] = report_focus(context)
    return context, [str(item["id"]) for item in facts], scope


def _report_source_hash(context: dict[str, Any], career_id: int, mode: str, scope: str) -> str:
    stable = {"career_id": int(career_id), "mode": mode, "scope_key": scope,
              "season_index": context.get("season_index"), "report_version": REPORT_VERSION,
              "language": context.get("language"),
              "facts": context.get("facts", []), "allowed_formations": context.get("allowed_formations"),
              "role_analysis": context.get("role_analysis")}
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


def _claim_has_structural_conflict(context: dict[str, Any], mode: str, text: str) -> bool:
    """Reject only claims that contradict a known source boundary or explicit fixture fact."""
    folded = text.casefold()
    facts = _report_fact_map(context)
    absent = facts.get("matchstats_missing") or facts.get("match_player_stats_missing")
    if absent and any(term in folded for term in ("xg", "expected goals", "gols esperados", "goles esperados", "shots", "finalizações", "tiros", "passes", "tackles", "desarmes", "interceptions", "interceptações")):
        return True
    unsupported_metric_claims = (
        ("possession share", ("possession share", "possession percentage", "posse de bola", "porcentagem de posse", "posesión del balón")),
        ("pressing", ("high press", "pressing intensity", "pressure situations", "in pressure situations", "situações de pressão", "em situações de pressão", "situaciones de presión", "pressão alta", "intensidade de pressão", "presión alta")),
        ("line height", ("defensive line height", "line height", "altura da linha", "linha defensiva alta", "altura de la línea")),
        ("injury or availability", ("injury", "injured", "lesão", "lesões", "lesionado", "suspensão", "suspended", "availability", "disponibilidade", "disponible", "condição física", "carga física", "workload", "physical condition", "fitness")),
        ("starting XI", ("starting xi", "starting eleven", "titularidade", "titular", "equipe inicial", "alineación titular")),
    )
    source_boundary_disclaimer = ("não registra", "não temos dados", "não há dados", "não permite confirmar",
                                  "não é possível confirmar", "não comprova", "not recorded", "no data for",
                                  "cannot confirm", "cannot establish", "does not establish", "not available",
                                  "no se registra", "no permite confirmar", "no hay datos")
    is_disclaimer = any(phrase in folded for phrase in source_boundary_disclaimer)
    for category, phrases in unsupported_metric_claims:
        if any(phrase in folded for phrase in phrases):
            if category == "injury or availability" and any(term in folded for term in ("monitorar", "monitor", "workload", "carga física", "evitar lesões", "prevent injury", "improve fitness")):
                return True
            # Pressure-pass metrics support discussion of passes under pressure,
            # but not a team press; a hypothesis may state its limitation without
            # claiming the missing metric was observed.
            if is_disclaimer or any(phrase in folded for phrase in ("pode indicar", "pode ter", "hipótese", "hypothesis", "podría", "could", "may have")):
                continue
            return True
    match = facts.get("match") or {}
    if mode in {"match", "match_player"} and match:
        if score_claim_bindings(context, {"text": text, "fact_refs": ["match", "selected_match_player"]})[1]:
            return True
        if any(term in folded for term in ("queda recente", "declínio", "decline", "recent drop", "falling trend")) and any(term in folded for term in ("dados longitudinais insuficientes", "insufficient longitudinal", "trend cannot be established", "tendência clara", "clear trend")):
            return True
        if match.get("event_timing_available") is False:
            chronology_terms = (
                "first half", "second half", "half-time", "halftime", "after the break", "before the break",
                "in the opening minutes", "early in the match", "late in the match", "at minute", "minute ",
                "primeiro tempo", "segundo tempo", "intervalo", "início da partida", "inicio da partida",
                "no começo da partida", "no início do jogo", "no inicio do jogo", "aos minutos", "minuto ",
                "primera parte", "segunda parte", "descanso", "tras el descanso", "al inicio del partido",
                "en el minuto", "minuto ", "marcou o primeiro gol", "marcou o segundo gol", "marcou o terceiro gol",
                "scored the first goal", "scored the second goal", "scored the third goal",
                "anotó el primer gol", "anotó el segundo gol", "marcó el primer gol", "marcó el segundo gol",
            )
            if any(term in folded for term in chronology_terms):
                return True
        # A player ID is team-scoped. Reject a report that attaches the player's name to the other club.
        players = facts.get("match_players") or []
        common_suffixes = {"city", "united", "town", "county", "rovers", "wanderers", "athletic", "albion"}
        for player in players:
            name = str(player.get("name") or "").casefold().strip()
            if not name or name not in folded:
                continue
            correct_team = str(player.get("team_name") or "").casefold().strip()
            other_names = {str(match.get("home") or "").casefold().strip(), str(match.get("away") or "").casefold().strip()} - {correct_team}
            other_aliases = set(other_names)
            for other_name in other_names:
                parts = other_name.split()
                if parts and parts[-1] not in common_suffixes:
                    other_aliases.add(parts[-1])
            associated_with_other = False
            for alias in (item for item in other_aliases if item):
                if f"do {alias}" in folded or f"da {alias}" in folded or f"de {alias}" in folded or f"of {alias}" in folded or f"for {alias}" in folded or f"{alias}'s" in folded:
                    associated_with_other = True
                    break
                if any(f"{alias} {role}" in folded for role in ("goalkeeper", "keeper", "goleiro", "portero")):
                    associated_with_other = True
                    break
            if associated_with_other:
                return True
        # Preserve the fixture's home/away orientation when the report names a club.
        sides = {str(match.get("home") or "").casefold().strip(): "home",
                 str(match.get("away") or "").casefold().strip(): "away"}
        side_terms = {
            "home": ("home team", "at home", "mandante", "time da casa", "equipe da casa", "local", "locales"),
            "away": ("away team", "visiting team", "away", "visitante", "time visitante", "equipe visitante", "visitante"),
        }
        for club, actual_side in sides.items():
            if not club or club not in folded:
                continue
            incorrect_side = "away" if actual_side == "home" else "home"
            if any(term in folded for term in side_terms[incorrect_side]):
                return True
        if match.get("opponent_specific_history_available") is False:
            managed_side = match.get("managed_team_side")
            current_opponent = str(match.get("away") if managed_side == "home" else match.get("home") or "").casefold().strip()
            historical_claim = any(term in folded for term in ("média", "media", "average", "averaged", "promedio", "temporada", "season", "últimas cinco", "last five", "últimos cinco"))
            opponent_average_pattern = r"(?:teve|registrou|had|recorded|averaged|mantuvo|registró).{0,35}(?:média|media|average|promedio)"
            if current_opponent and current_opponent in folded and historical_claim and re.search(opponent_average_pattern, folded):
                return True
        if any(term in folded for term in ("pelas laterais", "explorar as laterais", "pelos flancos", "corredor direito", "corredor esquerdo", "right flank", "left flank", "wide areas", "down the wing")):
            return True
        if any(term in folded for term in ("em casa e fora", "casa e fora", "both home and away", "at home and away", "tanto de local como visitante")):
            return True
        managed_score, opponent_score = match.get("managed_score"), match.get("opponent_score")
        managed_name = str(context.get("managed_team") or "").casefold()
        opponent_name = str(match.get("away") if match.get("managed_team_side") == "home" else match.get("home") or "").casefold()
        win_terms = (" venceu ", " vitória ", " ganhou ", " won ", " victory ", " beat ", " venció ", " ganó ")
        loss_terms = (" perdeu ", " derrota ", " foi derrotad", " lost ", " defeat ", " beaten ", " perdió ", " derrota ante ")
        padded = f" {folded} "
        if managed_score is not None and opponent_score is not None and managed_name and managed_name in folded:
            if int(managed_score) > int(opponent_score) and any(term in padded for term in loss_terms):
                return True
            if int(managed_score) < int(opponent_score) and any(term in padded for term in win_terms):
                return True
        if managed_score is not None and opponent_score is not None and opponent_name and opponent_name in folded:
            if int(managed_score) > int(opponent_score) and any(term in padded for term in win_terms):
                return True
            if int(managed_score) < int(opponent_score) and any(term in padded for term in loss_terms):
                return True
    return False


def _report_item_metric_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    """Check common named-team/player metric claims against the cited source rows."""
    text = str(item.get("text") or "").casefold()
    refs = set(item.get("fact_refs") or [])
    values = {str(fact.get("id")): fact.get("value") for fact in context.get("facts", []) if fact.get("id") in refs}
    teams = [row for row in (values.get("matchstats") or []) if isinstance(row, dict)]
    players = [row for row in (values.get("match_players") or []) if isinstance(row, dict)]
    if "selected_match_player" in refs:
        selected = _report_fact_map(context).get("selected_match_player")
        if isinstance(selected, dict) and selected not in players:
            players.append(selected)

    def mentions(name: Any) -> bool:
        return bool(name and str(name).casefold() in text)

    def mentions_team(name: Any) -> bool:
        if not name:
            return False
        normalized = str(name).casefold().strip()
        aliases = {normalized}
        parts = normalized.split()
        if parts:
            aliases.add(parts[0])
            common_suffixes = {"city", "united", "town", "county", "rovers", "wanderers", "athletic", "albion"}
            if parts[-1] not in common_suffixes:
                aliases.add(parts[-1])
        return any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text) for alias in aliases if len(alias) >= 4)

    def number_matches(claim: str, expected: Any) -> bool:
        if expected is None:
            return False
        try:
            expected_value = float(expected)
            numbers = [float(token.replace(",", ".")) for token in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", claim)]
        except (TypeError, ValueError):
            return False
        return any(abs(actual - expected_value) <= 0.051 for actual in numbers)

    pass_accuracy_terms = ("precisão de passes", "precisão dos passes", "precisão de passe sob pressão", "precisão dos passes sob pressão", "pass accuracy", "pass completion", "acerto nos passes", "precisión de pase")
    pressure_accuracy_terms = ("precisão de passe sob pressão", "precisão dos passes sob pressão", "pass accuracy under pressure", "pressure pass accuracy")
    shots_target_terms = ("chutes no alvo", "chutes a gol", "finalizações no alvo", "finalizações certas", "shots on target", "shots on goal", "tiros a puerta")
    pressure_completion_terms = ("passes concluídos sob pressão", "passes completados bajo presión", "passes completed under pressure")
    pressure_attempt_terms = ("passes sob pressão", "passes under pressure", "passes bajo presión")
    shots_faced_terms = ("tentativas no alvo sofridas", "chutes no alvo sofridos", "shots on target faced", "shots on target against", "saving shots on target", "tiros a puerta recibidos")
    pass_count_terms = ("passes", "passes completados", "passos concluídos", "passes completed", "completed passes", "passes certos", "passes tentados", "passes attempted")
    has_pass_accuracy = any(term in text for term in pass_accuracy_terms)
    has_pressure_accuracy = any(term in text for term in pressure_accuracy_terms)
    has_shots_target = any(term in text for term in shots_target_terms)
    has_pressure_completion = any(term in text for term in pressure_completion_terms)
    has_pressure_attempts = any(term in text for term in pressure_attempt_terms)
    has_shots_faced = any(term in text for term in shots_faced_terms) or ("sofreu" in text and any(term in text for term in ("tentativas no alvo", "chutes no alvo", "shots on target")))
    has_completed_passes = any(term in text for term in ("completou", "completó", "completed ", "passes completados", "passes concluídos", "passes completed", "completed passes", "passes certos", "passos concluídos"))
    has_pass_count = any(term in text for term in pass_count_terms) and not has_pass_accuracy and not has_pressure_completion and not has_pressure_attempts
    has_xg = any(term in text for term in ("xg", "expected goals", "gols esperados", "goles esperados"))
    # Explicit score claims are checked against the subject's own fixture value.
    has_goals = bool(re.search(r"\b(?:goals?|gols?|goles?)\b", text)) and not score_claim_bindings(context, item)[0]
    has_assists = any(term in text for term in ("assist", "assistência", "asistencia"))
    has_dribbles = any(term in text for term in ("dribble", "drible"))
    has_duels = any(term in text for term in ("duel", "duelo"))
    has_defensive_actions = any(term in text for term in ("tackle", "desarme", "interception", "intercepta"))
    if not (has_xg or has_goals or has_assists or has_dribbles or has_duels or has_defensive_actions
            or has_pass_accuracy or has_shots_target or has_pressure_completion or has_pressure_attempts or has_shots_faced or has_pass_count):
        return False
    surnames = [str(row.get("name") or "").casefold().split()[-1] for row in players if row.get("name")]
    matched_rows = [row for row in players if mentions(row.get("name")) or
                    (len(str(row.get("name") or "").split()) > 1 and
                     str(row.get("name") or "").casefold().split()[-1] in text and
                     surnames.count(str(row.get("name") or "").casefold().split()[-1]) == 1)]
    if matched_rows:
        for row in matched_rows:
            stats = row.get("stats") or {}
            if has_pass_accuracy and not number_matches(text, stats.get("pressure_pass_accuracy_pct" if has_pressure_accuracy else "pass_accuracy_pct_derived")):
                return True
            if has_shots_target and not number_matches(text, stats.get("shots_on_target")):
                return True
            if has_shots_faced and not number_matches(text, stats.get("saving_shots_on_target")):
                return True
            if has_pass_count and not number_matches(text, stats.get("passes_completed" if has_completed_passes else "passes")):
                return True
            if has_pressure_completion and not number_matches(text, stats.get("passes_completed_under_pressure")):
                return True
            if has_pressure_attempts and not has_pressure_completion and not number_matches(text, stats.get("passes_under_pressure")):
                return True
            if has_xg and not number_matches(text, stats.get("npk_expected_goals", stats.get("expected_goals_derived"))):
                return True
            if has_goals and not number_matches(text, stats.get("goals_derived", stats.get("npk_goals"))):
                return True
            if has_assists and not number_matches(text, stats.get("assists")):
                return True
            if has_dribbles and not number_matches(text, stats.get("dribbles_completed" if any(term in text for term in ("completed", "completou", "completados")) else "dribbles")):
                return True
            if has_duels and not any(number_matches(text, stats.get(key)) for key in ("aerial_duels_won", "defense_duels_won", "offense_duels_won")):
                return True
            if has_defensive_actions and not any(number_matches(text, stats.get(key)) for key in ("tackles", "interceptions", "stand_tackles", "stand_tackles_won", "slide_tackles", "slide_tackles_won")):
                return True
        return False
    matched_teams = [row for row in teams if mentions_team(row.get("team_name"))]
    for row in matched_teams:
        stats = row.get("stats") or {}
        if has_pass_accuracy and not number_matches(text, stats.get("pressure_pass_accuracy_pct" if has_pressure_accuracy else "pass_accuracy_pct_derived")):
            return True
        if has_shots_target and not number_matches(text, stats.get("shots_on_target")):
            return True
        if has_shots_faced and not number_matches(text, stats.get("saving_shots_on_target")):
            return True
        if has_pass_count and not number_matches(text, stats.get("passes_completed" if has_completed_passes else "passes")):
            return True
        if has_pressure_completion and not number_matches(text, stats.get("passes_completed_under_pressure")):
            return True
        if has_pressure_attempts and not has_pressure_completion and not number_matches(text, stats.get("passes_under_pressure")):
            return True
        if has_xg and not number_matches(text, stats.get("npk_expected_goals", stats.get("expected_goals_derived"))):
            return True
        if has_goals and not number_matches(text, stats.get("goals_derived", stats.get("npk_goals"))):
            return True
        if has_assists and not number_matches(text, stats.get("assists")):
            return True
        if has_dribbles and not number_matches(text, stats.get("dribbles_completed" if any(term in text for term in ("completed", "completou", "completados")) else "dribbles")):
            return True
        if has_duels and not any(number_matches(text, stats.get(key)) for key in ("aerial_duels_won", "defense_duels_won", "offense_duels_won")):
            return True
        if has_defensive_actions and not any(number_matches(text, stats.get(key)) for key in ("tackles", "interceptions", "stand_tackles", "stand_tackles_won", "slide_tackles", "slide_tackles_won")):
            return True
        if has_pressure_accuracy and any(term in text for term in ("melhorar", "improve", "mejorar", "increase", "aumentar")):
            try:
                if float(stats.get("pressure_pass_accuracy_pct")) >= 95:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _report_item_numeric_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    """Require numeric claims to be present in the cited fact values, allowing ordinary rounding."""
    cited = set(item.get("fact_refs") or [])
    allowed: list[float] = []
    excluded_keys = {"fixture_id", "player_ea_id", "team_ea_id", "team_index", "export_id", "snapshot_id", "external_export_id"}

    def collect(value: Any, key: str = "") -> None:
        if key in excluded_keys or isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            allowed.append(float(value))
        elif isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, str(child_key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for fact in context.get("facts", []):
        if fact.get("id") in cited:
            collect(fact.get("value"))
    for raw in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", str(item.get("text") or "")):
        token = raw.replace(",", ".")
        try:
            number = float(token)
        except ValueError:
            return True
        precision = len(token.partition(".")[2]) if "." in token else 0
        tolerance = 0.5 * (10 ** -precision) + 1e-7
        if not any(abs(number - candidate) <= tolerance for candidate in allowed):
            return True
    return False


def _validate_report_item(context: dict[str, Any], mode: str, item: dict[str, Any], valid_ids: set[str],
                          section: str | None = None, rejection_reasons: list[str] | None = None) -> bool:
    def reject(reason: str) -> bool:
        if rejection_reasons is not None:
            rejection_reasons.append(reason)
        return False

    if not isinstance(item.get("text"), str) or not item["text"].strip():
        return reject("empty_text")
    refs = item.get("fact_refs")
    if not isinstance(refs, list) or not refs or not set(refs).issubset(valid_ids):
        return reject("missing_or_invalid_fact_refs")
    if mode in {"match", "match_player"}:
        _, score_issues = score_claim_bindings(context, item)
        if score_issues:
            if rejection_reasons is not None:
                rejection_reasons.extend(score_issues)
            return False
    if mode == "match_player":
        facts = _report_fact_map(context)
        selected = facts.get("selected_match_player") or {}
        selected_name = str(selected.get("name") or "").strip().casefold()
        text = item["text"].casefold()
        historical_language = ("previous", "prior", "earlier", "last match", "last game", "previous match",
                               "última partida", "último jogo", "partida anterior", "jogo anterior", "actuación anterior",
                               "atuação anterior", "histórico", "historical", "temporada", "season")
        participants = facts.get("match_players") or []
        names_another_player = any(
            str(player.get("name") or "").strip().casefold() in text
            and str(player.get("name") or "").strip().casefold() != selected_name
            for player in participants if player.get("name")
        )
        if (selected_name and "selected_match_player" in valid_ids
                and not any(term in text for term in historical_language)
                and not names_another_player
                and set(refs) & {"matchstats", "match_players"}
                and "selected_match_player" not in refs):
            item["fact_refs"] = list(dict.fromkeys([*refs, "selected_match_player"]))
            refs = item["fact_refs"]
    kind = item.get("kind")
    if kind not in {"fact", "inference", "hypothesis"}:
        return reject("invalid_claim_kind")
    if kind == "hypothesis" and (not isinstance(item.get("limitations"), str) or len(item["limitations"].strip()) < 12):
        return reject("hypothesis_missing_limitations")
    folded = item["text"].casefold()
    causal_or_tactical_language = ("consequência natural", "natural consequence", "natural result of", "devido ao ritmo", "due to the tempo", "higher tempo", "ritmo mais alto", "pressão ofensiva", "intense attacking pressure", "presión ofensiva", "intensidade na circulação", "maintain intensity in circulation", "intensidad de circulación", "vulnerável a ataques diretos", "vulnerable to direct attacks", "vulnerable to direct attack")
    if mode in {"match", "match_player"} and kind == "inference" and any(term in folded for term in causal_or_tactical_language):
        return reject("unsupported_causal_inference")
    if is_generic_claim(item["text"], section):
        return reject("generic_claim")
    if mode in {"player", "match_player"} and role_relevance_conflict(context, item["text"]):
        return reject("irrelevant_player_role_metric")
    if section == "recommendations" and _report_recommendation_target_conflict(context, mode, item["text"]):
        return reject("recommendation_targets_opponent")
    if section == "recommendations" and _report_unavailable_metric_recommendation_conflict(context, item):
        return reject("recommendation_uses_unavailable_metric")
    if mode in {"match", "match_player"} and _report_wrong_team_metric_conflict(context, item):
        return reject("wrong_team_metric_source")
    if mode in {"match", "match_player"} and _report_managed_team_role_conflict(context, item["text"]):
        return reject("wrong_managed_team_role")
    if mode == "match_player" and _report_selected_player_metric_conflict(context, item):
        return reject("selected_player_metric_conflict")
    if mode == "player" and _report_accumulated_player_metric_conflict(context, item):
        return reject("player_summary_metric_conflict")
    if mode in {"match", "match_player"} and _report_missing_metric_source_conflict(context, item):
        return reject("metric_source_missing")
    if mode == "team_identity" and _report_unfounded_team_style_conflict(context, item):
        return reject("unfounded_team_style")
    if mode in {"match", "match_player"} and _report_uncompared_dominance_conflict(context, item):
        return reject("uncompared_dominance")
    if section == "recommendations" and _report_recommendation_confuses_xg_and_finishing(context, item):
        return reject("xg_finishing_confusion")
    if _claim_has_structural_conflict(context, mode, item["text"]):
        return reject("structural_fact_conflict")
    if _report_item_numeric_conflict(context, item):
        return reject("numeric_fact_conflict")
    if _report_item_metric_conflict(context, item):
        return reject("entity_metric_conflict")
    if _report_item_comparison_direction_conflict(context, mode, item):
        return reject("comparison_direction_conflict")
    return True


def _report_recommendation_target_conflict(context: dict[str, Any], mode: str, text: str) -> bool:
    if mode not in {"match", "match_player", "next_match"}:
        return False
    facts = _report_fact_map(context)
    match = facts.get("match") or {}
    managed_id = int(match.get("managed_team_ea_id") or -1)
    folded = text.casefold()
    for player in facts.get("match_players") or []:
        if int(player.get("team_ea_id") or -1) != managed_id:
            name = str(player.get("name") or "").casefold().strip()
            if name and name in folded:
                return True
    home = str(match.get("home") or "").strip()
    away = str(match.get("away") or "").strip()
    opponent = home if match.get("managed_team_side") == "away" else away
    if opponent and re.search(r"(?<!\w)" + re.escape(opponent.casefold()) + r"(?!\w)", folded):
        escaped = re.escape(opponent.casefold())
        recommendation_target = (
            r"(?:the\s+)?" + escaped + r"\s+(?:should|must|needs? to|has to|ought to|can improve|should investigate)\b",
            r"(?:o|a|ao|a\s+equipe\s+do)?\s*" + escaped + r"\s+(?:deve|precisa|tem de|pode melhorar|deveria)\b",
            r"(?:el|la|al)?\s*" + escaped + r"\s+(?:debe|necesita|tiene que|podr[ií]a mejorar)\b",
            r"(?:investigate|improve|train|review|adjust|treinar|ajustar|revisar|melhorar|investigar|mejorar)\s+(?:the\s+)?" + escaped + r"\b",
            r"(?:review|improve|adjust|train|investigate|revisar|melhorar|ajustar|treinar|investigar)\b.{0,55}\b(?:the\s+|a\s+|o\s+|do\s+|da\s+|of\s+|de\s+|del\s+|de la\s+)?" + escaped + r"\b",
        )
        if any(re.search(pattern, folded) for pattern in recommendation_target):
            return True
    return False


def _report_wrong_team_metric_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    """A named club's metrics must come from that club's row, not managed-team comparisons."""
    text = str(item.get("text") or "").casefold()
    metric_terms = ("xg", "expected goals", "gols esperados", "goles esperados", "finaliza", "shots", "chutes",
                    "tiros", "passes", "pass accuracy", "precisão", "tackles", "desarmes", "duels", "duelos",
                    "duelos", "interceptions", "interceptações", "intercepciones", "gols", "goals", "goles")
    performance_terms = metric_terms[:-3]
    if not any(term in text for term in metric_terms):
        return False
    refs = set(item.get("fact_refs") or [])
    facts = _report_fact_map(context)
    match = facts.get("match") or {}
    team_rows = facts.get("matchstats") if "matchstats" in refs else None
    team_rows = team_rows if isinstance(team_rows, list) else []
    for name in (str(match.get("home") or "").strip(), str(match.get("away") or "").strip()):
        aliases = {name.casefold(), name.casefold().split()[0] if name else ""}
        if not name or not any(alias and re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text) for alias in aliases):
            continue
        row = next((item for item in team_rows if str(item.get("team_name") or "").casefold().strip() == name.casefold()), None)
        if row is None:
            # match_comparisons are for the managed club only.
            if "match_comparisons" in refs:
                comparison = next((fact.get("value") for fact in context.get("facts", [])
                                   if fact.get("id") == "match_comparisons"), [])
                entity = next((str(item.get("entity") or "").casefold() for item in comparison or []
                               if isinstance(item, dict)), "")
                if entity and entity != name.casefold():
                    return True
            # The fixture fact supports score and identity, not the named club's performance metrics.
            if ("match" in refs and not ({"matchstats", "match_players"} & refs)
                    and any(term in text for term in performance_terms)):
                return True
        else:
            stats = row.get("stats") or {}
            metric_keys = []
            if any(term in text for term in ("xg", "expected goals", "gols esperados", "goles esperados")):
                metric_keys.extend(("expected_goals_derived", "npk_expected_goals"))
            if any(term in text for term in ("shot", "finaliza", "chute", "tiro")):
                metric_keys.append("shots")
            if any(term in text for term in ("pass", "passe", "precisão", "precision")):
                metric_keys.extend(("passes", "pass_accuracy_pct_derived"))
            if any(term in text for term in ("duel", "duelo", "duelos")):
                metric_keys.extend(("offense_duels_won", "defense_duels_won", "aerial_duels_won"))
            if metric_keys and not any(stats.get(key) is not None for key in metric_keys):
                return True
            if "xg" in text or "expected goals" in text or "gols esperados" in text or "goles esperados" in text:
                xg_pairs = re.findall(
                    r"(?:xg|expected goals|gols esperados|goles esperados)\s*(?:de|of|=|:)?\s*(\d+(?:[.,]\d+)?)|(?<![\w])(\d+(?:[.,]\d+)?)\s*xg\b",
                    text)
                xg_values = [float(next(token for token in pair if token).replace(",", "."))
                             for pair in xg_pairs if any(pair)]
                available_xg = [value for value in (_float(stats.get("expected_goals_derived")), _float(stats.get("npk_expected_goals"))) if value is not None]
                if xg_values and available_xg and any(not any(abs(value - source) <= 0.051 for source in available_xg) for value in xg_values):
                    return True
    return False


def _report_managed_team_role_conflict(context: dict[str, Any], text: str) -> bool:
    facts = _report_fact_map(context)
    match = facts.get("match") or {}
    team = str(context.get("managed_team") or "").casefold().strip()
    if not team or not re.search(r"(?<!\w)" + re.escape(team) + r"(?!\w)", str(text).casefold()):
        return False
    folded = str(text).casefold()
    role_patterns = (r"(?:opponent|opposition|adversary|rival|adversário|oponente|adversario|rival)\s+(?:club\s+)?" + re.escape(team),
                     r"(?:o|a|the|el|la)\s+(?:adversário|oponente|adversary|opponent)\s+" + re.escape(team))
    return any(re.search(pattern, folded) for pattern in role_patterns)


def _report_selected_player_metric_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    """Bind unlabelled player-performance statements to the selected participant's own row."""
    text = str(item.get("text") or "").casefold()
    score_bindings, _ = score_claim_bindings(context, item)
    if (score_bindings
            and all(binding["subject_side"] != "selected_player" for binding in score_bindings)
            and not any(term in text for term in ("assist", "xg", "pass", "passe", "shot", "chute",
                                                  "finaliza", "save", "defesa", "duel", "duelo",
                                                  "tackle", "desarme", "intercept", "dribble",
                                                  "drible", "cross", "cruzamento", "minute", "minuto"))):
        return False
    facts = _report_fact_map(context)
    selected = facts.get("selected_match_player") or {}
    player_name = str(selected.get("name") or "").casefold().strip()
    players = facts.get("match_players") or []
    explicitly_other = any(str(row.get("name") or "").casefold().strip() in text
                           and str(row.get("name") or "").casefold().strip() != player_name
                           for row in players if row.get("name"))
    if explicitly_other:
        return True
    if not player_name:
        return False
    metric_terms = ("goal", "gol", "gols", "goles", "assist", "xg", "expected goals", "passes", "pass", "passe",
                    "shot", "chute", "finaliza", "save", "defesa", "duel", "duelo", "tackle", "desarme",
                    "interception", "intercepta", "dribble", "drible", "cross", "cruzamento", "minute", "minuto")
    if not any(term in text for term in metric_terms):
        return False
    refs = set(item.get("fact_refs") or [])
    if not (refs & {"selected_match_player", "pre_match_player_context", "match_players"}):
        return True
    stats = selected.get("stats") or {}
    # A ratio is one claim about one metric. The denominator cannot be borrowed
    # from another stat merely because the same number occurs in the fact row.
    for match in re.finditer(r"(?<!\w)(\d+)\s+(?:de|dos|das|of|out of)\s+"
                             r"(?:(?:seus|suas|his|her)\s+)?(\d+)\s+(?:dribles|dribbles)\b", text):
        completed, attempted = int(match.group(1)), int(match.group(2))
        if (_float(stats.get("dribbles_completed")) != completed
                or _float(stats.get("dribbles")) != attempted):
            return True
    allowed: list[float] = []
    def add(*keys: str) -> None:
        for key in keys:
            value = _float(stats.get(key))
            if value is not None:
                allowed.append(value)
    if re.search(r"\b(?:goals?|gols?|goles?)\b", text):
        add("npk_goals", "goals_derived", "pk_goals", "own_goals", "assists", "goals_conceded")
    if "assist" in text or "assistência" in text or "asistencia" in text:
        add("assists", "secondary_assist")
    if any(term in text for term in ("xg", "expected goals", "gols esperados", "goles esperados")):
        add("npk_expected_goals", "expected_goals_derived")
    if any(term in text for term in ("pass", "passe")):
        add("passes", "passes_completed", "passes_under_pressure", "passes_completed_under_pressure",
            "pass_accuracy_pct_derived", "pressure_pass_accuracy_pct")
    if any(term in text for term in ("shot", "chute", "finaliza", "tiro")):
        add("shots", "shots_on_target", "shots_against", "saving_shots_on_target", "npk_finishing_delta")
    if any(term in text for term in ("save", "defesa", "defendeu")):
        add("saves", "saving_shots_on_target")
    if any(term in text for term in ("duel", "duelo")):
        add("aerial_duels_won", "aerial_duels_attempted", "defense_duels_won", "defense_duels_attempted",
            "offense_duels_won", "offense_duels_attempted")
    if any(term in text for term in ("tackle", "desarme")):
        add("tackles", "stand_tackles", "stand_tackles_won", "slide_tackles", "slide_tackles_won")
    if any(term in text for term in ("interception", "intercepta")):
        add("interceptions")
    if any(term in text for term in ("dribble", "drible")):
        add("dribbles", "dribbles_completed")
    if any(term in text for term in ("cross", "cruzamento")):
        add("crosses_attempted", "crosses_delivered")
    if any(term in text for term in ("minute", "minuto")):
        add("minutes_played")
    if any(term in text for term in ("rating", "nota", "avaliação", "nota")):
        add("game_rating")
    for fact in context.get("facts", []):
        if fact.get("id") != "pre_match_player_context" or fact.get("id") not in refs:
            continue
        previous = next((row for row in fact.get("value") or [] if int(row.get("player_ea_id") or -1) == int(selected.get("player_ea_id") or -2)), None)
        if previous:
            prev_stats = previous.get("stats") or {}
            for key in ("npk_goals", "goals_derived", "pk_goals", "assists", "npk_expected_goals",
                        "passes", "passes_completed", "pass_accuracy_pct_derived", "pressure_pass_accuracy_pct",
                        "shots", "shots_on_target", "saves", "saving_shots_on_target", "tackles",
                        "interceptions", "dribbles", "dribbles_completed", "aerial_duels_won",
                        "aerial_duels_attempted", "minutes_played"):
                value = _float(prev_stats.get(key))
                if value is not None:
                    allowed.append(value)
    # Only compare explicit numeric claims; qualitative interpretation is handled by other checks.
    claims = [_float(token.replace(",", ".")) for token in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", text)]
    claims = [value for value in claims if value is not None]
    return bool(claims and allowed and any(not any(abs(value - expected) <= 0.051 for expected in allowed) for value in claims))


def _report_accumulated_player_metric_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    facts = _report_fact_map(context)
    summary = facts.get("player_summary") or {}
    metrics = summary.get("metrics") or {}
    refs = set(item.get("fact_refs") or [])
    terms = ("goal", "gol", "gols", "goles", "assist", "xg", "expected goals", "passes", "pass",
             "passe", "shot", "chute", "finaliza", "rating", "nota", "dribble", "drible",
             "tackle", "desarme", "interception", "intercepta", "key pass", "passes-chave",
             "possession won", "posse ganha", "duel", "duelo")
    if not any(term in text for term in terms):
        return False
    if "player_summary" not in refs and "player_matchstats" not in refs:
        return True
    values = dict(metrics)
    values.update(summary)
    relevant_keys = {
        "goals": ("npk_goals", "goals_derived", "pk_goals", "own_goals"),
        "assists": ("assists", "secondary_assist"),
        "xg": ("npk_expected_goals", "expected_goals_derived", "xg"),
        "passes": ("passes", "passes_completed"),
        "shots": ("shots", "shots_on_target"),
        "rating": ("season_rating", "recent_rating", "average_rating"),
        "dribbles": ("dribbles", "dribbles_completed"),
        "tackles": ("tackles", "stand_tackles", "slide_tackles"),
        "interceptions": ("interceptions",),
        "key_passes": ("key_passes",),
        "minutes": ("minutes",),
        "appearances": ("appearances", "recent_appearances"),
    }
    requested = []
    if re.search(r"\b(?:goals?|gols?|goles?)\b", text): requested.extend(relevant_keys["goals"])
    if "assist" in text or "assistência" in text or "asistencia" in text: requested.extend(relevant_keys["assists"])
    if any(term in text for term in ("xg", "expected goals", "gols esperados")): requested.extend(relevant_keys["xg"])
    if "pass" in text or "passe" in text: requested.extend(relevant_keys["passes"])
    if "shot" in text or "chute" in text or "finaliza" in text: requested.extend(relevant_keys["shots"])
    if "rating" in text or "nota" in text: requested.extend(relevant_keys["rating"])
    if "%" in text or "percent" in text or "precisión" in text or "precisão" in text:
        requested.extend(("shot_accuracy_pct", "pass_accuracy_pct", "pressure_pass_accuracy_pct",
                          "dribble_success_pct", "cross_success_pct"))
    if "dribble" in text or "drible" in text: requested.extend(relevant_keys["dribbles"])
    if "tackle" in text or "desarme" in text: requested.extend(relevant_keys["tackles"])
    if "interception" in text or "intercepta" in text: requested.extend(relevant_keys["interceptions"])
    if "key pass" in text or "passes-chave" in text: requested.extend(relevant_keys["key_passes"])
    if "minute" in text or "minuto" in text: requested.extend(relevant_keys["minutes"])
    if "appearance" in text or "match" in text or "atuação" in text or "jogo" in text or "partida" in text: requested.extend(relevant_keys["appearances"])
    allowed = [_float(values.get(key)) for key in requested]
    allowed = [value for value in allowed if value is not None]
    claims = [_float(token.replace(",", ".")) for token in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", text)]
    claims = [value for value in claims if value is not None]
    return bool(claims and allowed and any(not any(abs(value - expected) <= 0.051 for expected in allowed) for value in claims))


def _report_uncompared_dominance_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    dominance_terms = ("dominaram", "dominou", "domínio", "dominance", "dominated", "dominating",
                       "superioridade", "superior", "outplayed", "controlou", "controlled the match")
    if not any(term in text for term in dominance_terms):
        return False
    if any(term in text for term in ("does not establish", "doesn't establish", "cannot establish", "does not prove",
                                      "não estabelece", "não comprova", "não prova", "no demuestra", "no confirma")):
        return False
    refs = set(item.get("fact_refs") or [])
    rows = next((fact.get("value") for fact in context.get("facts", [])
                 if fact.get("id") == "matchstats" and fact.get("id") in refs), [])
    match = _report_fact_map(context).get("match") or {}
    managed_id = int(match.get("managed_team_ea_id") or -1)
    opponent_id = int(match.get("opponent_ea_id") or -1)
    managed = next((row.get("stats") or {} for row in rows or [] if int(row.get("team_ea_id") or -1) == managed_id), {})
    opponent = next((row.get("stats") or {} for row in rows or [] if int(row.get("team_ea_id") or -1) == opponent_id), {})
    comparative_metrics = ("shots", "shots_on_target", "passes", "possession_won", "offense_duels_won",
                           "defense_duels_won", "aerial_duels_won", "tackles", "interceptions")
    has_comparable = any(managed.get(key) is not None and opponent.get(key) is not None for key in comparative_metrics)
    explicit_comparison = any(term in text for term in ("mais que", "mais do que", "acima do", "superou", "more than",
                                                         "higher than", "outnumbered", "exceeded", "superior a", "más que"))
    return not (has_comparable and explicit_comparison)


def _report_missing_metric_source_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    refs = set(item.get("fact_refs") or [])
    if any(term in text for term in ("long passes", "long pass", "passes longos", "passe longo", "pases largos")):
        cited_text = json.dumps([fact.get("value") for fact in context.get("facts", []) if fact.get("id") in refs],
                                ensure_ascii=False).casefold()
        if not any(term in cited_text for term in ("long_pass", "passe_longo", "long ball")):
            return True
    groups = (
        (("xg", "expected goals", "gols esperados", "goles esperados", "chance volume", "volume de chances",
          "volume of chances", "oportunidades criadas", "chances created"), {"matchstats", "match_players", "selected_match_player", "player_matchstats", "match_comparisons", "pre_match_team_context", "pre_match_player_context"}),
        (("shot", "finaliza", "chute", "tiro", "shots"), {"matchstats", "match_players", "selected_match_player", "player_matchstats", "match_comparisons", "pre_match_team_context", "pre_match_player_context"}),
        (("pass", "passe", "circula", "circulation", "progressão", "progression", "criação"), {"matchstats", "match_players", "selected_match_player", "player_matchstats", "match_comparisons", "pre_match_team_context", "pre_match_player_context"}),
        (("duel", "duelo", "duelos", "tackle", "desarme", "recuperaç", "recoveries", "interception", "interceptação"), {"matchstats", "match_players", "selected_match_player", "player_matchstats", "pre_match_team_context", "pre_match_player_context"}),
    )
    for terms, allowed in groups:
        if any(term in text for term in terms) and not (refs & allowed):
            return True
    conversion_terms = ("conversion", "conversão", "conversión", "finishing", "finalização", "eficiência de finalização")
    if any(term in text for term in conversion_terms) and not (refs & {"matchstats", "match_players", "selected_match_player", "player_matchstats", "match_comparisons", "pre_match_team_context", "pre_match_player_context"}):
        return True
    return False


def _report_unfounded_team_style_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    style_terms = ("playing style", "style", "estilo de jogo", "estilo da equipe", "estilo del equipo",
                   "approach", "abordagem", "abordaje", "transitions", "transições", "transiciones",
                   "individuality", "individualismo", "individualidade", "circulation", "circulação",
                   "circulación", "depends on", "depende de", "relies on", "se apoia em", "build-up",
                   "construction of play", "construção de jogo", "construcción de juego", "vertical",
                   "defensive effort", "esforço defensivo", "esfuerzo defensivo", "intense", "intenso",
                   "tactical", "tático", "táctico", "circulação eficiente", "efficient circulation",
                   "indicating", "indicando", "indica")
    if not any(term in text for term in style_terms):
        if item.get("kind") == "fact":
            return False
    facts = _report_fact_map(context)
    profile = facts.get("team_statistical_profile") or {}
    no_sample = not bool(profile.get("sample_sufficient"))
    if no_sample:
        return item.get("kind") != "fact"
    unavailable = " ".join(str(value) for value in profile.get("unavailable") or []).casefold()
    if any(term in text for term in ("passes under pressure", "pass under pressure", "passes sob pressão",
                                      "passes sob pressao", "high press", "pressão alta", "pressao alta")):
        if "pressure" in unavailable or "pressão" in unavailable or "pressao" in unavailable:
            return True
    # With enough data, broad tactical style remains a hypothesis, not a measured fact.
    if any(term in text for term in style_terms):
        return item.get("kind") != "hypothesis"
    return False


def _report_recommendation_confuses_xg_and_finishing(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    cited = set(item.get("fact_refs") or [])
    comparisons = next((fact.get("value") for fact in context.get("facts", [])
                        if fact.get("id") == "match_comparisons" and fact.get("id") in cited), [])
    asks_for_more_volume = any(term in text for term in ("increase the volume", "increase chances", "more chances",
        "create more chances", "aumentar o volume", "mais chances", "criar mais oportunidades",
        "aumentar oportunidades", "aumentar o número de finalizações"))
    if asks_for_more_volume:
        xg = next((row for row in comparisons or [] if row.get("metric_key") in {"expected_goals_derived", "npk_expected_goals"}), None)
        finishing = next((row for row in comparisons or [] if row.get("metric_key") == "finishing_delta"), None)
        if xg and finishing:
            current_xg, average_xg = _float(xg.get("current_match")), _float(xg.get("season_average"))
            current_delta = _float(finishing.get("current_match"))
            if current_delta is not None and current_delta < -0.25 and current_xg is not None and (
                average_xg is None or current_xg >= average_xg
            ):
                return True
    asks_for_finishing = any(term in text for term in ("finaliza", "finishing", "conversion", "conversão", "conversión"))
    mentions_xg = any(term in text for term in ("xg", "gols esperados", "expected goals"))
    if not asks_for_finishing or not mentions_xg:
        return False
    delta = next((row for row in comparisons or [] if row.get("metric_key") == "finishing_delta"), None)
    finishing_language = ("gols menos xg", "goals minus xg", "marcou mais do que seu xg", "scored more than its xg",
                          "gols acima do esperado", "goals above expected", "conversão acima", "finishing delta")
    return delta is None or not any(term in text for term in finishing_language)


def _report_unavailable_metric_recommendation_conflict(context: dict[str, Any], item: dict[str, Any]) -> bool:
    text = str(item.get("text") or "").casefold()
    if any(term in text for term in ("under pressure", "passes sob pressão", "passes sob pressao",
                                      "pressão alta", "pressao alta", "high press")):
        facts = _report_fact_map(context)
        cited = set(item.get("fact_refs") or [])
        sources = [facts.get(key) for key in cited]
        evidence = json.dumps(sources, ensure_ascii=False).casefold()
        if "passes_under_pressure" not in evidence and "passes_completed_under_pressure" not in evidence:
            return True
    spatial_terms = ("outside the box", "outside-area", "fora da área", "fora da area", "right flank", "left flank",
                     "corredor direito", "corredor esquerdo", "pelos flancos", "byline", "linha de fundo")
    if any(term in text for term in spatial_terms):
        return True
    return False


def _report_item_comparison_direction_conflict(context: dict[str, Any], mode: str, item: dict[str, Any]) -> bool:
    """Check explicit up/down claims against Atlas-computed same-metric comparisons."""
    if mode != "match":
        return False
    cited = set(item.get("fact_refs") or [])
    comparison_fact = next((fact.get("value") for fact in context.get("facts", [])
                            if fact.get("id") == "match_comparisons" and fact.get("id") in cited), None)
    if not isinstance(comparison_fact, list):
        return False
    text = str(item.get("text") or "").casefold()
    lower_terms = ("abaixo da média", "inferior à média", "menor que a média", "lower than average", "below the average", "below average", "less than average", "por debajo de la media", "inferior a la media")
    higher_terms = ("acima da média", "superior à média", "maior que a média", "higher than average", "above the average", "above average", "more than average", "por encima de la media", "superior a la media")
    has_lower, has_higher = any(term in text for term in lower_terms), any(term in text for term in higher_terms)
    direction = "lower" if has_lower and not has_higher else "higher" if has_higher and not has_lower else None
    if direction is None:
        return False
    if any(term in text for term in ("últimas cinco", "últimos cinco", "last five", "últimas 5", "últimos 5")):
        reference_key = "last_five_average"
    elif any(term in text for term in ("temporada", "season", "temporada")):
        reference_key = "season_average"
    else:
        return False
    metric_terms = (
        (("finalizações no alvo", "chutes no alvo", "shots on target", "tiros a puerta"), "shots_on_target"),
        (("gols sofridos", "sofreu", "goals conceded", "goals against", "encajó"), "goals_against"),
        (("gols marcados", "gols", "marcou", "goals scored", "scored"), "goals_for"),
        (("precisão de passe", "pass accuracy", "precisión de pase"), "pass_accuracy_pct_derived"),
        (("finalizações", "chutes", "shots", "tiros"), "shots"),
        (("xg", "gols esperados", "expected goals"), "expected_goals_derived"),
    )
    metric_key = next((key for terms, key in metric_terms if any(term in text for term in terms)), None)
    if metric_key is None:
        return False
    comparison = next((row for row in comparison_fact if row.get("metric_key") == metric_key), None)
    if not comparison:
        return False
    current, reference = _float(comparison.get("current_match")), _float(comparison.get(reference_key))
    if current is None or reference is None:
        return False
    if metric_key == "goals_against" and any(term in text for term in ("desvio positivo", "positive deviation", "positive delta", "desvio favorable", "favorable deviation")):
        return current > reference
    return current >= reference if direction == "lower" else current <= reference


def _report_coverage(context: dict[str, Any]) -> dict[str, Any]:
    facts = _report_fact_map(context)
    match_players = facts.get("match_players") or []
    history = facts.get("pre_match_team_context") or {}
    return {
        "detailed_match_statistics": "linked" if "matchstats" in facts else "unavailable",
        "players_with_detailed_rows": len(match_players),
        "previous_linked_matches": int(history.get("lookback_matches") or 0),
        "previous_five_matches": len(history.get("recent_five") or []),
        "observed_positions": sum(bool(item.get("observed_position")) for item in match_players),
        "limitations": [item["value"] for item in context.get("facts", []) if item.get("id") in {"matchstats_missing", "match_player_stats_missing"}],
    }


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
    coach_row = conn.execute(
        """SELECT snapshot_id,scope_key,source_hash,payload_json,generated_at FROM technical_commission_report_cache
             WHERE career_id=? AND snapshot_id=? AND mode=? AND scope_key GLOB ? AND model=?
             ORDER BY generated_at DESC LIMIT 1""",
        (career_id, snapshot_id, mode, f"{scope}:coach:*", selected),
    ).fetchone()
    row = conn.execute(
        """SELECT snapshot_id,source_hash,payload_json,generated_at FROM technical_commission_report_cache
             WHERE career_id=? AND mode=? AND scope_key=? AND model=? AND source_hash=?
             ORDER BY generated_at DESC,snapshot_id DESC LIMIT 1""",
        (career_id, mode, scope, selected, current_hash),
    ).fetchone()
    if coach_row and (not row or str(coach_row["generated_at"]) >= str(row["generated_at"])):
        value = json.loads(coach_row["payload_json"])
        coach_fact = next((item for item in value.get("fact_catalog", []) if item.get("id") == "coach_context"), None)
        coach_inputs = _normalize_report_clarifications(coach_fact.get("value") if coach_fact else None)
        coach_context = dict(context)
        if coach_fact:
            coach_context["facts"] = [*context.get("facts", []), coach_fact]
        suffix = hashlib.sha256(json.dumps(coach_inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        coach_scope = f"{scope}:coach:{suffix}"
        coach_hash = _report_source_hash(coach_context, career_id, mode, coach_scope)
        state = "ready" if str(coach_row["source_hash"]) == coach_hash else "stale"
        return {"state": state, "cached": True, "model": selected, "scope_key": coach_scope,
                "source_hash": coach_hash, "snapshot_id": int(coach_row["snapshot_id"]),
                "generated_at": coach_row["generated_at"], "result": value}
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
                          language: str | None = None,
                          clarifications: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Generate a cited, cached, local Ollama report from one selected Atlas context."""
    context, fact_ids, scope = _briefing_facts(conn, career_id, snapshot_id, mode, fixture_id, player_ea_id,
                                                 language, clarifications)
    clarifications = _normalize_report_clarifications(clarifications)
    if clarifications:
        suffix = hashlib.sha256(json.dumps(clarifications, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        scope = f"{scope}:coach:{suffix}"
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
        value.setdefault("source_hash", source_hash)
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
            "next_match": "Prepare a próxima partida com calendário, amostra de minutos e posições observadas. Sugira somente esquemas de allowed_formations. Separe adequação de elenco de escalação/disponibilidade.",
            "player": "Cruze radar e perfis de função já calculados com produção, eficiência por 90, recorte recente e pares da mesma posição no elenco. Compare amostras equivalentes; não infira hierarquia nem titularidade.",
            "match_player": "Compare o desempenho desta atuação com as últimas cinco atuações válidas anteriores do jogador e com atletas da mesma posição registrados nesta partida, quando houver dados. Considere contribuição ofensiva e defensiva, não só nota e gols.",
            "team_identity": "Interprete tendências e recortes calculados pelo Atlas. Só proponha hipótese sobre estilo de jogo se sample_sufficient=true; caso contrário descreva apenas métricas observadas. Associação não prova causa nem instrução tática.",
            "match": "Contextualize resultado versus desempenho; compare criação/concessão, volume/qualidade, circulação, progressão e ações defensivas atuais com médias anteriores e últimas cinco partidas válidas. Compare atletas com a mesma posição observada quando registrada. Identifique desvio, padrão, impacto e acompanhamento útil, sem atribuir causa não observada.",
        },
        "en-GB": {
            "next_match": "Prepare the next fixture using the calendar, recorded minutes and observed positions. Recommend only shapes in allowed_formations. Separate squad fit from confirmed selection or availability.",
            "player": "Combine Atlas role and attribute profiles with production, per-90 efficiency, recent form and same-position squad peers. Compare samples fairly; do not infer hierarchy or starting status.",
            "match_player": "Compare this appearance with the player's previous five valid appearances and with players recorded in the same position in this fixture where data exists. Consider attacking and defensive contribution, not only rating and goals.",
            "team_identity": "Interpret Atlas-calculated trends. Offer a playing-style hypothesis only when sample_sufficient=true; otherwise describe measured statistics only. Association does not prove a cause or tactical instruction.",
            "match": "Contextualise result versus performance; compare chance creation/concession, volume/quality, circulation, progression and defensive actions with prior averages and the last five valid fixtures. Compare players at the same observed position when recorded. Identify deviations, patterns, impact and useful follow-up without assigning unobserved causes.",
        },
        "es-ES": {
            "next_match": "Prepara el próximo partido con calendario, minutos y posiciones observadas. Recomienda solo esquemas de allowed_formations. Separa la compatibilidad de plantilla de una alineación o disponibilidad confirmada.",
            "player": "Cruza perfiles de función y atributos de Atlas con producción, eficiencia por 90, rendimiento reciente y compañeros de la misma posición. Compara muestras equivalentes; no infieras jerarquía ni titularidad.",
            "match_player": "Compara esta actuación con las cinco actuaciones válidas anteriores del jugador y con jugadores registrados en la misma posición en este partido cuando haya datos. Considera aportes ofensivos y defensivos, no solo nota y goles.",
            "team_identity": "Interpreta tendencias calculadas por Atlas. Propón una hipótesis de estilo solo si sample_sufficient=true; de lo contrario describe únicamente métricas observadas. Una asociación no demuestra una causa ni una instrucción táctica.",
            "match": "Contextualiza resultado frente a rendimiento; compara creación/concesión, volumen/calidad, circulación, progresión y acciones defensivas con promedios previos y los últimos cinco partidos válidos. Compara jugadores en la misma posición observada cuando esté registrada. Identifica desviaciones, patrones, impacto y seguimiento útil sin atribuir causas no observadas.",
        },
    }
    language_tasks = tasks.get(language, tasks["pt-BR"])
    task = language_tasks.get(mode, language_tasks["match"])
    system = build_system_prompt(language_name, task, mode)
    if mode == "match_player":
        system += (" This is an individual report about the selected managed-team player. For current-match individual statistics, cite the exact selected_match_player fact; matchstats contains team rows. For prior performances, cite pre_match_player_context and identify them as earlier evidence. Keep observations about the selected player; use the opponent only as match context. Recommendations, strengths, development areas and training suggestions must apply to the selected player, never the opponent or a different teammate. Do not give team tactical recommendations in an individual report.")
    elif mode == "player":
        system += (" This is an accumulated individual report. Keep conclusions about the selected player, their recorded position and their own comparable history. Do not convert team totals into individual contribution.")
    system += (" Ask for more context only when a specific qualitative answer from the coach could materially change the interpretation or recommendation and Atlas does not record it. Ask only about coach-only context such as intended instructions, tactical plan, or an observed adjustment. Never ask the coach to supply performance statistics, recent or historical results, player minutes, goals, xG, shots, ratings, or other figures; these are Atlas data questions, not coach-context questions. Continue with a qualified analysis when no coach-only answer is needed. Return at most two concise information_requests, each with question and reason, in the selected language; return an empty list when there is no material coach-context gap. Treat coach_context as unverified user narrative, never as an imported Atlas statistic. If coach_context is supplied, use it only for the stated context and label any use as coach-provided. If six coach answers are already present, return no more requests.")
    allowed_shapes = context.get("allowed_formations") or []
    formation_schema = {"type": "null"}
    if mode == "next_match" and allowed_shapes:
        formation_schema = {"type": "object", "additionalProperties": False,
                            "properties": {"shape": {"type": "string", "enum": allowed_shapes},
                                           "reason": {"type": "string", "maxLength": 500},
                                           "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                            "required": ["shape", "reason", "fact_refs"]}
    claim_schema = {"type": "object", "additionalProperties": False,
                    "properties": {"text": {"type": "string", "maxLength": 500},
                                   "kind": {"type": "string", "enum": ["fact", "inference", "hypothesis"]},
                                   "limitations": {"type": "string", "maxLength": 500},
                                   "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                    "required": ["text", "kind", "limitations", "fact_refs"]}
    information_request_schema = {"type": "object", "additionalProperties": False,
                                  "properties": {"question": {"type": "string", "maxLength": 280},
                                                 "reason": {"type": "string", "maxLength": 280}},
                                  "required": ["question", "reason"]}
    response_schema = {"type": "object", "additionalProperties": False,
                       "properties": {"summary": {"type": "object", "additionalProperties": False,
                                                   "properties": {"text": {"type": "string", "maxLength": 900},
                                                                  "kind": {"type": "string", "enum": ["fact", "inference", "hypothesis"]},
                                                                  "limitations": {"type": "string", "maxLength": 500},
                                                                  "fact_refs": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
                                                   "required": ["text", "kind", "limitations", "fact_refs"]},
                                      "observations": {"type": "array", "maxItems": 8, "items": claim_schema},
                                      "recommendations": {"type": "array", "maxItems": 8, "items": claim_schema},
                                      "strengths": {"type": "array", "maxItems": 8, "items": claim_schema},
                                      "development_areas": {"type": "array", "maxItems": 8, "items": claim_schema},
                                      "training_suggestions": {"type": "array", "maxItems": 8, "items": claim_schema},
                                      "information_requests": {"type": "array", "maxItems": 2, "items": information_request_schema},
                                      "formation": formation_schema},
                       "required": ["summary", "observations", "recommendations", "strengths", "development_areas", "training_suggestions", "formation", "information_requests"]}
    body = {"model": selected, "stream": False, "format": response_schema, "think": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(prompt_evidence(context), ensure_ascii=False, sort_keys=True)}],
            "keep_alive": "10m", "options": {"temperature": 0.2, "num_predict": 4600}}
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
        requests = []
        raw_requests = report.get("information_requests") if isinstance(report.get("information_requests"), list) else []
        for request in raw_requests[:2]:
            if not isinstance(request, dict):
                continue
            question = str(request.get("question") or "").strip()[:280]
            reason = str(request.get("reason") or "").strip()[:280]
            if question and reason and _coach_can_answer_information_request(question, reason):
                requests.append({"question": question, "reason": reason})
        if len(_normalize_report_clarifications(clarifications)) >= 6:
            requests = []
        report["information_requests"] = requests
        valid_ids = set(fact_ids)
        default_refs = {"match": ["match", "matchstats", "match_players", "pre_match_team_context"],
                        "match_player": ["match", "matchstats", "match_players", "selected_match_player", "pre_match_player_context"],
                        "player": ["player_checkpoint", "player_summary", "player_position_peers", "player_recent_matches", "player_matchstats"],
                        "team_identity": ["team_statistical_profile", "opponent_profiles"],
                        "next_match": ["match", "squad", "formation_options", "previous_fixture", "following_fixture"]}
        safe_default_refs = [item for item in default_refs.get(mode, []) if item in valid_ids]
        deterministic_summary = _deterministic_report_summary(context)
        summary = report.get("summary")
        rejected_details: list[dict[str, Any]] = []
        accepted_score_bindings: list[dict[str, Any]] = []
        summary_reasons: list[str] = []
        summary_valid = (isinstance(summary, dict) and _validate_report_item(context, mode, summary, valid_ids,
                                                                              rejection_reasons=summary_reasons)
                         and not is_generic_claim(summary.get("text", ""), "summary"))
        if summary_valid and mode in {"match", "match_player"}:
            accepted_score_bindings.extend(score_claim_bindings(context, summary)[0])
        elif not summary_valid:
            if isinstance(summary, dict) and not summary_reasons:
                summary_reasons.append("generic_claim")
            rejected_details.append({"section": "summary", "text": str(summary.get("text") or "")[:700]
                                     if isinstance(summary, dict) else "", "reasons": summary_reasons or ["invalid_claim"]})
        if summary_valid:
            report["summary"] = {"text": summary["text"][:900], "kind": summary["kind"],
                                  "limitations": str(summary.get("limitations") or "")[:500],
                                  "fact_refs": summary["fact_refs"]}
        elif deterministic_summary:
            report["summary"] = {"text": deterministic_summary["text"], "kind": "fact", "limitations": "",
                                  "fact_refs": deterministic_summary["fact_refs"]}
        else:
            report["summary"] = {"text": "Análise limitada aos fatos e métricas disponíveis neste recorte.",
                                  "kind": "fact", "limitations": "", "fact_refs": safe_default_refs}
        report["summary"]["model_generated"] = bool(summary_valid)
        accepted_claims = 1 if summary_valid else 0
        rejected_claims = 0 if summary_valid else 1
        seen_claims = {claim_signature(report["summary"]["text"])} if summary_valid else set()
        for key in ("observations", "recommendations", "strengths", "development_areas", "training_suggestions"):
            values = report.get(key) if isinstance(report.get(key), list) else []
            cleaned = []
            for item in values:
                reasons: list[str] = []
                if not isinstance(item, dict) or not _validate_report_item(context, mode, item, valid_ids,
                                                                            section=key, rejection_reasons=reasons):
                    rejected_claims += 1
                    rejected_details.append({"section": key,
                                             "text": str(item.get("text") or "")[:700] if isinstance(item, dict) else "",
                                             "reasons": reasons or ["invalid_claim"]})
                    continue
                # The same claim in the summary/observations/recommendations is not
                # three distinct insights. Keep its first fully validated occurrence.
                signature = claim_signature(item["text"])
                if not signature or signature in seen_claims:
                    rejected_claims += 1
                    rejected_details.append({"section": key, "text": item["text"][:700],
                                             "reasons": ["duplicate_claim"]})
                    continue
                seen_claims.add(signature)
                if mode in {"match", "match_player"}:
                    accepted_score_bindings.extend(score_claim_bindings(context, item)[0])
                cleaned.append({"text": item["text"][:700], "kind": item["kind"],
                                "limitations": str(item.get("limitations") or "")[:500],
                                "fact_refs": item["fact_refs"]})
            report[key] = cleaned
        if mode not in {"player", "match_player"}:
            for key in ("strengths", "development_areas", "training_suggestions"):
                report[key] = []
        accepted_claims += sum(len(report.get(key) or []) for key in ("observations", "recommendations", "strengths", "development_areas", "training_suggestions"))
        deterministic_note = _commission_note(context)
        if deterministic_note:
            report["commission_note"] = deterministic_note
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
        accepted_claims += int(report.get("formation") is not None)
        validation = {"method": "source-reference, evidence-scope, and objective-contradiction checks",
                      "accepted_claims": accepted_claims, "rejected_claims": rejected_claims,
                      "rejected_claim_details": rejected_details[:100],
                      "accepted_score_bindings": accepted_score_bindings[:100],
                      "interpretation_quality": "not independently scored"}
        result = {"available": True, "fallback": False, "cached": False, "model": selected,
                  "mode": mode, "scope_key": scope, "report": report, "fact_catalog": context["facts"],
                  "coach_context_received": bool(clarifications),
                  "source_hash": source_hash, "report_version": REPORT_VERSION,
                  "coverage": _report_coverage(context), "validation": validation,
                  "review_required": rejected_claims > 0}
        conn.execute("""INSERT INTO technical_commission_report_cache(career_id,snapshot_id,mode,scope_key,model,source_hash,payload_json)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(career_id,snapshot_id,mode,scope_key,model) DO UPDATE SET
            source_hash=excluded.source_hash,payload_json=excluded.payload_json,generated_at=CURRENT_TIMESTAMP""",
            (career_id, snapshot_id, mode, scope, selected, source_hash,
             json.dumps(result, ensure_ascii=False, sort_keys=True)))
        return result
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, TimeoutError) as exc:
        detail = str(exc).replace("\n", " ")[:120]
        return {"available": False, "fallback": True, "cached": False, "model": selected,
                "source_hash": source_hash, "report_version": REPORT_VERSION,
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
    snapshot = conn.execute("SELECT season_index,import_sequence FROM snapshots WHERE id=? AND career_id=?",
                            (snapshot_id, career_id)).fetchone()
    if not snapshot:
        return []
    export = conn.execute(
        """SELECT e.id FROM match_stat_exports e JOIN snapshots source_snapshot ON source_snapshot.id=e.snapshot_id
             WHERE e.fixture_id=? AND e.career_id=? AND source_snapshot.season_index=?
             AND source_snapshot.import_sequence<=?
             AND e.linkage_status='linked' AND e.export_status='complete_participant_export'
             AND e.superseded_by_export_id IS NULL ORDER BY e.id DESC LIMIT 1""",
        (fixture_id, career_id, int(snapshot["season_index"]), int(snapshot["import_sequence"])),
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


def _historical_report_tasks(conn: Any, career_id: int, season_index: int | None = None) -> list[dict[str, Any]]:
    """Build one chronological checkpoint per event snapshot, never from a season's final snapshot."""
    if season_index is None:
        selected = conn.execute(
            "SELECT season_index FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
            (career_id,),
        ).fetchone()
        if not selected:
            return []
        season_index = int(selected["season_index"])
    latest = conn.execute(
        "SELECT id,managed_team_ea_id FROM snapshots WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
        (career_id, int(season_index)),
    ).fetchone()
    if not latest:
        return []
    fixtures = conn.execute(
        """SELECT fo.fixture_id,fo.date FROM fixture_observations fo
             WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1
             ORDER BY CASE WHEN fo.date IS NULL OR fo.date='' THEN 1 ELSE 0 END,fo.date,fo.fixture_id""",
        (int(latest["id"]),),
    ).fetchall()
    checkpoints: list[dict[str, Any]] = []
    for fixture in fixtures:
        fixture_id = int(fixture["fixture_id"])
        source = conn.execute(
            """SELECT s.id,s.season_index,s.import_sequence,s.career_date,s.managed_team_ea_id
                 FROM fixture_observations fo JOIN snapshots s ON s.id=fo.snapshot_id
                WHERE s.career_id=? AND s.season_index=? AND fo.fixture_id=?
                  AND fo.managed_team_involved=1 AND fo.is_completed=1
                ORDER BY s.import_sequence,s.id LIMIT 1""",
            (career_id, int(season_index), fixture_id),
        ).fetchone()
        if not source:
            continue
        snapshot_id = int(source["id"])
        team_id = int(source["managed_team_ea_id"] or latest["managed_team_ea_id"] or -1)
        match_date = str(fixture["date"] or "")
        checkpoint = {"snapshot_id": snapshot_id, "season_index": int(season_index),
                      "import_sequence": int(source["import_sequence"]), "event_date": match_date,
                      "fixture_id": fixture_id, "team_id": team_id}
        label = f"{match_date or 'date unavailable'} · {fixture_id}"
        checkpoints.append(checkpoint | {"stage": "match", "mode": "match", "player_ea_id": None,
                                         "label": f"{label} · team match report"})
        player_ids = _managed_player_ids_for_fixture(conn, career_id, snapshot_id, fixture_id, team_id)
        for player_id in player_ids:
            checkpoints.append(checkpoint | {"stage": "match_player", "mode": "match_player",
                "player_ea_id": player_id, "label": f"{label} · player {player_id} match report"})
        checkpoints.append(checkpoint | {"stage": "team_checkpoint", "mode": "team_identity",
            "player_ea_id": None, "label": f"{label} · accumulated team assessment"})
        for player_id in player_ids:
            checkpoints.append(checkpoint | {"stage": "player_checkpoint", "mode": "player",
                "player_ea_id": player_id, "label": f"{label} · player {player_id} accumulated assessment"})
    return checkpoints


def _ensure_replay_schema(conn: Any) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS technical_commission_replay_runs (
        job_id TEXT PRIMARY KEY, career_id INTEGER NOT NULL REFERENCES careers(id), season_index INTEGER NOT NULL,
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), model TEXT NOT NULL, language TEXT NOT NULL,
        report_version INTEGER NOT NULL, status TEXT NOT NULL, total_tasks INTEGER NOT NULL DEFAULT 0,
        completed_tasks INTEGER NOT NULL DEFAULT 0, generated INTEGER NOT NULL DEFAULT 0,
        reused INTEGER NOT NULL DEFAULT 0, skipped_missing_data INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0, review_required INTEGER NOT NULL DEFAULT 0,
        current_task TEXT, backup_path TEXT, errors_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_commission_replay_run_scope
        ON technical_commission_replay_runs(career_id,season_index,report_version,status,created_at)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS technical_commission_replay_tasks (
        job_id TEXT NOT NULL REFERENCES technical_commission_replay_runs(job_id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        import_sequence INTEGER NOT NULL, season_index INTEGER NOT NULL, event_date TEXT, fixture_id INTEGER NOT NULL,
        stage TEXT NOT NULL, mode TEXT NOT NULL, player_ea_id INTEGER, label TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        source_hash TEXT, error TEXT, report_json TEXT,
        started_at TEXT, completed_at TEXT, PRIMARY KEY(job_id,sequence))""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_commission_replay_task_status
        ON technical_commission_replay_tasks(job_id,status,sequence)""")


def _replay_progress(conn: Any, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM technical_commission_replay_runs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["errors"] = json.loads(result.pop("errors_json") or "[]")
    task_counts = {str(item["status"]): int(item["amount"]) for item in conn.execute(
        "SELECT status,COUNT(*) amount FROM technical_commission_replay_tasks WHERE job_id=? GROUP BY status",
        (job_id,)).fetchall()}
    result["task_status_counts"] = task_counts
    result["pending"] = task_counts.get("pending", 0)
    result["running"] = task_counts.get("running", 0)
    result["job_id"] = job_id
    return result


def _find_resumable_replay(conn: Any, career_id: int, season_index: int, model: str) -> dict[str, Any] | None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='technical_commission_replay_runs'").fetchone()
    if not exists:
        return None
    row = conn.execute(
        """SELECT job_id,status,backup_path FROM technical_commission_replay_runs
             WHERE career_id=? AND season_index=? AND model=? AND report_version=?
               AND status IN ('queued','running','paused','paused_offline','complete_with_warnings','failed')
             ORDER BY created_at DESC LIMIT 1""",
        (career_id, season_index, model, REPORT_VERSION),
    ).fetchone()
    return dict(row) if row else None


def _run_retroactive_commission_reports_guarded(database: Any, career_id: int, job_id: str,
                                               language: str, model: str) -> None:
    """Persist unexpected worker exceptions instead of leaving a false running state."""
    try:
        run_retroactive_commission_reports(database, career_id, job_id, language, model)
    except Exception as exc:
        detail = f"{exc.__class__.__name__}: {str(exc)[:240]}"
        with database.connect() as conn:
            row = conn.execute("SELECT errors_json FROM technical_commission_replay_runs WHERE job_id=?",
                               (job_id,)).fetchone()
            if not row:
                return
            errors = json.loads(row["errors_json"] or "[]")
            errors.append({"stage": "worker", "message": detail})
            conn.execute("""UPDATE technical_commission_replay_runs
                           SET status='failed',current_task=NULL,errors_json=?,updated_at=CURRENT_TIMESTAMP
                           WHERE job_id=?""", (json.dumps(errors, ensure_ascii=False), job_id))


def start_retroactive_commission_reports(database: Any, career_id: int, season_index: int,
                                         model: str, language: str, backup_path: str = "") -> dict[str, str]:
    """Persist an ordered run and its tasks before scheduling local model work."""
    job_id = uuid.uuid4().hex
    with database.connect() as conn:
        _ensure_replay_schema(conn)
        resumable = _find_resumable_replay(conn, career_id, season_index, model)
        if resumable:
            job_id = str(resumable["job_id"])
            failed_count = int(conn.execute(
                "SELECT COUNT(*) FROM technical_commission_replay_tasks WHERE job_id=? AND status='failed'",
                (job_id,),
            ).fetchone()[0])
            conn.execute("UPDATE technical_commission_replay_tasks SET status='pending',attempts=0,started_at=NULL,completed_at=NULL,error=NULL WHERE job_id=? AND status='failed'",
                         (job_id,))
            conn.execute("UPDATE technical_commission_replay_runs SET status='queued',updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                         (job_id,))
            if failed_count:
                conn.execute("UPDATE technical_commission_replay_runs SET failed=MAX(0,failed-?),completed_tasks=MAX(0,completed_tasks-?) WHERE job_id=?",
                             (failed_count, failed_count, job_id))
            conn.execute("UPDATE technical_commission_replay_tasks SET status='pending',started_at=NULL WHERE job_id=? AND status='running'",
                         (job_id,))
            deduplicated = True
        else:
            snapshot = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
                (career_id, season_index),
            ).fetchone()
            if not snapshot:
                raise ValueError("No imported snapshot exists for the selected season.")
            tasks = _historical_report_tasks(conn, career_id, season_index)
            conn.execute(
                """INSERT INTO technical_commission_replay_runs
                   (job_id,career_id,season_index,snapshot_id,model,language,report_version,status,total_tasks,backup_path)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (job_id, career_id, season_index, int(snapshot["id"]), model, language, REPORT_VERSION,
                 "queued", len(tasks), backup_path),
            )
            for sequence, task in enumerate(tasks, 1):
                conn.execute(
                    """INSERT INTO technical_commission_replay_tasks
                       (job_id,sequence,snapshot_id,import_sequence,season_index,event_date,fixture_id,stage,mode,
                        player_ea_id,label,status,error)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (job_id, sequence, task["snapshot_id"], task["import_sequence"], task["season_index"],
                     task["event_date"] or None, task["fixture_id"], task["stage"], task["mode"],
                     task["player_ea_id"], task["label"], "pending",
                     "Fixture date missing; chronological context cannot be established." if not task["event_date"] else None),
                )
            conn.execute("""UPDATE technical_commission_replay_tasks SET status='skipped_missing_data'
                              WHERE job_id=? AND event_date IS NULL""", (job_id,))
            conn.execute("""UPDATE technical_commission_replay_runs SET skipped_missing_data=(
                              SELECT COUNT(*) FROM technical_commission_replay_tasks WHERE job_id=? AND status='skipped_missing_data')
                              WHERE job_id=?""", (job_id, job_id))
            deduplicated = False
    _REPORT_EXECUTOR.submit(_run_retroactive_commission_reports_guarded,
                            database, career_id, job_id, language, model)
    return {"job_id": job_id, "status": "queued", "deduplicated": str(deduplicated).lower()}


def run_retroactive_commission_reports(database: Any, career_id: int, job_id: str,
                                       language: str | None = None, model: str | None = None) -> None:
    """Resume one persisted chronological queue; each task is committed before advancing."""
    selected_model = model or os.environ.get("ATLAS_OLLAMA_MODEL") or "qwen3.5:9b"
    with database.connect() as conn:
        _ensure_replay_schema(conn)
        run = conn.execute("SELECT * FROM technical_commission_replay_runs WHERE job_id=? AND career_id=?",
                           (job_id, career_id)).fetchone()
        if not run:
            raise ValueError("Historical report task not found for this career.")
        if int(run["report_version"]) != REPORT_VERSION:
            raise ValueError("Replay report contract changed; create a new run to invalidate stale tasks.")
        conn.execute("UPDATE technical_commission_replay_tasks SET status='pending',started_at=NULL WHERE job_id=? AND status='running'",
                     (job_id,))
        conn.execute("UPDATE technical_commission_replay_runs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                     (job_id,))
        task_rows = conn.execute(
            "SELECT * FROM technical_commission_replay_tasks WHERE job_id=? AND status='pending' ORDER BY sequence",
            (job_id,),
        ).fetchall()
    if task_rows and not ollama_models(timeout=3.0).get("available"):
        with database.connect() as conn:
            conn.execute("UPDATE technical_commission_replay_runs SET status='paused_offline',current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                         (job_id,))
        return
    for task_row in task_rows:
        task = dict(task_row)
        fixture_arg = int(task["fixture_id"]) if task["mode"] in {"match", "match_player"} or task["stage"] in {"team_checkpoint", "player_checkpoint"} else None
        player_arg = int(task["player_ea_id"]) if task["player_ea_id"] is not None else None
        try:
            with database.connect() as conn:
                conn.execute("UPDATE technical_commission_replay_runs SET current_task=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                             (task["label"], job_id))
                cached = get_cached_commission_report(conn, career_id, int(task["snapshot_id"]), task["mode"],
                    fixture_arg, player_arg,
                    selected_model, language)
                was_cached = cached.get("state") == "ready"
                result = cached.get("result") if was_cached else None
        except ValueError as exc:
            # A single historical player checkpoint may no longer have a
            # professional-squad row. Record it and continue the chronological queue.
            message = f"{exc.__class__.__name__}: {str(exc)[:240]}"
            with database.connect() as conn:
                conn.execute("""UPDATE technical_commission_replay_tasks
                               SET status='skipped_missing_data',error=?,completed_at=CURRENT_TIMESTAMP
                               WHERE job_id=? AND sequence=?""", (message, job_id, task["sequence"]))
                conn.execute("""UPDATE technical_commission_replay_runs
                               SET skipped_missing_data=skipped_missing_data+1,current_task=NULL,
                                   updated_at=CURRENT_TIMESTAMP WHERE job_id=?""", (job_id,))
            continue
        except Exception as exc:
            message = f"{exc.__class__.__name__}: {str(exc)[:240]}"
            with database.connect() as conn:
                row = conn.execute("SELECT errors_json FROM technical_commission_replay_runs WHERE job_id=?",
                                   (job_id,)).fetchone()
                errors = json.loads(row["errors_json"] or "[]") if row else []
                errors.append({"sequence": int(task["sequence"]), "stage": task["stage"],
                               "player_ea_id": task["player_ea_id"], "message": message})
                conn.execute("""UPDATE technical_commission_replay_tasks
                               SET status='failed',error=?,completed_at=CURRENT_TIMESTAMP
                               WHERE job_id=? AND sequence=?""", (message, job_id, task["sequence"]))
                conn.execute("""UPDATE technical_commission_replay_runs
                               SET errors_json=?,failed=failed+1,completed_tasks=completed_tasks+1,
                                   current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                             (json.dumps(errors, ensure_ascii=False), job_id))
            continue
        if not was_cached:
            result = None
            message = "Report unavailable"
            for attempt in range(int(task.get("attempts") or 0) + 1, 3):
                with database.connect() as conn:
                    conn.execute("""UPDATE technical_commission_replay_tasks SET status='running',attempts=?,
                                      started_at=COALESCE(started_at,CURRENT_TIMESTAMP),error=NULL WHERE job_id=? AND sequence=?""",
                                 (attempt, job_id, task["sequence"]))
                    try:
                        result = get_commission_report(conn, career_id, int(task["snapshot_id"]), task["mode"],
                            fixture_arg, player_arg, selected_model, language=language, force_refresh=False)
                    except Exception as exc:
                        result = {"available": False, "message": f"{exc.__class__.__name__}: {str(exc)[:180]}"}
                if result and result.get("available"):
                    break
                message = str((result or {}).get("message") or "Report unavailable")[:300]
                if not ollama_models(timeout=2.0).get("available"):
                    with database.connect() as conn:
                        conn.execute("UPDATE technical_commission_replay_tasks SET status='pending',error=? WHERE job_id=? AND sequence=?",
                                     (message, job_id, task["sequence"]))
                        conn.execute("UPDATE technical_commission_replay_runs SET status='paused_offline',current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                                     (job_id,))
                    return
            if not result or not result.get("available"):
                errors = []
                with database.connect() as conn:
                    conn.execute("UPDATE technical_commission_replay_tasks SET status='failed',error=?,completed_at=CURRENT_TIMESTAMP WHERE job_id=? AND sequence=?",
                                 (message, job_id, task["sequence"]))
                    row = conn.execute("SELECT errors_json FROM technical_commission_replay_runs WHERE job_id=?", (job_id,)).fetchone()
                    errors = json.loads(row["errors_json"] or "[]")
                    errors.append({"sequence": int(task["sequence"]), "fixture_id": task["fixture_id"],
                                   "stage": task["stage"], "player_ea_id": task["player_ea_id"], "message": message})
                    conn.execute("""UPDATE technical_commission_replay_runs SET errors_json=?,failed=failed+1,
                                      completed_tasks=completed_tasks+1,current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                                 (json.dumps(errors, ensure_ascii=False), job_id))
                continue
        with database.connect() as conn:
            status = "reused" if was_cached or result.get("cached") else "completed"
            conn.execute("""UPDATE technical_commission_replay_tasks SET status=?,source_hash=?,report_json=?,
                              completed_at=CURRENT_TIMESTAMP,error=NULL WHERE job_id=? AND sequence=?""",
                         (status, result.get("source_hash"), json.dumps(result, ensure_ascii=False, sort_keys=True),
                          job_id, task["sequence"]))
            conn.execute("""UPDATE technical_commission_replay_runs SET completed_tasks=completed_tasks+1,
                              generated=generated+?,reused=reused+?,review_required=review_required+?,
                              current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                         (int(status == "completed"), int(status == "reused"), int(bool(result.get("review_required"))), job_id))
    with database.connect() as conn:
        counts = {str(row["status"]): int(row["amount"]) for row in conn.execute(
            "SELECT status,COUNT(*) amount FROM technical_commission_replay_tasks WHERE job_id=? GROUP BY status",
            (job_id,)).fetchall()}
        pending = counts.get("pending", 0) + counts.get("running", 0)
        failed = counts.get("failed", 0)
        skipped = counts.get("skipped_missing_data", 0)
        final = "paused" if pending else "complete" if not failed and not skipped else "complete_with_warnings"
        conn.execute("UPDATE technical_commission_replay_runs SET status=?,current_task=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                     (final, job_id))


def get_retroactive_commission_report_job(database: Any, career_id: int, job_id: str) -> dict[str, Any]:
    with database.connect() as conn:
        _ensure_replay_schema(conn)
        result = _replay_progress(conn, job_id)
    if not result or int(result.get("career_id") or -1) != int(career_id):
        raise ValueError("Historical report task not found for this career.")
    return result


def backfill_commission(conn: Any, career_id: int) -> int:
    snapshots = conn.execute("SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence", (career_id,)).fetchall()
    for row in snapshots:
        get_commission(conn, career_id, int(row["id"]))
    return len(snapshots)
