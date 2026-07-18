"""Build trace subgraphs from topology-admitted association decisions."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from diagnosis.evidence_graph.association import AssociationDecision
from diagnosis.evidence_graph.model import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
    UnassignedEvidence,
)
from diagnosis.evidence_graph.stage_window import StageWindow
from diagnosis.evidence_graph.topology_contract import TopologyContract
from diagnosis.schema import NormalizedEvent


def build_evidence_graph(
    windows: Iterable[StageWindow],
    system_events: Iterable[NormalizedEvent],
    decisions: Iterable[AssociationDecision],
    contract: TopologyContract,
) -> EvidenceGraph:
    window_list = list(windows)
    event_list = list(system_events)
    decision_list = list(decisions)
    events_by_id = _unique_by_id(event_list, "event")
    decisions_by_id = _unique_by_id(decision_list, "association decision")
    if events_by_id.keys() != decisions_by_id.keys():
        missing = sorted(events_by_id.keys() - decisions_by_id.keys())
        extra = sorted(decisions_by_id.keys() - events_by_id.keys())
        raise ValueError(
            f"association decision coverage mismatch: missing={missing}, extra={extra}"
        )

    graph = EvidenceGraph()
    windows_by_trace: dict[str, list[StageWindow]] = defaultdict(list)
    windows_by_id: dict[str, StageWindow] = {}
    for stage_window in window_list:
        if stage_window.window_id in windows_by_id:
            raise ValueError(f"duplicate stage window: {stage_window.window_id}")
        windows_by_id[stage_window.window_id] = stage_window
        windows_by_trace[stage_window.trace_id].append(stage_window)

    for trace_id, trace_windows in sorted(windows_by_trace.items()):
        ordered = sorted(
            trace_windows, key=lambda item: (item.start_ns, item.window_id)
        )
        sequence_ids = {item.sequence_id for item in ordered}
        if len(sequence_ids) != 1:
            raise ValueError(
                f"inconsistent trace identity: {trace_id} has sequences {sorted(sequence_ids)}"
            )
        trace_node_id = f"trace:{trace_id}"
        graph.add_node(
            EvidenceNode(
                node_id=trace_node_id,
                node_type=NodeType.TRACE,
                trace_id=trace_id,
                attributes={"sequence_id": ordered[0].sequence_id},
            )
        )
        for stage_window in ordered:
            graph.add_node(_stage_node(stage_window))
            graph.add_edge(
                EvidenceEdge(stage_window.window_id, trace_node_id, EdgeType.BELONGS_TO)
            )
        for previous, current in zip(ordered, ordered[1:]):
            graph.add_edge(
                EvidenceEdge(previous.window_id, current.window_id, EdgeType.PRECEDES)
            )
        validation = contract.validate(item.stage for item in ordered)
        graph.set_validation(trace_id, validation)
        for missing_stage in validation.missing_expected:
            missing_node_id = f"missing:{trace_id}:{missing_stage}"
            graph.add_node(
                EvidenceNode(
                    node_id=missing_node_id,
                    node_type=NodeType.STAGE_WINDOW,
                    trace_id=trace_id,
                    stage=missing_stage,
                    evidence_state="missing",
                    attributes={"reason_code": "topology_stage_missing"},
                )
            )
            graph.add_edge(
                EvidenceEdge(
                    trace_node_id,
                    missing_node_id,
                    EdgeType.MISSING_EXPECTED,
                    reason_code="topology_stage_missing",
                )
            )
        if validation.conflicting_stages:
            reason_code = validation.reason_codes[0]
            for source_stage, target_stage in zip(
                validation.conflicting_stages, validation.conflicting_stages[1:]
            ):
                source_window = next(
                    item for item in ordered if item.stage == source_stage
                )
                target_window = next(
                    item for item in ordered if item.stage == target_stage
                )
                graph.add_edge(
                    EvidenceEdge(
                        source_window.window_id,
                        target_window.window_id,
                        EdgeType.CONTRADICTS,
                        reason_code=reason_code,
                    )
                )

    for event_id in sorted(events_by_id):
        event = events_by_id[event_id]
        decision = decisions_by_id[event_id]
        if decision.status not in {"accepted", "ambiguous", "rejected", "unmatched"}:
            raise ValueError(f"unsupported association status: {decision.status}")
        if decision.status != "accepted":
            graph.add_unassigned(
                UnassignedEvidence(
                    event_id=event.event_id,
                    status=decision.status,
                    reason_code=decision.reason_code,
                    source=event.source,
                    event_type=event.event_type,
                    provenance=dict(event.provenance),
                )
            )
            continue
        stage_window = windows_by_id.get(decision.window_id)
        if stage_window is None:
            raise ValueError(
                f"accepted decision references unknown window: {decision.window_id}"
            )
        if (decision.trace_id, decision.sequence_id, decision.stage) != (
            stage_window.trace_id,
            stage_window.sequence_id,
            stage_window.stage,
        ):
            raise ValueError(f"accepted decision target mismatch: {event.event_id}")
        evidence_node = _system_node(event, decision)
        graph.add_node(evidence_node)
        if evidence_node.node_type == NodeType.ROS_CALLBACK:
            graph.add_edge(
                EvidenceEdge(
                    source_id=stage_window.window_id,
                    target_id=evidence_node.node_id,
                    edge_type=EdgeType.EXECUTED_BY,
                    reason_code=decision.reason_code,
                )
            )
        else:
            graph.add_edge(
                EvidenceEdge(
                    source_id=evidence_node.node_id,
                    target_id=stage_window.window_id,
                    edge_type=EdgeType.OVERLAPS,
                    reason_code=decision.reason_code,
                )
            )
    return graph


def _unique_by_id(items: Iterable[object], label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        item_id = str(getattr(item, "event_id"))
        if item_id in result:
            raise ValueError(f"duplicate {label}: {item_id}")
        result[item_id] = item
    return result


def _stage_node(stage_window: StageWindow) -> EvidenceNode:
    return EvidenceNode(
        node_id=stage_window.window_id,
        node_type=NodeType.STAGE_WINDOW,
        trace_id=stage_window.trace_id,
        stage=stage_window.stage,
        attributes={
            "sequence_id": stage_window.sequence_id,
            "source_node": stage_window.source_node,
            "pid": stage_window.pid,
            "tids": stage_window.tids,
            "host_id": stage_window.host_id,
            "clock_id": stage_window.clock_id,
            "start_ns": stage_window.start_ns,
            "end_ns": stage_window.end_ns,
        },
        provenance={
            "start_event_id": stage_window.start_event_id,
            "end_event_id": stage_window.end_event_id,
        },
    )


def _system_node(event: NormalizedEvent, decision: AssociationDecision) -> EvidenceNode:
    node_type = _system_node_type(event)
    return EvidenceNode(
        node_id=f"evidence:{event.event_id}",
        node_type=node_type,
        trace_id=decision.trace_id,
        stage=decision.stage,
        attributes={
            "source_attributes": dict(event.attributes),
            "source": event.source,
            "event_type": event.event_type,
            "timestamp_ns": event.timestamp_ns,
            "pid": event.pid,
            "tid": event.tid,
            "host_id": event.host_id,
            "clock_id": event.clock_id,
        },
        provenance=dict(event.provenance),
    )


def _system_node_type(event: NormalizedEvent) -> NodeType:
    event_type = event.event_type.lower()
    source = event.source.lower()
    if source == "derived_fusion" and event_type == "ros_callback_dispatch_bound":
        return NodeType.ROS_CALLBACK
    if source == "derived_fusion" and event_type == "dds_delivery_bound":
        return NodeType.DDS_COMMUNICATION
    if source == "ros2_tracing":
        if "callback" in event_type:
            return NodeType.ROS_CALLBACK
        if any(token in event_type for token in ("dds", "rmw", "publish", "take")):
            return NodeType.DDS_COMMUNICATION
    if source == "ebpf":
        if "syscall" in event_type:
            return NodeType.SYSCALL_INTERVAL
        if any(
            token in event_type
            for token in ("sched", "wakeup", "off_cpu", "scheduling")
        ):
            return NodeType.SCHEDULING_INTERVAL
    if source in {"can", "socketcan", "can_ack"}:
        if event_type in {
            "can_ack_received",
            "can_retry_exhausted",
            "can_frame_send_failed",
        }:
            return NodeType.ACK_TERMINAL
        return NodeType.CAN_COMMAND
    raise ValueError(f"unsupported accepted evidence type: {event.event_type}")
