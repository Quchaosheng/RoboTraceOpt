"""Runtime trial contracts for diagnosis-supported optimization actions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from optimizer.action_registry.registry import validate_action


_PROFILES = {
    "application_compute_delay": {
        "action_id": "planner_delay_ms",
        "metric": "planner_processing_elapsed_ns",
        "quantile": "p95",
        "cli_argument": "--planner-delay-ms",
    },
    "executor_queueing": {
        "action_id": "executor_threads",
        "metric": "callback_dispatch_upper_bound_ns",
        "quantile": "p95",
        "cli_argument": "--executor-threads",
    },
    "blocking_syscall_io": {
        "action_id": "server_delay_ms",
        "metric": "request_response_elapsed_ns",
        "quantile": "p95",
        "cli_argument": "--server-delay-ms",
    },
    "dds_communication_delay": {
        "action_id": "frame_qos_depth",
        "metric": "camera_to_planner_upper_bound_ns",
        "quantile": "p95",
        "cli_argument": "--frame-qos-depth",
    },
}


def runtime_profile(cause_id: str) -> dict[str, str]:
    profile = _PROFILES.get(cause_id)
    if profile is None:
        raise ValueError(f"unsupported runtime cause: {cause_id}")
    return deepcopy(profile)


def candidate_cli_arguments(cause_id: str, config: dict[str, Any]) -> list[str]:
    if not isinstance(config, dict) or len(config) != 1:
        raise ValueError("candidate configuration must contain one action")
    action_id, value = next(iter(config.items()))
    profile = runtime_profile(cause_id)
    if action_id != profile["action_id"]:
        raise ValueError(
            f"expected action {profile['action_id']} for {cause_id}, got {action_id}"
        )
    validate_action(cause_id, action_id, value)
    return [profile["cli_argument"], str(value)]
