import unittest

from diagnosis.adapters.application_compute_delay_adapter import (
    derive_application_compute_delay_evidence,
)


EVENTS = (
    "camera_frame_published",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
)


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
        "stage": event_name,
        "timestamp_ns": timestamp_ns,
        "event_name": event_name,
        "pid": 10 if camera else 20,
        "tid": 10 if camera else 20,
        "host_id": host_id,
        "clock_id": clock_id,
    }


def complete_trace(
    trace_id: str, sequence_id: int, *, processing_ns: int = 100_000_000
) -> list[dict]:
    timestamps = (1000, 1200, 1200 + processing_ns, 1300 + processing_ns)
    return [
        runtime_event(trace_id, event_name, timestamp, sequence_id)
        for event_name, timestamp in zip(EVENTS, timestamps)
    ]


def run_manifest() -> dict:
    return {
        "schema_version": "fault-run/v1",
        "condition_id": "condition-a",
        "session_id": "session-a",
        "dataset_role": "development",
        "workload": "w1",
        "git_commit": "a" * 40,
    }


def oracle_manifest(variant: str = "injected") -> dict:
    return {
        "schema_version": "fault-oracle/v1",
        "condition_id": "condition-a",
        "session_id": "session-a",
        "dataset_role": "development",
        "fault_id": "F1",
        "condition_variant": variant,
        "cause_id": "application_compute_delay" if variant == "injected" else "none",
        "injection": {
            "planner_delay_mode": "busy_compute",
            "planner_delay_ms": 100 if variant == "injected" else 0,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
        },
    }


def derive(records: list[dict], variant: str = "injected"):
    return derive_application_compute_delay_evidence(
        records,
        run_manifest(),
        oracle_manifest(variant),
        runtime_source_file="runtime.jsonl",
        run_manifest_source_file="run.json",
        oracle_manifest_source_file="oracle.json",
    )


class ApplicationComputeDelayAdapterTest(unittest.TestCase):
    def test_derives_elapsed_intervals_and_preserves_missingness(self) -> None:
        records = complete_trace("trace-1", 1)
        records.extend(complete_trace("trace-2", 2, processing_ns=102_000_000))
        records.append(runtime_event("trace-3", EVENTS[0], 3000, 3))

        events, report = derive(records)

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["observed_trace_count"], 3)
        self.assertEqual(report["complete_trace_count"], 2)
        self.assertEqual(report["incomplete_trace_count"], 1)
        self.assertEqual(
            report["metrics_ns"]["planner_processing_elapsed_ns"]["median"],
            101_000_000,
        )
        self.assertEqual(
            report["metrics_ns"]["camera_to_planner_publish_upper_bound_ns"]["median"],
            101_000_300,
        )
        self.assertEqual(
            report["measurement_semantics"], "runtime_event_elapsed_interval"
        )
        self.assertFalse(report["formal_cpu_time_measurement"])
        self.assertTrue(report["development_only"])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "application_compute_delay_interval")
        self.assertEqual(
            events[0].attributes["planner_processing_elapsed_ns"], 100_000_000
        )

    def test_accepts_zero_duration_busy_compute_control(self) -> None:
        events, report = derive(
            complete_trace("trace-1", 1, processing_ns=20_000), "control"
        )

        self.assertEqual(report["condition_variant"], "control")
        self.assertEqual(report["status"], "valid")
        self.assertEqual(len(events), 1)

    def test_rejects_wrong_oracle_delay_profile(self) -> None:
        oracle = oracle_manifest()
        oracle["injection"]["planner_delay_mode"] = "sleep"

        events, report = derive_application_compute_delay_evidence(
            complete_trace("trace-1", 1),
            run_manifest(),
            oracle,
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["reason_code"], "oracle_profile_mismatch")

    def test_rejects_formal_partition_and_manifest_identity_mismatch(self) -> None:
        run = run_manifest()
        run["dataset_role"] = "calibration"
        oracle = oracle_manifest()
        oracle["dataset_role"] = "calibration"
        events, report = derive_application_compute_delay_evidence(
            complete_trace("trace-1", 1),
            run,
            oracle,
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "development_partition_required")

        run = run_manifest()
        run["condition_id"] = "different-condition"
        events, report = derive_application_compute_delay_evidence(
            complete_trace("trace-1", 1),
            run,
            oracle_manifest(),
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "run_oracle_identity_mismatch")

    def test_excludes_clock_sequence_and_negative_intervals(self) -> None:
        clock = complete_trace("clock", 1)
        clock[1]["clock_id"] = "realtime"
        sequence = complete_trace("sequence", 2)
        sequence[2]["sequence_id"] = 99
        negative = complete_trace("negative", 3)
        negative[2]["timestamp_ns"] = negative[1]["timestamp_ns"] - 1

        events, report = derive(clock + sequence + negative)

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_count"], 3)
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {
                "clock_or_host_mismatch": 1,
                "negative_elapsed_interval": 1,
                "trace_identity_mismatch": 1,
            },
        )

    def test_rejects_non_integer_timestamp_without_crashing(self) -> None:
        records = complete_trace("trace-1", 1)
        records[2]["timestamp_ns"] = "invalid"

        events, report = derive(records)

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_reason_counts"], {"invalid_timestamp": 1})


if __name__ == "__main__":
    unittest.main()
