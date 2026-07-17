import unittest

from optimizer.validation.candidate_validator import validate_candidate, validate_reports


def objective(value: float, rate: float = 1.0, formal: bool = True):
    return {
        "schema_version": "runtime-objective/v1",
        "metric": "request_response_elapsed_ns",
        "quantile": "p95",
        "objective_value_ns": value,
        "complete_trace_rate": rate,
        "formal_optimization_allowed": formal,
    }


class CandidateValidatorTest(unittest.TestCase):
    def test_accepts_improvement_without_coverage_regression(self) -> None:
        result = validate_candidate(objective(100), objective(80), minimum_improvement_ratio=0.1)
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["improvement_ratio"], 0.2)
        self.assertFalse(result["rollback_required"])

    def test_rejects_latency_or_coverage_regression(self) -> None:
        latency = validate_candidate(objective(100), objective(95), minimum_improvement_ratio=0.1)
        self.assertEqual(latency["reason_code"], "insufficient_improvement")
        coverage = validate_candidate(objective(100, 1.0), objective(70, 0.8), minimum_improvement_ratio=0.1)
        self.assertEqual(coverage["reason_code"], "complete_trace_rate_regression")
        self.assertTrue(coverage["rollback_required"])

    def test_formal_validation_rejects_development_evidence(self) -> None:
        result = validate_candidate(objective(100, formal=False), objective(70, formal=False), formal=True)
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["reason_code"], "formal_evidence_required")

    def test_composes_reports_into_auditable_validation(self) -> None:
        baseline_report = {
            "schema_version": "evidence/v1",
            "development_only": True,
            "formal_inference_allowed": False,
            "complete_trace_rate": 1.0,
            "metrics_ns": {"latency": {"p95": 100.0}},
        }
        candidate_report = {
            **baseline_report,
            "metrics_ns": {"latency": {"p95": 70.0}},
        }
        result = validate_reports(
            baseline_report,
            candidate_report,
            metric="latency",
            quantile="p95",
            minimum_improvement_ratio=0.1,
        )
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["baseline_objective"]["objective_value_ns"], 100.0)
        self.assertEqual(result["candidate_objective"]["objective_value_ns"], 70.0)


if __name__ == "__main__":
    unittest.main()
