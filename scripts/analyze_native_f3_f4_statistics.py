#!/usr/bin/env python3
"""Compute run-level paired statistics for a processed native F3/F4 session."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
from pathlib import Path
from typing import Any


RUN_PATTERN = re.compile(r"_r(\d+)$")
METRICS = {
    "F3": (
        "complete_rate",
        "dispatch_upper_bound_ns",
        "zero_work_callback_elapsed_ns",
        "planner_path_upper_bound_ns",
    ),
    "F4": (
        "complete_rate",
        "server_processing_elapsed_ns",
        "request_response_elapsed_ns",
        "pre_server_elapsed_ns",
        "post_server_elapsed_ns",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=20000)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def exact_two_sided_sign_p(differences: list[float]) -> float | None:
    nonzero = [value for value in differences if value != 0]
    if not nonzero:
        return None
    positives = sum(value > 0 for value in nonzero)
    tail = min(positives, len(nonzero) - positives)
    cumulative = sum(math.comb(len(nonzero), k) for k in range(tail + 1))
    return min(1.0, 2.0 * cumulative / (2 ** len(nonzero)))


def bootstrap_median_ci(
    differences: list[float], *, samples: int, seed: int
) -> tuple[float, float] | tuple[None, None]:
    if not differences:
        return None, None
    rng = random.Random(seed)
    medians = sorted(
        statistics.median(rng.choices(differences, k=len(differences)))
        for _ in range(samples)
    )
    return medians[int(samples * 0.025)], medians[min(samples - 1, int(samples * 0.975))]


def case_run_index(case_name: str) -> int:
    match = RUN_PATTERN.search(case_name)
    if not match:
        raise ValueError(f"case name has no repetition suffix: {case_name}")
    return int(match.group(1))


def main() -> int:
    args = parse_args()
    session = args.session_dir.resolve()
    processed = args.processed_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    if args.bootstrap_samples < 1000:
        raise SystemExit("bootstrap-samples must be at least 1000")
    output.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for case_output in sorted((processed / "cases").iterdir()):
        if not case_output.is_dir():
            continue
        case_raw = session / "cases" / case_output.name
        oracle = read_json(case_raw / "oracle_manifest.json")
        fault_id = str(oracle.get("fault_id"))
        variant = str(oracle.get("condition_variant"))
        if fault_id not in METRICS or variant not in {"control", "injected"}:
            continue
        report = read_json(case_output / "evidence_report.json")
        events = read_jsonl(case_output / "derived_events.jsonl")
        observed = int(report.get("observed_trace_count", 0))
        complete = int(report.get("complete_trace_count", 0))
        row: dict[str, Any] = {
            "case": case_output.name,
            "fault_id": fault_id,
            "variant": variant,
            "run": case_run_index(case_output.name),
            "complete_rate": complete / observed if observed else None,
        }
        for metric in METRICS[fault_id]:
            if metric == "complete_rate":
                continue
            values = [float(event["attributes"][metric]) for event in events]
            row[metric] = statistics.median(values) if values else None
        rows.append(row)

    paired: dict[str, Any] = {}
    for fault_id, metrics in METRICS.items():
        paired[fault_id] = {}
        for metric_index, metric in enumerate(metrics):
            pairs = []
            for run in range(1, 11):
                matches = {
                    row["variant"]: row
                    for row in rows
                    if row["fault_id"] == fault_id and row["run"] == run
                }
                if set(matches) != {"control", "injected"}:
                    raise ValueError(f"missing pair for {fault_id}/{metric}/run {run}")
                control = matches["control"].get(metric)
                injected = matches["injected"].get(metric)
                if control is None or injected is None:
                    continue
                pairs.append(
                    {
                        "run": run,
                        "control": float(control),
                        "injected": float(injected),
                        "difference": float(injected) - float(control),
                    }
                )
            differences = [row["difference"] for row in pairs]
            ci_low, ci_high = bootstrap_median_ci(
                differences,
                samples=args.bootstrap_samples,
                seed=20260729 + metric_index + (100 if fault_id == "F4" else 0),
            )
            paired[fault_id][metric] = {
                "pair_count": len(pairs),
                "control_run_median": statistics.median(row["control"] for row in pairs),
                "injected_run_median": statistics.median(row["injected"] for row in pairs),
                "paired_difference_median": statistics.median(differences),
                "paired_difference_bootstrap_95_ci": [ci_low, ci_high],
                "positive_differences": sum(value > 0 for value in differences),
                "negative_differences": sum(value < 0 for value in differences),
                "zero_differences": sum(value == 0 for value in differences),
                "exact_two_sided_sign_p": exact_two_sided_sign_p(differences),
                "pairs": pairs,
            }

    result = {
        "schema_version": "native-f3-f4-run-level-statistics/v1",
        "analysis_unit": "run",
        "paired_repetitions": 10,
        "bootstrap_samples": args.bootstrap_samples,
        "source_session": str(session),
        "paired": paired,
    }
    (output / "paired_statistics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "run_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["case", "fault_id", "variant", "run"] + sorted(
            {metric for metrics in METRICS.values() for metric in metrics}
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"status": "completed", "run_rows": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
