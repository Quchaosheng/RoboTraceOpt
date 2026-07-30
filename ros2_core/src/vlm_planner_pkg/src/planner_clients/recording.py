"""Append-only, secret-safe planner decision recordings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from planner_clients.model_contract import ModelRequest, ModelResult, response_fingerprint


RECORDING_SCHEMA_VERSION = "planner-decision-record/v1"


class PlannerDecisionRecorder:
    """Persist normalized requests and results without model inputs or raw replies."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def record(self, request: ModelRequest, result: ModelResult) -> dict[str, Any]:
        row = make_record(request, result)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        return row


def make_record(request: ModelRequest, result: ModelResult) -> dict[str, Any]:
    public_result = result.public_dict()
    public_result["response_fingerprint"] = (
        public_result["response_fingerprint"] or response_fingerprint(result)
    )
    return {
        "schema_version": RECORDING_SCHEMA_VERSION,
        "request": request.public_dict(),
        "result": public_result,
    }


def read_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    records = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid recording JSON at line {line_number}") from error
        _validate_record(value, line_number)
        records.append(value)
    return records


def replay_key(request: ModelRequest) -> tuple[str, str, str]:
    return (
        request.input_fingerprint,
        request.prompt_version,
        request.output_schema_version,
    )


def records_for_request(
    records: Iterable[dict[str, Any]], request: ModelRequest
) -> list[dict[str, Any]]:
    key = replay_key(request)
    matches = []
    for row in records:
        recorded_request = row["request"]
        recorded_key = (
            str(recorded_request["input_fingerprint"]),
            str(recorded_request["prompt_version"]),
            str(recorded_request["output_schema_version"]),
        )
        if recorded_key == key:
            matches.append(row)
    return matches


def _validate_record(value: Any, line_number: int) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != RECORDING_SCHEMA_VERSION:
        raise ValueError(f"unsupported recording schema at line {line_number}")
    request = value.get("request")
    result = value.get("result")
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise ValueError(f"recording is missing request/result at line {line_number}")
    required_request = {
        "request_id",
        "session_id",
        "trace_id",
        "oracle_id",
        "sequence_id",
        "observation_timestamp_ns",
        "created_timestamp_ns",
        "deadline_ns",
        "input_fingerprint",
        "prompt_version",
        "output_schema_version",
    }
    if required_request - set(request):
        raise ValueError(f"recording request is incomplete at line {line_number}")
    required_result = {
        "backend",
        "decision",
        "latency_ns",
        "error_code",
        "provider_response_id",
        "response_fingerprint",
        "replayed",
    }
    if required_result - set(result):
        raise ValueError(f"recording result is incomplete at line {line_number}")
