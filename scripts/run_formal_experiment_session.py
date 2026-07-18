#!/usr/bin/env python3
"""Run a qualified, manifest-driven experiment session."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.protocol.matrix import load_experiment_matrix  # noqa: E402
from experiments.protocol.qualification import (  # noqa: E402
    qualify_experiment_session,
)
from experiments.protocol.session_integrity import (  # noqa: E402
    assess_session_integrity,
    mark_interrupted_runs,
)
from experiments.protocol.session_manifest import (  # noqa: E402
    build_session_manifest,
)


CaseExecutor = Callable[[list[str]], int]


def run_formal_session(
    *,
    matrix_path: Path,
    capability_path: Path,
    selected_case_ids: Sequence[str],
    dataset_role: str,
    session_name: str,
    seed: int,
    output_dir: Path,
    safe_root: Path,
    dry_run: bool,
    resume: bool,
    execute_case: CaseExecutor | None = None,
) -> dict[str, Any]:
    """Plan, execute, or conservatively resume one experiment session."""
    if dry_run and resume:
        raise ValueError("dry-run and resume are mutually exclusive")
    if resume:
        return _resume_session(
            matrix_path=matrix_path,
            capability_path=capability_path,
            selected_case_ids=selected_case_ids,
            dataset_role=dataset_role,
            session_name=session_name,
            seed=seed,
            output_dir=output_dir,
            safe_root=safe_root,
            execute_case=execute_case,
        )
    if output_dir.exists():
        raise ValueError(f"session output already exists: {output_dir}")

    matrix = load_experiment_matrix(matrix_path)
    capability = _read_json(capability_path)
    selected = list(selected_case_ids) or [row["case_id"] for row in matrix["cases"]]
    matrix_hash = _sha256_file(matrix_path)
    capability_hash = _sha256_file(capability_path)
    git_commit, git_status = _git_identity()
    qualification = qualify_experiment_session(
        matrix,
        capability,
        selected_case_ids=selected,
        dataset_role=dataset_role,
        matrix_sha256=matrix_hash,
        capability_sha256=capability_hash,
        git_commit=git_commit,
        git_status=git_status,
    )
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "qualification.json", qualification)
    if qualification["status"] != "allowed":
        summary = {
            "schema_version": "formal-experiment-session-summary/v1",
            "status": "denied",
            "reason_codes": qualification["reason_codes"],
            "dataset_role": dataset_role,
            "development_only": dataset_role in {"development", "pilot"},
            "execution_performed": False,
            "formal_experiment_allowed": False,
            "live_mutation_performed": False,
            "planned_run_count": 0,
        }
        _write_json(output_dir / "summary.json", summary)
        return summary

    manifest = build_session_manifest(
        matrix,
        qualification,
        session_name=session_name,
        dataset_role=dataset_role,
        seed=seed,
        session_root=output_dir,
        repository_root=ROOT,
        safe_root=safe_root,
        matrix_source={"path": str(matrix_path.resolve()), "sha256": matrix_hash},
        capability_source={
            "path": str(capability_path.resolve()),
            "sha256": capability_hash,
        },
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        git_commit=git_commit,
    )
    manifest_path = output_dir / "session_manifest.json"
    _write_json(manifest_path, manifest)
    (output_dir / "session_manifest.sha256").write_text(
        _sha256_file(manifest_path) + "\n", encoding="ascii"
    )
    if dry_run:
        integrity = assess_session_integrity(manifest, output_dir)
        _write_json(output_dir / "integrity.json", integrity)
        summary = {
            "schema_version": "formal-experiment-session-summary/v1",
            "status": "planned",
            "reason_codes": [],
            "dataset_role": dataset_role,
            "development_only": dataset_role in {"development", "pilot"},
            "execution_performed": False,
            "formal_experiment_allowed": False,
            "live_mutation_performed": False,
            "planned_run_count": len(manifest["runs"]),
            "counts": integrity["counts"],
        }
        _write_json(output_dir / "summary.json", summary)
        return summary
    return _execute_and_finish(manifest, output_dir, execute_case)


def _resume_session(
    *,
    matrix_path: Path,
    capability_path: Path,
    selected_case_ids: Sequence[str],
    dataset_role: str,
    session_name: str,
    seed: int,
    output_dir: Path,
    safe_root: Path,
    execute_case: CaseExecutor | None,
) -> dict[str, Any]:
    if not output_dir.is_dir():
        raise ValueError(f"resume session does not exist: {output_dir}")
    manifest_path = output_dir / "session_manifest.json"
    sidecar_path = output_dir / "session_manifest.sha256"
    manifest = _read_json(manifest_path)
    try:
        expected_manifest_hash = sidecar_path.read_text(encoding="ascii").strip()
    except OSError as error:
        raise ValueError("manifest hash sidecar is missing") from error
    if expected_manifest_hash != _sha256_file(manifest_path):
        raise ValueError("manifest hash does not match sidecar")
    if manifest.get("session_root") != str(output_dir.resolve()):
        raise ValueError("resume session root does not match")
    if manifest.get("session_name") != session_name:
        raise ValueError("resume session name does not match")
    if manifest.get("dataset_role") != dataset_role:
        raise ValueError("resume dataset role does not match")
    if manifest.get("seed") != seed:
        raise ValueError("resume seed does not match")
    if manifest.get("safe_root") != str(safe_root.resolve()):
        raise ValueError("resume safe root does not match")
    frozen_cases = manifest.get("selected_case_ids")
    selected = list(selected_case_ids) or list(frozen_cases or [])
    if selected != frozen_cases:
        raise ValueError("resume selected cases do not match")
    if _sha256_file(matrix_path) != manifest["matrix_source"]["sha256"]:
        raise ValueError("resume matrix hash does not match")
    if _sha256_file(capability_path) != manifest["capability_source"]["sha256"]:
        raise ValueError("resume capability hash does not match")
    git_commit, git_status = _git_identity()
    if git_commit != manifest.get("git_commit"):
        raise ValueError("resume git commit does not match")
    if git_status != manifest.get("git_status"):
        raise ValueError("resume git status does not match")
    qualification = _read_json(output_dir / "qualification.json")
    if _canonical_sha256(qualification) != manifest.get("qualification_sha256"):
        raise ValueError("resume qualification hash does not match")

    mark_interrupted_runs(manifest, output_dir)
    return _execute_and_finish(manifest, output_dir, execute_case)


def _execute_and_finish(
    manifest: dict[str, Any],
    output_dir: Path,
    execute_case: CaseExecutor | None,
) -> dict[str, Any]:
    executor = execute_case or _execute_case
    for row in manifest["runs"]:
        case_dir = _inside(output_dir, row["output_dir"])
        started_path = case_dir / "case_started.json"
        result_path = case_dir / "case_result.json"
        if result_path.is_file() or started_path.is_file():
            continue
        case_dir.mkdir(parents=True)
        _write_json(
            started_path,
            {
                "schema_version": "formal-experiment-case-started/v1",
                "run_id": row["run_id"],
                "dataset_role": manifest["dataset_role"],
                "argv": row["argv"],
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            return_code = executor(list(row["argv"]))
        except Exception as error:  # preserve the case and continue the session
            return_code = 1
            executor_error = f"{type(error).__name__}: {error}"
        else:
            executor_error = ""
        result = _case_result(
            manifest,
            row,
            output_dir,
            started_path,
            return_code,
            executor_error,
        )
        _write_json(result_path, result)

    integrity = assess_session_integrity(manifest, output_dir)
    _write_json(output_dir / "integrity.json", integrity)
    complete = integrity["status"] == "complete"
    summary = {
        "schema_version": "formal-experiment-session-summary/v1",
        "status": "completed" if complete else integrity["status"],
        "reason_codes": integrity["errors"],
        "dataset_role": manifest["dataset_role"],
        "development_only": manifest["development_only"],
        "execution_performed": True,
        "formal_experiment_allowed": bool(
            complete and manifest["formal_experiment_allowed"]
        ),
        "live_mutation_performed": False,
        "planned_run_count": len(manifest["runs"]),
        "counts": integrity["counts"],
        "integrity_status": integrity["status"],
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _case_result(
    manifest: dict[str, Any],
    row: dict[str, Any],
    output_dir: Path,
    started_path: Path,
    return_code: int,
    executor_error: str,
) -> dict[str, Any]:
    paths = {started_path}
    report_path = _inside(output_dir, row["expected_report"])
    role_path = _inside(output_dir, row["role_evidence_path"])
    if report_path.is_file():
        paths.add(report_path)
    if role_path.is_file():
        paths.add(role_path)
    status = "failed"
    if executor_error:
        reason = "executor_exception"
    elif return_code != 0:
        reason = "case_command_failed"
    elif not report_path.is_file():
        reason = "expected_report_missing"
    elif _try_read_json(report_path) is None:
        reason = "expected_report_invalid"
    elif not role_path.is_file():
        reason = "role_evidence_missing"
    else:
        role_record = _try_read_json(role_path)
        if role_record is None:
            reason = "role_evidence_invalid"
        elif role_record.get("dataset_role") != row["expected_child_dataset_role"]:
            reason = "child_dataset_role_mismatch"
        else:
            status = "successful"
            reason = ""
    return {
        "schema_version": "formal-experiment-case-result/v1",
        "run_id": row["run_id"],
        "dataset_role": manifest["dataset_role"],
        "status": status,
        "reason_code": reason,
        "return_code": return_code,
        "executor_error": executor_error,
        "artifacts": [
            _artifact(output_dir, path) for path in sorted(paths)
        ],
    }


def _execute_case(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT).returncode


def _git_identity() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, status


def _inside(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError("session path escapes output root")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _try_read_json(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--capability-report", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument(
        "--dataset-role",
        choices=("development", "pilot", "calibration", "test"),
        required=True,
    )
    parser.add_argument("--session-name", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--safe-root",
        type=Path,
        default=Path.home() / ".cache/robotraceopt_build",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    summary = run_formal_session(
        matrix_path=args.matrix,
        capability_path=args.capability_report,
        selected_case_ids=args.case,
        dataset_role=args.dataset_role,
        session_name=args.session_name,
        seed=args.seed,
        output_dir=args.output_dir,
        safe_root=args.safe_root,
        dry_run=args.dry_run,
        resume=args.resume,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] in {"planned", "completed"}:
        return 0
    if summary["status"] == "denied":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())