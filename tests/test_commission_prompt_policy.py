"""Regression tests for Atlas commission prompt coherence and managed-team identity."""
import unittest
import json
import sqlite3
import tempfile
from pathlib import Path

from scripts.audit_commission_reports import audit_database, evaluate_report

from atlas.commission import REPORT_VERSION, _validate_report_item
from atlas.commission_prompt_policy import (
    FORMATION_SLOTS, REASONING_POLICY, build_system_prompt, claim_signature, compatible_formations,
    is_generic_claim, report_focus, report_subject,
)


class ReportSubjectTests(unittest.TestCase):
    def test_away_fixture_identifies_the_managed_club_not_opponent(self):
        context = {
            "career_id": 9, "managed_team": "Plymouth Argyle", "managed_team_ea_id": 1929,
            "mode": "match", "facts": [{"id": "match", "value": {
                "fixture_id": 125, "home": "Exeter City", "away": "Plymouth Argyle",
                "managed_team_side": "away", "managed_team_ea_id": 1929,
                "opponent_ea_id": 33}}],
        }
        subject = report_subject(context)
        self.assertEqual(subject["managed_team_name"], "Plymouth Argyle")
        self.assertEqual(subject["managed_team_ea_id"], 1929)
        self.assertEqual(subject["opponent_team_name"], "Exeter City")
        self.assertEqual(subject["managed_team_side"], "away")
        self.assertEqual(subject["opponent_team_ea_id"], 33)

    def test_home_fixture_preserves_opponent_and_selected_player(self):
        ctx = {
            "managed_team": "Sheffield United", "managed_team_ea_id": 1794,
            "mode": "match_player",
            "facts": [
                {"id": "match", "value": {
                    "home": "Sheffield United", "away": "Watford",
                    "managed_team_side": "home", "opponent_ea_id": 1795}},
                {"id": "selected_match_player", "value": {
                    "player_ea_id": 12345, "name": "Selected Defender"}}],
        }
        subject = report_subject(ctx)
        self.assertEqual(subject["managed_team_name"], "Sheffield United")
        self.assertEqual(subject["opponent_team_name"], "Watford")
        self.assertEqual(subject["selected_player_ea_id"], 12345)
        self.assertEqual(subject["selected_player_name"], "Selected Defender")

    def test_mode_specific_prompts_do_not_mix_match_and_player_instructions(self):
        individual = build_system_prompt("Brazilian Portuguese", "Analyze player", "player")
        match = build_system_prompt("Brazilian Portuguese", "Analyze match", "match")
        next_fixture = build_system_prompt("Brazilian Portuguese", "Prepare next match", "next_match")
        self.assertIn("ACCUMULATED PLAYER:", individual)
        self.assertNotIn("opponent shot-volume cohorts", individual)
        self.assertNotIn("pooled across earlier opponents", individual)
        self.assertIn("MATCH:", match)
        self.assertNotIn("UPCOMING MATCH:", match)
        self.assertIn("UPCOMING MATCH:", next_fixture)
        self.assertIn("allowed_formations", next_fixture)
        self.assertIn("SPORTING ANALYSIS CONTRACT", individual)
        self.assertIn("Brazilian Portuguese", individual)

    def test_policy_explicitly_forbids_opponent_advice_and_boilerplate(self):
        self.assertIn("ONLY club being advised", REASONING_POLICY)
        self.assertIn("without asserting", REASONING_POLICY)
        self.assertIn("Avoid boilerplate", REASONING_POLICY)
        self.assertGreaterEqual(REPORT_VERSION, 32)


class FocusTests(unittest.TestCase):
    def test_selects_material_pre_match_deviations_with_comparable_samples(self):
        context = {
            "mode": "match",
            "facts": [{"id": "match_comparisons", "value": [
                {"metric_key": "shots", "metric": "Finalizações",
                 "current_match": 12, "season_average": 8, "last_five_average": 7,
                 "difference_vs_season": 4, "difference_vs_last_five": 5,
                 "reference_samples": {"season": 9, "last_five": 5},
                 "interpretation_direction": "attempt_volume_only", "unit": "chutes"},
                {"metric_key": "goals_against", "metric": "Gols sofridos",
                 "current_match": 3, "season_average": 1, "last_five_average": 0.5,
                 "difference_vs_season": 2, "difference_vs_last_five": 2.5,
                 "reference_samples": {"season": 9, "last_five": 5},
                 "interpretation_direction": "lower_is_favorable", "unit": "gols"},
                {"metric_key": "tackles", "metric": "Desarmes",
                 "current_match": 5, "season_average": None, "last_five_average": 4,
                 "difference_vs_season": None, "difference_vs_last_five": 1,
                 "reference_samples": {"season": 0, "last_five": 1},
                 "interpretation_direction": "event_count_only", "unit": "eventos"},
            ]}],
        }
        priorities = report_focus(context)
        self.assertEqual(len(priorities), 2)
        self.assertEqual(priorities[0]["metric"], "Gols sofridos")
        self.assertEqual(priorities[0]["difference"], 2.5)
        self.assertEqual(priorities[0]["interpretation_direction"], "lower_is_favorable")
        self.assertTrue(all(item["fact_refs"] == ["match_comparisons"] for item in priorities))

    def test_does_not_make_a_trend_out_of_one_prior_match(self):
        context = {"mode": "match", "facts": [
            {"id": "match_comparisons", "value": [{
                "metric_key": "npk_expected_goals", "metric": "NPK-xG",
                "current_match": 2.4, "last_five_average": 1.1,
                "difference_vs_last_five": 1.3,
                "reference_samples": {"last_five": 1, "season": 1},
            }]},
            {"id": "matchstats", "value": [
                {"team_ea_id": 190, "stats": {"npk_expected_goals": 2.4}}]},
            {"id": "match", "value": {"managed_team_ea_id": 190}},
        ]}
        priorities = report_focus(context)
        self.assertEqual(len(priorities), 1)
        self.assertEqual(priorities[0]["fact_refs"], ["match", "matchstats"])
        self.assertNotIn("difference", priorities[0])

    def test_player_focus_keeps_player_refs(self):
        context = {"mode": "player", "facts": [
            {"id": "player_summary", "value": {
                "player_ea_id": 110, "season_rating": 7.0,
                "recent_rating": 7.4, "sample": {"usable": True}}},
            {"id": "player_position_peers", "value": {"players": []}},
        ]}
        focus = report_focus(context)
        self.assertEqual(focus[0]["player_ea_id"], 110)
        self.assertEqual(focus[0]["fact_refs"], ["player_summary"])


class ShapeCompatibilityTests(unittest.TestCase):
    def _squad(self, positions):
        return [{"player_ea_id": index + 1, "position": pos}
                for index, pos in enumerate(positions)]

    def test_valid_eleven_has_conservative_supported_shape(self):
        squad = self._squad(["GK", "LB", "CB", "CB", "RB",
                             "CM", "CM", "CM", "LW", "ST", "RW"])
        self.assertIn("4-3-3", compatible_formations(squad))

    def test_counts_cannot_create_unavailable_fullbacks(self):
        # Eleven players and enough generic defenders, but no LB/RB.
        squad = self._squad(["GK", "CB", "CB", "CB", "CB",
                             "CM", "CM", "CM", "LW", "ST", "RW"])
        self.assertNotIn("4-3-3", compatible_formations(squad))

    def test_duplicate_player_id_cannot_fill_two_positions(self):
        squad = self._squad(["GK", "LB", "CB", "CB", "RB",
                             "CM", "CM", "CM", "LW", "ST", "RW"])
        squad[-1]["player_ea_id"] = squad[-2]["player_ea_id"]
        self.assertNotIn("4-3-3", compatible_formations(squad))

    def test_ten_or_unregistered_players_produce_no_shape(self):
        squad = self._squad(["GK", "LB", "CB", "CB", "RB",
                             "CM", "CM", "CM", "LW", "ST"])
        self.assertEqual(compatible_formations(squad), [])
        self.assertEqual(compatible_formations([{"player_ea_id": 1, "position": None}]), [])
        self.assertEqual(len(FORMATION_SLOTS["4-3-3"]), 11)


class NonGenericInsightsTests(unittest.TestCase):
    def test_generic_summary_is_rejected_and_literal_duplicate_detected(self):
        self.assertTrue(is_generic_claim("A equipe jogou bem.", "summary"))
        self.assertFalse(is_generic_claim(
            "O Plymouth produziu 2.4 NPK-xG e concedeu 0.7, acima e abaixo do padrão anterior, respectivamente.",
            "summary"))
        self.assertEqual(claim_signature("O Plymouth marcou dois gols!"),
                         claim_signature("o plymouth marcou dois gols."))

    def test_upcoming_match_never_advises_the_opponent(self):
        context = {"mode": "next_match", "managed_team": "Sheffield United",
                   "managed_team_ea_id": 10, "facts": [
                       {"id": "match", "value": {
                           "home": "Sheffield United", "away": "Watford",
                           "managed_team_ea_id": 10, "managed_team_side": "home"}}]}
        opponent_claim = {"text": "Watford should improve defensive transitions.",
                          "kind": "hypothesis", "limitations": "No spatial or tactical data.",
                          "fact_refs": ["match"]}
        self.assertFalse(_validate_report_item(
            context, "next_match", opponent_claim, {"match"}, section="recommendations"))


    def test_empty_boilerplate_is_rejected(self):
        for text in ("Manter acompanhamento", "Monitorar o desempenho do time.",
                     "Continuar em observação", "Improve team performance",
                     "Seguir el seguimiento del equipo"):
            with self.subTest(text=text):
                self.assertTrue(is_generic_claim(text, "recommendations"))
                claim = {"text": text, "kind": "inference",
                         "limitations": "", "fact_refs": ["player_summary"]}
                self.assertFalse(_validate_report_item(
                    {"mode": "player", "facts": [{"id": "player_summary", "value": {}}]},
                    "player", claim, {"player_summary"}, section="recommendations"))

    def test_concrete_follow_up_is_not_blocked(self):
        text = ("O jogador registrou 2 assistências em 7 partidas; acompanhar "
                "as próximas atuações antes de alterar sua função.")
        self.assertFalse(is_generic_claim(text, "recommendations"))
        claim = {"text": text, "kind": "inference",
                 "limitations": "", "fact_refs": ["player_summary"]}
        self.assertTrue(_validate_report_item(
            {"mode": "player", "facts": [
                {"id": "player_summary", "value": {
                    "appearances": 7, "metrics": {"assists": 2}}}]},
            "player", claim, {"player_summary"}, section="recommendations"))


class StoredReportAuditTests(unittest.TestCase):
    def test_flags_wrong_team_recommendation_generic_and_repetition(self):
        payload = {"mode": "next_match", "review_required": True,
                   "fact_catalog": [{"id": "match", "value": {
                       "managed_team_side": "home", "managed_team_ea_id": 1929,
                       "home": "Plymouth Argyle", "away": "Exeter City"}}],
                   "report": {
                       "summary": {"text": "A equipe jogou bem.", "kind": "inference",
                                   "fact_refs": ["match"], "model_generated": False},
                       "observations": [
                           {"text": "Manter acompanhamento", "fact_refs": ["match"]},
                           {"text": "Manter acompanhamento", "fact_refs": ["match"]}],
                       "recommendations": [
                           {"text": "Exeter City should improve its defensive transitions.",
                            "fact_refs": ["match"]}],
                   }}
        result = evaluate_report(payload)
        self.assertEqual(result["flags"]["generic_claims"], 3)
        self.assertEqual(result["flags"]["duplicate_claims"], 1)
        self.assertEqual(result["flags"]["opponent_targeted_recommendations"], 1)
        self.assertEqual(result["flags"]["deterministic_summary_fallback"], 1)
        self.assertEqual(result["flags"]["review_required"], 1)

    def test_database_audit_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "atlas.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE technical_commission_report_cache(
                    career_id INTEGER, snapshot_id INTEGER, mode TEXT, scope_key TEXT,
                    payload_json TEXT)""")
                conn.execute("INSERT INTO technical_commission_report_cache VALUES(?,?,?,?,?)",
                             (7, 20, "player", "player:100", json.dumps({
                                 "mode": "player", "fact_catalog": [
                                     {"id": "player_summary", "value": {"player_ea_id": 100}}],
                                 "report": {"summary": {
                                     "text": "A equipe jogou bem.", "fact_refs": ["player_summary"],
                                     "model_generated": False}}})))
            before = path.stat().st_mtime_ns
            outcome = audit_database(path, career_id=7)
            self.assertEqual(outcome["scanned"], 1)
            self.assertEqual(outcome["flags"]["deterministic_summary_fallback"], 1)
            self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
