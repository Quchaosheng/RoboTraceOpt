import unittest

from experiments.fault_injection.compare_f5_pressure import compare_reports


def report(variant: str, depth: int, delay_scale: int = 1) -> dict:
    return {
        "schema_version": "dds-pressure-evidence/v1",
        "condition_variant": variant,
        "measurement_semantics": "publish_to_receive_upper_bound",
        "includes_executor_wait": True,
        "paired_trace_count": 8,
        "published_trace_count": 10,
        "received_trace_count": 9,
        "received_sequence_gap_count": 1,
        "delay_ns": {
            "median": 10 * delay_scale,
            "p90": 20 * delay_scale,
            "p95": 30 * delay_scale,
            "p99": 40 * delay_scale,
        },
        "qos": {
            "input_rate_hz": 100,
            "payload_bytes": 262144,
            "reliability": "reliable",
            "history": "keep_last",
            "durability": "volatile",
            "publisher_depth": depth,
            "subscriber_depth": depth,
        },
    }


class F5PressureComparisonTest(unittest.TestCase):
    def test_compares_delivery_and_latency_without_formal_inference(self) -> None:
        comparison = compare_reports(
            report("injected", 1, delay_scale=3),
            report("control", 10),
        )

        self.assertTrue(comparison["development_only"])
        self.assertFalse(comparison["formal_inference_allowed"])
        self.assertEqual(comparison["sample_counts"], {"injected": 8, "control": 8})
        self.assertEqual(comparison["metrics_ns"]["median"]["ratio"], 3.0)
        self.assertEqual(comparison["pairing_rate_delta"], 0.0)
        self.assertEqual(comparison["sequence_gap_delta"], 0)
        self.assertEqual(
            comparison["depths"],
            {
                "injected": {"publisher": 1, "subscriber": 1},
                "control": {"publisher": 10, "subscriber": 10},
            },
        )

    def test_rejects_a_non_depth_profile_difference(self) -> None:
        control = report("control", 10)
        control["qos"]["payload_bytes"] = 1024

        with self.assertRaisesRegex(ValueError, "payload_bytes"):
            compare_reports(report("injected", 1), control)

    def test_rejects_reversed_variants(self) -> None:
        with self.assertRaisesRegex(ValueError, "injected"):
            compare_reports(report("control", 10), report("control", 10))


if __name__ == "__main__":
    unittest.main()
