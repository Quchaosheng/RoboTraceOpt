"""Compare matched F6 SocketCAN/vcan ACK lifecycle reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.fault_injection.compare_f6_mock_ack import (
    _compare_latency,
    _sha256,
)


MATCHED_FIELDS = (
    "git_commit",
    "workload",
    "host_id",
    "transport_profile",
    "ack_mode",
    "mock_mode",
    "can_interface",
    "ack_can_id_offset",
    "responder_delay_ms",
    "ack_timeout_ms",
    "max_retries",
    "input_rate_hz",
    "planner_backend",
    "action_manager_enabled",
    "candump_help_sha256",
    "responder_script_sha256",
)
COUNTS = ("attempt_count", "timeout_count", "retry_scheduled_count")
TERMINALS = ("ack_received", "retry_exhausted")


def compare_reports(
    injected: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    _validate(injected, "injected")
    _validate(control, "control")
    for field in MATCHED_FIELDS:
        if injected["profile"].get(field) != control["profile"].get(field):
            raise ValueError(f"F6 vcan reports differ in {field}")

    return {
        "schema_version": "f6-vcan-ack-comparison/v1",
        "measurement_semantics": "application_socketcan_vcan_ack_lifecycle",
        "socketcan_evidence": True,
        "virtual_can_bus": True,
        "physical_can_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "matched_profile": {
            field: injected["profile"][field] for field in MATCHED_FIELDS
        },
        "responder_policies": {"injected": "drop", "control": "echo"},
        "sample_counts": {
            "injected": int(injected["valid_terminal_count"]),
            "control": int(control["valid_terminal_count"]),
        },
        "terminal_coverage": _pair(injected, control, "terminal_coverage"),
        "terminal_coverage_delta": _delta(injected, control, "terminal_coverage"),
        "command_frame_match_coverage": _pair(
            injected, control, "command_frame_match_coverage"
        ),
        "command_frame_match_coverage_delta": _delta(
            injected, control, "command_frame_match_coverage"
        ),
        "responder_match_coverage": _pair(
            injected, control, "responder_match_coverage"
        ),
        "responder_match_coverage_delta": _delta(
            injected, control, "responder_match_coverage"
        ),
        "ack_frame_match_coverage": {
            "injected": injected["ack_frame_match_coverage"],
            "control": control["ack_frame_match_coverage"],
        },
        "ack_success_rate_delta": _delta(injected, control, "ack_success_rate"),
        "retry_exhausted_rate_delta": _delta(injected, control, "retry_exhausted_rate"),
        "rates": {
            "ack_success": _pair(injected, control, "ack_success_rate"),
            "retry_exhausted": _pair(injected, control, "retry_exhausted_rate"),
        },
        "mean_count_deltas": {
            name: float(injected["count_distributions"][name]["mean"])
            - float(control["count_distributions"][name]["mean"])
            for name in COUNTS
        },
        "terminal_latency_ns": {
            terminal: _compare_latency(
                injected["terminal_latency_ns"][terminal],
                control["terminal_latency_ns"][terminal],
            )
            for terminal in TERMINALS
        },
    }


def _pair(
    injected: dict[str, Any], control: dict[str, Any], field: str
) -> dict[str, float]:
    return {
        "injected": float(injected[field]),
        "control": float(control[field]),
    }


def _delta(injected: dict[str, Any], control: dict[str, Any], field: str) -> float:
    return float(injected[field]) - float(control[field])


def _validate(report: dict[str, Any], variant: str) -> None:
    if report.get("schema_version") != "socketcan-ack-lifecycle-evidence/v1":
        raise ValueError("unsupported F6 vcan report schema")
    if report.get("condition_variant") != variant:
        raise ValueError(f"expected {variant} report")
    if (
        report.get("measurement_semantics")
        != "application_socketcan_vcan_ack_lifecycle"
    ):
        raise ValueError("incompatible measurement semantics")
    if (
        report.get("socketcan_evidence") is not True
        or report.get("virtual_can_bus") is not True
    ):
        raise ValueError("SocketCAN/vcan evidence flags are required")
    if report.get("physical_can_evidence") is not False:
        raise ValueError("physical CAN evidence must be disabled")
    if (
        report.get("development_only") is not True
        or report.get("formal_inference_allowed") is not False
    ):
        raise ValueError("F6 vcan report must be development-only")
    profile = report.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("F6 vcan profile is required")
    if (
        profile.get("transport_profile") != "vcan"
        or profile.get("ack_mode") != "socketcan"
        or profile.get("mock_mode") is not False
    ):
        raise ValueError("F6 report is not a vcan SocketCAN profile")
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
    if variant == "injected":
        if ack_coverage is not None:
            raise ValueError("drop ACK-frame coverage must be null")
    elif (
        not isinstance(ack_coverage, (int, float))
        or isinstance(ack_coverage, bool)
        or not 0 <= ack_coverage <= 1
    ):
        raise ValueError("invalid ack_frame_match_coverage")
    counts = report.get("count_distributions")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(name), dict) or "mean" not in counts[name]
        for name in COUNTS
    ):
        raise ValueError("missing count distributions")
    latency = report.get("terminal_latency_ns")
    if not isinstance(latency, dict) or any(
        terminal not in latency for terminal in TERMINALS
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
