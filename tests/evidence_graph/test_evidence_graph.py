import unittest
from dataclasses import replace

from diagnosis.evidence_graph.association import AssociationDecision
from diagnosis.evidence_graph.builder import build_evidence_graph
from diagnosis.evidence_graph.model import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)
from diagnosis.evidence_graph.stage_window import StageWindow
from diagnosis.evidence_graph.topology_contract import get_topology_contract
from diagnosis.schema import NormalizedEvent


def window(index: int, stage: str, trace_id: str = "trace-1") -> StageWindow:
    return StageWindow(
        window_id=f"window:{index}",
        trace_id=trace_id,
        sequence_id=1,
        stage=stage,
        source_node="fixture",
        pid=10,
        tids=(11,),
        host_id="host-a",
        clock_id="monotonic",
        start_ns=index * 100,
        end_ns=index * 100 + 99,
        start_event_id=f"runtime:{index}",
        end_event_id=f"runtime:{index}",
    )


def system_event(
    event_id: str,
    event_type: str = "ros2:callback_start",
    source: str = "ros2_tracing",
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source=source,
        event_type=event_type,
        timestamp_ns=250,
        clock_id="monotonic",
        trace_id="",
        sequence_id=0,
        stage="",
        pid=10,
        tid=11,
        host_id="host-a",
        attributes={},
        provenance={"source_file": "fixture.jsonl", "record_index": 1},
    )


class EvidenceGraphModelTest(unittest.TestCase):
    def test_freezes_planned_node_and_edge_types(self) -> None:
        self.assertEqual(
            {item.value for item in NodeType},
            {
                "Trace",
                "StageWindow",
                "RosCallback",
                "DdsCommunication",
                "SyscallInterval",
                "SchedulingInterval",
                "CanCommand",
                "AckTerminal",
                "CandidateCause",
            },
        )
        self.assertEqual(
            {item.value for item in EdgeType},
            {
                "belongs_to",
                "precedes",
                "overlaps",
                "executed_by",
                "supports",
                "contradicts",
                "missing_expected",
            },
        )

    def test_rejects_duplicate_nodes_and_edges_with_unknown_endpoints(self) -> None:
        graph = EvidenceGraph()
        trace = EvidenceNode("trace:1", NodeType.TRACE, trace_id="trace-1")
        graph.add_node(trace)

        with self.assertRaises(ValueError):
            graph.add_node(trace)
        with self.assertRaises(ValueError):
            graph.add_edge(
                EvidenceEdge("trace:1", "missing", EdgeType.BELONGS_TO)
            )


class EvidenceGraphBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        stages = (
            "query_sent",
            "service_receive",
            "service_process_start",
            "service_process_end",
            "service_response",
            "response_received",
        )
        self.windows = [window(index + 1, stage) for index, stage in enumerate(stages)]

    def test_only_accepted_system_evidence_enters_trace_subgraph(self) -> None:
        accepted = system_event("callback")
        background = system_event("background", "ros2:rcl_node_init")
        graph = build_evidence_graph(
            self.windows,
            [accepted, background],
            [
                AssociationDecision(
                    event_id="callback",
                    status="accepted",
                    reason_code="pid_tid_time_match",
                    source="ros2_tracing",
                    event_type="ros2:callback_start",
                    trace_id="trace-1",
                    sequence_id=1,
                    stage="service_receive",
                    window_id="window:2",
                ),
                AssociationDecision(
                    event_id="background",
                    status="unmatched",
                    reason_code="topology_metadata",
                    source="ros2_tracing",
                    event_type="ros2:rcl_node_init",
                ),
            ],
            get_topology_contract("w2"),
        )

        self.assertEqual(
            [node.node_type for node in graph.nodes].count(NodeType.TRACE), 1
        )
        self.assertEqual(
            [node.node_type for node in graph.nodes].count(NodeType.STAGE_WINDOW), 6
        )
        self.assertEqual(
            [node.node_type for node in graph.nodes].count(NodeType.ROS_CALLBACK), 1
        )
        self.assertNotIn("evidence:background", {node.node_id for node in graph.nodes})
        self.assertEqual(graph.unassigned[0].event_id, "background")
        self.assertEqual(graph.unassigned[0].status, "unmatched")
        self.assertTrue(
            any(
                edge.edge_type == EdgeType.EXECUTED_BY
                and edge.source_id == "window:2"
                and edge.target_id == "evidence:callback"
                for edge in graph.edges
            )
        )
        self.assertEqual(graph.validations["trace-1"].status, "valid")

    def test_requires_one_decision_for_every_system_event(self) -> None:
        with self.assertRaisesRegex(ValueError, "association decision coverage"):
            build_evidence_graph(
                self.windows,
                [system_event("missing")],
                [],
                get_topology_contract("w2"),
            )

    def test_maps_each_admitted_source_to_a_typed_evidence_node(self) -> None:
        cases = (
            ("callback", "ros2:callback_start", "ros2_tracing", NodeType.ROS_CALLBACK),
            (
                "dispatch-bound",
                "ros_callback_dispatch_bound",
                "derived_fusion",
                NodeType.ROS_CALLBACK,
            ),
            (
                "delivery-bound",
                "dds_delivery_bound",
                "derived_fusion",
                NodeType.DDS_COMMUNICATION,
            ),
            ("dds", "ros2:rmw_publish", "ros2_tracing", NodeType.DDS_COMMUNICATION),
            ("syscall", "syscall_interval", "ebpf", NodeType.SYSCALL_INTERVAL),
            ("schedule", "scheduling_interval", "ebpf", NodeType.SCHEDULING_INTERVAL),
            ("command", "can_command", "can_ack", NodeType.CAN_COMMAND),
            ("ack", "can_ack_received", "can_ack", NodeType.ACK_TERMINAL),
        )
        for event_id, event_type, source, expected_type in cases:
            with self.subTest(event_type=event_type):
                event = system_event(event_id, event_type, source)
                decision = AssociationDecision(
                    event_id=event_id,
                    status="accepted",
                    reason_code="fixture_match",
                    source=source,
                    event_type=event_type,
                    trace_id="trace-1",
                    sequence_id=1,
                    stage="service_receive",
                    window_id="window:2",
                )

                graph = build_evidence_graph(
                    self.windows,
                    [event],
                    [decision],
                    get_topology_contract("w2"),
                )

                node = next(
                    item for item in graph.nodes if item.node_id == f"evidence:{event_id}"
                )
                self.assertEqual(node.node_type, expected_type)

    def test_materializes_missing_stage_as_non_observed_evidence(self) -> None:
        partial_windows = [
            item for item in self.windows if item.stage != "service_process_start"
        ]

        graph = build_evidence_graph(
            partial_windows, [], [], get_topology_contract("w2")
        )

        missing = next(
            node
            for node in graph.nodes
            if node.stage == "service_process_start" and node.evidence_state == "missing"
        )
        self.assertEqual(missing.provenance, {})
        self.assertTrue(
            any(
                edge.edge_type == EdgeType.MISSING_EXPECTED
                and edge.source_id == "trace:trace-1"
                and edge.target_id == missing.node_id
                for edge in graph.edges
            )
        )

    def test_connects_conflicting_observations_with_audit_edge(self) -> None:
        stages = (
            "query_sent",
            "service_receive",
            "service_process_end",
            "service_process_start",
            "service_response",
            "response_received",
        )
        conflicting_windows = [
            window(index + 1, stage) for index, stage in enumerate(stages)
        ]

        graph = build_evidence_graph(
            conflicting_windows, [], [], get_topology_contract("w2")
        )

        conflict = next(
            edge for edge in graph.edges if edge.edge_type == EdgeType.CONTRADICTS
        )
        self.assertEqual((conflict.source_id, conflict.target_id), ("window:3", "window:4"))
        self.assertEqual(conflict.reason_code, "topology_order_violation")

    def test_rejects_trace_id_reused_with_a_different_sequence(self) -> None:
        mixed = list(self.windows)
        mixed[-1] = replace(mixed[-1], sequence_id=2)

        with self.assertRaisesRegex(ValueError, "inconsistent trace identity"):
            build_evidence_graph(mixed, [], [], get_topology_contract("w2"))

    def test_rejects_accepted_decision_with_wrong_sequence(self) -> None:
        event = system_event("callback")
        decision = AssociationDecision(
            event_id="callback",
            status="accepted",
            reason_code="fixture_match",
            trace_id="trace-1",
            sequence_id=99,
            stage="service_receive",
            window_id="window:2",
        )

        with self.assertRaisesRegex(ValueError, "target mismatch"):
            build_evidence_graph(
                self.windows,
                [event],
                [decision],
                get_topology_contract("w2"),
            )

    def test_structured_identity_cannot_be_overwritten_by_source_attributes(self) -> None:
        event = replace(
            system_event("callback"),
            attributes={"timestamp_ns": 999, "pid": 999, "custom": "kept"},
        )
        decision = AssociationDecision(
            event_id="callback",
            status="accepted",
            reason_code="fixture_match",
            trace_id="trace-1",
            sequence_id=1,
            stage="service_receive",
            window_id="window:2",
        )

        graph = build_evidence_graph(
            self.windows, [event], [decision], get_topology_contract("w2")
        )

        node = next(item for item in graph.nodes if item.node_id == "evidence:callback")
        self.assertEqual(node.attributes["timestamp_ns"], 250)
        self.assertEqual(node.attributes["pid"], 10)
        self.assertEqual(
            node.attributes["source_attributes"],
            {"timestamp_ns": 999, "pid": 999, "custom": "kept"},
        )

    def test_rejects_unknown_association_status(self) -> None:
        event = system_event("callback")
        decision = AssociationDecision(
            event_id="callback",
            status="guessed",
            reason_code="fixture",
        )

        with self.assertRaisesRegex(ValueError, "unsupported association status"):
            build_evidence_graph(
                self.windows,
                [event],
                [decision],
                get_topology_contract("w2"),
            )

    def test_materializes_every_terminal_conflict_without_unpacking_failure(self) -> None:
        stages = (
            "camera_publish",
            "planner_receive",
            "planner_process_start",
            "planner_process_end",
            "planner_publish",
            "action_receive",
            "action_execute_start",
            "action_execute_end",
            "can_receive",
            "can_encode_start",
            "can_encode_end",
            "can_frame_sent",
            "can_ack_wait_start",
            "can_ack_received",
            "can_retry_exhausted",
            "can_frame_send_failed",
        )

        graph = build_evidence_graph(
            [window(index + 1, stage) for index, stage in enumerate(stages)],
            [],
            [],
            get_topology_contract("w1"),
        )

        conflicts = [
            edge for edge in graph.edges if edge.edge_type == EdgeType.CONTRADICTS
        ]
        self.assertEqual(len(conflicts), 2)
        self.assertEqual(
            {edge.reason_code for edge in conflicts}, {"topology_terminal_conflict"}
        )


class TopologyContractTest(unittest.TestCase):
    def test_accepts_complete_w1_ack_path(self) -> None:
        contract = get_topology_contract("w1")

        result = contract.validate(
            [
                "camera_publish",
                "planner_receive",
                "planner_process_start",
                "planner_process_end",
                "planner_publish",
                "action_receive",
                "action_execute_start",
                "action_execute_end",
                "can_receive",
                "can_encode_start",
                "can_encode_end",
                "can_frame_sent",
                "can_ack_wait_start",
                "can_ack_received",
            ]
        )

        self.assertEqual(result.status, "valid")
        self.assertEqual(result.matched_path, "ack_received")
        self.assertEqual(result.missing_expected, ())
        self.assertEqual(result.reason_codes, ())

    def test_accepts_complete_w2_service_path(self) -> None:
        result = get_topology_contract("w2").validate(
            [
                "query_sent",
                "service_receive",
                "service_process_start",
                "service_process_end",
                "service_response",
                "response_received",
            ]
        )

        self.assertEqual(result.status, "valid")
        self.assertEqual(result.matched_path, "request_response")

    def test_reports_missing_stage_without_inventing_evidence(self) -> None:
        result = get_topology_contract("w2").validate(
            [
                "query_sent",
                "service_receive",
                "service_process_end",
                "service_response",
                "response_received",
            ]
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.missing_expected, ("service_process_start",))
        self.assertEqual(result.reason_codes, ("topology_stage_missing",))

    def test_rejects_required_stages_observed_out_of_order(self) -> None:
        result = get_topology_contract("w2").validate(
            [
                "query_sent",
                "service_process_end",
                "service_process_start",
                "service_response",
                "response_received",
            ]
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn("topology_order_violation", result.reason_codes)
        self.assertEqual(result.conflicting_stages, ("service_process_end", "service_process_start"))

    def test_unknown_workload_has_no_implicit_contract(self) -> None:
        with self.assertRaises(KeyError):
            get_topology_contract("unknown")

    def test_rejects_multiple_w1_terminal_outcomes(self) -> None:
        result = get_topology_contract("w1").validate(
            [
                "camera_publish",
                "planner_receive",
                "planner_process_start",
                "planner_process_end",
                "planner_publish",
                "action_receive",
                "action_execute_start",
                "action_execute_end",
                "can_receive",
                "can_encode_start",
                "can_encode_end",
                "can_frame_sent",
                "can_ack_wait_start",
                "can_ack_received",
                "can_retry_exhausted",
            ]
        )

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.reason_codes, ("topology_terminal_conflict",))
        self.assertEqual(
            result.conflicting_stages,
            ("can_ack_received", "can_retry_exhausted"),
        )

    def test_terminal_path_order_violation_is_not_hidden_by_other_paths(self) -> None:
        result = get_topology_contract("w1").validate(
            [
                "camera_publish",
                "planner_receive",
                "planner_process_start",
                "planner_process_end",
                "planner_publish",
                "action_receive",
                "action_execute_start",
                "action_execute_end",
                "can_receive",
                "can_encode_start",
                "can_encode_end",
                "can_frame_sent",
                "can_ack_received",
                "can_ack_wait_start",
            ]
        )

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.matched_path, "ack_received")
        self.assertEqual(result.reason_codes, ("topology_order_violation",))


if __name__ == "__main__":
    unittest.main()
