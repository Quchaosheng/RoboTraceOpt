"""Evaluate association decisions against a separate, complete oracle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from diagnosis.evidence_graph.association import AssociationDecision


@dataclass(frozen=True)
class OracleEdge:
    event_id: str
    trace_id: str
    stage: str

    @property
    def should_associate(self) -> bool:
        return bool(self.trace_id)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_associations(
    decisions: Iterable[AssociationDecision], oracle_edges: Iterable[OracleEdge]
) -> dict[str, object]:
    decision_list = list(decisions)
    oracle_list = list(oracle_edges)
    decisions_by_id = {decision.event_id: decision for decision in decision_list}
    oracle_by_id = {edge.event_id: edge for edge in oracle_list}
    if len(decisions_by_id) != len(decision_list) or len(oracle_by_id) != len(
        oracle_list
    ):
        raise ValueError("decision and oracle event IDs must be unique")
    if decisions_by_id.keys() != oracle_by_id.keys():
        missing = sorted(decisions_by_id.keys() - oracle_by_id.keys())
        extra = sorted(oracle_by_id.keys() - decisions_by_id.keys())
        raise ValueError(f"oracle coverage mismatch: missing={missing}, extra={extra}")

    true_positive = 0
    false_positive = 0
    false_negative = 0
    mixed_trace_count = 0
    accepted_expected_count = 0
    for event_id, oracle in oracle_by_id.items():
        observed = decisions_by_id[event_id]
        accepted = observed.status == "accepted"
        exact = (
            accepted
            and observed.trace_id == oracle.trace_id
            and observed.stage == oracle.stage
        )
        if oracle.should_associate:
            if accepted:
                accepted_expected_count += 1
            if exact:
                true_positive += 1
            else:
                false_negative += 1
                if accepted:
                    false_positive += 1
                    if observed.trace_id != oracle.trace_id:
                        mixed_trace_count += 1
        elif accepted:
            false_positive += 1

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "schema_version": "association-evaluation/v1",
        "evaluated_event_count": len(decision_list),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
        "mixed_trace_count": mixed_trace_count,
        "mixed_trace_rate": _ratio(mixed_trace_count, accepted_expected_count),
    }
