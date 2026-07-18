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
from typing import Any, Callable, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.evidence_capture.artifact_manifest import (  # noqa: E402
    build_artifact_manifest,
)
from experiments.evidence_capture.collector_lifecycle import (  # noqa: E402
    EvidenceCaptureError,
    build_ebpf_capture_argv,
    needs_process_manifest,
    remaining_capture_duration,
    validate_ebpf_identity,
    validate_ebpf_summary,
)
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
from scripts.export_ros2_trace import (  # noqa: E402
    EXPORT_SCHEMA,
    FAULT_REQUIRED_EVENTS,
)
from scripts.export_tracetools_fixture import directory_sha256  # noqa: E402


def try_snapshot_runtime_processes(
    events_path: Path, *, minimum_processes: int, target_cpu: int
) -> dict[str, dict[str, object]] | None:
    if minimum_processes < 1:
        raise ValueError("minimum_processes must be positive")
    processes = processes_from_runtime_events(events_path)
    if len(processes) < minimum_processes:
        return None
    return snapshot_scheduler_processes(dict(processes), target_cpu)


def fault_capture_plan(fault_id: str, capabilities: set[str]) -> dict[str, bool]:
    tracing = "ros2_tracing" in capabilities and fault_id in FAULT_REQUIRED_EVENTS
    ebpf = bool({"ebpf", "identity_comparable_ebpf"} & capabilities) and fault_id in {
        "F3",
        "F4",
    }
    return {
        "process_manifest": needs_process_manifest(
            ({"ros2_tracing"} if tracing else set()) | ({"ebpf"} if ebpf else set())
        ),
        "ebpf": ebpf,
        "ros2_export": tracing,
    }


def capture_ebpf_evidence(
    *,
    fault_id: str,
    output_dir: Path,
    process_manifest: Path,
    duration_seconds: float,
    elapsed_startup_seconds: float,
    execute: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Path]:
    manifest = _read_json(process_manifest)
    validate_ebpf_identity(manifest)
    duration = remaining_capture_duration(duration_seconds, elapsed_startup_seconds)
    events_path = output_dir / "ebpf_events.jsonl"
    summary_path = output_dir / "ebpf_capture_summary.json"
    argv = build_ebpf_capture_argv(
        python=Path(sys.executable),
        script=REPOSITORY_ROOT / "scripts" / "capture_ebpf_runtime.py",
        process_manifest=process_manifest,
        duration=duration,
        output=events_path,
        summary_output=summary_path,
    )
    completed = execute(argv, cwd=REPOSITORY_ROOT)
    if completed.returncode != 0:
        raise EvidenceCaptureError(
            "ebpf_capture_command_failed", "eBPF capture command failed"
        )
    if not events_path.is_file() or not summary_path.is_file():
        raise EvidenceCaptureError(
            "ebpf_capture_output_missing", "eBPF capture output is missing"
        )
    summary = validate_ebpf_summary(_read_json(summary_path), fault_id=fault_id)
    if summary.get("host_id") != manifest.get("host_id"):
        raise EvidenceCaptureError(
            "ebpf_host_mismatch", "eBPF capture host does not match process manifest"
        )
    return {
        "ebpf_events": events_path,
        "ebpf_capture_summary": summary_path,
    }


def export_ros2_evidence(
    *,
    fault_id: str,
    output_dir: Path,
    host_id: str,
    execute: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Path]:
    if fault_id not in FAULT_REQUIRED_EVENTS:
        raise ValueError(f"ROS 2 trace export is not registered for {fault_id}")
    trace_path = output_dir / "ctf"
    events_path = output_dir / "ros2_events.jsonl"
    manifest_path = output_dir / "ros2_events.manifest.json"
    argv = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "export_ros2_trace.py"),
        "--fault-id",
        fault_id,
        "--trace",
        str(trace_path),
        "--output-jsonl",
        str(events_path),
        "--output-manifest",
        str(manifest_path),
        "--host-id",
        host_id,
    ]
    completed = execute(argv, cwd=REPOSITORY_ROOT)
    if completed.returncode != 0:
        raise RuntimeError("ROS 2 trace export command failed")
    if not events_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("ROS 2 trace export output is missing")
    manifest = _read_json(manifest_path)
    counts = manifest.get("event_counts")
    if (
        manifest.get("schema_version") != EXPORT_SCHEMA
        or manifest.get("host_id") != host_id
        or manifest.get("source_trace_sha256") != directory_sha256(trace_path)
        or not isinstance(manifest.get("event_count"), int)
        or manifest["event_count"] < 1
        or not isinstance(counts, dict)
        or not FAULT_REQUIRED_EVENTS[fault_id] <= set(counts)
    ):
        raise RuntimeError("ROS 2 trace export manifest is invalid")
    return {
        "ros2_events": events_path,
        "ros2_events_manifest": manifest_path,
    }


def finalize_fault_artifacts(
    *,
    fault_id: str,
    condition_variant: str,
    dataset_role: str,
    output_dir: Path,
    paths: Mapping[str, Path],
) -> Path:
    manifest_path = output_dir / "artifact_manifest.json"
    if manifest_path.exists():
        raise ValueError(f"artifact manifest already exists: {manifest_path}")
    manifest = build_artifact_manifest(
        fault_id=fault_id,
        condition_variant=condition_variant,
        dataset_role=dataset_role,
        case_root=output_dir,
        artifacts=paths,
    )
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(manifest_path)
    return manifest_path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def validate_formal_qualification(
    qualification: dict[str, Any] | None,
    *,
    dataset_role: str,
    fault_id: str,
    condition_variant: str,
    case_id: str | None,
    git_commit: str,
    git_status: str,
) -> None:
    """Validate the outer qualification before a formal fault can start."""
    if dataset_role not in {"calibration", "test"}:
        return
    if qualification is None:
        raise ValueError("formal fault role requires a qualification report")
    if (
        qualification.get("schema_version") != "formal-experiment-qualification/v1"
        or qualification.get("status") != "allowed"
        or qualification.get("dataset_role") != dataset_role
        or qualification.get("development_only") is not False
    ):
        raise ValueError("qualification report does not allow formal fault role")
    if (
        dataset_role == "test"
        and qualification.get("formal_experiment_allowed") is not True
    ):
        raise ValueError("test fault is not formally qualified")
    if not case_id:
        raise ValueError("formal fault role requires case-id")
    expected_case_id = f"diagnosis_{fault_id.lower()}_{condition_variant}"
    if case_id != expected_case_id:
        raise ValueError("case-id does not match fault condition")
    selected = qualification.get("selected_case_ids")
    if not isinstance(selected, list) or case_id not in selected:
        raise ValueError("qualification report does not select this case")
    case_rows = qualification.get("cases")
    matching_rows = (
        [
            row
            for row in case_rows
            if isinstance(row, dict) and row.get("case_id") == case_id
        ]
        if isinstance(case_rows, list)
        else []
    )
    if (
        len(matching_rows) != 1
        or matching_rows[0].get("status") != "ready"
        or matching_rows[0].get("missing_requirements")
        or matching_rows[0].get("role_errors")
    ):
        raise ValueError("qualification report does not mark this case ready")
    for field in ("matrix_sha256", "capability_sha256"):
        value = qualification.get(field)
        if not (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"qualification report has invalid {field}")
    if qualification.get("git_commit") != git_commit:
        raise ValueError("qualification report git commit does not match")
    if qualification.get("git_status") or git_status:
        raise ValueError("formal fault requires a clean worktree")
    if condition_variant == "control":
        raise ValueError("control variant is development-only")
    if fault_id == "F5":
        raise ValueError("F5 is development-only until its profile is frozen")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault-id", required=True)
    parser.add_argument(
        "--dataset-role",
        choices=("development", "calibration", "test"),
        required=True,
    )
    parser.add_argument("--case-id")
    parser.add_argument("--qualification-report", type=Path)
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
        default=Path.home() / ".cache" / "robotraceopt_build",
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
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    qualification = (
        _read_json(args.qualification_report)
        if args.qualification_report is not None
        else None
    )
    validate_formal_qualification(
        qualification,
        dataset_role=args.dataset_role,
        fault_id=spec.fault_id,
        condition_variant=args.condition_variant,
        case_id=args.case_id,
        git_commit=git_commit,
        git_status=git_status,
    )
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
        summary, measurement_paths = execute_condition(
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
            f6_injection=(dict(oracle["injection"]) if spec.fault_id == "F6" else None),
            session_id=args.session_id,
        )
        summary_path = args.output_dir / "summary.json"
        _write_json_atomic(summary_path, summary)
        paths["summary"] = summary_path
        artifact_paths = {
            "runtime_events": events_path,
            "run_manifest": paths["public_manifest"],
            "oracle_manifest": paths["oracle_manifest"],
            "command_manifest": paths["command"],
            "fault_summary": summary_path,
            **measurement_paths,
        }
        paths["artifact_manifest"] = finalize_fault_artifacts(
            fault_id=spec.fault_id,
            condition_variant=args.condition_variant,
            dataset_role=args.dataset_role,
            output_dir=args.output_dir,
            paths=artifact_paths,
        )
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
) -> tuple[dict[str, object], dict[str, Path]]:
    setup_path = safe_root / "install" / "setup.bash"
    if not setup_path.is_file():
        raise FileNotFoundError(f"ROS 2 build setup is missing: {setup_path}")
    ros_log_dir = safe_root / "ros_logs" / output_dir.name
    ros_log_dir.mkdir(parents=True, exist_ok=True)
    capture_plan = fault_capture_plan(fault_id, capabilities)
    tracing = capture_plan["ros2_export"]
    measurement_paths: dict[str, Path] = {}
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
        measurement_paths["clock_calibration"] = output_dir / "clock_calibration.json"
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
            workload_started = time.monotonic()
            process_manifest_captured = not capture_plan["process_manifest"]
            if capture_plan["process_manifest"]:
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
                            str(
                                REPOSITORY_ROOT
                                / "scripts"
                                / "capture_process_manifest.py"
                            ),
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
                        measurement_paths["process_manifest"] = process_manifest
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
            if capture_plan["ebpf"]:
                measurement_paths.update(
                    capture_ebpf_evidence(
                        fault_id=fault_id,
                        output_dir=output_dir,
                        process_manifest=output_dir / "process_manifest.json",
                        duration_seconds=duration_seconds,
                        elapsed_startup_seconds=time.monotonic() - workload_started,
                    )
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
        measurement_paths["ros2_ctf"] = trace_dir
        measurement_paths.update(
            export_ros2_evidence(
                fault_id=fault_id,
                output_dir=output_dir,
                host_id=socket.gethostname(),
            )
        )
    if fault_id == "F3":
        scheduler_path = output_dir / "scheduler_manifest.json"
        if not scheduler_path.is_file():
            raise RuntimeError("F3 scheduler manifest is missing")
        summary["scheduler_manifest"] = str(scheduler_path)
        measurement_paths["scheduler_manifest"] = scheduler_path
    if socketcan_manifest is not None:
        summary["socketcan_capture_manifest"] = str(
            output_dir / "socketcan_capture_manifest.json"
        )
    return summary, measurement_paths


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
        raise ValueError(
            f"{workload} fault run produced fewer than two complete traces"
        )
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
