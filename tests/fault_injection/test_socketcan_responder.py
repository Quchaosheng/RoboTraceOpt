import unittest

from experiments.fault_injection.socketcan_responder import (
    build_observation_record,
    build_ready_record,
    decode_can_frame,
    decide_response,
    encode_can_frame,
)


class SocketCanResponderTest(unittest.TestCase):
    def test_echo_preserves_payload_and_offsets_ack_id(self) -> None:
        decision = decide_response(
            can_id=0x123,
            payload=bytes.fromhex("010203"),
            policy="echo",
            ack_can_id_offset=128,
        )

        self.assertEqual(decision.command_can_id, 0x123)
        self.assertEqual(decision.command_payload, bytes.fromhex("010203"))
        self.assertEqual(decision.ack_can_id, 0x1A3)
        self.assertEqual(decision.ack_payload, bytes.fromhex("010203"))
        self.assertTrue(decision.should_send)
        self.assertEqual(decision.decision, "echo")

    def test_drop_records_identity_without_sending(self) -> None:
        decision = decide_response(
            can_id=0x17F,
            payload=b"abc",
            policy="drop",
            ack_can_id_offset=128,
        )

        self.assertFalse(decision.should_send)
        self.assertEqual(decision.decision, "drop")
        self.assertEqual(decision.ack_can_id, 0x1FF)
        self.assertEqual(decision.ack_payload, b"abc")

    def test_rejects_invalid_frame_or_policy(self) -> None:
        cases = (
            {"can_id": 0x0FF, "payload": b"", "policy": "echo", "ack_can_id_offset": 128},
            {"can_id": 0x180, "payload": b"", "policy": "echo", "ack_can_id_offset": 128},
            {"can_id": 0x123, "payload": b"123456789", "policy": "echo", "ack_can_id_offset": 128},
            {"can_id": 0x123, "payload": b"", "policy": "success", "ack_can_id_offset": 128},
            {"can_id": 0x123, "payload": b"", "policy": "echo", "ack_can_id_offset": 0x700},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                decide_response(**values)

    def test_linux_can_frame_round_trip_masks_flags(self) -> None:
        encoded = encode_can_frame(0x123, bytes.fromhex("0102030405"))

        can_id, payload = decode_can_frame(encoded)

        self.assertEqual(len(encoded), 16)
        self.assertEqual(can_id, 0x123)
        self.assertEqual(payload, bytes.fromhex("0102030405"))
        flagged = encode_can_frame(0x123 | 0x80000000, b"x", allow_flags=True)
        self.assertEqual(decode_can_frame(flagged), (0x123, b"x"))

    def test_evidence_records_include_session_policy_and_both_clocks(self) -> None:
        ready = build_ready_record(
            session_id="session-1",
            interface="vcan0",
            policy="echo",
            ack_can_id_offset=128,
            delay_ms=5,
            monotonic_ns=100,
            realtime_ns=200,
        )
        decision = decide_response(
            can_id=0x123,
            payload=b"abc",
            policy="echo",
            ack_can_id_offset=128,
        )
        observed = build_observation_record(
            decision,
            session_id="session-1",
            interface="vcan0",
            policy="echo",
            delay_ms=5,
            receive_monotonic_ns=110,
            receive_realtime_ns=210,
            decision_monotonic_ns=120,
            decision_realtime_ns=220,
            send_monotonic_ns=119,
            send_realtime_ns=219,
            send_success=True,
            send_error="",
        )

        self.assertEqual(ready["schema_version"], "socketcan-responder/v1")
        self.assertEqual(ready["record_type"], "responder_ready")
        self.assertEqual(ready["session_id"], "session-1")
        self.assertEqual(ready["monotonic_ns"], 100)
        self.assertEqual(ready["realtime_ns"], 200)
        self.assertEqual(observed["record_type"], "command_observed")
        self.assertEqual(observed["command_can_id"], "0x123")
        self.assertEqual(observed["command_payload_hex"], "616263")
        self.assertEqual(observed["ack_can_id"], "0x1A3")
        self.assertEqual(observed["ack_payload_hex"], "616263")
        self.assertEqual(observed["decision"], "echo")
        self.assertEqual(observed["send_monotonic_ns"], 119)
        self.assertEqual(observed["send_realtime_ns"], 219)
        self.assertTrue(observed["send_success"])


if __name__ == "__main__":
    unittest.main()
