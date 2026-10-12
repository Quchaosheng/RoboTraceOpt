#!/usr/bin/env python3
"""Capture target scheduler and syscall events with bpftrace."""

from __future__ import annotations

import argparse
import json
import re
import signal
import socket
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnosis.adapters.ebpf_adapter import TaskIdentity, load_process_identities
from diagnosis.adapters.errors import AdapterReject


def _predicate(expression: str, tids: Sequence[int]) -> str:
    return " || ".join(f"{expression} == {tid}" for tid in tids)


def build_bpftrace_program(pids: Sequence[int]) -> str:
    unique_pids = sorted(set(pids))
    if not unique_pids or any(
        isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
        for pid in unique_pids
    ):
        raise ValueError("at least one positive target PID is required")
    process_filter = _predicate("pid", unique_pids)
    return f"""
tracepoint:sched:sched_switch
{{
  printf("E\\tS\\t%llu\\t%d\\t%s\\t%lld\\t%d\\t%s\\t%d\\n",
         nsecs, args->prev_pid, args->prev_comm, args->prev_state,
         args->next_pid, args->next_comm, cpu);
}}

tracepoint:sched:sched_wakeup
{{
  printf("E\\tW\\t%llu\\t%d\\t%s\\t%d\\n",
         nsecs, args->pid, args->comm, args->target_cpu);
}}

tracepoint:raw_syscalls:sys_enter /{process_filter}/
{{
  @syscall_start[tid] = nsecs;
  @syscall_id[tid] = args->id;
}}

tracepoint:raw_syscalls:sys_exit /@syscall_start[tid]/
{{
  printf("E\\tY\\t%llu\\t%d\\t%d\\t%s\\t%lld\\t%lld\\t%llu\\n",
         nsecs, pid, tid, comm, @syscall_id[tid], args->ret,
         nsecs - @syscall_start[tid]);
  delete(@syscall_start[tid]);
  delete(@syscall_id[tid]);
}}
""".strip()


def _common(
    *, timestamp_ns: int, host_id: str, collector_version: str
) -> dict[str, Any]:
    return {
        "schema_version": "ebpf-runtime/v1",
        "timestamp_ns": timestamp_ns,
        "clock_id": "monotonic",
        "host_id": host_id,
        "collector": "bpftrace",
        "collector_version": collector_version,
    }


def parse_event_line(
    line: str, *, host_id: str, collector_version: str
) -> dict[str, Any]:
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 2 or fields[0] != "E":
        raise ValueError("not an eBPF collector event line")
    kind = fields[1]
    try:
        timestamp_ns = int(fields[2])
        record = _common(
            timestamp_ns=timestamp_ns,
            host_id=host_id,
            collector_version=collector_version,
        )
        if kind == "S" and len(fields) == 9:
            record.update(
                {
                    "event_source": "sched_switch",
                    "prev_tid": int(fields[3]),
                    "prev_comm": fields[4],
                    "prev_state": int(fields[5]),
                    "next_tid": int(fields[6]),
                    "next_comm": fields[7],
                    "cpu_id": int(fields[8]),
                }
            )
            return record
        if kind == "W" and len(fields) == 6:
            record.update(
                {
                    "event_source": "sched_wakeup",
                    "tid": int(fields[3]),
                    "comm": fields[4],
                    "target_cpu": int(fields[5]),
                }
            )
            return record
        if kind == "Y" and len(fields) == 9:
            syscall_id = int(fields[6])
            record.update(
                {
                    "event_source": "syscall",
                    "pid": int(fields[3]),
                    "tid": int(fields[4]),
                    "comm": fields[5],
                    "syscall_id": syscall_id,
                    "syscall_name": f"sys_{syscall_id}",
                    "ret": int(fields[7]),
                    "duration_ns": int(fields[8]),
                }
            )
            return record
    except (IndexError, ValueError) as error:
        raise ValueError(f"malformed bpftrace event line: {line!r}") from error
    raise ValueError(f"malformed bpftrace event line: {line!r}")


def record_targets_manifest(
    record: dict[str, Any], identities: dict[int, TaskIdentity]
) -> bool:
    event_source = record.get("event_source")
    if event_source == "sched_switch":
        return (
            record.get("prev_tid") in identities or record.get("next_tid") in identities
        )
    if event_source == "sched_wakeup":
        return record.get("tid") in identities
    if event_source == "syscall":
        tid = record.get("tid")
        return tid in identities and identities[tid].kernel_pid == record.get("pid")
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-manifest", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    # Both scheduler probes printf every host switch, so host-sized output is
    # possible; these bounds keep a busy host from exhausting this process.
    parser.add_argument("--max-events", type=int, default=2_000_000)
    parser.add_argument("--max-malformed-lines", type=int, default=1000)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def collect_bounded(
    lines: Iterable[str],
    *,
    identities: dict[int, TaskIdentity],
    host_id: str,
    collector_version: str,
    max_events: int,
    max_malformed_lines: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Parse target events, retaining at most max_events.

    Returns (records, malformed_count, truncated). Once a bound is reached the
    stream is drained without further retention, so memory tracks the bound
    rather than the host's switch rate; the caller reports the loss.
    """
    records: list[dict[str, Any]] = []
    malformed_count = 0
    truncated = False
    for line in lines:
        if not line.startswith("E\t"):
            continue
        if len(records) >= max_events or malformed_count >= max_malformed_lines:
            truncated = True
            continue
        try:
            record = parse_event_line(
                line, host_id=host_id, collector_version=collector_version
            )
            if record_targets_manifest(record, identities):
                records.append(record)
        except ValueError:
            malformed_count += 1
    return records, malformed_count, truncated


def collector_loss_status(stderr: str) -> str:
    """Classify collector-side event loss from bpftrace diagnostics.

    Only an explicit "Lost <n> events" report proves loss; stderr says nothing
    about the absence of loss, so a silent collector stays `unknown`.
    """
    reported = sum(
        int(match.group(1))
        for match in re.finditer(r"Lost\s+(\d+)\s+events", stderr or "")
    )
    if reported > 0:
        return "nonzero"
    if re.search(r"Lost\s+0\s+events", stderr or ""):
        return "zero"
    return "unknown"


def collect_until_timeout(
    process: subprocess.Popen[str], duration: float
) -> tuple[str, str]:
    """Collect for the window, then escalate SIGINT -> terminate -> kill."""
    try:
        return process.communicate(timeout=duration)
    except subprocess.TimeoutExpired:
        pass
    # Escalation ladder; each step reaps stdout/stderr, so no pipe deadlocks.
    for escalation in (
        (signal.SIGINT, 5.0),
        (signal.SIGTERM, 5.0),
        (signal.SIGKILL, 5.0),
    ):
        process.send_signal(escalation[0])
        try:
            return process.communicate(timeout=escalation[1])
        except subprocess.TimeoutExpired:
            continue
    return process.communicate()


def capture_exit_is_successful(
    *, returncode: int, event_count: int, malformed_count: int
) -> bool:
    return (
        returncode in (0, 130, -signal.SIGINT)
        and event_count > 0
        and malformed_count == 0
    )


def main() -> int:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    manifest = json.loads(args.process_manifest.read_text(encoding="utf-8"))
    try:
        identities = load_process_identities(manifest)
    except AdapterReject as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    host_id = str(manifest.get("host_id") or socket.gethostname())
    version_result = subprocess.run(
        ["bpftrace", "--version"], check=True, capture_output=True, text=True
    )
    collector_version = version_result.stdout.strip().removeprefix("bpftrace v")
    target_pids = sorted({identity.kernel_pid for identity in identities.values()})
    program = build_bpftrace_program(target_pids)

    command = ["bpftrace"]
    if args.verbose:
        command.append("-v")
    command.extend(["-q", "-e", program])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = collect_until_timeout(process, args.duration)
    finally:
        # Never orphan the collector on KeyboardInterrupt or a write failure.
        if process.poll() is None:
            process.kill()
            process.communicate()

    raw_line_count = 0

    def counted_lines() -> Iterable[str]:
        nonlocal raw_line_count
        for line in stdout.splitlines():
            raw_line_count += 1
            yield line

    records, malformed_count, truncated = collect_bounded(
        counted_lines(),
        identities=identities,
        host_id=host_id,
        collector_version=collector_version,
        max_events=args.max_events,
        max_malformed_lines=args.max_malformed_lines,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    counts = Counter(record["event_source"] for record in records)
    summary = {
        "schema_version": "ebpf-capture-summary/v1",
        "collector": "bpftrace",
        "collector_version": collector_version,
        "host_id": host_id,
        "duration_s": args.duration,
        "target_tid_count": len(identities),
        "target_pid_count": len(target_pids),
        "event_count": len(records),
        "counts_by_type": dict(sorted(counts.items())),
        "malformed_line_count": malformed_count,
        "raw_stdout_line_count": raw_line_count,
        "raw_stdout_sample": stdout.splitlines()[:5],
        "capture_truncated": truncated,
        "max_events": args.max_events,
        "bpftrace_returncode": process.returncode,
        "collector_loss_status": collector_loss_status(stderr),
        "bpftrace_stderr": stderr.strip(),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return (
        0
        if capture_exit_is_successful(
            returncode=process.returncode,
            event_count=len(records),
            malformed_count=malformed_count,
        )
        and not truncated
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
