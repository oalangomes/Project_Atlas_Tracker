import sqlite3
import unittest

from atlas.commission import analyze_players
from atlas.server_query_analysis import AnalysisQueryMixin
from atlas.server_query_entities import EntityQueryMixin


class P06FormTests(unittest.TestCase):
    def test_last_five_follow_fixture_time_and_weight_minutes(self):
        players = [{"ea_player_id": 1, "display_name": "A", "primary_position": "ST"}]
        rows = [{"player_ea_id": 1, "fixture_key": str(i), "date": "2025-09-01",
                 "fixture_date": "2025-09-01", "fixture_time": f"{i:02d}:00",
                 "rating": float(i), "minutes_played": 90} for i in range(1, 7)]
        rows.reverse()
        result = analyze_players(players, rows)["players"][0]
        self.assertEqual([row["fixture_key"] for row in result["recent_fixtures"]],
                         ["6", "5", "4", "3", "2"])
        self.assertEqual(result["recent_rating"], 4.0)

    def test_rival_requires_trusted_same_role_and_reliable_sample(self):
        players = [{"ea_player_id": i, "display_name": str(i), "primary_position": "ST"}
                   for i in (1, 2, 3, 4)]
        rows = []
        for player_id, rating, position, source in (
            (1, 7.0, "RDM", "career_playermatchratinghistory_position"),
            (2, 6.0, "CDM", "career_playermatchratinghistory_position"),
            (3, 9.0, "RDM", "unverified"),
            (4, 9.0, "RDM", "career_playermatchratinghistory_position"),
        ):
            rows.extend({"player_ea_id": player_id, "fixture_key": str(i),
                         "date": f"2025-09-{i:02d}", "rating": rating,
                         "minutes_played": 90, "actual_position": position,
                         "actual_position_source": source} for i in range(1, 5 if player_id == 4 else 6))
        result = {p["player_ea_id"]: p for p in analyze_players(players, rows)["players"]}
        self.assertEqual(result[1]["match_position"], "Volante")
        self.assertEqual(result[1]["functional_rival"]["player_ea_id"], 2)
        self.assertEqual(result[1]["functional_rival"]["rating_delta"], 1.0)
        self.assertIsNone(result[3]["match_position"])
        self.assertEqual(result[3]["functional_rival"]["status"], "insufficient_sample")
        self.assertEqual(result[4]["functional_rival"]["status"], "insufficient_sample")
        self.assertEqual(result[1]["minutes_decision"]["status"], "abstain")


class P06SquadTests(unittest.TestCase):
    def test_station_aliases_share_team_identity(self):
        class Query(EntityQueryMixin):
            def _season_options(self, conn, career_id):
                return []

        class Media:
            def team_identity(self, team_id, season_start=None):
                return None

        query = Query()
        query.state = type("State", (), {"media": Media()})()
        points = [
            {"team_ea_id": 10, "team_name": name, "season_start_year": 2025,
             "effective_date": f"2025-09-0{day}", "overall": 70 + day,
             "potential": 80, "source": "snapshot"}
            for day, name in ((1, "Club A"), (2, "Club A FC"))
        ]
        result = query._player_career_path(None, 1, 7, points)
        self.assertEqual(len(result["stations"]), 1)
        self.assertEqual(result["stations"][0]["observations"], 2)
        self.assertEqual(result["stations"][0]["overall"], 72)

    def test_full_universe_alias_dedup_and_historical_cutoff(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,season_index INTEGER,
                import_sequence INTEGER,managed_team_ea_id INTEGER,career_date TEXT);
            CREATE TABLE roster_states(snapshot_id INTEGER,team_ea_id INTEGER,player_ea_id INTEGER);
            CREATE TABLE player_states(snapshot_id INTEGER,ea_player_id INTEGER,display_name TEXT,
                overall INTEGER,potential INTEGER,primary_position TEXT,raw_json TEXT);
            CREATE TABLE season_stat_states(snapshot_id INTEGER,represented_team_ea_id INTEGER,
                player_ea_id INTEGER,competition_object_id INTEGER,competition_name TEXT,
                display_name TEXT,appearances INTEGER,goals INTEGER,assists INTEGER,
                clean_sheets INTEGER,average_rating REAL);
            CREATE TABLE manual_seasons(id INTEGER,career_id INTEGER,season_index INTEGER);
            CREATE TABLE manual_competitions(id INTEGER,manual_season_id INTEGER,
                competition_object_id INTEGER,competition_name TEXT);
            CREATE TABLE manual_player_stats(manual_competition_id INTEGER,player_ea_id INTEGER,
                player_key TEXT,display_name TEXT,appearances INTEGER,goals INTEGER,
                assists INTEGER,clean_sheets INTEGER,average_rating REAL);
        """)
        conn.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", [
            (1, 1, 0, 1, 10, "2025-09-01"), (2, 1, 0, 2, 10, "2025-10-01")])
        conn.executemany("INSERT INTO player_states VALUES (?,?,?,?,?,?,?)", [
            (1, i, f"Current {i}", 60, 70, "CM", "{}") for i in range(1, 42)] +
            [(2, 99, "Future", 90, 95, "ST", "{}")])
        conn.executemany("INSERT INTO roster_states VALUES (?,?,?)", [(1, 10, i) for i in range(1, 42)])
        conn.execute("INSERT INTO season_stat_states VALUES (1,10,1,3,'League One','Alias A',5,2,1,0,7.0)")
        conn.execute("INSERT INTO manual_seasons VALUES (1,1,0)")
        conn.execute("INSERT INTO manual_competitions VALUES (1,1,5,'League-One')")
        conn.executemany("INSERT INTO manual_player_stats VALUES (?,?,?,?,?,?,?,?,?)", [
            (1, 1, "a", "Alias B", 5, 2, 1, 0, 7.0),
            (1, 99, "future", "Manual 99", 2, 0, 0, 0, 6.0),
        ])
        result = AnalysisQueryMixin()._deep_squad_analysis(
            conn, 1, conn.execute("SELECT * FROM snapshots WHERE id=1").fetchall(),
            [{"season_index": 0, "manual_season_id": 1}])
        rows = result["performancePlayers"]
        self.assertEqual(len(rows), 42)
        self.assertEqual(len(result["performanceLeaders"]), 15)
        first = next(item for item in rows if item["player_ea_id"] == 1)
        self.assertEqual(first["appearances"], 5)
        self.assertEqual(first["goals"], 2)
        self.assertEqual(first["aliases"], ["Alias A", "Alias B", "Current 1"])
        self.assertIsNone(first["development"]["overall_change"])
        future = next(item for item in rows if item["player_ea_id"] == 99)
        self.assertIsNone(future["overall"])
        self.assertIsNone(future["development"]["overall_current"])
        conn.execute("INSERT INTO player_states VALUES (2,1,'Current 1',62,71,'CM','{}')")
        conn.execute("INSERT INTO roster_states VALUES (2,10,1)")
        later = AnalysisQueryMixin()._deep_squad_analysis(
            conn, 1, conn.execute("SELECT * FROM snapshots ORDER BY import_sequence").fetchall(),
            [{"season_index": 0, "manual_season_id": 1}])
        current = next(item for item in later["performancePlayers"] if item["player_ea_id"] == 1)
        self.assertEqual(current["development"]["overall_change"], 2)
        self.assertEqual(current["development"]["potential_change"], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
