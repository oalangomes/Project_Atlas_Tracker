import sqlite3
import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
from unittest.mock import patch

from atlas.db import Database
from atlas.commission import _briefing_facts, _report_source_hash
from atlas.match_diary import (MatchDiaryService, diary_at_fixture, formation_context,
                               normalize_content, own_formation_context)
from atlas.server_http import ApiHandler


class FormationContextTests(unittest.TestCase):
    def test_partial_observation_never_becomes_complete_formation(self):
        content = normalize_content({"ownFormation": "4-4-2", "opponentDefensiveLine": 5,
                                     "opponentLineup": [{"playerEaId": 7, "starter": True,
                                                         "observedPosition": "CB"}]})
        result = formation_context(content)
        self.assertEqual(result["status"], "indeterminate")
        self.assertEqual(result["defensiveLine"], 5)
        self.assertIsNone(result["formation"])
        self.assertEqual(own_formation_context(content)["formation"], "4-4-2")

    def test_complete_observed_opponent_xi_is_estimated_not_confirmed(self):
        positions = ["GK", "LB", "LCB", "RCB", "RB", "LM", "LCM", "RCM", "RM", "LS", "RS"]
        content = normalize_content({"opponentLineup": [
            {"playerEaId": i + 1, "starter": True, "observedPosition": position}
            for i, position in enumerate(positions)]})
        result = formation_context(content)
        self.assertEqual(result["status"], "estimated_observed_xi")
        self.assertEqual(result["formation"], "4-4-2")

    def test_manual_hypothesis_and_confirmation_preserve_source(self):
        hypothesis = formation_context(normalize_content({"opponentHypothesis": "5-4-1",
            "opponentAlternative": "5-3-2", "opponentEvidence": "Five defenders observed"}))
        self.assertEqual(hypothesis["status"], "estimated_manual")
        self.assertEqual(hypothesis["alternative"], "5-3-2")
        confirmed = formation_context(normalize_content({"opponentFormation": "5-4-1",
            "opponentEvidence": "Coach observed the complete setup"}))
        self.assertEqual(confirmed["status"], "confirmed_manual")


class MatchDiaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tmp.name) / "atlas.sqlite3")
        with self.database.transaction() as conn:
            conn.executemany("""INSERT INTO careers(id,public_id,fingerprint_candidate,display_name,created_at,updated_at)
                VALUES(?,?,?,?,?,?)""", [(1, "c1", "f1", "One", "x", "x"),
                                            (2, "c2", "f2", "Two", "x", "x")])
            conn.execute("""INSERT INTO snapshots(id,career_id,external_snapshot_id,schema_version,season_index,
                career_date,career_date_sort,managed_team_ea_id,managed_team_name,exported_at_utc,
                content_hash,import_status,source_path,imported_at)
                VALUES(1,1,'s1','1',0,'2025-09-01',20250901,10,'Home',
                    '2025-09-01T00:00:00Z','h1','valid','x','2025-09-04T00:00:00Z')""")
            conn.executemany("INSERT INTO fixtures(id,career_id,fixture_key,home_team_ea_id,away_team_ea_id) VALUES(?,?,?,?,?)",
                             [(1, 1, "match-1", 10, 20), (2, 2, "match-2", 30, 40)])
            conn.execute("""INSERT INTO fixture_observations(snapshot_id,fixture_id,fixture_key,
                managed_team_involved,is_completed,date,home_team_name,away_team_name,home_score,away_score,raw_json)
                VALUES(1,1,'match-1',1,1,'2025-09-01','Home','Away',1,0,'{}')""")
        self.service = MatchDiaryService(self.database)

    def tearDown(self):
        self.tmp.cleanup()

    def test_revision_history_isolation_and_retrospective_read(self):
        with patch("atlas.match_diary._now", return_value="2025-09-03T00:00:00Z"):
            first = self.service.save(1, 1, {"snapshotId": 1, "author": "Coach A", "note": "Five at back",
                "opponentDefensiveLine": 5,
                "ownLineup": [{"playerEaId": 11, "starter": None, "observedPosition": "CB",
                               "onMinute": None, "offMinute": None}]})
        self.assertEqual(first["current"]["revision"], 1)
        self.assertFalse(first["current"]["retrospective"])
        self.assertEqual(first["current"]["formationContext"]["status"], "indeterminate")
        self.assertIsNone(first["current"]["content"]["ownLineup"][0]["onMinute"])
        with patch("atlas.match_diary._now", return_value="2025-09-05T00:00:00Z"):
            second = self.service.save(1, 1, {"snapshotId": 1, "expectedRevision": 1,
                "author": "Coach B", "note": "Observed full 5-4-1",
                "opponentFormation": "5-4-1", "opponentEvidence": "Complete shape seen"})
        self.assertEqual(second["current"]["revision"], 2)
        self.assertTrue(second["current"]["retrospective"])
        self.assertEqual(second["current"]["knownAtSnapshot"]["revision"], 1)
        self.assertEqual([item["revision"] for item in second["revisions"]], [2, 1])
        self.assertEqual(second["current"]["formationContext"]["status"], "confirmed_manual")
        with self.assertRaisesRegex(ValueError, "revision changed"):
            self.service.save(1, 1, {"expectedRevision": 1, "author": "Coach A", "note": "stale"})
        with self.assertRaisesRegex(ValueError, "career"):
            self.service.get(2, 1)
        with self.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fixture_observations").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE manual_match_diary_revisions SET author='bad' WHERE diary_id=1")

    def test_invalidation_preserves_revisions_and_can_reopen(self):
        with patch("atlas.match_diary._now", return_value="2025-09-03T00:00:00Z"):
            self.service.save(1, 1, {"author": "Coach", "note": "Initial"})
        with patch("atlas.match_diary._now", return_value="2025-09-05T00:00:00Z"):
            result = self.service.invalidate(1, 1, {"author": "Coach", "expectedRevision": 1})
        self.assertEqual(result["revision"], 2)
        history = self.service.get(1, 1, snapshot_id=1)
        self.assertIsNone(history["current"])
        self.assertEqual(len(history["revisions"]), 2)
        self.assertEqual(history["knownAtSnapshot"]["revision"], 1)
        reopened = self.service.save(1, 1, {"author": "Coach", "expectedRevision": 2,
                                             "note": "Reopened"})
        self.assertEqual(reopened["current"]["revision"], 3)

    def test_fixture_must_be_managed_and_present_in_snapshot(self):
        with self.assertRaisesRegex(ValueError, "career"):
            self.service.save(2, 1, {"author": "Coach", "note": "wrong career"})
        with self.assertRaisesRegex(ValueError, "snapshot"):
            self.service.save(1, 1, {"snapshotId": 999, "author": "Coach", "note": "wrong snapshot"})
        with self.database.connect() as conn:
            self.assertIsNone(diary_at_fixture(conn, 1, 1))

    def test_diary_revision_changes_only_affected_report_evidence(self):
        with self.database.connect() as conn:
            before, _, scope = _briefing_facts(conn, 1, 1, "match", 1, None)
            before_hash = _report_source_hash(before, 1, "match", scope)
            self.assertNotIn("coach_diary", {fact["id"] for fact in before["facts"]})
        self.service.save(1, 1, {"author": "Coach", "note": "Observed late press"})
        with self.database.connect() as conn:
            after, _, scope = _briefing_facts(conn, 1, 1, "match", 1, None)
            after_hash = _report_source_hash(after, 1, "match", scope)
            coach = next(fact for fact in after["facts"] if fact["id"] == "coach_diary")
            self.assertIn("manual", coach["source"])
            self.assertTrue(coach["value"]["retrospective_to_snapshot"])
            self.assertNotEqual(before_hash, after_hash)

    def test_http_save_and_read_use_career_fixture_route(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
        passthrough = SimpleNamespace(apply_payload=lambda payload, *args, **kwargs: payload)
        server.state = SimpleNamespace(diary=self.service, database=self.database,
                                       club_names=passthrough, settings=passthrough)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/careers/1/matches/1/diary"
            body = json.dumps({"snapshotId": 1, "author": "Coach", "note": "Manual note"}).encode()
            with urlopen(Request(url + "/save", data=body,
                                 headers={"Content-Type": "application/json"}), timeout=5) as response:
                saved = json.load(response)
            self.assertEqual(saved["current"]["revision"], 1)
            with urlopen(url + "?snapshotId=1", timeout=5) as response:
                read = json.load(response)
            self.assertEqual(read["current"]["content"]["note"], "Manual note")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class DiaryMigrationTests(unittest.TestCase):
    def test_schema_upgrade_backs_up_existing_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            conn = sqlite3.connect(path)
            conn.executescript("CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT);"
                               "INSERT INTO app_meta VALUES('schema_version','1');"
                               "CREATE TABLE manual_test(value TEXT); INSERT INTO manual_test VALUES('preserved');")
            conn.close()
            db = Database(path)
            backups = db.list_backups()
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]["scope"], "manual_context")
            with closing(sqlite3.connect(backups[0]["path"])) as backup:
                self.assertEqual(backup.execute("SELECT value FROM manual_test").fetchone()[0], "preserved")
            with db.connect() as upgraded:
                self.assertEqual(upgraded.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()[0], "2")
                self.assertTrue(upgraded.execute("SELECT 1 FROM sqlite_master WHERE name='manual_match_diary'").fetchone())
