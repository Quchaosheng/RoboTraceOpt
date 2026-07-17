"""Resolve ROS 2 callback handles from tracetools initialization events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from diagnosis.schema import NormalizedEvent


@dataclass(frozen=True)
class CallbackIdentity:
    pid: int
    callback_handle: int
    kind: str
    node_name: str = ""
    topic_name: str = ""
    service_name: str = ""
    symbol: str = ""
    infrastructure: bool = False

    @property
    def name(self) -> str:
        return self.topic_name or self.service_name or self.symbol


def _payload(event: NormalizedEvent) -> Mapping[str, object]:
    payload = event.attributes.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _handle(payload: Mapping[str, object], name: str) -> int | None:
    value = payload.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def build_callback_identities(
    events: Iterable[NormalizedEvent],
) -> dict[tuple[int, int], CallbackIdentity]:
    ordered = sorted(events, key=lambda event: (event.timestamp_ns, event.event_id))
    nodes: dict[tuple[int, int], str] = {}
    rcl_subscriptions: dict[tuple[int, int], tuple[int, str]] = {}
    cpp_subscriptions: dict[tuple[int, int], int] = {}
    timers: dict[tuple[int, int], int] = {}
    services: dict[tuple[int, int], tuple[int, str]] = {}
    callbacks: dict[tuple[int, int], tuple[str, int]] = {}
    symbols: dict[tuple[int, int], str] = {}

    for event in ordered:
        payload = _payload(event)
        pid = event.pid
        if event.event_type == "ros2:rcl_node_init":
            node_handle = _handle(payload, "node_handle")
            node_name = payload.get("node_name")
            if node_handle and isinstance(node_name, str):
                nodes[(pid, node_handle)] = node_name
        elif event.event_type == "ros2:rcl_subscription_init":
            handle = _handle(payload, "subscription_handle")
            node_handle = _handle(payload, "node_handle")
            topic = payload.get("topic_name")
            if handle and node_handle and isinstance(topic, str):
                rcl_subscriptions[(pid, handle)] = (node_handle, topic)
        elif event.event_type == "ros2:rclcpp_subscription_init":
            handle = _handle(payload, "subscription_handle")
            subscription = _handle(payload, "subscription")
            if handle and subscription:
                cpp_subscriptions[(pid, subscription)] = handle
        elif event.event_type == "ros2:rclcpp_subscription_callback_added":
            subscription = _handle(payload, "subscription")
            callback = _handle(payload, "callback")
            if subscription and callback:
                callbacks[(pid, callback)] = ("subscription", subscription)
        elif event.event_type == "ros2:rclcpp_timer_link_node":
            timer = _handle(payload, "timer_handle")
            node_handle = _handle(payload, "node_handle")
            if timer and node_handle:
                timers[(pid, timer)] = node_handle
        elif event.event_type == "ros2:rclcpp_timer_callback_added":
            timer = _handle(payload, "timer_handle")
            callback = _handle(payload, "callback")
            if timer and callback:
                callbacks[(pid, callback)] = ("timer", timer)
        elif event.event_type == "ros2:rcl_service_init":
            service = _handle(payload, "service_handle")
            node_handle = _handle(payload, "node_handle")
            service_name = payload.get("service_name")
            if service and node_handle and isinstance(service_name, str):
                services[(pid, service)] = (node_handle, service_name)
        elif event.event_type == "ros2:rclcpp_service_callback_added":
            service = _handle(payload, "service_handle")
            callback = _handle(payload, "callback")
            if service and callback:
                callbacks[(pid, callback)] = ("service", service)
        elif event.event_type == "ros2:rclcpp_callback_register":
            callback = _handle(payload, "callback")
            symbol = payload.get("symbol")
            if callback and isinstance(symbol, str):
                symbols[(pid, callback)] = symbol

    identities: dict[tuple[int, int], CallbackIdentity] = {}
    for key in callbacks.keys() | symbols.keys():
        pid, callback = key
        kind, owner = callbacks.get(key, ("unknown", 0))
        node_name = ""
        topic_name = ""
        service_name = ""
        if kind == "subscription":
            rcl_handle = cpp_subscriptions.get((pid, owner), 0)
            node_handle, topic_name = rcl_subscriptions.get(
                (pid, rcl_handle), (0, "")
            )
            node_name = nodes.get((pid, node_handle), "")
        elif kind == "timer":
            node_name = nodes.get((pid, timers.get((pid, owner), 0)), "")
        elif kind == "service":
            node_handle, service_name = services.get((pid, owner), (0, ""))
            node_name = nodes.get((pid, node_handle), "")
        symbol = symbols.get(key, "")
        infrastructure = (
            "rclcpp::ParameterService" in symbol
            or topic_name in {"/parameter_events", "/rosout"}
        )
        identities[key] = CallbackIdentity(
            pid=pid,
            callback_handle=callback,
            kind=kind,
            node_name=node_name,
            topic_name=topic_name,
            service_name=service_name,
            symbol=symbol,
            infrastructure=infrastructure,
        )
    return identities


def callback_identity_for_event(
    event: NormalizedEvent,
    identities: Mapping[tuple[int, int], CallbackIdentity],
) -> CallbackIdentity | None:
    if event.event_type not in {"ros2:callback_start", "ros2:callback_end"}:
        return None
    callback = _handle(_payload(event), "callback")
    return identities.get((event.pid, callback)) if callback else None
