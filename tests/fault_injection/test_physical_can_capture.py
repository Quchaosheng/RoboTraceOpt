import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.fault_injection.socketcan_capture import (
    build_capture_manifest,
    build_responder_command,
)
from scripts import run_fault_condition


def link(name: str) -> dict:
    return {
        "ifname": name,
        "flags": ["UP", "LOWER_UP"],
        "linkinfo": {
            "info_kind": "can",
            "info_data": {
                "state": "ERROR-ACTIVE",
                "bittiming": {"bitrate": 500000},
            },
        },
    }


def profile(policy: str = "echo") -> dict:
    return {
        "transport_profile": "physical",
        "ack_mode": "socketcan",
        "mock_mode": False,
        "can_interface": "can0",
        "responder_interface": "can1",
        "bitrate": 500000,
        "ack_can_id_offset": 128,
        "responder_delay_ms": 5,
        "responder_policy": policy,
    }


class PhysicalCanCaptureTest(unittest.TestCase):
    def test_responder_binds_to_peer_interface(self) -> None:
        command = build_responder_command(
            profile("drop"), Path("/tmp/responder.jsonl"), "session-1"
        )

        interface_index = command.index("--interface") + 1
        self.assertEqual(command[interface_index], "can1")

    @patch.object(run_fault_condition, "start_socketcan_capture", create=True)
    def test_fault_runner_starts_physical_capture(self, start_capture) -> None:
        frozen_profile = profile("drop")
        start_capture.return_value = object()

        result = run_fault_condition.start_f6_socketcan_capture(
            fault_id="F6",
            f6_transport_profile="physical",
            f6_injection=frozen_profile,
            output_dir=Path("/tmp/physical"),
            session_id="session-1",
            condition_variant="injected",
        )

        self.assertIs(result, start_capture.return_value)

    def test_manifest_requires_before_and_after_physical_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            responder = root / "responder.jsonl"
            candump = root / "candump.log"
            records = [
                {
                    "schema_version": "socketcan-responder/v1",
                    "record_type": record_type,
                    "session_id": "session-1",
                    "interface": "can1",
                    "policy": "echo",
                }
                for record_type in (
                    "responder_ready",
                    "command_observed",
                    "responder_stopped",
                )
            ]
            responder.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            candump.write_text("(1.000001) can1 123#01\n", encoding="utf-8")
            pair = {"runtime": link("can0"), "peer": link("can1"), "bitrate": 500000}

            manifest = build_capture_manifest(
                session_id="session-1",
                condition_variant="control",
                capture_profile=profile(),
                responder_path=responder,
                candump_path=candump,
                responder_command=["python3", "responder"],
                candump_command=["candump", "-L", "can1"],
                responder_pid=12,
                candump_pid=13,
                responder_cleanup_status="graceful_sigint",
                candump_cleanup_status="graceful_sigint",
                interface_state=link("can1"),
                candump_identity={"path": "/usr/bin/candump", "help_sha256": "a" * 64},
                interface_pair_before=pair,
                interface_pair_after=pair,
            )

        self.assertEqual(manifest["schema_version"], "socketcan-capture/v2")
        self.assertFalse(manifest["virtual_can_bus"])
        self.assertTrue(manifest["physical_can_evidence"])
        self.assertEqual(
            manifest["interface_pair"]["before"]["runtime"]["ifname"], "can0"
        )
        self.assertEqual(manifest["interface_pair"]["after"]["peer"]["ifname"], "can1")

    def test_manifest_rejects_virtual_peer_claim(self) -> None:
        pair = {"runtime": link("can0"), "peer": link("can1"), "bitrate": 500000}
        pair["peer"]["linkinfo"]["info_kind"] = "vcan"
        with self.assertRaisesRegex(ValueError, "physical CAN"):
            build_capture_manifest(
                session_id="session-1",
                condition_variant="control",
                capture_profile=profile(),
                responder_path=Path("missing"),
                candump_path=Path("missing"),
                responder_command=[],
                candump_command=[],
                responder_pid=12,
                candump_pid=13,
                responder_cleanup_status="graceful_sigint",
                candump_cleanup_status="graceful_sigint",
                interface_state=link("can1"),
                candump_identity={"path": "/usr/bin/candump", "help_sha256": "a" * 64},
                interface_pair_before=pair,
                interface_pair_after=pair,
            )


if __name__ == "__main__":
    unittest.main()
