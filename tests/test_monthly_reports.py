"""Observable calculations and source-boundary tests for monthly reports."""
import sqlite3
import unittest
from unittest.mock import patch

from atlas.monthly_report_api import markdown_download, report_period
from atlas.monthly_report_markdown import render_month, render_season
from atlas.monthly_reports import _monthly_player, build_month_report, build_season_report


class MonthlyReportTests(unittest.TestCase):
    def test_role_metric_rate_uses_only_export_minutes_and_null_coverage(self):
        player = {"playerEaId": 10, "name": "Forward", "position": "ST", "overall": 70,
                  "potential": 75, "age": 22, "category": "profissional"}
        matches = [
            {"fixtureId": 1, "opponent": "A", "rating": 8.0, "minutes": 90,
             "detail": {"minutes_played": 90, "game_rating": 8.0,
                        "npk_goals": 1, "npk_expected_goals": 0.8, "shots": 2},
             "position": None, "superior": False, "reconstructed": None},
            {"fixtureId": 2, "opponent": "B", "rating": 7.0, "minutes": 90,
             "detail": None, "position": None, "superior": False, "reconstructed": None},
        ]
        result = _monthly_player(player, matches, None)
        self.assertEqual(result["minutes"], 180)
        self.assertEqual(result["detailedMatches"], 1)
        self.assertEqual(result["per90"]["npk_goals"], 1.0)
        self.assertIsNone(result["reconstructed"])
        self.assertEqual(result["averageRating"], 7.5)

    def test_two_months_one_fixture_each_and_snapshot_boundaries(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE careers(id INTEGER, fingerprint_candidate TEXT);
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                career_date TEXT,managed_team_ea_id INTEGER,managed_team_name TEXT,import_sequence INTEGER);
            CREATE TABLE fixtures(id INTEGER,fixture_key TEXT,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,date TEXT,
                competition_name TEXT,home_team_name TEXT,away_team_name TEXT,home_score INTEGER,
                away_score INTEGER,managed_team_involved INTEGER,is_completed INTEGER);
            CREATE TABLE roster_states(snapshot_id INTEGER,player_ea_id INTEGER,team_ea_id INTEGER);
            CREATE TABLE youth_player_states(snapshot_id INTEGER,player_ea_id INTEGER,display_name TEXT,
                overall INTEGER,potential INTEGER,primary_position TEXT);
            CREATE TABLE season_stat_states(snapshot_id INTEGER,player_ea_id INTEGER,represented_team_ea_id INTEGER);
            CREATE TABLE team_states(snapshot_id INTEGER,ea_team_id INTEGER,league_ea_id INTEGER,league_name TEXT);
            CREATE TABLE league_states(snapshot_id INTEGER,ea_league_id INTEGER,league_name TEXT,level INTEGER);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,
                overall INTEGER,potential INTEGER,primary_position TEXT,raw_json TEXT);
            CREATE TABLE loan_states(snapshot_id INTEGER,player_ea_id INTEGER,parent_team_ea_id INTEGER);
            CREATE TABLE player_match_performances(snapshot_id INTEGER,fixture_key TEXT,player_ea_id INTEGER,
                display_name TEXT,minutes_played INTEGER,rating REAL,actual_position TEXT,actual_position_source TEXT);
        """)
        conn.execute("INSERT INTO careers VALUES (1,'career')")
        conn.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)", [
            (1, 1, 1, "2025-07-31", 10, "Club", 1),
            (2, 1, 1, "2025-08-31", 10, "Club", 2)])
        conn.executemany("INSERT INTO fixtures VALUES (?,?,?,?)", [(101, "A", 10, 20), (102, "B", 30, 10)])
        conn.executemany("INSERT INTO fixture_observations VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (1, 101, "2025-07-20", "League", "Club", "A", 2, 1, 1, 1),
            (2, 101, "2025-07-20", "League", "Club", "A", 2, 1, 1, 1),
            (2, 102, "2025-08-20", "Cup", "B", "Club", 0, 0, 1, 1)])
        conn.executemany("INSERT INTO roster_states VALUES (?,?,?)", [(1, 7, 10), (2, 7, 10)])
        conn.executemany("INSERT INTO player_states VALUES (?,?,?,?,?,?,?)", [
            (1, 7, "Player", 70, 75, "ST", "{}"), (2, 7, "Player", 71, 75, "ST", "{}")])
        conn.executemany("INSERT INTO team_states VALUES (?,?,?,?)", [
            (2, 10, 100, "League"), (2, 20, 100, "League"), (2, 30, 200, "First")])
        conn.executemany("INSERT INTO league_states VALUES (?,?,?,?)", [(2, 100, "Third", 3), (2, 200, "First", 1)])
        conn.executemany("INSERT INTO player_match_performances VALUES (?,?,?,?,?,?,?,?)", [
            (1, "A", 7, "Player", 90, 8.0, "ST", "career_playerlastmatchhistory_latest_match"),
            (2, "A", 7, "Player", 90, 8.0, "", ""),
            (2, "B", 7, "Player", 45, 7.0, "ST", "career_playerlastmatchhistory_latest_match")])
        with patch("atlas.monthly_reports.snapshot_fixture_evidence", return_value=[]), \
             patch("atlas.monthly_reports.detailed_match", return_value=None), \
             patch("atlas.monthly_reports.reconstruct_match_stats", return_value={}):
            report = build_season_report(conn, 1, 1, 2)
            july = build_month_report(conn, 1, 1, 2, "2025-07")
            with self.assertRaises(ValueError):
                build_month_report(conn, 1, 1, 2, "2025-09")
        self.assertEqual(report["fixtureCount"], 2)
        self.assertEqual([len(month["matches"]) for month in report["months"]], [1, 1])
        self.assertEqual(sum(month["pointsLeague"] for month in report["months"]), 3)
        self.assertEqual(report["months"][1]["goalsFor"], 0)
        self.assertTrue(report["months"][1]["matches"][0]["superior"])
        self.assertEqual(july["players"][0]["overall"], 70)
        self.assertEqual(report["months"][1]["players"][0]["comparison"]["overallDelta"], 1)
        self.assertIn("2 partidas únicas", render_season(report))
        august_download = markdown_download(report_period(report, "2025-08", "2025-08"))
        self.assertIn("Relatório de 2025-08 a 2025-08", august_download["content"])
        self.assertIn("1 partidas únicas", august_download["content"])
        self.assertNotIn("2025-07", august_download["content"])
        self.assertNotIn("[Índice](README.md)", render_season(report, navigation=False))
        self.assertNotIn("[2025-07](2025-07.md)", render_season(report, navigation=False))
        self.assertIn("0/1 partidas com MatchStats", render_month(report, july))
        self.assertNotIn("[Índice](README.md)", render_month(report, july, navigation=False))
        with self.assertRaises(ValueError):
            build_season_report(conn, 2, 1, 2)
        conn.close()


if __name__ == "__main__":
    unittest.main()
