"""Link team possession and passing from the last match saved by FC 26."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .db import Database
from .fc26_save_feed import SavedCareerFeed, persist_save_career_feed, read_saved_career_feed
from .fc26_save_match import READER_REVISION, read_saved_match
from .fc26_save_participation import SavedParticipation, persist_save_participation, read_saved_participation
from .fc26_save_comparison import (
    collect_comparable_passing, collect_comparable_shooting_defending,
    save_passing_comparison_enabled, save_shooting_defending_comparison_enabled,
    save_shooting_defending_fallback_enabled,
)


LOGGER = logging.getLogger(__name__)
SOURCE = "fc26_save_mxif"
MAX_SAVE_BYTES = 64 * 1024 * 1024
SAVE_SETTLE_NS = 1_000_000_000

PASS_METRICS = (
    ("through_passes_attempted", "Ground through pass attempts"),
    ("through_passes_completed", "Completed ground through passes"),
    ("lobbed_through_passes_attempted", "Lobbed through pass attempts"),
    ("lobbed_through_passes_completed", "Completed lobbed through passes"),
    ("line_breaking_passes", "Line-breaking passes"),
    ("wing_passes", "Wide passes"),
    ("one_two_attempted", "One-two attempts"),
    ("one_two_completed", "Completed one-twos"),
    ("lobbed_passes_attempted", "Lobbed pass attempts"),
    ("lobbed_passes_completed", "Completed lobbed passes"),
    ("set_piece_passes_attempted", "Set-piece pass attempts"),
    ("set_piece_passes_completed", "Completed set-piece passes"),
)
PASS_RATE_METRICS = (
    ("through_passes_accuracy_pct", "Ground through pass accuracy", "through_passes_completed", "through_passes_attempted"),
    ("lobbed_through_passes_accuracy_pct", "Lobbed through pass accuracy", "lobbed_through_passes_completed", "lobbed_through_passes_attempted"),
    ("lobbed_passes_accuracy_pct", "Lobbed pass accuracy", "lobbed_passes_completed", "lobbed_passes_attempted"),
    ("set_piece_passes_accuracy_pct", "Set-piece pass accuracy", "set_piece_passes_completed", "set_piece_passes_attempted"),
    ("one_two_success_pct", "One-two success rate", "one_two_completed", "one_two_attempted"),
)
TEAM_COMPLETIONS_REQUIRING_PLAYER_SUM = ("lobbed_passes_completed", "set_piece_passes_completed")
PLAYER_PASS_KEYS = ("through_passes_completed", "lobbed_through_passes_completed",
                    *TEAM_COMPLETIONS_REQUIRING_PLAYER_SUM)


@dataclass(frozen=True)
class SavedPlayerPassing:
    player_id: int
    team_id: int
    stats: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SavedMatchPossession:
    match_date: str
    home_id: int
    away_id: int
    home_score: int
    away_score: int
    home_pct: int
    away_pct: int
    home_players: frozenset[int]
    away_players: frozenset[int]
    mxif_sha256: str
    home_passes: tuple[tuple[str, int], ...] = ()
    away_passes: tuple[tuple[str, int], ...] = ()
    player_passes: tuple[SavedPlayerPassing, ...] = ()
    comparison_json: str | None = None
    participation: SavedParticipation | None = None
    career_feed: SavedCareerFeed | None = None


def decode_save_possession(data: bytes, *, compare_passing: bool = False,
                           compare_shooting_defending: bool = False) -> SavedMatchPossession | None:
    fixture = read_saved_match(data, compare_passing=compare_passing,
                              compare_shooting_defending=compare_shooting_defending)
    if fixture is None:
        return None
    home, away = fixture.home, fixture.away
    home_pct, away_pct = home.fields["possession_pct"], away.fields["possession_pct"]
    if home_pct + away_pct != 100:
        return None
    home_players = frozenset(player["player_id"] for player in home.players)
    away_players = frozenset(player["player_id"] for player in away.players)
    unique_players = len(home_players | away_players) == len(home.players) + len(away.players)
    home_passes, home_individual = _passing(home.fields, home.players if unique_players else [], home.team_id)
    away_passes, away_individual = _passing(away.fields, away.players if unique_players else [], away.team_id)
    comparisons: dict[str, Any] = {}
    if compare_passing:
        sides = {}
        for name, side, passes, individuals in (("home", home, home_passes, home_individual),
                                                ("away", away, away_passes, away_individual)):
            team, players = collect_comparable_passing(side, unique_players, dict(passes),
                                                       {player.player_id: dict(player.stats) for player in individuals})
            sides[name] = {"team": team, "players": players}
        if any(side["team"] or side["players"] for side in sides.values()):
            comparisons.update(sides)
    if compare_shooting_defending:
        shooting_defending = {name: collect_comparable_shooting_defending(side, unique_players)
                              for name, side in (("home", home), ("away", away))}
        if any(side["team"] or side["players"] for side in shooting_defending.values()):
            comparisons["shootingAndDefending"] = shooting_defending
    return SavedMatchPossession(fixture.day.isoformat(), home.team_id, away.team_id, home.goals, away.goals,
                                home_pct, away_pct, home_players, away_players,
                                fixture.facts_sha256, home_passes, away_passes,
                                home_individual + away_individual, json.dumps(comparisons, sort_keys=True) if comparisons else None,
                                read_saved_participation(data, fixture), read_saved_career_feed(data))


def _passing(fields: Mapping[str, Any], players: list[dict[str, Any]], team_id: int
             ) -> tuple[tuple[tuple[str, int], ...], tuple[SavedPlayerPassing, ...]]:
    total = fields["passes_total"]
    limits = {
        "through_passes_completed": min(total, fields["through_passes_attempted"]),
        "lobbed_through_passes_completed": min(total, fields["lobbed_through_passes_attempted"]),
        "lobbed_passes_completed": min(fields["passes_completed"], fields["lobbed_passes_attempted"]),
        "set_piece_passes_completed": min(fields["passes_completed"], fields["set_piece_passes_attempted"]),
        "one_two_completed": fields["one_two_attempted"],
    }
    if total == 0xFFFFFFFF or fields["passes_completed"] > total:
        return (), ()
    team = {key: fields[key] for key, _ in PASS_METRICS if fields[key] <= min(total, limits.get(key, total))}
    one_two_attempts = team.get("one_two_attempted")
    if "one_two_completed" in team:
        expected_rate = 100 * team["one_two_completed"] // one_two_attempts if one_two_attempts else 0
        if one_two_attempts is None or fields["one_two_reported_success_pct"] != expected_rate:
            team.pop("one_two_completed")
    # Reconcile the complete roster before publishing individual data or team
    # completion counts whose binary mapping still needs a cross-check.
    complete_roster = sum(player["passes_completed"] for player in players) == fields["passes_completed"]
    keys = tuple(key for key in PLAYER_PASS_KEYS if players and key in team
                 and (key not in TEAM_COMPLETIONS_REQUIRING_PLAYER_SUM or complete_roster)
                 and all(player[key] <= player["passes_completed"] <= player["passes_total"] < 0xFFFFFFFF
                         for player in players)
                 and sum(player[key] for player in players) == team[key])
    for key in TEAM_COMPLETIONS_REQUIRING_PLAYER_SUM:
        if key not in keys:
            team.pop(key, None)
    individual = []
    for player in sorted(players, key=lambda item: item["player_id"]):
        stats = {key: player[key] for key in keys}
        if complete_roster and player["ground_passes_completed"] <= player["passes_completed"] <= player["passes_total"] < 0xFFFFFFFF:
            stats["ground_passes_completed"] = player["ground_passes_completed"]
        if stats:
            individual.append(SavedPlayerPassing(player["player_id"], team_id, tuple(stats.items())))
    return tuple(team.items()), tuple(individual)


class SavePossessionImporter:
    def __init__(self, database: Database, root: Path | None = None) -> None:
        self.database = database
        local_app_data = os.environ.get("LOCALAPPDATA")
        self.root = root if root is not None else (
            Path(local_app_data) / "EA SPORTS FC 26" / "settings" if local_app_data else None
        )
        self._files: dict[Path, tuple[tuple[int, int, int, bool, bool], SavedMatchPossession | None]] = {}
        self._last_scan: tuple[tuple[int, int], frozenset[SavedMatchPossession],
                               frozenset[tuple[SavedMatchPossession, int]]] | None = None

    def scan_once(self) -> int:
        files = {}
        compare_passing = save_passing_comparison_enabled()
        compare_shooting_defending = (save_shooting_defending_comparison_enabled()
                                     or save_shooting_defending_fallback_enabled())
        if self.root and self.root.is_dir():
            for path in self.root.glob("CmMgr*"):
                try:
                    before = path.stat()
                    if (not path.is_file() or not 0 < before.st_size <= MAX_SAVE_BYTES
                            or time.time_ns() - before.st_mtime_ns < SAVE_SETTLE_NS):
                        continue
                    signature = (before.st_size, before.st_mtime_ns, before.st_ino, compare_passing, compare_shooting_defending)
                    cached = self._files.get(path)
                    if cached and signature == cached[0]:
                        files[path] = cached
                        continue
                    with path.open("rb") as save:
                        data = save.read(MAX_SAVE_BYTES + 1)
                    after = path.stat()
                    if signature[:3] == (after.st_size, after.st_mtime_ns, after.st_ino) and after.st_size == len(data):
                        files[path] = (signature, decode_save_possession(data, compare_passing=compare_passing,
                                                                       compare_shooting_defending=compare_shooting_defending))
                except OSError:
                    # EA may replace or lock the file while saving. The next scan retries.
                    continue
        self._files = files
        matches = frozenset(match for _, match in files.values() if match is not None)
        feed_times: dict[SavedMatchPossession, int] = {}
        for signature, match in files.values():
            if match and match.career_feed:
                feed_times[match] = max(signature[1], feed_times.get(match, 0))
        if not matches:
            return 0
        with self.database.connect() as conn:
            snapshot_revision = tuple(conn.execute("SELECT COUNT(*),COALESCE(MAX(id),0) FROM snapshots").fetchone())
        scan = (snapshot_revision, matches, frozenset(feed_times.items()))
        if scan == self._last_scan:
            return 0

        saved: set[int] = set()
        with self.database.transaction() as conn:
            candidates: dict[int, list[tuple[int, SavedMatchPossession]]] = {}
            feeds: dict[int, list[tuple[str, int, int, SavedCareerFeed]]] = {}
            for match in sorted(matches, key=lambda match: match.mxif_sha256):
                candidate = self._linked_observation(conn, match)
                if candidate:
                    fixture_id, snapshot_id = candidate
                    candidates.setdefault(fixture_id, []).append((snapshot_id, match))
            for fixture_id, sources in candidates.items():
                if len({(item.home_pct, item.away_pct) for _, item in sources}) != 1:
                    LOGGER.info("FC26 saves disagree on possession for Atlas fixture %s", fixture_id)
                    continue
                snapshot_id, match = sources[0]
                inserted = conn.execute(
                    """INSERT INTO fc26_save_possession (fixture_id,snapshot_id,mxif_sha256,home_pct,away_pct)
                       VALUES (?,?,?,?,?) ON CONFLICT(fixture_id) DO NOTHING""",
                    (fixture_id, snapshot_id, match.mxif_sha256, match.home_pct, match.away_pct),
                ).rowcount
                passing = {(item.home_passes, item.away_passes) for _, item in sources}
                player_passing = {item.player_passes for _, item in sources}
                enriched = individual_imported = 0
                # A legacy possession row can only be enriched by the same
                # mxif that supplied it, without replacing historical evidence.
                anchor = conn.execute(
                    """SELECT p.mxif_sha256,p.snapshot_id,s.career_id
                       FROM fc26_save_possession p JOIN snapshots s ON s.id=p.snapshot_id WHERE p.fixture_id=?""",
                    (fixture_id,),
                ).fetchone()
                anchored_sources = [item for _, item in sources if item.mxif_sha256 == anchor["mxif_sha256"]]
                original = next(iter(anchored_sources), None)
                if original is not None and len(passing) == 1:
                    home, away = original.home_passes, original.away_passes
                    if home or away:
                        enriched = conn.execute(
                            """INSERT INTO fc26_save_passes (fixture_id,reader_revision,stats_json)
                               VALUES (?,?,?) ON CONFLICT(fixture_id) DO UPDATE
                               SET stats_json=json_patch(excluded.stats_json,fc26_save_passes.stats_json)
                               WHERE length(json_patch(excluded.stats_json,fc26_save_passes.stats_json))
                                     > length(json(fc26_save_passes.stats_json))""",
                            (fixture_id, READER_REVISION, json.dumps({"home": dict(home), "away": dict(away)})),
                        ).rowcount
                elif len(passing) > 1:
                    LOGGER.info("FC26 saves disagree on passing for Atlas fixture %s", fixture_id)
                if original is not None and original.player_passes and len(player_passing) == 1:
                    payload = {p.player_id: {"teamEaId": p.team_id, **dict(p.stats)} for p in original.player_passes}
                    individual_imported = conn.execute(
                        """INSERT INTO fc26_save_player_passes (fixture_id,reader_revision,stats_json)
                           VALUES (?,?,?) ON CONFLICT(fixture_id) DO UPDATE
                           SET stats_json=json_patch(excluded.stats_json,fc26_save_player_passes.stats_json)
                           WHERE length(json_patch(excluded.stats_json,fc26_save_player_passes.stats_json))
                                 > length(json(fc26_save_player_passes.stats_json))""",
                        (fixture_id, READER_REVISION, json.dumps(payload)),
                    ).rowcount
                elif len(player_passing) > 1:
                    LOGGER.info("FC26 saves disagree on individual passing for Atlas fixture %s", fixture_id)
                comparison_imported = 0
                if original is not None and original.comparison_json:
                    comparisons = {item.comparison_json for _, item in sources}
                    if len(comparisons) == 1:
                        comparison_imported = conn.execute(
                            """INSERT INTO fc26_save_passing_comparison (fixture_id,reader_revision,stats_json)
                               VALUES (?,?,?) ON CONFLICT(fixture_id) DO UPDATE
                               SET stats_json=json_patch(excluded.stats_json,fc26_save_passing_comparison.stats_json)
                               WHERE length(json_patch(excluded.stats_json,fc26_save_passing_comparison.stats_json))
                                     > length(json(fc26_save_passing_comparison.stats_json))""",
                            (fixture_id, READER_REVISION, original.comparison_json),
                        ).rowcount
                    else:
                        LOGGER.info("FC26 saves disagree on comparable statistics for Atlas fixture %s", fixture_id)
                participation_imported = 0
                states = [item.participation for item in anchored_sources if item.participation is not None]
                if states and len({(state.team_id, state.players) for state in states}) == 1:
                    state = min(states, key=lambda candidate: candidate.block_hash)
                    participation_imported = persist_save_participation(conn, fixture_id, anchor["snapshot_id"], state)
                if inserted or enriched or individual_imported or comparison_imported or participation_imported:
                    saved.add(fixture_id)
                for source in anchored_sources:
                    if source.career_feed:
                        feeds.setdefault(anchor["career_id"], []).append(
                            (source.match_date, feed_times[source], fixture_id, source.career_feed))
            for career_id, candidates_for_career in feeds.items():
                newest = max(item[:2] for item in candidates_for_career)
                at_newest = [item for item in candidates_for_career if item[:2] == newest]
                if len({item[3].sha256 for item in at_newest}) != 1:
                    LOGGER.info("FC26 saves disagree on career feed for Atlas career %s", career_id)
                    continue
                day, mtime, fixture_id, feed = min(at_newest, key=lambda item: item[2])
                if persist_save_career_feed(conn, career_id, fixture_id, day, mtime, feed):
                    saved.add(fixture_id)
        self._last_scan = scan
        return len(saved)

    @staticmethod
    def _linked_observation(conn: sqlite3.Connection, match: SavedMatchPossession) -> tuple[int, int] | None:
        rows = conn.execute(
            """SELECT s.id snapshot_id,s.managed_team_ea_id,fo.fixture_id,fo.fixture_key
               FROM snapshots s JOIN fixture_observations fo ON fo.snapshot_id=s.id
               JOIN fixtures f ON f.id=fo.fixture_id AND f.career_id=s.career_id
               WHERE fo.date=? AND f.home_team_ea_id=? AND f.away_team_ea_id=?
                 AND fo.home_score=? AND fo.away_score=? AND fo.is_completed=1
                 AND fo.managed_team_involved=1 AND s.managed_team_ea_id IN (?,?)
               ORDER BY s.import_sequence,s.id""",
            (match.match_date, match.home_id, match.away_id, match.home_score, match.away_score,
             match.home_id, match.away_id),
        ).fetchall()
        if len({row["fixture_id"] for row in rows}) != 1:
            return None
        for row in rows:
            observed = match.home_players if row["managed_team_ea_id"] == match.home_id else match.away_players
            participants = frozenset(result[0] for result in conn.execute(
                """SELECT player_ea_id FROM player_match_performances
                   WHERE snapshot_id=? AND fixture_key=? AND minutes_played>0 AND join_status='joined_by_date'""",
                (row["snapshot_id"], row["fixture_key"]),
            ))
            # mxif includes unused substitutes, while ratings list appearances.
            if len(participants) >= 11 and participants <= observed:
                return row["fixture_id"], row["snapshot_id"]
        return None


def snapshot_save_possession(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                             fixture_id: int | None = None) -> dict[int, dict[str, Any]]:
    try:
        rows = conn.execute(
            """SELECT p.*,f.home_team_ea_id,f.away_team_ea_id
               FROM fc26_save_possession p JOIN snapshots s ON s.id=p.snapshot_id
               JOIN fixtures f ON f.id=p.fixture_id
               WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
                 AND (? IS NULL OR p.fixture_id=?)""",
            (snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"], fixture_id, fixture_id),
        )
    except sqlite3.OperationalError as exc:
        if str(exc) == "no such table: fc26_save_possession":
            return {}
        raise
    return {row["fixture_id"]: {"kind": SOURCE, "sourceSnapshotId": row["snapshot_id"],
                               "mxifSha256": row["mxif_sha256"], "homePct": row["home_pct"],
                               "awayPct": row["away_pct"], "homeTeamEaId": row["home_team_ea_id"],
                               "awayTeamEaId": row["away_team_ea_id"]} for row in rows}


def snapshot_save_passes(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                         fixture_id: int | None = None) -> dict[int, dict[str, Any]]:
    try:
        rows = conn.execute(
            """SELECT p.fixture_id,p.snapshot_id,p.mxif_sha256,t.reader_revision,t.stats_json,
                      f.home_team_ea_id,f.away_team_ea_id
               FROM fc26_save_passes t JOIN fc26_save_possession p ON p.fixture_id=t.fixture_id
               JOIN snapshots s ON s.id=p.snapshot_id JOIN fixtures f ON f.id=p.fixture_id
               WHERE s.career_id=? AND s.season_index=? AND s.import_sequence<=?
                 AND (? IS NULL OR p.fixture_id=?)""",
            (snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"], fixture_id, fixture_id),
        )
    except sqlite3.OperationalError as exc:
        if str(exc) == "no such table: fc26_save_passes":
            return {}
        raise
    result = {}
    for row in rows:
        stats = json.loads(row["stats_json"])
        for side in ("home", "away"):
            fields = stats[side]
            for key, _, completed_key, attempted_key in PASS_RATE_METRICS:
                attempted, completed = fields.get(attempted_key), fields.get(completed_key)
                if attempted and completed is not None and 0 <= completed <= attempted:
                    fields[key] = round(completed / attempted * 100, 1)
        result[row["fixture_id"]] = {**stats, "kind": SOURCE, "sourceSnapshotId": row["snapshot_id"],
                                     "mxifSha256": row["mxif_sha256"], "readerRevision": row["reader_revision"],
                                     "homeTeamEaId": row["home_team_ea_id"], "awayTeamEaId": row["away_team_ea_id"]}
    return result


def fixture_save_player_passes(conn: sqlite3.Connection, snapshot: Mapping[str, Any],
                               fixture_id: int) -> dict[int, dict[str, Any]]:
    try:
        row = conn.execute(
            """SELECT p.snapshot_id,p.mxif_sha256,t.reader_revision,t.stats_json
               FROM fc26_save_player_passes t JOIN fc26_save_possession p ON p.fixture_id=t.fixture_id
               JOIN snapshots s ON s.id=p.snapshot_id
               WHERE p.fixture_id=? AND s.career_id=? AND s.season_index=? AND s.import_sequence<=?""",
            (fixture_id, snapshot["career_id"], snapshot["season_index"], snapshot["import_sequence"]),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if str(exc) == "no such table: fc26_save_player_passes":
            return {}
        raise
    if row is None:
        return {}
    source = {"kind": SOURCE, "sourceSnapshotId": row["snapshot_id"],
              "mxifSha256": row["mxif_sha256"], "readerRevision": row["reader_revision"]}
    return {int(player_id): {**stats, "source": source}
            for player_id, stats in json.loads(row["stats_json"]).items()}
