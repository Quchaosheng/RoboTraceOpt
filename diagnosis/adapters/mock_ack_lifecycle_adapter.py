"""Derive application-level mock ACK lifecycle evidence for F6."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.schema import NormalizedEvent


EVENTS = {
    "can_ack_wait_start",
    "can_ack_timeout",
    "can_retry_scheduled",
    "can_ack_received",
    "can_retry_exhausted",
}
TERMINALS = {"can_ack_received", "can_retry_exhausted"}
MEASUREMENT_SEMANTICS = "application_mock_ack_lifecycle"


def derive_mock_ack_lifecycle_evidence(
    runtime_records: Iterable[dict[str, Any]],
    run_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    *,
    runtime_source_file: str,
    run_manifest_source_file: str,
    oracle_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    if not all(
        (runtime_source_file, run_manifest_source_file, oracle_manifest_source_file)
    ):
        raise ValueError("all source file paths are required")
    variant, injection, reason = _validate_manifests(run_manifest, oracle_manifest)
    records = list(runtime_records)
    report: dict[str, Any] = {
        "schema_version": "mock-ack-lifecycle-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "physical_can_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "status": "invalid" if reason else "valid",
        "reason_code": reason,
        "profile": {
            "git_commit": run_manifest.get("git_commit", ""),
            "workload": run_manifest.get("workload", ""),
            "host_id": _single_host(records),
            **injection,
        },
        "runtime_source_file": runtime_source_file,
        "run_manifest_source_file": run_manifest_source_file,
        "oracle_manifest_source_file": oracle_manifest_source_file,
    }
    if reason:
        return [], report

    by_trace: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    malformed: set[str] = set()
    for index, record in enumerate(records, start=1):
        trace_id = record.get("trace_id")
        if (
            not isinstance(trace_id, str)
            or not trace_id
            or record.get("event_name") not in EVENTS
        ):
            continue
        try:
            extra = json.loads(record.get("extra_json", ""))
        except (json.JSONDecodeError, TypeError):
            malformed.add(trace_id)
            continue
        if not isinstance(extra, dict):
            malformed.add(trace_id)
            continue
        by_trace.setdefault(trace_id, []).append((index, record, extra))

    invalid: Counter[str] = Counter()
    incomplete = 0
    terminal_counts = Counter()
    distributions: dict[str, list[int]] = {
        "attempt_count": [],
        "timeout_count": [],
        "retry_scheduled_count": [],
    }
    latencies = {"ack_received": [], "retry_exhausted": []}
    output: list[tuple[int, str, NormalizedEvent]] = []
    for trace_id, rows in by_trace.items():
        if trace_id in malformed:
            invalid["invalid_extra_json"] += 1
            continue
        if any(not _event_profile_matches(extra, injection) for _, _, extra in rows):
            invalid["event_profile_mismatch"] += 1
            continue
        if any(not _integer(record.get("timestamp_ns")) for _, record, _ in rows):
            invalid["invalid_timestamp"] += 1
            continue
        ordered = sorted(rows, key=lambda row: (row[1]["timestamp_ns"], row[0]))
        host_ids = {record.get("host_id") for _, record, _ in ordered}
        clock_ids = {record.get("clock_id") for _, record, _ in ordered}
        if len(host_ids) != 1 or None in host_ids or clock_ids != {"monotonic"}:
            invalid["clock_or_host_mismatch"] += 1
            continue
        sequence_ids = {record.get("sequence_id") for _, record, _ in ordered}
        if len(sequence_ids) != 1 or not _integer(next(iter(sequence_ids))):
            invalid["trace_identity_mismatch"] += 1
            continue
        terminals = [row for row in ordered if row[1]["event_name"] in TERMINALS]
        if not terminals:
            incomplete += 1
            continue
        if len(terminals) != 1:
            invalid["conflicting_terminal"] += 1
            continue
        terminal = terminals[0]
        waits = [row for row in ordered if row[1]["event_name"] == "can_ack_wait_start"]
        if waits and int(terminal[1]["timestamp_ns"]) < int(
            waits[0][1]["timestamp_ns"]
        ):
            invalid["negative_terminal_interval"] += 1
            continue
        terminal_position = ordered.index(terminal)
        if terminal_position != len(ordered) - 1:
            invalid["event_after_terminal"] += 1
            continue
        timeouts = [row for row in ordered if row[1]["event_name"] == "can_ack_timeout"]
        retries = [
            row for row in ordered if row[1]["event_name"] == "can_retry_scheduled"
        ]
        if not waits:
            incomplete += 1
            continue
        terminal_name = terminal[1]["event_name"]
        valid_sequence = (
            _valid_exhausted(
                waits, timeouts, retries, terminal, int(injection["max_retries"])
            )
            if terminal_name == "can_retry_exhausted"
            else _valid_success(waits, timeouts, retries, terminal)
        )
        if not valid_sequence:
            invalid["retry_sequence_mismatch"] += 1
            continue
        latency = int(terminal[1]["timestamp_ns"]) - int(waits[0][1]["timestamp_ns"])
        if latency < 0:
            invalid["negative_terminal_interval"] += 1
            continue
        state = (
            "ack_received" if terminal_name == "can_ack_received" else "retry_exhausted"
        )
        counts = {
            "attempt_count": len(waits),
            "timeout_count": len(timeouts),
            "retry_scheduled_count": len(retries),
        }
        terminal_counts[state] += 1
        latencies[state].append(latency)
        for name, value in counts.items():
            distributions[name].append(value)
        record = terminal[1]
        event = NormalizedEvent(
            event_id=f"derived_fusion:mock_ack_lifecycle:{trace_id}",
            source="derived_fusion",
            event_type="mock_ack_lifecycle_terminal",
            timestamp_ns=int(record["timestamp_ns"]),
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(record["sequence_id"]),
            stage=str(record["event_name"]),
            pid=int(record["pid"]),
            tid=int(record["tid"]),
            host_id=str(record["host_id"]),
            attributes={
                "terminal_state": state,
                "terminal_latency_ns": latency,
                **counts,
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "physical_can_evidence": False,
            },
            provenance={
                "adapter": "mock_ack_lifecycle_v1",
                "runtime_source_file": runtime_source_file,
                "record_indices": [row[0] for row in ordered],
                "run_manifest_source_file": run_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
            },
        )
        output.append((int(waits[0][1]["timestamp_ns"]), trace_id, event))

    valid_count = len(output)
    report.update(
        {
            "observed_trace_count": len(by_trace),
            "valid_terminal_count": valid_count,
            "incomplete_trace_count": incomplete,
            "invalid_trace_count": sum(invalid.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid.items())),
            "ack_received_count": terminal_counts["ack_received"],
            "retry_exhausted_count": terminal_counts["retry_exhausted"],
            "terminal_coverage": valid_count / len(by_trace) if by_trace else 0.0,
            "ack_success_rate": terminal_counts["ack_received"] / valid_count
            if valid_count
            else 0.0,
            "retry_exhausted_rate": terminal_counts["retry_exhausted"] / valid_count
            if valid_count
            else 0.0,
            "count_distributions": {
                name: _describe(values) for name, values in distributions.items()
            },
            "terminal_latency_ns": {
                state: _describe(values) for state, values in latencies.items()
            },
        }
    )
    if not output:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_ack_terminals"
    elif incomplete or invalid:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_ack_lifecycles"
    return [event for _, _, event in sorted(output)], report


def _validate_manifests(
    run: dict[str, Any], oracle: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    if run.get("schema_version") != "fault-run/v1":
        return "", {}, "invalid_run_manifest"
    if oracle.get("schema_version") != "fault-oracle/v1":
        return "", {}, "invalid_f6_oracle"
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
    variant = oracle.get("condition_variant")
    injection = oracle.get("injection")
    if (
        run.get("workload") != "w1"
        or oracle.get("fault_id") != "F6"
        or variant not in {"injected", "control"}
        or not isinstance(injection, dict)
    ):
        return str(variant or ""), {}, "invalid_f6_profile"
    expected = {
        "mock_ack_policy": "drop" if variant == "injected" else "success",
        "ack_timeout_ms": 20,
        "max_retries": 2,
        "ack_mode": "mock",
        "mock_mode": True,
        "input_rate_hz": 4,
        "planner_backend": "mock",
        "action_manager_enabled": True,
    }
    expected_cause = "can_ack_failure" if variant == "injected" else "none"
    if oracle.get("cause_id") != expected_cause:
        return str(variant), dict(injection), "oracle_variant_mismatch"
    if any(injection.get(key) != value for key, value in expected.items()):
        return str(variant), dict(injection), "oracle_profile_mismatch"
    return str(variant), dict(injection), ""


def _event_profile_matches(extra: dict[str, Any], injection: dict[str, Any]) -> bool:
    return all(
        extra.get(key) == injection[key]
        for key in (
            "ack_mode",
            "mock_mode",
            "mock_ack_policy",
            "ack_timeout_ms",
            "max_retries",
        )
    ) and _integer(extra.get("retry_count"))


def _retry_counts(rows: list[tuple[int, dict[str, Any], dict[str, Any]]]) -> list[int]:
    return [int(row[2]["retry_count"]) for row in rows]


def _valid_exhausted(waits, timeouts, retries, terminal, max_retries: int) -> bool:
    return (
        _retry_counts(waits) == list(range(max_retries + 1))
        and _retry_counts(timeouts) == list(range(max_retries + 1))
        and _retry_counts(retries) == list(range(1, max_retries + 1))
        and int(terminal[2]["retry_count"]) == max_retries
    )


def _valid_success(waits, timeouts, retries, terminal) -> bool:
    return (
        len(waits) == 1
        and _retry_counts(waits) == [0]
        and not timeouts
        and not retries
        and int(terminal[2]["retry_count"]) == 0
    )


def _single_host(records: Iterable[dict[str, Any]]) -> str:
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
    events, report = derive_mock_ack_lifecycle_evidence(
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
