from __future__ import annotations

import sqlite3
import unittest

from atlas.server_query_matches import historical_observed_positions


class TemporalPositionTests(unittest.TestCase):
    def _build(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, career_id INTEGER, career_date TEXT, import_sequence INTEGER, season_index INTEGER)")
        conn.execute("CREATE TABLE player_match_performances (snapshot_id INTEGER, fixture_key TEXT, player_ea_id INTEGER, actual_position TEXT, actual_position_source TEXT, raw_json TEXT)")
        # career A
        conn.execute("INSERT INTO snapshots VALUES (1, 1, '2025-10-01', 3, 1)")
        conn.execute("INSERT INTO snapshots VALUES (2, 1, '2025-11-01', 7, 1)")
        conn.execute("INSERT INTO snapshots VALUES (3, 1, '2025-12-01', 11, 1)")
        # future-only observation for player 11
        conn.execute("INSERT INTO player_match_performances VALUES (3, 'K', 11, 'CAM', 'career_playerlastmatchhistory_latest_match', '{}')")
        # career B with similar ids
        conn.execute("INSERT INTO snapshots VALUES (10, 2, '2025-10-01', 3, 1)")
        conn.execute("INSERT INTO snapshots VALUES (11, 2, '2025-11-01', 7, 1)")
        conn.execute("INSERT INTO player_match_performances VALUES (11, 'K', 11, 'ST', 'career_playerlastmatchhistory_latest_match', '{}')")
        return conn

    def test_future_observation_not_eligible(self):
        conn = self._build()
        try:
            selected = conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone()
            trusted = historical_observed_positions(conn, selected, "K")
            self.assertNotIn(11, trusted)
        finally:
            conn.close()

    def test_career_isolation(self):
        conn = self._build()
        try:
            selected = conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone()
            trusted = historical_observed_positions(conn, selected, "K")
            # career B's ST must not leak into career A
            self.assertNotIn(11, trusted)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()