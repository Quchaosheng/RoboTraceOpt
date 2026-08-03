#!/usr/bin/env python3
"""Run the real planner on a fixed set of JPEG images through ROS 2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import struct
import subprocess
from pathlib import Path

from run_ai_planner_campaign import Condition, launch_trial, percentile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image", action="append", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    return parser.parse_args()


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError(f"not a JPEG image: {path}")
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    raise ValueError(f"JPEG dimensions were not found: {path}")


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def main() -> int:
    args = parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.output_dir}")
    for name in ("LLM_API_BASE", "LLM_API_KEY", "LLM_MODEL"):
        if not os.environ.get(name):
            raise SystemExit(f"missing environment variable: {name}")
    images = [path.resolve() for path in args.image]
    for path in images:
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"image is missing or empty: {path}")
        if path.stat().st_size > 1_000_000:
            raise SystemExit(f"image exceeds the configured 1 MB limit: {path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    condition = Condition(
        "V1_real_vision",
        "llm",
        os.environ.get("LLM_API_STYLE", "responses"),
        args.timeout_s,
        "real",
        "can_ack_received",
        "delivery",
        len(images),
    )
    trials = []
    for index, image_path in enumerate(images, 1):
        width, height = jpeg_dimensions(image_path)
        run_dir = args.output_dir / condition.name / f"run_{index:02d}"
        print(f"running image {index}/{len(images)}: {image_path.name}", flush=True)
        trial = launch_trial(
            condition,
            run_dir,
            0,
            vision_mode="payload_base64",
            image_file=image_path,
            image_encoding="jpeg",
            image_width=width,
            image_height=height,
        )
        trial.update(
            {
                "repetition": index,
                "image_name": image_path.name,
                "image_bytes": image_path.stat().st_size,
                "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "image_width": width,
                "image_height": height,
            }
        )
        trials.append(trial)
        (run_dir / "trial_summary.json").write_text(
            json.dumps(trial, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    durations = [
        float(t["planner_duration_ms"])
        for t in trials
        if t["planner_duration_ms"] is not None
    ]
    delivered = sum(bool(trial["command_delivery_observed"]) for trial in trials)
    summary = {
        "schema_version": "ai-vision-set-summary/v2",
        "status": "complete" if all(t["status"] == "complete" for t in trials) else "invalid",
        "software_commit": git_commit(),
        "model": os.environ["LLM_MODEL"],
        "api_style": condition.api_style,
        "vision_mode": "payload_base64",
        "secret_recorded": False,
        "task_success_semantics": "not_measured_by_runtime_event_campaign",
        "trial_count": len(trials),
        "command_delivery_rate": delivered / len(trials) if trials else None,
        "task_success_rate": None,
        "planner_latency_ms": {
            "median": statistics.median(durations) if durations else None,
            "p95": percentile(durations, 0.95),
            "minimum": min(durations) if durations else None,
            "maximum": max(durations) if durations else None,
        },
        "trials": trials,
    }
    (args.output_dir / "campaign_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": summary["status"], "trial_count": len(trials)}))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
