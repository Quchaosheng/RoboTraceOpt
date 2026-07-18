"""Derive three-source SocketCAN/vcan ACK lifecycle evidence for F6."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from diagnosis.adapters.mock_ack_lifecycle_adapter import (
    _describe,
    _integer,
    _valid_exhausted,
    _valid_success,
)
from diagnosis.schema import NormalizedEvent
from experiments.physical_can.interfaces import validate_physical_can_pair


EVENTS = {
    "can_frame_sent",
    "can_ack_wait_start",
    "can_ack_timeout",
    "can_retry_scheduled",
    "can_ack_received",
    "can_retry_exhausted",
}
TERMINALS = {"can_ack_received", "can_retry_exhausted"}
VCAN_MEASUREMENT_SEMANTICS = "application_socketcan_vcan_ack_lifecycle"
PHYSICAL_MEASUREMENT_SEMANTICS = "application_socketcan_physical_ack_lifecycle"
ORDER_TOLERANCE_NS = 10_000_000
CANDUMP_PATTERN = re.compile(
    r"^\((?P<timestamp>\d+\.\d+)\)\s+(?P<interface>[A-Za-z0-9_.:-]+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]{1,8})#(?P<payload>[0-9A-Fa-f]{0,16})$"
)


def parse_candump_line(line: str, record_index: int) -> dict[str, Any]:
    match = CANDUMP_PATTERN.fullmatch(line.strip())
    if match is None:
        raise ValueError(f"invalid candump record at line {record_index}")
    try:
        realtime_ns = int(Decimal(match.group("timestamp")) * Decimal(1_000_000_000))
    except InvalidOperation as error:
        raise ValueError(f"invalid candump timestamp at line {record_index}") from error
    payload = match.group("payload").upper()
    if len(payload) % 2:
        raise ValueError(f"invalid candump payload at line {record_index}")
    return {
        "record_index": record_index,
        "realtime_ns": realtime_ns,
        "interface": match.group("interface"),
        "can_id": int(match.group("can_id"), 16),
        "payload_hex": payload,
    }


def derive_socketcan_ack_lifecycle_evidence(
    runtime_records: Iterable[dict[str, Any]],
    responder_records: Iterable[dict[str, Any]],
    candump_records: Iterable[dict[str, Any]],
    run_manifest: dict[str, Any],
    oracle_manifest: dict[str, Any],
    capture_manifest: dict[str, Any],
    *,
    runtime_source_file: str,
    responder_source_file: str,
    candump_source_file: str,
    run_manifest_source_file: str,
    oracle_manifest_source_file: str,
    capture_manifest_source_file: str,
) -> tuple[list[NormalizedEvent], dict[str, Any]]:
    source_files = (
        runtime_source_file,
        responder_source_file,
        candump_source_file,
        run_manifest_source_file,
        oracle_manifest_source_file,
        capture_manifest_source_file,
    )
    if not all(source_files):
        raise ValueError("all source file paths are required")
    runtime = list(runtime_records)
    responder = list(responder_records)
    candump = list(candump_records)
    variant, injection, reason = _validate_manifests(
        run_manifest, oracle_manifest, capture_manifest
    )
    physical = injection.get("transport_profile") == "physical"
    measurement_semantics = (
        PHYSICAL_MEASUREMENT_SEMANTICS if physical else VCAN_MEASUREMENT_SEMANTICS
    )
    capture_interface = str(
        injection.get("responder_interface", injection.get("can_interface", ""))
    )
    report: dict[str, Any] = {
        "schema_version": "socketcan-ack-lifecycle-evidence/v1",
        "measurement_semantics": measurement_semantics,
        "socketcan_evidence": True,
        "virtual_can_bus": not physical,
        "physical_can_evidence": physical,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "status": "invalid" if reason else "valid",
        "reason_code": reason,
        "profile": {
            "git_commit": run_manifest.get("git_commit", ""),
            "workload": run_manifest.get("workload", ""),
            "host_id": _single_host(runtime),
            **injection,
            "candump_help_sha256": capture_manifest.get("candump_identity", {}).get(
                "help_sha256", ""
            ),
            "responder_script_sha256": capture_manifest.get("responder", {}).get(
                "script_sha256", ""
            ),
        },
        "runtime_source_file": runtime_source_file,
        "responder_source_file": responder_source_file,
        "candump_source_file": candump_source_file,
        "run_manifest_source_file": run_manifest_source_file,
        "oracle_manifest_source_file": oracle_manifest_source_file,
        "capture_manifest_source_file": capture_manifest_source_file,
    }
    if reason:
        return [], report

    by_trace: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    malformed: set[str] = set()
    for index, record in enumerate(runtime, start=1):
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
    terminal_counts: Counter[str] = Counter()
    distributions: dict[str, list[int]] = {
        "attempt_count": [],
        "timeout_count": [],
        "retry_scheduled_count": [],
    }
    latencies: dict[str, list[int]] = {"ack_received": [], "retry_exhausted": []}
    used_responder: set[int] = set()
    used_candump: set[int] = set()
    expected_attempts = 0
    matched_commands = 0
    matched_responders = 0
    expected_acks = 0
    matched_acks = 0
    output: list[tuple[int, str, NormalizedEvent]] = []

    ordered_traces = sorted(
        by_trace.items(),
        key=lambda item: min(
            int(row[1].get("timestamp_ns", 0))
            if _integer(row[1].get("timestamp_ns"))
            else 0
            for row in item[1]
        ),
    )
    for trace_id, rows in ordered_traces:
        if trace_id in malformed:
            invalid["invalid_extra_json"] += 1
            continue
        failure = _validate_runtime_rows(rows, injection)
        if failure:
            invalid[failure] += 1
            continue
        ordered = sorted(rows, key=lambda row: (row[1]["timestamp_ns"], row[0]))
        terminals = [row for row in ordered if row[1]["event_name"] in TERMINALS]
        waits = [row for row in ordered if row[1]["event_name"] == "can_ack_wait_start"]
        if not terminals or not waits:
            incomplete += 1
            continue
        if len(terminals) != 1:
            invalid["conflicting_terminal"] += 1
            continue
        terminal = terminals[0]
        if ordered.index(terminal) != len(ordered) - 1:
            invalid["event_after_terminal"] += 1
            continue
        sends = [row for row in ordered if row[1]["event_name"] == "can_frame_sent"]
        timeouts = [row for row in ordered if row[1]["event_name"] == "can_ack_timeout"]
        retries = [
            row for row in ordered if row[1]["event_name"] == "can_retry_scheduled"
        ]
        terminal_name = str(terminal[1]["event_name"])
        expected_terminal = (
            "can_retry_exhausted" if variant == "injected" else "can_ack_received"
        )
        if terminal_name != expected_terminal:
            invalid["terminal_variant_mismatch"] += 1
            continue
        lifecycle_valid = (
            _valid_exhausted(
                waits, timeouts, retries, terminal, int(injection["max_retries"])
            )
            if terminal_name == "can_retry_exhausted"
            else _valid_success(waits, timeouts, retries, terminal)
        )
        if (
            not lifecycle_valid
            or len(sends) != len(waits)
            or [int(row[2]["retry_count"]) for row in sends]
            != [int(row[2]["retry_count"]) for row in waits]
        ):
            invalid["retry_sequence_mismatch"] += 1
            continue
        expected_attempts += len(sends)
        trace_command_matches = 0
        trace_responder_matches = 0
        trace_ack_matches = 0
        trace_failure = ""
        for _, send_record, send_extra in sends:
            command_can_id = _parse_can_id(send_extra.get("can_id"))
            ack_can_id = _parse_can_id(send_extra.get("ack_can_id"))
            payload_hex = str(send_extra.get("payload_hex", "")).upper()
            command_index = _find_unused(
                candump,
                used_candump,
                lambda record: (
                    record.get("interface") == capture_interface
                    and record.get("can_id") == command_can_id
                    and str(record.get("payload_hex", "")).upper() == payload_hex
                ),
            )
            if command_index is None:
                trace_failure = "missing_candump_command"
                break
            used_candump.add(command_index)
            trace_command_matches += 1
            responder_index = _find_unused(
                responder,
                used_responder,
                lambda record: _responder_matches(
                    record,
                    injection,
                    command_can_id,
                    ack_can_id,
                    payload_hex,
                    int(send_record["timestamp_ns"]),
                    run_manifest["session_id"],
                ),
            )
            if responder_index is None:
                trace_failure = "missing_responder_observation"
                break
            used_responder.add(responder_index)
            trace_responder_matches += 1
            observation = responder[responder_index]
            if variant == "control":
                expected_acks += 1
                if observation.get("send_success") is not True:
                    trace_failure = "responder_ack_send_failed"
                    break
                ack_index = _find_unused(
                    candump,
                    used_candump,
                    lambda record: (
                        record.get("interface") == capture_interface
                        and record.get("can_id") == ack_can_id
                        and str(record.get("payload_hex", "")).upper() == payload_hex
                    ),
                )
                if ack_index is None:
                    trace_failure = "missing_candump_ack"
                    break
                used_candump.add(ack_index)
                trace_ack_matches += 1
            elif observation.get("send_success") is not None:
                trace_failure = "unexpected_drop_send_result"
                break
            elif any(
                record.get("interface") == capture_interface
                and record.get("can_id") == ack_can_id
                and str(record.get("payload_hex", "")).upper() == payload_hex
                for record in candump
            ):
                trace_failure = "unexpected_candump_ack"
                break
        matched_commands += trace_command_matches
        matched_responders += trace_responder_matches
        matched_acks += trace_ack_matches
        if trace_failure:
            invalid[trace_failure] += 1
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
            event_id=f"derived_fusion:socketcan_ack_lifecycle:{trace_id}",
            source="derived_fusion",
            event_type="socketcan_ack_lifecycle_terminal",
            timestamp_ns=int(record["timestamp_ns"]),
            clock_id="monotonic",
            trace_id=trace_id,
            sequence_id=int(record["sequence_id"]),
            stage=terminal_name,
            pid=int(record["pid"]),
            tid=int(record["tid"]),
            host_id=str(record["host_id"]),
            attributes={
                "terminal_state": state,
                "terminal_latency_ns": latency,
                **counts,
                "matched_command_frame_count": trace_command_matches,
                "matched_responder_count": trace_responder_matches,
                "matched_ack_frame_count": trace_ack_matches,
                "measurement_semantics": measurement_semantics,
                "socketcan_evidence": True,
                "virtual_can_bus": not physical,
                "physical_can_evidence": physical,
                "capture_interface": capture_interface,
            },
            provenance={
                "adapter": "socketcan_ack_lifecycle_v1",
                "runtime_source_file": runtime_source_file,
                "responder_source_file": responder_source_file,
                "candump_source_file": candump_source_file,
                "run_manifest_source_file": run_manifest_source_file,
                "oracle_manifest_source_file": oracle_manifest_source_file,
                "capture_manifest_source_file": capture_manifest_source_file,
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
            "command_frame_match_coverage": matched_commands / expected_attempts
            if expected_attempts
            else 0.0,
            "responder_match_coverage": matched_responders / expected_attempts
            if expected_attempts
            else 0.0,
            "ack_frame_match_coverage": matched_acks / expected_acks
            if expected_acks
            else None,
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
        report["reason_code"] = "no_valid_socketcan_ack_terminals"
    elif incomplete or invalid:
        report["status"] = "partial"
        report["reason_code"] = "incomplete_or_invalid_socketcan_ack_lifecycles"
    return [event for _, _, event in sorted(output)], report


def _validate_manifests(
    run: dict[str, Any], oracle: dict[str, Any], capture: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    variant = str(oracle.get("condition_variant", ""))
    if run.get("schema_version") != "fault-run/v1":
        return variant, {}, "invalid_run_manifest"
    if oracle.get("schema_version") != "fault-oracle/v1":
        return variant, {}, "invalid_f6_oracle"
    if any(
        run.get(field) != oracle.get(field)
        for field in ("condition_id", "session_id", "dataset_role")
    ):
        return variant, {}, "run_oracle_identity_mismatch"
    if run.get("dataset_role") != "development":
        return variant, {}, "development_partition_required"
    injection = oracle.get("injection")
    if (
        run.get("workload") != "w1"
        or oracle.get("fault_id") != "F6"
        or variant not in {"injected", "control"}
        or not isinstance(injection, dict)
    ):
        return variant, {}, "invalid_f6_profile"
    transport = injection.get("transport_profile")
    expected = {
        "ack_mode": "socketcan",
        "mock_mode": False,
        "ack_can_id_offset": 128,
        "responder_delay_ms": 5,
        "responder_policy": "drop" if variant == "injected" else "echo",
        "ack_timeout_ms": 20,
        "max_retries": 2,
        "input_rate_hz": 4,
        "planner_backend": "mock",
        "action_manager_enabled": True,
    }
    expected_cause = "can_ack_failure" if variant == "injected" else "none"
    if oracle.get("cause_id") != expected_cause:
        return variant, dict(injection), "oracle_variant_mismatch"
    if transport == "vcan":
        expected["transport_profile"] = "vcan"
        expected["can_interface"] = "vcan0"
    elif transport == "physical":
        expected["transport_profile"] = "physical"
        if (
            not isinstance(injection.get("can_interface"), str)
            or not isinstance(injection.get("responder_interface"), str)
            or injection.get("can_interface") == injection.get("responder_interface")
            or not _integer(injection.get("bitrate"))
            or int(injection["bitrate"]) <= 0
        ):
            return variant, dict(injection), "oracle_profile_mismatch"
    else:
        return variant, dict(injection), "oracle_profile_mismatch"
    if any(injection.get(key) != value for key, value in expected.items()):
        return variant, dict(injection), "oracle_profile_mismatch"
    common_capture_invalid = (
        capture.get("session_id") != run.get("session_id")
        or capture.get("condition_variant") != variant
        or capture.get("capture_profile") != injection
        or capture.get("socketcan_evidence") is not True
    )
    if common_capture_invalid:
        return variant, dict(injection), "invalid_capture_manifest"
    if transport == "vcan" and (
        capture.get("schema_version") != "socketcan-capture/v1"
        or capture.get("virtual_can_bus") is not True
        or capture.get("physical_can_evidence") is not False
    ):
        return variant, dict(injection), "invalid_capture_manifest"
    if transport == "physical" and (
        capture.get("schema_version") != "socketcan-capture/v2"
        or capture.get("virtual_can_bus") is not False
        or capture.get("physical_can_evidence") is not True
        or not _physical_pair_identity_matches(capture.get("interface_pair"), injection)
    ):
        return variant, dict(injection), "invalid_capture_manifest"
    return variant, dict(injection), ""


def _physical_pair_identity_matches(value: Any, injection: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    for phase in ("before", "after"):
        pair = value.get(phase)
        if (
            not isinstance(pair, dict)
            or pair.get("runtime", {}).get("ifname") != injection["can_interface"]
            or pair.get("peer", {}).get("ifname") != injection["responder_interface"]
        ):
            return False
        try:
            validate_physical_can_pair(
                [pair.get("runtime"), pair.get("peer")],
                runtime_interface=str(injection["can_interface"]),
                peer_interface=str(injection["responder_interface"]),
                bitrate=int(injection["bitrate"]),
            )
        except ValueError:
            return False
    return True


def _validate_runtime_rows(
    rows: list[tuple[int, dict[str, Any], dict[str, Any]]], injection: dict[str, Any]
) -> str:
    if any(not _integer(record.get("timestamp_ns")) for _, record, _ in rows):
        return "invalid_timestamp"
    host_ids = {record.get("host_id") for _, record, _ in rows}
    clock_ids = {record.get("clock_id") for _, record, _ in rows}
    sequence_ids = {record.get("sequence_id") for _, record, _ in rows}
    if len(host_ids) != 1 or None in host_ids or clock_ids != {"monotonic"}:
        return "clock_or_host_mismatch"
    if len(sequence_ids) != 1 or not _integer(next(iter(sequence_ids))):
        return "trace_identity_mismatch"
    for _, _, extra in rows:
        if any(
            extra.get(key) != injection[key]
            for key in (
                "ack_mode",
                "mock_mode",
                "can_interface",
                "ack_timeout_ms",
                "max_retries",
            )
        ) or not _integer(extra.get("retry_count")):
            return "event_profile_mismatch"
        if (
            _parse_can_id(extra.get("ack_can_id")) - _parse_can_id(extra.get("can_id"))
            != injection["ack_can_id_offset"]
        ):
            return "event_frame_identity_mismatch"
    return ""


def _responder_matches(
    record: dict[str, Any],
    injection: dict[str, Any],
    command_can_id: int,
    ack_can_id: int,
    payload_hex: str,
    send_timestamp_ns: int,
    session_id: str,
) -> bool:
    receive_timestamp = record.get("receive_monotonic_ns")
    return (
        record.get("record_type") == "command_observed"
        and record.get("session_id") == session_id
        and record.get("interface")
        == injection.get("responder_interface", injection["can_interface"])
        and record.get("policy") == injection["responder_policy"]
        and record.get("decision") == injection["responder_policy"]
        and _parse_can_id(record.get("command_can_id")) == command_can_id
        and _parse_can_id(record.get("ack_can_id")) == ack_can_id
        and str(record.get("command_payload_hex", "")).upper() == payload_hex
        and str(record.get("ack_payload_hex", "")).upper() == payload_hex
        and _integer(receive_timestamp)
        and int(receive_timestamp) + ORDER_TOLERANCE_NS >= send_timestamp_ns
    )


def _find_unused(
    records: list[dict[str, Any]], used: set[int], predicate
) -> int | None:
    for index, record in enumerate(records):
        if index not in used and predicate(record):
            return index
    return None


def _parse_can_id(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            pass
    return -1


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
    parser.add_argument("--responder-events", type=Path, required=True)
    parser.add_argument("--candump", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--oracle-manifest", type=Path, required=True)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--output-events", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    oracle = json.loads(args.oracle_manifest.read_text(encoding="utf-8"))
    capture = json.loads(args.capture_manifest.read_text(encoding="utf-8"))
    responder_sha = _sha256(args.responder_events)
    candump_sha = _sha256(args.candump)
    if capture.get("responder", {}).get("sha256") != responder_sha:
        raise ValueError("responder input hash does not match capture manifest")
    if capture.get("candump", {}).get("sha256") != candump_sha:
        raise ValueError("candump input hash does not match capture manifest")
    candump_records = [
        parse_candump_line(line, index)
        for index, line in enumerate(
            args.candump.read_text(encoding="utf-8").splitlines(), start=1
        )
        if line.strip()
    ]
    events, report = derive_socketcan_ack_lifecycle_evidence(
        _read_jsonl(args.runtime_events),
        _read_jsonl(args.responder_events),
        candump_records,
        run,
        oracle,
        capture,
        runtime_source_file=str(args.runtime_events),
        responder_source_file=str(args.responder_events),
        candump_source_file=str(args.candump),
        run_manifest_source_file=str(args.run_manifest),
        oracle_manifest_source_file=str(args.oracle_manifest),
        capture_manifest_source_file=str(args.capture_manifest),
    )
    report["input_sha256"] = {
        "runtime_events": _sha256(args.runtime_events),
        "responder_events": responder_sha,
        "candump": candump_sha,
        "run_manifest": _sha256(args.run_manifest),
        "oracle_manifest": _sha256(args.oracle_manifest),
        "capture_manifest": _sha256(args.capture_manifest),
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
