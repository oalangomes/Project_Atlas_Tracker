"""Read custom team sheets and tactical presets from the FC 26 career database."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .positions import POSITION_BY_ID


_DB_SIGNATURE = b"DB\0\x08\0\0\0\0"

# Player and position fields refer to the same eleven saved slots. The FC 26
# values were reconciled with teamplayerlinks in the matching Atlas snapshot.
_PLAYER_SLOTS = ("MVLC", "zWHI", "SfCW", "Ncmk", "Povf", "wjrR", "RaOP", "OhyJ", "WCfU", "FJbC", "qhEx")
_POSITION_SLOTS = ("ZzVx", "CEZz", "nNch", "cGsr", "aCho", "BBlW", "ksMI", "fvcy", "TMpL", "sPtx", "FuLD")


@dataclass(frozen=True)
class SavedCareerSetup:
    team_id: int
    payload: str
    sha256: str


def _uint(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset:offset + size], "little")


def _table(data: bytes, start: int, end: int, fields: dict[str, int]) -> list[dict[str, Any]]:
    """Read only the requested integer and string fields from a bounded table."""
    if start + 36 > end:
        return []
    stride = _uint(data, start + 4, 4)
    count = _uint(data, start + 18, 2)
    field_count = data[start + 24]
    records_start = start + 36 + field_count * 16
    if not stride or count > 1024 or records_start + count * stride > end:
        return []
    layout = {}
    for offset in range(start + 36, records_start, 16):
        kind = _uint(data, offset, 4)
        bit = _uint(data, offset + 4, 4)
        name = data[offset + 8:offset + 12].decode("latin-1")
        width = _uint(data, offset + 12, 4)
        if name not in fields:
            continue
        if (name in layout or kind != fields[name] or not width or bit + width > stride * 8
                or (kind == 3 and width > 32) or (kind == 0 and (bit % 8 or width % 8 or width > 640))):
            return []
        layout[name] = (kind, bit, width)
    if layout.keys() != fields.keys():
        return []

    rows = []
    for start in range(records_start, records_start + count * stride, stride):
        row = {}
        for name, (kind, bit, width) in layout.items():
            offset = start + bit // 8
            if kind == 3:
                shift = bit % 8
                row[name] = (_uint(data, offset, (shift + width + 7) // 8) >> shift) & ((1 << width) - 1)
            else:
                value = data[offset:offset + width // 8].split(b"\0", 1)[0]
                try:
                    row[name] = value.decode("utf-8").strip()
                except UnicodeDecodeError:
                    row[name] = value.decode("cp1252", errors="replace").strip()
        rows.append(row)
    return rows


def _career_tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    offset = data.find(_DB_SIGNATURE)
    while 0 <= offset <= len(data) - 28:
        end = offset + _uint(data, offset + 8, 4)
        count = _uint(data, offset + 16, 4)
        start = offset + 28 + count * 8
        if 0 < count <= 128 and start < end <= len(data):
            entries = [(data[i:i + 4], start + _uint(data, i + 4, 4))
                       for i in range(offset + 24, start - 4, 8)]
            if b"mPrV" in {name for name, _ in entries}:
                ordered = sorted(entries, key=lambda entry: entry[1])
                names = {name for name, _ in ordered}
                bounds = [position for _, position in ordered] + [end]
                if (len(names) == count and len(set(bounds)) == count + 1
                        and all(start <= position < end for position in bounds[:-1])):
                    return {name: (position, bounds[i + 1]) for i, (name, position) in enumerate(ordered)}
        offset = data.find(_DB_SIGNATURE, offset + len(_DB_SIGNATURE))
    return {}


def read_saved_career_setup(data: bytes, fixture_teams: tuple[int, int]) -> SavedCareerSetup | None:
    tables = _career_tables(data)

    def rows(table: bytes, **fields: int) -> list[dict[str, Any]]:
        return _table(data, *tables[table], fields) if table in tables else []

    users = rows(b"mPrV", NTyS=3)
    if len(users) != 1 or users[0]["NTyS"] - 1 not in fixture_teams:
        return None
    raw_team = users[0]["NTyS"]

    sheets = rows(b"zdMM", jfDM=3, mCXg=3, TrVp=0)
    presets = rows(b"emmj", jfDM=3, mCXg=3, AwZu=3, KAOA=0,
                   **dict.fromkeys((*_PLAYER_SLOTS, *_POSITION_SLOTS), 3))
    club_sheets = [row for row in sheets if row["mCXg"] == raw_team and row["TrVp"]]
    club_presets = [row for row in presets if row["mCXg"] == raw_team and row["KAOA"]]
    sheet_counts = Counter(row["jfDM"] for row in club_sheets)
    preset_counts = Counter((row["jfDM"], row["AwZu"]) for row in club_presets)
    tactics = []
    for sheet in sorted(club_sheets, key=lambda row: row["jfDM"]):
        sheet_id = sheet["jfDM"]
        if sheet_counts[sheet_id] != 1:
            continue
        saved_presets = []
        for preset in sorted(club_presets, key=lambda row: row["AwZu"]):
            if preset["jfDM"] != sheet_id or preset_counts[sheet_id, preset["AwZu"]] != 1:
                continue
            raw_players = [preset[key] for key in _PLAYER_SLOTS]
            saved_xi = []
            if len(set(raw_players)) == 11 and all(1 < player < 0x7FFFF for player in raw_players):
                saved_xi = [{"playerId": player - 1, "position": POSITION_BY_ID.get(preset[key] - 1)}
                            for player, key in zip(raw_players, _POSITION_SLOTS)]
            saved_presets.append({"name": preset["KAOA"], "players": saved_xi})
        tactics.append({"name": sheet["TrVp"], "presets": saved_presets})

    if not tactics:
        return None
    payload = json.dumps({"tactics": tactics}, ensure_ascii=True, separators=(",", ":"))
    return SavedCareerSetup(raw_team - 1, payload, hashlib.sha256(payload.encode("ascii")).hexdigest())


def persist_save_career_setup(conn: sqlite3.Connection, snapshot_id: int, fixture_id: int,
                              source_mtime_ns: int, setup: SavedCareerSetup) -> int:
    return conn.execute(
        """INSERT INTO fc26_save_career_setup
           (snapshot_id,source_fixture_id,source_mtime_ns,payload_sha256,payload_json)
           SELECT s.id,f.id,?,?,? FROM snapshots s JOIN fixtures f ON f.career_id=s.career_id
           WHERE s.id=? AND f.id=? AND s.managed_team_ea_id=?
           ON CONFLICT(snapshot_id) DO UPDATE SET source_fixture_id=excluded.source_fixture_id,
               source_mtime_ns=excluded.source_mtime_ns,payload_sha256=excluded.payload_sha256,payload_json=excluded.payload_json
           WHERE excluded.source_mtime_ns>fc26_save_career_setup.source_mtime_ns""",
        (source_mtime_ns, setup.sha256, setup.payload, snapshot_id, fixture_id, setup.team_id),
    ).rowcount


def snapshot_save_career_setup(conn: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT setup.*,s.career_date FROM fc26_save_career_setup setup
           JOIN snapshots s ON s.id=setup.snapshot_id WHERE setup.snapshot_id=?""", (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    # Early versions stored TcEm counters alongside tactics. Expose only
    # tactics even when the selected snapshot was imported by that version.
    tactics = json.loads(row["payload_json"]).get("tactics", [])
    return {"tactics": tactics,
            "source": {"kind": "fc26_save_career_setup", "snapshotId": snapshot_id,
                       "observedCareerDate": row["career_date"], "sourceFixtureId": row["source_fixture_id"],
                       "sha256": row["payload_sha256"]}}
