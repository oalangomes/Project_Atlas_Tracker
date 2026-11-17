"""Storage and public contract for the configured AI provider credentials."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .secret_protection import protect_secret, unprotect_secret


PROVIDERS = ("gemini", "groq")
SETTING_KEY = "llm_config"


def _stored_config(conn: Any) -> dict[str, Any]:
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (SETTING_KEY,)).fetchone()
        parsed = json.loads(row["value"]) if row else {}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _protected_keys(config: dict[str, Any]) -> tuple[dict[str, str], bool]:
    raw = config.get("keys")
    keys = {str(name).strip().lower(): str(value or "").strip()
            for name, value in raw.items()} if isinstance(raw, dict) else {}
    migrated = dict(keys)
    changed = False
    for name, value in keys.items():
        if not value or value.startswith("dpapi:"):
            continue
        protected = protect_secret(value)
        if protected is None or unprotect_secret(protected) != value:
            raise ValueError("Protected credential storage is unavailable on this system.")
        migrated[name] = protected
        changed = True
    return migrated, changed


def load_config(conn: Any, *, migrate: bool = True) -> tuple[dict[str, Any], bool]:
    """Migrate all legacy plaintext keys atomically when protection is available.

    A failed migration leaves the original row untouched, so an existing key is
    never discarded. The second value tells the UI that migration is pending.
    """
    config = _stored_config(conn)
    if not migrate:
        raw = config.get("keys")
        pending = isinstance(raw, dict) and any(
            str(value or "").strip() and not str(value).strip().startswith("dpapi:")
            for value in raw.values()
        )
        return config, bool(pending)
    try:
        keys, changed = _protected_keys(config)
    except ValueError:
        return config, True
    if changed:
        updated = {**config, "keys": keys}
        try:
            conn.execute(
                "UPDATE app_settings SET value=? WHERE key=?",
                (json.dumps(updated, ensure_ascii=False), SETTING_KEY),
            )
        except sqlite3.Error:
            conn.rollback()
            return config, True
        config = updated
    return config, False


def public_config(conn: Any) -> dict[str, Any]:
    config, migration_pending = load_config(conn)
    raw = config.get("keys") if isinstance(config.get("keys"), dict) else {}
    values = {name: str(raw.get(name) or "").strip() for name in PROVIDERS}
    resolved = {name: unprotect_secret(value) for name, value in values.items()}
    return {
        "provider": _provider(config.get("provider")),
        "model": str(config.get("model") or "").strip(),
        "cloud_consent": config.get("cloud_consent") is True,
        "cloud_failover_consent": config.get("cloud_failover_consent") is True,
        "configured": {name: bool(resolved[name]) for name in PROVIDERS},
        "key_hints": {name: (f"…{resolved[name][-4:]}" if len(resolved[name]) > 4
                             else "••••" if resolved[name] else "") for name in PROVIDERS},
        "locked": {name: bool(values[name].startswith("dpapi:") and not resolved[name])
                   for name in PROVIDERS},
        "migration_pending": migration_pending,
    }


def _provider(value: Any) -> str:
    name = str(value or "ollama").strip().lower()
    return name if name in {"ollama", *PROVIDERS} else "ollama"


def update_config(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    config, migration_pending = load_config(conn)
    if migration_pending:
        raise ValueError("Protected credential storage is unavailable on this system.")
    requested = payload.get("provider")
    provider = _provider(config.get("provider")) if requested is None else str(requested).strip().lower()
    if provider not in {"ollama", *PROVIDERS}:
        raise ValueError("Unknown AI provider.")
    raw = config.get("keys")
    keys = {str(name).strip().lower(): str(value or "").strip()
            for name, value in raw.items()} if isinstance(raw, dict) else {}
    incoming = payload.get("keys")
    if incoming is not None and not isinstance(incoming, dict):
        raise ValueError("Invalid credential update.")
    for name, value in (incoming or {}).items():
        name = str(name).strip().lower()
        if name not in PROVIDERS:
            raise ValueError("Unknown AI provider.")
        text = str(value or "").strip()
        if not text:
            continue
        protected = protect_secret(text)
        if protected is None or unprotect_secret(protected) != text:
            raise ValueError("Protected credential storage is unavailable on this system.")
        keys[name] = protected
    removed = payload.get("remove") or []
    if not isinstance(removed, list):
        raise ValueError("Invalid credential removal.")
    for name in removed:
        name = str(name).strip().lower()
        if name not in PROVIDERS:
            raise ValueError("Unknown AI provider.")
        keys.pop(name, None)
    updated = {**config, "provider": provider, "keys": keys,
               "model": str(payload.get("model") or config.get("model") or "").strip()}
    for field in ("cloud_consent", "cloud_failover_consent"):
        if field in payload:
            if not isinstance(payload[field], bool):
                raise ValueError("Invalid cloud consent setting.")
            updated[field] = payload[field]
    if not updated.get("cloud_consent"):
        updated["cloud_failover_consent"] = False
    conn.execute(
        "INSERT INTO app_settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SETTING_KEY, json.dumps(updated, ensure_ascii=False)),
    )
    return {"ok": True, **public_config(conn)}
