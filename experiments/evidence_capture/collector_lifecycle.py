"""Pure lifecycle contracts for formal evidence collectors."""

from __future__ import annotations

import copy
import signal
from collections.abc import Collection
from pathlib import Path
from typing import Any


class EvidenceCaptureError(RuntimeError):
    """A stable collector lifecycle failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def needs_process_manifest(capabilities: Collection[str]) -> bool:
    return bool({"ros2_tracing", "ebpf"} & set(capabilities))


def remaining_capture_duration(
    duration_seconds: float,
    elapsed_startup: float,
    *,
    shutdown_margin: float = 0.5,
) -> float:
    values = (duration_seconds, elapsed_startup, shutdown_margin)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise EvidenceCaptureError(
            "insufficient_ebpf_window", "capture timing values must be numeric"
        )
    if duration_seconds <= 0 or elapsed_startup < 0 or shutdown_margin < 0:
        raise EvidenceCaptureError(
            "insufficient_ebpf_window", "capture timing values are invalid"
        )
    remaining = round(duration_seconds - elapsed_startup - shutdown_margin, 3)
    if remaining < 1.0:
        raise EvidenceCaptureError(
            "insufficient_ebpf_window", "less than one second remains for eBPF capture"
        )
    return remaining


def validate_ebpf_identity(process_manifest: dict[str, Any]) -> None:
    if (
        not isinstance(process_manifest, dict)
        or process_manifest.get("schema_version") != "process-manifest/v2"
    ):
        raise EvidenceCaptureError(
            "process_manifest_invalid", "eBPF requires process-manifest/v2"
        )
    if process_manifest.get("ebpf_identity_status") != "comparable":
        raise EvidenceCaptureError(
            "identity_domain_not_comparable", "eBPF process identity is not comparable"
        )
    processes = process_manifest.get("processes")
    if not isinstance(processes, list) or not processes:
        raise EvidenceCaptureError(
            "process_manifest_invalid", "eBPF process manifest is empty"
        )


def build_ebpf_capture_argv(
    *,
    python: Path,
    script: Path,
    process_manifest: Path,
    duration: float,
    output: Path,
    summary_output: Path,
) -> list[str]:
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration < 1
    ):
        raise EvidenceCaptureError(
            "insufficient_ebpf_window", "eBPF duration must be at least one second"
        )
    return [
        str(python),
        str(script),
        "--process-manifest",
        str(process_manifest),
        "--duration",
        f"{duration:.3f}".rstrip("0").rstrip("."),
        "--output",
        str(output),
        "--summary-output",
        str(summary_output),
    ]


def validate_ebpf_summary(value: dict[str, Any], *, fault_id: str) -> dict[str, Any]:
    if fault_id not in {"F3", "F4"}:
        raise EvidenceCaptureError(
            "ebpf_fault_unsupported", f"eBPF capture is not registered for {fault_id}"
        )
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "ebpf-capture-summary/v1"
        or value.get("collector") != "bpftrace"
    ):
        raise EvidenceCaptureError(
            "ebpf_summary_invalid", "unsupported eBPF capture summary"
        )
    returncode = value.get("bpftrace_returncode")
    if returncode not in {0, 130, -signal.SIGINT}:
        raise EvidenceCaptureError(
            "ebpf_collector_failed", "bpftrace collector did not exit successfully"
        )
    malformed = value.get("malformed_line_count")
    if isinstance(malformed, bool) or not isinstance(malformed, int) or malformed != 0:
        raise EvidenceCaptureError(
            "ebpf_events_malformed", "eBPF capture contains malformed events"
        )
    event_count = value.get("event_count")
    if (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count < 1
    ):
        raise EvidenceCaptureError(
            "ebpf_events_missing", "eBPF capture contains no target events"
        )
    counts = value.get("counts_by_type")
    if (
        not isinstance(counts, dict)
        or any(
            not isinstance(name, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for name, count in counts.items()
        )
        or sum(counts.values()) != event_count
    ):
        raise EvidenceCaptureError(
            "ebpf_summary_invalid", "eBPF event counts are invalid"
        )
    if (
        fault_id == "F3"
        and counts.get("sched_switch", 0) + counts.get("sched_wakeup", 0) < 1
    ):
        raise EvidenceCaptureError(
            "ebpf_scheduler_events_missing", "F3 requires scheduler events"
        )
    if fault_id == "F4" and counts.get("syscall", 0) < 1:
        raise EvidenceCaptureError(
            "ebpf_syscall_events_missing", "F4 requires syscall events"
        )
    return copy.deepcopy(value)
