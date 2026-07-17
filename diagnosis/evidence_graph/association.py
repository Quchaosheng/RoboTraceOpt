"""Associate system evidence with RuntimeEvent stage windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from diagnosis.evidence_graph.callback_identity import (
    CallbackIdentity,
    callback_identity_for_event,
)
from diagnosis.evidence_graph.stage_window import StageWindow
from diagnosis.schema import NormalizedEvent


@dataclass(frozen=True)
class AssociationDecision:
    event_id: str
    status: str
    reason_code: str
    source: str = ""
    event_type: str = ""
    trace_id: str = ""
    sequence_id: int = 0
    stage: str = ""
    window_id: str = ""
    score: int = 0
    candidate_count: int = 0
    callback_handle: int = 0
    callback_kind: str = ""
    callback_name: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "source": self.source,
            "event_type": self.event_type,
            "trace_id": self.trace_id,
            "sequence_id": self.sequence_id,
            "stage": self.stage,
            "window_id": self.window_id,
            "score": self.score,
            "candidate_count": self.candidate_count,
            "callback_handle": self.callback_handle,
            "callback_kind": self.callback_kind,
            "callback_name": self.callback_name,
        }


def _accepted(
    event: NormalizedEvent,
    window: StageWindow,
    *,
    reason_code: str,
    score: int,
    candidate_count: int,
    callback_identity: CallbackIdentity | None = None,
) -> AssociationDecision:
    return AssociationDecision(
        event_id=event.event_id,
        status="accepted",
        reason_code=reason_code,
        source=event.source,
        event_type=event.event_type,
        trace_id=window.trace_id,
        sequence_id=window.sequence_id,
        stage=window.stage,
        window_id=window.window_id,
        score=score,
        candidate_count=candidate_count,
        callback_handle=(callback_identity.callback_handle if callback_identity else 0),
        callback_kind=(callback_identity.kind if callback_identity else ""),
        callback_name=(callback_identity.name if callback_identity else ""),
    )


def _admitted_windows(
    event: NormalizedEvent, windows: Sequence[StageWindow]
) -> tuple[list[StageWindow], AssociationDecision | None]:
    same_host = [window for window in windows if window.host_id == event.host_id]
    if not same_host:
        return [], AssociationDecision(
            event.event_id,
            "rejected",
            "host_mismatch",
            source=event.source,
            event_type=event.event_type,
        )
    same_clock = [window for window in same_host if window.clock_id == event.clock_id]
    if not same_clock:
        return [], AssociationDecision(
            event.event_id,
            "rejected",
            "clock_domain_mismatch",
            source=event.source,
            event_type=event.event_type,
        )
    return same_clock, None


def associate_system_event(
    event: NormalizedEvent,
    windows: Sequence[StageWindow],
    *,
    callback_identities: Mapping[tuple[int, int], CallbackIdentity] | None = None,
) -> AssociationDecision:
    if (
        event.event_type.endswith("_init")
        or event.event_type.endswith("_callback_added")
        or event.event_type
        in {"ros2:rclcpp_callback_register", "ros2:rclcpp_timer_link_node"}
    ):
        return AssociationDecision(
            event_id=event.event_id,
            status="unmatched",
            reason_code="topology_metadata",
            source=event.source,
            event_type=event.event_type,
        )
    callback_identity = callback_identity_for_event(
        event, callback_identities or {}
    )
    if callback_identity and callback_identity.infrastructure:
        return AssociationDecision(
            event_id=event.event_id,
            status="unmatched",
            reason_code="infrastructure_callback",
            source=event.source,
            event_type=event.event_type,
            callback_handle=callback_identity.callback_handle,
            callback_kind=callback_identity.kind,
            callback_name=callback_identity.name,
        )
    admitted, rejection = _admitted_windows(event, windows)
    if rejection is not None:
        return rejection
    candidates = [
        window
        for window in admitted
        if window.pid == event.pid and window.contains(event.timestamp_ns)
    ]
    if not candidates:
        return AssociationDecision(
            event.event_id,
            "unmatched",
            "no_process_time_candidate",
            source=event.source,
            event_type=event.event_type,
        )

    scored = [(2 if event.tid in window.tids else 1, window) for window in candidates]
    best_score = max(score for score, _ in scored)
    best = [window for score, window in scored if score == best_score]
    distinct_targets = {(window.trace_id, window.stage) for window in best}
    if len(distinct_targets) > 1:
        return AssociationDecision(
            event_id=event.event_id,
            status="ambiguous",
            reason_code="multiple_equal_candidates",
            source=event.source,
            event_type=event.event_type,
            score=best_score,
            candidate_count=len(best),
        )
    selected = max(best, key=lambda window: (window.start_ns, window.window_id))
    return _accepted(
        event,
        selected,
        reason_code="pid_tid_time_match" if best_score == 2 else "pid_time_match",
        score=best_score,
        candidate_count=len(candidates),
        callback_identity=callback_identity,
    )


def associate_by_timestamp(
    event: NormalizedEvent, windows: Sequence[StageWindow]
) -> AssociationDecision:
    admitted, rejection = _admitted_windows(event, windows)
    if rejection is not None:
        return rejection
    containing = [window for window in admitted if window.contains(event.timestamp_ns)]
    pool = containing or admitted
    selected = min(
        pool,
        key=lambda window: (
            abs(event.timestamp_ns - ((window.start_ns + window.end_ns) // 2)),
            window.window_id,
        ),
    )
    return _accepted(
        event,
        selected,
        reason_code="timestamp_only_baseline",
        score=0,
        candidate_count=len(pool),
    )
