"""Deterministic backend that replays normalized planner decision records."""

from __future__ import annotations

from pathlib import Path
from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.base_client import BasePlannerClient
from planner_clients.model_contract import (
    ModelRequest,
    ModelResult,
    PlannerErrorCode,
)
from planner_clients.recording import records_for_request, read_records
from planner_clients.schema import PlannerDecision


class ReplayPlannerClient(BasePlannerClient):
    """Replay a unique recording match; ambiguous recordings fail closed."""

    def __init__(self, recording_path: str | Path) -> None:
        self._recording_path = Path(recording_path)
        self._records = read_records(self._recording_path)

    def plan(self, frame: CameraFrame) -> PlannerDecision:
        raise RuntimeError("ReplayPlannerClient requires plan_with_request")

    def plan_with_request(self, frame: CameraFrame, request: ModelRequest) -> ModelResult:
        matches = records_for_request(self._records, request)
        if len(matches) != 1:
            return ModelResult(
                backend="replay",
                decision=None,
                latency_ns=0,
                error_code=PlannerErrorCode.REPLAY_MISS,
                replayed=True,
            )
        recorded_result = ModelResult.from_public_dict(matches[0]["result"])
        return ModelResult(
            backend="replay",
            decision=recorded_result.decision,
            latency_ns=recorded_result.latency_ns,
            error_code=recorded_result.error_code,
            provider_response_id="",
            response_fingerprint=recorded_result.response_fingerprint,
            replayed=True,
        )
