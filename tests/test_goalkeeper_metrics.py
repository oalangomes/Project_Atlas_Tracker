from __future__ import annotations

import unittest

from atlas.goalkeeper_metrics import fixture_goalkeepers, summarize_keeper_matches


def fixture(*, second_keeper=False, minutes=90, shots_on_target=5,
            opponent_xg=1.8, conceded=1, team_conceded=1):
    teams = [
        {"teamIndex": 0, "teamEaId": 10,
         "stats": {"saves": 4, "goals_conceded": team_conceded}},
        {"teamIndex": 1, "teamEaId": 20,
         "stats": {"shots_on_target": shots_on_target,
                   "npk_expected_goals": 1.1,
                   "expected_goals_derived": opponent_xg}},
    ]
    players = [{"playerEaId": 1, "teamIndex": 0, "primaryPosition": "GK",
                "stats": {"minutes_played": minutes, "saves": 4,
                          "goals_conceded": conceded, "shots_against": 9}}]
    if second_keeper:
        players.append({"playerEaId": 2, "teamIndex": 0, "primaryPosition": "GK",
                        "stats": {"minutes_played": 15, "saves": 1, "goals_conceded": 0}})
    return teams, players


class GoalkeeperMetricsTests(unittest.TestCase):
    def side(self, **kwargs):
        teams, players = fixture(**kwargs)
        return fixture_goalkeepers(teams, players)["sides"][0]

    def test_one_keeper_reconciles_team_and_opponent(self):
        side = self.side()
        self.assertEqual(side["state"], "single_goalkeeper")
        self.assertEqual(side["metrics"]["saveRatePct"], 80.0)
        self.assertEqual(side["metrics"]["savesPer90"], 4.0)
        self.assertEqual(side["metrics"]["goalsConcededPer90"], 1.0)
        self.assertEqual(side["metrics"]["goalsPrevented"], 0.8)
        self.assertEqual(side["keepers"][0]["shotsAgainst"], 9.0)

    def test_two_keepers_keep_raw_rows_without_team_attribution(self):
        side = self.side(second_keeper=True)
        self.assertEqual(side["state"], "multiple_goalkeepers")
        self.assertEqual(len(side["keepers"]), 2)
        self.assertIsNone(side["eligibleKeeperId"])
        self.assertIsNone(side["metrics"]["saveRatePct"])
        self.assertIsNone(side["metrics"]["goalsPrevented"])
        self.assertIsNone(side["metrics"]["opponentXg"])
        self.assertEqual(side["opponentTeamFacts"]["opponentXg"], 1.8)

    def test_zero_and_unknown_minutes_are_not_attributable(self):
        teams, players = fixture(minutes=0)
        self.assertEqual(fixture_goalkeepers(teams, players)["sides"][0]["state"], "no_goalkeeper")
        players[0]["stats"]["minutes_played"] = None
        self.assertEqual(fixture_goalkeepers(teams, players)["sides"][0]["state"], "uncertain_minutes")
        self.assertEqual(fixture_goalkeepers(teams, [])["sides"][0]["state"], "no_goalkeeper")

    def test_save_rate_denominator_mismatch_remains_visible(self):
        side = self.side(shots_on_target=8)
        self.assertEqual(side["saveRateReason"], "shots_on_target_mismatch")
        self.assertIsNone(side["metrics"]["saveRatePct"])
        self.assertEqual(side["metrics"]["savesPer90"], 4.0)

    def test_missing_total_xg_hides_goals_prevented(self):
        side = self.side(opponent_xg=None)
        self.assertEqual(side["goalsPreventedReason"], "missing_total_opponent_xg")
        self.assertIsNone(side["metrics"]["goalsPrevented"])
        self.assertEqual(side["metrics"]["opponentNpkXg"], 1.1)

    def test_missing_goal_concession_pair_hides_conceded_rate(self):
        side = self.side(team_conceded=None)
        self.assertEqual(side["goalsPreventedReason"], "missing_goal_concession_pair")
        self.assertIsNone(side["metrics"]["goalsConcededPer90"])

    def test_trusted_observed_outfield_position_overrides_registered_gk(self):
        teams, players = fixture()
        evidence = fixture_goalkeepers(
            teams, players,
            observed_positions={1: {"position": "CB", "source": "career_playermatchratinghistory_position"}})
        self.assertEqual(evidence["sides"][0]["state"], "no_goalkeeper")

    def test_aggregate_uses_distinct_metric_samples(self):
        reconciled = self.side()
        mismatch = self.side(shots_on_target=8)
        multiple = self.side(second_keeper=True)
        summary = summarize_keeper_matches([reconciled, mismatch, multiple])
        self.assertEqual(summary["sample"]["appearances"], 3)
        self.assertEqual(summary["sample"]["saveRate"], 1)
        self.assertEqual(summary["sample"]["savesPer90"], 2)
        self.assertEqual(summary["sample"]["excluded"], 1)
        self.assertEqual(summary["saveRatePct"], 80.0)
        self.assertEqual(summary["savesPer90"], 4.0)
        self.assertEqual(summary["goalsPrevented"], 1.6)


if __name__ == "__main__":
    unittest.main()
