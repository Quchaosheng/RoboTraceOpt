"""Compare matched F3 scheduling-pressure proxy reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


METRICS = (
    "dispatch_upper_bound_ns",
    "zero_work_callback_elapsed_ns",
    "planner_path_upper_bound_ns",
)
QUANTILES = ("median", "p90", "p95", "p99")
PROFILE_FIELDS = (
    "git_commit",
    "host_id",
    "host_class",
    "target_cpu",
    "input_rate_hz",
    "cpu_load_percent",
    "cpu_method",
    "tracing_required",
)


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate_report(injected, "injected")
    _validate_report(control, "control")
    for field in PROFILE_FIELDS:
        if injected["profile"].get(field) != control["profile"].get(field):
            raise ValueError(f"F3 reports differ in {field}")

    metric_comparisons: dict[str, dict[str, dict[str, float]]] = {}
    for metric in METRICS:
        metric_comparisons[metric] = {}
        for quantile in QUANTILES:
            injected_value = float(injected["metrics_ns"][metric][quantile])
            control_value = float(control["metrics_ns"][metric][quantile])
            if control_value <= 0:
                raise ValueError(f"control {metric} {quantile} must be positive")
            metric_comparisons[metric][quantile] = {
                "injected": injected_value,
                "control": control_value,
                "absolute_delta": injected_value - control_value,
                "ratio": injected_value / control_value,
            }

    injected_rate = _complete_rate(injected)
    control_rate = _complete_rate(control)
    return {
        "schema_version": "f3-pressure-comparison/v1",
        "development_only": True,
        "formal_inference_allowed": False,
        "measurement_semantics": "scheduling_pressure_proxy",
        "matched_profile": {
            field: injected["profile"][field] for field in PROFILE_FIELDS
        },
        "sample_counts": {
            "injected": int(injected["complete_trace_count"]),
            "control": int(control["complete_trace_count"]),
        },
        "complete_trace_rates": {
            "injected": injected_rate,
            "control": control_rate,
        },
        "complete_trace_rate_delta": injected_rate - control_rate,
        "metrics_ns": metric_comparisons,
    }


def _validate_report(report: dict[str, Any], variant: str) -> None:
    if report.get("schema_version") != "scheduling-pressure-evidence/v1":
        raise ValueError("unsupported F3 pressure report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if report.get("measurement_semantics") != "scheduling_pressure_proxy":
        raise ValueError("incompatible measurement semantics")
    if report.get("formal_scheduling_attribution") is not False:
        raise ValueError("formal scheduling attribution must be disabled")
    if report.get("development_only") is not True:
        raise ValueError("F3 proxy report must be development-only")
    if not isinstance(report.get("profile"), dict):
        raise ValueError("F3 profile is required")
    metrics = report.get("metrics_ns")
    if not isinstance(metrics, dict):
        raise ValueError("metrics_ns is required")
    for metric in METRICS:
        if not isinstance(metrics.get(metric), dict) or any(
            quantile not in metrics[metric] for quantile in QUANTILES
        ):
            raise ValueError(f"incomplete metric: {metric}")
    if int(report.get("complete_trace_count", 0)) < 1:
        raise ValueError("complete_trace_count must be positive")


def _complete_rate(report: dict[str, Any]) -> float:
    complete = int(report["complete_trace_count"])
    observed = int(report["observed_trace_count"])
    if observed < complete or observed < 1:
        raise ValueError("invalid trace counts")
    return complete / observed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injected-report", type=Path, required=True)
    parser.add_argument("--control-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    injected = json.loads(args.injected_report.read_text(encoding="utf-8"))
    control = json.loads(args.control_report.read_text(encoding="utf-8"))
    comparison = compare_reports(injected, control)
    comparison["inputs"] = {
        "injected_report": str(args.injected_report),
        "injected_report_sha256": _sha256(args.injected_report),
        "control_report": str(args.control_report),
        "control_report_sha256": _sha256(args.control_report),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
