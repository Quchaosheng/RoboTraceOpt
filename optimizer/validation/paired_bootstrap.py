"""Validate repeated optimization candidates with paired bootstrap intervals."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from typing import Any


def percentile_bootstrap_interval(
    values: Sequence[float],
    *,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> dict[str, float | None]:
    _validate_bootstrap_parameters(confidence_level, resamples, seed)
    numeric = [_finite_number(value, "bootstrap value") for value in values]
    if len(numeric) < 2:
        point = statistics.median(numeric) if numeric else None
        return {"estimate": point, "lower": None, "upper": None}
    rng = random.Random(seed)
    samples = sorted(
        statistics.median(rng.choices(numeric, k=len(numeric)))
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "estimate": statistics.median(numeric),
        "lower": _linear_quantile(samples, alpha),
        "upper": _linear_quantile(samples, 1.0 - alpha),
    }


def evaluate_repeated_candidates(
    schedule: dict[str, Any],
    records: Sequence[dict[str, Any]],
    *,
    minimum_improvement_ratio: float,
    minimum_complete_trace_rate_delta: float,
    confidence_level: float,
    bootstrap_resamples: int,
    seed: int,
) -> list[dict[str, Any]]:
    if schedule.get("schema_version") != "optimization-repeated-schedule/v1":
        raise ValueError("invalid repeated schedule schema")
    repetitions = schedule.get("repetitions")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 2:
        raise ValueError("invalid repeated schedule repetitions")
    if (
        isinstance(minimum_improvement_ratio, bool)
        or not isinstance(minimum_improvement_ratio, (int, float))
        or not 0 <= minimum_improvement_ratio <= 1
    ):
        raise ValueError("minimum improvement ratio must be between zero and one")
    if (
        isinstance(minimum_complete_trace_rate_delta, bool)
        or not isinstance(minimum_complete_trace_rate_delta, (int, float))
        or not -1 <= minimum_complete_trace_rate_delta <= 0
    ):
        raise ValueError("minimum complete trace rate delta must be between minus one and zero")
    _validate_bootstrap_parameters(confidence_level, bootstrap_resamples, seed)

    configurations = schedule.get("configurations")
    if not isinstance(configurations, list):
        raise ValueError("repeated schedule requires configurations")
    baselines = [row for row in configurations if row.get("role") == "baseline"]
    candidates = [row for row in configurations if row.get("role") == "candidate"]
    if len(baselines) != 1:
        raise ValueError("repeated schedule requires one baseline")
    known = {str(row.get("config_id")): row for row in configurations}
    if len(known) != len(configurations) or "None" in known:
        raise ValueError("repeated schedule has invalid configuration IDs")

    indexed: dict[tuple[int, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("repeated trial record must be an object")
        block = record.get("block_index")
        identifier = record.get("config_id")
        if (
            isinstance(block, bool)
            or not isinstance(block, int)
            or not 1 <= block <= repetitions
            or not isinstance(identifier, str)
            or identifier not in known
        ):
            raise ValueError("repeated trial record does not match schedule")
        key = (block, identifier)
        if key in indexed:
            raise ValueError("duplicate repeated trial record")
        expected = known[identifier]
        if (
            record.get("role") != expected.get("role")
            or record.get("candidate_config") != expected.get("candidate_config")
        ):
            raise ValueError("repeated trial record configuration mismatch")
        if record.get("status") == "succeeded":
            _objective(record)
            _complete_trace_rate(record)
        indexed[key] = record

    baseline = baselines[0]
    baseline_id = str(baseline["config_id"])
    results: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(candidates, start=1):
        candidate_id = str(candidate["config_id"])
        improvements: list[float] = []
        completeness_deltas: list[float] = []
        candidate_objectives: list[float] = []
        failed = 0
        missing = 0
        pairs = []
        for block in range(1, repetitions + 1):
            baseline_record = indexed.get((block, baseline_id))
            candidate_record = indexed.get((block, candidate_id))
            if baseline_record is None or candidate_record is None:
                missing += 1
                pairs.append({"block_index": block, "status": "missing"})
                continue
            if (
                baseline_record.get("status") != "succeeded"
                or candidate_record.get("status") != "succeeded"
            ):
                failed += 1
                pairs.append({"block_index": block, "status": "failed"})
                continue
            baseline_value = _objective(baseline_record)
            candidate_value = _objective(candidate_record)
            improvement = (baseline_value - candidate_value) / baseline_value
            completeness_delta = _complete_trace_rate(
                candidate_record
            ) - _complete_trace_rate(baseline_record)
            improvements.append(improvement)
            completeness_deltas.append(completeness_delta)
            candidate_objectives.append(candidate_value)
            pairs.append(
                {
                    "block_index": block,
                    "status": "succeeded",
                    "improvement_ratio": improvement,
                    "complete_trace_rate_delta": completeness_delta,
                }
            )

        improvement_interval = percentile_bootstrap_interval(
            improvements,
            confidence_level=confidence_level,
            resamples=bootstrap_resamples,
            seed=seed + candidate_index,
        )
        completeness_interval = percentile_bootstrap_interval(
            completeness_deltas,
            confidence_level=confidence_level,
            resamples=bootstrap_resamples,
            seed=seed + candidate_index,
        )
        successful = len(improvements)
        reason = ""
        if successful != repetitions:
            reason = "incomplete_repeated_evidence"
        elif (
            completeness_interval["lower"] is None
            or completeness_interval["lower"] < minimum_complete_trace_rate_delta
        ):
            reason = "complete_trace_rate_regression_uncertain"
        elif (
            improvement_interval["lower"] is None
            or improvement_interval["lower"] < minimum_improvement_ratio
        ):
            reason = "improvement_uncertain"

        results.append(
            {
                "schema_version": "repeated-candidate-validation/v1",
                "config_index": int(candidate["config_index"]),
                "config_id": candidate_id,
                "candidate_config": dict(candidate["candidate_config"]),
                "decision": "reject" if reason else "accept",
                "reason_code": reason,
                "rollback_required": bool(reason),
                "planned_pair_count": repetitions,
                "successful_pair_count": successful,
                "failed_pair_count": failed,
                "missing_pair_count": missing,
                "confidence_level": float(confidence_level),
                "bootstrap_resamples": bootstrap_resamples,
                "minimum_improvement_ratio": float(minimum_improvement_ratio),
                "minimum_complete_trace_rate_delta": float(
                    minimum_complete_trace_rate_delta
                ),
                "improvement_ratio": improvement_interval,
                "complete_trace_rate_delta": completeness_interval,
                "median_candidate_objective_ns": (
                    statistics.median(candidate_objectives)
                    if candidate_objectives
                    else None
                ),
                "pairs": pairs,
            }
        )
    return results


def _validate_bootstrap_parameters(
    confidence_level: float, resamples: int, seed: int
) -> None:
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not 0 < confidence_level < 1
    ):
        raise ValueError("confidence level must be between zero and one")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError("bootstrap resamples must be at least 100")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("bootstrap seed must be an integer")


def _linear_quantile(values: Sequence[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def _finite_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"invalid {label}")
    return float(value)


def _objective(record: dict[str, Any]) -> float:
    value = _finite_number(record.get("objective_value_ns"), "objective")
    if value <= 0:
        raise ValueError("invalid objective")
    return value


def _complete_trace_rate(record: dict[str, Any]) -> float:
    value = _finite_number(record.get("complete_trace_rate"), "complete trace rate")
    if not 0 <= value <= 1:
        raise ValueError("invalid complete trace rate")
    return value
