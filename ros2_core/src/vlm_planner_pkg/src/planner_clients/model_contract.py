"""Versioned, secret-safe contracts for model-backed planner calls."""

from __future__ import annotations

import hashlib
import json
import math
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any

from planner_clients.schema import PlannerDecision


PROMPT_VERSION = "planner-prompt/v1"
OUTPUT_SCHEMA_VERSION = "planner-decision/v1"


class PlannerErrorCode:
    """Stable public error codes used in evidence and replay records."""

    BACKEND_FAILURE = "backend_failure"
    CONFIGURATION = "configuration_error"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    HTTP_FAILURE = "http_failure"
    INVALID_RESPONSE = "invalid_response"
    NETWORK_FAILURE = "network_failure"
    REPLAY_MISS = "replay_miss"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ModelRequest:
    """The temporal and versioned identity of one planning request."""

    request_id: str
    session_id: str
    trace_id: str
    oracle_id: str
    sequence_id: int
    observation_timestamp_ns: int
    created_timestamp_ns: int
    deadline_ns: int
    input_fingerprint: str
    prompt_version: str = PROMPT_VERSION
    output_schema_version: str = OUTPUT_SCHEMA_VERSION

    def expired(self, now_ns: int | None = None) -> bool:
        if self.deadline_ns <= 0:
            return False
        return (time.monotonic_ns() if now_ns is None else int(now_ns)) > self.deadline_ns

    def public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "oracle_id": self.oracle_id,
            "sequence_id": int(self.sequence_id),
            "observation_timestamp_ns": int(self.observation_timestamp_ns),
            "created_timestamp_ns": int(self.created_timestamp_ns),
            "deadline_ns": int(self.deadline_ns),
            "input_fingerprint": self.input_fingerprint,
            "prompt_version": self.prompt_version,
            "output_schema_version": self.output_schema_version,
        }


@dataclass(frozen=True)
class ModelResult:
    """A structured result whose failure state never contains a raw exception."""

    backend: str
    decision: PlannerDecision | None
    latency_ns: int
    error_code: str = ""
    provider_response_id: str = ""
    response_fingerprint: str = ""
    replayed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.decision is not None and not self.error_code

    def public_dict(self) -> dict[str, Any]:
        decision: dict[str, Any] | None = None
        if self.decision is not None:
            decision = {
                "action": self.decision.action,
                "target": self.decision.target,
                "speed": float(self.decision.speed),
                "confidence": float(self.decision.confidence),
                "reason": self.decision.reason,
            }
        return {
            "backend": self.backend,
            "decision": decision,
            "latency_ns": max(int(self.latency_ns), 0),
            "error_code": self.error_code,
            "provider_response_id": self.provider_response_id,
            "response_fingerprint": self.response_fingerprint,
            "replayed": bool(self.replayed),
        }

    @classmethod
    def from_public_dict(cls, value: dict[str, Any]) -> "ModelResult":
        decision_value = value.get("decision")
        decision = None
        if isinstance(decision_value, dict):
            decision = PlannerDecision(
                action=str(decision_value.get("action", "")),
                target=str(decision_value.get("target", "")),
                speed=float(decision_value.get("speed", 0.0)),
                confidence=float(decision_value.get("confidence", 0.0)),
                reason=str(decision_value.get("reason", "")),
            )
        return cls(
            backend=str(value.get("backend", "")),
            decision=decision,
            latency_ns=max(int(value.get("latency_ns", 0)), 0),
            error_code=str(value.get("error_code", "")),
            provider_response_id=str(value.get("provider_response_id", "")),
            response_fingerprint=str(value.get("response_fingerprint", "")),
            replayed=bool(value.get("replayed", False)),
        )


def make_model_request(
    frame: Any,
    *,
    session_id: str,
    observation_timestamp_ns: int,
    ttl_ms: int,
    now_ns: int | None = None,
    prompt_version: str = PROMPT_VERSION,
    output_schema_version: str = OUTPUT_SCHEMA_VERSION,
) -> ModelRequest:
    """Create a request without persisting camera paths or image payloads."""

    created_ns = time.monotonic_ns() if now_ns is None else int(now_ns)
    observation_ns = int(observation_timestamp_ns)
    ttl_ns = max(int(ttl_ms), 0) * 1_000_000
    header = getattr(frame, "header", None)
    trace_id = str(getattr(header, "trace_id", ""))
    oracle_id = str(getattr(header, "oracle_id", ""))
    sequence_id = int(getattr(header, "sequence_id", 0))
    return ModelRequest(
        request_id=_request_id(session_id, trace_id, oracle_id, sequence_id),
        session_id=session_id,
        trace_id=trace_id,
        oracle_id=oracle_id,
        sequence_id=sequence_id,
        observation_timestamp_ns=observation_ns,
        created_timestamp_ns=created_ns,
        deadline_ns=observation_ns + ttl_ns if ttl_ns else 0,
        input_fingerprint=frame_fingerprint(frame),
        prompt_version=prompt_version,
        output_schema_version=output_schema_version,
    )


def make_session_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:16]}"


def frame_fingerprint(frame: Any) -> str:
    """Return a canonical digest; raw paths and image bytes never enter records."""

    payload = bytes(getattr(frame, "payload", b""))
    canonical = {
        "encoding": str(getattr(frame, "encoding", "")),
        "frame_id": int(getattr(frame, "frame_id", 0)),
        "height": int(getattr(frame, "height", 0)),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "width": int(getattr(frame, "width", 0)),
    }
    return _canonical_hash(canonical)


def response_fingerprint(result: ModelResult) -> str:
    """Fingerprint only the normalized decision/error contract."""

    public = result.public_dict()
    public.pop("latency_ns", None)
    public.pop("replayed", None)
    return _canonical_hash(public)


def validate_decision(decision: PlannerDecision) -> str:
    """Validate decisions from every backend before they reach ROS publication."""

    allowed_actions = {"move_forward", "turn_left", "turn_right", "stop", "inspect"}
    if decision.action not in allowed_actions:
        return "planner_decision_action_not_allowed"
    if not math.isfinite(float(decision.speed)):
        return "planner_decision_speed_not_finite"
    if not 0.0 <= float(decision.speed) <= 1.0:
        return "planner_decision_speed_out_of_range"
    if not math.isfinite(float(decision.confidence)):
        return "planner_decision_confidence_not_finite"
    if not 0.0 <= float(decision.confidence) <= 1.0:
        return "planner_decision_confidence_out_of_range"
    if decision.action == "stop" and float(decision.speed) != 0.0:
        return "planner_decision_stop_speed_nonzero"
    return ""


def classify_backend_error(error: BaseException) -> str:
    """Map unstable provider exceptions to a small public evidence vocabulary."""

    if isinstance(error, TimeoutError):
        return PlannerErrorCode.TIMEOUT
    name = error.__class__.__name__.lower()
    message = str(error).lower()
    if "timeout" in name or "timed out" in message or "timeout" in message:
        return PlannerErrorCode.TIMEOUT
    if "json" in name or "json" in message or "response" in message:
        return PlannerErrorCode.INVALID_RESPONSE
    if "http" in name or "http status" in message:
        return PlannerErrorCode.HTTP_FAILURE
    if "url" in name or "socket" in name or "connection" in name or "network" in message:
        return PlannerErrorCode.NETWORK_FAILURE
    if "config" in message or "missing llm" in message or "unsupported" in message:
        return PlannerErrorCode.CONFIGURATION
    return PlannerErrorCode.BACKEND_FAILURE


def _request_id(session_id: str, trace_id: str, oracle_id: str, sequence_id: int) -> str:
    material = f"{session_id}|{trace_id}|{oracle_id}|{int(sequence_id)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
