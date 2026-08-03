from __future__ import annotations

import unittest

from scripts.analyze_f3_scheduler_latency import (
    exact_two_sided_sign_p,
    pair_runnable_latencies,
)


class AnalyzeF3SchedulerLatencyTest(unittest.TestCase):
    def test_pairs_first_wakeup_with_next_switch_to_target(self) -> None:
        events = [
            {"timestamp_ns": 150, "event_source": "sched_switch", "next_tid": 7},
            {"timestamp_ns": 100, "event_source": "sched_wakeup", "tid": 42},
            {"timestamp_ns": 160, "event_source": "sched_switch", "next_tid": 42},
            {"timestamp_ns": 200, "event_source": "sched_wakeup", "tid": 42},
            {"timestamp_ns": 205, "event_source": "sched_wakeup", "tid": 42},
            {"timestamp_ns": 230, "event_source": "sched_switch", "next_tid": 42},
        ]
        values, counts = pair_runnable_latencies(events, 42)
        self.assertEqual(values, [60, 30])
        self.assertEqual(counts["wakeups"], 3)
        self.assertEqual(counts["matched_wakeup_switch"], 2)
        self.assertEqual(counts["duplicate_wakeups_while_pending"], 1)

    def test_reports_unmatched_final_wakeup(self) -> None:
        values, counts = pair_runnable_latencies(
            [{"timestamp_ns": 10, "event_source": "sched_wakeup", "tid": 42}],
            42,
        )
        self.assertEqual(values, [])
        self.assertEqual(counts["unmatched_final_wakeup"], 1)

    def test_exact_sign_test_uses_run_directions(self) -> None:
        self.assertAlmostEqual(
            exact_two_sided_sign_p([1.0] + [-1.0] * 9),
            0.021484375,
        )


if __name__ == "__main__":
    unittest.main()
