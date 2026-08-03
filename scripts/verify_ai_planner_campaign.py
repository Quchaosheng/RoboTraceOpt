#!/usr/bin/env python3
"""Validate trace-scoped AI planner evidence and secret-safe recordings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ai_campaign_contract import select_trace_events, summarize_trace, validate_trace


REQUIRED_EVENT_FIELDS = {
    "trace_id",
    "oracle_id",
    "sequence_id",
    "stage",
    "timestamp_ns",
    "pid",
    "tid",
    "host_id",
    "clock_id",
    "duration_ns",
    "status",
    "reason_code",
    "extra_json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--secret-env", default="LLM_API_KEY")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_events(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"event {number} is not an object: {path}")
        missing = REQUIRED_EVENT_FIELDS - set(row)
        if missing:
            raise ValueError(f"event {number} is missing {sorted(missing)}: {path}")
        if row["clock_id"] != "monotonic" or int(row["pid"]) <= 0 or int(row["tid"]) <= 0:
            raise ValueError(f"event {number} has invalid provenance: {path}")
        extra = json.loads(row["extra_json"])
        if not isinstance(extra, dict):
            raise ValueError(f"event {number} has non-object extra_json: {path}")
        row["extra"] = extra
        rows.append(row)
    if not rows:
        raise ValueError(f"event file is empty: {path}")
    return rows


def validate_trial(root: Path, trial: dict[str, Any]) -> list[str]:
    errors = []
    name = str(trial["condition"])
    repetition = int(trial["repetition"])
    run_dir = root / name / f"run_{repetition:02d}"
    events_path = run_dir / "runtime_events.jsonl"
    log_path = run_dir / "launch.log"
    trial_summary_path = run_dir / "trial_summary.json"
    for path in (events_path, log_path, trial_summary_path):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing_or_empty:{path.relative_to(root)}")
    if errors:
        return errors

    rows = read_events(events_path)
    terminal_stage = str(trial.get("expected_terminal_stage", ""))
    if not terminal_stage:
        errors.append("trial_missing_expected_terminal_stage")
        return errors
    selected_key, scoped_rows = select_trace_events(rows, terminal_stage)
    if selected_key is None:
        errors.append("expected_terminal_not_observed")
        return errors
    expected_key = (
        str(trial.get("trace_id", "")),
        str(trial.get("oracle_id", "")),
        int(trial.get("sequence_id", 0)),
    )
    if selected_key != expected_key:
        errors.append("trial_summary_trace_mismatch")

    trace_summary = summarize_trace(scoped_rows)
    expected_outcome = str(trial.get("expected_outcome", ""))
    errors.extend(validate_trace(trace_summary, expected_outcome))
    if trial.get("status") != "complete":
        errors.append("trial_summary_incomplete")
    if trial.get("semantic_errors"):
        errors.append("trial_summary_has_semantic_errors")
    if trial.get("task_success_semantics") != "not_measured_by_runtime_event_campaign":
        errors.append("task_success_semantics_mismatch")
    if trial.get("command_delivery_observed") != bool(trace_summary["can_ack_count"]):
        errors.append("command_delivery_summary_mismatch")

    record_path = run_dir / "planner_decisions.jsonl"
    if record_path.is_file():
        recording = record_path.read_text(encoding="utf-8")
        for forbidden in ("image_path", "payload", "LLM_API_KEY"):
            if forbidden in recording:
                errors.append(f"recording_contains_forbidden_field:{forbidden}")
    return errors


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    root = args.campaign_dir.resolve()
    summary_path = root / "campaign_summary.json"
    summary = read_json(summary_path)
    errors = []
    if summary.get("schema_version") not in {
        "ai-planner-campaign-summary/v2",
        "ai-vision-set-summary/v2",
    }:
        errors.append("unsupported_summary_schema")
    if summary.get("task_success_semantics") != "not_measured_by_runtime_event_campaign":
        errors.append("summary_task_success_semantics_mismatch")
    trials = summary.get("trials")
    if not isinstance(trials, list) or not trials:
        errors.append("missing_trials")
        trials = []
    for trial in trials:
        if not isinstance(trial, dict):
            errors.append("invalid_trial_record")
            continue
        try:
            trial_errors = validate_trial(root, trial)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            trial_errors = [f"trial_validation_error:{error.__class__.__name__}"]
        for error in trial_errors:
            errors.append(
                f"{trial.get('condition')}/run_{int(trial.get('repetition', 0)):02d}:{error}"
            )

    secret = os.environ.get(args.secret_env, "").encode("utf-8")
    secret_leak_paths = []
    records = []
    excluded = {"artifact_manifest.json", "integrity.json"}
    for path in sorted(
        item for item in root.rglob("*") if item.is_file() and item.name not in excluded
    ):
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        if secret and secret in payload:
            secret_leak_paths.append(relative)
        records.append(
            {
                "path": relative,
                "bytes": len(payload),
                "sha256": sha256(path),
            }
        )
    if secret_leak_paths:
        errors.append("secret_leak_detected")

    manifest = {
        "schema_version": "ai-planner-artifact-manifest/v2",
        "artifact_count": len(records),
        "artifacts": records,
    }
    (root / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    integrity = {
        "schema_version": "ai-planner-campaign-integrity/v2",
        "status": "complete" if not errors else "invalid",
        "trial_count": len(trials),
        "artifact_count": len(records),
        "secret_env_checked": args.secret_env,
        "secret_was_available_for_comparison": bool(secret),
        "secret_leak_detected": bool(secret_leak_paths),
        "errors": errors,
    }
    (root / "integrity.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(integrity, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
