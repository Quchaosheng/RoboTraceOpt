import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.fault_injection.socketcan_capture import (
    build_candump_command,
    build_capture_manifest,
    build_responder_command,
    wait_for_responder_ready,
)
from scripts import run_fault_condition


class FakeProcess:
    def __init__(self, returncode=None, pid=1234) -> None:
        self.returncode = returncode
        self.pid = pid

    def poll(self):
        return self.returncode


def profile(policy: str = "echo") -> dict[str, object]:
    return {
        "transport_profile": "vcan",
        "ack_mode": "socketcan",
        "mock_mode": False,
        "can_interface": "vcan0",
        "ack_can_id_offset": 128,
        "responder_delay_ms": 5,
        "responder_policy": policy,
    }


class SocketCanCaptureTest(unittest.TestCase):
    @patch.object(run_fault_condition, "start_socketcan_capture", create=True)
    def test_runner_starts_capture_only_for_f6_vcan(self, start_capture) -> None:
        frozen_profile = profile("drop")
        sentinel = object()
        start_capture.return_value = sentinel

        started = run_fault_condition.start_f6_socketcan_capture(
            fault_id="F6",
            f6_transport_profile="vcan",
            f6_injection=frozen_profile,
            output_dir=Path("/tmp/condition"),
            session_id="session-1",
            condition_variant="injected",
        )

        self.assertIs(started, sentinel)
        start_capture.assert_called_once_with(
            frozen_profile,
            Path("/tmp/condition"),
            session_id="session-1",
            condition_variant="injected",
            cwd=run_fault_condition.REPOSITORY_ROOT,
        )
        start_capture.reset_mock()
        self.assertIsNone(
            run_fault_condition.start_f6_socketcan_capture(
                fault_id="F6",
                f6_transport_profile="mock",
                f6_injection=None,
                output_dir=Path("/tmp/mock"),
                session_id="session-2",
                condition_variant="control",
            )
        )
        start_capture.assert_not_called()

    def test_builds_fixed_candump_and_responder_commands(self) -> None:
        responder = build_responder_command(
            profile("drop"), Path("/tmp/responder.jsonl"), "session-1"
        )

        self.assertEqual(build_candump_command("vcan0"), ["candump", "-L", "vcan0"])
        self.assertEqual(responder[:3], ["python3", "-m", "experiments.fault_injection.socketcan_responder"])
        self.assertIn("--policy", responder)
        self.assertIn("drop", responder)
        self.assertIn("--delay-ms", responder)
        self.assertIn("5", responder)
        self.assertIn("/tmp/responder.jsonl", responder)

    def test_rejects_invalid_capture_command_inputs(self) -> None:
        with self.assertRaises(ValueError):
            build_candump_command("vcan0;rm")
        with self.assertRaises(ValueError):
            build_responder_command(profile("invalid"), Path("out.jsonl"), "session")
        with self.assertRaises(ValueError):
            build_responder_command(profile(), Path("out.jsonl"), "")

    def test_waits_for_matching_responder_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "responder.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "socketcan-responder/v1",
                        "record_type": "responder_ready",
                        "session_id": "session-1",
                        "interface": "vcan0",
                        "policy": "echo",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            ready = wait_for_responder_ready(
                path,
                FakeProcess(),
                session_id="session-1",
                interface="vcan0",
                policy="echo",
                timeout_seconds=0.1,
                poll_seconds=0.001,
            )

        self.assertEqual(ready["record_type"], "responder_ready")

    def test_readiness_rejects_early_exit_wrong_identity_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "responder.jsonl"
            with self.assertRaisesRegex(RuntimeError, "exited"):
                wait_for_responder_ready(
                    path,
                    FakeProcess(returncode=2),
                    session_id="session-1",
                    interface="vcan0",
                    policy="echo",
                    timeout_seconds=0.1,
                    poll_seconds=0.001,
                )
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "socketcan-responder/v1",
                        "record_type": "responder_ready",
                        "session_id": "wrong",
                        "interface": "vcan0",
                        "policy": "echo",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "identity"):
                wait_for_responder_ready(
                    path,
                    FakeProcess(),
                    session_id="session-1",
                    interface="vcan0",
                    policy="echo",
                    timeout_seconds=0.1,
                    poll_seconds=0.001,
                )
            path.unlink()
            with self.assertRaisesRegex(TimeoutError, "readiness"):
                wait_for_responder_ready(
                    path,
                    FakeProcess(),
                    session_id="session-1",
                    interface="vcan0",
                    policy="echo",
                    timeout_seconds=0.01,
                    poll_seconds=0.001,
                )

    def test_capture_manifest_hashes_nonempty_complete_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            responder_path = root / "responder.jsonl"
            candump_path = root / "candump.log"
            records = [
                {
                    "schema_version": "socketcan-responder/v1",
                    "record_type": "responder_ready",
                    "session_id": "session-1",
                    "interface": "vcan0",
                    "policy": "echo",
                },
                {
                    "schema_version": "socketcan-responder/v1",
                    "record_type": "command_observed",
                    "session_id": "session-1",
                    "interface": "vcan0",
                    "policy": "echo",
                },
                {
                    "schema_version": "socketcan-responder/v1",
                    "record_type": "responder_stopped",
                    "session_id": "session-1",
                    "interface": "vcan0",
                    "policy": "echo",
                },
            ]
            responder_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            candump_path.write_text("(1.000001) vcan0 123#01\n", encoding="utf-8")

            manifest = build_capture_manifest(
                session_id="session-1",
                condition_variant="control",
                capture_profile=profile(),
                responder_path=responder_path,
                candump_path=candump_path,
                responder_command=["python3", "responder"],
                candump_command=["candump", "-L", "vcan0"],
                responder_pid=12,
                candump_pid=13,
                responder_cleanup_status="graceful_sigint",
                candump_cleanup_status="graceful_sigint",
                interface_state={"ifname": "vcan0", "linkinfo": {"info_kind": "vcan"}},
                candump_identity={"path": "/usr/bin/candump", "help_sha256": "a" * 64},
            )

        self.assertEqual(manifest["schema_version"], "socketcan-capture/v1")
        self.assertEqual(manifest["responder"]["command_observed_count"], 1)
        self.assertEqual(len(manifest["responder"]["sha256"]), 64)
        self.assertEqual(len(manifest["responder"]["script_sha256"]), 64)
        self.assertEqual(len(manifest["candump"]["sha256"]), 64)
        self.assertTrue(manifest["socketcan_evidence"])
        self.assertTrue(manifest["virtual_can_bus"])
        self.assertFalse(manifest["physical_can_evidence"])

    def test_capture_manifest_rejects_incomplete_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            responder_path = root / "responder.jsonl"
            candump_path = root / "candump.log"
            responder_path.write_text("", encoding="utf-8")
            candump_path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "responder evidence"):
                build_capture_manifest(
                    session_id="session-1",
                    condition_variant="control",
                    capture_profile=profile(),
                    responder_path=responder_path,
                    candump_path=candump_path,
                    responder_command=["python3"],
                    candump_command=["candump"],
                    responder_pid=12,
                    candump_pid=13,
                    responder_cleanup_status="graceful_sigint",
                    candump_cleanup_status="graceful_sigint",
                    interface_state={"ifname": "vcan0"},
                    candump_identity={"path": "/usr/bin/candump"},
                )


if __name__ == "__main__":
    unittest.main()
