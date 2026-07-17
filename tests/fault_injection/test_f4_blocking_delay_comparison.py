import copy
import unittest

from experiments.fault_injection.compare_f4_blocking_delay import compare_reports


METRICS = (
    "server_processing_elapsed_ns",
    "request_response_elapsed_ns",
    "pre_server_elapsed_ns",
    "post_server_elapsed_ns",
)


def report(variant: str) -> dict:
    injected = variant == "injected"
    metrics = {}
    for metric in METRICS:
        control_base = 0 if metric == "server_processing_elapsed_ns" else 1_000
        base = 100_000_000 if injected and metric == "server_processing_elapsed_ns" else control_base
        metrics[metric] = {
            "median": base,
            "p90": base + (100 if control_base else 0),
            "p95": base + (200 if control_base else 0),
            "p99": base + (300 if control_base else 0),
        }
    return {
        "schema_version": "service-blocking-evidence/v1",
        "measurement_semantics": "application_service_blocking_elapsed",
        "formal_syscall_attribution": False,
        "ebpf_evidence": False,
        "development_only": True,
        "formal_inference_allowed": False,
        "condition_variant": variant,
        "profile": {
            "git_commit": "a" * 40,
            "workload": "w2",
            "host_id": "host-a",
            "server_delay_ms": 100 if injected else 0,
            "request_rate_hz": 5,
            "blocking_primitive": "clock_nanosleep",
        },
        "observed_trace_count": 10,
        "complete_trace_count": 8 if injected else 10,
        "metrics_ns": metrics,
    }


class F4BlockingDelayComparisonTest(unittest.TestCase):
    def test_compares_absolute_effect_and_null_zero_control_ratio(self) -> None:
        comparison = compare_reports(report("injected"), report("control"))

        self.assertEqual(comparison["schema_version"], "f4-blocking-delay-comparison/v1")
        self.assertEqual(comparison["delay_profiles_ms"], {"injected": 100, "control": 0})
        self.assertEqual(comparison["sample_counts"], {"injected": 8, "control": 10})
        median = comparison["metrics_ns"]["server_processing_elapsed_ns"]["median"]
        self.assertEqual(median["absolute_delta"], 100_000_000)
        self.assertIsNone(median["ratio"])
        self.assertEqual(comparison["complete_trace_rate_delta"], -0.2)
        self.assertFalse(comparison["formal_inference_allowed"])

    def test_reports_ratio_when_control_is_positive(self) -> None:
        comparison = compare_reports(report("injected"), report("control"))

        median = comparison["metrics_ns"]["request_response_elapsed_ns"]["median"]
        self.assertEqual(median["ratio"], 1.0)

    def test_rejects_reversed_or_mismatched_reports(self) -> None:
        injected = report("injected")
        control = report("control")
        with self.assertRaisesRegex(ValueError, "injected"):
            compare_reports(control, injected)
        for field, value in (
            ("git_commit", "b" * 40),
            ("host_id", "host-b"),
            ("request_rate_hz", 4),
            ("blocking_primitive", "poll"),
        ):
            changed = copy.deepcopy(control)
            changed["profile"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                compare_reports(injected, changed)

    def test_rejects_formal_claims_missing_metrics_and_invalid_counts(self) -> None:
        injected = report("injected")
        control = report("control")
        injected["formal_syscall_attribution"] = True
        with self.assertRaisesRegex(ValueError, "syscall"):
            compare_reports(injected, control)
        injected = report("injected")
        injected["ebpf_evidence"] = True
        with self.assertRaisesRegex(ValueError, "eBPF"):
            compare_reports(injected, control)
        injected = report("injected")
        del injected["metrics_ns"]["pre_server_elapsed_ns"]["p95"]
        with self.assertRaisesRegex(ValueError, "pre_server_elapsed_ns"):
            compare_reports(injected, control)
        injected = report("injected")
        injected["complete_trace_count"] = 11
        with self.assertRaisesRegex(ValueError, "trace counts"):
            compare_reports(injected, control)


if __name__ == "__main__":
    unittest.main()
