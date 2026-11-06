"""Position-aware evidence selection for the Atlas Technical Commission.

This is a *prompt projection*, not a change to stored FC26 facts. The original
context remains the validation source. The role is resolved only from a
position recorded at the report's permitted historical checkpoint.
"""
from __future__ import annotations

import copy
import re
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
                                  "aerial_duels_won", "aerial_duels_attempted"),
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
    r"\b(?:dribl\w*|dribb\w*|regat\w*|xg|xg\+xa|expected goals|gols esperados|"
    r"goles esperados|shots per 90|chutes por 90)\b", re.IGNORECASE
)
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
    return {
        "player_ea_id": row["player_ea_id"], "position": position, "role": role,
        "position_source": provenance,
        "priority_metrics": list(dict.fromkeys(allowed)),
        "available_metrics": observed,
        "instructions": _ROLE_QUESTIONS[role] + " Missing metric is N/D, not zero. "
                        "Do not recommend tactical changes solely from a match rating.",
    }


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
            # Only the selected player and managed-team players with the same
            # registered/observed role. Do not offer all opponent players as peers.
            target_team = (_fact_map(context).get("selected_match_player") or {}).get("team_ea_id")
            peers = []
            for participant in value:
                if not isinstance(participant, dict):
                    continue
                pid = participant.get("player_ea_id")
                same_player = str(pid) == str(selected_id)
                if not same_player:
                    if target_team is None or str(participant.get("team_ea_id")) != str(target_team):
                        continue
                    registered = str(participant.get("registered_position") or "").upper()
                    if _POSITION_ROLE.get(registered) != role["role"]:
                        continue
                participant["stats"] = filter_metrics(participant.get("stats") or {})
                peers.append(participant)
                if len(peers) >= 10:
                    break
            item["value"] = peers
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
    # "Finalizações sofridas pelo goleiro" means shots *faced*, not
    # outfield finishing. Do not reject this legitimate GK observation.
    return bool(_GK_FINISHING.search(folded) and not _GK_FACED_SHOTS.search(folded))
