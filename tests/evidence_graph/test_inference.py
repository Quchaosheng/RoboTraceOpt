import unittest
import json

from diagnosis.evidence_graph.confidence import EvidenceAvailability, ScoringProfile
from diagnosis.evidence_graph.inference import infer_trace, load_root_cause_catalog
from diagnosis.evidence_graph.model import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)
from diagnosis.evidence_graph.topology_contract import TopologyValidation
from diagnosis.reports.diagnosis_report import build_diagnosis_report


def profile(
    metrics: tuple[str, ...],
    *,
    minimum_margin: float = 0.2,
    minimum_completeness: float = 1.0,
) -> ScoringProfile:
    return ScoringProfile.from_dict(
        {
            "schema_version": "diagnosis-scoring/v1",
            "profile_id": "synthetic-calibration-v1",
            "calibration_manifest_sha256": "a" * 64,
            "dataset_role": "calibration",
            "frozen_before_test": True,
            "thresholds": {metric: 100 for metric in metrics},
            "weights": {metric: 1 for metric in metrics},
            "conflict_penalty": 0.5,
            "missing_penalty": 0.25,
            "minimum_score": 0.5,
            "minimum_margin": minimum_margin,
            "minimum_completeness": minimum_completeness,
        }
    )


def graph_with_trace(validation_status: str = "valid") -> EvidenceGraph:
    graph = EvidenceGraph()
    graph.add_node(EvidenceNode("trace:trace-1", NodeType.TRACE, trace_id="trace-1"))
    graph.set_validation(
        "trace-1",
        TopologyValidation(
            status=validation_status,
            matched_path="fixture",
            reason_codes=(
                ("topology_order_violation",) if validation_status == "invalid" else ()
            ),
        ),
    )
    return graph


class RootCauseCatalogTest(unittest.TestCase):
    def test_catalog_freezes_six_planned_fault_classes(self) -> None:
        catalog = load_root_cause_catalog()

        self.assertEqual(
            {cause.cause_id for cause in catalog},
            {
                "application_compute_delay",
                "executor_queueing",
                "dds_communication_delay",
                "blocking_syscall_io",
                "scheduling_delay",
                "can_ack_failure",
            },
        )
        self.assertTrue(all(cause.metrics for cause in catalog))
        executor_rule = next(
            cause for cause in catalog if cause.cause_id == "executor_queueing"
        )
        self.assertEqual(
            [metric.metric_id for metric in executor_rule.metrics],
            ["callback_dispatch_upper_bound_ns"],
        )
        self.assertEqual(executor_rule.metrics[0].attribute, "queue_delay_ns")


class ScoringProfileTest(unittest.TestCase):
    def test_accepts_frozen_calibration_profile(self) -> None:
        profile = ScoringProfile.from_dict(
            {
                "schema_version": "diagnosis-scoring/v1",
                "profile_id": "synthetic-calibration-v1",
                "calibration_manifest_sha256": "a" * 64,
                "dataset_role": "calibration",
                "frozen_before_test": True,
                "thresholds": {"planner_compute_ns": 100},
                "weights": {"planner_compute_ns": 1.0},
                "conflict_penalty": 0.5,
                "missing_penalty": 0.25,
                "minimum_score": 1.0,
                "minimum_margin": 0.2,
                "minimum_completeness": 0.75,
            }
        )

        self.assertEqual(profile.thresholds["planner_compute_ns"], 100.0)
        self.assertEqual(profile.minimum_margin, 0.2)

    def test_rejects_test_data_or_unfrozen_profile(self) -> None:
        base = {
            "schema_version": "diagnosis-scoring/v1",
            "profile_id": "synthetic-calibration-v1",
            "calibration_manifest_sha256": "a" * 64,
            "dataset_role": "calibration",
            "frozen_before_test": True,
            "thresholds": {"metric": 1},
            "weights": {"metric": 1},
            "conflict_penalty": 0,
            "missing_penalty": 0,
            "minimum_score": 1,
            "minimum_margin": 0,
            "minimum_completeness": 1,
        }
        with self.assertRaisesRegex(ValueError, "calibration"):
            ScoringProfile.from_dict({**base, "dataset_role": "test"})
        with self.assertRaisesRegex(ValueError, "frozen"):
            ScoringProfile.from_dict({**base, "frozen_before_test": False})

    def test_rejects_threshold_weight_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "metric keys"):
            ScoringProfile.from_dict(
                {
                    "schema_version": "diagnosis-scoring/v1",
                    "profile_id": "synthetic-calibration-v1",
                    "calibration_manifest_sha256": "a" * 64,
                    "dataset_role": "calibration",
                    "frozen_before_test": True,
                    "thresholds": {"metric-a": 1},
                    "weights": {"metric-b": 1},
                    "conflict_penalty": 0,
                    "missing_penalty": 0,
                    "minimum_score": 1,
                    "minimum_margin": 0,
                    "minimum_completeness": 1,
                }
            )

    def test_rejects_nonpositive_metric_values_and_out_of_range_completeness(self) -> None:
        base = {
            "schema_version": "diagnosis-scoring/v1",
            "profile_id": "synthetic-calibration-v1",
            "calibration_manifest_sha256": "a" * 64,
            "dataset_role": "calibration",
            "frozen_before_test": True,
            "thresholds": {"metric": 1},
            "weights": {"metric": 1},
            "conflict_penalty": 0,
            "missing_penalty": 0,
            "minimum_score": 1,
            "minimum_margin": 0,
            "minimum_completeness": 1,
        }
        with self.assertRaisesRegex(ValueError, "positive"):
            ScoringProfile.from_dict({**base, "weights": {"metric": -1}})
        with self.assertRaisesRegex(ValueError, "minimum_completeness"):
            ScoringProfile.from_dict({**base, "minimum_completeness": 1.1})

    def test_requires_calibration_manifest_provenance(self) -> None:
        record = {
            "schema_version": "diagnosis-scoring/v1",
            "profile_id": "synthetic-calibration-v1",
            "calibration_manifest_sha256": "not-a-hash",
            "dataset_role": "calibration",
            "frozen_before_test": True,
            "thresholds": {"metric": 1},
            "weights": {"metric": 1},
            "conflict_penalty": 0,
            "missing_penalty": 0,
            "minimum_score": 1,
            "minimum_margin": 0,
            "minimum_completeness": 1,
        }
        with self.assertRaisesRegex(ValueError, "manifest"):
            ScoringProfile.from_dict(record)


class InferenceTest(unittest.TestCase):
    def test_diagnoses_supported_application_delay_and_materializes_audit_edge(self) -> None:
        graph = graph_with_trace()
        graph.add_node(
            EvidenceNode(
                "window:planner",
                NodeType.STAGE_WINDOW,
                trace_id="trace-1",
                stage="planner_process_start",
                attributes={"start_ns": 100, "end_ns": 300},
                provenance={"start_event_id": "a", "end_event_id": "b"},
            )
        )

        result = infer_trace(
            graph,
            "trace-1",
            profile(("planner_compute_ns",)),
            {NodeType.STAGE_WINDOW: EvidenceAvailability("valid", "runtime_complete")},
        )

        self.assertEqual(result.status, "diagnosed")
        self.assertEqual(result.candidates[0].cause_id, "application_compute_delay")
        self.assertEqual(result.candidates[0].score, 1.0)
        self.assertEqual(result.evidence_state, "valid")
        self.assertEqual(result.completeness, 1.0)
        self.assertTrue(
            any(
                edge.edge_type == EdgeType.SUPPORTS
                and edge.source_id == "window:planner"
                and edge.target_id == "cause:trace-1:application_compute_delay"
                for edge in graph.edges
            )
        )
    def test_abstains_when_top_candidates_are_not_separated(self) -> None:
        graph = graph_with_trace()
        graph.add_node(
            EvidenceNode(
                "evidence:syscall",
                NodeType.SYSCALL_INTERVAL,
                trace_id="trace-1",
                attributes={"source_attributes": {"duration_ns": 200}},
            )
        )
        graph.add_node(
            EvidenceNode(
                "evidence:schedule",
                NodeType.SCHEDULING_INTERVAL,
                trace_id="trace-1",
                attributes={"source_attributes": {"off_cpu_ns": 200}},
            )
        )

        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns", "off_cpu_ns"), minimum_margin=0.5),
            {
                NodeType.SYSCALL_INTERVAL: EvidenceAvailability("valid", "ebpf_complete"),
                NodeType.SCHEDULING_INTERVAL: EvidenceAvailability("valid", "ebpf_complete"),
            },
        )

        self.assertEqual(result.status, "abstained")
        self.assertIn("ambiguous_root_cause", result.reason_codes)

    def test_abstains_and_marks_partial_when_required_source_is_partial(self) -> None:
        graph = graph_with_trace()

        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns",), minimum_completeness=1.0),
            {NodeType.SYSCALL_INTERVAL: EvidenceAvailability("partial", "capture_truncated")},
        )

        self.assertEqual(result.status, "abstained")
        self.assertEqual(result.evidence_state, "partial")
        self.assertEqual(result.completeness, 0.5)
        self.assertIn("incomplete_evidence", result.reason_codes)
        self.assertEqual(result.candidates[0].missing_metrics, ("syscall_block_ns",))
        self.assertTrue(
            any(edge.edge_type == EdgeType.MISSING_EXPECTED for edge in graph.edges)
        )

    def test_valid_source_without_matching_event_is_not_observed(self) -> None:
        graph = graph_with_trace()

        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns",)),
            {NodeType.SYSCALL_INTERVAL: EvidenceAvailability("valid", "ebpf_complete")},
        )

        self.assertEqual(result.status, "abstained")
        self.assertEqual(result.evidence_state, "not_observed")
        self.assertIn("no_supporting_evidence", result.reason_codes)

    def test_invalid_topology_abstains_before_scoring(self) -> None:
        result = infer_trace(
            graph_with_trace("invalid"),
            "trace-1",
            profile(("planner_compute_ns",)),
            {NodeType.STAGE_WINDOW: EvidenceAvailability("valid", "runtime_complete")},
        )

        self.assertEqual(result.status, "abstained")
        self.assertEqual(result.evidence_state, "invalid")
        self.assertEqual(result.reason_codes, ("invalid_topology",))

    def test_invalid_source_marks_candidate_and_result_invalid(self) -> None:
        graph = graph_with_trace()

        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns",), minimum_completeness=0.0),
            {
                NodeType.SYSCALL_INTERVAL: EvidenceAvailability(
                    "invalid",
                    "identity_domain_not_comparable",
                    {"source_file": "process_manifest.json"},
                )
            },
        )

        self.assertEqual(result.evidence_state, "invalid")
        self.assertEqual(result.candidates[0].evidence_state, "invalid")
        self.assertEqual(result.reason_codes, ("invalid_evidence",))

    def test_partial_topology_reduces_completeness_and_forces_abstention(self) -> None:
        graph = graph_with_trace("partial")
        graph.add_node(
            EvidenceNode(
                "window:planner",
                NodeType.STAGE_WINDOW,
                trace_id="trace-1",
                stage="planner_process_start",
                attributes={"start_ns": 100, "end_ns": 300},
            )
        )

        result = infer_trace(
            graph,
            "trace-1",
            profile(("planner_compute_ns",), minimum_completeness=1.0),
            {NodeType.STAGE_WINDOW: EvidenceAvailability("valid", "runtime_partial")},
        )

        self.assertEqual(result.status, "abstained")
        self.assertEqual(result.evidence_state, "partial")
        self.assertEqual(result.completeness, 0.5)
        self.assertEqual(result.reason_codes, ("incomplete_evidence",))

    def test_system_explanation_contradicts_application_only_cause(self) -> None:
        graph = graph_with_trace()
        graph.add_node(
            EvidenceNode(
                "window:planner",
                NodeType.STAGE_WINDOW,
                trace_id="trace-1",
                stage="planner_process_start",
                attributes={"start_ns": 100, "end_ns": 300},
            )
        )
        graph.add_node(
            EvidenceNode(
                "evidence:schedule",
                NodeType.SCHEDULING_INTERVAL,
                trace_id="trace-1",
                attributes={"source_attributes": {"off_cpu_ns": 200}},
            )
        )

        result = infer_trace(
            graph,
            "trace-1",
            profile(("planner_compute_ns", "off_cpu_ns")),
            {
                NodeType.STAGE_WINDOW: EvidenceAvailability("valid", "runtime_complete"),
                NodeType.SCHEDULING_INTERVAL: EvidenceAvailability("valid", "ebpf_complete"),
            },
        )

        by_cause = {candidate.cause_id: candidate for candidate in result.candidates}
        self.assertEqual(by_cause["application_compute_delay"].score, 0.5)
        self.assertIn(
            "evidence:schedule",
            by_cause["application_compute_delay"].conflict_node_ids,
        )
        self.assertTrue(
            any(
                edge.edge_type == EdgeType.CONTRADICTS
                and edge.source_id == "evidence:schedule"
                and edge.target_id == "cause:trace-1:application_compute_delay"
                for edge in graph.edges
            )
        )
        app_node = next(
            node
            for node in graph.nodes
            if node.node_id == "cause:trace-1:application_compute_delay"
        )
        self.assertEqual(app_node.attributes["score"], 0.5)


class DiagnosisReportTest(unittest.TestCase):
    def test_serializes_ranked_causes_and_source_provenance(self) -> None:
        graph = graph_with_trace()
        graph.add_node(
            EvidenceNode(
                "evidence:syscall",
                NodeType.SYSCALL_INTERVAL,
                trace_id="trace-1",
                attributes={"source_attributes": {"duration_ns": 200}},
                provenance={"source_file": "ebpf.jsonl", "record_index": 17},
            )
        )
        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns",)),
            {
                NodeType.SYSCALL_INTERVAL: EvidenceAvailability(
                    "valid",
                    "ebpf_complete",
                    {"source_file": "ebpf_manifest.json"},
                )
            },
        )
        graph.add_node(
            EvidenceNode(
                "evidence:other-trace",
                NodeType.SYSCALL_INTERVAL,
                trace_id="trace-2",
                provenance={"source_file": "wrong.jsonl", "record_index": 1},
            )
        )
        graph.add_node(
            EvidenceNode(
                "cause:trace-2:blocking_syscall_io",
                NodeType.CANDIDATE_CAUSE,
                trace_id="trace-2",
            )
        )
        graph.add_edge(
            EvidenceEdge(
                "evidence:other-trace",
                "cause:trace-2:blocking_syscall_io",
                EdgeType.SUPPORTS,
                reason_code="metric_threshold_met",
            )
        )

        report = build_diagnosis_report(result, graph)

        self.assertEqual(report["schema_version"], "diagnosis-report/v1")
        self.assertEqual(report["top_1"], "blocking_syscall_io")
        self.assertEqual(report["top_k"], ["blocking_syscall_io"])
        self.assertEqual(report["scoring_profile_id"], "synthetic-calibration-v1")
        self.assertEqual(report["calibration_manifest_sha256"], "a" * 64)
        self.assertEqual(
            report["evidence_availability"][0]["provenance"],
            {"source_file": "ebpf_manifest.json"},
        )
        evidence = report["candidates"][0]["supporting_evidence"][0]
        self.assertEqual(len(report["candidates"][0]["supporting_evidence"]), 1)
        self.assertEqual(evidence["node_id"], "evidence:syscall")
        self.assertEqual(evidence["metric_id"], "syscall_block_ns")
        self.assertEqual(evidence["observed_value"], 200.0)
        self.assertEqual(evidence["threshold"], 100.0)
        self.assertEqual(evidence["weight"], 1.0)
        self.assertEqual(evidence["reason_code"], "metric_threshold_met")
        self.assertEqual(
            evidence["provenance"],
            {"source_file": "ebpf.jsonl", "record_index": 17},
        )
        json.dumps(report)

    def test_abstained_report_has_no_top_1_claim(self) -> None:
        graph = graph_with_trace()
        result = infer_trace(
            graph,
            "trace-1",
            profile(("syscall_block_ns",)),
            {NodeType.SYSCALL_INTERVAL: EvidenceAvailability("valid", "ebpf_complete")},
        )

        report = build_diagnosis_report(result, graph)

        self.assertEqual(report["status"], "abstained")
        self.assertIsNone(report["top_1"])


if __name__ == "__main__":
    unittest.main()
