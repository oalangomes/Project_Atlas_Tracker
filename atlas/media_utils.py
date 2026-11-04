from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SOURCE_TYPES = {
    "players": "Player images",
    "club_logos": "Club logos",
    "competition_logos": "Competitionslogos",
    "trophies": "Trophies",
    "stadiums": "Stadien",
    "kits": "Trikots",
    "sponsor_logos": "Sponsorenlogos",
    "supplier_logos": "Supplier logos",
    "auto": "Gemischter Ordner",
}
MEDIA_EXTENSIONS = {".dds", ".png", ".webp", ".jpg", ".jpeg"}

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def season_start_from_date(value: str | None) -> int | None:
    if not value:
        return None
    try:
        year, month, _ = [int(part) for part in value[:10].split("-")]
    except (TypeError, ValueError):
        return None
    return year if month >= 7 else year - 1

def unique_colors(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = str(value).upper()
        if normalized not in result:
            result.append(normalized)
    return result[:3]

def competition_crosswalk_name_key(value: str | None) -> str:
    """Conservative key for the supplied Object-ID/Competition-ID crosswalk.

    Sponsorship and country words stay intact so unrelated competitions can never
    collapse onto the same key. Broader normalization is only used later for the
    legacy league-name fallback.
    """
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def competition_name_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"mcdonald[’']?s", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [word for word in text.split() if word not in {
        "england", "germany", "france", "spain", "italy", "holland", "belgium",
        "denmark", "norway", "sweden", "scotland", "austria", "portugal", "usa",
        "mcdonalds", "uber", "eats", "enilive", "ea", "sports", "efl", "the",
    }]
    text = " ".join(words)
    replacements = (
        (r"\b1 bundesliga\b", "bundesliga"),
        (r"\bprimera division\b", "laliga"),
        (r"\bsegunda division\b", "laliga 2"),
        (r"\blg one\b", "league one"),
        (r"\blg two\b", "league two"),
        (r"\bplay offs?\b", ""),
        (r"\bplayoffs?\b", ""),
        (r"\bbarrages?\b", ""),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return " ".join(text.split())
