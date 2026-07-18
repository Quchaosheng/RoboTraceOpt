"""Own the candump and responder lifecycle for matched F6 vcan runs."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from experiments.fault_injection.scheduling_pressure import (
    start_isolated_process,
    stop_process,
)


INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
RESPONDER_SCHEMA = "socketcan-responder/v1"


@dataclass
class SocketCanCapture:
    session_id: str
    condition_variant: str
    profile: dict[str, Any]
    responder_path: Path
    candump_path: Path
    responder_log_path: Path
    responder_command: list[str]
    candump_command: list[str]
    responder_process: subprocess.Popen
    candump_process: subprocess.Popen
    responder_log_handle: TextIO
    candump_handle: TextIO
    interface_state: dict[str, Any]
    candump_identity: dict[str, Any]


def build_candump_command(interface: str) -> list[str]:
    _validate_interface(interface)
    return ["candump", "-L", interface]


def build_responder_command(
    profile: dict[str, Any], output_path: Path, session_id: str
) -> list[str]:
    _validate_profile(profile)
    if not session_id:
        raise ValueError("responder session ID is required")
    return [
        "python3",
        "-m",
        "experiments.fault_injection.socketcan_responder",
        "--interface",
        str(profile["can_interface"]),
        "--policy",
        str(profile["responder_policy"]),
        "--ack-can-id-offset",
        str(profile["ack_can_id_offset"]),
        "--delay-ms",
        str(profile["responder_delay_ms"]),
        "--session-id",
        session_id,
        "--output-jsonl",
        str(output_path),
    ]


def wait_for_responder_ready(
    path: Path,
    process: Any,
    *,
    session_id: str,
    interface: str,
    policy: str,
    timeout_seconds: float = 3.0,
    poll_seconds: float = 0.05,
) -> dict[str, Any]:
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("readiness timeouts must be positive")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"SocketCAN responder exited before readiness with status {returncode}"
            )
        if path.is_file() and path.stat().st_size:
            records = _read_jsonl(path)
            ready = next(
                (
                    record
                    for record in records
                    if record.get("record_type") == "responder_ready"
                ),
                None,
            )
            if ready is not None:
                if (
                    ready.get("schema_version") != RESPONDER_SCHEMA
                    or ready.get("session_id") != session_id
                    or ready.get("interface") != interface
                    or ready.get("policy") != policy
                ):
                    raise RuntimeError("responder readiness identity mismatch")
                return ready
        time.sleep(poll_seconds)
    raise TimeoutError("timed out waiting for responder readiness")


def capture_interface_state(interface: str) -> dict[str, Any]:
    _validate_interface(interface)
    completed = subprocess.run(
        ["ip", "-details", "-json", "link", "show", interface],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot inspect {interface}: {completed.stderr.strip()}")
    try:
        records = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("ip returned invalid JSON") from error
    if (
        not isinstance(records, list)
        or len(records) != 1
        or not isinstance(records[0], dict)
    ):
        raise RuntimeError(f"expected exactly one interface record for {interface}")
    record = records[0]
    if (
        record.get("ifname") != interface
        or record.get("linkinfo", {}).get("info_kind") != "vcan"
        or "UP" not in record.get("flags", [])
    ):
        raise RuntimeError(f"{interface} is not an UP vcan interface")
    return record


def capture_candump_identity() -> dict[str, Any]:
    executable = shutil.which("candump")
    if not executable:
        raise RuntimeError("candump is not installed")
    completed = subprocess.run(
        [executable, "-h"], check=False, capture_output=True, text=True
    )
    help_text = f"{completed.stdout}\n{completed.stderr}".strip()
    if not help_text:
        raise RuntimeError("candump returned no identity/help output")
    return {
        "path": executable,
        "help_command": [executable, "-h"],
        "help_returncode": completed.returncode,
        "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
    }


def start_socketcan_capture(
    profile: dict[str, Any],
    output_dir: Path,
    *,
    session_id: str,
    condition_variant: str,
    cwd: Path,
) -> SocketCanCapture:
    _validate_profile(profile)
    if condition_variant not in {"injected", "control"}:
        raise ValueError("invalid F6 condition variant")
    output_dir.mkdir(parents=True, exist_ok=True)
    responder_path = output_dir / "responder.jsonl"
    candump_path = output_dir / "candump.log"
    responder_log_path = output_dir / "responder.log"
    for path in (responder_path, candump_path, responder_log_path):
        if path.exists():
            raise ValueError(f"SocketCAN capture output already exists: {path}")

    interface = str(profile["can_interface"])
    interface_state = capture_interface_state(interface)
    candump_identity = capture_candump_identity()
    candump_command = build_candump_command(interface)
    responder_command = build_responder_command(profile, responder_path, session_id)
    candump_handle = candump_path.open("x", encoding="utf-8")
    responder_log_handle = responder_log_path.open("x", encoding="utf-8")
    candump_process = None
    responder_process = None
    try:
        candump_process = start_isolated_process(
            candump_command, cwd=cwd, output=candump_handle
        )
        time.sleep(0.1)
        if candump_process.poll() is not None:
            raise RuntimeError("candump exited during startup")
        responder_process = start_isolated_process(
            responder_command, cwd=cwd, output=responder_log_handle
        )
        wait_for_responder_ready(
            responder_path,
            responder_process,
            session_id=session_id,
            interface=interface,
            policy=str(profile["responder_policy"]),
        )
    except BaseException:
        if responder_process is not None:
            stop_process(responder_process, 2.0)
        if candump_process is not None:
            stop_process(candump_process, 2.0)
        responder_log_handle.close()
        candump_handle.close()
        raise

    return SocketCanCapture(
        session_id=session_id,
        condition_variant=condition_variant,
        profile=dict(profile),
        responder_path=responder_path,
        candump_path=candump_path,
        responder_log_path=responder_log_path,
        responder_command=responder_command,
        candump_command=candump_command,
        responder_process=responder_process,
        candump_process=candump_process,
        responder_log_handle=responder_log_handle,
        candump_handle=candump_handle,
        interface_state=interface_state,
        candump_identity=candump_identity,
    )


def stop_socketcan_capture(
    capture: SocketCanCapture, output_path: Path
) -> dict[str, Any]:
    responder_cleanup = stop_process(capture.responder_process, 3.0)
    candump_cleanup = stop_process(capture.candump_process, 3.0)
    capture.responder_log_handle.close()
    capture.candump_handle.close()
    manifest = build_capture_manifest(
        session_id=capture.session_id,
        condition_variant=capture.condition_variant,
        capture_profile=capture.profile,
        responder_path=capture.responder_path,
        candump_path=capture.candump_path,
        responder_command=capture.responder_command,
        candump_command=capture.candump_command,
        responder_pid=capture.responder_process.pid,
        candump_pid=capture.candump_process.pid,
        responder_cleanup_status=responder_cleanup,
        candump_cleanup_status=candump_cleanup,
        interface_state=capture.interface_state,
        candump_identity=capture.candump_identity,
    )
    if output_path.exists():
        raise ValueError(f"SocketCAN capture manifest already exists: {output_path}")
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def build_capture_manifest(
    *,
    session_id: str,
    condition_variant: str,
    capture_profile: dict[str, Any],
    responder_path: Path,
    candump_path: Path,
    responder_command: list[str],
    candump_command: list[str],
    responder_pid: int,
    candump_pid: int,
    responder_cleanup_status: str,
    candump_cleanup_status: str,
    interface_state: dict[str, Any],
    candump_identity: dict[str, Any],
) -> dict[str, Any]:
    _validate_profile(capture_profile)
    if condition_variant not in {"injected", "control"}:
        raise ValueError("invalid F6 condition variant")
    if responder_cleanup_status != "graceful_sigint":
        raise ValueError("responder did not stop gracefully")
    if candump_cleanup_status != "graceful_sigint":
        raise ValueError("candump did not stop gracefully")
    if not responder_path.is_file() or responder_path.stat().st_size == 0:
        raise ValueError("responder evidence is empty")
    records = _read_jsonl(responder_path)
    expected_identity = (
        session_id,
        capture_profile["can_interface"],
        capture_profile["responder_policy"],
    )
    if any(
        (
            record.get("schema_version") != RESPONDER_SCHEMA
            or (
                record.get("session_id"),
                record.get("interface"),
                record.get("policy"),
            )
            != expected_identity
        )
        for record in records
    ):
        raise ValueError("responder evidence identity mismatch")
    counts = {
        record_type: sum(record.get("record_type") == record_type for record in records)
        for record_type in ("responder_ready", "command_observed", "responder_stopped")
    }
    if counts["responder_ready"] != 1 or counts["responder_stopped"] != 1:
        raise ValueError("responder evidence lifecycle is incomplete")
    if counts["command_observed"] < 1:
        raise ValueError("responder evidence contains no command observations")
    if not candump_path.is_file() or candump_path.stat().st_size == 0:
        raise ValueError("candump evidence is empty")
    candump_lines = [
        line
        for line in candump_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not candump_lines:
        raise ValueError("candump evidence is empty")
    if interface_state.get("ifname") != capture_profile["can_interface"]:
        raise ValueError("capture interface identity mismatch")
    if interface_state.get("linkinfo", {}).get("info_kind") != "vcan":
        raise ValueError("capture interface is not vcan")
    if not candump_identity.get("path") or not candump_identity.get("help_sha256"):
        raise ValueError("candump identity is incomplete")
    responder_script = Path(__file__).with_name("socketcan_responder.py")
    return {
        "schema_version": "socketcan-capture/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "condition_variant": condition_variant,
        "capture_profile": dict(capture_profile),
        "socketcan_evidence": True,
        "virtual_can_bus": True,
        "physical_can_evidence": False,
        "interface_state": interface_state,
        "candump_identity": candump_identity,
        "responder": {
            "path": str(responder_path),
            "size_bytes": responder_path.stat().st_size,
            "sha256": _sha256(responder_path),
            "script_path": str(responder_script),
            "script_sha256": _sha256(responder_script),
            "argv": list(responder_command),
            "pid": responder_pid,
            "cleanup_status": responder_cleanup_status,
            **{f"{key}_count": value for key, value in counts.items()},
        },
        "candump": {
            "path": str(candump_path),
            "size_bytes": candump_path.stat().st_size,
            "sha256": _sha256(candump_path),
            "argv": list(candump_command),
            "pid": candump_pid,
            "cleanup_status": candump_cleanup_status,
            "line_count": len(candump_lines),
        },
    }


def _validate_profile(profile: dict[str, Any]) -> None:
    expected = {
        "transport_profile": "vcan",
        "ack_mode": "socketcan",
        "mock_mode": False,
        "ack_can_id_offset": 128,
        "responder_delay_ms": 5,
    }
    if not isinstance(profile, dict) or any(
        profile.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("invalid F6 vcan capture profile")
    _validate_interface(str(profile.get("can_interface", "")))
    if profile.get("responder_policy") not in {"echo", "drop"}:
        raise ValueError("invalid F6 responder policy")


def _validate_interface(interface: str) -> None:
    if not interface or not INTERFACE_PATTERN.fullmatch(interface):
        raise ValueError(f"invalid CAN interface: {interface}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("responder record must be an object")
            records.append(record)
    except json.JSONDecodeError as error:
        raise ValueError("responder evidence is malformed") from error
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
