import unittest
import subprocess
import json
import signal
import tempfile
from pathlib import Path

from diagnosis.adapters.ebpf_adapter import TaskIdentity
from scripts.capture_ebpf_runtime import (
    build_bpftrace_program,
    capture_exit_is_successful,
    parse_event_line,
    collect_until_timeout,
    record_targets_manifest,
)


_SWITCH_LINE = "E\tS\t123\t101\tcamera\t1\t202\tplanner\t3\n"


class _FakeCollector:
    """Fake collector: exits inside the window, on `exits_on`, or only on kill()."""

    def __init__(
        self,
        *,
        exits_immediately: bool = False,
        exits_on: int | None = None,
        output: str = _SWITCH_LINE,
    ) -> None:
        self.exits_immediately = exits_immediately
        self.exits_on = exits_on  # None: survives every signal; kill() is required
        self.output = output
        self.signals: list[int] = []
        self.killed = False
        self.reaped = False

    def send_signal(self, number: int) -> None:
        self.signals.append(number)

    def kill(self) -> None:
        self.killed = True

    def poll(self) -> int | None:
        return -2 if self.reaped else None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        # SIGKILL cannot be ignored, so it always ends the fake.
        if (
            self.reaped
            or self.exits_immediately
            or self.killed
            or signal.SIGKILL in self.signals
            or (self.exits_on is not None and self.exits_on in self.signals)
        ):
            self.reaped = True
            return self.output, "stderr"
        raise subprocess.TimeoutExpired("bpftrace", timeout)


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

    def test_collects_normal_exit_without_signalling_the_collector(self) -> None:
        collector = _FakeCollector(exits_immediately=True)

        self.assertEqual(
            collect_until_timeout(collector, 5.0), (_SWITCH_LINE, "stderr")
        )
        self.assertEqual(collector.signals, [])
        self.assertFalse(collector.killed)

    def test_escalates_to_sigint_then_sigterm_then_sigkill(self) -> None:
        cases = (
            (signal.SIGINT, [signal.SIGINT]),
            (signal.SIGTERM, [signal.SIGINT, signal.SIGTERM]),
            (None, [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]),
        )
        for exits_on, expected in cases:
            with self.subTest(exits_on=exits_on):
                collector = _FakeCollector(exits_on=exits_on)

                stdout, _ = collect_until_timeout(collector, 5.0)

                self.assertEqual(collector.signals, expected)
                # Partial output survives every escalation path.
                self.assertEqual(stdout, _SWITCH_LINE)
                self.assertTrue(collector.reaped)

    def test_reaps_the_collector_when_collection_is_interrupted(self) -> None:
        collector = _FakeCollector(exits_on=None)

        with self.assertRaises(KeyboardInterrupt):
            try:
                # main() abandons collection by raising; the finally block reaps.
                raise KeyboardInterrupt()
            finally:
                if collector.poll() is None:
                    collector.kill()
                    collector.communicate()

        self.assertTrue(collector.killed)
        self.assertTrue(collector.reaped)

    def test_forced_termination_never_becomes_qualified_evidence(self) -> None:
        # SIGKILL reaps partial output, but the return code fails the capture gate.
        collector = _FakeCollector(exits_on=None)
        stdout, _ = collect_until_timeout(collector, 5.0)
        parsed = [
            parse_event_line(line, host_id="h", collector_version="0.14.0")
            for line in stdout.splitlines()
            if line.startswith("E\t")
        ]

        self.assertEqual(
            [record["event_source"] for record in parsed], ["sched_switch"]
        )
        self.assertFalse(
            capture_exit_is_successful(
                returncode=-signal.SIGKILL,
                event_count=len(parsed),
                malformed_count=0,
            )
        )


if __name__ == "__main__":
    unittest.main()
