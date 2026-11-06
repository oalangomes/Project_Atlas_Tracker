"""Position-aware evidence selection for the Atlas Technical Commission.

This is a *prompt projection*, not a change to stored FC26 facts. The original
context remains the validation source. The role is resolved only from a
position recorded at the report's permitted historical checkpoint.
"""
from __future__ import annotations

import copy
import re
from statistics import median
import unicodedata
from typing import Any


_COMMON = (
    "minutes", "minutes_played", "appearances", "game_rating", "rating",
    "season_rating", "recent_rating", "valid_games",
)
_PASSING = ("passes", "passes_completed", "pass_accuracy_pct_derived", "pass_accuracy_pct",
            "passes_under_pressure", "passes_completed_under_pressure", "pressure_pass_accuracy_pct")
_DEFENCE = ("tackles", "interceptions", "blocks", "clearances", "possession_won",
            "possession_lost", "defense_duels_attempted", "defense_duels_won",
            "defense_duel_success_pct_derived", "aerial_duels_attempted",
            "aerial_duels_won", "aerial_duel_success_pct_derived")
_ATTACK = ("goals_derived", "npk_goals", "goals_per90", "assists", "assists_per90",
           "npk_expected_goals", "expected_goals_derived", "xg_per90",
           "expected_assists", "xa_per90", "xg_plus_xa_per90",
           "shots", "shots_on_target", "xg_per_shot", "npk_finishing_delta")
_CREATION = ("key_passes", "crosses_attempted", "crosses_delivered",
             "cross_success_pct_derived", "tracker_completed_through_passes_including_lobbed",
             "dribbles", "dribbles_completed", "dribble_success_pct_derived")

# Ordered, not ranked. "Relevant" does not mean a missing measurement is known or
# a recorded event proves its tactical cause.
_ROLE_METRICS: dict[str, tuple[str, ...]] = {
    "goalkeeper": _COMMON + ("saves", "shots_against", "saving_shots_on_target",
                            "goals_conceded", "clearances") + _PASSING,
    "centre_back": _COMMON + _DEFENCE + _PASSING,
    "fullback": _COMMON + _DEFENCE + _PASSING + _CREATION,
    "defensive_midfielder": _COMMON + _DEFENCE + _PASSING + ("key_passes",),
    "central_midfielder": _COMMON + _PASSING + _DEFENCE + _CREATION + ("assists", "expected_assists"),
    "attacking_midfielder": _COMMON + _PASSING + _CREATION + _ATTACK + ("possession_won",),
    "winger": _COMMON + _CREATION + _ATTACK + _PASSING + ("possession_won",),
    "striker": _COMMON + _ATTACK + ("key_passes", "passes", "passes_completed",
                                  "aerial_duels_won", "aerial_duels_attempted",
                                  "aerial_duel_success_pct_derived"),
}
_POSITION_ROLE = {
    "GK": "goalkeeper", "GOALKEEPER": "goalkeeper",
    "CB": "centre_back", "LCB": "centre_back", "RCB": "centre_back", "SW": "centre_back",
    "LB": "fullback", "RB": "fullback", "LWB": "fullback", "RWB": "fullback",
    "CDM": "defensive_midfielder", "LDM": "defensive_midfielder", "RDM": "defensive_midfielder",
    "CM": "central_midfielder", "LCM": "central_midfielder", "RCM": "central_midfielder",
    "CAM": "attacking_midfielder", "LAM": "attacking_midfielder", "RAM": "attacking_midfielder",
    "LM": "winger", "RM": "winger", "LW": "winger", "RW": "winger",
    "LF": "striker", "RF": "striker", "CF": "striker", "ST": "striker",
}

# MatchStats fields worth checking as positive contributions outside the player's
# primary role. Counts need a minimum raw sample; per-90 comparison then adjusts
# for minutes. This is a deterministic shortlist, not a judgement of tactics.
CROSS_ROLE_METRIC_FIELDS = (
    "offense_duels_attempted", "offense_duels_won", "offense_duel_success_pct_derived",
    "stand_tackles", "stand_tackles_won", "stand_tackle_success_pct_derived",
    "slide_tackles", "slide_tackles_won", "slide_tackle_success_pct_derived",
    "dribbles", "dribble_success_pct_derived", "crosses_attempted", "crosses_delivered",
    "cross_success_pct_derived",
)
_CROSS_ROLE_EVENT_MINIMUMS = {
    "interceptions": 2, "possession_won": 4, "tackles": 3, "blocks": 2,
    "clearances": 3, "defense_duels_won": 3, "aerial_duels_won": 3,
    "offense_duels_won": 3, "stand_tackles_won": 2, "slide_tackles_won": 2,
    "key_passes": 2, "dribbles_completed": 3, "crosses_delivered": 2,
    "passes_completed_under_pressure": 5, "assists": 1, "goals_derived": 2,
    "npk_goals": 2, "saves": 3,
}
_CROSS_ROLE_RATE_REQUIREMENTS = {
    "pass_accuracy_pct_derived": ("passes", 15),
    "pressure_pass_accuracy_pct": ("passes_under_pressure", 5),
    "defense_duel_success_pct_derived": ("defense_duels_attempted", 3),
    "aerial_duel_success_pct_derived": ("aerial_duels_attempted", 3),
    "offense_duel_success_pct_derived": ("offense_duels_attempted", 3),
    "stand_tackle_success_pct_derived": ("stand_tackles", 3),
    "slide_tackle_success_pct_derived": ("slide_tackles", 3),
    "dribble_success_pct_derived": ("dribbles", 3),
    "cross_success_pct_derived": ("crosses_attempted", 3),
}
_CROSS_ROLE_COMPARISON_MIN_PLAYERS = 5
_ROLE_COMPARISON_MIN_PLAYERS = 3
_CROSS_ROLE_MIN_MINUTES = 45
_CROSS_ROLE_STANDOUT_PERCENTILE = 80
_ROLE_QUESTIONS = {
    "goalkeeper": "Use saves and shots faced, conceded goals and passing when actually recorded. "
                  "Compare the keeper only with keepers and compatible samples. "
                  "Neither a conceded goal nor a clean sheet proves individual responsibility; "
                  "do not infer positioning, mistakes, handling or distribution quality from the score.",
    "centre_back": "Prioritize duels, clearances, interceptions and passing where measured. "
                   "Do not infer positioning or responsibility for a goal from event totals.",
    "fullback": "Balance recorded defensive duels/interceptions with passing and wide contribution; "
                "do not infer overlaps or runs from aggregate counts.",
    "defensive_midfielder": "Prioritize ball recoveries, defensive work and circulation where measured; "
                            "tackle totals alone do not prove defensive positioning.",
    "central_midfielder": "Prioritize circulation, recoveries and chances created when recorded; "
                          "do not infer tempo control from pass totals alone.",
    "attacking_midfielder": "Prioritize chance creation, key passes and attacking contribution where measured.",
    "winger": "Prioritize progression proxies, successful dribbles and final actions where recorded; "
              "do not claim a specific flank or movement without tracking.",
    "striker": "Prioritize shots, shots on target, goals and xG when recorded; "
               "differentiate opportunity volume from finishing efficiency.",
}
# Recommendation-like discussion of outfield attacking metrics about a goalkeeper is
# a priority error even when such a number happens to exist in the raw export.
_GK_OUTFIELD = re.compile(
    r"\b(?:dribl\w*|dribb\w*|regat\w*|xg\+xa|shots per 90|chutes por 90)\b", re.IGNORECASE
)
_GK_XG = re.compile(r"\b(?:xg|expected goals|gols esperados|goles esperados)\b", re.IGNORECASE)
_GK_FINISHING = re.compile(r"\bfinaliz\w*\b", re.IGNORECASE)
_GK_FACED_SHOTS = re.compile(
    r"(?:finaliz\w*.{0,45}(?:sofrid\w*|enfrentad\w*|recebid\w*|adversari\w*|oponent\w*)|"
    r"(?:sofrid\w*|enfrentad\w*|recebid\w*|adversari\w*|oponent\w*).{0,45}finaliz\w*)",
    re.IGNORECASE,
)


def _fact_map(context: dict[str, Any]) -> dict[str, Any]:
    return {str(fact.get("id")): fact.get("value")
            for fact in context.get("facts", []) if isinstance(fact, dict)}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _role_for_match_player(row: dict[str, Any]) -> str | None:
    position = None
    if (row.get("observed_position")
            and row.get("observed_position_source") == "career_playermatchratinghistory_position"):
        position = str(row["observed_position"]).upper().strip()
    elif row.get("registered_position"):
        position = str(row["registered_position"]).upper().strip()
    return _POSITION_ROLE.get(position or "")


def goalkeeper_match_context(context: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any] | None:
    """Pair the opponent's team xG with this keeper's same-match outcome facts."""
    if context.get("mode") != "match_player":
        return None
    facts = _fact_map(context)
    match = facts.get("match") or {}
    opponent_id = match.get("opponent_ea_id")
    selected_team = selected.get("team_ea_id")
    if opponent_id is None or selected_team is None or str(opponent_id) == str(selected_team):
        return None
    opponent = next((row for row in facts.get("matchstats") or []
                     if isinstance(row, dict) and str(row.get("team_ea_id")) == str(opponent_id)), None)
    if not opponent:
        return None
    team_stats = opponent.get("stats") or {}
    xg_value = _number(team_stats.get("expected_goals_derived"))
    xg_metric = "expected_goals_derived"
    xg_scope = "Atlas total xG, including modelled penalty attempts when available"
    if xg_value is None:
        xg_value = _number(team_stats.get("npk_expected_goals"))
        xg_metric = "npk_expected_goals"
        xg_scope = "opponent non-penalty xG; penalties excluded"
    player_stats = selected.get("stats") or {}
    goalkeeper_stats = {
        key: value for key, value in {
            "saves": _number(player_stats.get("saves")),
            "shots_on_target_saved": _number(player_stats.get("saving_shots_on_target")),
            "shots_faced": _number(player_stats.get("shots_against")),
            "goals_conceded": _number(player_stats.get("goals_conceded")),
        }.items() if value is not None
    }
    if xg_value is None or not goalkeeper_stats:
        return None
    return {
        "opponent_team_ea_id": opponent_id,
        "opponent_team_name": opponent.get("team_name"),
        "opponent_xg": xg_value,
        "opponent_xg_metric": xg_metric,
        "opponent_xg_scope": xg_scope,
        "opponent_shots_on_target": _number(team_stats.get("shots_on_target")),
        "goalkeeper_recorded_outcomes": goalkeeper_stats,
        "fact_refs": ["matchstats", "selected_match_player"],
        "interpretation_limit": (
            "These are same-match team chance-quality and goalkeeper outcome facts; "
            "they do not assign responsibility or prove shot difficulty or causation."
        ),
    }


def goalkeeper_opponent_xg_evidence(context: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Allow xG in a keeper report only when explicitly sourced to the opponent."""
    if context.get("mode") != "match_player":
        return None
    role = context.get("role_analysis") or player_role(context)
    if not role or role.get("role") != "goalkeeper":
        return None
    facts = _fact_map(context)
    selected = facts.get("selected_match_player") or {}
    evidence = role.get("goalkeeper_match_context") or goalkeeper_match_context(context, selected)
    if not evidence:
        return None
    folded = _fold(text)
    opponent_terms = ("oponente", "adversario", "rival", "opponent", "opposition", "adversary", "contrario")
    names_opponent = any(term in folded for term in opponent_terms)
    opponent_name = str(evidence.get("opponent_team_name") or "").strip()
    if opponent_name and _fold(opponent_name) in folded:
        names_opponent = True
    if not names_opponent:
        return None
    return evidence


def _match_standouts(context: dict[str, Any], selected: dict[str, Any],
                     role: str, priority_metrics: tuple[str, ...], *,
                     outside_role: bool) -> list[dict[str, Any]]:
    """Return deterministic match standouts, compared within-role or across the team."""
    facts = _fact_map(context)
    selected_id = str(selected.get("player_ea_id"))
    team_id = selected.get("team_ea_id")
    if team_id is None:
        return []
    participants = [row for row in facts.get("match_players", [])
                    if isinstance(row, dict) and str(row.get("team_ea_id")) == str(team_id)]
    if not any(str(row.get("player_ea_id")) == selected_id for row in participants):
        participants.append(selected)

    def stat(row: dict[str, Any], key: str) -> float | None:
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        return _number(stats.get(key, row.get(key)))

    managed_participants = []
    for row in participants:
        same_role = _role_for_match_player(row) == role
        if not outside_role and not same_role:
            continue
        managed_participants.append(row)
    eligible = []
    for row in managed_participants:
        minutes = _number(row.get("minutes", stat(row, "minutes_played")))
        if minutes is not None and minutes >= _CROSS_ROLE_MIN_MINUTES:
            eligible.append(row)
    minimum_players = (_CROSS_ROLE_COMPARISON_MIN_PLAYERS if outside_role
                       else _ROLE_COMPARISON_MIN_PLAYERS)
    if len(eligible) < minimum_players:
        return []

    selected_row = next((row for row in eligible if str(row.get("player_ea_id")) == selected_id), None)
    if selected_row is None:
        return []
    selected_minutes = _number(selected_row.get("minutes", stat(selected_row, "minutes_played")))
    assert selected_minutes is not None and selected_minutes > 0
    candidates: list[dict[str, Any]] = []

    def rank_signal(metric: str, threshold: float, denominator: str | None = None,
                    minimum_attempts: int = 0) -> None:
        if (metric in priority_metrics) == outside_role:
            return
        value = stat(selected_row, metric)
        attempts = stat(selected_row, denominator) if denominator else None
        if value is None or (denominator and (attempts is None or attempts < minimum_attempts)):
            return
        if denominator is None and value < threshold:
            return
        cohort: list[tuple[dict[str, Any], float]] = []
        for row in eligible:
            row_minutes = _number(row.get("minutes", stat(row, "minutes_played")))
            row_value = stat(row, metric)
            row_attempts = stat(row, denominator) if denominator else None
            if row_minutes is None or row_value is None:
                continue
            if denominator and (row_attempts is None or row_attempts < minimum_attempts):
                continue
            cohort.append((row, row_value if denominator else row_value * 90.0 / row_minutes))
        if len(cohort) < minimum_players:
            return
        current = value if denominator else value * 90.0 / selected_minutes
        comparable = [measure for row, measure in cohort]
        center = median(comparable)
        if current <= center:
            return
        percentile = 100.0 * sum(measure <= current for measure in comparable) / len(comparable)
        if percentile < _CROSS_ROLE_STANDOUT_PERCENTILE:
            return
        signal: dict[str, Any] = {
            "signal_type": "cross_role_standout" if outside_role else "role_standout",
            "metric_key": metric,
            "observed_value": value,
            "minutes": selected_minutes,
            "comparison_scope": ("managed-team participants with at least 45 minutes" if outside_role
                                 else "same-role managed-team participants with at least 45 minutes"),
            "comparison_players": len(cohort),
            "comparison_percentile": round(percentile, 1),
            "comparison_median": round(center, 2),
            "comparison_unit": "recorded value" if denominator else "per 90 minutes",
            "fact_refs": ["selected_match_player", "match_players"],
            "interpretation_limit": "Recognize the measured contribution only; do not infer tactical instructions, pressing, movement, or cause.",
        }
        if denominator:
            signal.update({"attempt_metric": denominator, "attempts": attempts,
                           "minimum_attempts": minimum_attempts})
        else:
            signal["value_per_90"] = round(current, 2)
            signal["minimum_raw_events"] = threshold
        candidates.append(signal)

    for metric, minimum in _CROSS_ROLE_EVENT_MINIMUMS.items():
        rank_signal(metric, minimum)
    for metric, (denominator, minimum_attempts) in _CROSS_ROLE_RATE_REQUIREMENTS.items():
        rank_signal(metric, 0, denominator, minimum_attempts)
    candidates.sort(key=lambda item: (-item["comparison_percentile"],
                                     -float(item.get("value_per_90", item["observed_value"])),
                                     item["metric_key"]))
    return candidates


def player_role(context: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve only selected-player roles, not a future position or arbitrary teammate."""
    if context.get("mode") not in {"player", "match_player"}:
        return None
    facts = _fact_map(context)
    key = "selected_match_player" if context["mode"] == "match_player" else "player_summary"
    row = facts.get(key)
    if not isinstance(row, dict) or row.get("player_ea_id") is None:
        return None
    position: str | None = None
    provenance = "unknown"
    if (context["mode"] == "match_player"
            and row.get("observed_position")
            and row.get("observed_position_source") == "career_playermatchratinghistory_position"):
        position = str(row["observed_position"]).upper().strip()
        provenance = "trusted_observed_position"
    elif context["mode"] == "match_player" and row.get("registered_position"):
        position = str(row["registered_position"]).upper().strip()
        provenance = "registered_position"
    elif context["mode"] == "player" and row.get("position"):
        position = str(row["position"]).upper().strip()
        provenance = "registered_position_at_checkpoint"
    role = _POSITION_ROLE.get(position or "")
    if not role:
        return {"player_ea_id": row["player_ea_id"], "position": None, "role": "unknown",
                "position_source": provenance, "priority_metrics": [],
                "available_metrics": {},
                "instructions": "Position unverified. Do not infer a role or prescribe position-specific training."}
    metrics = row.get("stats") or row.get("metrics") or {}
    allowed = _ROLE_METRICS[role]
    observed = {key: metrics[key] for key in allowed
                if key in metrics and metrics[key] is not None}
    # Match-level rating/minutes may live outside the stats object.
    for field in ("minutes", "rating"):
        if row.get(field) is not None:
            observed[field] = row[field]
    result = {
        "player_ea_id": row["player_ea_id"], "position": position, "role": role,
        "position_source": provenance,
        "priority_metrics": list(dict.fromkeys(allowed)),
        "available_metrics": observed,
        "instructions": _ROLE_QUESTIONS[role] + " Missing metric is N/D, not zero. "
                        "Do not recommend tactical changes solely from a match rating.",
    }
    if context.get("mode") == "match_player":
        standouts = [
            *_match_standouts(context, row, role, allowed, outside_role=False),
            *_match_standouts(context, row, role, allowed, outside_role=True),
        ]
        standouts.sort(key=lambda item: (-item["comparison_percentile"],
                                         -float(item.get("value_per_90", item["observed_value"])),
                                         item["metric_key"], item["signal_type"]))
        result["role_standouts"] = [item for item in standouts if item["signal_type"] == "role_standout"][:2]
        result["cross_role_standouts"] = [item for item in standouts if item["signal_type"] == "cross_role_standout"][:2]
        selected_signals = standouts[:2]
        result["match_standouts"] = selected_signals
        if role == "goalkeeper":
            keeper_context = goalkeeper_match_context(context, row)
            if keeper_context:
                result["goalkeeper_match_context"] = keeper_context
    return result


def prompt_evidence(context: dict[str, Any]) -> dict[str, Any]:
    """Shrink irrelevant *model input* while keeping the original facts intact.

    The validator and cache still use the complete original source. Cited fact IDs
    remain unchanged. No fact is manufactured and no chronological scope expands.
    """
    projected = copy.deepcopy(context)
    role = projected.get("role_analysis") or player_role(context)
    if not role or role["role"] == "unknown":
        return projected
    allowed = set(role["priority_metrics"])
    for signal in role.get("match_standouts", []):
        if signal.get("metric_key"):
            allowed.add(str(signal["metric_key"]))
        if signal.get("attempt_metric"):
            allowed.add(str(signal["attempt_metric"]))
    selected_id = int(role["player_ea_id"])

    def filter_metrics(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {key: metric for key, metric in value.items() if key in allowed}

    for item in projected.get("facts", []):
        if not isinstance(item, dict):
            continue
        key = item.get("id")
        value = item.get("value")
        if key in {"selected_match_player", "player_summary"} and isinstance(value, dict):
            if int(value.get("player_ea_id") or -1) != selected_id:
                continue
            for metric_key in ("stats", "metrics"):
                if isinstance(value.get(metric_key), dict):
                    value[metric_key] = filter_metrics(value[metric_key])
        elif key == "player_position_peers" and isinstance(value, dict):
            for peer in value.get("players") or []:
                if isinstance(peer, dict) and isinstance(peer.get("metrics"), dict):
                    peer["metrics"] = filter_metrics(peer["metrics"])
        elif key in {"pre_match_player_context", "player_matchstats"} and isinstance(value, list):
            for previous in value:
                if isinstance(previous, dict):
                    for metric_key in ("stats", "metrics"):
                        if isinstance(previous.get(metric_key), dict):
                            previous[metric_key] = filter_metrics(previous[metric_key])
        elif key == "match_players" and isinstance(value, list) and context.get("mode") == "match_player":
            # Team and peer comparisons are already calculated in a compact fact.
            # Repeating every participant's raw row confuses small local models.
            item["value"] = [participant for participant in value
                             if isinstance(participant, dict)
                             and str(participant.get("player_ea_id")) == str(selected_id)]
        elif key == "match_player_team_comparison" and isinstance(value, dict):
            priority = allowed | {"game_rating", "goals_derived", "assists", "saves",
                                  "goals_conceded", "shots_against", "pass_accuracy_pct_derived",
                                  "passes", "passes_completed", "possession_lost"}
            value["metrics"] = {metric: row for metric, row in (value.get("metrics") or {}).items()
                                if metric in priority}
    return projected


def role_relevance_conflict(context: dict[str, Any], text: str) -> bool:
    """Block demonstrably misplaced outfield emphases for an identified goalkeeper.

    Do not ban shots faced or saves. Other positions use scoped evidence prompts;
    their diverse duties do not support a safe lexical prohibition.
    """
    role = context.get("role_analysis") or player_role(context)
    if not role or role.get("role") != "goalkeeper":
        return False
    folded = _fold(text)
    if _GK_OUTFIELD.search(folded):
        return True
    if _GK_XG.search(folded):
        opponent_context = goalkeeper_opponent_xg_evidence(context, text)
        keeper_outcome = any(term in folded for term in (
            "defesa", "defendeu", "saves", "saved", "sofreu", "sofridos", "conceded", "gols contra",
            "chutes enfrentados", "finalizacoes enfrentadas", "shots faced", "shots on target faced",
            "enfrentou", "tiros recebidos", "tiros a puerta"))
        if not opponent_context or not keeper_outcome:
            return True
    # "Finalizações sofridas pelo goleiro" means shots *faced*, not
    # outfield finishing. Do not reject this legitimate GK observation.
    return bool(_GK_FINISHING.search(folded) and not _GK_FACED_SHOTS.search(folded))
