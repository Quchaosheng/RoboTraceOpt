import unittest

from optimizer.integration.runtime_profiles import (
    candidate_cli_arguments,
    runtime_profile,
)


class RuntimeProfileTest(unittest.TestCase):
    def test_returns_auditable_executor_and_qos_profiles(self) -> None:
        executor = runtime_profile("executor_queueing")
        qos = runtime_profile("dds_communication_delay")
        self.assertEqual(executor["action_id"], "executor_threads")
        self.assertEqual(executor["metric"], "callback_dispatch_upper_bound_ns")
        self.assertEqual(qos["action_id"], "frame_qos_depth")
        self.assertEqual(qos["metric"], "camera_to_planner_upper_bound_ns")

    def test_builds_one_argument_for_the_registered_action(self) -> None:
        self.assertEqual(
            candidate_cli_arguments("executor_queueing", {"executor_threads": 2}),
            ["--executor-threads", "2"],
        )
        self.assertEqual(
            candidate_cli_arguments("dds_communication_delay", {"frame_qos_depth": 4}),
            ["--frame-qos-depth", "4"],
        )

    def test_rejects_unknown_or_mismatched_actions(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported runtime cause"):
            runtime_profile("scheduling_delay")
        with self.assertRaisesRegex(ValueError, "expected action"):
            candidate_cli_arguments("executor_queueing", {"frame_qos_depth": 2})


if __name__ == "__main__":
    unittest.main()
