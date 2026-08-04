import subprocess
import unittest
from pathlib import Path

from tests.tools.bash_test_utils import find_working_bash


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASH = find_working_bash()


class BootstrapTest(unittest.TestCase):
    @unittest.skipUnless(BASH, "bash is unavailable")
    def test_native_x86_dry_run_selects_jazzy_installer(self) -> None:
        result = subprocess.run(
            [
                str(BASH),
                "scripts/bootstrap.sh",
                "--profile",
                "native-x86-2404",
                "--dry-run",
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bootstrap_profile=native-x86-2404", result.stdout)
        self.assertIn("install_native_x86_2404_dependencies.sh", result.stdout)
        self.assertNotIn("apt-get update", result.stdout)

    @unittest.skipUnless(BASH, "bash is unavailable")
    def test_x5_dry_run_delegates_to_board_bootstrap(self) -> None:
        result = subprocess.run(
            [
                str(BASH),
                "scripts/bootstrap.sh",
                "--profile",
                "x5",
                "--dry-run",
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bootstrap_profile=x5", result.stdout)
        self.assertIn("apt-get install", result.stdout)
        self.assertIn("ros-humble-ros-base", result.stdout)
        self.assertNotIn("Executing apt-get", result.stdout)


if __name__ == "__main__":
    unittest.main()
