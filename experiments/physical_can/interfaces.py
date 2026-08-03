"""Validate two Linux physical CAN links before an evidence run."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any


INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
SLCAN_BITRATES = {
    "s0": 10_000,
    "s1": 20_000,
    "s2": 50_000,
    "s3": 100_000,
    "s4": 125_000,
    "s5": 250_000,
    "s6": 500_000,
    "s7": 800_000,
    "s8": 1_000_000,
}


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
    slcand = subprocess.run(
        ["pgrep", "-a", "-x", "slcand"],
        check=False,
        capture_output=True,
        text=True,
    )
    if slcand.returncode not in {0, 1}:
        raise RuntimeError(f"cannot inspect slcand processes: {slcand.stderr.strip()}")
    return validate_physical_can_pair(
        records,
        runtime_interface=runtime_interface,
        peer_interface=peer_interface,
        bitrate=bitrate,
        slcand_processes=slcand.stdout.splitlines(),
    )


def validate_physical_can_pair(
    records: Any,
    *,
    runtime_interface: str,
    peer_interface: str,
    bitrate: int,
    slcand_processes: list[str] | None = None,
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
    slcan_evidence = _parse_slcand_processes(slcand_processes or [])
    runtime, runtime_bitrate = _validate_link(
        by_name.get(runtime_interface), runtime_interface, bitrate, slcan_evidence
    )
    peer, peer_bitrate = _validate_link(
        by_name.get(peer_interface), peer_interface, bitrate, slcan_evidence
    )
    return {
        "runtime": runtime,
        "peer": peer,
        "bitrate": bitrate,
        "bitrate_evidence": {
            "runtime": runtime_bitrate,
            "peer": peer_bitrate,
        },
    }


def _validate_link(
    record: Any,
    interface: str,
    bitrate: int,
    slcan_evidence: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    if actual_bitrate == bitrate:
        evidence = {"source": "netlink", "bitrate": actual_bitrate}
    elif actual_bitrate in {None, 0}:
        candidates = slcan_evidence.get(interface, [])
        matching = [row for row in candidates if row["bitrate"] == bitrate]
        if len(candidates) != 1 or len(matching) != 1:
            raise ValueError(
                f"{interface} bitrate is unreported by netlink and lacks one "
                f"matching slcand process for {bitrate} bit/s"
            )
        evidence = dict(matching[0])
    else:
        raise ValueError(
            f"{interface} bitrate mismatch: expected {bitrate}, observed {actual_bitrate}"
        )
    return dict(record), evidence


def _parse_slcand_processes(lines: list[str]) -> dict[str, list[dict[str, Any]]]:
    by_interface: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        argv = fields[1:]
        if argv[0].rsplit("/", 1)[-1] != "slcand":
            continue
        speed_code = next(
            (argument[1:] for argument in argv[1:] if re.fullmatch(r"-s[0-8]", argument)),
            None,
        )
        if speed_code is None:
            continue
        interface = argv[-1]
        if not INTERFACE_PATTERN.fullmatch(interface):
            continue
        by_interface.setdefault(interface, []).append(
            {
                "source": "slcand",
                "pid": int(fields[0]),
                "speed_code": speed_code,
                "bitrate": SLCAN_BITRATES[speed_code],
                "argv": argv,
            }
        )
    return by_interface


def slcand_process_lines_from_bitrate_evidence(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    lines = []
    for evidence in value.values():
        if not isinstance(evidence, dict) or evidence.get("source") != "slcand":
            continue
        pid = evidence.get("pid")
        argv = evidence.get("argv")
        if isinstance(pid, int) and isinstance(argv, list) and all(
            isinstance(argument, str) for argument in argv
        ):
            lines.append(f"{pid} {shlex.join(argv)}")
    return lines


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
