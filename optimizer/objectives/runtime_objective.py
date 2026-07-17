"""Extract one auditable latency objective from an evidence report."""

from __future__ import annotations

from typing import Any


def runtime_objective(
    report: dict[str, Any], *, metric: str, quantile: str
) -> dict[str, Any]:
    metrics = report.get("metrics_ns")
    values = metrics.get(metric) if isinstance(metrics, dict) else None
    if not isinstance(values, dict) or quantile not in values:
        raise ValueError(f"missing {metric} {quantile}")
    value = values[quantile]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"invalid {metric} {quantile}")
    rate = report.get("complete_trace_rate")
    if rate is None:
        complete = report.get("complete_trace_count")
        observed = report.get("observed_trace_count")
        if (
            isinstance(complete, int)
            and not isinstance(complete, bool)
            and isinstance(observed, int)
            and not isinstance(observed, bool)
            and observed > 0
            and 0 <= complete <= observed
        ):
            rate = complete / observed
    if (
        isinstance(rate, bool)
        or not isinstance(rate, (int, float))
        or not 0 <= rate <= 1
    ):
        raise ValueError("invalid complete_trace_rate")
    formal = (
        report.get("development_only") is False
        and report.get("formal_inference_allowed") is True
    )
    return {
        "schema_version": "runtime-objective/v1",
        "source_schema_version": report.get("schema_version", ""),
        "metric": metric,
        "quantile": quantile,
        "objective_value_ns": float(value),
        "complete_trace_rate": float(rate),
        "formal_optimization_allowed": formal,
    }
