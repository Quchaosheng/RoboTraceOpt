#!/usr/bin/env python3
"""Project and aggregate a completed native F3/F4 session without mutating it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from diagnosis.adapters.scheduling_pressure_adapter import (  # noqa: E402
    derive_scheduling_pressure_evidence,
)
from diagnosis.adapters.service_blocking_delay_adapter import (  # noqa: E402
    derive_service_blocking_delay_evidence,
)


METRICS = {
    "F3": (
        "dispatch_upper_bound_ns",
        "zero_work_callback_elapsed_ns",
        "planner_path_upper_bound_ns",
    ),
    "F4": (
        "server_processing_elapsed_ns",
        "request_response_elapsed_ns",
        "pre_server_elapsed_ns",
        "post_server_elapsed_ns",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median": None, "p90": None, "p95": None, "p99": None, "mean": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median": quantile(ordered, 0.5),
        "p90": quantile(ordered, 0.9),
        "p95": quantile(ordered, 0.95),
        "p99": quantile(ordered, 0.99),
        "mean": statistics.fmean(ordered),
    }


def quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def write_events(path: Path, events: list[Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")


def main() -> int:
    args = parse_args()
    session = args.session_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    session_summary = read_json(session / "summary.json")
    integrity = read_json(session / "integrity.json")
    qualification = read_json(session / "qualification.json")
    if session_summary.get("status") != "completed" or integrity.get("status") != "complete":
        raise SystemExit("session is not completed with complete integrity")

    metric_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    totals: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"runs": 0, "observed": 0, "complete": 0, "incomplete": 0, "ebpf_events": 0}
    )
    case_rows = []
    cases_output = output / "cases"
    cases_output.mkdir()

    for case_dir in sorted((session / "cases").iterdir()):
        if not case_dir.is_dir():
            continue
        oracle = read_json(case_dir / "oracle_manifest.json")
        fault_id = str(oracle.get("fault_id"))
        variant = str(oracle.get("condition_variant"))
        if fault_id not in METRICS or variant not in {"control", "injected"}:
            continue
        runtime = read_jsonl(case_dir / "runtime_events.jsonl")
        case_output = cases_output / case_dir.name
        case_output.mkdir()
        if fault_id == "F3":
            events, report = derive_scheduling_pressure_evidence(
                runtime,
                read_json(case_dir / "process_manifest.json"),
                read_json(case_dir / "scheduler_manifest.json"),
                oracle,
                runtime_source_file=str(case_dir / "runtime_events.jsonl"),
                process_manifest_source_file=str(case_dir / "process_manifest.json"),
                scheduler_manifest_source_file=str(case_dir / "scheduler_manifest.json"),
                oracle_manifest_source_file=str(case_dir / "oracle_manifest.json"),
            )
        else:
            events, report = derive_service_blocking_delay_evidence(
                runtime,
                read_json(case_dir / "run_manifest.json"),
                oracle,
                runtime_source_file=str(case_dir / "runtime_events.jsonl"),
                run_manifest_source_file=str(case_dir / "run_manifest.json"),
                oracle_manifest_source_file=str(case_dir / "oracle_manifest.json"),
            )
        write_events(case_output / "derived_events.jsonl", events)
        (case_output / "evidence_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        observed = int(report.get("observed_trace_count", 0))
        complete = int(report.get("complete_trace_count", 0))
        incomplete = int(report.get("incomplete_trace_count", observed - complete))
        ebpf = read_json(case_dir / "ebpf_capture_summary.json")
        key = (fault_id, variant)
        totals[key]["runs"] += 1
        totals[key]["observed"] += observed
        totals[key]["complete"] += complete
        totals[key]["incomplete"] += incomplete
        totals[key]["ebpf_events"] += int(ebpf.get("event_count", 0))
        for event in events:
            for metric in METRICS[fault_id]:
                metric_values[(fault_id, variant, metric)].append(float(event.attributes[metric]))
        case_rows.append(
            {
                "case": case_dir.name,
                "fault_id": fault_id,
                "variant": variant,
                "status": report.get("status"),
                "observed": observed,
                "complete": complete,
                "incomplete": incomplete,
                "ebpf_events": int(ebpf.get("event_count", 0)),
            }
        )

    conditions = []
    for fault_id in ("F3", "F4"):
        for variant in ("control", "injected"):
            total = totals[(fault_id, variant)]
            conditions.append(
                {
                    "fault_id": fault_id,
                    "variant": variant,
                    **total,
                    "complete_rate": total["complete"] / total["observed"] if total["observed"] else None,
                    "metrics_ns": {
                        metric: describe(metric_values[(fault_id, variant, metric)])
                        for metric in METRICS[fault_id]
                    },
                }
            )

    comparisons = {}
    for fault_id in ("F3", "F4"):
        metric_rows = {}
        for metric in METRICS[fault_id]:
            control = describe(metric_values[(fault_id, "control", metric)])
            injected = describe(metric_values[(fault_id, "injected", metric)])
            metric_rows[metric] = {}
            for quantile_name in ("median", "p90", "p95", "p99"):
                injected_value = injected[quantile_name]
                control_value = control[quantile_name]
                left = float(injected_value) if injected_value is not None else None
                right = float(control_value) if control_value is not None else None
                metric_rows[metric][quantile_name] = {
                    "injected": left,
                    "control": right,
                    "absolute_delta": (
                        left - right if left is not None and right is not None else None
                    ),
                    "ratio": (
                        left / right
                        if left is not None and right is not None and right > 0
                        else None
                    ),
                }
        comparisons[fault_id] = {"metrics_ns": metric_rows}

    summary = {
        "schema_version": "native-f3-f4-analysis/v1",
        "source_session": str(session),
        "source_session_integrity": integrity.get("status"),
        "dataset_role": qualification.get("dataset_role"),
        "development_only": qualification.get("development_only"),
        "formal_experiment_allowed": qualification.get("formal_experiment_allowed"),
        "platform_label": qualification.get("platform_label"),
        "host": qualification.get("host"),
        "git_commit": qualification.get("git_commit"),
        "git_status": qualification.get("git_status"),
        "source_archive": (
            {"path": str(args.source_archive.resolve()), "sha256": sha256(args.source_archive)}
            if args.source_archive
            else None
        ),
        "case_count": len(case_rows),
        "conditions": conditions,
        "comparisons": comparisons,
        "case_rows": case_rows,
    }
    (output / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(output / "metrics.csv", conditions)
    (output / "analysis_summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"status": "completed", "case_count": len(case_rows)}))
    return 0


def write_csv(path: Path, conditions: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("fault_id", "variant", "runs", "observed", "complete", "complete_rate", "ebpf_events", "metric", "median_ns", "p95_ns", "p99_ns"),
        )
        writer.writeheader()
        for condition in conditions:
            for metric, values in condition["metrics_ns"].items():
                writer.writerow(
                    {
                        "fault_id": condition["fault_id"],
                        "variant": condition["variant"],
                        "runs": condition["runs"],
                        "observed": condition["observed"],
                        "complete": condition["complete"],
                        "complete_rate": condition["complete_rate"],
                        "ebpf_events": condition["ebpf_events"],
                        "metric": metric,
                        "median_ns": values["median"],
                        "p95_ns": values["p95"],
                        "p99_ns": values["p99"],
                    }
                )


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Native x86 F3/F4 Analysis",
        "",
        f"- Platform: `{summary['platform_label']}`",
        f"- Dataset role: `{summary['dataset_role']}`",
        f"- Development only: `{str(summary['development_only']).lower()}`",
        f"- Formal inference allowed: `{str(summary['formal_experiment_allowed']).lower()}`",
        f"- Cases: {summary['case_count']}",
        "",
        "| Fault | Variant | Runs | Complete/Observed | Rate | eBPF events |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["conditions"]:
        lines.append(
            f"| {row['fault_id']} | {row['variant']} | {row['runs']} | "
            f"{row['complete']}/{row['observed']} | {row['complete_rate']:.4f} | {row['ebpf_events']} |"
        )
    lines.extend(["", "## Median comparisons", "", "| Fault | Metric | Control ms | Injected ms | Ratio |", "|---|---|---:|---:|---:|"])
    for fault_id, comparison in summary["comparisons"].items():
        for metric, quantiles in comparison["metrics_ns"].items():
            median = quantiles["median"]
            control_ms = (
                f"{median['control'] / 1e6:.4f}"
                if median["control"] is not None
                else "n/a"
            )
            injected_ms = (
                f"{median['injected'] / 1e6:.4f}"
                if median["injected"] is not None
                else "n/a"
            )
            ratio = f"{median['ratio']:.3f}" if median["ratio"] is not None else "n/a"
            lines.append(
                f"| {fault_id} | `{metric}` | {control_ms} | "
                f"{injected_ms} | {ratio} |"
            )
    if summary["dataset_role"] == "test" and summary["formal_experiment_allowed"]:
        evidence_note = (
            "This session is retained as the formal native Ubuntu 24.04/Jazzy test "
            "partition. F4 supports formal application-level blocking-delay inference; "
            "F3 remains a scheduling-pressure proxy and does not establish syscall- or "
            "scheduler-level causal attribution."
        )
    else:
        evidence_note = (
            "This session is retained as development evidence and is not admitted to "
            "the formal test partition."
        )
    lines.extend(
        [
            "",
            evidence_note,
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
