"""Summarize real optimization trial curves and target attainment."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def summarize_trial_records(
    records: Iterable[dict[str, Any]], *, target_objective_ns: float
) -> dict[str, Any]:
    rows = list(records)
    if not rows:
        raise ValueError("trial records are required")
    if (
        isinstance(target_objective_ns, bool)
        or not isinstance(target_objective_ns, (int, float))
        or target_objective_ns <= 0
    ):
        raise ValueError("target objective must be positive")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy = row.get("strategy")
        if not isinstance(strategy, str) or not strategy:
            raise ValueError("trial strategy is required")
        grouped[strategy].append(row)

    strategies: dict[str, Any] = {}
    for strategy, trials in sorted(grouped.items()):
        ordered = sorted(trials, key=lambda row: int(row["trial_index"]))
        valid = [row for row in ordered if row.get("valid") is True]
        for row in valid:
            value = row.get("objective_value_ns")
            rate = row.get("complete_trace_rate")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
                or isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not 0 <= rate <= 1
            ):
                raise ValueError("invalid trial measurement")
        best = min(valid, key=lambda row: float(row["objective_value_ns"])) if valid else None
        target = next(
            (
                row
                for row in ordered
                if row.get("valid") is True
                and float(row["objective_value_ns"]) <= target_objective_ns
            ),
            None,
        )
        strategies[strategy] = {
            "trial_count": len(ordered),
            "valid_trial_count": len(valid),
            "invalid_trial_count": len(ordered) - len(valid),
            "best_objective_ns": float(best["objective_value_ns"]) if best else None,
            "best_candidate_config": best.get("candidate_config") if best else None,
            "trials_to_target": int(target["trial_index"]) if target else None,
            "minimum_complete_trace_rate": min(
                (float(row["complete_trace_rate"]) for row in valid), default=None
            ),
            "curve": ordered,
        }
    return {
        "schema_version": "optimization-search-summary/v1",
        "target_objective_ns": float(target_objective_ns),
        "formal_optimization_allowed": False,
        "strategies": strategies,
    }


def load_trial_records(root: Path, *, metric: str, quantile: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    by_strategy: dict[str, list[Path]] = defaultdict(list)
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest = json.loads((directory / "trial_manifest.json").read_text(encoding="utf-8"))
        by_strategy[str(manifest["strategy"])].append(directory)
    for strategy, directories in sorted(by_strategy.items()):
        for index, directory in enumerate(sorted(directories), start=1):
            manifest = json.loads((directory / "trial_manifest.json").read_text(encoding="utf-8"))
            report = json.loads((directory / "trial_report.json").read_text(encoding="utf-8"))
            metrics = report.get("metrics_ns", {})
            values = metrics.get(metric) if isinstance(metrics, dict) else None
            value = values.get(quantile) if isinstance(values, dict) else None
            records.append(
                {
                    "strategy": strategy,
                    "trial_index": index,
                    "trial_id": manifest["trial_id"],
                    "candidate_config": manifest["candidate_config"],
                    "objective_value_ns": value,
                    "complete_trace_rate": report.get("complete_trace_rate", 0.0),
                    "valid": isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and report.get("complete_trace_count", 0) > 0,
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-root", type=Path, required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--quantile", default="p95")
    parser.add_argument("--target-objective-ns", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize_trial_records(
        load_trial_records(args.trial_root, metric=args.metric, quantile=args.quantile),
        target_objective_ns=args.target_objective_ns,
    )
    summary["trial_root"] = str(args.trial_root)
    summary["metric"] = args.metric
    summary["quantile"] = args.quantile
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
