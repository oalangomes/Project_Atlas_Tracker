"""Regression tests for in-match position provenance and historical recovery."""
from __future__ import annotations

import sqlite3
import unittest

from atlas.positions import trusted_actual_position, trusted_position_source
from atlas.server_query_matches import (apply_historical_observed_positions,
                                       historical_observed_positions)

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
            # Present positions are never overwritten.
            self.assertEqual(rows[1]["actual_position"], "GK")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
