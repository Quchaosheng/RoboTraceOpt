import xml.etree.ElementTree as ET
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MAINTAINER = "Quchaosheng"
EXPECTED_EMAIL = "Quchaosheng@users.noreply.github.com"
EXPECTED_ROS_PACKAGES = {
    "ai_robot_runtime_interfaces",
    "camera_mock_pkg",
    "can_bridge_pkg",
    "minimal_runtime_demo",
    "robot_action_pkg",
    "robotraceopt_core",
    "runtime_bringup",
    "runtime_logger_pkg",
    "service_runtime_demo",
    "vlm_planner_cpp_pkg",
    "vlm_planner_pkg",
}


class PackageMetadataTest(unittest.TestCase):
    def test_ros_packages_have_complete_metadata(self) -> None:
        package_files = {
            package_file.parent.name: package_file
            for package_file in (ROOT / "ros2_core/src").glob("*/package.xml")
        }
        self.assertSetEqual(set(package_files), EXPECTED_ROS_PACKAGES)

        for package_name in sorted(EXPECTED_ROS_PACKAGES):
            with self.subTest(package=package_name):
                package_file = package_files[package_name]
                package = ET.parse(package_file).getroot()
                maintainer = package.find("maintainer")
                license_name = package.findtext("license")
                self.assertEqual(package.findtext("name"), package_name)
                self.assertTrue((package.findtext("version") or "").strip())
                self.assertTrue((package.findtext("description") or "").strip())
                self.assertIsNotNone(maintainer)
                self.assertEqual(maintainer.text, EXPECTED_MAINTAINER)
                self.assertEqual(maintainer.get("email"), EXPECTED_EMAIL)
                self.assertEqual(license_name, "Apache-2.0")
                self.assertNotIn(
                    "todo", package_file.read_text(encoding="utf-8").lower()
                )

    def test_python_package_metadata_matches_package_xml(self) -> None:
        setup = (ROOT / "ros2_core/src/vlm_planner_pkg/setup.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'maintainer="{EXPECTED_MAINTAINER}"', setup)
        self.assertIn(f'maintainer_email="{EXPECTED_EMAIL}"', setup)
        self.assertIn('license="Apache-2.0"', setup)
        self.assertNotIn("TODO", setup)

    def test_runtime_logger_builds_every_bringup_executable(self) -> None:
        cmake = (
            ROOT / "ros2_core/src/runtime_logger_pkg/CMakeLists.txt"
        ).read_text(encoding="utf-8")
        launch = (
            ROOT / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
        ).read_text(encoding="utf-8")
        for executable in ("runtime_event_logger_node", "latency_probe_node"):
            with self.subTest(executable=executable):
                self.assertIn(f"add_executable({executable} ", cmake)
                self.assertIn(f'executable="{executable}"', launch)


if __name__ == "__main__":
    unittest.main()
