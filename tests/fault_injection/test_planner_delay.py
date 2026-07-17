import sys
import unittest
from pathlib import Path


PLANNER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "ros2_core"
    / "src"
    / "vlm_planner_pkg"
    / "src"
)
sys.path.insert(0, str(PLANNER_SOURCE))

from planner_clients.delay import apply_delay


class PlannerDelayTest(unittest.TestCase):
    def test_busy_compute_does_not_call_sleep(self) -> None:
        timestamps = iter((0, 0, 50_000_000, 100_000_000))
        sleep_calls: list[float] = []

        apply_delay(
            100,
            "busy_compute",
            monotonic_ns=lambda: next(timestamps),
            sleeper=sleep_calls.append,
        )

        self.assertEqual(sleep_calls, [])

    def test_sleep_mode_uses_blocking_sleep(self) -> None:
        sleep_calls: list[float] = []

        apply_delay(100, "sleep", sleeper=sleep_calls.append)

        self.assertEqual(sleep_calls, [0.1])

    def test_rejects_unknown_delay_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "delay mode"):
            apply_delay(10, "unknown")


if __name__ == "__main__":
    unittest.main()
