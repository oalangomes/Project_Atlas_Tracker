"""Regression tests for individual report sporting relevance, not just numeric truth."""
from __future__ import annotations

import copy
import unittest

from atlas.commission import REPORT_VERSION, _report_source_hash, _validate_report_item
from atlas.commission_prompt_policy import build_system_prompt, report_focus
from atlas.commission_role_policy import player_role, prompt_evidence, role_relevance_conflict


def fact_map(context):
    return {item["id"]: item["value"] for item in context["facts"]}


def keeper_context(mode="match_player"):
    participant = {
        "player_ea_id": 10, "name": "Goalkeeper", "team_ea_id": 1929,
        "registered_position": "GK", "observed_position": "GK",
        "observed_position_source": "career_playermatchratinghistory_position",
        "minutes": 90, "rating": 7.3,
        "stats": {
            "saves": 4, "shots_against": 5, "goals_conceded": 1,
            "passes": 21, "passes_completed": 17,
            "dribbles": 3, "dribbles_completed": 2,
            "npk_expected_goals": 1.4, "game_rating": 7.3,
        },
    }
    if mode == "match_player":
        return {
            "mode": "match_player", "managed_team": "Plymouth Argyle",
            "managed_team_ea_id": 1929, "career_id": 1, "season_index": 1,
            "report_version": REPORT_VERSION, "language": "pt-BR",
            "facts": [
                {"id": "selected_match_player", "value": participant},
                {"id": "match_players", "value": [
                    participant,
                    {"player_ea_id": 11, "name": "Striker Teammate", "team_ea_id": 1929,
                     "registered_position": "ST", "stats": {"dribbles": 7}},
                    {"player_ea_id": 12, "name": "Other Keeper", "team_ea_id": 1929,
                     "registered_position": "GK", "stats": {"saves": 2, "dribbles": 1}},
                    {"player_ea_id": 13, "name": "Opponent Keeper", "team_ea_id": 111,
                     "registered_position": "GK", "stats": {"saves": 4}},
                ]},
                {"id": "pre_match_player_context", "value": [
                    {"player_ea_id": 10, "stats": {
                        "saves": 6, "passes": 18, "dribbles": 9}},
                ]},
            ],
        }
    return {
        "mode": "player", "managed_team": "Plymouth Argyle",
        "managed_team_ea_id": 1929, "career_id": 1, "season_index": 1,
        "report_version": REPORT_VERSION, "language": "pt-BR",
        "facts": [
            {"id": "player_summary", "value": {
                "player_ea_id": 10, "display_name": "Goalkeeper", "position": "GK",
                "sample": {"usable": True, "label": "Amostra utilizável"},
                "minutes": 720, "metrics": {
                    "saves": 32, "goals_conceded": 5,
                    "passes": 214, "npk_expected_goals": 0.45, "dribbles": 8}}},
            {"id": "player_position_peers", "value": {
                "group": "Goleiro", "players": [
                    {"player_ea_id": 11, "registered_position": "GK",
                     "metrics": {"saves": 12, "dribbles": 2, "goals_per90": 1}}]}},
            {"id": "player_matchstats", "value": [
                {"date": "2025-10-01", "stats": {
                    "saves": 3, "passes": 20, "npk_goals": 1, "game_rating": 7.2}}
            ]},
        ],
    }


class KeeperRoleContextTests(unittest.TestCase):
    def test_goalkeeper_role_is_resolved_from_trusted_match_position(self):
        role = player_role(keeper_context())
        self.assertEqual(role["role"], "goalkeeper")
        self.assertEqual(role["position_source"], "trusted_observed_position")
        self.assertEqual(role["available_metrics"]["saves"], 4)
        self.assertEqual(role["available_metrics"]["goals_conceded"], 1)
        self.assertNotIn("dribbles", role["priority_metrics"])
        self.assertNotIn("npk_expected_goals", role["available_metrics"])

    def test_position_focused_projection_retains_original_facts_for_validation(self):
        context = keeper_context()
        original = copy.deepcopy(context)
        narrowed = prompt_evidence(context)
        self.assertEqual(context, original, "Do not mutate the Atlas facts/cache basis")
        selected = fact_map(narrowed)["selected_match_player"]
        self.assertEqual(selected["stats"]["saves"], 4)
        self.assertEqual(selected["stats"]["passes_completed"], 17)
        self.assertNotIn("dribbles", selected["stats"])
        self.assertNotIn("npk_expected_goals", selected["stats"])
        self.assertEqual([p["player_ea_id"] for p in fact_map(narrowed)["match_players"]],
                         [10, 12])
        self.assertEqual(fact_map(narrowed)["pre_match_player_context"][0]["stats"],
                         {"saves": 6, "passes": 18})
        self.assertEqual(fact_map(context)["selected_match_player"]["stats"]["dribbles"], 3)

    def test_accumulated_goalkeeper_excludes_outfield_numbers_but_preserves_samples(self):
        context = keeper_context("player")
        slim = prompt_evidence(context)
        facts = fact_map(slim)
        self.assertEqual(facts["player_summary"]["sample"]["label"], "Amostra utilizável")
        self.assertEqual(facts["player_summary"]["metrics"]["saves"], 32)
        self.assertNotIn("npk_expected_goals", facts["player_summary"]["metrics"])
        self.assertEqual(facts["player_position_peers"]["players"][0]["metrics"], {"saves": 12})
        self.assertEqual(facts["player_matchstats"][0]["stats"], {
            "saves": 3, "passes": 20, "game_rating": 7.2})

    def test_goalkeeper_dribbling_claim_is_rejected_even_if_dribble_count_is_true(self):
        context = keeper_context()
        valid = {fact["id"] for fact in context["facts"]}
        for section, text in (
            ("observations", "O goleiro registrou 3 dribles na partida."),
            ("strengths", "Os 3 dribles mostram sua principal qualidade."),
            ("recommendations", "Treinar dribles para melhorar a contribuição ofensiva."),
            ("development_areas", "Dribbling precisa ser prioridade."),
            ("training_suggestions", "Priorizar exercícios de drible."),
            ("summary", "O goleiro teve seu destaque em 3 dribles."),
        ):
            with self.subTest(section=section):
                item = {"text": text, "kind": "inference", "limitations": "",
                        "fact_refs": ["selected_match_player"]}
                reasons = []
                self.assertFalse(_validate_report_item(
                    context, "match_player", item, valid,
                    section=section, rejection_reasons=reasons))
                self.assertIn("irrelevant_player_role_metric", reasons)

    def test_keeper_can_still_discuss_saves_and_passes(self):
        context = keeper_context()
        valid = {fact["id"] for fact in context["facts"]}
        claim = {"text": "O goleiro realizou 4 defesas e completou 17 passes.",
                 "kind": "fact", "limitations": "", "fact_refs": ["selected_match_player"]}
        reasons = []
        self.assertTrue(_validate_report_item(
            context, "match_player", claim, valid, section="observations",
            rejection_reasons=reasons), reasons)

    def test_english_and_spanish_outfield_priorities_rejected(self):
        ctx = keeper_context("player")
        for text in ("Improve the goalkeeper's dribbling.",
                     "El portero debería priorizar los regates y los goles esperados.",
                     "Goleiro deve focar em finalizações.",
                     "O goleiro deve melhorar o xG."):
            # Regates is not a supported dribble synonym; xG is covered by
            # goalkeeping context. Other labels remain protected by prompt rules.
            if "regates" in text:
                self.assertTrue(role_relevance_conflict(ctx, text))
            else:
                self.assertTrue(role_relevance_conflict(ctx, text))

    def test_unverified_position_is_not_guessed(self):
        ctx = keeper_context("player")
        fact_map(ctx)["player_summary"]["position"] = None
        role = player_role(ctx)
        self.assertEqual(role["role"], "unknown")
        self.assertEqual(role["available_metrics"], {})
        self.assertFalse(role_relevance_conflict(ctx, "O jogador realizou 1 drible."))

    def test_trusted_observed_position_overrides_registered_position(self):
        ctx = keeper_context()
        selected = fact_map(ctx)["selected_match_player"]
        selected["observed_position"] = "CAM"
        self.assertEqual(player_role(ctx)["role"], "attacking_midfielder")
        self.assertFalse(role_relevance_conflict(ctx, "O jogador fez um drible."))
        selected["observed_position_source"] = "unverified"
        self.assertEqual(player_role(ctx)["role"], "goalkeeper")

    def test_role_profile_is_explicitly_a_prompt_lens_not_an_extra_fact(self):
        ctx = keeper_context("player")
        ctx["role_analysis"] = player_role(ctx)
        focus = report_focus(ctx)
        self.assertEqual(focus[0]["position_role"], "goalkeeper")
        self.assertIn("saves", focus[0]["available_role_metrics"])
        self.assertNotIn("dribbles", focus[0]["available_role_metrics"])
        self.assertNotIn("role_analysis", focus[0]["fact_refs"])
        self.assertIn("goalkeeper", build_system_prompt("Brazilian Portuguese", "Player review", "player"))
        self.assertGreaterEqual(REPORT_VERSION, 34)

    def test_source_hash_changes_if_role_lens_changes(self):
        ctx = keeper_context()
        ctx["role_analysis"] = player_role(ctx)
        first = _report_source_hash(ctx, 1, "match_player", "fixture:10:player:10")
        ctx["role_analysis"]["position"] = "CB"
        second = _report_source_hash(ctx, 1, "match_player", "fixture:10:player:10")
        self.assertNotEqual(first, second)

    def test_team_report_does_not_filter_goalkeeper_statistics_from_matchstats(self):
        ctx = keeper_context()
        ctx["mode"] = "match"
        ctx["facts"].append({"id": "matchstats", "value": [
            {"team_ea_id": 1929, "stats": {"shots": 13, "dribbles_completed": 7}}]})
        projected = prompt_evidence(ctx)
        self.assertEqual(projected, ctx)
        self.assertIsNone(player_role(ctx))


if __name__ == "__main__":
    unittest.main()
