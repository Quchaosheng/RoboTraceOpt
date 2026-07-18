"""Build reproducible guided and baseline optimization trial plans."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from optimizer.action_registry.registry import available_actions, actions_for_cause
from optimizer.search.diagnosis_guided_sampler import sample_candidates


STRATEGIES = {"guided", "random", "unguided_random"}


def build_trial_plan(
    cause_id: str, *, strategy: str, budget: int, seed: int
) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unsupported strategy: {strategy}")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("budget must be positive")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    relevant = actions_for_cause(cause_id)
    relevant_ids = {str(action["action_id"]) for action in relevant}
    catalog = available_actions()
    rng = random.Random(seed)

    if strategy == "guided":
        configs = sample_candidates(cause_id, limit=budget, seed=seed)
        configs = [configs[index % len(configs)] for index in range(budget)]
        selected = [(next(iter(config)), config) for config in configs]
    elif strategy == "random":
        action = relevant[0]
        selected = [
            (
                str(action["action_id"]),
                {str(action["action_id"]): _random_value(action, rng)},
            )
            for _ in range(budget)
        ]
    else:
        actions = list(catalog)
        rng.shuffle(actions)
        selected_actions = [actions[index % len(actions)] for index in range(budget)]
        selected = [
            (
                str(action["action_id"]),
                {str(action["action_id"]): _random_value(action, rng)},
            )
            for action in selected_actions
        ]

    return {
        "schema_version": "optimization-trial-plan/v1",
        "cause_id": cause_id,
        "strategy": strategy,
        "seed": seed,
        "budget": budget,
        "diagnosis_constrained": strategy != "unguided_random",
        "global_action_count": len(catalog),
        "constrained_action_count": len(relevant),
        "trials": [
            {
                "trial_index": index,
                "action_id": action_id,
                "candidate_config": config,
                "applicable_to_diagnosis": action_id in relevant_ids,
            }
            for index, (action_id, config) in enumerate(selected, start=1)
        ],
    }


def _random_value(action: dict[str, Any], rng: random.Random) -> Any:
    if action["kind"] == "boolean":
        return bool(rng.getrandbits(1))
    bounds = action["bounds"]
    return rng.randint(int(bounds["min"]), int(bounds["max"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cause-id", required=True)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = build_trial_plan(
        args.cause_id,
        strategy=args.strategy,
        budget=args.budget,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
