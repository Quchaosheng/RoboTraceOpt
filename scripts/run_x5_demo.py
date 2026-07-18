"""Run the deterministic physical CAN defense demonstration on an RDK X5."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_demo_plan(
    output_dir: Path,
    *,
    runtime_interface: str,
    peer_interface: str,
    bitrate: int,
    duration_seconds: int,
) -> list[dict[str, Any]]:
    if runtime_interface == peer_interface:
        raise ValueError("demo CAN interfaces must be distinct")
    if bitrate <= 0 or duration_seconds < 1:
        raise ValueError("bitrate and duration must be positive")

    root = output_dir.resolve()
    control = root / "control"
    injected = root / "injected"
    preflight = root / "preflight"
    common_fault = [
        "--fault-id",
        "F6",
        "--dataset-role",
        "development",
        "--capability",
        "ros2_runtime",
        "--capability",
        "runtime_event",
        "--capability",
        "socketcan_physical",
        "--duration-seconds",
        str(duration_seconds),
        "--f6-transport-profile",
        "physical",
        "--f6-can-interface",
        runtime_interface,
        "--f6-responder-interface",
        peer_interface,
        "--f6-bitrate",
        str(bitrate),
        "--execute",
    ]

    def fault_stage(variant: str, destination: Path) -> list[str]:
        return [
            "python3",
            "scripts/run_fault_condition.py",
            *common_fault,
            "--session-id",
            "x5-defense-demo",
            "--condition-id",
            f"physical-{variant}",
            "--condition-variant",
            variant,
            "--output-dir",
            destination.as_posix(),
        ]

    def adapter_stage(destination: Path) -> list[str]:
        return [
            "python3",
            "-m",
            "diagnosis.adapters.socketcan_ack_lifecycle_adapter",
            "--runtime-events",
            (destination / "runtime_events.jsonl").as_posix(),
            "--responder-events",
            (destination / "responder.jsonl").as_posix(),
            "--candump",
            (destination / "candump.log").as_posix(),
            "--run-manifest",
            (destination / "run_manifest.json").as_posix(),
            "--oracle-manifest",
            (destination / "oracle_manifest.json").as_posix(),
            "--capture-manifest",
            (destination / "socketcan_capture_manifest.json").as_posix(),
            "--output-events",
            (destination / "physical_ack_events.jsonl").as_posix(),
            "--output-report",
            (destination / "physical_ack_report.json").as_posix(),
        ]

    return [
        {
            "name": "preflight",
            "output_dir": preflight.as_posix(),
            "argv": [
                "python3",
                "scripts/preflight_x5.py",
                "--mode",
                "physical-can",
                "--runtime-interface",
                runtime_interface,
                "--peer-interface",
                peer_interface,
                "--bitrate",
                str(bitrate),
                "--output-json",
                (preflight / "report.json").as_posix(),
                "--output-md",
                (preflight / "report.md").as_posix(),
            ],
        },
        {
            "name": "control_capture",
            "output_dir": control.as_posix(),
            "argv": fault_stage("control", control),
        },
        {
            "name": "injected_capture",
            "output_dir": injected.as_posix(),
            "argv": fault_stage("injected", injected),
        },
        {
            "name": "control_adapter",
            "output_dir": control.as_posix(),
            "argv": adapter_stage(control),
        },
        {
            "name": "injected_adapter",
            "output_dir": injected.as_posix(),
            "argv": adapter_stage(injected),
        },
        {
            "name": "physical_comparison",
            "output_dir": root.as_posix(),
            "argv": [
                "python3",
                "-m",
                "experiments.fault_injection.compare_f6_physical_ack",
                "--injected-report",
                (injected / "physical_ack_report.json").as_posix(),
                "--control-report",
                (control / "physical_ack_report.json").as_posix(),
                "--output",
                (root / "physical_comparison.json").as_posix(),
            ],
        },
        {
            "name": "report",
            "output_dir": (root / "report").as_posix(),
            "argv": [
                "python3",
                "scripts/generate_experiment_report.py",
                "--source",
                root.as_posix(),
                "--output-dir",
                (root / "report").as_posix(),
            ],
        },
    ]


def execute_demo(
    plan: list[dict[str, Any]],
    output_dir: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    stages = [
        {
            "name": stage["name"],
            "argv": list(stage["argv"]),
            "output_dir": stage["output_dir"],
            "status": "pending",
            "returncode": None,
        }
        for stage in plan
    ]
    summary = {
        "schema_version": "x5-defense-demo/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "development_only": True,
        "formal_evidence": False,
        "stages": stages,
    }
    summary_path = output_dir / "demo_summary.json"
    _write_json_atomic(summary_path, summary)

    for index, stage in enumerate(stages):
        stage["status"] = "running"
        stage["started_at_utc"] = datetime.now(timezone.utc).isoformat()
        if stage["name"] == "report" and index == len(stages) - 1:
            summary["status"] = "completed"
        _write_json_atomic(summary_path, summary)
        log_path = output_dir / f"{index + 1:02d}_{stage['name']}.log"
        with log_path.open("x", encoding="utf-8") as handle:
            completed = runner(
                stage["argv"],
                cwd=REPOSITORY_ROOT,
                check=False,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        stage["returncode"] = int(completed.returncode)
        stage["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        stage["log"] = log_path.name
        if completed.returncode != 0:
            stage["status"] = "failed"
            summary["status"] = "failed"
            _write_json_atomic(summary_path, summary)
            return summary
        stage["status"] = "completed"
        _write_json_atomic(summary_path, summary)

    summary["status"] = "completed"
    _write_json_atomic(summary_path, summary)
    return summary


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-interface", default="can0")
    parser.add_argument("--peer-interface", default="can1")
    parser.add_argument("--bitrate", type=int, default=500_000)
    parser.add_argument("--duration-seconds", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_demo_plan(
        args.output_dir,
        runtime_interface=args.runtime_interface,
        peer_interface=args.peer_interface,
        bitrate=args.bitrate,
        duration_seconds=args.duration_seconds,
    )
    if args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        record = {
            "schema_version": "x5-defense-demo-plan/v1",
            "development_only": True,
            "formal_evidence": False,
            "stages": plan,
        }
        _write_json_atomic(args.output_dir / "demo_plan.json", record)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    summary = execute_demo(plan, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
