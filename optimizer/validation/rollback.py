"""Create an auditable apply-or-rollback decision without mutating a live system."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from optimizer.action_registry.registry import validate_action


def rollback_decision(
    validation: dict[str, Any],
    *,
    cause_id: str,
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
) -> dict[str, Any]:
    if validation.get("schema_version") != "candidate-validation/v1":
        raise ValueError("invalid candidate validation schema")
    decision = validation.get("decision")
    if decision not in {"accept", "reject"}:
        raise ValueError("invalid candidate validation decision")
    _validate_config(cause_id, baseline_config)
    _validate_config(cause_id, candidate_config)
    rollback = decision == "reject"
    if validation.get("rollback_required") is not rollback:
        raise ValueError("rollback flag conflicts with validation decision")
    return {
        "schema_version": "rollback-decision/v1",
        "cause_id": cause_id,
        "action": "restore_baseline" if rollback else "apply_candidate",
        "reason_code": str(validation.get("reason_code", "")),
        "baseline_config": dict(baseline_config),
        "candidate_config": dict(candidate_config),
        "selected_config": dict(baseline_config if rollback else candidate_config),
        "live_mutation_performed": False,
    }


def _validate_config(cause_id: str, config: dict[str, Any]) -> None:
    if not isinstance(config, dict) or len(config) != 1:
        raise ValueError("configuration must contain exactly one action")
    action_id, value = next(iter(config.items()))
    validate_action(cause_id, action_id, value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--cause-id", required=True)
    parser.add_argument("--baseline-config", required=True)
    parser.add_argument("--candidate-config", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = rollback_decision(
        json.loads(args.validation.read_text(encoding="utf-8")),
        cause_id=args.cause_id,
        baseline_config=json.loads(args.baseline_config),
        candidate_config=json.loads(args.candidate_config),
    )
    result["input"] = {
        "validation": str(args.validation),
        "validation_sha256": _sha256(args.validation),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
