"""Compare matched F6 application-level mock ACK lifecycle reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MATCHED_FIELDS = (
    "git_commit", "workload", "host_id", "ack_timeout_ms", "max_retries",
    "ack_mode", "mock_mode", "input_rate_hz", "planner_backend",
    "action_manager_enabled",
)
COUNTS = ("attempt_count", "timeout_count", "retry_scheduled_count")
TERMINALS = ("ack_received", "retry_exhausted")
QUANTILES = ("median", "p90", "p95", "p99")


def compare_reports(injected: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    _validate(injected, "injected")
    _validate(control, "control")
    for field in MATCHED_FIELDS:
        if injected["profile"].get(field) != control["profile"].get(field):
            raise ValueError(f"F6 reports differ in {field}")
    latency = {
        terminal: _compare_latency(
            injected["terminal_latency_ns"][terminal],
            control["terminal_latency_ns"][terminal],
        )
        for terminal in TERMINALS
    }
    return {
        "schema_version": "f6-mock-ack-comparison/v1",
        "measurement_semantics": "application_mock_ack_lifecycle",
        "physical_can_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "matched_profile": {field: injected["profile"][field] for field in MATCHED_FIELDS},
        "ack_policies": {"injected": "drop", "control": "success"},
        "sample_counts": {
            "injected": int(injected["valid_terminal_count"]),
            "control": int(control["valid_terminal_count"]),
        },
        "terminal_coverage": {
            "injected": float(injected["terminal_coverage"]),
            "control": float(control["terminal_coverage"]),
        },
        "terminal_coverage_delta": float(injected["terminal_coverage"]) - float(control["terminal_coverage"]),
        "ack_success_rate_delta": float(injected["ack_success_rate"]) - float(control["ack_success_rate"]),
        "retry_exhausted_rate_delta": float(injected["retry_exhausted_rate"]) - float(control["retry_exhausted_rate"]),
        "rates": {
            "ack_success": {"injected": float(injected["ack_success_rate"]), "control": float(control["ack_success_rate"])},
            "retry_exhausted": {"injected": float(injected["retry_exhausted_rate"]), "control": float(control["retry_exhausted_rate"])},
        },
        "mean_count_deltas": {
            name: float(injected["count_distributions"][name]["mean"]) - float(control["count_distributions"][name]["mean"])
            for name in COUNTS
        },
        "terminal_latency_ns": latency,
    }


def _validate(report: dict[str, Any], variant: str) -> None:
    if report.get("schema_version") != "mock-ack-lifecycle-evidence/v1":
        raise ValueError("unsupported F6 report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if report.get("measurement_semantics") != "application_mock_ack_lifecycle":
        raise ValueError("incompatible measurement semantics")
    if report.get("physical_can_evidence") is not False:
        raise ValueError("physical CAN evidence must be disabled")
    if report.get("development_only") is not True or report.get("formal_inference_allowed") is not False:
        raise ValueError("F6 report must be development-only")
    profile = report.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("F6 profile is required")
    expected_policy = "drop" if variant == "injected" else "success"
    if profile.get("mock_ack_policy") != expected_policy:
        raise ValueError(f"invalid {variant} mock_ack_policy")
    if int(report.get("valid_terminal_count", 0)) < 1:
        raise ValueError("valid_terminal_count must be positive")
    for name in ("terminal_coverage", "ack_success_rate", "retry_exhausted_rate"):
        value = report.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise ValueError(f"invalid {name}")
    counts = report.get("count_distributions")
    if not isinstance(counts, dict) or any(not isinstance(counts.get(name), dict) or "mean" not in counts[name] for name in COUNTS):
        raise ValueError("missing count distributions")
    latency = report.get("terminal_latency_ns")
    if not isinstance(latency, dict) or any(terminal not in latency for terminal in TERMINALS):
        raise ValueError("missing terminal latency distributions")


def _compare_latency(injected: Any, control: Any) -> dict[str, dict[str, float]] | None:
    if injected is None or control is None:
        return None
    result = {}
    for quantile in QUANTILES:
        injected_value = float(injected[quantile])
        control_value = float(control[quantile])
        if control_value <= 0:
            raise ValueError(f"control terminal latency {quantile} must be positive")
        result[quantile] = {"injected": injected_value, "control": control_value, "absolute_delta": injected_value - control_value, "ratio": injected_value / control_value}
    return result


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
    injected = json.loads(args.injected_report.read_text(encoding="utf-8"))
    control = json.loads(args.control_report.read_text(encoding="utf-8"))
    comparison = compare_reports(injected, control)
    comparison["inputs"] = {
        "injected_report": str(args.injected_report), "injected_report_sha256": _sha256(args.injected_report),
        "control_report": str(args.control_report), "control_report_sha256": _sha256(args.control_report),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
