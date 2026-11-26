import os
import tempfile
import unittest
from pathlib import Path
from struct import pack_into
from unittest.mock import patch

from atlas.db import Database
from atlas.fc26_save_possession import SavePossessionImporter, decode_save_possession, snapshot_save_possession
from atlas.importer import SnapshotImporter
from atlas.manifest import SnapshotContract, SnapshotValidator
from atlas.match_stats_importer import MatchStatsImporter
from atlas.metric_evidence import snapshot_fixture_evidence
from atlas.watcher import HotFolderWatcher


def make_save(slots=36, home_pct=46, score=1, repeated_day=20260317):
    trailer = 0x198 + slots * 0x92
    match = bytearray(trailer + 0x2A5)
    match[:6] = b"mxif\x01\x01"
    pack_into("<I", match, 0x192, slots)
    pack_into("<I", match, 0x1D, home_pct)
    pack_into("<I", match, 0xDD, 100 - home_pct)
    pack_into("<I", match, trailer + 409, 20260317)
    pack_into("<II", match, trailer + 645, 1929, 361)
    pack_into("<I", match, trailer + 668, repeated_day)
    for index in range(slots):
        pack_into("<I", match, 0x198 + index * 0x92, 1000 + index)
    history = bytearray(116)
    history[:4] = b"mham"
    pack_into("<I", history, 20, 3)
    history[24] = 1
    pack_into("<IIII", history, 25, 1929, 361, score, 0)
    return b"FBCHUNKS" + match + b"mrni" + history + b"mssm"


class SavePossessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = Database(self.root / "atlas.sqlite3")
        self.importer = SavePossessionImporter(self.db, self.root)

    def write_save(self, name="CmMgrC1", **kwargs):
        path = self.root / name
        timestamp = path.stat().st_mtime_ns + 1_000_000_000 if path.exists() else 1_000_000_000
        path.write_bytes(make_save(**kwargs))
        os.utime(path, ns=(timestamp, timestamp))

    def add_observation(self, career=1, snapshot=2, fixture=9, players=range(1000, 1016)):
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO careers (id,public_id,fingerprint_candidate,display_name,created_at,updated_at)"
                         " VALUES (? ,?,?,'Career','','')", (career, f"career-{career}", f"fp-{career}"))
            conn.execute("""INSERT INTO snapshots
                         (id,career_id,external_snapshot_id,schema_version,season_index,career_date,career_date_sort,
                          managed_team_ea_id,exported_at_utc,import_sequence,content_hash,import_status,source_path,imported_at)
                         VALUES (?, ?, ?, '1', 1, '2026-03-18', 20260318, 1929, '', ?, ?, 'imported', '', '')""",
                         (snapshot, career, f"snapshot-{snapshot}", snapshot, f"hash-{snapshot}"))
            conn.execute("INSERT OR IGNORE INTO fixtures (id,career_id,fixture_key,home_team_ea_id,away_team_ea_id)"
                         " VALUES (?,?,'fixture',1929,361)", (fixture, career))
            conn.execute("""INSERT INTO fixture_observations
                         (snapshot_id,fixture_id,fixture_key,date,is_completed,home_score,away_score,managed_team_involved,raw_json)
                         VALUES (?,?,'fixture','2026-03-17',1,1,0,1,'{}')""", (snapshot, fixture))
            conn.executemany("""INSERT INTO player_match_performances
                             (snapshot_id,artificial_key,fixture_key,join_status,player_ea_id,minutes_played,raw_json)
                             VALUES (?,?,'fixture','joined_by_date',?,90,'{}')""",
                             [(snapshot, str(player), player) for player in players])

    def test_decodes_both_layouts_and_rejects_invalid_evidence(self):
        for slots in (36, 40):
            match = decode_save_possession(make_save(slots=slots))
            self.assertEqual((match.home_pct, match.away_pct, match.match_date), (46, 54, "2026-03-17"))
            self.assertEqual(len(match.home_players), slots // 2)
        self.assertIsNone(decode_save_possession(make_save(slots=34)))
        self.assertIsNone(decode_save_possession(make_save(repeated_day=20260316)))
        self.assertIsNone(decode_save_possession(make_save()[:-4]))

    def test_watcher_imports_after_fixture_arrives_and_exposes_direct_source(self):
        self.write_save()
        schemas = Path(__file__).resolve().parents[1] / "schemas"
        contract = SnapshotContract(schemas / "FC26_CareerTracker_Snapshot_Contract_v1.2.0.json")
        watcher = HotFolderWatcher(SnapshotImporter(self.db, SnapshotValidator(contract)))
        watcher.save_possession = self.importer
        status = MatchStatsImporter(self.db)
        before = status.status()
        with patch("atlas.watcher.read_snapshot_root", return_value=None):
            watcher.scan_once()
            self.add_observation()
            watcher.scan_once()
            watcher.scan_once()
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            evidence = snapshot_fixture_evidence(conn, snapshot)[0]["evidence"]
            self.assertEqual([team["indicators"][0]["value"] for team in evidence["teams"]], [46, 54])
            self.assertEqual(evidence["teams"][0]["indicators"][0]["source"]["kind"], "fc26_save_mxif")
            self.assertEqual(evidence["state"], "absent")
            self.assertEqual(snapshot_save_possession(conn, {**snapshot, "import_sequence": 1}), {})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_possession").fetchone()[0], 1)
        after = status.status()
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(before["exports"], after["exports"])

    def test_refuses_wrong_scores_players_ambiguous_careers_and_conflicting_saves(self):
        self.add_observation(players=range(1000, 1010))
        self.write_save()
        self.assertEqual(self.importer.scan_once(), 0)
        self.add_observation(snapshot=3)
        self.write_save(score=2)
        self.assertEqual(self.importer.scan_once(), 0)
        self.write_save()
        self.write_save("CmMgrC2", home_pct=60)
        self.assertEqual(self.importer.scan_once(), 0)
        (self.root / "CmMgrC2").unlink()
        self.add_observation(career=2, snapshot=4, fixture=10)
        self.assertEqual(self.importer.scan_once(), 0)
