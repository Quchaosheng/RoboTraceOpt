"""Load fault specifications and create blinded run/oracle manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from string import hexdigits
from typing import Any


@dataclass(frozen=True)
class FaultSpec:
    fault_id: str
    cause_id: str
    workload: str
    implementation_status: str
    oracle_mechanism: str
    required_capabilities: tuple[str, ...]
    injection: dict[str, Any]


def load_fault_catalog(path: Path | None = None) -> dict[str, FaultSpec]:
    catalog_path = path or Path(__file__).with_name("fault_catalog.json")
    record = json.loads(catalog_path.read_text(encoding="utf-8"))
    if record.get("schema_version") != "fault-catalog/v1":
        raise ValueError("unsupported fault catalog schema")
    records = record.get("faults")
    if not isinstance(records, list) or not records:
        raise ValueError("fault catalog must contain faults")
    result: dict[str, FaultSpec] = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("fault specification must be an object")
        spec = FaultSpec(
            fault_id=str(item["fault_id"]),
            cause_id=str(item["cause_id"]),
            workload=str(item["workload"]),
            implementation_status=str(item["implementation_status"]),
            oracle_mechanism=str(item["oracle_mechanism"]),
            required_capabilities=tuple(
                str(value) for value in item.get("required_capabilities", [])
            ),
            injection=dict(item["injection"]),
        )
        if spec.fault_id in result:
            raise ValueError(f"duplicate fault ID: {spec.fault_id}")
        result[spec.fault_id] = spec
    return result


def create_fault_manifests(
    spec: FaultSpec,
    *,
    dataset_role: str,
    session_id: str,
    condition_id: str,
    git_commit: str,
    condition_variant: str = "injected",
    target_cpu: int | None = None,
    f6_transport_profile: str = "mock",
    f6_can_interface: str | None = None,
    f6_responder_interface: str | None = None,
    f6_bitrate: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if spec.implementation_status != "ready":
        raise ValueError(
            f"fault {spec.fault_id} is not ready: {spec.implementation_status}"
        )
    if dataset_role not in {"development", "calibration", "test"}:
        raise ValueError(f"invalid dataset role: {dataset_role}")
    if spec.fault_id == "F5" and dataset_role != "development":
        raise ValueError("F5 is development-only until its profile is frozen")
    if spec.fault_id != "F6" and f6_transport_profile != "mock":
        raise ValueError("F6 transport profile is only valid for F6")
    if (
        spec.fault_id == "F6"
        and f6_transport_profile in {"vcan", "physical"}
        and dataset_role != "development"
    ):
        raise ValueError(
            f"F6 {f6_transport_profile} transport profile is development-only"
        )
    validate_condition_variant(spec, condition_variant)
    if condition_variant == "control" and dataset_role != "development":
        raise ValueError("control variant is development-only")
    if not session_id:
        raise ValueError("session_id is required")
    if not condition_id:
        raise ValueError("condition_id is required")
    if len(git_commit) != 40 or any(
        character not in hexdigits for character in git_commit
    ):
        raise ValueError("git_commit must be a 40-character SHA-1")
    public = {
        "schema_version": "fault-run/v1",
        "condition_id": condition_id,
        "session_id": session_id,
        "dataset_role": dataset_role,
        "workload": spec.workload,
        "git_commit": git_commit.lower(),
        "required_capabilities": list(spec.required_capabilities),
    }
    injection = dict(spec.injection)
    if spec.fault_id == "F1":
        injection["planner_delay_ms"] = (
            int(injection["planner_delay_ms"])
            if condition_variant == "injected"
            else int(injection["control_delay_ms"])
        )
        injection.pop("control_delay_ms")
    if spec.fault_id == "F2":
        injection["executor_contention_enabled"] = condition_variant == "injected"
    if spec.fault_id == "F4":
        injection["server_delay_ms"] = (
            int(injection["server_delay_ms"])
            if condition_variant == "injected"
            else int(injection["control_delay_ms"])
        )
        injection.pop("control_delay_ms")
    if spec.fault_id == "F5":
        depth = (
            int(injection["publisher_depth"])
            if condition_variant == "injected"
            else int(injection["control_depth"])
        )
        injection["publisher_depth"] = depth
        injection["subscriber_depth"] = depth
        injection.pop("control_depth")
    if spec.fault_id == "F3":
        if (
            isinstance(target_cpu, bool)
            or not isinstance(target_cpu, int)
            or target_cpu < 0
        ):
            raise ValueError("F3 target_cpu must be a non-negative integer")
        injection["target_cpu"] = target_cpu
        injection["stress_enabled"] = condition_variant == "injected"
    if spec.fault_id == "F6":
        injection = materialize_f6_injection(
            spec,
            condition_variant,
            f6_transport_profile,
            can_interface=f6_can_interface,
            responder_interface=f6_responder_interface,
            bitrate=f6_bitrate,
        )
    oracle = {
        "schema_version": "fault-oracle/v1",
        "condition_id": condition_id,
        "session_id": session_id,
        "dataset_role": dataset_role,
        "fault_id": spec.fault_id,
        "condition_variant": condition_variant,
        "cause_id": spec.cause_id if condition_variant == "injected" else "none",
        "oracle_mechanism": spec.oracle_mechanism,
        "injection": injection,
    }
    return public, oracle


def materialize_f6_injection(
    spec: FaultSpec,
    condition_variant: str,
    transport_profile: str = "mock",
    *,
    can_interface: str | None = None,
    responder_interface: str | None = None,
    bitrate: int | None = None,
) -> dict[str, Any]:
    if spec.fault_id != "F6":
        raise ValueError("F6 transport profile is only valid for F6")
    validate_condition_variant(spec, condition_variant)
    if transport_profile not in {"mock", "vcan", "physical"}:
        raise ValueError(f"invalid F6 transport profile: {transport_profile}")

    injection = dict(spec.injection)
    vcan_profile = injection.pop("vcan_profile", None)
    physical_profile = injection.pop("physical_profile", None)
    if transport_profile == "mock":
        injection["mock_ack_policy"] = (
            str(injection["mock_ack_policy"])
            if condition_variant == "injected"
            else str(injection["control_ack_policy"])
        )
        injection.pop("control_ack_policy")
        return injection

    selected_profile = vcan_profile if transport_profile == "vcan" else physical_profile
    if not isinstance(selected_profile, dict):
        raise ValueError(f"F6 {transport_profile} profile is missing")
    for key in ("mock_ack_policy", "control_ack_policy", "ack_mode", "mock_mode"):
        injection.pop(key)
    policy_key = (
        "injected_responder_policy"
        if condition_variant == "injected"
        else "control_responder_policy"
    )
    injection.update(
        {
            key: value
            for key, value in selected_profile.items()
            if key not in {"injected_responder_policy", "control_responder_policy"}
        }
    )
    injection["responder_policy"] = str(selected_profile[policy_key])
    if transport_profile == "physical":
        if can_interface is not None:
            injection["can_interface"] = can_interface
        if responder_interface is not None:
            injection["responder_interface"] = responder_interface
        if bitrate is not None:
            injection["bitrate"] = bitrate
        if injection["can_interface"] == injection["responder_interface"]:
            raise ValueError("physical CAN interfaces must be distinct")
        if not isinstance(injection["bitrate"], int) or injection["bitrate"] <= 0:
            raise ValueError("physical CAN bitrate must be positive")
    return injection


def validate_condition_variant(spec: FaultSpec, condition_variant: str) -> None:
    if condition_variant not in {"injected", "control"}:
        raise ValueError(f"invalid condition variant: {condition_variant}")
    if condition_variant == "control" and spec.fault_id not in {
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
    }:
        raise ValueError(
            "control variant is only supported for F1, F2, F3, F4, F5, or F6"
        )
