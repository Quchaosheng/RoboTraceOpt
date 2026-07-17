import json
import os
import socket
import threading
import time
from typing import Any, Dict, Optional, Tuple

import rclpy
from ai_robot_runtime_interfaces.msg import CameraFrame, PlannerCommand, RuntimeEvent
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from planner_clients.llm_client import OpenAICompatiblePlannerClient
from planner_clients.delay import apply_delay
from planner_clients.mock_client import MockPlannerClient
from planner_clients.schema import PlannerDecision


class VlmPlannerNode(Node):
    def __init__(self) -> None:
        super().__init__("vlm_planner_node")

        self._planner_backend = (
            self.declare_parameter("planner_backend", "mock").get_parameter_value().string_value
        ).strip().lower() or "mock"
        self._planner_mode = (
            self.declare_parameter("planner_mode", "mock").get_parameter_value().string_value
        )
        self._planner_delay_ms = (
            self.declare_parameter("planner_delay_ms", 50).get_parameter_value().integer_value
        )
        self._planner_delay_mode = (
            self.declare_parameter("planner_delay_mode", "sleep")
            .get_parameter_value()
            .string_value
        ).strip().lower()
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
            self.declare_parameter("frame_qos_depth", 10).get_parameter_value().integer_value
        )
        self._frame_qos_reliability = (
            self.declare_parameter("frame_qos_reliability", "reliable")
            .get_parameter_value()
            .string_value
        ).strip().lower()
        if self._frame_qos_depth <= 0:
            raise ValueError("frame_qos_depth must be positive")
        if self._frame_qos_reliability not in {"reliable", "best_effort"}:
            raise ValueError("frame_qos_reliability must be reliable or best_effort")
        self._llm_provider = (
            self.declare_parameter("llm_provider", "openai_compatible")
            .get_parameter_value()
            .string_value
        ).strip().lower()
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
            self.declare_parameter("llm_timeout_s", 3.0).get_parameter_value().double_value
        )
        self._fallback_to_mock = (
            self.declare_parameter("fallback_to_mock", True).get_parameter_value().bool_value
        )

        if self._planner_mode not in ("", "mock"):
            self.get_logger().warn(
                "planner_mode is deprecated and ignored; use planner_backend for backend selection"
            )

        self._mock_client = MockPlannerClient(
            delay_ms=int(self._planner_delay_ms), delay_mode=self._planner_delay_mode
        )
        self._host_id = socket.gethostname()
        self._llm_client: Optional[OpenAICompatiblePlannerClient] = None
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
            f"active_backend={self._active_backend}, publishing /planner/command"
        )

    def _on_camera_frame(self, frame: CameraFrame) -> None:
        self._publish_event(
            frame,
            "planner_receive",
            self._make_event_extra(frame),
        )
        self._publish_event(
            frame,
            "planner_process_start",
            self._make_event_extra(
                frame,
                extra={
                    "planner_delay_ms": int(self._planner_delay_ms),
                    "planner_delay_mode": self._planner_delay_mode,
                    "executor_contention_enabled": self._executor_contention_enabled,
                    "executor_contention_period_ms": self._executor_contention_period_ms,
                    "executor_contention_load_ms": self._executor_contention_load_ms,
                    "llm_timeout_s": float(self._llm_timeout_s),
                },
            ),
        )

        try:
            decision, used_fallback, effective_backend, fallback_reason = self._plan(frame)
        except Exception as exc:
            self.get_logger().error(f"planner backend failed without fallback: {exc}")
            return

        self._publish_event(
            frame,
            "planner_process_end",
            self._make_event_extra(
                frame,
                decision=decision,
                used_fallback=used_fallback,
                effective_backend=effective_backend,
                fallback_reason=fallback_reason,
            ),
        )

        command = self._make_command(frame, decision)
        self._command_publisher.publish(command)
        self._publish_event(
            frame,
            "planner_publish",
            self._make_event_extra(
                frame,
                decision=decision,
                used_fallback=used_fallback,
                effective_backend=effective_backend,
                fallback_reason=fallback_reason,
            ),
            timestamp_ns=int(command.header.timestamp_ns),
        )

    def _run_executor_contention(self) -> None:
        apply_delay(self._executor_contention_load_ms, "busy_compute")

    def _configure_backend(self) -> str:
        if self._planner_backend not in ("mock", "llm"):
            message = f"unsupported planner_backend={self._planner_backend}"
            if not self._fallback_to_mock:
                raise RuntimeError(message)
            self._startup_fallback_reason = message
            self.get_logger().warn(f"{message}; falling back to mock")
            return "mock"

        if self._planner_backend == "mock":
            return "mock"

        if self._llm_provider != "openai_compatible":
            message = f"unsupported llm_provider={self._llm_provider}"
            if not self._fallback_to_mock:
                raise RuntimeError(message)
            self._startup_fallback_reason = message
            self.get_logger().warn(f"{message}; falling back to mock")
            return "mock"

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
            if not self._fallback_to_mock:
                raise RuntimeError(message)
            self._startup_fallback_reason = message
            self.get_logger().warn(f"{message}; falling back to mock")
            return "mock"

        self._llm_client = OpenAICompatiblePlannerClient(
            api_base=self._llm_api_base,
            api_key=llm_api_key,
            model=self._llm_model,
            timeout_s=float(self._llm_timeout_s),
        )
        return "llm"

    def _plan(self, frame: CameraFrame) -> Tuple[PlannerDecision, bool, str, str]:
        if self._active_backend == "llm" and self._llm_client is not None:
            try:
                return self._llm_client.plan(frame), False, "llm", ""
            except Exception as exc:
                if not self._fallback_to_mock:
                    raise
                fallback_reason = exc.__class__.__name__
                self.get_logger().warn(
                    f"llm planner failed with {fallback_reason}; falling back to mock"
                )
                return self._mock_client.plan(frame), True, "mock", fallback_reason

        used_fallback = self._planner_backend != "mock"
        return (
            self._mock_client.plan(frame),
            used_fallback,
            "mock",
            self._startup_fallback_reason if used_fallback else "",
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
        used_fallback: bool = False,
        effective_backend: Optional[str] = None,
        fallback_reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        startup_fallback = self._planner_backend != "mock" and self._active_backend == "mock"
        if startup_fallback:
            used_fallback = True
            fallback_reason = fallback_reason or self._startup_fallback_reason

        event_extra: Dict[str, Any] = {
            "image_path": frame.image_path,
            "frame_id": int(frame.frame_id),
            "planner_backend": self._planner_backend,
            "effective_backend": effective_backend or self._active_backend,
            "used_fallback": bool(used_fallback),
            "llm_provider": self._llm_provider,
            "action": decision.action if decision else None,
            "target": decision.target if decision else None,
            "speed": decision.speed if decision else None,
            "confidence": decision.confidence if decision else None,
            "reason": decision.reason if decision else None,
            "executor_threads": self.executor_threads,
        }
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
        event.duration_ns = 0
        event.status = "observed"
        event.reason_code = ""
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
