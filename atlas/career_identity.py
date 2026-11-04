from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import SnapshotValidationError
from .paths import (
    current_workspace_id,
    load_workspace_registry,
    save_workspace_registry,
)

IDENTITY_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def identity_descriptor(career: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret origin metadata useful for safe alias evolution.

    FC26 currently exposes only a candidate fingerprint, not a proven save GUID.  Atlas
    therefore stores its own profile identity and treats exporter fingerprints as
    aliases.  Manager + initial club are deliberately used only as an evolution check,
    never as a globally unique key.
    """
    return {
        "managerDisplayName": _text(career.get("managerDisplayName")) or None,
        "managerNationalityId": career.get("managerNationalityId"),
        "initialTeamId": career.get("initialTeamId"),
        "initialTeamName": _text(career.get("initialTeamName")) or None,
    }


def _same_origin(left: dict[str, Any] | None, right: dict[str, Any]) -> bool:
    if not left:
        return False
    left_manager = _text(left.get("managerDisplayName")).casefold()
    right_manager = _text(right.get("managerDisplayName")).casefold()
    left_team = left.get("initialTeamId")
    right_team = right.get("initialTeamId")
    if left_team not in (None, "") and right_team not in (None, "") and str(left_team) != str(right_team):
        return False
    if left_manager and right_manager and left_manager != right_manager:
        return False
    # Require at least one strong matching field; empty metadata must never auto-alias.
    return bool((left_team not in (None, "") and right_team not in (None, "")) or (left_manager and right_manager))


def _workspace_target(registry: dict[str, Any]) -> dict[str, Any]:
    workspace_id = current_workspace_id()
    target = next(
        (item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id),
        None,
    )
    if target is None:
        raise SnapshotValidationError("The active Atlas career profile is not registered.", code="career_profile_missing")
    return target


def _ensure_identity(target: dict[str, Any]) -> dict[str, Any]:
    identity = target.get("careerIdentity")
    if not isinstance(identity, dict):
        legacy = _text(target.get("careerFingerprint"))
        identity = {
            "version": IDENTITY_VERSION,
            "localProfileId": str(target.get("id") or ""),
            "state": "bound" if legacy else "unbound",
            "primaryFingerprint": legacy or None,
            "fingerprintAliases": [legacy] if legacy else [],
            "origin": None,
            "pending": None,
        }
        target["careerIdentity"] = identity
    identity.setdefault("version", IDENTITY_VERSION)
    identity.setdefault("localProfileId", str(target.get("id") or ""))
    identity.setdefault("state", "bound" if _text(target.get("careerFingerprint")) else "unbound")
    aliases = identity.get("fingerprintAliases")
    if not isinstance(aliases, list):
        aliases = []
    legacy = _text(target.get("careerFingerprint"))
    primary = _text(identity.get("primaryFingerprint"))
    for value in (legacy, primary):
        if value and value not in aliases:
            aliases.append(value)
    identity["fingerprintAliases"] = aliases
    return identity


@dataclass(frozen=True)
class IdentityDecision:
    state: str
    fingerprint: str
    message: str = ""


class CareerIdentityGuard:
    """Installation registry backed save/profile identity guard.

    A profile owns a local identity. FC26 exporter candidates are accepted aliases,
    not trusted save GUIDs. New empty profiles require explicit user approval before
    the first snapshot can bind; the binding is finalized only after the snapshot DB
    transaction commits successfully.
    """

    @classmethod
    def inspect_snapshot(cls, career: dict[str, Any]) -> IdentityDecision:
        fingerprint = _text(career.get("fingerprintCandidate"))
        if not fingerprint:
            raise SnapshotValidationError("Snapshot does not contain a career fingerprint.", code="career_identity_missing")
        registry = load_workspace_registry()
        target = _workspace_target(registry)
        identity = _ensure_identity(target)
        aliases = {_text(value) for value in identity.get("fingerprintAliases", []) if _text(value)}
        origin = identity_descriptor(career)
        state = _text(identity.get("state")) or "unbound"

        if state == "bound":
            if fingerprint in aliases:
                return IdentityDecision("accepted", fingerprint)
            if _same_origin(identity.get("origin") if isinstance(identity.get("origin"), dict) else None, origin):
                # Candidate evolution (e.g. legacy v1 -> stable v2) is allowed only when
                # immutable origin metadata agrees. The alias itself is persisted only
                # after the snapshot transaction commits successfully.
                return IdentityDecision("accepted_alias_pending_commit", fingerprint)
            raise SnapshotValidationError(
                f"Wrong FC26 save for career profile '{target.get('name') or target.get('id')}'.",
                code="career_profile_fingerprint_mismatch",
                details={"receivedFingerprint": fingerprint, "expectedAliases": sorted(aliases), "receivedOrigin": origin},
            )

        pending = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        if pending and _text(pending.get("fingerprint")) == fingerprint and bool(pending.get("approved")):
            return IdentityDecision("approved_pending", fingerprint)

        identity["state"] = "pending"
        identity["pending"] = {
            "fingerprint": fingerprint,
            "origin": origin,
            "approved": False,
            "firstSeenAt": _now(),
        }
        target["updatedAt"] = _now()
        save_workspace_registry(registry)
        return IdentityDecision(
            "approval_required",
            fingerprint,
            "New career save detected. Confirm the assignment in Atlas setup; the snapshot remains untouched until then.",
        )

    @classmethod
    def finalize_after_commit(cls, career: dict[str, Any]) -> None:
        fingerprint = _text(career.get("fingerprintCandidate"))
        registry = load_workspace_registry()
        target = _workspace_target(registry)
        identity = _ensure_identity(target)
        aliases = {_text(value) for value in identity.get("fingerprintAliases", []) if _text(value)}
        origin = identity_descriptor(career)
        if _text(identity.get("state")) == "bound":
            if fingerprint in aliases:
                return
            if _same_origin(identity.get("origin") if isinstance(identity.get("origin"), dict) else None, origin):
                identity["fingerprintAliases"] = sorted(aliases | {fingerprint})
                identity["primaryFingerprint"] = fingerprint
                target["careerFingerprint"] = fingerprint
                target["updatedAt"] = _now()
                save_workspace_registry(registry)
                return
            return
        pending = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        if not pending or _text(pending.get("fingerprint")) != fingerprint or not bool(pending.get("approved")):
            return
        aliases = {_text(value) for value in identity.get("fingerprintAliases", []) if _text(value)}
        aliases.add(fingerprint)
        identity.update({
            "version": IDENTITY_VERSION,
            "state": "bound",
            "primaryFingerprint": fingerprint,
            "fingerprintAliases": sorted(aliases),
            "origin": pending.get("origin") or identity_descriptor(career),
            "boundAt": _now(),
            "pending": None,
        })
        target["careerFingerprint"] = fingerprint
        target["updatedAt"] = _now()
        save_workspace_registry(registry)

    @classmethod
    def approve_pending(cls, workspace_id: str) -> dict[str, Any]:
        registry = load_workspace_registry()
        target = next((item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id), None)
        if target is None:
            raise ValueError("Career save not found.")
        identity = _ensure_identity(target)
        pending = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        if not pending or not _text(pending.get("fingerprint")):
            raise ValueError("This career save has no detected FC26 career waiting for confirmation.")
        pending["approved"] = True
        pending["approvedAt"] = _now()
        identity["state"] = "pending"
        target["updatedAt"] = _now()
        save_workspace_registry(registry)
        return dict(target)

    @classmethod
    def cancel_pending(cls, workspace_id: str) -> dict[str, Any]:
        registry = load_workspace_registry()
        target = next((item for item in registry.get("workspaces", []) if isinstance(item, dict) and str(item.get("id")) == workspace_id), None)
        if target is None:
            raise ValueError("Career save not found.")
        identity = _ensure_identity(target)
        if _text(identity.get("state")) == "bound":
            raise ValueError("A bound career save cannot be unbound without clearing its data.")
        identity["pending"] = None
        identity["state"] = "unbound"
        target["careerFingerprint"] = None
        target["updatedAt"] = _now()
        save_workspace_registry(registry)
        return dict(target)

    @classmethod
    def validate_artifact_fingerprint(cls, fingerprint: str, *, artifact: str) -> str:
        fingerprint = _text(fingerprint)
        registry = load_workspace_registry()
        target = _workspace_target(registry)
        identity = _ensure_identity(target)
        aliases = {_text(value) for value in identity.get("fingerprintAliases", []) if _text(value)}
        state = _text(identity.get("state")) or "unbound"
        if state == "bound":
            if fingerprint in aliases:
                return "accepted"
            raise SnapshotValidationError(
                f"{artifact} does not belong to the active career save '{target.get('name') or target.get('id')}'.",
                code="career_profile_fingerprint_mismatch",
                details={"artifact": artifact, "receivedFingerprint": fingerprint, "expectedAliases": sorted(aliases)},
            )
        pending = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        if pending and bool(pending.get("approved")) and _text(pending.get("fingerprint")) == fingerprint:
            return "approved_pending"
        return "unbound"

    @classmethod
    def accepts_fingerprint(cls, fingerprint: str) -> bool:
        fingerprint = _text(fingerprint)
        registry = load_workspace_registry()
        target = _workspace_target(registry)
        identity = _ensure_identity(target)
        aliases = {_text(value) for value in identity.get("fingerprintAliases", []) if _text(value)}
        if fingerprint in aliases:
            return True
        pending = identity.get("pending") if isinstance(identity.get("pending"), dict) else None
        return bool(pending and bool(pending.get("approved")) and _text(pending.get("fingerprint")) == fingerprint)
