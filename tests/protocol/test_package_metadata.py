import xml.etree.ElementTree as ET
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MAINTAINER = "Quchaosheng"
EXPECTED_EMAIL = "Quchaosheng@users.noreply.github.com"


class PackageMetadataTest(unittest.TestCase):
    def test_ros_packages_have_complete_metadata(self) -> None:
        package_files = sorted((ROOT / "ros2_core/src").glob("*/package.xml"))
        self.assertEqual(len(package_files), 9)
        for package_file in package_files:
            with self.subTest(package=package_file.parent.name):
                package = ET.parse(package_file).getroot()
                maintainer = package.find("maintainer")
                license_name = package.findtext("license")
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


if __name__ == "__main__":
    unittest.main()
