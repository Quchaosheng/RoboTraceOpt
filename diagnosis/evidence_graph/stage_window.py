"""Build process-local semantic windows from RuntimeEvent evidence."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import Iterable

from diagnosis.schema import NormalizedEvent


@dataclass(frozen=True)
class StageWindow:
    window_id: str
    trace_id: str
    sequence_id: int
    stage: str
    source_node: str
    pid: int
    tids: tuple[int, ...]
    host_id: str
    clock_id: str
    start_ns: int
    end_ns: int
    start_event_id: str
    end_event_id: str

    def contains(self, timestamp_ns: int) -> bool:
        return self.start_ns <= timestamp_ns <= self.end_ns


def build_stage_windows(events: Iterable[NormalizedEvent]) -> list[StageWindow]:
    runtime_events = [event for event in events if event.source == "runtime_event"]
    for event in runtime_events:
        if not event.trace_id or not event.stage or event.pid <= 0 or event.tid <= 0:
            raise ValueError(f"incomplete RuntimeEvent identity: {event.event_id}")

    def event_key(event: NormalizedEvent) -> tuple[object, ...]:
        return (
            event.trace_id,
            event.sequence_id,
            event.pid,
            event.host_id,
            event.clock_id,
        )

    windows: list[StageWindow] = []
    for _, grouped in groupby(
        sorted(runtime_events, key=lambda item: (*event_key(item), item.timestamp_ns)),
        key=event_key,
    ):
        process_events = list(grouped)
        end_by_start = _pair_explicit_end_events(process_events)
        for index, start_event in enumerate(process_events):
            paired_end = end_by_start.get(index)
            duration_ns = start_event.attributes.get("duration_ns", 0)
            if (
                isinstance(duration_ns, bool)
                or not isinstance(duration_ns, int)
                or duration_ns < 0
            ):
                raise ValueError(f"invalid duration_ns: {start_event.event_id}")
            # A stage ends at its own end event or its declared duration. Using
            # "whatever was emitted next" made a duration depend on unrelated
            # instrumentation, and duration_ns=0 means "not measured", not a
            # real zero-width interval.
            if paired_end is not None:
                end_ns = paired_end.timestamp_ns
            else:
                end_ns = start_event.timestamp_ns + duration_ns
            if end_ns < start_event.timestamp_ns:
                raise ValueError(f"non-monotonic stage events: {start_event.trace_id}")
            windows.append(
                StageWindow(
                    window_id=f"stage-window:{start_event.event_id}",
                    trace_id=start_event.trace_id,
                    sequence_id=start_event.sequence_id,
                    stage=start_event.stage,
                    source_node=str(start_event.attributes.get("source_node", "")),
                    pid=start_event.pid,
                    tids=(start_event.tid,),
                    host_id=start_event.host_id,
                    clock_id=start_event.clock_id,
                    start_ns=start_event.timestamp_ns,
                    end_ns=end_ns,
                    start_event_id=start_event.event_id,
                    end_event_id=(
                        paired_end.event_id
                        if paired_end is not None
                        else start_event.event_id
                    ),
                )
            )
    return sorted(windows, key=lambda item: (item.start_ns, item.window_id))


def _pair_explicit_end_events(
    process_events: list[NormalizedEvent],
) -> dict[int, NormalizedEvent]:
    """Match `<stage>_start` with the next `<stage>_end` of the same trace body.

    Intermediate events (`action_feedback`, planner publish, ...) belong to the
    running stage, so they must not close it. Matches the semantic interval the
    stage represents instead of "whatever was emitted next".
    """
    end_index: dict[str, list[int]] = {}
    for index, event in enumerate(process_events):
        if event.stage.endswith("_end"):
            end_index.setdefault(event.stage[: -len("_end")], []).append(index)
    paired: dict[int, NormalizedEvent] = {}
    # Walk the ends in order and give each one to the nearest preceding start
    # that is still open. A repeated start therefore cannot claim an end that
    # already belongs to the attempt it opened.
    open_starts: dict[str, list[int]] = {}
    for index, event in enumerate(process_events):
        if event.stage.endswith("_start"):
            open_starts.setdefault(event.stage[: -len("_start")], []).append(index)
        elif event.stage.endswith("_end"):
            pending = open_starts.get(event.stage[: -len("_end")])
            if pending:
                paired[pending.pop()] = event
    return paired
