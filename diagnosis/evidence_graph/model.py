"""Typed nodes and edges for topology-constrained evidence graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from diagnosis.evidence_graph.topology_contract import TopologyValidation


class NodeType(str, Enum):
    TRACE = "Trace"
    STAGE_WINDOW = "StageWindow"
    ROS_CALLBACK = "RosCallback"
    DDS_COMMUNICATION = "DdsCommunication"
    SYSCALL_INTERVAL = "SyscallInterval"
    SCHEDULING_INTERVAL = "SchedulingInterval"
    CAN_COMMAND = "CanCommand"
    ACK_TERMINAL = "AckTerminal"
    CANDIDATE_CAUSE = "CandidateCause"


class EdgeType(str, Enum):
    BELONGS_TO = "belongs_to"
    PRECEDES = "precedes"
    OVERLAPS = "overlaps"
    EXECUTED_BY = "executed_by"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    MISSING_EXPECTED = "missing_expected"


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    node_type: NodeType
    trace_id: str = ""
    stage: str = ""
    evidence_state: str = "observed"
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceEdge:
    source_id: str
    target_id: str
    edge_type: EdgeType
    reason_code: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnassignedEvidence:
    event_id: str
    status: str
    reason_code: str
    source: str
    event_type: str
    provenance: dict[str, Any] = field(default_factory=dict)


class EvidenceGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}
        self._edges: list[EvidenceEdge] = []
        self._unassigned: list[UnassignedEvidence] = []
        self._validations: dict[str, TopologyValidation] = {}

    @property
    def nodes(self) -> tuple[EvidenceNode, ...]:
        return tuple(self._nodes.values())

    @property
    def edges(self) -> tuple[EvidenceEdge, ...]:
        return tuple(self._edges)

    @property
    def unassigned(self) -> tuple[UnassignedEvidence, ...]:
        return tuple(self._unassigned)

    @property
    def validations(self) -> dict[str, TopologyValidation]:
        return dict(self._validations)

    def add_node(self, node: EvidenceNode) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"duplicate evidence node: {node.node_id}")
        self._nodes[node.node_id] = node

    def replace_node(self, node: EvidenceNode) -> None:
        if node.node_id not in self._nodes:
            raise ValueError(f"unknown evidence node: {node.node_id}")
        self._nodes[node.node_id] = node

    def add_edge(self, edge: EvidenceEdge) -> None:
        missing = [
            node_id
            for node_id in (edge.source_id, edge.target_id)
            if node_id not in self._nodes
        ]
        if missing:
            raise ValueError(f"unknown evidence edge endpoint: {', '.join(missing)}")
        self._edges.append(edge)

    def add_unassigned(self, evidence: UnassignedEvidence) -> None:
        self._unassigned.append(evidence)

    def set_validation(self, trace_id: str, validation: TopologyValidation) -> None:
        self._validations[trace_id] = validation
