from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SnapshotValidationError(Exception):
    def __init__(self, message: str, *, code: str = "validation_error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class ValidatedSnapshot:
    path: Path
    manifest: dict[str, Any]
    content_hash: str
    warnings: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshotId"])

    @property
    def ordering_key(self) -> tuple[Any, ...]:
        ordering = self.manifest["ordering"]
        return (
            int(ordering.get("seasonIndex") or 0),
            int(ordering.get("careerDateSort") or 0),
            int(ordering.get("managedCompletedFixtureCount") or 0),
            int(ordering.get("globalCompletedFixtureCount") or 0),
            str(ordering.get("exportedAtUtc") or ""),
            str(ordering.get("snapshotId") or self.snapshot_id),
        )


class SnapshotContract:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8-sig"))
        self.compatibility_contracts: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
        for candidate in path.parent.glob("FC26_CareerTracker_Snapshot_Contract_v*.json"):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                self.compatibility_contracts.append((self.version_tuple(data.get("schemaVersion")), data))
            except Exception:
                continue
        self.compatibility_contracts.sort(key=lambda item: item[0])

    @staticmethod
    def version_tuple(value: Any) -> tuple[int, int, int]:
        parts = str(value or "0.0.0").split(".")
        values = []
        for part in parts[:3]:
            try:
                values.append(int(part))
            except ValueError:
                values.append(0)
        while len(values) < 3:
            values.append(0)
        return tuple(values)  # type: ignore[return-value]

    @property
    def supported_major(self) -> int:
        return self.version_tuple(self.data["schemaVersion"])[0]

    def data_for(self, schema_version: Any) -> dict[str, Any]:
        target = self.version_tuple(schema_version)
        eligible = [data for version, data in self.compatibility_contracts if version <= target]
        return eligible[-1] if eligible else self.data


class SnapshotValidator:
    def __init__(self, contract: SnapshotContract):
        self.contract = contract

    def validate(self, folder: Path) -> ValidatedSnapshot:
        folder = folder.resolve()
        if not folder.is_dir():
            raise SnapshotValidationError("Snapshot path is not a folder.", code="not_a_directory")
        if not (folder / self.contract.data["readyMarker"]).is_file():
            raise SnapshotValidationError("READY marker is missing.", code="ready_missing")
        manifest_path = folder / self.contract.data["authoritativeManifest"]
        if not manifest_path.is_file():
            raise SnapshotValidationError("manifest.json is missing.", code="manifest_missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise SnapshotValidationError(f"manifest.json is invalid: {exc}", code="manifest_invalid") from exc

        self._validate_manifest(manifest)
        schema_version = str(manifest["schemaVersion"])
        contract_data = self.contract.data_for(schema_version)
        file_entries = {str(item.get("name")): item for item in manifest.get("files", []) if item.get("name")}
        warnings: list[str] = []
        row_counts: dict[str, int] = {}

        for required in contract_data["hardRequiredFiles"]:
            if required not in file_entries and not (folder / required).is_file():
                raise SnapshotValidationError(f"Required file is missing: {required}", code="required_file_missing")

        for expected in contract_data.get("expectedFeatureFiles", []):
            entry = file_entries.get(expected)
            if not (folder / expected).is_file():
                warnings.append(f"Feature file is missing: {expected}")
            elif entry and entry.get("status") not in (None, "ok"):
                warnings.append(f"{expected}: {entry.get('status')} – {entry.get('note', '')}".strip())

        for name, entry in file_entries.items():
            file_path = folder / name
            status = str(entry.get("status") or "ok")
            if status == "ok" and not file_path.is_file():
                raise SnapshotValidationError(f"A file marked as OK in the manifest is missing: {name}", code="listed_file_missing")
            if not file_path.is_file():
                warnings.append(f"Optional file is not present: {name}")
                continue
            expected_size = entry.get("byteSize")
            if expected_size not in (None, "") and file_path.stat().st_size != int(expected_size):
                raise SnapshotValidationError(
                    f"File size does not match: {name}",
                    code="file_size_mismatch",
                    details={"expected": int(expected_size), "actual": file_path.stat().st_size},
                )
            if name.endswith(".csv"):
                count, csv_warnings = self._validate_csv(file_path, name, contract_data, schema_version)
                warnings.extend(csv_warnings)
                row_counts[name] = count
                expected_rows = entry.get("rowCount")
                if expected_rows not in (None, "") and count != int(expected_rows):
                    raise SnapshotValidationError(
                        f"Row count does not match: {name}",
                        code="row_count_mismatch",
                        details={"expected": int(expected_rows), "actual": count},
                    )
            if status != "ok":
                warnings.append(f"{name}: {status} – {entry.get('note', '')}".strip())

        warnings.extend(self._profitability_warnings(folder, manifest, schema_version))

        unresolved = folder / "unresolved_player_names.csv"
        if unresolved.is_file() and self._count_csv_rows(unresolved) > 0:
            raise SnapshotValidationError(
                "Snapshot contains unresolved player names.", code="unresolved_player_names"
            )

        content_hash = self._content_hash(folder, file_entries)
        return ValidatedSnapshot(folder, manifest, content_hash, warnings, row_counts)

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        required = ("schemaVersion", "snapshotId", "status", "career", "ordering")
        missing = [key for key in required if key not in manifest]
        if missing:
            raise SnapshotValidationError(f"Manifest-Pflichtfelder fehlen: {', '.join(missing)}", code="manifest_fields_missing")
        if manifest.get("status") != "complete":
            raise SnapshotValidationError("Snapshot is not marked as complete in the manifest.", code="manifest_incomplete")
        try:
            major = int(str(manifest["schemaVersion"]).split(".")[0])
        except Exception as exc:
            raise SnapshotValidationError("Invalid schemaVersion.", code="schema_invalid") from exc
        if major != self.contract.supported_major:
            raise SnapshotValidationError(
                f"Unsupported snapshot major version: {manifest['schemaVersion']}", code="schema_unsupported"
            )
        career = manifest["career"]
        ordering = manifest["ordering"]
        for key in ("fingerprintCandidate", "seasonIndex", "careerDate", "careerDateSort"):
            if career.get(key) in (None, ""):
                raise SnapshotValidationError(f"Career metadata is missing: {key}", code="career_metadata_missing")
        for key in ("seasonIndex", "careerDateSort", "managedCompletedFixtureCount", "globalCompletedFixtureCount", "exportedAtUtc", "snapshotId"):
            if ordering.get(key) in (None, ""):
                raise SnapshotValidationError(f"Sort metadata is missing: {key}", code="ordering_metadata_missing")

    def _validate_csv(
        self, path: Path, name: str, contract_data: dict[str, Any], schema_version: str
    ) -> tuple[int, list[str]]:
        warnings: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            contract = contract_data.get("files", {}).get(name)
            if contract:
                missing = [col for col in contract.get("requiredColumns", []) if col not in headers]
                if name == "teams.csv" and "profitability" in missing and self.contract.version_tuple(schema_version) >= (1, 2, 0):
                    warnings.append("teams.csv: profitability column is missing despite snapshot schema 1.2.0 or newer.")
                    missing.remove("profitability")
                if missing:
                    raise SnapshotValidationError(
                        f"Pflichtspalten fehlen in {name}: {', '.join(missing)}",
                        code="required_columns_missing",
                    )
            count = sum(1 for _ in reader)
        return count, warnings

    def _profitability_warnings(
        self, folder: Path, manifest: dict[str, Any], schema_version: str
    ) -> list[str]:
        warnings: list[str] = []
        capabilities = manifest.get("capabilities") or {}
        if self.contract.version_tuple(schema_version) >= (1, 2, 0) and capabilities.get("teamProfitability") is False:
            warnings.append("Capability teamProfitability is false.")
        path = folder / "teams.csv"
        if not path.is_file():
            return warnings
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            if "profitability" not in headers:
                return warnings
            nonempty = 0
            nonnumeric = 0
            outside = 0
            samples: list[str] = []
            for row in reader:
                raw = str(row.get("profitability") or "").strip()
                if not raw:
                    continue
                nonempty += 1
                try:
                    value = int(float(raw))
                except (TypeError, ValueError):
                    nonnumeric += 1
                    if len(samples) < 3:
                        samples.append(f"Team {row.get('team_id')}: {raw}")
                    continue
                if not 1 <= value <= 10:
                    outside += 1
                    if len(samples) < 3:
                        samples.append(f"Team {row.get('team_id')}: {value}")
            if nonempty == 0:
                warnings.append("teams.csv: all profitability values are empty.")
            if nonnumeric:
                warnings.append(f"teams.csv: {nonnumeric} Profitability values are not numeric ({'; '.join(samples)}).")
            if outside:
                warnings.append(f"teams.csv: {outside} Profitability values are outside 1–10; raw values were retained ({'; '.join(samples)}).")
        return warnings

    @staticmethod
    def _count_csv_rows(path: Path) -> int:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)

    @staticmethod
    def _content_hash(folder: Path, file_entries: dict[str, dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for name in sorted(file_entries):
            path = folder / name
            if not path.is_file() or name in {"manifest.json", "manifest.csv", "export_log.txt"}:
                continue
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()
