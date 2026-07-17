"""Root-cause catalog loading and evidence-graph inference."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from diagnosis.evidence_graph.confidence import EvidenceAvailability, ScoringProfile
from diagnosis.evidence_graph.model import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)


@dataclass(frozen=True)
class MetricRule:
    metric_id: str
    node_type: NodeType
    extractor: str
    attribute: str = ""
    stages: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RootCauseRule:
    cause_id: str
    layer: str
    metrics: tuple[MetricRule, ...]
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateDiagnosis:
    cause_id: str
    layer: str
    score: float
    evidence_state: str
    support_node_ids: tuple[str, ...] = ()
    conflict_node_ids: tuple[str, ...] = ()
    missing_metrics: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosisResult:
    trace_id: str
    status: str
    evidence_state: str
    confidence: float
    completeness: float
    candidates: tuple[CandidateDiagnosis, ...]
    reason_codes: tuple[str, ...]
    scoring_profile_id: str
    calibration_manifest_sha256: str
    evidence_availability: tuple["SourceAvailability", ...]


@dataclass(frozen=True)
class SourceAvailability:
    node_type: NodeType
    state: str
    reason_code: str
    provenance: dict[str, object]


def load_root_cause_catalog(path: Path | None = None) -> tuple[RootCauseRule, ...]:
    catalog_path = path or Path(__file__).parents[1] / "rules" / "root_cause_catalog.yaml"
    record = json.loads(catalog_path.read_text(encoding="utf-8"))
    if record.get("schema_version") != "root-cause-catalog/v1":
        raise ValueError("unsupported root-cause catalog schema")
    causes = record.get("causes")
    if not isinstance(causes, list) or not causes:
        raise ValueError("root-cause catalog must contain causes")
    result = tuple(_cause_from_dict(cause) for cause in causes)
    cause_ids = [cause.cause_id for cause in result]
    if len(cause_ids) != len(set(cause_ids)):
        raise ValueError("root-cause catalog contains duplicate cause IDs")
    return result


def _cause_from_dict(record: object) -> RootCauseRule:
    if not isinstance(record, dict):
        raise ValueError("root-cause record must be an object")
    metrics = record.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("root-cause record must contain metrics")
    return RootCauseRule(
        cause_id=str(record["cause_id"]),
        layer=str(record["layer"]),
        metrics=tuple(_metric_from_dict(metric) for metric in metrics),
        conflicts_with=tuple(str(item) for item in record.get("conflicts_with", [])),
    )


def _metric_from_dict(record: object) -> MetricRule:
    if not isinstance(record, dict):
        raise ValueError("metric rule must be an object")
    try:
        node_type = NodeType(str(record["node_type"]))
    except ValueError as error:
        raise ValueError(f"unknown metric node type: {record.get('node_type')}") from error
    return MetricRule(
        metric_id=str(record["metric_id"]),
        node_type=node_type,
        extractor=str(record["extractor"]),
        attribute=str(record.get("attribute", "")),
        stages=tuple(str(item) for item in record.get("stages", [])),
        event_types=tuple(str(item) for item in record.get("event_types", [])),
    )


def infer_trace(
    graph: EvidenceGraph,
    trace_id: str,
    profile: ScoringProfile,
    availability: Mapping[NodeType, EvidenceAvailability],
    *,
    catalog: tuple[RootCauseRule, ...] | None = None,
    top_k: int = 3,
) -> DiagnosisResult:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not any(
        node.node_type == NodeType.TRACE and node.trace_id == trace_id
        for node in graph.nodes
    ):
        raise ValueError(f"unknown trace: {trace_id}")
    availability_records = tuple(
        SourceAvailability(
            node_type=node_type,
            state=value.state,
            reason_code=value.reason_code,
            provenance=dict(value.provenance or {}),
        )
        for node_type, value in sorted(availability.items(), key=lambda item: item[0].value)
    )
    validation = graph.validations.get(trace_id)
    if validation is None:
        raise ValueError(f"missing topology validation: {trace_id}")
    if validation.status == "invalid":
        return DiagnosisResult(
            trace_id=trace_id,
            status="abstained",
            evidence_state="invalid",
            confidence=0.0,
            completeness=0.0,
            candidates=(),
            reason_codes=("invalid_topology",),
            scoring_profile_id=profile.profile_id,
            calibration_manifest_sha256=profile.calibration_manifest_sha256,
            evidence_availability=availability_records,
        )

    rules = catalog or load_root_cause_catalog()
    metric_rules = {
        metric.metric_id: metric
        for cause in rules
        for metric in cause.metrics
    }
    unknown_metrics = sorted(profile.thresholds.keys() - metric_rules.keys())
    if unknown_metrics:
        raise ValueError(f"scoring profile has unknown metrics: {unknown_metrics}")
    active_causes = tuple(
        cause
        for cause in rules
        if any(metric.metric_id in profile.thresholds for metric in cause.metrics)
    )
    trace_nodes = tuple(
        node
        for node in graph.nodes
        if node.trace_id == trace_id and node.evidence_state == "observed"
    )

    candidates = [
        _score_cause(graph, trace_id, trace_nodes, cause, profile, availability)
        for cause in active_causes
    ]
    candidates = _apply_cross_cause_conflicts(
        graph, trace_id, active_causes, candidates, profile.conflict_penalty
    )
    candidates.sort(key=lambda item: (-item.score, item.cause_id))
    expected_metrics = [metric_rules[metric_id] for metric_id in profile.thresholds]
    completeness = sum(
        _availability_value(availability.get(metric.node_type))
        for metric in expected_metrics
    ) / len(expected_metrics)
    if validation.status == "partial":
        completeness *= 0.5
    has_invalid = any(
        availability.get(metric.node_type) is None
        or availability[metric.node_type].state == "invalid"
        for metric in expected_metrics
    )
    has_partial = validation.status == "partial" or any(
        availability.get(metric.node_type) is not None
        and availability[metric.node_type].state == "partial"
        for metric in expected_metrics
    )
    has_observation = any(
        candidate.support_node_ids or candidate.conflict_node_ids
        for candidate in candidates
    )
    if has_invalid:
        evidence_state = "invalid"
    elif has_partial:
        evidence_state = "partial"
    elif not has_observation:
        evidence_state = "not_observed"
    else:
        evidence_state = "valid"

    top = candidates[0].score if candidates else 0.0
    second = candidates[1].score if len(candidates) > 1 else 0.0
    margin = top - second
    if has_invalid:
        status = "abstained"
        reasons = ("invalid_evidence",)
    elif completeness < profile.minimum_completeness:
        status = "abstained"
        reasons = ("incomplete_evidence",)
    elif top < profile.minimum_score:
        status = "abstained"
        reasons = ("no_supporting_evidence",)
    elif margin < profile.minimum_margin:
        status = "abstained"
        reasons = ("ambiguous_root_cause",)
    else:
        status = "diagnosed"
        reasons = ("root_cause_ranked",)
    confidence = completeness * min(1.0, margin / top) if top > 0 else 0.0
    return DiagnosisResult(
        trace_id=trace_id,
        status=status,
        evidence_state=evidence_state,
        confidence=confidence,
        completeness=completeness,
        candidates=tuple(candidates[:top_k]),
        reason_codes=reasons,
        scoring_profile_id=profile.profile_id,
        calibration_manifest_sha256=profile.calibration_manifest_sha256,
        evidence_availability=availability_records,
    )


def _score_cause(
    graph: EvidenceGraph,
    trace_id: str,
    trace_nodes: tuple[EvidenceNode, ...],
    cause: RootCauseRule,
    profile: ScoringProfile,
    availability: Mapping[NodeType, EvidenceAvailability],
) -> CandidateDiagnosis:
    support: list[str] = []
    conflict: list[str] = []
    support_details: list[tuple[str, str, float, float, float]] = []
    conflict_details: list[tuple[str, str, float, float]] = []
    missing: list[str] = []
    invalid_source = False
    partial_source = False
    score = 0.0
    for metric in cause.metrics:
        if metric.metric_id not in profile.thresholds:
            continue
        source_state = availability.get(metric.node_type)
        if source_state is None or source_state.state != "valid":
            missing.append(metric.metric_id)
            score -= profile.missing_penalty
            invalid_source = invalid_source or (
                source_state is None or source_state.state == "invalid"
            )
            partial_source = partial_source or (
                source_state is not None and source_state.state == "partial"
            )
            continue
        observations = [
            (node, _metric_value(node, metric))
            for node in trace_nodes
            if node.node_type == metric.node_type and _matches_rule(node, metric)
        ]
        observations = [item for item in observations if item[1] is not None]
        if not observations:
            continue
        node, value = max(observations, key=lambda item: float(item[1]))
        if float(value) >= profile.thresholds[metric.metric_id]:
            support.append(node.node_id)
            support_details.append(
                (
                    node.node_id,
                    metric.metric_id,
                    float(value),
                    profile.thresholds[metric.metric_id],
                    profile.weights[metric.metric_id],
                )
            )
            score += profile.weights[metric.metric_id]
        else:
            conflict.append(node.node_id)
            conflict_details.append(
                (
                    node.node_id,
                    metric.metric_id,
                    float(value),
                    profile.thresholds[metric.metric_id],
                )
            )
            score -= profile.conflict_penalty

    if invalid_source:
        state = "invalid"
    elif partial_source or missing:
        state = "partial"
    elif support or conflict:
        state = "valid"
    else:
        state = "not_observed"
    score = max(0.0, score)
    cause_node_id = f"cause:{trace_id}:{cause.cause_id}"
    graph.add_node(
        EvidenceNode(
            cause_node_id,
            NodeType.CANDIDATE_CAUSE,
            trace_id=trace_id,
            evidence_state=state,
            attributes={"cause_id": cause.cause_id, "layer": cause.layer, "score": score},
        )
    )
    for node_id, metric_id, value, threshold, weight in support_details:
        graph.add_edge(
            EvidenceEdge(
                node_id,
                cause_node_id,
                EdgeType.SUPPORTS,
                reason_code="metric_threshold_met",
                attributes={
                    "metric_id": metric_id,
                    "observed_value": value,
                    "threshold": threshold,
                    "weight": weight,
                },
            )
        )
    for node_id, metric_id, value, threshold in conflict_details:
        graph.add_edge(
            EvidenceEdge(
                node_id,
                cause_node_id,
                EdgeType.CONTRADICTS,
                reason_code="metric_below_threshold",
                attributes={
                    "metric_id": metric_id,
                    "observed_value": value,
                    "threshold": threshold,
                    "penalty": profile.conflict_penalty,
                },
            )
        )
    for metric_id in missing:
        graph.add_edge(
            EvidenceEdge(
                f"trace:{trace_id}",
                cause_node_id,
                EdgeType.MISSING_EXPECTED,
                reason_code=f"missing_metric:{metric_id}",
            )
        )
    reasons: list[str] = []
    if support:
        reasons.append("supporting_evidence_observed")
    if conflict:
        reasons.append("conflicting_evidence_observed")
    if missing:
        reasons.append("required_evidence_missing")
    return CandidateDiagnosis(
        cause_id=cause.cause_id,
        layer=cause.layer,
        score=score,
        evidence_state=state,
        support_node_ids=tuple(dict.fromkeys(support)),
        conflict_node_ids=tuple(dict.fromkeys(conflict)),
        missing_metrics=tuple(missing),
        reason_codes=tuple(reasons),
    )


def _apply_cross_cause_conflicts(
    graph: EvidenceGraph,
    trace_id: str,
    rules: tuple[RootCauseRule, ...],
    candidates: list[CandidateDiagnosis],
    conflict_penalty: float,
) -> list[CandidateDiagnosis]:
    by_cause = {candidate.cause_id: candidate for candidate in candidates}
    updated: list[CandidateDiagnosis] = []
    for rule in rules:
        candidate = by_cause[rule.cause_id]
        conflicting_candidates = [
            by_cause[cause_id]
            for cause_id in rule.conflicts_with
            if cause_id in by_cause and by_cause[cause_id].support_node_ids
        ]
        cross_nodes = tuple(
            dict.fromkeys(
                node_id
                for other in conflicting_candidates
                for node_id in other.support_node_ids
            )
        )
        if not cross_nodes or not candidate.support_node_ids:
            updated.append(candidate)
            continue
        score = max(0.0, candidate.score - conflict_penalty * len(conflicting_candidates))
        conflict_nodes = tuple(dict.fromkeys(candidate.conflict_node_ids + cross_nodes))
        reasons = tuple(
            dict.fromkeys(candidate.reason_codes + ("alternative_system_explanation",))
        )
        candidate = replace(
            candidate,
            score=score,
            conflict_node_ids=conflict_nodes,
            reason_codes=reasons,
        )
        cause_node_id = f"cause:{trace_id}:{candidate.cause_id}"
        cause_node = next(node for node in graph.nodes if node.node_id == cause_node_id)
        graph.replace_node(
            replace(
                cause_node,
                attributes={**cause_node.attributes, "score": score},
            )
        )
        existing_edges = {
            (edge.source_id, edge.target_id, edge.edge_type) for edge in graph.edges
        }
        for node_id in cross_nodes:
            edge_key = (node_id, cause_node_id, EdgeType.CONTRADICTS)
            if edge_key not in existing_edges:
                graph.add_edge(
                    EvidenceEdge(
                        node_id,
                        cause_node_id,
                        EdgeType.CONTRADICTS,
                        reason_code="alternative_system_explanation",
                    )
                )
        updated.append(candidate)
    return updated


def _matches_rule(node: EvidenceNode, metric: MetricRule) -> bool:
    if metric.stages and node.stage not in metric.stages:
        return False
    event_type = str(node.attributes.get("event_type", ""))
    return not metric.event_types or event_type in metric.event_types


def _metric_value(node: EvidenceNode, metric: MetricRule) -> float | None:
    if metric.extractor == "window_duration_ns":
        start = node.attributes.get("start_ns")
        end = node.attributes.get("end_ns")
        if _is_number(start) and _is_number(end) and float(end) >= float(start):
            return float(end) - float(start)
        return None
    if metric.extractor == "attribute":
        source_attributes = node.attributes.get("source_attributes", {})
        value = (
            source_attributes.get(metric.attribute)
            if isinstance(source_attributes, dict)
            else None
        )
        if value is None:
            value = node.attributes.get(metric.attribute)
        return float(value) if _is_number(value) else None
    if metric.extractor == "terminal_failure":
        return 1.0
    raise ValueError(f"unsupported metric extractor: {metric.extractor}")


def _availability_value(value: EvidenceAvailability | None) -> float:
    if value is None or value.state == "invalid":
        return 0.0
    return 1.0 if value.state == "valid" else 0.5


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))
