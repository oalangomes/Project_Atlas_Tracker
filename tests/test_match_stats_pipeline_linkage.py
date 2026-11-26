from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from atlas.db import Database
from atlas.match_stats_importer import MatchStatsImporter


def _add_snapshot(db, snapshot_id, capture_id=None):
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO snapshots (
                id, career_id, external_snapshot_id, schema_version, season_index, career_date,
                career_date_sort, managed_team_ea_id, exported_at_utc, import_sequence,
                content_hash, import_status, source_path, imported_at
            ) VALUES (?, 1, ?, '1', 1, '2026-03-14', 20260314, 1929,
                      '2026-11-26T12:00:00Z', ?, ?, 'imported', '', '2026-11-26T12:00:00Z')""",
            (snapshot_id, f"snapshot-{snapshot_id}", snapshot_id, f"hash-{snapshot_id}"),
        )
        conn.executemany(
            """INSERT INTO fixture_observations (
                snapshot_id, fixture_id, fixture_key, is_completed, home_score, away_score,
                managed_team_involved, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, 1, '{}')""",
            [(snapshot_id, fixture, str(fixture), int(fixture <= snapshot_id),
              0 if fixture <= snapshot_id else None, 2 if fixture <= snapshot_id else None)
             for fixture in (1, 2, 3)],
        )
        if capture_id:
            conn.execute(
                "INSERT INTO snapshot_metadata VALUES (?, 'post_match_capture_id', ?)",
                (snapshot_id, capture_id),
            )


def _write_ready(ready, name, capture_id=""):
    path = ready / f"FC26_MatchStats_{name}"
    path.mkdir()
    (path / "16_match_participants_wide.csv").write_text(
        "player_id,team_index,minutes_played\n" +
        "".join(f"{player},{int(player > 7)},90\n" for player in range(1, 15)),
        encoding="utf-8",
    )
    (path / "18_match_teams_wide.csv").write_text(
        "team_index,goals_derived\n0,0\n1,2\n", encoding="utf-8",
    )
    (path / "20_match_export_summary.csv").write_text(
        f"status,pipeline_capture_id\ncomplete_participant_export,{capture_id}\n",
        encoding="utf-8",
    )
    (path / "MATCH_READY").touch()
    return path


class MatchStatsPipelineLinkageTests(unittest.TestCase):
    def test_two_matches_with_identical_statistics_link_only_to_their_own_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "MatchStats" / "ready"
            ready.mkdir(parents=True)
            db = Database(root / "atlas.sqlite3")
            importer = MatchStatsImporter(db)
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO careers VALUES (1, 'career', 'fingerprint', 'Career', NULL, 1929, NULL, '', '')"
                )
                conn.executemany(
                    """INSERT INTO fixtures (id, career_id, fixture_key, home_team_ea_id, away_team_ea_id)
                       VALUES (?, 1, ?, 1793, 1929)""",
                    [(fixture, str(fixture)) for fixture in (1, 2, 3)],
                )
            _add_snapshot(db, 1)
            with db.transaction() as conn:
                conn.executemany(
                    """INSERT INTO player_match_performances (
                        snapshot_id, artificial_key, fixture_key, player_ea_id, raw_json
                    ) VALUES (1, ?, '1', ?, '{}')""",
                    [(str(player), player) for player in range(1, 15)],
                )

            with patch.object(importer, "roots", return_value=[ready]):
                _write_ready(ready, "legacy")
                legacy, = importer.scan_once()
                self.assertEqual(legacy.fixture_id, 1)

                first_path = _write_ready(ready, "first", "pmc-first")
                first, = importer.scan_once()
                self.assertEqual(first.status, "imported")
                with db.connect() as conn:
                    pending = conn.execute(
                        "SELECT linkage_status FROM match_stat_exports WHERE id=?", (first.export_id,),
                    ).fetchone()
                self.assertEqual(pending["linkage_status"], "pending")
                self.assertIsNone(first.fixture_id)
                self.assertFalse(importer.last_linked_matches)
                self.assertFalse(first_path.exists())
                self.assertTrue((ready.parent / "imported" / first_path.name).is_dir())

                same_token = _write_ready(ready, "reexport", "pmc-first")
                (same_token / "20_match_export_summary.csv").write_text(
                    "status,pipeline_capture_id,exporter_version\ncomplete_participant_export,pmc-first,1.1.2\n",
                    encoding="utf-8",
                )
                duplicate, = importer.scan_once()
                self.assertEqual((duplicate.status, duplicate.export_id), ("duplicate_semantic", first.export_id))

                _add_snapshot(db, 2, "pmc-first")
                self.assertEqual(importer.scan_once(), [])
                self.assertEqual(
                    importer.last_linked_matches, [{"career_id": 1, "fixture_id": 2, "snapshot_id": 2}],
                )

                _add_snapshot(db, 3, "pmc-second")
                _write_ready(ready, "second", "pmc-second")
                second, = importer.scan_once()
                self.assertEqual((second.fixture_id, second.status), (3, "imported"))
                self.assertEqual(
                    importer.last_linked_matches, [{"career_id": 1, "fixture_id": 3, "snapshot_id": 3}],
                )
                self.assertEqual(importer.scan_once(), [])
                self.assertEqual(importer.last_linked_matches, [])

            with db.connect() as conn:
                rows = conn.execute(
                    """SELECT id, fixture_id, snapshot_id, linkage_method, superseded_by_export_id
                       FROM match_stat_exports ORDER BY id"""
                ).fetchall()
            self.assertEqual([tuple(row) for row in rows], [
                (legacy.export_id, 1, 1, "roster_and_scoreline", None),
                (first.export_id, 2, 2, "pipeline_capture_verified", None),
                (second.export_id, 3, 3, "pipeline_capture_verified", None),
            ])
