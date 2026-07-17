"""Deterministic candidate generation constrained by diagnosed root cause."""

from __future__ import annotations

from typing import Any

from optimizer.action_registry.registry import actions_for_cause, validate_action


def sample_candidates(cause_id: str, *, limit: int, seed: int = 0) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be positive")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    actions = actions_for_cause(cause_id)
    if len(actions) != 1:
        raise ValueError("sampler currently requires one action per cause")
    action = actions[0]
    action_id = str(action["action_id"])
    if action["kind"] == "boolean":
        values: list[Any] = [False, True]
    else:
        lower = int(action["bounds"]["min"])
        upper = int(action["bounds"]["max"])
        count = min(limit, upper - lower + 1)
        if count == 1:
            values = [lower]
        else:
            values = [round(lower + index * (upper - lower) / (count - 1)) for index in range(count)]
    candidates = [{action_id: value} for value in values[:limit]]
    for candidate in candidates:
        validate_action(cause_id, action_id, candidate[action_id])
    return candidates
