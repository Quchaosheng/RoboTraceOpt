"""Capture ROS node process identities from Linux procfs."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence


def capture_code_version(repo_root: Path) -> dict[str, object]:
    commit_result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    unstaged_result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--quiet", "--ignore-cr-at-eol"],
        check=False,
    )
    staged_result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--cached", "--quiet"],
        check=False,
    )
    untracked_result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    if unstaged_result.returncode not in (0, 1) or staged_result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            max(unstaged_result.returncode, staged_result.returncode), "git diff"
        )
    return {
        "git_commit": commit_result.stdout.strip(),
        "git_dirty": (
            unstaged_result.returncode == 1
            or staged_result.returncode == 1
            or bool(untracked_result.stdout.strip())
        ),
    }


def _boot_time_seconds(proc_root: Path) -> int:
    for line in (proc_root / "stat").read_text(encoding="utf-8").splitlines():
        if line.startswith("btime "):
            return int(line.split()[1])
    raise ValueError(f"btime is missing from {proc_root / 'stat'}")


def _process_start_ticks(stat_text: str) -> int:
    closing_parenthesis = stat_text.rfind(")")
    if closing_parenthesis < 0:
        raise ValueError("invalid proc stat record")
    fields_after_name = stat_text[closing_parenthesis + 1 :].split()
    if len(fields_after_name) <= 19:
        raise ValueError("proc stat record does not contain starttime")
    return int(fields_after_name[19])


def _namespace_ids(status_path: Path, expected_runtime_id: int) -> tuple[int, int, int]:
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("NSpid:"):
            ids = [int(value) for value in line.split()[1:]]
            if not ids or ids[-1] != expected_runtime_id:
                raise ValueError(f"invalid NSpid mapping in {status_path}")
            return ids[0], ids[-1], len(ids)
    raise ValueError(f"NSpid is missing from {status_path}")


def assess_ebpf_identity_status(
    *, osrelease: str, namespace_depths: Sequence[int]
) -> tuple[str, str]:
    if "microsoft" in osrelease.lower() and max(namespace_depths, default=0) < 2:
        return "not_comparable", "wsl_initial_pid_namespace_unavailable"
    return "comparable", ""


def _executable(process_root: Path) -> str:
    exe_path = process_root / "exe"
    try:
        return os.readlink(exe_path)
    except OSError:
        command = (process_root / "cmdline").read_bytes().split(b"\0", 1)[0]
        if not command:
            raise ValueError(f"executable is unavailable for PID {process_root.name}")
        return os.fsdecode(command)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def capture_process_manifest(
    processes: Sequence[tuple[str, int]],
    *,
    repo_root: Path,
    proc_root: Path = Path("/proc"),
    host_id: str | None = None,
    clock_ticks_per_second: int | None = None,
    captured_at_utc: str | None = None,
) -> dict[str, object]:
    if not processes:
        raise ValueError("at least one NODE=PID process is required")
    resolved_host = host_id or socket.gethostname()
    if not resolved_host:
        raise ValueError("host_id is required")
    ticks_per_second = clock_ticks_per_second or os.sysconf("SC_CLK_TCK")
    if ticks_per_second <= 0:
        raise ValueError("clock tick frequency must be positive")
    boot_time = datetime.fromtimestamp(_boot_time_seconds(proc_root), tz=timezone.utc)

    records: list[dict[str, object]] = []
    namespace_depths: list[int] = []
    for node, pid in processes:
        process_root = proc_root / str(pid)
        if not node or pid <= 0 or not process_root.is_dir():
            raise ProcessLookupError(f"live process not found for {node or '<empty>'} PID {pid}")
        start_ticks = _process_start_ticks(
            (process_root / "stat").read_text(encoding="utf-8")
        )
        tids = sorted(
            int(path.name)
            for path in (process_root / "task").iterdir()
            if path.is_dir() and path.name.isdigit()
        )
        if not tids:
            raise ProcessLookupError(f"no live threads found for {node} PID {pid}")
        kernel_pid, _, process_namespace_depth = _namespace_ids(
            process_root / "status", pid
        )
        namespace_depths.append(process_namespace_depth)
        threads = []
        for tid in tids:
            kernel_tid, runtime_tid, namespace_depth = _namespace_ids(
                process_root / "task" / str(tid) / "status", tid
            )
            namespace_depths.append(namespace_depth)
            threads.append({"tid": runtime_tid, "kernel_tid": kernel_tid})
        start_monotonic_ns = start_ticks * 1_000_000_000 // ticks_per_second
        start_time = boot_time + timedelta(seconds=start_ticks / ticks_per_second)
        records.append(
            {
                "node": node,
                "executable": _executable(process_root),
                "pid": pid,
                "kernel_pid": kernel_pid,
                "tids": tids,
                "threads": threads,
                "host_id": resolved_host,
                "start_time_monotonic_ns": start_monotonic_ns,
                "start_time_utc": _format_utc(start_time),
            }
        )

    code_version = capture_code_version(repo_root)
    osrelease_path = proc_root / "sys" / "kernel" / "osrelease"
    osrelease = (
        osrelease_path.read_text(encoding="utf-8").strip()
        if osrelease_path.is_file()
        else os.uname().release
    )
    ebpf_status, ebpf_reason = assess_ebpf_identity_status(
        osrelease=osrelease, namespace_depths=namespace_depths
    )
    return {
        "schema_version": "process-manifest/v2",
        "host_id": resolved_host,
        "captured_at_utc": captured_at_utc
        or _format_utc(datetime.now(timezone.utc)),
        **code_version,
        "osrelease": osrelease,
        "ebpf_identity_status": ebpf_status,
        "ebpf_identity_reason": ebpf_reason,
        "processes": records,
    }


def processes_from_runtime_events(path: Path) -> list[tuple[str, int]]:
    identities: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
                node = record["source_node"]
                pid = record["pid"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(
                    f"invalid RuntimeEvent identity at {path}:{line_number}"
                ) from error
            if not isinstance(node, str) or not node:
                raise ValueError(f"invalid source_node at {path}:{line_number}")
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise ValueError(f"invalid pid at {path}:{line_number}")
            previous_pid = identities.setdefault(node, pid)
            if previous_pid != pid:
                raise ValueError(
                    f"source_node {node!r} maps to multiple PIDs in {path}"
                )
    if not identities:
        raise ValueError(f"no RuntimeEvent identities found in {path}")
    return sorted(identities.items())


def _parse_process(value: str) -> tuple[str, int]:
    try:
        node, raw_pid = value.rsplit("=", 1)
        pid = int(raw_pid)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("process must use NODE=PID") from error
    if not node or pid <= 0:
        raise argparse.ArgumentTypeError("process must use non-empty NODE and positive PID")
    return node, pid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--process", action="append", type=_parse_process)
    source.add_argument("--runtime-events", type=Path)
    parser.add_argument("--minimum-processes", type=int, default=1)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.minimum_processes < 1:
        raise SystemExit("--minimum-processes must be positive")
    processes = (
        processes_from_runtime_events(args.runtime_events)
        if args.runtime_events
        else args.process
    )
    if len(processes) < args.minimum_processes:
        raise SystemExit(
            f"expected at least {args.minimum_processes} process identities, "
            f"found {len(processes)}"
        )
    manifest = capture_process_manifest(
        processes,
        repo_root=args.repo_root,
        host_id=args.host_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
