import unittest

from diagnosis.adapters.dds_pressure_adapter import derive_dds_pressure_evidence


def runtime_event(
    trace_id: str,
    event_name: str,
    timestamp_ns: int,
    sequence_id: int,
    *,
    host_id: str = "host-a",
    clock_id: str = "monotonic",
) -> dict:
    camera = event_name == "camera_frame_published"
    return {
        "trace_id": trace_id,
        "sequence_id": sequence_id,
        "source_node": "camera_mock_node" if camera else "vlm_planner_node",
        "stage": "camera_publish" if camera else "planner_receive",
        "timestamp_ns": timestamp_ns,
        "event_name": event_name,
        "pid": 10 if camera else 20,
        "tid": 10 if camera else 20,
        "host_id": host_id,
        "clock_id": clock_id,
    }


def tracing_event(pid: int, event_name: str, payload: dict) -> dict:
    return {
        "event_name": event_name,
        "host_id": "host-a",
        "clock": {"name": "monotonic", "frequency": 1_000_000_000, "value": 1},
        "context": {"vpid": pid, "vtid": pid, "procname": "node"},
        "payload": payload,
    }


def tracing_records(depth: int) -> list[dict]:
    return [
        tracing_event(
            10,
            "ros2:rcl_node_init",
            {"node_handle": 100, "node_name": "camera_mock_node", "namespace": "/"},
        ),
        tracing_event(
            10,
            "ros2:rcl_publisher_init",
            {
                "publisher_handle": 110,
                "node_handle": 100,
                "topic_name": "/camera/frame",
                "queue_depth": depth,
            },
        ),
        tracing_event(
            20,
            "ros2:rcl_node_init",
            {"node_handle": 200, "node_name": "vlm_planner_node", "namespace": "/"},
        ),
        tracing_event(
            20,
            "ros2:rcl_subscription_init",
            {
                "subscription_handle": 210,
                "node_handle": 200,
                "topic_name": "/camera/frame",
                "queue_depth": depth,
            },
        ),
    ]


def process_manifest() -> dict:
    return {
        "schema_version": "process-manifest/v2",
        "host_id": "host-a",
        "processes": [
            {"node": "camera_mock_node", "pid": 10},
            {"node": "vlm_planner_node", "pid": 20},
        ],
    }


def oracle_manifest(variant: str = "injected") -> dict:
    depth = 1 if variant == "injected" else 10
    return {
        "schema_version": "fault-oracle/v1",
        "fault_id": "F5",
        "condition_variant": variant,
        "cause_id": "dds_communication_delay" if variant == "injected" else "none",
        "injection": {
            "input_rate_hz": 100,
            "payload_bytes": 262144,
            "reliability": "reliable",
            "history": "keep_last",
            "durability": "volatile",
            "publisher_depth": depth,
            "subscriber_depth": depth,
        },
    }


def derive(runtime_records: list[dict], variant: str = "injected", depth: int = 1):
    return derive_dds_pressure_evidence(
        runtime_records,
        tracing_records(depth),
        process_manifest(),
        oracle_manifest(variant),
        runtime_source_file="runtime.jsonl",
        tracing_source_file="tracing.jsonl",
        process_manifest_source_file="process.json",
        oracle_manifest_source_file="oracle.json",
    )


class DdsPressureAdapterTest(unittest.TestCase):
    def test_derives_delivery_bounds_and_preserves_missingness(self) -> None:
        records = [
            runtime_event("trace-1", "camera_frame_published", 100, 1),
            runtime_event("trace-1", "planner_receive", 160, 1),
            runtime_event("trace-2", "camera_frame_published", 200, 2),
            runtime_event("trace-3", "camera_frame_published", 300, 3),
            runtime_event("trace-3", "planner_receive", 420, 3),
        ]

        events, report = derive(records)

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["published_trace_count"], 3)
        self.assertEqual(report["received_trace_count"], 2)
        self.assertEqual(report["paired_trace_count"], 2)
        self.assertEqual(report["missing_receive_count"], 1)
        self.assertEqual(report["received_sequence_gap_count"], 1)
        self.assertEqual(report["delay_ns"]["median"], 90)
        self.assertEqual([event.trace_id for event in events], ["trace-1", "trace-3"])
        self.assertEqual(events[0].event_type, "dds_delivery_bound")
        self.assertEqual(events[0].attributes["duration_ns"], 60)
        self.assertEqual(
            events[0].attributes["measurement_semantics"],
            "publish_to_receive_upper_bound",
        )
        self.assertTrue(events[0].attributes["includes_executor_wait"])
        self.assertEqual(report["structural_gate"]["publisher_depth"], 1)

    def test_accepts_the_matched_control_depth(self) -> None:
        events, report = derive(
            [
                runtime_event("trace-1", "camera_frame_published", 100, 1),
                runtime_event("trace-1", "planner_receive", 120, 1),
            ],
            variant="control",
            depth=10,
        )

        self.assertEqual(report["condition_variant"], "control")
        self.assertEqual(report["status"], "valid")
        self.assertEqual(len(events), 1)

    def test_rejects_traced_depth_that_contradicts_the_oracle(self) -> None:
        events, report = derive_dds_pressure_evidence(
            [
                runtime_event("trace-1", "camera_frame_published", 100, 1),
                runtime_event("trace-1", "planner_receive", 120, 1),
            ],
            tracing_records(10),
            process_manifest(),
            oracle_manifest("injected"),
            runtime_source_file="runtime.jsonl",
            tracing_source_file="tracing.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["reason_code"], "endpoint_depth_mismatch")

    def test_excludes_clock_mismatch_and_negative_intervals(self) -> None:
        events, report = derive(
            [
                runtime_event("clock", "camera_frame_published", 100, 1),
                runtime_event(
                    "clock", "planner_receive", 120, 1, clock_id="realtime"
                ),
                runtime_event("negative", "camera_frame_published", 300, 2),
                runtime_event("negative", "planner_receive", 200, 2),
            ]
        )

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_count"], 2)
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {"clock_or_host_mismatch": 1, "negative_delivery_interval": 1},
        )


if __name__ == "__main__":
    unittest.main()
