import unittest

from optimizer.integration.diagnosis_gate import plan_from_diagnosis


def diagnosis(**overrides):
    report = {
        "schema_version": "diagnosis-report/v1",
        "trace_id": "trace-1",
        "status": "diagnosed",
        "evidence_state": "valid",
        "confidence": 0.8,
        "completeness": 1.0,
        "top_1": "application_compute_delay",
        "top_k": ["application_compute_delay"],
        "reason_codes": ["root_cause_ranked"],
    }
    report.update(overrides)
    return report


class DiagnosisOptimizationGateTest(unittest.TestCase):
    def test_allows_valid_diagnosis_and_builds_constrained_plan(self) -> None:
        result = plan_from_diagnosis(
            diagnosis(), strategy="guided", budget=3, seed=7, minimum_confidence=0.6
        )
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["cause_id"], "application_compute_delay")
        self.assertTrue(result["trial_plan"]["diagnosis_constrained"])
        self.assertEqual(len(result["trial_plan"]["trials"]), 3)

    def test_denies_abstained_or_low_confidence_diagnosis(self) -> None:
        abstained = plan_from_diagnosis(
            diagnosis(status="abstained", top_1=None, top_k=[]),
            strategy="guided",
            budget=3,
            seed=7,
            minimum_confidence=0.6,
        )
        self.assertEqual(abstained["reason_code"], "diagnosis_abstained")
        self.assertIsNone(abstained["trial_plan"])
        low = plan_from_diagnosis(
            diagnosis(confidence=0.5),
            strategy="guided",
            budget=3,
            seed=7,
            minimum_confidence=0.6,
        )
        self.assertEqual(low["reason_code"], "confidence_below_gate")

    def test_denies_partial_evidence_or_unregistered_cause(self) -> None:
        partial = plan_from_diagnosis(
            diagnosis(evidence_state="partial"),
            strategy="guided",
            budget=3,
            seed=7,
            minimum_confidence=0.6,
        )
        self.assertEqual(partial["reason_code"], "valid_evidence_required")
        unknown = plan_from_diagnosis(
            diagnosis(top_1="unknown_cause", top_k=["unknown_cause"]),
            strategy="guided",
            budget=3,
            seed=7,
            minimum_confidence=0.6,
        )
        self.assertEqual(unknown["reason_code"], "no_registered_action")

    def test_rejects_malformed_or_oracle_tainted_report(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema"):
            plan_from_diagnosis(
                {}, strategy="guided", budget=3, seed=7, minimum_confidence=0.6
            )
        with self.assertRaisesRegex(ValueError, "oracle"):
            plan_from_diagnosis(
                diagnosis(true_cause_id="application_compute_delay"),
                strategy="guided",
                budget=3,
                seed=7,
                minimum_confidence=0.6,
            )


if __name__ == "__main__":
    unittest.main()
