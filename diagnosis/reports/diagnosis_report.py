"""Serialize diagnosis results with evidence provenance."""

from __future__ import annotations

from typing import Any

from diagnosis.evidence_graph.inference import CandidateDiagnosis, DiagnosisResult
from diagnosis.evidence_graph.model import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
)


def build_diagnosis_report(
    result: DiagnosisResult, graph: EvidenceGraph
) -> dict[str, Any]:
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    candidates = [
        _candidate_record(result.trace_id, candidate, nodes_by_id, graph.edges)
        for candidate in result.candidates
    ]
    ranked = [candidate.cause_id for candidate in result.candidates]
    diagnosed = result.status == "diagnosed"
    return {
        "schema_version": "diagnosis-report/v1",
        "trace_id": result.trace_id,
        "status": result.status,
        "evidence_state": result.evidence_state,
        "confidence": result.confidence,
        "confidence_method": "score_margin_x_completeness_v1",
        "completeness": result.completeness,
        "scoring_profile_id": result.scoring_profile_id,
        "calibration_manifest_sha256": result.calibration_manifest_sha256,
        "evidence_availability": [
            {
                "node_type": item.node_type.value,
                "state": item.state,
                "reason_code": item.reason_code,
                "provenance": dict(item.provenance),
            }
            for item in result.evidence_availability
        ],
        "reason_codes": list(result.reason_codes),
        "top_1": ranked[0] if diagnosed and ranked else None,
        "top_k": ranked if diagnosed else [],
        "candidates": candidates,
    }


def _candidate_record(
    trace_id: str,
    candidate: CandidateDiagnosis,
    nodes_by_id: dict[str, EvidenceNode],
    edges: tuple[EvidenceEdge, ...],
) -> dict[str, Any]:
    cause_node_id = f"cause:{trace_id}:{candidate.cause_id}"
    candidate_edges = [edge for edge in edges if edge.target_id == cause_node_id]
    return {
        "cause_id": candidate.cause_id,
        "layer": candidate.layer,
        "score": candidate.score,
        "evidence_state": candidate.evidence_state,
        "reason_codes": list(candidate.reason_codes),
        "supporting_evidence": [
            _evidence_record(nodes_by_id[edge.source_id], edge)
            for edge in candidate_edges
            if edge.edge_type == EdgeType.SUPPORTS
        ],
        "conflicting_evidence": [
            _evidence_record(nodes_by_id[edge.source_id], edge)
            for edge in candidate_edges
            if edge.edge_type == EdgeType.CONTRADICTS
        ],
        "missing_evidence": list(candidate.missing_metrics),
    }


def _evidence_record(node: EvidenceNode, edge: EvidenceEdge) -> dict[str, Any]:
    record = {
        "node_id": node.node_id,
        "node_type": node.node_type.value,
        "stage": node.stage,
        "evidence_state": node.evidence_state,
        "provenance": dict(node.provenance),
        "reason_code": edge.reason_code,
    }
    record.update(edge.attributes)
    return record
