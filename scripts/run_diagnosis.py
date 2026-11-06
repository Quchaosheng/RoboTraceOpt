"""Produce a diagnosis report from captured evidence in one command.

The chain is capture -> association -> evidence graph -> inference -> report.
Before this script every step existed as a library but nothing executed them
together, so `--diagnosis-report` had to be hand-written and no gate could tell
where it came from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diagnosis.evidence_graph.association import associate_system_event  # noqa: E402
from diagnosis.evidence_graph.association_report import (  # noqa: E402
    build_association_report,
    load_normalized_jsonl,
)
from diagnosis.evidence_graph.builder import build_evidence_graph  # noqa: E402
from diagnosis.evidence_graph.callback_identity import build_callback_identities  # noqa: E402
from diagnosis.evidence_graph.confidence import (  # noqa: E402
    EvidenceAvailability,
    ScoringProfile,
)
from diagnosis.evidence_graph.inference import infer_trace  # noqa: E402
from diagnosis.evidence_graph.model import NodeType  # noqa: E402
from diagnosis.evidence_graph.stage_window import build_stage_windows  # noqa: E402
from diagnosis.evidence_graph.topology_contract import get_topology_contract  # noqa: E402
from diagnosis.reports.diagnosis_report import build_diagnosis_report  # noqa: E402
from diagnosis.schema import NormalizedEvent  # noqa: E402


def run_diagnosis(
    runtime_events: list[NormalizedEvent],
    system_events: list[NormalizedEvent],
    profile: ScoringProfile,
    *,
    workload_id: str,
    trace_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the diagnosis report plus the association summary behind it."""
    windows = build_stage_windows(runtime_events)
    callback_identities = build_callback_identities(system_events)
    decisions = [
        associate_system_event(event, windows, callback_identities=callback_identities)
        for event in system_events
    ]
    graph = build_evidence_graph(
        windows, system_events, decisions, get_topology_contract(workload_id)
    )
    selected = trace_id or _select_trace(windows)
    availability = _availability(graph, selected)
    result = infer_trace(graph, selected, profile, availability)
    report = build_diagnosis_report(result, graph)
    association = build_association_report(decisions)
    return report, {
        "schema_version": "diagnosis-input-association/v1",
        "window_count": len(windows),
        "callback_identity_count": len(callback_identities),
        "counts_by_status": association["counts_by_status"],
    }


def _select_trace(windows: list[Any]) -> str:
    trace_ids = sorted({window.trace_id for window in windows})
    if not trace_ids:
        raise ValueError("no runtime events produced a stage window")
    if len(trace_ids) > 1:
        raise ValueError(
            "capture contains more than one trace; select one with --trace-id: "
            + ", ".join(trace_ids[:5])
        )
    return trace_ids[0]


def _availability(graph: Any, trace_id: str) -> dict[NodeType, EvidenceAvailability]:
    # Every evidence source that reached this trace is present and complete by
    # construction; the topology validation, not this map, decides admission.
    # STAGE_WINDOW stays in: the compute-delay metrics are read from it.
    node_types = sorted(
        {node.node_type for node in graph.nodes if node.trace_id == trace_id},
        key=lambda item: item.value,
    )
    return {
        node_type: EvidenceAvailability("valid", "captured_in_this_run")
        for node_type in node_types
        if node_type is not NodeType.TRACE
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--workload", default="w1")
    parser.add_argument("--trace-id", default="")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = ScoringProfile.from_dict(
        json.loads(args.profile.read_text(encoding="utf-8"))
    )
    report, association = run_diagnosis(
        load_normalized_jsonl(args.runtime),
        load_normalized_jsonl(args.system),
        profile,
        workload_id=args.workload,
        trace_id=args.trace_id,
    )
    report["inputs"] = {
        "runtime": str(args.runtime),
        "system": str(args.system),
        "profile": str(args.profile),
        "association": association,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(args.output), "status": report["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
