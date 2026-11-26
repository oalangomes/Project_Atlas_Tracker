import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas.db import Database
from atlas.finance_core import FinanceCoreService
from atlas.financial import FinancialService, PROFILE_FILE
from atlas.player_dynamics import MODEL_ID as DYNAMIC_MODEL, PlayerDynamicsService
from atlas.player_finance import PlayerFinanceService
from atlas.server_queries import QueryApiMixin
from atlas.server_utils import effective_career_date
from atlas.team_strength import live_squad_strength
from atlas.world_simulation import MODEL_ID as WORLD_MODEL


class SquadFinanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = Database(Path(folder.name) / "atlas.sqlite3")
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO careers(id,public_id,fingerprint_candidate,display_name,created_at,updated_at) "
                "VALUES(1,'career','fingerprint','Career','now','now')"
            )
            conn.executemany(
                """INSERT INTO snapshots(id,career_id,external_snapshot_id,schema_version,season_index,career_date,
                       career_date_sort,managed_team_ea_id,import_sequence,exported_at_utc,content_hash,
                       import_status,source_path,imported_at)
                   VALUES(?,1,?,'1',0,?,?,100,?,'now',?,'valid','test','now')""",
                [(1, "historical", "2026-02-01", 20260201, 1, "hash-1"),
                 (2, "latest", "2026-03-01", 20260301, 2, "hash-2")],
            )
            conn.executemany(
                """INSERT INTO entities(id,career_id,entity_type,ea_id,first_seen_snapshot_id,last_seen_snapshot_id)
                   VALUES(?,1,?,?,1,2)""",
                [(11, "player", "11"), (22, "player", "22"), (33, "player", "33"),
                 (100, "team", "100"), (200, "team", "200")],
            )
            for snapshot_id in (1, 2):
                conn.executemany(
                    """INSERT INTO team_states(snapshot_id,entity_id,ea_team_id,team_name,league_ea_id,league_name,raw_json)
                       VALUES(?,?,?,?,?,?,'{}')""",
                    [(snapshot_id, 100, 100, "Home", 13, "Premier League"),
                     (snapshot_id, 200, 200, "Away", 19, "Bundesliga")],
                )
                conn.executemany(
                    """INSERT INTO player_states(snapshot_id,entity_id,ea_player_id,display_name,team_ea_id,
                           overall,potential,primary_position,contract_valid_until,raw_json)
                       VALUES(?,?,?,?,?,?,80,'CM','2027-06-30','{"birthdate_raw":"20010305"}')""",
                    [(snapshot_id, 11, 11, "First", 100, 62), (snapshot_id, 22, 22, "Second", 100, 68),
                     (snapshot_id, 33, 33, "Third", 200, 75)],
                )
                conn.executemany(
                    """INSERT INTO roster_states(snapshot_id,player_entity_id,team_entity_id,player_ea_id,
                           team_ea_id,jersey_number,raw_json) VALUES(?,?,?,?,?,?,'{}')""",
                    [(snapshot_id, 11, 100, 11, 100, 9), (snapshot_id, 22, 100, 22, 100, 7),
                     (snapshot_id, 33, 200, 33, 200, 5)],
                )
                conn.executemany(
                    "INSERT INTO contract_states(snapshot_id,player_ea_id,team_ea_id,wage,raw_json) VALUES(?,?,?,?,'{}')",
                    [(snapshot_id, 11, 100, 1500), (snapshot_id, 33, 200, 2400)],
                )
                conn.execute(
                    "INSERT INTO atlas_world_simulation_runs(snapshot_id,model_version,created_at,updated_at) "
                    "VALUES(?,?,'now','now')", (snapshot_id, WORLD_MODEL),
                )
                conn.execute(
                    """INSERT INTO player_dynamic_states(career_id,snapshot_id,player_ea_id,base_overall,
                           potential,dynamic_overall,dynamic_delta,form_score,morale_score,fitness_score,
                           performance_source,confidence,model_version,created_at,updated_at)
                       SELECT 1,snapshot_id,ea_player_id,overall,potential,overall+1,1,60,70,80,'observed',
                              0.9,?,'now','now' FROM player_states WHERE snapshot_id=?""",
                    (DYNAMIC_MODEL, snapshot_id),
                )
            conn.execute(
                """INSERT INTO transfer_pulses(public_id,career_id,career_date,career_date_sort,
                       content_hash,source_path,imported_at)
                   VALUES('pulse-1',1,'2026-03-10',20260310,'pulse-hash','test','now')"""
            )

        profile = Path(__file__).resolve().parents[1] / "reference" / "financial" / PROFILE_FILE
        self.financial = FinancialService(self.database, profile)
        self.dynamics = PlayerDynamicsService(self.database)
        self.finance = PlayerFinanceService(self.database, self.financial,
                                            FinanceCoreService(self.database), self.dynamics)

    def test_batch_reuses_snapshot_and_club_inputs_without_merging_player_evidence(self):
        with patch.object(self.dynamics, "ensure_snapshot", wraps=self.dynamics.ensure_snapshot) as ensure, \
             patch("atlas.player_finance.effective_career_date", wraps=effective_career_date) as clock, \
             patch("atlas.player_finance.live_squad_strength", wraps=live_squad_strength) as strength:
            latest = self.finance.analyze_many(2, [11, 22, 33, 11])
            self.assertEqual(self.finance.analyze_many(999, []), {})

        ensure.assert_called_once_with(2)
        self.assertEqual(clock.call_count, 1)
        self.assertEqual([call.args[2] for call in strength.call_args_list], [100, 200])
        self.assertEqual(list(latest), [11, 22, 33])
        self.assertEqual([latest[pid]["context"]["squadAverageOverall"] for pid in latest], [65, 65, 75])
        self.assertEqual([latest[pid]["wage"]["current"] for pid in latest], [1500, None, 2400])
        self.assertEqual([latest[pid]["dynamic"]["dynamicOverall"] for pid in latest], [63, 69, 76])
        self.assertTrue(all(value["player"]["age"] == 25 for value in latest.values()))
        self.assertIsNot(latest[11]["context"]["leagueMarket"], latest[22]["context"]["leagueMarket"])
        self.assertEqual(self.finance.analyze(2, 11), latest[11])
        self.assertEqual(self.finance.analyze(1, 11)["player"]["age"], 24)
        with self.assertRaisesRegex(ValueError, "Dynamic performance value"):
            self.finance.analyze_many(2, [11, 999])

    def query(self):
        query = QueryApiMixin()
        query.state = SimpleNamespace(database=self.database, financial=self.financial,
                                      player_finance=self.finance, player_dynamics=self.dynamics,
                                      club_names=SimpleNamespace(mapping=lambda *_: {}),
                                      media=SimpleNamespace(team_identity=lambda *args, **kwargs: {},
                                                            player_media=lambda *_: {}))
        return query

    def test_squad_returns_finances_in_roster_order(self):
        query = self.query()
        with patch.object(self.dynamics, "ensure_snapshot", wraps=self.dynamics.ensure_snapshot) as ensure:
            payload = query._squad(2)
        ensure.assert_called_once_with(2)
        self.assertEqual([player["ea_player_id"] for player in payload["players"]], [22, 11])
        self.assertEqual([player["weekly_wage"] for player in payload["players"]], [None, 1500])
        self.assertEqual([player["dynamic_overall"] for player in payload["players"]], [69, 63])

    def test_squad_preview_uses_imported_data_even_if_simulation_is_pending(self):
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM atlas_world_simulation_runs WHERE snapshot_id=2")
            conn.execute("DELETE FROM player_dynamic_states WHERE snapshot_id=2")
        with patch.object(self.finance, "analyze_many") as finance:
            payload = self.query()._squad(2, include_finance=False)
        finance.assert_not_called()
        self.assertEqual([player["ea_player_id"] for player in payload["players"]], [22, 11])
        self.assertEqual([player["overall"] for player in payload["players"]], [68, 62])
        for player in payload["players"]:
            self.assertNotIn("market_value", player)
            self.assertNotIn("dynamic_overall", player)

    def test_club_batches_squad_finances_and_preserves_the_own_and_rival_rosters(self):
        query = self.query()
        with patch.object(self.dynamics, "ensure_snapshot", wraps=self.dynamics.ensure_snapshot) as ensure:
            managed = query._club(2, 100)
            rival = query._club(2, 200)
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual([player["ea_player_id"] for player in managed["squad"]], [22, 11])
        self.assertEqual(managed["summary"]["wage_total"], 1500)
        self.assertEqual([player["ea_player_id"] for player in rival["squad"]], [33])
        self.assertEqual(rival["squad"][0]["player_finance"]["wage"]["currentObserved"], 2400)
