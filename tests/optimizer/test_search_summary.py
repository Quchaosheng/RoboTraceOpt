import unittest

from optimizer.search.search_summary import summarize_trial_records


def record(strategy: str, index: int, value: float, *, rate: float = 1.0):
    return {
        "strategy": strategy,
        "trial_index": index,
        "candidate_config": {"planner_delay_ms": index},
        "objective_value_ns": value,
        "complete_trace_rate": rate,
        "valid": True,
    }


class SearchSummaryTest(unittest.TestCase):
    def test_summarizes_best_value_and_trials_to_target(self) -> None:
        summary = summarize_trial_records(
            [
                record("guided", 1, 20),
                record("guided", 2, 10),
                record("random", 1, 40),
                record("random", 2, 25),
                record("random", 3, 15),
            ],
            target_objective_ns=18,
        )
        self.assertEqual(summary["strategies"]["guided"]["best_objective_ns"], 10.0)
        self.assertEqual(summary["strategies"]["guided"]["trials_to_target"], 2)
        self.assertEqual(summary["strategies"]["random"]["trials_to_target"], 3)

    def test_retains_invalid_trials_and_minimum_coverage(self) -> None:
        invalid = record("guided", 2, 0, rate=0.0)
        invalid["valid"] = False
        summary = summarize_trial_records(
            [record("guided", 1, 20, rate=0.9), invalid],
            target_objective_ns=10,
        )
        guided = summary["strategies"]["guided"]
        self.assertEqual(guided["invalid_trial_count"], 1)
        self.assertEqual(guided["minimum_complete_trace_rate"], 0.9)
        self.assertIsNone(guided["trials_to_target"])

    def test_rejects_empty_records_or_invalid_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "records"):
            summarize_trial_records([], target_objective_ns=10)
        with self.assertRaisesRegex(ValueError, "target"):
            summarize_trial_records([record("guided", 1, 10)], target_objective_ns=0)


if __name__ == "__main__":
    unittest.main()
