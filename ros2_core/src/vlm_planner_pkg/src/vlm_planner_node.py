import json
import os
import socket
import threading
import time
from typing import Any, Dict, Optional

import rclpy
from ai_robot_runtime_interfaces.msg import CameraFrame, PlannerCommand, RuntimeEvent
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from planner_clients.admission import ModelAdmission
from planner_clients.base_client import BasePlannerClient
from planner_clients.llm_client import OpenAICompatiblePlannerClient
from planner_clients.delay import apply_delay
from planner_clients.model_contract import (
    ModelRequest,
    ModelResult,
    PlannerErrorCode,
    make_model_request,
    make_session_id,
    validate_decision,
)
from planner_clients.mock_client import MockPlannerClient
from planner_clients.recording import PlannerDecisionRecorder
from planner_clients.replay_client import ReplayPlannerClient
from planner_clients.schema import PlannerDecision


class VlmPlannerNode(Node):
    def __init__(self) -> None:
        super().__init__("vlm_planner_node")

        self._planner_backend = (
            self.declare_parameter("planner_backend", "mock")
            .get_parameter_value()
            .string_value
        ).strip().lower() or "mock"
        self._planner_mode = (
            self.declare_parameter("planner_mode", "mock")
            .get_parameter_value()
            .string_value
        )
        self._planner_delay_ms = (
            self.declare_parameter("planner_delay_ms", 50)
            .get_parameter_value()
            .integer_value
        )
        self._planner_delay_mode = (
            (
                self.declare_parameter("planner_delay_mode", "sleep")
                .get_parameter_value()
                .string_value
            )
            .strip()
            .lower()
        )
        self._executor_contention_enabled = (
            self.declare_parameter("executor_contention_enabled", False)
            .get_parameter_value()
            .bool_value
        )
        self._executor_contention_period_ms = int(
            self.declare_parameter("executor_contention_period_ms", 25)
            .get_parameter_value()
            .integer_value
        )
        self._executor_contention_load_ms = int(
            self.declare_parameter("executor_contention_load_ms", 0)
            .get_parameter_value()
            .integer_value
        )
        self.executor_threads = int(
            self.declare_parameter("executor_threads", 1)
            .get_parameter_value()
            .integer_value
        )
        if not 1 <= self.executor_threads <= 4:
            raise ValueError("executor_threads must be between 1 and 4")
        self._runtime_events_enabled = (
            self.declare_parameter("runtime_events_enabled", True)
            .get_parameter_value()
            .bool_value
        )
        self._frame_qos_depth = int(
            self.declare_parameter("frame_qos_depth", 10)
            .get_parameter_value()
            .integer_value
        )
        self._frame_qos_reliability = (
            (
                self.declare_parameter("frame_qos_reliability", "reliable")
                .get_parameter_value()
                .string_value
            )
            .strip()
            .lower()
        )
        if self._frame_qos_depth <= 0:
            raise ValueError("frame_qos_depth must be positive")
        if self._frame_qos_reliability not in {"reliable", "best_effort"}:
            raise ValueError("frame_qos_reliability must be reliable or best_effort")
        self._llm_provider = (
            (
                self.declare_parameter("llm_provider", "openai_compatible")
                .get_parameter_value()
                .string_value
            )
            .strip()
            .lower()
        )
        self._llm_api_base = (
            self.declare_parameter("llm_api_base", os.environ.get("LLM_API_BASE", ""))
            .get_parameter_value()
            .string_value
        )
        self._llm_api_key_env = (
            self.declare_parameter("llm_api_key_env", "LLM_API_KEY")
            .get_parameter_value()
            .string_value
        )
        self._llm_model = (
            self.declare_parameter("llm_model", os.environ.get("LLM_MODEL", ""))
            .get_parameter_value()
            .string_value
        )
        self._llm_timeout_s = (
            self.declare_parameter("llm_timeout_s", 3.0)
            .get_parameter_value()
            .double_value
        )
        self._llm_api_style = (
            self.declare_parameter(
                "llm_api_style", os.environ.get("LLM_API_STYLE", "chat_completions")
            )
            .get_parameter_value()
            .string_value
        ).strip().lower()
        self._llm_vision_mode = (
            self.declare_parameter("llm_vision_mode", "metadata")
            .get_parameter_value()
            .string_value
        )
        self._llm_max_image_bytes = int(
            self.declare_parameter("llm_max_image_bytes", 1_000_000)
            .get_parameter_value()
            .integer_value
        )
        if self._llm_max_image_bytes <= 0:
            raise ValueError("llm_max_image_bytes must be positive")
        self._observation_ttl_ms = int(
            self.declare_parameter("observation_ttl_ms", 1000)
            .get_parameter_value()
            .integer_value
        )
        self._model_queue_delay_ms = int(
            self.declare_parameter("model_queue_delay_ms", 0)
            .get_parameter_value()
            .integer_value
        )
        self._model_queue_delay_mode = (
            self.declare_parameter("model_queue_delay_mode", "sleep")
            .get_parameter_value()
            .string_value
            .strip()
            .lower()
        )
        self._model_dedup_window_ms = int(
            self.declare_parameter("model_dedup_window_ms", 10000)
            .get_parameter_value()
            .integer_value
        )
        self._observation_max_future_skew_ms = int(
            self.declare_parameter("observation_max_future_skew_ms", 100)
            .get_parameter_value()
            .integer_value
        )
        self._model_failure_window_ms = int(
            self.declare_parameter("model_failure_window_ms", 30000)
            .get_parameter_value()
            .integer_value
        )
        self._model_failure_storm_count = int(
            self.declare_parameter("model_failure_storm_count", 3)
            .get_parameter_value()
            .integer_value
        )
        self._model_record_path = (
            self.declare_parameter("model_record_path", "")
            .get_parameter_value()
            .string_value
            .strip()
        )
        self._model_replay_path = (
            self.declare_parameter("model_replay_path", "")
            .get_parameter_value()
            .string_value
            .strip()
        )
        if self._observation_ttl_ms <= 0:
            raise ValueError("observation_ttl_ms must be positive")
        if self._model_queue_delay_ms < 0:
            raise ValueError("model_queue_delay_ms must be non-negative")
        if self._model_queue_delay_mode not in {"sleep", "busy_compute"}:
            raise ValueError("model_queue_delay_mode must be sleep or busy_compute")
        if self._model_dedup_window_ms <= 0:
            raise ValueError("model_dedup_window_ms must be positive")
        if self._observation_max_future_skew_ms < 0:
            raise ValueError("observation_max_future_skew_ms must be non-negative")
        if self._model_failure_window_ms <= 0 or self._model_failure_storm_count <= 0:
            raise ValueError("model failure window and threshold must be positive")
        self._fallback_to_mock = (
            self.declare_parameter("fallback_to_mock", False)
            .get_parameter_value()
            .bool_value
        )
        if self._fallback_to_mock and self._planner_backend == "llm":
            self.get_logger().warn(
                "fallback_to_mock is deprecated and ignored for llm; "
                "LLM failures abstain without publishing a motion command"
            )

        if self._planner_mode not in ("", "mock"):
            self.get_logger().warn(
                "planner_mode is deprecated and ignored; use planner_backend for backend selection"
            )

        self._mock_client = MockPlannerClient(
            delay_ms=int(self._planner_delay_ms), delay_mode=self._planner_delay_mode
        )
        self._host_id = socket.gethostname()
        self._session_id = make_session_id()
        self._model_admission = ModelAdmission(
            dedup_window_ms=self._model_dedup_window_ms,
            failure_window_ms=self._model_failure_window_ms,
            max_failures=self._model_failure_storm_count,
            max_future_skew_ms=self._observation_max_future_skew_ms,
        )
        self._decision_recorder = (
            PlannerDecisionRecorder(self._model_record_path)
            if self._model_record_path
            else None
        )
        self._llm_client: Optional[OpenAICompatiblePlannerClient] = None
        self._replay_client: Optional[ReplayPlannerClient] = None
        self._startup_fallback_reason = ""
        self._active_backend = self._configure_backend()
        self._frame_callback_group = MutuallyExclusiveCallbackGroup()
        self._contention_callback_group = MutuallyExclusiveCallbackGroup()

        self._command_publisher = self.create_publisher(
            PlannerCommand,
            "/planner/command",
            10,
        )
        self._event_publisher = self.create_publisher(
            RuntimeEvent,
            "/runtime/events",
            10,
        )
        frame_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=self._frame_qos_depth,
            reliability=(
                ReliabilityPolicy.RELIABLE
                if self._frame_qos_reliability == "reliable"
                else ReliabilityPolicy.BEST_EFFORT
            ),
            durability=DurabilityPolicy.VOLATILE,
        )
        self._frame_subscription = self.create_subscription(
            CameraFrame,
            "/camera/frame",
            self._on_camera_frame,
            frame_qos,
            callback_group=self._frame_callback_group,
        )
        self._contention_timer = None
        if self._executor_contention_enabled:
            if self._executor_contention_period_ms <= 0:
                raise ValueError("executor_contention_period_ms must be positive")
            if self._executor_contention_load_ms <= 0:
                raise ValueError("executor_contention_load_ms must be positive")
            self._contention_timer = self.create_timer(
                self._executor_contention_period_ms / 1000.0,
                self._run_executor_contention,
                callback_group=self._contention_callback_group,
            )

        self.get_logger().info(
            f"vlm_planner_node running with planner_backend={self._planner_backend}, "
            f"active_backend={self._active_backend}, executor_threads={self.executor_threads}, "
            "publishing /planner/command"
        )

    def _on_camera_frame(self, frame: CameraFrame) -> None:
        planning_started_ns = time.monotonic_ns()
        request = make_model_request(
            frame,
            session_id=self._session_id,
            observation_timestamp_ns=int(frame.header.timestamp_ns),
            ttl_ms=self._observation_ttl_ms,
            now_ns=planning_started_ns,
        )
        self._publish_event(
            frame,
            "planner_receive",
            self._make_event_extra(frame, request=request),
        )
        admission_reason = self._model_admission.admit(request, planning_started_ns)
        if admission_reason:
            self._reject_without_model(
                frame,
                request,
                stage="planner_request_rejected",
                reason_code=admission_reason,
                started_ns=planning_started_ns,
            )
            return

        self._publish_event(
            frame,
            "planner_process_start",
            self._make_event_extra(
                frame,
                request=request,
                extra={
                    "planner_delay_ms": int(self._planner_delay_ms),
                    "planner_delay_mode": self._planner_delay_mode,
                    "model_queue_delay_ms": self._model_queue_delay_ms,
                    "model_queue_delay_mode": self._model_queue_delay_mode,
                    "executor_contention_enabled": self._executor_contention_enabled,
                    "executor_contention_period_ms": self._executor_contention_period_ms,
                    "executor_contention_load_ms": self._executor_contention_load_ms,
                    "llm_timeout_s": float(self._llm_timeout_s),
                },
            ),
        )

        if self._model_queue_delay_ms:
            apply_delay(self._model_queue_delay_ms, self._model_queue_delay_mode)
        queued_ns = time.monotonic_ns()
        queue_reason = self._model_admission.output_allowed(request, queued_ns)
        if queue_reason:
            self._reject_without_model(
                frame,
                request,
                stage="planner_queue_deadline_exceeded",
                reason_code=queue_reason,
                started_ns=planning_started_ns,
            )
            return

        result = self._plan(frame, request)
        planning_finished_ns = time.monotonic_ns()
        output_reason = self._model_admission.output_allowed(request, planning_finished_ns)
        if output_reason:
            self._publish_event(
                frame,
                "planner_output_stale",
                self._make_event_extra(
                    frame,
                    request=request,
                    result=result,
                    used_fallback=not result.succeeded,
                    effective_backend="abstain",
                    fallback_reason=output_reason,
                ),
                timestamp_ns=planning_finished_ns,
                duration_ns=planning_finished_ns - planning_started_ns,
                status="rejected",
                reason_code=output_reason,
            )
            self._publish_abstention(
                frame,
                request,
                result,
                output_reason,
                planning_started_ns,
                planning_finished_ns,
            )
            return

        if not result.succeeded:
            self._publish_event(
                frame,
                "planner_backend_failure",
                self._make_event_extra(
                    frame,
                    request=request,
                    result=result,
                    used_fallback=True,
                    effective_backend="abstain",
                    fallback_reason=result.error_code,
                ),
                timestamp_ns=planning_finished_ns,
                duration_ns=planning_finished_ns - planning_started_ns,
                status="error",
                reason_code=result.error_code or PlannerErrorCode.BACKEND_FAILURE,
            )
            if self._model_admission.note_backend_failure(planning_finished_ns):
                self._publish_event(
                    frame,
                    "planner_fallback_storm",
                    self._make_event_extra(
                        frame,
                        request=request,
                        result=result,
                        used_fallback=True,
                        effective_backend="abstain",
                        fallback_reason=result.error_code,
                        extra={
                            "model_failure_count_in_window": (
                                self._model_admission.failure_count_in_window
                            ),
                            "model_failure_storm_count": self._model_failure_storm_count,
                        },
                    ),
                    timestamp_ns=planning_finished_ns,
                    duration_ns=planning_finished_ns - planning_started_ns,
                    status="rejected",
                    reason_code="planner_fallback_storm",
                )
            self._publish_abstention(
                frame,
                request,
                result,
                result.error_code or PlannerErrorCode.BACKEND_FAILURE,
                planning_started_ns,
                planning_finished_ns,
            )
            return

        assert result.decision is not None
        decision_reason = validate_decision(result.decision)
        if decision_reason:
            self._publish_event(
                frame,
                "planner_decision_rejected",
                self._make_event_extra(
                    frame,
                    request=request,
                    result=result,
                    effective_backend="abstain",
                    fallback_reason=decision_reason,
                ),
                timestamp_ns=planning_finished_ns,
                duration_ns=planning_finished_ns - planning_started_ns,
                status="rejected",
                reason_code=decision_reason,
            )
            self._publish_abstention(
                frame,
                request,
                result,
                decision_reason,
                planning_started_ns,
                planning_finished_ns,
            )
            return

        self._publish_event(
            frame,
            "planner_process_end",
            self._make_event_extra(
                frame,
                decision=result.decision,
                request=request,
                result=result,
                effective_backend=result.backend,
            ),
            timestamp_ns=planning_finished_ns,
            duration_ns=planning_finished_ns - planning_started_ns,
        )
        command = self._make_command(frame, result.decision)
        self._command_publisher.publish(command)
        self._publish_event(
            frame,
            "planner_publish",
            self._make_event_extra(
                frame,
                decision=result.decision,
                request=request,
                result=result,
                effective_backend=result.backend,
            ),
            timestamp_ns=int(command.header.timestamp_ns),
        )

    def _run_executor_contention(self) -> None:
        apply_delay(self._executor_contention_load_ms, "busy_compute")

    def _configure_backend(self) -> str:
        if self._planner_backend not in ("mock", "llm", "replay"):
            message = f"unsupported planner_backend={self._planner_backend}"
            self._startup_fallback_reason = message
            self.get_logger().error(f"{message}; entering fail-closed abstain mode")
            return "abstain"

        if self._planner_backend == "mock":
            return "mock"

        if self._planner_backend == "replay":
            if not self._model_replay_path:
                self._startup_fallback_reason = "missing model_replay_path"
                self.get_logger().error(
                    "missing model_replay_path; entering fail-closed abstain mode"
                )
                return "abstain"
            try:
                self._replay_client = ReplayPlannerClient(self._model_replay_path)
            except (OSError, ValueError) as error:
                self._startup_fallback_reason = error.__class__.__name__
                self.get_logger().error(
                    "cannot load model replay; entering fail-closed abstain mode"
                )
                return "abstain"
            return "replay"

        if self._llm_provider != "openai_compatible":
            message = f"unsupported llm_provider={self._llm_provider}"
            self._startup_fallback_reason = message
            self.get_logger().error(f"{message}; entering fail-closed abstain mode")
            return "abstain"

        llm_api_key = os.environ.get(self._llm_api_key_env, "")
        missing = []
        if not self._llm_api_base:
            missing.append("LLM_API_BASE")
        if not llm_api_key:
            missing.append(self._llm_api_key_env)
        if not self._llm_model:
            missing.append("LLM_MODEL")

        if missing:
            message = "missing " + ",".join(missing)
            self._startup_fallback_reason = message
            self.get_logger().error(f"{message}; entering fail-closed abstain mode")
            return "abstain"

        self._llm_client = OpenAICompatiblePlannerClient(
            api_base=self._llm_api_base,
            api_key=llm_api_key,
            model=self._llm_model,
            timeout_s=float(self._llm_timeout_s),
            api_style=self._llm_api_style,
            vision_mode=self._llm_vision_mode,
            max_image_bytes=self._llm_max_image_bytes,
        )
        return "llm"

    def _plan(self, frame: CameraFrame, request: ModelRequest) -> ModelResult:
        backend: Optional[BasePlannerClient] = None
        if self._active_backend == "mock":
            backend = self._mock_client
        elif self._active_backend == "llm":
            backend = self._llm_client
        elif self._active_backend == "replay":
            backend = self._replay_client

        if backend is None:
            result = ModelResult(
                backend="abstain",
                decision=None,
                latency_ns=0,
                error_code=PlannerErrorCode.CONFIGURATION,
            )
            self._record_model_result(request, result)
            return result

        try:
            raw_result = backend.plan_with_request(frame, request)
        except Exception as error:
            self.get_logger().error(
                f"planner backend raised {error.__class__.__name__}; abstaining"
            )
            raw_result = ModelResult(
                backend=self._active_backend,
                decision=None,
                latency_ns=0,
                error_code=PlannerErrorCode.BACKEND_FAILURE,
            )
        result = ModelResult(
            backend=self._active_backend,
            decision=raw_result.decision,
            latency_ns=raw_result.latency_ns,
            error_code=raw_result.error_code,
            provider_response_id=raw_result.provider_response_id,
            response_fingerprint=raw_result.response_fingerprint,
            replayed=raw_result.replayed,
        )
        self._record_model_result(request, result)
        return result

    def _reject_without_model(
        self,
        frame: CameraFrame,
        request: ModelRequest,
        *,
        stage: str,
        reason_code: str,
        started_ns: int,
    ) -> None:
        result = ModelResult(
            backend=self._active_backend,
            decision=None,
            latency_ns=0,
            error_code=reason_code,
        )
        self._record_model_result(request, result)
        finished_ns = time.monotonic_ns()
        self._publish_event(
            frame,
            stage,
            self._make_event_extra(
                frame,
                request=request,
                result=result,
                used_fallback=True,
                effective_backend="abstain",
                fallback_reason=reason_code,
            ),
            timestamp_ns=finished_ns,
            duration_ns=finished_ns - started_ns,
            status="rejected",
            reason_code=reason_code,
        )
        self._publish_abstention(
            frame,
            request,
            result,
            reason_code,
            started_ns,
            finished_ns,
        )

    def _publish_abstention(
        self,
        frame: CameraFrame,
        request: ModelRequest,
        result: ModelResult,
        reason_code: str,
        started_ns: int,
        finished_ns: int,
    ) -> None:
        extra = self._make_event_extra(
            frame,
            request=request,
            result=result,
            used_fallback=True,
            effective_backend="abstain",
            fallback_reason=reason_code,
        )
        self._publish_event(
            frame,
            "planner_process_end",
            extra,
            timestamp_ns=finished_ns,
            duration_ns=finished_ns - started_ns,
            status="rejected",
            reason_code=reason_code,
        )
        self._publish_event(
            frame,
            "planner_command_abstained",
            extra,
            timestamp_ns=finished_ns,
            duration_ns=finished_ns - started_ns,
            status="rejected",
            reason_code="planner_fail_closed_abstain",
        )

    def _record_model_result(self, request: ModelRequest, result: ModelResult) -> None:
        if self._decision_recorder is None:
            return
        try:
            self._decision_recorder.record(request, result)
        except OSError as error:
            self.get_logger().error(
                f"planner decision recording failed with {error.__class__.__name__}"
            )

    def _make_command(
        self,
        frame: CameraFrame,
        decision: PlannerDecision,
    ) -> PlannerCommand:
        command = PlannerCommand()
        command.header.trace_id = frame.header.trace_id
        command.header.oracle_id = frame.header.oracle_id
        command.header.sequence_id = frame.header.sequence_id
        command.header.source_node = self.get_name()
        command.header.stage = "planner_publish"
        command.header.timestamp_ns = time.monotonic_ns()
        command.action = decision.action
        command.target = decision.target
        command.speed = float(decision.speed)
        command.confidence = float(decision.confidence)
        command.reason = decision.reason
        return command

    def _make_event_extra(
        self,
        frame: CameraFrame,
        decision: Optional[PlannerDecision] = None,
        request: Optional[ModelRequest] = None,
        result: Optional[ModelResult] = None,
        used_fallback: bool = False,
        effective_backend: Optional[str] = None,
        fallback_reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_extra: Dict[str, Any] = {
            "frame_id": int(frame.frame_id),
            "planner_backend": self._planner_backend,
            "effective_backend": effective_backend or self._active_backend,
            "used_fallback": bool(used_fallback),
            "legacy_mock_fallback_requested": bool(self._fallback_to_mock),
            "motion_mock_backend_explicit": self._planner_backend == "mock",
            "observation_ttl_ms": self._observation_ttl_ms,
            "llm_provider": self._llm_provider,
            "llm_api_style": self._llm_api_style,
            "llm_vision_mode": self._llm_vision_mode,
            "action": decision.action if decision else None,
            "target": decision.target if decision else None,
            "speed": decision.speed if decision else None,
            "confidence": decision.confidence if decision else None,
            "reason": decision.reason if decision else None,
            "executor_threads": self.executor_threads,
            "frame_qos_depth": self._frame_qos_depth,
            "frame_qos_reliability": self._frame_qos_reliability,
        }
        if request is not None:
            event_extra.update(request.public_dict())
        if result is not None:
            event_extra.update(
                {
                    "model_backend": result.backend,
                    "model_latency_ns": max(int(result.latency_ns), 0),
                    "model_error_code": result.error_code,
                    "model_response_fingerprint": result.response_fingerprint,
                    "model_replayed": bool(result.replayed),
                }
            )
            if result.provider_response_id:
                event_extra["provider_response_id"] = result.provider_response_id
        if self._llm_model:
            event_extra["llm_model"] = self._llm_model
        if fallback_reason:
            event_extra["fallback_reason"] = fallback_reason
        if extra:
            event_extra.update(extra)
        return event_extra

    def _publish_event(
        self,
        frame: CameraFrame,
        stage: str,
        extra: Dict[str, Any],
        timestamp_ns: Optional[int] = None,
        duration_ns: int = 0,
        status: str = "observed",
        reason_code: str = "",
    ) -> None:
        if not self._runtime_events_enabled:
            return
        event = RuntimeEvent()
        event.header.trace_id = frame.header.trace_id
        event.header.oracle_id = frame.header.oracle_id
        event.header.sequence_id = frame.header.sequence_id
        event.header.source_node = self.get_name()
        event.header.stage = stage
        event.header.timestamp_ns = (
            timestamp_ns if timestamp_ns is not None else time.monotonic_ns()
        )
        event.event_name = stage
        event.event_type = "planner"
        event.pid = os.getpid()
        event.tid = threading.get_native_id()
        event.host_id = self._host_id
        event.clock_id = "monotonic"
        event.duration_ns = max(int(duration_ns), 0)
        event.status = status
        event.reason_code = reason_code
        event.extra_json = json.dumps(extra, separators=(",", ":"))
        self._event_publisher.publish(event)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VlmPlannerNode()
    executor = (
        SingleThreadedExecutor()
        if node.executor_threads == 1
        else MultiThreadedExecutor(num_threads=node.executor_threads)
    )
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
