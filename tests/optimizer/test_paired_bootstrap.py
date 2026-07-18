import copy
import unittest

from optimizer.experiments.campaign_schedule import build_repeated_schedule
from optimizer.validation.paired_bootstrap import evaluate_repeated_candidates


def schedule():
    return build_repeated_schedule(
        {
            "schema_version": "optimization-execution-schedule/v1",
            "cause_id": "executor_queueing",
            "action_id": "executor_threads",
            "baseline_config": {"executor_threads": 1},
            "strategy": "guided",
            "seed": 7,
            "budget": 2,
            "trials": [
                {
                    "trial_index": 1,
                    "status": "baseline_duplicate",
                    "candidate_config": {"executor_threads": 1},
                },
                {
                    "trial_index": 2,
                    "status": "scheduled",
                    "candidate_config": {"executor_threads": 2},
                },
            ],
        },
        repetitions=5,
        seed=17,
        campaign_name="paired_test",
    )


def records(
    candidate_values=(80.0, 88.0, 72.0, 84.0, 76.0),
    candidate_rates=(1.0, 1.0, 1.0, 1.0, 1.0),
):
    frozen = schedule()
    baseline = next(
        row for row in frozen["configurations"] if row["role"] == "baseline"
    )
    candidate = next(
        row for row in frozen["configurations"] if row["role"] == "candidate"
    )
    baseline_values = (100.0, 110.0, 90.0, 105.0, 95.0)
    result = []
    for block, (base_value, candidate_value, candidate_rate) in enumerate(
        zip(baseline_values, candidate_values, candidate_rates), start=1
    ):
        result.extend(
            [
                {
                    "block_index": block,
                    "config_id": baseline["config_id"],
                    "role": "baseline",
                    "candidate_config": baseline["candidate_config"],
                    "status": "succeeded",
                    "objective_value_ns": base_value,
                    "complete_trace_rate": 1.0,
                },
                {
                    "block_index": block,
                    "config_id": candidate["config_id"],
                    "role": "candidate",
                    "candidate_config": candidate["candidate_config"],
                    "status": "succeeded",
                    "objective_value_ns": candidate_value,
                    "complete_trace_rate": candidate_rate,
                },
            ]
        )
    return result


def evaluate(rows):
    return evaluate_repeated_candidates(
        schedule(),
        rows,
        minimum_improvement_ratio=0.10,
        minimum_complete_trace_rate_delta=0.0,
        confidence_level=0.95,
        bootstrap_resamples=1000,
        seed=17,
    )


class PairedBootstrapTest(unittest.TestCase):
    def test_accepts_stable_improvement_with_complete_evidence(self):
        result = evaluate(records())[0]

        self.assertEqual(result["schema_version"], "repeated-candidate-validation/v1")
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["reason_code"], "")
        self.assertEqual(result["planned_pair_count"], 5)
        self.assertEqual(result["successful_pair_count"], 5)
        self.assertGreaterEqual(result["improvement_ratio"]["lower"], 0.10)
        self.assertGreaterEqual(result["complete_trace_rate_delta"]["lower"], 0.0)

    def test_rejects_when_improvement_interval_crosses_threshold(self):
        result = evaluate(records((80.0, 132.0, 81.0, 115.5, 95.0)))[0]

        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["reason_code"], "improvement_uncertain")
        self.assertLess(result["improvement_ratio"]["lower"], 0.10)

    def test_rejects_when_completeness_interval_can_regress(self):
        result = evaluate(records(candidate_rates=(1.0, 0.9, 1.0, 0.9, 1.0)))[0]

        self.assertEqual(result["decision"], "reject")
        self.assertEqual(
            result["reason_code"], "complete_trace_rate_regression_uncertain"
        )
        self.assertLess(result["complete_trace_rate_delta"]["lower"], 0.0)

    def test_failed_pair_forces_incomplete_evidence_rejection(self):
        rows = records()
        candidate_id = next(
            row["config_id"]
            for row in schedule()["configurations"]
            if row["role"] == "candidate"
        )
        failed = next(
            row
            for row in rows
            if row["config_id"] == candidate_id and row["block_index"] == 3
        )
        failed.clear()
        failed.update(
            {
                "block_index": 3,
                "config_id": candidate_id,
                "role": "candidate",
                "candidate_config": {"executor_threads": 2},
                "status": "failed",
                "reason_code": "trial_failed",
            }
        )

        result = evaluate(rows)[0]

        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["reason_code"], "incomplete_repeated_evidence")
        self.assertEqual(result["successful_pair_count"], 4)
        self.assertEqual(result["failed_pair_count"], 1)

    def test_one_successful_pair_has_no_interval(self):
        rows = records()
        candidate_id = next(
            row["config_id"]
            for row in schedule()["configurations"]
            if row["role"] == "candidate"
        )
        for row in rows:
            if row["config_id"] == candidate_id and row["block_index"] > 1:
                row["status"] = "failed"
                row.pop("objective_value_ns")
                row.pop("complete_trace_rate")

        result = evaluate(rows)[0]

        self.assertIsNone(result["improvement_ratio"]["lower"])
        self.assertIsNone(result["improvement_ratio"]["upper"])
        self.assertEqual(result["reason_code"], "incomplete_repeated_evidence")

    def test_fixed_seed_is_exactly_deterministic(self):
        self.assertEqual(evaluate(records()), evaluate(records()))

    def test_rejects_duplicate_records_and_invalid_objective(self):
        duplicate = records()
        duplicate.append(copy.deepcopy(duplicate[0]))
        with self.assertRaisesRegex(ValueError, "duplicate repeated trial record"):
            evaluate(duplicate)

        invalid = records()
        invalid[0]["objective_value_ns"] = 0
        with self.assertRaisesRegex(ValueError, "objective"):
            evaluate(invalid)


if __name__ == "__main__":
    unittest.main()
