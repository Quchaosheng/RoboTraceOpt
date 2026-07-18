import unittest

from experiments.fault_injection.compare_f1_compute_delay import compare_reports


METRICS = (
    "planner_processing_elapsed_ns",
    "camera_to_planner_publish_upper_bound_ns",
)


def report(variant: str, *, complete: int = 8) -> dict:
    multiplier = 100 if variant == "injected" else 1
    return {
        "schema_version": "application-compute-delay-evidence/v1",
        "measurement_semantics": "runtime_event_elapsed_interval",
        "formal_cpu_time_measurement": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "status": "valid",
        "observed_trace_count": 10,
        "complete_trace_count": complete,
        "profile": {
            "git_commit": "a" * 40,
            "workload": "w1",
            "host_id": "host-a",
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
            "planner_delay_mode": "busy_compute",
            "planner_delay_ms": 100 if variant == "injected" else 0,
        },
        "metrics_ns": {
            metric: {
                "median": 1_000_000 * multiplier,
                "p90": 2_000_000 * multiplier,
                "p95": 3_000_000 * multiplier,
                "p99": 4_000_000 * multiplier,
            }
            for metric in METRICS
        },
    }


class F1ComputeDelayComparisonTest(unittest.TestCase):
    def test_compares_only_matched_injected_and_control_reports(self) -> None:
        comparison = compare_reports(report("injected"), report("control", complete=10))

        self.assertEqual(comparison["schema_version"], "f1-compute-delay-comparison/v1")
        self.assertEqual(comparison["sample_counts"], {"injected": 8, "control": 10})
        self.assertEqual(
            comparison["complete_trace_rates"],
            {"injected": 0.8, "control": 1.0},
        )
        self.assertEqual(
            comparison["metrics_ns"]["planner_processing_elapsed_ns"]["median"][
                "ratio"
            ],
            100.0,
        )
        self.assertTrue(comparison["development_only"])
        self.assertFalse(comparison["formal_inference_allowed"])

    def test_rejects_variant_and_profile_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected injected"):
            compare_reports(report("control"), report("control"))

        control = report("control")
        control["profile"]["git_commit"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "git_commit"):
            compare_reports(report("injected"), control)

        control = report("control")
        control["profile"]["host_id"] = "host-b"
        with self.assertRaisesRegex(ValueError, "host_id"):
            compare_reports(report("injected"), control)

        control = report("control")
        control["profile"]["input_rate_hz"] = 5
        with self.assertRaisesRegex(ValueError, "input_rate_hz"):
            compare_reports(report("injected"), control)

    def test_rejects_wrong_semantics_and_formal_cpu_claim(self) -> None:
        injected = report("injected")
        injected["measurement_semantics"] = "cpu_time"
        with self.assertRaisesRegex(ValueError, "measurement semantics"):
            compare_reports(injected, report("control"))

        injected = report("injected")
        injected["formal_cpu_time_measurement"] = True
        with self.assertRaisesRegex(ValueError, "CPU-time"):
            compare_reports(injected, report("control"))

    def test_rejects_missing_or_zero_quantiles_and_empty_samples(self) -> None:
        injected = report("injected")
        del injected["metrics_ns"][METRICS[0]]["p99"]
        with self.assertRaisesRegex(ValueError, "incomplete metric"):
            compare_reports(injected, report("control"))

        control = report("control")
        control["metrics_ns"][METRICS[0]]["median"] = 0
        with self.assertRaisesRegex(ValueError, "must be positive"):
            compare_reports(report("injected"), control)

        with self.assertRaisesRegex(ValueError, "complete_trace_count"):
            compare_reports(report("injected", complete=0), report("control"))

    def test_preserves_an_unfavorable_ratio(self) -> None:
        injected = report("injected")
        injected["metrics_ns"][METRICS[1]]["p99"] = 2_000_000

        comparison = compare_reports(injected, report("control"))

        self.assertEqual(comparison["metrics_ns"][METRICS[1]]["p99"]["ratio"], 0.5)


if __name__ == "__main__":
    unittest.main()
