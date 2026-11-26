import tempfile
import unittest
from pathlib import Path

from atlas.commission import _briefing_facts, _deterministic_report_summary
from atlas.db import Database


class YouthDevelopmentReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tmp.name) / "atlas.sqlite3")
        with self.database.transaction() as conn:
            conn.execute("""INSERT INTO careers(id,public_id,fingerprint_candidate,display_name,created_at,updated_at)
                            VALUES(1,'career','fingerprint','Career','now','now')""")
            conn.executemany(
                """INSERT INTO snapshots(id,career_id,external_snapshot_id,schema_version,season_index,import_sequence,
                                           career_date,career_date_sort,managed_team_ea_id,managed_team_name,exported_at_utc,
                                           content_hash,import_status,source_path,imported_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(1, 1, 'one', '1', 0, 1, '2025-08-01', 20250801, 10, 'Home', 'now', 'one', 'valid', 'test', 'now'),
                 (2, 1, 'two', '1', 0, 2, '2025-09-01', 20250901, 10, 'Home', 'now', 'two', 'valid', 'test', 'now')],
            )
            conn.executemany(
                """INSERT INTO youth_player_states(snapshot_id,player_ea_id,display_name,overall,potential,primary_position,raw_json)
                   VALUES(?,?,?,?,?,?,?)""",
                [(1, 101, 'Prospect', 60, 84, 'CM', '{}'), (2, 101, 'Prospect', 63, 84, 'CM', '{}')],
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_uses_registered_path_and_exposes_academy_data_boundary(self):
        with self.database.connect() as conn:
            context, fact_ids, scope = _briefing_facts(conn, 1, 2, 'youth_development', None, 101)

        facts = {item['id']: item['value'] for item in context['facts']}
        self.assertEqual(scope, 'youth_development:101')
        self.assertEqual(facts['youth_profile']['registered_position'], 'CM')
        self.assertEqual([row['overall'] for row in facts['youth_trajectory']], [60, 63])
        self.assertEqual(facts['academy_data_limitations']['youth_5v5_match_statistics'], 'unavailable')
        self.assertEqual(facts['academy_data_limitations']['automatic_position_change'], 'not supported')
        self.assertIn('professional_evidence', fact_ids)
        summary = _deterministic_report_summary(context)
        self.assertIn('não há estatísticas ou minutos de partidas da base', summary['text'])
        self.assertIn('academy_data_limitations', summary['fact_refs'])

    def test_rejects_a_player_missing_from_the_selected_youth_snapshot(self):
        with self.database.connect() as conn:
            with self.assertRaisesRegex(ValueError, 'not in the youth export'):
                _briefing_facts(conn, 1, 2, 'youth_development', None, 999)


if __name__ == '__main__':
    unittest.main()
