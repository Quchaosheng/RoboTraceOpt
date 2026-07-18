import unittest
import subprocess
import json
import tempfile
from pathlib import Path

from diagnosis.adapters.ebpf_adapter import TaskIdentity
from scripts.capture_ebpf_runtime import (
    build_bpftrace_program,
    capture_exit_is_successful,
    parse_event_line,
    record_targets_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CaptureEbpfRuntimeTest(unittest.TestCase):
    def test_cli_reports_incomparable_identity_without_traceback(self) -> None:
        manifest = {
            "schema_version": "process-manifest/v2",
            "ebpf_identity_status": "not_comparable",
            "ebpf_identity_reason": "wsl_initial_pid_namespace_unavailable",
            "processes": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    "scripts/capture_ebpf_runtime.py",
                    "--process-manifest",
                    str(manifest_path),
                    "--duration",
                    "1",
                    "--output",
                    str(root / "events.jsonl"),
                    "--summary-output",
                    str(root / "summary.json"),
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("wsl_initial_pid_namespace_unavailable", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_sigint_timeout_is_success_only_with_valid_events(self) -> None:
        self.assertTrue(
            capture_exit_is_successful(returncode=-2, event_count=10, malformed_count=0)
        )
        self.assertFalse(
            capture_exit_is_successful(returncode=-2, event_count=0, malformed_count=0)
        )
        self.assertFalse(
            capture_exit_is_successful(
                returncode=255, event_count=10, malformed_count=0
            )
        )

    def test_direct_script_entrypoint_loads_repository_modules(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/capture_ebpf_runtime.py", "--help"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_program_filters_syscalls_by_process_without_large_sched_predicate(
        self,
    ) -> None:
        program = build_bpftrace_program([10, 20])

        for probe in (
            "tracepoint:sched:sched_switch",
            "tracepoint:sched:sched_wakeup",
            "tracepoint:raw_syscalls:sys_enter",
            "tracepoint:raw_syscalls:sys_exit",
        ):
            self.assertIn(probe, program)
        self.assertIn("pid == 10", program)
        self.assertIn("pid == 20", program)
        self.assertNotIn("args->prev_pid ==", program)
        self.assertNotIn("str(args->", program)

    def test_userspace_filter_keeps_only_manifest_tasks(self) -> None:
        identities = {
            9101: TaskIdentity(pid=10, tid=101, kernel_pid=9000, kernel_tid=9101),
            9202: TaskIdentity(pid=20, tid=202, kernel_pid=9200, kernel_tid=9202),
        }
        self.assertTrue(
            record_targets_manifest(
                {"event_source": "sched_switch", "prev_tid": 0, "next_tid": 9101},
                identities,
            )
        )
        self.assertFalse(
            record_targets_manifest(
                {"event_source": "sched_wakeup", "tid": 999}, identities
            )
        )
        self.assertTrue(
            record_targets_manifest(
                {"event_source": "syscall", "pid": 9200, "tid": 9202}, identities
            )
        )

    def test_parses_sched_switch_line(self) -> None:
        record = parse_event_line(
            "E\tS\t123\t101\tcamera\t1\t202\tplanner\t3",
            host_id="host-a",
            collector_version="0.14.0",
        )

        self.assertEqual(record["event_source"], "sched_switch")
        self.assertEqual(record["prev_tid"], 101)
        self.assertEqual(record["next_tid"], 202)
        self.assertEqual(record["cpu_id"], 3)

    def test_parses_wakeup_and_syscall_lines(self) -> None:
        wakeup = parse_event_line(
            "E\tW\t124\t102\tcamera\t2",
            host_id="host-a",
            collector_version="0.14.0",
        )
        syscall = parse_event_line(
            "E\tY\t125\t10\t101\tcamera\t202\t0\t8000",
            host_id="host-a",
            collector_version="0.14.0",
        )

        self.assertEqual(wakeup["event_source"], "sched_wakeup")
        self.assertEqual(syscall["event_source"], "syscall")
        self.assertEqual(syscall["syscall_name"], "sys_202")
        self.assertEqual(syscall["duration_ns"], 8_000)

    def test_rejects_malformed_collector_line(self) -> None:
        with self.assertRaises(ValueError):
            parse_event_line(
                "E\tS\tmissing",
                host_id="host-a",
                collector_version="0.14.0",
            )


if __name__ == "__main__":
    unittest.main()
