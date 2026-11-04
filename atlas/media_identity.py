from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .media_utils import (
    MEDIA_EXTENSIONS, SOURCE_TYPES, competition_crosswalk_name_key, competition_name_key,
    file_sha256, now_iso, season_start_from_date, unique_colors,
)
from .paths import media_cache_dir, media_originals_dir, media_thumbnails_dir

class MediaIdentityMixin:
    def assign(self, asset_id: int, entity_type: str, ea_id: int, media_type: str | None = None) -> dict[str, Any]:
        if entity_type not in {"player", "club", "competition", "stadium", "sponsor", "supplier"}:
            raise ValueError("Unknown entity type.")
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                raise ValueError("Media item not found.")
            chosen_type = media_type or row["media_type"]
            if chosen_type in {"logo", "unrecognized"}:
                chosen_type = "club_logo" if entity_type == "club" else "competition_logo" if entity_type == "competition" else "player_portrait" if entity_type == "player" else "sponsor_logo" if entity_type == "sponsor" else "supplier_logo" if entity_type == "supplier" else "stadium"
            conn.execute(
                """UPDATE media_assets SET entity_type=?,ea_id=?,media_type=?,status='assigned',warning=NULL,
                           is_active=1,processing_state=CASE WHEN cache_path IS NULL THEN 'pending' ELSE 'ready' END,updated_at=? WHERE id=?""",
                (entity_type, ea_id, chosen_type, now_iso(), asset_id),
            )
        self.enqueue(asset_id, priority=0)
        return self.asset(asset_id)

    def asset(self, asset_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise ValueError("Media item not found.")
        item = dict(row)
        if item.get("status") == "assigned":
            version = self._asset_version(item)
            item["url"] = self.asset_url(asset_id, "cache", version)
            item["thumbUrl"] = self.asset_url(asset_id, "thumb", version)
        else:
            item["url"] = None
            item["thumbUrl"] = None
        return item

    @staticmethod
    def _asset_version(item: dict[str, Any]) -> str:
        content_hash = str(item.get("content_hash") or "").strip()
        if content_hash:
            return content_hash[:16]
        basis = "|".join(str(item.get(key) or "") for key in (
            "source_path", "source_mtime_ns", "source_size", "updated_at",
            "entity_type", "ea_id", "media_type", "season_start", "variant",
        ))
        return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()[:16]

    @staticmethod
    def asset_url(asset_id: int, kind: str = "cache", version: str | None = None) -> str:
        base = f"/api/media/files/{int(asset_id)}/{kind}"
        return f"{base}?v={version}" if version else base

    def file_path(self, asset_id: int, kind: str) -> tuple[Path, str]:
        field = {"cache": "cache_path", "thumb": "thumb_path", "original": "original_copy_path"}.get(kind)
        if not field:
            raise ValueError("Unknowne Mediendatei-Variante.")
        self.ensure_processed(asset_id)
        with self.database.connect() as conn:
            row = conn.execute(f"SELECT {field} path FROM media_assets WHERE id=?", (asset_id,)).fetchone()
        if not row or not row["path"]:
            raise ValueError("Media file not found.")
        path = Path(row["path"])
        if not path.is_file():
            raise ValueError("Media file is missing from Atlas storage.")
        return path, mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def resolve(self, entity_type: str, ea_id: int, media_type: str, *, season_start: int | None = None, variant: str | None = None) -> dict[str, Any] | None:
        clauses = ["entity_type=?", "ea_id=?", "media_type=?", "status='assigned'", "is_active=1"]
        args: list[Any] = [entity_type, ea_id, media_type]
        if variant is not None:
            clauses.append("COALESCE(variant,'')=?")
            args.append(variant)
        with self.database.connect() as conn:
            preferred = None
            if season_start is not None:
                preferred = conn.execute(
                    f"""SELECT * FROM media_assets WHERE {' AND '.join(clauses)} AND season_start=?
                        ORDER BY updated_at DESC,id DESC LIMIT 1""",
                    (*args, season_start),
                ).fetchone()
            row = preferred or conn.execute(
                f"""SELECT * FROM media_assets WHERE {' AND '.join(clauses)} AND COALESCE(season_start,0)=0
                    ORDER BY updated_at DESC,id DESC LIMIT 1""",
                tuple(args),
            ).fetchone()
            if not row and season_start is None:
                row = conn.execute(
                    f"SELECT * FROM media_assets WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC,id DESC LIMIT 1",
                    tuple(args),
                ).fetchone()
        if not row:
            return None
        item = dict(row)
        version = self._asset_version(item)
        item["url"] = self.asset_url(item["id"], "cache", version)
        item["thumbUrl"] = self.asset_url(item["id"], "thumb", version)
        item["usedFallback"] = bool(season_start and (item.get("season_start") or 0) == 0)
        return item

    def resolve_many(self, entity_type: str, ea_ids: list[int] | set[int] | tuple[int, ...], media_type: str) -> dict[int, dict[str, Any]]:
        """Resolve many non-seasonal identities with one database read.

        Sponsor and supplier catalogs contain thousands of entries. Resolving
        every logo through ``resolve`` would open thousands of SQLite
        connections and make the commercial overview unusably slow.
        """
        ids = sorted({int(value) for value in ea_ids})
        if not ids:
            return {}
        rows = []
        # Stay below SQLite builds that still use a conservative host-parameter
        # limit. The catalog currently contains more than four thousand
        # sponsors, so one giant ``IN`` clause is not portable enough.
        with self.database.connect() as conn:
            for start in range(0, len(ids), 800):
                chunk = ids[start:start + 800]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(conn.execute(
                    f"""SELECT * FROM media_assets
                        WHERE entity_type=? AND media_type=? AND status='assigned' AND is_active=1
                          AND ea_id IN ({placeholders})
                        ORDER BY ea_id,
                                 CASE WHEN COALESCE(season_start,0)=0 THEN 0 ELSE 1 END,
                                 updated_at DESC,id DESC""",
                    (entity_type, media_type, *chunk),
                ).fetchall())
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            ea_id = int(row["ea_id"])
            if ea_id in result:
                continue
            item = dict(row)
            version = self._asset_version(item)
            item["url"] = self.asset_url(item["id"], "cache", version)
            item["thumbUrl"] = self.asset_url(item["id"], "thumb", version)
            item["usedFallback"] = False
            result[ea_id] = item
        return result

    def player_media(self, player_id: int) -> dict[str, Any]:
        portrait = self.resolve("player", player_id, "player_portrait")
        return {"portrait": portrait, "placeholderSeed": int(player_id)}

    def team_brief(self, team_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            reference = conn.execute("SELECT * FROM reference_teams WHERE ea_team_id=?", (team_id,)).fetchone()
        return {
            "teamId": team_id,
            "colors": unique_colors([reference["color1"], reference["color2"], reference["color3"]]) if reference else [],
            "logo": self.resolve("club", team_id, "club_logo"),
            "referenceName": reference["team_name"] if reference else None,
        }

    def team_identity(self, team_id: int, *, season_start: int | None = None) -> dict[str, Any]:
        with self.database.connect() as conn:
            reference = conn.execute("SELECT * FROM reference_teams WHERE ea_team_id=?", (team_id,)).fetchone()
        colors = unique_colors([reference["color1"], reference["color2"], reference["color3"]]) if reference else []
        return {
            "teamId": team_id,
            "colors": colors,
            "logo": self.resolve("club", team_id, "club_logo"),
            "kits": self.kits_for_team(team_id, season_start=season_start),
            "stadiums": self.stadiums_for_team(team_id),
            "referenceName": reference["team_name"] if reference else None,
        }

    def _save_competition_link(self, competition_object_id: int, competition_name: str, media_ea_id: int, source: str, confidence: float) -> None:
        key = competition_name_key(competition_name)
        with self.database.transaction() as conn:
            existing = conn.execute(
                "SELECT source FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=?",
                (competition_object_id, key),
            ).fetchone()
            if existing and existing["source"] == "manual" and source != "manual":
                return
            conn.execute(
                """INSERT INTO competition_media_links(competition_object_id,competition_name_key,competition_name,media_ea_id,source,confidence,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(competition_object_id,competition_name_key) DO UPDATE SET
                     competition_name=excluded.competition_name,media_ea_id=excluded.media_ea_id,
                     source=excluded.source,confidence=excluded.confidence,updated_at=excluded.updated_at""",
                (competition_object_id, key, competition_name, media_ea_id, source, confidence, now_iso()),
            )

    def _competition_row(self, competition_object_id: int, snapshot_id: int | None = None):
        with self.database.connect() as conn:
            if snapshot_id is not None:
                row = conn.execute(
                    "SELECT * FROM competition_states WHERE snapshot_id=? AND competition_object_id=?",
                    (snapshot_id, competition_object_id),
                ).fetchone()
                if row:
                    return row
            return conn.execute(
                """SELECT cs.* FROM competition_states cs JOIN snapshots s ON s.id=cs.snapshot_id
                   WHERE cs.competition_object_id=? ORDER BY s.import_sequence DESC,cs.snapshot_id DESC LIMIT 1""",
                (competition_object_id,),
            ).fetchone()

    def _participant_league_id(self, snapshot_id: int, competition_object_id: int) -> tuple[int, float] | None:
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT f.home_team_ea_id,f.away_team_ea_id FROM fixtures f
                   JOIN fixture_observations fo ON fo.fixture_id=f.id
                   WHERE fo.snapshot_id=? AND f.competition_object_id=?""",
                (snapshot_id, competition_object_id),
            ).fetchall()
            team_ids = {int(value) for row in rows for value in (row["home_team_ea_id"], row["away_team_ea_id"]) if value is not None}
            if not team_ids:
                return None
            placeholders = ",".join("?" for _ in team_ids)
            league_rows = conn.execute(
                f"SELECT league_ea_id,COUNT(*) count FROM team_league_states WHERE snapshot_id=? AND team_ea_id IN ({placeholders}) AND league_ea_id IS NOT NULL GROUP BY league_ea_id ORDER BY count DESC",
                (snapshot_id, *sorted(team_ids)),
            ).fetchall()
        if not league_rows:
            return None
        total = sum(int(row["count"]) for row in league_rows)
        top = league_rows[0]
        share = int(top["count"]) / max(1, total)
        if int(top["count"]) >= 6 and share >= 0.72:
            return int(top["league_ea_id"]), share
        return None

    def _derive_competition_media_id(self, competition_object_id: int, competition_name: str, snapshot_id: int | None) -> tuple[int, str, float] | None:
        crosswalk_target = competition_crosswalk_name_key(competition_name)
        target = competition_name_key(competition_name)

        # Competition names are much more stable across FC26 title updates than
        # runtime object IDs. If the bundled crosswalk has exactly one exact name
        # match, it is authoritative and must beat a stale/wrong snapshot static ID.
        if crosswalk_target:
            with self.database.connect() as conn:
                crosswalk = conn.execute(
                    "SELECT ea_competition_id,source_object_id,competition_name FROM reference_competition_mappings WHERE competition_name_key=? ORDER BY ea_competition_id",
                    (crosswalk_target,),
                ).fetchall()
            if len(crosswalk) == 1:
                return int(crosswalk[0]["ea_competition_id"]), "reference_crosswalk_name", 1.0

        def snapshot_candidate(media_id: int, source: str) -> tuple[int, str, float] | None:
            """Accept a snapshot media ID unless reference data disproves its name."""
            if media_id <= 0:
                return None
            if crosswalk_target or target:
                with self.database.connect() as conn:
                    known = conn.execute(
                        "SELECT competition_name FROM reference_competition_mappings WHERE ea_competition_id=?",
                        (media_id,),
                    ).fetchall()
                if known:
                    compatible = any(
                        (crosswalk_target and competition_crosswalk_name_key(item["competition_name"]) == crosswalk_target)
                        or (target and competition_name_key(item["competition_name"]) == target)
                        for item in known
                    )
                    if not compatible:
                        return None
            return media_id, source, 1.0

        row = self._competition_row(competition_object_id, snapshot_id)
        if row:
            static_column = row["static_competition_id"] if "static_competition_id" in row.keys() else None
            try:
                static_value = int(static_column)
            except (TypeError, ValueError):
                static_value = 0
            candidate = snapshot_candidate(static_value, "snapshot_static_id")
            if candidate:
                return candidate
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                raw = {}
            for key in ("competition_id", "competitionid", "static_competition_id", "media_competition_id"):
                try:
                    media_id = int(raw.get(key))
                except (TypeError, ValueError):
                    continue
                candidate = snapshot_candidate(media_id, "snapshot")
                if candidate:
                    return candidate

        # Runtime competition object IDs may shift between title updates. Known
        # namespace offsets are useful only when the candidate's name agrees.
        # A name mismatch now rejects the object-ID candidate instead of silently
        # borrowing a neighbouring competition's logo.
        candidates = (competition_object_id, competition_object_id - 31, competition_object_id - 32, competition_object_id - 45)
        placeholders = ",".join("?" for _ in candidates)
        with self.database.connect() as conn:
            direct_rows = conn.execute(
                f"SELECT ea_competition_id,source_object_id,competition_name FROM reference_competition_mappings WHERE source_object_id IN ({placeholders})",
                candidates,
            ).fetchall()
        if target:
            named_rows = [item for item in direct_rows if competition_name_key(item["competition_name"]) == target]
            direct_rows = named_rows  # no name match means no object-ID fallback
        if direct_rows:
            best_offset = min(abs(competition_object_id - int(item["source_object_id"])) for item in direct_rows)
            best = [item for item in direct_rows if abs(competition_object_id - int(item["source_object_id"])) == best_offset]
            if len({int(item["ea_competition_id"]) for item in best}) == 1:
                return int(best[0]["ea_competition_id"]), "reference_crosswalk_object", 1.0

        # League names in the reference file include country/level decorations, so
        # use the broader normalizer only after the conservative competition map.
        if target:
            with self.database.connect() as conn:
                leagues = conn.execute("SELECT ea_league_id,league_name FROM reference_leagues ORDER BY ea_league_id").fetchall()
            exact = [row for row in leagues if competition_name_key(row["league_name"]) == target]
            if len(exact) == 1:
                return int(exact[0]["ea_league_id"]), "league_name", 0.98
            contained = [
                row for row in leagues
                if (lambda key: key and min(len(key), len(target)) >= 5 and (key in target or target in key))(competition_name_key(row["league_name"]))
            ]
            if len(contained) == 1:
                return int(contained[0]["ea_league_id"]), "league_name", 0.94

        league_markers = ("league", "liga", "bundesliga", "ligue", "serie", "eredivisie", "premiership", "superliga", "allsvenskan", "division", "championship")
        if snapshot_id is not None and any(marker in target for marker in league_markers):
            inferred = self._participant_league_id(snapshot_id, competition_object_id)
            if inferred:
                league_id, share = inferred
                return league_id, "participants", round(share, 3)
        return None

    def league_identity(self, league_id: int, *, league_name: str | None = None) -> dict[str, Any]:
        """Resolve league media directly from the stable EA league ID.

        Atlas world competitions use EA league IDs rather than transient competition
        object IDs. Their logos can therefore be assigned with the same competition
        media assets, without creating a synthetic competition mapping.
        """
        with self.database.connect() as conn:
            league = conn.execute(
                "SELECT * FROM reference_leagues WHERE ea_league_id=?", (league_id,)
            ).fetchone()
            reference = conn.execute(
                "SELECT * FROM reference_competitions WHERE ea_competition_id=?", (league_id,)
            ).fetchone()
        name = str(league_name or (league["league_name"] if league else "") or f"Liga {league_id}")
        return {
            "competitionId": league_id,
            "competitionObjectId": None,
            "competitionName": name,
            "mediaCompetitionId": league_id,
            "mappingSource": "league_id",
            "mappingConfidence": 1.0,
            "colors": unique_colors([reference["color1"], reference["color2"]]) if reference else [],
            "logo": self.resolve("competition", league_id, "competition_logo"),
            "trophy": self.resolve("competition", league_id, "trophy"),
        }

    def competition_identity(self, competition_id: int, *, snapshot_id: int | None = None, competition_name: str | None = None) -> dict[str, Any]:
        row = self._competition_row(competition_id, snapshot_id)
        name = str(competition_name or (row["competition_name"] if row else "") or f"Competition {competition_id}")
        key = competition_name_key(name)
        with self.database.connect() as conn:
            link = conn.execute(
                """SELECT * FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=?
                   UNION ALL SELECT * FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=''
                   LIMIT 1""",
                (competition_id, key, competition_id),
            ).fetchone()
        # Automatic mappings are deliberately re-evaluated. This repairs stale
        # links after an FC26 title update without overwriting a user's manual map.
        derived = None if link and link["source"] == "manual" else self._derive_competition_media_id(competition_id, name, snapshot_id)
        if derived and (not link or int(link["media_ea_id"]) != int(derived[0]) or link["source"] != derived[1]):
            self._save_competition_link(competition_id, name, *derived)
            with self.database.connect() as conn:
                link = conn.execute(
                    "SELECT * FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=?",
                    (competition_id, key),
                ).fetchone()
        elif not link and derived:
            if derived:
                self._save_competition_link(competition_id, name, *derived)
                with self.database.connect() as conn:
                    link = conn.execute(
                        "SELECT * FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=?",
                        (competition_id, key),
                    ).fetchone()
        media_id = int(link["media_ea_id"]) if link else None
        with self.database.connect() as conn:
            reference = conn.execute("SELECT * FROM reference_competitions WHERE ea_competition_id=?", (media_id,)).fetchone() if media_id is not None else None
        return {
            "competitionId": competition_id,
            "competitionObjectId": competition_id,
            "competitionName": name,
            "mediaCompetitionId": media_id,
            "mappingSource": link["source"] if link else None,
            "mappingConfidence": link["confidence"] if link else None,
            "colors": unique_colors([reference["color1"], reference["color2"]]) if reference else [],
            "logo": self.resolve("competition", media_id, "competition_logo") if media_id is not None else None,
            "trophy": self.resolve("competition", media_id, "trophy") if media_id is not None else None,
        }

    def competition_mappings(self, snapshot_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError("Snapshot not found.")
            competitions = conn.execute(
                "SELECT competition_object_id,competition_name FROM competition_states WHERE snapshot_id=? ORDER BY competition_name",
                (snapshot_id,),
            ).fetchall()
            available = conn.execute(
                """SELECT ea_id,MAX(CASE WHEN media_type='competition_logo' THEN id END) logo_asset_id,
                          MAX(CASE WHEN media_type='trophy' THEN id END) trophy_asset_id
                   FROM media_assets WHERE entity_type='competition' AND status='assigned' AND is_active=1
                     AND media_type IN ('competition_logo','trophy') GROUP BY ea_id ORDER BY ea_id"""
            ).fetchall()
        items = []
        for competition in competitions:
            identity = self.competition_identity(
                int(competition["competition_object_id"]), snapshot_id=snapshot_id, competition_name=competition["competition_name"]
            )
            items.append(identity)
        choices = []
        for item in available:
            logo_id = item["logo_asset_id"]
            trophy_id = item["trophy_asset_id"]
            choices.append({
                "mediaCompetitionId": item["ea_id"],
                "logo": self.asset(int(logo_id)) if logo_id else None,
                "trophy": self.asset(int(trophy_id)) if trophy_id else None,
            })
        return {"snapshotId": snapshot_id, "items": items, "choices": choices}

    def set_competition_mapping(self, snapshot_id: int, competition_object_id: int, media_ea_id: int | None) -> dict[str, Any]:
        row = self._competition_row(competition_object_id, snapshot_id)
        if not row:
            raise ValueError("Competition not found in the selected snapshot.")
        name = str(row["competition_name"] or "")
        key = competition_name_key(name)
        with self.database.transaction() as conn:
            if media_ea_id is None:
                conn.execute(
                    "DELETE FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=?",
                    (competition_object_id, key),
                )
            else:
                exists = conn.execute(
                    """SELECT 1 FROM media_assets WHERE entity_type='competition' AND ea_id=? AND status='assigned'
                       AND media_type IN ('competition_logo','trophy') LIMIT 1""",
                    (media_ea_id,),
                ).fetchone()
                if not exists:
                    raise ValueError("No competition logo or trophy was found for this media ID.")
                conn.execute(
                    """INSERT INTO competition_media_links(competition_object_id,competition_name_key,competition_name,media_ea_id,source,confidence,updated_at)
                       VALUES(?,?,?,?, 'manual',1.0,?)
                       ON CONFLICT(competition_object_id,competition_name_key) DO UPDATE SET
                         competition_name=excluded.competition_name,media_ea_id=excluded.media_ea_id,
                         source='manual',confidence=1.0,updated_at=excluded.updated_at""",
                    (competition_object_id, key, name, media_ea_id, now_iso()),
                )
        return self.competition_identity(competition_object_id, snapshot_id=snapshot_id, competition_name=name)

    def rebuild_competition_mappings(self, snapshot_id: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT competition_object_id,competition_name FROM competition_states WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "DELETE FROM competition_media_links WHERE competition_object_id=? AND competition_name_key=? AND source<>'manual'",
                    (row["competition_object_id"], competition_name_key(row["competition_name"])),
                )
        return self.competition_mappings(snapshot_id)

    def kits_for_team(self, team_id: int, *, season_start: int | None = None) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            references = conn.execute(
                "SELECT * FROM reference_kits WHERE ea_team_id=? ORDER BY kit_type,ea_kit_id", (team_id,)
            ).fetchall()
        by_type: dict[int, dict[str, Any]] = {}
        for row in references:
            kit_type = int(row["kit_type"])
            by_type.setdefault(kit_type, {
                "kitType": kit_type,
                "label": self.kit_label(kit_type),
                "referenceKitId": row["ea_kit_id"],
                "colors": unique_colors([row["color1"], row["color2"], row["color3"]]),
                "image": None,
            })
        with self.database.connect() as conn:
            available_types = [
                row[0] for row in conn.execute(
                    """SELECT DISTINCT kit_type FROM media_assets WHERE entity_type='club' AND ea_id=?
                       AND media_type='kit' AND status='assigned' AND is_active=1 ORDER BY kit_type""",
                    (team_id,),
                ).fetchall() if row[0] is not None
            ]
        for kit_type in sorted(set(by_type).union(available_types)):
            item = by_type.setdefault(kit_type, {"kitType": kit_type, "label": self.kit_label(kit_type), "colors": [], "image": None})
            item["image"] = self.resolve("club", team_id, "kit", season_start=season_start, variant=f"j{kit_type}")
        return [by_type[key] for key in sorted(by_type)]

    @staticmethod
    def _stadium_classification(name: str | None) -> dict[str, Any]:
        raw_name = str(name or "").strip()
        if not raw_name:
            return {"stadiumType": "unknown", "stadiumTypeLabel": "Type could not be determined unambiguously", "stadiumTypeSource": "missing_reference", "displayName": raw_name}
        if raw_name.startswith("_"):
            return {"stadiumType": "generic", "stadiumTypeLabel": "Generisches EA-Stadion", "stadiumTypeSource": "reference_name_prefix", "displayName": raw_name.lstrip("_").strip() or raw_name}
        return {"stadiumType": "authentic", "stadiumTypeLabel": "Authentisches Stadion", "stadiumTypeSource": "reference_stadium_catalog", "displayName": raw_name}

    def stadium_by_id(self, stadium_id: int) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            stadium = conn.execute(
                "SELECT * FROM reference_stadiums WHERE ea_stadium_id=?", (stadium_id,)
            ).fetchone()
            assets = conn.execute(
                """SELECT * FROM media_assets WHERE entity_type='stadium' AND ea_id=?
                   AND media_type='stadium' AND status='assigned' AND is_active=1
                   ORDER BY CAST(COALESCE(variant,'0') AS INTEGER),id""",
                (stadium_id,),
            ).fetchall()
        if not stadium and not assets:
            return None
        variants = []
        for asset in assets:
            item = self._public_asset(dict(asset))
            variants.append(item)
        raw_name = stadium["stadium_name"] if stadium else f"Stadion {stadium_id}"
        classification = self._stadium_classification(raw_name if stadium else None)
        return {
            "stadiumId": stadium_id,
            "name": classification["displayName"] or raw_name,
            "referenceName": raw_name,
            "variants": variants,
            **{key: value for key, value in classification.items() if key != "displayName"},
        }

    def stadiums_for_team(self, team_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            stadium_rows = conn.execute(
                """SELECT s.* FROM reference_stadiums s JOIN reference_team_stadiums l
                   ON l.ea_stadium_id=s.ea_stadium_id WHERE l.ea_team_id=? ORDER BY s.stadium_name""",
                (team_id,),
            ).fetchall()
        result = []
        for stadium in stadium_rows:
            with self.database.connect() as conn:
                assets = conn.execute(
                    """SELECT * FROM media_assets WHERE entity_type='stadium' AND ea_id=? AND media_type='stadium'
                       AND status='assigned' AND is_active=1 ORDER BY CAST(COALESCE(variant,'0') AS INTEGER),id""",
                    (stadium["ea_stadium_id"],),
                ).fetchall()
            variants = []
            for row in assets:
                item = dict(row)
                version = self._asset_version(item)
                item["url"] = self.asset_url(item["id"], "cache", version)
                item["thumbUrl"] = self.asset_url(item["id"], "thumb", version)
                variants.append(item)
            raw_name = stadium["stadium_name"]
            classification = self._stadium_classification(raw_name)
            result.append({
                "stadiumId": stadium["ea_stadium_id"],
                "name": classification["displayName"] or raw_name,
                "referenceName": raw_name,
                "variants": variants,
                **{key: value for key, value in classification.items() if key != "displayName"},
            })
        return result

    @staticmethod
    def kit_label(kit_type: int) -> str:
        return {0: "Heim", 1: "Away", 2: "Torwart", 3: "Drittes", 4: "Viertes"}.get(kit_type, f"Sondertrikot {kit_type}")
