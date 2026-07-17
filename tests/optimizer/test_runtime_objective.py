import unittest

from optimizer.objectives.runtime_objective import runtime_objective


def report(*, value: float = 100.0, complete_rate: float = 1.0, development: bool = False):
    return {
        "schema_version": "service-blocking-evidence/v1",
        "development_only": development,
        "formal_inference_allowed": not development,
        "complete_trace_rate": complete_rate,
        "metrics_ns": {"request_response_elapsed_ns": {"p95": value}},
    }


class RuntimeObjectiveTest(unittest.TestCase):
    def test_extracts_primary_latency_and_coverage_constraint(self) -> None:
        objective = runtime_objective(
            report(value=120.0, complete_rate=0.95),
            metric="request_response_elapsed_ns",
            quantile="p95",
        )
        self.assertEqual(objective["objective_value_ns"], 120.0)
        self.assertEqual(objective["complete_trace_rate"], 0.95)
        self.assertTrue(objective["formal_optimization_allowed"])

    def test_development_report_is_labeled_non_formal(self) -> None:
        objective = runtime_objective(
            report(development=True),
            metric="request_response_elapsed_ns",
            quantile="p95",
        )
        self.assertFalse(objective["formal_optimization_allowed"])

    def test_derives_complete_rate_from_trace_counts(self) -> None:
        source = report()
        del source["complete_trace_rate"]
        source["complete_trace_count"] = 8
        source["observed_trace_count"] = 10
        objective = runtime_objective(source, metric="request_response_elapsed_ns", quantile="p95")
        self.assertEqual(objective["complete_trace_rate"], 0.8)

    def test_rejects_missing_or_invalid_measurements(self) -> None:
        broken = report()
        del broken["metrics_ns"]["request_response_elapsed_ns"]["p95"]
        with self.assertRaisesRegex(ValueError, "p95"):
            runtime_objective(broken, metric="request_response_elapsed_ns", quantile="p95")
        with self.assertRaisesRegex(ValueError, "complete_trace_rate"):
            runtime_objective(
                report(complete_rate=1.1),
                metric="request_response_elapsed_ns",
                quantile="p95",
            )


if __name__ == "__main__":
    unittest.main()
