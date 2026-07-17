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
            REPOSITORY_ROOT
            / "ros2_core/src/camera_mock_pkg/src/camera_mock_node.cpp"
        ).read_text(encoding="utf-8")
        planner = (
            REPOSITORY_ROOT
            / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
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

    def test_bringup_preserves_existing_transport_defaults(self) -> None:
        launch = (
            REPOSITORY_ROOT
            / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
        ).read_text(encoding="utf-8")

        for name, default in (
            ("frame_payload_bytes", 'default_value="0"'),
            ("frame_qos_depth", 'default_value="10"'),
            ("frame_qos_reliability", 'default_value="reliable"'),
        ):
            self.assertIn(f'"{name}"', launch)
            declaration = launch.split(
                f'DeclareLaunchArgument(\n            "{name}"', 1
            )[1].split("),", 1)[0]
            self.assertIn(default, declaration)
        self.assertGreaterEqual(launch.count('"frame_qos_depth"'), 3)
        self.assertGreaterEqual(launch.count('"frame_qos_reliability"'), 3)


if __name__ == "__main__":
    unittest.main()
