import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "ros2_core" / "src"


class RuntimeEventSchemaTest(unittest.TestCase):
    def test_runtime_event_declares_cross_layer_identity_fields(self) -> None:
        schema = (
            SOURCE_ROOT
            / "ai_robot_runtime_interfaces"
            / "msg"
            / "RuntimeEvent.msg"
        ).read_text(encoding="utf-8")

        for field in (
            "uint32 pid",
            "uint32 tid",
            "string host_id",
            "string clock_id",
            "int64 duration_ns",
            "string status",
            "string reason_code",
        ):
            self.assertIn(field, schema)

    def test_cpp_emitters_use_the_shared_runtime_identity_helper(self) -> None:
        helper = (
            SOURCE_ROOT
            / "ai_robot_runtime_interfaces"
            / "include"
            / "ai_robot_runtime_interfaces"
            / "runtime_event_identity.hpp"
        )
        self.assertTrue(helper.is_file())

        emitters = (
            "camera_mock_pkg/src/camera_mock_node.cpp",
            "can_bridge_pkg/src/can_bridge_node.cpp",
            "robot_action_pkg/src/robot_action_node.cpp",
            "robot_action_pkg/src/action_manager_node.cpp",
            "service_runtime_demo/src/service_client_node.cpp",
            "service_runtime_demo/src/service_server_node.cpp",
            "minimal_runtime_demo/include/minimal_runtime_demo/common.hpp",
        )
        for relative_path in emitters:
            source = (SOURCE_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("populate_runtime_identity", source, relative_path)

    def test_identity_header_uses_rosidl_exported_include_root(self) -> None:
        cmake = (
            SOURCE_ROOT / "ai_robot_runtime_interfaces" / "CMakeLists.txt"
        ).read_text(encoding="utf-8")

        self.assertIn("DESTINATION include/${PROJECT_NAME}", cmake)

    def test_python_emitter_and_logger_cover_v2_fields(self) -> None:
        planner = (
            SOURCE_ROOT / "vlm_planner_pkg" / "src" / "vlm_planner_node.py"
        ).read_text(encoding="utf-8")
        logger = (
            SOURCE_ROOT
            / "runtime_logger_pkg"
            / "src"
            / "runtime_event_logger_node.cpp"
        ).read_text(encoding="utf-8")

        for field in (
            "pid",
            "tid",
            "host_id",
            "clock_id",
            "duration_ns",
            "status",
            "reason_code",
        ):
            self.assertIn(f"event.{field}", planner)
            self.assertIn(f"event.{field}", logger)

    def test_w3_uses_monotonic_not_epoch_time(self) -> None:
        common = (
            SOURCE_ROOT
            / "minimal_runtime_demo"
            / "include"
            / "minimal_runtime_demo"
            / "common.hpp"
        ).read_text(encoding="utf-8")

        self.assertIn("steady_clock", common)
        self.assertNotIn("system_clock", common)


if __name__ == "__main__":
    unittest.main()
