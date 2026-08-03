#!/usr/bin/env python3
"""Run trace-scoped AI planner delivery and fail-closed fault campaigns."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ai_campaign_contract import select_trace_events, summarize_trace, validate_trace


@dataclass(frozen=True)
class Condition:
    name: str
    backend: str
    api_style: str
    timeout_s: float
    endpoint_profile: str
    expected_terminal_stage: str
    expected_outcome: str
    repetitions: int
    observation_ttl_ms: int = 1000
    model_queue_delay_ms: int = 0
    camera_rate_hz: float = 1.0
    second_camera_enabled: bool = False
    fixed_duplicate_identity: bool = False
    failure_storm_count: int = 3
    record_decisions: bool = False


class FaultHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if "/timeout/" in self.path:
            time.sleep(2.0)
            self._write_json(200, self._valid_response())
            return
        if "/delayed/" in self.path:
            time.sleep(0.25)
            self._write_json(200, self._valid_response())
            return
        if "/reset/" in self.path:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if "/unavailable/" in self.path:
            self._write_json(
                503,
                {
                    "error": {
                        "type": "service_unavailable",
                        "code": "injected_503",
                        "message": "deterministic campaign fault",
                    }
                },
            )
            return
        if "/invalid/" in self.path:
            self._write_json(
                200,
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "not-json"}],
                        }
                    ],
                },
            )
            return
        self._write_json(404, {"error": {"type": "not_found"}})

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _valid_response() -> dict[str, Any]:
        decision = (
            '{"action":"stop","target":"robot","speed":0,'
            '"confidence":1,"reason":"fault test"}'
        )
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": decision}],
                }
            ],
        }

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--real-repetitions", type=int, default=5)
    parser.add_argument("--mock-repetitions", type=int, default=3)
    parser.add_argument("--fault-repetitions", type=int, default=3)
    parser.add_argument("--real-timeout-s", type=float, default=30.0)
    parser.add_argument("--api-style", default=os.environ.get("LLM_API_STYLE", "responses"))
    parser.add_argument(
        "--install-prefix",
        type=Path,
        default=Path.home() / ".cache" / "robotraceopt_build" / "install",
    )
    return parser.parse_args()


def conditions(args: argparse.Namespace) -> list[Condition]:
    fault = args.fault_repetitions
    return [
        Condition(
            "A0_mock_delivery",
            "mock",
            args.api_style,
            3.0,
            "real",
            "can_ack_received",
            "delivery",
            args.mock_repetitions,
            record_decisions=True,
        ),
        Condition(
            "A1_real_llm_delivery",
            "llm",
            args.api_style,
            args.real_timeout_s,
            "real",
            "can_ack_received",
            "delivery",
            args.real_repetitions,
        ),
        Condition(
            "A2_timeout_fail_closed",
            "llm",
            "responses",
            0.1,
            "timeout",
            "planner_command_abstained",
            "fail_closed",
            fault,
        ),
        Condition(
            "A2_unavailable_fail_closed",
            "llm",
            "responses",
            2.0,
            "unavailable",
            "planner_command_abstained",
            "fail_closed",
            fault,
        ),
        Condition(
            "A2_invalid_json_fail_closed",
            "llm",
            "responses",
            2.0,
            "invalid",
            "planner_command_abstained",
            "fail_closed",
            fault,
        ),
        Condition(
            "A2_connection_reset_fail_closed",
            "llm",
            "responses",
            2.0,
            "reset",
            "planner_command_abstained",
            "fail_closed",
            fault,
        ),
        Condition(
            "F7_model_queue_deadline",
            "mock",
            args.api_style,
            3.0,
            "real",
            "planner_queue_deadline_exceeded",
            "queue_expired",
            fault,
            observation_ttl_ms=25,
            model_queue_delay_ms=100,
        ),
        Condition(
            "F9_stale_model_output",
            "llm",
            "responses",
            2.0,
            "delayed",
            "planner_output_stale",
            "stale_output",
            fault,
            observation_ttl_ms=25,
        ),
        Condition(
            "F10_fallback_storm",
            "llm",
            "responses",
            2.0,
            "unavailable",
            "planner_fallback_storm",
            "fallback_storm",
            1,
            camera_rate_hz=5.0,
            failure_storm_count=3,
        ),
        Condition(
            "A3_duplicate_request",
            "mock",
            args.api_style,
            3.0,
            "real",
            "planner_duplicate_request",
            "duplicate_request",
            1,
            second_camera_enabled=True,
            fixed_duplicate_identity=True,
        ),
    ]


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            try:
                extra = json.loads(row.get("extra_json", "{}"))
            except json.JSONDecodeError:
                extra = {}
            row["extra"] = extra if isinstance(extra, dict) else {}
            rows.append(row)
    return rows


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3.0)


def _first_stage(rows: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("stage") == stage), None)


def launch_trial(
    condition: Condition,
    run_dir: Path,
    fault_port: int,
    *,
    vision_mode: str = "metadata",
    image_file: Path | None = None,
    image_encoding: str = "jpeg",
    image_width: int = 640,
    image_height: int = 480,
    model_record_path: Path | None = None,
    model_replay_path: Path | None = None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True)
    events_path = run_dir / "runtime_events.jsonl"
    log_path = run_dir / "launch.log"
    env = os.environ.copy()
    api_base = env.get("LLM_API_BASE", "")
    model = env.get("LLM_MODEL", "")
    if condition.endpoint_profile != "real":
        api_base = f"http://127.0.0.1:{fault_port}/{condition.endpoint_profile}/v1"
        model = "deterministic-fault-model"
        env["LLM_API_KEY"] = "campaign-placeholder"

    command = [
        "ros2",
        "launch",
        "runtime_bringup",
        "ai_runtime.launch.py",
        "profile:=enhanced",
        f"camera_rate_hz:={condition.camera_rate_hz}",
        f"planner_backend:={condition.backend}",
        f"llm_api_style:={condition.api_style}",
        f"llm_api_base:={api_base}",
        f"llm_model:={model}",
        f"llm_timeout_s:={condition.timeout_s}",
        f"llm_vision_mode:={vision_mode}",
        f"observation_ttl_ms:={condition.observation_ttl_ms}",
        f"model_queue_delay_ms:={condition.model_queue_delay_ms}",
        f"model_failure_storm_count:={condition.failure_storm_count}",
        "fallback_to_mock:=false",
        "action_manager_enabled:=true",
        "ack_mode:=mock",
        "mock_mode:=true",
        f"second_camera_enabled:={'true' if condition.second_camera_enabled else 'false'}",
        f"output_path:={events_path}",
    ]
    if condition.fixed_duplicate_identity:
        command.extend(
            [
                "camera_fixed_trace_id:=duplicate-trace",
                "camera_fixed_oracle_id:=duplicate-oracle",
                "camera_fixed_sequence_id:=1",
            ]
        )
    if model_record_path is not None:
        command.append(f"model_record_path:={model_record_path.resolve()}")
    if model_replay_path is not None:
        command.append(f"model_replay_path:={model_replay_path.resolve()}")
    if image_file is not None:
        command.extend(
            [
                f"camera_image_file:={image_file.resolve()}",
                f"camera_encoding:={image_encoding}",
                f"camera_width:={image_width}",
                f"camera_height:={image_height}",
            ]
        )

    started_ns = time.monotonic_ns()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        max_runtime_s = (
            45.0
            if condition.backend == "llm" and condition.endpoint_profile == "real"
            else 12.0
        )
        deadline = time.monotonic() + max_runtime_s
        while time.monotonic() < deadline and process.poll() is None:
            _, scoped_rows = select_trace_events(
                read_rows(events_path), condition.expected_terminal_stage
            )
            if scoped_rows:
                time.sleep(0.75)
                break
            time.sleep(0.15)
        stop_process(process)

    rows = read_rows(events_path)
    selected_key, scoped_rows = select_trace_events(rows, condition.expected_terminal_stage)
    trace_summary = summarize_trace(scoped_rows)
    semantic_errors = (
        validate_trace(trace_summary, condition.expected_outcome)
        if scoped_rows
        else ["expected_terminal_not_observed"]
    )
    camera = _first_stage(scoped_rows, "camera_publish")
    ack = _first_stage(scoped_rows, "can_ack_received")
    planner_end = _first_stage(scoped_rows, "planner_process_end")
    planner_publish = _first_stage(scoped_rows, "planner_publish")
    publish_extra = planner_publish.get("extra", {}) if planner_publish else {}
    return {
        "status": "complete" if not semantic_errors else "invalid",
        "condition": condition.name,
        "expected_outcome": condition.expected_outcome,
        "expected_terminal_stage": condition.expected_terminal_stage,
        "semantic_errors": semantic_errors,
        "event_count": len(scoped_rows),
        "trace_id": selected_key[0] if selected_key else None,
        "oracle_id": selected_key[1] if selected_key else None,
        "sequence_id": selected_key[2] if selected_key else None,
        "planner_duration_ms": (
            float(planner_end.get("duration_ns", 0)) / 1_000_000.0
            if planner_end
            else None
        ),
        "end_to_end_command_delivery_ms": (
            (int(ack["timestamp_ns"]) - int(camera["timestamp_ns"])) / 1_000_000.0
            if camera and ack
            else None
        ),
        "effective_backend": publish_extra.get("effective_backend"),
        "used_fallback": bool(trace_summary["used_fallback"]),
        "fallback_reason_codes": trace_summary["model_error_codes"],
        "action": publish_extra.get("action"),
        "command_delivery_observed": bool(trace_summary["can_ack_count"]),
        "task_success_observed": None,
        "task_success_semantics": "not_measured_by_runtime_event_campaign",
        "trace_summary": trace_summary,
        "recording_enabled": model_record_path is not None,
        "replay_enabled": model_replay_path is not None,
        "wall_duration_ms": (time.monotonic_ns() - started_ns) / 1_000_000.0,
        "events_path": str(events_path),
        "log_path": str(log_path),
    }


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[rank]


def aggregate(name: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    planner = [
        float(trial["planner_duration_ms"])
        for trial in trials
        if trial["planner_duration_ms"] is not None
    ]
    delivery = [
        float(trial["end_to_end_command_delivery_ms"])
        for trial in trials
        if trial["end_to_end_command_delivery_ms"] is not None
    ]
    publishes = sum(int(trial["trace_summary"]["planner_publish_count"]) for trial in trials)
    acknowledgements = sum(int(trial["trace_summary"]["can_ack_count"]) for trial in trials)
    rejected = sum(
        bool(trial["trace_summary"]["abstain_count"])
        or bool(trial["trace_summary"]["request_rejection_count"])
        or bool(trial["trace_summary"]["can_rejection_count"])
        for trial in trials
    )
    return {
        "condition": name,
        "trial_count": len(trials),
        "complete_count": sum(trial["status"] == "complete" for trial in trials),
        "completion_rate": (
            sum(trial["status"] == "complete" for trial in trials) / len(trials)
            if trials
            else None
        ),
        "fallback_rate": sum(trial["used_fallback"] for trial in trials) / len(trials),
        "rejection_rate": rejected / len(trials),
        "safe_abstain_rate": (
            sum(bool(trial["trace_summary"]["abstain_count"]) for trial in trials)
            / len(trials)
        ),
        "command_delivery_rate": acknowledgements / publishes if publishes else None,
        "task_success_rate": None,
        "task_success_semantics": "not_measured_by_runtime_event_campaign",
        "planner_latency_ms": {
            "median": statistics.median(planner) if planner else None,
            "p95": percentile(planner, 0.95),
            "minimum": min(planner) if planner else None,
            "maximum": max(planner) if planner else None,
        },
        "command_delivery_latency_ms": {
            "median": statistics.median(delivery) if delivery else None,
            "p95": percentile(delivery, 0.95),
        },
        "model_error_codes": sorted(
            {
                code
                for trial in trials
                for code in trial["trace_summary"]["model_error_codes"]
            }
        ),
    }


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_trial(run_dir: Path, trial: dict[str, Any]) -> None:
    (run_dir / "trial_summary.json").write_text(
        json.dumps(trial, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    if any(
        value <= 0
        for value in (
            args.real_repetitions,
            args.mock_repetitions,
            args.fault_repetitions,
        )
    ):
        raise SystemExit("repetition counts must be positive")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.output_dir}")
    if not (args.install_prefix / "setup.bash").is_file():
        raise SystemExit(f"ROS install prefix is missing: {args.install_prefix}")
    for name in ("LLM_API_BASE", "LLM_API_KEY", "LLM_MODEL"):
        if not os.environ.get(name):
            raise SystemExit(f"missing environment variable: {name}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FaultHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    all_trials = []
    replay_source: Path | None = None
    try:
        for condition in conditions(args):
            for repetition in range(1, condition.repetitions + 1):
                print(
                    f"running {condition.name} {repetition}/{condition.repetitions}",
                    flush=True,
                )
                run_dir = args.output_dir / condition.name / f"run_{repetition:02d}"
                record_path = (
                    run_dir / "planner_decisions.jsonl"
                    if condition.record_decisions
                    else None
                )
                trial = launch_trial(
                    condition,
                    run_dir,
                    server.server_port,
                    model_record_path=record_path,
                )
                trial["repetition"] = repetition
                all_trials.append(trial)
                write_trial(run_dir, trial)
                if (
                    replay_source is None
                    and record_path is not None
                    and record_path.is_file()
                    and trial["status"] == "complete"
                ):
                    replay_source = record_path

        if replay_source is not None:
            replay_condition = Condition(
                "R1_recorded_mock_replay",
                "replay",
                args.api_style,
                3.0,
                "real",
                "can_ack_received",
                "replay_delivery",
                1,
            )
            run_dir = args.output_dir / replay_condition.name / "run_01"
            print("running R1_recorded_mock_replay 1/1", flush=True)
            replay_trial = launch_trial(
                replay_condition,
                run_dir,
                server.server_port,
                model_replay_path=replay_source,
            )
            replay_trial["repetition"] = 1
            all_trials.append(replay_trial)
            write_trial(run_dir, replay_trial)
    finally:
        server.shutdown()
        server_thread.join(timeout=2.0)
        server.server_close()

    grouped = {
        condition_name: [
            trial for trial in all_trials if trial["condition"] == condition_name
        ]
        for condition_name in sorted({trial["condition"] for trial in all_trials})
    }
    summary = {
        "schema_version": "ai-planner-campaign-summary/v2",
        "status": (
            "complete" if all(trial["status"] == "complete" for trial in all_trials) else "invalid"
        ),
        "host": socket.gethostname(),
        "software_commit": git_commit(),
        "model": os.environ["LLM_MODEL"],
        "api_style": args.api_style,
        "vision_mode": "metadata",
        "secret_recorded": False,
        "task_success_semantics": "not_measured_by_runtime_event_campaign",
        "trial_count": len(all_trials),
        "conditions": [
            aggregate(name, trials) for name, trials in grouped.items()
        ],
        "trials": all_trials,
    }
    (args.output_dir / "campaign_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": summary["status"], "trial_count": len(all_trials)}))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
