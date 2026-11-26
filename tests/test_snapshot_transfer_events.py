import sqlite3
import unittest
from contextlib import closing

from atlas.server_query_analysis import AnalysisQueryMixin


class SnapshotTransferEventsTests(unittest.TestCase):
    def test_reports_only_club_changes_without_a_matching_loan(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE snapshots(id INTEGER, career_id INTEGER, season_index INTEGER,
                                       import_sequence INTEGER, career_date TEXT);
                CREATE TABLE player_states(snapshot_id INTEGER, ea_player_id INTEGER, display_name TEXT,
                                           team_ea_id INTEGER, team_name TEXT, overall INTEGER,
                                           primary_position TEXT, raw_json TEXT,
                                           PRIMARY KEY(snapshot_id, ea_player_id));
                CREATE TABLE loan_states(snapshot_id INTEGER, player_ea_id INTEGER,
                                         parent_team_ea_id INTEGER, loan_team_ea_id INTEGER,
                                         PRIMARY KEY(snapshot_id, player_ea_id, parent_team_ea_id, loan_team_ea_id));
                INSERT INTO snapshots VALUES
                    (1, 1, 0, 1, '2025-05-31'), (2, 1, 1, 2, '2025-07-01'),
                    (3, 2, 0, 1, '2025-06-01'), (4, 1, 1, 3, '2025-07-31');
                INSERT INTO player_states VALUES
                    (1, 11, 'Transfer', 100, 'Origin', 60, 'CM', '{}'),
                    (2, 11, '', 200, NULL, 62, 'CAM', '{"primary_position_id":18}'),
                    (1, 12, 'Unchanged', 100, NULL, 60, 'CM', '{}'),
                    (2, 12, 'Unchanged', 100, NULL, 60, 'CM', '{}'),
                    (1, 13, 'Unknown club', NULL, NULL, 60, 'CM', '{}'),
                    (2, 13, 'Unknown club', 200, NULL, 60, 'CM', '{}'),
                    (2, 14, 'Other career', 200, NULL, 60, 'CM', '{}'),
                    (3, 14, 'Other career', 100, NULL, 60, 'CM', '{}'),
                    (1, 15, 'Earlier loan', 100, NULL, 60, 'CM', '{}'),
                    (2, 15, 'Earlier loan', 200, NULL, 60, 'CM', '{}'),
                    (1, 16, 'New loan', 100, NULL, 60, 'CM', '{}'),
                    (2, 16, 'New loan', 200, NULL, 60, 'CM', '{}'),
                    (4, 12, 'Later transfer', 300, NULL, 60, 'CM', '{}');
                INSERT INTO loan_states VALUES (1, 15, 100, 200), (2, 16, 100, 200),
                                               (2, 11, 200, 100), (3, 11, 100, 200);
            """)
            query = AnalysisQueryMixin()
            events = query._snapshot_transfer_events(conn, 1, 1)
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, team_id=100), events)
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, team_id=200), events[:1])
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, team_id=300), events[1:])
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, team_id=900), [])
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, player_id=11), events[:1])
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, player_id=12), events[1:])
            self.assertEqual(query._snapshot_transfer_events(conn, 1, 1, player_id=15), [])

        self.assertEqual([event["player_ea_id"] for event in events], [11, 12])
        self.assertEqual(events[0], {
            "eventKey": "derived:1:2:11:100:200", "date": "2025-07-01", "season_index": 1,
            "fromSnapshotId": 1, "toSnapshotId": 2, "player_ea_id": 11,
            "display_name": "Transfer", "overall": 62, "primary_position": "CAM",
            "primary_position_id": 18, "from_team_ea_id": 100, "from_team_name": "Origin",
            "to_team_ea_id": 200, "to_team_name": "Team 200", "fee": None, "currency": "EUR",
            "source": "snapshot_difference", "source_label": "Derived", "event_status": "Completed",
        })
