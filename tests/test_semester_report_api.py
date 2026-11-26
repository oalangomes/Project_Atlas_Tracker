import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atlas.server_http import ApiHandler


class SemesterReportApiTests(unittest.TestCase):
    def test_route_reads_the_database_without_writing_and_validates_the_semester(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "atlas.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE existing (id INTEGER)")
            handler = ApiHandler.__new__(ApiHandler)
            handler.server = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(path=path)))
            handler._json = Mock()

            def season(conn, career_id, season_index, snapshot_id):
                self.assertEqual((career_id, season_index, snapshot_id), (1, 2, 9))
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("CREATE TABLE forbidden (id INTEGER)")
                return {"months": []}

            with patch("atlas.monthly_reports.build_season_report", side_effect=season), \
                 patch("atlas.semester_report.build_semester_report", return_value={"semester": 2}) as aggregate:
                handler._api_get("/api/careers/1/sporting-reports/semester", {
                    "season_index": ["2"], "snapshot_id": ["9"], "semester": ["2"]})
                self.assertEqual(handler._json.call_args.args[0], {"semester": 2})
                aggregate.assert_called_once_with({"months": []}, 2)
                with self.assertRaisesRegex(ValueError, "Semester"):
                    handler._api_get("/api/careers/1/sporting-reports/semester", {
                        "season_index": ["2"], "snapshot_id": ["9"], "semester": ["3"]})


if __name__ == "__main__":
    unittest.main()
