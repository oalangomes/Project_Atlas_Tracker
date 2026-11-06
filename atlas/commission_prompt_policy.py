"""Shared report policy: explicit club identity, grounded focus and conservative shape checks.

This module does not infer formations, tactics or player availability from MatchStats.
It only structures evidence already supplied to Atlas's commission reports.
"""
from __future__ import annotations

import re
from typing import Any


# Each slot accepts registered-position equivalents, not inferred tactical roles.
SLOTS: dict[str, set[str]] = {
    "GK": {"GK"},
    "CB": {"CB", "LCB", "RCB", "SW"},
    "LB": {"LB", "LWB"},
    "RB": {"RB", "RWB"},
    "LWB": {"LWB", "LB"},
    "RWB": {"RWB", "RB"},
    "CM": {"CM", "LCM", "RCM", "CDM", "LDM", "RDM", "CAM"},
    "DM": {"CDM", "LDM", "RDM", "CM", "LCM", "RCM"},
    "AM": {"CAM", "CM", "LCM", "RCM"},
    "LM": {"LM", "LW", "LWB"},
    "RM": {"RM", "RW", "RWB"},
    "LW": {"LW", "LM", "LF"},
    "RW": {"RW", "RM", "RF"},
    "ST": {"ST", "CF", "LF", "RF"},
}
FORMATION_SLOTS: dict[str, tuple[str, ...]] = {
    "4-3-3": ("GK", "LB", "CB", "CB", "RB", "CM", "CM", "CM", "LW", "ST", "RW"),
    "4-2-3-1": ("GK", "LB", "CB", "CB", "RB", "DM", "DM", "LW", "AM", "RW", "ST"),
    "4-4-2": ("GK", "LB", "CB", "CB", "RB", "LM", "CM", "CM", "RM", "ST", "ST"),
    "3-5-2": ("GK", "CB", "CB", "CB", "LWB", "CM", "CM", "CM", "RWB", "ST", "ST"),
}


def compatible_formations(players: list[dict[str, Any]]) -> list[str]:
    """Conservative positional compatibility, never a verified XI or fitness decision.

    The same player may fill only one slot. Missing/ambiguous positions are not
    counted and two wide midfielders cannot stand in for four separate players.
    """
    available = [
        (int(player["player_ea_id"]), str(player.get("position") or "").upper().strip())
        for player in players if player.get("player_ea_id") is not None
    ]
    available = [(pid, pos) for pid, pos in available if pos]
    supported: list[str] = []
    for shape, slots in FORMATION_SLOTS.items():
        candidates = [
            {pid for pid, pos in available if pos in SLOTS[slot]}
            for slot in slots
        ]
        if any(not group for group in candidates):
            continue
        used: set[int] = set()

        def can_assign(remaining: tuple[int, ...]) -> bool:
            if not remaining:
                return True
            index = min(remaining, key=lambda i: len(candidates[i] - used))
            if not candidates[index] - used:
                return False
            for pid in sorted(candidates[index] - used):
                used.add(pid)
                if can_assign(tuple(i for i in remaining if i != index)):
                    return True
                used.remove(pid)
            return False

        if can_assign(tuple(range(len(slots)))):
            supported.append(shape)
    return supported


def report_subject(context: dict[str, Any]) -> dict[str, Any]:
    facts = {str(item.get("id")): item.get("value")
             for item in context.get("facts", []) if isinstance(item, dict)}
    match = facts.get("match") or {}
    managed_id = context.get("managed_team_ea_id") or match.get("managed_team_ea_id")
    side = match.get("managed_team_side")
    opponent = match.get("away") if side == "home" else match.get("home") if side == "away" else None
    result: dict[str, Any] = {
        "career_id": context.get("career_id"),
        "managed_team_name": context.get("managed_team"),
        "managed_team_ea_id": managed_id,
        "role": "team_under_analysis_not_opponent",
    }
    if match:
        result.update({"fixture_id": match.get("fixture_id"),
                       "managed_team_side": side, "opponent_team_name": opponent,
                       "opponent_team_ea_id": match.get("opponent_ea_id")})
    selected = facts.get("selected_match_player") or facts.get("player_summary") or {}
    if selected:
        result["selected_player_ea_id"] = selected.get("player_ea_id")
        result["selected_player_name"] = selected.get("name") or selected.get("display_name")
    return result


def report_focus(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Small list of *supported* analysis priorities, not invented conclusions."""
    mode = context.get("mode")
    facts = {str(item.get("id")): item.get("value")
             for item in context.get("facts", []) if isinstance(item, dict)}
    priorities: list[dict[str, Any]] = []
    if mode == "match":
        candidates = []
        for item in facts.get("match_comparisons") or []:
            if not isinstance(item, dict):
                continue
            samples = item.get("reference_samples") or {}
            for period, baseline, delta in (
                ("last_five", "last_five_average", "difference_vs_last_five"),
                ("season_to_date", "season_average", "difference_vs_season"),
            ):
                if int(samples.get("last_five" if period == "last_five" else "season") or 0) < 3:
                    continue
                if item.get(baseline) is None or item.get(delta) is None:
                    continue
                try:
                    importance = abs(float(item[delta])) / max(1.0, abs(float(item[baseline])))
                except (TypeError, ValueError):
                    continue
                candidates.append((importance, str(item.get("metric_key") or ""), {
                    "question": "Explain the observed contrast and its sporting implication without assuming a cause",
                    "metric": item.get("metric"), "unit": item.get("unit"),
                    "current_match": item.get("current_match"),
                    "baseline": item[baseline], "difference": item[delta],
                    "comparison_period": period, "reference_matches": samples.get(
                        "last_five" if period == "last_five" else "season"),
                    "interpretation_direction": item.get("interpretation_direction"),
                    "fact_refs": ["match_comparisons"],
                }))
                break
        seen: set[str] = set()
        for _, key, focus in sorted(candidates, key=lambda item: -item[0]):
            if key and key not in seen:
                priorities.append(focus)
                seen.add(key)
            if len(priorities) == 3:
                break
        if not priorities and facts.get("matchstats"):
            priorities.append({
                "question": "Distinguish the managed club's chance creation, conversion and defensive events from its opponent, using each side's own rows",
                "fact_refs": ["match", "matchstats"],
            })
    elif mode in {"player", "match_player"}:
        summary = facts.get("player_summary") or facts.get("selected_match_player") or {}
        role = context.get("role_analysis") or {}
        # The role profile is a prompt hint derived only from checkpoint-safe
        # source fields; it is NOT a new independent fact to cite.
        role_keys = list((role.get("available_metrics") or {}).keys())[:8]
        names = {"player_summary": "player_summary", "selected_match_player": "selected_match_player"}
        for key, field in names.items():
            if facts.get(key):
                priorities.append({
                    "question": ("Prioritize recorded metrics relevant to the selected player's position, "
                                 "with minutes and comparable previous samples; do not invent a baseline"),
                    "position_role": role.get("role", "unknown"),
                    "available_role_metrics": role_keys,
                    "player_ea_id": summary.get("player_ea_id"),
                    "sample": summary.get("sample"),
                    "fact_refs": [field],
                })
                break
        for key in ("pre_match_player_context", "player_position_peers", "player_matchstats"):
            if facts.get(key):
                priorities.append({
                    "question": "Compare relevant individual evidence only if positions, periods, minutes and provenance are compatible",
                    "fact_refs": [key],
                })
    elif mode == "team_identity":
        profile = facts.get("team_statistical_profile") or {}
        priorities.append({
            "question": "Identify two distinctive measured team indicators; discuss a pattern only when the sample is sufficient",
            "detailed_matches": profile.get("detailed_matches"),
            "sample_sufficient": profile.get("sample_sufficient"),
            "fact_refs": ["team_statistical_profile"] if profile else [],
        })
    elif mode == "next_match":
        options = context.get("allowed_formations") or []
        priorities.append({
            "question": "Evaluate registered-position coverage of permitted shapes; state that fitness, tactical instructions and confirmed starting eleven are unknown",
            "allowed_formations": options,
            "fact_refs": [key for key in ("formation_options", "squad") if facts.get(key) is not None],
        })
    return priorities


def claim_signature(text: str) -> str:
    """Normalize only literal repetition, without guessing semantic equivalence."""
    return re.sub(r"[^\w]+", " ", str(text).casefold(), flags=re.UNICODE).strip()


def is_generic_claim(text: str, section: str | None) -> bool:
    """Reject boilerplate instead of requiring arbitrary numbers in every claim."""
    if section not in {"summary", "observations", "recommendations", "strengths", "development_areas",
                       "training_suggestions"}:
        return False
    normalized = " ".join(str(text).casefold().split()).strip(" .!;")
    generic = (
        r"(?:manter|continuar|seguir)\s+(?:em\s+)?(?:acompanhamento|observação|monitoramento)(?:\s+(?:do|da)\s+(?:jogador|equipe|time|atleta))?",
        r"(?:monitorar|acompanhar|observar)\s+(?:(?:o|a)\s+)?(?:rendimento|desempenho|evolução|forma)(?:\s+(?:do|da)\s+(?:equipe|time|jogador|atleta))?",
        r"(?:melhorar|otimizar|evoluir)\s+(?:o|a)?\s*(?:rendimento|desempenho|performance)(?:\s+(?:da|do)\s+(?:equipe|time|jogador|atleta))?",
        r"(?:keep|continue)\s+(?:monitoring|watching|observing)(?:\s+(?:the\s+)?(?:player|team))?",
        r"(?:monitor|improve|track)\s+(?:the\s+)?(?:team|player)?\s*(?:performance|form|development)",
        r"(?:seguir|mantener)\s+(?:el\s+)?seguimiento(?:\s+(?:del\s+)?(?:jugador|equipo))?",
        r"(?:mejorar|vigilar)\s+(?:el\s+)?(?:rendimiento|desempeño)(?:\s+(?:del\s+)?(?:jugador|equipo))?",
    )
    if normalized in {"o time jogou bem", "a equipe jogou bem", "a equipe teve boa atuação",
                      "o jogador teve boa atuação", "the team played well", "the player did well",
                      "el equipo jugó bien", "el jugador jugó bien"}:
        return True
    return any(re.fullmatch(pattern, normalized) for pattern in generic)


REASONING_POLICY = (
    "SPORTING ANALYSIS CONTRACT: The report_subject identifies the managed club; "
    "it is the ONLY club being advised. In every fixture, resolve identities by EA IDs "
    "and managed_team_side before comparing sides. Never swap the managed club and "
    "opponent, credit an opponent player with a managed-team contribution, or recommend "
    "improvements for the opponent. The selected player, if any, must be the focus of "
    "an individual report. "
    "Use analysis_focus as a shortlist of verified contrasts, not as guaranteed "
    "interpretations or a substitute for the complete facts. First identify the "
    "most surprising or decision-relevant available evidence. Then explain what "
    "is different from the comparable baseline, why that matters *without asserting "
    "an unobserved cause*, and what evidence would confirm or refute the proposed "
    "next action. Distinguish chance creation from conversion, and offensive actions "
    "from defensive results. Only compare like units, entity IDs, match periods and "
    "sample-qualified cohorts. When historical evidence is missing, describe the "
    "current evidence and the gap precisely; do not fabricate trends. "
    "A good recommendation names the relevant observed indicator and a specific "
    "follow-up/decision conditioned on that indicator. Avoid boilerplate such as "
    "'monitor player performance', 'keep observing', 'continue improving' or "
    "'the team played well' without a concrete, supported distinction. "
    "Do not reuse the same observation verbatim in summary, strengths and "
    "recommendations. Do not invent minutes, score, tactical roles or availability. "
    "When role_analysis is present, treat its verified position and actually "
    "available metrics as the primary individual analysis lens, not as new facts. "
    "Never manufacture a metric or cite role_analysis as a fact. If the position "
    "is unverified, abstain from role-specific claims. A goalkeeper must be "
    "evaluated on recorded goalkeeping and distribution indicators, not dribbles, "
    "xG or finalisations. A conceded goal is not proof of an individual mistake. "
    "Prefer fewer grounded, distinctive conclusions over eight interchangeable items."
)


# Keep the small local model's instructions relevant to each report mode.
_MODE_RULES: dict[str, str] = {
    "match": (
        "MATCH: Identify the managed side by its EA ID and home/away role. "
        "Use each team's own MatchStats row; preserve score direction and goals conceded. "
        "Use match_comparisons only for the managed team's current-versus-prior differences, "
        "respect reference_samples and interpretation_direction. The historical 'against' "
        "baseline is pooled across earlier opponents, NOT a trend for the current named opponent. "
        "Explain chance volume versus finishing from goals-minus-xG only, never from xG volume. "
        "No match event timing, possession share, attacking corridors, press intensity, "
        "line height or player movement is available unless a fact explicitly supplies it. "
        "Do not treat passing, tackles, interceptions or saves as territorial control. "
        "Any tactical explanation is a bounded hypothesis with a clear limitation."
    ),
    "match_player": (
        "INDIVIDUAL MATCH: Identify the selected managed-team player's exact "
        "selected_match_player row and cite it for current figures; matchstats is team-level. "
        "Contrast with pre_match_player_context only where earlier linked matches exist. "
        "Never attribute another player or the opponent's statistic to this player. "
        "Use role_analysis to select relevant measured indicators instead of "
        "giving the same offensive/defensive rubric to all positions. "
        "A goalkeeper needs goalkeeping and passing evidence, never outfield "
        "dribbling or finishing suggestions. Compare like positions and minutes; "
        "do not infer error or blame from goals conceded. No starting status or "
        "movement pattern can be inferred from aggregate MatchStats."
    ),
    "player": (
        "ACCUMULATED PLAYER: Keep the selected player's career/season scope. "
        "Compare player_summary, last recorded matches and player_position_peers "
        "only through the role_analysis position lens, with sample sizes, minutes "
        "and units. Do not evaluate a goalkeeper as a dribbler, chance creator or "
        "striker. Missing goalkeeper metrics are N/D; a clean sheet alone does not "
        "prove superior goalkeeping. Do not mistake attribute percentiles for "
        "recorded match impact or nominal position for a confirmed tactical role. "
        "Do not convert club goals into player goals or promote a player to "
        "starter solely from rating/OVR."
    ),
    "team_identity": (
        "TEAM IDENTITY: Team averages are measured observations, not direct "
        "evidence of tactical instructions, pressure or possession. "
        "Only form a cautious style hypothesis when team_statistical_profile "
        "says sample_sufficient=true. opponent_profiles only separates measured "
        "opponent shot-volume cohorts and results; it is not a tactical opponent "
        "classifier or a causal diagnosis. Report an inconclusive style when "
        "detailed evidence is inadequate instead of writing generic praise."
    ),
    "next_match": (
        "UPCOMING MATCH: Use only the managed squad and fixture calendar; "
        "opponent style is unknown unless documented independently in this context. "
        "allowed_formations are candidates from conservative registered-position "
        "matching with distinct players, NOT proof of fitness, tactical fit or "
        "confirmed starting eleven. Return formation=null if the list is empty. "
        "If a shape is offered, explain which registration constraints support "
        "its eligibility and explicitly state lineup and availability are not "
        "confirmed. Do not claim a player can fill a role not registered in the facts. "
        "Recovery interval between fixtures is calendar data, not fatigue."
    ),
}


def build_system_prompt(language_name: str, task: str, mode: str) -> str:
    """One shared football reasoning contract plus only the active mode's rules."""
    return (
        f"You are Atlas's technical commission analyst. Every visible text field "
        f"MUST be written in {language_name}. Return a JSON object with EXACTLY "
        "the schema keys summary, observations, recommendations, strengths, "
        "development_areas, training_suggestions, formation, information_requests. "
        "Each claim has text, kind (fact, inference, hypothesis), limitations and "
        "fact_refs from the supplied fact IDs. Do not cite nonexistent facts. "
        "A hypothesis must describe what the evidence cannot prove; never present "
        "coach-provided context as verified imported statistics. "
        "Keep each finding to one or two precise sentences. Only suggest a "
        "concrete next action when there is an observed signal to investigate. "
        "Omit unsupported categories instead of padding with boilerplate. "
        "Do not assert injuries, suspensions, physical fitness, confirmed "
        "starting lineup, hierarchy, possession %, pressing, spatial events "
        "or exact match-event chronology without reliable source fields. "
        "A missing measurement remains N/D, never zero. "
        "Results, team and player identities, data-source provenance, role "
        "and date scopes must be preserved. "
        "If there are fewer than three comparable earlier matches, do not "
        "state an established multi-match trend. "
        "Strengths, development areas and training suggestions are reserved "
        "for individual-player modes. Do not score your own intelligence. "
        + REASONING_POLICY + " " + _MODE_RULES.get(mode, "") + " " + task
    )
