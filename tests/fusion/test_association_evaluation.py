import unittest

from diagnosis.evidence_graph.association import AssociationDecision
from diagnosis.evidence_graph.evaluation import OracleEdge, evaluate_associations


def decision(
    event_id: str, status: str, trace_id: str = "", stage: str = ""
) -> AssociationDecision:
    return AssociationDecision(
        event_id=event_id,
        status=status,
        reason_code="fixture",
        trace_id=trace_id,
        stage=stage,
    )


class AssociationEvaluationTest(unittest.TestCase):
    def test_computes_edge_metrics_and_mixed_trace_rate(self) -> None:
        decisions = [
            decision("correct", "accepted", "trace-a", "planner"),
            decision("missed", "unmatched"),
            decision("mixed", "accepted", "trace-x", "planner"),
            decision("background", "unmatched"),
        ]
        oracle = [
            OracleEdge("correct", "trace-a", "planner"),
            OracleEdge("missed", "trace-b", "action"),
            OracleEdge("mixed", "trace-c", "planner"),
            OracleEdge("background", "", ""),
        ]

        report = evaluate_associations(decisions, oracle)

        self.assertEqual(report["true_positive"], 1)
        self.assertEqual(report["false_positive"], 1)
        self.assertEqual(report["false_negative"], 2)
        self.assertEqual(report["precision"], 0.5)
        self.assertAlmostEqual(report["recall"], 1 / 3)
        self.assertAlmostEqual(report["f1"], 0.4)
        self.assertEqual(report["mixed_trace_count"], 1)
        self.assertEqual(report["mixed_trace_rate"], 0.5)

    def test_background_assignment_is_false_positive(self) -> None:
        report = evaluate_associations(
            [decision("background", "accepted", "trace-a", "planner")],
            [OracleEdge("background", "", "")],
        )

        self.assertEqual(report["false_positive"], 1)
        self.assertEqual(report["false_negative"], 0)
        self.assertEqual(report["precision"], 0.0)

    def test_rejects_incomplete_oracle_coverage(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_associations(
                [decision("covered", "unmatched"), decision("missing", "unmatched")],
                [OracleEdge("covered", "", "")],
            )


if __name__ == "__main__":
    unittest.main()
