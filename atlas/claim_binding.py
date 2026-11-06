"""Bind explicit match score claims to one subject, metric, fixture and source."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


_NUMBER_WORDS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "cero": 0, "uno": 1, "una": 1, "dos": 2, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}
_NUMBER = r"(?:\d{1,2}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_GOALS = r"(?:gols?|goals?|goles?)"
_SCORED = r"(?:marcou|marcaram|marcado|marc[oó]|anotou|anot[oó]|fez|fizeram|scored|score|netted|hizo|hicieron)"
_CONCEDED = r"(?:sofreu|sofreram|sofrido|concedido|conceded|concede|allowed|encaj[oó]|encajaron|recibi[oó]|recibieron)"
_ACTION = rf"(?P<action>{_SCORED}|{_CONCEDED})"
_FILLER = r"(?:\s+(?:que|who|that|ha|had|has|have|tem|ter|tinha|tambem|also|ja|ya)){0,3}"


def _fold(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBER_WORDS[value]


def _score(match: dict[str, Any], side: str) -> int | None:
    score = match.get("score")
    if isinstance(score, (list, tuple)) and len(score) == 2:
        value = score[0 if side == "home" else 1]
    else:
        managed_side = match.get("managed_team_side")
        if managed_side not in {"home", "away"}:
            return None
        value = match.get("managed_score" if side == managed_side else "opponent_score")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _aliases(match: dict[str, Any], selected: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    for name, side in ((home, "home"), (away, "away")):
        if name:
            aliases[_fold(name)] = side
    first_names = [_fold(name.split()[0]) for name in (home, away) if name]
    for name, side in ((home, "home"), (away, "away")):
        first = _fold(name.split()[0]) if name else ""
        if len(first) >= 4 and first_names.count(first) == 1:
            aliases[first] = side
    for alias in ("mandante", "time mandante", "equipe mandante", "time da casa",
                  "equipe da casa", "home team", "home side", "equipo local"):
        aliases[alias] = "home"
    for alias in ("visitante", "time visitante", "equipe visitante", "away team",
                  "visiting team", "equipo visitante"):
        aliases[alias] = "away"
    managed = match.get("managed_team_side")
    if managed in {"home", "away"}:
        other = "away" if managed == "home" else "home"
        for alias in ("clube controlado", "time controlado", "equipe controlada",
                      "managed club", "managed team", "equipo controlado"):
            aliases[alias] = managed
        for alias in ("adversario", "oponente", "opponent", "rival"):
            aliases[alias] = other
    player_name = _fold(selected.get("name"))
    if player_name:
        aliases[player_name] = "selected_player"
        surname = player_name.split()[-1]
        if len(surname) >= 4 and surname not in aliases:
            aliases[surname] = "selected_player"
        for alias in ("jogador selecionado", "selected player", "jugador seleccionado"):
            aliases[alias] = "selected_player"
    return aliases


def score_claim_bindings(context: dict[str, Any], item: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate explicit current-fixture goal claims; leave other metrics to their validators."""
    facts = {str(fact.get("id")): fact.get("value") for fact in context.get("facts", [])
             if isinstance(fact, dict)}
    match = facts.get("match") if isinstance(facts.get("match"), dict) else {}
    selected = facts.get("selected_match_player") if isinstance(facts.get("selected_match_player"), dict) else {}
    if not match:
        return [], []
    text = _fold(item.get("text"))
    refs = set(item.get("fact_refs") or [])
    aliases = _aliases(match, selected)
    if (context.get("mode") == "match_player" and match.get("managed_team_side") in {"home", "away"}
            and selected.get("team_ea_id") is not None and match.get("managed_team_ea_id") is not None
            and str(selected["team_ea_id"]) == str(match["managed_team_ea_id"])):
        for alias in ("a equipe", "o time", "equipe", "time", "the team", "team", "el equipo", "equipo"):
            aliases[alias] = match["managed_team_side"]
    if not aliases:
        return [], []
    subject_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    goal_pattern = re.compile(
        rf"(?<!\w)(?P<subject>{subject_pattern})(?!\w){_FILLER}\s+{_ACTION}"
        rf"\s+(?:apenas\s+|somente\s+|only\s+|solo\s+)?(?P<value>{_NUMBER})\s+{_GOALS}\b"
    )
    scoreline_pattern = re.compile(
        rf"(?<!\w)(?P<first>{subject_pattern})(?!\w)\s+(?P<first_value>\d{{1,2}})"
        rf"\s*[-–:]\s*(?P<second_value>\d{{1,2}})\s+"
        rf"(?P<second>{subject_pattern})(?!\w)"
    )
    draw_score_pattern = re.compile(r"\b(?:empate|draw)\s+(?:de|por|at)?\s*(?P<first_value>\d{1,2})"
                                    r"\s*[-–:]\s*(?P<second_value>\d{1,2})\b")
    bindings: list[dict[str, Any]] = []
    issues: list[str] = []

    def bind(subject: str, metric: str, value: int) -> None:
        side = aliases[subject]
        source = "selected_match_player" if side == "selected_player" else "match"
        if side == "selected_player":
            stats = selected.get("stats") or {}
            raw = (stats.get("goals_derived", stats.get("npk_goals")) if metric == "goals_scored"
                   else stats.get("goals_conceded"))
            try:
                expected = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                expected = None
            subject_name = str(selected.get("name") or "")
        else:
            expected = _score(match, side if metric == "goals_scored" else
                              ("away" if side == "home" else "home"))
            subject_name = str(match.get(side) or side)
        binding = {"subject": subject_name, "subject_side": side, "metric": metric,
                   "value": value, "expected": expected, "fixture_id": match.get("fixture_id"),
                   "source_ref": source, "accepted": source in refs and expected == value}
        bindings.append(binding)
        if source not in refs:
            issues.append("score_source_missing")
        elif expected is None:
            issues.append("score_source_unavailable")
        elif expected != value:
            issues.append("score_value_conflict")

    for found in goal_pattern.finditer(text):
        if (item.get("kind") == "hypothesis"
                and re.search(r"\b(?:if|se|si)\b", text[max(0, found.start() - 35):found.start()])):
            continue
        action = found.group("action")
        metric = "goals_scored" if re.fullmatch(_SCORED, action) else "goals_conceded"
        bind(found.group("subject"), metric, _number(found.group("value")))
    for found in scoreline_pattern.finditer(text):
        if aliases[found.group("first")] == "selected_player" or aliases[found.group("second")] == "selected_player":
            continue
        bind(found.group("first"), "goals_scored", int(found.group("first_value")))
        bind(found.group("second"), "goals_scored", int(found.group("second_value")))
    for found in draw_score_pattern.finditer(text):
        if not ({"home", "away"} & set(aliases.get(alias) for alias in aliases if
                re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text))):
            continue
        value = [int(found.group("first_value")), int(found.group("second_value"))]
        expected = [_score(match, "home"), _score(match, "away")]
        accepted = "match" in refs and expected == value and value[0] == value[1]
        bindings.append({"subject": "fixture", "subject_side": "fixture", "metric": "draw_score",
                         "value": value, "expected": expected, "fixture_id": match.get("fixture_id"),
                         "source_ref": "match", "accepted": accepted})
        if "match" not in refs:
            issues.append("score_source_missing")
        elif None in expected:
            issues.append("score_source_unavailable")
        elif not accepted:
            issues.append("score_value_conflict")
    return bindings, list(dict.fromkeys(issues))
