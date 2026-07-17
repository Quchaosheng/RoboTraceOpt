"""Normalize a validated RuntimeEvent v2 JSON record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from diagnosis.adapters.errors import AdapterReject
from diagnosis.schema import NormalizedEvent


KNOWN_CLOCKS = {"monotonic", "realtime", "tai"}
REQUIRED_FIELDS = {
    "trace_id",
    "sequence_id",
    "source_node",
    "stage",
    "timestamp_ns",
    "event_name",
    "event_type",
    "pid",
    "tid",
    "host_id",
    "clock_id",
    "duration_ns",
    "status",
    "reason_code",
    "extra_json",
}


def adapt_runtime_event(
    record: dict[str, Any], *, source_file: str, record_index: int
) -> NormalizedEvent:
    missing = sorted(REQUIRED_FIELDS - record.keys())
    if missing:
        raise AdapterReject(
            "missing_required_field", "missing fields: " + ", ".join(missing)
        )
    if not source_file or record_index < 0:
        raise AdapterReject("invalid_provenance", "source_file and record_index are required")

    string_fields = (
        "trace_id",
        "source_node",
        "stage",
        "event_name",
        "event_type",
        "host_id",
        "clock_id",
        "status",
        "reason_code",
        "extra_json",
    )
    invalid_strings = [name for name in string_fields if not isinstance(record[name], str)]
    if invalid_strings:
        reason = "invalid_extra_json" if invalid_strings == ["extra_json"] else "invalid_field_type"
        raise AdapterReject(reason, "fields must be strings: " + ", ".join(invalid_strings))

    trace_id = record["trace_id"]
    stage = record["stage"]
    event_name = record["event_name"]
    source_node = record["source_node"]
    host_id = record["host_id"]
    status = record["status"]
    if not all((trace_id, stage, event_name, source_node, host_id, status)):
        raise AdapterReject("missing_required_field", "required string field is empty")

    clock_id = record["clock_id"]
    if clock_id not in KNOWN_CLOCKS:
        raise AdapterReject("unknown_clock", f"unsupported clock_id={clock_id!r}")

    numeric_fields = ("timestamp_ns", "sequence_id", "pid", "tid", "duration_ns")
    invalid_numbers = [
        name
        for name in numeric_fields
        if isinstance(record[name], bool) or not isinstance(record[name], int)
    ]
    if invalid_numbers:
        raise AdapterReject(
            "invalid_numeric_field",
            "fields must be JSON integers: " + ", ".join(invalid_numbers),
        )
    timestamp_ns = record["timestamp_ns"]
    sequence_id = record["sequence_id"]
    pid = record["pid"]
    tid = record["tid"]
    duration_ns = record["duration_ns"]
    if pid <= 0 or tid <= 0 or host_id == "unknown":
        raise AdapterReject(
            "invalid_runtime_identity", "pid/tid must be positive and host_id must be known"
        )
    if timestamp_ns < 0 or sequence_id < 0 or duration_ns < 0:
        raise AdapterReject("invalid_numeric_field", "numeric fields must be non-negative")

    try:
        extra = json.loads(record["extra_json"])
    except json.JSONDecodeError as error:
        raise AdapterReject("invalid_extra_json", error.msg) from error
    if not isinstance(extra, dict):
        raise AdapterReject("invalid_extra_json", "extra_json must decode to an object")

    return NormalizedEvent(
        event_id=f"runtime_event:{source_file}:{record_index}",
        source="runtime_event",
        event_type=event_name,
        timestamp_ns=timestamp_ns,
        clock_id=clock_id,
        trace_id=trace_id,
        sequence_id=sequence_id,
        stage=stage,
        pid=pid,
        tid=tid,
        host_id=host_id,
        attributes={
            "source_node": source_node,
            "runtime_event_type": record["event_type"],
            "duration_ns": duration_ns,
            "status": status,
            "reason_code": record["reason_code"],
            "extra": extra,
        },
        provenance={
            "adapter": "runtime_event_v2",
            "source_file": source_file,
            "record_index": record_index,
        },
    )


def adapt_runtime_jsonl(
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
            raise AdapterReject("invalid_json", f"line {line_number}: {error.msg}") from error
        if not isinstance(record, dict):
            raise AdapterReject("invalid_json", f"line {line_number}: record must be an object")
        try:
            events.append(
                adapt_runtime_event(
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
        events = adapt_runtime_jsonl(handle, source_file=str(args.input))
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
