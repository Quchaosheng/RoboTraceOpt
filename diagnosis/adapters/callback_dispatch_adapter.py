"""Derive an auditable publish-to-callback dispatch upper bound for F2."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.schema import NormalizedEvent


PUBLISH_EVENT = "camera_frame_published"
RECEIVE_EVENT = "planner_receive"
MEASUREMENT_SEMANTICS = "publish_to_callback_upper_bound"


def derive_callback_dispatch_evidence(
    runtime_records: Iterable[dict[str, Any]],
    tracing_records: Iterable[dict[str, Any]],
    process_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    *,
    expected_timer_period_ns: int,
    runtime_source_file: str,
    tracing_source_file: str,
    process_manifest_source_file: str,
    oracle_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if expected_timer_period_ns <= 0:
        raise ValueError("expected_timer_period_ns must be positive")
    if not all(
        (
            runtime_source_file,
            tracing_source_file,
            process_manifest_source_file,
            oracle_manifest_source_file,
        )
    ):
        raise ValueError("all source file paths are required")

    condition_variant, oracle_reason = _validate_oracle(
        oracle_manifest, expected_timer_period_ns
    )
    tracing_list = list(tracing_records)
    if oracle_reason:
        structural_gate, reason_code = {}, oracle_reason
    else:
        structural_gate, reason_code = _validate_structure(
            tracing_list,
            process_manifest,
            expected_timer_period_ns,
            condition_variant,
        )
    report: dict[str, Any] = {
        "schema_version": "callback-dispatch-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "includes_dds_transfer": True,
        "condition_variant": condition_variant,
        "status": "invalid" if reason_code else "valid",
        "reason_code": reason_code,
        "structural_gate": structural_gate,
        "runtime_source_file": runtime_source_file,
        "tracing_source_file": tracing_source_file,
        "process_manifest_source_file": process_manifest_source_file,
        "oracle_manifest_source_file": oracle_manifest_source_file,
    }
    if reason_code:
        return [], report

    published: dict[str, tuple[int, dict[str, Any]]] = {}
    received: dict[str, tuple[int, dict[str, Any]]] = {}
    for record_index, record in enumerate(runtime_records, start=1):
        trace_id = record.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id:
            continue
        event_name = record.get("event_name")
        if event_name == PUBLISH_EVENT:
            published.setdefault(trace_id, (record_index, record))
        elif event_name == RECEIVE_EVENT:
            received.setdefault(trace_id, (record_index, record))

    common_ids = set(published) & set(received)
    missing_receive = set(published) - set(received)
    missing_publish = set(received) - set(published)
    invalid_reasons: Counter[str] = Counter()
    valid_rows: list[tuple[int, str, NormalizedEvent]] = []
    delays: list[int] = []
    for trace_id in common_ids:
        publish_index, publish = published[trace_id]
        receive_index, receive = received[trace_id]
        if (
            publish.get("host_id") != receive.get("host_id")
            or publish.get("clock_id") != receive.get("clock_id")
            or publish.get("clock_id") != "monotonic"
        ):
            invalid_reasons["clock_or_host_mismatch"] += 1
            continue
        if publish.get("sequence_id") != receive.get("sequence_id"):
            invalid_reasons["trace_identity_mismatch"] += 1
            continue
        publish_ns = publish.get("timestamp_ns")
        receive_ns = receive.get("timestamp_ns")
        if (
            isinstance(publish_ns, bool)
            or not isinstance(publish_ns, int)
            or isinstance(receive_ns, bool)
            or not isinstance(receive_ns, int)
        ):
            invalid_reasons["invalid_timestamp"] += 1
            continue
        delay_ns = receive_ns - publish_ns
        if delay_ns < 0:
            invalid_reasons["negative_dispatch_interval"] += 1
            continue
        event = NormalizedEvent(
            event_id=f"derived_fusion:callback_dispatch:{trace_id}",
            source="derived_fusion",
            event_type="ros_callback_dispatch_bound",
            timestamp_ns=receive_ns,
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(receive["sequence_id"]),
            stage=str(receive.get("stage", "planner_receive")),
            pid=int(receive["pid"]),
            tid=int(receive["tid"]),
            host_id=str(receive["host_id"]),
            attributes={
                "queue_delay_ns": delay_ns,
                "callback_dispatch_upper_bound_ns": delay_ns,
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "includes_dds_transfer": True,
                "planner_timer_period_ns": expected_timer_period_ns,
            },
            provenance={
                "adapter": "callback_dispatch_fusion_v1",
                "runtime_source_file": runtime_source_file,
                "publish_record_index": publish_index,
                "receive_record_index": receive_index,
                "tracing_source_file": tracing_source_file,
                "process_manifest_source_file": process_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
                "structural_gate": dict(structural_gate),
            },
        )
        valid_rows.append((publish_ns, trace_id, event))
        delays.append(delay_ns)

    events = [event for _, _, event in sorted(valid_rows)]
    report.update(
        {
            "published_trace_count": len(published),
            "received_trace_count": len(received),
            "paired_trace_count": len(events),
            "missing_receive_count": len(missing_receive),
            "missing_publish_count": len(missing_publish),
            "invalid_pair_count": sum(invalid_reasons.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid_reasons.items())),
            "delay_ns": _describe(delays),
        }
    )
    if not events:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_dispatch_pairs"
    elif missing_receive or missing_publish or invalid_reasons:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_runtime_pairs"
    return events, report


def _validate_structure(
    tracing_records: list[dict[str, Any]],
    process_manifest: dict[str, Any],
    expected_timer_period_ns: int,
    condition_variant: str,
) -> tuple[dict[str, Any], str]:
    processes = process_manifest.get("processes", [])
    planners = [
        process
        for process in processes
        if isinstance(process, dict) and process.get("node") == "vlm_planner_node"
    ]
    if len(planners) != 1 or not isinstance(planners[0].get("pid"), int):
        return {}, "planner_process_not_observed"
    planner_pid = int(planners[0]["pid"])
    host_id = process_manifest.get("host_id")

    node_handles = {
        record.get("payload", {}).get("node_handle")
        for record in tracing_records
        if record.get("event_name") == "ros2:rcl_node_init"
        and record.get("context", {}).get("vpid") == planner_pid
        and record.get("host_id") == host_id
        and record.get("payload", {}).get("node_name") == "vlm_planner_node"
    }
    node_handles.discard(None)
    if len(node_handles) != 1:
        return {"planner_pid": planner_pid}, "planner_node_trace_not_observed"
    node_handle = next(iter(node_handles))

    subscriptions = [
        record.get("payload", {})
        for record in tracing_records
        if record.get("event_name") == "ros2:rcl_subscription_init"
        and record.get("context", {}).get("vpid") == planner_pid
        and record.get("payload", {}).get("node_handle") == node_handle
        and record.get("payload", {}).get("topic_name") == "/camera/frame"
    ]
    if len(subscriptions) != 1:
        return {
            "planner_pid": planner_pid,
            "node_handle": node_handle,
        }, "planner_subscription_not_observed"

    timers = [
        record.get("payload", {})
        for record in tracing_records
        if record.get("event_name") == "ros2:rcl_timer_init"
        and record.get("context", {}).get("vpid") == planner_pid
        and record.get("payload", {}).get("period") == expected_timer_period_ns
    ]
    base_gate = {
        "planner_pid": planner_pid,
        "node_handle": node_handle,
        "subscription_handle": subscriptions[0].get("subscription_handle"),
    }
    if condition_variant == "control":
        if timers:
            return base_gate, "unexpected_control_contention_timer"
        return {
            **base_gate,
            "timer_status": "not_observed",
            "timer_period_ns": expected_timer_period_ns,
        }, ""
    if len(timers) != 1:
        return {
            **base_gate,
            "timer_status": "not_observed",
        }, "planner_timer_not_observed"
    return {
        **base_gate,
        "timer_status": "observed",
        "timer_handle": timers[0].get("timer_handle"),
        "timer_period_ns": expected_timer_period_ns,
    }, ""


def _validate_oracle(
    oracle_manifest: dict[str, Any], expected_timer_period_ns: int
) -> tuple[str, str]:
    if oracle_manifest.get("fault_id") != "F2":
        return "", "invalid_f2_oracle"
    variant = oracle_manifest.get("condition_variant")
    if variant not in {"injected", "control"}:
        return "", "invalid_f2_oracle"
    injection = oracle_manifest.get("injection")
    if not isinstance(injection, dict):
        return str(variant), "invalid_f2_oracle"
    expected_enabled = variant == "injected"
    if injection.get("executor_contention_enabled") is not expected_enabled:
        return str(variant), "oracle_variant_mismatch"
    if injection.get("callback_period_ms") != expected_timer_period_ns // 1_000_000:
        return str(variant), "oracle_timer_period_mismatch"
    return str(variant), ""


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
    parser.add_argument("--tracing-events", type=Path, required=True)
    parser.add_argument("--process-manifest", type=Path, required=True)
    parser.add_argument("--oracle-manifest", type=Path, required=True)
    parser.add_argument("--expected-timer-period-ns", type=int, required=True)
    parser.add_argument("--output-events", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    process_manifest = json.loads(args.process_manifest.read_text(encoding="utf-8"))
    oracle_manifest = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
    events, report = derive_callback_dispatch_evidence(
        _read_jsonl(args.runtime_events),
        _read_jsonl(args.tracing_events),
        process_manifest,
        oracle_manifest,
        expected_timer_period_ns=args.expected_timer_period_ns,
        runtime_source_file=str(args.runtime_events),
        tracing_source_file=str(args.tracing_events),
        process_manifest_source_file=str(args.process_manifest),
        oracle_manifest_source_file=str(args.oracle_manifest),
    )
    report["input_sha256"] = {
        "runtime_events": _sha256(args.runtime_events),
        "tracing_events": _sha256(args.tracing_events),
        "process_manifest": _sha256(args.process_manifest),
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
