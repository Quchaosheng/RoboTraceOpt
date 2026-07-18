import unittest

from diagnosis.evidence_graph.association import associate_system_event
from diagnosis.evidence_graph.callback_identity import build_callback_identities
from diagnosis.evidence_graph.stage_window import build_stage_windows
from diagnosis.schema import NormalizedEvent


def trace_event(event_id: str, event_type: str, payload: dict) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source="ros2_tracing",
        event_type=event_type,
        timestamp_ns=100,
        clock_id="monotonic",
        trace_id="",
        sequence_id=0,
        stage="",
        pid=10,
        tid=10,
        host_id="host-a",
        attributes={"payload": payload},
        provenance={},
    )


class CallbackIdentityTest(unittest.TestCase):
    def test_resolves_subscription_callback_to_node_topic_and_symbol(self) -> None:
        events = [
            trace_event(
                "node", "ros2:rcl_node_init", {"node_handle": 1, "node_name": "planner"}
            ),
            trace_event(
                "rcl-sub",
                "ros2:rcl_subscription_init",
                {
                    "subscription_handle": 2,
                    "node_handle": 1,
                    "topic_name": "/camera/frame",
                },
            ),
            trace_event(
                "cpp-sub",
                "ros2:rclcpp_subscription_init",
                {"subscription_handle": 2, "subscription": 3},
            ),
            trace_event(
                "callback-added",
                "ros2:rclcpp_subscription_callback_added",
                {"subscription": 3, "callback": 4},
            ),
            trace_event(
                "registered",
                "ros2:rclcpp_callback_register",
                {"callback": 4, "symbol": "Planner::on_frame"},
            ),
        ]

        identities = build_callback_identities(events)
        identity = identities[(10, 4)]

        self.assertEqual(identity.kind, "subscription")
        self.assertEqual(identity.node_name, "planner")
        self.assertEqual(identity.topic_name, "/camera/frame")
        self.assertEqual(identity.symbol, "Planner::on_frame")
        self.assertFalse(identity.infrastructure)

    def test_parameter_service_callback_is_infrastructure_background(self) -> None:
        init_events = [
            trace_event(
                "service-added",
                "ros2:rclcpp_service_callback_added",
                {"service_handle": 8, "callback": 9},
            ),
            trace_event(
                "registered",
                "ros2:rclcpp_callback_register",
                {"callback": 9, "symbol": "rclcpp::ParameterService::get_parameters"},
            ),
        ]
        callback = trace_event("callback", "ros2:callback_start", {"callback": 9})
        callback = NormalizedEvent(
            **{**callback.to_dict(), "timestamp_ns": 150, "tid": 11}
        )
        runtime = [
            NormalizedEvent(
                event_id="start",
                source="runtime_event",
                event_type="planner_start",
                timestamp_ns=100,
                clock_id="monotonic",
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_start",
                pid=10,
                tid=11,
                host_id="host-a",
                attributes={"source_node": "planner", "duration_ns": 0},
                provenance={},
            ),
            NormalizedEvent(
                event_id="end",
                source="runtime_event",
                event_type="planner_end",
                timestamp_ns=200,
                clock_id="monotonic",
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_end",
                pid=10,
                tid=11,
                host_id="host-a",
                attributes={"source_node": "planner", "duration_ns": 0},
                provenance={},
            ),
        ]
        identities = build_callback_identities(init_events + [callback])

        decision = associate_system_event(
            callback, build_stage_windows(runtime), callback_identities=identities
        )

        self.assertEqual(decision.status, "unmatched")
        self.assertEqual(decision.reason_code, "infrastructure_callback")
        self.assertEqual(decision.callback_handle, 9)
        self.assertEqual(decision.callback_kind, "service")


if __name__ == "__main__":
    unittest.main()
