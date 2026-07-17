"""Compare matched F2 dispatch-bound reports without formal inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


METRICS = ("median", "p90", "p95", "p99")


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate_report(injected, "injected")
    _validate_report(control, "control")
    metric_comparison: dict[str, dict[str, float]] = {}
    for metric in METRICS:
        injected_value = float(injected["delay_ns"][metric])
        control_value = float(control["delay_ns"][metric])
        if control_value <= 0:
            raise ValueError(f"control {metric} must be positive")
        metric_comparison[metric] = {
            "injected": injected_value,
            "control": control_value,
            "absolute_delta": injected_value - control_value,
            "ratio": injected_value / control_value,
        }
    return {
        "schema_version": "f2-dispatch-comparison/v1",
        "development_only": True,
        "formal_inference_allowed": False,
        "measurement_semantics": "publish_to_callback_upper_bound",
        "sample_counts": {
            "injected": int(injected["paired_trace_count"]),
            "control": int(control["paired_trace_count"]),
        },
        "pairing_rates": {
            "injected": _pairing_rate(injected),
            "control": _pairing_rate(control),
        },
        "metrics_ns": metric_comparison,
    }


def _validate_report(report: dict[str, Any], expected_variant: str) -> None:
    if report.get("schema_version") != "callback-dispatch-evidence/v1":
        raise ValueError("unsupported callback dispatch report schema")
    if report.get("condition_variant") != expected_variant:
        raise ValueError(f"expected {expected_variant} report")
    if report.get("measurement_semantics") != "publish_to_callback_upper_bound":
        raise ValueError("incompatible measurement semantics")
    if not isinstance(report.get("delay_ns"), dict):
        raise ValueError("delay_ns summary is required")
    if any(metric not in report["delay_ns"] for metric in METRICS):
        raise ValueError("delay_ns summary is incomplete")
    if int(report.get("paired_trace_count", 0)) < 1:
        raise ValueError("paired_trace_count must be positive")


def _pairing_rate(report: dict[str, Any]) -> float:
    paired = int(report["paired_trace_count"])
    observed_union = (
        int(report["published_trace_count"])
        + int(report["received_trace_count"])
        - paired
    )
    if observed_union < paired or observed_union < 1:
        raise ValueError("invalid endpoint counts")
    return paired / observed_union


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
