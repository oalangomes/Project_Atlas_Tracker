from __future__ import annotations

import sqlite3
import unittest

from atlas.defense_context import build_defense_context, defense_context


SOURCE = "career_playermatchratinghistory_position"


def player(player_id=1, position="CB", minutes=90, source=SOURCE, tackles=2):
    return {"playerEaId": player_id, "displayName": f"Player {player_id}",
            "primaryPosition": "ST", "observedPosition": position,
            "observedPositionSource": source,
            "stats": {"minutes_played": minutes, "tackles": tackles,
                      "interceptions": 1, "blocks": None, "clearances": 3}}


def fixture(fixture_id=1, xga=2.0, shots=10, conceded=0, players=None):
    return {"fixtureId": fixture_id, "ownStats": {"goals_conceded": conceded},
            "opponentStats": {"expected_goals_derived": xga, "shots": shots,
                              "shots_on_target": 4},
            "players": [player()] if players is None else players}


class DefenseContextTests(unittest.TestCase):
    def test_direct_actions_and_context_have_distinct_sources_and_samples(self):
        result = build_defense_context([
            fixture(1), fixture(2, xga=1.0, shots=8, conceded=1,
                                players=[player(minutes=45, tackles=1)]),
        ])
        defender = result["players"][0]
        self.assertEqual(defender["direct"]["tackles"]["total"], 3)
        self.assertEqual(defender["direct"]["tackles"]["per90"], 2.0)
        self.assertEqual(defender["direct"]["blocks"]["fixtures"], 0)
        self.assertIsNone(defender["direct"]["blocks"]["per90"])
        context = defender["estimatedContext"]
        self.assertEqual(context["sample"]["xga"], {"fixtures": 2, "minutes": 135.0})
        self.assertEqual(context["metrics"]["xgaPer90Estimated"], 1.667)
        self.assertEqual(context["metrics"]["cleanSheetExposurePctEstimated"], 66.7)
        self.assertFalse(result["sectorPanelAvailable"])

    def test_missing_xga_keeps_shots_separate_but_disables_sector(self):
        result = build_defense_context([
            fixture(1, xga=None), fixture(2, xga=None), fixture(3, xga=None)])
        self.assertEqual(result["coverage"]["xgaFixtures"], 0)
        individual = result["players"][0]["estimatedContext"]
        self.assertIsNone(individual["metrics"]["xgaPer90Estimated"])
        self.assertEqual(individual["metrics"]["shotsPer90Estimated"], 10.0)
        self.assertFalse(result["sectorPanelAvailable"])
        self.assertIsNone(result["sectors"][0]["estimatedContext"]["metrics"]["shotsPer90Estimated"])

    def test_untrusted_position_and_missing_minutes_do_not_create_context(self):
        untrusted = player(1, source="registered_position")
        untrusted["primaryPosition"] = "CB"
        result = build_defense_context([fixture(players=[untrusted, player(2, minutes=None)])])
        self.assertEqual(result["coverage"]["trustedDefensiveRows"], 0)
        self.assertEqual(result["coverage"]["withoutTrustedPosition"], 1)
        self.assertEqual(result["coverage"]["withoutMinutes"], 1)
        self.assertFalse(result["sectorPanelAvailable"])
        first, second = result["players"]
        self.assertEqual(first["direct"]["tackles"]["total"], 2)
        self.assertEqual(second["direct"]["tackles"]["total"], 2)
        self.assertIsNone(second["direct"]["tackles"]["per90"])

    def test_sector_requires_270_minutes_across_three_distinct_fixtures(self):
        same_two = [player(1), player(2, position="LCB")]
        two_fixtures = build_defense_context([fixture(1, players=same_two), fixture(2, players=same_two)])
        centre = two_fixtures["sectors"][0]
        self.assertEqual(centre["estimatedContext"]["sample"]["xga"]["minutes"], 360)
        self.assertFalse(centre["qualified"])
        three_fixtures = build_defense_context([fixture(1), fixture(2), fixture(3)])
        self.assertTrue(three_fixtures["sectors"][0]["qualified"])
        self.assertTrue(three_fixtures["sectorPanelAvailable"])

    def test_sector_metric_uses_its_own_coverage(self):
        result = build_defense_context([
            fixture(1), fixture(2, shots=None), fixture(3, shots=None)])
        centre = result["sectors"][0]
        self.assertTrue(centre["qualified"])
        self.assertEqual(centre["estimatedContext"]["metrics"]["xgaPer90Estimated"], 2.0)
        self.assertIsNone(centre["estimatedContext"]["metrics"]["shotsPer90Estimated"])
        self.assertEqual(centre["estimatedContext"]["sample"]["shots"]["fixtures"], 1)

    def test_substituted_pair_is_only_same_fixture_with_overlap_upper_bound(self):
        result = build_defense_context([fixture(players=[
            player(1, minutes=45), player(2, position="RCB", minutes=45)])])
        pair = result["pairs"][0]
        self.assertEqual(pair["sameFixtureCount"], 1)
        self.assertEqual(pair["overlapUpperBoundMinutes"], 45)
        self.assertFalse(pair["simultaneousPresenceConfirmed"])
        self.assertFalse(pair["referenceUpperBoundReached"])

    def test_future_observed_position_is_excluded_from_historical_cutoff(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                import_sequence INTEGER,managed_team_ea_id INTEGER);
            CREATE TABLE fixtures(id INTEGER,fixture_key TEXT);
            CREATE TABLE match_stat_exports(id INTEGER,fixture_id INTEGER,career_id INTEGER,
                snapshot_id INTEGER,linkage_status TEXT,export_status TEXT,superseded_by_export_id INTEGER);
            CREATE TABLE match_team_detailed_stats(export_id INTEGER,team_index INTEGER,
                team_ea_id INTEGER,stats_json TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,player_ea_id INTEGER,
                team_index INTEGER,minutes_played INTEGER,stats_json TEXT);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,
                display_name TEXT,primary_position TEXT);
            CREATE TABLE player_match_performances(snapshot_id INTEGER,fixture_key TEXT,
                player_ea_id INTEGER,actual_position TEXT,actual_position_source TEXT);
            INSERT INTO snapshots VALUES(1,1,0,1,10),(2,1,0,2,10);
            INSERT INTO fixtures VALUES(5,'fixture-5');
            INSERT INTO match_stat_exports VALUES(7,5,1,1,'linked','complete_participant_export',NULL);
            INSERT INTO match_team_detailed_stats VALUES
                (7,0,10,'{"goals_conceded":0,"penalties_committed":0}'),
                (7,1,20,'{"npk_expected_goals":1.5,"shots":7}');
            INSERT INTO match_player_detailed_stats VALUES(7,100,0,90,'{"tackles":2}');
            INSERT INTO player_states VALUES(1,100,'Defender','CB');
            INSERT INTO player_match_performances VALUES
                (2,'fixture-5',100,'CB','career_playermatchratinghistory_position');
        """)
        try:
            before = defense_context(conn, 1, [0], 10, as_of_import_sequence=1)
            after = defense_context(conn, 1, [0], 10, as_of_import_sequence=2)
            self.assertEqual(before["coverage"]["trustedDefensiveRows"], 0)
            self.assertEqual(after["coverage"]["trustedDefensiveRows"], 1)
            self.assertIsNone(before["players"][0]["estimatedContext"]["metrics"]["xgaPer90Estimated"])
            self.assertEqual(after["players"][0]["estimatedContext"]["metrics"]["xgaPer90Estimated"], 1.5)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
