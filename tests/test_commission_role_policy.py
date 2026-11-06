"""Regression tests for individual report sporting relevance, not just numeric truth."""
from __future__ import annotations

import copy
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

from atlas.commission import (REPORT_VERSION, _apply_match_player_fact_contract,
                              _deterministic_match_player_observations,
                              _match_player_team_comparison,
                              _report_source_hash, _validate_report_item,
                              get_commission_report)
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


def striker_match_context(peer_interceptions=(0, 1, 0, 1)):
    selected = {
        "player_ea_id": 20, "name": "Striker", "team_ea_id": 1929,
        "registered_position": "ST", "minutes": 90, "rating": 8.0,
        "stats": {"goals_derived": 1, "interceptions": 4, "passes": 12,
                  "passes_completed": 12, "pass_accuracy_pct_derived": 100,
                  "aerial_duels_attempted": 1, "aerial_duels_won": 0},
    }
    teammates = [
        {"player_ea_id": 21 + index, "team_ea_id": 1929,
         "registered_position": "CM" if index % 2 else "CB", "minutes": 90,
         "stats": {"interceptions": interceptions}}
        for index, interceptions in enumerate(peer_interceptions)
    ]
    opponent = {"player_ea_id": 90, "team_ea_id": 111, "registered_position": "ST",
                "minutes": 90, "stats": {"interceptions": 99}}
    return {
        "mode": "match_player", "managed_team": "Plymouth Argyle",
        "managed_team_ea_id": 1929, "career_id": 1, "season_index": 1,
        "report_version": REPORT_VERSION, "language": "pt-BR",
        "facts": [
            {"id": "match", "value": {"managed_team_ea_id": 1929, "managed_score": 3,
                                           "opponent_score": 1}},
            {"id": "selected_match_player", "value": selected},
            {"id": "match_players", "value": [selected, *teammates, opponent]},
        ],
    }


def winger_match_context():
    selected = {
        "player_ea_id": 30, "name": "Winger", "team_ea_id": 1929,
        "registered_position": "RM", "minutes": 63, "rating": 7.8,
        "stats": {"assists": 1, "key_passes": 1, "shots": 0, "passes": 7,
                  "passes_completed": 6, "pass_accuracy_pct_derived": 85.7,
                  "dribbles": 6, "dribbles_completed": 6, "dribble_success_pct_derived": 100,
                  "crosses_attempted": 3, "crosses_delivered": 3,
                  "cross_success_pct_derived": 100},
    }


    peers = [
        {"player_ea_id": 31, "team_ea_id": 1929, "registered_position": "RW",
         "minutes": 90, "stats": {"dribbles": 4, "dribbles_completed": 2,
                                    "dribble_success_pct_derived": 50,
                                    "crosses_attempted": 2, "crosses_delivered": 0,
                                    "cross_success_pct_derived": 0}},
        {"player_ea_id": 32, "team_ea_id": 1929, "registered_position": "LM",
         "minutes": 90, "stats": {"dribbles": 4, "dribbles_completed": 2,
                                    "dribble_success_pct_derived": 50,
                                    "crosses_attempted": 2, "crosses_delivered": 1,
                                    "cross_success_pct_derived": 50}},
    ]
    return {
        "mode": "match_player", "managed_team": "Plymouth Argyle",
        "managed_team_ea_id": 1929, "career_id": 1, "season_index": 1,
        "report_version": REPORT_VERSION, "language": "pt-BR",
        "facts": [
            {"id": "selected_match_player", "value": selected},
            {"id": "match_players", "value": [selected, *peers]},
        ],
    }


def keeper_context_with_opponent_xg():
    context = keeper_context()
    selected = fact_map(context)["selected_match_player"]
    selected["stats"].update({"saving_shots_on_target": 4, "goals_conceded": 1})
    context["facts"].extend([
        {"id": "match", "value": {"managed_team_ea_id": 1929, "managed_team_side": "home",
                                      "opponent_ea_id": 111, "home": "Plymouth Argyle",
                                      "away": "Exeter City"}},
        {"id": "matchstats", "value": [
            {"team_ea_id": 111, "team_name": "Exeter City", "stats": {
                "npk_expected_goals": 1.7, "expected_goals_derived": 2.4,
                "shots_on_target": 5}},
        ]},
    ])
    return context


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
                         [10])
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
                item = {"text": text, "kind": "fact", "limitations": "",
                        "fact_refs": ["selected_match_player"]}
                reasons = []
                self.assertFalse(_validate_report_item(
                    context, "match_player", item, valid,
                    section=section, rejection_reasons=reasons))
                expected_reason = ("match_player_fact_only" if section in {
                    "recommendations", "strengths", "development_areas", "training_suggestions"
                } else "irrelevant_player_role_metric")
                self.assertIn(expected_reason, reasons)

    def test_keeper_can_still_discuss_saves_and_passes(self):
        context = keeper_context()
        valid = {fact["id"] for fact in context["facts"]}
        claim = {"text": "O goleiro realizou 4 defesas e completou 17 passes.",
                 "kind": "fact", "limitations": "", "fact_refs": ["selected_match_player"]}
        reasons = []
        self.assertTrue(_validate_report_item(
            context, "match_player", claim, valid, section="observations",
            rejection_reasons=reasons), reasons)

    def test_goalkeeper_context_pairs_opponent_xg_with_same_match_outcomes(self):
        context = keeper_context_with_opponent_xg()
        role = player_role(context)
        signal = role["goalkeeper_match_context"]
        self.assertEqual(signal["opponent_xg"], 2.4)
        self.assertEqual(signal["opponent_xg_metric"], "expected_goals_derived")
        self.assertEqual(signal["opponent_shots_on_target"], 5)
        self.assertEqual(signal["goalkeeper_recorded_outcomes"]["saves"], 4)
        self.assertEqual(signal["goalkeeper_recorded_outcomes"]["goals_conceded"], 1)

        refs = {fact["id"] for fact in context["facts"]}
        claim = {"text": "O adversário registrou xG de 2,4; o goleiro fez 4 defesas e sofreu 1 gol.",
                 "kind": "fact", "limitations": "", "fact_refs": ["selected_match_player", "matchstats"]}
        reasons = []
        self.assertTrue(_validate_report_item(context, "match_player", claim, refs,
                                              section="observations", rejection_reasons=reasons), reasons)

        wrong_xg = {**claim, "text": "O adversário registrou xG de 1,2; o goleiro fez 4 defesas e sofreu 1 gol."}
        reasons = []
        self.assertFalse(_validate_report_item(context, "match_player", wrong_xg, refs,
                                               section="observations", rejection_reasons=reasons))

    def test_match_player_report_accepts_grounded_inference_and_rejects_development_advice(self):
        context = keeper_context()
        refs = {fact["id"] for fact in context["facts"]}
        fact = {"text": "O goleiro registrou 4 defesas nesta partida.", "kind": "fact",
                "limitations": "", "fact_refs": ["selected_match_player"]}
        reasons = []
        self.assertTrue(_validate_report_item(context, "match_player", fact, refs,
                                              section="observations", rejection_reasons=reasons), reasons)
        inference = {**fact,
                     "text": "As 4 defesas foram um dos sinais positivos desta atuação, junto de 17 passes completos.",
                     "kind": "inference"}
        reasons = []
        self.assertTrue(_validate_report_item(context, "match_player", inference, refs,
                                              section="observations", rejection_reasons=reasons), reasons)
        vague = {**inference, "text": "Atuação consistente na circulação e movimentação."}
        reasons = []
        self.assertFalse(_validate_report_item(context, "match_player", vague, refs,
                                               section="observations", rejection_reasons=reasons))
        self.assertIn("match_player_claim_needs_metrics", reasons)
        absolute = {**inference, "text": "Partida praticamente perfeita e incrível: 4 defesas."}
        reasons = []
        self.assertFalse(_validate_report_item(context, "match_player", absolute, refs,
                                               section="observations", rejection_reasons=reasons))
        self.assertIn("match_player_uncalibrated_absolute_verdict", reasons)
        advice_as_fact = {**fact, "text": "O goleiro deve focar em melhorar as saídas."}
        reasons = []
        self.assertFalse(_validate_report_item(
            context, "match_player", advice_as_fact, refs,
            section="observations", rejection_reasons=reasons))
        self.assertIn("match_player_advice_not_allowed", reasons)
        for section, kind, text in (
            ("observations", "inference", "O goleiro deveria melhorar as saídas."),
            ("recommendations", "fact", "Focar em melhorar as saídas."),
        ):
            with self.subTest(section=section, kind=kind):
                reasons = []
                self.assertFalse(_validate_report_item(
                    context, "match_player", {**fact, "kind": kind, "text": text}, refs,
                    section=section, rejection_reasons=reasons))
                self.assertTrue(any(reason in {"match_player_advice_not_allowed", "match_player_fact_only"}
                                    for reason in reasons), reasons)

    def test_match_player_schema_allows_four_observations_and_no_advice(self):
        keys = ("observations", "recommendations", "strengths", "development_areas",
                "training_suggestions", "information_requests")
        schema = {"properties": {
            "summary": {"properties": {"kind": {"enum": ["fact", "inference"]}}},
            **{key: {"maxItems": 8} for key in keys},
        }}
        claim = {"properties": {"kind": {"enum": ["fact", "inference"]}}}
        _apply_match_player_fact_contract(schema, claim)
        self.assertEqual(schema["properties"]["observations"]["maxItems"], 4)
        self.assertEqual(schema["properties"]["summary"]["properties"]["kind"]["enum"], ["fact", "inference"])
        self.assertEqual(claim["properties"]["kind"]["enum"], ["fact", "inference"])
        for key in keys[1:]:
            self.assertEqual(schema["properties"][key]["maxItems"], 0)

    def test_english_and_spanish_outfield_priorities_rejected(self):
        ctx = keeper_context("player")
        for text in ("Improve the goalkeeper's dribbling.",
                     "El portero debería priorizar los regates.",
                     "Goleiro deve focar em finalizações.",
                     "O goleiro deve melhorar o xG."):
            with self.subTest(text=text):
                self.assertTrue(role_relevance_conflict(ctx, text))

    def test_legitimate_shots_faced_are_not_treated_as_outfield_finishing(self):
        ctx = keeper_context()
        for text in ("O goleiro enfrentou 5 finalizações do adversário.",
                     "As finalizações sofridas exigiram 4 defesas.",
                     "O goleiro completou 17 passes e fez 4 defesas."):
            with self.subTest(text=text):
                self.assertFalse(role_relevance_conflict(ctx, text))

    def test_keeper_opponent_xg_is_allowed_only_as_sourced_match_context(self):
        ctx = keeper_context_with_opponent_xg()
        ctx["role_analysis"] = player_role(ctx)
        self.assertFalse(role_relevance_conflict(
            ctx, "O adversário teve xG de 2,4; o goleiro fez 4 defesas e sofreu 1 gol."))
        self.assertFalse(role_relevance_conflict(
            ctx, "O adversário teve xG de 2,4; o goleiro enfrentou 5 chutes no alvo."))
        self.assertTrue(role_relevance_conflict(ctx, "O goleiro teve xG de 2,4 nesta partida."))

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

    def test_match_player_prompt_contract_only_invalidates_match_player_cache(self):
        match_ctx = keeper_context()
        player_ctx = keeper_context("player")
        match_hash = _report_source_hash(match_ctx, 1, "match_player", "fixture:10:player:10")
        player_hash = _report_source_hash(player_ctx, 1, "player", "player:10")
        with patch("atlas.commission.MATCH_PLAYER_REPORT_CONTRACT", 7):
            self.assertNotEqual(match_hash, _report_source_hash(
                match_ctx, 1, "match_player", "fixture:10:player:10"))
            self.assertEqual(player_hash, _report_source_hash(player_ctx, 1, "player", "player:10"))

    def test_striker_cross_role_interceptions_are_a_deterministic_team_standout(self):
        ctx = striker_match_context()
        role = player_role(ctx)
        signals = role["cross_role_standouts"]
        self.assertEqual([item["metric_key"] for item in signals], ["interceptions"])
        self.assertEqual(signals[0]["observed_value"], 4)
        self.assertEqual(signals[0]["comparison_players"], 5)
        self.assertEqual(signals[0]["comparison_percentile"], 100.0)
        self.assertEqual(signals[0]["fact_refs"], ["selected_match_player", "match_players"])
        self.assertNotIn("interceptions", role["priority_metrics"])
        self.assertNotIn("pass_accuracy_pct_derived", [item["metric_key"] for item in signals],
                         "12/12 attempts do not meet the 15-pass comparison minimum")

    def test_cross_role_signal_keeps_full_audit_cohort_out_of_model_input(self):
        ctx = striker_match_context()
        narrowed = prompt_evidence(ctx)
        self.assertIn("interceptions", fact_map(narrowed)["selected_match_player"]["stats"])
        cohort = fact_map(narrowed)["match_players"]
        self.assertEqual(len(cohort), 1)
        self.assertEqual({row["team_ea_id"] for row in cohort}, {1929})
        self.assertEqual(cohort[0]["player_ea_id"], 20)
        self.assertEqual(len(fact_map(ctx)["match_players"]), 6)
        focus = report_focus({**ctx, "role_analysis": player_role(ctx)})
        standout_focus = next(item for item in focus if "match_standouts" in item)
        self.assertEqual(standout_focus["match_standouts"][0]["metric_key"], "interceptions")
        self.assertEqual(standout_focus["fact_refs"], ["selected_match_player", "match_players"])

    def test_cross_role_standout_requires_a_comparable_team_sample(self):
        ctx = striker_match_context(peer_interceptions=(0, 1, 0))
        self.assertEqual(player_role(ctx)["cross_role_standouts"], [])

    def test_cross_role_standout_can_use_extra_matchstats_fields_and_validate_claim(self):
        ctx = striker_match_context()
        selected = fact_map(ctx)["selected_match_player"]
        selected["stats"].update({"stand_tackles": 3, "stand_tackles_won": 3})
        for index, row in enumerate(fact_map(ctx)["match_players"][1:5]):
            row["stats"].update({"stand_tackles": 2, "stand_tackles_won": index % 2})

        role = player_role(ctx)
        self.assertIn("stand_tackles_won", [item["metric_key"] for item in role["cross_role_standouts"]])
        projected = prompt_evidence(ctx)
        self.assertIn("stand_tackles_won", fact_map(projected)["selected_match_player"]["stats"])
        self.assertTrue(all("stand_tackles_won" in row["stats"]
                            for row in fact_map(projected)["match_players"]))

        valid = {fact["id"] for fact in ctx["facts"]}
        item = {"text": "O atacante venceu 3 desarmes em pé nesta partida.",
                "kind": "fact", "limitations": "", "fact_refs": ["selected_match_player"]}
        reasons = []
        self.assertTrue(_validate_report_item(ctx, "match_player", item, valid,
                                             section="observations", rejection_reasons=reasons), reasons)

    def test_winger_report_focus_prioritizes_rating_and_deterministic_primary_strengths(self):
        ctx = winger_match_context()
        role = player_role(ctx)
        self.assertEqual(role["role"], "winger")
        self.assertEqual(role["role_standouts"][0]["signal_type"], "role_standout")
        self.assertIn(role["role_standouts"][0]["metric_key"], {
            "dribble_success_pct_derived", "cross_success_pct_derived"})
        self.assertEqual(role["match_standouts"], role["role_standouts"][:2])

        focus = report_focus({**ctx, "role_analysis": role})
        player_focus = next(item for item in focus if item.get("position_role") == "winger")
        self.assertEqual(player_focus["match_rating"], 7.8)
        self.assertEqual(player_focus["minutes"], 63)
        standout_focus = next(item for item in focus if "match_standouts" in item)
        self.assertEqual(standout_focus["match_standouts"], role["match_standouts"])

    def test_match_facts_are_selected_deterministically_for_the_two_reported_examples(self):
        nishan = winger_match_context()
        selected = fact_map(nishan)["selected_match_player"]
        selected.update({"name": "Nishan Velupillay", "minutes": 63, "rating": 7.4})
        selected["stats"] = {
            "goals_derived": 1, "npk_goals": 1, "assists": 0, "npk_expected_goals": 1.36,
            "shots": 2, "shots_on_target": 2, "passes": 9, "passes_completed": 3,
            "pass_accuracy_pct_derived": 33.3, "passes_under_pressure": 2,
            "passes_completed_under_pressure": 0, "pressure_pass_accuracy_pct": 0,
            "dribbles": 11, "dribbles_completed": 10, "dribble_success_pct_derived": 90.9,
            "crosses_attempted": 2, "crosses_delivered": 0, "cross_success_pct_derived": 0,
            "possession_won": 0, "possession_lost": 6, "offense_duels_attempted": 2,
            "offense_duels_won": 1,
        }
        nishan["role_analysis"] = player_role(nishan)
        nishan_items = _deterministic_match_player_observations(nishan)
        nishan_text = "\n".join(item["text"] for item in nishan_items)
        self.assertLessEqual(len(nishan_items), 4)
        self.assertIn("10/11", nishan_text)
        self.assertIn("1 gol", nishan_text)
        self.assertIn("3/9", nishan_text)
        self.assertIn("0/2 completos", nishan_text)
        self.assertTrue(all(item["kind"] == "fact" for item in nishan_items))
        self.assertNotIn("dificuldades", nishan_text.casefold())

        jamie = winger_match_context()
        jamie_selected = fact_map(jamie)["selected_match_player"]
        jamie_selected.update({"name": "Jamie Paterson", "registered_position": "CAM",
                               "minutes": 63, "rating": 7.1})
        jamie_selected["stats"] = {
            "goals_derived": 0, "npk_goals": 0, "assists": 0, "expected_assists": 0.38,
            "shots": 0, "key_passes": 1, "passes": 16, "passes_completed": 16,
            "pass_accuracy_pct_derived": 100, "passes_under_pressure": 5,
            "passes_completed_under_pressure": 5, "pressure_pass_accuracy_pct": 100,
            "dribbles": 15, "dribbles_completed": 14, "dribble_success_pct_derived": 93.3,
            "possession_won": 0, "possession_lost": 1, "offense_duels_attempted": 3,
            "offense_duels_won": 2, "defense_duels_attempted": 2, "defense_duels_won": 1,
        }
        jamie["role_analysis"] = player_role(jamie)
        jamie_items = _deterministic_match_player_observations(jamie)
        jamie_text = "\n".join(item["text"] for item in jamie_items)
        self.assertLessEqual(len(jamie_items), 4)
        self.assertIn("14/15", jamie_text)
        self.assertIn("16/16", jamie_text)
        self.assertIn("5/5", jamie_text)
        self.assertIn("1 passe-chave", jamie_text)
        self.assertIn("0,38", jamie_text)
        self.assertNotIn("impecável", jamie_text.casefold())

    def test_player_team_comparison_precomputes_efficiency_and_defensive_rank(self):
        context = winger_match_context()
        selected = fact_map(context)["selected_match_player"]
        selected["stats"].update({"passes": 9, "passes_completed": 3,
                                   "pass_accuracy_pct_derived": 33.3, "interceptions": 4})
        peers = [
            {"player_ea_id": 31, "team_ea_id": 1929, "minutes": 90,
             "stats": {"passes": 10, "passes_completed": 8,
                       "pass_accuracy_pct_derived": 80, "interceptions": 1}},
            {"player_ea_id": 32, "team_ea_id": 1929, "minutes": 90,
             "stats": {"passes": 10, "passes_completed": 10,
                       "pass_accuracy_pct_derived": 100, "interceptions": 2}},
        ]
        facts = [*context["facts"], {"id": "match_players", "value": [selected, *peers]},
                 {"id": "matchstats", "value": [{"team_ea_id": 1929,
                  "stats": {"passes": 29, "passes_completed": 21, "interceptions": 9}}]}]
        comparison = _match_player_team_comparison(facts, 1929)
        self.assertEqual(comparison["metrics"]["pass_accuracy_pct_derived"]["team_value"], 72.414)
        self.assertEqual(comparison["metrics"]["pass_accuracy_pct_derived"]["difference_vs_team"], -39.114)
        self.assertEqual(comparison["metrics"]["interceptions"]["teammate_average_excluding_player"], 1.5)
        self.assertEqual(comparison["metrics"]["interceptions"]["rank_among_exported_players"], 1)

        context["facts"] = [*facts, {"id": "match_player_team_comparison", "value": comparison}]
        context["role_analysis"] = player_role(context)
        projected = prompt_evidence(context)
        projected_comparison = fact_map(projected)["match_player_team_comparison"]
        self.assertEqual(projected_comparison["metrics"]["pass_accuracy_pct_derived"]["team_value"], 72.414)
        claim = {"text": "A precisão de passe foi 33,3%, abaixo dos 72,4% coletivos; "
                         "as 4 interceptações lideraram os 3 atletas exportados, ante média de 1,5 dos colegas.",
                 "kind": "inference", "limitations": "Comparação restrita aos participantes exportados.",
                 "fact_refs": ["selected_match_player", "match_player_team_comparison", "matchstats", "match_players"]}
        reasons = []
        self.assertTrue(_validate_report_item(context, "match_player", claim,
                                              {fact["id"] for fact in context["facts"]},
                                              section="observations", rejection_reasons=reasons), reasons)

    def test_rejected_model_claims_still_produce_a_bounded_technical_report(self):
        context = keeper_context_with_opponent_xg()
        fact_map(context)["selected_match_player"].update({"rating": 5.0})
        context["role_analysis"] = player_role(context)
        output = {"summary": {"text": "Partida incrível e perfeita: 4 defesas.",
                              "kind": "inference", "limitations": "",
                              "fact_refs": ["selected_match_player"]},
                  "observations": [{"text": "O goleiro completou 124/133 dribles.",
                                    "kind": "fact", "limitations": "",
                                    "fact_refs": ["selected_match_player"]}],
                  "recommendations": [], "strengths": [], "development_areas": [],
                  "training_suggestions": [], "information_requests": [], "formation": None}
        response = io.BytesIO(json.dumps({"message": {"content": json.dumps(output)}}).encode())
        with sqlite3.connect(":memory:") as conn, \
             patch("atlas.commission._briefing_facts", return_value=(
                 context, [item["id"] for item in context["facts"]], "fixture:1:player:10")), \
             patch("atlas.commission.ollama_models", return_value={"available": True, "models": ["local"]}), \
             patch("atlas.commission.urllib.request.urlopen", return_value=response):
            result = get_commission_report(conn, 1, 1, "match_player", fixture_id=1, player_ea_id=10,
                                           model="local")
        self.assertTrue(result["available"])
        self.assertEqual(result["report"]["summary"]["kind"], "inference")
        self.assertFalse(result["report"]["summary"]["model_generated"])
        self.assertGreaterEqual(len(result["report"]["observations"]), 2)
        self.assertGreaterEqual(result["validation"]["rejected_claims"], 2)

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
