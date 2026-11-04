from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .db import Database

REFERENCE_FILE = Path(__file__).resolve().parent.parent / "reference" / "fc26_reference_v1.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rgb_hex(values: Iterable[Any]) -> str:
    parts = []
    for value in values:
        try:
            number = max(0, min(255, int(value or 0)))
        except (TypeError, ValueError):
            number = 0
        parts.append(number)
    while len(parts) < 3:
        parts.append(0)
    return "#" + "".join(f"{part:02X}" for part in parts[:3])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ReferenceImporter:
    def __init__(self, database: Database):
        self.database = database

    def ensure_builtin(self) -> bool:
        if not REFERENCE_FILE.is_file():
            return False
        payload = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
        with self.database.connect() as conn:
            team_count = conn.execute("SELECT COUNT(*) FROM reference_teams").fetchone()[0]
            league_count = conn.execute("SELECT COUNT(*) FROM reference_leagues").fetchone()[0]
            mapping_count = conn.execute("SELECT COUNT(*) FROM reference_competition_mappings").fetchone()[0]
            nation_count = conn.execute("SELECT COUNT(*) FROM reference_nations").fetchone()[0]
        changed = False
        if not team_count or not league_count:
            self._apply_payload(payload, str(REFERENCE_FILE), is_builtin=True)
            return True
        if not mapping_count:
            self._apply_competition_mappings(payload.get("competition_mappings") or [])
            changed = True
        if not nation_count:
            self._apply_nations(payload.get("nations") or [])
            changed = True
        return changed

    def status(self) -> dict[str, Any]:
        with self.database.connect() as conn:
            latest = conn.execute("SELECT * FROM reference_imports ORDER BY id DESC LIMIT 1").fetchone()
            counts = {
                "teams": conn.execute("SELECT COUNT(*) FROM reference_teams").fetchone()[0],
                "competitions": conn.execute("SELECT COUNT(*) FROM reference_competitions").fetchone()[0],
                "leagues": conn.execute("SELECT COUNT(*) FROM reference_leagues").fetchone()[0],
                "competitionMappings": conn.execute("SELECT COUNT(*) FROM reference_competition_mappings").fetchone()[0],
                "nations": conn.execute("SELECT COUNT(*) FROM reference_nations").fetchone()[0],
                "kits": conn.execute("SELECT COUNT(*) FROM reference_kits").fetchone()[0],
                "stadiums": conn.execute("SELECT COUNT(*) FROM reference_stadiums").fetchone()[0],
            }
        return {"latest": dict(latest) if latest else None, "counts": counts}

    @staticmethod
    def _name_key(value: Any) -> str:
        # Keep the imported crosswalk and runtime media resolver in exactly the
        # same conservative name space. Exact Object-ID mapping remains primary.
        from .media import competition_crosswalk_name_key
        return competition_crosswalk_name_key(str(value or ""))

    def _apply_competition_mappings(self, mappings: list[dict[str, Any]]) -> None:
        if not mappings:
            return
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM reference_competition_mappings")
            conn.executemany(
                "INSERT INTO reference_competition_mappings(source_object_id,ea_competition_id,competition_name,competition_name_key,source_label) VALUES(?,?,?,?,?)",
                [(int(item["object_id"]), int(item["competition_id"]), str(item.get("name") or ""), self._name_key(item.get("name")), "builtin_crosswalk") for item in mappings],
            )

    def _apply_nations(self, nations: list[dict[str, Any]]) -> None:
        if not nations:
            return
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM reference_nations")
            conn.executemany(
                "INSERT INTO reference_nations(nation_id,nation_name,iso_code,flag_code) VALUES(?,?,?,?)",
                [(int(item["id"]), str(item.get("name") or f"Nation {item['id']}"), item.get("iso"), item.get("flag_code")) for item in nations],
            )

    def import_xlsx(self, path: Path) -> dict[str, Any]:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise ValueError("The selected main database file was not found.")
        try:
            from openpyxl import load_workbook  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openpyxl is required for main database import. Run install_optional_dependencies.bat."
            ) from exc

        workbook = load_workbook(path, read_only=True, data_only=True)
        required = {"teams", "teamkits", "kitcoloroverrides", "competition", "leagues", "stadiums", "teamstadiumlinks"}
        missing = sorted(required.difference(workbook.sheetnames))
        if missing:
            raise ValueError("Main database does not contain all required tables: " + ", ".join(missing))

        def rows(sheet: str):
            worksheet = workbook[sheet]
            iterator = worksheet.iter_rows(values_only=True)
            headers = [str(value) if value is not None else "" for value in next(iterator)]
            for values in iterator:
                yield {headers[index]: values[index] for index in range(min(len(headers), len(values)))}

        teams = []
        for row in rows("teams"):
            team_id = row.get("teamid")
            if team_id is None:
                continue
            teams.append({
                "id": int(team_id),
                "name": str(row.get("teamname") or f"Team {team_id}"),
                "colors": [
                    [row.get("teamcolor1r"), row.get("teamcolor1g"), row.get("teamcolor1b")],
                    [row.get("teamcolor2r"), row.get("teamcolor2g"), row.get("teamcolor2b")],
                    [row.get("teamcolor3r"), row.get("teamcolor3g"), row.get("teamcolor3b")],
                ],
            })

        competitions = []
        for row in rows("competition"):
            competition_id = row.get("competitionid")
            if competition_id is None:
                continue
            competitions.append({
                "id": int(competition_id),
                "colors": [
                    [row.get("competitioncolor1r"), row.get("competitioncolor1g"), row.get("competitioncolor1b")],
                    [row.get("competitioncolor2r"), row.get("competitioncolor2g"), row.get("competitioncolor2b")],
                ],
            })

        leagues = []
        for row in rows("leagues"):
            league_id = row.get("leagueid")
            if league_id is None:
                continue
            leagues.append({
                "id": int(league_id),
                "name": str(row.get("leaguename") or f"Liga {league_id}"),
                "country_id": int(row.get("countryid") or 0),
                "level": int(row.get("level") or 0),
            })

        overrides: dict[int, list[list[Any]]] = {}
        for row in rows("kitcoloroverrides"):
            kit_id = row.get("teamkitid")
            if kit_id is None:
                continue
            overrides[int(kit_id)] = [
                [row.get("teamcolor1r"), row.get("teamcolor1g"), row.get("teamcolor1b")],
                [row.get("teamcolor2r"), row.get("teamcolor2g"), row.get("teamcolor2b")],
                [row.get("teamcolor3r"), row.get("teamcolor3g"), row.get("teamcolor3b")],
            ]

        kits = []
        for row in rows("teamkits"):
            kit_id, team_id = row.get("teamkitid"), row.get("teamtechid")
            if kit_id is None or team_id is None:
                continue
            colors = [
                [row.get("teamcolorprimr"), row.get("teamcolorprimg"), row.get("teamcolorprimb")],
                [row.get("teamcolorsecr"), row.get("teamcolorsecg"), row.get("teamcolorsecb")],
                [row.get("teamcolortertr"), row.get("teamcolortertg"), row.get("teamcolortertb")],
            ]
            kits.append({
                "id": int(kit_id),
                "team_id": int(team_id),
                "type": int(row.get("teamkittypetechid") or 0),
                "colors": overrides.get(int(kit_id), colors),
            })

        stadiums = []
        for row in rows("stadiums"):
            stadium_id = row.get("stadiumid")
            if stadium_id is None:
                continue
            stadiums.append({"id": int(stadium_id), "name": str(row.get("name") or f"Stadion {stadium_id}")})

        links = []
        for row in rows("teamstadiumlinks"):
            team_id, stadium_id = row.get("teamid"), row.get("stadiumid")
            if team_id is None or stadium_id is None:
                continue
            links.append({"team_id": int(team_id), "stadium_id": int(stadium_id)})


        nations = []
        if "nations" in workbook.sheetnames:
            for row in rows("nations"):
                nation_id = row.get("nationid")
                if nation_id is None:
                    continue
                name = str(row.get("nationname") or f"Nation {nation_id}")
                iso = str(row.get("isocountrycode") or "").upper() or None
                special = {"England": "GB-ENG", "Scotland": "GB-SCT", "Wales": "GB", "Northern Ireland": "GB"}
                nations.append({"id": int(nation_id), "name": name, "iso": iso, "flag_code": special.get(name, iso)})

        payload = {
            "format": "project-atlas-reference-1",
            "source_file": path.name,
            "source_sha256": file_sha256(path),
            "generated_at": now_iso(),
            "teams": teams,
            "competitions": competitions,
            "leagues": leagues,
            "kits": kits,
            "stadiums": stadiums,
            "team_stadium_links": links,
            "nations": nations,
        }
        self._apply_payload(payload, str(path), is_builtin=False)
        return self.status()

    def _apply_payload(self, payload: dict[str, Any], source_path: str, *, is_builtin: bool) -> None:
        teams = payload.get("teams") or []
        competitions = payload.get("competitions") or []
        leagues = payload.get("leagues") or []
        kits = payload.get("kits") or []
        stadiums = payload.get("stadiums") or []
        links = payload.get("team_stadium_links") or []
        competition_mappings = payload.get("competition_mappings") or []
        nations = payload.get("nations") or []
        with self.database.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO reference_imports(source_path,source_hash,source_label,imported_at,
                           team_count,competition_count,kit_count,stadium_count,is_builtin)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    source_path,
                    str(payload.get("source_sha256") or ""),
                    str(payload.get("source_file") or "EA FC Referenzdaten"),
                    now_iso(),
                    len(teams), len(competitions), len(kits), len(stadiums), int(is_builtin),
                ),
            )
            import_id = cursor.lastrowid
            conn.execute("DELETE FROM reference_team_stadiums")
            conn.execute("DELETE FROM reference_kits")
            conn.execute("DELETE FROM reference_stadiums")
            conn.execute("DELETE FROM reference_competitions")
            conn.execute("DELETE FROM reference_leagues")
            conn.execute("DELETE FROM reference_teams")
            conn.executemany(
                "INSERT INTO reference_teams(ea_team_id,team_name,color1,color2,color3,source_import_id) VALUES(?,?,?,?,?,?)",
                [
                    (
                        int(item["id"]), item.get("name"),
                        rgb_hex((item.get("colors") or [[0,0,0]])[0]),
                        rgb_hex((item.get("colors") or [[0,0,0],[0,0,0]])[1]),
                        rgb_hex((item.get("colors") or [[0,0,0],[0,0,0],[0,0,0]])[2]),
                        import_id,
                    )
                    for item in teams
                ],
            )
            conn.executemany(
                "INSERT INTO reference_competitions(ea_competition_id,color1,color2,source_import_id) VALUES(?,?,?,?)",
                [
                    (
                        int(item["id"]),
                        rgb_hex((item.get("colors") or [[0,0,0]])[0]),
                        rgb_hex((item.get("colors") or [[0,0,0],[0,0,0]])[1]),
                        import_id,
                    )
                    for item in competitions
                ],
            )
            conn.executemany(
                "INSERT INTO reference_leagues(ea_league_id,league_name,country_id,level,source_import_id) VALUES(?,?,?,?,?)",
                [
                    (int(item["id"]), str(item.get("name") or f"Liga {item['id']}"),
                     int(item.get("country_id") or 0), int(item.get("level") or 0), import_id)
                    for item in leagues
                ],
            )
            conn.executemany(
                "INSERT INTO reference_kits(ea_kit_id,ea_team_id,kit_type,color1,color2,color3,source_import_id) VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        int(item["id"]), int(item["team_id"]), int(item.get("type") or 0),
                        rgb_hex((item.get("colors") or [[0,0,0]])[0]),
                        rgb_hex((item.get("colors") or [[0,0,0],[0,0,0]])[1]),
                        rgb_hex((item.get("colors") or [[0,0,0],[0,0,0],[0,0,0]])[2]),
                        import_id,
                    )
                    for item in kits
                ],
            )
            conn.executemany(
                "INSERT INTO reference_stadiums(ea_stadium_id,stadium_name,source_import_id) VALUES(?,?,?)",
                [(int(item["id"]), item.get("name"), import_id) for item in stadiums],
            )
            conn.executemany(
                "INSERT INTO reference_team_stadiums(ea_team_id,ea_stadium_id,source_import_id) VALUES(?,?,?)",
                [(int(item["team_id"]), int(item["stadium_id"]), import_id) for item in links],
            )
            if competition_mappings:
                conn.execute("DELETE FROM reference_competition_mappings")
                conn.executemany(
                    "INSERT INTO reference_competition_mappings(source_object_id,ea_competition_id,competition_name,competition_name_key,source_label) VALUES(?,?,?,?,?)",
                    [(int(item["object_id"]), int(item["competition_id"]), str(item.get("name") or ""), self._name_key(item.get("name")), "builtin_crosswalk") for item in competition_mappings],
                )
            if nations:
                conn.execute("DELETE FROM reference_nations")
                conn.executemany(
                    "INSERT INTO reference_nations(nation_id,nation_name,iso_code,flag_code) VALUES(?,?,?,?)",
                    [(int(item["id"]), str(item.get("name") or f"Nation {item['id']}"), item.get("iso"), item.get("flag_code")) for item in nations],
                )
