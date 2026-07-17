"""Linux process helpers for the F3 same-CPU pressure condition."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Iterable, TextIO

from experiments.fault_injection.registry import FaultSpec


def start_isolated_process(
    command: list[str], *, cwd: Path, output: int | TextIO
) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=output,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def select_target_cpu(allowed_cpus: Iterable[int]) -> int:
    cpus = set(allowed_cpus)
    if not cpus or any(
        isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in cpus
    ):
        raise ValueError("allowed CPU set must contain non-negative integers")
    return max(cpus)


def build_stress_command(
    spec: FaultSpec, *, target_cpu: int, duration_seconds: int
) -> list[str]:
    if spec.fault_id != "F3" or spec.implementation_status != "ready":
        raise ValueError("a ready F3 specification is required")
    if isinstance(target_cpu, bool) or not isinstance(target_cpu, int) or target_cpu < 0:
        raise ValueError("target_cpu must be a non-negative integer")
    if duration_seconds < 1:
        raise ValueError("duration_seconds must be positive")
    return [
        "taskset",
        "--cpu-list",
        str(target_cpu),
        "stress-ng",
        "--cpu",
        str(spec.injection["stressors"]),
        "--cpu-load",
        str(spec.injection["cpu_load_percent"]),
        "--cpu-method",
        str(spec.injection["cpu_method"]),
        "--timeout",
        f"{duration_seconds + 5}s",
        "--metrics-brief",
    ]


def process_tree_pids(root_pid: int, proc_root: Path = Path("/proc")) -> set[int]:
    if root_pid <= 0:
        raise ValueError("root_pid must be positive")
    parent_by_pid: dict[int, int] = {}
    for process_root in proc_root.iterdir():
        if not process_root.name.isdigit():
            continue
        try:
            status = (process_root / "status").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        parent_line = next(
            (line for line in status.splitlines() if line.startswith("PPid:")), None
        )
        if parent_line is not None:
            parent_by_pid[int(process_root.name)] = int(parent_line.split()[1])

    result = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parent_by_pid.items():
            if parent_pid in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def snapshot_scheduler_processes(
    processes: dict[str, int], target_cpu: int
) -> dict[str, dict[str, object]]:
    if not processes:
        raise ValueError("at least one process is required")
    snapshots: dict[str, dict[str, object]] = {}
    for name, pid in sorted(processes.items()):
        try:
            allowed_cpus = sorted(os.sched_getaffinity(pid))
            policy = os.sched_getscheduler(pid)
            priority = os.sched_getparam(pid).sched_priority
        except ProcessLookupError as error:
            raise ProcessLookupError(f"live process not found: {name} PID {pid}") from error
        if allowed_cpus != [target_cpu]:
            raise ValueError(
                f"process {name} PID {pid} affinity {allowed_cpus} does not match "
                f"target CPU {target_cpu}"
            )
        snapshots[name] = {
            "pid": pid,
            "allowed_cpus": allowed_cpus,
            "policy": _policy_name(policy),
            "priority": priority,
        }
    return snapshots


def capture_scheduler_manifest(
    *,
    process_manifest: dict[str, object],
    condition_variant: str,
    target_cpu: int,
    ros_command: list[str],
    stress_process_pid: int | None,
    stress_command: list[str],
    stress_version: str,
    ros_process_snapshots: dict[str, dict[str, object]] | None = None,
    stress_process_pids: list[int] | None = None,
    stress_process_snapshots: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    if process_manifest.get("schema_version") != "process-manifest/v2":
        raise ValueError("process-manifest/v2 is required")
    if condition_variant not in {"injected", "control"}:
        raise ValueError("invalid F3 condition variant")
    process_records = process_manifest.get("processes")
    if not isinstance(process_records, list):
        raise ValueError("process manifest records are required")
    ros_processes = {
        str(record["node"]): int(record["pid"])
        for record in process_records
        if isinstance(record, dict) and record.get("node") and record.get("pid")
    }
    if not ros_processes:
        raise ValueError("ROS process identities are required")

    stress_enabled = condition_variant == "injected"
    if stress_enabled and (stress_process_pid is None or not stress_command):
        raise ValueError("injected F3 requires a live stress process and command")
    if not stress_enabled and (stress_process_pid is not None or stress_command):
        raise ValueError("control F3 must not include a stress process")
    if ros_process_snapshots is None:
        ros_process_snapshots = snapshot_scheduler_processes(
            ros_processes, target_cpu
        )
    if stress_process_pids is None:
        stress_process_pids = (
            sorted(process_tree_pids(stress_process_pid))
            if stress_process_pid is not None
            else []
        )
    if stress_process_snapshots is None:
        stress_process_snapshots = (
            snapshot_scheduler_processes(
                {f"stress_{pid}": pid for pid in stress_process_pids}, target_cpu
            )
            if stress_process_pids
            else {}
        )
    return {
        "schema_version": "f3-scheduler-manifest/v1",
        "condition_variant": condition_variant,
        "target_cpu": target_cpu,
        "target_cpu_selection": "highest_allowed_cpu",
        "host_id": process_manifest.get("host_id"),
        "git_commit": process_manifest.get("git_commit"),
        "ebpf_identity_status": process_manifest.get("ebpf_identity_status"),
        "ebpf_identity_reason": process_manifest.get("ebpf_identity_reason", ""),
        "ros_command": list(ros_command),
        "ros_processes": ros_process_snapshots,
        "stress": {
            "enabled": stress_enabled,
            "command": list(stress_command),
            "version": stress_version,
            "pids": stress_process_pids,
            "processes": stress_process_snapshots,
        },
    }


def stop_process(process: subprocess.Popen, grace_seconds: float) -> str:
    if grace_seconds <= 0:
        raise ValueError("grace_seconds must be positive")
    if process.poll() is not None:
        return "already_exited"
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=grace_seconds)
        return "graceful_sigint"
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return "forced_kill"


def _policy_name(policy: int) -> str:
    names = {
        getattr(os, name): name
        for name in ("SCHED_OTHER", "SCHED_FIFO", "SCHED_RR", "SCHED_BATCH", "SCHED_IDLE")
        if hasattr(os, name)
    }
    return names.get(policy, f"UNKNOWN_{policy}")
