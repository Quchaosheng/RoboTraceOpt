import unittest

from optimizer.integration.closed_loop import (
    build_execution_schedule,
    evaluate_candidate,
    select_closed_loop_decision,
    validate_baseline_profile,
)


def gate(*trials):
    return {
        "schema_version": "diagnosis-optimization-gate/v1",
        "decision": "allow",
        "reason_code": "",
        "cause_id": "executor_queueing",
        "trial_plan": {
            "schema_version": "optimization-trial-plan/v1",
            "cause_id": "executor_queueing",
            "strategy": "guided",
            "seed": 7,
            "budget": len(trials),
            "trials": list(trials),
        },
    }


class ClosedLoopScheduleTest(unittest.TestCase):
    def test_validates_a_matching_baseline_profile(self) -> None:
        config = validate_baseline_profile(
            {
                "schema_version": "optimization-baseline-profile/v1",
                "cause_id": "executor_queueing",
                "baseline_config": {"executor_threads": 1},
            },
            "executor_queueing",
        )
        self.assertEqual(config, {"executor_threads": 1})

    def test_marks_baseline_duplicates_and_inapplicable_budget(self) -> None:
        result = build_execution_schedule(
            gate(
                {
                    "trial_index": 1,
                    "action_id": "executor_threads",
                    "candidate_config": {"executor_threads": 1},
                    "applicable_to_diagnosis": True,
                },
                {
                    "trial_index": 2,
                    "action_id": "executor_threads",
                    "candidate_config": {"executor_threads": 2},
                    "applicable_to_diagnosis": True,
                },
                {
                    "trial_index": 3,
                    "action_id": "frame_qos_depth",
                    "candidate_config": {"frame_qos_depth": 4},
                    "applicable_to_diagnosis": False,
                },
            ),
            {"executor_threads": 1},
        )
        self.assertEqual(
            [row["status"] for row in result["trials"]],
            ["baseline_duplicate", "scheduled", "not_applicable"],
        )

    def test_rejects_denied_gate_or_mismatched_baseline(self) -> None:
        denied = gate()
        denied["decision"] = "deny"
        with self.assertRaisesRegex(ValueError, "gate must allow"):
            build_execution_schedule(denied, {"executor_threads": 1})
        with self.assertRaisesRegex(ValueError, "baseline cause"):
            validate_baseline_profile(
                {
                    "schema_version": "optimization-baseline-profile/v1",
                    "cause_id": "dds_communication_delay",
                    "baseline_config": {"frame_qos_depth": 10},
                },
                "executor_queueing",
            )


def report(value, rate=1.0):
    return {
        "schema_version": "optimization-runtime-trial/v1",
        "development_only": True,
        "formal_inference_allowed": False,
        "complete_trace_rate": rate,
        "metrics_ns": {"callback_dispatch_upper_bound_ns": {"p95": value}},
    }


class ClosedLoopSelectionTest(unittest.TestCase):
    def test_selects_the_best_accepted_candidate(self) -> None:
        first = evaluate_candidate(
            report(100),
            report(80),
            cause_id="executor_queueing",
            trial_index=1,
            candidate_config={"executor_threads": 2},
            quantile="p95",
            minimum_improvement_ratio=0.0,
            minimum_complete_trace_rate_delta=0.0,
        )
        second = evaluate_candidate(
            report(100),
            report(70),
            cause_id="executor_queueing",
            trial_index=2,
            candidate_config={"executor_threads": 3},
            quantile="p95",
            minimum_improvement_ratio=0.0,
            minimum_complete_trace_rate_delta=0.0,
        )
        decision = select_closed_loop_decision(
            "executor_queueing", {"executor_threads": 1}, [first, second]
        )
        self.assertEqual(decision["action"], "apply_candidate")
        self.assertEqual(decision["selected_config"], {"executor_threads": 3})

    def test_restores_baseline_when_all_candidates_are_rejected(self) -> None:
        rejected = evaluate_candidate(
            report(100),
            report(120, 0.9),
            cause_id="executor_queueing",
            trial_index=1,
            candidate_config={"executor_threads": 2},
            quantile="p95",
            minimum_improvement_ratio=0.0,
            minimum_complete_trace_rate_delta=0.0,
        )
        decision = select_closed_loop_decision(
            "executor_queueing", {"executor_threads": 1}, [rejected]
        )
        self.assertEqual(decision["action"], "restore_baseline")
        self.assertEqual(decision["selected_config"], {"executor_threads": 1})

    def test_restores_baseline_when_no_candidate_is_valid(self) -> None:
        decision = select_closed_loop_decision(
            "executor_queueing",
            {"executor_threads": 1},
            [
                {
                    "trial_index": 1,
                    "status": "failed",
                    "candidate_config": {"executor_threads": 2},
                }
            ],
        )
        self.assertEqual(decision["reason_code"], "no_valid_candidate")


if __name__ == "__main__":
    unittest.main()
