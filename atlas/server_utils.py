from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable

from .media_utils import competition_name_key

def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]

def latest_snapshot(conn: sqlite3.Connection, career_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC LIMIT 1",
        (career_id,),
    ).fetchone()

def career_clock(conn: sqlite3.Connection, career_id: int) -> dict[str, Any]:
    """Return the canonical live FC career clock for a career.

    Full snapshots remain the authoritative data state for attributes, fixtures and
    statistics. Lightweight transfer pulses are allowed to advance only the live
    career date (and matching season/team metadata) between full snapshots. An old
    pulse can never move the clock backwards behind the latest full snapshot.
    """
    snapshot = latest_snapshot(conn, career_id)
    if not snapshot:
        raise ValueError("The career clock requires at least one complete snapshot.")
    pulse = conn.execute(
        "SELECT * FROM transfer_pulses WHERE career_id=? ORDER BY career_date_sort DESC,id DESC LIMIT 1",
        (career_id,),
    ).fetchone()
    snapshot_date = str(snapshot["career_date"] or "")[:10]
    pulse_date = str(pulse["career_date"] or "")[:10] if pulse else None
    use_pulse = bool(pulse_date and pulse_date >= snapshot_date)
    career_date = pulse_date if use_pulse else snapshot_date
    try:
        staleness_days = max(0, (date.fromisoformat(career_date) - date.fromisoformat(snapshot_date)).days)
    except ValueError:
        staleness_days = 0
    return {
        "careerDate": career_date,
        "source": "transfer_pulse" if use_pulse else "snapshot",
        "snapshotDate": snapshot_date,
        "pulseDate": pulse_date,
        "stalenessDays": staleness_days,
        "seasonIndex": int(pulse["season_index"] if use_pulse else snapshot["season_index"]),
        "managedTeamId": as_int(pulse["managed_team_ea_id"]) if use_pulse else as_int(snapshot["managed_team_ea_id"]),
        "snapshotId": int(snapshot["id"]),
        "pulseId": int(pulse["id"]) if use_pulse else None,
    }

def effective_career_date(conn: sqlite3.Connection, snapshot: sqlite3.Row | dict[str, Any]) -> str:
    """Use the live career clock only for the latest snapshot.

    Historical snapshot views deliberately retain their own date, while live systems
    advance with transfer pulses between full snapshots.
    """
    career_id = as_int(snapshot["career_id"])
    snapshot_id = as_int(snapshot["id"])
    snapshot_date = str(snapshot["career_date"] or "")[:10]
    if career_id is None or snapshot_id is None:
        return snapshot_date
    latest = latest_snapshot(conn, career_id)
    if not latest or int(latest["id"]) != snapshot_id:
        return snapshot_date
    return str(career_clock(conn, career_id)["careerDate"])

def parse_raw(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}

def clean_raw(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["raw"] = parse_raw(item.pop("raw_json", None))
    return item

def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None

def input_bool(value: Any, label: str = "Wert", *, default: bool | None = None) -> bool:
    """Parse JSON/form booleans without treating the string ``false`` as true."""
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "ja"}:
            return True
        if normalized in {"0", "false", "no", "off", "nein", ""}:
            return False
    raise ValueError(f"{label} must be a Boolean value.")

def contract_role_label(value: Any) -> str:
    raw = as_int(value)
    return {
        -1: "Not set",
        0: "Not set",
        1: "Crucial player",
        2: "Important player",
        3: "Rotationsspieler",
        4: "Squad player",
        5: "Perspektivspieler",
    }.get(raw, f"Unknowne Rolle ({raw})" if raw is not None else "Not recorded")


def contract_role_expected_minutes_share(value: Any) -> float:
    """Deprecated compatibility shim.

    An FC26 squad role is technical metadata only and creates no
    Atlas playing-time entitlement.  Sporting expectations live in the separate
    player_sporting_expectations model.  Returning zero prevents legacy callers
    from silently reintroducing the old role-to-minutes coupling.
    """
    return 0.0

def parse_fc_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return None

def subtract_months(value: str, months: int) -> str:
    try:
        current = date.fromisoformat(value)
    except ValueError:
        return value
    total = current.year * 12 + current.month - 1 - max(0, months)
    year, month_index = divmod(total, 12)
    month = month_index + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(current.day, days[month - 1])
    return date(year, month, day).isoformat()

def fixture_group_value(row: dict[str, Any]) -> tuple[str, str, int]:
    raw = parse_raw(row.get("raw_json") or row.get("raw"))
    candidate = raw.get("match_group_id") or raw.get("matchday") or raw.get("round") or raw.get("stage_id")
    number = as_int(candidate)
    if number is not None and number >= 0:
        return (f"group-{number}", f"Spieltag / Runde {number}", number)
    day = str(row.get("date") or "No date")
    return (f"date-{day}", day, 100000000 + (as_int(day.replace('-', '')) or 0))

def ea_day_to_iso(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    raw = as_int(value)
    if raw is None or raw <= 0:
        return None
    if 19000101 <= raw <= 25001231:
        try:
            return datetime.strptime(str(raw), "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    try:
        from datetime import timedelta
        return (date(1970, 1, 1) + timedelta(days=raw - 141428)).isoformat()
    except (OverflowError, ValueError):
        return None

def age_on_date(birth_value: Any, current_date: str | None) -> int | None:
    birth_iso = ea_day_to_iso(birth_value)
    if not birth_iso or not current_date:
        return None
    try:
        born = date.fromisoformat(birth_iso)
        current = date.fromisoformat(current_date[:10])
    except ValueError:
        return None
    return current.year - born.year - ((current.month, current.day) < (born.month, born.day))

def player_age_data(birth_value: Any, current_date: str | None) -> dict[str, Any]:
    """Return the canonical player birth date and snapshot-relative age.

    Player ages must always be calculated against the career date of the selected
    snapshot rather than the computer's current date. Keeping both values together
    prevents individual views from formatting or calculating them differently.
    """
    return {
        "birth_date": ea_day_to_iso(birth_value),
        "age": age_on_date(birth_value, current_date),
    }

def competition_format_info(
    fixtures: list[dict[str, Any]],
    *,
    name: str,
    static_is_league: bool,
) -> dict[str, Any]:
    normalized = competition_name_key(name)
    group_counts: dict[int, int] = defaultdict(int)
    group_participants: dict[int, set[int]] = defaultdict(set)
    participants: set[int] = set()
    for fixture in fixtures:
        group = as_int(fixture.get("match_group_id"))
        if group is None:
            _, _, group = fixture_group_value(fixture)
        group_counts[group] += 1
        for field in ("home_team_ea_id", "away_team_ea_id"):
            team = as_int(fixture.get(field))
            if team is not None:
                participants.add(team)
                group_participants[group].add(team)

    if any(marker in normalized for marker in ("testspiel", "friendly")):
        return {"type": "friendly", "label": "Friendly", "source": "name", "confidence": 0.98, "hasTable": False, "leaguePhaseGroups": []}
    if any(marker in normalized for marker in ("relegation", "barrages", "play off", "playoff")):
        return {"type": "playoff", "label": "Play-off / Relegation", "source": "name", "confidence": 0.98, "hasTable": False, "leaguePhaseGroups": []}
    if any(marker in normalized for marker in ("super cup", "supercup", "supercopa", "trophee champ", "community shield")):
        return {"type": "knockout", "label": "Supercup", "source": "name", "confidence": 0.98, "hasTable": False, "leaguePhaseGroups": []}
    hybrid_markers = ("champions league", "europa league", "uecl", "uwcl", "libertadores", "sudamericana")
    if any(marker in normalized for marker in hybrid_markers):
        count_frequency = Counter(group_counts.values())
        candidates = [
            (frequency, count)
            for count, frequency in count_frequency.items()
            if frequency >= 3 and count >= 2
        ]
        phase_groups: list[int] = []
        if candidates:
            _, selected_count = max(candidates)
            phase_groups = sorted(group for group, count in group_counts.items() if count == selected_count)
        return {
            "type": "hybrid",
            "label": "League phase & knockout phase",
            "source": "name+fixtures",
            "confidence": 0.96,
            "hasTable": bool(phase_groups),
            "leaguePhaseGroups": phase_groups,
        }
    if static_is_league:
        return {"type": "league", "label": "League", "source": "reference_league", "confidence": 1.0, "hasTable": True, "leaguePhaseGroups": []}

    # Structural fallback for leagues whose static media ID is not yet known.
    non_empty_counts = [count for count in group_counts.values() if count > 0]
    if len(non_empty_counts) >= 4:
        most_common_count, frequency = Counter(non_empty_counts).most_common(1)[0]
        expected = len(participants) / 2 if participants else 0
        if frequency >= 4 and expected and abs(most_common_count - expected) <= 1:
            return {"type": "league", "label": "League", "source": "fixture_structure", "confidence": 0.9, "hasTable": True, "leaguePhaseGroups": []}

    return {"type": "knockout", "label": "Knockout competition", "source": "fixture_structure", "confidence": 0.82, "hasTable": False, "leaguePhaseGroups": []}

def aggregate_standings(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: dict[int, dict[str, Any]] = {}

    def entry(team_id: int | None, name: str | None) -> dict[str, Any] | None:
        if team_id is None:
            return None
        if team_id not in table:
            table[team_id] = {
                "team_id": team_id,
                "team_name": name or f"Team {team_id}",
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "goals_for": 0,
                "goals_against": 0,
                "goal_difference": 0,
                "points": 0,
            }
        return table[team_id]

    for fixture in fixtures:
        if not fixture.get("is_completed"):
            continue
        home_id = as_int(fixture.get("home_team_ea_id"))
        away_id = as_int(fixture.get("away_team_ea_id"))
        home = entry(home_id, fixture.get("home_team_name"))
        away = entry(away_id, fixture.get("away_team_name"))
        hs = as_int(fixture.get("home_score"))
        aw = as_int(fixture.get("away_score"))
        if home is None or away is None or hs is None or aw is None:
            continue
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += hs
        home["goals_against"] += aw
        away["goals_for"] += aw
        away["goals_against"] += hs
        if hs > aw:
            home["won"] += 1
            home["points"] += 3
            away["lost"] += 1
        elif aw > hs:
            away["won"] += 1
            away["points"] += 3
            home["lost"] += 1
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    result = list(table.values())
    for row in result:
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    result.sort(
        key=lambda row: (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            row["team_name"].lower(),
        )
    )
    for index, row in enumerate(result, start=1):
        row["position"] = index
    return result

def youth_potential_range(potential: Any, variance: Any, swing_low: Any) -> tuple[int | None, int | None]:
    """Return the two visible youth-potential bounds exported by EA FC.

    The career table stores a base potential plus two signed offsets.  Atlas does not
    reinterpret the hidden exact potential; it only renders the lowest and highest
    values described by those exported fields.
    """
    base = as_int(potential)
    if base is None:
        return None, None
    candidates = [base]
    for offset in (as_int(variance), as_int(swing_low)):
        if offset is not None:
            candidates.append(base + offset)
    return max(1, min(candidates)), min(99, max(candidates))

def annotate_knockout_progress(groups: list[dict[str, Any]], *, enabled: bool) -> None:
    if not enabled or not groups:
        return
    valid_orders = [as_int(group.get("order")) for group in groups]
    final_order = max((value for value in valid_orders if value is not None and value < 100000000), default=None)
    for group in groups:
        fixtures = group.get("fixtures") or []
        pairs: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for fixture in fixtures:
            home_id = as_int(fixture.get("home_team_ea_id")); away_id = as_int(fixture.get("away_team_ea_id"))
            if home_id is None or away_id is None or home_id <= 0 or away_id <= 0:
                continue
            pair = tuple(sorted((home_id, away_id)))
            pairs[pair].append(fixture)
            if fixture.get("is_completed"):
                hs = as_int(fixture.get("home_score")); aw = as_int(fixture.get("away_score"))
                hp = as_int(fixture.get("home_penalties")); ap = as_int(fixture.get("away_penalties"))
                winner = home_id if hs is not None and aw is not None and hs > aw else away_id if hs is not None and aw is not None and aw > hs else home_id if hp is not None and ap is not None and hp > ap else away_id if hp is not None and ap is not None and ap > hp else None
                fixture["winner_team_id"] = winner
        for pair_fixtures in pairs.values():
            if not pair_fixtures or not all(bool(item.get("is_completed")) for item in pair_fixtures):
                continue
            totals: dict[int, int] = defaultdict(int)
            penalty_winner = None
            for fixture in pair_fixtures:
                home_id = int(fixture["home_team_ea_id"]); away_id = int(fixture["away_team_ea_id"])
                hs = as_int(fixture.get("home_score")); aw = as_int(fixture.get("away_score"))
                if hs is not None and aw is not None:
                    totals[home_id] += hs; totals[away_id] += aw
                hp = as_int(fixture.get("home_penalties")); ap = as_int(fixture.get("away_penalties"))
                if hp is not None and ap is not None and hp != ap:
                    penalty_winner = home_id if hp > ap else away_id
            team_a, team_b = sorted(totals) if len(totals) == 2 else (None, None)
            advanced = None
            if team_a is not None and totals[team_a] != totals[team_b]:
                advanced = team_a if totals[team_a] > totals[team_b] else team_b
            elif penalty_winner is not None:
                advanced = penalty_winner
            if advanced is None:
                continue
            is_final = final_order is not None and as_int(group.get("order")) == final_order
            label = "Cup winner" if is_final else "Advanced"
            for fixture in pair_fixtures:
                fixture["advanced_team_id"] = advanced
                fixture["decision_label"] = label
                fixture["aggregate_score"] = f"{totals.get(advanced, 0)}:{totals.get(next((team for team in totals if team != advanced), advanced), 0)}" if len(pair_fixtures) > 1 else None
