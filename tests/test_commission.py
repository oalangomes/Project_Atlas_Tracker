import unittest
import sqlite3
import io
import json
import time
from pathlib import Path
from unittest.mock import patch

from atlas.commission import (analyze_players, assess_sample, get_commission, get_commission_report,
                              get_cached_commission_report, get_commission_report_job, ollama_analysis,
                              queue_auto_reports_for_imported_snapshots, start_commission_report_job,
                              _commission_note, _claim_has_structural_conflict, _validate_report_item, _prior_match_context)


class CommissionMetricTests(unittest.TestCase):
    def test_commission_note_is_localized_and_only_calls_a_first_recorded_win_historical(self):
        context = {"mode": "match", "language": "pt-BR", "managed_team": "Plymouth Argyle", "facts": [
            {"id": "match", "value": {"completed": True, "managed_team_side": "home", "managed_score": 4,
                                       "opponent_score": 0, "home": "Plymouth Argyle", "away": "Everton"}},
            {"id": "opponent_history", "value": {"previous_meetings": 1, "previous_wins": 0}},
        ]}
        note = _commission_note(context)
        self.assertIn("grande vitória", note["text"])
        self.assertIn("primeiro triunfo registrado", note["text"])
        self.assertEqual(note["fact_refs"], ["match", "opponent_history"])

        context["language"] = "en-GB"
        self.assertIn("first recorded victory", _commission_note(context)["text"])
        context["facts"][1]["value"]["previous_wins"] = 1
        self.assertNotIn("history", _commission_note(context)["text"].casefold())

    def test_report_validation_allows_labelled_inference_but_rejects_source_conflicts(self):
        context = {"mode": "match", "managed_team": "Plymouth Argyle", "facts": [{"id": "match", "value": {
            "completed": True, "managed_team_side": "home", "managed_score": 4,
            "opponent_score": 0, "home": "Plymouth Argyle", "away": "Everton"}}]}
        self.assertFalse(_claim_has_structural_conflict(context, "match", "Plymouth Argyle won 4–0."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Plymouth Argyle lost 0–4."))
        self.assertFalse(_claim_has_structural_conflict(context, "match", "The scoreline alone does not establish territorial dominance."))

    def test_report_validation_rejects_numbers_absent_from_cited_facts(self):
        context = {"mode": "match", "facts": [{"id": "matchstats", "value": {"npk_expected_goals": 2.4}}]}
        valid_ids = {"matchstats"}
        supported = {"text": "The team registered 2.4 NPK-xG.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        invented = {"text": "The team registered 9.8 NPK-xG.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertTrue(_validate_report_item(context, "match", supported, valid_ids))
        self.assertFalse(_validate_report_item(context, "match", invented, valid_ids))

    def test_twelve_reproducible_intelligence_scenarios_keep_labelled_supported_claims(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "commission_intelligence_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["fixture_type"], "synthetic_validator_cases_not_live_model_outputs")
        self.assertEqual(len(fixture["cases"]), 12)
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                context = {"mode": "match", "facts": [{"id": fact_id, "value": {"synthetic_supported_values": case.get("supported_numbers", [])}} for fact_id in case["facts"]]}
                claim = {"text": case["text"], "kind": case["kind"], "limitations": case["limitations"], "fact_refs": case["facts"]}
                self.assertTrue(_validate_report_item(context, "match", claim, set(case["facts"])))
        hypothesis = next(case for case in fixture["cases"] if case["kind"] == "hypothesis")
        context = {"mode": "match", "facts": [{"id": fact_id, "value": {"synthetic_supported_values": hypothesis.get("supported_numbers", [])}} for fact_id in hypothesis["facts"]]}
        claim = {"text": hypothesis["text"], "kind": "hypothesis", "limitations": "", "fact_refs": hypothesis["facts"]}
        self.assertFalse(_validate_report_item(context, "match", claim, set(hypothesis["facts"])))

    def test_hub_sample_thresholds_are_preserved(self):
        self.assertFalse(assess_sample(299, 3)["usable"])
        self.assertFalse(assess_sample(300, 2)["usable"])
        self.assertTrue(assess_sample(300, 3)["usable"])
        self.assertFalse(assess_sample(449, 4)["reliable"])
        self.assertTrue(assess_sample(450, 5)["reliable"])

    def test_recent_form_uses_last_five_valid_rows_weighted_by_minutes(self):
        performances = [
            {"player_ea_id": 7, "fixture_key": str(i), "date": f"2025-09-{i:02d}", "rating": float(i), "minutes_played": 90}
            for i in range(1, 7)
        ]
        performances.append({"player_ea_id": 7, "fixture_key": "cameo", "date": "2025-09-30", "rating": 10.0, "minutes_played": 5})
        report = analyze_players([{"ea_player_id": 7, "display_name": "Player", "primary_position": "ST"}], performances)
        player = report["players"][0]
        self.assertEqual(player["recent_appearances"], 5)
        self.assertEqual(player["recent_rating"], 4.0)
        self.assertEqual(player["season_rating"], 3.5)
        self.assertEqual(player["minutes"], 545)
        self.assertEqual(player["hierarchy"], None)
        self.assertIsNone(player["goals"])

    def test_recorded_goal_makes_a_short_cameo_a_valid_form_appearance(self):
        report = analyze_players(
            [{"ea_player_id": 7, "display_name": "Player", "primary_position": "ST"}],
            [{"player_ea_id": 7, "fixture_key": "short-goal", "date": "2025-09-01", "rating": 8.0, "minutes_played": 5}],
            [{"player_ea_id": 7, "fixture_key": "short-goal", "minutes": 5,
              "stats": {"npk_goals": 1}}],
        )
        player = report["players"][0]
        self.assertEqual(player["valid_form_games"], 1)
        self.assertEqual(player["recent_rating"], 8.0)

    def test_hierarchy_is_not_inferred_from_appearances(self):
        report = analyze_players(
            [{"ea_player_id": 7, "display_name": "Player", "primary_position": "ST"}],
            [{"player_ea_id": 7, "fixture_key": str(i), "date": f"2025-09-{i:02d}", "rating": 7.0, "minutes_played": 90} for i in range(1, 6)],
        )
        self.assertEqual(report["players"][0]["sample"]["label"], "Amostra confiável")
        self.assertEqual(report["players"][0]["hierarchy_label"], "N/D — não registrada no Atlas")
        self.assertEqual(report["players"][0]["recommendation"], "Manter acompanhamento")

    def test_matchstats_metrics_are_partial_and_never_fill_missing_xg(self):
        stats = {"npk_goals": 2, "assists": 1, "shots": 5, "shots_on_target": 3,
                 "passes": 20, "passes_completed": 17, "npk_expected_goals": None,
                 "expected_assists": 0.4, "game_rating": 7.2}
        report = analyze_players([{"ea_player_id": 7, "display_name": "Player", "primary_position": "ST"}], [],
                                 [{"player_ea_id": 7, "minutes": 90, "rating": 7.2, "stats": stats}],
                                 {"detailed_matches": 1, "completed_team_matches": 5})
        player = report["players"][0]
        self.assertEqual(player["metrics"]["npk_goals"], 2)
        self.assertIsNone(player["metrics"]["npk_expected_goals"])
        self.assertEqual(player["metrics"]["expected_assists"], 0.4)
        self.assertEqual(report["coverage"]["detailed_matches"], 1)
        self.assertEqual(player["metrics"]["sample"]["label"], "Amostra muito curta (90–179 min) — não conclusiva")

    def test_function_cohort_uses_observed_match_position_not_roster_position(self):
        player_rows = [{"ea_player_id": 7, "display_name": "Player", "primary_position": "ST"}]
        details = [{"player_ea_id": 7, "minutes": 90, "rating": 7.0, "match_position": "GK",
                    "position": "Goleiro", "stats": {"npk_goals": 0}}]
        report = analyze_players(player_rows, [], details, {})
        self.assertEqual(report["function_comparisons"][0]["position"], "Goleiro")
        self.assertEqual(report["position_comparisons"][0]["position"], "ST")

    def test_ollama_fails_to_fallback_when_offline_without_raising(self):
        result = ollama_analysis({"players": []}, timeout=0.01)
        self.assertFalse(result["available"])
        self.assertTrue(result["fallback"])

    def test_ollama_signal_is_revalidated_and_text_comes_from_atlas_facts(self):
        payload = {"coverage": {}, "players": [{"player_ea_id": 7, "display_name": "Player", "position": "ST",
            "minutes": 450, "appearances": 5, "season_rating": 7.0, "recent_rating": 7.5,
            "sample": {"usable": True, "reliable": True}, "goals": 3, "assists": 1,
            "metrics": {"npk_goals": 3, "assists": 1, "npk_expected_goals": 2.4}}]}
        content = {"observations": [{"player_ea_id": "7", "signal": "goals_above_xg"}]}
        response = io.BytesIO(json.dumps({"message": {"content": json.dumps(content)}}).encode())
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: None
        with patch("atlas.commission.ollama_models", return_value={"available": True, "models": ["local"]}), \
             patch("atlas.commission.urllib.request.urlopen", return_value=response):
            result = ollama_analysis(payload)
        self.assertTrue(result["available"])
        self.assertEqual(result["observations"][0]["text"], "Gols (3) acima do NPK-xG registrado (2.40) no recorte coberto.")

    def test_snapshot_cache_is_idempotent_and_career_scoped(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE careers(id INTEGER PRIMARY KEY);
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,managed_team_ea_id INTEGER,
                season_index INTEGER,career_date TEXT,managed_team_name TEXT,managed_completed_fixture_count INTEGER);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,
                primary_position TEXT,team_ea_id INTEGER);
            CREATE TABLE player_match_performances(snapshot_id INTEGER,player_ea_id INTEGER,fixture_key TEXT,
                date TEXT,rating REAL,minutes_played INTEGER,actual_position TEXT,actual_position_source TEXT,raw_json TEXT);
            CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                export_status TEXT,linkage_status TEXT,superseded_by_export_id INTEGER,team0_ea_id INTEGER,team1_ea_id INTEGER);
            CREATE TABLE fixtures(id INTEGER,fixture_key TEXT);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,is_completed INTEGER,managed_team_involved INTEGER,date TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,minutes_played INTEGER,
                game_rating REAL,stats_json TEXT,team_index INTEGER);
            INSERT INTO careers VALUES(1);
            INSERT INTO snapshots VALUES(10,1,1794,0,'2025-09-30','Sheffield Utd',5);
            INSERT INTO player_states VALUES(10,7,'Player','ST',1794);
        """)
        for day in range(1, 6):
            conn.execute(
                "INSERT INTO player_match_performances VALUES(10,7,?,?,?,?,?,?,?)",
                (str(day), f"2025-09-{day:02d}", 7.0, 90, "ST", None, '{"managed_team_id":"1794"}'),
            )
        first = get_commission(conn, 1, 10)
        second = get_commission(conn, 1, 10)
        self.assertEqual(first, second)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM technical_commission_cache").fetchone()[0], 1)
        conn.execute("INSERT INTO player_match_performances VALUES(10,7,'6','2025-09-06',8.0,60,'ST',NULL,'{\"managed_team_id\":\"1794\"}')")
        refreshed = get_commission(conn, 1, 10)
        self.assertEqual(refreshed["players"][0]["appearances"], 6)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM technical_commission_cache").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            get_commission(conn, 2, 10)
        conn.close()

    def test_dynamic_match_report_is_career_scoped_cited_and_cached(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE careers(id INTEGER PRIMARY KEY);
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,managed_team_ea_id INTEGER,
                season_index INTEGER,career_date TEXT,managed_team_name TEXT,import_sequence INTEGER);
            CREATE TABLE fixtures(id INTEGER PRIMARY KEY,fixture_key TEXT,home_team_ea_id INTEGER,
                away_team_ea_id INTEGER,competition_object_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,fixture_key TEXT,
                is_completed INTEGER,managed_team_involved INTEGER,date TEXT,competition_name TEXT,
                home_team_name TEXT,away_team_name TEXT,home_score INTEGER,away_score INTEGER,managed_team_result TEXT);
            CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                external_export_id TEXT,linkage_confidence REAL,linkage_status TEXT,export_status TEXT,superseded_by_export_id INTEGER);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,team_index INTEGER,
                minutes_played INTEGER,game_rating REAL,stats_json TEXT);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,primary_position TEXT,team_ea_id INTEGER);
            CREATE TABLE player_match_performances(snapshot_id INTEGER,player_ea_id INTEGER,fixture_key TEXT,
                date TEXT,rating REAL,minutes_played INTEGER,actual_position TEXT,actual_position_source TEXT,raw_json TEXT);
            INSERT INTO careers VALUES(1);
            INSERT INTO snapshots VALUES(48,1,1929,1,'2025-10-25','Plymouth Argyle',48);
            INSERT INTO fixtures VALUES(1408,'fixture-1408',100,1929,3);
            INSERT INTO fixture_observations VALUES(48,1408,'fixture-1408',1,1,'2025-10-25',
                'League One','Plymouth Argyle','Everton',4,0,'W');
            INSERT INTO match_stat_exports VALUES(1,1408,1,48,'export-1',1.0,'linked','complete_participant_export',NULL);
            INSERT INTO match_team_detailed_stats VALUES(1,0,100,'{"npk_expected_goals":0.4,"goals_conceded":4,"shots":5}');
            INSERT INTO match_team_detailed_stats VALUES(1,1,1929,'{"npk_expected_goals":3.1,"goals_conceded":0,"shots":20}');
        """)
        content = {
            "summary": {"text": "Plymouth scored four from 3.1 recorded NPK-xG; the score alone does not establish territorial dominance.",
                        "kind": "inference", "limitations": "No spatial or possession data is exported.",
                        "fact_refs": ["match", "matchstats"]},
            "observations": [{"text": "The result was 4–0, while recorded NPK-xG was 3.1 for Plymouth.",
                              "kind": "fact", "limitations": "", "fact_refs": ["match", "matchstats"]}],
            "recommendations": [{"text": "Review finishing decisions across the next few matches before changing the attacking approach.",
                                 "kind": "hypothesis", "limitations": "One match cannot establish a persistent finishing pattern.",
                                 "fact_refs": ["matchstats"]}],
            "strengths": [], "development_areas": [], "training_suggestions": [], "formation": None}
        response = io.BytesIO(json.dumps({"message": {"content": json.dumps(content)}}).encode())
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: None
        with patch("atlas.commission.ollama_models", return_value={"available": True, "models": ["local"]}), \
             patch("atlas.commission.urllib.request.urlopen", return_value=response) as call:
            first = get_commission_report(conn, 1, 48, "match", fixture_id=1408, model="local")
            second = get_commission_report(conn, 1, 48, "match", fixture_id=1408, model="local")
        self.assertTrue(first["available"])
        self.assertEqual(first["report"]["summary"]["fact_refs"], ["match", "matchstats"])
        self.assertIn("does not establish territorial dominance", first["report"]["summary"]["text"])
        self.assertEqual(first["report"]["observations"][0]["kind"], "fact")
        self.assertEqual(first["report"]["recommendations"][0]["kind"], "hypothesis")
        self.assertEqual(first["report"]["recommendations"][0]["limitations"], "One match cannot establish a persistent finishing pattern.")
        self.assertEqual(first["validation"]["interpretation_quality"], "not independently scored")
        self.assertNotIn("quality_score", first)
        self.assertNotIn("confidence_pct", first)
        self.assertIsNone(first["report"]["formation"])
        self.assertTrue(second["cached"])
        self.assertEqual(call.call_count, 1)
        conn.execute("INSERT INTO snapshots VALUES(49,1,1929,1,'2025-10-26','Plymouth Argyle',49)")
        conn.execute("INSERT INTO fixture_observations VALUES(49,1408,'fixture-1408',1,1,'2025-10-25','League One','Plymouth Argyle','Everton',4,0,'W')")
        saved = get_cached_commission_report(conn, 1, 49, "match", fixture_id=1408, model="local")
        self.assertEqual(saved["state"], "ready")
        self.assertTrue(saved["cached"])
        with patch("atlas.commission.ollama_models", side_effect=AssertionError("cache read must not call Ollama")):
            reused = get_commission_report(conn, 1, 49, "match", fixture_id=1408, model="local")
        self.assertTrue(reused["cached"])
        self.assertEqual(call.call_count, 1)
        with self.assertRaises(ValueError):
            get_commission_report(conn, 2, 48, "match", fixture_id=1408, model="local")
        conn.close()

    def test_pre_match_context_excludes_same_day_future_and_other_career_exports(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,import_sequence INTEGER);
            CREATE TABLE fixtures(id INTEGER PRIMARY KEY,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,managed_team_involved INTEGER,
                is_completed INTEGER,date TEXT,home_team_name TEXT,away_team_name TEXT,home_score INTEGER,away_score INTEGER);
            CREATE TABLE match_stat_exports(id INTEGER PRIMARY KEY,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                linkage_status TEXT,export_status TEXT,superseded_by_export_id INTEGER,team0_ea_id INTEGER,team1_ea_id INTEGER,
                external_export_id TEXT,linkage_confidence REAL);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,team_index INTEGER,
                minutes_played INTEGER,game_rating REAL,stats_json TEXT);
            INSERT INTO snapshots VALUES(100,1,10),(101,1,11),(200,2,10);
        """)
        # Same career and earlier date, but only this export predates the selected snapshot.
        rows = [
            (1, 1, 1, 100, '2025-10-01', 40, 50, 2),
            (2, 2, 1, 100, '2025-10-11', 40, 50, 99),
            (3, 3, 1, 100, '2025-10-10', 40, 50, 99),
            (4, 4, 1, 200, '2025-10-02', 40, 50, 99),
            (5, 5, 1, 101, '2025-10-03', 40, 50, 99),
        ]
        for export_id, fixture_id, career_id, snapshot_id, match_date, opponent_id, team_id, xg in rows:
            conn.execute("INSERT INTO fixtures VALUES(?,?,?)", (fixture_id, opponent_id, team_id))
            conn.execute("INSERT INTO fixture_observations VALUES(100,?,1,1,?,'Opponent','Managed',1,0)", (fixture_id, match_date))
            conn.execute("INSERT INTO match_stat_exports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (export_id, fixture_id, career_id, snapshot_id, 'linked', 'complete_participant_export', None,
                          opponent_id, team_id, f'exp-{export_id}', 1.0))
            conn.execute("INSERT INTO match_team_detailed_stats VALUES(?,?,?,?)", (export_id, 0, opponent_id, json.dumps({"npk_expected_goals": 0.2})))
            conn.execute("INSERT INTO match_team_detailed_stats VALUES(?,?,?,?)", (export_id, 1, team_id, json.dumps({"npk_expected_goals": xg, "shots": 8})))
        result = _prior_match_context(conn, 1, conn.execute("SELECT * FROM snapshots WHERE id=100").fetchone(),
                                      999, 50, '2025-10-10')
        self.assertEqual(result["lookback_matches"], 1)
        self.assertEqual(result["recent_five"][0]["fixture_id"], 1)
        self.assertEqual(result["season_to_date_reference"]["for"]["metrics_per_match"]["npk_expected_goals"], 2.0)
        conn.close()

    def test_dynamic_report_job_runs_without_blocking_the_request(self):
        started = start_commission_report_job(17, lambda: {"available": True, "report": {"summary": "ready"}})
        self.assertEqual(started["status"], "queued")
        for _ in range(100):
            job = get_commission_report_job(17, started["job_id"])
            if job["status"] == "complete":
                break
            time.sleep(0.01)
        self.assertEqual(job["status"], "complete")
        self.assertEqual(job["result"]["report"]["summary"], "ready")
        with self.assertRaises(ValueError):
            get_commission_report_job(18, started["job_id"])

    def test_auto_queue_only_targets_fixtures_newly_completed_in_an_import(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,import_sequence INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,managed_team_involved INTEGER,
                is_completed INTEGER,date TEXT);
            INSERT INTO snapshots VALUES(1,9,1),(2,9,2);
            INSERT INTO fixture_observations VALUES
                (1,101,1,1,'2025-09-01'),(1,102,1,0,'2025-09-08'),
                (2,101,1,1,'2025-09-01'),(2,102,1,1,'2025-09-08'),(2,103,1,1,'2025-09-15'),
                (2,104,0,1,'2025-09-16');
        """)
        class FakeDatabase:
            def connect(self):
                return conn
        class ImportResult:
            status = "imported"
            career_id = 9
            snapshot_id = 2
        scheduled = []
        with patch("atlas.commission.queue_auto_commission_reports", side_effect=lambda _db, career, fixture, snapshot: scheduled.append((career, fixture, snapshot)) or []):
            queue_auto_reports_for_imported_snapshots(FakeDatabase(), [ImportResult()])
        self.assertEqual(scheduled, [(9, 102, 2), (9, 103, 2)])
        conn.close()


if __name__ == "__main__":
    unittest.main()
