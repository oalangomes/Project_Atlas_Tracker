import unittest
import sqlite3
import io
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch
from atlas.db import ClosingConnection
from atlas.match_stats import detailed_match

from atlas.commission import (analyze_players, assess_sample, get_commission, get_commission_report,
                              get_cached_commission_report, get_commission_report_job, ollama_analysis,
                              queue_auto_reports_for_imported_snapshots, start_commission_report_job,
                              _commission_note, _claim_has_structural_conflict, _validate_report_item,
                              _report_item_metric_conflict, _prior_match_context,
                              _normalize_report_clarifications, _coach_can_answer_information_request,
                              _historical_report_tasks, _ensure_replay_schema,
                              run_retroactive_commission_reports, get_retroactive_commission_report_job,
                              REPORT_VERSION)


class _ReplayTestDatabase:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn


class CommissionReplayQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = _ReplayTestDatabase(Path(self.temp.name) / "replay.sqlite3")
        with self.database.connect() as conn:
            conn.executescript("""
                CREATE TABLE careers(id INTEGER PRIMARY KEY);
                CREATE TABLE snapshots(id INTEGER PRIMARY KEY);
                INSERT INTO careers VALUES(1);
                INSERT INTO snapshots VALUES(10);
                INSERT INTO snapshots VALUES(11);
            """)
            _ensure_replay_schema(conn)
            conn.execute("""INSERT INTO technical_commission_replay_runs
                (job_id,career_id,season_index,snapshot_id,model,language,report_version,status,total_tasks)
                VALUES('job',1,0,10,'local','pt-BR',?,'queued',2)""", (REPORT_VERSION,))
            conn.executemany("""INSERT INTO technical_commission_replay_tasks
                (job_id,sequence,snapshot_id,import_sequence,season_index,event_date,fixture_id,stage,mode,
                 player_ea_id,label,status) VALUES('job',?,?,?,?,?,?,?,?,?,?,?)""", [
                (1,10,1,0,'2025-08-01',100,'match','match',None,'match 100','pending'),
                (2,11,2,0,'2025-08-03',101,'match_player','match_player',7,'player 7 match 101','pending'),
            ])

    def tearDown(self):
        self.temp.cleanup()

    def test_replay_runs_tasks_sequentially_and_persists_results(self):
        from unittest.mock import call
        success = {'available': True, 'source_hash': 'facts', 'report': {'summary': {'text': 'ok'}},
                   'review_required': False}
        with patch('atlas.commission.ollama_models', return_value={'available': True, 'models': ['local']}), \
             patch('atlas.commission.get_cached_commission_report', return_value={'state': 'missing'}), \
             patch('atlas.commission.get_commission_report', side_effect=[success.copy(), success.copy()]) as generate:
            run_retroactive_commission_reports(self.database, 1, 'job', 'pt-BR', 'local')
        self.assertEqual([item.args[3] for item in generate.call_args_list], ['match', 'match_player'])
        progress = get_retroactive_commission_report_job(self.database, 1, 'job')
        self.assertEqual(progress['status'], 'complete')
        self.assertEqual(progress['completed_tasks'], 2)
        self.assertEqual(progress['generated'], 2)
        with self.database.connect() as conn:
            self.assertEqual([row['status'] for row in conn.execute(
                "SELECT status FROM technical_commission_replay_tasks WHERE job_id='job' ORDER BY sequence")],
                ['completed', 'completed'])

    def test_offline_replay_preserves_pending_checkpoint_for_resume(self):
        with patch('atlas.commission.ollama_models', return_value={'available': False, 'models': []}):
            run_retroactive_commission_reports(self.database, 1, 'job', 'pt-BR', 'local')
        paused = get_retroactive_commission_report_job(self.database, 1, 'job')
        self.assertEqual(paused['status'], 'paused_offline')
        self.assertEqual(paused['pending'], 2)
        success = {'available': True, 'source_hash': 'facts', 'report': {}, 'review_required': False}
        with patch('atlas.commission.ollama_models', return_value={'available': True, 'models': ['local']}), \
             patch('atlas.commission.get_cached_commission_report', return_value={'state': 'missing'}), \
             patch('atlas.commission.get_commission_report', side_effect=[success.copy(), success.copy()]) as generate:
            run_retroactive_commission_reports(self.database, 1, 'job', 'pt-BR', 'local')
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(get_retroactive_commission_report_job(self.database, 1, 'job')['status'], 'complete')

    def test_transient_task_failure_retries_once_before_advancing(self):
        failed = {'available': False, 'message': 'temporary failure'}
        success = {'available': True, 'source_hash': 'facts', 'report': {}, 'review_required': False}
        with patch('atlas.commission.ollama_models', return_value={'available': True, 'models': ['local']}), \
             patch('atlas.commission.get_cached_commission_report', return_value={'state': 'missing'}), \
             patch('atlas.commission.get_commission_report',
                   side_effect=[failed.copy(), success.copy(), success.copy()]) as generate:
            run_retroactive_commission_reports(self.database, 1, 'job', 'pt-BR', 'local')
        self.assertEqual(generate.call_count, 3)
        with self.database.connect() as conn:
            attempts = conn.execute("SELECT attempts FROM technical_commission_replay_tasks WHERE sequence=1").fetchone()[0]
        self.assertEqual(attempts, 2)
        self.assertEqual(get_retroactive_commission_report_job(self.database, 1, 'job')['status'], 'complete')


class CommissionMetricTests(unittest.TestCase):
    def test_detailed_match_never_selects_an_export_from_another_season(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,season_index INTEGER,import_sequence INTEGER);
            CREATE TABLE match_stat_exports(id INTEGER PRIMARY KEY,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                superseded_by_export_id INTEGER,external_export_id TEXT,export_status TEXT,linkage_confidence REAL,
                team0_ea_id INTEGER,team1_ea_id INTEGER);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,team_index INTEGER,game_rating REAL,
                minutes_played INTEGER,player_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,primary_position TEXT,team_ea_id INTEGER);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
            INSERT INTO snapshots VALUES(1,1,0,1),(2,1,1,2);
            INSERT INTO match_stat_exports VALUES(1,55,1,1,NULL,'old','complete_participant_export',1.0,100,1929);
            INSERT INTO match_stat_exports VALUES(2,55,1,2,NULL,'current','complete_participant_export',1.0,100,1929);
            INSERT INTO match_team_detailed_stats VALUES(1,0,100,'{}'),(1,1,1929,'{}');
            INSERT INTO match_team_detailed_stats VALUES(2,0,100,'{}'),(2,1,1929,'{}');
        """)
        report = detailed_match(conn, 55, career_id=1, as_of_import_sequence=2, season_index=1)
        self.assertEqual(report["exportId"], 2)
        conn.close()

    def test_historical_tasks_use_first_observed_snapshot_and_do_not_order_same_day_as_history(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,season_index INTEGER,import_sequence INTEGER,
                career_date TEXT,managed_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,date TEXT,
                managed_team_involved INTEGER,is_completed INTEGER);
            INSERT INTO snapshots VALUES
                (10,1,0,1,'2025-08-01',1929),(11,1,0,2,'2025-08-01',1929),
                (12,1,0,3,'2025-08-03',1929),(13,1,1,4,'2026-07-01',1929);
            INSERT INTO fixture_observations VALUES
                (10,100,'2025-08-01',1,1),
                (11,100,'2025-08-01',1,1),(11,101,'2025-08-01',1,1),
                (12,100,'2025-08-01',1,1),(12,101,'2025-08-01',1,1),(12,102,'2025-08-03',1,1),
                (13,200,'2026-07-01',1,1);
        """)
        participants = {100: [7], 101: [8], 102: [7, 8]}
        with patch("atlas.commission._managed_player_ids_for_fixture", side_effect=lambda _c, _career, _snap, fixture, _team: participants[fixture]):
            tasks = _historical_report_tasks(conn, 1, 0)
        first_per_fixture = {task["fixture_id"]: task for task in tasks if task["stage"] == "match"}
        self.assertEqual([task["fixture_id"] for task in first_per_fixture.values()], [100, 101, 102])
        self.assertEqual([first_per_fixture[key]["snapshot_id"] for key in (100, 101, 102)], [10, 11, 12])
        self.assertEqual([task["stage"] for task in tasks[:4]], ["match", "match_player", "team_checkpoint", "player_checkpoint"])
        same_day = [task for task in tasks if task["event_date"] == "2025-08-01"]
        self.assertTrue(all(task["snapshot_id"] in {10, 11} for task in same_day))
        self.assertFalse(any(task["fixture_id"] == 200 for task in tasks))
        conn.close()

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

    def test_match_report_never_recommends_to_the_opponent_or_misattributes_its_metrics(self):
        context = {"mode": "match", "facts": [
            {"id": "match", "value": {"managed_team_ea_id": 1929, "managed_team_side": "home",
                "home": "Plymouth Argyle", "away": "Telstar", "opponent_ea_id": 1979}},
            {"id": "match_comparisons", "value": [{"entity": "Plymouth Argyle", "metric_key": "expected_goals_derived",
                "current_match": 1.8, "season_average": 1.4}]},
        ]}
        opponent_recommendation = {"text": "O Telstar deve investigar como melhorar a eficiência ofensiva, pois seu xG foi alto.",
            "kind": "hypothesis", "limitations": "Os dados desta partida não identificam a causa.", "fact_refs": ["match_comparisons"]}
        wrong_entity_inference = {"text": "O Telstar criou muitas chances, com xG elevado.", "kind": "inference",
            "limitations": "", "fact_refs": ["match_comparisons"]}
        unsupported_volume = {"text": "Plymouth converted its volume of chances into victory.", "kind": "inference",
            "limitations": "", "fact_refs": ["match"]}
        self.assertFalse(_validate_report_item(context, "match", opponent_recommendation,
            {"match", "match_comparisons"}, section="recommendations"))
        self.assertFalse(_validate_report_item(context, "match", wrong_entity_inference,
            {"match", "match_comparisons"}, section="observations"))
        self.assertFalse(_validate_report_item(context, "match", unsupported_volume,
            {"match"}, section="observations"))

    def test_team_style_requires_sample_and_hypothesis_label(self):
        claim = {"text": "The team style appears to rely on quick transitions.", "kind": "inference",
                 "limitations": "Aggregate counts cannot prove the tactical cause.", "fact_refs": ["team_statistical_profile"]}
        small = {"mode": "team_identity", "facts": [{"id": "team_statistical_profile", "value": {
            "sample_sufficient": False, "metrics": {"passes_per_match": 140}}}]}
        sufficient = {"mode": "team_identity", "facts": [{"id": "team_statistical_profile", "value": {
            "sample_sufficient": True, "metrics": {"passes_per_match": 140}}}]}
        self.assertFalse(_validate_report_item(small, "team_identity", claim, {"team_statistical_profile"}))
        self.assertFalse(_validate_report_item(sufficient, "team_identity", claim, {"team_statistical_profile"}))
        hypothesis = {**claim, "kind": "hypothesis"}
        self.assertTrue(_validate_report_item(sufficient, "team_identity", hypothesis, {"team_statistical_profile"}))

    def test_match_player_claims_are_bound_to_selected_player_row(self):
        context = {"mode": "match_player", "facts": [
            {"id": "selected_match_player", "value": {"player_ea_id": 9, "name": "Keeper",
                "stats": {"npk_goals": 0, "goals_derived": 0, "goals_conceded": 0, "passes": 3,
                          "passes_completed": 3, "pass_accuracy_pct_derived": 100, "minutes_played": 91,
                          "shots_against": 3, "saves": 1}}},
        ]}
        wrong = {"text": "O goleiro completou 3 passes e 100% de precisão, mas permitiu 2 gols.",
                 "kind": "inference", "limitations": "", "fact_refs": ["selected_match_player"]}
        supported = {"text": "O jogador completou 3 passes com 100% de precisão em 91 minutos.",
                     "kind": "fact", "limitations": "", "fact_refs": ["selected_match_player"]}
        self.assertFalse(_validate_report_item(context, "match_player", wrong, {"selected_match_player"}))
        self.assertTrue(_validate_report_item(context, "match_player", supported, {"selected_match_player"}))

    def test_match_player_statistics_get_exact_selected_player_citation(self):
        context = {"mode": "match_player", "managed_team": "Plymouth Argyle", "facts": [
            {"id": "selected_match_player", "value": {"player_ea_id": 9, "name": "Bim Pepple",
                "stats": {"npk_goals": 1, "npk_expected_goals": 0.981496, "minutes_played": 33,
                          "passes": 2, "passes_completed": 1, "pass_accuracy_pct_derived": 50.0}}},
            {"id": "matchstats", "value": [{"team_name": "Plymouth Argyle", "stats": {"passes": 130}}]},
            {"id": "match_players", "value": [{"name": "Bim Pepple", "team_name": "Plymouth Argyle"},
                                                   {"name": "Other Player", "team_name": "Plymouth Argyle"}]},
        ]}
        valid = {"selected_match_player", "matchstats", "match_players"}
        claim = {"text": "Bim Pepple marcou 1 gol com 0.98 xG em 33 minutos.", "kind": "fact",
                 "limitations": "", "fact_refs": ["matchstats"]}
        self.assertTrue(_validate_report_item(context, "match_player", claim, valid))
        self.assertIn("selected_match_player", claim["fact_refs"])
        wrong_player = {**claim, "text": "Other Player marcou 130 gols.", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match_player", wrong_player, valid))

    def test_accumulated_player_claims_use_its_own_summary_metrics(self):
        context = {"mode": "player", "facts": [{"id": "player_summary", "value": {
            "display_name": "Bim Pepple", "appearances": 7, "metrics": {
                "npk_goals": 2, "assists": 2, "shots": 10, "shot_accuracy_pct": 50.0}}}]}
        supported = {"text": "Bim scored 2 goals and 2 assists in 7 matches, with 50% shot accuracy.",
                     "kind": "fact", "limitations": "", "fact_refs": ["player_summary"]}
        wrong = {**supported, "text": "Bim scored 3 goals and 2 assists in 7 matches."}
        self.assertTrue(_validate_report_item(context, "player", supported, {"player_summary"}))
        self.assertFalse(_validate_report_item(context, "player", wrong, {"player_summary"}))

    def test_report_validation_rejects_unrecorded_match_timing_and_wrong_player_team(self):
        context = {"mode": "match", "facts": [
            {"id": "match", "value": {"event_timing_available": False, "home": "Exeter City", "away": "Plymouth Argyle", "managed_team_side": "away", "opponent_specific_history_available": False}},
            {"id": "match_players", "value": [{"name": "Joe Whitworth", "team_name": "Exeter City", "team_ea_id": 143}]},
        ]}
        self.assertTrue(_claim_has_structural_conflict(context, "match", "The goals came in the second half."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Bim Pepple marcou o segundo gol do Plymouth Argyle."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Plymouth should exploit the right flank."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Train the team in pressure situations."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "O Exeter City teve média de 147 passes nas últimas cinco partidas."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Monitorar a carga física para evitar lesões."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "Exeter had a recent decline. Limitations: insufficient longitudinal data to establish a clear trend."))
        self.assertTrue(_claim_has_structural_conflict(context, "match", "O goleiro do Argyle, Joe Whitworth, sofreu quatro gols."))
        self.assertFalse(_claim_has_structural_conflict(context, "match", "Joe Whitworth is listed for Exeter City."))

    def test_report_validation_rejects_wrong_home_away_and_named_metric_values(self):
        context = {"mode": "match", "facts": [
            {"id": "match", "value": {"event_timing_available": False, "home": "Exeter City", "away": "Plymouth Argyle"}},
            {"id": "matchstats", "value": [
                {"team_name": "Exeter City", "team_side": "home", "stats": {"pass_accuracy_pct_derived": 91.0, "shots_on_target": 3, "passes_under_pressure": 41, "pressure_pass_accuracy_pct": 97.6}},
                {"team_name": "Plymouth Argyle", "team_side": "away", "stats": {"pass_accuracy_pct_derived": 86.0, "shots_on_target": 8, "passes": 150, "passes_completed": 129, "saving_shots_on_target": 3}},
            ]},
            {"id": "match_players", "value": [
                {"name": "Ethan Brierley", "team_name": "Exeter City", "stats": {"pass_accuracy_pct_derived": 100.0}},
                {"name": "Charlie Cummins", "team_name": "Exeter City", "stats": {"pass_accuracy_pct_derived": 89.5}},
                {"name": "Joe Whitworth", "team_name": "Exeter City", "stats": {"passes_completed_under_pressure": 0}},
            ]},
        ]}
        valid_ids = {"match", "matchstats", "match_players"}
        wrong_side = {"text": "O time visitante Exeter City enfrentou Plymouth Argyle mandante.", "kind": "fact", "limitations": "", "fact_refs": ["match"]}
        self.assertFalse(_validate_report_item(context, "match", wrong_side, valid_ids))
        wrong_passes = {"text": "Exeter City teve 86% de precisão de passes.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match", wrong_passes, valid_ids))
        right_passes = {"text": "Exeter City teve 91% de precisão de passes.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertTrue(_validate_report_item(context, "match", right_passes, valid_ids))
        wrong_shots = {"text": "O Exeter City teve 4 chutes a gol.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match", wrong_shots, valid_ids))
        wrong_passes = {"text": "O Plymouth completou 150 passes.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        right_passes = {"text": "O Plymouth completou 129 passes.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        wrong_faced_shots = {"text": "O goleiro do Plymouth sofreu 8 tentativas no alvo.", "kind": "fact", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match", wrong_passes, valid_ids))
        self.assertTrue(_validate_report_item(context, "match", right_passes, valid_ids))
        self.assertFalse(_validate_report_item(context, "match", wrong_faced_shots, valid_ids))
        backwards_pressure = {"text": "O Exeter City deve melhorar a precisão dos passes sob pressão, pois completou 41 passes sob pressão com precisão de 97.6%.", "kind": "hypothesis", "limitations": "A inferência é limitada a esta partida.", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match", backwards_pressure, valid_ids))
        grouped = {"text": "Ethan Brierley e Charlie Cummins tiveram 100% de precisão de passes.", "kind": "fact", "limitations": "", "fact_refs": ["match_players"]}
        self.assertFalse(_validate_report_item(context, "match", grouped, valid_ids))
        wrong_pressure = {"text": "Joe Whitworth completou 2 passes concluídos sob pressão.", "kind": "fact", "limitations": "", "fact_refs": ["match_players"]}
        self.assertTrue(_report_item_metric_conflict(context, wrong_pressure))

    def test_report_requires_causal_match_claims_to_be_labelled_as_hypotheses(self):
        context = {"mode": "match", "facts": [{"id": "matchstats", "value": {"npk_expected_goals": 3.1}}]}
        inference = {"text": "A natural consequence of Plymouth's 3.1 xG.", "kind": "inference", "limitations": "", "fact_refs": ["matchstats"]}
        hypothesis = {**inference, "kind": "hypothesis", "limitations": "The data cannot establish that the chances caused the score."}
        self.assertFalse(_validate_report_item(context, "match", inference, {"matchstats"}))
        self.assertTrue(_validate_report_item(context, "match", hypothesis, {"matchstats"}))
        tactical = {"text": "The Exeter defence was vulnerable to direct attacks.", "kind": "inference", "limitations": "", "fact_refs": ["matchstats"]}
        self.assertFalse(_validate_report_item(context, "match", tactical, {"matchstats"}))

    def test_report_validation_checks_comparison_direction_and_period(self):
        context = {"mode": "match", "facts": [{"id": "match_comparisons", "value": [
            {"metric_key": "goals_against", "current_match": 1, "last_five_average": 0.6, "season_average": 0.8},
            {"metric_key": "goals_for", "current_match": 4, "last_five_average": 3.6, "season_average": 3.06},
        ]}]}
        refs = {"match_comparisons"}
        wrong = {"text": "Plymouth sofreu 1 gol, abaixo da média das últimas cinco partidas de 0.6.", "kind": "fact", "limitations": "", "fact_refs": ["match_comparisons"]}
        correct = {"text": "Plymouth marcou 4 gols, acima da média das últimas cinco partidas de 3.6.", "kind": "fact", "limitations": "", "fact_refs": ["match_comparisons"]}
        positive_goals_against = {"text": "Plymouth sofreu 1 gol, um desvio positivo de 0.2 em relação à média da temporada.", "kind": "inference", "limitations": "", "fact_refs": ["match_comparisons"]}
        self.assertFalse(_validate_report_item(context, "match", wrong, refs))
        self.assertTrue(_validate_report_item(context, "match", correct, refs))
        self.assertFalse(_validate_report_item(context, "match", positive_goals_against, refs))

    def test_match_recommendations_cannot_assign_work_to_an_opponent_player(self):
        context = {"mode": "match", "facts": [
            {"id": "match", "value": {"managed_team_ea_id": 1929}},
            {"id": "match_players", "value": [{"name": "Joe Whitworth", "team_ea_id": 143}]},
        ]}
        claim = {"text": "Avaliar a eficácia do goleiro Joe Whitworth.", "kind": "inference", "limitations": "", "fact_refs": ["match_players"]}
        self.assertTrue(_validate_report_item(context, "match", claim, {"match_players"}))
        self.assertFalse(_validate_report_item(context, "match", claim, {"match_players"}, section="recommendations"))

    def test_match_recommendation_cannot_treat_lower_xg_as_poor_finishing(self):
        context = {"mode": "match", "facts": [{"id": "match_comparisons", "value": [
            {"metric_key": "expected_goals_derived", "current_match": 3.4, "season_average": 3.8},
            {"metric_key": "finishing_delta", "current_match": 0.6, "season_average": 0.2},
        ]}]}
        claim = {"text": "Revisar a estratégia de finalização, pois o xG ficou abaixo da média da temporada.", "kind": "hypothesis", "limitations": "A amostra é de uma partida e não confirma uma tendência.", "fact_refs": ["match_comparisons"]}
        self.assertFalse(_validate_report_item(context, "match", claim, {"match_comparisons"}, section="recommendations"))

    def test_coach_clarifications_are_bounded_and_keep_question_provenance(self):
        cleaned = _normalize_report_clarifications([
            {"question": "What was the intended press?", "answer": "We pressed high after the opponent's first pass."},
            {"question": "Second question", "answer": "Second answer"},
            {"question": "Third question", "answer": "Third answer"},
            {"question": "Fourth question", "answer": "Fourth answer"},
            {"question": "Fifth question", "answer": "Fifth answer"},
            {"question": "Sixth question", "answer": "Sixth answer"},
            {"question": "Ignored", "answer": "The interface allows only six requests."},
        ])
        self.assertEqual(len(cleaned), 6)
        self.assertEqual(cleaned[0]["answer"], "We pressed high after the opponent's first pass.")
        with self.assertRaises(ValueError):
            _normalize_report_clarifications({"question": "bad shape"})

    def test_information_requests_are_for_coach_context_not_statistics(self):
        self.assertTrue(_coach_can_answer_information_request(
            "What defensive instruction did you give after halftime?", "This could change how the line adjustment is interpreted."))
        self.assertFalse(_coach_can_answer_information_request(
            "What is Exeter City's recent history against high-scoring teams?", "Recent history would contextualize the result."))
        self.assertFalse(_coach_can_answer_information_request(
            "Qual foi o desempenho de Owen Oseni nas últimas cinco partidas?", "A média ajudaria a avaliar sua atuação."))
        self.assertFalse(_coach_can_answer_information_request(
            "O treinador poderia fornecer instruções táticas sobre como melhorar a finalização?", "Isso ajudaria a planejar treinos."))

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
            INSERT INTO snapshots VALUES(9,1,1794,0,'2025-08-31','Sheffield Utd',0);
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
                'League One','Everton','Plymouth Argyle',0,4,'W');
            INSERT INTO match_stat_exports VALUES(1,1408,1,48,'export-1',1.0,'linked','complete_participant_export',NULL);
            INSERT INTO match_team_detailed_stats VALUES(1,0,100,'{"npk_expected_goals":0.4,"goals_conceded":4,"shots":5}');
            INSERT INTO match_team_detailed_stats VALUES(1,1,1929,'{"npk_expected_goals":3.1,"goals_conceded":0,"shots":20}');
        """)
        content = {
            "summary": {"text": "Plymouth scored four from 3.1 recorded NPK-xG; the score alone does not establish territorial dominance.",
                        "kind": "inference", "limitations": "No spatial or possession data is exported.",
                        "fact_refs": ["match", "matchstats"]},
            "observations": [
                {"text": "The result was 4–0, while recorded NPK-xG was 3.1 for Plymouth.",
                 "kind": "fact", "limitations": "", "fact_refs": ["match", "matchstats"]},
                {"text": "Plymouth Argyle conceded 4 goals.", "kind": "fact", "limitations": "",
                 "fact_refs": ["match"]},
                {"text": "Plymouth Argyle scored 4 goals.", "kind": "fact", "limitations": "",
                 "fact_refs": ["match"]},
            ],
            "recommendations": [{"text": "Review finishing decisions across the next few matches before changing the attacking approach.",
                                 "kind": "hypothesis", "limitations": "One match cannot establish a persistent finishing pattern.",
                                 "fact_refs": ["matchstats"]}],
            "strengths": [], "development_areas": [], "training_suggestions": [], "formation": None,
            "information_requests": [{"question": "Was the team instructed to press high?", "reason": "This would change how the interception count is interpreted."}]}
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
        self.assertTrue(any(item["text"] == "Plymouth Argyle scored 4 goals."
                            for item in first["report"]["observations"]))
        self.assertFalse(any(item["text"] == "Plymouth Argyle conceded 4 goals."
                             for item in first["report"]["observations"]))
        self.assertTrue(any("score_value_conflict" in item["reasons"]
                            for item in first["validation"]["rejected_claim_details"]))
        self.assertEqual(first["report"]["recommendations"][0]["kind"], "hypothesis")
        self.assertEqual(first["report"]["recommendations"][0]["limitations"], "One match cannot establish a persistent finishing pattern.")
        self.assertEqual(first["report"]["information_requests"], content["information_requests"])
        self.assertEqual(first["validation"]["interpretation_quality"], "not independently scored")
        self.assertNotIn("quality_score", first)
        self.assertNotIn("confidence_pct", first)
        self.assertIsNone(first["report"]["formation"])
        initial_body = json.loads(call.call_args.args[0].data.decode("utf-8"))
        initial_context = json.loads(initial_body["messages"][1]["content"])
        self.assertEqual(initial_context["report_subject"]["managed_team_name"], "Plymouth Argyle")
        self.assertEqual(initial_context["report_subject"]["opponent_team_name"], "Everton")
        self.assertEqual(initial_context["report_subject"]["managed_team_side"], "away")
        self.assertTrue(initial_context["analysis_focus"])
        self.assertIn("SPORTING ANALYSIS CONTRACT", initial_body["messages"][0]["content"])
        comparison_fact = next(item for item in initial_context["facts"] if item["id"] == "match_comparisons")
        self.assertTrue(all("unit" in item and "current_match" in item and "reference_samples" in item
                            for item in comparison_fact["value"]))
        self.assertTrue(second["cached"])
        self.assertEqual(call.call_count, 1)
        followup_response = io.BytesIO(json.dumps({"message": {"content": json.dumps(content)}}).encode())
        followup_response.__enter__ = lambda: followup_response
        followup_response.__exit__ = lambda *args: None
        clarifications = [{"question": "Was the team instructed to press high?", "answer": "Yes, after the first pass."}]
        with patch("atlas.commission.ollama_models", return_value={"available": True, "models": ["local"]}), \
             patch("atlas.commission.urllib.request.urlopen", return_value=followup_response) as followup_call:
            followup = get_commission_report(conn, 1, 48, "match", fixture_id=1408, model="local",
                                             clarifications=clarifications)
        request_body = json.loads(followup_call.call_args.args[0].data.decode("utf-8"))
        sent_context = json.loads(request_body["messages"][1]["content"])
        coach_fact = next(item for item in sent_context["facts"] if item["id"] == "coach_context")
        self.assertEqual(coach_fact["value"], clarifications)
        self.assertIn("not imported or independently verified", coach_fact["source"])
        self.assertTrue(followup["coach_context_received"])
        saved_followup = get_cached_commission_report(conn, 1, 48, "match", fixture_id=1408, model="local")
        self.assertEqual(saved_followup["state"], "ready")
        self.assertTrue(saved_followup["result"]["coach_context_received"])
        conn.execute("INSERT INTO snapshots VALUES(49,1,1929,1,'2025-10-26','Plymouth Argyle',49)")
        conn.execute("INSERT INTO fixture_observations VALUES(49,1408,'fixture-1408',1,1,'2025-10-25','League One','Everton','Plymouth Argyle',0,4,'W')")
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
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,career_id INTEGER,import_sequence INTEGER,season_index INTEGER);
            CREATE TABLE fixtures(id INTEGER PRIMARY KEY,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,managed_team_involved INTEGER,
                is_completed INTEGER,date TEXT,home_team_name TEXT,away_team_name TEXT,home_score INTEGER,away_score INTEGER);
            CREATE TABLE match_stat_exports(id INTEGER PRIMARY KEY,fixture_id INTEGER,career_id INTEGER,snapshot_id INTEGER,
                linkage_status TEXT,export_status TEXT,superseded_by_export_id INTEGER,team0_ea_id INTEGER,team1_ea_id INTEGER,
                external_export_id TEXT,linkage_confidence REAL);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,team_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,team_index INTEGER,
                minutes_played INTEGER,game_rating REAL,stats_json TEXT);
            INSERT INTO snapshots VALUES(100,1,10,1),(101,1,11,1),(200,2,10,1);
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
