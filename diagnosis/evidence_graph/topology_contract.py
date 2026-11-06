"""Frozen workload topology contracts used to admit trace evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TopologyPath:
    name: str
    required_stages: tuple[str, ...]
    # Stages a retry repeats: (retry marker, repeated subsequence). A retried
    # attempt replays the subsequence after the marker, so the strict stage
    # ordering restarts there instead of reporting a backwards step.
    retry_marker: str = ""
    retry_repeat: tuple[str, ...] = ()

    @property
    def retry_repeat_first(self) -> str:
        """Stage that begins the repeated retry subsequence."""
        return self.retry_repeat[0] if self.retry_repeat else ""


@dataclass(frozen=True)
class TopologyValidation:
    status: str
    matched_path: str
    missing_expected: tuple[str, ...] = ()
    conflicting_stages: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopologyContract:
    workload_id: str
    paths: tuple[TopologyPath, ...]

    def validate(self, observed_stages: Iterable[str]) -> TopologyValidation:
        observed = tuple(observed_stages)
        terminal_stages = {path.required_stages[-1] for path in self.paths}
        observed_terminals = tuple(
            dict.fromkeys(stage for stage in observed if stage in terminal_stages)
        )
        if len(observed_terminals) > 1:
            return TopologyValidation(
                status="invalid",
                matched_path="",
                conflicting_stages=observed_terminals,
                reason_codes=("topology_terminal_conflict",),
            )
        candidate_paths = self.paths
        if observed_terminals:
            candidate_paths = tuple(
                path
                for path in self.paths
                if path.required_stages[-1] == observed_terminals[0]
            )
        evaluations = [self._evaluate_path(observed, path) for path in candidate_paths]
        valid = next(
            (result for result in evaluations if result.status == "valid"), None
        )
        if valid is not None:
            return valid
        return min(
            evaluations,
            key=lambda result: (
                result.status == "invalid",
                len(result.missing_expected),
                len(result.conflicting_stages),
                result.matched_path,
            ),
        )

    @staticmethod
    def _evaluate_path(
        observed: tuple[str, ...], path: TopologyPath
    ) -> TopologyValidation:
        stage_index = {stage: index for index, stage in enumerate(path.required_stages)}
        admitted: list[str] = []
        restarts: set[int] = set()
        retry_pending = False
        for stage in observed:
            if path.retry_marker and stage == path.retry_marker:
                retry_pending = True
                continue
            if stage not in stage_index:
                continue
            if retry_pending and stage == path.retry_repeat_first:
                restarts.add(len(admitted))
            retry_pending = False
            admitted.append(stage)
        conflict: tuple[str, ...] = ()
        for index, (previous, current) in enumerate(zip(admitted, admitted[1:]), start=1):
            if index in restarts:
                continue
            if stage_index[current] < stage_index[previous]:
                conflict = (previous, current)
                break
        missing = tuple(
            stage for stage in path.required_stages if stage not in admitted
        )
        if conflict:
            return TopologyValidation(
                status="invalid",
                matched_path=path.name,
                missing_expected=missing,
                conflicting_stages=conflict,
                reason_codes=("topology_order_violation",),
            )
        if missing:
            return TopologyValidation(
                status="partial",
                matched_path=path.name,
                missing_expected=missing,
                reason_codes=("topology_stage_missing",),
            )
        return TopologyValidation(status="valid", matched_path=path.name)


_W1_PREFIX = (
    "camera_publish",
    "planner_receive",
    "planner_process_start",
    "planner_process_end",
    "planner_publish",
    "action_receive",
    "action_execute_start",
    "action_execute_end",
    "can_receive",
    "can_encode_start",
    "can_encode_end",
    "can_frame_sent",
)


_CONTRACTS = {
    "w1": TopologyContract(
        workload_id="w1",
        paths=(
            TopologyPath(
                "ack_received",
                _W1_PREFIX + ("can_ack_wait_start", "can_ack_received"),
                retry_marker="can_retry_scheduled",
                retry_repeat=("can_frame_sent", "can_ack_wait_start"),
            ),
            TopologyPath(
                "retry_exhausted",
                _W1_PREFIX + ("can_ack_wait_start", "can_retry_exhausted"),
                retry_marker="can_retry_scheduled",
                retry_repeat=("can_frame_sent", "can_ack_wait_start"),
            ),
            TopologyPath("send_failed", _W1_PREFIX + ("can_frame_send_failed",)),
        ),
    ),
    "w2": TopologyContract(
        workload_id="w2",
        paths=(
            TopologyPath(
                "request_response",
                (
                    "query_sent",
                    "service_receive",
                    "service_process_start",
                    "service_process_end",
                    "service_response",
                    "response_received",
                ),
            ),
        ),
    ),
}


def get_topology_contract(workload_id: str) -> TopologyContract:
    try:
        return _CONTRACTS[workload_id.lower()]
    except KeyError as error:
        raise KeyError(f"unknown topology contract: {workload_id}") from error
