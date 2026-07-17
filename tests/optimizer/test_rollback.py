import unittest

from optimizer.validation.rollback import rollback_decision


def validation(decision: str, reason: str = ""):
    return {
        "schema_version": "candidate-validation/v1",
        "decision": decision,
        "reason_code": reason,
        "rollback_required": decision == "reject",
    }


class RollbackDecisionTest(unittest.TestCase):
    def test_accept_selects_candidate_configuration(self) -> None:
        result = rollback_decision(
            validation("accept"),
            cause_id="blocking_syscall_io",
            baseline_config={"server_delay_ms": 100},
            candidate_config={"server_delay_ms": 0},
        )
        self.assertEqual(result["action"], "apply_candidate")
        self.assertEqual(result["selected_config"], {"server_delay_ms": 0})

    def test_reject_restores_baseline_configuration(self) -> None:
        result = rollback_decision(
            validation("reject", "complete_trace_rate_regression"),
            cause_id="blocking_syscall_io",
            baseline_config={"server_delay_ms": 100},
            candidate_config={"server_delay_ms": 0},
        )
        self.assertEqual(result["action"], "restore_baseline")
        self.assertEqual(result["selected_config"], {"server_delay_ms": 100})
        self.assertEqual(result["reason_code"], "complete_trace_rate_regression")

    def test_rejects_unregistered_or_multi_action_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "one action"):
            rollback_decision(
                validation("accept"),
                cause_id="blocking_syscall_io",
                baseline_config={"server_delay_ms": 100, "frame_qos_depth": 10},
                candidate_config={"server_delay_ms": 0},
            )
        with self.assertRaisesRegex(ValueError, "not allowed"):
            rollback_decision(
                validation("accept"),
                cause_id="blocking_syscall_io",
                baseline_config={"server_delay_ms": 100},
                candidate_config={"frame_qos_depth": 10},
            )


if __name__ == "__main__":
    unittest.main()
