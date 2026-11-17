"""Regression tests for in-match position provenance and historical recovery."""
from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from atlas.positions import trusted_actual_position, trusted_position_source
from atlas.server_query_matches import (apply_historical_observed_positions,
                                       historical_observed_positions, MatchQueryMixin)

KEY = "841:20251025:0:0:1:1875"
RATING_SOURCE = "career_playermatchratinghistory_position"
LAST_MATCH_SOURCE = "career_playerlastmatchhistory_latest_match"


def _build_position_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, career_id INTEGER, career_date TEXT, import_sequence INTEGER, season_index INTEGER)")
    conn.execute(
        """CREATE TABLE player_match_performances (
               snapshot_id INTEGER, fixture_key TEXT, player_ea_id INTEGER, actual_position TEXT,
               actual_position_source TEXT, raw_json TEXT)"""
    )
    conn.execute("INSERT INTO snapshots VALUES (1, 1, '2025-10-01', 3, 1)")
    conn.execute("INSERT INTO snapshots VALUES (2, 1, '2025-11-01', 7, 1)")
    conn.execute("INSERT INTO snapshots VALUES (3, 1, '2025-12-01', 11, 1)")
    # Current snapshot only carries the rating-history line-up slot; the
    # substitute slot 28 therefore produces an empty observed position.
    conn.execute(
        "INSERT INTO player_match_performances VALUES (3, ?, 10, 'GK', ?, '{}')", (KEY, RATING_SOURCE),
    )
    conn.execute("INSERT INTO player_match_performances VALUES (3, ?, 11, '', '', '')", (KEY,))
    # Snapshot captured right after the substitute entered: trusted last-match position.
    conn.execute(
        "INSERT INTO player_match_performances VALUES (2, ?, 11, 'CAM', ?, '{}')", (KEY, LAST_MATCH_SOURCE),
    )
    conn.execute(
        "INSERT INTO player_match_performances VALUES (2, ?, 10, 'GK', ?, '{}')", (KEY, RATING_SOURCE),
    )
    return conn


class TrustedPositionProvenanceTests(unittest.TestCase):
    def test_accredits_both_trusted_in_match_sources(self):
        self.assertEqual(trusted_position_source(RATING_SOURCE), RATING_SOURCE)
        self.assertEqual(trusted_position_source(LAST_MATCH_SOURCE), LAST_MATCH_SOURCE)
        self.assertIsNone(trusted_position_source("unverified"))
        self.assertEqual(trusted_actual_position(" ST ", LAST_MATCH_SOURCE), "ST")
        self.assertIsNone(trusted_actual_position("ST", None))
        self.assertIsNone(trusted_actual_position(None, RATING_SOURCE))

    def test_historical_observed_positions_pick_most_recent_trusted_row(self):
        conn = _build_position_db()
        try:
            selected = conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
            trusted = historical_observed_positions(conn, selected, KEY)
            self.assertIn(11, trusted)
            self.assertEqual(trusted[11]["position"], "CAM")
            self.assertEqual(trusted[11]["source"], LAST_MATCH_SOURCE)
            self.assertEqual(trusted[11]["snapshot_id"], 2)
        finally:
            conn.close()

    def test_historical_observed_positions_ignores_untrusted_and_empty(self):
        conn = _build_position_db()
        try:
            selected = conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
            trusted = historical_observed_positions(conn, selected, KEY)
            self.assertIn(10, trusted)
            self.assertEqual(trusted[10]["position"], "GK")
            self.assertEqual(trusted[10]["source"], RATING_SOURCE)
            self.assertIn(11, trusted)
            self.assertEqual(trusted[11]["position"], "CAM")
            # Rows without a position or with an unverified source are not trusted.
            conn.execute("INSERT INTO player_match_performances VALUES (2, ?, 12, '', '', '')", (KEY,))
            conn.execute(
                "UPDATE player_match_performances SET actual_position_source='unverified', actual_position='ST' WHERE snapshot_id=? AND fixture_key=? AND player_ea_id=?",
                (2, KEY, 11),
            )
            conn.commit()
            trusted = historical_observed_positions(conn, selected, KEY)
            self.assertNotIn(12, trusted)
            self.assertNotIn(11, trusted)
        finally:
            conn.close()

    def test_historical_lookup_never_uses_later_or_unordered_snapshot(self):
        conn = _build_position_db()
        try:
            conn.execute("INSERT INTO player_match_performances VALUES (1, ?, 21, 'RW', ?, '{}')",
                         (KEY, LAST_MATCH_SOURCE))
            conn.execute("INSERT INTO player_match_performances VALUES (3, ?, 21, 'ST', ?, '{}')",
                         (KEY, LAST_MATCH_SOURCE))
            conn.execute("INSERT INTO snapshots VALUES (4, 1, '2025-10-15', NULL, 1)")
            conn.execute("INSERT INTO player_match_performances VALUES (4, ?, 22, 'CAM', ?, '{}')",
                         (KEY, LAST_MATCH_SOURCE))
            conn.execute("INSERT INTO snapshots VALUES (5, 2, '2025-09-01', 1, 1)")
            conn.execute("INSERT INTO player_match_performances VALUES (5, ?, 23, 'GK', ?, '{}')",
                         (KEY, LAST_MATCH_SOURCE))
            selected = conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone()
            trusted = historical_observed_positions(conn, selected, KEY)
            self.assertEqual(trusted[21]["position"], "RW")
            self.assertEqual(trusted[21]["snapshot_id"], 1)
            self.assertNotIn(22, trusted)
            self.assertNotIn(23, trusted)
        finally:
            conn.close()

    def test_equal_sequence_uses_only_earlier_id_and_missing_limit_abstains(self):
        conn = _build_position_db()
        try:
            conn.execute("UPDATE snapshots SET import_sequence=11 WHERE id=2")
            conn.execute("INSERT INTO snapshots VALUES (4, 1, '2025-12-02', 11, 1)")
            conn.execute("INSERT INTO player_match_performances VALUES (4, ?, 11, 'ST', ?, '{}')",
                         (KEY, LAST_MATCH_SOURCE))
            selected = conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
            trusted = historical_observed_positions(conn, selected, KEY)
            self.assertEqual(trusted[11]["position"], "CAM")
            self.assertEqual(trusted[11]["import_sequence"], 11)
            conn.execute("UPDATE snapshots SET import_sequence=NULL WHERE id=3")
            selected_without_order = conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
            self.assertEqual(historical_observed_positions(conn, selected_without_order, KEY), {})
        finally:
            conn.close()


class HistoricalObservedPositionBackfillTests(unittest.TestCase):
    def test_missing_position_is_backfilled_from_earlier_snapshot(self):
        conn = _build_position_db()
        try:
            trusted = historical_observed_positions(
                conn, conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone(), KEY
            )
            rows = [
                {"player_ea_id": 11, "actual_position": "", "actual_position_source": ""},
                {"player_ea_id": 10, "actual_position": "GK", "actual_position_source": RATING_SOURCE},
            ]
            filled = apply_historical_observed_positions(rows, trusted)
            self.assertEqual(filled, 1)
            self.assertEqual(rows[0]["actual_position"], "CAM")
            self.assertEqual(rows[0]["actual_position_source"], LAST_MATCH_SOURCE)
            self.assertEqual(rows[0]["observedPositionBackfill"]["snapshotId"], 2)
            self.assertEqual(rows[0]["observedPositionBackfill"]["importSequence"], 7)
            # Present positions are never overwritten.
            self.assertEqual(rows[1]["actual_position"], "GK")
        finally:
            conn.close()

    def test_match_detail_uses_only_positions_known_at_selected_snapshot(self):
        conn = _build_position_db()
        try:
            conn.execute("ALTER TABLE snapshots ADD COLUMN capabilities_json TEXT DEFAULT '{}'")
            for field, kind in (("rating", "REAL"), ("minutes_played", "INTEGER"),
                                ("display_name", "TEXT")):
                conn.execute(f"ALTER TABLE player_match_performances ADD COLUMN {field} {kind}")
            conn.execute("UPDATE player_match_performances SET rating=7, minutes_played=45, display_name='Player'")
            conn.execute("CREATE TABLE fixtures (id INTEGER, home_team_ea_id INTEGER, away_team_ea_id INTEGER, competition_object_id INTEGER, static_competition_id INTEGER, stadium_ea_id INTEGER)")
            conn.execute("INSERT INTO fixtures VALUES (99, NULL, NULL, NULL, NULL, NULL)")
            conn.execute("CREATE TABLE fixture_observations (snapshot_id INTEGER, fixture_id INTEGER, fixture_key TEXT, is_completed INTEGER, home_score INTEGER, away_score INTEGER, home_penalties INTEGER, away_penalties INTEGER)")
            conn.execute("INSERT INTO fixture_observations VALUES (3, 99, ?, 1, 1, 0, NULL, NULL)", (KEY,))
            conn.execute("CREATE TABLE player_states (snapshot_id INTEGER, ea_player_id INTEGER, overall INTEGER, potential INTEGER, primary_position TEXT, team_ea_id INTEGER, team_name TEXT)")
            conn.execute("CREATE TABLE roster_states (snapshot_id INTEGER, player_ea_id INTEGER, jersey_number INTEGER)")
            conn.execute("CREATE TABLE competition_states (snapshot_id INTEGER, competition_object_id INTEGER)")
            conn.execute("INSERT INTO snapshots VALUES (4, 1, '2026-01-01', 12, 1, '{}')")
            conn.execute("INSERT INTO fixture_observations VALUES (4, 99, ?, 1, 9, 0, NULL, NULL)", (KEY,))
            conn.execute("INSERT INTO player_match_performances (snapshot_id,fixture_key,player_ea_id,actual_position,actual_position_source,raw_json,rating,minutes_played,display_name) VALUES (4, ?, 11, 'ST', ?, '{}', 9, 45, 'Player')",
                         (KEY, LAST_MATCH_SOURCE))

            class Query(MatchQueryMixin):
                state = SimpleNamespace(database=SimpleNamespace(connect=lambda: conn),
                                        media=SimpleNamespace())
                _snapshot = staticmethod(lambda db, snapshot_id: db.execute(
                    "SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone())
                _season_start = staticmethod(lambda snapshot: 2025)
                _enrich_fixtures = staticmethod(lambda rows, season_start, snapshot_id: rows)
                _enrich_players = staticmethod(lambda rows: rows)

            with patch("atlas.server_query_matches.reconstruct_match_stats", return_value={}), \
                 patch("atlas.server_query_matches.detailed_match", return_value=None):
                result = Query()._match_detail(3, 99)
            player = next(item for item in result["performances"] if item["player_ea_id"] == 11)
            self.assertEqual(player["actual_position"], "CAM")
            self.assertEqual(player["observedPositionBackfill"],
                             {"snapshotId": 2, "importSequence": 7})
            self.assertEqual(result["performanceDiagnostics"]["historicalObservedPositionsBackfilled"], 1)
            self.assertEqual([item["snapshot_id"] for item in result["history"]], [3])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
