"""Gate optimization planning on an auditable, non-abstained diagnosis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from optimizer.action_registry.registry import actions_for_cause
from optimizer.search.trial_planner import build_trial_plan


FORBIDDEN_ORACLE_FIELDS = {"oracle_id", "true_cause_id", "condition_variant"}


def plan_from_diagnosis(
    report: dict[str, Any],
    *,
    strategy: str,
    budget: int,
    seed: int,
    minimum_confidence: float,
    minimum_completeness: float = 1.0,
) -> dict[str, Any]:
    _validate_report(report)
    _validate_threshold("minimum_confidence", minimum_confidence)
    _validate_threshold("minimum_completeness", minimum_completeness)
    status = str(report["status"])
    cause_id = report.get("top_1")
    reason = ""
    if status == "abstained":
        reason = "diagnosis_abstained"
    elif report["evidence_state"] != "valid":
        reason = "valid_evidence_required"
    elif float(report["confidence"]) < minimum_confidence:
        reason = "confidence_below_gate"
    elif float(report["completeness"]) < minimum_completeness:
        reason = "completeness_below_gate"
    else:
        try:
            actions_for_cause(str(cause_id))
        except ValueError:
            reason = "no_registered_action"

    plan = None
    if not reason:
        plan = build_trial_plan(
            str(cause_id), strategy=strategy, budget=budget, seed=seed
        )
    return {
        "schema_version": "diagnosis-optimization-gate/v1",
        "trace_id": report["trace_id"],
        "decision": "deny" if reason else "allow",
        "reason_code": reason,
        "cause_id": cause_id,
        "diagnosis_status": status,
        "diagnosis_confidence": float(report["confidence"]),
        "diagnosis_completeness": float(report["completeness"]),
        "minimum_confidence": float(minimum_confidence),
        "minimum_completeness": float(minimum_completeness),
        "oracle_fields_consumed": False,
        "trial_plan": plan,
    }


def _validate_report(report: dict[str, Any]) -> None:
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != "diagnosis-report/v1"
    ):
        raise ValueError("invalid diagnosis report schema")
    forbidden = _find_forbidden_fields(report)
    if forbidden:
        raise ValueError(f"oracle fields are forbidden: {', '.join(sorted(forbidden))}")
    if report.get("status") not in {"diagnosed", "abstained"}:
        raise ValueError("invalid diagnosis status")
    if report.get("evidence_state") not in {
        "valid",
        "partial",
        "invalid",
        "not_observed",
    }:
        raise ValueError("invalid evidence state")
    for field in ("confidence", "completeness"):
        value = report.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError(f"invalid diagnosis {field}")
    top_1 = report.get("top_1")
    top_k = report.get("top_k")
    if report["status"] == "diagnosed":
        if not isinstance(top_1, str) or not top_1:
            raise ValueError("diagnosed report requires top_1")
        if not isinstance(top_k, list) or top_1 not in top_k:
            raise ValueError("diagnosed report requires a consistent top_k")
    elif top_1 is not None or top_k != []:
        raise ValueError("abstained report cannot expose a cause claim")
    if not isinstance(report.get("trace_id"), str) or not report["trace_id"]:
        raise ValueError("diagnosis trace_id is required")


def _find_forbidden_fields(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = FORBIDDEN_ORACLE_FIELDS & set(value)
        return found | set().union(
            *(_find_forbidden_fields(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_find_forbidden_fields(item) for item in value), set())
    return set()


def _validate_threshold(name: str, value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{name} must be between 0 and 1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis-report", type=Path, required=True)
    parser.add_argument(
        "--strategy", choices=("guided", "random", "unguided_random"), default="guided"
    )
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--minimum-confidence", type=float, required=True)
    parser.add_argument("--minimum-completeness", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = plan_from_diagnosis(
        json.loads(args.diagnosis_report.read_text(encoding="utf-8")),
        strategy=args.strategy,
        budget=args.budget,
        seed=args.seed,
        minimum_confidence=args.minimum_confidence,
        minimum_completeness=args.minimum_completeness,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if result["decision"] == "allow" else 2


if __name__ == "__main__":
    raise SystemExit(main())
