"""Small, explicit registry for diagnosis-constrained optimization actions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


_REGISTRY_PATH = Path(__file__).with_name("actions.json")


def _load() -> list[dict[str, Any]]:
    payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "optimizer-action-registry/v1":
        raise ValueError("unsupported optimizer action registry schema")
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("optimizer action registry is empty")
    return actions


def available_actions() -> list[dict[str, Any]]:
    return deepcopy(_load())


def actions_for_cause(cause_id: str) -> list[dict[str, Any]]:
    if not isinstance(cause_id, str) or not cause_id:
        raise ValueError("unknown cause")
    actions = [item for item in _load() if cause_id in item.get("causes", [])]
    if not actions:
        raise ValueError(f"unknown cause: {cause_id}")
    return deepcopy(actions)


def validate_action(cause_id: str, action_id: str, value: Any) -> None:
    actions = actions_for_cause(cause_id)
    action = next(
        (item for item in actions if item.get("action_id") == action_id), None
    )
    if action is None:
        raise ValueError(f"action {action_id} is not allowed for cause {cause_id}")
    kind = action.get("kind")
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"action {action_id} expects boolean")
        return
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"action {action_id} expects integer")
        bounds = action.get("bounds", {})
        if not bounds["min"] <= value <= bounds["max"]:
            raise ValueError(f"action {action_id} is outside bounds")
        return
    raise ValueError(f"unsupported action kind for {action_id}")
