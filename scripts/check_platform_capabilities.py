#!/usr/bin/env python3
"""Collect a read-only ROS 2/Linux platform capability report."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KERNEL_CONFIG_KEYS = (
    "CONFIG_BPF",
    "CONFIG_BPF_SYSCALL",
    "CONFIG_BPF_JIT",
    "CONFIG_BPF_EVENTS",
    "CONFIG_CGROUP_BPF",
    "CONFIG_KPROBES",
    "CONFIG_UPROBES",
    "CONFIG_FTRACE",
    "CONFIG_DEBUG_INFO_BTF",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="Platform label, e.g. x86-wsl or rk3568.")
    parser.add_argument("--can-interface", default="vcan0")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def run_command(command: list[str], timeout: int = 15) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {
            "command": command,
            "available": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"{command[0]} not found",
            "timed_out": False,
        }
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "command": command,
            "available": True,
            "returncode": None,
            "stdout": (error.stdout or "").strip(),
            "stderr": (error.stderr or "").strip(),
            "timed_out": True,
        }
    return {
        "command": command,
        "available": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "timed_out": False,
    }


def command_ok(result: dict[str, Any]) -> bool:
    return result["available"] and result["returncode"] == 0


def tracing_capability_available(
    trace_help: dict[str, Any], status: dict[str, Any]
) -> bool:
    status_text = f"{status.get('stdout', '')}\n{status.get('stderr', '')}"
    return command_ok(trace_help) and command_ok(status) and "Tracing enabled" in status_text


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def parse_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_text(Path("/etc/os-release")).splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def find_tracefs() -> Path | None:
    for candidate in (Path("/sys/kernel/tracing"), Path("/sys/kernel/debug/tracing")):
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def read_kernel_config() -> dict[str, str]:
    release = platform.release()
    lines: list[str] = []
    proc_config = Path("/proc/config.gz")
    boot_config = Path(f"/boot/config-{release}")
    try:
        if proc_config.is_file():
            with gzip.open(proc_config, "rt", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        elif boot_config.is_file():
            lines = boot_config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []

    observed: dict[str, str] = {}
    wanted = set(KERNEL_CONFIG_KEYS)
    for line in lines:
        line = line.strip()
        if line.startswith("# ") and line.endswith(" is not set"):
            key = line[2 : -len(" is not set")]
            if key in wanted:
                observed[key] = "n"
        elif "=" in line:
            key, value = line.split("=", 1)
            if key in wanted:
                observed[key] = value
    return {key: observed.get(key, "unknown") for key in KERNEL_CONFIG_KEYS}


def collect_governors() -> dict[str, str]:
    governors: dict[str, str] = {}
    pattern = Path("/sys/devices/system/cpu/cpufreq")
    if not pattern.is_dir():
        return governors
    for path in sorted(pattern.glob("policy*/scaling_governor")):
        governors[path.parent.name] = read_text(path)
    return governors


def parse_can_interfaces(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not command_ok(result) or not result["stdout"]:
        return []
    try:
        parsed = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict) and item.get("ifname")]


def classify_readiness(checks: dict[str, bool]) -> dict[str, dict[str, str]]:
    if checks["ros2_runtime"]:
        runtime = item("ready", "workspace", "ROS 2 and runtime_bringup are discoverable.")
    else:
        runtime = item("blocked", "unavailable", "ROS 2 or runtime_bringup is not discoverable.")

    if checks["tracetools"]:
        tracing = item("ready", "tracetools", "The tracetools provider reports tracing enabled at compile time.")
    else:
        tracing = item("blocked", "unavailable", "The tracetools provider is missing or reports tracing disabled.")

    if checks["btf"] and checks["sched_switch_tracepoint"] and checks["bpftool_probe"]:
        ebpf = item("ready", "libbpf_core", "BTF, sched_switch tracepoint, and bpftool probe are available.")
    elif checks["sched_switch_tracepoint"] and checks["bpftool_probe"]:
        ebpf = item("partial", "bcc_or_non_core", "Tracepoints and BPF are usable, but CO-RE BTF was not found.")
    elif checks["sched_switch_tracepoint"]:
        ebpf = item("partial", "tracefs_only", "Tracefs is visible, but eBPF support was not proven by bpftool.")
    else:
        ebpf = item("blocked", "unavailable", "No usable sched_switch tracepoint was observed.")

    if checks["can_interface"] and checks["can_utils"]:
        socketcan = item("ready", "existing_interface", "A CAN interface and can-utils are available.")
    elif checks["can_utils"]:
        socketcan = item("partial", "create_vcan", "can-utils are present; create or attach the requested CAN interface.")
    else:
        socketcan = item("blocked", "unavailable", "No usable CAN interface/can-utils combination was observed.")

    if checks["cpu_governor_visible"]:
        cpu = item("ready", "cpufreq", "CPU governor controls are visible.")
    else:
        cpu = item("partial", "not_exposed", "CPU governor controls are not exposed by this platform.")

    if checks["time_sync_reported"]:
        clock = item("partial", "sync_reported", "A synchronization service reports status; measure offset before cross-host fusion.")
    else:
        clock = item("blocked", "not_verified", "No host synchronization status was available; cross-host timestamps are not comparable.")

    return {
        "runtime_event": runtime,
        "ros2_tracing": tracing,
        "ebpf": ebpf,
        "socketcan": socketcan,
        "cpu_control": cpu,
        "cross_host_clock": clock,
    }


def item(status: str, path: str, reason: str) -> dict[str, str]:
    return {"status": status, "path": path, "reason": reason}


def collect_capabilities(label: str, can_interface: str = "vcan0") -> dict[str, Any]:
    tracefs = find_tracefs()
    tracepoint = tracefs / "events/sched/sched_switch/format" if tracefs else None
    euid = os.geteuid() if hasattr(os, "geteuid") else None
    bpftool_args = ["bpftool", "feature", "probe"]
    if euid not in (None, 0):
        bpftool_args.append("unprivileged")

    commands = {
        "lscpu": run_command(["lscpu"]),
        "ros2_runtime_prefix": run_command(["ros2", "pkg", "prefix", "runtime_bringup"]),
        "ros2_trace_help": run_command(["ros2", "trace", "--help"]),
        "tracetools_status": run_command(["ros2", "run", "tracetools", "status"]),
        "bpftool_feature_probe": run_command(bpftool_args, timeout=30),
        "can_links": run_command(["ip", "-details", "-json", "link", "show", "type", "can"]),
        "can_interface": run_command(["ip", "-details", "link", "show", can_interface]),
        "timedatectl": run_command(["timedatectl", "show", "--property=NTPSynchronized", "--value"]),
        "chronyc_tracking": run_command(["chronyc", "tracking"]),
        "ptp4l_version": run_command(["ptp4l", "-v"]),
    }
    can_interfaces = parse_can_interfaces(commands["can_links"])
    governors = collect_governors()
    btf_path = Path("/sys/kernel/btf/vmlinux")
    proc_version = read_text(Path("/proc/version"))
    timedatectl_synced = command_ok(commands["timedatectl"]) and commands["timedatectl"]["stdout"].lower() == "yes"
    chrony_reported = command_ok(commands["chronyc_tracking"])
    can_utils = bool(shutil.which("candump") and shutil.which("cansend"))

    checks = {
        "ros2_runtime": command_ok(commands["ros2_runtime_prefix"]),
        "tracetools": tracing_capability_available(
            commands["ros2_trace_help"], commands["tracetools_status"]
        ),
        "btf": btf_path.is_file(),
        "sched_switch_tracepoint": bool(tracepoint and tracepoint.is_file()),
        "bpftool_probe": command_ok(commands["bpftool_feature_probe"]),
        "can_interface": command_ok(commands["can_interface"]),
        "can_utils": can_utils,
        "cpu_governor_visible": bool(governors),
        "time_sync_reported": timedatectl_synced or chrony_reported,
    }
    readiness = classify_readiness(checks)
    is_wsl = "microsoft" in proc_version.lower() or bool(os.environ.get("WSL_INTEROP"))
    limitations = [
        "Cross-host timestamps require a measured offset report even when NTP/PTP reports synchronized.",
        "A successful capability probe does not replace a workload-attached tracing smoke test.",
    ]
    if is_wsl:
        limitations.append("WSL2 is a development environment, not the planned native x86 Ubuntu experiment host.")
    if "rk3568" in label.lower() and platform.machine().lower() not in {"aarch64", "arm64"}:
        limitations.append("The rk3568 label does not match the detected machine architecture.")

    script_path = Path(__file__).resolve()
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform_label": label,
        "host": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "machine": platform.machine(),
            "kernel": platform.release(),
            "os_release": parse_os_release(),
            "euid": euid,
            "is_wsl": is_wsl,
        },
        "readiness": readiness,
        "evidence": {
            "ros2": {
                "ros_distro": os.environ.get("ROS_DISTRO", ""),
                "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION", "default"),
                "runtime_prefix": commands["ros2_runtime_prefix"],
                "trace_cli_help": commands["ros2_trace_help"],
                "tracetools_status": commands["tracetools_status"],
            },
            "kernel": {
                "btf_vmlinux": btf_path.is_file(),
                "btf_path": str(btf_path),
                "tracefs": str(tracefs) if tracefs else "",
                "sched_switch_tracepoint": bool(tracepoint and tracepoint.is_file()),
                "kernel_config": read_kernel_config(),
                "unprivileged_bpf_disabled": read_text(Path("/proc/sys/kernel/unprivileged_bpf_disabled")),
                "perf_event_paranoid": read_text(Path("/proc/sys/kernel/perf_event_paranoid")),
                "kptr_restrict": read_text(Path("/proc/sys/kernel/kptr_restrict")),
                "cap_eff": next(
                    (line.split(":", 1)[1].strip() for line in read_text(Path("/proc/self/status")).splitlines() if line.startswith("CapEff:")),
                    "",
                ),
                "bpftool_feature_probe": commands["bpftool_feature_probe"],
            },
            "can": {
                "requested_interface": can_interface,
                "interfaces": can_interfaces,
                "requested_interface_status": commands["can_interface"],
                "candump": shutil.which("candump") or "",
                "cansend": shutil.which("cansend") or "",
            },
            "cpu": {
                "lscpu": commands["lscpu"],
                "governors": governors,
            },
            "clock": {
                "clocksource_current": read_text(Path("/sys/devices/system/clocksource/clocksource0/current_clocksource")),
                "clocksource_available": read_text(Path("/sys/devices/system/clocksource/clocksource0/available_clocksource")),
                "clock_realtime_ns": time.clock_gettime_ns(time.CLOCK_REALTIME),
                "clock_monotonic_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC),
                "timedatectl": commands["timedatectl"],
                "chronyc_tracking": commands["chronyc_tracking"],
                "ptp4l_version": commands["ptp4l_version"],
            },
        },
        "provenance": {
            "script": str(script_path),
            "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
            "git_commit": run_command(["git", "rev-parse", "HEAD"])["stdout"],
            "git_status": run_command(["git", "status", "--short"])["stdout"],
        },
        "limitations": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    host = report["host"]
    lines = [
        "# Platform Capability Report",
        "",
        f"- Label: `{report['platform_label']}`",
        f"- Generated: `{report['generated_at_utc']}`",
        f"- Host: `{host['hostname']}`",
        f"- Machine: `{host['machine']}`",
        f"- Kernel: `{host['kernel']}`",
        "",
        "## Readiness",
        "",
        "| Capability | Status | Selected path | Evidence-based reason |",
        "|---|---|---|---|",
    ]
    for name, value in report["readiness"].items():
        reason = value["reason"].replace("|", "\\|")
        lines.append(f"| `{name}` | {value['status']} | `{value['path']}` | {reason} |")

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            "```json",
            json.dumps(report["evidence"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = collect_capabilities(args.label, args.can_interface)
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_markdown(report)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered_json, encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(rendered_markdown, encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(rendered_markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
