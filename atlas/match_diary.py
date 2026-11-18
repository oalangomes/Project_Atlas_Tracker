"""Versioned coach observations attached to an Atlas career fixture."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .db import Database
from .positions import broad_position_group, canonical_position


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"Coach observation exceeds {limit} characters.")
    return text or None


def _formation(value: Any) -> str | None:
    text = _text(value, 12)
    if text and (not re.fullmatch(r"[1-5](?:-[1-5]){2,4}", text)
                 or sum(int(part) for part in text.split("-")) != 10):
        raise ValueError("Formation must describe ten outfield players, for example 4-4-2.")
    return text


def _lineup(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError("Lineup must be a list of at most 30 players.")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each lineup entry must be an object.")
        try:
            player_id = int(raw.get("playerEaId"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Lineup player EA ID is required.") from exc
        if player_id <= 0 or player_id in seen:
            raise ValueError("Lineup player EA IDs must be positive and unique.")
        seen.add(player_id)
        starter = raw.get("starter")
        if starter not in (True, False, None):
            raise ValueError("Starter must be true, false or unknown.")
        position_value = raw.get("observedPosition")
        position = canonical_position(position_value) if position_value else None
        if position_value and not position:
            raise ValueError("Observed position is not recognized.")
        minutes = {}
        for key in ("onMinute", "offMinute"):
            value = raw.get(key)
            if value in (None, ""):
                minutes[key] = None
            else:
                try:
                    minutes[key] = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Substitution minute must be an integer.") from exc
                if not 0 <= minutes[key] <= 130:
                    raise ValueError("Substitution minute must be between 0 and 130.")
        result.append({"playerEaId": player_id, "starter": starter,
                       "observedPosition": position, "role": _text(raw.get("role"), 80), **minutes})
    return result


def normalize_content(payload: dict[str, Any]) -> dict[str, Any]:
    line = payload.get("opponentDefensiveLine")
    if line in (None, ""):
        line = None
    else:
        try:
            line = int(line)
        except (TypeError, ValueError) as exc:
            raise ValueError("Opponent defensive line must be 3, 4 or 5.") from exc
        if line not in (3, 4, 5):
            raise ValueError("Opponent defensive line must be 3, 4 or 5.")
    content = {
        "note": _text(payload.get("note"), 5000),
        "ownLineup": _lineup(payload.get("ownLineup")),
        "opponentLineup": _lineup(payload.get("opponentLineup")),
        "ownFormation": _formation(payload.get("ownFormation")),
        "opponentFormation": _formation(payload.get("opponentFormation")),
        "opponentHypothesis": _formation(payload.get("opponentHypothesis")),
        "opponentAlternative": _formation(payload.get("opponentAlternative")),
        "opponentEvidence": _text(payload.get("opponentEvidence"), 1200),
        "opponentDefensiveLine": line,
    }
    own_ids = {item["playerEaId"] for item in content["ownLineup"]}
    if own_ids.intersection(item["playerEaId"] for item in content["opponentLineup"]):
        raise ValueError("The same player EA ID cannot appear on both teams.")
    if content["opponentFormation"] and not content["opponentEvidence"]:
        raise ValueError("A confirmed opponent formation needs the coach's observation as evidence.")
    if content["opponentHypothesis"] and not content["opponentEvidence"]:
        raise ValueError("An opponent formation hypothesis needs supporting evidence.")
    return content


def _observed_xi_shape(lineup: list[dict[str, Any]]) -> str | None:
    """Only explicitly marked starters with observed match positions count."""
    starters = [item for item in lineup if item.get("starter") is True]
    if len(starters) != 11 or any(not item.get("observedPosition") for item in starters):
        return None
    groups = [broad_position_group(item["observedPosition"], default="Unknown") for item in starters]
    if groups.count("GK") != 1 or "Unknown" in groups:
        return None
    counts = [groups.count(group) for group in ("DEF", "MID", "ATT")]
    if not 3 <= counts[0] <= 5 or any(count <= 0 for count in counts[1:]):
        return None
    return "-".join(map(str, counts))


def own_formation_context(content: dict[str, Any]) -> dict[str, Any]:
    if content.get("ownFormation"):
        return {"status": "confirmed_manual", "formation": content["ownFormation"],
                "source": "coach observation", "support": "explicit own-team observation"}
    shape = _observed_xi_shape(content.get("ownLineup") or [])
    if shape:
        return {"status": "estimated_observed_xi", "formation": shape,
                "source": "coach-observed own XI", "support": "11 observed starters; phase changes unavailable"}
    return {"status": "indeterminate", "formation": None, "source": None,
            "support": "complete own XI with observed positions unavailable"}


def formation_context(content: dict[str, Any]) -> dict[str, Any]:
    """Never infer opponent shape from the managed club or natural positions."""
    line = content.get("opponentDefensiveLine")
    if content.get("opponentFormation"):
        return {"status": "confirmed_manual", "formation": content["opponentFormation"],
                "alternative": None, "defensiveLine": line, "source": "coach observation",
                "evidence": content.get("opponentEvidence"), "support": "explicit observation"}
    if content.get("opponentHypothesis"):
        return {"status": "estimated_manual", "formation": content["opponentHypothesis"],
                "alternative": content.get("opponentAlternative"), "defensiveLine": line,
                "source": "coach hypothesis", "evidence": content.get("opponentEvidence"),
                "support": "qualitative; not independently verified"}
    shape = _observed_xi_shape(content.get("opponentLineup") or [])
    if shape:
        return {"status": "estimated_observed_xi", "formation": shape,
                "alternative": None, "defensiveLine": line, "source": "coach-observed opponent XI",
                "evidence": "11 explicitly marked starters with observed positions",
                "support": "descriptive shape; phase changes unavailable"}
    return {"status": "indeterminate", "formation": None, "alternative": None,
            "defensiveLine": line, "source": "manual observation" if line else None,
            "evidence": content.get("opponentEvidence"),
            "support": "complete observed opponent XI or explicit formation evidence unavailable"}


def _row_payload(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["content"] = json.loads(item.pop("content_json"))
    item["formationContext"] = formation_context(item["content"])
    item["ownFormationContext"] = own_formation_context(item["content"])
    return item


def diary_at_fixture(conn: Any, career_id: int, fixture_id: int, snapshot: Any | None = None) -> dict[str, Any] | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_match_diary'").fetchone():
        return None
    row = conn.execute("SELECT * FROM manual_match_diary WHERE career_id=? AND fixture_id=? AND active=1",
                       (career_id, fixture_id)).fetchone()
    if not row:
        return None
    current = _row_payload(row)
    if snapshot is not None:
        cutoff = str(snapshot["imported_at"] or "")
        known = conn.execute(
            """SELECT * FROM manual_match_diary_revisions
               WHERE diary_id=? AND recorded_at<=? ORDER BY revision DESC LIMIT 1""",
            (row["id"], cutoff)).fetchone() if cutoff else None
        current["knownAtSnapshot"] = _row_payload(known) if known and known["active"] else None
        current["retrospective"] = current["knownAtSnapshot"] is None or current["knownAtSnapshot"]["revision"] != current["revision"]
    return current


class MatchDiaryService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _fixture(conn: Any, career_id: int, fixture_id: int, snapshot_id: int | None = None) -> Any:
        row = conn.execute("""SELECT f.id FROM fixtures f WHERE f.id=? AND f.career_id=?
            AND EXISTS (SELECT 1 FROM fixture_observations fo JOIN snapshots s ON s.id=fo.snapshot_id
                        WHERE fo.fixture_id=f.id AND fo.managed_team_involved=1 AND s.career_id=?)""",
            (fixture_id, career_id, career_id)).fetchone()
        if not row:
            raise ValueError("Fixture does not belong to this career.")
        if snapshot_id is not None:
            observed = conn.execute(
                """SELECT s.id,s.imported_at FROM fixture_observations fo
                   JOIN snapshots s ON s.id=fo.snapshot_id
                   WHERE s.id=? AND s.career_id=? AND fo.fixture_id=? AND fo.managed_team_involved=1""",
                (snapshot_id, career_id, fixture_id)).fetchone()
            if not observed:
                raise ValueError("Fixture is not available in the selected snapshot.")
            return observed
        return row

    def get(self, career_id: int, fixture_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        with self.database.connect() as conn:
            snapshot = self._fixture(conn, career_id, fixture_id, snapshot_id)
            current = diary_at_fixture(conn, career_id, fixture_id, snapshot if snapshot_id is not None else None)
            revisions = []
            known_at_snapshot = current.get("knownAtSnapshot") if current else None
            diary_row = conn.execute("SELECT id FROM manual_match_diary WHERE career_id=? AND fixture_id=?",
                                     (career_id, fixture_id)).fetchone()
            if diary_row:
                revisions = [_row_payload(row) for row in conn.execute(
                    "SELECT * FROM manual_match_diary_revisions WHERE diary_id=? ORDER BY revision DESC",
                    (diary_row["id"],))]
                if snapshot_id is not None and current is None:
                    known_revision = next((item for item in revisions
                                           if item["recorded_at"] <= str(snapshot["imported_at"] or "")), None)
                    known_at_snapshot = known_revision if known_revision and known_revision["active"] else None
            return {"current": current, "revisions": revisions, "fixtureId": fixture_id,
                    "careerId": career_id, "snapshotId": snapshot_id,
                    "knownAtSnapshot": known_at_snapshot}

    def save(self, career_id: int, fixture_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        author = _text(payload.get("author"), 120)
        if not author:
            raise ValueError("Coach/author is required.")
        content = normalize_content(payload)
        if not any(value for value in content.values()):
            raise ValueError("Record at least one observation.")
        observed_at = _text(payload.get("observedAt"), 30)
        if observed_at:
            try:
                datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("Observation date must use ISO format.") from exc
        with self.database.transaction() as conn:
            self._fixture(conn, career_id, fixture_id, int(payload["snapshotId"]) if payload.get("snapshotId") else None)
            prior = conn.execute("SELECT * FROM manual_match_diary WHERE career_id=? AND fixture_id=?",
                                 (career_id, fixture_id)).fetchone()
            expected = payload.get("expectedRevision")
            if prior and (expected is None or int(expected) != int(prior["revision"])):
                raise ValueError("Diary revision changed; reload before editing.")
            if not prior and expected not in (None, 0, "0"):
                raise ValueError("Diary revision changed; reload before editing.")
            stamp = _now()
            content_json = json.dumps(content, ensure_ascii=False, sort_keys=True)
            if prior:
                diary_id, revision = int(prior["id"]), int(prior["revision"]) + 1
                conn.execute("""UPDATE manual_match_diary SET revision=?,author=?,observed_at=?,updated_at=?,active=1,
                               content_json=? WHERE id=?""",
                             (revision, author, observed_at, stamp, content_json, diary_id))
            else:
                revision = 1
                cursor = conn.execute("""INSERT INTO manual_match_diary
                    (career_id,fixture_id,revision,author,observed_at,recorded_at,updated_at,active,content_json)
                    VALUES(?,?,?,?,?,?,?,1,?)""",
                    (career_id, fixture_id, revision, author, observed_at, stamp, stamp, content_json))
                diary_id = int(cursor.lastrowid)
            conn.execute("""INSERT INTO manual_match_diary_revisions
                (diary_id,revision,author,recorded_at,active,content_json) VALUES(?,?,?,?,1,?)""",
                (diary_id, revision, author, stamp, content_json))
        return self.get(career_id, fixture_id, int(payload["snapshotId"]) if payload.get("snapshotId") else None)

    def invalidate(self, career_id: int, fixture_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        author = _text(payload.get("author"), 120)
        if not author:
            raise ValueError("Coach/author is required.")
        with self.database.transaction() as conn:
            self._fixture(conn, career_id, fixture_id)
            prior = conn.execute("SELECT * FROM manual_match_diary WHERE career_id=? AND fixture_id=? AND active=1",
                                 (career_id, fixture_id)).fetchone()
            if not prior:
                raise ValueError("No active diary entry for this fixture.")
            if int(payload.get("expectedRevision") or -1) != int(prior["revision"]):
                raise ValueError("Diary revision changed; reload before editing.")
            revision, stamp = int(prior["revision"]) + 1, _now()
            conn.execute("UPDATE manual_match_diary SET revision=?,author=?,updated_at=?,active=0 WHERE id=?",
                         (revision, author, stamp, prior["id"]))
            conn.execute("""INSERT INTO manual_match_diary_revisions
                (diary_id,revision,author,recorded_at,active,content_json) VALUES(?,?,?,?,0,?)""",
                (prior["id"], revision, author, stamp, prior["content_json"]))
        return {"ok": True, "fixtureId": fixture_id, "revision": revision, "active": False}
