"""Generate reproducible Atlas season reports from a read-only SQLite database."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from atlas.monthly_report_markdown import render_index, render_month, render_season
from atlas.monthly_reports import build_season_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Atlas workspace SQLite file")
    parser.add_argument("--career", type=int, required=True, help="careers.id")
    parser.add_argument("--season", type=int, required=True, help="snapshots.season_index")
    parser.add_argument("--snapshot", type=int, required=True, help="snapshots.id")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--month", help="optional YYYY-MM to write only that monthly Markdown")
    args = parser.parse_args()
    db = args.database.resolve(strict=True)
    out = args.out.resolve()
    if db == out or db in out.parents or out == db.parent:
        raise SystemExit("Output directory must be separate from the database")
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        report = build_season_report(conn, args.career, args.season, args.snapshot)
    out.mkdir(parents=True, exist_ok=True)
    previous = None
    for month in report["months"]:
        if args.month is None or args.month == month["month"]:
            (out / f"{month['month']}.md").write_text(
                render_month(report, month, previous, navigation=args.month is None), encoding="utf-8")
        previous = month
    if args.month is not None:
        if args.month not in {month["month"] for month in report["months"]}:
            raise SystemExit(f"No completed managed matches in {args.month}")
        print(json.dumps({"month": args.month, "snapshotId": report["snapshotId"]}))
        return 0
    (out / "temporada.md").write_text(render_season(report), encoding="utf-8")
    (out / "README.md").write_text(render_index(report), encoding="utf-8")
    print(json.dumps({"months": [month["month"] for month in report["months"]],
                      "fixtures": report["fixtureCount"], "players": report["playerCount"],
                      "snapshotId": report["snapshotId"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
