"""Evaluate whether an RDK X5 is ready for RoboTraceOpt experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.check_platform_capabilities import collect_capabilities


def evaluate_x5_readiness(
    report: dict[str, Any],
    *,
    mode: str,
    runtime_interface: str = "can0",
    peer_interface: str = "can1",
    bitrate: int = 500_000,
) -> dict[str, Any]:
    if mode not in {"software", "physical-can"}:
        raise ValueError(f"unsupported X5 preflight mode: {mode}")
    if bitrate <= 0:
        raise ValueError("CAN bitrate must be positive")

    host = report.get("host", {})
    os_release = host.get("os_release", {})
    evidence = report.get("evidence", {})
    provenance = report.get("provenance", {})
    readiness = report.get("readiness", {})
    checks = [
        _check(
            "native_linux",
            host.get("system") == "Linux" and host.get("is_wsl") is False,
            "native Linux",
            f"system={host.get('system', '')}, is_wsl={host.get('is_wsl')}",
        ),
        _check(
            "aarch64",
            str(host.get("machine", "")).lower() in {"aarch64", "arm64"},
            "aarch64",
            str(host.get("machine", "")),
        ),
        _check(
            "ubuntu_22_04",
            str(os_release.get("ID", "")).lower() == "ubuntu"
            and str(os_release.get("VERSION_ID", "")).strip('"') == "22.04",
            "Ubuntu 22.04",
            f"{os_release.get('ID', '')} {os_release.get('VERSION_ID', '')}".strip(),
        ),
        _check(
            "ros2_humble",
            str(evidence.get("ros2", {}).get("ros_distro", "")).lower()
            == "humble",
            "ROS 2 Humble",
            str(evidence.get("ros2", {}).get("ros_distro", "")),
        ),
        _check(
            "git_clean",
            not str(provenance.get("git_status", "")).strip(),
            "clean Git worktree",
            str(provenance.get("git_status", "")).strip() or "clean",
        ),
    ]
    for name in ("ebpf", "identity_comparable_ebpf", "ros2_tracing"):
        status = str(readiness.get(name, {}).get("status", "missing"))
        checks.append(_check(name, status == "ready", "ready", status))

    if mode == "physical-can":
        interfaces = evidence.get("can", {}).get("interfaces", [])
        physical_ready, observed = _physical_pair_ready(
            interfaces,
            runtime_interface=runtime_interface,
            peer_interface=peer_interface,
            bitrate=bitrate,
        )
        checks.append(
            _check(
                "physical_can_pair",
                physical_ready,
                f"distinct UP physical CAN links at {bitrate} bit/s",
                observed,
            )
        )

    failed = [check["name"] for check in checks if not check["ready"]]
    return {
        "schema_version": "x5-preflight/v1",
        "mode": mode,
        "status": "blocked" if failed else "ready",
        "development_only": True,
        "formal_evidence": False,
        "runtime_interface": runtime_interface,
        "peer_interface": peer_interface,
        "bitrate": bitrate,
        "checks": checks,
        "failed_checks": failed,
        "capability_report": report,
    }


def render_x5_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# RDK X5 Preflight",
        "",
        f"- Mode: `{result['mode']}`",
        f"- Status: **{result['status']}**",
        "- Evidence level: development readiness only",
        "",
        "| Check | Status | Expected | Observed |",
        "|---|---|---|---|",
    ]
    for check in result["checks"]:
        status = "ready" if check["ready"] else "blocked"
        expected = str(check["expected"]).replace("|", "\\|")
        observed = str(check["observed"]).replace("|", "\\|")
        lines.append(f"| `{check['name']}` | {status} | {expected} | {observed} |")
    lines.append("")
    return "\n".join(lines)


def _check(name: str, ready: bool, expected: str, observed: str) -> dict[str, Any]:
    return {
        "name": name,
        "ready": bool(ready),
        "expected": expected,
        "observed": observed,
    }


def _physical_pair_ready(
    records: Any,
    *,
    runtime_interface: str,
    peer_interface: str,
    bitrate: int,
) -> tuple[bool, str]:
    if runtime_interface == peer_interface:
        return False, "runtime and peer interfaces are identical"
    if not isinstance(records, list):
        return False, "CAN interface evidence is missing"
    by_name = {
        str(record.get("ifname")): record
        for record in records
        if isinstance(record, dict) and record.get("ifname")
    }
    failures: list[str] = []
    for name in (runtime_interface, peer_interface):
        record = by_name.get(name)
        if record is None:
            failures.append(f"{name}:missing")
            continue
        linkinfo = record.get("linkinfo", {})
        info_data = linkinfo.get("info_data", {})
        actual_bitrate = _find_integer(info_data, "bitrate")
        state = str(info_data.get("state", "")).upper()
        if linkinfo.get("info_kind") != "can":
            failures.append(f"{name}:not-physical-can")
        elif "UP" not in record.get("flags", []):
            failures.append(f"{name}:down")
        elif state == "BUS-OFF":
            failures.append(f"{name}:bus-off")
        elif actual_bitrate != bitrate:
            failures.append(f"{name}:bitrate={actual_bitrate}")
    return not failures, ", ".join(failures) if failures else "ready"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("software", "physical-can"), default="software")
    parser.add_argument("--runtime-interface", default="can0")
    parser.add_argument("--peer-interface", default="can1")
    parser.add_argument("--bitrate", type=int, default=500_000)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capability = collect_capabilities("rdk-x5", args.runtime_interface)
    result = evaluate_x5_readiness(
        capability,
        mode=args.mode,
        runtime_interface=args.runtime_interface,
        peer_interface=args.peer_interface,
        bitrate=args.bitrate,
    )
    rendered_json = json.dumps(result, indent=2, sort_keys=True) + "\n"
    rendered_markdown = render_x5_markdown(result)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered_json, encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(rendered_markdown, encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(rendered_markdown, end="")
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
