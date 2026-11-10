from __future__ import annotations

import json
from typing import Any, Iterable

from .server_utils import as_int


MODEL_ID = "atlas-position-fit-v2"

# FC stores the 28 preferred-position ids in this exact order.  Canonical
# values preserve side and line; no suitability decision may collapse them to
# defence/midfield/attack.
POSITION_BY_ID: dict[int, str] = {
    0: "GK", 1: "SW", 2: "RWB", 3: "RB", 4: "RCB", 5: "CB", 6: "LCB",
    7: "LB", 8: "LWB", 9: "RDM", 10: "CDM", 11: "LDM", 12: "RM",
    13: "RCM", 14: "CM", 15: "LCM", 16: "LM", 17: "RAM", 18: "CAM",
    19: "LAM", 20: "RF", 21: "CF", 22: "LF", 23: "RW", 24: "RS",
    25: "ST", 26: "LS", 27: "LW",
}

POSITION_ALIASES: dict[str, str] = {
    "TW": "GK", "TORWART": "GK", "LIB": "SW", "LIBERO": "SW",
    "RAV": "RWB", "RV": "RB", "RIV": "RCB", "IV": "CB", "LIV": "LCB",
    "LV": "LB", "LAV": "LWB", "ZDM": "CDM", "RZM": "RCM", "ZM": "CM",
    "LZM": "LCM", "ROM": "RAM", "ZOM": "CAM", "LOM": "LAM", "HS": "CF",
    "MS": "CF", "LST": "LS", "RST": "RS",
}

CANONICAL_POSITIONS = frozenset(POSITION_BY_ID.values())

# --- Observed in-match position provenance ---------------------------------
# Atlas accepts an in-match position only when the export proves where the
# player actually took the pitch:
# * "career_playermatchratinghistory_position" — the FC26 rating-history row
#   keeps the line-up slot for that match; slots 28/29 (SUB/RES) carry no
#   position, and occasionally a stale slot survives for a full-match player.
# * "career_playerlastmatchhistory_latest_match" — the position actually used
#   in the player's latest completed managed match, including substitutes,
#   as retained by career_playerlastmatchhistory until the next managed match.
TRUSTED_POSITION_SOURCES: frozenset[str] = frozenset({
    "career_playermatchratinghistory_position",
    "career_playerlastmatchhistory_latest_match",
})


def trusted_position_source(value: Any) -> str | None:
    """Return the provenance text only when it identifies an in-match record."""

    text = str(value or "").strip()
    return text if text in TRUSTED_POSITION_SOURCES else None


def trusted_actual_position(position: Any, source: Any) -> str | None:
    """Return the position only when it is recorded with trusted provenance."""

    text = str(position or "").strip().upper()
    return text if text and trusted_position_source(source) else None

# Broad groups remain available for high-level charts and generic statistical
# models.  They are explicitly forbidden as squad-coverage evidence.
BROAD_POSITION_GROUPS: dict[str, frozenset[str]] = {
    "GK": frozenset({"GK"}),
    "DEF": frozenset({"SW", "RWB", "RB", "RCB", "CB", "LCB", "LB", "LWB"}),
    "MID": frozenset({"RDM", "CDM", "LDM", "RM", "RCM", "CM", "LCM", "LM", "RAM", "CAM", "LAM"}),
    "ATT": frozenset({"RF", "CF", "LF", "RW", "RS", "ST", "LS", "LW"}),
}

# The nine functional families supplied for v0.19.1.  Left/right wings are
# deliberately separate, as are defensive, central and attacking midfield.
DETAILED_POSITION_GROUPS: dict[str, frozenset[str]] = {
    "goalkeeper": frozenset({"GK"}),
    "centre_back": frozenset({"SW", "RCB", "CB", "LCB"}),
    "fullback": frozenset({"RWB", "RB", "LB", "LWB"}),
    "defensive_midfield": frozenset({"RDM", "CDM", "LDM"}),
    "central_midfield": frozenset({"RCM", "CM", "LCM"}),
    "attacking_midfield": frozenset({"RAM", "CAM", "LAM"}),
    "right_wing": frozenset({"RM", "RF", "RW"}),
    "left_wing": frozenset({"LM", "LF", "LW"}),
    "striker": frozenset({"CF", "RS", "ST", "LS"}),
}

POSITION_GROUP_LABELS = {
    "goalkeeper": "Torwart",
    "centre_back": "Innenverteidigung",
    "fullback": "Full-back",
    "defensive_midfield": "Defensive midfield",
    "central_midfield": "Central midfield",
    "attacking_midfield": "Attacking midfield",
    "right_wing": "Right wing",
    "left_wing": "Left wing",
    "striker": "Sturm",
}

GERMAN_DISPLAY_BY_CANONICAL: dict[str, str] = {
    "GK": "TW", "SW": "LIB", "RWB": "RAV", "RB": "RV", "RCB": "RIV",
    "CB": "IV", "LCB": "LIV", "LB": "LV", "LWB": "LAV", "RDM": "RDM",
    "CDM": "ZDM", "LDM": "LDM", "RM": "RM", "RCM": "RZM", "CM": "ZM",
    "LCM": "LZM", "LM": "LM", "RAM": "ROM", "CAM": "ZOM", "LAM": "LOM",
    "RF": "RF", "CF": "MS", "LF": "LF", "RW": "RF", "RS": "RS", "ST": "ST",
    "LS": "LS", "LW": "LF",
}

# Squad pools are side- and role-specific.  A player only contributes after an
# individual fit assessment, so a centre-back never counts as a fullback merely
# because both used to live in DEF.
SQUAD_POSITION_POOLS: dict[str, dict[str, Any]] = {
    "goalkeeper": {"label": "Torwart", "positions": ("GK",), "desiredDepth": 3, "starterSlots": 1},
    "centre_back": {"label": "Innenverteidigung", "positions": ("LCB", "CB", "RCB", "SW"), "desiredDepth": 4, "starterSlots": 2},
    "left_fullback": {"label": "Left-back", "positions": ("LB", "LWB"), "desiredDepth": 2, "starterSlots": 1},
    "right_fullback": {"label": "Right-back", "positions": ("RB", "RWB"), "desiredDepth": 2, "starterSlots": 1},
    "defensive_midfield": {"label": "Defensive midfield", "positions": ("LDM", "CDM", "RDM"), "desiredDepth": 2, "starterSlots": 1},
    "central_midfield": {"label": "Central midfield", "positions": ("LCM", "CM", "RCM"), "desiredDepth": 3, "starterSlots": 2},
    "attacking_midfield": {"label": "Attacking midfield", "positions": ("LAM", "CAM", "RAM"), "desiredDepth": 2, "starterSlots": 1},
    "left_wing": {"label": "Left wing", "positions": ("LM", "LF", "LW"), "desiredDepth": 2, "starterSlots": 1},
    "right_wing": {"label": "Right wing", "positions": ("RM", "RF", "RW"), "desiredDepth": 2, "starterSlots": 1},
    "striker": {"label": "Sturm", "positions": ("LS", "CF", "ST", "RS"), "desiredDepth": 3, "starterSlots": 1},
}

_LEFT = frozenset({"LCB", "LB", "LWB", "LDM", "LCM", "LAM", "LM", "LF", "LW", "LS"})
_RIGHT = frozenset({"RCB", "RB", "RWB", "RDM", "RCM", "RAM", "RM", "RF", "RW", "RS"})
_SECONDARY_KEYS = (
    "position_2", "position_2_id", "position_3", "position_3_id", "position_4", "position_4_id",
    "secondary_position", "secondary_position_1", "secondary_position_2", "alternative_positions", "positions",
)


def canonical_position(value: Any, position_id: Any = None) -> str | None:
    """Return one canonical FC position while preserving left/right variants."""

    numeric = as_int(position_id)
    if numeric in POSITION_BY_ID:
        return POSITION_BY_ID[numeric]
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text.isdigit() and int(text) in POSITION_BY_ID:
        return POSITION_BY_ID[int(text)]
    canonical = POSITION_ALIASES.get(text, text)
    return canonical if canonical in CANONICAL_POSITIONS else None


def broad_position_group(value: Any, position_id: Any = None, *, default: str = "ATT") -> str:
    canonical = canonical_position(value, position_id)
    for group, positions in BROAD_POSITION_GROUPS.items():
        if canonical in positions:
            return group
    return default


def detailed_position_group(value: Any, position_id: Any = None, *, default: str = "striker") -> str:
    canonical = canonical_position(value, position_id)
    for group, positions in DETAILED_POSITION_GROUPS.items():
        if canonical in positions:
            return group
    return default


def position_variants(canonical_positions: frozenset[str]) -> tuple[str, ...]:
    variants = set(canonical_positions)
    variants.update(alias for alias, canonical in POSITION_ALIASES.items() if canonical in canonical_positions)
    return tuple(sorted(variants))


BROAD_POSITION_VARIANTS: dict[str, tuple[str, ...]] = {
    group: position_variants(positions) for group, positions in BROAD_POSITION_GROUPS.items()
}

DETAILED_POSITION_VARIANTS: dict[str, tuple[str, ...]] = {
    group: position_variants(positions) for group, positions in DETAILED_POSITION_GROUPS.items()
}


def is_wide_position(value: Any, position_id: Any = None) -> bool:
    return canonical_position(value, position_id) in {"RWB", "RB", "LB", "LWB", "RM", "LM", "RF", "LF", "RW", "LW"}


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _raw_player(player: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("raw_json", "player_raw_json", "roster_raw_json"):
        result.update(_json_dict(player.get(key)))
    result.update({key: value for key, value in player.items() if value not in (None, "")})
    return result


def player_positions(player: dict[str, Any]) -> tuple[str, ...]:
    """Return primary plus all exported FC secondary positions, in order."""

    raw = _raw_player(player)
    primary = canonical_position(player.get("primary_position"), raw.get("primary_position_id"))
    values: list[str] = [primary] if primary else []
    for key in _SECONDARY_KEYS:
        item = raw.get(key)
        parts: Iterable[Any]
        if isinstance(item, list):
            parts = item
        elif item in (None, "", -1, "-1", 255, "255"):
            continue
        else:
            parts = str(item).replace("/", ",").split(",")
        for part in parts:
            canonical = canonical_position(part)
            if canonical and canonical not in values:
                values.append(canonical)
    return tuple(values)


def _side(position: str | None) -> str:
    if position in _LEFT:
        return "left"
    if position in _RIGHT:
        return "right"
    return "central"


def _number(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(1.0, min(99.0, number))


def _measurement(raw: dict[str, Any], key: str) -> float | None:
    """Read a physical measurement without applying the 1..99 attribute cap."""

    try:
        return float(raw.get(key))
    except (TypeError, ValueError):
        return None


def _profile(raw: dict[str, Any], fields: tuple[str, ...]) -> tuple[float | None, int]:
    values = [value for key in fields if (value := _number(raw, key)) is not None]
    return (sum(values) / len(values), len(values)) if values else (None, 0)


def _attribute_fit(raw: dict[str, Any], source_group: str, target_group: str, same_side: bool) -> tuple[float, str]:
    fields: tuple[str, ...] = ()
    base = 18.0
    cap = 72.0
    label = "Attribute profile is insufficient for the unfamiliar role"
    pair = (source_group, target_group)
    if pair == ("defensive_midfield", "central_midfield"):
        fields = ("short_passing", "long_passing", "vision", "ball_control", "reactions", "stamina")
        base, label = 40.0, "Build-up and passing profile supports a move from DM to CM"
    elif pair == ("central_midfield", "defensive_midfield"):
        fields = ("interceptions", "defensive_awareness", "standing_tackle", "stamina", "strength", "aggression")
        base, label = 38.0, "Defensive profile supports a move from CM to DM"
    elif pair == ("attacking_midfield", "central_midfield"):
        fields = ("short_passing", "long_passing", "vision", "ball_control", "reactions", "stamina")
        base, label = 37.0, "Passing, control and movement profile supports a move from AM to CM"
    elif pair == ("central_midfield", "attacking_midfield"):
        fields = ("vision", "short_passing", "ball_control", "dribbling", "positioning", "reactions")
        base, label = 38.0, "Creative profile supports a move from CM to AM"
    elif source_group == "centre_back" and target_group == "fullback":
        fields = ("acceleration", "sprint_speed", "agility", "stamina", "crossing", "ball_control")
        base, cap, label = 14.0, 62.0, "Centre-back with pace and wide-role attributes"
    elif source_group == "fullback" and target_group == "centre_back":
        fields = ("defensive_awareness", "standing_tackle", "interceptions", "strength", "jumping", "heading_accuracy")
        base, cap, label = 22.0, 68.0, "Full-back with tackling and aerial attributes"
    elif {source_group, target_group} <= {"fullback", "left_wing"} or {source_group, target_group} <= {"fullback", "right_wing"}:
        if target_group == "fullback":
            fields = ("acceleration", "sprint_speed", "stamina", "defensive_awareness", "standing_tackle", "crossing")
        else:
            fields = ("acceleration", "sprint_speed", "agility", "stamina", "crossing", "dribbling")
        base, cap, label = 27.0, 70.0, "Wide-role profile connects wing and full-back"
    elif source_group == "attacking_midfield" and target_group in {"left_wing", "right_wing"}:
        fields = ("acceleration", "sprint_speed", "agility", "dribbling", "ball_control", "crossing")
        base, cap, label = 27.0, 69.0, "Agility and dribbling support a wing role"
    elif source_group in {"left_wing", "right_wing"} and target_group == "attacking_midfield":
        fields = ("vision", "short_passing", "ball_control", "dribbling", "positioning", "reactions")
        base, cap, label = 30.0, 71.0, "Creative profile supports an attacking-midfield role"
    elif source_group == "striker" and target_group == "attacking_midfield":
        fields = ("vision", "short_passing", "ball_control", "dribbling", "positioning", "reactions")
        base, cap, label = 24.0, 66.0, "Link-up profile supports a second-striker role"
    elif source_group == "attacking_midfield" and target_group == "striker":
        fields = ("positioning", "finishing", "reactions", "ball_control", "shot_power", "composure")
        base, cap, label = 24.0, 66.0, "Finishing profile supports a striker role"
    average, available = _profile(raw, fields)
    if not fields:
        return 8.0, "No reliable positional similarity"
    if average is None or available < max(3, len(fields) // 2):
        return max(12.0, min(36.0, base - 8.0)), "No reliable secondary position or sufficient attribute coverage"
    score = base + (average - 50.0) * .72
    if not same_side and source_group in {"centre_back", "fullback", "left_wing", "right_wing"}:
        score -= 18.0
    height = _measurement(raw, "height")
    if source_group == "centre_back" and target_group == "fullback" and height and height >= 190:
        score -= min(8.0, (height - 188) * .8)
    return max(8.0, min(cap, score)), label


def _same_family_fit(primary: str, target: str, raw: dict[str, Any]) -> tuple[float, str]:
    group = detailed_position_group(primary)
    source_side, target_side = _side(primary), _side(target)
    if group == "centre_back":
        if source_side == target_side:
            return 88.0, "Gleiche Innenverteidigerseite"
        if "central" in {source_side, target_side}:
            foot = as_int(raw.get("preferred_foot_id"))
            suited = (target_side == "left" and foot == 2) or (target_side == "right" and foot == 1)
            return (82.0 if suited else 76.0), "Centre-back with side adjustment"
        foot = as_int(raw.get("preferred_foot_id"))
        suited = (target_side == "left" and foot == 2) or (target_side == "right" and foot == 1)
        return (62.0 if suited else 52.0), "Move to the opposite centre-back side"
    if group == "fullback":
        if source_side == target_side:
            return 86.0, "Same wide side"
        return 34.0, "Opposite full-back side"
    if group in {"left_wing", "right_wing"}:
        return 87.0, "Gleiche Wingseite"
    if group in {"defensive_midfield", "central_midfield", "attacking_midfield"}:
        return 88.0, "Gleiche Midfieldlinie"
    if group == "striker":
        return (86.0 if source_side == target_side or "central" in {source_side, target_side} else 72.0), "Benachbarte Sturmposition"
    return 20.0, "No reliable positional similarity"


def player_position_fit(player: dict[str, Any], accepted_positions: Iterable[Any]) -> dict[str, Any]:
    """Assess one player against concrete positions, never against a broad group.

    A primary or exported secondary position is decisive.  Only selected role
    transitions (DM/CM/AM and physically plausible adjacent roles) may be
    inferred from attributes.  The return value is deterministic and suitable
    for tactics, recruitment and transfer models.
    """

    accepted = tuple(dict.fromkeys(
        canonical for value in accepted_positions if (canonical := canonical_position(value))
    ))
    positions = player_positions(player)
    primary = positions[0] if positions else canonical_position(player.get("primary_position"))
    raw = _raw_player(player)
    best_score = 0.0
    best_target = accepted[0] if accepted else None
    reason = "No valid target position"
    evidence = "none"
    for target in accepted:
        if primary == target:
            score, current_reason, current_evidence = 100.0, "Exakte Hauptposition", "primary"
        elif target in positions[1:]:
            score, current_reason, current_evidence = 93.0, "Exportierte FC-Zweitposition", "secondary"
        elif primary:
            source_group = detailed_position_group(primary)
            target_group = detailed_position_group(target)
            if source_group == target_group:
                score, current_reason = _same_family_fit(primary, target, raw)
                current_evidence = "adjacent"
            else:
                same_side = _side(primary) == _side(target) or "central" in {_side(primary), _side(target)}
                score, current_reason = _attribute_fit(raw, source_group, target_group, same_side)
                current_evidence = "attributes"
        else:
            score, current_reason, current_evidence = 0.0, "Primary position is missing", "none"
        if score > best_score:
            best_score, best_target, reason, evidence = score, target, current_reason, current_evidence
    if best_score >= 96:
        tier, label, coverage = "natural", "Hauptposition", 1.0
    elif best_score >= 90:
        tier, label, coverage = "secondary", "Zweitposition", .92
    elif best_score >= 74:
        tier, label, coverage = "capable", "Geeignete Alternative", .78
    elif best_score >= 58:
        tier, label, coverage = "adaptable", "Bedingt geeignet", .55
    elif best_score >= 42:
        tier, label, coverage = "emergency", "Emergency option", .25
    else:
        tier, label, coverage = "unsuitable", "Ungeeignet", 0.0
    return {
        "model": MODEL_ID,
        "score": round(best_score, 1),
        "tier": tier,
        "label": label,
        "coverageWeight": coverage,
        "targetPosition": best_target,
        "targetLabel": GERMAN_DISPLAY_BY_CANONICAL.get(str(best_target), best_target),
        "primaryPosition": primary,
        "positions": list(positions),
        "evidence": evidence,
        "reason": reason,
        "inPosition": best_score >= 58,
    }


def normalise_squad_group_assignments(value: Any, valid_player_ids: Iterable[int] | None = None) -> dict[str, list[str]]:
    """Validate the coach's optional squad-planning classifications.

    A missing player key means automatic position-fit assessment. An explicit
    empty list means "no group". One or two concrete pools are a deliberate
    coach override for squad-depth planning only.
    """

    raw = value if isinstance(value, dict) else _json_dict(value)
    valid = {int(item) for item in valid_player_ids} if valid_player_ids is not None else None
    result: dict[str, list[str]] = {}
    for player_key, groups in raw.items():
        player_id = as_int(player_key)
        if player_id is None or (valid is not None and player_id not in valid):
            continue
        source = groups if isinstance(groups, list) else []
        cleaned: list[str] = []
        for group in source:
            key = str(group or "")
            if key in SQUAD_POSITION_POOLS and key not in cleaned:
                cleaned.append(key)
            if len(cleaned) >= 2:
                break
        result[str(player_id)] = cleaned
    return result


def apply_squad_group_assignments(players: Iterable[dict[str, Any]], assignments: Any) -> list[dict[str, Any]]:
    """Decorate players without changing their observed FC positions."""

    source = list(players)
    normalised = normalise_squad_group_assignments(
        assignments,
        (int(player["ea_player_id"]) for player in source if as_int(player.get("ea_player_id")) is not None),
    )
    for player in source:
        player_id = str(as_int(player.get("ea_player_id")) or "")
        if player_id in normalised:
            player["squadGroupMode"] = "manual" if normalised[player_id] else "none"
            player["squadGroups"] = list(normalised[player_id])
        else:
            player["squadGroupMode"] = "auto"
            player["squadGroups"] = []
    return source


def squad_pool_fit(player: dict[str, Any], pool_key: str, accepted_positions: Iterable[Any] | None = None) -> dict[str, Any]:
    """Assess depth coverage, respecting an explicit coach classification.

    Manual classification is intentionally scoped to squad planning. Tactics
    still shows the objective FC/attribute position fit for the actual XI.
    """

    spec = SQUAD_POSITION_POOLS.get(pool_key)
    accepted = tuple(accepted_positions or (spec or {}).get("positions") or ())
    automatic = player_position_fit(player, accepted)
    mode = str(player.get("squadGroupMode") or "auto")
    groups = {str(item) for item in (player.get("squadGroups") or [])}
    if mode == "auto":
        return automatic
    if mode == "none" or pool_key not in groups:
        return {
            **automatic,
            "score": 0.0,
            "tier": "unsuitable",
            "label": "Not assigned to this squad group",
            "coverageWeight": 0.0,
            "evidence": "manual_squad_group",
            "reason": "Manual squad planning excludes this group",
            "inPosition": False,
        }
    score = max(86.0, float(automatic.get("score") or 0.0))
    return {
        **automatic,
        "score": round(score, 1),
        "tier": automatic.get("tier") if float(automatic.get("score") or 0.0) >= 90 else "capable",
        "label": automatic.get("label") if float(automatic.get("score") or 0.0) >= 90 else "Manual eingeplant",
        "coverageWeight": max(.86, float(automatic.get("coverageWeight") or 0.0)),
        "evidence": automatic.get("evidence") if float(automatic.get("score") or 0.0) >= 90 else "manual_squad_group",
        "reason": automatic.get("reason") if float(automatic.get("score") or 0.0) >= 90 else "Vom Trainer dieser Kadergruppe zugeordnet",
        "inPosition": True,
    }


def slot_position_pool(slot: dict[str, Any]) -> str:
    """Map one concrete formation slot to its side- and line-specific pool."""

    accepted = {canonical_position(value) for value in slot.get("acceptedPositions") or []}
    accepted.discard(None)
    label = canonical_position(slot.get("label"))
    group = str(slot.get("group") or "")
    x = float(slot.get("x") or 50)
    if "GK" in accepted or label == "GK":
        return "goalkeeper"
    if accepted & {"LCB", "CB", "RCB", "SW"} and not accepted & {"LB", "LWB", "RB", "RWB"}:
        return "centre_back"
    if accepted & {"LB", "LWB"} and not accepted & {"RB", "RWB"}:
        return "left_fullback"
    if accepted & {"RB", "RWB"} and not accepted & {"LB", "LWB"}:
        return "right_fullback"
    if label in {"LDM", "CDM", "RDM"} or group == "defensive_midfield":
        return "defensive_midfield"
    if label in {"LAM", "CAM", "RAM"} or group == "attacking_midfield":
        return "attacking_midfield"
    if label in {"LCM", "CM", "RCM"} or group == "central_midfield":
        return "central_midfield"
    if group == "left_wing" or (x < 50 and accepted & {"LM", "LF", "LW"}):
        return "left_wing"
    if group == "right_wing" or (x > 50 and accepted & {"RM", "RF", "RW"}):
        return "right_wing"
    return "striker"


def squad_pool_profiles(players: Iterable[dict[str, Any]], fallback_overall: float = 65.0) -> dict[str, dict[str, Any]]:
    """Build side-specific quality/depth profiles using weighted individual fit."""

    result: dict[str, dict[str, Any]] = {}
    source = list(players)
    for pool_key, spec in SQUAD_POSITION_POOLS.items():
        eligible: list[dict[str, Any]] = []
        for player in source:
            fit = squad_pool_fit(player, pool_key, spec["positions"])
            if float(fit["score"]) < 42:
                continue
            overall = float(as_int(player.get("dynamic_overall")) or as_int(player.get("overall")) or 0)
            effective = max(0.0, overall - max(0.0, 100.0 - float(fit["score"])) * .14)
            eligible.append({"overall": overall, "effectiveOverall": effective, "fit": fit, "player": player})
        eligible.sort(key=lambda item: (item["effectiveOverall"], item["fit"]["score"]), reverse=True)
        reliable = [item for item in eligible if float(item["fit"]["score"]) >= 58]
        natural = [item for item in eligible if str(item["fit"]["tier"]) in {"natural", "secondary"}]
        ratings = [float(item["effectiveOverall"]) for item in reliable]
        starter_slots = int(spec["starterSlots"])
        desired_depth = int(spec["desiredDepth"])
        starters = ratings[:starter_slots]
        rotation_index = min(len(ratings) - 1, desired_depth - 1) if ratings else -1
        result[pool_key] = {
            "label": spec["label"],
            "positions": list(spec["positions"]),
            "desiredDepth": desired_depth,
            "starterSlots": starter_slots,
            "count": len(reliable),
            "naturalCount": len(natural),
            "coverageUnits": round(sum(float(item["fit"]["coverageWeight"]) for item in eligible), 2),
            "avg": round(sum(ratings) / len(ratings), 2) if ratings else float(fallback_overall),
            "starterAvg": round(sum(starters) / len(starters), 2) if starters else float(fallback_overall - 1),
            "starterFloor": round(min(starters), 2) if starters else float(fallback_overall - 1),
            "rotationFloor": round(ratings[rotation_index], 2) if rotation_index >= 0 else float(fallback_overall - 4),
            "players": eligible,
        }
    return result


def best_squad_pool(player: dict[str, Any], profiles: dict[str, dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """Choose the most credible side-specific pool for one player."""

    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    for key, spec in SQUAD_POSITION_POOLS.items():
        fit = squad_pool_fit(player, key, spec["positions"])
        if float(fit["score"]) < 42:
            continue
        shortage = 0.0
        if profiles and key in profiles:
            profile = profiles[key]
            shortage = max(0.0, float(profile.get("desiredDepth") or 0) - float(profile.get("coverageUnits") or 0))
        candidates.append((float(fit["score"]), shortage, key, fit))
    if not candidates:
        fallback = detailed_position_group(player.get("primary_position"))
        key = fallback if fallback in SQUAD_POSITION_POOLS else "striker"
        return key, squad_pool_fit(player, key, SQUAD_POSITION_POOLS[key]["positions"])
    candidates.sort(reverse=True)
    _, _, key, fit = candidates[0]
    return key, fit
