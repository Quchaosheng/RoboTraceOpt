"""Load and validate the frozen formal experiment matrix."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


MATRIX_SCHEMA = "formal-experiment-matrix/v1"
RUNNERS = {"fault_condition", "repeated_optimization"}
CAPABILITIES = {
    "runtime_event",
    "ros2_tracing",
    "ebpf",
    "identity_comparable_ebpf",
    "socketcan",
    "cpu_control",
    "cross_host_clock",
    "scheduling_tools",
}
CASE_FIELDS = {
    "case_id",
    "group_id",
    "runner_id",
    "requirements",
    "repetitions",
    "parameters",
}
FAULT_PARAMETER_FIELDS = {
    "fault_id",
    "condition_variant",
    "duration_seconds",
}
OPTIMIZATION_PARAMETER_FIELDS = {
    "diagnosis_report",
    "baseline_profile",
    "strategy",
    "budget",
    "campaign_repetitions",
    "duration_seconds",
    "minimum_confidence",
    "minimum_completeness",
    "minimum_improvement_ratio",
    "minimum_complete_trace_rate_delta",
    "confidence_level",
    "bootstrap_resamples",
}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def load_experiment_matrix(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return validate_experiment_matrix(value)


def validate_experiment_matrix(value: dict[str, Any]) -> dict[str, Any]:
    """Return a validated deep copy of formal-experiment-matrix/v1."""
    if not isinstance(value, dict):
        raise ValueError("experiment matrix must be an object")
    unknown_top = set(value) - {"schema_version", "cases"}
    if unknown_top:
        raise ValueError(f"unknown matrix fields: {sorted(unknown_top)}")
    if value.get("schema_version") != MATRIX_SCHEMA:
        raise ValueError("unsupported formal experiment matrix schema")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("experiment matrix cases must be a non-empty list")

    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        unknown = set(case) - CASE_FIELDS
        missing = CASE_FIELDS - set(case)
        if unknown:
            raise ValueError(f"unknown case fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing case fields: {sorted(missing)}")

        case_id = _identifier(case["case_id"], "case_id")
        _identifier(case["group_id"], "group_id")
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if case["runner_id"] not in RUNNERS:
            raise ValueError(f"unsupported runner_id: {case['runner_id']}")
        _requirements(case["requirements"])
        _positive_integer(case["repetitions"], "repetitions")
        _parameters(case["runner_id"], case["parameters"])
    return copy.deepcopy(value)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _requirements(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("requirements must be a non-empty list")
    if any(not isinstance(item, str) or item not in CAPABILITIES for item in value):
        raise ValueError("unknown capability requirement")
    if len(value) != len(set(value)):
        raise ValueError("capability requirements must be unique")


def _parameters(runner_id: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("parameters must be an object")
    expected = (
        FAULT_PARAMETER_FIELDS
        if runner_id == "fault_condition"
        else OPTIMIZATION_PARAMETER_FIELDS
    )
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ValueError(f"unknown parameter fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing parameter fields: {sorted(missing)}")

    if runner_id == "fault_condition":
        if value["fault_id"] not in {f"F{index}" for index in range(1, 7)}:
            raise ValueError("invalid fault_id")
        if value["condition_variant"] not in {"control", "injected"}:
            raise ValueError("invalid condition_variant")
        _positive_integer(value["duration_seconds"], "duration_seconds")
        return

    for field in ("diagnosis_report", "baseline_profile"):
        path = value[field]
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise ValueError(f"invalid {field}")
    if value["strategy"] not in {"guided", "random", "unguided_random"}:
        raise ValueError("invalid strategy")
    _positive_integer(value["budget"], "budget")
    repetitions = _positive_integer(
        value["campaign_repetitions"], "campaign_repetitions"
    )
    if repetitions < 2:
        raise ValueError("campaign_repetitions must be at least two")
    _positive_integer(value["duration_seconds"], "duration_seconds")
    _ratio(value["minimum_confidence"], "minimum_confidence", 0.0, 1.0)
    _ratio(value["minimum_completeness"], "minimum_completeness", 0.0, 1.0)
    _ratio(
        value["minimum_improvement_ratio"],
        "minimum_improvement_ratio",
        0.0,
        1.0,
    )
    _ratio(
        value["minimum_complete_trace_rate_delta"],
        "minimum_complete_trace_rate_delta",
        -1.0,
        0.0,
    )
    confidence = _number(value["confidence_level"], "confidence_level")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    resamples = _positive_integer(value["bootstrap_resamples"], "bootstrap_resamples")
    if resamples < 100:
        raise ValueError("bootstrap_resamples must be at least 100")


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def _ratio(value: Any, field: str, lower: float, upper: float) -> None:
    number = _number(value, field)
    if not lower <= number <= upper:
        raise ValueError(f"{field} must be in [{lower}, {upper}]")
