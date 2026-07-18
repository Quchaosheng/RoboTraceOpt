"""Compare matched F4 service blocking-delay evidence reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


METRICS = (
    "server_processing_elapsed_ns",
    "request_response_elapsed_ns",
    "pre_server_elapsed_ns",
    "post_server_elapsed_ns",
)
MATCHED_FIELDS = (
    "git_commit",
    "workload",
    "host_id",
    "request_rate_hz",
    "blocking_primitive",
)
QUANTILES = ("median", "p90", "p95", "p99")


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate(injected, "injected")
    _validate(control, "control")
    for field in MATCHED_FIELDS:
        left = injected["profile"].get(field)
        right = control["profile"].get(field)
        if left != right:
            raise ValueError(f"F4 reports differ in {field}")
    if injected["profile"]["server_delay_ms"] != 100:
        raise ValueError("injected report must use 100 ms delay")
    if control["profile"]["server_delay_ms"] != 0:
        raise ValueError("control report must use 0 ms delay")

    metrics: dict[str, Any] = {}
    for metric in METRICS:
        metrics[metric] = {
            quantile: _compare_quantile(
                injected["metrics_ns"][metric][quantile],
                control["metrics_ns"][metric][quantile],
            )
            for quantile in QUANTILES
        }
    return {
        "schema_version": "f4-blocking-delay-comparison/v1",
        "measurement_semantics": "application_service_blocking_elapsed",
        "development_only": True,
        "formal_inference_allowed": False,
        "matched_profile": {
            field: injected["profile"][field] for field in MATCHED_FIELDS
        },
        "delay_profiles_ms": {
            "injected": int(injected["profile"]["server_delay_ms"]),
            "control": int(control["profile"]["server_delay_ms"]),
        },
        "sample_counts": {
            "injected": int(injected["complete_trace_count"]),
            "control": int(control["complete_trace_count"]),
        },
        "complete_trace_rate_delta": round(_rate(injected) - _rate(control), 12),
        "metrics_ns": metrics,
    }


def _compare_quantile(injected: Any, control: Any) -> dict[str, float | None]:
    left = float(injected)
    right = float(control)
    return {
        "injected": left,
        "control": right,
        "absolute_delta": left - right,
        "ratio": left / right if right > 0 else None,
    }


def _rate(report: dict[str, Any]) -> float:
    observed = int(report["observed_trace_count"])
    return float(
        report.get("complete_trace_rate", report["complete_trace_count"] / observed)
    )


def _validate(report: dict[str, Any], variant: str) -> None:
    if report.get("schema_version") != "service-blocking-evidence/v1":
        raise ValueError("unsupported F4 report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if report.get("measurement_semantics") != "application_service_blocking_elapsed":
        raise ValueError("incompatible measurement semantics")
    if report.get("formal_syscall_attribution") is not False:
        raise ValueError("formal syscall attribution must be false")
    if report.get("ebpf_evidence") is not False:
        raise ValueError("eBPF evidence must be false")
    if (
        report.get("development_only") is not True
        or report.get("formal_inference_allowed") is not False
    ):
        raise ValueError("F4 report must be development-only")
    profile = report.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("F4 profile is required")
    for field in (
        "git_commit",
        "workload",
        "host_id",
        "request_rate_hz",
        "blocking_primitive",
        "server_delay_ms",
    ):
        if field not in profile:
            raise ValueError(f"missing profile field {field}")
    if profile.get("workload") != "w2":
        raise ValueError("F4 workload must be w2")
    if int(report.get("observed_trace_count", 0)) < 1:
        raise ValueError("observed trace count must be positive")
    complete = int(report.get("complete_trace_count", -1))
    observed = int(report.get("observed_trace_count", -1))
    if complete < 0 or complete > observed:
        raise ValueError("invalid trace counts")
    rate = report.get("complete_trace_rate", complete / observed if observed else 0.0)
    if (
        not isinstance(rate, (int, float))
        or isinstance(rate, bool)
        or not 0 <= rate <= 1
    ):
        raise ValueError("invalid complete_trace_rate")
    metrics = report.get("metrics_ns")
    if not isinstance(metrics, dict):
        raise ValueError("metrics_ns is required")
    for metric in METRICS:
        values = metrics.get(metric)
        if not isinstance(values, dict) or any(q not in values for q in QUANTILES):
            raise ValueError(f"missing {metric}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injected-report", type=Path, required=True)
    parser.add_argument("--control-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparison = compare_reports(
        json.loads(args.injected_report.read_text(encoding="utf-8")),
        json.loads(args.control_report.read_text(encoding="utf-8")),
    )
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
