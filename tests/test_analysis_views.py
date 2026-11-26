import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atlas.server_http import ApiHandler


class AnalysisViewTests(unittest.TestCase):
    def test_performance_view_uses_only_match_data_and_accepts_all_seasons(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE snapshots(id INTEGER, career_id INTEGER, season_index INTEGER,
                                   import_sequence INTEGER, managed_team_ea_id INTEGER);
            INSERT INTO snapshots VALUES (9, 1, 0, 3, 100), (10, 1, 1, 4, 100), (11, 2, 1, 5, 200);
        """)
        handler = ApiHandler.__new__(ApiHandler)
        handler.server = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(connect=lambda: conn)))
        handler._json = Mock()
        handler._season_options = Mock(return_value=[{"season_index": 0}, {"season_index": 1}])
        path = "/api/careers/1/analysis"
        query = {"snapshot_id": ["9"], "season_index": ["-1"], "view": ["performance"]}

        with patch("atlas.server_query_analysis.detailed_analysis", return_value={"matchesCovered": 8}) as detailed, \
             patch("atlas.server_query_analysis.defense_context", return_value={"available": True}) as defense:
            handler._api_get(path, query)

        detailed.assert_called_once_with(conn, 1, [0, 1], 100, as_of_import_sequence=4)
        defense.assert_called_once_with(conn, 1, [0, 1], 100, as_of_import_sequence=4)
        self.assertEqual(handler._json.call_args.args[0], {
            "careerId": 1,
            "snapshotId": 9,
            "selectedSnapshotId": 10,
            "seasonOptions": [{"season_index": 0}, {"season_index": 1}],
            "selectedSeasonIndex": -1,
            "selectedSeasonLabel": "All seasons",
            "matchIntelligence": {"matchesCovered": 8},
            "defenseContext": {"available": True},
        })
        with self.assertRaisesRegex(ValueError, "Unsupported analysis view"):
            handler._api_get(path, {**query, "view": ["unknown"]})
