"""HTTP projection and read-only access for sporting reports."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from atlas.monthly_report_api import compact_report, markdown_download
from atlas.server_http import ApiHandler


def sample_report():
    return {
        "careerId": 1, "careerFingerprint": "career", "seasonIndex": 1,
        "snapshotId": 2, "snapshotCareerDate": "2025-08-31", "teamEaId": 10,
        "teamName": "Club", "fixtureCount": 1, "playerCount": 1,
        "months": [{
            "month": "2025-08", "partial": True, "snapshotIdForPlayerState": 2,
            "competitions": {}, "pointsLeague": 3, "goalsFor": 2,
            "goalsAgainst": 1, "resultCoverage": 1, "pointsPct": 100,
            "exports": 0, "metricCoverage": {}, "rosterChanges": None,
            "matches": [{"fixtureId": 5, "date": "2025-08-20", "opponent": "A",
                         "goalsFor": 2, "goalsAgainst": 1, "standouts": [],
                         "teamStats": {"shots": 4, "private_raw": 99},
                         "evidence": {"state": "missing", "reason": "no export"}}],
            "players": [{"playerEaId": 7, "name": "Player", "minutes": 90,
                         "sampleCode": "short", "private_raw": "omit"}],
        }],
    }


class MonthlyReportApiTests(unittest.TestCase):
    def test_projection_keeps_null_and_omits_raw_details(self):
        result = compact_report(sample_report())
        match = result["months"][0]["matches"][0]
        self.assertEqual(match["teamStats"]["shots"], 4)
        self.assertIsNone(match["teamStats"]["passes"])
        self.assertEqual(match["evidenceState"], "missing")
        self.assertNotIn("private_raw", str(result))
        self.assertEqual(result["months"][0]["players"][0]["sampleCode"], "short")

    def test_download_uses_selected_month_without_relative_navigation(self):
        with patch("atlas.monthly_report_api.render_season", return_value="season text") as season_renderer:
            season = markdown_download(sample_report())
        self.assertEqual(season["content"], "season text")
        self.assertFalse(season_renderer.call_args.kwargs["navigation"])
        with patch("atlas.monthly_report_api.render_month", return_value="month text") as month_renderer:
            result = markdown_download(sample_report(), "2025-08")
        self.assertEqual(result["fileName"], "atlas-2025-08-snapshot-2.md")
        self.assertEqual(result["content"], "month text")
        self.assertFalse(month_renderer.call_args.kwargs["navigation"])
        with self.assertRaises(ValueError):
            markdown_download(sample_report(), "2025-09")

    def test_http_route_opens_database_read_only_and_filters_month(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "atlas.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE existing (id INTEGER)")
            handler = ApiHandler.__new__(ApiHandler)
            handler.server = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(path=path)))
            handler._json = Mock()

            def build(conn, career_id, season_index, snapshot_id):
                self.assertEqual((career_id, season_index, snapshot_id), (1, 1, 2))
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("CREATE TABLE forbidden (id INTEGER)")
                return sample_report()

            with patch("atlas.monthly_reports.build_season_report", side_effect=build):
                handler._api_get("/api/careers/1/sporting-reports", {
                    "season_index": ["1"], "snapshot_id": ["2"], "month": ["2025-08"]})
                payload = handler._json.call_args.args[0]
                self.assertEqual(len(payload["months"]), 1)
                with self.assertRaises(ValueError):
                    handler._api_get("/api/careers/1/sporting-reports", {
                        "season_index": ["1"], "snapshot_id": ["2"], "month": ["2025-13"]})
                with self.assertRaises(ValueError):
                    handler._api_get("/api/careers/1/sporting-reports", {
                        "season_index": ["1"], "snapshot_id": ["2"], "month": ["2025-09"]})


if __name__ == "__main__":
    unittest.main()
