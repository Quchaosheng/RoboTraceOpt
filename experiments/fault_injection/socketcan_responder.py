"""Observe F6 command frames and deterministically echo or drop vcan ACKs."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


SCHEMA_VERSION = "socketcan-responder/v1"
CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_FLAG = 0x80000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x7FF
COMMAND_ID_MIN = 0x100
COMMAND_ID_MAX = 0x17F


@dataclass(frozen=True)
class ResponseDecision:
    command_can_id: int
    command_payload: bytes
    ack_can_id: int
    ack_payload: bytes
    should_send: bool
    decision: str


def decide_response(
    *,
    can_id: int,
    payload: bytes,
    policy: str,
    ack_can_id_offset: int,
) -> ResponseDecision:
    if not isinstance(can_id, int) or isinstance(can_id, bool):
        raise ValueError("CAN ID must be an integer")
    if not COMMAND_ID_MIN <= can_id <= COMMAND_ID_MAX:
        raise ValueError("command CAN ID is outside the F6 command range")
    if not isinstance(payload, bytes) or len(payload) > 8:
        raise ValueError("classic CAN payload must contain at most eight bytes")
    if policy not in {"echo", "drop"}:
        raise ValueError(f"unsupported responder policy: {policy}")
    if not isinstance(ack_can_id_offset, int) or isinstance(ack_can_id_offset, bool):
        raise ValueError("ACK CAN ID offset must be an integer")
    ack_can_id = can_id + ack_can_id_offset
    if ack_can_id_offset <= 0 or ack_can_id > CAN_SFF_MASK:
        raise ValueError("ACK CAN ID is outside the standard 11-bit range")
    return ResponseDecision(
        command_can_id=can_id,
        command_payload=payload,
        ack_can_id=ack_can_id,
        ack_payload=payload,
        should_send=policy == "echo",
        decision=policy,
    )


def encode_can_frame(
    can_id: int, payload: bytes, *, allow_flags: bool = False
) -> bytes:
    if not isinstance(can_id, int) or isinstance(can_id, bool):
        raise ValueError("CAN ID must be an integer")
    if not isinstance(payload, bytes) or len(payload) > 8:
        raise ValueError("classic CAN payload must contain at most eight bytes")
    if can_id < 0 or (not allow_flags and can_id > CAN_SFF_MASK):
        raise ValueError("CAN ID is outside the standard 11-bit range")
    if allow_flags and can_id > 0xFFFFFFFF:
        raise ValueError("flagged CAN ID exceeds 32 bits")
    return CAN_FRAME.pack(can_id, len(payload), payload.ljust(8, b"\0"))


def decode_can_frame(frame: bytes) -> tuple[int, bytes]:
    if len(frame) != CAN_FRAME.size:
        raise ValueError("Linux classic CAN frame must be 16 bytes")
    can_id, payload_length, padded_payload = CAN_FRAME.unpack(frame)
    if payload_length > 8:
        raise ValueError("classic CAN frame has an invalid payload length")
    return can_id & CAN_EFF_MASK, padded_payload[:payload_length]


def build_ready_record(
    *,
    session_id: str,
    interface: str,
    policy: str,
    ack_can_id_offset: int,
    delay_ms: int,
    monotonic_ns: int,
    realtime_ns: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "responder_ready",
        "session_id": session_id,
        "interface": interface,
        "policy": policy,
        "ack_can_id_offset": ack_can_id_offset,
        "delay_ms": delay_ms,
        "monotonic_ns": monotonic_ns,
        "realtime_ns": realtime_ns,
    }


def build_observation_record(
    decision: ResponseDecision,
    *,
    session_id: str,
    interface: str,
    policy: str,
    delay_ms: int,
    receive_monotonic_ns: int,
    receive_realtime_ns: int,
    decision_monotonic_ns: int,
    decision_realtime_ns: int,
    send_monotonic_ns: int | None,
    send_realtime_ns: int | None,
    send_success: bool | None,
    send_error: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "command_observed",
        "session_id": session_id,
        "interface": interface,
        "policy": policy,
        "delay_ms": delay_ms,
        "receive_monotonic_ns": receive_monotonic_ns,
        "receive_realtime_ns": receive_realtime_ns,
        "decision_monotonic_ns": decision_monotonic_ns,
        "decision_realtime_ns": decision_realtime_ns,
        "send_monotonic_ns": send_monotonic_ns,
        "send_realtime_ns": send_realtime_ns,
        "command_can_id": _format_can_id(decision.command_can_id),
        "command_payload_hex": decision.command_payload.hex(),
        "decision": decision.decision,
        "ack_can_id": _format_can_id(decision.ack_can_id),
        "ack_payload_hex": decision.ack_payload.hex(),
        "send_success": send_success,
        "send_error": send_error,
    }


def _format_can_id(can_id: int) -> str:
    return f"0x{can_id:03X}"


def _write_record(handle: TextIO, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--policy", choices=("echo", "drop"), required=True)
    parser.add_argument("--ack-can-id-offset", type=int, required=True)
    parser.add_argument("--delay-ms", type=int, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.interface or not args.session_id:
        raise ValueError("interface and session ID are required")
    if args.delay_ms < 0:
        raise ValueError("delay-ms must be non-negative")
    if args.output_jsonl.exists():
        raise ValueError(f"responder output already exists: {args.output_jsonl}")
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    with socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as can_socket:
        can_socket.bind((args.interface,))
        can_socket.settimeout(0.2)
        with args.output_jsonl.open("x", encoding="utf-8", buffering=1) as output:
            _write_record(
                output,
                build_ready_record(
                    session_id=args.session_id,
                    interface=args.interface,
                    policy=args.policy,
                    ack_can_id_offset=args.ack_can_id_offset,
                    delay_ms=args.delay_ms,
                    monotonic_ns=time.monotonic_ns(),
                    realtime_ns=time.time_ns(),
                ),
            )
            while not stopping:
                try:
                    frame = can_socket.recv(CAN_FRAME.size)
                except TimeoutError:
                    continue
                receive_monotonic_ns = time.monotonic_ns()
                receive_realtime_ns = time.time_ns()
                can_id, payload = decode_can_frame(frame)
                if not COMMAND_ID_MIN <= can_id <= COMMAND_ID_MAX:
                    continue
                decision = decide_response(
                    can_id=can_id,
                    payload=payload,
                    policy=args.policy,
                    ack_can_id_offset=args.ack_can_id_offset,
                )
                time.sleep(args.delay_ms / 1000.0)
                send_success: bool | None = None
                send_error = ""
                send_monotonic_ns: int | None = None
                send_realtime_ns: int | None = None
                if decision.should_send:
                    send_monotonic_ns = time.monotonic_ns()
                    send_realtime_ns = time.time_ns()
                    try:
                        can_socket.send(
                            encode_can_frame(decision.ack_can_id, decision.ack_payload)
                        )
                        send_success = True
                    except OSError as error:
                        send_success = False
                        send_error = str(error)
                _write_record(
                    output,
                    build_observation_record(
                        decision,
                        session_id=args.session_id,
                        interface=args.interface,
                        policy=args.policy,
                        delay_ms=args.delay_ms,
                        receive_monotonic_ns=receive_monotonic_ns,
                        receive_realtime_ns=receive_realtime_ns,
                        decision_monotonic_ns=time.monotonic_ns(),
                        decision_realtime_ns=time.time_ns(),
                        send_monotonic_ns=send_monotonic_ns,
                        send_realtime_ns=send_realtime_ns,
                        send_success=send_success,
                        send_error=send_error,
                    ),
                )
            _write_record(
                output,
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "responder_stopped",
                    "session_id": args.session_id,
                    "interface": args.interface,
                    "policy": args.policy,
                    "monotonic_ns": time.monotonic_ns(),
                    "realtime_ns": time.time_ns(),
                },
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
