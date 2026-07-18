import unittest

from experiments.fault_injection.compare_f6_physical_ack import compare_reports


def report(variant: str) -> dict:
    return {
        "schema_version": "socketcan-ack-lifecycle-evidence/v1",
        "measurement_semantics": "application_socketcan_physical_ack_lifecycle",
        "socketcan_evidence": True,
        "virtual_can_bus": False,
        "physical_can_evidence": True,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "valid_terminal_count": 3,
        "terminal_coverage": 1.0,
        "command_frame_match_coverage": 1.0,
        "responder_match_coverage": 1.0,
        "ack_frame_match_coverage": None if variant == "injected" else 1.0,
        "ack_success_rate": 0.0 if variant == "injected" else 1.0,
        "retry_exhausted_rate": 1.0 if variant == "injected" else 0.0,
        "count_distributions": {
            name: {"mean": 3.0 if variant == "injected" else 1.0}
            for name in ("attempt_count", "timeout_count", "retry_scheduled_count")
        },
        "terminal_latency_ns": {
            "ack_received": None
            if variant == "injected"
            else {"median": 5.0, "p90": 6.0, "p95": 7.0, "p99": 8.0},
            "retry_exhausted": {
                "median": 80.0,
                "p90": 82.0,
                "p95": 83.0,
                "p99": 84.0,
            }
            if variant == "injected"
            else None,
        },
        "profile": {
            "git_commit": "a" * 40,
            "workload": "w1",
            "host_id": "x5",
            "transport_profile": "physical",
            "ack_mode": "socketcan",
            "mock_mode": False,
            "can_interface": "can0",
            "responder_interface": "can1",
            "bitrate": 500000,
            "ack_can_id_offset": 128,
            "responder_delay_ms": 5,
            "responder_policy": "drop" if variant == "injected" else "echo",
            "ack_timeout_ms": 20,
            "max_retries": 2,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
            "candump_help_sha256": "b" * 64,
            "responder_script_sha256": "c" * 64,
        },
    }


class PhysicalCanAckComparisonTest(unittest.TestCase):
    def test_compares_matched_physical_conditions(self) -> None:
        comparison = compare_reports(report("injected"), report("control"))

        self.assertEqual(
            comparison["schema_version"], "f6-physical-can-ack-comparison/v1"
        )
        self.assertTrue(comparison["physical_can_evidence"])
        self.assertEqual(comparison["ack_success_rate_delta"], -1.0)

    def test_rejects_vcan_or_mismatched_interface_reports(self) -> None:
        injected = report("injected")
        control = report("control")
        injected["virtual_can_bus"] = True
        with self.assertRaises(ValueError):
            compare_reports(injected, control)

        injected = report("injected")
        injected["profile"]["responder_interface"] = "can2"
        with self.assertRaisesRegex(ValueError, "responder_interface"):
            compare_reports(injected, control)


if __name__ == "__main__":
    unittest.main()
