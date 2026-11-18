from __future__ import annotations

import unittest
import json
import sqlite3

from atlas.match_lineups import (_departures, _formation_shape, _line_shape,
                                 match_lineup_phases, save_match_formation_estimates)


class MatchLineupPhasesTests(unittest.TestCase):
    def test_position_bands_refine_4231_and_keep_523(self) -> None:
        tactical = ["GK", "RB", "RCB", "LCB", "LB", "RDM", "LDM", "RM", "CAM", "LM", "ST"]
        history = {i: {"actual_position": pos} for i, pos in enumerate(tactical, start=1)}
        self.assertEqual(_formation_shape(set(history), history), ("4-2-3-1", "role_bands"))
        defensive = ["GK", "RWB", "RCB", "CB", "LCB", "LWB", "RCM", "LCM", "RW", "ST", "LW"]
        history = {i: {"actual_position": pos} for i, pos in enumerate(defensive, start=1)}
        self.assertEqual(_formation_shape(set(history), history), ("5-2-3", "broad_lines"))

    def test_substitution_changes_final_line_distribution(self) -> None:
        positions = ["GK", "RB", "RCB", "LCB", "LB", "RM", "RCM", "CM", "LCM", "LM", "ST"]
        history = {index: {"actual_position": position, "minutes_played": "90"}
                   for index, position in enumerate(positions, start=1)}
        history[6]["minutes_played"] = "51"
        history[12] = {"actual_position": "ST", "minutes_played": "39"}
        starters, incoming = set(range(1, 12)), {12}
        outgoing = _departures(starters, incoming, history, 90)
        self.assertEqual(outgoing, {6})
        self.assertEqual(_line_shape(starters, history), "4-5-1")
        self.assertEqual(_line_shape((starters - outgoing) | incoming, history), "4-4-2")

    def test_incomplete_or_ambiguous_substitution_is_not_inferred(self) -> None:
        positions = ["GK", "RB", "RCB", "LCB", "LB", "RM", "RCM", "CM", "LCM", "LM", "ST"]
        history = {index: {"actual_position": position, "minutes_played": "90"}
                   for index, position in enumerate(positions, start=1)}
        history[6]["minutes_played"] = "88"
        history[7]["minutes_played"] = "88"
        history[12] = {"actual_position": "CM", "minutes_played": "4"}
        self.assertIsNone(_departures(set(range(1, 12)), {12}, history, 90))
        del history[3]["actual_position"]
        self.assertIsNone(_line_shape(set(range(1, 12)), history))

    def test_snapshot_history_must_be_fresh_for_this_fixture(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,import_sequence INTEGER);
            CREATE TABLE match_stat_exports(id INTEGER,snapshot_id INTEGER,fixture_id INTEGER,
                team0_ea_id INTEGER,team1_ea_id INTEGER);
            CREATE TABLE fixtures(id INTEGER,fixture_key TEXT,competition_object_id INTEGER);
            CREATE TABLE fixture_observations(snapshot_id INTEGER,fixture_id INTEGER,
                managed_team_involved INTEGER,is_completed INTEGER,date TEXT,competition_name TEXT);
            CREATE TABLE generic_snapshot_rows(snapshot_id INTEGER,file_name TEXT,raw_json TEXT);
            CREATE TABLE match_player_detailed_stats(export_id INTEGER,team_index INTEGER,
                player_ea_id INTEGER,stats_json TEXT);
            INSERT INTO snapshots VALUES(1,1,1),(2,1,2);
            INSERT INTO match_stat_exports VALUES(1,2,9,100,200);
            INSERT INTO fixtures VALUES(9,'fixture-9',1);
            INSERT INTO fixture_observations VALUES(1,9,1,0,'2026-01-01','Cup');
            INSERT INTO fixture_observations VALUES(2,9,1,1,'2026-01-01','Cup');
        """)
        positions = ["GK", "RB", "RCB", "LCB", "LB", "RM", "RCM", "CM", "LCM", "LM", "ST"]
        for index, position in enumerate(positions, start=1):
            row = {"team_id": "100", "player_id": str(index), "actual_position": position,
                   "minutes_played": "90"}
            for snapshot_id in (1, 2):
                conn.execute("INSERT INTO generic_snapshot_rows VALUES(?,'last_match_players.csv',?)",
                             (snapshot_id, json.dumps(row)))
            conn.execute("INSERT INTO match_player_detailed_stats VALUES(1,0,?,?)",
                         (index, json.dumps({"array_index": index - 1})))
        detail = {"exportId": 1, "snapshotId": 2}
        self.assertIsNone(match_lineup_phases(conn, detail, 9))
        conn.execute("UPDATE generic_snapshot_rows SET raw_json=? WHERE snapshot_id=2 AND json_extract(raw_json,'$.player_id')='6'",
                     (json.dumps({"team_id": "100", "player_id": "6", "actual_position": "RM", "minutes_played": "51"}),))
        conn.execute("INSERT INTO generic_snapshot_rows VALUES(2,'last_match_players.csv',?)",
                     (json.dumps({"team_id": "100", "player_id": "12", "actual_position": "ST", "minutes_played": "39"}),))
        phases = match_lineup_phases(conn, detail, 9)
        self.assertEqual(phases["teams"][0]["initialFormation"], "4-5-1")
        self.assertEqual(phases["teams"][0]["finalFormation"], "4-4-2")
        self.assertEqual(phases["teams"][0]["substitutionCount"], 1)
        conn.execute("""CREATE TABLE match_formation_estimates(
            source_export_id INTEGER,team_ea_id INTEGER,phase TEXT,model_id TEXT,
            formation TEXT,evidence_json TEXT,saved_at TEXT,
            PRIMARY KEY(source_export_id,team_ea_id,phase,model_id))""")
        save_match_formation_estimates(conn, phases)
        save_match_formation_estimates(conn, phases)
        stored = conn.execute("SELECT phase,formation,evidence_json FROM match_formation_estimates ORDER BY phase").fetchall()
        self.assertEqual([(row["phase"], row["formation"]) for row in stored],
                         [("final", "4-4-2"), ("initial", "4-5-1")])
        self.assertEqual(json.loads(stored[0]["evidence_json"])["substitutionCount"], 1)


if __name__ == "__main__":
    unittest.main()
