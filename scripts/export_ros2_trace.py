#!/usr/bin/env python3
"""Export all selected ROS 2 CTF events for formal analysis."""

from __future__ import annotations

import argparse
import json
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.export_tracetools_fixture import (
    DEFAULT_EVENTS,
    directory_sha256,
    trace_records,
)


EXPORT_SCHEMA = "ros2-trace-export/v1"
FAULT_REQUIRED_EVENTS = {
    "F2": {"ros2:callback_start", "ros2:callback_end"},
    "F3": {"ros2:callback_start", "ros2:callback_end"},
    "F5": {"ros2:rclcpp_publish", "ros2:rmw_take"},
}
CLOCK_FIELDS = {
    "name",
    "frequency",
    "value",
    "ns_from_origin",
    "offset_seconds",
    "offset_cycles",
    "origin_is_unix_epoch",
}


def export_records(
    records: Iterable[dict[str, Any]],
    *,
    trace_path: Path,
    output_jsonl: Path,
    output_manifest: Path,
    host_id: str,
    required_events: set[str],
    generated_at_utc: str,
) -> dict[str, Any]:
    if not trace_path.is_dir():
        raise ValueError("source trace must be a directory")
    if output_jsonl.exists() or output_manifest.exists():
        raise ValueError("trace export output already exists")
    if not host_id or not generated_at_utc or not required_events:
        raise ValueError("host, timestamp, and required events are required")

    rows = list(records)
    if not rows:
        raise ValueError("trace export requires at least one event")
    counts: Counter[str] = Counter()
    clock_classes = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("trace records must be JSON objects")
        event_name = row.get("event_name")
        if not isinstance(event_name, str) or not event_name:
            raise ValueError("trace event name is required")
        if row.get("host_id") != host_id:
            raise ValueError("trace record host does not match")
        clock = row.get("clock")
        if not isinstance(clock, dict) or not CLOCK_FIELDS <= set(clock):
            raise ValueError("trace record clock is incomplete")
        if (
            not isinstance(clock["frequency"], int)
            or isinstance(clock["frequency"], bool)
            or clock["frequency"] <= 0
        ):
            raise ValueError("trace record clock frequency is invalid")
        counts[event_name] += 1
        clock_classes.add(
            (
                str(clock["name"]),
                int(clock["frequency"]),
                int(clock["offset_seconds"]),
                int(clock["offset_cycles"]),
            )
        )
    missing = required_events - set(counts)
    if missing:
        raise ValueError(f"trace is missing required events: {sorted(missing)}")

    manifest = {
        "schema_version": EXPORT_SCHEMA,
        "generated_at_utc": generated_at_utc,
        "source_trace": str(trace_path),
        "source_trace_sha256": directory_sha256(trace_path),
        "host_id": host_id,
        "required_events": sorted(required_events),
        "event_count": len(rows),
        "event_counts": dict(sorted(counts.items())),
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
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    jsonl_temporary = output_jsonl.with_name(output_jsonl.name + ".tmp")
    manifest_temporary = output_manifest.with_name(output_manifest.name + ".tmp")
    try:
        with jsonl_temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        manifest_temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        jsonl_temporary.replace(output_jsonl)
        manifest_temporary.replace(output_manifest)
    finally:
        jsonl_temporary.unlink(missing_ok=True)
        manifest_temporary.unlink(missing_ok=True)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-id", choices=sorted(FAULT_REQUIRED_EVENTS), required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--host-id", default=socket.gethostname())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = export_records(
        trace_records(
            args.trace,
            event_names=set(DEFAULT_EVENTS),
            host_id=args.host_id,
        ),
        trace_path=args.trace,
        output_jsonl=args.output_jsonl,
        output_manifest=args.output_manifest,
        host_id=args.host_id,
        required_events=FAULT_REQUIRED_EVENTS[args.fault_id],
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
