"""Pre-match difficulty context must come from a prior career save snapshot."""
import json
import io
import sqlite3
import unittest
from unittest.mock import patch

from atlas.commission import (_competitive_match_observation, _unverified_competitive_claim,
                              _validate_report_item,
                              get_commission_report)
from atlas.commission_prompt_policy import report_focus
from atlas.match_competitive_context import pre_match_competitive_context


class MatchCompetitiveContextTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                                   import_sequence INTEGER,career_date TEXT);
            CREATE TABLE team_states(snapshot_id INTEGER,ea_team_id INTEGER,team_name TEXT,
                                     league_ea_id INTEGER,league_name TEXT);
            CREATE TABLE league_states(snapshot_id INTEGER,ea_league_id INTEGER,
                                       league_name TEXT,country_id INTEGER,level INTEGER);
            CREATE TABLE roster_states(snapshot_id INTEGER,team_ea_id INTEGER,player_ea_id INTEGER);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,team_ea_id INTEGER,
                                       overall INTEGER,primary_position TEXT);
            CREATE TABLE fixtures(id INTEGER,career_id INTEGER,home_team_ea_id INTEGER,away_team_ea_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,
                                              competition_name TEXT,date TEXT,is_completed INTEGER,
                                              home_team_name TEXT,away_team_name TEXT,
                                              home_score INTEGER,away_score INTEGER);
            INSERT INTO snapshots VALUES
                (1,1,1,1,'2025-09-20'),(2,1,1,2,'2025-09-23'),
                (3,1,1,3,'2025-09-30'),(4,2,1,4,'2025-09-22');
        """)
        for snapshot_id, own_overall, opponent_overall in ((1, 65, 79), (2, 99, 99), (3, 99, 99)):
            self.conn.executemany("INSERT INTO team_states VALUES(?,?,?,?,?)", [
                (snapshot_id, 1929, "Plymouth Argyle", 60, "EFL League One"),
                (snapshot_id, 9, "Liverpool", 13, "Premier League"),
            ])
            self.conn.executemany("INSERT INTO league_states VALUES(?,?,?,?,?)", [
                (snapshot_id, 60, "EFL League One", 14, 3),
                (snapshot_id, 13, "Premier League", 14, 1),
            ])
            for team_id, overall in ((1929, own_overall), (9, opponent_overall)):
                for index in range(16):
                    player_id = snapshot_id * 10000 + team_id * 20 + index
                    self.conn.execute("INSERT INTO roster_states VALUES(?,?,?)",
                                      (snapshot_id, team_id, player_id))
                    self.conn.execute("INSERT INTO player_states VALUES(?,?,?,?,?)",
                                      (snapshot_id, player_id, team_id, overall, "CM"))

    def tearDown(self):
        self.conn.close()

    def test_uses_strictly_prior_same_career_snapshot_and_withholds_unverified_fields(self):
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        result = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23",
                                               1929, 9, json.dumps({"match_group_id": 1}))
        self.assertTrue(result["available"])
        self.assertEqual(result["as_of_snapshot_id"], 1)
        self.assertEqual(result["managed_team"]["squad_average_overall"], 65)
        self.assertEqual(result["opponent"]["squad_average_overall"], 79)
        self.assertEqual(result["opponent_overall_gap"], 14)
        self.assertEqual(result["opponent"]["league_level"], 1)
        self.assertIsNone(result["opponent_table_position"])
        self.assertIsNone(result["competition_phase"])
        context = {"mode": "match", "language": "pt-BR", "managed_team": "Plymouth Argyle",
                   "facts": [{"id": "pre_match_competitive_context", "value": result}]}
        item = _competitive_match_observation(context)
        self.assertIn("79", item["text"])
        self.assertIn("65", item["text"])
        self.assertTrue(_validate_report_item(context, "match", item,
                                              {"pre_match_competitive_context"}, section="observations"))
        self.assertEqual(report_focus(context)[0]["fact_refs"], ["pre_match_competitive_context"])
        self.assertFalse(_unverified_competitive_claim(context, {
            "text": "Pleguezuelo foi 1º colocado em recuperações nesta partida.",
            "fact_refs": ["pre_match_competitive_context"]}))
        for unsupported in ("Liverpool era o 5º colocado na liga.",
                            "O encontro ocorreu nas quartas de final da copa.",
                            "Liverpool tinha overall médio 65 contra Plymouth Argyle."):
            claim = {"text": unsupported, "kind": "fact", "limitations": "",
                     "fact_refs": ["pre_match_competitive_context"]}
            reasons = []
            self.assertFalse(_validate_report_item(context, "match", claim,
                                                    {"pre_match_competitive_context"},
                                                    section="observations", rejection_reasons=reasons))
            self.assertIn("unverified_competitive_context", reasons)

    def test_no_prior_snapshot_or_partial_roster_does_not_invent_strength(self):
        first = self.conn.execute("SELECT * FROM snapshots WHERE id=1").fetchone()
        missing = pre_match_competitive_context(self.conn, 1, first, "2025-09-20", 1929, 9)
        self.assertFalse(missing["available"])
        self.assertEqual(missing["reason"], "no_prior_same_season_snapshot")
        self.conn.execute("DELETE FROM roster_states WHERE snapshot_id=1 AND team_ea_id=9 AND player_ea_id IN "
                          "(SELECT player_ea_id FROM roster_states WHERE snapshot_id=1 AND team_ea_id=9 LIMIT 6)")
        later = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        partial = pre_match_competitive_context(self.conn, 1, later, "2025-09-23", 1929, 9)
        self.assertIsNone(partial["opponent"]["squad_average_overall"])
        self.assertIsNone(partial["opponent_overall_gap"])
        observation = _competitive_match_observation({"mode": "match", "facts": [
            {"id": "pre_match_competitive_context", "value": partial}]})
        self.assertIn("Divisões registradas", observation["text"])
        self.assertNotIn("overall médio", observation["text"])

    def test_explicit_phase_name_is_used_but_numeric_group_is_not(self):
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        result = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23",
                                               1929, 9, json.dumps({"round_name": "Quarter-final"}))
        self.assertEqual(result["competition_phase"], "Quarter-final")

    def test_prior_league_fixtures_supply_rank_only_with_complete_coverage(self):
        self.conn.executemany("INSERT INTO team_states VALUES(?,?,?,?,?)", [
            (1, 10, "Team Ten", 13, "Premier League"),
            (1, 11, "Team Eleven", 13, "Premier League"),
            (1, 12, "Team Twelve", 13, "Premier League"),
        ])
        self.conn.executemany("INSERT INTO fixtures VALUES(?,?,?,?)", [
            (101, 1, 9, 10), (102, 1, 11, 12), (103, 2, 10, 9)])
        self.conn.executemany("INSERT INTO fixture_observations VALUES(?,?,?,?,?,?,?,?,?)", [
            (1, 101, "Premier League", "2025-09-20", 1, "Liverpool", "Team Ten", 3, 0),
            (1, 102, "Premier League", "2025-09-20", 1, "Team Eleven", "Team Twelve", 1, 0),
            (1, 103, "Premier League", "2025-09-20", 1, "Team Ten", "Liverpool", 10, 0),
        ])
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        ranked = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23", 1929, 9)
        self.assertEqual(ranked["opponent_table_position"], 1)
        self.assertEqual(ranked["opponent"]["league_table"]["team_count"], 4)
        self.assertEqual(ranked["table_position_status"],
                         "derived_from_prior_completed_league_fixtures")
        self.assertIn("posição 1 de 4", _competitive_match_observation({"mode": "match", "facts": [
            {"id": "pre_match_competitive_context", "value": ranked}]})["text"])
        context = {"mode": "match", "facts": [{"id": "pre_match_competitive_context", "value": ranked}]}
        wrong_rank = {"text": "Liverpool ocupava a posição 2 antes da partida.",
                      "kind": "fact", "limitations": "", "fact_refs": ["pre_match_competitive_context"]}
        reasons = []
        self.assertFalse(_validate_report_item(context, "match", wrong_rank,
                                                {"pre_match_competitive_context"},
                                                section="observations", rejection_reasons=reasons))
        self.assertIn("unverified_competitive_context", reasons)
        self.conn.execute("UPDATE fixture_observations SET home_score=0,away_score=0 WHERE snapshot_id=1")
        tied = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23", 1929, 9)
        self.assertIsNone(tied["opponent_table_position"])
        self.conn.execute("DELETE FROM fixture_observations WHERE fixture_id=102")
        incomplete = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23", 1929, 9)
        self.assertIsNone(incomplete["opponent_table_position"])

    def test_generated_match_report_keeps_verified_strength_context(self):
        snapshot = self.conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone()
        competitive = pre_match_competitive_context(self.conn, 1, snapshot, "2025-09-23", 1929, 9)
        context = {"mode": "match", "language": "pt-BR", "career_id": 1,
                   "season_index": 1, "managed_team": "Plymouth Argyle",
                   "managed_team_ea_id": 1929, "facts": [
                       {"id": "match", "value": {"fixture_id": 20, "home": "Liverpool",
                                                "away": "Plymouth Argyle", "managed_team_side": "away",
                                                "managed_team_ea_id": 1929, "opponent_ea_id": 9,
                                                "managed_score": 2, "opponent_score": 1,
                                                "score": [1, 2], "competition": "Carabao Cup"}},
                       {"id": "pre_match_competitive_context", "value": competitive},
                   ]}
        model_report = {"summary": {"text": "Plymouth Argyle venceu Liverpool por 2–1.",
                                    "kind": "fact", "limitations": "", "fact_refs": ["match"]},
                        "observations": [], "recommendations": [], "strengths": [],
                        "development_areas": [], "training_suggestions": [],
                        "information_requests": [], "formation": None}
        response = io.BytesIO(json.dumps({"message": {"content": json.dumps(model_report)}}).encode())
        with sqlite3.connect(":memory:") as cache, \
             patch("atlas.commission._briefing_facts", return_value=(
                 context, [fact["id"] for fact in context["facts"]], "fixture:20")), \
             patch("atlas.commission.ollama_models", return_value={"available": True, "models": ["local"]}), \
             patch("atlas.commission.urllib.request.urlopen", return_value=response):
            result = get_commission_report(cache, 1, 3, "match", fixture_id=20, model="local")
        observations = result["report"]["observations"]
        self.assertTrue(any("overall médio 79" in item["text"] and "Premier League" in item["text"]
                            for item in observations))


if __name__ == "__main__":
    unittest.main()
