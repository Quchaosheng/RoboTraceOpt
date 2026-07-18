"""Validate that a workload smoke run emitted its required semantic stages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_EVENTS: dict[str, set[str]] = {
    "w1": {
        "camera_frame_published",
        "planner_receive",
        "planner_process_start",
        "planner_process_end",
        "planner_publish",
        "action_goal_received",
        "action_goal_accepted",
        "action_execute_start",
        "action_execute_end",
        "action_result",
        "can_command_received",
        "can_frame_sent",
        "can_ack_wait_start",
        "can_ack_received",
    },
    "w2": {
        "query_sent",
        "service_receive",
        "service_process_start",
        "service_process_end",
        "service_response",
        "response_received",
    },
    "w3": {
        "input_publish",
        "planner_receive",
        "planner_process_start",
        "planner_process_end",
        "planner_publish",
        "action_receive",
        "action_start",
        "action_end",
        "action_publish",
        "control_receive",
        "control_send_start",
        "control_send_end",
    },
}

REQUIRED_V2_FIELDS = {
    "pid",
    "tid",
    "host_id",
    "clock_id",
    "duration_ns",
    "status",
    "reason_code",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"smoke output is missing: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid JSON at line {line_number}: {error.msg}"
                ) from error
            if not isinstance(row, dict):
                raise ValueError(f"JSON value at line {line_number} is not an object")
            rows.append(row)
    return rows


def check_smoke_output(
    workload: str, path: Path, minimum_traces: int = 1
) -> dict[str, Any]:
    if workload not in REQUIRED_EVENTS:
        raise ValueError(f"unknown workload: {workload}")
    if minimum_traces < 1:
        raise ValueError("minimum_traces must be at least 1")

    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"smoke output is empty: {path}")

    for row_number, row in enumerate(rows, start=1):
        missing_fields = sorted(REQUIRED_V2_FIELDS - row.keys())
        if missing_fields:
            raise ValueError(
                f"v2 event {row_number} is missing fields: {', '.join(missing_fields)}"
            )
        if int(row["pid"]) <= 0 or int(row["tid"]) <= 0:
            raise ValueError(f"v2 event {row_number} has invalid pid/tid")
        if not str(row["host_id"]):
            raise ValueError(f"v2 event {row_number} has an empty host_id")
        if row["clock_id"] != "monotonic":
            raise ValueError(
                f"v2 event {row_number} uses unsupported clock_id={row['clock_id']!r}"
            )
        if not str(row["status"]):
            raise ValueError(f"v2 event {row_number} has an empty status")

    event_names = {
        str(row.get("event_name", "")) for row in rows if row.get("event_name")
    }
    trace_ids = {str(row.get("trace_id", "")) for row in rows if row.get("trace_id")}
    missing_events = sorted(REQUIRED_EVENTS[workload] - event_names)
    if missing_events:
        raise ValueError(
            f"{workload} is missing required events: {', '.join(missing_events)}"
        )
    if len(trace_ids) < minimum_traces:
        raise ValueError(
            f"{workload} has {len(trace_ids)} traces; expected at least {minimum_traces}"
        )

    timestamps = [
        int(row["timestamp_ns"]) for row in rows if row.get("timestamp_ns") is not None
    ]
    host_ids = sorted({str(row["host_id"]) for row in rows})
    clock_ids = sorted({str(row["clock_id"]) for row in rows})
    process_ids = {int(row["pid"]) for row in rows}
    thread_ids = {int(row["tid"]) for row in rows}
    return {
        "workload": workload,
        "input": str(path.resolve()),
        "event_count": len(rows),
        "trace_count": len(trace_ids),
        "event_names": sorted(event_names),
        "missing_events": missing_events,
        "host_ids": host_ids,
        "clock_ids": clock_ids,
        "process_count": len(process_ids),
        "thread_count": len(thread_ids),
        "first_timestamp_ns": min(timestamps) if timestamps else None,
        "last_timestamp_ns": max(timestamps) if timestamps else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", choices=sorted(REQUIRED_EVENTS), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--minimum-traces", type=int, default=1)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = check_smoke_output(args.workload, args.input, args.minimum_traces)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
