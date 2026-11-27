"""Import persisted career feed key counts without inferring dated events."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping


_FEED_BLOCKS = ((b"mcos", b"momp", {b"Social", b"News"}),
                (b"mvlp", b"mrdp", {b"Chat"}))
_CONTENT_KEY = re.compile(rb"CM_(Chat|Social|News)_[A-Za-z0-9_]{1,192}(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class SavedCareerFeed:
    sha256: str
    records_json: str


def read_saved_career_feed(data: bytes) -> SavedCareerFeed | None:
    # The Hub mapping identifies the content keys and their blocks. Nearby
    # bytes do not establish the date, speaker, recipient, or full message.
    counts: Counter[tuple[str, str]] = Counter()
    for marker, sibling, kinds in _FEED_BLOCKS:
        start = data.find(marker)
        end = data.find(sibling, start + len(marker)) if start >= 0 else -1
        if end < 0:
            continue
        for match in _CONTENT_KEY.finditer(data, start + len(marker), end):
            kind = match.group(1)
            if kind in kinds:
                counts[(kind.decode("ascii").lower(), match.group().decode("ascii"))] += 1
    if not counts:
        return None
    records = [{"category": kind, "key": key, "count": count}
               for (kind, key), count in sorted(counts.items())]
    payload = json.dumps(records, separators=(",", ":"))
    return SavedCareerFeed(hashlib.sha256(payload.encode("ascii")).hexdigest(), payload)


def persist_save_career_feed(conn: sqlite3.Connection, career_id: int, fixture_id: int,
                             last_match_day: str, source_mtime_ns: int, feed: SavedCareerFeed) -> int:
    # The last match links the file to a career. Its date is not the date of
    # the feed. Record visibility at the newest career snapshot at observation.
    snapshot = conn.execute(
        "SELECT id FROM snapshots WHERE career_id=? ORDER BY import_sequence DESC,id DESC LIMIT 1",
        (career_id,),
    ).fetchone()
    last = conn.execute(
        """SELECT f.last_match_day,f.source_mtime_ns
           FROM fc26_save_career_feed f JOIN snapshots s ON s.id=f.snapshot_id
           WHERE s.career_id=? ORDER BY s.import_sequence DESC,s.id DESC LIMIT 1""",
        (career_id,),
    ).fetchone()
    if snapshot is None or (last and (last_match_day, source_mtime_ns) <=
                            (last["last_match_day"], last["source_mtime_ns"])):
        return 0
    return conn.execute(
        """INSERT INTO fc26_save_career_feed
           (snapshot_id,source_fixture_id,last_match_day,source_mtime_ns,feed_sha256,records_json)
           VALUES (?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO UPDATE SET
               source_fixture_id=excluded.source_fixture_id,last_match_day=excluded.last_match_day,
               source_mtime_ns=excluded.source_mtime_ns,feed_sha256=excluded.feed_sha256,
               records_json=excluded.records_json""",
        (snapshot["id"], fixture_id, last_match_day, source_mtime_ns, feed.sha256, feed.records_json),
    ).rowcount


def snapshot_save_career_feed(conn: sqlite3.Connection, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT f.*,s.career_date FROM fc26_save_career_feed f JOIN snapshots s ON s.id=f.snapshot_id
           WHERE s.career_id=? AND (s.import_sequence<? OR (s.import_sequence=? AND s.id<=?))
           ORDER BY s.import_sequence DESC,s.id DESC LIMIT 1""",
        (snapshot["career_id"], snapshot["import_sequence"], snapshot["import_sequence"], snapshot["id"]),
    ).fetchone()
    if row is None:
        return None
    records = json.loads(row["records_json"])
    counts: Counter[str] = Counter()
    for item in records:
        counts[item["category"]] += item["count"]
    return {"source": {"kind": "fc26_save_career_feed", "observedSnapshotId": row["snapshot_id"],
                       "observedCareerDate": row["career_date"], "sourceFixtureId": row["source_fixture_id"],
                       "feedSha256": row["feed_sha256"]},
            "countsByCategory": dict(counts), "records": records}
