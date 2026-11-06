import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diagnosis.evidence_graph.confidence import ScoringProfile  # noqa: E402
from diagnosis.schema import NormalizedEvent  # noqa: E402
from optimizer.integration.diagnosis_gate import plan_from_diagnosis  # noqa: E402
from scripts.run_diagnosis import run_diagnosis  # noqa: E402


W1_STAGES = (
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
    "can_ack_wait_start",
    "can_ack_received",
)


def runtime_event(event_id: str, stage: str, timestamp_ns: int) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        source="runtime_event",
        event_type=stage,
        timestamp_ns=timestamp_ns,
        clock_id="monotonic",
        trace_id="trace-1",
        sequence_id=1,
        stage=stage,
        pid=100,
        tid=100,
        host_id="host-a",
        attributes={"duration_ns": 0},
        provenance={"source_file": "runtime.jsonl", "record_index": 1},
    )


def w1_runtime() -> list[NormalizedEvent]:
    """One complete W1 trace whose planner stage takes 300 ms."""
    # Realistic monotonic timeline: the planner stage spans 1 ms -> 300 ms and
    # every later stage follows it, so the stage order matches the topology.
    offsets = {
        "camera_publish": 0,
        "planner_receive": 1_000_000,
        "planner_process_start": 2_000_000,
        "planner_process_end": 300_000_000,
        "planner_publish": 300_100_000,
        "action_receive": 301_000_000,
        "action_execute_start": 302_000_000,
        "action_execute_end": 402_000_000,
        "can_receive": 403_000_000,
        "can_encode_start": 403_100_000,
        "can_encode_end": 403_200_000,
        "can_frame_sent": 404_000_000,
        "can_ack_wait_start": 405_000_000,
        "can_ack_received": 406_000_000,
    }
    return [
        runtime_event(f"event-{index}", stage, offsets[stage])
        for index, stage in enumerate(W1_STAGES)
    ]


def profile_record() -> dict:
    return {
        "schema_version": "diagnosis-scoring/v1",
        "profile_id": "entrypoint-test-v1",
        "calibration_manifest_sha256": "a" * 64,
        "dataset_role": "calibration",
        "frozen_before_test": True,
        "thresholds": {"planner_compute_ns": 100},
        "weights": {"planner_compute_ns": 1},
        "conflict_penalty": 0.5,
        "missing_penalty": 0.25,
        "minimum_score": 0.5,
        "minimum_margin": 0.2,
        "minimum_completeness": 1.0,
    }


class DiagnosisEntrypointTest(unittest.TestCase):
    def test_capture_produces_a_diagnosis_the_optimizer_gate_accepts(self) -> None:
        # planner_process_start is 300 ms long against a 100 ns threshold.
        runtime = w1_runtime()

        report, association = run_diagnosis(
            runtime,
            [],
            ScoringProfile.from_dict(profile_record()),
            workload_id="w1",
        )

        self.assertEqual(association["counts_by_status"], {})
        self.assertEqual(report["status"], "diagnosed")
        self.assertEqual(report["top_1"], "application_compute_delay")

        gate = plan_from_diagnosis(
            report, strategy="guided", budget=4, seed=7, minimum_confidence=0.5
        )
        self.assertEqual(gate["decision"], "allow")
        self.assertEqual(gate["cause_id"], "application_compute_delay")
        self.assertIsNotNone(gate["trial_plan"])

    def test_reports_which_trace_to_select_when_a_capture_has_several(self) -> None:
        runtime = w1_runtime()
        second = [
            NormalizedEvent(
                event_id=f"{stage}-2",
                source="runtime_event",
                event_type=stage,
                timestamp_ns=2_000 + index,
                clock_id="monotonic",
                trace_id="trace-2",
                sequence_id=2,
                stage=stage,
                pid=100,
                tid=100,
                host_id="host-a",
                attributes={"duration_ns": 0},
                provenance={"source_file": "runtime.jsonl", "record_index": 2},
            )
            for index, stage in enumerate(W1_STAGES)
        ]

        with self.assertRaisesRegex(ValueError, "more than one trace"):
            run_diagnosis(
                runtime + second,
                [],
                ScoringProfile.from_dict(profile_record()),
                workload_id="w1",
            )

    def test_cli_writes_a_report_from_captured_files(self) -> None:
        runtime = w1_runtime()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "runtime.jsonl"
            system_path = root / "system.jsonl"
            profile_path = root / "profile.json"
            output_path = root / "diagnosis.json"
            runtime_path.write_text(
                "".join(json.dumps(item.to_dict()) + "\n" for item in runtime),
                encoding="utf-8",
            )
            system_path.write_text("", encoding="utf-8")
            profile_path.write_text(json.dumps(profile_record()), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_diagnosis.py"),
                    "--runtime",
                    str(runtime_path),
                    "--system",
                    str(system_path),
                    "--profile",
                    str(profile_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema_version"], "diagnosis-report/v1")
        self.assertEqual(report["top_1"], "application_compute_delay")
        self.assertEqual(report["inputs"]["runtime"], str(runtime_path))
        self.assertEqual(
            report["inputs"]["association"]["schema_version"],
            "diagnosis-input-association/v1",
        )


if __name__ == "__main__":
    unittest.main()
