"""Summarize trace-stage association decisions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from diagnosis.evidence_graph.association import (
    AssociationDecision,
    associate_system_event,
)
from diagnosis.evidence_graph.callback_identity import build_callback_identities
from diagnosis.evidence_graph.stage_window import build_stage_windows
from diagnosis.schema import NormalizedEvent


def build_association_report(
    decisions: Iterable[AssociationDecision],
) -> dict[str, object]:
    decision_list = list(decisions)
    status_counts = Counter(decision.status for decision in decision_list)
    reason_counts = Counter(decision.reason_code for decision in decision_list)
    event_type_counts = Counter(decision.event_type for decision in decision_list)
    by_status_and_type: dict[str, Counter[str]] = {}
    for decision in decision_list:
        by_status_and_type.setdefault(decision.status, Counter())[
            decision.event_type
        ] += 1
    total = len(decision_list)
    return {
        "schema_version": "association-report/v1",
        "decision_count": total,
        "counts_by_status": dict(sorted(status_counts.items())),
        "counts_by_reason": dict(sorted(reason_counts.items())),
        "counts_by_event_type": dict(sorted(event_type_counts.items())),
        "counts_by_status_and_event_type": {
            status: dict(sorted(counts.items()))
            for status, counts in sorted(by_status_and_type.items())
        },
        "accepted_rate": status_counts.get("accepted", 0) / total if total else 0.0,
        "decisions": [decision.to_dict() for decision in decision_list],
    }


def load_normalized_jsonl(path: Path) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            record = json.loads(raw_line)
            if not isinstance(record, dict):
                raise ValueError(f"record must be an object: {path}:{line_number}")
            events.append(NormalizedEvent(**record))
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    windows = build_stage_windows(load_normalized_jsonl(args.runtime))
    system_events = load_normalized_jsonl(args.system)
    callback_identities = build_callback_identities(system_events)
    decisions = [
        associate_system_event(event, windows, callback_identities=callback_identities)
        for event in system_events
    ]
    report = build_association_report(decisions)
    report["window_count"] = len(windows)
    report["callback_identity_count"] = len(callback_identities)
    report["runtime_input"] = str(args.runtime)
    report["system_input"] = str(args.system)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
