"""Build and evaluate development-only F1 optimization runtime trials."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.adapters.mock_ack_lifecycle_adapter import _describe, _integer
from optimizer.action_registry.registry import validate_action


STAGES = ("planner_process_start", "planner_process_end")
SERVICE_STAGES = (
    "query_sent",
    "service_process_start",
    "service_process_end",
    "response_received",
)
SERVICE_SERVER_STAGES = {"service_process_start", "service_process_end"}


def build_trial_manifest(
    *,
    cause_id: str,
    candidate_config: dict[str, Any],
    trial_id: str,
    strategy: str,
    seed: int,
    git_commit: str,
    command: list[str],
) -> dict[str, Any]:
    _single_config(cause_id, candidate_config)
    if not trial_id or not strategy or len(git_commit) != 40 or not command:
        raise ValueError("complete trial identity is required")
    return {
        "schema_version": "optimization-runtime-trial-manifest/v1",
        "dataset_role": "development",
        "formal_optimization_allowed": False,
        "trial_id": trial_id,
        "strategy": strategy,
        "seed": seed,
        "cause_id": cause_id,
        "candidate_config": dict(candidate_config),
        "git_commit": git_commit,
        "command": list(command),
    }


def build_trial_command(
    cause_id: str, candidate_config: dict[str, Any], events_path: Path
) -> list[str]:
    action_id, value = _single_config(cause_id, candidate_config)
    if cause_id == "application_compute_delay" and action_id == "planner_delay_ms":
        return [
            "ros2",
            "launch",
            "runtime_bringup",
            "ai_runtime.launch.py",
            "profile:=enhanced",
            "camera_rate_hz:=4",
            "planner_backend:=mock",
            "action_manager_enabled:=true",
            "planner_delay_mode:=busy_compute",
            f"planner_delay_ms:={value}",
            "runtime_event_enabled:=true",
            f"output_path:={events_path.as_posix()}",
        ]
    if cause_id == "blocking_syscall_io" and action_id == "server_delay_ms":
        return [
            "ros2",
            "launch",
            "service_runtime_demo",
            "service_runtime_demo.launch.py",
            "request_rate_hz:=5",
            f"server_delay_ms:={value}",
            "runtime_events_enabled:=true",
            f"output_path:={events_path.as_posix()}",
        ]
    raise ValueError("unsupported runtime optimization trial")


def derive_f1_trial_report(
    runtime_records: Iterable[dict[str, Any]], candidate_config: dict[str, Any]
) -> dict[str, Any]:
    action_id, delay_ms = _single_config("application_compute_delay", candidate_config)
    if action_id != "planner_delay_ms":
        raise ValueError("F1 trial requires planner_delay_ms")
    by_trace: dict[str, list[dict[str, Any]]] = {}
    for record in runtime_records:
        trace_id = record.get("trace_id")
        if isinstance(trace_id, str) and trace_id and record.get("event_name") in STAGES:
            by_trace.setdefault(trace_id, []).append(record)

    incomplete = 0
    invalid: Counter[str] = Counter()
    elapsed: list[int] = []
    for rows in by_trace.values():
        counts = Counter(str(row.get("event_name", "")) for row in rows)
        if any(counts[name] > 1 for name in STAGES):
            invalid["duplicate_stage"] += 1
            continue
        if any(counts[name] == 0 for name in STAGES):
            incomplete += 1
            continue
        by_name = {str(row["event_name"]): row for row in rows}
        start = by_name["planner_process_start"]
        end = by_name["planner_process_end"]
        if any(not _integer(row.get("timestamp_ns")) for row in (start, end)):
            invalid["invalid_timestamp"] += 1
            continue
        if any(
            start.get(field) != end.get(field)
            for field in ("sequence_id", "host_id", "clock_id")
        ) or start.get("clock_id") != "monotonic":
            invalid["identity_mismatch"] += 1
            continue
        try:
            metadata = json.loads(start.get("extra_json", ""))
        except (json.JSONDecodeError, TypeError):
            invalid["invalid_extra_json"] += 1
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("planner_delay_ms") != delay_ms
            or metadata.get("planner_delay_mode") != "busy_compute"
        ):
            raise ValueError("runtime event does not match candidate profile")
        value = int(end["timestamp_ns"]) - int(start["timestamp_ns"])
        if value < 0:
            invalid["negative_interval"] += 1
            continue
        elapsed.append(value)

    observed = len(by_trace)
    complete = len(elapsed)
    return {
        "schema_version": "optimization-runtime-trial/v1",
        "cause_id": "application_compute_delay",
        "candidate_config": dict(candidate_config),
        "measurement_semantics": "runtime_event_elapsed_interval",
        "development_only": True,
        "formal_inference_allowed": False,
        "formal_optimization_allowed": False,
        "observed_trace_count": observed,
        "complete_trace_count": complete,
        "incomplete_trace_count": incomplete,
        "invalid_trace_count": sum(invalid.values()),
        "invalid_trace_reason_counts": dict(sorted(invalid.items())),
        "complete_trace_rate": complete / observed if observed else 0.0,
        "metrics_ns": {"planner_processing_elapsed_ns": _describe(elapsed)},
    }


def derive_f4_trial_report(
    runtime_records: Iterable[dict[str, Any]], candidate_config: dict[str, Any]
) -> dict[str, Any]:
    action_id, delay_ms = _single_config("blocking_syscall_io", candidate_config)
    if action_id != "server_delay_ms":
        raise ValueError("F4 trial requires server_delay_ms")
    by_trace: dict[str, list[dict[str, Any]]] = {}
    for record in runtime_records:
        trace_id = record.get("trace_id")
        if (
            isinstance(trace_id, str)
            and trace_id
            and record.get("event_name") in SERVICE_STAGES
        ):
            by_trace.setdefault(trace_id, []).append(record)

    incomplete = 0
    invalid: Counter[str] = Counter()
    values = {
        "server_processing_elapsed_ns": [],
        "request_response_elapsed_ns": [],
    }
    for trace_id, initial_rows in by_trace.items():
        rows = list(initial_rows)
        counts = Counter(str(row.get("event_name", "")) for row in rows)
        if any(counts[name] > 1 for name in SERVICE_STAGES):
            server_rows = {
                name: [row for row in rows if row.get("event_name") == name]
                for name in SERVICE_SERVER_STAGES
            }
            server_pids = {
                int(row["pid"])
                for items in server_rows.values()
                for row in items
                if _integer(row.get("pid"))
            }
            if not (
                counts["query_sent"] == counts["response_received"] == 1
                and all(len(server_rows[name]) == 2 for name in SERVICE_SERVER_STAGES)
                and len(server_pids) == 2
            ):
                invalid["duplicate_stage"] += 1
                continue
            selected_pid = min(server_pids)
            rows = [
                row
                for row in rows
                if row.get("event_name") not in SERVICE_SERVER_STAGES
                or int(row.get("pid")) == selected_pid
            ]
        counts = Counter(str(row.get("event_name", "")) for row in rows)
        if any(counts[name] == 0 for name in SERVICE_STAGES):
            incomplete += 1
            continue
        by_name = {str(row["event_name"]): row for row in rows}
        ordered = [by_name[name] for name in SERVICE_STAGES]
        if any(not _integer(row.get("timestamp_ns")) for row in ordered):
            invalid["invalid_timestamp"] += 1
            continue
        if len({row.get("sequence_id") for row in ordered}) != 1 or len(
            {row.get("host_id") for row in ordered}
        ) != 1 or {row.get("clock_id") for row in ordered} != {"monotonic"}:
            invalid["identity_mismatch"] += 1
            continue
        metadata: list[dict[str, Any]] = []
        try:
            for row in ordered:
                extra = json.loads(row.get("extra_json", ""))
                if not isinstance(extra, dict):
                    raise TypeError
                metadata.append(extra)
        except (json.JSONDecodeError, TypeError):
            invalid["invalid_extra_json"] += 1
            continue
        payload_ids = {extra.get("payload_id") for extra in metadata}
        if len(payload_ids) != 1 or None in payload_ids or "" in payload_ids:
            invalid["payload_identity_mismatch"] += 1
            continue
        if any(
            metadata[SERVICE_STAGES.index(name)].get("requested_delay_ms") != delay_ms
            for name in SERVICE_SERVER_STAGES
        ):
            raise ValueError("runtime event does not match candidate profile")
        timestamps = [int(row["timestamp_ns"]) for row in ordered]
        if timestamps != sorted(timestamps):
            invalid["stage_order_mismatch"] += 1
            continue
        query_ns, start_ns, end_ns, response_ns = timestamps
        values["server_processing_elapsed_ns"].append(end_ns - start_ns)
        values["request_response_elapsed_ns"].append(response_ns - query_ns)

    observed = len(by_trace)
    complete = len(values["request_response_elapsed_ns"])
    return {
        "schema_version": "optimization-runtime-trial/v1",
        "cause_id": "blocking_syscall_io",
        "candidate_config": dict(candidate_config),
        "measurement_semantics": "application_service_blocking_elapsed",
        "development_only": True,
        "formal_inference_allowed": False,
        "formal_optimization_allowed": False,
        "observed_trace_count": observed,
        "complete_trace_count": complete,
        "incomplete_trace_count": incomplete,
        "invalid_trace_count": sum(invalid.values()),
        "invalid_trace_reason_counts": dict(sorted(invalid.items())),
        "complete_trace_rate": complete / observed if observed else 0.0,
        "metrics_ns": {name: _describe(metric_values) for name, metric_values in values.items()},
    }


def _single_config(cause_id: str, config: dict[str, Any]) -> tuple[str, Any]:
    if not isinstance(config, dict) or len(config) != 1:
        raise ValueError("candidate configuration must contain one action")
    action_id, value = next(iter(config.items()))
    validate_action(cause_id, action_id, value)
    return action_id, value
