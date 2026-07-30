import ast
import math
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLANNER_SOURCE = ROOT / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
PLANNER_CONFIG = ROOT / "ros2_core/src/vlm_planner_pkg/config/planner.yaml"
PLANNER_LAUNCH = ROOT / "ros2_core/src/vlm_planner_pkg/launch/vlm_planner.launch.py"
BRINGUP_LAUNCH = ROOT / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
CAN_SOURCE = ROOT / "ros2_core/src/can_bridge_pkg/src/can_bridge_node.cpp"
CAN_HEADER = ROOT / "ros2_core/src/can_bridge_pkg/include/can_bridge_pkg/can_bridge_node.hpp"
ACTION_MANAGER = ROOT / "ros2_core/src/robot_action_pkg/src/action_manager_node.cpp"
PLANNER_CLIENT_SOURCE = ROOT / "ros2_core/src/vlm_planner_pkg/src"
sys.path.insert(0, str(PLANNER_CLIENT_SOURCE))

interfaces = types.ModuleType("ai_robot_runtime_interfaces")
messages = types.ModuleType("ai_robot_runtime_interfaces.msg")
messages.CameraFrame = object
interfaces.msg = messages
sys.modules.setdefault("ai_robot_runtime_interfaces", interfaces)
sys.modules.setdefault("ai_robot_runtime_interfaces.msg", messages)

from planner_clients.llm_client import OpenAICompatiblePlannerClient  # noqa: E402


class LlmDecisionSafetyTest(unittest.TestCase):
    def test_rejects_nonfinite_boolean_and_out_of_range_numbers(self) -> None:
        base = {
            "action": "move_forward",
            "target": "front",
            "speed": 0.2,
            "confidence": 0.8,
            "reason": "test",
        }
        invalid_values = (
            ("speed", math.nan),
            ("speed", math.inf),
            ("speed", -math.inf),
            ("speed", True),
            ("speed", -0.01),
            ("speed", 1.01),
            ("confidence", math.nan),
            ("confidence", math.inf),
            ("confidence", False),
            ("confidence", -0.01),
            ("confidence", 1.01),
        )

        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                raw = dict(base)
                raw[field] = value
                with self.assertRaises(ValueError):
                    OpenAICompatiblePlannerClient._decision_from_json(raw)

    def test_accepts_only_finite_in_range_numbers(self) -> None:
        decision = OpenAICompatiblePlannerClient._decision_from_json(
            {
                "action": "stop",
                "target": "safety_hold",
                "speed": 0.0,
                "confidence": 1.0,
                "reason": "test",
            }
        )

        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.speed, 0.0)
        self.assertEqual(decision.confidence, 1.0)


class RuntimeFailClosedContractTest(unittest.TestCase):
    @staticmethod
    def _launch_default(source: str, argument: str) -> str:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DeclareLaunchArgument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == argument
            ):
                for keyword in node.keywords:
                    if keyword.arg == "default_value" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        return str(keyword.value.value)
        raise AssertionError(f"missing launch argument: {argument}")

    def test_motion_producing_mock_fallback_requires_explicit_opt_in(self) -> None:
        planner = PLANNER_SOURCE.read_text(encoding="utf-8")
        configure = planner.split("def _configure_backend", 1)[1].split(
            "def _plan", 1
        )[0]
        plan = planner.split("def _plan", 1)[1].split(
            "def _reject_without_model", 1
        )[0]

        self.assertIn('declare_parameter("fallback_to_mock", False)', planner)
        self.assertIn("planner_command_abstained", planner)
        self.assertEqual(configure.count('return "mock"'), 1)
        self.assertIn('if self._planner_backend == "mock":\n            return "mock"', configure)
        self.assertNotIn("fallback_to_mock", plan)
        self.assertIn('backend="abstain",', plan)
        self.assertIn("planner backend raised", plan)
        self.assertIn("abstaining", plan)
        self.assertIn("fallback_to_mock: false", PLANNER_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(
            self._launch_default(PLANNER_LAUNCH.read_text(encoding="utf-8"), "fallback_to_mock"),
            "false",
        )
        self.assertEqual(
            self._launch_default(BRINGUP_LAUNCH.read_text(encoding="utf-8"), "fallback_to_mock"),
            "false",
        )

    def test_abstention_happens_before_command_publication(self) -> None:
        planner = PLANNER_SOURCE.read_text(encoding="utf-8")
        on_frame = planner.split("def _on_camera_frame", 1)[1].split(
            "def _run_executor_contention", 1
        )[0]
        abstention = planner.split("def _publish_abstention", 1)[1].split(
            "def _record_model_result", 1
        )[0]
        publish_position = on_frame.index("_command_publisher.publish")

        self.assertIn('"planner_command_abstained"', abstention)
        self.assertIn('reason_code="planner_fail_closed_abstain"', abstention)
        self.assertNotIn("_command_publisher.publish", abstention)
        for gate in (
            "if admission_reason:",
            "if queue_reason:",
            "if output_reason:",
            "if not result.succeeded:",
            "if decision_reason:",
        ):
            self.assertLess(on_frame.index(gate), publish_position)
        self.assertGreaterEqual(on_frame.count("self._publish_abstention("), 3)

    def test_can_guard_runs_before_encoding_and_before_each_send(self) -> None:
        source = CAN_SOURCE.read_text(encoding="utf-8")
        header = CAN_HEADER.read_text(encoding="utf-8")
        on_command = source.split("void CanBridgeNode::on_planner_command", 1)[1].split(
            "void CanBridgeNode::send_attempt", 1
        )[0]
        send_attempt = source.split("void CanBridgeNode::send_attempt", 1)[1].split(
            "void CanBridgeNode::publish_probe_completion", 1
        )[0]

        self.assertLess(on_command.index("validate_command"), on_command.index("encode_command"))
        self.assertGreaterEqual(send_attempt.count("validate_command(command"), 2)
        self.assertIn("admit_request", on_command)
        self.assertIn("std::unordered_map<std::string, int64_t>", header)
        self.assertIn('"can_command_rejected"', source)
        for reason_code in (
            "can_guard_action_not_allowed",
            "can_guard_speed_not_finite",
            "can_guard_speed_out_of_range",
            "can_guard_command_expired",
            "can_guard_duplicate_request",
        ):
            self.assertIn(reason_code, source)

        bringup = BRINGUP_LAUNCH.read_text(encoding="utf-8")
        for parameter in (
            "command_ttl_ms",
            "command_max_future_skew_ms",
            "command_dedup_window_ms",
            "max_command_speed",
        ):
            self.assertEqual(self._launch_default(bringup, parameter), {
                "command_ttl_ms": "1000",
                "command_max_future_skew_ms": "100",
                "command_dedup_window_ms": "10000",
                "max_command_speed": "1.0",
            }[parameter])
            self.assertIn(f'"{parameter}": ParameterValue(', bringup)

    def test_action_manager_preserves_the_originating_ttl_timestamp(self) -> None:
        source = ACTION_MANAGER.read_text(encoding="utf-8")
        publish_result = source.split("void ActionManagerNode::publish_result_command", 1)[
            1
        ].split("void ActionManagerNode::publish_event", 1)[0]

        self.assertIn("result_command.header.timestamp_ns = command.header.timestamp_ns", publish_result)
        self.assertNotIn("result.end_timestamp_ns > 0", publish_result)


if __name__ == "__main__":
    unittest.main()
