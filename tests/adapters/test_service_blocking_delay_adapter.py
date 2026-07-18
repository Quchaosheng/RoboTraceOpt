import json
import unittest

from diagnosis.adapters.service_blocking_delay_adapter import (
    derive_service_blocking_delay_evidence,
)


EVENTS = (
    "query_sent",
    "service_process_start",
    "service_process_end",
    "response_received",
)


def manifests(variant: str = "injected"):
    delay_ms = 100 if variant == "injected" else 0
    run = {
        "schema_version": "fault-run/v1",
        "condition_id": f"condition-{variant}",
        "session_id": f"session-{variant}",
        "dataset_role": "development",
        "workload": "w2",
        "git_commit": "a" * 40,
    }
    oracle = {
        "schema_version": "fault-oracle/v1",
        "condition_id": run["condition_id"],
        "session_id": run["session_id"],
        "dataset_role": "development",
        "fault_id": "F4",
        "condition_variant": variant,
        "cause_id": "blocking_syscall_io" if variant == "injected" else "none",
        "injection": {
            "server_delay_ms": delay_ms,
            "request_rate_hz": 5,
            "blocking_primitive": "clock_nanosleep",
        },
    }
    return run, oracle


def event(
    name: str, timestamp_ns: int, *, delay_ms: int = 100, payload_id: str = "payload-1"
):
    extra = {"payload_id": payload_id}
    if name in {"service_process_start", "service_process_end"}:
        extra["requested_delay_ms"] = delay_ms
    else:
        extra["context_fault_injected"] = False
    return {
        "trace_id": "trace-1",
        "sequence_id": 1,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": 10,
        "tid": 11,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(extra),
    }


def complete_trace(delay_ms: int = 100):
    return [
        event("query_sent", 1_000, delay_ms=delay_ms),
        event("service_process_start", 2_000, delay_ms=delay_ms),
        event("service_process_end", 100_002_000, delay_ms=delay_ms),
        event("response_received", 100_003_000, delay_ms=delay_ms),
    ]


def derive(records, variant="injected"):
    run, oracle = manifests(variant)
    return derive_service_blocking_delay_evidence(
        records,
        run,
        oracle,
        runtime_source_file="runtime.jsonl",
        run_manifest_source_file="run.json",
        oracle_manifest_source_file="oracle.json",
    )


class ServiceBlockingDelayAdapterTest(unittest.TestCase):
    def test_derives_four_service_elapsed_intervals(self) -> None:
        events, report = derive(complete_trace())

        self.assertEqual(len(events), 1)
        attributes = events[0].attributes
        self.assertEqual(events[0].event_type, "service_blocking_elapsed")
        self.assertEqual(attributes["server_processing_elapsed_ns"], 100_000_000)
        self.assertEqual(attributes["request_response_elapsed_ns"], 100_002_000)
        self.assertEqual(attributes["pre_server_elapsed_ns"], 1_000)
        self.assertEqual(attributes["post_server_elapsed_ns"], 1_000)
        self.assertEqual(attributes["configured_delay_ms"], 100)
        self.assertEqual(attributes["blocking_primitive"], "clock_nanosleep")
        self.assertFalse(attributes["formal_syscall_attribution"])
        self.assertFalse(attributes["ebpf_evidence"])
        self.assertEqual(report["complete_trace_count"], 1)
        self.assertEqual(
            report["measurement_semantics"], "application_service_blocking_elapsed"
        )

    def test_accepts_zero_delay_control(self) -> None:
        records = [
            event("query_sent", 1_000, delay_ms=0),
            event("service_process_start", 2_000, delay_ms=0),
            event("service_process_end", 2_100, delay_ms=0),
            event("response_received", 3_000, delay_ms=0),
        ]

        events, report = derive(records, "control")

        self.assertEqual(events[0].attributes["configured_delay_ms"], 0)
        self.assertEqual(events[0].attributes["server_processing_elapsed_ns"], 100)
        self.assertEqual(report["condition_variant"], "control")

    def test_reports_missing_and_duplicate_stages(self) -> None:
        missing, missing_report = derive(complete_trace()[:-1])
        duplicated, duplicate_report = derive(
            complete_trace() + [event("service_process_end", 100_002_001)]
        )

        self.assertEqual(missing, [])
        self.assertEqual(missing_report["incomplete_trace_count"], 1)
        self.assertEqual(duplicated, [])
        self.assertEqual(
            duplicate_report["invalid_pair_reason_counts"], {"duplicate_stage": 1}
        )

    def test_rejects_wrong_order_payload_and_delay_profile(self) -> None:
        cases = []
        wrong_order = complete_trace()
        wrong_order[1]["timestamp_ns"], wrong_order[2]["timestamp_ns"] = (
            wrong_order[2]["timestamp_ns"],
            wrong_order[1]["timestamp_ns"],
        )
        cases.append((wrong_order, "stage_order_mismatch"))
        wrong_payload = complete_trace()
        wrong_payload[-1]["extra_json"] = json.dumps(
            {"payload_id": "other", "context_fault_injected": False}
        )
        cases.append((wrong_payload, "payload_identity_mismatch"))
        wrong_delay = complete_trace()
        wrong_delay[2]["extra_json"] = json.dumps(
            {"payload_id": "payload-1", "requested_delay_ms": 99}
        )
        cases.append((wrong_delay, "event_profile_mismatch"))

        for records, reason in cases:
            with self.subTest(reason=reason):
                events, report = derive(records)
                self.assertEqual(events, [])
                self.assertEqual(report["invalid_pair_reason_counts"], {reason: 1})

    def test_rejects_identity_clock_negative_and_malformed_metadata(self) -> None:
        cases = []
        wrong_host = complete_trace()
        wrong_host[-1]["host_id"] = "host-b"
        cases.append((wrong_host, "clock_or_host_mismatch"))
        wrong_sequence = complete_trace()
        wrong_sequence[-1]["sequence_id"] = 2
        cases.append((wrong_sequence, "trace_identity_mismatch"))
        negative = complete_trace()
        negative[-1]["timestamp_ns"] = 500
        cases.append((negative, "stage_order_mismatch"))
        malformed = complete_trace()
        malformed[1]["extra_json"] = "{"
        cases.append((malformed, "invalid_extra_json"))

        for records, reason in cases:
            with self.subTest(reason=reason):
                events, report = derive(records)
                self.assertEqual(events, [])
                self.assertEqual(report["invalid_pair_reason_counts"], {reason: 1})

    def test_rejects_non_development_or_mismatched_manifest(self) -> None:
        run, oracle = manifests()
        run["dataset_role"] = "test"
        oracle["dataset_role"] = "test"
        events, report = derive_service_blocking_delay_evidence(
            complete_trace(),
            run,
            oracle,
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "development_partition_required")

        run, oracle = manifests()
        oracle["session_id"] = "other"
        events, report = derive_service_blocking_delay_evidence(
            complete_trace(),
            run,
            oracle,
            runtime_source_file="runtime.jsonl",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
        )
        self.assertEqual(events, [])
        self.assertEqual(report["reason_code"], "run_oracle_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
