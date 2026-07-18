"""Validate two Linux physical CAN links before an evidence run."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any


INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def inspect_physical_can_pair(
    *, runtime_interface: str, peer_interface: str, bitrate: int
) -> dict[str, Any]:
    for interface in (runtime_interface, peer_interface):
        _validate_interface_name(interface)
    completed = subprocess.run(
        ["ip", "-details", "-json", "link", "show", "type", "can"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot inspect CAN links: {completed.stderr.strip()}")
    try:
        records = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("ip returned invalid CAN link JSON") from error
    return validate_physical_can_pair(
        records,
        runtime_interface=runtime_interface,
        peer_interface=peer_interface,
        bitrate=bitrate,
    )


def validate_physical_can_pair(
    records: Any,
    *,
    runtime_interface: str,
    peer_interface: str,
    bitrate: int,
) -> dict[str, Any]:
    _validate_interface_name(runtime_interface)
    _validate_interface_name(peer_interface)
    if runtime_interface == peer_interface:
        raise ValueError("physical CAN interfaces must be distinct")
    if not isinstance(bitrate, int) or isinstance(bitrate, bool) or bitrate <= 0:
        raise ValueError("physical CAN bitrate must be a positive integer")
    if not isinstance(records, list):
        raise ValueError("physical CAN interface records must be a list")

    by_name = {
        str(record.get("ifname")): record
        for record in records
        if isinstance(record, dict) and record.get("ifname")
    }
    runtime = _validate_link(by_name.get(runtime_interface), runtime_interface, bitrate)
    peer = _validate_link(by_name.get(peer_interface), peer_interface, bitrate)
    return {"runtime": runtime, "peer": peer, "bitrate": bitrate}


def _validate_link(record: Any, interface: str, bitrate: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"physical CAN interface is missing: {interface}")
    linkinfo = record.get("linkinfo", {})
    if linkinfo.get("info_kind") != "can":
        raise ValueError(f"{interface} is not a physical CAN interface")
    if "UP" not in record.get("flags", []):
        raise ValueError(f"{interface} is not UP")
    info_data = linkinfo.get("info_data", {})
    state = str(info_data.get("state", "")).upper()
    if state == "BUS-OFF":
        raise ValueError(f"{interface} is BUS-OFF")
    actual_bitrate = _find_integer(info_data, "bitrate")
    if actual_bitrate != bitrate:
        raise ValueError(
            f"{interface} bitrate mismatch: expected {bitrate}, observed {actual_bitrate}"
        )
    return dict(record)


def _find_integer(value: Any, key: str) -> int | None:
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
        for child in value.values():
            found = _find_integer(child, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_integer(child, key)
            if found is not None:
                return found
    return None


def _validate_interface_name(interface: str) -> None:
    if not interface or not INTERFACE_PATTERN.fullmatch(interface):
        raise ValueError(f"invalid CAN interface: {interface}")
