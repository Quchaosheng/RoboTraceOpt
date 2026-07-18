import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ExecutorThreadRuntimeTest(unittest.TestCase):
    def test_planner_uses_separate_callback_groups_and_configurable_executor(self) -> None:
        source = (
            ROOT / "ros2_core/src/vlm_planner_pkg/src/vlm_planner_node.py"
        ).read_text(encoding="utf-8")
        for contract in (
            "MutuallyExclusiveCallbackGroup",
            "MultiThreadedExecutor",
            "SingleThreadedExecutor",
            'declare_parameter("executor_threads", 1)',
            "callback_group=self._frame_callback_group",
            "callback_group=self._contention_callback_group",
            "num_threads=node.executor_threads",
        ):
            self.assertIn(contract, source)

    def test_bringup_exposes_executor_threads_with_single_thread_default(self) -> None:
        launch = (
            ROOT / "ros2_core/src/runtime_bringup/launch/ai_runtime.launch.py"
        ).read_text(encoding="utf-8")
        declaration = launch.split(
            'DeclareLaunchArgument(\n            "executor_threads"', 1
        )[1].split("),", 1)[0]
        self.assertIn('default_value="1"', declaration)
        self.assertGreaterEqual(launch.count('"executor_threads"'), 2)
        config = (
            ROOT / "ros2_core/src/vlm_planner_pkg/config/planner.yaml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("executor_threads:", config)


if __name__ == "__main__":
    unittest.main()
