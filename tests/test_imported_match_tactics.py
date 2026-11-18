import unittest

from atlas.server_query_matches import imported_match_tactics


class ImportedMatchTacticsTests(unittest.TestCase):
    def test_complete_recorded_xi_gives_line_distribution_for_own_team_only(self):
        positions = [0, 7, 6, 4, 3, 16, 15, 13, 12, 26, 24]
        rows = [
            {"player_ea_id": index + 1, "match_team_ea_id": 10,
             "rating_position_raw": slot, "minutes_played": 90,
             "actual_position": "GK" if slot == 0 else "CB",
             "actual_position_source": "career_playermatchratinghistory_position"}
            for index, slot in enumerate(positions)
        ]
        rows.append({"player_ea_id": 20, "match_team_ea_id": 10,
                     "rating_position_raw": 28, "minutes_played": 20,
                     "actual_position": "ST",
                     "actual_position_source": "career_playerlastmatchhistory_latest_match"})
        rows.append({"player_ea_id": 30, "match_team_ea_id": 20,
                     "primary_position": "GK", "minutes_played": 90})

        own, rival = imported_match_tactics(rows, (10, 20))

        self.assertEqual(own["initialLineDistribution"], "4-4-2")
        self.assertEqual(own["recordedStarterCount"], 11)
        self.assertEqual(own["observedPositionCount"], 12)
        self.assertIsNone(rival["initialLineDistribution"])
        self.assertEqual(rival["observedPositionCount"], 0)

    def test_incomplete_or_ambiguous_xi_does_not_invent_a_formation(self):
        base = [{"player_ea_id": index + 1, "match_team_ea_id": 10,
                 "rating_position_raw": slot, "minutes_played": 90}
                for index, slot in enumerate([0, 7, 6, 4, 3, 16, 15, 13, 12, 26, 24])]
        self.assertEqual(imported_match_tactics(base, (10, 20))[0]["observedPositionCount"], 11)
        self.assertIsNone(imported_match_tactics(base[:-1], (10, 20))[0]["initialLineDistribution"])
        duplicate = base + [{"player_ea_id": 99, "match_team_ea_id": 10,
                             "rating_position_raw": 25, "minutes_played": 45}]
        self.assertIsNone(imported_match_tactics(duplicate, (10, 20))[0]["initialLineDistribution"])


if __name__ == "__main__":
    unittest.main()
