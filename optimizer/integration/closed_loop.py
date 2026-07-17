"""Pure orchestration for diagnosis-guided runtime optimization."""

from __future__ import annotations

from typing import Any

from optimizer.integration.runtime_profiles import (
    candidate_cli_arguments,
    runtime_profile,
)


def validate_baseline_profile(
    record: dict[str, Any], cause_id: str
) -> dict[str, Any]:
    if record.get("schema_version") != "optimization-baseline-profile/v1":
        raise ValueError("invalid baseline profile schema")
    if record.get("cause_id") != cause_id:
        raise ValueError("baseline cause does not match diagnosis")
    config = record.get("baseline_config")
    candidate_cli_arguments(cause_id, config)
    return dict(config)


def build_execution_schedule(
    gate_result: dict[str, Any], baseline_config: dict[str, Any]
) -> dict[str, Any]:
    if gate_result.get("schema_version") != "diagnosis-optimization-gate/v1":
        raise ValueError("invalid diagnosis gate schema")
    if gate_result.get("decision") != "allow":
        raise ValueError("diagnosis gate must allow optimization")
    cause_id = str(gate_result.get("cause_id", ""))
    profile = runtime_profile(cause_id)
    candidate_cli_arguments(cause_id, baseline_config)
    plan = gate_result.get("trial_plan")
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != "optimization-trial-plan/v1"
        or plan.get("cause_id") != cause_id
    ):
        raise ValueError("allowed gate requires a matching trial plan")
    rows = plan.get("trials")
    if not isinstance(rows, list):
        raise ValueError("trial plan requires trials")

    trials = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("trial record must be an object")
        config = row.get("candidate_config")
        if row.get("applicable_to_diagnosis") is not True:
            status = "not_applicable"
            reason = "action_not_applicable"
        else:
            candidate_cli_arguments(cause_id, config)
            if config == baseline_config:
                status = "baseline_duplicate"
                reason = "candidate_matches_baseline"
            else:
                status = "scheduled"
                reason = ""
        trials.append({**dict(row), "status": status, "reason_code": reason})

    return {
        "schema_version": "optimization-execution-schedule/v1",
        "cause_id": cause_id,
        "action_id": profile["action_id"],
        "baseline_config": dict(baseline_config),
        "strategy": plan["strategy"],
        "seed": plan["seed"],
        "budget": plan["budget"],
        "trials": trials,
    }
