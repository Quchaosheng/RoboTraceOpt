import json
import unittest

from diagnosis.adapters.mock_ack_lifecycle_adapter import (
    derive_mock_ack_lifecycle_evidence,
)


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
        "fault_id": "F6",
        "condition_variant": variant,
        "cause_id": "can_ack_failure" if variant == "injected" else "none",
        "injection": {
            "mock_ack_policy": "drop" if variant == "injected" else "success",
            "ack_timeout_ms": 20,
            "max_retries": 2,
            "ack_mode": "mock",
            "mock_mode": True,
            "input_rate_hz": 4,
            "planner_backend": "mock",
            "action_manager_enabled": True,
        },
    }


def event(
    trace_id: str,
    name: str,
    timestamp_ns: int,
    retry_count: int,
    *,
    sequence_id: int = 1,
    variant: str = "injected",
) -> dict:
    return {
        "trace_id": trace_id,
        "sequence_id": sequence_id,
        "event_name": name,
        "stage": name,
        "timestamp_ns": timestamp_ns,
        "pid": 20,
        "tid": 20,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(
            {
                "ack_mode": "mock",
                "mock_mode": True,
                "mock_ack_policy": "drop" if variant == "injected" else "success",
                "ack_timeout_ms": 20,
                "retry_count": retry_count,
                "max_retries": 2,
            }
        ),
    }


def exhausted_trace(trace_id: str = "trace-1") -> list[dict]:
    names_and_retries = (
        ("can_ack_wait_start", 0),
        ("can_ack_timeout", 0),
        ("can_retry_scheduled", 1),
        ("can_ack_wait_start", 1),
        ("can_ack_timeout", 1),
        ("can_retry_scheduled", 2),
        ("can_ack_wait_start", 2),
        ("can_ack_timeout", 2),
        ("can_retry_exhausted", 2),
    )
    return [
        event(trace_id, name, 1000 + index * 20_000_000, retry)
        for index, (name, retry) in enumerate(names_and_retries)
    ]


def success_trace(trace_id: str = "trace-1") -> list[dict]:
    return [
        event(trace_id, "can_ack_wait_start", 1000, 0, variant="control"),
        event(trace_id, "can_ack_received", 5_001_000, 0, variant="control"),
    ]


def derive(records: list[dict], variant: str = "injected"):
    return derive_mock_ack_lifecycle_evidence(
        records,
        run_manifest(),
        oracle_manifest(variant),
        runtime_source_file="runtime.jsonl",
        run_manifest_source_file="run.json",
        oracle_manifest_source_file="oracle.json",
    )


class MockAckLifecycleAdapterTest(unittest.TestCase):
    def test_derives_retry_exhausted_lifecycle(self) -> None:
        events, report = derive(exhausted_trace())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].attributes["terminal_state"], "retry_exhausted")
        self.assertEqual(events[0].attributes["attempt_count"], 3)
        self.assertEqual(events[0].attributes["timeout_count"], 3)
        self.assertEqual(events[0].attributes["retry_scheduled_count"], 2)
        self.assertFalse(events[0].attributes["physical_can_evidence"])
        self.assertEqual(report["retry_exhausted_rate"], 1.0)
        self.assertEqual(report["ack_success_rate"], 0.0)
        self.assertIsNone(report["terminal_latency_ns"]["ack_received"])

    def test_accepts_success_control_and_reports_missing_terminal(self) -> None:
        records = success_trace()
        records.append(event("trace-missing", "can_ack_wait_start", 1000, 0, variant="control", sequence_id=2))

        events, report = derive(records, "control")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].attributes["terminal_state"], "ack_received")
        self.assertEqual(events[0].attributes["attempt_count"], 1)
        self.assertEqual(report["ack_success_rate"], 1.0)
        self.assertEqual(report["incomplete_trace_count"], 1)
        self.assertIsNone(report["terminal_latency_ns"]["retry_exhausted"])

    def test_rejects_conflicting_terminal_and_event_after_terminal(self) -> None:
        conflict = success_trace("conflict")
        conflict.append(event("conflict", "can_retry_exhausted", 6_001_000, 2, variant="control"))
        after = success_trace("after")
        after.append(event("after", "can_ack_timeout", 6_001_000, 0, variant="control"))

        events, report = derive(conflict + after, "control")

        self.assertEqual(events, [])
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {"conflicting_terminal": 1, "event_after_terminal": 1},
        )

    def test_rejects_wrong_retry_sequence_and_profile(self) -> None:
        records = exhausted_trace()
        records[2]["extra_json"] = records[2]["extra_json"].replace(
            '"retry_count": 1', '"retry_count": 2'
        )
        events, report = derive(records)
        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_reason_counts"], {"retry_sequence_mismatch": 1})

        oracle = oracle_manifest()
        oracle["injection"]["ack_timeout_ms"] = 30
        events, report = derive_mock_ack_lifecycle_evidence(
            exhausted_trace(),
            run_manifest(),
            oracle,
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "oracle_profile_mismatch")

    def test_rejects_identity_clock_and_negative_interval(self) -> None:
        identity = exhausted_trace("identity")
        identity[1]["sequence_id"] = 9
        clock = exhausted_trace("clock")
        clock[1]["clock_id"] = "realtime"
        negative = exhausted_trace("negative")
        negative[-1]["timestamp_ns"] = 0

        events, report = derive(identity + clock + negative)

        self.assertEqual(events, [])
        self.assertEqual(
            report["invalid_pair_reason_counts"],
            {
                "clock_or_host_mismatch": 1,
                "negative_terminal_interval": 1,
                "trace_identity_mismatch": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
