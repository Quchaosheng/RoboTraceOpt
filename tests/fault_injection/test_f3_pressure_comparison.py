import unittest

from experiments.fault_injection.compare_f3_pressure import compare_reports


METRICS = (
    "dispatch_upper_bound_ns",
    "zero_work_callback_elapsed_ns",
    "planner_path_upper_bound_ns",
)


def report(variant: str, scale: int = 1) -> dict:
    return {
        "schema_version": "scheduling-pressure-evidence/v1",
        "condition_variant": variant,
        "measurement_semantics": "scheduling_pressure_proxy",
        "formal_scheduling_attribution": False,
        "development_only": True,
        "observed_trace_count": 10,
        "complete_trace_count": 8,
        "profile": {
            "git_commit": "a" * 40,
            "host_id": "host-a",
            "host_class": "wsl",
            "target_cpu": 31,
            "input_rate_hz": 100,
            "cpu_load_percent": 90,
            "cpu_method": "matrixprod",
            "tracing_required": True,
        },
        "metrics_ns": {
            metric: {
                "median": 10 * scale,
                "p90": 20 * scale,
                "p95": 30 * scale,
                "p99": 40 * scale,
            }
            for metric in METRICS
        },
    }


class F3PressureComparisonTest(unittest.TestCase):
    def test_compares_all_proxies_without_formal_inference(self) -> None:
        comparison = compare_reports(report("injected", 3), report("control"))

        self.assertTrue(comparison["development_only"])
        self.assertFalse(comparison["formal_inference_allowed"])
        self.assertEqual(comparison["complete_trace_rates"], {"injected": 0.8, "control": 0.8})
        for metric in METRICS:
            self.assertEqual(
                comparison["metrics_ns"][metric]["median"]["ratio"], 3.0
            )

    def test_rejects_a_non_matched_target_cpu(self) -> None:
        control = report("control")
        control["profile"]["target_cpu"] = 30

        with self.assertRaisesRegex(ValueError, "target_cpu"):
            compare_reports(report("injected"), control)

    def test_rejects_reversed_variants(self) -> None:
        with self.assertRaisesRegex(ValueError, "injected"):
            compare_reports(report("control"), report("control"))


if __name__ == "__main__":
    unittest.main()
