#!/usr/bin/env python3
"""Export a bounded JSON fixture from a real ROS 2 CTF trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_EVENTS = (
    "ros2:rcl_init",
    "ros2:rcl_node_init",
    "ros2:rcl_publisher_init",
    "ros2:rcl_subscription_init",
    "ros2:rcl_service_init",
    "ros2:rcl_timer_init",
    "ros2:rclcpp_subscription_init",
    "ros2:rclcpp_subscription_callback_added",
    "ros2:rclcpp_timer_callback_added",
    "ros2:rclcpp_timer_link_node",
    "ros2:rclcpp_service_callback_added",
    "ros2:rclcpp_callback_register",
    "ros2:rmw_take",
    "ros2:rcl_take",
    "ros2:rclcpp_take",
    "ros2:rclcpp_publish",
    "ros2:rcl_publish",
    "ros2:callback_start",
    "ros2:callback_end",
    "ros2:rclcpp_executor_wait_for_work",
    "ros2:rclcpp_executor_execute",
)


def select_records(
    records: Iterable[dict[str, Any]], *, max_per_event: int
) -> list[dict[str, Any]]:
    if max_per_event < 1:
        raise ValueError("max_per_event must be positive")
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for position, record in enumerate(records):
        event_name = str(record["event_name"])
        grouped.setdefault(event_name, []).append((position, record))

    selected: list[tuple[int, dict[str, Any]]] = []
    for group in grouped.values():
        if len(group) <= max_per_event:
            selected.extend(group)
            continue
        if max_per_event == 1:
            selected.append(group[0])
            continue
        indices = {
            round(index * (len(group) - 1) / (max_per_event - 1))
            for index in range(max_per_event)
        }
        selected.extend(group[index] for index in sorted(indices))
    return [record for _, record in sorted(selected, key=lambda item: item[0])]


def field_to_python(field: Any) -> Any:
    if field is None or isinstance(field, (bool, int, float, str)):
        return field
    if hasattr(field, "items"):
        return {str(key): field_to_python(value) for key, value in field.items()}

    type_name = type(field).__name__
    if "String" in type_name:
        return str(field)
    if "Bool" in type_name:
        return bool(field)
    if "Integer" in type_name or "Enumeration" in type_name:
        return int(field)
    if "Real" in type_name:
        return float(field)
    if hasattr(field, "__iter__"):
        return [field_to_python(value) for value in field]
    return str(field)


def trace_records(
    trace_path: Path, *, event_names: set[str], host_id: str
) -> Iterable[dict[str, Any]]:
    try:
        import bt2
    except ImportError as error:
        raise RuntimeError("bt2 is required to export a CTF fixture") from error

    iterator = bt2.TraceCollectionMessageIterator(str(trace_path))
    for message in iterator:
        if not isinstance(message, bt2._EventMessageConst):
            continue
        event = message.event
        if event.name not in event_names or message.default_clock_snapshot is None:
            continue

        snapshot = message.default_clock_snapshot
        clock_class = snapshot.clock_class
        offset = clock_class.offset
        context = field_to_python(event.common_context_field) or {}
        packet_context = field_to_python(event.packet.context_field) or {}
        if "cpu_id" in packet_context:
            context["cpu_id"] = packet_context["cpu_id"]

        yield {
            "event_name": event.name,
            "host_id": host_id,
            "clock": {
                "name": clock_class.name or "",
                "frequency": int(clock_class.frequency),
                "value": int(snapshot.value),
                "ns_from_origin": int(snapshot.ns_from_origin),
                "offset_seconds": int(offset.seconds),
                "offset_cycles": int(offset.cycles),
                "origin_is_unix_epoch": bool(clock_class.origin_is_unix_epoch),
            },
            "context": context,
            "payload": field_to_python(event.payload_field) or {},
        }


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--event", action="append", default=[])
    parser.add_argument("--max-per-event", type=int, default=8)
    parser.add_argument("--host-id", default=socket.gethostname())
    parser.add_argument("--tracetools-source-commit", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.trace.is_dir():
        raise FileNotFoundError(f"trace directory is missing: {args.trace}")
    event_names = set(args.event or DEFAULT_EVENTS)
    records = select_records(
        trace_records(args.trace, event_names=event_names, host_id=args.host_id),
        max_per_event=args.max_per_event,
    )
    if not records:
        raise RuntimeError("the trace did not contain any selected ROS 2 events")

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.output_jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    event_counts = Counter(str(record["event_name"]) for record in records)
    clock_classes = {
        (
            record["clock"]["name"],
            record["clock"]["frequency"],
            record["clock"]["offset_seconds"],
            record["clock"]["offset_cycles"],
        )
        for record in records
    }
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "real_w1_ros2_tracing_smoke",
        "source_trace": str(args.trace),
        "source_trace_sha256": directory_sha256(args.trace),
        "tracetools_source_commit": args.tracetools_source_commit,
        "host_id": args.host_id,
        "event_count": len(records),
        "event_counts": dict(sorted(event_counts.items())),
        "clock_classes": [
            {
                "name": name,
                "frequency": frequency,
                "offset_seconds": offset_seconds,
                "offset_cycles": offset_cycles,
            }
            for name, frequency, offset_seconds, offset_cycles in sorted(clock_classes)
        ],
    }
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
