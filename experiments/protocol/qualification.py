"""Qualify experiment cases against one immutable platform report."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from experiments.protocol.matrix import validate_experiment_matrix


QUALIFICATION_SCHEMA = "formal-experiment-qualification/v1"
DATASET_ROLES = {"development", "pilot", "calibration", "test"}
FORMAL_ROLES = {"calibration", "test"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def qualify_experiment_session(
    matrix: dict[str, Any],
    capability_report: dict[str, Any],
    *,
    selected_case_ids: Sequence[str],
    dataset_role: str,
    matrix_sha256: str,
    capability_sha256: str,
    git_commit: str,
    git_status: str,
) -> dict[str, Any]:
    """Return formal-experiment-qualification/v1 without executing commands."""
    validated = validate_experiment_matrix(matrix)
    if dataset_role not in DATASET_ROLES:
        raise ValueError("unsupported dataset role")
    _digest(matrix_sha256, "matrix_sha256")
    _digest(capability_sha256, "capability_sha256")
    if not isinstance(git_commit, str) or not GIT_COMMIT.fullmatch(git_commit):
        raise ValueError("invalid git_commit")
    if not isinstance(git_status, str):
        raise ValueError("git_status must be a string")
    if (
        not isinstance(selected_case_ids, Sequence)
        or isinstance(selected_case_ids, (str, bytes))
        or not selected_case_ids
    ):
        raise ValueError("selected cases must be a non-empty sequence")
    selected = list(selected_case_ids)
    if any(not isinstance(item, str) for item in selected):
        raise ValueError("selected cases must contain strings")
    if len(selected) != len(set(selected)):
        raise ValueError("duplicate selected case")

    cases_by_id = {case["case_id"]: case for case in validated["cases"]}
    unknown = [case_id for case_id in selected if case_id not in cases_by_id]
    if unknown:
        raise ValueError(f"unknown selected cases: {unknown}")
    _validate_capability_report(capability_report)

    host = capability_report["host"]
    platform_label = capability_report["platform_label"]
    readiness = capability_report["readiness"]
    reasons: set[str] = set()
    if str(host["system"]).lower() != "linux":
        reasons.add("linux_required")
    if host["is_wsl"] and dataset_role in FORMAL_ROLES:
        reasons.add("wsl_formal_role_forbidden")
    if dataset_role in FORMAL_ROLES and git_status:
        reasons.add("dirty_formal_worktree")
    if "x5" in platform_label.lower() and str(host["machine"]).lower() not in {
        "aarch64",
        "arm64",
    }:
        reasons.add("platform_label_architecture_mismatch")

    provenance = capability_report.get("provenance", {})
    report_commit = provenance.get("git_commit")
    if report_commit and report_commit != git_commit:
        reasons.add("capability_git_commit_mismatch")
    if dataset_role in FORMAL_ROLES and provenance.get("git_status"):
        reasons.add("capability_report_from_dirty_worktree")

    case_rows = []
    for case_id in selected:
        case = cases_by_id[case_id]
        missing = sorted(
            requirement
            for requirement in case["requirements"]
            if readiness.get(requirement, {}).get("status") != "ready"
        )
        if missing:
            reasons.add("capability_not_ready")
        case_rows.append(
            {
                "case_id": case_id,
                "requirements": list(case["requirements"]),
                "missing_requirements": missing,
                "status": "blocked" if missing else "ready",
            }
        )

    status = "allowed" if not reasons else "denied"
    return {
        "schema_version": QUALIFICATION_SCHEMA,
        "status": status,
        "reason_codes": sorted(reasons),
        "dataset_role": dataset_role,
        "development_only": dataset_role in {"development", "pilot"},
        "formal_experiment_allowed": status == "allowed"
        and dataset_role == "test",
        "platform_label": platform_label,
        "host": {
            "hostname": host["hostname"],
            "system": host["system"],
            "machine": host["machine"],
            "kernel": host["kernel"],
            "is_wsl": host["is_wsl"],
        },
        "matrix_sha256": matrix_sha256,
        "capability_sha256": capability_sha256,
        "git_commit": git_commit,
        "git_status": git_status,
        "selected_case_ids": selected,
        "cases": case_rows,
    }


def _validate_capability_report(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported capability report schema")
    if not isinstance(value.get("platform_label"), str) or not value["platform_label"]:
        raise ValueError("capability report requires platform_label")
    host = value.get("host")
    required_host = {"hostname", "system", "machine", "kernel", "is_wsl"}
    if not isinstance(host, dict) or not required_host <= set(host):
        raise ValueError("capability report host is incomplete")
    if not isinstance(host["is_wsl"], bool):
        raise ValueError("capability report is_wsl must be boolean")
    if not isinstance(value.get("readiness"), dict):
        raise ValueError("capability report readiness must be an object")


def _digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"invalid {field}")
