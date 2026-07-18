import json
import unittest
from pathlib import Path

from optimizer.trials.runtime_trial import (
    build_trial_command,
    build_trial_manifest,
    derive_f1_trial_report,
    derive_f2_trial_report,
    derive_f4_trial_report,
    derive_f5_trial_report,
)


def event(name: str, timestamp_ns: int, *, trace_id: str = "trace-1", delay_ms: int = 25):
    extra = {"planner_delay_ms": delay_ms, "planner_delay_mode": "busy_compute"} if name == "planner_process_start" else {}
    return {
        "trace_id": trace_id,
        "sequence_id": 1,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": 10,
        "tid": 10,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(extra),
    }


class RuntimeTrialTest(unittest.TestCase):
    def test_builds_arbitrary_f1_candidate_command(self) -> None:
        command = build_trial_command(
            "application_compute_delay",
            {"planner_delay_ms": 25},
            Path("events.jsonl"),
        )
        self.assertIn("planner_delay_ms:=25", command)
        self.assertIn("planner_delay_mode:=busy_compute", command)

    def test_builds_development_only_trial_manifest(self) -> None:
        manifest = build_trial_manifest(
            cause_id="application_compute_delay",
            candidate_config={"planner_delay_ms": 25},
            trial_id="f1-guided-02",
            strategy="guided",
            seed=7,
            git_commit="a" * 40,
            command=["ros2", "launch"],
        )
        self.assertEqual(manifest["dataset_role"], "development")
        self.assertFalse(manifest["formal_optimization_allowed"])
        self.assertEqual(manifest["candidate_config"], {"planner_delay_ms": 25})

    def test_manifest_accepts_unguided_and_rejects_unknown_strategy(self) -> None:
        manifest = build_trial_manifest(
            cause_id="dds_communication_delay",
            candidate_config={"frame_qos_depth": 4},
            trial_id="trial-unguided",
            strategy="unguided_random",
            seed=7,
            git_commit="a" * 40,
            command=["ros2"],
        )
        self.assertEqual(manifest["strategy"], "unguided_random")
        with self.assertRaisesRegex(ValueError, "strategy"):
            build_trial_manifest(
                cause_id="dds_communication_delay",
                candidate_config={"frame_qos_depth": 4},
                trial_id="trial-grid",
                strategy="grid",
                seed=7,
                git_commit="a" * 40,
                command=["ros2"],
            )

    def test_builds_arbitrary_f4_candidate_command(self) -> None:
        command = build_trial_command(
            "blocking_syscall_io", {"server_delay_ms": 50}, Path("events.jsonl")
        )
        self.assertIn("server_delay_ms:=50", command)
        self.assertIn("request_rate_hz:=5", command)

    def test_builds_executor_thread_candidate_command(self) -> None:
        command = build_trial_command(
            "executor_queueing", {"executor_threads": 2}, Path("events.jsonl")
        )
        self.assertIn("executor_threads:=2", command)
        self.assertIn("executor_contention_enabled:=true", command)
        self.assertIn("executor_contention_load_ms:=20", command)

    def test_builds_qos_depth_candidate_command(self) -> None:
        command = build_trial_command(
            "dds_communication_delay", {"frame_qos_depth": 4}, Path("events.jsonl")
        )
        self.assertIn("frame_qos_depth:=4", command)
        self.assertIn("frame_payload_bytes:=262144", command)
        self.assertIn("camera_rate_hz:=100", command)

    def test_derives_f1_candidate_objective_report(self) -> None:
        records = [
            event("planner_process_start", 1_000),
            event("planner_process_end", 25_002_000),
            event("planner_process_start", 30_000_000, trace_id="trace-2"),
            event("planner_process_end", 55_003_000, trace_id="trace-2"),
        ]
        report = derive_f1_trial_report(records, {"planner_delay_ms": 25})
        self.assertEqual(report["complete_trace_count"], 2)
        self.assertEqual(report["complete_trace_rate"], 1.0)
        self.assertEqual(report["metrics_ns"]["planner_processing_elapsed_ns"]["median"], 25_002_000.0)
        self.assertFalse(report["formal_optimization_allowed"])

    def test_rejects_wrong_profile_and_counts_incomplete_trace(self) -> None:
        wrong = [
            event("planner_process_start", 1_000, delay_ms=50),
            event("planner_process_end", 2_000),
        ]
        with self.assertRaisesRegex(ValueError, "candidate profile"):
            derive_f1_trial_report(wrong, {"planner_delay_ms": 25})
        partial = derive_f1_trial_report(
            [event("planner_process_start", 1_000)], {"planner_delay_ms": 25}
        )
        self.assertEqual(partial["complete_trace_count"], 0)
        self.assertEqual(partial["incomplete_trace_count"], 1)

    def test_derives_f4_request_response_trial_report(self) -> None:
        rows = [
            service_event("query_sent", 1_000, pid=20),
            service_event("service_process_start", 2_000, pid=10),
            service_event("service_process_end", 50_002_000, pid=10),
            service_event("response_received", 50_003_000, pid=20),
        ]
        report = derive_f4_trial_report(rows, {"server_delay_ms": 50})
        self.assertEqual(report["complete_trace_count"], 1)
        self.assertEqual(
            report["metrics_ns"]["request_response_elapsed_ns"]["median"],
            50_002_000.0,
        )

    def test_derives_f2_dispatch_upper_bound(self) -> None:
        records = [
            dispatch_event("camera_frame_published", 1_000, executor_threads=2),
            dispatch_event("planner_receive", 2_500, executor_threads=2),
        ]
        report = derive_f2_trial_report(records, {"executor_threads": 2})
        self.assertEqual(report["complete_trace_count"], 1)
        self.assertEqual(
            report["metrics_ns"]["callback_dispatch_upper_bound_ns"]["median"],
            1_500.0,
        )

    def test_f4_selects_one_of_two_distinct_server_pids(self) -> None:
        rows = [
            service_event("query_sent", 1_000, pid=20),
            service_event("service_process_start", 2_000, pid=10, delay_ms=25),
            service_event("service_process_start", 2_100, pid=11, delay_ms=25),
            service_event("service_process_end", 25_002_000, pid=10, delay_ms=25),
            service_event("service_process_end", 25_002_100, pid=11, delay_ms=25),
            service_event("response_received", 25_003_000, pid=20),
        ]
        report = derive_f4_trial_report(rows, {"server_delay_ms": 25})
        self.assertEqual(report["complete_trace_count"], 1)

    def test_derives_qos_delivery_and_latency_report(self) -> None:
        rows = [
            qos_event("camera_frame_published", 1_000, sequence_id=1),
            qos_event("planner_receive", 2_000, sequence_id=1, depth=4),
            qos_event("camera_frame_published", 3_000, sequence_id=2),
            qos_event("camera_frame_published", 4_000, sequence_id=3),
            qos_event("planner_receive", 5_500, sequence_id=3, depth=4),
        ]
        report = derive_f5_trial_report(rows, {"frame_qos_depth": 4})
        self.assertEqual(report["complete_trace_count"], 2)
        self.assertEqual(report["incomplete_trace_count"], 1)
        self.assertEqual(report["received_sequence_gap_count"], 1)
        self.assertAlmostEqual(report["complete_trace_rate"], 2 / 3)
        self.assertEqual(
            report["metrics_ns"]["camera_to_planner_upper_bound_ns"]["median"],
            1_250.0,
        )


def service_event(name: str, timestamp_ns: int, *, pid: int, delay_ms: int = 50):
    extra = {"payload_id": "payload-1"}
    if name in {"service_process_start", "service_process_end"}:
        extra["requested_delay_ms"] = delay_ms
    return {
        "trace_id": "trace-service-1",
        "sequence_id": 1,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": pid,
        "tid": pid,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(extra),
    }


def dispatch_event(name: str, timestamp_ns: int, *, executor_threads: int):
    extra = {"executor_threads": executor_threads} if name == "planner_receive" else {}
    return {
        "trace_id": "trace-dispatch-1",
        "sequence_id": 1,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": 10,
        "tid": 10,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(extra),
    }


def qos_event(
    name: str,
    timestamp_ns: int,
    *,
    sequence_id: int,
    depth: int = 4,
):
    extra = (
        {"frame_qos_depth": depth, "frame_qos_reliability": "reliable"}
        if name == "planner_receive"
        else {}
    )
    return {
        "trace_id": f"trace-qos-{sequence_id}",
        "sequence_id": sequence_id,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": 10,
        "tid": 10,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(extra),
    }


if __name__ == "__main__":
    unittest.main()
