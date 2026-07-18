"""Compare matched F6 physical SocketCAN ACK lifecycle reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.fault_injection.compare_f6_mock_ack import _sha256
from experiments.fault_injection.compare_f6_vcan_ack import (
    MATCHED_FIELDS,
    build_comparison,
)


PHYSICAL_MATCHED_FIELDS = MATCHED_FIELDS + ("responder_interface", "bitrate")


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate(injected, "injected")
    _validate(control, "control")
    return build_comparison(
        injected,
        control,
        schema_version="f6-physical-can-ack-comparison/v1",
        measurement_semantics="application_socketcan_physical_ack_lifecycle",
        virtual_can_bus=False,
        physical_can_evidence=True,
        matched_fields=PHYSICAL_MATCHED_FIELDS,
        profile_label="physical CAN",
    )


def _validate(report: dict[str, Any], variant: str) -> None:
    if report.get("schema_version") != "socketcan-ack-lifecycle-evidence/v1":
        raise ValueError("unsupported F6 physical CAN report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if (
        report.get("measurement_semantics")
        != "application_socketcan_physical_ack_lifecycle"
        or report.get("socketcan_evidence") is not True
        or report.get("virtual_can_bus") is not False
        or report.get("physical_can_evidence") is not True
    ):
        raise ValueError("physical SocketCAN evidence flags are required")
    if (
        report.get("development_only") is not True
        or report.get("formal_inference_allowed") is not False
    ):
        raise ValueError("physical F6 report must be development-only")
    profile = report.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("physical F6 profile is required")
    if (
        profile.get("transport_profile") != "physical"
        or profile.get("ack_mode") != "socketcan"
        or profile.get("mock_mode") is not False
        or profile.get("can_interface") == profile.get("responder_interface")
        or not isinstance(profile.get("bitrate"), int)
        or profile["bitrate"] <= 0
    ):
        raise ValueError("invalid physical SocketCAN profile")
    expected_policy = "drop" if variant == "injected" else "echo"
    if profile.get("responder_policy") != expected_policy:
        raise ValueError(f"invalid {variant} responder_policy")
    if int(report.get("valid_terminal_count", 0)) < 1:
        raise ValueError("valid_terminal_count must be positive")
    for name in (
        "terminal_coverage",
        "command_frame_match_coverage",
        "responder_match_coverage",
        "ack_success_rate",
        "retry_exhausted_rate",
    ):
        value = report.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= value <= 1
        ):
            raise ValueError(f"invalid {name}")
    ack_coverage = report.get("ack_frame_match_coverage")
    if variant == "injected" and ack_coverage is not None:
        raise ValueError("drop ACK-frame coverage must be null")
    if variant == "control" and (
        not isinstance(ack_coverage, (int, float))
        or isinstance(ack_coverage, bool)
        or not 0 <= ack_coverage <= 1
    ):
        raise ValueError("invalid ack_frame_match_coverage")
    counts = report.get("count_distributions")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(name), dict) or "mean" not in counts[name]
        for name in ("attempt_count", "timeout_count", "retry_scheduled_count")
    ):
        raise ValueError("missing count distributions")
    latency = report.get("terminal_latency_ns")
    if not isinstance(latency, dict) or any(
        terminal not in latency for terminal in ("ack_received", "retry_exhausted")
    ):
        raise ValueError("missing terminal latency distributions")
    for field in ("candump_help_sha256", "responder_script_sha256"):
        value = profile.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"invalid {field}")


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
