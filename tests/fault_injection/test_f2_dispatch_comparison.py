import unittest

from experiments.fault_injection.compare_f2_dispatch import compare_reports


class F2DispatchComparisonTest(unittest.TestCase):
    def test_compares_only_matched_injected_and_control_reports(self) -> None:
        injected = {
            "schema_version": "callback-dispatch-evidence/v1",
            "condition_variant": "injected",
            "measurement_semantics": "publish_to_callback_upper_bound",
            "paired_trace_count": 10,
            "published_trace_count": 12,
            "received_trace_count": 11,
            "delay_ns": {"median": 100.0, "p90": 180.0, "p95": 200.0, "p99": 240.0},
        }
        control = {
            "schema_version": "callback-dispatch-evidence/v1",
            "condition_variant": "control",
            "measurement_semantics": "publish_to_callback_upper_bound",
            "paired_trace_count": 20,
            "published_trace_count": 20,
            "received_trace_count": 20,
            "delay_ns": {"median": 20.0, "p90": 30.0, "p95": 40.0, "p99": 60.0},
        }

        comparison = compare_reports(injected, control)

        self.assertTrue(comparison["development_only"])
        self.assertFalse(comparison["formal_inference_allowed"])
        self.assertEqual(comparison["sample_counts"], {"injected": 10, "control": 20})
        self.assertEqual(comparison["metrics_ns"]["median"]["ratio"], 5.0)
        self.assertEqual(comparison["metrics_ns"]["p95"]["absolute_delta"], 160.0)
        self.assertAlmostEqual(comparison["pairing_rates"]["injected"], 10 / 13)

    def test_rejects_reversed_or_incompatible_reports(self) -> None:
        base = {
            "schema_version": "callback-dispatch-evidence/v1",
            "condition_variant": "control",
            "measurement_semantics": "publish_to_callback_upper_bound",
            "paired_trace_count": 1,
            "published_trace_count": 1,
            "received_trace_count": 1,
            "delay_ns": {"median": 1, "p90": 1, "p95": 1, "p99": 1},
        }
        with self.assertRaisesRegex(ValueError, "injected"):
            compare_reports(base, base)


if __name__ == "__main__":
    unittest.main()
