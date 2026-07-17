"""Derive development-only W2 service blocking-delay evidence for F4."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from diagnosis.adapters.mock_ack_lifecycle_adapter import _describe, _integer
from diagnosis.schema import NormalizedEvent


EVENTS = (
    "query_sent",
    "service_process_start",
    "service_process_end",
    "response_received",
)
SERVER_EVENTS = {"service_process_start", "service_process_end"}
METRICS = (
    "server_processing_elapsed_ns",
    "request_response_elapsed_ns",
    "pre_server_elapsed_ns",
    "post_server_elapsed_ns",
)
MEASUREMENT_SEMANTICS = "application_service_blocking_elapsed"


def derive_service_blocking_delay_evidence(
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
    records = list(runtime_records)
    variant, injection, reason = _validate_manifests(run_manifest, oracle_manifest)
    report: dict[str, Any] = {
        "schema_version": "service-blocking-evidence/v1",
        "measurement_semantics": MEASUREMENT_SEMANTICS,
        "formal_syscall_attribution": False,
        "ebpf_evidence": False,
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
        if not isinstance(trace_id, str) or not trace_id or record.get("event_name") not in EVENTS:
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
    metric_values: dict[str, list[int]] = {metric: [] for metric in METRICS}
    output: list[tuple[int, str, NormalizedEvent]] = []
    for trace_id, rows in by_trace.items():
        if trace_id in malformed:
            invalid["invalid_extra_json"] += 1
            continue
        counts = Counter(str(row[1].get("event_name", "")) for row in rows)
        if any(counts[name] > 1 for name in EVENTS):
            server_rows = {
                name: [row for row in rows if row[1].get("event_name") == name]
                for name in SERVER_EVENTS
            }
            server_pids = {
                int(row[1].get("pid"))
                for values in server_rows.values()
                for row in values
                if _integer(row[1].get("pid"))
            }
            if not (
                counts["query_sent"] == counts["response_received"] == 1
                and all(len(server_rows[name]) == 2 for name in SERVER_EVENTS)
                and len(server_pids) == 2
            ):
                invalid["duplicate_stage"] += 1
                continue
            chosen_pid = min(server_pids)
            rows = [
                row
                for row in rows
                if row[1].get("event_name") not in SERVER_EVENTS
                or int(row[1].get("pid")) == chosen_pid
            ]
        if any(counts[name] == 0 for name in EVENTS):
            incomplete += 1
            continue
        if any(not _integer(record.get("timestamp_ns")) for _, record, _ in rows):
            invalid["invalid_timestamp"] += 1
            continue
        hosts = {record.get("host_id") for _, record, _ in rows}
        clocks = {record.get("clock_id") for _, record, _ in rows}
        sequences = {record.get("sequence_id") for _, record, _ in rows}
        if len(hosts) != 1 or None in hosts or clocks != {"monotonic"}:
            invalid["clock_or_host_mismatch"] += 1
            continue
        if (
            len(sequences) != 1
            or not _integer(next(iter(sequences)))
            or int(next(iter(sequences))) <= 0
        ):
            invalid["trace_identity_mismatch"] += 1
            continue
        row_by_name = {str(row[1]["event_name"]): row for row in rows}
        stage_rows = [row_by_name[name] for name in EVENTS]
        payload_ids = {row[2].get("payload_id") for row in stage_rows}
        if len(payload_ids) != 1 or None in payload_ids or "" in payload_ids:
            invalid["payload_identity_mismatch"] += 1
            continue
        if any(
            row_by_name[name][2].get("requested_delay_ms")
            != injection["server_delay_ms"]
            for name in SERVER_EVENTS
        ):
            invalid["event_profile_mismatch"] += 1
            continue
        timestamps = [int(row[1]["timestamp_ns"]) for row in stage_rows]
        if timestamps != sorted(timestamps):
            invalid["stage_order_mismatch"] += 1
            continue
        query_ns, start_ns, end_ns, response_ns = timestamps
        intervals = {
            "server_processing_elapsed_ns": end_ns - start_ns,
            "request_response_elapsed_ns": response_ns - query_ns,
            "pre_server_elapsed_ns": start_ns - query_ns,
            "post_server_elapsed_ns": response_ns - end_ns,
        }
        if any(value < 0 for value in intervals.values()):
            invalid["negative_interval"] += 1
            continue
        for metric, value in intervals.items():
            metric_values[metric].append(value)
        terminal = row_by_name["response_received"][1]
        event = NormalizedEvent(
            event_id=f"derived_fusion:service_blocking:{trace_id}",
            source="derived_fusion",
            event_type="service_blocking_elapsed",
            timestamp_ns=response_ns,
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(terminal["sequence_id"]),
            stage="response_received",
            pid=int(terminal["pid"]),
            tid=int(terminal["tid"]),
            host_id=str(terminal["host_id"]),
            attributes={
                **intervals,
                "configured_delay_ms": int(injection["server_delay_ms"]),
                "blocking_primitive": str(injection["blocking_primitive"]),
                "measurement_semantics": MEASUREMENT_SEMANTICS,
                "formal_syscall_attribution": False,
                "ebpf_evidence": False,
            },
            provenance={
                "adapter": "service_blocking_delay_v1",
                "runtime_source_file": runtime_source_file,
                "record_indices": [row[0] for row in stage_rows],
                "run_manifest_source_file": run_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
            },
        )
        output.append((query_ns, trace_id, event))

    complete = len(output)
    report.update(
        {
            "observed_trace_count": len(by_trace),
            "complete_trace_count": complete,
            "incomplete_trace_count": incomplete,
            "invalid_trace_count": sum(invalid.values()),
            "invalid_pair_reason_counts": dict(sorted(invalid.items())),
            "complete_trace_rate": complete / len(by_trace) if by_trace else 0.0,
            "metrics_ns": {
                metric: _describe(values) for metric, values in metric_values.items()
            },
        }
    )
    if not output:
        report["status"] = "invalid"
        report["reason_code"] = "no_valid_service_blocking_intervals"
    elif incomplete or invalid:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_service_lifecycles"
    return [event for _, _, event in sorted(output)], report


def _validate_manifests(
    run: dict[str, Any], oracle: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    variant = str(oracle.get("condition_variant", ""))
    if run.get("schema_version") != "fault-run/v1":
        return variant, {}, "invalid_run_manifest"
    if oracle.get("schema_version") != "fault-oracle/v1":
        return variant, {}, "invalid_f4_oracle"
    if any(
        run.get(field) != oracle.get(field)
        for field in ("condition_id", "session_id", "dataset_role")
    ):
        return variant, {}, "run_oracle_identity_mismatch"
    if run.get("dataset_role") != "development":
        return variant, {}, "development_partition_required"
    injection = oracle.get("injection")
    if (
        run.get("workload") != "w2"
        or oracle.get("fault_id") != "F4"
        or variant not in {"injected", "control"}
        or not isinstance(injection, dict)
    ):
        return variant, {}, "invalid_f4_profile"
    expected = {
        "server_delay_ms": 100 if variant == "injected" else 0,
        "request_rate_hz": 5,
        "blocking_primitive": "clock_nanosleep",
    }
    expected_cause = "blocking_syscall_io" if variant == "injected" else "none"
    if oracle.get("cause_id") != expected_cause:
        return variant, dict(injection), "oracle_variant_mismatch"
    if any(injection.get(key) != value for key, value in expected.items()):
        return variant, dict(injection), "oracle_profile_mismatch"
    return variant, dict(injection), ""


def _single_host(records: Iterable[dict[str, Any]]) -> str:
    hosts = {
        record.get("host_id")
        for record in records
        if record.get("event_name") in EVENTS
        and isinstance(record.get("host_id"), str)
        and record.get("host_id")
    }
    return str(next(iter(hosts))) if len(hosts) == 1 else ""


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
    events, report = derive_service_blocking_delay_evidence(
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
