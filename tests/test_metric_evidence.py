from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace

from atlas.match_stats import aggregate_detailed_stats, detailed_match, detailed_player_matches
from atlas.metric_evidence import fixture_evidence, snapshot_fixture_evidence
from atlas.commission import analyze_team_identity
from atlas.server_query_history import HistoryQueryMixin


class MetricEvidenceTests(unittest.TestCase):
    def test_absent_is_distinct_from_recorded_zero_and_uses_covered_denominator(self):
        stats = aggregate_detailed_stats([
            {"minutes_played": 90, "shots": 0, "npk_expected_goals": 0.0,
             "expected_assists": 0.0, "passes": 10, "passes_completed": 8},
            {"minutes_played": 90, "shots": None, "npk_expected_goals": None,
             "expected_assists": 1.0, "passes": 20, "passes_completed": None},
        ])
        self.assertEqual(stats["matches"], 2)
        self.assertEqual(stats["metricCoverage"]["shots"], 1)
        self.assertEqual(stats["shots_per_match"], 0.0)
        self.assertEqual(stats["shots_per90"], 0.0)
        self.assertEqual(stats["expected_assists_per_match"], 0.5)
        self.assertEqual(stats["xa_per90"], 0.5)
        self.assertIsNone(stats["xg_plus_xa"])
        self.assertIsNone(stats["pass_accuracy_pct_derived"])
        self.assertIsNone(stats["xg_per_shot"])

    def test_missing_minutes_blocks_per90(self):
        stats = aggregate_detailed_stats([
            {"npk_expected_goals": 1.0, "minutes_played": 90},
            {"npk_expected_goals": 1.0},
        ])
        self.assertIsNone(stats["npk_xg_per90"])

    def test_snapshot_evidence_covers_complete_partial_absent_and_future(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript("""
                CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,import_sequence INTEGER);
                CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,date TEXT,
                    home_team_name TEXT,away_team_name TEXT,managed_team_involved INTEGER,is_completed INTEGER);
                CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                    export_status TEXT,linkage_status TEXT,superseded_by_export_id INTEGER,
                    imported_at TEXT,pipeline_capture_id TEXT);
                CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
                CREATE TABLE match_player_detailed_stats(export_id INTEGER,team_index INTEGER,game_rating REAL,
                    minutes_played INTEGER,player_ea_id INTEGER,stats_json TEXT);
                CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,
                    primary_position TEXT,team_ea_id INTEGER);
                INSERT INTO snapshots VALUES (1,1,0,1),(2,1,0,2),(3,2,0,2),(4,1,0,3);
                INSERT INTO fixture_observations VALUES
                    (1,10,'2025-08-01','A','B',1,1),(1,11,'2025-08-02','A','C',1,1),
                    (1,12,'2025-08-03','A','D',1,1),(1,13,'2025-08-04','A','E',1,1),
                    (2,10,'2025-08-01','A','B',1,1),(2,13,'2025-08-04','A','E',1,1);
                INSERT INTO match_stat_exports VALUES
                    (1,10,1,1,'incomplete_participant_export','linked',NULL,'2025-08-01',NULL),
                    (2,10,1,2,'complete_participant_export','linked',NULL,'2025-08-02','capture-2'),
                    (3,11,2,3,'complete_participant_export','linked',NULL,'2025-08-02',NULL),
                    (4,12,1,4,'complete_participant_export','linked',NULL,'2025-08-03',NULL),
                    (5,13,1,1,'complete_participant_export','linked',6,'2025-08-01',NULL),
                    (6,13,1,2,'complete_participant_export','linked',NULL,'2025-08-02',NULL);
                INSERT INTO match_team_detailed_stats VALUES
                    (2,0,100,'{"npk_expected_goals":1.0,"expected_assists":0,"shots":0}'),
                    (2,1,200,'{"npk_expected_goals":0.5,"penalties_committed":1}'),
                    (3,0,100,'{"expected_assists":9}'),(3,1,300,'{}'),
                    (4,0,100,'{"expected_assists":9}'),(4,1,400,'{}'),
                    (5,0,100,'{"expected_assists":1}'),(5,1,500,'{}'),
                    (6,0,100,'{"expected_assists":2}'),(6,1,500,'{}');
            """)
            conn.execute("ALTER TABLE match_stat_exports ADD COLUMN external_export_id TEXT")
            conn.execute("ALTER TABLE match_stat_exports ADD COLUMN linkage_confidence REAL")
            first = dict(conn.execute("SELECT * FROM snapshots WHERE id=1").fetchone())
            early = {item["fixtureId"]: item["evidence"] for item in snapshot_fixture_evidence(conn, first)}
            self.assertEqual(early[10]["state"], "partial")
            self.assertEqual(early[11]["state"], "absent")
            self.assertEqual(early[12]["state"], "absent")
            self.assertEqual(early[13]["source"]["exportId"], 5)
            self.assertEqual(early[13]["state"], "complete")
            self.assertEqual(detailed_match(conn, 13, career_id=1, season_index=0,
                                            as_of_import_sequence=1)["exportId"], 5)
            second = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            second_rows = {item["fixtureId"]: item["evidence"] for item in snapshot_fixture_evidence(conn, second)}
            current = second_rows[10]
            self.assertEqual(second_rows[13]["source"]["exportId"], 6)
            self.assertEqual(detailed_match(conn, 13, career_id=1, season_index=0,
                                            as_of_import_sequence=2)["exportId"], 6)
            self.assertEqual(current["state"], "complete")
            self.assertEqual(current["careerId"], 1)
            self.assertEqual(current["source"]["sourceSnapshotId"], 2)
            home = {indicator["key"]: indicator for indicator in current["teams"][0]["indicators"]}
            self.assertEqual(home["expected_assists"]["value"], 0)
            self.assertEqual(home["expected_assists"]["state"], "available")
            self.assertEqual(home["expected_goals_derived"]["value"], 1.7)
            self.assertEqual(home["expected_goals_derived"]["origin"], "derived")
            away = {indicator["key"]: indicator for indicator in current["teams"][1]["indicators"]}
            self.assertEqual(away["expected_assists"]["state"], "absent")
        finally:
            conn.close()

    def test_position_provenance_never_substitutes_natural_position(self):
        evidence = fixture_evidence(
            {"id": 5, "career_id": 1, "season_index": 0}, 10,
            performances=[{"player_ea_id": 7, "primary_position": "ST"},
                          {"player_ea_id": 8, "primary_position": "CM", "actual_position": "CAM",
                           "actual_position_source": "career_playerlastmatchhistory_latest_match",
                           "observedPositionBackfill": {"snapshotId": 3}}],
        )
        self.assertIsNone(evidence["positions"][0]["observed"])
        self.assertEqual(evidence["positions"][0]["natural"], "ST")
        self.assertEqual(evidence["positions"][1]["sourceSnapshotId"], 3)

    def test_player_detail_respects_selected_import_sequence(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript("""
                CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                    import_sequence INTEGER,career_date TEXT);
                CREATE TABLE fixtures(id INTEGER,fixture_key TEXT,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
                CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,date TEXT,
                    competition_name TEXT,home_team_name TEXT,away_team_name TEXT,
                    home_score INTEGER,away_score INTEGER,home_penalties INTEGER,away_penalties INTEGER);
                CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                    linkage_confidence REAL,superseded_by_export_id INTEGER,linkage_status TEXT,export_status TEXT);
                CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,team_index INTEGER,stats_json TEXT);
                INSERT INTO snapshots VALUES (1,1,0,1,'2025-08-01'),(2,1,0,2,'2025-08-02');
                INSERT INTO fixtures VALUES (10,'a',100,200),(11,'b',100,200);
                INSERT INTO match_stat_exports VALUES
                    (1,10,1,1,1.0,NULL,'linked','complete_participant_export'),
                    (2,11,1,2,1.0,NULL,'linked','complete_participant_export');
                INSERT INTO match_player_detailed_stats VALUES
                    (1,7,0,'{"expected_assists":0}'),(2,7,0,'{"expected_assists":5}');
            """)
            early = detailed_player_matches(conn, 1, 7, as_of_import_sequence=1)
            self.assertEqual([item["fixtureId"] for item in early], [10])
            self.assertEqual(early[0]["stats"]["expected_assists"], 0)
        finally:
            conn.close()


class SnapshotDeltaEvidenceTests(unittest.TestCase):
    def test_missing_endpoint_does_not_create_ovr_potential_or_wage_delta(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript("""
                CREATE TABLE snapshots(id INTEGER,career_id INTEGER,managed_team_ea_id INTEGER);
                CREATE TABLE roster_states(snapshot_id INTEGER,team_ea_id INTEGER,player_ea_id INTEGER,jersey_number INTEGER);
                CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,
                    overall INTEGER,potential INTEGER,team_ea_id INTEGER,team_name TEXT,
                    primary_position TEXT,contract_valid_until TEXT);
                CREATE TABLE contract_states(snapshot_id INTEGER,player_ea_id INTEGER,wage INTEGER,duration_months INTEGER);
                CREATE TABLE season_stat_states(snapshot_id INTEGER,represented_team_ea_id INTEGER,player_ea_id INTEGER,
                    display_name TEXT,appearances INTEGER,goals INTEGER,assists INTEGER,average_rating REAL);
                CREATE TABLE team_league_states(snapshot_id INTEGER,team_ea_id INTEGER);
                CREATE TABLE loan_states(snapshot_id INTEGER,player_ea_id INTEGER,parent_team_ea_id INTEGER,loan_team_ea_id INTEGER);
                INSERT INTO snapshots VALUES (1,1,100),(2,1,100);
                INSERT INTO roster_states VALUES (1,100,7,9),(2,100,7,9);
                INSERT INTO player_states VALUES
                    (1,7,'Player',NULL,70,100,'A','ST',NULL),
                    (2,7,'Player',75,NULL,100,'A','ST',NULL);
                INSERT INTO contract_states VALUES (1,7,NULL,12),(2,7,0,12);
            """)

            class Query(HistoryQueryMixin):
                state = SimpleNamespace(database=SimpleNamespace(connect=lambda: conn))
                _fixture_rows = staticmethod(lambda *args, **kwargs: [])

            change = Query()._compare(1, 1, 2)["changedPlayers"][0]
            self.assertIsNone(change["overall_delta"])
            self.assertIsNone(change["potential_delta"])
            self.assertIsNone(change["wage_delta"])
            self.assertEqual(change["delta_source"]["fromSnapshotId"], 1)
        finally:
            conn.close()


class CommissionCoverageTests(unittest.TestCase):
    def test_team_profile_uses_paired_passes_and_reports_field_sample(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript("""
                CREATE TABLE snapshots(id INTEGER,career_id INTEGER,managed_team_ea_id INTEGER,
                    season_index INTEGER,career_date TEXT,managed_team_name TEXT,import_sequence INTEGER);
                CREATE TABLE fixtures(id INTEGER,career_id INTEGER,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
                CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,date TEXT,
                    home_team_name TEXT,away_team_name TEXT,home_score INTEGER,away_score INTEGER,
                    managed_team_involved INTEGER,is_completed INTEGER);
                CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                    team0_ea_id INTEGER,team1_ea_id INTEGER,linkage_status TEXT,export_status TEXT,
                    superseded_by_export_id INTEGER);
                CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
                INSERT INTO snapshots VALUES (1,1,100,0,'2025-08-01','A',1);
                INSERT INTO fixtures VALUES (10,1,100,200),(11,1,100,300);
                INSERT INTO fixture_observations VALUES
                    (1,10,'2025-08-02','A','B',1,0,1,1),
                    (1,11,'2025-08-03','A','C',0,0,1,1);
                INSERT INTO match_stat_exports VALUES
                    (1,10,1,1,100,200,'linked','complete_participant_export',NULL),
                    (2,11,1,1,100,300,'linked','complete_participant_export',NULL);
                INSERT INTO match_team_detailed_stats VALUES
                    (1,0,100,'{"passes":10,"passes_completed":8}'),
                    (1,1,200,'{"passes":12}'),
                    (2,0,100,'{"passes":20}'),
                    (2,1,300,'{"passes":15}');
            """)
            profile = analyze_team_identity(conn, 1, 1)
            self.assertEqual(profile["detailed_matches"], 2)
            self.assertEqual(profile["metrics"]["passes_per_match"], 15)
            self.assertEqual(profile["metrics"]["pass_accuracy_pct"], 80)
            self.assertEqual(profile["metric_coverage"]["pass_accuracy_pct"],
                             {"covered_matches": 1, "completed_matches": 2})
        finally:
            conn.close()
