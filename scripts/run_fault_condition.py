"""Prepare or execute one capability-gated diagnosis fault condition."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.fault_injection.registry import (  # noqa: E402
    create_fault_manifests,
    load_fault_catalog,
)
from experiments.fault_injection.runner import (  # noqa: E402
    build_execution_script,
    build_launch_command,
    require_capabilities,
    write_condition_bundle,
)
from experiments.fault_injection.scheduling_pressure import (  # noqa: E402
    build_stress_command,
    capture_scheduler_manifest,
    process_tree_pids,
    select_target_cpu,
    snapshot_scheduler_processes,
    start_isolated_process,
    stop_process,
)
from experiments.fault_injection.socketcan_capture import (  # noqa: E402
    SocketCanCapture,
    start_socketcan_capture,
    stop_socketcan_capture,
)
from scripts.capture_process_manifest import processes_from_runtime_events  # noqa: E402


def try_snapshot_runtime_processes(
    events_path: Path, *, minimum_processes: int, target_cpu: int
) -> dict[str, dict[str, object]] | None:
    if minimum_processes < 1:
        raise ValueError("minimum_processes must be positive")
    processes = processes_from_runtime_events(events_path)
    if len(processes) < minimum_processes:
        return None
    return snapshot_scheduler_processes(dict(processes), target_cpu)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-id", required=True)
    parser.add_argument(
        "--dataset-role",
        choices=("development", "calibration", "test"),
        required=True,
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--condition-id", required=True)
    parser.add_argument(
        "--condition-variant",
        choices=("injected", "control"),
        default="injected",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument(
        "--f6-transport-profile", choices=("mock", "vcan"), default="mock"
    )
    parser.add_argument(
        "--safe-root",
        type=Path,
        default=Path.home() / ".cache" / "robotracert_fusion_build",
    )
    parser.add_argument(
        "--tracing-overlay-root",
        type=Path,
        default=Path.home() / ".cache" / "robotracert_tracing_overlay",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration_seconds < 1:
        raise ValueError("duration-seconds must be positive")
    catalog = load_fault_catalog()
    if args.fault_id not in catalog:
        raise ValueError(f"unknown fault ID: {args.fault_id}")
    spec = catalog[args.fault_id]
    require_capabilities(
        spec,
        set(args.capability),
        dataset_role=args.dataset_role,
        f6_transport_profile=args.f6_transport_profile,
    )
    target_cpu = (
        select_target_cpu(os.sched_getaffinity(0)) if spec.fault_id == "F3" else None
    )
    stress_command = (
        build_stress_command(
            spec,
            target_cpu=target_cpu,
            duration_seconds=args.duration_seconds,
        )
        if spec.fault_id == "F3" and args.condition_variant == "injected"
        else []
    )
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    public, oracle = create_fault_manifests(
        spec,
        dataset_role=args.dataset_role,
        session_id=args.session_id,
        condition_id=args.condition_id,
        git_commit=git_commit,
        condition_variant=args.condition_variant,
        target_cpu=target_cpu,
        f6_transport_profile=args.f6_transport_profile,
    )
    events_path = args.output_dir / "runtime_events.jsonl"
    command = build_launch_command(
        spec,
        events_path.resolve(),
        condition_variant=args.condition_variant,
        target_cpu=target_cpu,
        f6_transport_profile=args.f6_transport_profile,
    )
    paths = write_condition_bundle(
        args.output_dir,
        public,
        oracle,
        command,
        stress_command=stress_command if spec.fault_id == "F3" else None,
    )
    if args.execute:
        summary = execute_condition(
            spec.fault_id,
            spec.workload,
            command,
            args.output_dir,
            args.safe_root,
            args.duration_seconds,
            set(args.capability),
            args.tracing_overlay_root,
            condition_variant=args.condition_variant,
            target_cpu=target_cpu,
            stress_command=stress_command,
            f6_transport_profile=args.f6_transport_profile,
            f6_injection=(
                dict(oracle["injection"]) if spec.fault_id == "F6" else None
            ),
            session_id=args.session_id,
        )
        summary_path = args.output_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        paths["summary"] = summary_path
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))
    return 0


def start_f6_socketcan_capture(
    *,
    fault_id: str,
    f6_transport_profile: str,
    f6_injection: dict[str, object] | None,
    output_dir: Path,
    session_id: str,
    condition_variant: str,
) -> SocketCanCapture | None:
    if f6_transport_profile != "vcan":
        return None
    if fault_id != "F6" or f6_injection is None:
        raise ValueError("F6 vcan execution requires the frozen oracle profile")
    return start_socketcan_capture(
        f6_injection,
        output_dir,
        session_id=session_id,
        condition_variant=condition_variant,
        cwd=REPOSITORY_ROOT,
    )


def execute_condition(
    fault_id: str,
    workload: str,
    command: list[str],
    output_dir: Path,
    safe_root: Path,
    duration_seconds: int,
    capabilities: set[str],
    tracing_overlay_root: Path,
    *,
    condition_variant: str = "injected",
    target_cpu: int | None = None,
    stress_command: list[str] | None = None,
    f6_transport_profile: str = "mock",
    f6_injection: dict[str, object] | None = None,
    session_id: str = "",
) -> dict[str, object]:
    setup_path = safe_root / "install" / "setup.bash"
    if not setup_path.is_file():
        raise FileNotFoundError(f"ROS 2 build setup is missing: {setup_path}")
    ros_log_dir = safe_root / "ros_logs" / output_dir.name
    ros_log_dir.mkdir(parents=True, exist_ok=True)
    tracing = "ros2_tracing" in capabilities
    trace_session = f"fault_{fault_id.lower()}_{os.getpid()}"
    trace_dir = output_dir / "ctf"
    tracing_setup = tracing_overlay_root / "install" / "setup.bash"
    if tracing and not tracing_setup.is_file():
        raise FileNotFoundError(f"tracetools overlay is missing: {tracing_setup}")
    if tracing:
        subprocess.run(
            [
                "python3",
                "-m",
                "diagnosis.adapters.clock_calibration",
                "--host-id",
                socket.gethostname(),
                "--sample-count",
                "1000",
                "--tolerance-ns",
                "100000",
                "--output",
                str(output_dir / "clock_calibration.json"),
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
    shell_command = build_execution_script(
        command,
        setup_path=setup_path,
        ros_log_dir=ros_log_dir,
        duration_seconds=duration_seconds,
        tracing_overlay_setup=tracing_setup if tracing else None,
        trace_session=trace_session if tracing else "",
        trace_dir=trace_dir if tracing else None,
    )
    launch_log = output_dir / "launch.log"
    stress_process = None
    stress_handle = None
    scheduler_manifest = None
    ros_process_snapshots = None
    stress_process_pids = None
    stress_process_snapshots = None
    cleanup_status = "not_applicable"
    socketcan_capture = start_f6_socketcan_capture(
        fault_id=fault_id,
        f6_transport_profile=f6_transport_profile,
        f6_injection=f6_injection,
        output_dir=output_dir,
        session_id=session_id,
        condition_variant=condition_variant,
    )
    socketcan_manifest = None
    try:
        if fault_id == "F3" and condition_variant == "injected":
            if target_cpu is None or not stress_command:
                raise ValueError("injected F3 requires target CPU and stress command")
            stress_handle = (output_dir / "stress.log").open("w", encoding="utf-8")
            stress_process = start_isolated_process(
                stress_command,
                cwd=REPOSITORY_ROOT,
                output=stress_handle,
            )
            time.sleep(0.25)
            if stress_process.poll() is not None:
                raise RuntimeError("stress-ng exited during startup; see stress.log")

        with launch_log.open("w", encoding="utf-8") as handle:
            process = start_isolated_process(
                ["bash", "-lc", shell_command],
                cwd=REPOSITORY_ROOT,
                output=handle,
            )
            process_manifest_captured = not tracing
            if tracing:
                process_manifest = output_dir / "process_manifest.json"
                minimum_processes = 2 if workload == "w2" else 4
                for _ in range(50):
                    time.sleep(0.2)
                    events_path = output_dir / "runtime_events.jsonl"
                    if not events_path.is_file() or events_path.stat().st_size == 0:
                        continue
                    if fault_id == "F3" and ros_process_snapshots is None:
                        if target_cpu is None:
                            raise ValueError("F3 target CPU is required")
                        try:
                            candidate_snapshots = try_snapshot_runtime_processes(
                                events_path,
                                minimum_processes=minimum_processes,
                                target_cpu=target_cpu,
                            )
                            if candidate_snapshots is None:
                                continue
                            ros_process_snapshots = candidate_snapshots
                            stress_process_pids = (
                                sorted(process_tree_pids(stress_process.pid))
                                if stress_process is not None
                                else []
                            )
                            stress_process_snapshots = (
                                snapshot_scheduler_processes(
                                    {
                                        f"stress_{pid}": pid
                                        for pid in stress_process_pids
                                    },
                                    target_cpu,
                                )
                                if stress_process_pids
                                else {}
                            )
                        except (ValueError, ProcessLookupError):
                            continue
                    capture = subprocess.run(
                        [
                            "python3",
                            str(REPOSITORY_ROOT / "scripts" / "capture_process_manifest.py"),
                            "--runtime-events",
                            str(events_path),
                            "--minimum-processes",
                            str(minimum_processes),
                            "--repo-root",
                            str(REPOSITORY_ROOT),
                            "--output",
                            str(process_manifest),
                        ],
                        cwd=REPOSITORY_ROOT,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if capture.returncode == 0:
                        process_manifest_captured = True
                        break
            if fault_id == "F3" and process_manifest_captured:
                if target_cpu is None:
                    raise ValueError("F3 target CPU is required")
                process_record = json.loads(
                    (output_dir / "process_manifest.json").read_text(encoding="utf-8")
                )
                version = subprocess.run(
                    ["stress-ng", "--version"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                scheduler_manifest = capture_scheduler_manifest(
                    process_manifest=process_record,
                    condition_variant=condition_variant,
                    target_cpu=target_cpu,
                    ros_command=command,
                    stress_process_pid=(
                        stress_process.pid if stress_process is not None else None
                    ),
                    stress_command=stress_command or [],
                    stress_version=version,
                    ros_process_snapshots=ros_process_snapshots,
                    stress_process_pids=stress_process_pids,
                    stress_process_snapshots=stress_process_snapshots,
                )
                scheduler_manifest["captured_at_utc"] = datetime.now(
                    timezone.utc
                ).isoformat()
                scheduler_manifest["stress_log"] = (
                    str(output_dir / "stress.log") if stress_process is not None else ""
                )
            return_code = process.wait()
    finally:
        if stress_process is not None:
            cleanup_status = stop_process(stress_process, 3.0)
        if stress_handle is not None:
            stress_handle.close()
        if socketcan_capture is not None:
            socketcan_manifest = stop_socketcan_capture(
                socketcan_capture,
                output_dir / "socketcan_capture_manifest.json",
            )
        if scheduler_manifest is not None:
            scheduler_manifest["stress"]["cleanup_status"] = cleanup_status
            (output_dir / "scheduler_manifest.json").write_text(
                json.dumps(scheduler_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    if return_code not in {124, 130}:
        raise RuntimeError(
            f"fault launch failed with status {return_code}; see {launch_log}"
        )
    if not process_manifest_captured:
        raise RuntimeError("could not capture a complete live process manifest")
    summary = validate_fault_output(
        fault_id,
        workload,
        output_dir / "runtime_events.jsonl",
        condition_variant=condition_variant,
    )
    if tracing:
        ctf_files = [path for path in trace_dir.rglob("*") if path.is_file()]
        if not ctf_files:
            raise RuntimeError("ros2_tracing produced no CTF files")
        summary["ros2_tracing"] = {
            "ctf_path": str(trace_dir),
            "ctf_file_count": len(ctf_files),
            "clock_calibration": str(output_dir / "clock_calibration.json"),
            "process_manifest": str(output_dir / "process_manifest.json"),
        }
    if fault_id == "F3":
        scheduler_path = output_dir / "scheduler_manifest.json"
        if not scheduler_path.is_file():
            raise RuntimeError("F3 scheduler manifest is missing")
        summary["scheduler_manifest"] = str(scheduler_path)
    if socketcan_manifest is not None:
        summary["socketcan_capture_manifest"] = str(
            output_dir / "socketcan_capture_manifest.json"
        )
    return summary


def validate_fault_output(
    fault_id: str,
    workload: str,
    events_path: Path,
    *,
    condition_variant: str = "injected",
) -> dict[str, object]:
    if not events_path.is_file():
        raise FileNotFoundError(f"runtime events are missing: {events_path}")
    rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_names = {str(row.get("event_name", "")) for row in rows}
    trace_ids = {str(row.get("trace_id", "")) for row in rows if row.get("trace_id")}
    required = {
        "F1": {
            "planner_process_start",
            "planner_process_end",
            "planner_publish",
            "action_execute_end",
            "can_ack_received",
        },
        "F2": {"planner_receive", "planner_process_end", "planner_publish"},
        "F3": {
            "camera_frame_published",
            "planner_receive",
            "planner_process_start",
            "planner_process_end",
            "planner_publish",
        },
        "F4": {"service_process_start", "service_process_end", "response_received"},
        "F5": {"camera_frame_published", "planner_receive", "planner_process_end"},
        "F6": (
            {"can_ack_wait_start", "can_ack_timeout", "can_retry_exhausted"}
            if condition_variant == "injected"
            else {"can_ack_wait_start", "can_ack_received"}
        ),
    }[fault_id]
    missing = sorted(required - event_names)
    if missing:
        raise ValueError(f"{fault_id} output is missing events: {', '.join(missing)}")
    events_by_trace = {
        trace_id: {
            str(row.get("event_name", ""))
            for row in rows
            if row.get("trace_id") == trace_id
        }
        for trace_id in trace_ids
    }
    complete_trace_ids = {
        trace_id
        for trace_id, trace_events in events_by_trace.items()
        if required <= trace_events
    }
    if len(complete_trace_ids) < 2:
        raise ValueError(f"{workload} fault run produced fewer than two complete traces")
    return {
        "schema_version": "fault-run-summary/v1",
        "fault_id": fault_id,
        "workload": workload,
        "event_count": len(rows),
        "trace_count": len(trace_ids),
        "fault_complete_trace_count": len(complete_trace_ids),
        "incomplete_trace_count": len(trace_ids - complete_trace_ids),
        "required_events": sorted(required),
        "missing_events": missing,
    }


if __name__ == "__main__":
    raise SystemExit(main())
