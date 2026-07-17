"""Source-independent event used by association and diagnosis."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    source: str
    event_type: str
    timestamp_ns: int
    clock_id: str
    trace_id: str
    sequence_id: int
    stage: str
    pid: int
    tid: int
    host_id: str
    attributes: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "event_type": self.event_type,
            "timestamp_ns": self.timestamp_ns,
            "clock_id": self.clock_id,
            "trace_id": self.trace_id,
            "sequence_id": self.sequence_id,
            "stage": self.stage,
            "pid": self.pid,
            "tid": self.tid,
            "host_id": self.host_id,
            "attributes": deepcopy(self.attributes),
            "provenance": deepcopy(self.provenance),
        }
