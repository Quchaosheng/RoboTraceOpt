from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.evidence_capture.artifact_manifest import (
    ARTIFACT_SCHEMA,
    ArtifactValidationError,
)
from scripts.export_tracetools_fixture import directory_sha256
from scripts import run_fault_condition
from scripts.run_fault_condition import (
    capture_ebpf_evidence,
    export_ros2_evidence,
    fault_capture_plan,
    finalize_fault_artifacts,
)


class FaultEvidenceCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_capture_plan_matches_fault_capabilities(self) -> None:
        self.assertEqual(
            fault_capture_plan("F1", {"runtime_event"}),
            {"process_manifest": False, "ebpf": False, "ros2_export": False},
        )
        self.assertEqual(
            fault_capture_plan("F2", {"runtime_event", "ros2_tracing"}),
            {"process_manifest": True, "ebpf": False, "ros2_export": True},
        )
        self.assertEqual(
            fault_capture_plan("F3", {"runtime_event", "ros2_tracing", "ebpf"}),
            {"process_manifest": True, "ebpf": True, "ros2_export": True},
        )
        self.assertEqual(
            fault_capture_plan("F4", {"runtime_event", "ebpf"}),
            {"process_manifest": True, "ebpf": True, "ros2_export": False},
        )

    def test_f4_runs_ebpf_with_live_process_manifest(self) -> None:
        process_manifest = self.root / "process_manifest.json"
        self._write_json(process_manifest, self._process_manifest())
        calls = []

        def execute(argv, **kwargs):
            calls.append((argv, kwargs))
            (self.root / "ebpf_events.jsonl").write_text("{}\n", encoding="utf-8")
            self._write_json(
                self.root / "ebpf_capture_summary.json",
                self._ebpf_summary({"syscall": 3}),
            )
            return subprocess.CompletedProcess(argv, 0)

        roles = capture_ebpf_evidence(
            fault_id="F4",
            output_dir=self.root,
            process_manifest=process_manifest,
            duration_seconds=8,
            elapsed_startup_seconds=1,
            execute=execute,
        )

        self.assertEqual(set(roles), {"ebpf_events", "ebpf_capture_summary"})
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0][0], list)
        self.assertIn("capture_ebpf_runtime.py", " ".join(calls[0][0]))
        self.assertNotIn("shell", calls[0][1])

    def test_f2_exports_ros2_trace_and_validates_manifest(self) -> None:
        trace = self.root / "ctf"
        trace.mkdir()
        (trace / "metadata").write_text("ctf", encoding="utf-8")
        calls = []

        def execute(argv, **kwargs):
            calls.append((argv, kwargs))
            (self.root / "ros2_events.jsonl").write_text("{}\n", encoding="utf-8")
            self._write_json(
                self.root / "ros2_events.manifest.json",
                {
                    "schema_version": "ros2-trace-export/v1",
                    "host_id": "host-a",
                    "source_trace_sha256": directory_sha256(trace),
                    "event_count": 2,
                    "event_counts": {
                        "ros2:callback_start": 1,
                        "ros2:callback_end": 1,
                    },
                },
            )
            return subprocess.CompletedProcess(argv, 0)

        roles = export_ros2_evidence(
            fault_id="F2",
            output_dir=self.root,
            host_id="host-a",
            execute=execute,
        )

        self.assertEqual(set(roles), {"ros2_events", "ros2_events_manifest"})
        self.assertEqual(len(calls), 1)
        self.assertIn("export_ros2_trace.py", " ".join(calls[0][0]))

    def test_artifact_manifest_is_written_only_after_summary_exists(self) -> None:
        paths = self._base_paths()
        with self.assertRaises(ArtifactValidationError):
            finalize_fault_artifacts(
                fault_id="F1",
                condition_variant="control",
                dataset_role="test",
                output_dir=self.root,
                paths=paths,
            )
        self.assertFalse((self.root / "artifact_manifest.json").exists())

        paths["fault_summary"] = self.root / "summary.json"
        self._write_json(paths["fault_summary"], {"status": "completed"})
        manifest_path = finalize_fault_artifacts(
            fault_id="F1",
            condition_variant="control",
            dataset_role="test",
            output_dir=self.root,
            paths=paths,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], ARTIFACT_SCHEMA)

    @patch.object(run_fault_condition.time, "sleep")
    @patch.object(run_fault_condition.subprocess, "run")
    @patch.object(run_fault_condition, "start_isolated_process")
    @patch.object(run_fault_condition, "capture_ebpf_evidence")
    def test_execute_f4_captures_process_identity_without_tracing(
        self, capture_ebpf, start_process, run, _sleep
    ) -> None:
        safe_root = self.root / "build"
        setup = safe_root / "install" / "setup.bash"
        setup.parent.mkdir(parents=True)
        setup.write_text("setup", encoding="utf-8")
        output = self.root / "condition"
        output.mkdir()
        events = []
        for index in (1, 2):
            for name, source_node, pid in (
                ("service_process_start", "service_server", 20),
                ("service_process_end", "service_server", 20),
                ("response_received", "service_client", 10),
            ):
                events.append(
                    {
                        "event_name": name,
                        "trace_id": f"trace-{index}",
                        "source_node": source_node,
                        "pid": pid,
                    }
                )
        (output / "runtime_events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
        )

        class FakeProcess:
            pid = 99

            @staticmethod
            def wait() -> int:
                return 124

        start_process.return_value = FakeProcess()

        def capture_manifest(argv, **_kwargs):
            path = Path(argv[argv.index("--output") + 1])
            self._write_json(path, self._process_manifest())
            return subprocess.CompletedProcess(argv, 0)

        run.side_effect = capture_manifest
        ebpf_events = output / "ebpf_events.jsonl"
        ebpf_summary = output / "ebpf_capture_summary.json"
        ebpf_events.write_text("{}\n", encoding="utf-8")
        self._write_json(ebpf_summary, self._ebpf_summary({"syscall": 1}))
        capture_ebpf.return_value = {
            "ebpf_events": ebpf_events,
            "ebpf_capture_summary": ebpf_summary,
        }

        summary, evidence = run_fault_condition.execute_condition(
            "F4",
            "w2",
            ["ros2", "launch", "service_runtime_demo"],
            output,
            safe_root,
            8,
            {"runtime_event", "ebpf"},
            self.root / "tracing_overlay",
            condition_variant="control",
        )

        self.assertEqual(summary["schema_version"], "fault-run-summary/v1")
        self.assertIn("process_manifest", evidence)
        self.assertIn("ebpf_events", evidence)
        capture_ebpf.assert_called_once()

    def _base_paths(self) -> dict[str, Path]:
        paths = {
            "runtime_events": self.root / "runtime_events.jsonl",
            "run_manifest": self.root / "run_manifest.json",
            "oracle_manifest": self.root / "oracle_manifest.json",
            "command_manifest": self.root / "command.json",
        }
        for role, path in paths.items():
            path.write_text('{"role":"' + role + '"}\n', encoding="utf-8")
        return paths

    @staticmethod
    def _process_manifest() -> dict:
        return {
            "schema_version": "process-manifest/v2",
            "host_id": "host-a",
            "ebpf_identity_status": "comparable",
            "processes": [{"node": "planner", "pid": 10}],
        }

    @staticmethod
    def _ebpf_summary(counts: dict[str, int]) -> dict:
        return {
            "schema_version": "ebpf-capture-summary/v1",
            "collector": "bpftrace",
            "collector_version": "0.14.0",
            "host_id": "host-a",
            "duration_s": 6.5,
            "target_tid_count": 1,
            "target_pid_count": 1,
            "event_count": sum(counts.values()),
            "counts_by_type": counts,
            "malformed_line_count": 0,
            "raw_stdout_line_count": sum(counts.values()),
            "raw_stdout_sample": [],
            "bpftrace_returncode": 0,
            "bpftrace_stderr": "",
        }

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
