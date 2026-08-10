#!/usr/bin/env python3
"""Evaluate identity-constrained association on a run-held-out split.

The predictor only receives public event fields.  Oracle labels are retained in
a separate map and joined after predictions have been generated, so the script
can audit the same oracle-isolation rule used by the thesis protocol.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


EXPECTED_STAGES = (
    "camera_frame_published",
    "planner_receive",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
    "can_command_received",
    "can_encode_start",
    "can_encode_end",
    "can_frame_sent",
)
TIMESTAMP_WINDOWS_MS = (100.0, 250.0, 500.0, 1000.0)
BASE_POLICIES = (
    "sequence_only",
    "source_sequence",
    "trace_id",
    "trace_id_contract",
)
PUBLIC_FIELDS = (
    "event_uid",
    "trace_id",
    "sequence_id",
    "stage",
    "timestamp_ns",
)
METRIC_FIELDS = (
    "precision",
    "recall",
    "f1",
    "false_admission_rate",
    "mixed_chain_rate",
    "reject_rate",
    "incomplete_rate",
    "valid_path_coverage",
    "unassigned_event_rate",
    "duplicate_group_rate",
    "topology_violation_rate",
)


@dataclass(frozen=True)
class PublicEvent:
    event_uid: str
    trace_id: str
    sequence_id: int | None
    stage: str
    timestamp_ns: int


@dataclass(frozen=True)
class RunData:
    scenario: str
    run_id: str
    run_dir: Path
    event_path: Path
    manifest_path: Path
    events: tuple[PublicEvent, ...]
    oracle_by_event: dict[str, str]
    stage_by_event: dict[str, str]
    input_sha256: str
    manifest_sha256: str
    public_projection_sha256: str


@dataclass(frozen=True)
class GroupPrediction:
    policy: str
    group_id: str
    events: tuple[PublicEvent, ...]
    missing_stages: tuple[str, ...]
    duplicate_stages: tuple[str, ...]
    order_violation: bool
    sequence_conflict: bool
    accepted: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        default="ROS2Probe/ai_robotics_runtime_ws/reports/paper_formal_20260712",
        help="paper_formal report root containing scenario/run directories",
    )
    parser.add_argument(
        "--scenarios",
        default="overlap_dual_10hz,overlap_dual_mixed",
        help="comma-separated scenarios",
    )
    parser.add_argument("--calibration-runs", default="1,2,3,4,5")
    parser.add_argument("--test-runs", default="6,7,8,9,10")
    parser.add_argument(
        "--output-dir",
        default="revision/heldout_association_20260731/results",
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260731)
    parser.add_argument("--negative-control-repeats", type=int, default=10)
    return parser.parse_args()


def parse_run_ids(raw: str) -> tuple[int, ...]:
    values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    if not values or any(value < 1 for value in values):
        raise ValueError("run IDs must be positive integers")
    if len(set(values)) != len(values):
        raise ValueError("run IDs must be unique")
    return values


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_public_projection(events: Sequence[PublicEvent]) -> str:
    lines = []
    for event in events:
        lines.append(
            json.dumps(
                {field: getattr(event, field) for field in PUBLIC_FIELDS},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def normalize_raw_event(raw: dict[str, Any], event_uid: str) -> tuple[PublicEvent, str]:
    header = raw.get("header") if isinstance(raw.get("header"), dict) else raw
    trace_id = str(header.get("trace_id", ""))
    oracle_id = str(header.get("oracle_id", ""))
    sequence_raw = header.get("sequence_id")
    timestamp_raw = header.get("timestamp_ns")
    stage = str(raw.get("event_name") or header.get("stage") or raw.get("stage") or "")
    if not trace_id or not oracle_id or not stage or timestamp_raw is None:
        raise ValueError("event requires trace_id, oracle_id, stage, and timestamp_ns")
    sequence_id = None if sequence_raw in (None, "") else int(sequence_raw)
    return (
        PublicEvent(
            event_uid=event_uid,
            trace_id=trace_id,
            sequence_id=sequence_id,
            stage=stage,
            timestamp_ns=int(timestamp_raw),
        ),
        oracle_id,
    )


def load_run(source_root: Path, scenario: str, run_number: int) -> RunData:
    run_id = f"run_{run_number:02d}"
    run_dir = source_root / scenario / run_id
    event_path = run_dir / "runtime_events.measurement.jsonl"
    manifest_path = run_dir / "manifest.json"
    if not event_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"missing measurement or manifest for {scenario}/{run_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_scenario = manifest.get("scenario", {}).get("name")
    if manifest_scenario != scenario:
        raise ValueError(f"manifest scenario mismatch in {manifest_path}")

    events: list[PublicEvent] = []
    oracle_by_event: dict[str, str] = {}
    stage_by_event: dict[str, str] = {}
    with event_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            event_uid = f"{scenario}/{run_id}/line_{line_number:06d}"
            event, oracle_id = normalize_raw_event(raw, event_uid)
            events.append(event)
            oracle_by_event[event_uid] = oracle_id
            stage_by_event[event_uid] = event.stage
    events.sort(key=lambda event: (event.timestamp_ns, event.event_uid))
    return RunData(
        scenario=scenario,
        run_id=run_id,
        run_dir=run_dir,
        event_path=event_path,
        manifest_path=manifest_path,
        events=tuple(events),
        oracle_by_event=oracle_by_event,
        stage_by_event=stage_by_event,
        input_sha256=sha256_file(event_path),
        manifest_sha256=sha256_file(manifest_path),
        public_projection_sha256=canonical_public_projection(events),
    )


def group_events(
    events: Iterable[PublicEvent], key_function: Callable[[PublicEvent], str]
) -> dict[str, list[PublicEvent]]:
    groups: dict[str, list[PublicEvent]] = defaultdict(list)
    for event in events:
        groups[key_function(event)].append(event)
    return dict(groups)


def trace_key(event: PublicEvent) -> str:
    return event.trace_id


def sequence_key(event: PublicEvent) -> str:
    return str(event.sequence_id)


def source_sequence_key(event: PublicEvent) -> str:
    parts = event.trace_id.rsplit("_", 2)
    source_id = parts[0] if len(parts) == 3 else event.trace_id
    return f"{source_id}:{event.sequence_id}"


def timestamp_groups(events: Sequence[PublicEvent], window_ns: int) -> dict[str, list[PublicEvent]]:
    groups: dict[str, list[PublicEvent]] = {}
    open_groups: list[str] = []
    group_index = 0
    for event in events:
        if event.stage == "camera_frame_published":
            group_index += 1
            group_id = f"timestamp_{group_index:06d}"
            groups[group_id] = [event]
            open_groups.append(group_id)
            continue

        selected_group = None
        for group_id in reversed(open_groups):
            group_events = groups[group_id]
            age_ns = event.timestamp_ns - group_events[0].timestamp_ns
            stages = {item.stage for item in group_events}
            if 0 <= age_ns <= window_ns and event.stage not in stages:
                selected_group = group_id
                break
        if selected_group is not None:
            groups[selected_group].append(event)
        open_groups = [
            group_id
            for group_id in open_groups
            if event.timestamp_ns - groups[group_id][0].timestamp_ns <= window_ns
        ]
    return groups


def group_predictions(
    events: Sequence[PublicEvent], policy: str, timestamp_window_ms: float | None = None
) -> list[GroupPrediction]:
    if policy == "sequence_only":
        groups = group_events(events, sequence_key)
    elif policy == "source_sequence":
        groups = group_events(events, source_sequence_key)
    elif policy in ("trace_id", "trace_id_contract"):
        groups = group_events(events, trace_key)
    elif policy == "timestamp_only" or policy.startswith("timestamp_"):
        if timestamp_window_ms is None and policy.startswith("timestamp_"):
            timestamp_window_ms = float(policy.split("_")[1][:-2])
        if timestamp_window_ms is None:
            raise ValueError("timestamp_only requires timestamp_window_ms")
        groups = timestamp_groups(events, int(timestamp_window_ms * 1_000_000))
    else:
        raise ValueError(f"unsupported policy: {policy}")

    predictions = []
    for index, (group_key, group) in enumerate(groups.items(), 1):
        counts = Counter(event.stage for event in group)
        missing = tuple(stage for stage in EXPECTED_STAGES if counts[stage] == 0)
        duplicates = tuple(stage for stage in EXPECTED_STAGES if counts[stage] > 1)
        timestamps = {
            stage: next(event.timestamp_ns for event in group if event.stage == stage)
            for stage in EXPECTED_STAGES
            if counts[stage] == 1
        }
        order_violation = any(
            timestamps[end] < timestamps[start]
            for start, end in zip(EXPECTED_STAGES, EXPECTED_STAGES[1:])
            if start in timestamps and end in timestamps
        )
        sequence_ids = {event.sequence_id for event in group if event.sequence_id is not None}
        sequence_conflict = len(sequence_ids) > 1
        complete = not missing
        if policy == "trace_id_contract":
            accepted = complete and not duplicates and not order_violation and not sequence_conflict
        else:
            accepted = complete
        predictions.append(
            GroupPrediction(
                policy=policy,
                group_id=f"{policy}_{index:06d}_{group_key}",
                events=tuple(group),
                missing_stages=missing,
                duplicate_stages=duplicates,
                order_violation=order_violation,
                sequence_conflict=sequence_conflict,
                accepted=accepted,
            )
        )
    return predictions


def score_predictions(
    run: RunData, predictions: Sequence[GroupPrediction]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reference_oracles = {
        run.oracle_by_event[event.event_uid]
        for event in run.events
        if event.stage == "camera_frame_published"
    }
    correct_oracles: set[str] = set()
    correct_group_count = 0
    mixed_group_count = 0
    mixed_accepted_count = 0
    complete_group_count = 0
    duplicate_group_count = 0
    topology_violation_count = 0
    accepted_group_count = 0
    scored_rows: list[dict[str, Any]] = []
    for prediction in predictions:
        oracle_ids = {
            run.oracle_by_event[event.event_uid] for event in prediction.events
        }
        mixed = len(oracle_ids) > 1
        if mixed:
            mixed_group_count += 1
        complete = not prediction.missing_stages
        structurally_valid = (
            complete
            and not prediction.duplicate_stages
            and not prediction.order_violation
            and not prediction.sequence_conflict
            and len(oracle_ids) == 1
        )
        correct = prediction.accepted and structurally_valid
        if complete:
            complete_group_count += 1
        if prediction.duplicate_stages:
            duplicate_group_count += 1
        if prediction.order_violation:
            topology_violation_count += 1
        if prediction.accepted:
            accepted_group_count += 1
            if mixed:
                mixed_accepted_count += 1
        if correct:
            correct_group_count += 1
            correct_oracles.update(oracle_ids)
        scored_rows.append(
            {
                "scenario": run.scenario,
                "run_id": run.run_id,
                "policy": prediction.policy,
                "group_id": prediction.group_id,
                "event_count": len(prediction.events),
                "oracle_count": len(oracle_ids),
                "mixed": mixed,
                "complete": complete,
                "accepted": prediction.accepted,
                "correct": correct,
                "missing_stages": ";".join(prediction.missing_stages),
                "duplicate_stages": ";".join(prediction.duplicate_stages),
                "order_violation": prediction.order_violation,
                "sequence_conflict": prediction.sequence_conflict,
                "oracles": ";".join(sorted(oracle_ids)),
            }
        )

    group_count = len(predictions)
    assigned_events = sum(len(prediction.events) for prediction in predictions)
    precision = (
        correct_group_count / accepted_group_count if accepted_group_count else 0.0
    )
    recall = len(correct_oracles) / len(reference_oracles) if reference_oracles else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    summary = {
        "scenario": run.scenario,
        "run_id": run.run_id,
        "policy": predictions[0].policy if predictions else "",
        "group_count": group_count,
        "reference_trace_count": len(reference_oracles),
        "correct_group_count": correct_group_count,
        "accepted_group_count": accepted_group_count,
        "complete_group_count": complete_group_count,
        "mixed_group_count": mixed_group_count,
        "duplicate_group_count": duplicate_group_count,
        "topology_violation_group_count": topology_violation_count,
        "unassigned_event_count": len(run.events) - assigned_events,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_admission_rate": (
            (accepted_group_count - correct_group_count) / accepted_group_count
            if accepted_group_count
            else 0.0
        ),
        "mixed_chain_rate": (
            mixed_accepted_count / accepted_group_count if accepted_group_count else 0.0
        ),
        "reject_rate": (
            (group_count - accepted_group_count) / group_count if group_count else 0.0
        ),
        "incomplete_rate": (
            (group_count - complete_group_count) / group_count if group_count else 0.0
        ),
        "valid_path_coverage": recall,
        "unassigned_event_rate": (
            (len(run.events) - assigned_events) / len(run.events) if run.events else 0.0
        ),
        "duplicate_group_rate": duplicate_group_count / group_count if group_count else 0.0,
        "topology_violation_rate": topology_violation_count / group_count if group_count else 0.0,
    }
    return summary, scored_rows


def public_prediction_rows(
    run: RunData, predictions: Sequence[GroupPrediction]
) -> list[dict[str, Any]]:
    rows = []
    for prediction in predictions:
        event_hash = sha256_bytes(
            "\n".join(event.event_uid for event in prediction.events).encode("utf-8")
        )[:16]
        rows.append(
            {
                "scenario": run.scenario,
                "run_id": run.run_id,
                "policy": prediction.policy,
                "group_id": prediction.group_id,
                "event_count": len(prediction.events),
                "event_uid_sha256_16": event_hash,
                "missing_stages": ";".join(prediction.missing_stages),
                "duplicate_stages": ";".join(prediction.duplicate_stages),
                "order_violation": prediction.order_violation,
                "sequence_conflict": prediction.sequence_conflict,
                "accepted": prediction.accepted,
            }
        )
    return rows


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_ci(
    values: Sequence[float], resamples: int, seed: int
) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    random_source = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [values[random_source.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    return percentile(means, 0.025), percentile(means, 0.975)


def mean_or_none(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stable_policy_seed(base_seed: int, scenario: str, policy: str, metric: str) -> int:
    token = f"{scenario}|{policy}|{metric}".encode("utf-8")
    return base_seed + int.from_bytes(hashlib.sha256(token).digest()[:4], "big")


def aggregate_run_metrics(
    rows: Sequence[dict[str, Any]],
    scenario: str,
    policy: str,
    bootstrap_resamples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    selected = [row for row in rows if row["scenario"] == scenario and row["policy"] == policy]
    if not selected:
        raise ValueError(f"no held-out rows for {scenario}/{policy}")
    summary: dict[str, Any] = {
        "scenario": scenario,
        "policy": policy,
        "test_run_count": len(selected),
        "test_runs": ";".join(row["run_id"] for row in selected),
        "mean_group_count": mean_or_none([float(row["group_count"]) for row in selected]),
        "mean_reference_trace_count": mean_or_none(
            [float(row["reference_trace_count"]) for row in selected]
        ),
        "pooled_reference_trace_count": sum(int(row["reference_trace_count"]) for row in selected),
    }
    for metric in METRIC_FIELDS:
        values = [float(row[metric]) for row in selected]
        low, high = bootstrap_ci(
            values,
            bootstrap_resamples,
            stable_policy_seed(bootstrap_seed, scenario, policy, metric),
        )
        summary[f"mean_{metric}"] = mean_or_none(values)
        summary[f"bootstrap95_low_{metric}"] = low
        summary[f"bootstrap95_high_{metric}"] = high
    return summary


def contract_valid(events: Sequence[PublicEvent]) -> bool:
    counts = Counter(event.stage for event in events)
    if any(counts[stage] != 1 for stage in EXPECTED_STAGES):
        return False
    timestamps = {event.stage: event.timestamp_ns for event in events}
    if any(
        timestamps[end] < timestamps[start]
        for start, end in zip(EXPECTED_STAGES, EXPECTED_STAGES[1:])
    ):
        return False
    sequence_ids = {event.sequence_id for event in events if event.sequence_id is not None}
    return len(sequence_ids) <= 1


def validator_statuses(
    events: Sequence[PublicEvent], validator: str
) -> dict[str, str]:
    groups = group_events(events, trace_key)
    statuses: dict[str, str] = {}
    for trace_id, trace_events in groups.items():
        counts = Counter(event.stage for event in trace_events)
        cardinality_error = any(counts[stage] != 1 for stage in EXPECTED_STAGES)
        timestamps = {
            event.stage: event.timestamp_ns
            for event in trace_events
            if event.stage in EXPECTED_STAGES and counts[event.stage] == 1
        }
        order_error = (
            not cardinality_error
            and any(
                timestamps[end] < timestamps[start]
                for start, end in zip(EXPECTED_STAGES, EXPECTED_STAGES[1:])
            )
        )
        sequence_ids = {event.sequence_id for event in trace_events if event.sequence_id is not None}
        sequence_error = len(sequence_ids) > 1
        if validator == "grouping_only":
            invalid = False
        elif validator == "cardinality":
            invalid = cardinality_error
        elif validator == "cardinality_order":
            invalid = cardinality_error or order_error
        elif validator == "full_topology":
            invalid = cardinality_error or order_error or sequence_error
        else:
            raise ValueError(f"unsupported validator: {validator}")
        statuses[trace_id] = "invalid" if invalid else "valid"
    return statuses


def inject_trace_fault(
    events: Sequence[PublicEvent], fault_type: str, random_source: random.Random
) -> list[PublicEvent]:
    indexed = {event.stage: event for event in events if event.stage in EXPECTED_STAGES}
    available = [stage for stage in EXPECTED_STAGES if stage in indexed]
    if len(available) < 2:
        return list(events)
    if fault_type == "drop":
        selected = random_source.choice(available[1:-1] or available)
        removed = False
        result = []
        for event in events:
            if event.stage == selected and not removed:
                removed = True
                continue
            result.append(event)
        return result
    if fault_type == "duplicate":
        selected = indexed[random_source.choice(available)]
        duplicate = replace(
            selected,
            event_uid=selected.event_uid + ":duplicate",
            timestamp_ns=selected.timestamp_ns + 1,
        )
        return list(events) + [duplicate]
    if fault_type == "timestamp_inversion":
        pairs = list(zip(EXPECTED_STAGES, EXPECTED_STAGES[1:]))
        start_stage, end_stage = random_source.choice(pairs)
        start_event = indexed[start_stage]
        end_event = indexed[end_stage]
        result = []
        for event in events:
            if event.event_uid == start_event.event_uid:
                result.append(replace(event, timestamp_ns=end_event.timestamp_ns + 1))
            elif event.event_uid == end_event.event_uid:
                result.append(replace(event, timestamp_ns=start_event.timestamp_ns - 1))
            else:
                result.append(event)
        return result
    if fault_type == "sequence_conflict":
        selected = random_source.choice(list(events))
        return [
            replace(event, sequence_id=event.sequence_id + 1)
            if event.event_uid == selected.event_uid and event.sequence_id is not None
            else event
            for event in events
        ]
    raise ValueError(f"unsupported fault type: {fault_type}")


def inject_faults(
    clean_groups: dict[str, list[PublicEvent]],
    fault_type: str,
    fault_rate: float,
    random_source: random.Random,
) -> tuple[list[PublicEvent], set[str]]:
    trace_ids = sorted(clean_groups)
    corruption_count = max(1, round(len(trace_ids) * fault_rate))
    corrupted = set(random_source.sample(trace_ids, corruption_count))
    output: list[PublicEvent] = []
    for trace_id in trace_ids:
        group = clean_groups[trace_id]
        output.extend(
            inject_trace_fault(group, fault_type, random_source)
            if trace_id in corrupted
            else group
        )
    return output, corrupted


def score_negative_control(
    events: Sequence[PublicEvent], corrupted_trace_ids: set[str], validator: str
) -> dict[str, Any]:
    statuses = validator_statuses(events, validator)
    detected = {trace_id for trace_id, status in statuses.items() if status != "valid"}
    all_trace_ids = set(statuses)
    true_positive = len(detected & corrupted_trace_ids)
    false_positive = len(detected - corrupted_trace_ids)
    false_negative = len(corrupted_trace_ids - detected)
    true_negative = len((all_trace_ids - corrupted_trace_ids) - detected)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "trace_count": len(all_trace_ids),
        "corrupted_trace_count": len(corrupted_trace_ids),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_acceptance_rate": false_negative / len(corrupted_trace_ids)
        if corrupted_trace_ids
        else 0.0,
        "false_positive_rate": false_positive / len(all_trace_ids - corrupted_trace_ids)
        if all_trace_ids - corrupted_trace_ids
        else 0.0,
    }


def negative_control_rows(
    runs: Sequence[RunData], repeats: int, base_seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validators = ("grouping_only", "cardinality", "cardinality_order", "full_topology")
    fault_types = ("drop", "duplicate", "timestamp_inversion", "sequence_conflict")
    rates = (0.01, 0.05, 0.10)
    rows: list[dict[str, Any]] = []
    for run in runs:
        clean_groups = {
            trace_id: group
            for trace_id, group in group_events(run.events, trace_key).items()
            if contract_valid(group)
        }
        for fault_type in fault_types:
            for fault_rate in rates:
                for repeat in range(repeats):
                    seed_token = f"{run.scenario}|{run.run_id}|{fault_type}|{fault_rate}|{repeat}"
                    seed = base_seed + int.from_bytes(
                        hashlib.sha256(seed_token.encode("utf-8")).digest()[:4], "big"
                    )
                    random_source = random.Random(seed)
                    corrupted_events, corrupted_ids = inject_faults(
                        clean_groups, fault_type, fault_rate, random_source
                    )
                    for validator in validators:
                        result = score_negative_control(
                            corrupted_events, corrupted_ids, validator
                        )
                        rows.append(
                            {
                                "scenario": run.scenario,
                                "run_id": run.run_id,
                                "fault_type": fault_type,
                                "fault_rate": fault_rate,
                                "repeat": repeat,
                                "seed": seed,
                                "validator": validator,
                                "clean_trace_count": len(clean_groups),
                                **result,
                            }
                        )

    summary: list[dict[str, Any]] = []
    keys = sorted({(row["validator"], row["fault_type"], row["fault_rate"]) for row in rows})
    for validator, fault_type, fault_rate in keys:
        selected = [
            row
            for row in rows
            if row["validator"] == validator
            and row["fault_type"] == fault_type
            and row["fault_rate"] == fault_rate
        ]
        item: dict[str, Any] = {
            "validator": validator,
            "fault_type": fault_type,
            "fault_rate": fault_rate,
            "repeat_count": len(selected),
            "mean_trace_count": mean_or_none([float(row["trace_count"]) for row in selected]),
            "mean_corrupted_trace_count": mean_or_none(
                [float(row["corrupted_trace_count"]) for row in selected]
            ),
        }
        for metric in ("precision", "recall", "f1", "false_acceptance_rate", "false_positive_rate"):
            item[f"mean_{metric}"] = mean_or_none([float(row[metric]) for row in selected])
        summary.append(item)
    return rows, summary


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.bootstrap_resamples < 100:
        raise ValueError("bootstrap-resamples must be at least 100")
    if args.negative_control_repeats < 1:
        raise ValueError("negative-control-repeats must be positive")
    source_root = Path(args.source_root)
    output_dir = Path(args.output_dir)
    scenarios = tuple(value.strip() for value in args.scenarios.split(",") if value.strip())
    calibration_ids = parse_run_ids(args.calibration_runs)
    test_ids = parse_run_ids(args.test_runs)
    if set(calibration_ids) & set(test_ids):
        raise ValueError("calibration and test runs must be disjoint")
    runs = [
        load_run(source_root, scenario, run_number)
        for scenario in scenarios
        for run_number in (*calibration_ids, *test_ids)
    ]
    role_by_run = {
        (scenario, f"run_{run_number:02d}"): "calibration"
        for scenario in scenarios
        for run_number in calibration_ids
    }
    role_by_run.update(
        {
            (scenario, f"run_{run_number:02d}"): "test"
            for scenario in scenarios
            for run_number in test_ids
        }
    )

    candidate_policies = [f"timestamp_{window:g}ms" for window in TIMESTAMP_WINDOWS_MS]
    calibration_rows: list[dict[str, Any]] = []
    all_run_rows: list[dict[str, Any]] = []
    public_rows: list[dict[str, Any]] = []
    scored_rows: list[dict[str, Any]] = []
    labels_rows: list[dict[str, Any]] = []
    prediction_cache: dict[tuple[str, str, str], tuple[GroupPrediction, ...]] = {}
    selected_windows: dict[str, float] = {}

    for run in runs:
        for event_uid, oracle_id in sorted(run.oracle_by_event.items()):
            labels_rows.append(
                {
                    "scenario": run.scenario,
                    "run_id": run.run_id,
                    "event_uid": event_uid,
                    "stage": run.stage_by_event[event_uid],
                    "oracle_id": oracle_id,
                }
            )
        policy_specs: list[tuple[str, float | None]] = [
            (policy, None) for policy in BASE_POLICIES
        ] + [(policy, float(policy.split("_")[1][:-2])) for policy in candidate_policies]
        for policy, timestamp_window in policy_specs:
            predictions = tuple(group_predictions(run.events, policy, timestamp_window))
            prediction_cache[(run.scenario, run.run_id, policy)] = predictions
            summary, rows = score_predictions(run, predictions)
            summary["role"] = role_by_run[(run.scenario, run.run_id)]
            all_run_rows.append(summary)
            public_rows.extend(public_prediction_rows(run, predictions))
            scored_rows.extend(rows)

    for scenario in scenarios:
        calibration_candidates = [
            row
            for row in all_run_rows
            if row["scenario"] == scenario
            and row["role"] == "calibration"
            and row["policy"] in candidate_policies
        ]
        candidate_means = []
        for policy in candidate_policies:
            values = [float(row["f1"]) for row in calibration_candidates if row["policy"] == policy]
            candidate_means.append((mean_or_none(values) or 0.0, float(policy.split("_")[1][:-2]), policy))
        _, selected_window, _ = max(candidate_means, key=lambda item: (item[0], -item[1]))
        selected_windows[scenario] = selected_window
        calibration_rows.extend(
            {
                "scenario": scenario,
                "policy": policy,
                "timestamp_window_ms": float(policy.split("_")[1][:-2]),
                "calibration_mean_f1": mean_or_none(
                    [float(row["f1"]) for row in calibration_candidates if row["policy"] == policy]
                ),
            }
            for policy in candidate_policies
        )
        selected_policy = "timestamp_only"
        for run in runs:
            if run.scenario != scenario:
                continue
            predictions = tuple(group_predictions(run.events, selected_policy, selected_window))
            prediction_cache[(run.scenario, run.run_id, selected_policy)] = predictions
            summary, rows = score_predictions(run, predictions)
            summary["role"] = role_by_run[(run.scenario, run.run_id)]
            summary["timestamp_window_ms"] = selected_window
            all_run_rows.append(summary)
            public_rows.extend(public_prediction_rows(run, predictions))
            scored_rows.extend(rows)

    headline_policies = ("timestamp_only",) + BASE_POLICIES
    heldout_rows = [
        row for row in all_run_rows if row["role"] == "test" and row["policy"] in headline_policies
    ]
    heldout_summary = [
        aggregate_run_metrics(
            heldout_rows,
            scenario,
            policy,
            args.bootstrap_resamples,
            args.bootstrap_seed,
        )
        for scenario in scenarios
        for policy in headline_policies
    ]

    negative_rows, negative_summary = negative_control_rows(
        [run for run in runs if role_by_run[(run.scenario, run.run_id)] == "test"],
        args.negative_control_repeats,
        args.bootstrap_seed,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    split_rows = []
    for run in runs:
        split_rows.append(
            {
                "scenario": run.scenario,
                "run_id": run.run_id,
                "role": role_by_run[(run.scenario, run.run_id)],
                "event_path": str(run.event_path),
                "manifest_path": str(run.manifest_path),
                "event_sha256": run.input_sha256,
                "manifest_sha256": run.manifest_sha256,
                "public_projection_sha256": run.public_projection_sha256,
                "event_count": len(run.events),
            }
        )
    write_csv(output_dir / "run_split_manifest.csv", split_rows)
    write_csv(output_dir / "calibration_timestamp_selection.csv", calibration_rows)
    write_csv(output_dir / "run_metrics_all_policies.csv", all_run_rows)
    write_csv(output_dir / "heldout_summary.csv", heldout_summary)
    write_csv(output_dir / "prediction_groups_public.csv", public_rows)
    write_csv(output_dir / "scored_groups_oracle_joined.csv", scored_rows)
    write_csv(output_dir / "oracle_labels_sealed_after_prediction.csv", labels_rows)
    write_csv(output_dir / "negative_control_runs.csv", negative_rows)
    write_csv(output_dir / "negative_control_summary.csv", negative_summary)

    code_path = Path(__file__).resolve()
    protocol = {
        "protocol_id": "association_run_heldout_v2_standard_metrics",
        "source_root": str(source_root.resolve()),
        "scenarios": list(scenarios),
        "calibration_runs": [f"run_{value:02d}" for value in calibration_ids],
        "test_runs": [f"run_{value:02d}" for value in test_ids],
        "unit": "independent run invocation; same host/boot, not reboot-held-out",
        "metric_definitions": {
            "precision": "correct accepted groups / all accepted groups",
            "recall": "oracle traces recovered by correct accepted groups / reference oracle traces",
            "f1": "harmonic mean of run precision and recall",
            "false_admission_rate": "incorrect accepted groups / all accepted groups",
            "mixed_chain_rate": "accepted groups containing multiple oracle identities / all accepted groups",
            "reject_rate": "rejected candidate groups / all candidate groups",
            "valid_path_coverage": "same denominator as recall",
        },
        "oracle_isolation": {
            "prediction_input_fields": list(PUBLIC_FIELDS),
            "oracle_join_stage": "after all public predictions are generated",
            "oracle_not_used_by_grouping": True,
        },
        "timestamp_windows_ms": list(TIMESTAMP_WINDOWS_MS),
        "headline_policies": list(headline_policies),
        "expected_stages": list(EXPECTED_STAGES),
        "bootstrap_resamples": args.bootstrap_resamples,
        "bootstrap_seed": args.bootstrap_seed,
        "negative_control_repeats": args.negative_control_repeats,
        "negative_control_faults": [
            "drop",
            "duplicate",
            "timestamp_inversion",
            "sequence_conflict",
        ],
        "analysis_script": str(code_path),
        "analysis_script_sha256": sha256_file(code_path),
    }
    (output_dir / "protocol_manifest.json").write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = {
        "protocol": protocol,
        "selected_timestamp_windows_ms": selected_windows,
        "heldout_summary": heldout_summary,
        "negative_control_summary": negative_summary,
        "run_count": len(runs),
        "prediction_group_row_count": len(public_rows),
        "scored_group_row_count": len(scored_rows),
    }
    (output_dir / "heldout_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for row in heldout_summary:
        print(
            f"{row['scenario']} {row['policy']}: "
            f"F1={row['mean_f1']:.4f} "
            f"precision={row['mean_precision']:.4f} "
            f"recall={row['mean_recall']:.4f} "
            f"false_admission={row['mean_false_admission_rate']:.4f}"
        )
    print(f"wrote {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
