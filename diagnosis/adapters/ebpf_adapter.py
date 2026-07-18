"""Normalize eBPF scheduler and syscall records using process identities."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from diagnosis.adapters.errors import AdapterReject
from diagnosis.schema import NormalizedEvent


SCHEMA_VERSION = "ebpf-runtime/v1"
COMMON_FIELDS = {
    "schema_version",
    "event_source",
    "timestamp_ns",
    "clock_id",
    "host_id",
    "collector",
    "collector_version",
}


@dataclass(frozen=True)
class TaskIdentity:
    pid: int
    tid: int
    kernel_pid: int
    kernel_tid: int


def load_process_identities(manifest: dict[str, Any]) -> dict[int, TaskIdentity]:
    schema_version = manifest.get("schema_version")
    if schema_version not in {"process-manifest/v1", "process-manifest/v2"}:
        raise AdapterReject(
            "unsupported_schema", "expected process-manifest/v1 or process-manifest/v2"
        )
    if (
        schema_version == "process-manifest/v2"
        and manifest.get("ebpf_identity_status") != "comparable"
    ):
        raise AdapterReject(
            "identity_domain_not_comparable",
            str(manifest.get("ebpf_identity_reason") or "kernel identity unavailable"),
        )
    processes = manifest.get("processes")
    if not isinstance(processes, list) or not processes:
        raise AdapterReject(
            "missing_required_field", "processes must be a non-empty list"
        )
    identities: dict[int, TaskIdentity] = {}
    for process in processes:
        if not isinstance(process, dict):
            raise AdapterReject(
                "invalid_field_type", "process record must be an object"
            )
        pid = _integer(process, "pid", minimum=1)
        tids = process.get("tids")
        if not isinstance(tids, list) or not tids:
            raise AdapterReject(
                "missing_required_field", "tids must be a non-empty list"
            )
        if schema_version == "process-manifest/v2":
            kernel_pid = _integer(process, "kernel_pid", minimum=1)
            threads = process.get("threads")
            if not isinstance(threads, list) or len(threads) != len(tids):
                raise AdapterReject(
                    "identity_mismatch", "threads must map every runtime TID"
                )
        else:
            kernel_pid = pid
            threads = [{"tid": tid, "kernel_tid": tid} for tid in tids]

        observed_runtime_tids: set[int] = set()
        for thread in threads:
            if not isinstance(thread, dict):
                raise AdapterReject(
                    "invalid_field_type", "thread record must be an object"
                )
            tid = _integer(thread, "tid", minimum=1)
            kernel_tid = _integer(thread, "kernel_tid", minimum=1)
            observed_runtime_tids.add(tid)
            identity = TaskIdentity(
                pid=pid,
                tid=tid,
                kernel_pid=kernel_pid,
                kernel_tid=kernel_tid,
            )
            previous = identities.setdefault(kernel_tid, identity)
            if previous != identity:
                raise AdapterReject(
                    "identity_mismatch",
                    f"kernel TID {kernel_tid} maps to multiple runtime identities",
                )
        if observed_runtime_tids != set(tids):
            raise AdapterReject("identity_mismatch", "threads and tids disagree")
    return identities


def _integer(record: dict[str, Any], name: str, *, minimum: int = 0) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AdapterReject(
            "invalid_numeric_field", f"{name} must be an integer >= {minimum}"
        )
    return value


def _string(record: dict[str, Any], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise AdapterReject("invalid_field_type", f"{name} must be a non-empty string")
    return value


def _event(
    *,
    event_type: str,
    timestamp_ns: int,
    host_id: str,
    pid: int,
    tid: int,
    attributes: dict[str, Any],
    source_file: str,
    record_index: int,
    collector: str,
    collector_version: str,
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=f"ebpf:{source_file}:{record_index}:{event_type}:{tid}",
        source="ebpf",
        event_type=event_type,
        timestamp_ns=timestamp_ns,
        clock_id="monotonic",
        trace_id="",
        sequence_id=0,
        stage="",
        pid=pid,
        tid=tid,
        host_id=host_id,
        attributes=attributes,
        provenance={
            "adapter": "ebpf_runtime_v1",
            "source_file": source_file,
            "record_index": record_index,
            "collector": collector,
            "collector_version": collector_version,
        },
    )


def adapt_ebpf_record(
    record: dict[str, Any],
    *,
    tid_to_pid: Mapping[int, TaskIdentity],
    source_file: str,
    record_index: int,
) -> list[NormalizedEvent]:
    missing = sorted(COMMON_FIELDS - record.keys())
    if missing:
        raise AdapterReject(
            "missing_required_field", "missing fields: " + ", ".join(missing)
        )
    if not source_file or record_index < 0:
        raise AdapterReject(
            "invalid_provenance", "source_file and record_index are required"
        )
    if record["schema_version"] != SCHEMA_VERSION:
        raise AdapterReject("unsupported_schema", f"expected {SCHEMA_VERSION}")
    if record["clock_id"] != "monotonic":
        raise AdapterReject("unknown_clock", "eBPF ktime records must use monotonic")

    event_source = _string(record, "event_source")
    host_id = _string(record, "host_id")
    if host_id == "unknown":
        raise AdapterReject("invalid_runtime_identity", "host_id must be known")
    collector = _string(record, "collector")
    collector_version = _string(record, "collector_version")
    timestamp_ns = _integer(record, "timestamp_ns")

    if event_source == "sched_switch":
        prev_tid = _integer(record, "prev_tid")
        next_tid = _integer(record, "next_tid")
        prev_comm = _string(record, "prev_comm")
        next_comm = _string(record, "next_comm")
        prev_state = _integer(record, "prev_state")
        cpu_id = _integer(record, "cpu_id")
        events: list[NormalizedEvent] = []
        if prev_tid in tid_to_pid:
            identity = tid_to_pid[prev_tid]
            events.append(
                _event(
                    event_type="sched_switch_out",
                    timestamp_ns=timestamp_ns,
                    host_id=host_id,
                    pid=identity.pid,
                    tid=identity.tid,
                    attributes={
                        "kernel_pid": identity.kernel_pid,
                        "kernel_tid": identity.kernel_tid,
                        "comm": prev_comm,
                        "state": prev_state,
                        "cpu_id": cpu_id,
                        "counterpart_tid": next_tid,
                        "counterpart_comm": next_comm,
                    },
                    source_file=source_file,
                    record_index=record_index,
                    collector=collector,
                    collector_version=collector_version,
                )
            )
        if next_tid in tid_to_pid:
            identity = tid_to_pid[next_tid]
            events.append(
                _event(
                    event_type="sched_switch_in",
                    timestamp_ns=timestamp_ns,
                    host_id=host_id,
                    pid=identity.pid,
                    tid=identity.tid,
                    attributes={
                        "kernel_pid": identity.kernel_pid,
                        "kernel_tid": identity.kernel_tid,
                        "comm": next_comm,
                        "cpu_id": cpu_id,
                        "counterpart_tid": prev_tid,
                        "counterpart_comm": prev_comm,
                    },
                    source_file=source_file,
                    record_index=record_index,
                    collector=collector,
                    collector_version=collector_version,
                )
            )
        return events

    if event_source == "sched_wakeup":
        tid = _integer(record, "tid", minimum=1)
        comm = _string(record, "comm")
        target_cpu = _integer(record, "target_cpu")
        if tid not in tid_to_pid:
            return []
        identity = tid_to_pid[tid]
        return [
            _event(
                event_type="sched_wakeup",
                timestamp_ns=timestamp_ns,
                host_id=host_id,
                pid=identity.pid,
                tid=identity.tid,
                attributes={
                    "comm": comm,
                    "target_cpu": target_cpu,
                    "kernel_pid": identity.kernel_pid,
                    "kernel_tid": identity.kernel_tid,
                },
                source_file=source_file,
                record_index=record_index,
                collector=collector,
                collector_version=collector_version,
            )
        ]

    if event_source == "syscall":
        pid = _integer(record, "pid", minimum=1)
        tid = _integer(record, "tid", minimum=1)
        comm = _string(record, "comm")
        syscall_id = _integer(record, "syscall_id")
        syscall_name = _string(record, "syscall_name")
        return_value = _integer(record, "ret", minimum=-(2**63))
        duration_ns = _integer(record, "duration_ns")
        if tid not in tid_to_pid:
            return []
        identity = tid_to_pid[tid]
        if identity.kernel_pid != pid:
            raise AdapterReject(
                "identity_mismatch",
                f"kernel TID {tid} belongs to kernel PID {identity.kernel_pid}, not {pid}",
            )
        return [
            _event(
                event_type="syscall_interval",
                timestamp_ns=timestamp_ns,
                host_id=host_id,
                pid=identity.pid,
                tid=identity.tid,
                attributes={
                    "kernel_pid": identity.kernel_pid,
                    "kernel_tid": identity.kernel_tid,
                    "comm": comm,
                    "syscall_id": syscall_id,
                    "syscall_name": syscall_name,
                    "ret": return_value,
                    "duration_ns": duration_ns,
                },
                source_file=source_file,
                record_index=record_index,
                collector=collector,
                collector_version=collector_version,
            )
        ]

    raise AdapterReject(
        "unsupported_event", f"unsupported event_source={event_source!r}"
    )


def adapt_ebpf_jsonl(
    lines: Iterable[str],
    *,
    tid_to_pid: Mapping[int, TaskIdentity],
    source_file: str,
) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise AdapterReject(
                "invalid_json", f"line {line_number}: {error.msg}"
            ) from error
        if not isinstance(record, dict):
            raise AdapterReject(
                "invalid_json", f"line {line_number}: record must be an object"
            )
        try:
            events.extend(
                adapt_ebpf_record(
                    record,
                    tid_to_pid=tid_to_pid,
                    source_file=source_file,
                    record_index=line_number,
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
    parser.add_argument("--process-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.process_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise AdapterReject("invalid_json", "process manifest must be an object")
    identities = load_process_identities(manifest)
    with args.input.open("r", encoding="utf-8") as handle:
        events = adapt_ebpf_jsonl(
            handle, tid_to_pid=identities, source_file=str(args.input)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
