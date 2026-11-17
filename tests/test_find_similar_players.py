"""Player scouting filters must respect position, foot, league and club scope."""
import json
import sqlite3
import unittest

from scripts.find_similar_players import find_candidates, player_positions, similarity


REFERENCE = {
    "acceleration": "93", "sprint_speed": "94", "agility": "93", "dribbling": "70",
    "ball_control": "69", "finishing": "64", "crossing": "58", "short_passing": "61",
    "vision": "53", "balance": "67", "composure": "51", "reactions": "47",
    "stamina": "45", "strength": "70",
}


def _player(**overrides):
    raw = dict(REFERENCE)
    raw.update({"primary_position": "RM", "position_2": "", "position_3": "", "position_4": "",
                "preferred_foot_id": "1", "weak_foot": "4", "contract_valid_until": "2028"})
    raw.update(overrides)
    return raw


class SimilarityTests(unittest.TestCase):
    def test_player_positions_reads_exported_position_chain(self):
        self.assertEqual(player_positions(_player(position_2="LW", position_3="RW")),
                         ["RM", "LW", "RW"])

    def test_closer_profile_scores_higher(self):
        close = _player(overall="67", acceleration="90")
        far = _player(overall="67", acceleration="60", sprint_speed="60", agility="60")
        self.assertGreater(similarity(close, REFERENCE, 0.6, 1.5, 67, 67),
                           similarity(far, REFERENCE, 0.6, 1.5, 67, 67))

    def test_potential_gap_adds_score(self):
        low = similarity(_player(), REFERENCE, 0.6, 1.5, 67, 67)
        high = similarity(_player(), REFERENCE, 0.6, 1.5, 67, 80)
        self.assertGreater(high, low)


class CandidateFilterTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE team_states(snapshot_id INTEGER, ea_team_id INTEGER, team_name TEXT,
                league_name TEXT);
            CREATE TABLE player_states(snapshot_id INTEGER, ea_player_id INTEGER, display_name TEXT,
                team_ea_id INTEGER, team_name TEXT, overall INTEGER, potential INTEGER, raw_json TEXT);
        """)
        teams = [(1, "Plymouth Argyle", "EFL League One"), (2, "Man Utd", "Premier League"),
                 (3, "*TeamName_Abbr99", "Liga Mundial")]
        self.con.executemany("INSERT INTO team_states VALUES(1,?,?,?)", teams)
        rows = [
            (10, "Reference", 1, "Plymouth Argyle", 67, 67, _player()),
            (11, "LeftFoot", 2, "Man Utd", 68, 80, _player(primary_position="RW", preferred_foot_id="2", weak_foot="3")),
            (12, "RightFoot", 2, "Man Utd", 66, 78, _player(primary_position="RW", preferred_foot_id="1", weak_foot="4")),
            (13, "WeakRightFoot", 2, "Man Utd", 66, 78, _player(primary_position="RW", preferred_foot_id="1", weak_foot="3")),
            (14, "Striker", 2, "Man Utd", 66, 78, _player(primary_position="ST")),
            (15, "Placeholder", 3, "*TeamName_Abbr99", 70, 80, _player(primary_position="RW")),
        ]
        self.con.executemany(
            "INSERT INTO player_states VALUES(1,?,?,?,?,?,?,?)",
            [(pid, name, tid, team_name, ovr, pot, json.dumps(raw))
             for pid, name, tid, team_name, ovr, pot, raw in rows])

    def tearDown(self):
        self.con.close()

    def _find(self, foot="any", positions=("RW", "RM"), leagues=(), excluded=()):
        return find_candidates(self.con, 1, REFERENCE, positions, foot, 4, 0, 100,
                               leagues, excluded, 0.6, 1.5)

    def test_left_foot_filter(self):
        names = [item["name"] for item in self._find(foot="left")]
        self.assertIn("LeftFoot", names)
        self.assertNotIn("RightFoot", names)

    def test_right_foot_filter_requires_min_weak_foot(self):
        names = [item["name"] for item in self._find(foot="right")]
        self.assertIn("RightFoot", names)
        self.assertNotIn("WeakRightFoot", names)

    def test_position_filter_and_managed_club_exclusion(self):
        names = [item["name"] for item in self._find(excluded=("Plymouth Argyle",))]
        self.assertNotIn("Reference", names)
        self.assertNotIn("Striker", names)
        self.assertIn("LeftFoot", names)

    def test_placeholder_clubs_are_ignored(self):
        names = [item["name"] for item in self._find()]
        self.assertNotIn("Placeholder", names)

    def test_league_filter(self):
        names = [item["name"] for item in self._find(leagues=("Premier League",))]
        self.assertEqual(names, ["LeftFoot", "RightFoot"])

    def test_managed_club_is_included_when_not_excluded(self):
        names = [item["name"] for item in self._find()]
        self.assertIn("Reference", names)


if __name__ == "__main__":
    unittest.main()
