import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.storage_codec_prototype import (
    INSERT_SQL, SCHEMA, decode_row, encode_row, run_prototype,
)


class StorageCodecPrototypeTests(unittest.TestCase):
    def test_codec_preserves_exact_text_and_columns(self):
        row = (
            1, 1, 7, 42, 67, 80, 67.25, 0.25, 48.0, 52.0, 100.0,
            "simulated", 0.7, '{"name": "João", "value": null}',
            '{"availability": {"state": "fit"}, "note": "⚽"}',
            "atlas-dynamic-performance-v12", "2026-01-01", "2026-01-01",
        )
        self.assertEqual(decode_row(encode_row(row, True), True), row)

    def test_historical_rows_survive_isolated_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            with closing(sqlite3.connect(source_path)) as connection:
                connection.executescript(
                    SCHEMA.replace("CREATE TABLE states", "CREATE TABLE player_dynamic_states")
                    .replace("ON states", "ON player_dynamic_states")
                    .format(json_type="TEXT")
                )
                rows = []
                row_id = 0
                for snapshot_id in (1, 2, 3):
                    for player_id in range(1, 401):
                        row_id += 1
                        rows.append((
                            row_id, 1, snapshot_id, player_id, 67, 80,
                            67.0 + snapshot_id / 10, snapshot_id / 10,
                            48.0, 52.0, 100.0, "simulated", 0.7,
                            '{"name":"João","score":7}',
                            '{"availability":{"state":"fit"},"history":['
                            + ','.join('"observed"' for _ in range(90)) + ']'
                            + f',"snapshot":{snapshot_id}}}',
                            "atlas-dynamic-performance-v12", "2026-01-01", "2026-01-01",
                        ))
                connection.executemany(INSERT_SQL.replace("states", "player_dynamic_states"), rows)
                connection.commit()
            result = run_prototype(source_path, (1, 2, 3))
            self.assertEqual(result["rows_verified"], 1200)
            self.assertEqual(result["snapshots"], (1, 2, 3))
            self.assertLess(result["packed_bytes"], result["plain_bytes"])
            self.assertIn("previous_snapshot_scan_ms", result["packed_reads"])


if __name__ == "__main__":
    unittest.main()
