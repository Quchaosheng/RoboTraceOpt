"""Map validated experiment cases to existing runner argument lists."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from experiments.fault_injection.registry import load_fault_catalog


ROLE_MAP = {
    "development": "development",
    "pilot": "development",
    "calibration": "calibration",
    "test": "test",
}


def build_case_argv(
    case: dict[str, Any],
    *,
    run_id: str,
    dataset_role: str,
    output_dir: Path,
    repository_root: Path,
    safe_root: Path,
    qualification_path: Path,
    seed: int,
) -> dict[str, Any]:
    """Return argv, terminal report, and role-evidence contract."""
    if dataset_role not in ROLE_MAP:
        raise ValueError("unsupported dataset role")
    runner_id = case.get("runner_id")
    if runner_id == "fault_condition":
        return _fault_invocation(
            case,
            run_id=run_id,
            dataset_role=dataset_role,
            output_dir=output_dir,
            repository_root=repository_root,
            safe_root=safe_root,
        )
    if runner_id == "repeated_optimization":
        return _optimization_invocation(
            case,
            run_id=run_id,
            dataset_role=dataset_role,
            output_dir=output_dir,
            repository_root=repository_root,
            safe_root=safe_root,
            qualification_path=qualification_path,
            seed=seed,
        )
    raise ValueError(f"unsupported runner_id: {runner_id}")


def _fault_invocation(
    case: dict[str, Any],
    *,
    run_id: str,
    dataset_role: str,
    output_dir: Path,
    repository_root: Path,
    safe_root: Path,
) -> dict[str, Any]:
    parameters = case["parameters"]
    fault_id = parameters["fault_id"]
    catalog = load_fault_catalog(repository_root / "experiments/fault_injection/fault_catalog.json")
    if fault_id not in catalog:
        raise ValueError(f"fault is not in the catalog: {fault_id}")
    child_role = ROLE_MAP[dataset_role]
    argv = [
        sys.executable,
        str(repository_root / "scripts/run_fault_condition.py"),
        "--fault-id",
        fault_id,
        "--dataset-role",
        child_role,
        "--session-id",
        run_id,
        "--condition-id",
        run_id,
        "--condition-variant",
        parameters["condition_variant"],
        "--output-dir",
        str(output_dir),
        "--duration-seconds",
        str(parameters["duration_seconds"]),
        "--safe-root",
        str(safe_root),
    ]
    for capability in catalog[fault_id].required_capabilities:
        argv.extend(["--capability", capability])
    argv.append("--execute")
    return {
        "argv": argv,
        "expected_report": "summary.json",
        "role_evidence_path": "run_manifest.json",
        "expected_child_dataset_role": child_role,
        "expected_artifact_manifest": "artifact_manifest.json",
        "expected_artifact_identity": {
            "fault_id": fault_id,
            "condition_variant": parameters["condition_variant"],
            "dataset_role": child_role,
        },
    }


def _optimization_invocation(
    case: dict[str, Any],
    *,
    run_id: str,
    dataset_role: str,
    output_dir: Path,
    repository_root: Path,
    safe_root: Path,
    qualification_path: Path,
    seed: int,
) -> dict[str, Any]:
    parameters = case["parameters"]
    diagnosis = _repository_file(repository_root, parameters["diagnosis_report"])
    baseline = _repository_file(repository_root, parameters["baseline_profile"])
    argv = [
        sys.executable,
        str(repository_root / "scripts/run_repeated_optimization_campaign.py"),
        "--diagnosis-report",
        str(diagnosis),
        "--baseline-profile",
        str(baseline),
        "--campaign-name",
        run_id,
        "--strategy",
        parameters["strategy"],
        "--budget",
        str(parameters["budget"]),
        "--seed",
        str(seed),
        "--repetitions",
        str(parameters["campaign_repetitions"]),
        "--duration-seconds",
        str(parameters["duration_seconds"]),
        "--minimum-confidence",
        str(parameters["minimum_confidence"]),
        "--minimum-completeness",
        str(parameters["minimum_completeness"]),
        "--minimum-improvement-ratio",
        str(parameters["minimum_improvement_ratio"]),
        "--minimum-complete-trace-rate-delta",
        str(parameters["minimum_complete_trace_rate_delta"]),
        "--confidence-level",
        str(parameters["confidence_level"]),
        "--bootstrap-resamples",
        str(parameters["bootstrap_resamples"]),
        "--dataset-role",
        dataset_role,
        "--output-dir",
        str(output_dir),
        "--safe-root",
        str(safe_root),
    ]
    if dataset_role in {"calibration", "test"}:
        argv.extend(["--qualification-report", str(qualification_path)])
    return {
        "argv": argv,
        "expected_report": "summary.json",
        "role_evidence_path": "summary.json",
        "expected_child_dataset_role": dataset_role,
    }


def _repository_file(repository_root: Path, relative: str) -> Path:
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("repository input path escapes the repository")
    if not path.is_file():
        raise ValueError(f"repository input does not exist: {relative}")
    return path
