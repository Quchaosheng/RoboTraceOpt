import unittest

from diagnosis.evaluation import (
    DiagnosisOracle,
    evaluate_diagnoses,
    validate_partition_isolation,
)
from diagnosis.evidence_graph.inference import CandidateDiagnosis, DiagnosisResult


def prediction(
    trace_id: str,
    *,
    status: str,
    causes: tuple[str, ...],
    confidence: float,
) -> DiagnosisResult:
    return DiagnosisResult(
        trace_id=trace_id,
        status=status,
        evidence_state="valid",
        confidence=confidence,
        completeness=1.0,
        candidates=tuple(
            CandidateDiagnosis(cause_id, "fixture", 1.0, "valid") for cause_id in causes
        ),
        reason_codes=("fixture",),
        scoring_profile_id="calibration-v1",
        calibration_manifest_sha256="a" * 64,
        evidence_availability=(),
    )


class DiagnosisEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.predictions = [
            prediction("t1", status="diagnosed", causes=("cause-a",), confidence=0.8),
            prediction(
                "t2", status="diagnosed", causes=("cause-a", "cause-b"), confidence=0.7
            ),
            prediction("t3", status="abstained", causes=(), confidence=0.2),
            prediction("t4", status="diagnosed", causes=("cause-a",), confidence=0.6),
        ]
        self.oracle = [
            DiagnosisOracle("t1", "cause-a", False, "test", "session-1"),
            DiagnosisOracle("t2", "cause-b", False, "test", "session-2"),
            DiagnosisOracle("t3", "", True, "test", "session-3"),
            DiagnosisOracle("t4", "", True, "test", "session-4"),
        ]

    def test_computes_shared_diagnosis_and_abstention_metrics(self) -> None:
        report = evaluate_diagnoses(
            self.predictions,
            self.oracle,
            mode="fused",
            expected_role="test",
            calibration_bins=2,
        )

        self.assertEqual(report["mode"], "fused")
        self.assertEqual(report["sample_count"], 4)
        self.assertEqual(report["fault_case_count"], 2)
        self.assertEqual(report["top_1_accuracy"], 0.5)
        self.assertEqual(report["top_k_recall"], 1.0)
        self.assertAlmostEqual(report["macro_f1"], 1 / 3)
        self.assertEqual(report["abstention_accuracy"], 0.75)
        self.assertEqual(
            report["confusion_matrix"],
            {
                "cause-a": {"cause-a": 1},
                "cause-b": {"cause-a": 1},
                "__abstain__": {"__abstain__": 1, "cause-a": 1},
            },
        )
        self.assertEqual(report["confidence_calibration"]["sample_count"], 2)
        self.assertAlmostEqual(report["confidence_calibration"]["brier_score"], 0.265)

    def test_rejects_incomplete_or_mixed_role_oracle(self) -> None:
        with self.assertRaisesRegex(ValueError, "coverage"):
            evaluate_diagnoses(
                self.predictions,
                self.oracle[:-1],
                mode="app_only",
                expected_role="test",
            )
        mixed = [
            *self.oracle[:-1],
            DiagnosisOracle("t4", "", True, "calibration", "session-4"),
        ]
        with self.assertRaisesRegex(ValueError, "dataset role"):
            evaluate_diagnoses(
                self.predictions,
                mixed,
                mode="app_only",
                expected_role="test",
            )

    def test_all_modes_use_same_report_schema(self) -> None:
        reports = [
            evaluate_diagnoses(
                self.predictions,
                self.oracle,
                mode=mode,
                expected_role="test",
            )
            for mode in ("app_only", "tracing_only", "ebpf_only", "fused")
        ]

        key_sets = [{*report.keys()} - {"mode"} for report in reports]
        self.assertTrue(all(keys == key_sets[0] for keys in key_sets))


class PartitionIsolationTest(unittest.TestCase):
    def test_rejects_trace_overlap_between_calibration_and_test(self) -> None:
        calibration = [
            DiagnosisOracle("same", "cause-a", False, "calibration", "cal-session")
        ]
        test = [DiagnosisOracle("same", "cause-a", False, "test", "test-session")]

        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_partition_isolation(calibration, test)

    def test_accepts_disjoint_role_correct_partitions(self) -> None:
        validate_partition_isolation(
            [DiagnosisOracle("cal-1", "cause-a", False, "calibration", "cal-session")],
            [DiagnosisOracle("test-1", "cause-a", False, "test", "test-session")],
        )

    def test_rejects_session_overlap_even_when_trace_ids_differ(self) -> None:
        calibration = [
            DiagnosisOracle("cal-1", "cause-a", False, "calibration", "same-session")
        ]
        test = [DiagnosisOracle("test-1", "cause-a", False, "test", "same-session")]

        with self.assertRaisesRegex(ValueError, "session overlap"):
            validate_partition_isolation(calibration, test)


if __name__ == "__main__":
    unittest.main()
