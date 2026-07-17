import unittest

from diagnosis.adapters.callback_dispatch_adapter import (
    derive_callback_dispatch_evidence,
)


def runtime_event(
    trace_id: str,
    event_name: str,
    timestamp_ns: int,
    *,
    sequence_id: int = 1,
    host_id: str = "host-a",
    clock_id: str = "monotonic",
) -> dict:
    return {
        "trace_id": trace_id,
        "sequence_id": sequence_id,
        "source_node": (
            "camera_mock_node"
            if event_name == "camera_frame_published"
            else "vlm_planner_node"
        ),
        "stage": (
            "camera_publish"
            if event_name == "camera_frame_published"
            else "planner_receive"
        ),
        "timestamp_ns": timestamp_ns,
        "event_name": event_name,
        "event_type": "runtime",
        "pid": 10 if event_name == "camera_frame_published" else 20,
        "tid": 10 if event_name == "camera_frame_published" else 20,
        "host_id": host_id,
        "clock_id": clock_id,
    }


def tracing_event(event_name: str, payload: dict) -> dict:
    return {
        "event_name": event_name,
        "host_id": "host-a",
        "clock": {"name": "monotonic", "frequency": 1_000_000_000, "value": 1},
        "context": {"vpid": 20, "vtid": 20, "procname": "vlm_planner_nod"},
        "payload": payload,
    }


def valid_tracing_records() -> list[dict]:
    return [
        tracing_event(
            "ros2:rcl_node_init",
            {"node_handle": 100, "node_name": "vlm_planner_node", "namespace": "/"},
        ),
        tracing_event(
            "ros2:rcl_subscription_init",
            {
                "subscription_handle": 200,
                "node_handle": 100,
                "rmw_subscription_handle": 201,
                "topic_name": "/camera/frame",
                "queue_depth": 10,
            },
        ),
        tracing_event(
            "ros2:rcl_timer_init",
            {"timer_handle": 300, "period": 25_000_000},
        ),
    ]


def process_manifest() -> dict:
    return {
        "schema_version": "process-manifest/v2",
        "host_id": "host-a",
        "processes": [{"node": "vlm_planner_node", "pid": 20}],
    }


def oracle_manifest(variant: str = "injected") -> dict:
    return {
        "schema_version": "fault-oracle/v1",
        "fault_id": "F2",
        "condition_variant": variant,
        "cause_id": "executor_queueing" if variant == "injected" else "none",
        "injection": {
            "callback_period_ms": 25,
            "callback_load_ms": 20,
            "executor_contention_enabled": variant == "injected",
        },
    }


class CallbackDispatchAdapterTest(unittest.TestCase):
    def test_derives_bounded_evidence_and_counts_missing_endpoints(self) -> None:
        runtime_records = [
            runtime_event("trace-1", "camera_frame_published", 100, sequence_id=1),
            runtime_event("trace-1", "planner_receive", 160, sequence_id=1),
            runtime_event("trace-2", "camera_frame_published", 200, sequence_id=2),
            runtime_event("trace-2", "planner_receive", 300, sequence_id=2),
            runtime_event("trace-3", "camera_frame_published", 400, sequence_id=3),
        ]

        events, report = derive_callback_dispatch_evidence(
            runtime_records,
            valid_tracing_records(),
            process_manifest(),
            oracle_manifest(),
            expected_timer_period_ns=25_000_000,
            runtime_source_file="runtime.jsonl",
            tracing_source_file="ros2.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["paired_trace_count"], 2)
        self.assertEqual(report["missing_receive_count"], 1)
        self.assertEqual(report["missing_publish_count"], 0)
        self.assertEqual(report["invalid_pair_count"], 0)
        self.assertEqual(report["delay_ns"]["min"], 60)
        self.assertEqual(report["delay_ns"]["median"], 80)
        self.assertEqual(report["delay_ns"]["max"], 100)
        self.assertEqual([event.trace_id for event in events], ["trace-1", "trace-2"])
        self.assertEqual(events[0].source, "derived_fusion")
        self.assertEqual(events[0].event_type, "ros_callback_dispatch_bound")
        self.assertEqual(events[0].attributes["queue_delay_ns"], 60)
        self.assertEqual(
            events[0].attributes["measurement_semantics"],
            "publish_to_callback_upper_bound",
        )
        self.assertTrue(events[0].attributes["includes_dds_transfer"])
        self.assertEqual(report["structural_gate"]["timer_period_ns"], 25_000_000)

    def test_rejects_bundle_when_expected_planner_timer_is_missing(self) -> None:
        events, report = derive_callback_dispatch_evidence(
            [
                runtime_event("trace-1", "camera_frame_published", 100),
                runtime_event("trace-1", "planner_receive", 160),
            ],
            valid_tracing_records()[:-1],
            process_manifest(),
            oracle_manifest(),
            expected_timer_period_ns=25_000_000,
            runtime_source_file="runtime.jsonl",
            tracing_source_file="ros2.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["reason_code"], "planner_timer_not_observed")

    def test_excludes_clock_mismatch_and_negative_intervals(self) -> None:
        runtime_records = [
            runtime_event("clock", "camera_frame_published", 100),
            runtime_event("clock", "planner_receive", 160, clock_id="realtime"),
            runtime_event("negative", "camera_frame_published", 300),
            runtime_event("negative", "planner_receive", 200),
        ]

        events, report = derive_callback_dispatch_evidence(
            runtime_records,
            valid_tracing_records(),
            process_manifest(),
            oracle_manifest(),
            expected_timer_period_ns=25_000_000,
            runtime_source_file="runtime.jsonl",
            tracing_source_file="ros2.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["invalid_pair_count"], 2)
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {"clock_or_host_mismatch": 1, "negative_dispatch_interval": 1},
        )

    def test_control_requires_disabled_oracle_and_absent_contention_timer(self) -> None:
        runtime_records = [
            runtime_event("trace-1", "camera_frame_published", 100),
            runtime_event("trace-1", "planner_receive", 120),
        ]

        events, report = derive_callback_dispatch_evidence(
            runtime_records,
            valid_tracing_records()[:-1],
            process_manifest(),
            oracle_manifest("control"),
            expected_timer_period_ns=25_000_000,
            runtime_source_file="runtime.jsonl",
            tracing_source_file="ros2.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["condition_variant"], "control")
        self.assertEqual(report["structural_gate"]["timer_status"], "not_observed")
        self.assertEqual(len(events), 1)

    def test_control_rejects_an_observed_contention_timer(self) -> None:
        events, report = derive_callback_dispatch_evidence(
            [
                runtime_event("trace-1", "camera_frame_published", 100),
                runtime_event("trace-1", "planner_receive", 120),
            ],
            valid_tracing_records(),
            process_manifest(),
            oracle_manifest("control"),
            expected_timer_period_ns=25_000_000,
            runtime_source_file="runtime.jsonl",
            tracing_source_file="ros2.jsonl",
            process_manifest_source_file="process.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["reason_code"], "unexpected_control_contention_timer")


if __name__ == "__main__":
    unittest.main()
