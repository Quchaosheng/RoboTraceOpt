"""Compile deterministic formal experiment session manifests."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from experiments.protocol.matrix import validate_experiment_matrix
from experiments.protocol.runner_registry import build_case_argv


SESSION_SCHEMA = "formal-experiment-session-manifest/v1"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
HEX = set("0123456789abcdef")


def build_session_manifest(
    matrix: dict[str, Any],
    qualification: dict[str, Any],
    *,
    session_name: str,
    dataset_role: str,
    seed: int,
    session_root: Path,
    repository_root: Path,
    safe_root: Path,
    matrix_source: dict[str, str],
    capability_source: dict[str, str],
    generated_at_utc: str,
    git_commit: str,
) -> dict[str, Any]:
    validated = validate_experiment_matrix(matrix)
    _validate_session_inputs(
        qualification,
        session_name=session_name,
        dataset_role=dataset_role,
        seed=seed,
        matrix_source=matrix_source,
        capability_source=capability_source,
        generated_at_utc=generated_at_utc,
        git_commit=git_commit,
    )
    cases_by_id = {case["case_id"]: case for case in validated["cases"]}
    selected_ids = list(qualification["selected_case_ids"])
    if any(case_id not in cases_by_id for case_id in selected_ids):
        raise ValueError("qualification references a case missing from the matrix")

    root = session_root.resolve()
    repository = repository_root.resolve()
    qualification_path = root / "qualification.json"
    selected_cases = [cases_by_id[case_id] for case_id in selected_ids]
    ordered_rows = _expand_cases(selected_cases, seed)
    runs = []
    position_counts = _initial_position_counts(selected_cases)
    for sequence, row in enumerate(ordered_rows, start=1):
        case = row["case"]
        _validate_case_role(case, dataset_role)
        run_id = f"{session_name}_{case['case_id']}_r{row['repetition_index']:02d}"
        relative_output = Path("cases") / f"{sequence:03d}_{run_id}"
        output = (root / relative_output).resolve()
        if not output.is_relative_to(root):
            raise ValueError("case output path escapes the session root")
        invocation = build_case_argv(
            case,
            run_id=run_id,
            dataset_role=dataset_role,
            output_dir=output,
            repository_root=repository,
            safe_root=safe_root.resolve(),
            qualification_path=qualification_path,
            seed=seed,
        )
        position = str(row["position_index"])
        counts = position_counts[case["case_id"]]
        counts[position] += 1
        run = {
            "sequence_index": sequence,
            "run_id": run_id,
            "case_id": case["case_id"],
            "group_id": case["group_id"],
            "runner_id": case["runner_id"],
            "repetition_index": row["repetition_index"],
            "block_index": row["block_index"],
            "position_index": row["position_index"],
            "requirements": list(case["requirements"]),
            "output_dir": relative_output.as_posix(),
            "argv": invocation["argv"],
            "expected_report": (
                relative_output / invocation["expected_report"]
            ).as_posix(),
            "role_evidence_path": (
                relative_output / invocation["role_evidence_path"]
            ).as_posix(),
            "expected_child_dataset_role": invocation["expected_child_dataset_role"],
        }
        if "expected_artifact_manifest" in invocation:
            run["expected_artifact_manifest"] = (
                relative_output / invocation["expected_artifact_manifest"]
            ).as_posix()
            run["expected_artifact_identity"] = dict(
                invocation["expected_artifact_identity"]
            )
        runs.append(run)

    return {
        "schema_version": SESSION_SCHEMA,
        "session_name": session_name,
        "generated_at_utc": generated_at_utc,
        "dataset_role": dataset_role,
        "development_only": dataset_role in {"development", "pilot"},
        "formal_experiment_allowed": qualification["formal_experiment_allowed"],
        "live_mutation_performed": False,
        "platform_label": qualification["platform_label"],
        "git_commit": git_commit,
        "git_status": qualification.get("git_status", ""),
        "seed": seed,
        "session_root": str(root),
        "safe_root": str(safe_root.resolve()),
        "matrix_source": dict(matrix_source),
        "capability_source": dict(capability_source),
        "qualification_path": "qualification.json",
        "qualification_sha256": _canonical_sha256(qualification),
        "selected_case_ids": selected_ids,
        "planned_run_count": len(runs),
        "position_counts": dict(position_counts),
        "runs": runs,
    }


def _initial_position_counts(
    cases: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    group_sizes: dict[str, int] = defaultdict(int)
    for case in cases:
        if case["runner_id"] == "fault_condition":
            group_sizes[case["group_id"]] += 1
    result = {}
    for case in cases:
        positions = group_sizes.get(case["group_id"], 1)
        result[case["case_id"]] = {
            str(position): 0 for position in range(1, positions + 1)
        }
    return result


def _validate_case_role(case: dict[str, Any], dataset_role: str) -> None:
    if dataset_role not in {"calibration", "test"}:
        return
    if case["runner_id"] != "fault_condition":
        return
    parameters = case["parameters"]
    if parameters["condition_variant"] == "control":
        raise ValueError("case is not allowed for formal dataset role")
    if parameters["fault_id"] == "F5":
        raise ValueError("case is not allowed for formal dataset role")


def _expand_cases(cases: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    fault_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    remaining = []
    for case in cases:
        if case["runner_id"] == "fault_condition":
            fault_groups[case["group_id"]].append(case)
        else:
            remaining.append(case)

    rows = []
    rng = random.Random(seed)
    for group_cases in fault_groups.values():
        repetitions = {case["repetitions"] for case in group_cases}
        if len(repetitions) != 1:
            raise ValueError("balanced fault cases require equal repetitions")
        order = list(group_cases)
        rng.shuffle(order)
        for block_index in range(1, repetitions.pop() + 1):
            offset = (block_index - 1) % len(order)
            rotated = order[offset:] + order[:offset]
            for position_index, case in enumerate(rotated, start=1):
                rows.append(
                    {
                        "case": case,
                        "repetition_index": block_index,
                        "block_index": block_index,
                        "position_index": position_index,
                    }
                )
    for case in remaining:
        for repetition in range(1, case["repetitions"] + 1):
            rows.append(
                {
                    "case": case,
                    "repetition_index": repetition,
                    "block_index": repetition,
                    "position_index": 1,
                }
            )
    return rows


def _validate_session_inputs(
    qualification: dict[str, Any],
    *,
    session_name: str,
    dataset_role: str,
    seed: int,
    matrix_source: dict[str, str],
    capability_source: dict[str, str],
    generated_at_utc: str,
    git_commit: str,
) -> None:
    if not isinstance(session_name, str) or not IDENTIFIER.fullmatch(session_name):
        raise ValueError("invalid session name")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not isinstance(generated_at_utc, str) or not generated_at_utc:
        raise ValueError("generated_at_utc is required")
    if not _lower_hex(git_commit, (40, 64)):
        raise ValueError("invalid git commit")
    for field, source in (
        ("matrix", matrix_source),
        ("capability", capability_source),
    ):
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            raise ValueError(f"invalid {field} source")
        if not isinstance(source["path"], str) or not source["path"]:
            raise ValueError(f"invalid {field} source path")
        if not _lower_hex(source["sha256"], (64,)):
            raise ValueError(f"invalid {field} source sha256")
    if (
        qualification.get("schema_version") != "formal-experiment-qualification/v1"
        or qualification.get("status") != "allowed"
    ):
        raise ValueError("session requires an allowed qualification")
    if qualification.get("dataset_role") != dataset_role:
        raise ValueError("qualification dataset role does not match")
    if qualification.get("matrix_sha256") != matrix_source["sha256"]:
        raise ValueError("qualification matrix hash does not match")
    if qualification.get("capability_sha256") != capability_source["sha256"]:
        raise ValueError("qualification capability hash does not match")
    if qualification.get("git_commit") != git_commit:
        raise ValueError("qualification git commit does not match")
    selected = qualification.get("selected_case_ids")
    if not isinstance(selected, list) or not selected:
        raise ValueError("qualification selected cases are missing")


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _lower_hex(value: Any, lengths: tuple[int, ...]) -> bool:
    return (
        isinstance(value, str)
        and len(value) in lengths
        and all(character in HEX for character in value)
    )
