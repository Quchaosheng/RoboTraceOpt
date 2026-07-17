import unittest

from experiments.fault_injection.compare_f6_mock_ack import compare_reports


def distribution(value: float) -> dict:
    return {key: value for key in ("min", "median", "p90", "p95", "p99", "max", "mean")}


def report(variant: str) -> dict:
    injected = variant == "injected"
    return {
        "schema_version": "mock-ack-lifecycle-evidence/v1",
        "measurement_semantics": "application_mock_ack_lifecycle",
        "physical_can_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "observed_trace_count": 10,
        "valid_terminal_count": 10,
        "terminal_coverage": 1.0,
        "ack_success_rate": 0.0 if injected else 1.0,
        "retry_exhausted_rate": 1.0 if injected else 0.0,
        "profile": {
            "git_commit": "a" * 40,
            "workload": "w1",
            "host_id": "host-a",
            "mock_ack_policy": "drop" if injected else "success",
            "ack_timeout_ms": 20,
            "max_retries": 2,
            "ack_mode": "mock",
            "mock_mode": True,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
        },
        "count_distributions": {
            "attempt_count": distribution(3 if injected else 1),
            "timeout_count": distribution(3 if injected else 0),
            "retry_scheduled_count": distribution(2 if injected else 0),
        },
        "terminal_latency_ns": {
            "ack_received": None if injected else distribution(5_000_000),
            "retry_exhausted": distribution(96_000_000) if injected else None,
        },
    }


class F6MockAckComparisonTest(unittest.TestCase):
    def test_compares_terminal_outcomes_without_artificial_latency_ratios(self) -> None:
        comparison = compare_reports(report("injected"), report("control"))

        self.assertEqual(comparison["ack_success_rate_delta"], -1.0)
        self.assertEqual(comparison["retry_exhausted_rate_delta"], 1.0)
        self.assertEqual(comparison["mean_count_deltas"]["attempt_count"], 2.0)
        self.assertIsNone(comparison["terminal_latency_ns"]["ack_received"])
        self.assertIsNone(comparison["terminal_latency_ns"]["retry_exhausted"])
        self.assertFalse(comparison["physical_can_evidence"])
        self.assertFalse(comparison["formal_inference_allowed"])

    def test_rejects_variant_profile_and_physical_can_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected injected"):
            compare_reports(report("control"), report("control"))
        control = report("control")
        control["profile"]["host_id"] = "host-b"
        with self.assertRaisesRegex(ValueError, "host_id"):
            compare_reports(report("injected"), control)
        injected = report("injected")
        injected["physical_can_evidence"] = True
        with self.assertRaisesRegex(ValueError, "physical CAN"):
            compare_reports(injected, report("control"))

    def test_preserves_unfavorable_rate_effect(self) -> None:
        injected = report("injected")
        injected["ack_success_rate"] = 1.0

        comparison = compare_reports(injected, report("control"))

        self.assertEqual(comparison["ack_success_rate_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
