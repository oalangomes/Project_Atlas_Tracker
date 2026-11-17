"""Find FC26 career players similar to a reference player (read-only).

The script reads an Atlas Tracker career database and ranks players by
attribute similarity to a reference player taken from the same snapshot.  It is
meant for scouting answers such as "find a right winger like Nishan Velupillay,
preferably left-footed or right-footed with four weak-foot stars".

Usage:
  python -m scripts.find_similar_players --save ARGILA --reference "Nishan Velupillay"
  python -m scripts.find_similar_players --save ARGILA --positions RW --foot left
  python -m scripts.find_similar_players --save ARGILA --reference "Nishan Velupillay" --json

The database is opened with SQLite mode=ro.  Nothing is written to a career.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas.paths import app_data_dir, workspace_registry_path  # noqa: E402


# Attributes used for the outfield similarity profile.
ATTACK_PROFILE = (
    "acceleration", "sprint_speed", "agility", "dribbling", "ball_control",
    "finishing", "crossing", "short_passing", "vision", "balance", "composure",
    "reactions", "stamina", "strength",
)

# Attributes shown for every candidate row.
REPORT_ATTRIBUTES = (
    "acceleration", "sprint_speed", "agility", "dribbling", "ball_control",
    "finishing", "crossing", "stamina",
)

POSITION_FIELDS = ("primary_position", "position_2", "position_3", "position_4")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def workspace_database_path(save: str | None) -> Path:
    """Resolves a workspace name (for example ARGILA) to its career database."""
    registry = _read_json(workspace_registry_path().read_text(encoding="utf-8-sig"))
    records = [item for item in registry.get("workspaces", []) if isinstance(item, dict)]
    target = None
    if save:
        for item in records:
            if str(item.get("name") or "").casefold() == save.casefold():
                target = item
                break
        if target is None:
            raise SystemExit(f"Unknown workspace: {save}. Use --list-workspaces.")
    else:
        target = next((item for item in records
                       if str(item.get("id")) == str(registry.get("activeWorkspaceId") or "")), None)
        if target is None:
            target = records[0] if records else None
    if target is None:
        raise SystemExit("No workspace found in the registry.")
    data_dir = str(target.get("dataDir") or ".")
    base = app_data_dir()
    path = (base / data_dir / "atlas_tracker.sqlite3").resolve()
    if not path.is_file():
        raise SystemExit(f"Career database not found: {path}")
    return path


def list_workspaces() -> list[dict[str, Any]]:
    registry = _read_json(workspace_registry_path().read_text(encoding="utf-8-sig"))
    rows = []
    for item in registry.get("workspaces", []):
        if not isinstance(item, dict):
            continue
        path = (app_data_dir() / str(item.get("dataDir") or ".") / "atlas_tracker.sqlite3")
        rows.append({"id": item.get("id"), "name": item.get("name"), "kind": item.get("kind"),
                     "database": str(path), "exists": path.is_file()})
    return rows


def connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def latest_snapshot(con: sqlite3.Connection, career_id: int | None) -> int:
    sql = "SELECT MAX(id) FROM snapshots"
    args: list[Any] = []
    if career_id is not None:
        sql = "SELECT MAX(id) FROM snapshots WHERE career_id=?"
        args.append(career_id)
    row = con.execute(sql, args).fetchone()
    return int(row[0] or 0)


def load_reference(con: sqlite3.Connection, snapshot_id: int, name: str | None,
                   player_id: int | None) -> tuple[str, dict[str, Any]]:
    if player_id is not None:
        row = con.execute(
            "SELECT display_name, raw_json FROM player_states WHERE snapshot_id=? AND ea_player_id=?",
            (snapshot_id, player_id)).fetchone()
    else:
        row = con.execute(
            "SELECT display_name, raw_json FROM player_states WHERE snapshot_id=? "
            "AND display_name LIKE ? COLLATE NOCASE ORDER BY snapshot_id DESC LIMIT 1",
            (snapshot_id, f"%{name}%")).fetchone()
    if not row:
        raise SystemExit(f"Reference player not found in snapshot {snapshot_id}: {name or player_id}")
    return str(row["display_name"]), _read_json(row["raw_json"])


def player_positions(raw: dict[str, Any]) -> list[str]:
    return [str(raw.get(field) or "") for field in POSITION_FIELDS if raw.get(field)]


def similarity(candidate: dict[str, Any], reference: dict[str, Any],
               pace_weight: float, potential_weight: float,
               overall: int, potential: int) -> float:
    """Similarity of one candidate to the reference profile (higher is closer)."""
    total = 0.0
    for key in ATTACK_PROFILE:
        target = _as_int(reference.get(key))
        if not target:
            continue
        total += max(0.0, 100 - abs(_as_int(candidate.get(key)) - target))
    score = total / len(ATTACK_PROFILE)
    candidate_pace = (_as_int(candidate.get("acceleration")) + _as_int(candidate.get("sprint_speed"))) / 2
    reference_pace = (_as_int(reference.get("acceleration")) + _as_int(reference.get("sprint_speed"))) / 2
    score += pace_weight * (candidate_pace - reference_pace)
    score += potential_weight * max(0, potential - overall)
    return score


def find_candidates(con: sqlite3.Connection, snapshot_id: int, reference: dict[str, Any],
                    positions: Iterable[str], foot: str, min_weak_foot: int,
                    min_overall: int, max_overall: int, leagues: Iterable[str],
                    exclude_teams: Iterable[str], pace_weight: float,
                    potential_weight: float) -> list[dict[str, Any]]:
    wanted = {p.upper() for p in positions}
    league_filters = [l.casefold() for l in leagues]
    excluded = {t.casefold() for t in exclude_teams}
    teams = {int(row["ea_team_id"]): (str(row["team_name"]), str(row["league_name"] or ""))
             for row in con.execute(
                 "SELECT ea_team_id, team_name, league_name FROM team_states WHERE snapshot_id=?",
                 (snapshot_id,))}
    candidates: list[dict[str, Any]] = []
    for row in con.execute(
            "SELECT ea_player_id, display_name, team_ea_id, team_name, overall, potential, raw_json "
            "FROM player_states WHERE snapshot_id=?", (snapshot_id,)):
        raw = _read_json(row["raw_json"])
        if not wanted & set(player_positions(raw)):
            continue
        preferred_foot = _as_int(raw.get("preferred_foot_id"))
        weak_foot = _as_int(raw.get("weak_foot"))
        if foot == "left" and preferred_foot != 2:
            continue
        if foot == "right" and not (preferred_foot == 1 and weak_foot >= min_weak_foot):
            continue
        if foot == "any" and not (preferred_foot == 2 or (preferred_foot == 1 and weak_foot >= min_weak_foot)):
            continue
        overall = _as_int(row["overall"])
        potential = _as_int(row["potential"])
        if overall < min_overall or overall > max_overall:
            continue
        team_name, league_name = teams.get(int(row["team_ea_id"] or 0), (str(row["team_name"] or ""), ""))
        if team_name.casefold() in excluded:
            continue
        if team_name.startswith("*"):
            # Placeholder club names come from unfinished custom career teams.
            continue
        if league_filters and not any(f in league_name.casefold() for f in league_filters):
            continue
        candidates.append({
            "score": round(similarity(raw, reference, pace_weight, potential_weight, overall, potential), 1),
            "name": str(row["display_name"]),
            "ea_player_id": int(row["ea_player_id"] or 0),
            "overall": overall,
            "potential": potential,
            "team": team_name,
            "league": league_name,
            "positions": player_positions(raw),
            "preferred_foot": preferred_foot,
            "weak_foot": weak_foot,
            "contract_valid_until": str(raw.get("contract_valid_until") or ""),
            "attributes": {key: _as_int(raw.get(key)) for key in REPORT_ATTRIBUTES},
        })
    candidates.sort(key=lambda item: (-item["score"], item["name"]))
    return candidates


def format_table(candidates: list[dict[str, Any]], reference_name: str) -> str:
    header = (f"{'#':>3} {'Score':>6} {'Nome':24} {'OVR':>3} {'POT':>3} {'Clube':22} {'Liga':20} "
              f"{'Pos':14} {'Pe':8} {'acc':>3} {'vel':>3} {'agi':>3} {'dri':>3} {'bc':>3} {'fin':>3} {'cro':>3} {'Contr':>5}")
    lines = [f"Referencia: {reference_name}", header, "-" * len(header)]
    for index, item in enumerate(candidates, start=1):
        attrs = item["attributes"]
        foot = "canhoto" if item["preferred_foot"] == 2 else "destro"
        lines.append(
            f"{index:>3} {item['score']:>6.1f} {item['name'][:24]:24} {item['overall']:>3} {item['potential']:>3} "
            f"{item['team'][:22]:22} {item['league'][:20]:20} {'/'.join(item['positions'][:3])[:14]:14} "
            f"{foot + ' ' + str(item['weak_foot']) + '*':8} {attrs['acceleration']:>3} {attrs['sprint_speed']:>3} "
            f"{attrs['agility']:>3} {attrs['dribbling']:>3} {attrs['ball_control']:>3} "
            f"{attrs['finishing']:>3} {attrs['crossing']:>3} {item['contract_valid_until']:>5}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", default=None, help="Workspace name, for example ARGILA")
    parser.add_argument("--db", type=Path, default=None, help="Explicit career database path")
    parser.add_argument("--list-workspaces", action="store_true")
    parser.add_argument("--snapshot-id", type=int, default=None, help="Defaults to the latest snapshot")
    parser.add_argument("--career-id", type=int, default=None)
    parser.add_argument("--reference", default=None, help="Reference player name (substring match)")
    parser.add_argument("--reference-id", type=int, default=None, help="Reference EA player id")
    parser.add_argument("--positions", default="RW,RM", help="Comma separated target positions")
    parser.add_argument("--foot", choices=("left", "right", "any"), default="any",
                        help="left = canhoto, right = destro with enough weak foot, any = both")
    parser.add_argument("--min-weak-foot", type=int, default=4,
                        help="Minimum weak-foot stars for right-footed candidates")
    parser.add_argument("--min-overall", type=int, default=0)
    parser.add_argument("--max-overall", type=int, default=100)
    parser.add_argument("--league", action="append", default=[],
                        help="League substring filter, repeatable")
    parser.add_argument("--exclude-team", action="append", default=[],
                        help="Team name to exclude, repeatable")
    parser.add_argument("--include-managed-team", action="store_true",
                        help="Keep the managed club of the snapshot in the results")
    parser.add_argument("--pace-weight", type=float, default=0.6)
    parser.add_argument("--potential-weight", type=float, default=1.5)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.list_workspaces:
        print(json.dumps(list_workspaces(), ensure_ascii=False, indent=2))
        return

    db_path = args.db or workspace_database_path(args.save)
    con = connect(db_path)
    try:
        snapshot_id = args.snapshot_id or latest_snapshot(con, args.career_id)
        if not snapshot_id:
            raise SystemExit("No snapshot found in this database.")
        if not args.reference and args.reference_id is None:
            raise SystemExit("Provide --reference NAME or --reference-id.")
        reference_name, reference = load_reference(con, snapshot_id, args.reference, args.reference_id)

        excluded = list(args.exclude_team)
        if not args.include_managed_team:
            row = con.execute("SELECT managed_team_name FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if row and row["managed_team_name"]:
                excluded.append(str(row["managed_team_name"]))

        candidates = find_candidates(
            con, snapshot_id, reference,
            [p for p in str(args.positions).split(",") if p.strip()],
            args.foot, args.min_weak_foot, args.min_overall, args.max_overall,
            args.league, excluded, args.pace_weight, args.potential_weight)
        candidates = candidates[:max(1, args.top)]
        if args.json:
            print(json.dumps({"database": str(db_path), "snapshot_id": snapshot_id,
                              "reference": reference_name, "candidates": candidates},
                             ensure_ascii=False, indent=2))
        else:
            print(f"Save: {db_path} | snapshot {snapshot_id}")
            print(format_table(candidates, reference_name))
    finally:
        con.close()


if __name__ == "__main__":
    main()
