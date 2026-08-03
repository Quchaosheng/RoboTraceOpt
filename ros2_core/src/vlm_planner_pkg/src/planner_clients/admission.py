"""Temporal admission rules shared by live and replay planner backends."""

from __future__ import annotations

from collections import deque

from planner_clients.model_contract import ModelRequest


class ModelAdmission:
    """Reject duplicate, stale, and failure-storm requests before ROS publication."""

    def __init__(
        self,
        *,
        dedup_window_ms: int,
        failure_window_ms: int,
        max_failures: int,
        max_future_skew_ms: int = 100,
    ) -> None:
        if (
            dedup_window_ms <= 0
            or failure_window_ms <= 0
            or max_failures <= 0
            or max_future_skew_ms < 0
        ):
            raise ValueError("invalid temporal admission configuration")
        self._dedup_window_ns = int(dedup_window_ms) * 1_000_000
        self._failure_window_ns = int(failure_window_ms) * 1_000_000
        self._max_failures = int(max_failures)
        self._max_future_skew_ns = int(max_future_skew_ms) * 1_000_000
        self._admitted_until_ns: dict[str, int] = {}
        self._failure_timestamps_ns: deque[int] = deque()

    def admit(self, request: ModelRequest, now_ns: int) -> str:
        self._purge_admitted(now_ns)
        if not request.trace_id or not request.oracle_id:
            return "planner_request_identity_missing"
        if request.observation_timestamp_ns <= 0:
            return "planner_observation_timestamp_missing"
        if request.observation_timestamp_ns > int(now_ns) + self._max_future_skew_ns:
            return "planner_observation_timestamp_future"
        if request.expired(now_ns):
            return "planner_observation_expired"
        if request.request_id in self._admitted_until_ns:
            return "planner_duplicate_request"
        self._admitted_until_ns[request.request_id] = max(
            int(request.deadline_ns), int(now_ns)
        ) + self._dedup_window_ns
        return ""

    @staticmethod
    def output_allowed(request: ModelRequest, now_ns: int) -> str:
        if request.expired(now_ns):
            return "planner_output_expired"
        return ""

    def note_backend_failure(self, now_ns: int) -> bool:
        self._purge_failures(now_ns)
        self._failure_timestamps_ns.append(int(now_ns))
        return len(self._failure_timestamps_ns) >= self._max_failures

    @property
    def failure_count_in_window(self) -> int:
        return len(self._failure_timestamps_ns)

    def _purge_admitted(self, now_ns: int) -> None:
        self._admitted_until_ns = {
            request_id: expiry_ns
            for request_id, expiry_ns in self._admitted_until_ns.items()
            if expiry_ns > int(now_ns)
        }

    def _purge_failures(self, now_ns: int) -> None:
        cutoff_ns = int(now_ns) - self._failure_window_ns
        while self._failure_timestamps_ns and self._failure_timestamps_ns[0] <= cutoff_ns:
            self._failure_timestamps_ns.popleft()
