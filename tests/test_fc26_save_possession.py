import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from struct import pack_into
from unittest.mock import patch

from atlas.db import Database
from atlas.fc26_save_feed import snapshot_save_career_feed
from atlas.fc26_save_match import read_saved_match
from atlas.fc26_save_participation import fixture_save_participation
from atlas.fc26_save_comparison import fixture_save_stat_sources
from atlas.fc26_save_possession import (
    SavePossessionImporter, decode_save_possession, fixture_save_player_passes,
    snapshot_save_passes, snapshot_save_possession,
)
from atlas.importer import SnapshotImporter
from atlas.manifest import SnapshotContract, SnapshotValidator
from atlas.match_stats_importer import MatchStatsImporter
from atlas.metric_evidence import snapshot_fixture_evidence
from atlas.watcher import HotFolderWatcher


def make_save(slots=36, home_pct=46, score=1, repeated_day=20260317, home_through=32,
              extra_passing=False, played_day=20260317, clubs=(1929, 361), player_start=1000,
              history_records=3):
    trailer = 0x198 + slots * 0x92
    match = bytearray(trailer + 0x2A5)
    match[:6] = b"mxif\x01\x01"
    pack_into("<I", match, 0x192, slots)
    pack_into("<I", match, 0x1D, home_pct)
    pack_into("<I", match, 0xDD, 100 - home_pct)
    for offset, values in (
        (0x11, {4: 138, 9: 114, 13: 36, 14: home_through, 16: 6, 17: 3, 19: 4, 22: 4, 28: 6}),
        (0xD1, {4: 155, 9: 136, 13: 34, 14: 28, 16: 7, 17: 4, 19: 8, 22: 0, 28: 0}),
    ):
        for slot, value in values.items():
            pack_into("<I", match, offset + slot * 4, value)
    pack_into("<I", match, trailer + 409, played_day)
    pack_into("<II", match, trailer + 645, *clubs)
    pack_into("<I", match, trailer + 668, repeated_day)
    for index in range(slots):
        pack_into("<I", match, 0x198 + index * 0x92, player_start + index)
    for index, ground, lobbed in ((0, 2, 0), (1, home_through - 2, 3), (slots // 2, 28, 4)):
        offset = 0x198 + index * 0x92
        for field, value in ((0x14, ground + lobbed), (0x3C, ground + lobbed), (0x4C, ground), (0x50, lobbed)):
            pack_into("<I", match, offset + field, value)
    if extra_passing:
        for slot, value in ((31, 3), (32, 2), (37, 4), (38, 1)):
            pack_into("<I", match, 0x11 + slot * 4, value)
        for field, value in ((0x14, 114 - home_through - 1), (0x3C, 114 - home_through - 1),
                             (0x58, 2), (0x60, 1)):
            pack_into("<I", match, 0x198 + field, value)
    history = bytearray(24 + history_records * 29 + 5)
    history[:4] = b"mham"
    pack_into("<I", history, 20, history_records)
    if history_records:
        history[24] = 1
        pack_into("<IIII", history, 25, *clubs, score, 0)
    return b"FBCHUNKS" + match + b"mrni" + history + b"mssm"


def make_participation_block(count, *, overlap=False):
    block = bytearray(26 + 90 * count + 4)
    block[:6] = b"mflp\x01\x01"
    for offset, value in ((11, 1929), (16, 1929), (21, count)):
        pack_into("<I", block, offset, value)
    for index in range(count):
        offset = 26 + 90 * index
        pack_into("<I", block, offset, 1000 + index)
        block[offset + 0x58] = 255
        if index >= 16:
            continue
        starter_who_left = index < 5
        entered = index >= 11
        position = index - 11 if entered else index
        if overlap and position == 1:
            position = 0
        pack_into("<BB", block, offset + 0x4F, 68 if entered else 0, 24 if entered else 68 if starter_who_left else 90)
        pack_into("<I", block, offset + 0x54, position)
        pack_into("<BB", block, offset + 0x58, 16 if entered else 8 if starter_who_left else 0, 1)
    return bytes(block) + b"mglp"


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

    def add_observation(self, career=1, snapshot=2, fixture=9, players=range(1000, 1016),
                        clubs=(1929, 361), managed_side=0, played_day="2026-03-17", score=1,
                        minutes_by_player=None):
        snapshot_day = (date.fromisoformat(played_day) + timedelta(days=1)).isoformat()
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO careers (id,public_id,fingerprint_candidate,display_name,created_at,updated_at)"
                         " VALUES (? ,?,?,'Career','','')", (career, f"career-{career}", f"fp-{career}"))
            conn.execute("""INSERT INTO snapshots
                         (id,career_id,external_snapshot_id,schema_version,season_index,career_date,career_date_sort,
                          managed_team_ea_id,exported_at_utc,import_sequence,content_hash,import_status,source_path,imported_at)
                         VALUES (?, ?, ?, '1', 1, ?, ?, ?, '', ?, ?, 'imported', '', '')""",
                         (snapshot, career, f"snapshot-{snapshot}", snapshot_day, int(snapshot_day.replace("-", "")),
                          clubs[managed_side], snapshot, f"hash-{snapshot}"))
            conn.execute("INSERT OR IGNORE INTO fixtures (id,career_id,fixture_key,home_team_ea_id,away_team_ea_id)"
                         " VALUES (?,?,'fixture',?,?)", (fixture, career, *clubs))
            conn.execute("""INSERT INTO fixture_observations
                         (snapshot_id,fixture_id,fixture_key,date,is_completed,home_score,away_score,managed_team_involved,raw_json)
                         VALUES (?,?,'fixture',?,1,?,0,1,'{}')""", (snapshot, fixture, played_day, score))
            conn.executemany("""INSERT INTO player_match_performances
                             (snapshot_id,artificial_key,fixture_key,join_status,player_ea_id,minutes_played,raw_json)
                             VALUES (?,?,'fixture','joined_by_date',?,?,'{}')""",
                             [(snapshot, str(player), player, (minutes_by_player or {}).get(player, 90))
                              for player in players])

    def test_decodes_declared_layout_and_rejects_invalid_evidence(self):
        for slots in (34, 36, 40, 42):
            match = decode_save_possession(make_save(slots=slots))
            self.assertEqual((match.home_pct, match.away_pct, match.match_date), (46, 54, "2026-03-17"))
            self.assertEqual(len(match.home_players), slots // 2)
            self.assertEqual(dict(match.home_passes)["through_passes_completed"], 32)
            self.assertEqual(dict(match.home_passes)["lobbed_through_passes_completed"], 3)
            self.assertEqual(dict(match.home_passes)["line_breaking_passes"], 4)
            self.assertEqual(dict(match.home_passes)["one_two_attempted"], 6)
            self.assertEqual(dict(match.away_passes)["one_two_attempted"], 0)
            individual = {p.player_id: dict(p.stats) for p in match.player_passes}
            self.assertEqual(individual[1000], {"through_passes_completed": 2, "lobbed_through_passes_completed": 0})
            self.assertEqual(individual[1000 + slots // 2]["lobbed_through_passes_completed"], 4)
        invalid_passing = decode_save_possession(make_save(home_through=99))
        self.assertNotIn("through_passes_completed", dict(invalid_passing.home_passes))
        self.assertIsNone(decode_save_possession(make_save(slots=35)))
        self.assertIsNone(decode_save_possession(make_save(history_records=0)))
        self.assertIsNone(decode_save_possession(make_save(repeated_day=20260316)))
        self.assertIsNone(decode_save_possession(make_save()[:-4]))

    def test_count_and_latest_history_identity_must_match_the_save(self):
        valid = make_save(history_records=5)
        history_start = valid.index(b"mham")
        for offset, value in ((len(b"FBCHUNKS") + 0x192, 38), (history_start + 20, 4),
                              (history_start + 25, 9999)):
            with self.subTest(offset=offset):
                damaged = bytearray(valid)
                pack_into("<I", damaged, offset, value)
                self.assertIsNone(decode_save_possession(bytes(damaged)))

    def test_watcher_reads_distinct_careers_and_layouts_from_the_same_folder(self):
        self.add_observation()
        self.write_save(history_records=1)
        clubs = (723, 1561)
        self.add_observation(career=2, snapshot=3, fixture=10, players=range(8021, 8037),
                             clubs=clubs, managed_side=1, played_day="2027-09-09", score=3)
        self.write_save("CmMgrOutraCarreira", slots=42, clubs=clubs, player_start=8000, history_records=5,
                        played_day=20270909, repeated_day=20270909, score=3, home_pct=57)
        self.assertEqual(self.importer.scan_once(), 2)
        with self.db.connect() as conn:
            for row in conn.execute("SELECT * FROM snapshots ORDER BY id"):
                snapshot = dict(row)
                passing = snapshot_save_passes(conn, snapshot)
                fixture_id = 9 if snapshot["career_id"] == 1 else 10
                self.assertEqual(list(passing), [fixture_id])
            second = passing[10]
            self.assertEqual((second["homeTeamEaId"], second["awayTeamEaId"]), clubs)
            self.assertEqual(second["readerRevision"], "atlas-fc26-match-v1")
            self.assertEqual(fixture_save_player_passes(conn, snapshot, 10)[8021]["teamEaId"], clubs[1])

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
            self.assertEqual([team["teamIndex"] for team in evidence["teams"]], [0, 1])
            self.assertEqual([team["indicators"][0]["value"] for team in evidence["teams"]], [46, 54])
            self.assertEqual(evidence["teams"][0]["indicators"][0]["source"]["kind"], "fc26_save_mxif")
            self.assertEqual(evidence["state"], "absent")
            passing = snapshot_save_passes(conn, snapshot, 9)[9]
            self.assertEqual(passing["home"]["through_passes_completed"], 32)
            self.assertEqual(passing["home"]["through_passes_accuracy_pct"], 88.9)
            self.assertNotIn("set_piece_passes_accuracy_pct", passing["away"])
            self.assertEqual(passing["away"]["line_breaking_passes"], 0)
            self.assertEqual(evidence["teams"][0]["indicators"][1]["source"]["readerRevision"],
                             passing["readerRevision"])
            rate = next(indicator for indicator in evidence["teams"][0]["indicators"]
                        if indicator["key"] == "through_passes_accuracy_pct")
            self.assertEqual((rate["value"], rate["unit"], rate["origin"]), (88.9, "%", "derived"))
            self.assertEqual(rate["inputs"], ["through_passes_completed", "through_passes_attempted"])
            self.assertEqual(snapshot_save_passes(conn, {**snapshot, "import_sequence": 1}), {})
            player_passing = fixture_save_player_passes(conn, snapshot, 9)
            self.assertEqual(player_passing[1000]["through_passes_completed"], 2)
            self.assertEqual(player_passing[1000]["lobbed_through_passes_completed"], 0)
            self.assertEqual(player_passing[1000]["teamEaId"], 1929)
            self.assertEqual(player_passing[1000]["source"]["mxifSha256"], passing["mxifSha256"])
            self.assertEqual(fixture_save_player_passes(conn, {**snapshot, "import_sequence": 1}, 9), {})
            self.assertEqual(snapshot_save_possession(conn, {**snapshot, "import_sequence": 1}), {})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_possession").fetchone()[0], 1)
        after = status.status()
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertEqual(before["exports"], after["exports"])

    def test_ground_passes_and_one_two_success_require_consistent_counters(self):
        self.add_observation()
        data = bytearray(make_save(extra_passing=True))
        team, player = len(b"FBCHUNKS") + 0x11, len(b"FBCHUNKS") + 0x198
        pack_into("<II", data, team + 29 * 4, 4, 66)
        pack_into("<I", data, player + 0x5C, 19)
        path = self.root / "CmMgrPassingDetails"
        path.write_bytes(data)
        os.utime(path, (1, 1))
        self.assertEqual(self.importer.scan_once(), 1)
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            team_stats = snapshot_save_passes(conn, snapshot, 9)[9]["home"]
            self.assertEqual(team_stats["one_two_completed"], 4)
            self.assertEqual(team_stats["one_two_success_pct"], 66.7)
            player_stats = fixture_save_player_passes(conn, snapshot, 9)[1000]
            self.assertEqual(player_stats["ground_passes_completed"], 19)
            self.assertEqual(player_stats["through_passes_completed"], 2)
        pack_into("<I", data, team + 30 * 4, 100)
        pack_into("<I", data, player + 0x5C, 999)
        invalid = decode_save_possession(bytes(data))
        self.assertNotIn("one_two_completed", dict(invalid.home_passes))
        self.assertEqual(dict(invalid.home_passes)["one_two_attempted"], 6)
        self.assertNotIn("ground_passes_completed", dict(invalid.player_passes[0].stats))

    def test_career_feed_captures_only_known_blocks_and_respects_snapshot_boundary(self):
        self.add_observation()
        source = self.root / "CmMgrFeed"
        prefix = make_save() + b"CM_News_Outside\x00mcos\x00CM_News_Result\x00CM_Social_Match\x00momp"
        source.write_bytes(prefix + b"mvlp\x00CM_Chat_Welcome\x00CM_Chat_Welcome\x00mrdp")
        os.utime(source, (1, 1))
        self.assertEqual(self.importer.scan_once(), 1)
        self.assertEqual(self.importer.scan_once(), 0)
        with self.db.connect() as conn:
            before_snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            before = snapshot_save_career_feed(conn, before_snapshot)
            self.assertEqual(before["countsByCategory"], {"chat": 2, "news": 1, "social": 1})
            self.assertEqual(before["source"]["sourceFixtureId"], 9)
            self.assertNotIn("CM_News_Outside", [item["key"] for item in before["records"]])
        self.add_observation(snapshot=3)
        source.write_bytes(prefix + b"mvlp\x00CM_Chat_Training\x00mrdp")
        os.utime(source, (2, 2))
        self.assertEqual(self.importer.scan_once(), 1)
        with self.db.connect() as conn:
            after_snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=3").fetchone())
            after = snapshot_save_career_feed(conn, after_snapshot)
            self.assertEqual(after["source"]["observedSnapshotId"], 3)
            self.assertIn("CM_Chat_Training", [item["key"] for item in after["records"]])
            self.assertEqual(snapshot_save_career_feed(conn, before_snapshot), before)
            self.assertIsNone(snapshot_save_career_feed(conn, {**after_snapshot, "career_id": 2}))
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

    def test_player_metric_is_omitted_when_its_sum_differs_from_the_team(self):
        data = bytearray(make_save())
        pack_into("<I", data, len(b"FBCHUNKS") + 0x198 + 0x4C, 1)
        match = decode_save_possession(bytes(data))
        self.assertEqual(dict(match.home_passes)["through_passes_completed"], 32)
        player = next(p for p in match.player_passes if p.player_id == 1000)
        self.assertEqual(dict(player.stats), {"lobbed_through_passes_completed": 0})

    def test_publishes_extra_completion_only_when_reconciled(self):
        data = bytearray(make_save(extra_passing=True))
        match = decode_save_possession(bytes(data))
        self.assertEqual(dict(match.home_passes)["through_passes_attempted"], 36)
        self.assertEqual(dict(match.home_passes)["lobbed_passes_attempted"], 3)
        self.assertEqual(dict(match.home_passes)["lobbed_passes_completed"], 2)
        player = next(p for p in match.player_passes if p.player_id == 1000)
        self.assertEqual(dict(player.stats)["set_piece_passes_completed"], 1)
        self.assertNotIn("lobbed_passes_completed", dict(match.away_passes))

        pack_into("<I", data, len(b"FBCHUNKS") + 0x198 + 0x58, 1)
        match = decode_save_possession(bytes(data))
        self.assertNotIn("lobbed_passes_completed", dict(match.home_passes))
        player = next(p for p in match.player_passes if p.player_id == 1000)
        self.assertNotIn("lobbed_passes_completed", dict(player.stats))
        self.assertEqual(dict(player.stats)["set_piece_passes_completed"], 1)

    def test_extends_preexisting_passing_records_idempotently(self):
        self.add_observation()
        self.write_save(extra_passing=True)
        self.assertEqual(self.importer.scan_once(), 1)
        with self.db.transaction() as conn:
            conn.execute("UPDATE fc26_save_passes SET stats_json=?",
                         ('{"home":{"through_passes_completed":32},"away":{}}',))
            conn.execute("UPDATE fc26_save_player_passes SET stats_json=?",
                         ('{"1000":{"teamEaId":1929,"through_passes_completed":2}}',))
        status = MatchStatsImporter(self.db)
        before = status.status()["revision"]
        self.assertEqual(SavePossessionImporter(self.db, self.root).scan_once(), 1)
        self.assertNotEqual(status.status()["revision"], before)
        self.assertEqual(SavePossessionImporter(self.db, self.root).scan_once(), 0)
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            self.assertEqual(snapshot_save_passes(conn, snapshot, 9)[9]["home"]["lobbed_passes_completed"], 2)
            passing = fixture_save_player_passes(conn, snapshot, 9)[1000]
            self.assertEqual(passing["through_passes_completed"], 2)
            self.assertEqual(passing["set_piece_passes_completed"], 1)

    def test_shared_passing_is_opt_in_and_never_replaces_live_editor(self):
        self.add_observation()
        payload = bytearray(make_save(extra_passing=True))
        team, player = len(b"FBCHUNKS") + 0x11, len(b"FBCHUNKS") + 0x198
        for slot, value in ((4, 114), (10, 3), (11, 2), (25, 1)):
            pack_into("<I", payload, team + slot * 4, value)
        for offset, value in ((0x40, 3), (0x44, 2), (0x54, 1)):
            pack_into("<I", payload, player + offset, value)
        path = self.root / "CmMgrComparison"
        path.write_bytes(payload)
        os.utime(path, (1, 1))
        self.assertNotIn("crosses_attempted", read_saved_match(bytes(payload)).home.fields)
        detailed = {"exportId": 41, "teams": [{"teamIndex": 1, "teamEaId": 1929, "stats": {"passes": 113}},
                                             {"teamIndex": 0, "teamEaId": 361, "stats": {}}],
                    "players": [{"playerEaId": 1000, "teamIndex": 1, "stats": {"crosses_delivered": 0}},
                                {"playerEaId": 1001, "teamIndex": 0, "stats": {}}]}
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
        with patch.dict(os.environ):
            os.environ.pop("ATLAS_SAVE_PASSING_COMPARISON", None)
            os.environ.pop("ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON", None)
            self.assertEqual(self.importer.scan_once(), 1)
            with self.db.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_passing_comparison").fetchone()[0], 0)
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, detailed), {})

            os.environ["ATLAS_SAVE_PASSING_COMPARISON"] = "1"
            status = MatchStatsImporter(self.db)
            revision_before_audit = status.status()["revision"]
            self.assertEqual(self.importer.scan_once(), 1)
            self.assertNotEqual(status.status()["revision"], revision_before_audit)
            self.assertEqual(self.importer.scan_once(), 0)
            with self.db.connect() as conn:
                audit = fixture_save_stat_sources(conn, snapshot, 9, detailed)["savePassingComparison"]
                self.assertEqual(audit["liveEditorExportId"], 41)
                self.assertEqual(audit["home"]["passes"], {"careerFile": 114, "liveEditor": 113})
                self.assertEqual(audit["home"]["cross_success_pct_derived"]["careerFile"], 66.7)
                self.assertEqual(list(audit["players"]), ["1000"])
                self.assertEqual(audit["players"]["1000"]["stats"]["crosses_delivered"],
                                 {"careerFile": 2, "liveEditor": 0})
                self.assertNotIn("passes", snapshot_save_passes(conn, snapshot, 9)[9]["home"])
                self.assertEqual(fixture_save_stat_sources(conn, {**snapshot, "import_sequence": 1}, 9, detailed), {})

            os.environ["ATLAS_SAVE_PASSING_COMPARISON"] = "0"
            self.assertEqual(self.importer.scan_once(), 0)
            with self.db.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_passing_comparison").fetchone()[0], 1)
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, detailed), {})

    def test_shooting_and_defending_audit_extends_legacy_passing_row_only_when_enabled(self):
        self.add_observation()
        payload = bytearray(make_save())
        team, player = len(b"FBCHUNKS") + 0x11, len(b"FBCHUNKS") + 0x198
        for slot, value in ((2, 5), (40, 2), (43, 1), (44, 4), (45, 6), (47, 3)):
            pack_into("<I", payload, team + slot * 4, value)
        for offset, value in ((0x64, 5), (0x68, 2), (0x70, 2), (0x78, 0), (0x7C, 4), (0x80, 1), (0x84, 2)):
            pack_into("<I", payload, player + offset, value)
        path = self.root / "CmMgrShootingDefending"
        path.write_bytes(payload)
        os.utime(path, (1, 1))
        self.assertNotIn("shots", read_saved_match(bytes(payload)).home.fields)
        detailed = {"exportId": 41, "teams": [{"teamIndex": 1, "teamEaId": 1929, "stats": {"shots": 4, "saves": 3}},
                                             {"teamIndex": 0, "teamEaId": 361, "stats": {}}],
                    "players": [{"playerEaId": 1000, "teamIndex": 1, "stats": {"blocks": 0, "shots_blocked": 2}},
                                {"playerEaId": 1001, "teamIndex": 0, "stats": {}}]}
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
        with patch.dict(os.environ, {"ATLAS_SAVE_PASSING_COMPARISON": "1", "ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON": "0"}):
            self.assertEqual(self.importer.scan_once(), 1)
            with self.db.connect() as conn:
                original_passing = fixture_save_stat_sources(conn, snapshot, 9, detailed)
                self.assertEqual(list(original_passing), ["savePassingComparison"])

            os.environ["ATLAS_SAVE_PASSING_COMPARISON"] = "0"
            os.environ["ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON"] = "1"
            status = MatchStatsImporter(self.db)
            before = status.status()["revision"]
            self.assertEqual(self.importer.scan_once(), 1)
            self.assertNotEqual(status.status()["revision"], before)
            self.assertEqual(self.importer.scan_once(), 0)
            with self.db.connect() as conn:
                comparisons = fixture_save_stat_sources(conn, snapshot, 9, detailed)
                self.assertEqual(list(comparisons), ["saveShootingDefendingComparison"])
                audit = comparisons["saveShootingDefendingComparison"]
                self.assertEqual(audit["home"]["shots"], {"careerFile": 5, "liveEditor": 4})
                self.assertEqual(audit["home"]["saves"], {"careerFile": 3, "liveEditor": 3})
                self.assertEqual(list(audit["players"]), ["1000"])
                player_audit = audit["players"]["1000"]["stats"]
                self.assertEqual(player_audit["shots_blocked"], {"careerFile": 1, "liveEditor": 2})
                self.assertEqual(player_audit["blocks"], {"careerFile": 0, "liveEditor": 0})
                self.assertNotIn("aerial_duels_won", player_audit)
                self.assertNotIn("shots", snapshot_save_passes(conn, snapshot, 9)[9]["home"])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_passing_comparison").fetchone()[0], 1)

            os.environ["ATLAS_SAVE_PASSING_COMPARISON"] = "1"
            with self.db.connect() as conn:
                comparisons = fixture_save_stat_sources(conn, snapshot, 9, detailed)
                self.assertEqual(comparisons["savePassingComparison"], original_passing["savePassingComparison"])
                self.assertIn("saveShootingDefendingComparison", comparisons)
            os.environ["ATLAS_SAVE_PASSING_COMPARISON"] = "0"
            os.environ["ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON"] = "0"
            with self.db.connect() as conn:
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, detailed), {})

    def test_save_participation_checks_all_players_and_minutes_and_omits_ambiguous_pairs(self):
        for count in (30, 33, 36, 49):
            with self.subTest(count=count):
                saved = decode_save_possession(make_save() + make_participation_block(count))
                self.assertEqual(len(saved.participation.players), 16)
        minutes = {**dict.fromkeys(range(1000, 1005), 68), **dict.fromkeys(range(1011, 1016), 24)}
        self.add_observation(minutes_by_player=minutes)
        path = self.root / "CmMgrParticipation"
        valid_block = make_participation_block(36, overlap=True)
        stale_block = bytearray(valid_block)
        stale_block[26 + 0x50] = 67
        path.write_bytes(make_save() + stale_block)
        os.utime(path, (1, 1))
        status = MatchStatsImporter(self.db)
        self.assertEqual(self.importer.scan_once(), 1)
        with self.db.connect() as conn:
            snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
            self.assertIsNone(fixture_save_participation(conn, snapshot, 9))
        before = status.status()["revision"]
        path.write_bytes(make_save() + valid_block)
        os.utime(path, (2, 2))
        self.assertEqual(self.importer.scan_once(), 1)
        self.assertNotEqual(status.status()["revision"], before)
        with self.db.connect() as conn:
            linked = fixture_save_participation(conn, snapshot, 9)
            self.assertEqual(linked["teamEaId"], 1929)
            self.assertEqual(linked["source"]["kind"], "fc26_save_mflp")
            players = linked["players"]
            self.assertEqual(players["1000"]["role"], "starter_substituted")
            self.assertEqual(players["1005"]["role"], "starter_finished")
            self.assertEqual(players["1013"]["role"], "substitute_entered")
            self.assertEqual(players["1013"]["entryMinuteInternal"], 68)
            self.assertEqual(players["1013"]["replacedPlayerEaId"], 1002)
            self.assertNotIn("replacedPlayerEaId", players["1011"])
            self.assertNotIn("1016", players)
            self.assertIsNone(fixture_save_participation(conn, {**snapshot, "import_sequence": 1}, 9))

    def test_fallback_requires_save_reconciliation_and_absence_of_matchstats(self):
        self.add_observation()
        data = bytearray(make_save())
        team, player = len(b"FBCHUNKS") + 0x11, len(b"FBCHUNKS") + 0x198
        for slot, value in ((2, 5), (40, 2), (43, 8), (44, 4), (45, 1), (47, 3)):
            pack_into("<I", data, team + slot * 4, value)
        for offset, value in ((0x64, 5), (0x68, 2), (0x70, 2), (0x7C, 4), (0x80, 1), (0x84, 1)):
            pack_into("<I", data, player + offset, value)
        path = self.root / "CmMgrFixtureFallback"
        path.write_bytes(data)
        os.utime(path, (1, 1))
        flags = {"ATLAS_SAVE_PASSING_COMPARISON": "0", "ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON": "0",
                 "ATLAS_SAVE_SHOOTING_DEFENDING_FALLBACK": "0"}
        with patch.dict(os.environ, flags):
            self.assertEqual(self.importer.scan_once(), 1)
            with self.db.connect() as conn:
                snapshot = dict(conn.execute("SELECT * FROM snapshots WHERE id=2").fetchone())
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, None), {})
            os.environ["ATLAS_SAVE_SHOOTING_DEFENDING_FALLBACK"] = "1"
            self.assertEqual(self.importer.scan_once(), 1)
            self.assertEqual(self.importer.scan_once(), 0)
            with self.db.connect() as conn:
                sources = fixture_save_stat_sources(conn, snapshot, 9, None)
                self.assertEqual(list(sources), ["saveShootingDefendingFallback"])
                fallback = sources["saveShootingDefendingFallback"]
                expected = {"shots": 5, "shots_on_target": 2, "clearances": 4, "aerial_duels_won": 1}
                self.assertEqual(fallback["home"], expected)
                self.assertEqual(fallback["away"]["blocks"], 0)
                self.assertEqual(fallback["players"]["1000"], {"teamEaId": 1929, "stats": expected})
                self.assertEqual(fallback["source"]["kind"], "fc26_save_mxif")
                self.assertNotIn("saves", fallback["home"])
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, {"available": True}), {})
                self.assertEqual(fixture_save_stat_sources(conn, {**snapshot, "import_sequence": 1}, 9, None), {})
            os.environ["ATLAS_SAVE_SHOOTING_DEFENDING_FALLBACK"] = "0"
            with self.db.connect() as conn:
                self.assertEqual(fixture_save_stat_sources(conn, snapshot, 9, None), {})

    def test_passing_is_backfilled_only_from_the_original_possession_block(self):
        self.add_observation()
        original = decode_save_possession(make_save())
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO fc26_save_possession VALUES (9,2,?,46,54)", (original.mxif_sha256,))
        status = MatchStatsImporter(self.db)
        before = status.status()["revision"]

        self.write_save(home_through=30)
        self.assertEqual(self.importer.scan_once(), 0)
        self.write_save("CmMgrC2")
        self.assertEqual(self.importer.scan_once(), 0)
        (self.root / "CmMgrC1").unlink()
        self.assertEqual(self.importer.scan_once(), 1)
        self.assertNotEqual(status.status()["revision"], before)
        self.assertEqual(self.importer.scan_once(), 0)
        with self.db.connect() as conn:
            saved = conn.execute("SELECT snapshot_id,mxif_sha256,home_pct,away_pct FROM fc26_save_possession").fetchone()
            self.assertEqual(tuple(saved), (2, original.mxif_sha256, 46, 54))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_passes").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fc26_save_player_passes").fetchone()[0], 1)

    def test_backfills_individual_passing_after_collective_import(self):
        self.add_observation()
        self.write_save()
        self.assertEqual(self.importer.scan_once(), 1)
        with self.db.transaction() as conn:
            collective = tuple(conn.execute("SELECT * FROM fc26_save_passes").fetchone())
            conn.execute("DELETE FROM fc26_save_player_passes")
        status = MatchStatsImporter(self.db)
        before = status.status()["revision"]
        self.assertEqual(SavePossessionImporter(self.db, self.root).scan_once(), 1)
        self.assertNotEqual(status.status()["revision"], before)
        with self.db.connect() as conn:
            self.assertEqual(tuple(conn.execute("SELECT * FROM fc26_save_passes").fetchone()), collective)
