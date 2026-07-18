"""Run a role-qualified balanced repeated optimization campaign."""

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

from optimizer.experiments.campaign_schedule import (  # noqa: E402
    build_repeated_schedule,
    validate_campaign_parameters,
)
from optimizer.integration.closed_loop import (  # noqa: E402
    build_execution_schedule,
    validate_baseline_profile,
)
from optimizer.integration.diagnosis_gate import plan_from_diagnosis  # noqa: E402
from optimizer.integration.runtime_profiles import runtime_profile  # noqa: E402
from optimizer.objectives.runtime_objective import runtime_objective  # noqa: E402
from optimizer.search.trial_planner import STRATEGIES  # noqa: E402
from optimizer.validation.paired_bootstrap import (  # noqa: E402
    evaluate_repeated_candidates,
)
from scripts.run_closed_loop_optimization import build_trial_invocation  # noqa: E402


TrialExecutor = Callable[[list[str]], int]


def run_repeated_campaign(
    diagnosis_report: dict[str, Any],
    baseline_profile: dict[str, Any],
    *,
    campaign_name: str,
    strategy: str,
    budget: int,
    seed: int,
    repetitions: int,
    duration_seconds: int,
    minimum_confidence: float,
    minimum_completeness: float,
    quantile: str | None,
    minimum_improvement_ratio: float,
    minimum_complete_trace_rate_delta: float,
    confidence_level: float,
    bootstrap_resamples: int,
    output_dir: Path,
    safe_root: Path,
    execute_trial: TrialExecutor | None = None,
    diagnosis_source: Path | None = None,
    baseline_source: Path | None = None,
    dataset_role: str = "pilot",
    qualification_report: dict[str, Any] | None = None,
    qualification_source: Path | None = None,
) -> dict[str, Any]:
    evidence = _evidence_fields(dataset_role, qualification_report)
    if output_dir.exists():
        raise ValueError(f"campaign output already exists: {output_dir}")
    validate_campaign_parameters(
        repetitions=repetitions, seed=seed, campaign_name=campaign_name
    )
    _validate_parameters(
        duration_seconds=duration_seconds,
        confidence_level=confidence_level,
        bootstrap_resamples=bootstrap_resamples,
        minimum_improvement_ratio=minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=minimum_complete_trace_rate_delta,
    )
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
            evidence,
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
            evidence,
        )

    baseline_config = validate_baseline_profile(baseline_profile, cause_id)
    execution_schedule = build_execution_schedule(gate, baseline_config)
    schedule = build_repeated_schedule(
        execution_schedule,
        repetitions=repetitions,
        seed=seed,
        campaign_name=campaign_name,
    )
    selected_quantile = quantile or profile["quantile"]
    manifest = {
        "schema_version": "optimization-repeated-campaign-manifest/v1",
        **evidence,
        "git_commit": _git_commit(),
        "cause_id": cause_id,
        "runtime_profile": profile,
        "baseline_config": baseline_config,
        "schedule": schedule,
        "parameters": {
            "strategy": strategy,
            "budget": budget,
            "seed": seed,
            "repetitions": repetitions,
            "duration_seconds": duration_seconds,
            "minimum_confidence": minimum_confidence,
            "minimum_completeness": minimum_completeness,
            "quantile": selected_quantile,
            "minimum_improvement_ratio": minimum_improvement_ratio,
            "minimum_complete_trace_rate_delta": (
                minimum_complete_trace_rate_delta
            ),
            "confidence_level": confidence_level,
            "bootstrap_resamples": bootstrap_resamples,
        },
        "inputs": {
            "diagnosis": _input_record(diagnosis_report, diagnosis_source),
            "baseline": _input_record(baseline_profile, baseline_source),
        },
    }
    if qualification_report is not None:
        manifest["inputs"]['qualification'] = _input_record(
            qualification_report, qualification_source
        )
    manifest_path = output_dir / "campaign_manifest.json"
    _write_json(manifest_path, manifest)

    trial_records: list[dict[str, Any]] = []
    for row in schedule["trials"]:
        block_index = int(row["block_index"])
        position_index = int(row["position_index"])
        identifier = str(row["config_id"])
        config = dict(row["candidate_config"])
        trial_dir = (
            output_dir
            / "trials"
            / f"block_{block_index:02d}"
            / f"position_{position_index:02d}_{identifier}"
        )
        command = build_trial_invocation(
            trial_id=str(row["trial_id"]),
            strategy=strategy,
            seed=seed,
            cause_id=cause_id,
            candidate_config=config,
            duration_seconds=duration_seconds,
            output_dir=trial_dir,
            safe_root=safe_root,
        )
        result = {
            "schema_version": "optimization-repeated-trial-result/v1",
            **evidence,
            **dict(row),
            "command": command,
        }
        return_code = executor(command)
        if return_code != 0:
            result.update(
                {
                    "status": "failed",
                    "reason_code": "trial_failed",
                    "return_code": return_code,
                }
            )
        else:
            report_path = trial_dir / "trial_report.json"
            try:
                report = _read_json(report_path)
                if report.get("candidate_config") != config:
                    raise CandidateConfigMismatch
                objective = runtime_objective(
                    report,
                    metric=profile["metric"],
                    quantile=selected_quantile,
                )
            except CandidateConfigMismatch:
                result.update(
                    {
                        "status": "invalid",
                        "reason_code": "trial_report_config_mismatch",
                        "return_code": return_code,
                    }
                )
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                result.update(
                    {
                        "status": "invalid",
                        "reason_code": "trial_report_invalid",
                        "return_code": return_code,
                    }
                )
            else:
                result.update(
                    {
                        "status": "succeeded",
                        "reason_code": "",
                        "return_code": return_code,
                        "objective_value_ns": objective["objective_value_ns"],
                        "complete_trace_rate": objective["complete_trace_rate"],
                        "trial_report": str(report_path),
                        "trial_report_sha256": _sha256_file(report_path),
                    }
                )
        trial_dir.mkdir(parents=True, exist_ok=True)
        result_path = trial_dir / "trial_result.json"
        result["trial_result"] = str(result_path)
        _write_json(result_path, result)
        trial_records.append(result)

    validations = evaluate_repeated_candidates(
        schedule,
        trial_records,
        minimum_improvement_ratio=minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=minimum_complete_trace_rate_delta,
        confidence_level=confidence_level,
        bootstrap_resamples=bootstrap_resamples,
        seed=seed,
    )
    for validation in validations:
        validation.update(evidence)
        identifier = str(validation["config_id"])
        validation["inputs"] = [
            {
                "block_index": record["block_index"],
                "config_id": record["config_id"],
                "status": record["status"],
                "trial_result": record["trial_result"],
                "trial_report": record.get("trial_report", ""),
                "trial_report_sha256": record.get("trial_report_sha256", ""),
            }
            for record in trial_records
            if record["role"] == "baseline" or record["config_id"] == identifier
        ]
        validation_path = output_dir / "candidate_validations" / f"{identifier}.json"
        validation["validation_path"] = str(validation_path)
        _write_json(validation_path, validation)

    accepted = [row for row in validations if row["decision"] == "accept"]
    if accepted:
        selected = min(
            accepted,
            key=lambda row: (
                -float(row["improvement_ratio"]["lower"]),
                -float(row["improvement_ratio"]["estimate"]),
                int(row["config_index"]),
            ),
        )
        action = "apply_candidate"
        reason_code = ""
        selected_config = dict(selected["candidate_config"])
        selected_config_id = selected["config_id"]
    else:
        action = "restore_baseline"
        reason_code = "no_statistically_supported_candidate"
        selected_config = dict(baseline_config)
        selected_config_id = None
    decision = {
        "schema_version": "optimization-repeated-campaign-decision/v1",
        **evidence,
        "cause_id": cause_id,
        "action": action,
        "reason_code": reason_code,
        "baseline_config": baseline_config,
        "selected_config": selected_config,
        "selected_config_id": selected_config_id,
    }
    decision_path = output_dir / "decision.json"
    _write_json(decision_path, decision)

    succeeded_count = sum(row["status"] == "succeeded" for row in trial_records)
    failed_count = sum(row["status"] == "failed" for row in trial_records)
    invalid_count = len(trial_records) - succeeded_count - failed_count
    return _finish_summary(
        output_dir,
        {
            "status": "completed",
            "reason_code": reason_code,
            "cause_id": cause_id,
            "action": action,
            "selected_config": selected_config,
            "gate": str(gate_path),
            "manifest": str(manifest_path),
            "decision": str(decision_path),
            "trial_invocation_count": len(trial_records),
            "successful_trial_count": succeeded_count,
            "failed_trial_count": failed_count,
            "invalid_trial_count": invalid_count,
            "accepted_candidate_count": len(accepted),
            "rejected_candidate_count": len(validations) - len(accepted),
        },
        evidence,
    )


class CandidateConfigMismatch(Exception):
    """Keep report/config mismatch distinct from malformed reports."""


def _validate_parameters(
    *,
    duration_seconds: int,
    confidence_level: float,
    bootstrap_resamples: int,
    minimum_improvement_ratio: float,
    minimum_complete_trace_rate_delta: float,
) -> None:
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or duration_seconds < 1:
        raise ValueError("duration-seconds must be positive")
    if isinstance(confidence_level, bool) or not isinstance(confidence_level, (int, float)) or not 0 < confidence_level < 1:
        raise ValueError("confidence-level must be between zero and one")
    if isinstance(bootstrap_resamples, bool) or not isinstance(bootstrap_resamples, int) or bootstrap_resamples < 100:
        raise ValueError("bootstrap-resamples must be at least 100")
    if isinstance(minimum_improvement_ratio, bool) or not isinstance(minimum_improvement_ratio, (int, float)) or not 0 <= minimum_improvement_ratio <= 1:
        raise ValueError("minimum-improvement-ratio must be between zero and one")
    if isinstance(minimum_complete_trace_rate_delta, bool) or not isinstance(minimum_complete_trace_rate_delta, (int, float)) or not -1 <= minimum_complete_trace_rate_delta <= 0:
        raise ValueError("minimum-complete-trace-rate-delta must be between minus one and zero")


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


def _evidence_fields(
    dataset_role: str, qualification: dict[str, Any] | None
) -> dict[str, Any]:
    roles = {"development", "pilot", "calibration", "test"}
    if dataset_role not in roles:
        raise ValueError("unsupported dataset role")
    if dataset_role in {"calibration", "test"}:
        if (
            qualification is None
            or qualification.get("schema_version")
            != "formal-experiment-qualification/v1"
        ):
            raise ValueError(
                "qualified campaign role requires a qualification report"
            )
        if (
            qualification.get("status") != "allowed"
            or qualification.get("dataset_role") != dataset_role
        ):
            raise ValueError("qualification report does not allow campaign role")
        for field in ("matrix_sha256", "capability_sha256"):
            value = qualification.get(field)
            if not _is_lower_hex(value, 64):
                raise ValueError(f"qualification report has invalid {field}")
        if qualification.get("git_commit") != _git_commit():
            raise ValueError("qualification report git commit does not match")
        if qualification.get("git_status"):
            raise ValueError("qualification report records a dirty worktree")
        if dataset_role == "test" and (
            qualification.get("formal_experiment_allowed") is not True
        ):
            raise ValueError("test campaign is not formally qualified")
    return {
        "dataset_role": dataset_role,
        "development_only": dataset_role in {"development", "pilot"},
        "formal_optimization_allowed": dataset_role == "test",
        "live_mutation_performed": False,
    }


def _is_lower_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )

def _finish_summary(
    output_dir: Path,
    fields: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "schema_version": "optimization-repeated-campaign-summary/v1",
        **evidence,
        **fields,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis-report", type=Path, required=True)
    parser.add_argument("--baseline-profile", type=Path, required=True)
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--minimum-confidence", type=float, required=True)
    parser.add_argument("--minimum-completeness", type=float, default=1.0)
    parser.add_argument("--quantile")
    parser.add_argument("--minimum-improvement-ratio", type=float, default=0.0)
    parser.add_argument(
        "--minimum-complete-trace-rate-delta", type=float, default=0.0
    )
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--bootstrap-resamples", type=int, default=10000)
    parser.add_argument(
        "--dataset-role",
        choices=("development", "pilot", "calibration", "test"),
        default="pilot",
    )
    parser.add_argument("--qualification-report", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--safe-root",
        type=Path,
        default=Path.home() / ".cache" / "robotraceopt_build",
    )
    args = parser.parse_args()
    summary = run_repeated_campaign(
        _read_json(args.diagnosis_report),
        _read_json(args.baseline_profile),
        campaign_name=args.campaign_name,
        strategy=args.strategy,
        budget=args.budget,
        seed=args.seed,
        repetitions=args.repetitions,
        duration_seconds=args.duration_seconds,
        minimum_confidence=args.minimum_confidence,
        minimum_completeness=args.minimum_completeness,
        quantile=args.quantile,
        minimum_improvement_ratio=args.minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=args.minimum_complete_trace_rate_delta,
        confidence_level=args.confidence_level,
        bootstrap_resamples=args.bootstrap_resamples,
        output_dir=args.output_dir,
        safe_root=args.safe_root,
        diagnosis_source=args.diagnosis_report,
        baseline_source=args.baseline_profile,
        dataset_role=args.dataset_role,
        qualification_report=(
            _read_json(args.qualification_report)
            if args.qualification_report is not None
            else None
        ),
        qualification_source=args.qualification_report,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] == "completed":
        return 0
    if summary["status"] == "denied":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
