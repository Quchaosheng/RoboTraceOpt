"""Normalize exported ros2_tracing/tracetools records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from diagnosis.adapters.errors import AdapterReject
from diagnosis.schema import NormalizedEvent


def adapt_tracetools_record(
    record: dict[str, Any], *, source_file: str, record_index: int
) -> NormalizedEvent:
    missing = sorted(
        {"event_name", "host_id", "clock", "context", "payload"} - record.keys()
    )
    if missing:
        raise AdapterReject(
            "missing_required_field", "missing fields: " + ", ".join(missing)
        )
    if not source_file or record_index < 0:
        raise AdapterReject(
            "invalid_provenance", "source_file and record_index are required"
        )
    if not isinstance(record["clock"], dict):
        raise AdapterReject("invalid_clock", "clock must be an object")
    if not isinstance(record["context"], dict) or not isinstance(
        record["payload"], dict
    ):
        raise AdapterReject("invalid_field_type", "context and payload must be objects")

    event_name = record["event_name"]
    host_id = record["host_id"]
    if not isinstance(event_name, str) or not event_name.startswith("ros2:"):
        raise AdapterReject(
            "invalid_event_type", "event_name must use the ros2: namespace"
        )
    if not isinstance(host_id, str) or not host_id or host_id == "unknown":
        raise AdapterReject("invalid_runtime_identity", "host_id must be known")

    clock = record["clock"]
    clock_name = clock.get("name")
    if clock_name != "monotonic":
        raise AdapterReject("unknown_clock", f"unsupported clock name={clock_name!r}")
    frequency = clock.get("frequency")
    raw_value = clock.get("value")
    if (
        isinstance(frequency, bool)
        or not isinstance(frequency, int)
        or frequency <= 0
        or isinstance(raw_value, bool)
        or not isinstance(raw_value, int)
        or raw_value < 0
    ):
        raise AdapterReject(
            "invalid_clock", "clock frequency/value must be valid integers"
        )
    timestamp_ns = raw_value * 1_000_000_000 // frequency

    context = record["context"]
    pid = context.get("vpid")
    tid = context.get("vtid")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(tid, bool)
        or not isinstance(tid, int)
        or tid <= 0
    ):
        raise AdapterReject(
            "invalid_runtime_identity", "vpid and vtid must be positive integers"
        )

    return NormalizedEvent(
        event_id=f"ros2_tracing:{source_file}:{record_index}",
        source="ros2_tracing",
        event_type=event_name,
        timestamp_ns=timestamp_ns,
        clock_id="monotonic",
        trace_id="",
        sequence_id=0,
        stage="",
        pid=pid,
        tid=tid,
        host_id=host_id,
        attributes={
            "procname": context.get("procname", ""),
            "cpu_id": context.get("cpu_id"),
            "payload": record["payload"],
            "clock": {
                "raw_value": raw_value,
                "frequency": frequency,
                "ns_from_origin": clock.get("ns_from_origin"),
                "offset_seconds": clock.get("offset_seconds"),
                "offset_cycles": clock.get("offset_cycles"),
                "origin_is_unix_epoch": clock.get("origin_is_unix_epoch"),
            },
        },
        provenance={
            "adapter": "tracetools_ctf_fixture_v1",
            "source_file": source_file,
            "record_index": record_index,
        },
    )


def adapt_tracetools_jsonl(
    lines: Iterable[str], *, source_file: str
) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise AdapterReject(
                "invalid_json", f"line {line_number}: {error.msg}"
            ) from error
        if not isinstance(record, dict):
            raise AdapterReject(
                "invalid_json", f"line {line_number}: record must be an object"
            )
        try:
            events.append(
                adapt_tracetools_record(
                    record, source_file=source_file, record_index=line_number
                )
            )
        except AdapterReject as error:
            raise AdapterReject(
                error.reason_code, f"line {line_number}: {error}"
            ) from error
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.input.open("r", encoding="utf-8") as handle:
        events = adapt_tracetools_jsonl(handle, source_file=str(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(
                json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
