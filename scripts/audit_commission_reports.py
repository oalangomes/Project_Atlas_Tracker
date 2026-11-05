"""Read-only quality audit for cached Atlas technical commission reports.

Usage:
  python -m scripts.audit_commission_reports --db path/to/atlas.sqlite3 --career-id 1

Does not contact Ollama, modify the database, or claim to score football reasoning.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from atlas.commission import _report_recommendation_target_conflict
from atlas.commission_prompt_policy import claim_signature, is_generic_claim


_SECTIONS = ("observations", "recommendations", "strengths",
             "development_areas", "training_suggestions")


def evaluate_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Flags measurable failure modes; human review is required for sporting value."""
    report = payload.get("report") or {}
    if not isinstance(report, dict):
        report = {}
    facts = payload.get("fact_catalog") or []
    valid_refs = {str(fact.get("id")) for fact in facts if isinstance(fact, dict)}
    mode = str(payload.get("mode") or "")
    context = {"mode": mode, "facts": facts}
    totals = Counter()
    seen: set[str] = set()
    sample: list[str] = []

    def inspect(item: Any, section: str) -> None:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            return
        text = str(item["text"])
        totals["total_claims"] += 1
        signature = claim_signature(text)
        if signature in seen:
            totals["duplicate_claims"] += 1
        seen.add(signature)
        if is_generic_claim(text, section):
            totals["generic_claims"] += 1
            if len(sample) < 3:
                sample.append(text[:160])
        references = item.get("fact_refs")
        if not isinstance(references, list) or not references or not set(references).issubset(valid_refs):
            totals["missing_or_invalid_refs"] += 1
        if section == "recommendations" and _report_recommendation_target_conflict(context, mode, text):
            totals["opponent_targeted_recommendations"] += 1

    inspect(report.get("summary"), "summary")
    for section in _SECTIONS:
        for item in report.get(section) or []:
            inspect(item, section)
    summary = report.get("summary") or {}
    if isinstance(summary, dict) and summary.get("model_generated") is False:
        totals["deterministic_summary_fallback"] += 1
    if payload.get("review_required"):
        totals["review_required"] += 1
    if report.get("formation"):
        value = report["formation"]
        allowed = next((f.get("value") for f in facts if f.get("id") == "formation_options"), [])
        if not isinstance(value, dict) or value.get("shape") not in (allowed or []):
            totals["unsupported_formation"] += 1
    return {"mode": mode, "flags": dict(totals), "examples": sample}


def audit_database(db_path: Path, career_id: int | None = None,
                   limit: int = 5000) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    # The URI is opened in SQLite mode=ro. Never mutate a user career.
    uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='technical_commission_report_cache'"
        ).fetchone()
        if not table:
            return {"scanned": 0, "warning": "No technical_commission_report_cache table"}
        sql = ("SELECT career_id,snapshot_id,mode,scope_key,payload_json "
               "FROM technical_commission_report_cache")
        args: list[Any] = []
        if career_id is not None:
            sql += " WHERE career_id=?"
            args.append(career_id)
        sql += " ORDER BY snapshot_id,mode,scope_key LIMIT ?"
        args.append(limit)
        totals: Counter[str] = Counter()
        modes: Counter[str] = Counter()
        flagged = []
        scanned = 0
        for row in con.execute(sql, args):
            scanned += 1
            try:
                payload = json.loads(row["payload_json"] or "{}")
                quality = evaluate_report(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                totals["invalid_payload_json"] += 1
                continue
            modes[str(row["mode"])] += 1
            totals.update(quality["flags"])
            if any(quality["flags"].get(key, 0) for key in (
                    "generic_claims", "duplicate_claims", "missing_or_invalid_refs",
                    "opponent_targeted_recommendations", "unsupported_formation",
                    "deterministic_summary_fallback")) and len(flagged) < 30:
                flagged.append({"career_id": int(row["career_id"]),
                                "snapshot_id": int(row["snapshot_id"]),
                                "mode": str(row["mode"]),
                                "scope_key": str(row["scope_key"]),
                                "flags": quality["flags"],
                                "generic_examples": quality["examples"]})
        return {"scanned": scanned, "by_mode": dict(modes),
                "flags": dict(totals), "flagged_examples": flagged,
                "caveat": "These checks measure structure, specificity and contradictions; "
                          "they do not prove sporting correctness or causal insight."}
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="SQLite file (opened read-only)")
    parser.add_argument("--career-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    print(json.dumps(audit_database(args.db, args.career_id, max(1, args.limit)),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
