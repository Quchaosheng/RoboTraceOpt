import json
import unittest

from diagnosis.adapters.socketcan_ack_lifecycle_adapter import (
    derive_socketcan_ack_lifecycle_evidence,
)
from tests.adapters.test_socketcan_ack_lifecycle_adapter import (
    control_sources,
    manifests,
)


def physical_sources():
    run, oracle, capture = manifests("control")
    oracle["injection"].update(
        {
            "transport_profile": "physical",
            "can_interface": "can0",
            "responder_interface": "can1",
            "bitrate": 500000,
        }
    )
    capture.update(
        {
            "schema_version": "socketcan-capture/v2",
            "capture_profile": dict(oracle["injection"]),
            "virtual_can_bus": False,
            "physical_can_evidence": True,
            "interface_pair": {
                "before": {"runtime": {"ifname": "can0"}, "peer": {"ifname": "can1"}},
                "after": {"runtime": {"ifname": "can0"}, "peer": {"ifname": "can1"}},
            },
        }
    )
    runtime, responder, candump = control_sources()
    for record in runtime:
        extra = json.loads(record["extra_json"])
        extra["can_interface"] = "can0"
        record["extra_json"] = json.dumps(extra)
    responder[0]["interface"] = "can1"
    for record in candump:
        record["interface"] = "can1"
    return run, oracle, capture, runtime, responder, candump


class PhysicalCanAckLifecycleAdapterTest(unittest.TestCase):
    def test_derives_physical_evidence_across_runtime_and_peer_interfaces(self) -> None:
        run, oracle, capture, runtime, responder, candump = physical_sources()

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
        self.assertTrue(report["physical_can_evidence"])
        self.assertFalse(report["virtual_can_bus"])
        self.assertEqual(
            report["measurement_semantics"],
            "application_socketcan_physical_ack_lifecycle",
        )
        self.assertTrue(events[0].attributes["physical_can_evidence"])
        self.assertEqual(events[0].attributes["capture_interface"], "can1")

    def test_rejects_physical_profile_with_virtual_capture_flags(self) -> None:
        run, oracle, capture, runtime, responder, candump = physical_sources()
        capture["virtual_can_bus"] = True

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
        self.assertEqual(report["reason_code"], "invalid_capture_manifest")


if __name__ == "__main__":
    unittest.main()
