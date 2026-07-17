import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "scripts"


class TracingScriptsTest(unittest.TestCase):
    def test_overlay_build_is_pinned_and_enables_lttng(self) -> None:
        script = (SCRIPTS / "build_tracetools_overlay.sh").read_text(encoding="utf-8")

        self.assertIn("4.1.2", script)
        self.assertIn("3c159b382d2d565e26eaa91e39c9ec06a5c6fe88", script)
        self.assertIn("-DTRACETOOLS_DISABLED=OFF", script)
        self.assertNotIn("sudo", script)

    def test_capture_checks_provider_and_records_runtime_identity_context(self) -> None:
        script = (SCRIPTS / "run_ros2_tracing_smoke.sh").read_text(encoding="utf-8")

        self.assertIn("ros2 run tracetools status", script)
        self.assertIn('lttng enable-event --userspace "ros2:*"', script)
        for context_name in ("vpid", "vtid", "procname"):
            self.assertIn(f"--type={context_name}", script)
        self.assertIn("run_smoke_workload.sh", script)
        self.assertNotIn("sudo", script)

    def test_tracing_smoke_captures_clock_and_process_manifests(self) -> None:
        tracing_script = (SCRIPTS / "run_ros2_tracing_smoke.sh").read_text(
            encoding="utf-8"
        )
        workload_script = (SCRIPTS / "run_smoke_workload.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("clock_calibration", tracing_script)
        self.assertIn("PROCESS_MANIFEST_PATH", tracing_script)
        self.assertIn("PROCESS_MANIFEST_PATH", workload_script)
        self.assertIn("capture_process_manifest.py", workload_script)

    def test_process_manifest_waits_for_complete_workload_identity_set(self) -> None:
        workload_script = (SCRIPTS / "run_smoke_workload.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--minimum-processes", workload_script)
        for expected_count in (2, 4):
            self.assertIn(f"expected_processes={expected_count}", workload_script)


if __name__ == "__main__":
    unittest.main()
