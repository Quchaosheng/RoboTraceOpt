import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


class BootstrapX5Test(unittest.TestCase):
    @unittest.skipUnless(BASH.is_file(), "Git Bash is unavailable")
    def test_dry_run_prints_packages_without_running_apt(self) -> None:
        result = subprocess.run(
            [str(BASH), "scripts/bootstrap_x5.sh", "--dry-run"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        install_line = result.stdout.splitlines()[0]
        self.assertIn("apt-get install", install_line)
        self.assertIn("can-utils", install_line)
        self.assertIn("lttng-tools", install_line)
        self.assertIn("python3-bt2", install_line)
        self.assertNotIn("bpftool", install_line)
        self.assertNotIn("clang", install_line)
        self.assertNotIn("llvm", install_line)
        self.assertIn("ros-humble-ros2trace", result.stdout)
        self.assertNotIn("ros-humble-ros2-tracing", result.stdout)
        self.assertIn("python3-colcon-common-extensions", result.stdout)
        self.assertNotIn("Executing apt-get", result.stdout)


if __name__ == "__main__":
    unittest.main()
