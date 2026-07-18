import ast
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class F5RuntimeContractTest(unittest.TestCase):
    def test_camera_frame_carries_transport_payload(self) -> None:
        message = (
            REPOSITORY_ROOT
            / "ros2_core/src/ai_robot_runtime_interfaces/msg/CameraFrame.msg"
        ).read_text(encoding="utf-8")

        self.assertIn("uint8[] payload", message.splitlines())

    def test_camera_and_planner_expose_frame_qos_parameters(self) -> None:
        camera = (
            REPOSITORY_ROOT / "ros2_core/src/camera_mock_pkg/src/camera_mock_node.cpp"
        ).read_text(encoding="utf-8")
        planner = (
            REPOSITORY_ROOT / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
        ).read_text(encoding="utf-8")

        for parameter in (
            "frame_payload_bytes",
            "frame_qos_depth",
            "frame_qos_reliability",
        ):
            self.assertIn(parameter, camera)
        for parameter in ("frame_qos_depth", "frame_qos_reliability"):
            self.assertIn(parameter, planner)
        self.assertIn("frame.payload", camera)
        self.assertIn("QoSProfile", planner)
        self.assertIn('"frame_qos_depth": self._frame_qos_depth', planner)
        self.assertIn('"frame_qos_reliability": self._frame_qos_reliability', planner)

    def test_bringup_preserves_existing_transport_defaults(self) -> None:
        launch = (
            REPOSITORY_ROOT
            / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
        ).read_text(encoding="utf-8")

        for name, default in (
            ("frame_payload_bytes", "0"),
            ("frame_qos_depth", "10"),
            ("frame_qos_reliability", "reliable"),
            ("ack_can_id_offset", "128"),
        ):
            self.assertIn(f'"{name}"', launch)
            declaration = next(
                node
                for node in ast.walk(ast.parse(launch))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DeclareLaunchArgument"
                and node.args
                and ast.literal_eval(node.args[0]) == name
            )
            defaults = {
                keyword.arg: ast.literal_eval(keyword.value)
                for keyword in declaration.keywords
            }
            self.assertEqual(defaults["default_value"], default)
        self.assertGreaterEqual(launch.count('"frame_qos_depth"'), 3)
        self.assertGreaterEqual(launch.count('"frame_qos_reliability"'), 3)

    def test_bringup_declares_every_launch_configuration(self) -> None:
        launch = (
            REPOSITORY_ROOT
            / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(launch)
        used = {
            ast.literal_eval(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "LaunchConfiguration"
            and node.args
        }
        declared = {
            ast.literal_eval(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DeclareLaunchArgument"
            and node.args
        }
        self.assertEqual(used - declared, set())


if __name__ == "__main__":
    unittest.main()
