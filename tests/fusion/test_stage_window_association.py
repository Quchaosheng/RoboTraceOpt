import unittest
import json
import subprocess
import tempfile
from pathlib import Path

from diagnosis.evidence_graph.association import (
    associate_by_timestamp,
    associate_system_event,
)
from diagnosis.evidence_graph.association_report import build_association_report
from diagnosis.evidence_graph.stage_window import build_stage_windows
from diagnosis.schema import NormalizedEvent


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def event(
    event_id: str,
    *,
    source: str,
    timestamp_ns: int,
    pid: int,
    tid: int,
    trace_id: str = "",
    sequence_id: int = 0,
    stage: str = "",
    clock_id: str = "monotonic",
    host_id: str = "host-a",
) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source=source,
        event_type=stage or "callback_start",
        timestamp_ns=timestamp_ns,
        clock_id=clock_id,
        trace_id=trace_id,
        sequence_id=sequence_id,
        stage=stage,
        pid=pid,
        tid=tid,
        host_id=host_id,
        attributes={},
        provenance={"source_file": "fixture.jsonl", "record_index": 1},
    )


class StageWindowTest(unittest.TestCase):
    def test_builds_process_local_windows_from_adjacent_runtime_events(self) -> None:
        runtime_events = [
            event(
                "a-start",
                source="runtime_event",
                timestamp_ns=100,
                pid=10,
                tid=11,
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_process_start",
            ),
            event(
                "a-end",
                source="runtime_event",
                timestamp_ns=200,
                pid=10,
                tid=11,
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_process_end",
            ),
        ]

        windows = build_stage_windows(runtime_events)

        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].trace_id, "trace-a")
        self.assertEqual(windows[0].stage, "planner_process_start")
        self.assertEqual((windows[0].start_ns, windows[0].end_ns), (100, 200))
        self.assertEqual(windows[0].tids, (11,))
        self.assertEqual((windows[1].start_ns, windows[1].end_ns), (200, 200))

    def test_rejects_runtime_event_without_trace_identity(self) -> None:
        incomplete = event(
            "missing-trace",
            source="runtime_event",
            timestamp_ns=100,
            pid=10,
            tid=11,
            stage="planner",
        )

        with self.assertRaises(ValueError):
            build_stage_windows([incomplete])


class AssociationTest(unittest.TestCase):
    def test_report_cli_associates_normalized_jsonl(self) -> None:
        runtime = [
            event(
                "start",
                source="runtime_event",
                timestamp_ns=100,
                pid=10,
                tid=11,
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_start",
            ),
            event(
                "end",
                source="runtime_event",
                timestamp_ns=200,
                pid=10,
                tid=11,
                trace_id="trace-a",
                sequence_id=1,
                stage="planner_end",
            ),
        ]
        system = event(
            "callback",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=10,
            tid=11,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            runtime_path = root / "runtime.jsonl"
            system_path = root / "system.jsonl"
            output_path = root / "report.json"
            runtime_path.write_text(
                "".join(json.dumps(item.to_dict()) + "\n" for item in runtime),
                encoding="utf-8",
            )
            system_path.write_text(json.dumps(system.to_dict()) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    "-m",
                    "diagnosis.evidence_graph.association_report",
                    "--runtime",
                    str(runtime_path),
                    "--system",
                    str(system_path),
                    "--output",
                    str(output_path),
                ],
                cwd=REPOSITORY_ROOT,
                check=True,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["counts_by_status"], {"accepted": 1})
        self.assertEqual(report["decisions"][0]["trace_id"], "trace-a")

    def setUp(self) -> None:
        self.windows = build_stage_windows(
            [
                event(
                    "a-start",
                    source="runtime_event",
                    timestamp_ns=100,
                    pid=10,
                    tid=11,
                    trace_id="trace-a",
                    sequence_id=1,
                    stage="planner_start",
                ),
                event(
                    "a-end",
                    source="runtime_event",
                    timestamp_ns=200,
                    pid=10,
                    tid=11,
                    trace_id="trace-a",
                    sequence_id=1,
                    stage="planner_end",
                ),
                event(
                    "b-start",
                    source="runtime_event",
                    timestamp_ns=120,
                    pid=10,
                    tid=12,
                    trace_id="trace-b",
                    sequence_id=2,
                    stage="planner_start",
                ),
                event(
                    "b-end",
                    source="runtime_event",
                    timestamp_ns=220,
                    pid=10,
                    tid=12,
                    trace_id="trace-b",
                    sequence_id=2,
                    stage="planner_end",
                ),
            ]
        )

    def test_exact_tid_breaks_overlapping_trace_tie(self) -> None:
        system = event(
            "ros-callback",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=10,
            tid=11,
        )

        decision = associate_system_event(system, self.windows)

        self.assertEqual(decision.status, "accepted")
        self.assertEqual(decision.reason_code, "pid_tid_time_match")
        self.assertEqual(decision.source, "ros2_tracing")
        self.assertEqual(decision.event_type, "callback_start")
        self.assertEqual(decision.trace_id, "trace-a")
        self.assertEqual(decision.stage, "planner_start")

    def test_equal_pid_only_candidates_remain_ambiguous(self) -> None:
        system = event(
            "ros-worker",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=10,
            tid=99,
        )

        decision = associate_system_event(system, self.windows)

        self.assertEqual(decision.status, "ambiguous")
        self.assertEqual(decision.reason_code, "multiple_equal_candidates")
        self.assertEqual(decision.candidate_count, 2)
        self.assertEqual(decision.trace_id, "")

    def test_unmatched_event_is_retained_as_background(self) -> None:
        system = event(
            "other-process",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=999,
            tid=999,
        )

        decision = associate_system_event(system, self.windows)

        self.assertEqual(decision.status, "unmatched")
        self.assertEqual(decision.reason_code, "no_process_time_candidate")

    def test_topology_metadata_is_not_assigned_to_active_trace(self) -> None:
        metadata = event(
            "timer-init",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=10,
            tid=11,
        )
        metadata = NormalizedEvent(
            **{**metadata.to_dict(), "event_type": "ros2:rcl_timer_init"}
        )

        decision = associate_system_event(metadata, self.windows)

        self.assertEqual(decision.status, "unmatched")
        self.assertEqual(decision.reason_code, "topology_metadata")

    def test_clock_mismatch_is_rejected_before_candidate_search(self) -> None:
        system = event(
            "wrong-clock",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=10,
            tid=11,
            clock_id="realtime",
        )

        decision = associate_system_event(system, self.windows)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason_code, "clock_domain_mismatch")

    def test_timestamp_only_baseline_forces_a_deterministic_choice(self) -> None:
        system = event(
            "wrong-process",
            source="ros2_tracing",
            timestamp_ns=150,
            pid=999,
            tid=999,
        )

        decision = associate_by_timestamp(system, self.windows)

        self.assertEqual(decision.status, "accepted")
        self.assertEqual(decision.reason_code, "timestamp_only_baseline")
        self.assertIn(decision.trace_id, {"trace-a", "trace-b"})

    def test_report_counts_all_decision_states_and_reasons(self) -> None:
        decisions = [
            associate_system_event(
                event("accepted", source="ros2_tracing", timestamp_ns=150, pid=10, tid=11),
                self.windows,
            ),
            associate_system_event(
                event("ambiguous", source="ros2_tracing", timestamp_ns=150, pid=10, tid=99),
                self.windows,
            ),
            associate_system_event(
                event("unmatched", source="ros2_tracing", timestamp_ns=150, pid=99, tid=99),
                self.windows,
            ),
        ]

        report = build_association_report(decisions)

        self.assertEqual(report["decision_count"], 3)
        self.assertEqual(
            report["counts_by_status"],
            {"accepted": 1, "ambiguous": 1, "unmatched": 1},
        )
        self.assertEqual(report["accepted_rate"], 1 / 3)
        self.assertEqual(
            report["counts_by_event_type"], {"callback_start": 3}
        )
        self.assertEqual(
            report["counts_by_status_and_event_type"],
            {
                "accepted": {"callback_start": 1},
                "ambiguous": {"callback_start": 1},
                "unmatched": {"callback_start": 1},
            },
        )


if __name__ == "__main__":
    unittest.main()
