from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from .media_utils import season_start_from_date
from .server_utils import as_int


MODEL_ID = "atlas-match-stat-reconstruction-v1"

COUNT_FIELDS = (
    "appearances",
    "man_of_the_match",
    "goals",
    "assists",
    "yellow_cards",
    "second_yellow_cards",
    "red_cards",
    "saves",
    "goals_conceded",
    "clean_sheets",
)


def _season_snapshots(conn: sqlite3.Connection, snapshot_id: int) -> list[sqlite3.Row]:
    current = conn.execute(
        "SELECT id,career_id,career_date,import_sequence,managed_team_ea_id FROM snapshots WHERE id=?",
        (snapshot_id,),
    ).fetchone()
    if not current:
        return []
    season = season_start_from_date(str(current["career_date"] or ""))
    rows = conn.execute(
        "SELECT id,career_id,career_date,import_sequence,managed_team_ea_id FROM snapshots "
        "WHERE career_id=? AND import_sequence<=? ORDER BY import_sequence",
        (current["career_id"], current["import_sequence"]),
    ).fetchall()
    return [row for row in rows if season_start_from_date(str(row["career_date"] or "")) == season]


def _new_completed_fixture(
    conn: sqlite3.Connection, previous_snapshot_id: int, current_snapshot_id: int,
) -> sqlite3.Row | None:
    rows = conn.execute(
        "SELECT f.fixture_key,f.id fixture_id,f.competition_object_id,fo.date,fo.competition_name "
        "FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id "
        "WHERE fo.snapshot_id=? AND fo.managed_team_involved=1 AND fo.is_completed=1 "
        "AND NOT EXISTS(SELECT 1 FROM fixture_observations old "
        "WHERE old.snapshot_id=? AND old.fixture_id=fo.fixture_id AND old.is_completed=1)",
        (current_snapshot_id, previous_snapshot_id),
    ).fetchall()
    # Snapshot deltas are only attributable when exactly one managed match became
    # complete. Missing exports are deliberately reported as unknown, never guessed.
    return rows[0] if len(rows) == 1 else None


def _competition_totals(
    conn: sqlite3.Connection, snapshot_id: int, team_id: int, competition_id: int | None,
) -> dict[int, dict[str, int]]:
    if competition_id is None:
        return {}
    columns = ",".join(f"COALESCE({field},0) {field}" for field in COUNT_FIELDS)
    rows = conn.execute(
        f"SELECT player_ea_id,{columns} FROM season_stat_states "
        "WHERE snapshot_id=? AND represented_team_ea_id=? AND competition_object_id=?",
        (snapshot_id, team_id, competition_id),
    ).fetchall()
    result: dict[int, dict[str, int]] = {}
    for row in rows:
        result[int(row["player_ea_id"])] = {field: as_int(row[field]) or 0 for field in COUNT_FIELDS}
    return result


def reconstruct_match_stats(
    conn: sqlite3.Connection, snapshot_id: int, *, player_id: int | None = None,
) -> dict[str, dict[int, dict[str, Any]]]:
    """Reconstruct managed-team match counts from consecutive cumulative snapshots.

    FC exposes these statistics cumulatively per player, competition and season. The
    auto-exporter normally creates one snapshot after each completed managed match.
    We only attribute a delta when one—and exactly one—new completed fixture exists.
    """

    snapshots = _season_snapshots(conn, snapshot_id)
    reconstructed: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for previous, current in zip(snapshots, snapshots[1:]):
        previous_team = as_int(previous["managed_team_ea_id"])
        current_team = as_int(current["managed_team_ea_id"])
        if current_team is None or previous_team != current_team:
            continue
        fixture = _new_completed_fixture(conn, int(previous["id"]), int(current["id"]))
        if not fixture or not fixture["fixture_key"]:
            continue
        competition_id = as_int(fixture["competition_object_id"])
        before = _competition_totals(conn, int(previous["id"]), current_team, competition_id)
        after = _competition_totals(conn, int(current["id"]), current_team, competition_id)
        participant_rows = conn.execute(
            "SELECT player_ea_id,rating,minutes_played,actual_position FROM player_match_performances "
            "WHERE snapshot_id=? AND fixture_key=?",
            (current["id"], fixture["fixture_key"]),
        ).fetchall()
        participants = {int(row["player_ea_id"]): row for row in participant_rows}
        candidate_ids = set(participants) | set(after)
        if player_id is not None:
            candidate_ids &= {int(player_id)}
        rows_for_fixture: dict[int, dict[str, Any]] = {}
        invalid_fixture = False
        for candidate_id in candidate_ids:
            current_values = after.get(candidate_id, {})
            previous_values = before.get(candidate_id, {})
            delta = {
                field: int(current_values.get(field, 0)) - int(previous_values.get(field, 0))
                for field in COUNT_FIELDS
            }
            if any(value < 0 for value in delta.values()) or delta["appearances"] > 1:
                invalid_fixture = True
                break
            performance = participants.get(candidate_id)
            if performance is None and not any(delta.values()):
                continue
            shots_on_target_faced = delta["saves"] + delta["goals_conceded"]
            rows_for_fixture[candidate_id] = {
                "modelId": MODEL_ID,
                "source": "consecutive_snapshot_delta",
                "sourceLabel": "Aus aufeinanderfolgenden Snapshots rekonstruiert",
                "confidence": 1.0,
                "snapshotId": int(current["id"]),
                "fixtureId": as_int(fixture["fixture_id"]),
                "fixtureKey": str(fixture["fixture_key"]),
                "date": fixture["date"],
                "competitionObjectId": competition_id,
                "competitionName": fixture["competition_name"],
                "playerEaId": candidate_id,
                "rating": float(performance["rating"]) if performance and performance["rating"] is not None else None,
                "minutesPlayed": as_int(performance["minutes_played"]) if performance else None,
                "actualPosition": performance["actual_position"] if performance else None,
                **delta,
                "shots_on_target_faced": shots_on_target_faced,
                "save_percentage": (
                    round(delta["saves"] / shots_on_target_faced, 4)
                    if shots_on_target_faced > 0 else None
                ),
            }
        if not invalid_fixture:
            reconstructed[str(fixture["fixture_key"])] = rows_for_fixture
    return dict(reconstructed)


def reconstructed_player_matches(
    conn: sqlite3.Connection, snapshot_id: int, player_id: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rows in reconstruct_match_stats(conn, snapshot_id, player_id=player_id).values():
        item = rows.get(int(player_id))
        if item:
            result.append(item)
    return sorted(result, key=lambda item: (str(item.get("date") or ""), str(item.get("fixtureKey") or "")), reverse=True)

# ---------------------------------------------------------------------------
# FC26 detailed match-stat integration (validated v0.41 wide export)
# ---------------------------------------------------------------------------
DETAILED_MODEL_ID = "atlas-fc26-match-stats-v2"

_DETAIL_METADATA_FIELDS = {
    "snapshot_id", "tracker_capture_id", "trigger", "team_index", "array_index",
    "selector_signed", "player_id", "player_name", "binding_source", "tracker_participant",
}
_RATE_FIELDS = {
    "pass_accuracy_pct_derived", "dribble_success_pct_derived", "cross_success_pct_derived",
    "stand_tackle_success_pct_derived", "slide_tackle_success_pct_derived",
    "offense_duel_success_pct_derived", "defense_duel_success_pct_derived",
    "aerial_duel_success_pct_derived", "save_success_pct_derived",
}
_SUM_FIELDS = {
    "npk_goals", "own_goals", "assists", "secondary_assist", "yellow_card_events", "red_dismissals",
    "minutes_played", "shots", "shots_on_target", "pk_goals", "passes", "passes_completed",
    "fouls_committed", "saves", "tackles", "interceptions", "goals_conceded", "offsides",
    "dribbles", "dribbles_completed", "fouls_won", "shootout_goals", "blocks", "clearances",
    "fk_goals", "crosses_attempted", "crosses_delivered", "crosses_blocked", "punches", "dives_at_feet",
    "stand_tackles", "slide_tackles", "key_passes", "penalties_committed", "skillmove_beats",
    "possession_won", "possession_lost", "shots_against", "penalty_saves", "shootout_saves",
    "stand_tackles_won", "slide_tackles_won", "penalties_won", "beaten_by_opponent",
    "beaten_in_defensive_third", "beaten_in_box", "saving_shots_on_target", "shootout_goals_conceded",
    "penalty_goals_conceded", "passes_intercepted", "nutmegs", "knock_ons", "shots_blocked",
    "offside_passes", "tackled_by_opponent", "beat_with_pass", "offense_duels_attempted",
    "offense_duels_won", "defense_duels_attempted", "defense_duels_won", "aerial_duels_attempted",
    "aerial_duels_won", "passes_under_pressure", "passes_completed_under_pressure", "offsides_caused",
    "corners_won", "assists_from_shots", "assists_from_dummy", "save_punch_to_clearance", "saving_crosses",
    "tracker_completed_through_passes_including_lobbed", "tracker_non_set_piece_shots",
    "npk_expected_goals", "expected_assists", "expected_goals_derived", "penalty_attempts_derived",
    "goals_derived", "shots_off_target_derived",
    "passes_incomplete_derived", "dribbles_failed_derived",
}


def _json_object(value: Any) -> dict[str, Any]:
    import json
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _num(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(num: float, den: float) -> float | None:
    return round(num / den * 100.0, 1) if den > 0 else None


def _recalculate_rates(stats: dict[str, Any]) -> None:
    pairs = {
        "pass_accuracy_pct_derived": ("passes_completed", "passes"),
        "dribble_success_pct_derived": ("dribbles_completed", "dribbles"),
        "cross_success_pct_derived": ("crosses_delivered", "crosses_attempted"),
        "stand_tackle_success_pct_derived": ("stand_tackles_won", "stand_tackles"),
        "slide_tackle_success_pct_derived": ("slide_tackles_won", "slide_tackles"),
        "offense_duel_success_pct_derived": ("offense_duels_won", "offense_duels_attempted"),
        "defense_duel_success_pct_derived": ("defense_duels_won", "defense_duels_attempted"),
        "aerial_duel_success_pct_derived": ("aerial_duels_won", "aerial_duels_attempted"),
    }
    for field, (won, attempted) in pairs.items():
        stats[field] = _pct(float(stats.get(won) or 0), float(stats.get(attempted) or 0))
    # FC26 validation uses saves/(saves + conceded) for the visible save-success surface.
    stats["save_success_pct_derived"] = _pct(float(stats.get("saves") or 0), float(stats.get("saves") or 0) + float(stats.get("goals_conceded") or 0))
    stats["pressure_pass_accuracy_pct"] = _pct(float(stats.get("passes_completed_under_pressure") or 0), float(stats.get("passes_under_pressure") or 0))
    stats["shot_accuracy_pct"] = _pct(float(stats.get("shots_on_target") or 0), float(stats.get("shots") or 0))


def _safe_ratio(numerator: Any, denominator: Any, *, scale: float = 1.0, digits: int = 2) -> float | None:
    num = _num(numerator)
    den = _num(denominator)
    if num is None or den is None or den <= 0:
        return None
    return round(num / den * scale, digits)


def _evidence_class(matches: int, minutes: float) -> dict[str, Any]:
    if matches >= 8 and minutes >= 540:
        key, label, confidence = "established", "reliable sample", 1.0
    elif matches >= 3 and minutes >= 180:
        key, label, confidence = "developing", "wachsende Stichprobe", 0.72
    else:
        key, label, confidence = "small_sample", "kleine Stichprobe", 0.38
    return {
        "key": key, "label": label, "confidence": confidence,
        "matches": matches, "minutes": round(minutes, 1),
        "minimumPer90SampleMet": matches >= 3 and minutes >= 180,
        "minimumLeaderboardSampleMet": matches >= 5 and minutes >= 300,
    }


def _add_context_metrics(stats: dict[str, Any], *, matches: int | None = None) -> None:
    """Add interpretation-friendly metrics without changing the raw FC26 surface."""
    minutes = float(stats.get("minutes_played") or 0)
    per90_fields = (
        "goals_derived", "npk_goals", "assists", "shots", "shots_on_target", "key_passes",
        "dribbles_completed", "possession_won", "possession_lost", "interceptions", "tackles",
        "clearances", "aerial_duels_won", "fouls_committed", "saves", "goals_conceded",
    )
    if minutes > 0:
        for field in per90_fields:
            if field in stats:
                stats[f"{field}_per90"] = round(float(stats.get(field) or 0) * 90.0 / minutes, 2)
    stats["xg_per_shot"] = _safe_ratio(stats.get("npk_expected_goals"), stats.get("shots"), digits=3)
    stats["shot_on_target_pct"] = _safe_ratio(stats.get("shots_on_target"), stats.get("shots"), scale=100.0, digits=1)
    stats["pressure_pass_accuracy_pct"] = _safe_ratio(
        stats.get("passes_completed_under_pressure"), stats.get("passes_under_pressure"), scale=100.0, digits=1
    )
    stats["npk_finishing_delta"] = (
        round(float(stats.get("npk_goals") or 0) - float(stats.get("npk_expected_goals") or 0), 2)
        if stats.get("npk_expected_goals") is not None else None
    )
    stats["xg_plus_xa"] = round(float(stats.get("npk_expected_goals") or 0) + float(stats.get("expected_assists") or 0), 3)
    if minutes > 0:
        stats["xg_plus_xa_per90"] = round(float(stats["xg_plus_xa"]) * 90.0 / minutes, 2)
    stats["possession_balance"] = int(stats.get("possession_won") or 0) - int(stats.get("possession_lost") or 0)
    duel_won = sum(float(stats.get(key) or 0) for key in ("offense_duels_won", "defense_duels_won", "aerial_duels_won"))
    duel_attempted = sum(float(stats.get(key) or 0) for key in ("offense_duels_attempted", "defense_duels_attempted", "aerial_duels_attempted"))
    stats["combined_duel_success_pct"] = _pct(duel_won, duel_attempted)
    if matches and matches > 0:
        for field in (
            "npk_expected_goals", "expected_goals_derived", "penalty_attempts_derived", "expected_assists", "shots", "shots_on_target", "passes", "key_passes",
            "dribbles_completed", "possession_won", "possession_lost", "interceptions", "tackles",
            "aerial_duels_won", "fouls_committed", "goals_derived", "npk_goals", "assists",
        ):
            if field in stats:
                stats[f"{field}_per_match"] = round(float(stats.get(field) or 0) / matches, 2)


def _team_single_match_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    result = dict(stats)
    _recalculate_rates(result)
    _add_context_metrics(result, matches=1)
    return result


def _add_team_expected_goals_from_opponent_penalty(stats: dict[str, Any], opponent: dict[str, Any]) -> None:
    """Add project-level team xG when the opponent's committed-penalty count is known.

    The validated FC26 surface directly exposes NPK-xG. At team level, each
    opponent penalty committed represents one awarded penalty attempt in the
    integration model, so Atlas can apply the documented project rule
    `xG = NPK-xG + 0.7 * penalty_attempts`. Player-level total xG remains NPK-only
    because a missed penalty cannot yet be assigned safely to a shooter.
    """
    npk = _num(stats.get("npk_expected_goals"))
    committed = _num(opponent.get("penalties_committed"))
    if npk is None or committed is None:
        return
    attempts = max(0, int(round(committed)))
    stats["penalty_attempts_derived"] = attempts
    stats["expected_goals_derived"] = round(npk + 0.7 * attempts, 3)


def _rolling_mean(items: list[dict[str, Any]], key: str, window: int = 5) -> list[float | None]:
    out: list[float | None] = []
    for idx in range(len(items)):
        values = [_num(row.get(key)) for row in items[max(0, idx - window + 1):idx + 1]]
        clean = [value for value in values if value is not None]
        out.append(round(sum(clean) / len(clean), 3) if clean else None)
    return out


def aggregate_detailed_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate player/team detailed rows without averaging pre-computed percentages."""
    aggregate: dict[str, Any] = {}
    ratings: list[float] = []
    appearances = 0
    motm = 0
    for row in rows:
        if not row:
            continue
        appearances += 1
        rating = _num(row.get("game_rating"))
        if rating is not None and rating > 0:
            ratings.append(rating)
        motm += 1 if row.get("man_of_the_match") in (True, 1, "1", "true", "True") else 0
        for key, value in row.items():
            if key not in _SUM_FIELDS:
                continue
            number = _num(value)
            if number is not None:
                aggregate[key] = float(aggregate.get(key) or 0) + number
    for key, value in list(aggregate.items()):
        if abs(value - round(value)) < 1e-9 and key not in {"npk_expected_goals", "expected_assists"}:
            aggregate[key] = int(round(value))
        elif key in {"npk_expected_goals", "expected_assists"}:
            aggregate[key] = round(float(value), 3)
    aggregate["matches"] = appearances
    aggregate["man_of_the_match"] = motm
    aggregate["average_game_rating"] = round(sum(ratings) / len(ratings), 2) if ratings else None
    aggregate["minutes_per_match"] = round(float(aggregate.get("minutes_played") or 0) / appearances, 1) if appearances else None
    aggregate["evidence"] = _evidence_class(appearances, float(aggregate.get("minutes_played") or 0))
    _recalculate_rates(aggregate)
    minutes = float(aggregate.get("minutes_played") or 0)
    aggregate["npk_xg_per90"] = round(float(aggregate.get("npk_expected_goals") or 0) * 90 / minutes, 2) if minutes > 0 else None
    aggregate["xa_per90"] = round(float(aggregate.get("expected_assists") or 0) * 90 / minutes, 2) if minutes > 0 else None
    aggregate["shots_per90"] = round(float(aggregate.get("shots") or 0) * 90 / minutes, 2) if minutes > 0 else None
    aggregate["key_passes_per90"] = round(float(aggregate.get("key_passes") or 0) * 90 / minutes, 2) if minutes > 0 else None
    _add_context_metrics(aggregate, matches=appearances)
    return aggregate


def _match_events(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build an event summary without inventing chronology.

    The validated wide surface exposes event counts but no trustworthy event clock.
    NPK goals and penalty goals are split to avoid double-counting `goals_derived`.
    """
    events: list[dict[str, Any]] = []
    definitions = (
        ("own_goals", "own_goal", "Eigentor"),
        ("assists", "assist", "Vorlage"),
        ("yellow_card_events", "yellow_card", "Gelbe Karte"),
        ("red_dismissals", "red_card", "Platzverweis"),
        ("penalties_committed", "penalty_committed", "Elfmeter verursacht"),
        ("penalties_won", "penalty_won", "Elfmeter herausgeholt"),
        ("penalty_saves", "penalty_save", "Elfmeter gehalten"),
    )
    for player in players:
        stats = player.get("stats") or {}
        npk = _num(stats.get("npk_goals"))
        penalties = int(_num(stats.get("pk_goals")) or 0)
        if npk is None:
            # Compatibility fallback for synthetic/older compatible exports.
            npk_count = max(0, int(_num(stats.get("goals_derived")) or 0) - penalties)
        else:
            npk_count = max(0, int(npk))
        if npk_count:
            events.append({
                "type": "goal", "label": "Tor", "count": npk_count,
                "playerEaId": player.get("playerEaId"), "displayName": player.get("displayName"),
                "teamIndex": player.get("teamIndex"), "minute": None,
            })
        if penalties:
            events.append({
                "type": "penalty_goal", "label": "Elfmetertor", "count": penalties,
                "playerEaId": player.get("playerEaId"), "displayName": player.get("displayName"),
                "teamIndex": player.get("teamIndex"), "minute": None,
            })
        for field, event_type, label in definitions:
            count = int(_num(stats.get(field)) or 0)
            if count > 0:
                events.append({
                    "type": event_type, "label": label, "count": count,
                    "playerEaId": player.get("playerEaId"), "displayName": player.get("displayName"),
                    "teamIndex": player.get("teamIndex"), "minute": None,
                })
        if stats.get("man_of_the_match") in (True, 1, "1", "true", "True"):
            events.append({
                "type": "motm", "label": "Man of the Match", "count": 1,
                "playerEaId": player.get("playerEaId"), "displayName": player.get("displayName"),
                "teamIndex": player.get("teamIndex"), "minute": None,
            })
    priority = {"goal": 0, "own_goal": 1, "penalty_goal": 2, "yellow_card": 3, "red_card": 4, "penalty_save": 5, "motm": 6, "assist": 7}
    return sorted(events, key=lambda item: (priority.get(str(item.get("type")), 20), str(item.get("displayName") or "")))


def detailed_match(conn: sqlite3.Connection, fixture_id: int, *, career_id: int | None = None,
                   as_of_import_sequence: int | None = None) -> dict[str, Any] | None:
    clauses = ["mse.fixture_id=?", "mse.superseded_by_export_id IS NULL"]
    params: list[Any] = [fixture_id]
    if career_id is not None:
        clauses.append("mse.career_id=?")
        params.append(int(career_id))
    if as_of_import_sequence is not None:
        clauses.append("source_snapshot.import_sequence<=?")
        params.append(int(as_of_import_sequence))
    export = conn.execute(
        "SELECT mse.* FROM match_stat_exports mse LEFT JOIN snapshots source_snapshot ON source_snapshot.id=mse.snapshot_id WHERE "
        + " AND ".join(clauses) + " ORDER BY mse.id DESC LIMIT 1", tuple(params)
    ).fetchone()
    if not export:
        return None
    player_rows = conn.execute(
        "SELECT * FROM match_player_detailed_stats WHERE export_id=? ORDER BY team_index,game_rating DESC,minutes_played DESC",
        (export["id"],),
    ).fetchall()
    players: list[dict[str, Any]] = []
    for row in player_rows:
        stats = _json_object(row["stats_json"])
        _recalculate_rates(stats)
        _add_context_metrics(stats, matches=1)
        player_id = int(row["player_ea_id"])
        context = conn.execute(
            "SELECT display_name,primary_position,team_ea_id FROM player_states WHERE snapshot_id=? AND ea_player_id=?",
            (export["snapshot_id"], player_id),
        ).fetchone() if export["snapshot_id"] is not None else None
        players.append({
            "playerEaId": player_id,
            "displayName": context["display_name"] if context else None,
            "primaryPosition": context["primary_position"] if context else None,
            "teamEaId": context["team_ea_id"] if context else None,
            "teamIndex": int(row["team_index"]),
            "stats": stats,
        })
    team_rows = conn.execute(
        "SELECT * FROM match_team_detailed_stats WHERE export_id=? ORDER BY team_index", (export["id"],)
    ).fetchall()
    teams = [{"teamIndex": int(row["team_index"]), "teamEaId": row["team_ea_id"], "stats": _team_single_match_metrics(_json_object(row["stats_json"]))} for row in team_rows]
    if len(teams) == 2:
        _add_team_expected_goals_from_opponent_penalty(teams[0]["stats"], teams[1]["stats"])
        _add_team_expected_goals_from_opponent_penalty(teams[1]["stats"], teams[0]["stats"])
    return {
        "modelId": DETAILED_MODEL_ID,
        "available": True,
        "exportId": int(export["id"]),
        "externalExportId": export["external_export_id"],
        "status": export["export_status"],
        "linkageConfidence": export["linkage_confidence"],
        "snapshotId": export["snapshot_id"],
        "teams": teams,
        "players": players,
        "events": _match_events(players),
        "eventChronologyAvailable": False,
        "eventTimingAvailable": False,
        "eventTimingNote": "FC26 does not provide confirmed event minutes in this validated export surface. The event view is intentionally non-chronological and shows only exported types and counts.",
        "xgMode": "team_total_when_penalty_context_available",
        "xgNote": "FC26 provides NPK-xG directly. Total team xG is additionally derived as NPK-xG + 0.7 × opponent penalties conceded only when penalty context exists; player xG remains NPK-xG without a reliably attributable missed penalty.",
    }


def detailed_player_matches(
    conn: sqlite3.Connection, career_id: int, player_id: int, *, season_indices: list[int] | None = None,
    as_of_import_sequence: int | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [career_id, player_id]
    season_filter = ""
    if season_indices:
        placeholders = ",".join("?" for _ in season_indices)
        season_filter = f" AND s.season_index IN ({placeholders})"
        params.extend(int(v) for v in season_indices)
    if as_of_import_sequence is not None:
        season_filter += " AND s.import_sequence<=?"
        params.append(int(as_of_import_sequence))
    rows = conn.execute(
        f"""SELECT mse.id export_id,mse.fixture_id,mse.snapshot_id,mse.linkage_confidence,
                   mpds.team_index,mpds.stats_json,s.season_index,s.career_date,
                   f.fixture_key,fo.date,fo.competition_name,fo.home_team_name,fo.away_team_name,
                   fo.home_score,fo.away_score,fo.home_penalties,fo.away_penalties,
                   f.home_team_ea_id,f.away_team_ea_id
            FROM match_player_detailed_stats mpds
            JOIN match_stat_exports mse ON mse.id=mpds.export_id
            JOIN snapshots s ON s.id=mse.snapshot_id
            JOIN fixtures f ON f.id=mse.fixture_id
            LEFT JOIN fixture_observations fo ON fo.snapshot_id=mse.snapshot_id AND fo.fixture_id=mse.fixture_id
            WHERE mse.career_id=? AND mpds.player_ea_id=? AND mse.superseded_by_export_id IS NULL {season_filter}
            ORDER BY COALESCE(fo.date,s.career_date) DESC,mse.id DESC""",
        tuple(params),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        stats = _json_object(row["stats_json"])
        result.append({
            "exportId": int(row["export_id"]), "fixtureId": int(row["fixture_id"]), "fixtureKey": row["fixture_key"],
            "snapshotId": int(row["snapshot_id"]), "seasonIndex": int(row["season_index"]),
            "date": row["date"] or row["career_date"], "competitionName": row["competition_name"],
            "homeTeamName": row["home_team_name"], "awayTeamName": row["away_team_name"],
            "homeScore": row["home_score"], "awayScore": row["away_score"],
            "homePenalties": row["home_penalties"], "awayPenalties": row["away_penalties"],
            "homeTeamEaId": row["home_team_ea_id"], "awayTeamEaId": row["away_team_ea_id"],
            "teamIndex": int(row["team_index"]), "linkageConfidence": row["linkage_confidence"], "stats": stats,
        })
    return result



def _official_player_appearances(
    conn: sqlite3.Connection, career_id: int, player_id: int, season_indices: list[int],
) -> int | None:
    total = 0
    found = False
    for season_index in season_indices:
        snap = conn.execute(
            "SELECT id FROM snapshots WHERE career_id=? AND season_index=? ORDER BY import_sequence DESC LIMIT 1",
            (career_id, season_index),
        ).fetchone()
        if not snap:
            continue
        rows = conn.execute(
            "SELECT COALESCE(appearances,0) appearances FROM season_stat_states WHERE snapshot_id=? AND player_ea_id=?",
            (snap["id"], player_id),
        ).fetchall()
        if rows:
            found = True
            total += sum(int(row["appearances"] or 0) for row in rows)
    return total if found else None


def _player_team_context(conn: sqlite3.Connection, matches: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in matches:
        row = conn.execute(
            "SELECT stats_json FROM match_team_detailed_stats WHERE export_id=? AND team_index=?",
            (item["exportId"], item["teamIndex"]),
        ).fetchone()
        if row:
            rows.append(_json_object(row["stats_json"]))
    return aggregate_detailed_stats(rows) if rows else {}


def _player_team_share(player: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("npk_expected_goals", "expected_assists", "shots", "key_passes", "possession_won", "interceptions"):
        value = _num(player.get(key)); total = _num(team.get(key))
        result[key] = round(value / total * 100.0, 1) if value is not None and total and total > 0 else None
    return result


def detailed_player_season_history(conn: sqlite3.Connection, career_id: int, player_id: int) -> list[dict[str, Any]]:
    matches = detailed_player_matches(conn, career_id, player_id)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    grouped_matches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    competitions: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for item in matches:
        season_index = int(item.get("seasonIndex") or 0)
        stats = item.get("stats") or {}
        grouped[season_index].append(stats)
        grouped_matches[season_index].append(item)
        competitions[season_index][str(item.get("competitionName") or "Unknown competition")].append(stats)
    result: list[dict[str, Any]] = []
    for season_index in sorted(grouped, reverse=True):
        aggregate = aggregate_detailed_stats(grouped[season_index])
        official = _official_player_appearances(conn, career_id, player_id, [season_index])
        team = _player_team_context(conn, grouped_matches[season_index])
        covered = len({int(item["fixtureId"]) for item in grouped_matches[season_index]})
        result.append({
            "seasonIndex": season_index,
            "matchesCovered": covered,
            "officialAppearances": official,
            "coveragePct": round(covered / official * 100.0, 1) if official and official > 0 else None,
            "aggregate": aggregate,
            "teamShare": _player_team_share(aggregate, team),
            "competitions": [
                {"competitionName": name, "stats": aggregate_detailed_stats(rows)}
                for name, rows in sorted(competitions[season_index].items())
            ],
        })
    return result


def detailed_player_season_summary(
    conn: sqlite3.Connection, career_id: int, player_id: int, *, season_indices: list[int] | None = None,
) -> dict[str, Any]:
    matches = detailed_player_matches(conn, career_id, player_id, season_indices=season_indices)
    aggregate = aggregate_detailed_stats([item["stats"] for item in matches])
    competitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in matches:
        competitions[str(item.get("competitionName") or "Unknown competition")].append(item["stats"])
    resolved_seasons = season_indices or sorted({int(item.get("seasonIndex") or 0) for item in matches})
    official = _official_player_appearances(conn, career_id, player_id, [int(value) for value in resolved_seasons]) if resolved_seasons else None
    team = _player_team_context(conn, matches)
    covered = len({int(item["fixtureId"]) for item in matches})
    return {
        "modelId": DETAILED_MODEL_ID,
        "available": bool(matches),
        "matchesCovered": covered,
        "officialAppearances": official,
        "coveragePct": round(covered / official * 100.0, 1) if official and official > 0 else None,
        "aggregate": aggregate,
        "teamShare": _player_team_share(aggregate, team),
        "competitions": [
            {"competitionName": name, "stats": aggregate_detailed_stats(rows)}
            for name, rows in sorted(competitions.items())
        ],
    }


def _completed_managed_matches(conn: sqlite3.Connection, career_id: int, season_indices: list[int]) -> int:
    if not season_indices:
        return 0
    placeholders = ",".join("?" for _ in season_indices)
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT fo.fixture_id) total
            FROM fixture_observations fo JOIN snapshots s ON s.id=fo.snapshot_id
            WHERE s.career_id=? AND s.season_index IN ({placeholders})
              AND fo.is_completed=1 AND fo.managed_team_involved=1""",
        (career_id, *season_indices),
    ).fetchone()
    return int(row["total"] or 0) if row else 0


def detailed_analysis(
    conn: sqlite3.Connection, career_id: int, season_indices: list[int], managed_team_id: int | None,
) -> dict[str, Any]:
    if not season_indices:
        return {"modelId": DETAILED_MODEL_ID, "available": False, "matchesCovered": 0, "coveragePct": 0.0}
    placeholders = ",".join("?" for _ in season_indices)
    exports = conn.execute(
        f"""SELECT mse.*,s.season_index,s.career_date,f.home_team_ea_id,f.away_team_ea_id,
                   fo.date,fo.competition_name,fo.home_team_name,fo.away_team_name,fo.home_score,fo.away_score
            FROM match_stat_exports mse
            JOIN snapshots s ON s.id=mse.snapshot_id
            JOIN fixtures f ON f.id=mse.fixture_id
            LEFT JOIN fixture_observations fo ON fo.snapshot_id=mse.snapshot_id AND fo.fixture_id=mse.fixture_id
            WHERE mse.career_id=? AND s.season_index IN ({placeholders}) AND mse.fixture_id IS NOT NULL
              AND mse.superseded_by_export_id IS NULL
            ORDER BY COALESCE(fo.date,s.career_date),mse.id""",
        (career_id, *season_indices),
    ).fetchall()
    team_for_rows: list[dict[str, Any]] = []
    team_against_rows: list[dict[str, Any]] = []
    trends: list[dict[str, Any]] = []
    player_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    player_context: dict[int, tuple[str | None, str | None]] = {}
    season_for_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    season_against_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    home_for_rows: list[dict[str, Any]] = []
    home_against_rows: list[dict[str, Any]] = []
    away_for_rows: list[dict[str, Any]] = []
    away_against_rows: list[dict[str, Any]] = []
    competition_for: dict[str, list[dict[str, Any]]] = defaultdict(list)
    competition_against: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for export in exports:
        local_managed = managed_team_id
        if export["snapshot_id"] is not None:
            snap = conn.execute("SELECT managed_team_ea_id FROM snapshots WHERE id=?", (export["snapshot_id"],)).fetchone()
            if snap and snap[0] is not None:
                local_managed = as_int(snap[0])
        teams = conn.execute(
            "SELECT team_index,team_ea_id,stats_json FROM match_team_detailed_stats WHERE export_id=? ORDER BY team_index",
            (export["id"],),
        ).fetchall()
        parsed_teams = [
            {"teamIndex": int(r["team_index"]), "teamEaId": as_int(r["team_ea_id"]), "stats": _json_object(r["stats_json"])}
            for r in teams
        ]
        own = next((r for r in parsed_teams if local_managed is not None and r["teamEaId"] == local_managed), None)
        opp = next((r for r in parsed_teams if own is not None and r["teamIndex"] != own["teamIndex"]), None)
        if own and opp:
            own_stats = dict(own["stats"]); opp_stats = dict(opp["stats"])
            _add_team_expected_goals_from_opponent_penalty(own_stats, opp_stats)
            _add_team_expected_goals_from_opponent_penalty(opp_stats, own_stats)
            team_for_rows.append(own_stats); team_against_rows.append(opp_stats)
            season_index = int(export["season_index"])
            season_for_rows[season_index].append(own_stats)
            season_against_rows[season_index].append(opp_stats)
            competition = str(export["competition_name"] or "Unknown competition")
            competition_for[competition].append(own_stats); competition_against[competition].append(opp_stats)
            is_home = as_int(export["home_team_ea_id"]) == local_managed
            (home_for_rows if is_home else away_for_rows).append(own_stats)
            (home_against_rows if is_home else away_against_rows).append(opp_stats)
            own_metric = _team_single_match_metrics(own_stats); opp_metric = _team_single_match_metrics(opp_stats)
            trends.append({
                "fixtureId": int(export["fixture_id"]), "date": export["date"] or export["career_date"],
                "competitionName": export["competition_name"], "homeTeamName": export["home_team_name"], "awayTeamName": export["away_team_name"],
                "homeScore": export["home_score"], "awayScore": export["away_score"], "venue": "home" if is_home else "away",
                "npkXgFor": own_metric.get("npk_expected_goals"), "npkXgAgainst": opp_metric.get("npk_expected_goals"),
                "totalXgFor": own_metric.get("expected_goals_derived"), "totalXgAgainst": opp_metric.get("expected_goals_derived"),
                "xgDiff": round(float(own_metric.get("npk_expected_goals") or 0) - float(opp_metric.get("npk_expected_goals") or 0), 3),
                "xAFor": own_metric.get("expected_assists"), "xAAgainst": opp_metric.get("expected_assists"),
                "shotsFor": own_metric.get("shots"), "shotsAgainst": opp_metric.get("shots"),
                "shotQualityFor": own_metric.get("xg_per_shot"), "shotQualityAgainst": opp_metric.get("xg_per_shot"),
                "possessionBalanceFor": own_metric.get("possession_balance"),
            })
        prows = conn.execute(
            "SELECT player_ea_id,team_index,stats_json FROM match_player_detailed_stats WHERE export_id=?",
            (export["id"],),
        ).fetchall()
        for prow in prows:
            pid = int(prow["player_ea_id"]); stats = _json_object(prow["stats_json"])
            pteam = int(prow["team_index"])
            if own is not None and pteam != own["teamIndex"]:
                continue
            player_rows[pid].append(stats)
            if pid not in player_context:
                ctx = conn.execute(
                    "SELECT display_name,primary_position FROM player_states WHERE snapshot_id=? AND ea_player_id=?",
                    (export["snapshot_id"], pid),
                ).fetchone()
                player_context[pid] = (ctx["display_name"], ctx["primary_position"]) if ctx else (None, None)
    rolling_for = _rolling_mean(trends, "npkXgFor")
    rolling_against = _rolling_mean(trends, "npkXgAgainst")
    rolling_diff = _rolling_mean(trends, "xgDiff")
    for idx, trend in enumerate(trends):
        trend["rolling5NpkXgFor"] = rolling_for[idx]
        trend["rolling5NpkXgAgainst"] = rolling_against[idx]
        trend["rolling5XgDiff"] = rolling_diff[idx]
    player_summaries: list[dict[str, Any]] = []
    for pid, rows in player_rows.items():
        agg = aggregate_detailed_stats(rows)
        name, pos = player_context.get(pid, (None, None))
        player_summaries.append({"playerEaId": pid, "displayName": name, "primaryPosition": pos, "stats": agg, "evidence": agg.get("evidence")})
    total_completed = _completed_managed_matches(conn, career_id, season_indices)
    matches_covered = len({int(item["fixtureId"]) for item in trends})
    season_payload = []
    for season_index in sorted(season_for_rows):
        total_season = _completed_managed_matches(conn, career_id, [season_index])
        covered = len(season_for_rows[season_index])
        season_payload.append({
            "seasonIndex": season_index,
            "matchesCovered": covered,
            "totalCompletedMatches": total_season,
            "coveragePct": round(covered / total_season * 100.0, 1) if total_season else None,
            "for": aggregate_detailed_stats(season_for_rows[season_index]),
            "against": aggregate_detailed_stats(season_against_rows[season_index]),
        })
    return {
        "modelId": DETAILED_MODEL_ID,
        "available": bool(team_for_rows),
        "matchesCovered": matches_covered,
        "totalCompletedMatches": total_completed,
        "coveragePct": round(matches_covered / total_completed * 100.0, 1) if total_completed else None,
        "team": {"for": aggregate_detailed_stats(team_for_rows), "against": aggregate_detailed_stats(team_against_rows)},
        "trends": trends,
        "players": player_summaries,
        "splits": {
            "venue": {
                "home": {"matches": len(home_for_rows), "for": aggregate_detailed_stats(home_for_rows), "against": aggregate_detailed_stats(home_against_rows)},
                "away": {"matches": len(away_for_rows), "for": aggregate_detailed_stats(away_for_rows), "against": aggregate_detailed_stats(away_against_rows)},
            },
            "competitions": [
                {"competitionName": name, "matches": len(competition_for[name]), "for": aggregate_detailed_stats(competition_for[name]), "against": aggregate_detailed_stats(competition_against[name])}
                for name in sorted(competition_for)
            ],
        },
        "bySeason": season_payload,
        "xgMode": "team_total_when_penalty_context_available",
        "xgNote": "NPK-xG comes directly from FC26. Total team xG is supplemented only when penalty context exists, using NPK-xG + 0.7 × penalty attempts; player values remain NPK-xG.",
    }
