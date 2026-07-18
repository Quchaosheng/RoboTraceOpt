"""Derive auditable publish-to-receive delivery bounds for F5."""

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
MEASUREMENT_SEMANTICS = "publish_to_receive_upper_bound"


def derive_dds_pressure_evidence(
    runtime_records: Iterable[dict[str, Any]],
    tracing_records: Iterable[dict[str, Any]],
    process_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    *,
    runtime_source_file: str,
    tracing_source_file: str,
    process_manifest_source_file: str,
    oracle_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if not all(
        (
            runtime_source_file,
            tracing_source_file,
            process_manifest_source_file,
            oracle_manifest_source_file,
        )
    ):
        raise ValueError("all source file paths are required")

    variant, injection, oracle_reason = _validate_oracle(oracle_manifest)
    if oracle_reason:
        structural_gate, reason_code = {}, oracle_reason
    else:
        structural_gate, reason_code = _validate_structure(
            list(tracing_records), process_manifest, injection
        )
    report: dict[str, Any] = {
        "schema_version": "dds-pressure-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "includes_executor_wait": True,
        "condition_variant": variant,
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
        if record.get("event_name") == PUBLISH_EVENT:
            published.setdefault(trace_id, (record_index, record))
        elif record.get("event_name") == RECEIVE_EVENT:
            received.setdefault(trace_id, (record_index, record))

    missing_receive = set(published) - set(received)
    missing_publish = set(received) - set(published)
    invalid_reasons: Counter[str] = Counter()
    valid_rows: list[tuple[int, str, NormalizedEvent]] = []
    delays: list[int] = []
    for trace_id in set(published) & set(received):
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
        if not _integer(publish_ns) or not _integer(receive_ns):
            invalid_reasons["invalid_timestamp"] += 1
            continue
        duration_ns = receive_ns - publish_ns
        if duration_ns < 0:
            invalid_reasons["negative_delivery_interval"] += 1
            continue
        event = NormalizedEvent(
            event_id=f"derived_fusion:dds_delivery:{trace_id}",
            source="derived_fusion",
            event_type="dds_delivery_bound",
            timestamp_ns=receive_ns,
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(receive["sequence_id"]),
            stage=str(receive.get("stage", RECEIVE_EVENT)),
            pid=int(receive["pid"]),
            tid=int(receive["tid"]),
            host_id=str(receive["host_id"]),
            attributes={
                "duration_ns": duration_ns,
                "delivery_upper_bound_ns": duration_ns,
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "includes_executor_wait": True,
                "payload_bytes": int(injection["payload_bytes"]),
                "publisher_depth": int(injection["publisher_depth"]),
                "subscriber_depth": int(injection["subscriber_depth"]),
                "reliability": str(injection["reliability"]),
            },
            provenance={
                "adapter": "dds_pressure_fusion_v1",
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
        delays.append(duration_ns)

    events = [event for _, _, event in sorted(valid_rows)]
    report.update(
        {
            "published_trace_count": len(published),
            "received_trace_count": len(received),
            "paired_trace_count": len(events),
            "missing_receive_count": len(missing_receive),
            "missing_publish_count": len(missing_publish),
            "received_sequence_gap_count": _sequence_gap_count(received),
            "invalid_pair_count": sum(invalid_reasons.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid_reasons.items())),
            "delay_ns": _describe(delays),
            "qos": dict(injection),
        }
    )
    if not events:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_delivery_pairs"
    elif missing_receive or missing_publish or invalid_reasons:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_runtime_pairs"
    return events, report


def _validate_oracle(
    oracle_manifest: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    if oracle_manifest.get("fault_id") != "F5":
        return "", {}, "invalid_f5_oracle"
    variant = oracle_manifest.get("condition_variant")
    if variant not in {"injected", "control"}:
        return "", {}, "invalid_f5_oracle"
    injection = oracle_manifest.get("injection")
    if not isinstance(injection, dict):
        return str(variant), {}, "invalid_f5_oracle"
    expected = {
        "input_rate_hz": 100,
        "payload_bytes": 262144,
        "reliability": "reliable",
        "history": "keep_last",
        "durability": "volatile",
        "publisher_depth": 1 if variant == "injected" else 10,
        "subscriber_depth": 1 if variant == "injected" else 10,
    }
    if any(injection.get(key) != value for key, value in expected.items()):
        return str(variant), dict(injection), "oracle_profile_mismatch"
    expected_cause = "dds_communication_delay" if variant == "injected" else "none"
    if oracle_manifest.get("cause_id") != expected_cause:
        return str(variant), dict(injection), "oracle_variant_mismatch"
    return str(variant), dict(injection), ""


def _validate_structure(
    tracing_records: list[dict[str, Any]],
    process_manifest: dict[str, Any],
    injection: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    processes = process_manifest.get("processes", [])
    camera_pid = _single_process_pid(processes, "camera_mock_node")
    planner_pid = _single_process_pid(processes, "vlm_planner_node")
    if camera_pid is None:
        return {}, "camera_process_not_observed"
    if planner_pid is None:
        return {"camera_pid": camera_pid}, "planner_process_not_observed"
    host_id = process_manifest.get("host_id")
    camera_handle = _node_handle(
        tracing_records, camera_pid, host_id, "camera_mock_node"
    )
    planner_handle = _node_handle(
        tracing_records, planner_pid, host_id, "vlm_planner_node"
    )
    base = {"camera_pid": camera_pid, "planner_pid": planner_pid}
    if camera_handle is None:
        return base, "camera_node_trace_not_observed"
    if planner_handle is None:
        return {
            **base,
            "camera_node_handle": camera_handle,
        }, "planner_node_trace_not_observed"

    publishers = _topic_endpoints(
        tracing_records,
        "ros2:rcl_publisher_init",
        camera_pid,
        camera_handle,
    )
    subscriptions = _topic_endpoints(
        tracing_records,
        "ros2:rcl_subscription_init",
        planner_pid,
        planner_handle,
    )
    if len(publishers) != 1:
        return base, "camera_publisher_not_observed"
    if len(subscriptions) != 1:
        return base, "planner_subscription_not_observed"
    publisher_depth = publishers[0].get("queue_depth")
    subscriber_depth = subscriptions[0].get("queue_depth")
    gate = {
        **base,
        "camera_node_handle": camera_handle,
        "planner_node_handle": planner_handle,
        "publisher_handle": publishers[0].get("publisher_handle"),
        "subscription_handle": subscriptions[0].get("subscription_handle"),
        "publisher_depth": publisher_depth,
        "subscriber_depth": subscriber_depth,
    }
    if (
        publisher_depth != injection["publisher_depth"]
        or subscriber_depth != injection["subscriber_depth"]
    ):
        return gate, "endpoint_depth_mismatch"
    return gate, ""


def _single_process_pid(processes: Any, node: str) -> int | None:
    matches = (
        [
            process.get("pid")
            for process in processes
            if isinstance(process, dict)
            and process.get("node") == node
            and _integer(process.get("pid"))
        ]
        if isinstance(processes, list)
        else []
    )
    return int(matches[0]) if len(matches) == 1 else None


def _node_handle(
    records: list[dict[str, Any]], pid: int, host_id: Any, node_name: str
) -> Any:
    handles = {
        record.get("payload", {}).get("node_handle")
        for record in records
        if record.get("event_name") == "ros2:rcl_node_init"
        and record.get("context", {}).get("vpid") == pid
        and record.get("host_id") == host_id
        and record.get("payload", {}).get("node_name") == node_name
    }
    handles.discard(None)
    return next(iter(handles)) if len(handles) == 1 else None


def _topic_endpoints(
    records: list[dict[str, Any]], event_name: str, pid: int, node_handle: Any
) -> list[dict[str, Any]]:
    return [
        record.get("payload", {})
        for record in records
        if record.get("event_name") == event_name
        and record.get("context", {}).get("vpid") == pid
        and record.get("payload", {}).get("node_handle") == node_handle
        and record.get("payload", {}).get("topic_name") == "/camera/frame"
    ]


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sequence_gap_count(records: dict[str, tuple[int, dict[str, Any]]]) -> int:
    sequence_ids = sorted(
        {
            int(record["sequence_id"])
            for _, record in records.values()
            if _integer(record.get("sequence_id"))
        }
    )
    return sum(
        max(0, current - previous - 1)
        for previous, current in zip(sequence_ids, sequence_ids[1:])
    )


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
    parser.add_argument("--output-events", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    process_manifest = json.loads(args.process_manifest.read_text(encoding="utf-8"))
    oracle_manifest = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
    events, report = derive_dds_pressure_evidence(
        _read_jsonl(args.runtime_events),
        _read_jsonl(args.tracing_events),
        process_manifest,
        oracle_manifest,
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
