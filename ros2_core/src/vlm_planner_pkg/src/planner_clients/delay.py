"""Controlled planner delay mechanisms for baseline and fault runs."""

from __future__ import annotations

import time
from collections.abc import Callable


def apply_delay(
    delay_ms: int,
    mode: str,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    duration_ms = max(delay_ms, 0)
    if mode == "sleep":
        if duration_ms:
            sleeper(duration_ms / 1000.0)
        return
    if mode != "busy_compute":
        raise ValueError(f"unsupported planner delay mode: {mode}")
    deadline_ns = monotonic_ns() + duration_ms * 1_000_000
    accumulator = 0
    while monotonic_ns() < deadline_ns:
        accumulator = (accumulator * 1664525 + 1013904223) & 0xFFFFFFFF
    _ = accumulator
