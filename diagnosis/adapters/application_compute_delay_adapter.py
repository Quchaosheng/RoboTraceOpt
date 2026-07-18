"""Derive development-only RuntimeEvent elapsed intervals for F1."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.schema import NormalizedEvent


EVENTS = (
    "camera_frame_published",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
)
METRICS = (
    "planner_processing_elapsed_ns",
    "camera_to_planner_publish_upper_bound_ns",
)
MEASUREMENT_SEMANTICS = "runtime_event_elapsed_interval"


def derive_application_compute_delay_evidence(
    runtime_records: Iterable[dict[str, Any]],
    run_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    *,
    runtime_source_file: str,
    run_manifest_source_file: str,
    oracle_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if not all(
        (
            runtime_source_file,
            run_manifest_source_file,
            oracle_manifest_source_file,
        )
    ):
        raise ValueError("all source file paths are required")

    variant, injection, reason_code = _validate_manifests(run_manifest, oracle_manifest)
    records = list(runtime_records)
    report: dict[str, Any] = {
        "schema_version": "application-compute-delay-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "formal_cpu_time_measurement": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "status": "invalid" if reason_code else "valid",
        "reason_code": reason_code,
        "profile": {
            "git_commit": run_manifest.get("git_commit", ""),
            "workload": run_manifest.get("workload", ""),
            "host_id": _single_runtime_host(records),
            "input_rate_hz": injection.get("input_rate_hz"),
            "planner_backend": injection.get("planner_backend"),
            "action_manager_enabled": injection.get("action_manager_enabled"),
            "planner_delay_mode": injection.get("planner_delay_mode"),
            "planner_delay_ms": injection.get("planner_delay_ms"),
        },
        "runtime_source_file": runtime_source_file,
        "run_manifest_source_file": run_manifest_source_file,
        "oracle_manifest_source_file": oracle_manifest_source_file,
    }
    if reason_code:
        return [], report

    by_trace: dict[str, dict[str, tuple[int, dict[str, Any]]]] = {}
    for index, record in enumerate(records, start=1):
        trace_id = record.get("trace_id")
        event_name = record.get("event_name")
        if isinstance(trace_id, str) and trace_id and event_name in EVENTS:
            by_trace.setdefault(trace_id, {}).setdefault(event_name, (index, record))

    missing_counts: Counter[str] = Counter()
    invalid_reasons: Counter[str] = Counter()
    metric_values: dict[str, list[int]] = {metric: [] for metric in METRICS}
    valid_rows: list[tuple[int, str, NormalizedEvent]] = []
    for trace_id, trace_events in by_trace.items():
        missing = [
            event_name for event_name in EVENTS if event_name not in trace_events
        ]
        if missing:
            missing_counts.update(missing)
            continue
        event_records = {name: trace_events[name][1] for name in EVENTS}
        host_ids = {record.get("host_id") for record in event_records.values()}
        clock_ids = {record.get("clock_id") for record in event_records.values()}
        if len(host_ids) != 1 or None in host_ids or clock_ids != {"monotonic"}:
            invalid_reasons["clock_or_host_mismatch"] += 1
            continue
        sequence_ids = {record.get("sequence_id") for record in event_records.values()}
        if len(sequence_ids) != 1 or not _integer(next(iter(sequence_ids))):
            invalid_reasons["trace_identity_mismatch"] += 1
            continue
        timestamps = {name: event_records[name].get("timestamp_ns") for name in EVENTS}
        if any(not _integer(value) for value in timestamps.values()):
            invalid_reasons["invalid_timestamp"] += 1
            continue
        values = {
            "planner_processing_elapsed_ns": (
                timestamps["planner_process_end"] - timestamps["planner_process_start"]
            ),
            "camera_to_planner_publish_upper_bound_ns": (
                timestamps["planner_publish"] - timestamps["camera_frame_published"]
            ),
        }
        if any(value < 0 for value in values.values()):
            invalid_reasons["negative_elapsed_interval"] += 1
            continue

        end_record = event_records["planner_process_end"]
        if any(
            not _integer(end_record.get(field)) or int(end_record[field]) <= 0
            for field in ("pid", "tid")
        ):
            invalid_reasons["invalid_runtime_identity"] += 1
            continue
        event = NormalizedEvent(
            event_id=f"derived_fusion:application_compute_delay:{trace_id}",
            source="derived_fusion",
            event_type="application_compute_delay_interval",
            timestamp_ns=int(timestamps["planner_process_end"]),
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(end_record["sequence_id"]),
            stage="planner_process_end",
            pid=int(end_record["pid"]),
            tid=int(end_record["tid"]),
            host_id=str(end_record["host_id"]),
            attributes={
                **values,
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "formal_cpu_time_measurement": False,
                "planner_delay_mode": injection["planner_delay_mode"],
                "planner_delay_ms": int(injection["planner_delay_ms"]),
            },
            provenance={
                "adapter": "application_compute_delay_v1",
                "runtime_source_file": runtime_source_file,
                "record_indices": {name: trace_events[name][0] for name in EVENTS},
                "run_manifest_source_file": run_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
            },
        )
        valid_rows.append((int(timestamps["planner_process_start"]), trace_id, event))
        for metric, value in values.items():
            metric_values[metric].append(value)

    events = [event for _, _, event in sorted(valid_rows)]
    incomplete_count = sum(
        1 for trace in by_trace.values() if any(name not in trace for name in EVENTS)
    )
    report.update(
        {
            "observed_trace_count": len(by_trace),
            "complete_trace_count": len(events),
            "incomplete_trace_count": incomplete_count,
            "missing_event_counts": dict(sorted(missing_counts.items())),
            "invalid_pair_count": sum(invalid_reasons.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid_reasons.items())),
            "metrics_ns": {
                metric: _describe(values) for metric, values in metric_values.items()
            },
        }
    )
    if not events:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_elapsed_traces"
    elif incomplete_count or invalid_reasons:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_runtime_traces"
    return events, report


def _validate_manifests(
    run: dict[str, Any], oracle: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    if run.get("schema_version") != "fault-run/v1":
        return "", {}, "invalid_run_manifest"
    if oracle.get("schema_version") != "fault-oracle/v1":
        return "", {}, "invalid_f1_oracle"
    if any(
        run.get(field) != oracle.get(field)
        for field in ("condition_id", "session_id", "dataset_role")
    ):
        return (
            str(oracle.get("condition_variant", "")),
            {},
            "run_oracle_identity_mismatch",
        )
    if run.get("dataset_role") != "development":
        return (
            str(oracle.get("condition_variant", "")),
            {},
            "development_partition_required",
        )
    if run.get("workload") != "w1" or oracle.get("fault_id") != "F1":
        return str(oracle.get("condition_variant", "")), {}, "invalid_f1_profile"
    variant = oracle.get("condition_variant")
    injection = oracle.get("injection")
    if variant not in {"injected", "control"} or not isinstance(injection, dict):
        return str(variant or ""), {}, "invalid_f1_oracle"
    expected = {
        "planner_delay_mode": "busy_compute",
        "planner_delay_ms": 100 if variant == "injected" else 0,
        "input_rate_hz": 4,
        "planner_backend": "mock",
        "action_manager_enabled": True,
    }
    expected_cause = "application_compute_delay" if variant == "injected" else "none"
    if oracle.get("cause_id") != expected_cause:
        return str(variant), dict(injection), "oracle_variant_mismatch"
    if any(injection.get(key) != value for key, value in expected.items()):
        return str(variant), dict(injection), "oracle_profile_mismatch"
    return str(variant), dict(injection), ""


def _single_runtime_host(records: Iterable[dict[str, Any]]) -> str:
    hosts = {
        record.get("host_id")
        for record in records
        if record.get("event_name") in EVENTS
        and isinstance(record.get("host_id"), str)
        and record.get("host_id")
    }
    return str(next(iter(hosts))) if len(hosts) == 1 else ""


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _describe(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": _quantile(ordered, 0.5),
        "p90": _quantile(ordered, 0.9),
        "p95": _quantile(ordered, 0.95),
        "p99": _quantile(ordered, 0.99),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def _quantile(values: list[int], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-events", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--oracle-manifest", type=Path, required=True)
    parser.add_argument("--output-events", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    oracle = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
    events, report = derive_application_compute_delay_evidence(
        _read_jsonl(args.runtime_events),
        run,
        oracle,
        runtime_source_file=str(args.runtime_events),
        run_manifest_source_file=str(args.run_manifest),
        oracle_manifest_source_file=str(args.oracle_manifest),
    )
    report["input_sha256"] = {
        "runtime_events": _sha256(args.runtime_events),
        "run_manifest": _sha256(args.run_manifest),
        "oracle_manifest": _sha256(args.oracle_manifest),
    }
    args.output_events.parent.mkdir(parents=True, exist_ok=True)
    with args.output_events.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
