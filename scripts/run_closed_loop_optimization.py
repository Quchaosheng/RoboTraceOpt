"""Run one development-only diagnosis-guided optimization closed loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimizer.integration.closed_loop import (  # noqa: E402
    build_execution_schedule,
    evaluate_candidate,
    select_closed_loop_decision,
    validate_baseline_profile,
)
from optimizer.integration.diagnosis_gate import plan_from_diagnosis  # noqa: E402
from optimizer.integration.runtime_profiles import (  # noqa: E402
    candidate_cli_arguments,
    runtime_profile,
)
from optimizer.search.trial_planner import STRATEGIES  # noqa: E402


TrialExecutor = Callable[[list[str]], int]


def build_trial_invocation(
    *,
    trial_id: str,
    strategy: str,
    seed: int,
    cause_id: str,
    candidate_config: dict[str, object],
    duration_seconds: int,
    output_dir: Path,
    safe_root: Path,
    dataset_role: str = "development",
    qualification_path: Path | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_optimization_trial.py"),
        "--trial-id",
        trial_id,
        "--strategy",
        strategy,
        "--seed",
        str(seed),
        "--dataset-role",
        dataset_role,
        *candidate_cli_arguments(cause_id, candidate_config),
        "--duration-seconds",
        str(duration_seconds),
        "--output-dir",
        str(output_dir),
        "--safe-root",
        str(safe_root),
    ]
    if dataset_role in {"calibration", "test"}:
        if qualification_path is None:
            raise ValueError("qualified trial requires qualification_path")
        command.extend(["--qualification-report", str(qualification_path)])
    return command


def run_closed_loop(
    diagnosis_report: dict[str, Any],
    baseline_profile: dict[str, Any],
    *,
    strategy: str,
    budget: int,
    seed: int,
    duration_seconds: int,
    minimum_confidence: float,
    minimum_completeness: float,
    quantile: str | None,
    minimum_improvement_ratio: float,
    minimum_complete_trace_rate_delta: float,
    output_dir: Path,
    safe_root: Path,
    execute_trial: TrialExecutor | None = None,
    diagnosis_source: Path | None = None,
    baseline_source: Path | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        raise ValueError(f"closed-loop output already exists: {output_dir}")
    if duration_seconds < 1:
        raise ValueError("duration-seconds must be positive")
    output_dir.mkdir(parents=True)
    executor = execute_trial or _execute_trial

    gate = plan_from_diagnosis(
        diagnosis_report,
        strategy=strategy,
        budget=budget,
        seed=seed,
        minimum_confidence=minimum_confidence,
        minimum_completeness=minimum_completeness,
    )
    gate_path = output_dir / "gate.json"
    _write_json(gate_path, gate)
    if gate["decision"] != "allow":
        return _finish_summary(
            output_dir,
            {
                "status": "denied",
                "reason_code": gate["reason_code"],
                "cause_id": gate.get("cause_id"),
                "gate": str(gate_path),
                "trial_invocation_count": 0,
            },
        )

    cause_id = str(gate["cause_id"])
    try:
        profile = runtime_profile(cause_id)
    except ValueError:
        return _finish_summary(
            output_dir,
            {
                "status": "denied",
                "reason_code": "unsupported_runtime_action",
                "cause_id": cause_id,
                "gate": str(gate_path),
                "trial_invocation_count": 0,
            },
        )

    baseline_config = validate_baseline_profile(baseline_profile, cause_id)
    schedule = build_execution_schedule(gate, baseline_config)
    selected_quantile = quantile or profile["quantile"]
    manifest = {
        "schema_version": "optimization-closed-loop-manifest/v1",
        "development_only": True,
        "formal_optimization_allowed": False,
        "git_commit": _git_commit(),
        "cause_id": cause_id,
        "runtime_profile": profile,
        "baseline_config": baseline_config,
        "schedule": schedule,
        "parameters": {
            "strategy": strategy,
            "budget": budget,
            "seed": seed,
            "duration_seconds": duration_seconds,
            "minimum_confidence": minimum_confidence,
            "minimum_completeness": minimum_completeness,
            "quantile": selected_quantile,
            "minimum_improvement_ratio": minimum_improvement_ratio,
            "minimum_complete_trace_rate_delta": (minimum_complete_trace_rate_delta),
        },
        "inputs": {
            "diagnosis": _input_record(diagnosis_report, diagnosis_source),
            "baseline": _input_record(baseline_profile, baseline_source),
        },
    }
    manifest_path = output_dir / "closed_loop_manifest.json"
    _write_json(manifest_path, manifest)

    baseline_dir = output_dir / "baseline"
    baseline_command = build_trial_invocation(
        trial_id=f"{output_dir.name}_baseline",
        strategy=strategy,
        seed=seed,
        cause_id=cause_id,
        candidate_config=baseline_config,
        duration_seconds=duration_seconds,
        output_dir=baseline_dir,
        safe_root=safe_root,
    )
    if executor(baseline_command) != 0:
        return _finish_summary(
            output_dir,
            {
                "status": "failed",
                "reason_code": "baseline_trial_failed",
                "cause_id": cause_id,
                "gate": str(gate_path),
                "manifest": str(manifest_path),
                "trial_invocation_count": 1,
            },
        )
    try:
        baseline_report = _read_json(baseline_dir / "trial_report.json")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return _finish_summary(
            output_dir,
            {
                "status": "failed",
                "reason_code": "baseline_report_invalid",
                "cause_id": cause_id,
                "gate": str(gate_path),
                "manifest": str(manifest_path),
                "trial_invocation_count": 1,
            },
        )

    candidate_results: list[dict[str, Any]] = []
    invocation_count = 1
    for row in schedule["trials"]:
        if row["status"] != "scheduled":
            candidate_results.append(dict(row))
            continue
        trial_index = int(row["trial_index"])
        candidate_config = dict(row["candidate_config"])
        trial_dir = output_dir / "candidates" / f"trial_{trial_index:02d}"
        command = build_trial_invocation(
            trial_id=f"{output_dir.name}_trial_{trial_index:02d}",
            strategy=strategy,
            seed=seed,
            cause_id=cause_id,
            candidate_config=candidate_config,
            duration_seconds=duration_seconds,
            output_dir=trial_dir,
            safe_root=safe_root,
        )
        invocation_count += 1
        if executor(command) != 0:
            candidate_results.append(
                {
                    **dict(row),
                    "status": "failed",
                    "reason_code": "candidate_trial_failed",
                }
            )
            continue
        report_path = trial_dir / "trial_report.json"
        try:
            candidate_report = _read_json(report_path)
            evaluated = evaluate_candidate(
                baseline_report,
                candidate_report,
                cause_id=cause_id,
                trial_index=trial_index,
                candidate_config=candidate_config,
                quantile=selected_quantile,
                minimum_improvement_ratio=minimum_improvement_ratio,
                minimum_complete_trace_rate_delta=(minimum_complete_trace_rate_delta),
            )
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            candidate_results.append(
                {
                    **dict(row),
                    "status": "failed",
                    "reason_code": "candidate_report_invalid",
                }
            )
            continue
        validation = dict(evaluated["validation"])
        validation["inputs"] = {
            "baseline_report": str(baseline_dir / "trial_report.json"),
            "baseline_report_sha256": _sha256_file(baseline_dir / "trial_report.json"),
            "candidate_report": str(report_path),
            "candidate_report_sha256": _sha256_file(report_path),
        }
        validation_path = output_dir / "validations" / f"trial_{trial_index:02d}.json"
        _write_json(validation_path, validation)
        evaluated["validation"] = validation
        evaluated["trial_report"] = str(report_path)
        evaluated["validation_path"] = str(validation_path)
        candidate_results.append(evaluated)

    decision = select_closed_loop_decision(cause_id, baseline_config, candidate_results)
    decision_path = output_dir / "decision.json"
    _write_json(decision_path, decision)
    validated_count = sum(row.get("status") == "validated" for row in candidate_results)
    failed_count = sum(row.get("status") == "failed" for row in candidate_results)
    skipped_count = len(candidate_results) - validated_count - failed_count
    return _finish_summary(
        output_dir,
        {
            "status": "completed",
            "reason_code": decision["reason_code"],
            "cause_id": cause_id,
            "action": decision["action"],
            "selected_config": decision["selected_config"],
            "gate": str(gate_path),
            "manifest": str(manifest_path),
            "baseline_report": str(baseline_dir / "trial_report.json"),
            "decision": str(decision_path),
            "trial_invocation_count": invocation_count,
            "validated_candidate_count": validated_count,
            "failed_candidate_count": failed_count,
            "skipped_candidate_count": skipped_count,
            "candidate_results": candidate_results,
        },
    )


def _execute_trial(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT).returncode


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_record(value: dict[str, Any], source: Path | None) -> dict[str, str]:
    if source is not None:
        return {"path": str(source), "sha256": _sha256_file(source)}
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return {"path": "", "sha256": hashlib.sha256(payload).hexdigest()}


def _finish_summary(output_dir: Path, fields: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "schema_version": "optimization-closed-loop-summary/v1",
        "development_only": True,
        "formal_optimization_allowed": False,
        **fields,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis-report", type=Path, required=True)
    parser.add_argument("--baseline-profile", type=Path, required=True)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--minimum-confidence", type=float, required=True)
    parser.add_argument("--minimum-completeness", type=float, default=1.0)
    parser.add_argument("--quantile")
    parser.add_argument("--minimum-improvement-ratio", type=float, default=0.0)
    parser.add_argument("--minimum-complete-trace-rate-delta", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--safe-root",
        type=Path,
        default=Path.home() / ".cache" / "robotraceopt_build",
    )
    args = parser.parse_args()
    summary = run_closed_loop(
        _read_json(args.diagnosis_report),
        _read_json(args.baseline_profile),
        strategy=args.strategy,
        budget=args.budget,
        seed=args.seed,
        duration_seconds=args.duration_seconds,
        minimum_confidence=args.minimum_confidence,
        minimum_completeness=args.minimum_completeness,
        quantile=args.quantile,
        minimum_improvement_ratio=args.minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=(args.minimum_complete_trace_rate_delta),
        output_dir=args.output_dir,
        safe_root=args.safe_root,
        diagnosis_source=args.diagnosis_report,
        baseline_source=args.baseline_profile,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] == "completed":
        return 0
    if summary["status"] == "denied":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
