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
        self.assertIn("apt-get install", result.stdout)
        self.assertIn("can-utils", result.stdout)
        self.assertIn("bpftool", result.stdout)
        self.assertIn("clang", result.stdout)
        self.assertNotIn("Executing apt-get", result.stdout)


if __name__ == "__main__":
    unittest.main()
