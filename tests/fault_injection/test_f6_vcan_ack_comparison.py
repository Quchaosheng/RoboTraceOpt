import copy
import unittest

from experiments.fault_injection.compare_f6_vcan_ack import compare_reports


def report(variant: str) -> dict:
    injected = variant == "injected"
    return {
        "schema_version": "socketcan-ack-lifecycle-evidence/v1",
        "measurement_semantics": "application_socketcan_vcan_ack_lifecycle",
        "socketcan_evidence": True,
        "virtual_can_bus": True,
        "physical_can_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "profile": {
            "git_commit": "a" * 40,
            "workload": "w1",
            "host_id": "host-a",
            "transport_profile": "vcan",
            "ack_mode": "socketcan",
            "mock_mode": False,
            "can_interface": "vcan0",
            "ack_can_id_offset": 128,
            "responder_delay_ms": 5,
            "responder_policy": "drop" if injected else "echo",
            "ack_timeout_ms": 20,
            "max_retries": 2,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
            "candump_help_sha256": "b" * 64,
            "responder_script_sha256": "c" * 64,
        },
        "valid_terminal_count": 20,
        "terminal_coverage": 0.8 if injected else 0.9,
        "command_frame_match_coverage": 0.95 if injected else 1.0,
        "responder_match_coverage": 0.9 if injected else 1.0,
        "ack_frame_match_coverage": None if injected else 1.0,
        "ack_success_rate": 0.0 if injected else 1.0,
        "retry_exhausted_rate": 1.0 if injected else 0.0,
        "count_distributions": {
            "attempt_count": {"mean": 3.0 if injected else 1.0},
            "timeout_count": {"mean": 3.0 if injected else 0.0},
            "retry_scheduled_count": {"mean": 2.0 if injected else 0.0},
        },
        "terminal_latency_ns": {
            "ack_received": None
            if injected
            else {"median": 5.0, "p90": 6.0, "p95": 7.0, "p99": 8.0},
            "retry_exhausted": {"median": 80.0, "p90": 82.0, "p95": 83.0, "p99": 84.0}
            if injected
            else None,
        },
    }


class F6VcanAckComparisonTest(unittest.TestCase):
    def test_compares_matched_outcomes_without_cross_terminal_ratios(self) -> None:
        comparison = compare_reports(report("injected"), report("control"))

        self.assertEqual(comparison["schema_version"], "f6-vcan-ack-comparison/v1")
        self.assertEqual(comparison["ack_success_rate_delta"], -1.0)
        self.assertEqual(comparison["retry_exhausted_rate_delta"], 1.0)
        self.assertAlmostEqual(comparison["terminal_coverage_delta"], -0.1)
        self.assertAlmostEqual(comparison["command_frame_match_coverage_delta"], -0.05)
        self.assertAlmostEqual(comparison["responder_match_coverage_delta"], -0.1)
        self.assertIsNone(comparison["terminal_latency_ns"]["ack_received"])
        self.assertIsNone(comparison["terminal_latency_ns"]["retry_exhausted"])
        self.assertTrue(comparison["socketcan_evidence"])
        self.assertTrue(comparison["virtual_can_bus"])
        self.assertFalse(comparison["physical_can_evidence"])

    def test_rejects_tool_or_profile_mismatch(self) -> None:
        injected = report("injected")
        control = report("control")
        for field, value in (
            ("responder_script_sha256", "d" * 64),
            ("candump_help_sha256", "e" * 64),
            ("can_interface", "vcan1"),
            ("responder_delay_ms", 6),
        ):
            changed = copy.deepcopy(control)
            changed["profile"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                compare_reports(injected, changed)

    def test_rejects_mock_or_physical_can_reports(self) -> None:
        injected = report("injected")
        control = report("control")
        injected["profile"]["transport_profile"] = "mock"
        with self.assertRaises(ValueError):
            compare_reports(injected, control)
        injected = report("injected")
        injected["physical_can_evidence"] = True
        with self.assertRaisesRegex(ValueError, "physical"):
            compare_reports(injected, control)

    def test_rejects_empty_samples_invalid_rates_and_reversed_variants(self) -> None:
        injected = report("injected")
        control = report("control")
        injected["valid_terminal_count"] = 0
        with self.assertRaisesRegex(ValueError, "valid_terminal_count"):
            compare_reports(injected, control)
        injected = report("injected")
        injected["terminal_coverage"] = 1.1
        with self.assertRaisesRegex(ValueError, "terminal_coverage"):
            compare_reports(injected, control)
        with self.assertRaisesRegex(ValueError, "injected"):
            compare_reports(control, report("injected"))


if __name__ == "__main__":
    unittest.main()
