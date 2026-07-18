"""Reconstruct session integrity from an immutable manifest and case files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from experiments.evidence_capture.artifact_manifest import (
    ArtifactValidationError,
    validate_artifact_manifest,
)

INTEGRITY_SCHEMA = "formal-experiment-session-integrity/v1"
RESULT_SCHEMA = "formal-experiment-case-result/v1"
STARTED_SCHEMA = "formal-experiment-case-started/v1"
TERMINAL_STATUSES = {"successful", "failed", "interrupted"}


def assess_session_integrity(
    manifest: dict[str, Any], session_root: Path
) -> dict[str, Any]:
    """Return a deterministic audit reconstructed from files."""
    root = session_root.resolve()
    errors: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    runs = manifest.get("runs")
    dataset_role = manifest.get("dataset_role")
    if (
        manifest.get("schema_version") != "formal-experiment-session-manifest/v1"
        or not isinstance(runs, list)
        or not isinstance(dataset_role, str)
    ):
        return _audit(0, {}, {"invalid_manifest"}, [])

    run_ids = [row.get("run_id") for row in runs if isinstance(row, dict)]
    if len(run_ids) != len(set(run_ids)):
        errors.add("duplicate_run_id")
    output_dirs = [row.get("output_dir") for row in runs if isinstance(row, dict)]
    if len(output_dirs) != len(set(output_dirs)):
        errors.add("duplicate_output_directory")

    counts = {
        "planned": len(runs),
        "not_started": 0,
        "running": 0,
        "successful": 0,
        "failed": 0,
        "interrupted": 0,
    }
    expected_case_dirs: set[Path] = set()
    for row in runs:
        if not isinstance(row, dict):
            errors.add("invalid_run_record")
            counts["not_started"] += 1
            continue
        try:
            output = _inside(root, row.get("output_dir"))
        except ValueError:
            errors.add("path_escape")
            counts["not_started"] += 1
            continue
        expected_case_dirs.add(output)
        started_path = output / "case_started.json"
        result_path = output / "case_result.json"
        if result_path.is_file():
            result = _read_object(result_path, errors, "invalid_case_result")
            if result is None:
                counts["failed"] += 1
                continue
            status = result.get("status")
            if status not in TERMINAL_STATUSES:
                errors.add("invalid_terminal_status")
                counts["failed"] += 1
            else:
                counts[status] += 1
            _validate_result(
                result,
                row=row,
                dataset_role=dataset_role,
                root=root,
                errors=errors,
                artifacts=artifacts,
            )
            artifacts.append(_artifact(root, result_path))
        elif started_path.is_file():
            counts["running"] += 1
            started = _read_object(started_path, errors, "invalid_case_started")
            if started is not None:
                if started.get("schema_version") != STARTED_SCHEMA:
                    errors.add("invalid_case_started")
                if started.get("run_id") != row.get("run_id"):
                    errors.add("started_run_id_mismatch")
                if started.get("dataset_role") != dataset_role:
                    errors.add("started_dataset_role_mismatch")
        else:
            counts["not_started"] += 1

    cases_root = root / "cases"
    if cases_root.is_dir():
        for path in cases_root.iterdir():
            if path.is_dir() and path.resolve() not in expected_case_dirs:
                errors.add("unreferenced_case_directory")
    status = (
        "invalid"
        if errors
        else "complete"
        if counts["successful"] == counts["planned"]
        else "incomplete"
    )
    return {
        "schema_version": INTEGRITY_SCHEMA,
        "status": status,
        "dataset_role": dataset_role,
        "counts": counts,
        "errors": sorted(errors),
        "artifacts": sorted(artifacts, key=lambda row: row["path"]),
    }


def mark_interrupted_runs(manifest: dict[str, Any], session_root: Path) -> list[str]:
    """Write interrupted results for started runs that lack terminal results."""
    root = session_root.resolve()
    dataset_role = manifest.get("dataset_role")
    affected = []
    for row in manifest.get("runs", []):
        output = _inside(root, row.get("output_dir"))
        started_path = output / "case_started.json"
        result_path = output / "case_result.json"
        if result_path.exists() or not started_path.is_file():
            continue
        started = json.loads(started_path.read_text(encoding="utf-8"))
        if (
            not isinstance(started, dict)
            or started.get("schema_version") != STARTED_SCHEMA
            or started.get("run_id") != row.get("run_id")
            or started.get("dataset_role") != dataset_role
        ):
            raise ValueError(f"invalid started record: {started_path}")
        result = {
            "schema_version": RESULT_SCHEMA,
            "run_id": row["run_id"],
            "dataset_role": dataset_role,
            "status": "interrupted",
            "reason_code": "execution_interrupted",
            "return_code": None,
            "artifacts": [_artifact(root, started_path)],
        }
        _write_json(result_path, result)
        affected.append(row["run_id"])
    return affected


def _validate_result(
    result: dict[str, Any],
    *,
    row: dict[str, Any],
    dataset_role: str,
    root: Path,
    errors: set[str],
    artifacts: list[dict[str, Any]],
) -> None:
    if result.get("schema_version") != RESULT_SCHEMA:
        errors.add("invalid_case_result_schema")
    if result.get("run_id") != row.get("run_id"):
        errors.add("result_run_id_mismatch")
    if result.get("dataset_role") != dataset_role:
        errors.add("result_dataset_role_mismatch")
    records = result.get("artifacts")
    if not isinstance(records, list):
        errors.add("invalid_artifact_records")
        return
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            errors.add("invalid_artifact_record")
            continue
        relative = record["path"]
        if relative in seen:
            errors.add("duplicate_artifact_record")
            continue
        seen.add(relative)
        try:
            path = _inside(root, relative)
        except ValueError:
            errors.add("path_escape")
            continue
        if not path.is_file():
            errors.add("artifact_missing")
            continue
        actual = _artifact(root, path)
        if record["bytes"] != actual["bytes"]:
            errors.add("artifact_size_mismatch")
        if record["sha256"] != actual["sha256"]:
            errors.add("artifact_hash_mismatch")
        artifacts.append(actual)

    if result.get("status") == "successful":
        expected_report = row.get("expected_report")
        role_path = row.get("role_evidence_path")
        if expected_report not in seen:
            errors.add("expected_report_not_recorded")
        try:
            role_file = _inside(root, role_path)
        except ValueError:
            errors.add("path_escape")
            return
        role_record = _read_object(role_file, errors, "role_evidence_invalid")
        if role_record is None:
            return
        if role_record.get("dataset_role") != row.get("expected_child_dataset_role"):
            errors.add("child_dataset_role_mismatch")
        _validate_nested_artifacts(row, root=root, seen=seen, errors=errors)


def _validate_nested_artifacts(
    row: dict[str, Any],
    *,
    root: Path,
    seen: set[str],
    errors: set[str],
) -> None:
    relative = row.get("expected_artifact_manifest")
    if relative is None:
        return
    if relative not in seen:
        errors.add("expected_artifact_manifest_not_recorded")
    try:
        path = _inside(root, relative)
    except ValueError:
        errors.add("nested_artifact_path_escape")
        return
    value = _read_object(path, errors, "nested_artifact_manifest_invalid")
    identity = row.get("expected_artifact_identity")
    if value is None:
        return
    if not isinstance(identity, dict) or set(identity) != {
        "fault_id",
        "condition_variant",
        "dataset_role",
    }:
        errors.add("nested_artifact_manifest_invalid")
        return
    try:
        validate_artifact_manifest(
            value,
            case_root=path.parent,
            expected_fault_id=identity["fault_id"],
            expected_condition_variant=identity["condition_variant"],
            expected_dataset_role=identity["dataset_role"],
        )
    except ArtifactValidationError as error:
        errors.add(f"nested_{error.reason_code}")
    except (OSError, ValueError, KeyError, TypeError):
        errors.add("nested_artifact_manifest_invalid")


def _inside(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("path is required")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path escapes root")
    return candidate


def _read_object(path: Path, errors: set[str], reason: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.add(reason)
        return None
    if not isinstance(value, dict):
        errors.add(reason)
        return None
    return value


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _audit(
    planned: int,
    counts: dict[str, int],
    errors: set[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    base = {
        "planned": planned,
        "not_started": 0,
        "running": 0,
        "successful": 0,
        "failed": 0,
        "interrupted": 0,
    }
    base.update(counts)
    return {
        "schema_version": INTEGRITY_SCHEMA,
        "status": "invalid",
        "dataset_role": "",
        "counts": base,
        "errors": sorted(errors),
        "artifacts": artifacts,
    }
