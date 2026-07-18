"""Build and validate immutable fault evidence artifact manifests."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ARTIFACT_SCHEMA = "fault-evidence-artifact-manifest/v1"
DATASET_ROLES = {"development", "calibration", "test"}
CONDITION_VARIANTS = {"control", "injected"}

BASE_ROLES = {
    "runtime_events",
    "run_manifest",
    "oracle_manifest",
    "command_manifest",
    "fault_summary",
}
TRACE_ROLES = {
    "process_manifest",
    "clock_calibration",
    "ros2_ctf",
    "ros2_events",
    "ros2_events_manifest",
}
EBPF_ROLES = {
    "process_manifest",
    "ebpf_events",
    "ebpf_capture_summary",
}
REQUIRED_ROLES = {
    "F1": BASE_ROLES,
    "F2": BASE_ROLES | TRACE_ROLES,
    "F3": BASE_ROLES
    | TRACE_ROLES
    | {"scheduler_manifest", "ebpf_events", "ebpf_capture_summary"},
    "F4": BASE_ROLES | EBPF_ROLES,
    "F5": BASE_ROLES | TRACE_ROLES,
    "F6": BASE_ROLES,
}
MEDIA_TYPES = {
    "runtime_events": "application/x-ndjson",
    "ros2_events": "application/x-ndjson",
    "ebpf_events": "application/x-ndjson",
    "ros2_ctf": "application/x-ctf",
}
RECORD_FIELDS = {"role", "path", "kind", "bytes", "sha256", "media_type"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "fault_id",
    "condition_variant",
    "dataset_role",
    "required_roles",
    "artifacts",
}


class ArtifactValidationError(ValueError):
    """A stable evidence validation failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class MeasuredPath:
    kind: str
    bytes: int
    sha256: str


def required_artifact_roles(fault_id: str) -> set[str]:
    try:
        return set(REQUIRED_ROLES[fault_id])
    except KeyError as error:
        raise ArtifactValidationError(
            "artifact_invalid_fault", f"unsupported fault ID: {fault_id}"
        ) from error


def measure_path(path: Path) -> MeasuredPath:
    if path.is_symlink():
        raise ArtifactValidationError(
            "artifact_symlink", f"symlink is forbidden: {path}"
        )
    if path.is_file():
        size = path.stat().st_size
        if size < 1:
            raise ArtifactValidationError(
                "artifact_empty", f"artifact is empty: {path}"
            )
        return MeasuredPath("file", size, _sha256_file(path))
    if not path.is_dir():
        raise ArtifactValidationError(
            "artifact_missing", f"artifact is missing: {path}"
        )

    entries = sorted(path.rglob("*"))
    if any(item.is_symlink() for item in entries):
        raise ArtifactValidationError(
            "artifact_symlink", f"symlink is forbidden below: {path}"
        )
    files = [item for item in entries if item.is_file()]
    if not files:
        raise ArtifactValidationError("artifact_empty", f"directory is empty: {path}")
    digest = hashlib.sha256()
    total = 0
    for file_path in files:
        relative = file_path.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        payload = file_path.read_bytes()
        digest.update(payload)
        total += len(payload)
    return MeasuredPath("directory", total, digest.hexdigest())


def build_artifact_manifest(
    *,
    fault_id: str,
    condition_variant: str,
    dataset_role: str,
    case_root: Path,
    artifacts: Mapping[str, Path],
) -> dict[str, Any]:
    required = required_artifact_roles(fault_id)
    _validate_identity(condition_variant, dataset_role)
    roles = set(artifacts)
    _validate_roles(roles, required)
    root = case_root.resolve()
    records = []
    for role in sorted(roles):
        path = _inside(root, artifacts[role])
        measured = measure_path(path)
        expected_kind = "directory" if role == "ros2_ctf" else "file"
        if measured.kind != expected_kind:
            raise ArtifactValidationError(
                "artifact_kind_mismatch", f"{role} must be a {expected_kind}"
            )
        records.append(
            {
                "role": role,
                "path": path.relative_to(root).as_posix(),
                "kind": measured.kind,
                "bytes": measured.bytes,
                "sha256": measured.sha256,
                "media_type": MEDIA_TYPES.get(role, "application/json"),
            }
        )
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "fault_id": fault_id,
        "condition_variant": condition_variant,
        "dataset_role": dataset_role,
        "required_roles": sorted(required),
        "artifacts": records,
    }


def validate_artifact_manifest(
    value: dict[str, Any],
    *,
    case_root: Path,
    expected_fault_id: str,
    expected_condition_variant: str,
    expected_dataset_role: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_FIELDS:
        raise ArtifactValidationError(
            "artifact_manifest_invalid", "invalid artifact manifest fields"
        )
    if value.get("schema_version") != ARTIFACT_SCHEMA:
        raise ArtifactValidationError(
            "artifact_manifest_invalid", "unsupported artifact manifest schema"
        )
    if value.get("dataset_role") != expected_dataset_role:
        raise ArtifactValidationError(
            "artifact_dataset_role_mismatch", "artifact dataset role does not match"
        )
    if (
        value.get("fault_id") != expected_fault_id
        or value.get("condition_variant") != expected_condition_variant
    ):
        raise ArtifactValidationError(
            "artifact_identity_mismatch", "artifact fault identity does not match"
        )
    _validate_identity(expected_condition_variant, expected_dataset_role)
    required = required_artifact_roles(expected_fault_id)
    if value.get("required_roles") != sorted(required):
        raise ArtifactValidationError(
            "artifact_role_missing", "artifact required role contract does not match"
        )
    records = value.get("artifacts")
    if not isinstance(records, list):
        raise ArtifactValidationError(
            "artifact_manifest_invalid", "artifact records must be a list"
        )
    roles = [record.get("role") for record in records if isinstance(record, dict)]
    if len(roles) != len(records) or len(set(roles)) != len(roles):
        raise ArtifactValidationError(
            "artifact_manifest_invalid", "artifact roles must be unique strings"
        )
    _validate_roles(set(roles), required)

    root = case_root.resolve()
    for record in records:
        if set(record) != RECORD_FIELDS:
            raise ArtifactValidationError(
                "artifact_manifest_invalid", "invalid artifact record fields"
            )
        role = record["role"]
        relative = record["path"]
        if not isinstance(relative, str) or not relative:
            raise ArtifactValidationError(
                "artifact_manifest_invalid", "artifact path must be a string"
            )
        path = _inside(root, root / relative)
        measured = measure_path(path)
        expected_kind = "directory" if role == "ros2_ctf" else "file"
        if record["kind"] != expected_kind or measured.kind != expected_kind:
            raise ArtifactValidationError(
                "artifact_kind_mismatch", f"artifact kind mismatch for {role}"
            )
        if record["media_type"] != MEDIA_TYPES.get(role, "application/json"):
            raise ArtifactValidationError(
                "artifact_manifest_invalid", f"artifact media type mismatch for {role}"
            )
        if record["bytes"] != measured.bytes:
            raise ArtifactValidationError(
                "artifact_size_mismatch", f"artifact size mismatch for {role}"
            )
        if record["sha256"] != measured.sha256:
            raise ArtifactValidationError(
                "artifact_hash_mismatch", f"artifact hash mismatch for {role}"
            )
    return copy.deepcopy(value)


def _validate_identity(condition_variant: str, dataset_role: str) -> None:
    if condition_variant not in CONDITION_VARIANTS:
        raise ArtifactValidationError(
            "artifact_identity_mismatch", "unsupported condition variant"
        )
    if dataset_role not in DATASET_ROLES:
        raise ArtifactValidationError(
            "artifact_dataset_role_mismatch", "unsupported artifact dataset role"
        )


def _validate_roles(actual: set[str], required: set[str]) -> None:
    missing = required - actual
    if missing:
        raise ArtifactValidationError(
            "artifact_role_missing", f"missing artifact roles: {sorted(missing)}"
        )
    extra = actual - required
    if extra:
        raise ArtifactValidationError(
            "artifact_role_unexpected", f"unexpected artifact roles: {sorted(extra)}"
        )


def _inside(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ArtifactValidationError(
            "artifact_path_escape", f"artifact path escapes case root: {path}"
        )
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
