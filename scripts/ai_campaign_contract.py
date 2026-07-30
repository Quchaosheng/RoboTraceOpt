"""Trace-scoped semantics for AI planner evidence campaigns."""

from __future__ import annotations

from collections import Counter
from typing import Any


MOTION_ACTIONS = {"move_forward", "turn_left", "turn_right"}


def trace_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("trace_id", "")),
        str(row.get("oracle_id", "")),
        int(row.get("sequence_id", 0)),
    )


def select_trace_events(
    rows: list[dict[str, Any]], terminal_stage: str
) -> tuple[tuple[str, str, int] | None, list[dict[str, Any]]]:
    """Select one complete trace instead of mixing first matching rows."""

    terminal = next((row for row in rows if row.get("stage") == terminal_stage), None)
    if terminal is None:
        return None, []
    selected_key = trace_key(terminal)
    return selected_key, [row for row in rows if trace_key(row) == selected_key]


def summarize_trace(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stages = [str(row.get("stage", "")) for row in rows]
    counter = Counter(stages)
    publishes = [row for row in rows if row.get("stage") == "planner_publish"]
    publish_extras = [row.get("extra", {}) for row in publishes]
    actions = [str(extra.get("action", "")) for extra in publish_extras]
    model_errors = sorted(
        {
            str(row.get("extra", {}).get("model_error_code", ""))
            for row in rows
            if str(row.get("extra", {}).get("model_error_code", ""))
        }
    )
    reasons = sorted(
        {str(row.get("reason_code", "")) for row in rows if row.get("reason_code")}
    )
    storm_events = [
        row for row in rows if row.get("stage") == "planner_fallback_storm"
    ]
    storm_failure_count = max(
        (
            int(row.get("extra", {}).get("model_failure_count_in_window", 0))
            for row in storm_events
        ),
        default=0,
    )
    return {
        "event_count": len(rows),
        "stages": stages,
        "stage_counts": dict(sorted(counter.items())),
        "planner_publish_count": counter["planner_publish"],
        "motion_publish_count": sum(action in MOTION_ACTIONS for action in actions),
        "published_actions": actions,
        "backend_failure_count": counter["planner_backend_failure"],
        "abstain_count": counter["planner_command_abstained"],
        "request_rejection_count": counter["planner_request_rejected"],
        "duplicate_request_count": counter["planner_duplicate_request"],
        "queue_deadline_count": counter["planner_queue_deadline_exceeded"],
        "stale_output_count": counter["planner_output_stale"],
        "fallback_storm_count": counter["planner_fallback_storm"],
        "fallback_storm_failure_count": storm_failure_count,
        "can_ack_count": counter["can_ack_received"],
        "can_rejection_count": counter["can_command_rejected"],
        "action_execution_complete_count": counter["action_execute_end"],
        "model_error_codes": model_errors,
        "reason_codes": reasons,
        "used_fallback": any(
            bool(row.get("extra", {}).get("used_fallback", False)) for row in rows
        ),
        "model_replayed": any(
            bool(row.get("extra", {}).get("model_replayed", False)) for row in publishes
        ),
        "effective_backends": sorted(
            {
                str(row.get("extra", {}).get("effective_backend", ""))
                for row in rows
                if row.get("extra", {}).get("effective_backend")
            }
        ),
    }


def validate_trace(summary: dict[str, Any], outcome: str) -> list[str]:
    """Verify an explicit delivery/fail-closed outcome for one trace."""

    errors = []
    stages = list(summary["stages"])
    publish_count = int(summary["planner_publish_count"])
    ack_count = int(summary["can_ack_count"])
    abstain_count = int(summary["abstain_count"])
    failure_count = int(summary["backend_failure_count"])

    if stages and "planner_receive" in stages:
        if stages.index("planner_receive") > min(
            (
                index
                for index, stage in enumerate(stages)
                if stage
                in {
                    "planner_publish",
                    "planner_command_abstained",
                    "planner_request_rejected",
                }
            ),
            default=len(stages),
        ):
            errors.append("planner_terminal_precedes_receive")

    if outcome in {"delivery", "replay_delivery"}:
        if publish_count != 1:
            errors.append("delivery_requires_one_planner_publish")
        if ack_count != 1:
            errors.append("delivery_requires_one_can_ack")
        if abstain_count or failure_count or int(summary["can_rejection_count"]):
            errors.append("delivery_contains_rejection_or_failure")
        if not summary["published_actions"]:
            errors.append("delivery_action_missing")
        if outcome == "replay_delivery":
            if not summary["model_replayed"]:
                errors.append("replay_delivery_missing_replay_marker")
            if "replay" not in summary["effective_backends"]:
                errors.append("replay_delivery_backend_mismatch")
    elif outcome == "fail_closed":
        if publish_count or ack_count:
            errors.append("failed_model_output_reached_downstream")
        if abstain_count < 1:
            errors.append("fail_closed_missing_abstention")
        if failure_count < 1:
            errors.append("fail_closed_missing_backend_failure")
    elif outcome == "queue_expired":
        if publish_count or ack_count:
            errors.append("expired_queue_output_reached_downstream")
        if int(summary["queue_deadline_count"]) < 1 or abstain_count < 1:
            errors.append("queue_expiry_not_observed")
    elif outcome == "stale_output":
        if publish_count or ack_count:
            errors.append("stale_output_reached_downstream")
        if int(summary["stale_output_count"]) < 1 or abstain_count < 1:
            errors.append("stale_output_not_observed")
    elif outcome == "duplicate_request":
        if int(summary["duplicate_request_count"]) < 1:
            errors.append("duplicate_request_not_observed")
        if publish_count > 1 or ack_count > 1:
            errors.append("duplicate_request_published_more_than_once")
    elif outcome == "fallback_storm":
        if publish_count or ack_count:
            errors.append("fallback_storm_output_reached_downstream")
        if int(summary["fallback_storm_count"]) < 1:
            errors.append("fallback_storm_not_observed")
        if failure_count < 1 or int(summary["fallback_storm_failure_count"]) < 3:
            errors.append("fallback_storm_has_too_few_failures")
    else:
        errors.append("unknown_outcome")
    return errors
