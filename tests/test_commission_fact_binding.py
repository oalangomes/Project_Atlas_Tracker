"""Fixture score claims must resolve to the named entity's own source value."""
import unittest

from atlas.claim_binding import score_claim_bindings
from atlas.commission import _validate_report_item


def context(home="Telstar", away="Plymouth Argyle", score=(0, 2), managed="away"):
    return {"mode": "match_player", "managed_team": "Plymouth Argyle", "facts": [
        {"id": "match", "value": {"fixture_id": 10992, "home": home, "away": away,
                                  "score": score, "managed_team_side": managed,
                                  "managed_score": score[1 if managed == "away" else 0],
                                  "opponent_score": score[0 if managed == "away" else 1],
                                  "event_timing_available": True}},
        {"id": "selected_match_player", "value": {"name": "Joe Edwards", "player_ea_id": 192231,
                                                  "stats": {"goals_derived": 0, "npk_goals": 0}}},
    ]}


class ScoreClaimBindingTests(unittest.TestCase):
    def check_claim(self, text, expected, ctx=None, kind="fact", refs=None):
        ctx = ctx or context()
        refs = refs or ["match"]
        item = {"text": text, "kind": kind, "limitations": "Hipótese sem evidência direta da partida.",
                "fact_refs": refs}
        reasons = []
        result = _validate_report_item(ctx, ctx.get("mode", "match_player"), item, {"match", "selected_match_player"},
                                       rejection_reasons=reasons)
        self.assertEqual(result, expected, (text, reasons))
        bindings, issues = score_claim_bindings(ctx, item)
        if expected and bindings:
            self.assertTrue(all(binding["accepted"] for binding in bindings), (text, bindings, issues))
        return reasons

    def test_telstar_plymouth_three_languages(self):
        cases = [
            ("Plymouth Argyle marcou 2 gols.", True),
            ("Plymouth Argyle sofreu 0 gols.", True),
            ("Plymouth Argyle sofreu 2 gols.", False),
            ("O visitante sofreu 2 gols.", False),
            ("O time visitante sofreu dois gols, mas o jogador não foi diretamente responsabilizado por falhas defensivas registradas nos dados disponíveis.", False),
            ("O mandante sofreu 2 gols.", True),
            ("Telstar marcou 2 gols.", False),
            ("Plymouth Argyle scored 2 goals.", True),
            ("Plymouth Argyle conceded 0 goals.", True),
            ("Plymouth Argyle conceded 2 goals.", False),
            ("The away team conceded 2 goals.", False),
            ("The home team conceded 2 goals.", True),
            ("Telstar scored 2 goals.", False),
            ("Plymouth Argyle marcó 2 goles.", True),
            ("Plymouth Argyle encajó 0 goles.", True),
            ("Plymouth Argyle encajó 2 goles.", False),
            ("El equipo visitante encajó 2 goles.", False),
            ("El equipo local encajó 2 goles.", True),
            ("Telstar marcó 2 goles.", False),
        ]
        for claim, expected in cases:
            with self.subTest(claim=claim):
                reasons = self.check_claim(claim, expected)
                if not expected:
                    self.assertIn("score_value_conflict", reasons)

    def test_player_scoreline_and_home_orientation(self):
        for claim, expected, refs in [
            ("Joe Edwards marcou 2 gols.", False, ["match", "selected_match_player"]),
            ("Joe Edwards marcou 0 gols.", True, ["match", "selected_match_player"]),
            ("Telstar 0–2 Plymouth Argyle.", True, ["match"]),
            ("Plymouth Argyle 0–2 Telstar.", False, ["match"]),
        ]:
            with self.subTest(claim=claim):
                self.check_claim(claim, expected, refs=refs)
        home = context(home="Plymouth Argyle", away="Telstar", score=(2, 0), managed="home")
        self.check_claim("O mandante marcou 2 gols.", True, ctx=home)
        self.check_claim("O visitante marcou 2 gols.", False, ctx=home)
        self.assertIn("score_value_conflict", self.check_claim(
            "Joe Edwards atuou no empate de 0-0 contra o Telstar.", False))

    def test_player_ratio_requires_the_metric_denominator(self):
        ctx = context()
        ctx["facts"][1]["value"]["stats"].update({"dribbles_completed": 5, "passes": 6})
        self.assertIn("selected_player_metric_conflict", self.check_claim(
            "Joe Edwards completou 5 de 6 dribles.", False, ctx=ctx,
            refs=["match", "selected_match_player"]))

    def test_selected_players_team_score_binds_generic_equipe(self):
        ctx = context(home="Huddersfield Town", away="Plymouth Argyle", score=(2, 4))
        ctx["facts"][0]["value"]["managed_team_ea_id"] = 1929
        ctx["facts"][1]["value"]["team_ea_id"] = 1929
        self.assertIn("score_value_conflict", self.check_claim(
            "Apesar da equipe ter sofrido 4 gols, o jogador foi positivo.", False,
            ctx=ctx, refs=["match", "selected_match_player"]))
        self.check_claim("A equipe sofreu 2 gols.", True, ctx=ctx, refs=["match", "selected_match_player"])

    def test_missing_source_and_legitimate_hypothesis(self):
        self.assertIn("score_source_missing", self.check_claim("Plymouth Argyle marcou 2 gols.", False,
                                                              refs=["selected_match_player"]))
        match_context = context()
        match_context["mode"] = "match"
        self.check_claim("Se o visitante cedesse espaços, o cenário exigiria uma revisão defensiva.", True,
                         ctx=match_context, kind="hypothesis")


if __name__ == "__main__":
    unittest.main()
