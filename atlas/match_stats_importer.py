from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import Database
from .paths import read_snapshot_root, database_path as active_workspace_database_path
from .career_identity import CareerIdentityGuard

PARTICIPANTS_FILE = "16_match_participants_wide.csv"
TEAMS_FILE = "18_match_teams_wide.csv"
SUMMARY_FILE = "20_match_export_summary.csv"
READY_MARKERS = {"READY_FOR_MANUAL_ZIP_AND_UPLOAD.txt", "MATCH_READY", "READY_MATCH_STATS", "READY"}
EXPORT_PREFIXES = ("FC26_MatchStatsExport_", "matchstats_", "FC26_MatchStats_")

# Only participant-complete exports are safe to persist. Do not use substring
# checks here: "incomplete_participant_export" contains the word "complete".
COMPLETE_EXPORT_STATUSES = {
    "complete_participant_export",
    "participant_export_complete_with_unresolved_nonparticipant",
}


@dataclass(frozen=True)
class MatchStatsImportResult:
    status: str
    source: str
    export_id: int | None = None
    fixture_id: int | None = None
    message: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    low = text.casefold()
    if low in {"true", "yes"}:
        return True
    if low in {"false", "no"}:
        return False
    try:
        if any(ch in text for ch in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _rows(raw: bytes) -> list[dict[str, Any]]:
    # FC exports may contain a UTF-8 BOM.
    text = raw.decode("utf-8-sig", errors="strict")
    return [{str(k): _coerce(v) for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


_VOLATILE_SEMANTIC_FIELDS = {
    "snapshot_id", "tracker_capture_id", "pipeline_capture_id", "post_match_capture_id",
    "trigger", "exported_at", "exported_at_utc", "source_path", "status", "export_status",
}


def _semantic_hash(participants: list[dict[str, Any]], teams: list[dict[str, Any]]) -> str:
    def stable(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in sorted(row.items()) if key not in _VOLATILE_SEMANTIC_FIELDS}
    payload = {
        "participants": sorted((stable(row) for row in participants), key=lambda row: (int(row.get("team_index") or 0), int(row.get("player_id") or 0))),
        "teams": sorted((stable(row) for row in teams), key=lambda row: int(row.get("team_index") or 0)),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_export(
    participants: list[dict[str, Any]], teams: list[dict[str, Any]], summary_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(summary_rows) != 1:
        raise ValueError(f"The export requires exactly one summary row; found {len(summary_rows)}.")
    summary = summary_rows[0]
    status = str(summary.get("status") or summary.get("export_status") or "").strip()
    if status.casefold() not in COMPLETE_EXPORT_STATUSES:
        raise ValueError(f"The match-stat export does not report a complete participant export: {status or 'missing'}")
    if len(participants) < 14:
        raise ValueError(f"Too few participant rows for a reliable match: {len(participants)}.")
    team_indexes = [int(row.get("team_index") if row.get("team_index") is not None else -1) for row in teams]
    if sorted(team_indexes) != [0, 1]:
        raise ValueError("The team export must contain exactly one row for team_index 0 and 1.")
    seen: set[tuple[int, int]] = set()
    counts = {0: 0, 1: 0}
    for row_number, row in enumerate(participants, start=2):
        player_id = int(row.get("player_id") or 0)
        team_index = int(row.get("team_index") if row.get("team_index") is not None else -1)
        if player_id <= 0 or team_index not in (0, 1):
            raise ValueError(f"Invalid player ID or team_index in participant row {row_number}.")
        key = (player_id, team_index)
        if key in seen:
            raise ValueError(f"Duplicate participant row for player {player_id}, team {team_index}.")
        seen.add(key); counts[team_index] += 1
        minutes = row.get("minutes_played")
        rating = row.get("game_rating")
        if minutes is not None and not 0 <= float(minutes) <= 130:
            raise ValueError(f"Invalid minutes played for player {player_id}: {minutes}.")
        if rating is not None and not 0 <= float(rating) <= 10:
            raise ValueError(f"Invalid match rating for player {player_id}: {rating}.")
        for field, value in row.items():
            if value is None or field in _VOLATILE_SEMANTIC_FIELDS or field in {"array_index", "selector_signed", "player_id", "team_index", "game_rating"}:
                continue
            if isinstance(value, (int, float)) and value < 0:
                raise ValueError(f"Negative statistic {field}={value} for player {player_id}.")
    if min(counts.values()) < 7:
        raise ValueError(f"Both teams require at least seven participant rows; found {counts}.")
    expected_participants = summary.get("participants")
    expected_teams = summary.get("teams")
    if expected_participants is not None and int(expected_participants) != len(participants):
        raise ValueError("Summary participant count does not match the CSV content.")
    if expected_teams is not None and int(expected_teams) != len(teams):
        raise ValueError("Summary team count does not match the CSV content.")
    exporter_version = str(summary.get("exporter_version") or summary.get("version") or "")
    if exporter_version and not (exporter_version.startswith("0.41") or exporter_version.startswith("1.0") or exporter_version.startswith("1.1")):
        raise ValueError(f"Unsupported MatchStats exporter version: {exporter_version}.")
    return summary, {
        "model": "atlas-matchstats-validation-v2", "valid": True, "status": status,
        "participants": len(participants), "teams": len(teams), "participantsByTeam": counts,
        "exporterVersion": exporter_version or None,
    }


class MatchStatsImporter:
    """Imports the validated FC26 v0.41 match-stat surface and links it conservatively to Atlas fixtures."""

    def __init__(self, database: Database):
        self.database = database
        self.last_scan_at: str | None = None
        self.last_results: list[MatchStatsImportResult] = []
        self.last_linked_matches: list[dict[str, int]] = []

    def _desktop(self) -> Path | None:
        profile = os.environ.get("USERPROFILE")
        if not profile:
            return None
        desktop = Path(profile) / "Desktop"
        return desktop if desktop.is_dir() else None

    def roots(self) -> list[Path]:
        roots: list[Path] = []
        snapshot_root = read_snapshot_root()
        if snapshot_root:
            if snapshot_root.name.casefold() == "snapshots":
                roots.append(snapshot_root.parent / "MatchStats" / "ready")
            else:
                roots.append(snapshot_root / "MatchStats" / "ready")
                roots.append(snapshot_root / "match_stats" / "ready")
        else:
            # Desktop discovery is only a compatibility fallback when Atlas has no
            # configured workspace root. Scanning it in parallel would let files from
            # another Atlas workspace leak into the active save.
            desktop = self._desktop()
            if desktop:
                roots.append(desktop)
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key not in seen:
                seen.add(key); unique.append(root)
        return unique

    @staticmethod
    def _looks_like_export(path: Path) -> bool:
        if not path.name.startswith(EXPORT_PREFIXES):
            return False
        if path.is_dir():
            return (path / PARTICIPANTS_FILE).is_file() and (path / TEAMS_FILE).is_file() and (path / SUMMARY_FILE).is_file() and any((path / marker).exists() for marker in READY_MARKERS)
        if path.is_file() and path.suffix.casefold() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    names = [Path(name).name for name in zf.namelist()]
                return all(name in names for name in (PARTICIPANTS_FILE, TEAMS_FILE, SUMMARY_FILE)) and any(marker in names for marker in READY_MARKERS)
            except (OSError, zipfile.BadZipFile):
                return False
        return False

    @staticmethod
    def _unique_destination(path: Path) -> Path:
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        for index in range(1, 10000):
            candidate = path.with_name(f"{stem}_{index}{suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"Could not allocate a unique destination for {path.name}.")

    def _archive_ready_artifact(self, path: Path, bucket: str) -> None:
        # MatchStats packages are immutable once MATCH_READY exists. Move a consumed
        # package out of ready so users can see that Atlas has actually processed it
        # and so the watcher does not re-validate the same directory every 3 seconds.
        if path.parent.name.casefold() != "ready":
            return
        destination_root = path.parent.parent / bucket
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = self._unique_destination(destination_root / path.name)
        try:
            path.replace(destination)
        except OSError:
            # Import state is authoritative; an antivirus/indexer lock must not turn a
            # successful database import into a failure. The next scan can retry move.
            return

    def scan_once(self) -> list[MatchStatsImportResult]:
        results: list[MatchStatsImportResult] = []
        with self.database.connect() as conn:
            previously_linked = {int(row[0]) for row in conn.execute(
                "SELECT id FROM match_stat_exports WHERE fixture_id IS NOT NULL AND linkage_status='linked'").fetchall()}
        for root in self.roots():
            if not root.exists():
                continue
            if root.name == "ready":
                root.mkdir(parents=True, exist_ok=True)
            for path in sorted(root.iterdir(), key=lambda p: p.name):
                if self._looks_like_export(path):
                    try:
                        result = self.import_export(path)
                        results.append(result)
                        if result.status in {"imported", "duplicate", "duplicate_semantic"}:
                            self._archive_ready_artifact(path, "imported")
                    except Exception as exc:  # preserve snapshot watcher even for a malformed match export
                        self._record_error(path, exc)
                        results.append(MatchStatsImportResult("failed", str(path), message=str(exc)))
                        self._archive_ready_artifact(path, "failed")
        self.reconcile_pending()
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT id,career_id,fixture_id,snapshot_id FROM match_stat_exports
                     WHERE fixture_id IS NOT NULL AND linkage_status='linked' AND superseded_by_export_id IS NULL
                     ORDER BY id"""
            ).fetchall()
        self.last_linked_matches = [
            {"career_id": int(row["career_id"]), "fixture_id": int(row["fixture_id"]),
             "snapshot_id": int(row["snapshot_id"])}
            for row in rows if int(row["id"]) not in previously_linked and row["career_id"] is not None
        ]
        self.last_scan_at = _now()
        self.last_results = results
        return results

    def _read_files(self, path: Path) -> dict[str, bytes]:
        required = (PARTICIPANTS_FILE, TEAMS_FILE, SUMMARY_FILE)
        if path.is_dir():
            return {name: (path / name).read_bytes() for name in required}
        with zipfile.ZipFile(path) as zf:
            by_base = {Path(name).name: name for name in zf.namelist()}
            return {name: zf.read(by_base[name]) for name in required}

    def import_export(self, path: Path) -> MatchStatsImportResult:
        files = self._read_files(path)
        digest = hashlib.sha256()
        for name in sorted(files):
            digest.update(name.encode()); digest.update(b"\0"); digest.update(files[name])
        content_hash = digest.hexdigest()
        with self.database.connect() as conn:
            existing = conn.execute("SELECT id,fixture_id FROM match_stat_exports WHERE content_hash=?", (content_hash,)).fetchone()
        if existing:
            return MatchStatsImportResult("duplicate", str(path), int(existing["id"]), int(existing["fixture_id"]) if existing["fixture_id"] is not None else None)

        participants = _rows(files[PARTICIPANTS_FILE])
        teams = _rows(files[TEAMS_FILE])
        summary_rows = _rows(files[SUMMARY_FILE])
        summary, validation = _validate_export(participants, teams, summary_rows)
        active_profile = Path(self.database.path).resolve() == active_workspace_database_path().resolve()
        artifact_fingerprint = str(summary.get("career_fingerprint_candidate") or "").strip()
        if active_profile and artifact_fingerprint:
            validation["careerIdentity"] = CareerIdentityGuard.validate_artifact_fingerprint(artifact_fingerprint, artifact="MatchStats")
        elif active_profile:
            validation["careerIdentity"] = "legacy_missing_fingerprint"
        semantic_hash = _semantic_hash(participants, teams)
        status = str(summary.get("status") or summary.get("export_status"))
        with self.database.connect() as conn:
            semantic = conn.execute(
                "SELECT id,fixture_id FROM match_stat_exports WHERE semantic_hash=? ORDER BY id DESC LIMIT 1", (semantic_hash,),
            ).fetchone()
        if semantic:
            return MatchStatsImportResult(
                "duplicate_semantic", str(path), int(semantic["id"]),
                int(semantic["fixture_id"]) if semantic["fixture_id"] is not None else None,
                "Inhaltlich identischer Export; volatile Capture-Metadaten wurden ignoriert.",
            )

        external_id = path.stem
        trigger = next((str(row.get("trigger")) for row in participants if row.get("trigger")), None)
        pipeline_capture_id = str(summary.get("pipeline_capture_id") or summary.get("post_match_capture_id") or "").strip() or None
        with self.database.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO match_stat_exports(
                       external_export_id,content_hash,source_path,export_status,linkage_status,
                       participant_rows,team_rows,trigger,pipeline_capture_id,semantic_hash,validation_json,imported_at,raw_summary_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (external_id, content_hash, str(path), status, "pending", len(participants), len(teams), trigger,
                 pipeline_capture_id, semantic_hash, json.dumps(validation, ensure_ascii=False), _now(), json.dumps(summary, ensure_ascii=False)),
            )
            export_id = int(cur.lastrowid)
            for row in participants:
                player_id = int(row.get("player_id") or 0)
                team_index = int(row.get("team_index") or 0)
                if player_id <= 0 or team_index not in (0, 1):
                    continue
                conn.execute(
                    """INSERT INTO match_player_detailed_stats(
                           export_id,player_ea_id,team_index,minutes_played,game_rating,man_of_the_match,
                           npk_expected_goals,expected_assists,stats_json
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (export_id, player_id, team_index, row.get("minutes_played"), row.get("game_rating"), 1 if row.get("man_of_the_match") else 0,
                     row.get("npk_expected_goals"), row.get("expected_assists"), json.dumps(row, ensure_ascii=False)),
                )
            for row in teams:
                team_index = int(row.get("team_index") or 0)
                if team_index not in (0, 1):
                    continue
                conn.execute(
                    "INSERT INTO match_team_detailed_stats(export_id,team_index,stats_json) VALUES(?,?,?)",
                    (export_id, team_index, json.dumps(row, ensure_ascii=False)),
                )
        if not self._link_by_pipeline_capture(export_id):
            self.reconcile_export(export_id)
        with self.database.connect() as conn:
            linked = conn.execute("SELECT fixture_id,linkage_status FROM match_stat_exports WHERE id=?", (export_id,)).fetchone()
        return MatchStatsImportResult("imported", str(path), export_id, int(linked["fixture_id"]) if linked and linked["fixture_id"] is not None else None, str(linked["linkage_status"]) if linked else None)

    def _record_error(self, path: Path, exc: Exception) -> None:
        try:
            with self.database.transaction() as conn:
                conn.execute(
                    "INSERT INTO import_events(occurred_at,level,code,message,details_json) VALUES(?,?,?,?,?)",
                    (_now(), "error", "match_stats_import_failed", f"FC26 detailed match statistics could not be imported: {exc}", json.dumps({"path": str(path), "error": str(exc)}, ensure_ascii=False)),
                )
        except Exception:
            pass

    @staticmethod
    def _stats(row: sqlite3.Row | None) -> dict[str, Any]:
        if not row:
            return {}
        try:
            return json.loads(str(row["stats_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _activate_fixture_export(
        conn: sqlite3.Connection, export_id: int, *, career_id: int, fixture_id: int, snapshot_id: int,
        confidence: float, mapping: dict[int, int], method: str,
    ) -> None:
        # A changed re-export is a revision of the fixture, never a second match.
        conn.execute(
            "UPDATE match_stat_exports SET superseded_by_export_id=? WHERE fixture_id=? AND id<>? AND superseded_by_export_id IS NULL",
            (export_id, fixture_id, export_id),
        )
        conn.execute(
            """UPDATE match_stat_exports SET career_id=?,fixture_id=?,snapshot_id=?,linkage_status='linked',
                   linkage_confidence=?,team0_ea_id=?,team1_ea_id=?,linkage_method=?,superseded_by_export_id=NULL
               WHERE id=?""",
            (career_id, fixture_id, snapshot_id, round(min(1.0, confidence), 4), mapping.get(0), mapping.get(1), method, export_id),
        )
        for idx, team_id in mapping.items():
            conn.execute(
                "UPDATE match_team_detailed_stats SET team_ea_id=? WHERE export_id=? AND team_index=?",
                (team_id, export_id, idx),
            )

    def _link_by_pipeline_capture(self, export_id: int) -> bool:
        """Prefer the unified post-match capture token over heuristic fixture matching.

        AutoCapture v1.6+ writes the same opaque capture ID into the completed
        MatchStats package and the immediately following full snapshot.  The token
        never identifies a career or fixture by itself; it only joins two artifacts
        created by the same local pipeline.  The new completed managed fixture is
        still validated from immutable snapshot observations before linking.
        """
        with self.database.connect() as conn:
            export = conn.execute(
                "SELECT pipeline_capture_id,fixture_id FROM match_stat_exports WHERE id=?", (export_id,)
            ).fetchone()
            if not export or export["fixture_id"] is not None:
                return bool(export and export["fixture_id"] is not None)
            token = str(export["pipeline_capture_id"] or "").strip()
            if not token:
                return False
            snapshots = conn.execute(
                """SELECT s.id,s.career_id,s.import_sequence,s.managed_team_ea_id
                   FROM snapshot_metadata sm JOIN snapshots s ON s.id=sm.snapshot_id
                   WHERE sm.key='post_match_capture_id' AND sm.value=?
                   ORDER BY s.import_sequence DESC""",
                (token,),
            ).fetchall()
            if len(snapshots) != 1:
                return False
            snap = snapshots[0]
            previous = conn.execute(
                "SELECT id FROM snapshots WHERE career_id=? AND import_sequence<? ORDER BY import_sequence DESC LIMIT 1",
                (snap["career_id"], snap["import_sequence"]),
            ).fetchone()
            if not previous:
                return False
            fixtures = conn.execute(
                """SELECT f.id fixture_id,f.home_team_ea_id,f.away_team_ea_id,fo.home_score,fo.away_score
                   FROM fixture_observations fo JOIN fixtures f ON f.id=fo.fixture_id
                   WHERE fo.snapshot_id=? AND fo.is_completed=1 AND fo.managed_team_involved=1
                     AND NOT EXISTS(
                         SELECT 1 FROM fixture_observations old
                         WHERE old.snapshot_id=? AND old.fixture_id=fo.fixture_id AND old.is_completed=1
                     )""",
                (snap["id"], previous["id"]),
            ).fetchall()
            if len(fixtures) != 1:
                return False
            fixture = fixtures[0]
            detailed = conn.execute(
                "SELECT player_ea_id,team_index FROM match_player_detailed_stats WHERE export_id=?",
                (export_id,),
            ).fetchall()
            team_rows = conn.execute(
                "SELECT team_index,stats_json FROM match_team_detailed_stats WHERE export_id=? ORDER BY team_index",
                (export_id,),
            ).fetchall()
            participant_ids = {int(row["player_ea_id"]) for row in detailed}
            if not participant_ids:
                return False
            home = int(fixture["home_team_ea_id"]) if fixture["home_team_ea_id"] is not None else None
            away = int(fixture["away_team_ea_id"]) if fixture["away_team_ea_id"] is not None else None
            mapping: dict[int, int] = {}
            memberships = conn.execute(
                "SELECT ea_player_id,team_ea_id FROM player_states WHERE snapshot_id=? AND ea_player_id IN (%s)" % ",".join("?" * len(participant_ids)),
                (snap["id"], *sorted(participant_ids)),
            ).fetchall()
            by_player = {
                int(row["ea_player_id"]): int(row["team_ea_id"]) if row["team_ea_id"] is not None else None
                for row in memberships
            }
            for idx in (0, 1):
                ids = [int(row["player_ea_id"]) for row in detailed if int(row["team_index"]) == idx]
                counts = {team: sum(by_player.get(pid) == team for pid in ids) for team in (home, away) if team is not None}
                if counts and ids:
                    team_id, count = max(counts.items(), key=lambda item: item[1])
                    if count >= max(2, math.ceil(len(ids) * 0.60)):
                        mapping[idx] = int(team_id)
            export_team_stats = {int(row["team_index"]): self._stats(row) for row in team_rows}
            goals = {idx: int((export_team_stats.get(idx) or {}).get("goals_derived") or 0) for idx in (0, 1)}
            hs = int(fixture["home_score"] or 0); aws = int(fixture["away_score"] or 0)
            if len(mapping) < 2 and goals[0] != goals[1] and hs != aws and home is not None and away is not None:
                if goals[0] == hs and goals[1] == aws:
                    mapping = {0: home, 1: away}
                elif goals[0] == aws and goals[1] == hs:
                    mapping = {0: away, 1: home}
            if len(mapping) != 2 or mapping.get(0) == mapping.get(1):
                return False
            mapped_home_idx = next((idx for idx, team_id in mapping.items() if team_id == home), None)
            mapped_away_idx = next((idx for idx, team_id in mapping.items() if team_id == away), None)
            if mapped_home_idx is None or mapped_away_idx is None:
                return False
            if goals[mapped_home_idx] != hs or goals[mapped_away_idx] != aws:
                return False

        with self.database.transaction() as conn:
            current = conn.execute("SELECT fixture_id FROM match_stat_exports WHERE id=?", (export_id,)).fetchone()
            if current and current["fixture_id"] is None:
                self._activate_fixture_export(
                    conn, export_id, career_id=int(snap["career_id"]), fixture_id=int(fixture["fixture_id"]),
                    snapshot_id=int(snap["id"]), confidence=1.0, mapping=mapping, method="pipeline_capture_verified",
                )
        return True

    def reconcile_pending(self) -> None:
        with self.database.connect() as conn:
            ids = [int(row[0]) for row in conn.execute("SELECT id FROM match_stat_exports WHERE fixture_id IS NULL ORDER BY id").fetchall()]
        for export_id in ids:
            try:
                if not self._link_by_pipeline_capture(export_id):
                    self.reconcile_export(export_id)
            except Exception:
                continue

    def reconcile_export(self, export_id: int) -> bool:
        with self.database.connect() as conn:
            export = conn.execute("SELECT * FROM match_stat_exports WHERE id=?", (export_id,)).fetchone()
            if not export or export["fixture_id"] is not None:
                return bool(export and export["fixture_id"] is not None)
            try:
                summary = json.loads(str(export["raw_summary_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                summary = {}
            explicit_career_id = int(summary.get("career_id") or 0) or None
            career_ids = [int(row[0]) for row in conn.execute("SELECT id FROM careers ORDER BY id").fetchall()]
            if explicit_career_id is not None and explicit_career_id not in career_ids:
                conn.execute("UPDATE match_stat_exports SET linkage_status='career_invalid' WHERE id=?", (export_id,))
                return False
            if explicit_career_id is None:
                if len(career_ids) != 1:
                    conn.execute("UPDATE match_stat_exports SET linkage_status='career_required' WHERE id=?", (export_id,))
                    return False
                explicit_career_id = career_ids[0]
            detailed = conn.execute("SELECT player_ea_id,team_index FROM match_player_detailed_stats WHERE export_id=?", (export_id,)).fetchall()
            team_rows = conn.execute("SELECT team_index,stats_json FROM match_team_detailed_stats WHERE export_id=?", (export_id,)).fetchall()
            participant_ids = {int(row["player_ea_id"]) for row in detailed}
            if not participant_ids:
                return False
            export_team_stats = {int(row["team_index"]): self._stats(row) for row in team_rows}
            candidates = conn.execute(
                """WITH first_complete AS (
                       SELECT f.id fixture_id,f.career_id,f.fixture_key,f.home_team_ea_id,f.away_team_ea_id,
                              fo.home_score,fo.away_score,fo.date,s.id snapshot_id,s.import_sequence,
                              ROW_NUMBER() OVER(PARTITION BY f.id ORDER BY s.import_sequence ASC) rn
                       FROM fixtures f
                       JOIN fixture_observations fo ON fo.fixture_id=f.id
                       JOIN snapshots s ON s.id=fo.snapshot_id
                       WHERE fo.is_completed=1 AND fo.managed_team_involved=1 AND f.career_id=?
                   )
                   SELECT * FROM first_complete c WHERE rn=1
                   ORDER BY import_sequence DESC LIMIT 80"""
                , (explicit_career_id,)
            ).fetchall()

            scored: list[tuple[float, sqlite3.Row, dict[int, int]]] = []
            for candidate in candidates:
                pmp_rows = conn.execute(
                    "SELECT DISTINCT player_ea_id FROM player_match_performances WHERE snapshot_id=? AND fixture_key=?",
                    (candidate["snapshot_id"], candidate["fixture_key"]),
                ).fetchall()
                pmp_ids = {int(row[0]) for row in pmp_rows}
                overlap = (
                    len(participant_ids & pmp_ids) / max(len(participant_ids), len(pmp_ids), 1)
                    if pmp_ids else 0.0
                )
                home = int(candidate["home_team_ea_id"]) if candidate["home_team_ea_id"] is not None else None
                away = int(candidate["away_team_ea_id"]) if candidate["away_team_ea_id"] is not None else None
                mapping: dict[int, int] = {}
                membership_quality: list[float] = []
                memberships = conn.execute(
                    "SELECT ea_player_id,team_ea_id FROM player_states WHERE snapshot_id=? AND ea_player_id IN (%s)" % ",".join("?" * len(participant_ids)),
                    (candidate["snapshot_id"], *sorted(participant_ids)),
                ).fetchall()
                by_player = {int(row["ea_player_id"]): int(row["team_ea_id"]) if row["team_ea_id"] is not None else None for row in memberships}
                for idx in (0, 1):
                    ids = [int(row["player_ea_id"]) for row in detailed if int(row["team_index"]) == idx]
                    counts = {team: sum(by_player.get(pid) == team for pid in ids) for team in (home, away) if team is not None}
                    if counts and ids:
                        team, count = max(counts.items(), key=lambda it: it[1])
                        quality = count / len(ids)
                        if count >= max(2, math.ceil(len(ids) * 0.60)):
                            mapping[idx] = int(team)
                            membership_quality.append(quality)
                distinct_roster_mapping = len(mapping) == 2 and mapping.get(0) != mapping.get(1)
                roster_quality = sum(membership_quality) / len(membership_quality) if distinct_roster_mapping and membership_quality else 0.0
                # A 22-player match-rating overlap is the strongest source. If it is missing,
                # require near-complete roster evidence for both teams before the candidate is even scored.
                if overlap < 0.45 and not (distinct_roster_mapping and roster_quality >= 0.90):
                    continue
                score = overlap * 0.74
                if distinct_roster_mapping:
                    score += 0.20 + 0.45 * roster_quality
                # Scoreline is an independent validator and can orient team_index when roster mapping is unavailable.
                hs = int(candidate["home_score"] or 0); aws = int(candidate["away_score"] or 0)
                goals = {idx: int((export_team_stats.get(idx) or {}).get("goals_derived") or 0) for idx in (0, 1)}
                if len(mapping) < 2 and goals[0] != goals[1] and hs != aws:
                    if goals[0] == hs and goals[1] == aws and home is not None and away is not None:
                        mapping = {0: home, 1: away}
                    elif goals[0] == aws and goals[1] == hs and home is not None and away is not None:
                        mapping = {0: away, 1: home}
                if len(mapping) == 2:
                    mapped_home_idx = next((idx for idx, team in mapping.items() if team == home), None)
                    mapped_away_idx = next((idx for idx, team in mapping.items() if team == away), None)
                    if mapped_home_idx is not None and mapped_away_idx is not None:
                        if goals[mapped_home_idx] == hs and goals[mapped_away_idx] == aws:
                            score += 0.12
                        else:
                            score -= 0.35
                scored.append((score, candidate, mapping))

        if not scored:
            return False
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best, mapping = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best_score < 0.72 or (second > 0 and best_score - second < 0.06):
            with self.database.transaction() as conn:
                conn.execute("UPDATE match_stat_exports SET linkage_status='ambiguous' WHERE id=? AND fixture_id IS NULL", (export_id,))
            return False
        with self.database.transaction() as conn:
            current = conn.execute("SELECT fixture_id FROM match_stat_exports WHERE id=?", (export_id,)).fetchone()
            if current and current["fixture_id"] is None:
                method = "participant_overlap" if best_score >= 0.90 else "roster_and_scoreline"
                self._activate_fixture_export(
                    conn, export_id, career_id=int(best["career_id"]), fixture_id=int(best["fixture_id"]),
                    snapshot_id=int(best["snapshot_id"]), confidence=best_score, mapping=mapping, method=method,
                )
        return True

    def link_export(self, career_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        export_id = int(payload.get("exportId") or 0)
        fixture_id = int(payload.get("fixtureId") or 0)
        team0 = int(payload.get("team0EaId") or 0)
        team1 = int(payload.get("team1EaId") or 0)
        if min(export_id, fixture_id, team0, team1) <= 0 or team0 == team1:
            raise ValueError("Export, fixture and two distinct team assignments are required.")
        with self.database.transaction() as conn:
            export = conn.execute("SELECT * FROM match_stat_exports WHERE id=?", (export_id,)).fetchone()
            fixture = conn.execute(
                """SELECT f.*,fo.snapshot_id,fo.home_score,fo.away_score FROM fixtures f
                   JOIN fixture_observations fo ON fo.fixture_id=f.id
                   JOIN snapshots s ON s.id=fo.snapshot_id
                   WHERE f.id=? AND f.career_id=? AND fo.is_completed=1
                   ORDER BY s.import_sequence DESC LIMIT 1""",
                (fixture_id, career_id),
            ).fetchone()
            if not export or not fixture:
                raise ValueError("Export or completed fixture was not found in this career.")
            if {team0, team1} != {int(fixture["home_team_ea_id"]), int(fixture["away_team_ea_id"])}:
                raise ValueError("The team assignment does not match the fixture's home and away teams.")
            team_stats = {
                int(row["team_index"]): self._stats(row)
                for row in conn.execute("SELECT * FROM match_team_detailed_stats WHERE export_id=?", (export_id,)).fetchall()
            }
            mapping = {0: team0, 1: team1}
            home_idx = 0 if team0 == int(fixture["home_team_ea_id"]) else 1
            away_idx = 1 - home_idx
            if int((team_stats.get(home_idx) or {}).get("goals_derived") or 0) != int(fixture["home_score"] or 0) or int((team_stats.get(away_idx) or {}).get("goals_derived") or 0) != int(fixture["away_score"] or 0):
                raise ValueError("The exported score does not match the selected fixture.")
            self._activate_fixture_export(
                conn, export_id, career_id=career_id, fixture_id=fixture_id, snapshot_id=int(fixture["snapshot_id"]),
                confidence=1.0, mapping=mapping, method="manual_verified",
            )
        return {"ok": True, "exportId": export_id, "fixtureId": fixture_id, "linkageMethod": "manual_verified"}

    def status(self) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) total,
                          SUM(CASE WHEN fixture_id IS NOT NULL THEN 1 ELSE 0 END) linked,
                          SUM(CASE WHEN fixture_id IS NULL THEN 1 ELSE 0 END) pending,
                          SUM(CASE WHEN pipeline_capture_id IS NOT NULL AND pipeline_capture_id<>'' THEN 1 ELSE 0 END) paired,
                          MAX(imported_at) last_import
                   FROM match_stat_exports WHERE superseded_by_export_id IS NULL"""
            ).fetchone()
        return {
            "model": "atlas-fc26-match-stats-v2",
            "exports": int(row["total"] or 0),
            "linked": int(row["linked"] or 0),
            "pending": int(row["pending"] or 0),
            "pairedCaptures": int(row["paired"] or 0),
            "lastImportAt": row["last_import"],
            "lastScanAt": self.last_scan_at,
            "roots": [str(p) for p in self.roots()],
        }
