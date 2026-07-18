"""Validate an optimization candidate against a frozen baseline objective."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from optimizer.objectives.runtime_objective import runtime_objective


def validate_reports(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    metric: str,
    quantile: str,
    minimum_improvement_ratio: float = 0.0,
    minimum_complete_trace_rate_delta: float = 0.0,
    formal: bool = False,
) -> dict[str, Any]:
    baseline = runtime_objective(baseline_report, metric=metric, quantile=quantile)
    candidate = runtime_objective(candidate_report, metric=metric, quantile=quantile)
    result = validate_candidate(
        baseline,
        candidate,
        minimum_improvement_ratio=minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=minimum_complete_trace_rate_delta,
        formal=formal,
    )
    result["baseline_objective"] = baseline
    result["candidate_objective"] = candidate
    return result


def validate_candidate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    minimum_improvement_ratio: float = 0.0,
    minimum_complete_trace_rate_delta: float = 0.0,
    formal: bool = False,
) -> dict[str, Any]:
    _validate_objective(baseline, "baseline")
    _validate_objective(candidate, "candidate")
    for field in ("metric", "quantile"):
        if baseline[field] != candidate[field]:
            raise ValueError(f"objective mismatch in {field}")
    if not 0 <= minimum_improvement_ratio <= 1:
        raise ValueError("minimum_improvement_ratio must be between 0 and 1")
    if not -1 <= minimum_complete_trace_rate_delta <= 0:
        raise ValueError("minimum_complete_trace_rate_delta must be between -1 and 0")

    baseline_value = float(baseline["objective_value_ns"])
    candidate_value = float(candidate["objective_value_ns"])
    improvement = (baseline_value - candidate_value) / baseline_value
    coverage_delta = float(candidate["complete_trace_rate"]) - float(
        baseline["complete_trace_rate"]
    )
    reason = ""
    if formal and not (
        baseline["formal_optimization_allowed"]
        and candidate["formal_optimization_allowed"]
    ):
        reason = "formal_evidence_required"
    elif coverage_delta < minimum_complete_trace_rate_delta:
        reason = "complete_trace_rate_regression"
    elif improvement < minimum_improvement_ratio:
        reason = "insufficient_improvement"
    return {
        "schema_version": "candidate-validation/v1",
        "decision": "reject" if reason else "accept",
        "reason_code": reason,
        "rollback_required": bool(reason),
        "improvement_ratio": round(improvement, 12),
        "complete_trace_rate_delta": round(coverage_delta, 12),
        "formal_validation": formal,
    }


def _validate_objective(objective: dict[str, Any], label: str) -> None:
    if objective.get("schema_version") != "runtime-objective/v1":
        raise ValueError(f"invalid {label} objective schema")
    value = objective.get("objective_value_ns")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"invalid {label} objective value")
    rate = objective.get("complete_trace_rate")
    if (
        isinstance(rate, bool)
        or not isinstance(rate, (int, float))
        or not 0 <= rate <= 1
    ):
        raise ValueError(f"invalid {label} complete_trace_rate")
    if not isinstance(objective.get("formal_optimization_allowed"), bool):
        raise ValueError(f"invalid {label} formal flag")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--quantile", default="p95")
    parser.add_argument("--minimum-improvement-ratio", type=float, default=0.0)
    parser.add_argument("--minimum-complete-trace-rate-delta", type=float, default=0.0)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_reports(
        json.loads(args.baseline_report.read_text(encoding="utf-8")),
        json.loads(args.candidate_report.read_text(encoding="utf-8")),
        metric=args.metric,
        quantile=args.quantile,
        minimum_improvement_ratio=args.minimum_improvement_ratio,
        minimum_complete_trace_rate_delta=args.minimum_complete_trace_rate_delta,
        formal=args.formal,
    )
    result["inputs"] = {
        "baseline_report": str(args.baseline_report),
        "baseline_report_sha256": _sha256(args.baseline_report),
        "candidate_report": str(args.candidate_report),
        "candidate_report_sha256": _sha256(args.candidate_report),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if result["decision"] == "accept" else 1


if __name__ == "__main__":
    raise SystemExit(main())
