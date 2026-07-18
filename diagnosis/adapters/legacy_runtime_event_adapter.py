"""Convert v1 RuntimeEvent JSON records into the flat v2 log shape."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def adapt_legacy_event(
    record: dict[str, Any],
    *,
    legacy_clock_id: str = "unknown",
    legacy_host_id: str = "unknown",
) -> dict[str, Any]:
    header = record.get("header", {})
    if not isinstance(header, dict):
        raise ValueError("header must be an object")

    def get(name: str, default: Any = None) -> Any:
        return record[name] if name in record else header.get(name, default)

    required = {
        "trace_id": get("trace_id"),
        "sequence_id": get("sequence_id"),
        "source_node": get("source_node"),
        "stage": get("stage"),
        "timestamp_ns": get("timestamp_ns"),
        "event_name": get("event_name"),
    }
    missing = [name for name, value in required.items() if value is None or value == ""]
    if missing:
        raise ValueError("missing required RuntimeEvent fields: " + ", ".join(missing))

    extra_json = get("extra_json", "{}")
    if not isinstance(extra_json, str):
        extra_json = json.dumps(extra_json, ensure_ascii=False, separators=(",", ":"))

    return {
        "trace_id": str(required["trace_id"]),
        "oracle_id": str(get("oracle_id", "")),
        "sequence_id": int(required["sequence_id"]),
        "source_node": str(required["source_node"]),
        "stage": str(required["stage"]),
        "timestamp_ns": int(required["timestamp_ns"]),
        "event_name": str(required["event_name"]),
        "event_type": str(get("event_type", "runtime")),
        "pid": int(get("pid", 0)),
        "tid": int(get("tid", 0)),
        "host_id": str(get("host_id", legacy_host_id)),
        "clock_id": str(get("clock_id", legacy_clock_id)),
        "duration_ns": int(get("duration_ns", 0)),
        "status": str(get("status", "observed")),
        "reason_code": str(get("reason_code", "")),
        "extra_json": extra_json,
    }


def adapt_jsonl(
    lines: Iterable[str],
    *,
    legacy_clock_id: str = "unknown",
    legacy_host_id: str = "unknown",
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("record must be an object")
            events.append(
                adapt_legacy_event(
                    record,
                    legacy_clock_id=legacy_clock_id,
                    legacy_host_id=legacy_host_id,
                )
            )
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError(
                f"invalid legacy RuntimeEvent at line {line_number}: {error}"
            ) from error
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-clock-id", default="unknown")
    parser.add_argument("--legacy-host-id", default="unknown")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.input.open("r", encoding="utf-8") as handle:
        events = adapt_jsonl(
            handle,
            legacy_clock_id=args.legacy_clock_id,
            legacy_host_id=args.legacy_host_id,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(
                json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
