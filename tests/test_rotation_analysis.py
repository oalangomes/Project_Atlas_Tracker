from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

from atlas.rotation_analysis import rotation_continuity


class RotationContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                import_sequence INTEGER,career_date TEXT,managed_team_ea_id INTEGER);
            CREATE TABLE fixtures(id INTEGER,career_id INTEGER,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,managed_team_involved INTEGER,
                is_completed INTEGER,date TEXT,competition_name TEXT,home_team_name TEXT,away_team_name TEXT,
                home_score INTEGER,away_score INTEGER,raw_json TEXT);
            CREATE TABLE match_stat_exports(id INTEGER,career_id INTEGER,fixture_id INTEGER,snapshot_id INTEGER,
                linkage_status TEXT,export_status TEXT,team0_ea_id INTEGER,team1_ea_id INTEGER);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,team_index INTEGER,
                player_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,stats_json TEXT);
            INSERT INTO snapshots VALUES(1,1,1,1,'2025-08-01',100),
                                        (2,1,1,2,'2025-08-02',100),
                                        (3,1,1,3,'2025-08-09',100),
                                        (4,1,1,4,'2025-08-16',100);
            INSERT INTO fixtures VALUES(20,1,100,200),(30,1,300,100),(40,1,100,400);
            INSERT INTO fixture_observations VALUES
                (2,20,1,1,'2025-08-02','League','Own','Rival A',2,1,'{}'),
                (3,30,1,1,'2025-08-09','Cup','Rival B','Own',1,1,'{}'),
                (4,40,1,1,'2025-08-16','League','Own','Rival C',3,0,'{}');
            INSERT INTO match_stat_exports VALUES
                (1,1,20,2,'linked','complete_participant_export',100,200),
                (2,1,30,3,'linked','complete_participant_export',300,100),
                (3,1,40,4,'linked','complete_participant_export',100,400);
        """)
        for export_id, own_index, players in ((1, 0, list(range(1, 12))),
                                               (2, 1, list(range(1, 9)) + [12, 13, 14]),
                                               (3, 0, list(range(21, 32)))):
            for slot, player_id in enumerate(players):
                self.conn.execute("INSERT INTO match_player_detailed_stats VALUES(?,?,?,?)",
                                  (export_id, own_index, player_id, json.dumps({"array_index": slot})))
            own = {"shots": 10, "npk_expected_goals": 1.5} if export_id != 2 else {"shots": 7}
            opponent = {"shots": 5, "npk_expected_goals": 0.8}
            for index, stats in ((own_index, own), (1 - own_index, opponent)):
                self.conn.execute("INSERT INTO match_team_detailed_stats VALUES(?,?,?)",
                                  (export_id, index, json.dumps(stats)))

    def tearDown(self) -> None:
        self.conn.close()

    def test_as_of_snapshot_previous_xi_and_missing_metric(self) -> None:
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        calls: list[tuple[int, str]] = []

        def context(conn, career_id, source_snapshot, match_date, team_id, opponent_id, raw):
            calls.append((source_snapshot["id"], match_date))
            return {"available": True, "opponent_overall_gap": 3 if opponent_id == 300 else -1,
                    "as_of_snapshot_id": source_snapshot["id"] - 1,
                    "opponent": {"league_level": 3}, "opponent_table_position": None}

        with patch("atlas.rotation_analysis.pre_match_competitive_context", side_effect=context), \
             patch("atlas.rotation_analysis.match_lineup_phases", return_value=None):
            result = rotation_continuity(self.conn, 1, snapshot, [1])
        self.assertEqual(calls, [(2, "2025-08-02"), (3, "2025-08-09")])
        self.assertEqual(result["coverage"]["completedMatches"], 2)
        self.assertEqual(result["coverage"]["groupedMatches"], 1)
        self.assertEqual(result["matches"][0]["exclusionReason"], "previous_xi_unavailable")
        self.assertEqual(result["matches"][1]["retainedStarters"], 8)
        self.assertEqual(result["matches"][1]["rotationGroup"], "continued")
        self.assertIsNone(result["groups"]["continued"]["metrics"]["npkXgFor"]["average"])
        self.assertEqual(result["groups"]["continued"]["metrics"]["shotsFor"]["coveredMatches"], 1)
        self.assertEqual(result["possessionShare"]["status"], "unavailable")
        self.assertFalse(result["comparisonEligible"])

    def test_filters_keep_previous_match_reference(self) -> None:
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        with patch("atlas.rotation_analysis.pre_match_competitive_context", return_value={
                "available": True, "opponent_overall_gap": 4, "as_of_snapshot_id": 1,
                "opponent": {}, "opponent_table_position": None}), \
             patch("atlas.rotation_analysis.match_lineup_phases", return_value=None):
            result = rotation_continuity(self.conn, 1, snapshot, [1],
                                         {"competition": "Cup", "venue": "away", "opponentTier": "stronger"})
        self.assertEqual([row["fixtureId"] for row in result["matches"]], [30])
        self.assertEqual(result["matches"][0]["retainedStarters"], 8)
        self.assertEqual(result["coverage"]["selectedMatches"], 1)
        self.assertEqual(result["coverage"]["knownInitialXi"], 1)

    def test_missing_previous_xi_does_not_compare_across_gap(self) -> None:
        self.conn.execute("DELETE FROM match_stat_exports WHERE id=1")
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        with patch("atlas.rotation_analysis.pre_match_competitive_context", return_value={
                "available": False, "reason": "no_prior_same_season_snapshot"}), \
             patch("atlas.rotation_analysis.match_lineup_phases", return_value=None):
            result = rotation_continuity(self.conn, 1, snapshot, [1])
        self.assertEqual(result["coverage"]["linkedDetailedMatches"], 1)
        self.assertEqual(result["coverage"]["groupedMatches"], 0)
        self.assertEqual(result["matches"][1]["exclusionReason"], "previous_xi_unavailable")
        self.assertIsNone(result["matches"][1]["retainedStarters"])

    def test_unknown_opponent_formation_is_a_separate_filter(self) -> None:
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        with patch("atlas.rotation_analysis.pre_match_competitive_context", return_value={
                "available": False, "reason": "no_prior_same_season_snapshot"}), \
             patch("atlas.rotation_analysis.match_lineup_phases", return_value=None):
            result = rotation_continuity(self.conn, 1, snapshot, [1],
                                         {"opponentFormation": "unknown"})
        self.assertEqual([row["fixtureId"] for row in result["matches"]], [20, 30])
        self.assertEqual(result["coverage"]["selectedMatches"], 2)
        self.assertEqual(result["groups"]["continued"]["matches"], 1)


if __name__ == "__main__":
    unittest.main()
