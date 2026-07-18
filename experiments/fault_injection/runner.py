"""Prepare capability-gated commands and evidence bundles for fault runs."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Iterable

from experiments.fault_injection.registry import (
    FaultSpec,
    materialize_f6_injection,
    validate_condition_variant,
)


def build_execution_script(
    command: list[str],
    *,
    setup_path: Path,
    ros_log_dir: Path,
    duration_seconds: int,
    tracing_overlay_setup: Path | None = None,
    trace_session: str = "",
    trace_dir: Path | None = None,
) -> str:
    tracing = tracing_overlay_setup is not None
    lines = [
        "set -euo pipefail",
        "set +u",
        f"source {shlex.quote(str(setup_path))}",
    ]
    if tracing:
        if not trace_session or trace_dir is None:
            raise ValueError("trace session and directory are required")
        session = shlex.quote(trace_session)
        lines.append(f"source {shlex.quote(str(tracing_overlay_setup))}")
    lines.extend(
        [
            "set -u",
            f"export ROS_LOG_DIR={shlex.quote(str(ros_log_dir))}",
        ]
    )
    if tracing:
        lines.extend(
            [
                'ros2 run tracetools status | grep -qx "Tracing enabled"',
                f"cleanup() {{ lttng stop {session} >/dev/null 2>&1 || true; "
                f"lttng destroy {session} >/dev/null 2>&1 || true; }}",
                "trap cleanup EXIT INT TERM",
                f"lttng create {session} --output={shlex.quote(str(trace_dir))}",
                'lttng enable-event --userspace "ros2:*"',
                "lttng add-context --userspace --type=vpid --type=vtid --type=procname",
                f"lttng start {session}",
            ]
        )
    lines.extend(
        [
            "set +e",
            f"timeout --signal=INT --kill-after=3s {duration_seconds}s {shlex.join(command)}",
            "launch_status=$?",
            "set -e",
        ]
    )
    if tracing:
        lines.extend(
            [
                f"lttng stop {shlex.quote(trace_session)}",
                f"lttng destroy {shlex.quote(trace_session)}",
                "trap - EXIT INT TERM",
            ]
        )
    lines.append('exit "${launch_status}"')
    return "\n".join(lines)


def require_capabilities(
    spec: FaultSpec,
    available: Iterable[str],
    *,
    dataset_role: str,
    f6_transport_profile: str = "mock",
) -> None:
    if spec.implementation_status != "ready":
        raise ValueError(
            f"fault {spec.fault_id} is not ready: {spec.implementation_status}"
        )
    required = set(spec.required_capabilities)
    if spec.fault_id != "F6" and f6_transport_profile != "mock":
        raise ValueError("F6 transport profile is only valid for F6")
    if spec.fault_id == "F6" and f6_transport_profile == "vcan":
        if dataset_role != "development":
            raise ValueError("F6 vcan transport profile is development-only")
        required.add("socketcan_vcan")
    missing = sorted(required - set(available))
    if missing:
        raise ValueError(f"missing required capabilities: {', '.join(missing)}")


def build_launch_command(
    spec: FaultSpec,
    events_path: Path,
    *,
    condition_variant: str = "injected",
    target_cpu: int | None = None,
    f6_transport_profile: str = "mock",
) -> list[str]:
    if spec.implementation_status != "ready":
        raise ValueError(
            f"fault {spec.fault_id} is not ready: {spec.implementation_status}"
        )
    validate_condition_variant(spec, condition_variant)
    output_argument = f"output_path:={events_path.as_posix()}"
    if spec.fault_id == "F1":
        delay_ms = (
            int(spec.injection["planner_delay_ms"])
            if condition_variant == "injected"
            else int(spec.injection["control_delay_ms"])
        )
        return [
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            f"camera_rate_hz:={spec.injection['input_rate_hz']}",
            f"planner_backend:={spec.injection['planner_backend']}",
            "action_manager_enabled:="
            + ("true" if spec.injection["action_manager_enabled"] else "false"),
            f"planner_delay_mode:={spec.injection['planner_delay_mode']}",
            f"planner_delay_ms:={delay_ms}",
            "runtime_event_enabled:=true",
            output_argument,
        ]
    if spec.fault_id == "F2":
        return [
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            f"camera_rate_hz:={spec.injection['input_rate_hz']}",
            "planner_backend:=mock",
            "planner_delay_ms:=0",
            "action_manager_enabled:=false",
            "executor_contention_enabled:="
            + ("true" if condition_variant == "injected" else "false"),
            f"executor_contention_period_ms:={spec.injection['callback_period_ms']}",
            f"executor_contention_load_ms:={spec.injection['callback_load_ms']}",
            "runtime_event_enabled:=true",
            output_argument,
        ]
    if spec.fault_id == "F4":
        delay_ms = (
            int(spec.injection["server_delay_ms"])
            if condition_variant == "injected"
            else int(spec.injection["control_delay_ms"])
        )
        return [
            "ros2",
            "launch",
            "service_runtime_demo",
            "service_runtime_demo.launch.py",
            f"request_rate_hz:={spec.injection['request_rate_hz']}",
            f"server_delay_ms:={delay_ms}",
            "runtime_events_enabled:=true",
            output_argument,
        ]
    if spec.fault_id == "F3":
        if (
            isinstance(target_cpu, bool)
            or not isinstance(target_cpu, int)
            or target_cpu < 0
        ):
            raise ValueError("F3 target_cpu must be a non-negative integer")
        return [
            "taskset",
            "--cpu-list",
            str(target_cpu),
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            f"camera_rate_hz:={spec.injection['input_rate_hz']}",
            "planner_backend:=mock",
            "planner_delay_ms:=0",
            "action_manager_enabled:=false",
            "executor_contention_enabled:=false",
            "runtime_event_enabled:=true",
            output_argument,
        ]
    if spec.fault_id == "F5":
        depth = (
            int(spec.injection["publisher_depth"])
            if condition_variant == "injected"
            else int(spec.injection["control_depth"])
        )
        return [
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            f"camera_rate_hz:={spec.injection['input_rate_hz']}",
            f"frame_payload_bytes:={spec.injection['payload_bytes']}",
            f"frame_qos_depth:={depth}",
            f"frame_qos_reliability:={spec.injection['reliability']}",
            "planner_backend:=mock",
            "planner_delay_ms:=0",
            "action_manager_enabled:=false",
            "executor_contention_enabled:=false",
            "runtime_event_enabled:=true",
            output_argument,
        ]
    if spec.fault_id == "F6":
        injection = materialize_f6_injection(
            spec, condition_variant, f6_transport_profile
        )
        command = [
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            f"camera_rate_hz:={injection['input_rate_hz']}",
            f"planner_backend:={injection['planner_backend']}",
            "action_manager_enabled:="
            + ("true" if injection["action_manager_enabled"] else "false"),
            f"ack_mode:={injection['ack_mode']}",
            "mock_mode:=" + ("true" if injection["mock_mode"] else "false"),
            "runtime_event_enabled:=true",
        ]
        if f6_transport_profile == "mock":
            command.append(f"mock_ack_policy:={injection['mock_ack_policy']}")
        else:
            command.extend(
                [
                    f"can_interface:={injection['can_interface']}",
                    f"ack_can_id_offset:={injection['ack_can_id_offset']}",
                ]
            )
        command.extend(
            [
                f"ack_timeout_ms:={injection['ack_timeout_ms']}",
                f"max_retries:={injection['max_retries']}",
                output_argument,
            ]
        )
        return command
    raise ValueError(f"no launch command for ready fault: {spec.fault_id}")


def write_condition_bundle(
    output_dir: Path,
    public_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    command: list[str],
    *,
    stress_command: list[str] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "public_manifest": output_dir / "run_manifest.json",
        "oracle_manifest": output_dir / "oracle_manifest.json",
        "command": output_dir / "command.json",
    }
    existing = [path for path in paths.values() if path.exists()]
    if existing:
        raise ValueError(f"condition bundle already exists: {existing[0]}")
    paths["public_manifest"].write_text(
        json.dumps(public_manifest, indent=2) + "\n", encoding="utf-8"
    )
    paths["oracle_manifest"].write_text(
        json.dumps(oracle_manifest, indent=2) + "\n", encoding="utf-8"
    )
    command_record: dict[str, Any] = {"argv": command}
    if stress_command is not None:
        command_record["stress_argv"] = stress_command
    paths["command"].write_text(
        json.dumps(command_record, indent=2) + "\n", encoding="utf-8"
    )
    return paths
