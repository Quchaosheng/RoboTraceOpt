"""Compare matched F5 delivery-bound reports without formal inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


METRICS = ("median", "p90", "p95", "p99")
MATCHED_PROFILE_FIELDS = (
    "input_rate_hz",
    "payload_bytes",
    "reliability",
    "history",
    "durability",
)


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate_report(injected, "injected", 1)
    _validate_report(control, "control", 10)
    for field in MATCHED_PROFILE_FIELDS:
        if injected["qos"].get(field) != control["qos"].get(field):
            raise ValueError(f"F5 reports differ in {field}")

    metrics: dict[str, dict[str, float]] = {}
    for metric in METRICS:
        injected_value = float(injected["delay_ns"][metric])
        control_value = float(control["delay_ns"][metric])
        if control_value <= 0:
            raise ValueError(f"control {metric} must be positive")
        metrics[metric] = {
            "injected": injected_value,
            "control": control_value,
            "absolute_delta": injected_value - control_value,
            "ratio": injected_value / control_value,
        }

    injected_pairing = _pairing_rate(injected)
    control_pairing = _pairing_rate(control)
    return {
        "schema_version": "f5-pressure-comparison/v1",
        "development_only": True,
        "formal_inference_allowed": False,
        "measurement_semantics": "publish_to_receive_upper_bound",
        "matched_profile": {
            field: injected["qos"][field] for field in MATCHED_PROFILE_FIELDS
        },
        "depths": {
            "injected": {
                "publisher": int(injected["qos"]["publisher_depth"]),
                "subscriber": int(injected["qos"]["subscriber_depth"]),
            },
            "control": {
                "publisher": int(control["qos"]["publisher_depth"]),
                "subscriber": int(control["qos"]["subscriber_depth"]),
            },
        },
        "sample_counts": {
            "injected": int(injected["paired_trace_count"]),
            "control": int(control["paired_trace_count"]),
        },
        "pairing_rates": {
            "injected": injected_pairing,
            "control": control_pairing,
        },
        "pairing_rate_delta": injected_pairing - control_pairing,
        "sequence_gaps": {
            "injected": int(injected["received_sequence_gap_count"]),
            "control": int(control["received_sequence_gap_count"]),
        },
        "sequence_gap_delta": int(injected["received_sequence_gap_count"])
        - int(control["received_sequence_gap_count"]),
        "metrics_ns": metrics,
    }


def _validate_report(report: dict[str, Any], variant: str, depth: int) -> None:
    if report.get("schema_version") != "dds-pressure-evidence/v1":
        raise ValueError("unsupported DDS pressure report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if report.get("measurement_semantics") != "publish_to_receive_upper_bound":
        raise ValueError("incompatible measurement semantics")
    if report.get("includes_executor_wait") is not True:
        raise ValueError("executor-wait inclusion must be explicit")
    qos = report.get("qos")
    if not isinstance(qos, dict):
        raise ValueError("qos profile is required")
    if qos.get("publisher_depth") != depth or qos.get("subscriber_depth") != depth:
        raise ValueError(f"unexpected {variant} endpoint depth")
    delay = report.get("delay_ns")
    if not isinstance(delay, dict) or any(metric not in delay for metric in METRICS):
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
