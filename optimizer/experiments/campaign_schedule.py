"""Build deterministic balanced schedules for repeated optimization trials."""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from optimizer.integration.runtime_profiles import candidate_cli_arguments


_CAMPAIGN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def config_id(config: dict[str, Any]) -> str:
    payload = _canonical_config(config).encode()
    return f"cfg_{hashlib.sha256(payload).hexdigest()[:12]}"


def validate_campaign_parameters(
    *, repetitions: int, seed: int, campaign_name: str
) -> None:
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 2:
        raise ValueError("repetitions must be an integer of at least two")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not isinstance(campaign_name, str) or _CAMPAIGN_NAME.fullmatch(campaign_name) is None:
        raise ValueError("invalid campaign name")


def build_repeated_schedule(
    execution_schedule: dict[str, Any],
    *,
    repetitions: int,
    seed: int,
    campaign_name: str,
) -> dict[str, Any]:
    if execution_schedule.get("schema_version") != "optimization-execution-schedule/v1":
        raise ValueError("invalid execution schedule schema")
    validate_campaign_parameters(
        repetitions=repetitions, seed=seed, campaign_name=campaign_name
    )

    cause_id = execution_schedule.get("cause_id")
    action_id = execution_schedule.get("action_id")
    baseline = execution_schedule.get("baseline_config")
    if not isinstance(cause_id, str) or not isinstance(action_id, str):
        raise ValueError("execution schedule requires cause and action")
    candidate_cli_arguments(cause_id, baseline)
    rows = execution_schedule.get("trials")
    if not isinstance(rows, list):
        raise ValueError("execution schedule requires trials")

    raw_configs: list[tuple[str, dict[str, Any]]] = [("baseline", dict(baseline))]
    seen = {_canonical_config(baseline)}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("execution schedule trial must be an object")
        if row.get("status") != "scheduled":
            continue
        config = row.get("candidate_config")
        candidate_cli_arguments(cause_id, config)
        canonical = _canonical_config(config)
        if canonical in seen:
            continue
        seen.add(canonical)
        raw_configs.append(("candidate", dict(config)))

    configurations = [
        {
            "config_index": index,
            "config_id": config_id(config),
            "role": role,
            "candidate_config": config,
            "position_counts": {
                str(position): 0 for position in range(1, len(raw_configs) + 1)
            },
        }
        for index, (role, config) in enumerate(raw_configs)
    ]
    by_id = {str(row["config_id"]): row for row in configurations}
    order = [str(row["config_id"]) for row in configurations]
    random.Random(seed).shuffle(order)

    trials: list[dict[str, Any]] = []
    for block_index in range(1, repetitions + 1):
        shift = (block_index - 1) % len(order)
        rotated = order[shift:] + order[:shift]
        for position_index, identifier in enumerate(rotated, start=1):
            config = by_id[identifier]
            config["position_counts"][str(position_index)] += 1
            trials.append(
                {
                    "block_index": block_index,
                    "position_index": position_index,
                    "config_id": identifier,
                    "config_index": config["config_index"],
                    "role": config["role"],
                    "candidate_config": dict(config["candidate_config"]),
                    "trial_id": (
                        f"{campaign_name}_b{block_index:02d}_p{position_index:02d}_"
                        f"{identifier}"
                    ),
                }
            )

    return {
        "schema_version": "optimization-repeated-schedule/v1",
        "campaign_name": campaign_name,
        "cause_id": cause_id,
        "action_id": action_id,
        "strategy": execution_schedule.get("strategy"),
        "seed": seed,
        "repetitions": repetitions,
        "configuration_count": len(configurations),
        "trial_count": len(trials),
        "configurations": configurations,
        "trials": trials,
    }


def _canonical_config(config: Any) -> str:
    if not isinstance(config, dict) or len(config) != 1:
        raise ValueError("candidate configuration must contain one action")
    return json.dumps(config, sort_keys=True, separators=(",", ":"))
