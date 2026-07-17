"""Execute one development-only F1 optimization candidate trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.fault_injection.runner import build_execution_script  # noqa: E402
from optimizer.trials.runtime_trial import (  # noqa: E402
    build_trial_command,
    build_trial_manifest,
    derive_f1_trial_report,
    derive_f2_trial_report,
    derive_f4_trial_report,
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--strategy", choices=("guided", "random"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    candidate = parser.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--planner-delay-ms", type=int)
    candidate.add_argument("--server-delay-ms", type=int)
    candidate.add_argument("--executor-threads", type=int)
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--safe-root",
        type=Path,
        default=Path.home() / ".cache" / "robotracert_fusion_build",
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError(f"trial output already exists: {args.output_dir}")
    if args.duration_seconds < 1:
        raise ValueError("duration-seconds must be positive")
    args.output_dir.mkdir(parents=True)
    events_path = (args.output_dir / "runtime_events.jsonl").resolve()
    if args.planner_delay_ms is not None:
        cause_id = "application_compute_delay"
        config = {"planner_delay_ms": args.planner_delay_ms}
        derive_report = derive_f1_trial_report
    elif args.server_delay_ms is not None:
        cause_id = "blocking_syscall_io"
        config = {"server_delay_ms": args.server_delay_ms}
        derive_report = derive_f4_trial_report
    else:
        cause_id = "executor_queueing"
        config = {"executor_threads": args.executor_threads}
        derive_report = derive_f2_trial_report
    command = build_trial_command(cause_id, config, events_path)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = build_trial_manifest(
        cause_id=cause_id,
        candidate_config=config,
        trial_id=args.trial_id,
        strategy=args.strategy,
        seed=args.seed,
        git_commit=git_commit,
        command=command,
    )
    manifest_path = args.output_dir / "trial_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    setup_path = args.safe_root / "install" / "setup.bash"
    if not setup_path.is_file():
        raise FileNotFoundError(f"ROS 2 build setup is missing: {setup_path}")
    ros_log_dir = args.safe_root / "ros_logs" / args.trial_id
    ros_log_dir.mkdir(parents=True, exist_ok=True)
    shell = build_execution_script(
        command,
        setup_path=setup_path,
        ros_log_dir=ros_log_dir,
        duration_seconds=args.duration_seconds,
    )
    launch_log = args.output_dir / "launch.log"
    with launch_log.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(["bash", "-lc", shell], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if completed.returncode not in {124, 130}:
        raise RuntimeError(f"optimization trial failed with status {completed.returncode}")
    report = derive_report(_read_jsonl(events_path), config)
    if report["complete_trace_count"] < 2:
        raise RuntimeError("optimization trial produced fewer than two complete traces")
    report["trial_manifest"] = str(manifest_path)
    report["input_sha256"] = {
        "runtime_events": _sha256(events_path),
        "trial_manifest": _sha256(manifest_path),
    }
    report_path = args.output_dir / "trial_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
