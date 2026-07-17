import json
import unittest

from diagnosis.adapters.socketcan_ack_lifecycle_adapter import (
    derive_socketcan_ack_lifecycle_evidence,
    parse_candump_line,
)


def manifests(variant: str):
    session_id = f"session-{variant}"
    run = {
        "schema_version": "fault-run/v1",
        "condition_id": f"condition-{variant}",
        "session_id": session_id,
        "dataset_role": "development",
        "workload": "w1",
        "git_commit": "a" * 40,
    }
    profile = {
        "transport_profile": "vcan",
        "ack_mode": "socketcan",
        "mock_mode": False,
        "can_interface": "vcan0",
        "ack_can_id_offset": 128,
        "responder_delay_ms": 5,
        "responder_policy": "drop" if variant == "injected" else "echo",
        "ack_timeout_ms": 20,
        "max_retries": 2,
        "input_rate_hz": 4,
        "planner_backend": "mock",
        "action_manager_enabled": True,
    }
    oracle = {
        "schema_version": "fault-oracle/v1",
        "condition_id": run["condition_id"],
        "session_id": session_id,
        "dataset_role": "development",
        "fault_id": "F6",
        "condition_variant": variant,
        "cause_id": "can_ack_failure" if variant == "injected" else "none",
        "injection": profile,
    }
    capture = {
        "schema_version": "socketcan-capture/v1",
        "session_id": session_id,
        "condition_variant": variant,
        "capture_profile": profile,
        "socketcan_evidence": True,
        "virtual_can_bus": True,
        "physical_can_evidence": False,
        "responder": {"command_observed_count": 3 if variant == "injected" else 1},
        "candump": {"line_count": 3 if variant == "injected" else 2},
        "candump_identity": {"path": "/usr/bin/candump", "help_sha256": "b" * 64},
    }
    return run, oracle, capture


def runtime_event(name: str, timestamp_ns: int, retry_count: int) -> dict:
    return {
        "trace_id": "trace-1",
        "sequence_id": 1,
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "pid": 10,
        "tid": 11,
        "host_id": "host-a",
        "clock_id": "monotonic",
        "extra_json": json.dumps(
            {
                "ack_mode": "socketcan",
                "mock_mode": False,
                "can_interface": "vcan0",
                "ack_timeout_ms": 20,
                "max_retries": 2,
                "retry_count": retry_count,
                "can_id": "0x123",
                "ack_can_id": "0x1A3",
                "payload_hex": "010203",
                "send_success": True,
            }
        ),
    }


def injected_sources():
    runtime = []
    for attempt, base in enumerate((1_000_000_000, 1_030_000_000, 1_060_000_000)):
        runtime.extend(
            [
                runtime_event("can_frame_sent", base, attempt),
                runtime_event("can_ack_wait_start", base + 100_000, attempt),
                runtime_event("can_ack_timeout", base + 20_000_000, attempt),
            ]
        )
        if attempt < 2:
            runtime.append(runtime_event("can_retry_scheduled", base + 20_100_000, attempt + 1))
    runtime.append(runtime_event("can_retry_exhausted", 1_080_100_000, 2))
    responder = [
        {
            "record_type": "command_observed",
            "session_id": "session-injected",
            "interface": "vcan0",
            "policy": "drop",
            "decision": "drop",
            "command_can_id": "0x123",
            "command_payload_hex": "010203",
            "ack_can_id": "0x1A3",
            "ack_payload_hex": "010203",
            "receive_monotonic_ns": base + 50_000,
            "send_success": None,
        }
        for base in (1_000_000_000, 1_030_000_000, 1_060_000_000)
    ]
    candump = [
        {"record_index": index, "realtime_ns": index * 1_000, "interface": "vcan0", "can_id": 0x123, "payload_hex": "010203"}
        for index in (1, 2, 3)
    ]
    return runtime, responder, candump


def control_sources():
    runtime = [
        runtime_event("can_frame_sent", 2_000_000_000, 0),
        runtime_event("can_ack_wait_start", 2_000_100_000, 0),
        runtime_event("can_ack_received", 2_006_000_000, 0),
    ]
    responder = [
        {
            "record_type": "command_observed",
            "session_id": "session-control",
            "interface": "vcan0",
            "policy": "echo",
            "decision": "echo",
            "command_can_id": "0x123",
            "command_payload_hex": "010203",
            "ack_can_id": "0x1A3",
            "ack_payload_hex": "010203",
            "receive_monotonic_ns": 2_000_050_000,
            "send_success": True,
        }
    ]
    candump = [
        {"record_index": 1, "realtime_ns": 1_000, "interface": "vcan0", "can_id": 0x123, "payload_hex": "010203"},
        {"record_index": 2, "realtime_ns": 2_000, "interface": "vcan0", "can_id": 0x1A3, "payload_hex": "010203"},
    ]
    return runtime, responder, candump


class SocketCanAckLifecycleAdapterTest(unittest.TestCase):
    def test_parses_candump_log_frame(self) -> None:
        parsed = parse_candump_line("(1773734400.123456) vcan0 123#010203", 7)

        self.assertEqual(parsed["record_index"], 7)
        self.assertEqual(parsed["interface"], "vcan0")
        self.assertEqual(parsed["can_id"], 0x123)
        self.assertEqual(parsed["payload_hex"], "010203")
        self.assertEqual(parsed["realtime_ns"], 1_773_734_400_123_456_000)

    def test_derives_drop_retry_exhaustion_with_three_source_coverage(self) -> None:
        run, oracle, capture = manifests("injected")
        runtime, responder, candump = injected_sources()

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime,
            responder,
            candump,
            run,
            oracle,
            capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "socketcan_ack_lifecycle_terminal")
        self.assertEqual(events[0].attributes["terminal_state"], "retry_exhausted")
        self.assertEqual(events[0].attributes["attempt_count"], 3)
        self.assertEqual(events[0].attributes["matched_command_frame_count"], 3)
        self.assertEqual(events[0].attributes["matched_responder_count"], 3)
        self.assertTrue(events[0].attributes["socketcan_evidence"])
        self.assertTrue(events[0].attributes["virtual_can_bus"])
        self.assertFalse(events[0].attributes["physical_can_evidence"])
        self.assertEqual(report["retry_exhausted_rate"], 1.0)
        self.assertEqual(report["command_frame_match_coverage"], 1.0)
        self.assertEqual(report["responder_match_coverage"], 1.0)

    def test_derives_echo_ack_success_and_matches_ack_frame(self) -> None:
        run, oracle, capture = manifests("control")
        runtime, responder, candump = control_sources()

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime,
            responder,
            candump,
            run,
            oracle,
            capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(events[0].attributes["terminal_state"], "ack_received")
        self.assertEqual(events[0].attributes["matched_ack_frame_count"], 1)
        self.assertEqual(report["ack_success_rate"], 1.0)
        self.assertEqual(report["ack_frame_match_coverage"], 1.0)

    def test_payload_mismatch_is_reported_instead_of_silently_matched(self) -> None:
        run, oracle, capture = manifests("control")
        runtime, responder, candump = control_sources()
        responder[0]["command_payload_hex"] = "ffffff"

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime,
            responder,
            candump,
            run,
            oracle,
            capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_reason_counts"], {"missing_responder_observation": 1})

    def test_drop_rejects_an_unexpected_ack_frame(self) -> None:
        run, oracle, capture = manifests("injected")
        runtime, responder, candump = injected_sources()
        candump.append(
            {"record_index": 4, "realtime_ns": 4_000, "interface": "vcan0", "can_id": 0x1A3, "payload_hex": "010203"}
        )

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime, responder, candump, run, oracle, capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_reason_counts"], {"unexpected_candump_ack": 1})

    def test_drop_rejects_an_ack_received_terminal(self) -> None:
        run, oracle, capture = manifests("injected")
        runtime, responder, candump = control_sources()
        responder[0].update(
            {
                "session_id": "session-injected",
                "policy": "drop",
                "decision": "drop",
                "send_success": None,
            }
        )
        candump = candump[:1]

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime, responder, candump, run, oracle, capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["invalid_pair_reason_counts"], {"terminal_variant_mismatch": 1})

    def test_rejects_mock_profile_and_physical_can_claim(self) -> None:
        run, oracle, capture = manifests("control")
        runtime, responder, candump = control_sources()
        oracle["injection"]["ack_mode"] = "mock"
        capture["physical_can_evidence"] = True

        events, report = derive_socketcan_ack_lifecycle_evidence(
            runtime,
            responder,
            candump,
            run,
            oracle,
            capture,
            runtime_source_file="runtime.jsonl",
            responder_source_file="responder.jsonl",
            candump_source_file="candump.log",
            run_manifest_source_file="run.json",
            oracle_manifest_source_file="oracle.json",
            capture_manifest_source_file="capture.json",
        )

        self.assertEqual(events, [])
        self.assertEqual(report["status"], "invalid")
        self.assertIn(report["reason_code"], {"oracle_profile_mismatch", "invalid_capture_manifest"})


if __name__ == "__main__":
    unittest.main()
