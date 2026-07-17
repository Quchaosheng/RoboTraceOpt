"""Derive non-formal RuntimeEvent timing proxies for F3."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.schema import NormalizedEvent


EVENTS = (
    "camera_frame_published",
    "planner_receive",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
)
METRICS = (
    "dispatch_upper_bound_ns",
    "zero_work_callback_elapsed_ns",
    "planner_path_upper_bound_ns",
)
MEASUREMENT_SEMANTICS = "scheduling_pressure_proxy"


def derive_scheduling_pressure_evidence(
    runtime_records: Iterable[dict[str, Any]],
    process_manifest: dict[str, Any],
    scheduler_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    *,
    runtime_source_file: str,
    process_manifest_source_file: str,
    scheduler_manifest_source_file: str,
    oracle_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if not all(
        (
            runtime_source_file,
            process_manifest_source_file,
            scheduler_manifest_source_file,
            oracle_manifest_source_file,
        )
    ):
        raise ValueError("all source file paths are required")
    variant, injection, oracle_reason = _validate_oracle(oracle_manifest)
    if oracle_reason:
        gate, reason_code = {}, oracle_reason
    else:
        gate, reason_code = _validate_structure(
            process_manifest, scheduler_manifest, variant, injection
        )
    host_class = (
        "wsl"
        if "microsoft" in str(process_manifest.get("osrelease", "")).lower()
        else "native_linux"
    )
    report: dict[str, Any] = {
        "schema_version": "scheduling-pressure-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "formal_scheduling_attribution": False,
        "development_only": True,
        "condition_variant": variant,
        "status": "invalid" if reason_code else "valid",
        "reason_code": reason_code,
        "structural_gate": gate,
        "ebpf_identity_status": process_manifest.get("ebpf_identity_status", ""),
        "profile": {
            "git_commit": process_manifest.get("git_commit", ""),
            "host_id": process_manifest.get("host_id", ""),
            "host_class": host_class,
            "target_cpu": injection.get("target_cpu"),
            "input_rate_hz": injection.get("input_rate_hz"),
            "cpu_load_percent": injection.get("cpu_load_percent"),
            "cpu_method": injection.get("cpu_method"),
            "tracing_required": True,
        },
        "runtime_source_file": runtime_source_file,
        "process_manifest_source_file": process_manifest_source_file,
        "scheduler_manifest_source_file": scheduler_manifest_source_file,
        "oracle_manifest_source_file": oracle_manifest_source_file,
    }
    if reason_code:
        return [], report

    by_trace: dict[str, dict[str, tuple[int, dict[str, Any]]]] = {}
    for index, record in enumerate(runtime_records, start=1):
        trace_id = record.get("trace_id")
        event_name = record.get("event_name")
        if isinstance(trace_id, str) and trace_id and event_name in EVENTS:
            by_trace.setdefault(trace_id, {}).setdefault(event_name, (index, record))

    missing_counts: Counter[str] = Counter()
    invalid_reasons: Counter[str] = Counter()
    metric_values: dict[str, list[int]] = {metric: [] for metric in METRICS}
    valid_rows: list[tuple[int, str, NormalizedEvent]] = []
    for trace_id, trace_events in by_trace.items():
        missing = [event_name for event_name in EVENTS if event_name not in trace_events]
        if missing:
            missing_counts.update(missing)
            continue
        records = {name: trace_events[name][1] for name in EVENTS}
        host_ids = {record.get("host_id") for record in records.values()}
        clock_ids = {record.get("clock_id") for record in records.values()}
        if len(host_ids) != 1 or clock_ids != {"monotonic"}:
            invalid_reasons["clock_or_host_mismatch"] += 1
            continue
        sequence_ids = {record.get("sequence_id") for record in records.values()}
        if len(sequence_ids) != 1:
            invalid_reasons["trace_identity_mismatch"] += 1
            continue
        timestamps = {
            name: records[name].get("timestamp_ns") for name in EVENTS
        }
        if any(not _integer(value) for value in timestamps.values()):
            invalid_reasons["invalid_timestamp"] += 1
            continue
        values = {
            "dispatch_upper_bound_ns": (
                timestamps["planner_receive"] - timestamps["camera_frame_published"]
            ),
            "zero_work_callback_elapsed_ns": (
                timestamps["planner_process_end"] - timestamps["planner_process_start"]
            ),
            "planner_path_upper_bound_ns": (
                timestamps["planner_publish"] - timestamps["camera_frame_published"]
            ),
        }
        if any(value < 0 for value in values.values()):
            invalid_reasons["negative_proxy_interval"] += 1
            continue
        receive = records["planner_receive"]
        event = NormalizedEvent(
            event_id=f"derived_fusion:scheduling_pressure:{trace_id}",
            source="derived_fusion",
            event_type="scheduling_pressure_proxy",
            timestamp_ns=int(timestamps["planner_publish"]),
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(receive["sequence_id"]),
            stage="planner_publish",
            pid=int(receive["pid"]),
            tid=int(receive["tid"]),
            host_id=str(receive["host_id"]),
            attributes={
                **values,
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "formal_scheduling_attribution": False,
                "target_cpu": int(injection["target_cpu"]),
                "stress_enabled": bool(injection["stress_enabled"]),
            },
            provenance={
                "adapter": "scheduling_pressure_proxy_v1",
                "runtime_source_file": runtime_source_file,
                "record_indices": {
                    name: trace_events[name][0] for name in EVENTS
                },
                "process_manifest_source_file": process_manifest_source_file,
                "scheduler_manifest_source_file": scheduler_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
                "structural_gate": dict(gate),
            },
        )
        valid_rows.append(
            (int(timestamps["camera_frame_published"]), trace_id, event)
        )
        for metric, value in values.items():
            metric_values[metric].append(value)

    events = [event for _, _, event in sorted(valid_rows)]
    incomplete_trace_count = sum(
        1 for trace in by_trace.values() if any(name not in trace for name in EVENTS)
    )
    report.update(
        {
            "observed_trace_count": len(by_trace),
            "complete_trace_count": len(events),
            "incomplete_trace_count": incomplete_trace_count,
            "missing_event_counts": dict(sorted(missing_counts.items())),
            "invalid_pair_count": sum(invalid_reasons.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid_reasons.items())),
            "metrics_ns": {
                metric: _describe(values) for metric, values in metric_values.items()
            },
        }
    )
    if not events:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_proxy_traces"
    elif report["incomplete_trace_count"] or invalid_reasons:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_runtime_traces"
    return events, report


def _validate_oracle(
    oracle: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    if oracle.get("fault_id") != "F3":
        return "", {}, "invalid_f3_oracle"
    variant = oracle.get("condition_variant")
    if variant not in {"injected", "control"}:
        return "", {}, "invalid_f3_oracle"
    injection = oracle.get("injection")
    if not isinstance(injection, dict):
        return str(variant), {}, "invalid_f3_oracle"
    expected = {
        "stressors": 1,
        "cpu_load_percent": 90,
        "cpu_method": "matrixprod",
        "input_rate_hz": 100,
        "affinity": "same_cpu",
        "scheduler_policy": "SCHED_OTHER",
        "scheduler_priority": 0,
        "stress_enabled": variant == "injected",
    }
    if any(injection.get(key) != value for key, value in expected.items()):
        return str(variant), dict(injection), "oracle_profile_mismatch"
    if not _integer(injection.get("target_cpu")) or injection["target_cpu"] < 0:
        return str(variant), dict(injection), "oracle_target_cpu_invalid"
    expected_cause = "scheduling_delay" if variant == "injected" else "none"
    if oracle.get("cause_id") != expected_cause:
        return str(variant), dict(injection), "oracle_variant_mismatch"
    return str(variant), dict(injection), ""


def _validate_structure(
    process: dict[str, Any],
    scheduler: dict[str, Any],
    variant: str,
    injection: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if process.get("schema_version") != "process-manifest/v2":
        return {}, "invalid_process_manifest"
    if scheduler.get("schema_version") != "f3-scheduler-manifest/v1":
        return {}, "invalid_scheduler_manifest"
    if scheduler.get("condition_variant") != variant:
        return {}, "scheduler_variant_mismatch"
    if scheduler.get("target_cpu") != injection["target_cpu"]:
        return {}, "scheduler_target_cpu_mismatch"
    if scheduler.get("host_id") != process.get("host_id"):
        return {}, "scheduler_host_mismatch"
    if scheduler.get("git_commit") != process.get("git_commit"):
        return {}, "scheduler_commit_mismatch"
    if scheduler.get("ebpf_identity_status") != process.get("ebpf_identity_status"):
        return {}, "scheduler_ebpf_identity_mismatch"

    target_cpu = int(injection["target_cpu"])
    ros_processes = scheduler.get("ros_processes")
    if not isinstance(ros_processes, dict) or not {
        "camera_mock_node", "vlm_planner_node"
    } <= set(ros_processes):
        return {}, "required_ros_process_not_observed"
    if not all(_valid_snapshot(snapshot, target_cpu) for snapshot in ros_processes.values()):
        return {}, "ros_affinity_mismatch"

    stress = scheduler.get("stress")
    if not isinstance(stress, dict) or stress.get("enabled") is not (
        variant == "injected"
    ):
        return {}, "stressor_variant_mismatch"
    stress_pids = stress.get("pids")
    stress_processes = stress.get("processes")
    if variant == "injected":
        if not isinstance(stress_pids, list) or not stress_pids:
            return {}, "stressor_not_observed"
        if not isinstance(stress_processes, dict) or not stress_processes:
            return {}, "stressor_not_observed"
        if not all(
            _valid_snapshot(snapshot, target_cpu)
            for snapshot in stress_processes.values()
        ):
            return {}, "stressor_affinity_mismatch"
        if stress.get("cleanup_status") != "graceful_sigint":
            return {}, "stressor_cleanup_invalid"
    elif stress_pids or stress_processes or stress.get("command"):
        return {}, "unexpected_control_stressor"
    return {
        "target_cpu": target_cpu,
        "ros_process_count": len(ros_processes),
        "stress_process_count": len(stress_pids or []),
        "scheduler_policy": "SCHED_OTHER",
        "scheduler_priority": 0,
        "ebpf_identity_status": process.get("ebpf_identity_status"),
    }, ""


def _valid_snapshot(snapshot: Any, target_cpu: int) -> bool:
    return (
        isinstance(snapshot, dict)
        and snapshot.get("allowed_cpus") == [target_cpu]
        and snapshot.get("policy") == "SCHED_OTHER"
        and snapshot.get("priority") == 0
    )


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _describe(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": _quantile(ordered, 0.5),
        "p90": _quantile(ordered, 0.9),
        "p95": _quantile(ordered, 0.95),
        "p99": _quantile(ordered, 0.99),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def _quantile(values: list[int], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-events", type=Path, required=True)
    parser.add_argument("--process-manifest", type=Path, required=True)
    parser.add_argument("--scheduler-manifest", type=Path, required=True)
    parser.add_argument("--oracle-manifest", type=Path, required=True)
    parser.add_argument("--output-events", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    process = json.loads(args.process_manifest.read_text(encoding="utf-8"))
    scheduler = json.loads(args.scheduler_manifest.read_text(encoding="utf-8"))
    oracle = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
    events, report = derive_scheduling_pressure_evidence(
        _read_jsonl(args.runtime_events),
        process,
        scheduler,
        oracle,
        runtime_source_file=str(args.runtime_events),
        process_manifest_source_file=str(args.process_manifest),
        scheduler_manifest_source_file=str(args.scheduler_manifest),
        oracle_manifest_source_file=str(args.oracle_manifest),
    )
    report["input_sha256"] = {
        "runtime_events": _sha256(args.runtime_events),
        "process_manifest": _sha256(args.process_manifest),
        "scheduler_manifest": _sha256(args.scheduler_manifest),
        "oracle_manifest": _sha256(args.oracle_manifest),
    }
    args.output_events.parent.mkdir(parents=True, exist_ok=True)
    with args.output_events.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
