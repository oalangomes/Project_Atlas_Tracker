"""Regression tests for Atlas commission prompt coherence and managed-team identity."""
import unittest

from atlas.commission import REPORT_VERSION, _validate_report_item
from atlas.commission_prompt_policy import (
    FORMATION_SLOTS, REASONING_POLICY, compatible_formations,
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
        text = ("Revisar a queda de passes-chave por 90 nos últimos cinco jogos "
                "antes de alterar a função de meia central.")
        self.assertFalse(is_generic_claim(text, "recommendations"))
        claim = {"text": text, "kind": "inference",
                 "limitations": "", "fact_refs": ["player_matchstats"]}
        self.assertTrue(_validate_report_item(
            {"mode": "player", "facts": [
                {"id": "player_matchstats", "value": [
                    {"stats": {"key_passes": 5}}]}]},
            "player", claim, {"player_matchstats"}, section="recommendations"))


if __name__ == "__main__":
    unittest.main()
