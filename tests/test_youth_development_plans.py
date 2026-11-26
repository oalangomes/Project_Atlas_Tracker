import sqlite3
import tempfile
import unittest
from pathlib import Path

from atlas.db import Database
from atlas.manual_data import ManualDataService


class YouthDevelopmentPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tmp.name) / "atlas.sqlite3")
        with self.database.transaction() as conn:
            conn.executemany(
                """INSERT INTO careers(id,public_id,fingerprint_candidate,display_name,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                [(1, "career-one", "fingerprint-one", "One", "now", "now"),
                 (2, "career-two", "fingerprint-two", "Two", "now", "now")],
            )
            conn.executemany(
                """INSERT INTO snapshots(id,career_id,external_snapshot_id,schema_version,season_index,
                           career_date,career_date_sort,managed_team_ea_id,managed_team_name,exported_at_utc,
                           content_hash,import_status,source_path,imported_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(1, 1, "snapshot-one", "1", 0, "2025-09-01", 20250901, 10, "Home",
                  "2025-09-01T00:00:00Z", "hash-one", "valid", "test", "2025-09-01T00:00:00Z"),
                 (2, 2, "snapshot-two", "1", 0, "2025-09-01", 20250901, 20, "Other",
                  "2025-09-01T00:00:00Z", "hash-two", "valid", "test", "2025-09-01T00:00:00Z")],
            )
            conn.execute(
                """INSERT INTO youth_player_states(snapshot_id,player_ea_id,display_name,overall,potential,primary_position,raw_json)
                   VALUES(1,101,'Prospect',62,84,'CM','{}')"""
            )
            conn.execute(
                """INSERT INTO youth_player_states(snapshot_id,player_ea_id,display_name,overall,potential,primary_position,raw_json)
                   VALUES(2,101,'Different career prospect',62,84,'CM','{}')"""
            )
        self.service = ManualDataService(self.database)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def payload(**changes):
        value = {
            "playerEaId": 101,
            "basisSnapshotId": 1,
            "displayName": "Prospect",
            "intendedRole": "Left-sided creator",
            "objectives": "Review first touch and passing choices.",
            "opportunityPriority": "standard",
            "integrationDecision": "monitor",
            "horizonDate": "2026-01-15",
            "notes": "Coach observation.",
        }
        value.update(changes)
        return value

    def test_plan_revisions_are_immutable_and_keep_the_original_decision(self):
        first = self.service.save_youth_plan(1, self.payload())
        second = self.service.save_youth_plan(1, self.payload(
            objectives="Review passing choices in the next monthly meeting.",
            opportunityPriority="high", integrationDecision="review",
        ))

        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        plans = self.service.youth_plans(1, 101)
        self.assertEqual(len(plans), 1)
        self.assertEqual([row["revision"] for row in plans[0]["revisions"]], [2, 1])
        self.assertEqual(plans[0]["revisions"][1]["objectives"], "Review first touch and passing choices.")
        self.assertEqual(plans[0]["revisions"][0]["integrationDecision"], "review")
        with self.database.connect() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE manual_youth_development_plan_revisions SET recorded_at='changed' WHERE plan_id=?", (first["id"],))

    def test_archive_preserves_history_and_hides_the_active_plan(self):
        plan = self.service.save_youth_plan(1, self.payload())
        archived = self.service.archive_youth_plan(1, plan["id"])

        self.assertEqual(archived["revision"], 2)
        self.assertEqual(self.service.youth_plans(1), [])
        history = self.service.youth_plans(1, 101, include_inactive=True)[0]
        self.assertFalse(history["active"])
        self.assertEqual([row["revision"] for row in history["revisions"]], [2, 1])
        self.assertFalse(history["revisions"][0]["active"])

    def test_plan_requires_a_youth_player_in_a_snapshot_of_the_same_career(self):
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.service.save_youth_plan(1, self.payload(basisSnapshotId=2))
        with self.assertRaisesRegex(ValueError, "not present in the youth export"):
            self.service.save_youth_plan(1, self.payload(playerEaId=999))


if __name__ == "__main__":
    unittest.main()
