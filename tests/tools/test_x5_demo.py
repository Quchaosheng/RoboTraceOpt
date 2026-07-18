import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_x5_demo import build_demo_plan, execute_demo


class Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


class X5DemoTest(unittest.TestCase):
    def test_builds_deterministic_seven_stage_physical_plan(self) -> None:
        plan = build_demo_plan(
            Path("/tmp/demo"),
            runtime_interface="can2",
            peer_interface="can3",
            bitrate=250000,
            duration_seconds=6,
        )

        self.assertEqual(
            [stage["name"] for stage in plan],
            [
                "preflight",
                "control_capture",
                "injected_capture",
                "control_adapter",
                "injected_adapter",
                "physical_comparison",
                "report",
            ],
        )
        for stage in plan:
            self.assertIsInstance(stage["argv"], list)
            self.assertNotIn("shell", stage)
        flattened = [argument for stage in plan for argument in stage["argv"]]
        self.assertIn("physical", flattened)
        self.assertIn("socketcan_physical", flattened)
        self.assertIn("can2", flattened)
        self.assertIn("can3", flattened)
        self.assertIn("250000", flattened)
        self.assertNotEqual(plan[1]["output_dir"], plan[2]["output_dir"])

    def test_failure_is_retained_and_later_stages_are_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "demo"
            plan = build_demo_plan(
                output_dir,
                runtime_interface="can0",
                peer_interface="can1",
                bitrate=500000,
                duration_seconds=4,
            )
            calls: list[list[str]] = []

            def runner(argv, **kwargs):
                calls.append(argv)
                return Completed(0 if len(calls) == 1 else 7)

            summary = execute_demo(plan, output_dir, runner=runner)
            saved = json.loads(
                (output_dir / "demo_summary.json").read_text(encoding="utf-8")
            )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(len(calls), 2)
        self.assertEqual(saved["stages"][0]["status"], "completed")
        self.assertEqual(saved["stages"][1]["status"], "failed")
        self.assertTrue(
            all(stage["status"] == "pending" for stage in saved["stages"][2:])
        )
        self.assertTrue(saved["development_only"])
        self.assertFalse(saved["formal_evidence"])

    def test_report_stage_observes_completed_demo_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "demo"
            plan = build_demo_plan(
                output_dir,
                runtime_interface="can0",
                peer_interface="can1",
                bitrate=500000,
                duration_seconds=4,
            )
            observed_status = []

            def runner(argv, **kwargs):
                if any(
                    argument.endswith("generate_experiment_report.py")
                    for argument in argv
                ):
                    observed_status.append(
                        json.loads(
                            (output_dir / "demo_summary.json").read_text(
                                encoding="utf-8"
                            )
                        )["status"]
                    )
                return Completed(0)

            summary = execute_demo(plan, output_dir, runner=runner)

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(observed_status, ["completed"])


if __name__ == "__main__":
    unittest.main()
