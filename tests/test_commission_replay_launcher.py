"""Tests for the local HTTP launcher of chronological commission reports."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.replay_commission_reports import (
    AtlasAPI, ReplayError, career_options, choose_number, job_path,
    main, seasons_from_snapshots, validate_base_url, watch_job,
)


EXAMPLE_JOB = "a" * 32


class ReplayLauncherContractTests(unittest.TestCase):
    def test_only_local_urls_are_allowed(self):
        self.assertEqual(validate_base_url("http://127.0.0.1:8765/"),
                         "http://127.0.0.1:8765")
        for url in ("https://127.0.0.1:8765", "http://example.com:8765",
                    "http://127.0.0.1:8765/path", "http://127.0.0.1",
                    "http://evil@127.0.0.1:8765", "http://localhost:8765/?x=1"):
            with self.subTest(url=url), self.assertRaises(ReplayError):
                validate_base_url(url)

    def test_zero_is_an_exact_valid_season_index(self):
        seasons = seasons_from_snapshots([
            {"season_index": 0, "season_label": "2025/26", "career_date": "2025-12-01", "import_sequence": 1},
            {"season_index": 0, "season_label": "2025/26", "career_date": "2025-12-20", "import_sequence": 2},
            {"season_index": 1, "season_label": "2026/27", "career_date": "2026-08-01", "import_sequence": 3},
        ])
        self.assertEqual([s["index"] for s in seasons], [1, 0])
        selected = choose_number(seasons, "index", "temporada", 0, interactive=False)
        self.assertEqual(selected["count"], 2)
        self.assertEqual(selected["latest_date"], "2025-12-20")

    def test_rejects_unknown_team_and_malformed_job_id(self):
        careers = career_options([
            {"id": 1, "display_name": "Plymouth", "snapshot_count": 4,
             "latestSnapshot": {"managed_team_name": "Plymouth Argyle"}},
            {"id": 2, "display_name": "Sheffield", "snapshot_count": 10,
             "latestSnapshot": {"managed_team_name": "Sheffield United"}},
        ])
        self.assertIn("Sheffield United", choose_number(
            careers, "id", "carreira", 2, False)["label"])
        with self.assertRaises(ReplayError):
            choose_number(careers, "id", "carreira", 3, False)
        with self.assertRaises(ReplayError):
            job_path(1, "not-a-job")

    def test_remote_http_stub_preserves_explicit_zero_in_POST(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b'{"job_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        with patch("scripts.replay_commission_reports.urllib.request.urlopen",
                   return_value=FakeResponse()) as call:
            response = AtlasAPI().request(
                "/api/careers/1/commission/retroactive-report-jobs",
                {"season_index": 0})
        self.assertEqual(response["job_id"], EXAMPLE_JOB)
        request = call.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"season_index": 0})
        self.assertEqual(call.call_args.kwargs["timeout"], 600.0)

    def test_status_read_keeps_short_timeout(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b'{}'
        with patch("scripts.replay_commission_reports.urllib.request.urlopen",
                   return_value=FakeResponse()) as call:
            AtlasAPI().request("/api/careers")
        self.assertEqual(call.call_args.kwargs["timeout"], 20.0)

    def test_poll_reports_progress_and_does_not_restart_jobs(self):
        states = [
            {"status": "queued", "total_tasks": 12, "completed_tasks": 0},
            {"status": "running", "total_tasks": 12, "completed_tasks": 4,
             "generated": 3, "reused": 1, "current_task": "rodada 2"},
            {"status": "complete_with_warnings", "total_tasks": 12,
             "completed_tasks": 12, "review_required": 2, "failed": 1},
        ]
        class FakeApi:
            def __init__(self):
                self.calls = []

            def request(self, path):
                self.calls.append(path)
                return states.pop(0)
        api = FakeApi()
        printed = []
        final = watch_job(api, 3, EXAMPLE_JOB, poll_seconds=1,
                          sleeper=lambda _: None, printer=printed.append)
        self.assertEqual(final["status"], "complete_with_warnings")
        self.assertEqual(len(api.calls), 3)
        self.assertTrue(all("/retroactive-report-jobs/" in path for path in api.calls))
        self.assertTrue(any("4/12" in message for message in printed))

    def test_launcher_starts_correct_career_and_season_without_following(self):
        class FakeApi:
            calls = []

            def __init__(self, *args):
                pass

            def request(self, path, payload=None):
                self.calls.append((path, payload))
                if path == "/api/careers":
                    return [{"id": 17, "display_name": "Save", "snapshot_count": 3,
                             "latestSnapshot": {"managed_team_name": "Plymouth Argyle"}}]
                if path == "/api/careers/17/snapshots":
                    return [{"season_index": 0, "season_label": "2025/26", "career_date": "2025-08-01", "import_sequence": 1}]
                if path.endswith("/commission/retroactive-report-jobs"):
                    return {"job_id": EXAMPLE_JOB, "model": "qwen3.5:9b",
                            "report_version": 32, "backup_path": "C:/backups/atlas.sqlite3"}
                raise AssertionError("Unexpected API " + path)
        with patch("scripts.replay_commission_reports.AtlasAPI", FakeApi), redirect_stdout(io.StringIO()):
            code = main(["--career-id", "17", "--season-index", "0", "--yes", "--no-watch"])
        self.assertEqual(code, 0)
        self.assertEqual(FakeApi.calls[-1], (
            "/api/careers/17/commission/retroactive-report-jobs", {"season_index": 0}))

    def test_dry_run_does_not_start_generation(self):
        class FakeApi:
            calls = []

            def __init__(self, *args):
                pass

            def request(self, path, payload=None):
                self.calls.append((path, payload))
                if path == "/api/careers":
                    return [{"id": 1, "display_name": "Career", "latestSnapshot": {"managed_team_name": "Sheffield United"}}]
                if path == "/api/careers/1/snapshots":
                    return [{"season_index": 2, "season_label": "2027/28",
                             "career_date": "2027-06-01", "import_sequence": 50}]
                raise AssertionError("Dry-run should not POST")
        with patch("scripts.replay_commission_reports.AtlasAPI", FakeApi), redirect_stdout(io.StringIO()):
            code = main(["--career-id", "1", "--season-index", "2", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(len(FakeApi.calls), 2)

    def test_audit_runs_only_after_replay_reaches_final_status(self):
        class FakeApi:
            def __init__(self, *args):
                pass

            def request(self, path, payload=None):
                if path == "/api/careers/7":
                    return {"career": {"id": 7}}
                if path.endswith(EXAMPLE_JOB):
                    return {"status": "complete", "total_tasks": 10,
                            "completed_tasks": 10, "generated": 8, "reused": 2}
                raise AssertionError(path)
        with patch("scripts.replay_commission_reports.AtlasAPI", FakeApi), \
             patch("scripts.replay_commission_reports.audit_database",
                   return_value={"scanned": 10, "flags": {}}) as audit, \
             redirect_stdout(io.StringIO()):
            code = main(["--career-id", "7", "--job-id", EXAMPLE_JOB, "--audit-db", "db.sqlite3"])
        self.assertEqual(code, 0)
        audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
