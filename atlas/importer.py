from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import Database
from .paths import current_workspace_id, database_path as active_workspace_database_path, load_workspace_registry, save_workspace_registry
from .manifest import SnapshotValidationError, SnapshotValidator, ValidatedSnapshot
from .career_identity import CareerIdentityGuard


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(" ", "")))
    except (ValueError, TypeError):
        return None


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def read_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


@dataclass
class ImportResult:
    status: str
    snapshot_id: str
    career_id: int | None = None
    database_snapshot_id: int | None = None
    message: str = ""
    destination: str | None = None


class SnapshotImporter:
    def __init__(self, database: Database, validator: SnapshotValidator):
        self.database = database
        self.validator = validator

    def validate_many(self, folders: Iterable[Path]) -> list[ValidatedSnapshot]:
        validated: list[ValidatedSnapshot] = []
        for folder in folders:
            validated.append(self.validator.validate(folder))
        return validated

    @staticmethod
    def _is_transient_database_lock(exc: Exception) -> bool:
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        text = str(exc).casefold()
        return "database is locked" in text or "database table is locked" in text or "database is busy" in text

    def _recover_transient_failed(self, root: Path) -> int:
        """Return snapshots incorrectly failed only because SQLite was busy.

        v1.2.5 and earlier moved every import exception to failed/, including a
        short-lived SQLite writer collision. Those packages are immutable and
        safe to retry, so move only the known lock/busy failures back to ready.
        """
        failed = root / "failed"
        ready = root / "ready"
        if not failed.is_dir():
            return 0
        ready.mkdir(parents=True, exist_ok=True)
        recovered = 0
        for folder in sorted(failed.iterdir(), key=lambda p: p.name):
            if not folder.is_dir() or not (folder / "READY").is_file():
                continue
            error_path = folder / "import_error.json"
            if not error_path.is_file():
                continue
            try:
                payload = json.loads(error_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            message = str(payload.get("message") or "").casefold()
            code = str(payload.get("code") or "").casefold()
            if not (
                "database is locked" in message
                or "database table is locked" in message
                or "database is busy" in message
                or code in {"database_locked", "database_busy"}
            ):
                continue
            destination = ready / folder.name
            counter = 1
            while destination.exists():
                destination = ready / f"{folder.name}_retry{counter}"
                counter += 1
            try:
                error_path.unlink(missing_ok=True)
                shutil.move(str(folder), str(destination))
                recovered += 1
            except OSError:
                continue
        return recovered

    def import_ready_root(self, root: Path) -> list[ImportResult]:
        ready = root / "ready"
        # Heal the specific v1.2.5 failure mode before looking for new work.
        self._recover_transient_failed(root)
        ready.mkdir(parents=True, exist_ok=True)
        folders = [p for p in ready.iterdir() if p.is_dir() and (p / "READY").is_file()]
        validation_failures: list[ImportResult] = []
        valid: list[ValidatedSnapshot] = []
        for folder in folders:
            try:
                valid.append(self.validator.validate(folder))
            except Exception as exc:
                validation_failures.append(self._fail_folder(folder, exc, root))

        # Resolve careers before sorting by career. Unknown fingerprints become new careers.
        grouped: dict[str, list[ValidatedSnapshot]] = {}
        for item in valid:
            fingerprint = str(item.manifest["career"]["fingerprintCandidate"])
            grouped.setdefault(fingerprint, []).append(item)

        results = validation_failures
        for fingerprint in sorted(grouped):
            for item in sorted(grouped[fingerprint], key=lambda value: value.ordering_key):
                results.append(self.import_validated(item, root=root, move_after=True))
        return results

    def import_folder(self, folder: Path, *, root: Path | None = None, move_after: bool = False) -> ImportResult:
        try:
            validated = self.validator.validate(folder)
            return self.import_validated(validated, root=root, move_after=move_after)
        except Exception as exc:
            if root and move_after:
                return self._fail_folder(folder, exc, root)
            raise

    def import_validated(self, item: ValidatedSnapshot, *, root: Path | None, move_after: bool) -> ImportResult:
        external_id = item.snapshot_id
        with self.database.connect() as conn:
            duplicate = conn.execute(
                "SELECT id, career_id FROM snapshots WHERE external_snapshot_id=? OR content_hash=?",
                (external_id, item.content_hash),
            ).fetchone()
        if duplicate:
            destination = self._move_imported(item.path, root, duplicate["career_id"], suffix="duplicate") if move_after and root else None
            self._event("info", "duplicate_snapshot", f"Snapshot skipped: {external_id}", external_id)
            return ImportResult("duplicate", external_id, duplicate["career_id"], duplicate["id"], "Already imported.", destination)

        active_profile = Path(self.database.path).resolve() == active_workspace_database_path().resolve()
        if active_profile:
            decision = CareerIdentityGuard.inspect_snapshot(item.manifest["career"])
            if decision.state == "approval_required":
                return ImportResult("pending", external_id, None, None, decision.message, None)

        try:
            with self.database.transaction() as conn:
                career_id = self._resolve_career(conn, item)
                snapshot_db_id = self._insert_snapshot(conn, career_id, item)
                self._insert_import_files(conn, snapshot_db_id, item)
                self._insert_snapshot_metadata(conn, snapshot_db_id, item.path)
                entity_cache: dict[tuple[str, str], int] = {}
                self._import_core_files(conn, career_id, snapshot_db_id, item.path, entity_cache)
                self._import_optional_files(conn, career_id, snapshot_db_id, item.path, entity_cache)
                self._resequence(conn, career_id)
            if active_profile:
                CareerIdentityGuard.finalize_after_commit(item.manifest["career"])
            destination = self._move_imported(item.path, root, career_id) if move_after and root else None
            self._event("info", "snapshot_imported", f"Snapshot imported: {external_id}", external_id)
            return ImportResult("imported", external_id, career_id, snapshot_db_id, "Import successful.", destination)
        except sqlite3.OperationalError as exc:
            if self._is_transient_database_lock(exc):
                # A busy database is not evidence that the export is bad. Keep
                # the immutable package in ready/ and let the polling watcher
                # retry it. This also covers contention from a separate scan_now
                # process that cannot share the in-process write mutex.
                return ImportResult(
                    "retry", external_id, message="Atlas database is temporarily busy; import will retry automatically."
                )
            if move_after and root:
                return self._fail_folder(item.path, exc, root, external_id)
            raise
        except sqlite3.IntegrityError as exc:
            # The watcher and a manual scan can validate the same READY folder at
            # nearly the same time. If the other importer committed first, treat
            # the unique-key collision as the duplicate it is instead of moving a
            # perfectly valid snapshot into failed/.
            if "snapshots.content_hash" in str(exc) or "snapshots.external_snapshot_id" in str(exc):
                with self.database.connect() as conn:
                    duplicate = conn.execute(
                        "SELECT id, career_id FROM snapshots WHERE external_snapshot_id=? OR content_hash=?",
                        (external_id, item.content_hash),
                    ).fetchone()
                if duplicate:
                    destination = self._move_imported(item.path, root, duplicate["career_id"], suffix="duplicate") if move_after and root else None
                    self._event("info", "duplicate_snapshot", f"Snapshot skipped: {external_id}", external_id)
                    return ImportResult("duplicate", external_id, duplicate["career_id"], duplicate["id"], "Already imported.", destination)
            if move_after and root:
                return self._fail_folder(item.path, exc, root, external_id)
            raise
        except Exception as exc:
            if move_after and root:
                return self._fail_folder(item.path, exc, root, external_id)
            raise

    def _resolve_career(self, conn: sqlite3.Connection, item: ValidatedSnapshot) -> int:
        data = item.manifest["career"]
        fingerprint = str(data["fingerprintCandidate"])
        active_profile = Path(self.database.path).resolve() == active_workspace_database_path().resolve()
        existing = None
        if active_profile:
            rows = conn.execute("SELECT * FROM careers ORDER BY id LIMIT 2").fetchall()
            if len(rows) > 1:
                raise SnapshotValidationError("The career profile contains multiple careers and must be resolved before further imports.", code="career_profile_multiple_careers")
            existing = rows[0] if rows else None
        else:
            existing = conn.execute("SELECT * FROM careers WHERE fingerprint_candidate=?", (fingerprint,)).fetchone()
        manager = str(data.get("managerDisplayName") or "").strip()
        initial_team_id = as_int(data.get("initialTeamId"))
        initial_team_name = str(data.get("initialTeamName") or "").strip()
        now = utc_now()
        if existing:
            conflict: list[str] = []
            if existing["manager_name"] and manager and existing["manager_name"] != manager:
                conflict.append("Managername")
            if existing["initial_team_ea_id"] is not None and initial_team_id is not None and existing["initial_team_ea_id"] != initial_team_id:
                conflict.append("Startverein-ID")
            if conflict:
                raise SnapshotValidationError(
                    "Career fingerprint conflicts with existing identity data: " + ", ".join(conflict),
                    code="career_identity_collision",
                )
            conn.execute("UPDATE careers SET updated_at=? WHERE id=?", (now, existing["id"]))
            return int(existing["id"])
        display = manager or initial_team_name or f"Career {fingerprint}"
        public_id = str(uuid.uuid4())
        cursor = conn.execute(
            """INSERT INTO careers(public_id, fingerprint_candidate, display_name, manager_name,
               initial_team_ea_id, initial_team_name, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (public_id, fingerprint, display, manager or None, initial_team_id, initial_team_name or None, now, now),
        )
        return int(cursor.lastrowid)


    def _insert_snapshot(self, conn: sqlite3.Connection, career_id: int, item: ValidatedSnapshot) -> int:
        m = item.manifest
        c = m["career"]
        o = m["ordering"]
        cursor = conn.execute(
            """INSERT INTO snapshots(
              career_id, external_snapshot_id, schema_version, exporter_version, season_index,
              career_date, career_date_sort, managed_team_ea_id, managed_team_name,
              managed_completed_fixture_count, global_completed_fixture_count, exported_at_utc,
              content_hash, import_status, source_path, imported_at, warnings_json, capabilities_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                career_id, item.snapshot_id, str(m["schemaVersion"]), str(m.get("exporterVersion") or ""),
                as_int(o.get("seasonIndex")) or as_int(c.get("seasonIndex")) or 0,
                str(c.get("careerDate") or ""), as_int(o.get("careerDateSort")) or as_int(c.get("careerDateSort")) or 0,
                as_int(c.get("managedTeamId")), str(c.get("managedTeamName") or ""),
                as_int(o.get("managedCompletedFixtureCount")) or 0,
                as_int(o.get("globalCompletedFixtureCount")) or 0,
                str(o.get("exportedAtUtc") or m.get("exportedAtUtc") or ""), item.content_hash,
                "degraded" if item.warnings else "valid", str(item.path), utc_now(),
                compact_json(item.warnings), compact_json(m.get("capabilities") or {}),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_import_files(conn: sqlite3.Connection, snapshot_id: int, item: ValidatedSnapshot) -> None:
        values = []
        for entry in item.manifest.get("files", []):
            values.append((snapshot_id, entry.get("name"), as_int(entry.get("rowCount")), as_int(entry.get("byteSize")), entry.get("status"), entry.get("note")))
        conn.executemany("INSERT INTO import_files VALUES(?,?,?,?,?,?)", values)

    @staticmethod
    def _insert_snapshot_metadata(conn: sqlite3.Connection, snapshot_id: int, folder: Path) -> None:
        path = folder / "career_metadata.csv"
        values = []
        if path.exists():
            for row in read_csv_rows(path):
                key = str(row.get("key") or "").strip()
                if key:
                    values.append((snapshot_id, key, row.get("value")))
        if values:
            conn.executemany("INSERT INTO snapshot_metadata VALUES(?,?,?)", values)

    def _entity(self, conn: sqlite3.Connection, career_id: int, snapshot_id: int, entity_type: str, ea_id: Any, cache: dict[tuple[str, str], int]) -> int:
        key = (entity_type, str(ea_id))
        if key in cache:
            return cache[key]
        conn.execute(
            """INSERT INTO entities(career_id, entity_type, ea_id, first_seen_snapshot_id, last_seen_snapshot_id)
               VALUES(?,?,?,?,?) ON CONFLICT(career_id, entity_type, ea_id)
               DO UPDATE SET last_seen_snapshot_id=excluded.last_seen_snapshot_id""",
            (career_id, entity_type, str(ea_id), snapshot_id, snapshot_id),
        )
        row = conn.execute("SELECT id FROM entities WHERE career_id=? AND entity_type=? AND ea_id=?", (career_id, entity_type, str(ea_id))).fetchone()
        entity_id = int(row["id"])
        cache[key] = entity_id
        return entity_id

    def _import_core_files(self, conn: sqlite3.Connection, career_id: int, snapshot_id: int, folder: Path, cache: dict[tuple[str, str], int]) -> None:
        teams = []
        for r in read_csv_rows(folder / "teams.csv"):
            team_id = as_int(r.get("team_id"))
            if team_id is None:
                continue
            entity = self._entity(conn, career_id, snapshot_id, "team", team_id, cache)
            teams.append((
                snapshot_id, entity, team_id, r.get("team_name") or "",
                as_int(r.get("league_id")), r.get("league_name"), as_int(r.get("overall")),
                as_int(r.get("attack")), as_int(r.get("midfield")), as_int(r.get("defence")),
                as_int(r.get("domestic_prestige")), as_int(r.get("international_prestige")),
                as_int(r.get("profitability")), as_int(r.get("gender")),
                as_int(r.get("club_worth")), as_int(r.get("stadium_capacity")), compact_json(r),
            ))
        conn.executemany(
            """INSERT INTO team_states(
                   snapshot_id,entity_id,ea_team_id,team_name,league_ea_id,league_name,overall,attack,
                   midfield,defence,domestic_prestige,international_prestige,profitability,gender,
                   club_worth,stadium_capacity,raw_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            teams,
        )

        players = []
        for r in read_csv_rows(folder / "players.csv"):
            player_id = as_int(r.get("player_id"))
            name = (r.get("display_name") or "").strip()
            if player_id is None or not name:
                raise SnapshotValidationError("Player without a valid ID or name in players.csv", code="invalid_player")
            entity = self._entity(conn, career_id, snapshot_id, "player", player_id, cache)
            players.append((snapshot_id, entity, player_id, name, as_int(r.get("team_id")), r.get("team_name"), as_int(r.get("overall")), as_int(r.get("potential")), r.get("primary_position"), as_int(r.get("nationality_id")), r.get("contract_valid_until"), as_int(r.get("height")), as_int(r.get("weight")), as_int(r.get("preferred_foot_id")), compact_json(r)))
        conn.executemany("INSERT INTO player_states VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", players)

        rosters = []
        for r in read_csv_rows(folder / "rosters.csv"):
            player_id, team_id = as_int(r.get("player_id")), as_int(r.get("team_id"))
            if player_id is None or team_id is None:
                continue
            pe = self._entity(conn, career_id, snapshot_id, "player", player_id, cache)
            te = self._entity(conn, career_id, snapshot_id, "team", team_id, cache)
            rosters.append((snapshot_id, pe, te, player_id, team_id, as_int(r.get("jersey_number")), as_int(r.get("teamsheet_slot_raw")), r.get("teamsheet_slot_label"), r.get("primary_position"), as_int(r.get("form")), as_int(r.get("injury")), compact_json(r)))
        conn.executemany("INSERT INTO roster_states VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rosters)

    def _import_optional_files(self, conn: sqlite3.Connection, career_id: int, snapshot_id: int, folder: Path, cache: dict[tuple[str, str], int]) -> None:
        self._import_leagues(conn, career_id, snapshot_id, folder, cache)
        self._import_competitions(conn, career_id, snapshot_id, folder, cache)
        self._import_team_leagues(conn, snapshot_id, folder)
        self._import_season_stats(conn, snapshot_id, folder)
        self._import_fixtures(conn, career_id, snapshot_id, folder)
        self._import_match_performances(conn, snapshot_id, folder)
        self._import_contracts(conn, snapshot_id, folder)
        self._import_loans(conn, snapshot_id, folder)
        self._import_youth(conn, snapshot_id, folder)
        self._import_growth(conn, snapshot_id, folder)
        self._import_competition_progress(conn, snapshot_id, folder)
        known = {"career_metadata.csv", "players.csv", "teams.csv", "rosters.csv", "leagues.csv", "competitions.csv", "team_leagues.csv", "season_stats.csv", "fixtures.csv", "managed_team_match_players.csv", "contracts.csv", "loans.csv", "youth_players.csv", "player_growth.csv", "competition_progress.csv", "unresolved_player_names.csv", "manifest.csv"}
        for path in folder.glob("*.csv"):
            if path.name in known:
                continue
            rows = []
            for index, r in enumerate(read_csv_rows(path), start=1):
                key = r.get("artificial_key") or r.get("fixture_key") or r.get("player_id") or str(index)
                rows.append((snapshot_id, path.name, str(key), compact_json(r)))
            if rows:
                conn.executemany("INSERT OR IGNORE INTO generic_snapshot_rows VALUES(?,?,?,?)", rows)

    def _import_leagues(self, conn, career_id, snapshot_id, folder, cache):
        path = folder / "leagues.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            eid=as_int(r.get("league_id")); name=r.get("league_name") or ""
            if eid is None: continue
            entity=self._entity(conn,career_id,snapshot_id,"league",eid,cache)
            values.append((snapshot_id,entity,eid,name,as_int(r.get("country_id")),as_int(r.get("level")),compact_json(r)))
        conn.executemany("INSERT INTO league_states VALUES(?,?,?,?,?,?,?)",values)

    def _import_competitions(self, conn, career_id, snapshot_id, folder, cache):
        path=folder/"competitions.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            eid=as_int(r.get("competition_object_id")); name=r.get("competition_name") or ""
            if eid is None: continue
            entity=self._entity(conn,career_id,snapshot_id,"competition",eid,cache)
            values.append((snapshot_id,entity,eid,as_int(r.get("competition_id")),name,compact_json(r)))
        conn.executemany(
            """INSERT INTO competition_states(
                   snapshot_id,entity_id,competition_object_id,static_competition_id,competition_name,raw_json
               ) VALUES(?,?,?,?,?,?)""",
            values,
        )

    def _import_team_leagues(self, conn, snapshot_id, folder):
        path=folder/"team_leagues.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            team=as_int(r.get("team_id"))
            if team is None: continue
            values.append((
                snapshot_id, team, as_int(r.get("league_id")), as_int(r.get("previous_league_id")),
                as_int(r.get("current_table_position")), as_int(r.get("points")), as_int(r.get("matches_played")),
                as_int(r.get("home_wins")), as_int(r.get("home_draws")), as_int(r.get("home_losses")),
                as_int(r.get("away_wins")), as_int(r.get("away_draws")), as_int(r.get("away_losses")),
                as_int(r.get("home_goals_for")), as_int(r.get("home_goals_against")),
                as_int(r.get("away_goals_for")), as_int(r.get("away_goals_against")),
                as_int(r.get("champion")), compact_json(r),
            ))
        conn.executemany(
            """INSERT INTO team_league_states(
                   snapshot_id,team_ea_id,league_ea_id,previous_league_ea_id,current_table_position,points,matches_played,
                   home_wins,home_draws,home_losses,away_wins,away_draws,away_losses,
                   home_goals_for,home_goals_against,away_goals_for,away_goals_against,champion,raw_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )

    def _import_season_stats(self, conn, snapshot_id, folder):
        path=folder/"season_stats.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            p,t,c=as_int(r.get("player_id")),as_int(r.get("represented_team_id")),as_int(r.get("competition_object_id"))
            if None in (p,t,c): continue
            values.append((snapshot_id,p,t,as_int(r.get("current_club_id")),c,as_int(r.get("appearances")),as_float(r.get("average_rating")),as_int(r.get("man_of_the_match")),as_int(r.get("goals")),as_int(r.get("assists")),as_int(r.get("yellow_cards")),as_int(r.get("second_yellow_cards")),as_int(r.get("red_cards")),as_int(r.get("saves")),as_int(r.get("goals_conceded")),as_int(r.get("clean_sheets")),r.get("display_name"),r.get("represented_team_name"),r.get("competition_name"),compact_json(r)))
        conn.executemany(
            "INSERT INTO season_stat_states(snapshot_id,player_ea_id,represented_team_ea_id,current_club_ea_id,competition_object_id,appearances,average_rating,man_of_the_match,goals,assists,yellow_cards,second_yellow_cards,red_cards,saves,goals_conceded,clean_sheets,display_name,represented_team_name,competition_name,raw_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )

    def _import_fixtures(self, conn, career_id, snapshot_id, folder):
        path=folder/"fixtures.csv"
        if not path.exists(): return
        observations=[]
        for r in read_csv_rows(path):
            key=r.get("fixture_key")
            if not key: continue
            conn.execute(
                """INSERT INTO fixtures(
                       career_id,fixture_key,competition_object_id,static_competition_id,stadium_ea_id,
                       home_team_ea_id,away_team_ea_id
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(career_id,fixture_key) DO UPDATE SET
                       competition_object_id=COALESCE(excluded.competition_object_id,fixtures.competition_object_id),
                       static_competition_id=COALESCE(excluded.static_competition_id,fixtures.static_competition_id),
                       stadium_ea_id=COALESCE(excluded.stadium_ea_id,fixtures.stadium_ea_id),
                       home_team_ea_id=COALESCE(excluded.home_team_ea_id,fixtures.home_team_ea_id),
                       away_team_ea_id=COALESCE(excluded.away_team_ea_id,fixtures.away_team_ea_id)""",
                (
                    career_id,key,as_int(r.get("competition_object_id")),as_int(r.get("competition_id")),
                    as_int(r.get("stadium_id")),as_int(r.get("home_team_id")),as_int(r.get("away_team_id")),
                ),
            )
            fixture_id=conn.execute("SELECT id FROM fixtures WHERE career_id=? AND fixture_key=?",(career_id,key)).fetchone()["id"]
            observations.append((snapshot_id,fixture_id,key,r.get("competition_name"),r.get("home_team_name"),r.get("away_team_name"),r.get("date"),r.get("time"),as_int(r.get("is_completed")),as_int(r.get("home_score")),as_int(r.get("away_score")),as_int(r.get("home_penalties")),as_int(r.get("away_penalties")),as_int(r.get("managed_team_involved")),r.get("managed_team_result"),compact_json(r)))
        conn.executemany("INSERT INTO fixture_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",observations)

    def _import_match_performances(self, conn, snapshot_id, folder):
        path=folder/"managed_team_match_players.csv"
        if not path.exists(): return
        values=[]
        for i,r in enumerate(read_csv_rows(path),start=1):
            player=as_int(r.get("player_id"))
            if player is None: continue
            key=r.get("rating_artificial_key") or f"{player}:{r.get('date_raw')}:{i}"
            actual_position = r.get("actual_position") or r.get("rating_position_hint")
            actual_position_source = r.get("actual_position_source") or ("career_playermatchratinghistory_position" if r.get("rating_position_hint") else None)
            values.append((snapshot_id,key,r.get("fixture_key") if r.get("join_status")=="joined_by_date" else None,r.get("join_status"),player,r.get("display_name"),r.get("date"),as_float(r.get("rating")),as_int(r.get("minutes_played")),as_int(r.get("rating_position_raw")),actual_position,actual_position_source,compact_json(r)))
        conn.executemany("INSERT INTO player_match_performances VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",values)

    def _import_contracts(self, conn, snapshot_id, folder):
        path=folder/"contracts.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            p=as_int(r.get("player_id"))
            if p is None: continue
            values.append((snapshot_id,p,as_int(r.get("team_id")),as_int(r.get("wage")),as_int(r.get("duration_months")),as_int(r.get("contract_status")),compact_json(r)))
        conn.executemany("INSERT INTO contract_states VALUES(?,?,?,?,?,?,?)",values)

    def _import_loans(self, conn, snapshot_id, folder):
        path=folder/"loans.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            p,a,b=as_int(r.get("player_id")),as_int(r.get("parent_team_id")),as_int(r.get("loan_team_id"))
            if None in (p,a,b): continue
            values.append((snapshot_id,p,a,b,r.get("loan_end_date"),as_int(r.get("is_loan_to_buy")),compact_json(r)))
        conn.executemany("INSERT INTO loan_states VALUES(?,?,?,?,?,?,?)",values)

    def _import_youth(self, conn, snapshot_id, folder):
        path=folder/"youth_players.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            p=as_int(r.get("player_id")); name=r.get("display_name") or ""
            if p is None or not name: continue
            values.append((snapshot_id,p,name,as_int(r.get("overall")),as_int(r.get("potential")),r.get("primary_position"),compact_json(r)))
        conn.executemany("INSERT INTO youth_player_states VALUES(?,?,?,?,?,?,?)",values)

    def _import_growth(self, conn, snapshot_id, folder):
        path=folder/"player_growth.csv"
        if not path.exists(): return
        values=[]
        for r in read_csv_rows(path):
            p=as_int(r.get("player_id"))
            if p is None: continue
            values.append((snapshot_id,p,r.get("display_name"),as_int(r.get("overall")),compact_json(r)))
        conn.executemany("INSERT INTO player_growth_states VALUES(?,?,?,?,?)",values)

    def _import_competition_progress(self, conn, snapshot_id, folder):
        path=folder/"competition_progress.csv"
        if not path.exists(): return
        values=[]
        for i,r in enumerate(read_csv_rows(path),start=1):
            key=r.get("artificial_key") or str(i)
            values.append((snapshot_id,key,as_int(r.get("team_id")),as_int(r.get("season")),as_int(r.get("competition_object_id")),as_int(r.get("stage_id")),as_int(r.get("has_team_won")),compact_json(r)))
        conn.executemany("INSERT INTO competition_progress_states VALUES(?,?,?,?,?,?,?,?)",values)

    @staticmethod
    def _resequence(conn: sqlite3.Connection, career_id: int) -> None:
        rows=conn.execute("""SELECT id,season_index,career_date_sort,managed_completed_fixture_count,
          global_completed_fixture_count,exported_at_utc,external_snapshot_id FROM snapshots
          WHERE career_id=? ORDER BY season_index,career_date_sort,managed_completed_fixture_count,
          global_completed_fixture_count,exported_at_utc,external_snapshot_id""",(career_id,)).fetchall()
        same_day: dict[tuple[int,int],int]={}
        for seq,row in enumerate(rows, start=1):
            key=(row["season_index"],row["career_date_sort"])
            same_day[key]=same_day.get(key,0)+1
            conn.execute("UPDATE snapshots SET import_sequence=?,same_day_sequence=? WHERE id=?",(seq,same_day[key],row["id"]))
        SnapshotImporter._rebuild_entity_lifetimes(conn, career_id)

    @staticmethod
    def _rebuild_entity_lifetimes(conn: sqlite3.Connection, career_id: int) -> None:
        """Keep entity first/last-seen pointers aligned with snapshot chronology.

        Snapshots can legitimately be imported out of wall-clock order (for
        example when recovering an older save). Resequencing changes their
        chronological order, so entity lifetimes must be derived from retained
        state rows rather than wall-clock import order.

        IMPORTANT: do this in one ordered scan per entity type. The previous
        implementation issued one history query per entity, which became
        effectively quadratic on real full-career databases and could leave the
        hot-folder importer looking stuck for many minutes.
        """
        state_tables = {
            "player": "player_states",
            "team": "team_states",
            "league": "league_states",
            "competition": "competition_states",
        }
        for entity_type, table in state_tables.items():
            entity_rows = conn.execute(
                "SELECT id FROM entities WHERE career_id=? AND entity_type=? ORDER BY id",
                (career_id, entity_type),
            ).fetchall()
            if not entity_rows:
                continue
            entity_ids = {int(row[0]) for row in entity_rows}

            first_last: dict[int, list[int]] = {}
            cursor = conn.execute(
                f"""SELECT st.entity_id, st.snapshot_id
                       FROM {table} st
                       JOIN snapshots s ON s.id=st.snapshot_id
                       JOIN entities e ON e.id=st.entity_id
                       WHERE e.career_id=? AND e.entity_type=?
                       ORDER BY st.entity_id, s.import_sequence, s.id""",
                (career_id, entity_type),
            )
            for entity_id_raw, snapshot_id_raw in cursor:
                entity_id = int(entity_id_raw)
                snapshot_id = int(snapshot_id_raw)
                pair = first_last.get(entity_id)
                if pair is None:
                    first_last[entity_id] = [snapshot_id, snapshot_id]
                else:
                    pair[1] = snapshot_id

            if first_last:
                conn.executemany(
                    "UPDATE entities SET first_seen_snapshot_id=?,last_seen_snapshot_id=? WHERE id=?",
                    [(pair[0], pair[1], entity_id) for entity_id, pair in first_last.items()],
                )

            # If an entity has no retained state rows at all, it cannot belong to
            # this career history. This mostly matters after out-of-order imports
            # and keeps the same invariant as the hard-reset implementation.
            missing = [(entity_id,) for entity_id in entity_ids.difference(first_last)]
            if missing:
                conn.executemany("DELETE FROM entities WHERE id=?", missing)

    def _move_imported(self, folder: Path, root: Path | None, career_id: int, suffix: str | None = None) -> str | None:
        if root is None or not folder.exists(): return None
        destination_dir=root/"imported"/str(career_id)
        destination_dir.mkdir(parents=True,exist_ok=True)
        name=folder.name+(f"_{suffix}" if suffix else "")
        destination=destination_dir/name
        counter=1
        while destination.exists():
            destination=destination_dir/f"{name}_{counter}"
            counter+=1
        shutil.move(str(folder),str(destination))
        return str(destination)

    def _fail_folder(self, folder: Path, exc: Exception, root: Path, snapshot_id: str | None = None) -> ImportResult:
        code=getattr(exc,"code","import_error")
        details=getattr(exc,"details",{})
        failed_dir=root/"failed"
        failed_dir.mkdir(parents=True,exist_ok=True)
        destination=failed_dir/folder.name
        counter=1
        while destination.exists():
            destination=failed_dir/f"{folder.name}_{counter}"; counter+=1
        if folder.exists(): shutil.move(str(folder),str(destination))
        payload={"occurredAt":utc_now(),"code":code,"message":str(exc),"details":details,"source":str(folder)}
        destination.mkdir(parents=True,exist_ok=True)
        (destination/"import_error.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        self._event("error",code,str(exc),snapshot_id,details)
        return ImportResult("failed",snapshot_id or folder.name,message=str(exc),destination=str(destination))

    def _event(self, level: str, code: str, message: str, snapshot_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO import_events(occurred_at,level,code,message,snapshot_external_id,details_json) VALUES(?,?,?,?,?,?)",
                (utc_now(),level,code,message,snapshot_id,compact_json(details or {})),
            )
