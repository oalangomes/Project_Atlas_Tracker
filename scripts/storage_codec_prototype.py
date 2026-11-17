"""Isolated, read-only-source benchmark for lossless dynamic-state JSON compression.

The source is opened with SQLite mode=ro. Only selected snapshots are copied into
temporary databases; no production schema or file is changed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import tempfile
import time
import zlib
from pathlib import Path


COLUMNS = (
    "id", "career_id", "snapshot_id", "player_ea_id", "base_overall", "potential",
    "dynamic_overall", "dynamic_delta", "form_score", "morale_score", "fitness_score",
    "performance_source", "confidence", "stats_json", "breakdown_json",
    "model_version", "created_at", "updated_at",
)
SELECT_COLUMNS = ",".join(COLUMNS)
INSERT_SQL = "INSERT INTO states VALUES(" + ",".join("?" for _ in COLUMNS) + ")"
SCHEMA = """
CREATE TABLE states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL,
    player_ea_id INTEGER NOT NULL,
    base_overall INTEGER NOT NULL,
    potential INTEGER NOT NULL,
    dynamic_overall REAL NOT NULL,
    dynamic_delta REAL NOT NULL,
    form_score REAL NOT NULL,
    morale_score REAL NOT NULL,
    fitness_score REAL NOT NULL,
    performance_source TEXT NOT NULL,
    confidence REAL NOT NULL,
    stats_json {json_type} NOT NULL,
    breakdown_json {json_type} NOT NULL,
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(snapshot_id, player_ea_id)
);
CREATE INDEX idx_snapshot ON states(snapshot_id, dynamic_delta DESC, dynamic_overall DESC);
CREATE INDEX idx_player ON states(career_id, player_ea_id, snapshot_id);
"""


def encode_row(row: tuple, compressed: bool) -> tuple:
    if not compressed:
        return row
    values = list(row)
    for index in (13, 14):
        values[index] = zlib.compress(values[index].encode("utf-8"), level=6)
    return tuple(values)


def decode_row(row: tuple, compressed: bool) -> tuple:
    if not compressed:
        return row
    values = list(row)
    for index in (13, 14):
        values[index] = zlib.decompress(values[index]).decode("utf-8")
    return tuple(values)


def create_variant(path: Path, compressed: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA page_size=4096")
    connection.executescript(SCHEMA.format(json_type="BLOB" if compressed else "TEXT"))
    return connection


def copy_selected(
    source: sqlite3.Connection, destination: sqlite3.Connection,
    snapshot_ids: tuple[int, ...], limit_per_snapshot: int | None, compressed: bool,
) -> tuple[int, float]:
    started = time.perf_counter()
    count = 0
    for snapshot_id in snapshot_ids:
        sql = f"SELECT {SELECT_COLUMNS} FROM player_dynamic_states WHERE snapshot_id=? ORDER BY player_ea_id"
        if limit_per_snapshot is not None:
            sql += " LIMIT ?"
            parameters = (snapshot_id, limit_per_snapshot)
        else:
            parameters = (snapshot_id,)
        cursor = source.execute(sql, parameters)
        while batch := cursor.fetchmany(500):
            destination.executemany(INSERT_SQL, (encode_row(row, compressed) for row in batch))
            count += len(batch)
    destination.commit()
    return count, time.perf_counter() - started


def verify_lossless(plain: sqlite3.Connection, packed: sqlite3.Connection) -> int:
    query = f"SELECT {SELECT_COLUMNS} FROM states ORDER BY snapshot_id,player_ea_id"
    left = plain.execute(query)
    right = packed.execute(query)
    verified = 0
    while left_batch := left.fetchmany(500):
        right_batch = right.fetchmany(500)
        if len(left_batch) != len(right_batch):
            raise AssertionError("Different row counts")
        for baseline_row, packed_row in zip(left_batch, right_batch):
            if baseline_row != decode_row(packed_row, True):
                raise AssertionError(f"Mismatch at snapshot/player {baseline_row[2:4]}")
            verified += 1
    if right.fetchone() is not None:
        raise AssertionError("Packed database contains extra rows")
    return verified


def timed(operation, repeats: int = 5) -> float:
    operation()  # warm-up, excluded from timing
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples) * 1000


def benchmark(connection: sqlite3.Connection, snapshot_id: int, compressed: bool) -> dict:
    keys = [row[0] for row in connection.execute(
        "SELECT player_ea_id FROM states WHERE snapshot_id=? ORDER BY player_ea_id LIMIT 300",
        (snapshot_id,),
    )]
    model = connection.execute(
        "SELECT model_version FROM states WHERE snapshot_id=? LIMIT 1", (snapshot_id,),
    ).fetchone()[0]

    def point_reads() -> None:
        for key in keys:
            row = connection.execute(
                f"SELECT {SELECT_COLUMNS} FROM states WHERE snapshot_id=? AND player_ea_id=?",
                (snapshot_id, key),
            ).fetchone()
            decoded = decode_row(row, compressed)
            json.loads(decoded[13])
            json.loads(decoded[14])

    def previous_snapshot_scan() -> None:
        for _, _, payload in connection.execute(
            "SELECT player_ea_id,dynamic_delta,breakdown_json FROM states "
            "WHERE snapshot_id=? AND model_version=?", (snapshot_id, model),
        ):
            json.loads(zlib.decompress(payload).decode("utf-8") if compressed else payload)

    def board_reads() -> None:
        for stats, breakdown in connection.execute(
            "SELECT stats_json,breakdown_json FROM states WHERE snapshot_id=? "
            "ORDER BY dynamic_delta DESC,dynamic_overall DESC LIMIT 300", (snapshot_id,),
        ):
            if compressed:
                stats = zlib.decompress(stats).decode("utf-8")
                breakdown = zlib.decompress(breakdown).decode("utf-8")
            json.loads(stats)
            json.loads(breakdown)

    return {
        "point_300_ms": round(timed(point_reads), 3),
        "previous_snapshot_scan_ms": round(timed(previous_snapshot_scan), 3),
        "board_300_ms": round(timed(board_reads), 3),
    }


def run_prototype(source_path: Path, snapshot_ids: tuple[int, ...], limit_per_snapshot: int | None = None) -> dict:
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    source.execute("PRAGMA query_only=ON")
    source.execute("BEGIN")
    try:
        with tempfile.TemporaryDirectory(prefix="atlas_storage_codec_") as temporary:
            directory = Path(temporary)
            plain_path, packed_path = directory / "plain.sqlite3", directory / "packed.sqlite3"
            plain = create_variant(plain_path, False)
            packed = create_variant(packed_path, True)
            try:
                plain_count, plain_write = copy_selected(source, plain, snapshot_ids, limit_per_snapshot, False)
                packed_count, packed_write = copy_selected(source, packed, snapshot_ids, limit_per_snapshot, True)
                if plain_count != packed_count or not plain_count:
                    raise AssertionError("Selected snapshots yielded no rows or unequal row counts")
                verified = verify_lossless(plain, packed)
                if verified != plain_count:
                    raise AssertionError("Not all rows were verified")
                if plain.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise AssertionError("Baseline quick_check failed")
                if packed.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise AssertionError("Packed quick_check failed")
                latest = snapshot_ids[-1]
                result = {
                    "snapshots": snapshot_ids,
                    "limit_per_snapshot": limit_per_snapshot,
                    "rows_verified": verified,
                    "plain_bytes": plain_path.stat().st_size,
                    "packed_bytes": packed_path.stat().st_size,
                    "plain_write_seconds": round(plain_write, 3),
                    "packed_write_seconds": round(packed_write, 3),
                    "plain_reads": benchmark(plain, latest, False),
                    "packed_reads": benchmark(packed, latest, True),
                }
                result["size_reduction_percent"] = round(
                    100 * (1 - result["packed_bytes"] / result["plain_bytes"]), 2,
                )
                return result
            finally:
                plain.close()
                packed.close()
    finally:
        source.rollback()
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--snapshots", type=int, nargs="+", required=True)
    parser.add_argument("--limit-per-snapshot", type=int)
    args = parser.parse_args()
    if args.limit_per_snapshot is not None and args.limit_per_snapshot <= 0:
        parser.error("--limit-per-snapshot must be positive")
    print(json.dumps(run_prototype(args.database, tuple(args.snapshots), args.limit_per_snapshot), indent=2))


if __name__ == "__main__":
    main()
