import json
import sqlite3
import unittest
from contextlib import contextmanager

from atlas.match_stats_importer import MatchStatsImporter


class MemoryDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def connect(self):
        return self.conn

    @contextmanager
    def transaction(self):
        yield self.conn
        self.conn.commit()


class MatchStatsOwnGoalLinkageTests(unittest.TestCase):
    def test_completed_export_links_to_score_with_opponent_own_goal(self):
        db = MemoryDatabase()
        db.conn.executescript("""
            CREATE TABLE careers (id INTEGER PRIMARY KEY);
            CREATE TABLE snapshots (id INTEGER PRIMARY KEY, import_sequence INTEGER);
            CREATE TABLE fixtures (id INTEGER PRIMARY KEY, career_id INTEGER, fixture_key TEXT,
                                   home_team_ea_id INTEGER, away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations (snapshot_id INTEGER, fixture_id INTEGER,
                is_completed INTEGER, managed_team_involved INTEGER, home_score INTEGER,
                away_score INTEGER, date TEXT);
            CREATE TABLE player_match_performances (snapshot_id INTEGER, fixture_key TEXT,
                player_ea_id INTEGER);
            CREATE TABLE player_states (snapshot_id INTEGER, ea_player_id INTEGER,
                team_ea_id INTEGER);
            CREATE TABLE match_stat_exports (id INTEGER PRIMARY KEY, fixture_id INTEGER,
                career_id INTEGER, snapshot_id INTEGER, raw_summary_json TEXT,
                linkage_status TEXT, linkage_confidence REAL, team0_ea_id INTEGER,
                team1_ea_id INTEGER, linkage_method TEXT, superseded_by_export_id INTEGER);
            CREATE TABLE match_player_detailed_stats (export_id INTEGER, player_ea_id INTEGER,
                team_index INTEGER);
            CREATE TABLE match_team_detailed_stats (export_id INTEGER, team_index INTEGER,
                team_ea_id INTEGER, stats_json TEXT);
            INSERT INTO careers VALUES (1);
            INSERT INTO snapshots VALUES (99, 99);
            INSERT INTO fixtures VALUES (309261, 1, 'burnley', 1929, 1796);
            INSERT INTO fixture_observations VALUES (99, 309261, 1, 1, 4, 3, '2026-02-14');
            INSERT INTO match_stat_exports VALUES (46, NULL, NULL, NULL, '{}', 'ambiguous',
                NULL, NULL, NULL, NULL, NULL);
        """)
        db.conn.executemany(
            "INSERT INTO match_team_detailed_stats VALUES (46, ?, NULL, ?)",
            [(0, json.dumps({"goals_derived": 4, "own_goals": 1})),
             (1, json.dumps({"goals_derived": 2, "own_goals": 0}))],
        )
        for index in range(30):
            player_id = index + 1
            team_index = 0 if index < 16 else 1
            db.conn.execute("INSERT INTO match_player_detailed_stats VALUES (46, ?, ?)",
                            (player_id, team_index))
            db.conn.execute("INSERT INTO player_states VALUES (99, ?, ?)",
                            (player_id, 1929 if team_index == 0 else 1796))
            if index < 16:
                db.conn.execute("INSERT INTO player_match_performances VALUES (99, 'burnley', ?)",
                                (player_id,))
        db.conn.commit()

        self.assertTrue(MatchStatsImporter(db).reconcile_export(46))
        row = db.conn.execute("SELECT fixture_id,snapshot_id,linkage_status,team0_ea_id,team1_ea_id "
                              "FROM match_stat_exports WHERE id=46").fetchone()
        self.assertEqual(tuple(row), (309261, 99, "linked", 1929, 1796))


if __name__ == "__main__":
    unittest.main()
