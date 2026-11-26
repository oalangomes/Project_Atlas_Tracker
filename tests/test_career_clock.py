import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from atlas.server_http import ApiHandler


class CareerClockViewsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE careers(id INTEGER);
            INSERT INTO careers VALUES(1),(2);
            CREATE TABLE snapshots(id INTEGER,career_id INTEGER,import_sequence INTEGER,career_date TEXT,
                                   season_index INTEGER,managed_team_ea_id INTEGER);
            INSERT INTO snapshots VALUES(10,1,5,'2026-03-01',1,100);
            CREATE TABLE transfer_pulses(id INTEGER,public_id TEXT,career_id INTEGER,career_date TEXT,
                career_date_sort INTEGER,season_index INTEGER,managed_team_ea_id INTEGER,player_count INTEGER,
                loan_count INTEGER,generated_at_utc TEXT,imported_at TEXT);
            INSERT INTO transfer_pulses VALUES
                (11,'older',1,'2026-02-25',20260225,1,100,23,2,NULL,'now'),
                (12,'live',1,'2026-03-10',20260310,1,100,24,2,NULL,'now');
        """)
        self.handler = ApiHandler.__new__(ApiHandler)
        self.handler.server = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(connect=lambda: self.conn)))
        self.handler._json = Mock()

    def test_summary_matches_full_clock_and_does_not_read_pulse_history(self):
        self.handler._api_get("/api/careers/1/clock", {})
        full = self.handler._json.call_args.args[0]
        self.assertEqual(full["pulseCount"], 2)
        self.assertEqual([pulse["id"] for pulse in full["recentPulses"]], [12, 11])

        statements = []
        self.conn.set_trace_callback(statements.append)
        self.handler._api_get("/api/careers/1/clock", {"view": ["summary"]})
        summary = self.handler._json.call_args.args[0]
        self.assertEqual(summary, {key: value for key, value in full.items() if key not in {"pulseCount", "recentPulses"}})
        self.assertEqual(summary["careerDate"], "2026-03-10")
        self.assertEqual(summary["source"], "transfer_pulse")
        self.assertEqual(self.handler._json.call_args.kwargs, {"apply_presentation": False})
        self.assertEqual(len(statements), 2)

    def test_empty_and_unknown_careers_keep_their_status(self):
        self.handler._api_get("/api/careers/2/clock", {})
        empty = self.handler._json.call_args.args[0]
        self.assertEqual(empty["recentPulses"], [])
        self.handler._api_get("/api/careers/2/clock", {"view": ["summary"]})
        self.assertEqual(self.handler._json.call_args.args[0],
                         {key: value for key, value in empty.items() if key != "recentPulses"})
        with self.assertRaisesRegex(ValueError, "Career not found"):
            self.handler._api_get("/api/careers/3/clock", {"view": ["summary"]})
