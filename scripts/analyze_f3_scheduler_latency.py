#!/usr/bin/env python3
"""Aggregate identity-bound F3 runnable-to-running scheduler latency."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterable


RUN_PATTERN = re.compile(r"_r(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def quantile(values: list[int], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def describe(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median": None, "p90": None, "p95": None, "p99": None, "mean": None}
    return {
        "count": len(values),
        "median": quantile(values, 0.5),
        "p90": quantile(values, 0.9),
        "p95": quantile(values, 0.95),
        "p99": quantile(values, 0.99),
        "mean": statistics.fmean(values),
    }


def planner_main_tid(process_manifest: dict[str, Any]) -> int:
    matches = [
        process
        for process in process_manifest.get("processes", [])
        if isinstance(process, dict) and process.get("node") == "vlm_planner_node"
    ]
    if len(matches) != 1:
        raise ValueError("process manifest must identify exactly one vlm_planner_node")
    process = matches[0]
    if process_manifest.get("ebpf_identity_status") != "comparable":
        raise ValueError("planner eBPF identity is not comparable")
    pid = process.get("kernel_pid")
    tids = process.get("tids", [])
    if not isinstance(pid, int) or pid <= 0 or pid not in tids:
        raise ValueError("planner main TID is not frozen in the process manifest")
    return pid


def pair_runnable_latencies(
    records: Iterable[dict[str, Any]], planner_tid: int
) -> tuple[list[int], dict[str, int]]:
    pending_wakeup: int | None = None
    wakeups = 0
    duplicate_wakeups = 0
    switches = 0
    invalid_intervals = 0
    values: list[int] = []
    for record in sorted(records, key=lambda row: int(row.get("timestamp_ns", -1))):
        timestamp = record.get("timestamp_ns")
        if not isinstance(timestamp, int) or timestamp < 0:
            continue
        source = record.get("event_source")
        if source == "sched_wakeup" and record.get("tid") == planner_tid:
            wakeups += 1
            if pending_wakeup is None:
                pending_wakeup = timestamp
            else:
                duplicate_wakeups += 1
        elif source == "sched_switch" and record.get("next_tid") == planner_tid:
            switches += 1
            if pending_wakeup is not None:
                latency = timestamp - pending_wakeup
                if latency >= 0:
                    values.append(latency)
                else:
                    invalid_intervals += 1
                pending_wakeup = None
    return values, {
        "wakeups": wakeups,
        "switches_to_planner": switches,
        "matched_wakeup_switch": len(values),
        "duplicate_wakeups_while_pending": duplicate_wakeups,
        "unmatched_final_wakeup": int(pending_wakeup is not None),
        "invalid_intervals": invalid_intervals,
    }


def exact_two_sided_sign_p(differences: list[float]) -> float | None:
    nonzero = [value for value in differences if value != 0]
    if not nonzero:
        return None
    positives = sum(value > 0 for value in nonzero)
    tail = min(positives, len(nonzero) - positives)
    cumulative = sum(math.comb(len(nonzero), k) for k in range(tail + 1))
    return min(1.0, 2.0 * cumulative / (2 ** len(nonzero)))


def main() -> int:
    args = parse_args()
    session = args.session_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    summary = read_json(session / "summary.json")
    qualification = read_json(session / "qualification.json")
    integrity = read_json(session / "integrity.json")
    if (
        summary.get("status") != "completed"
        or summary.get("dataset_role") != "test"
        or not summary.get("formal_experiment_allowed")
        or integrity.get("status") != "complete"
        or qualification.get("git_status")
    ):
        raise SystemExit("session is not an admissible clean formal test partition")

    rows: list[dict[str, Any]] = []
    pooled: dict[str, list[int]] = {"control": [], "injected": []}
    for case_dir in sorted((session / "cases").iterdir()):
        if not case_dir.is_dir():
            continue
        oracle = read_json(case_dir / "oracle_manifest.json")
        if oracle.get("fault_id") != "F3":
            continue
        variant = str(oracle.get("condition_variant", ""))
        if variant not in pooled:
            raise ValueError(f"invalid F3 variant: {variant}")
        process = read_json(case_dir / "process_manifest.json")
        scheduler = read_json(case_dir / "scheduler_manifest.json")
        capture = read_json(case_dir / "ebpf_capture_summary.json")
        tid = planner_main_tid(process)
        planner = scheduler.get("ros_processes", {}).get("vlm_planner_node", {})
        if planner.get("pid") != tid or scheduler.get("ebpf_identity_status") != "comparable":
            raise ValueError(f"scheduler/process identity mismatch: {case_dir.name}")
        if capture.get("malformed_line_count") != 0 or capture.get("bpftrace_returncode") != 0:
            raise ValueError(f"invalid eBPF capture: {case_dir.name}")
        records = read_jsonl(case_dir / "ebpf_events.jsonl")
        values, counts = pair_runnable_latencies(records, tid)
        pooled[variant].extend(values)
        rows.append(
            {
                "case": case_dir.name,
                "variant": variant,
                "run": int(RUN_PATTERN.search(case_dir.name).group(1)),
                "planner_tid": tid,
                "target_cpu": scheduler.get("target_cpu"),
                "capture_duration_s": capture.get("duration_s"),
                **counts,
                "match_rate": len(values) / counts["wakeups"] if counts["wakeups"] else None,
                "latency_ns": describe(values),
            }
        )

    condition_rows: dict[str, Any] = {}
    for variant, values in pooled.items():
        condition_rows[variant] = {
            "runs": sum(row["variant"] == variant for row in rows),
            "latency_ns": describe(values),
            "wakeups": sum(row["wakeups"] for row in rows if row["variant"] == variant),
            "matched_wakeup_switch": sum(
                row["matched_wakeup_switch"] for row in rows if row["variant"] == variant
            ),
        }
    control_median = condition_rows["control"]["latency_ns"]["median"]
    injected_median = condition_rows["injected"]["latency_ns"]["median"]
    pooled_comparison = {
        "median_absolute_delta_ns": (
            injected_median - control_median
            if injected_median is not None and control_median is not None
            else None
        ),
        "median_ratio": (
            injected_median / control_median
            if injected_median is not None and control_median is not None and control_median > 0
            else None
        ),
    }
    run_pairs = []
    for run in range(1, 11):
        matches = {row["variant"]: row for row in rows if row["run"] == run}
        if set(matches) != {"control", "injected"}:
            raise ValueError(f"missing scheduler pair for run {run}")
        control = float(matches["control"]["latency_ns"]["median"])
        injected = float(matches["injected"]["latency_ns"]["median"])
        run_pairs.append(
            {
                "run": run,
                "control_median_ns": control,
                "injected_median_ns": injected,
                "difference_ns": injected - control,
            }
        )
    differences = [row["difference_ns"] for row in run_pairs]
    run_level_comparison = {
        "analysis_unit": "run",
        "pair_count": len(run_pairs),
        "paired_difference_median_ns": statistics.median(differences),
        "positive_differences": sum(value > 0 for value in differences),
        "negative_differences": sum(value < 0 for value in differences),
        "zero_differences": sum(value == 0 for value in differences),
        "exact_two_sided_sign_p": exact_two_sided_sign_p(differences),
        "pairs": run_pairs,
    }
    result = {
        "schema_version": "f3-identity-bound-scheduler-analysis/v1",
        "source_session": str(session),
        "dataset_role": "test",
        "formal_experiment_allowed": True,
        "git_commit": qualification.get("git_commit"),
        "measurement": "planner_main_thread_sched_wakeup_to_sched_switch",
        "clock_id": "monotonic",
        "identity_join": "process_manifest.kernel_pid == eBPF tid/next_tid",
        "trace_level_attribution": False,
        "condition_rows": condition_rows,
        "pooled_event_comparison": pooled_comparison,
        "run_level_paired_comparison": run_level_comparison,
        "runs": rows,
    }
    (output / "scheduler_analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "scheduler_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case",
                "variant",
                "planner_tid",
                "target_cpu",
                "capture_duration_s",
                "wakeups",
                "matched_wakeup_switch",
                "match_rate",
                "median_ns",
                "p95_ns",
                "p99_ns",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["case"],
                    row["variant"],
                    row["planner_tid"],
                    row["target_cpu"],
                    row["capture_duration_s"],
                    row["wakeups"],
                    row["matched_wakeup_switch"],
                    row["match_rate"],
                    row["latency_ns"]["median"],
                    row["latency_ns"]["p95"],
                    row["latency_ns"]["p99"],
                ]
            )
    print(
        json.dumps(
            {
                "status": "completed",
                "runs": len(rows),
                "run_level_paired_comparison": run_level_comparison,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
